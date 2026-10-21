# -*- coding: utf-8 -*-
"""摄像头采集层（GUI / API 服务器 / 手机端共用，不依赖 Qt）。

解决的问题（对应国赛现场的两个坑）：

1. **多客户端抢设备**：`api_server.py` 的 `/ws/stream` 原来每来一个 WebSocket 就
   `cv2.VideoCapture(...)` 一次 —— 一个手机页面 + 一个 PC 页面同时打开时，第二个拿不到设备。
   现在改为**按 key 共享单例**（`get_source()` 引用计数），所有订阅者读同一份最新帧。

2. **跑一会就卡死**：USB 相机断流后 `cap.read()` 可能一直返回 False，
   或换插口后设备句柄失效。这里用**独立采集线程 + 看门狗**：
   超过 `stale_sec` 没有新帧就判 DOWN，先只换新 handle（不阻塞等待 release），
   连续多次失败再尝试真正释放；`read()` 永远非阻塞，只会拿到"最新一帧"。

用法::

    from tool.camera_source import get_source

    src = get_source(('cam', 'A'), source=1, width=1280, height=720)  # 首次打开
    ok, frame = src.read()          # 非阻塞，返回最新帧副本
    src.state()                     # {'state': 'ok'|'down'|'dead', 'fps': ..., 'reopens': ...}
    src.release()                   # 引用计数 -1，最后一个用户离开才真正关设备

说明：
* 采集线程内部只保留最新一帧（`self._frame`），画面延迟不随时间累积。
* Windows 下优先 DirectShow（MSMF 长跑容易 `OnReadSample` 后彻底读不到帧），
  失败再回退默认后端；`backend: 'auto'|'dshow'|'msmf'` 可在 config 里指定。
"""
import hashlib
import os
import threading
import time

import cv2

# ---------------------------------------------------------------- 常量
STATE_OK = 'ok'
STATE_DOWN = 'down'      # 暂时读不到帧，正在自愈
STATE_DEAD = 'dead'      # 连首帧都拿不到 / 设备不存在

_DEFAULT_WIDTH = 1280
_DEFAULT_HEIGHT = 720
_DEFAULT_FOURCC = 'MJPG'
_DEFAULT_STALE = 2.0
_DEFAULT_PROBE = 5.0


def _log(msg):
    print(f'[CAM] {msg}', flush=True)


def _release_cap(cap):
    """安全释放（模块级，供解析流程复用）。"""
    try:
        if cap is not None:
            cap.release()
    except Exception:
        pass


def _release_after(cap, thread, timeout=3.0):
    """等占用该句柄的读取线程退出后再 release。

    ⚠️ 不能在别的线程还卡在 `cap.read()` 时 release 同一个句柄：
    OpenCV 的 VideoCapture 不是线程安全的，DSHOW/MSMF 下会直接段错误（整个进程闪退）。
    读取线程迟迟不退（驱动卡死）就宁可泄漏这个句柄，也不冒崩溃的险。
    """
    def _job():
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
            if thread.is_alive():
                _log(f'读取线程 {thread.name} 未在 {timeout:.0f}s 内退出，'
                     f'放弃释放旧句柄（避免跨线程 release 段错误）')
                return
        _release_cap(cap)
    threading.Thread(target=_job, name='CamRelease', daemon=True).start()


def _backend_candidates(prefer='auto'):
    """按优先级返回 (名称, cv2 flag) 列表。非 Windows 只返回默认后端。"""
    if os.name == 'nt':
        dshow = ('dshow', getattr(cv2, 'CAP_DSHOW', None))
        msmf = ('msmf', getattr(cv2, 'CAP_MSMF', None))
        if prefer == 'dshow':
            order = [dshow, msmf]
        elif prefer == 'msmf':
            order = [msmf, dshow]
        else:
            order = [dshow, msmf]
        return [(n, f) for n, f in order if f is not None] + [('default', None)]
    return [('default', None)]


def resolve_source(spec):
    """把配置里的摄像头写法解析成 (source, 错误, 设备名)。

    * `int` / 纯数字串        → 直接当索引用
    * 设备标识（非数字串）    → 走 DirectShow 枚举换成索引
                                （`'vid_0c45'` / `'0c45'` / `'USB Camera'` …）
    * 其它字符串              → 原样返回（RTSP/HTTP 流、视频文件、图片序列）

    error 只在"看着像设备标识、但当前找不到"时非空。调用方必须据此**报错中止**，
    而不是换一个相机打开 —— 现场就吃过这个亏：配置写死 index=1，
    后来系统把两个相机的索引顺序翻了过来（见 tool/ds_enum.py 顶部记录），
    程序静默打开了笔记本内置摄像头，画面一切正常，不主动核对根本发现不了。
    """
    if isinstance(spec, bool):
        return int(spec), '', ''
    if isinstance(spec, int):
        return spec, '', ''
    if spec is None:
        return 0, '', ''
    text = str(spec).strip()
    if not text:
        return 0, '', ''
    if text.isdigit():
        return int(text), '', ''

    low = text.lower()
    # 看着像 URL / 文件路径的，直接交给 OpenCV，不做设备枚举
    if ('://' in text or os.sep in text or '/' in text
            or low.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.mp4', '.avi', '.mjpg'))):
        return text, '', ''

    try:
        from tool.ds_enum import find_index
        index = find_index(text)
    except Exception as exc:
        return text, f'设备标识解析失败（{type(exc).__name__}: {exc}）', ''

    if index is None:
        try:
            from tool.ds_enum import describe_devices
            available = describe_devices()
        except Exception:
            available = '（枚举失败）'
        return None, f'找不到匹配 {text!r} 的摄像头。当前可用：{available}', ''
    return index, '', text


class CameraSource:
    """单个摄像头源：采集线程 + 看门狗 + 最新帧缓存。

    线程安全：`read()` / `peek()` 用锁保护；`_frame` 只被采集线程写。
    """

    def __init__(self, source=0, width=_DEFAULT_WIDTH, height=_DEFAULT_HEIGHT,
                 fourcc=_DEFAULT_FOURCC, backend='auto', stale_sec=_DEFAULT_STALE,
                 probe_timeout=_DEFAULT_PROBE, name=None, max_soft_retry=6,
                 duplicate_sec=None):
        # 设备标识（'vid_0c45' / 'USB Camera'）在这里解析成**索引**。
        # 数字索引会因为插拔/重启而重排（本机 10-08 与 10-11 就整个翻过来了），
        # 设备标识不会 —— 所以配置里推荐写标识，别写死索引。
        self.source_spec = source
        self._pick_error = ''
        self.device_name = ''
        resolved, self._pick_error, self.device_name = resolve_source(source)
        self.source = resolved
        self.width = int(width or 0)
        self.height = int(height or 0)
        self.fourcc = fourcc or None
        self.backend = str(backend or 'auto').lower()
        self.stale_sec = float(stale_sec or _DEFAULT_STALE)
        self.probe_timeout = float(probe_timeout or _DEFAULT_PROBE)
        self.max_soft_retry = int(max_soft_retry)
        # 静止画面也可能连续几秒不变，所以"同一帧"的容忍时间要远大于 stale_sec
        self.duplicate_sec = float(duplicate_sec or max(self.stale_sec * 3.0, 6.0))
        self.name = name or self.device_name or str(source)
        if self.device_name:
            _log(f'{self.name}: 按标识 {source!r} 选中 {self.device_name} '
                 f'(index={self.source})')
        elif self._pick_error:
            _log(f'{self.name}: {self._pick_error}')

        self._cap = None
        self._cap_lock = threading.Lock()
        self._frame = None
        self._frame_lock = threading.Lock()
        self._frame_ts = 0.0
        self._last_error = ''
        self._fps = 0.0
        self._last_read_ts = 0.0

        self._reader = None
        self._reader_gen = 0                 # 换代计数：旧线程靠它自行退出
        self._swap_lock = threading.Lock()   # 看门狗 / 手动 restart 不能同时换句柄
        self._stop = threading.Event()
        self._watchdog = None
        self._state = STATE_DEAD
        self._opened_once = False
        self._reopens = 0
        self._hard_reopens = 0
        self._size = None
        self._last_swap_ts = 0.0
        self._sig = None            # 最新帧的快速指纹（检测"驱动一直吐同一帧"）
        self._last_change_ts = 0.0  # 画面最后一次变化的时刻
        # 帧序号：每读到一帧 +1。界面用它判断"有没有新帧"，避免重复渲染同一帧
        self._seq = 0

    # ------------------------------------------------------------ 打开/关闭
    def _open_best(self):
        """多策略打开：优先直接打开，失败则进入 resolve_camera 解析。"""
        # 0) 明确指定的设备标识没匹配上 —— 直接失败返回。
        #    ⚠️ 这里**绝不能**退化成"扫一遍所有索引、哪个能开就用哪个"：
        #    那会静默换成另一个摄像头。本机真实事故：配置写死 index=1，
        #    系统把索引翻过来之后打开了笔记本内置摄像头，画面看着完全正常。
        if self._pick_error:
            self._last_error = self._pick_error
            self._resolve_report = {
                'tried': [self._pick_error],
                'opened': None,
                'capture': '指定的设备标识未匹配，已停止（不会改用其它相机）',
            }
            return None, None

        # 1) 快速路径：同一索引/源 + 自动后端候选
        cap, backend_name = _open_capture_ex(
            self.source, backend=self.backend,
            width=self.width, height=self.height,
            fourcc=self.fourcc, only_open=True)
        if cap is not None:
            ok, frame = self._grab_first(cap)
            if ok:
                self._frame_set(frame)
                self._last_error = ''
                be = backend_name or self.backend
                self._resolve_report = {'opened': f'index={self.source} backend={be}',
                                        'tried': []}
                _log(f"{self.name}: 打开成功 backend={be} "
                     f"size={frame.shape[1]}x{frame.shape[0]}"
                     + (f" 设备={self.device_name}" if self.device_name else ''))
                return cap, be
            self._last_error = f'{backend_name or self.backend}: 打开后读不到帧'
            _release_cap(cap)

        # 2) 文件 / URL / 图片序列打不开就是打不开：**绝不能**退化成扫索引 ——
        #    那会静默打开笔记本内置摄像头（测试机上实测：RTSP 地址写错 → 打开了 index 0）。
        if not isinstance(self.source, int):
            self._resolve_report = {
                'tried': [f'source={self.source!r} → 打不开/无帧'],
                'opened': None,
                'capture': '文件/流地址打不开，已停止（不会改用其它相机）',
            }
            self._last_error = (self._last_error or
                                f'无法打开 {self.source!r}（文件不存在 / 流地址不可达 / 格式不支持）')
            return None, None

        # 3) 多策略解析（换 FOURCC / 扫其它索引 / 按设备名）——只对数字索引做
        _log(f'{self.name}: 常规打开失败，进入多策略解析…')
        cap, report = resolve_camera(
            preferred_index=self.source if isinstance(self.source, int) else None,
            width=self.width, height=self.height, fourcc=self.fourcc,
            max_index=int(os.environ.get('CROPGuard_CAM_MAX_INDEX', '6') or 6),
            verbose=True)
        self._resolve_report = report
        if cap is not None:
            ok, frame = self._grab_first(cap)
            if ok:
                self._frame_set(frame)
                self._last_error = ''
                _log(f"{self.name}: 多策略打开成功 → {report.get('opened')}")
                return cap, self.backend
            _release_cap(cap)
            self._last_error = '多策略打开后读不到帧'
        else:
            self._last_error = ('所有策略都失败（索引/FOURCC/按设备名）；'
                                f'DirectShow 枚举数见 tried；详细报告在 state()["resolve"]')
        return None, None

    def _grab_first(self, cap, timeout=None):
        """等首帧（驱动出图有延迟，第一帧常是空的）。

        timeout 默认用 self.probe_timeout。注意这是**打开成功之后**的等待，
        与"打开设备"本身的开销是两回事（现场实测：索引1 冷启动要 3 秒才出图）。
        """
        deadline = time.time() + float(timeout if timeout is not None
                                       else self.probe_timeout)
        while time.time() < deadline and not self._stop.is_set():
            try:
                ok, frame = cap.read()
            except Exception as exc:
                self._last_error = f'read: {type(exc).__name__}: {exc}'
                ok, frame = False, None
            if ok and frame is not None:
                return True, frame
            time.sleep(0.05)
        return False, None

    def start(self):
        """打开设备并启动采集线程。

        返回**是否成功打开设备**（不是"是否已出图"）：
        打开成功就返回 True，首帧由后台采集线程继续等（用 `wait_first_frame` 显式等）。
        这样区分开，才不会出现"相机其实能用、只是冷启动慢 3 秒，却被判成打不开"。

        打开过程的每一步都会写进日志（`[CAM] ...`），现场能直接看到
        "选了哪个索引/后端/格式、哪一步失败"，不用猜。
        """
        self._stop.clear()
        _log(f'{self.name}: 开始打开（source={self.source!r} 期望 {self.width}x{self.height} '
             f'{self.fourcc or "默认格式"} backend={self.backend}）')
        cap, _ = self._open_best()
        if cap is None:
            self._state = STATE_DEAD
            _log(f"{self.name}: 打开失败 source={self.source} ({self._last_error})")
            return False
        with self._cap_lock:
            self._cap = cap
        # 设备已打开：先记 DOWN（还没帧），采集线程拿到第一帧后会自动转 OK。
        # 同时把"帧时间戳"打个新鲜的基准，给冷启动留出时间
        # （实测某些 USB 相机打开后要 3 秒才吐第一帧，别被看门狗当成"卡死"重开）
        self._state = STATE_DOWN
        self._opened_once = True
        self._frame_ts = time.time()
        self._last_change_ts = self._frame_ts
        self._spawn_reader()
        self._spawn_watchdog()
        _log(f'{self.name}: 设备已打开，后台采集线程开始等首帧'
             f'（最多 {self.probe_timeout:.1f}s）')
        return True

    def _spawn_reader(self):
        self._reader_gen += 1
        gen = self._reader_gen
        self._reader = threading.Thread(target=self._read_loop, args=(gen,),
                                        name=f'CamRead-{self.name}', daemon=True)
        self._reader.start()

    def _spawn_watchdog(self):
        if self._watchdog is not None and self._watchdog.is_alive():
            return
        self._watchdog = threading.Thread(target=self._watch_loop,
                                          name=f'CamWatch-{self.name}', daemon=True)
        self._watchdog.start()

    # ------------------------------------------------------------ 采集线程
    def _read_loop(self, gen):
        while not self._stop.is_set() and gen == self._reader_gen:
            with self._cap_lock:
                cap = self._cap
            if cap is None:
                if self._reader_gen != gen:
                    break
                time.sleep(0.1)
                continue
            try:
                ok, frame = cap.read()
            except Exception as exc:
                self._last_error = f'read: {type(exc).__name__}: {exc}'
                ok, frame = False, None
            if not ok or frame is None:
                time.sleep(0.02)
                continue
            now = time.time()
            if self._last_read_ts:
                dt = now - self._last_read_ts
                if dt > 0:
                    inst = 1.0 / dt
                    self._fps = inst if self._fps == 0 else 0.9 * self._fps + 0.1 * inst
            self._last_read_ts = now
            self._frame_set(frame)
            self._seq += 1
            if self._state != STATE_OK:
                self._state = STATE_OK

    def _frame_set(self, frame):
        now = time.time()
        try:
            sig = hashlib.blake2b(frame[::16, ::16].tobytes(), digest_size=8).digest()
        except Exception:
            sig = None
        with self._frame_lock:
            if sig is None or sig != self._sig:
                self._last_change_ts = now
            self._sig = sig
            self._frame = frame
            self._frame_ts = now
            if self._size != frame.shape[:2][::-1]:
                self._size = frame.shape[:2][::-1]

    # ------------------------------------------------------------ 看门狗
    def _watch_loop(self):
        while not self._stop.is_set():
            time.sleep(0.5)
            if not self._opened_once:
                continue
            age = time.time() - self._frame_ts
            # 两种情况都算卡死：
            #   a) 采集线程长时间拿不到新帧（掉线/断流）；
            #   b) 驱动一直吐同一帧，且这种情况已经持续超过一个完整静默窗口
            #      （真实现场画面一直在变，只有驱动死了才会这样）。
            flat_age = time.time() - (self._last_change_ts or self._frame_ts)
            stuck = (age > self.stale_sec) or \
                    (flat_age > self.duplicate_sec and age > self.duplicate_sec)
            if not stuck:
                if self._state == STATE_DOWN and age < 0.5:
                    self._state = STATE_OK
                continue

            # ---- 超时：判 DOWN，开始自愈 ----
            now = time.time()
            if self._state != STATE_DOWN:
                self._state = STATE_DOWN
                self._reopens += 1
                _log(f"{self.name}: 卡死（无新帧 {age:.1f}s / 画面未变 {flat_age:.1f}s）"
                     f"→ 换新 handle 自愈（第 {self._reopens} 次）")
            # 1 秒内已经换过一次就再等等，避免驱动/电源不好的相机被反复猛开
            if now - self._last_swap_ts < 1.0:
                continue
            self._last_swap_ts = now
            # 先只换 handle：绝不在看门狗线程里 release（release 可能跟着一起卡死）
            self._swap_capture()
            # 连续多次救不回来，才在一个次级线程里尝试真正释放旧句柄
            if self._reopens % self.max_soft_retry == 0:
                self._hard_reopen()

    def _swap_capture(self):
        with self._swap_lock:
            if self._stop.is_set():
                return
            cap, _ = self._open_best()
            self._last_swap_ts = time.time()
            if cap is None:
                self._state = STATE_DOWN
                return
            with self._cap_lock:
                old, self._cap = self._cap, cap
            old_reader = self._reader
            self._state = STATE_OK
            self._spawn_reader()      # 换了 cap，旧读取线程靠 generation 自行退出
            # 旧句柄等旧读取线程退出后再在后台释放：句柄卡死也不会拖住任何循环
            if old is not None:
                _release_after(old, old_reader)

    def _hard_reopen(self):
        """连续软重开都救不回来：把当前句柄摘下来，等读取线程退出后真正释放。

        旧实现直接 release 正在被读取线程使用的句柄（还留在 self._cap 上继续被读），
        是跨线程 release 段错误的高危点。现在先摘句柄 + 让读取线程换代退出，再释放；
        下一轮看门狗会重新打开。
        """
        with self._swap_lock:
            with self._cap_lock:
                cap, self._cap = self._cap, None
            old_reader = self._reader
            self._reader_gen += 1          # 让读取线程自行退出
            self._reader = None
            self._hard_reopens += 1
        if cap is not None:
            _release_after(cap, old_reader)

    # ------------------------------------------------------------ 对外读取
    def read(self, copy=True):
        """返回 (ok, frame)。copy=False 时直接给出内部帧引用（调用方不得改写）。"""
        if self._frame is None:
            return False, None
        with self._frame_lock:
            frame = self._frame
            if frame is None:
                return False, None
            return True, (frame.copy() if copy else frame)

    def peek(self):
        """零拷贝取最新帧引用；调用方只读。"""
        return self._frame

    def seq(self):
        """最新帧的序号（每读到一帧 +1）。界面靠它判断"有没有新帧"。"""
        return self._seq

    def wait_first_frame(self, timeout=None):
        """等首帧（用于 start() 之后需要立刻出图的场景）。"""
        deadline = time.time() + (timeout if timeout is not None else self.probe_timeout)
        while time.time() < deadline:
            if self._frame is not None:
                return True
            time.sleep(0.05)
        return self._frame is not None

    # ------------------------------------------------------------ 状态 / 重开
    def state(self):
        now = time.time()
        age = (now - self._frame_ts) if self._frame_ts else None
        change_age = (now - self._last_change_ts) if self._last_change_ts else None
        return {
            'name': self.name,
            'source': self.source,
            'source_spec': self.source_spec,
            'device': self.device_name,
            'index': self.source if isinstance(self.source, int) else None,
            'state': self._state,
            'ok': self._state == STATE_OK,
            'opened': self._opened_once,
            'opened_once': self._opened_once,
            'reopens': self._reopens,
            'hard_reopens': self._hard_reopens,
            'fps': round(self._fps, 1),
            'seq': self._seq,
            'size': f'{self._size[0]}x{self._size[1]}' if self._size else None,
            'frame_age': round(age, 2) if age is not None else None,
            'change_age': round(change_age, 2) if change_age is not None else None,
            'last_error': self._last_error,
            'resolve': getattr(self, '_resolve_report', None),
        }

    def restart(self):
        """强制重启（现场抢救用）：换 handle + 重开采集线程。"""
        _log(f'{self.name}: 手动 restart')
        if self._opened_once:
            self._reopens += 1
        self._swap_capture()
        return self._state == STATE_OK

    # ------------------------------------------------------------ 关闭
    def close(self):
        self._stop.set()
        self._reader_gen += 1
        reader = self._reader
        for th in (self._reader, self._watchdog):
            if th is not None and th.is_alive():
                th.join(timeout=1.0)
        self._reader = None
        self._watchdog = None
        with self._swap_lock:
            with self._cap_lock:
                cap, self._cap = self._cap, None
        if cap is not None:
            if reader is not None and reader.is_alive():
                _release_after(cap, reader)      # 读取线程还卡在 read()：后台等它退出再放
            else:
                _release_cap(cap)
        with self._frame_lock:
            self._frame = None
        self._state = STATE_DEAD


# ================================================================ 单例池
_pool = {}
_pool_lock = threading.Lock()
# 每个 key 一把"打开锁"：打开设备可能要好几秒，绝不能拿着全局 _pool_lock 去开 ——
# 那样 A 区相机冷启动时，B 区、/api/camera/health 全都会被卡住。
_open_locks = {}


# ---------------------------------------------------------------- 多策略解析
def resolve_camera(preferred_index=None, width=_DEFAULT_WIDTH, height=_DEFAULT_HEIGHT,
                   fourcc=_DEFAULT_FOURCC, max_index=6, extra_indices=(), verbose=True):
    """**多策略**找一个真能出图的相机。返回 (cap, report)。

    为什么要多策略（现场踩过的坑）：
    * 索引会变（换 USB 口、插拔顺序、系统更新后重排）；
    * 有的相机只对 MJPG 出图，默认格式（YUY2/NV12）直接打不开；
    * MSMF 与 DSHOW 枚举到的设备集合可能不一样；
    * 有的设备只有**按名字**（DirectShow 友好名）才能打开。

    尝试顺序：
      1) 0..max_index-1 逐个索引（首选索引优先），每个索引尝试 MJPG / YUY2 / 默认格式
      2) DirectShow 按设备名打开（`tool/ds_enum.py`）
    每一步都会记进 report，失败时能明确回答"到底试过什么、为什么不行"。

    report: {'tried': [...], 'opened': 描述 或 None, 'capture': 简短结论}
    """
    report = {'tried': [], 'opened': None,
              'fourcc_used': None, 'index_used': None, 'name_used': None}

    # index 解析阶段只要求"能打开"；按名阶段才要求"真出帧"。
    # 理由：现场实测相机打开后要 3 秒才吐第一帧，若每步都等帧，
    # 解析会慢到十几秒，还会因为"等不到帧"把能用的相机判死。
    order_index = []
    if preferred_index is not None:
        order_index.append(int(preferred_index))
    order_index.extend(i for i in extra_indices if i is not None)
    order_index.extend(i for i in range(int(max_index)) if i not in order_index)

    fmt_order = []
    if fourcc:
        fmt_order.append(fourcc)
    for f in ('YUY2', None):
        if f not in fmt_order:
            fmt_order.append(f)

    # ---- 1) 按索引（只要求能打开，不等帧） ----
    be = 'dshow' if os.name == 'nt' else None
    for idx in order_index:
        for fmt in fmt_order:
            cap = _try_open_index(idx, be, fmt, width, height, report, verbose,
                                  need_frame=False)
            if cap is not None:
                return cap, report

    # ---- 2) DirectShow 按设备名 ----
    cap = _try_by_name(fmt_order, width, height, report, verbose)
    if cap is not None:
        return cap, report

    return None, report


def _configure(cap, width, height, fourcc):
    """给已经打开的 cap 设 FOURCC / 分辨率 / 缓冲。"""
    try:
        if fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        if width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return True


def _grab_any(cap, timeout=3.0):
    """在给定时间内尝试读一帧；读到返回 True。"""
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        try:
            ok, frame = cap.read()
        except Exception:
            ok, frame = False, None
        if ok and frame is not None:
            return True
        time.sleep(0.05)
    return False


def _open_capture_ex(source, backend='auto', width=0, height=0, fourcc=None,
                     only_open=False, grab_timeout=3.0):
    """按指定后端/FOURCC 打开一个设备；成功返回 (cap, backend_name)。

    only_open=True 时只要求"能打开"，不等帧 —— 用于快速多策略解析
    （很多相机打开成功但要 2~3 秒才吐第一帧，等帧会把解析拖得很慢）。
    """
    if source is None:
        return None, None
    for name, flag in _backend_candidates(backend):
        try:
            cap = (cv2.VideoCapture(source, flag) if flag is not None
                   else cv2.VideoCapture(source))
        except Exception as exc:
            _log(f'open {source} {name} 异常: {type(exc).__name__}: {exc}')
            continue
        if cap is None or not cap.isOpened():
            if cap is not None:
                _release_cap(cap)
            continue
        _configure(cap, width, height, fourcc)
        if only_open:
            return cap, name
        if _grab_any(cap, grab_timeout):
            return cap, name
        _release_cap(cap)
    return None, None


def _try_open_index(idx, backend, fmt, width, height, report, verbose, need_frame=False):
    """按索引打开，成功返回 cap；失败更新 report 并返回 None。"""
    label = f'index={idx} backend={backend} fourcc={fmt or "默认"}'
    cap, _ = _open_capture_ex(idx, backend=backend, width=width, height=height,
                              fourcc=fmt, only_open=not need_frame)
    if cap is None:
        report['tried'].append(label + ' → 打不开/无帧')
        if verbose:
            _log(f'尝试 {label}: 失败')
        return None
    report['tried'].append(label + ' → ✅')
    report['opened'] = label
    report['fourcc_used'] = fmt
    report['index_used'] = idx
    if verbose:
        _log(f'尝试 {label}: 成功')
    return cap


def _try_by_name(fmt_order, width, height, report, verbose):
    """DirectShow 按设备名打开，成功返回 cap；失败返回 None。"""
    try:
        from tool.ds_enum import list_devices
        devices, errs = list_devices()
        if errs:
            report['tried'].extend(f'设备枚举提示: {e}' for e in errs)
        if verbose:
            _log(f'DirectShow 设备数={len(devices)}')
        for d in devices:
            name = d.get('name') or ''
            for fmt in fmt_order:
                for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, None):
                    for spec in (f'video={name}', name):
                        try:
                            cap = (cv2.VideoCapture(spec, backend) if backend is not None
                                   else cv2.VideoCapture(spec))
                        except Exception:
                            continue
                        if cap is None or not cap.isOpened():
                            if cap is not None:
                                cap.release()
                            continue
                        if _configure(cap, width, height, fmt) and _grab_any(cap, 4.0):
                            label = f'name="{name}" backend={backend} fourcc={fmt or "默认"}'
                            report['tried'].append(label + ' → ✅')
                            report['opened'] = label
                            report['name_used'] = name
                            report['fourcc_used'] = fmt
                            if verbose:
                                _log(f'尝试 {label}: 成功')
                            return cap
                        _release_cap(cap)
            report['tried'].append(f'name="{name}" → 打不开/无帧')
    except Exception as exc:
        report['tried'].append(f'按名打开失败: {type(exc).__name__}: {str(exc)[:100]}')
    return None


def get_source(key, source=0, retry_dead=True, **kwargs):
    """按 key 取共享摄像头源；不存在则创建并打开（引用计数 +1）。

    key 建议用 ``('cam', cam_id)`` 这种元组，保证 URL/索引变化时不会复用错对象。

    retry_dead: 池里那个源如果是 **dead（打开失败/已关闭）**，就重新尝试打开。
    为什么需要它：第一次打开可能因为"相机被别的程序占着"失败，
    若不重试，之后每次点「打开摄像头」都只会拿到那个死对象、永远不再打开设备
    （现场表现就是"日志说打开了、但一直没画面"）。
    """
    with _pool_lock:
        open_lock = _open_locks.setdefault(key, threading.Lock())
    with open_lock:                       # 同一 key 串行打开；不同 key 互不阻塞
        with _pool_lock:
            src = _pool.get(key)
            fresh = src is None
            if fresh:
                src = CameraSource(source, **kwargs)
                src._refcount = 0
                _pool[key] = src
            src._refcount += 1            # 先占住引用：打开期间别人 release 不会把它关掉
        if fresh:
            src.start()
        else:
            st = src.state()
            if retry_dead and (not st.get('opened_once') or st.get('state') == STATE_DEAD):
                _log(f'{key}: 池中对象处于 {st.get("state")}，重新尝试打开设备')
                src.start()
        return src


def release_source(key):
    """引用计数 -1；归零则真正关闭设备并从池中移除。"""
    with _pool_lock:
        src = _pool.get(key)
        if src is None:
            return None
        src._refcount -= 1
        if src._refcount > 0:
            return src
        _pool.pop(key, None)
    src.close()
    return None


def pool_state():
    with _pool_lock:
        return {str(k): v.state() for k, v in _pool.items()}


def close_all():
    with _pool_lock:
        items = list(_pool.items())
        _pool.clear()
    for _, src in items:
        src.close()
