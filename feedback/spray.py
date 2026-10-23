"""喷淋执行控制器：风险 → 片区/分组喷淋时长映射，下发指令到喷洒设备。

国赛形态C「物理反馈/外部设备联动」的喷淋执行链路，支持三种传输方式：

    serial : Server --USB串口--> 网关 ESP32 --ESP-NOW--> 节点（现状，含一根 USB 线）
    http   : Server --HTTP--> 目标设备（方案甲：节点直连 WiFi；方案丙：无线网关转发）
    mqtt   : Server --MQTT--> 目标设备（方案乙/丙，需 broker）

transport='http' 时，每个目标还能各自指定**接口协议**（targets 项的 protocol 字段）：

    'json' : 项目固件（ESP32/src/http_node）
             POST /spray {"group":"g1","duration":2} + POST /stop，按状态码判成败
    'mist' : 手写 Arduino sketch（sketch_oct12a.ino：继电器 + 模拟雾化板按键）
             GET /start?time=N（定时）/ GET /startDirect（持续，**不会自停**）/ GET /stop
             ⚠️ 该固件没有分组过滤（片区隔离靠 IP 寻址），而且**永远回 200**
                —— 连"雾化正在运行中，请先关闭！"也是 200，所以必须读响应体判成败。
             ⚠️ 持续模式固件不会自停，本模块用 direct_max_sec 兜底强制关（见 _direct_timeout）。

「田间无线」推荐 **方案丙**：transport=http，http_targets 只配一项 ``group='gateway'``，
全部指令发给无线网关，网关再经 ESP-NOW 广播/单播给节点——**节点固件（ESP32/src/espnow_node）零改动**。

与 feedback.Feedback 同一风格：异步执行、失败静默、不阻塞推理主流程。
链路不可用（无串口/无目标地址/broker 未连）时静默降级，仅推理不做喷淋。
"""
import json
import re
import threading
import time

try:
    import serial
except ImportError:
    serial = None

try:
    import requests
except ImportError:
    requests = None


def _lan_session():
    """节点都在局域网里：发指令**绝不能走系统代理**。

    requests 默认读 Windows 注册表里的系统代理（trust_env）。现场那台机器的代理
    可能早已失效（曾记录过 127.0.0.1:65532），走代理时 POST 到节点会直接失败，
    而 curl 联调没有这个问题 —— 所以这里显式建一个 trust_env=False 的会话。
    """
    if requests is None:
        return None
    sess = requests.Session()
    sess.trust_env = False
    return sess


class SprayController:
    """喷淋控制器：按风险等级/手动触发下发指令，支持 serial / http / mqtt 三种传输。"""

    #: http 目标的两种接口协议
    PROTOCOLS = ('json', 'mist')

    def __init__(self, serial_port=None, baud=115200, enabled=True,
                 risk_map=None, min_interval=3.0,
                 transport='serial', http_targets=None, http_timeout=1.0,
                 mqtt=None, max_duration=30, default_protocol='json',
                 direct_max_sec=300, status_timeout=1.5, nodes=None):
        self.enabled = bool(enabled)
        self.serial_port = serial_port
        self.baud = int(baud or 115200)
        self.risk_map = risk_map or {}
        self.min_interval = float(min_interval)
        self.max_duration = int(max_duration or 30)
        # 持续模式（只对 mist 协议的 /startDirect 有效）服务器兜底自动停止秒数；<=0 关闭兜底
        try:
            self.direct_max_sec = int(direct_max_sec)
        except (TypeError, ValueError):
            self.direct_max_sec = 300
        self.status_timeout = float(status_timeout or 1.5)

        # ---------- 传输方式 ----------
        self.transport = str(transport or 'serial').lower()
        if self.transport not in ('serial', 'http', 'mqtt'):
            self.transport = 'serial'

        self.default_protocol = str(default_protocol or 'json').strip().lower()
        if self.default_protocol not in self.PROTOCOLS:
            self.default_protocol = 'json'

        # http 目标表：{group: url}；group='gateway' 表示方案丙的无线网关（承接全部指令）
        # 协议单独一张表 {group: 'json'|'mist'}，不动 http_targets 的取值口径（外部只读 .keys()）
        self.http_targets = {}
        self.target_protocols = {}
        for item in (http_targets or []):
            try:
                g = str(item.get('group', '') or '').strip()
                u = str(item.get('url', '') or '').strip()
                p = str(item.get('protocol', '') or '').strip().lower()
            except AttributeError:
                continue
            if g and u:
                self.http_targets[g] = u
                self.target_protocols[g] = p if p in self.PROTOCOLS else self.default_protocol
        self.http_timeout = float(http_timeout or 1.0)

        # mqtt 配置
        mqtt = mqtt or {}
        self.mqtt_host = str(mqtt.get('host', '') or '')
        self.mqtt_port = int(mqtt.get('port', 1883) or 1883)
        self.mqtt_topic = str(mqtt.get('topic', 'cropguard/spray') or 'cropguard/spray')
        self.mqtt_qos = int(mqtt.get('qos', 0) or 0)

        self._serial = None
        self._mqtt = None
        self._lock = threading.Lock()
        # 自动喷淋节流时间戳，按分组独立计时（多片区不会互相压制）
        self._last_auto_spray = {}
        # 持续模式的兜底计时器：{group: threading.Timer} / {group: 起始时间}
        self._direct_timers = {}
        self._direct_started = {}
        # 局域网会话（trust_env=False，见 _lan_session）
        self._http = _lan_session()
        # 节点探活缓存（/api/spray/status 3 秒内复用，避免页面轮询把节点打满）
        self._probe_lock = threading.Lock()
        self._probe_cache = {'ts': 0.0, 'nodes': []}
        # 节点登记表里的分组（serial/mqtt 形态下唯一能知道"有哪些片区"的地方）
        self.node_groups = set()
        self.node_names = {}
        for n in (nodes or []):
            try:
                g = str(n.get('group', '') or '').strip()
                name = str(n.get('name', '') or '').strip()
            except AttributeError:
                continue
            if g:
                self.node_groups.add(g)
                if name:
                    self.node_names.setdefault(g, name)

        if self.enabled:
            self._init_transport()

    # ==================== 初始化 ====================

    def _init_transport(self):
        """按传输方式初始化；失败静默（链路不可用时降级为纯推理）。"""
        if self.transport == 'serial':
            self._init_serial()
        elif self.transport == 'mqtt':
            self._init_mqtt()
        # http 无需预先连接，调用时直接 POST

    def _init_serial(self):
        """打开网关串口，失败静默（无网关时降级为纯推理）。"""
        if serial is None or not self.serial_port:
            return
        try:
            self._serial = serial.Serial(self.serial_port, self.baud, timeout=0.1)
        except Exception:
            self._serial = None

    def _init_mqtt(self):
        """初始化 MQTT 客户端（需 paho-mqtt）；失败静默。"""
        if not self.mqtt_host:
            return
        try:
            import paho.mqtt.client as mqtt_client
        except ImportError:
            return
        try:
            client = mqtt_client.Client()
            client.connect(self.mqtt_host, self.mqtt_port, keepalive=30)
            client.loop_start()
            self._mqtt = client
        except Exception:
            self._mqtt = None

    @property
    def available(self):
        """链路是否可用（按传输方式判定）。"""
        if not self.enabled:
            return False
        if self.transport == 'serial':
            return bool(self._serial and self._serial.is_open)
        if self.transport == 'http':
            return bool(self.http_targets) and requests is not None
        if self.transport == 'mqtt':
            return bool(self._mqtt)
        return False

    @property
    def allowed_groups(self):
        """可下发的分组白名单（聊天/语音指令解析用，跨传输形态）。

        http 直连：http_targets 里的分组；serial/mqtt：只认 nodes 登记表里的分组。
        'gateway' 是转发通道不算片区；'all' 永远合法。
        """
        groups = set(self.http_targets.keys()) | set(self.node_groups)
        groups.discard('gateway')
        groups.add('all')
        return groups

    # ==================== 目标寻址 ====================

    def _targets_for(self, group):
        """按分组取出 http 目标列表 [(group, url)]。

        方案丙：只配了 'gateway' 时，所有指令都发网关，由网关 ESP-NOW 转发。
        方案甲：按 group 精确寻址，实现片区间故障隔离。
        """
        group = group or 'all'
        if group in self.http_targets:
            return [(group, self.http_targets[group])]
        if 'gateway' in self.http_targets:
            return [('gateway', self.http_targets['gateway'])]
        if group == 'all':
            return [(g, u) for g, u in self.http_targets.items()]
        return []

    def protocol_of(self, group):
        """该分组的接口协议（group 没配时按网关、再按默认值兜底）。"""
        group = group or 'all'
        if group in self.target_protocols:
            return self.target_protocols[group]
        if 'gateway' in self.target_protocols:
            return self.target_protocols['gateway']
        return self.default_protocol

    def mist_targets(self):
        """所有 mist 协议目标（手机页据此显示节点地址与状态）。"""
        return [{'group': g, 'url': u, 'protocol': 'mist'}
                for g, u in self.http_targets.items()
                if self.target_protocols.get(g) == 'mist']

    # ==================== 现场改节点地址（不改 YAML、不重启） ====================
    def http_target_rows(self):
        """当前 http 目标表（指挥台「节点地址」面板据此渲染，顺序 = 配置顺序）。"""
        return [{'group': g, 'url': u,
                 'protocol': self.target_protocols.get(g, self.default_protocol)}
                for g, u in self.http_targets.items()]

    def set_http_targets(self, targets):
        """运行时替换 http 节点地址表，返回 ``(applied, errors)``。

        现场节点是 DHCP 拿地址、只印在串口上；改 ``configs.yaml`` 要重启服务，
        比赛现场很危险 —— 所以指挥台直接调这里热更新，持久化由调用方负责
        （``app.spray_targets.save``）。

        校验（宁可拒绝，也别把人送到错误地址上）：
        * group 不能空、同组重复以最后一项为准；
        * url 必须是 http:// 或 https:// 开头（mist 固件没有 TLS，也别写裸 IP）；
        * protocol 只认 json / mist，认不出来按 default_protocol（不静默当 mist）。
        全部不合格时**不改动**现有地址表，把原因原样带回去。
        """
        applied, errors = [], []
        for item in (targets or []):
            if not isinstance(item, dict):
                errors.append(f'忽略一项（不是对象）：{item!r}')
                continue
            group = str(item.get('group', '') or '').strip()
            url = str(item.get('url', '') or '').strip()
            proto = str(item.get('protocol', '') or '').strip().lower()
            if not group:
                errors.append('有一项没写 group，已忽略')
                continue
            if not url:
                errors.append(f'{group}：地址为空，已忽略')
                continue
            if not url.lower().startswith(('http://', 'https://')):
                errors.append(f'{group}：地址要以 http:// 开头（现在是 {url}）')
                continue
            applied.append({'group': group, 'url': url,
                            'protocol': proto if proto in self.PROTOCOLS
                            else self.default_protocol})
        if not applied:
            return [], (errors or ['没有可用的节点地址'])
        # 同组重复：后面的覆盖前面的，但顺序按第一次出现（面板不乱跳）
        merged = {}
        for row in applied:
            merged[row['group']] = row
        applied = list(merged.values())
        self.http_targets = {row['group']: row['url'] for row in applied}
        self.target_protocols = {row['group']: row['protocol'] for row in applied}
        with self._probe_lock:                       # 清了缓存，下一次探活立刻重连
            self._probe_cache = {'ts': 0.0, 'nodes': []}
        return applied, errors

    def _stop_url(self, url):
        """把节点 /spray 地址换成 /stop（固件 http_node 提供 /stop）。"""
        u = str(url or '')
        if u.endswith('/spray'):
            return u[:-len('/spray')] + '/stop'
        return u.rstrip('/') + '/stop'

    @staticmethod
    def _base_url(url):
        """取出节点根地址：配置里写 http://ip、http://ip/spray、http://ip/ 都能用。"""
        u = str(url or '').strip().rstrip('/')
        for suffix in ('/spray', '/stop', '/start', '/startDirect', '/status', '/m'):
            if u.endswith(suffix):
                u = u[:-len(suffix)].rstrip('/')
                break
        return u

    # ==================== 下发 ====================

    @staticmethod
    def _decode_utf8(raw):
        """按 UTF-8 解码（解不开就用 replace，绝不让状态解析抛异常）。"""
        data = raw or b''
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return data.decode('utf-8', 'replace')

    def _http_get(self, url, timeout=None):
        """GET 一个地址，返回 (status_code, text)；连不上时返回 (None, 原因)。

        统一按 UTF-8 解码：sketch 的 ``server.send(200, "text/html", page)`` 没带
        charset，交给 requests 猜编码会把中文状态文本猜成乱码（实测过）。
        """
        if requests is None:
            return None, 'requests 未安装'
        try:
            resp = (self._http or requests).get(url, timeout=float(timeout or self.http_timeout))
        except Exception as exc:
            return None, f'{type(exc).__name__}: {exc}'
        return resp.status_code, self._decode_utf8(resp.content)

    def _mist_url_for(self, base, command):
        """把一条通用指令翻译成 sketch 的 GET 地址。"""
        action = str((command or {}).get('action') or '').strip().lower()
        if action == 'direct':
            return base + '/startDirect'
        duration = (command or {}).get('duration')
        try:
            seconds = int(duration or 0)
        except (TypeError, ValueError):
            seconds = 0
        if action == 'stop' or seconds <= 0:
            return base + '/stop'
        return f'{base}/start?time={seconds}'

    def _write_mist(self, url, command):
        """按 sketch 的 GET 协议下发，返回 (ok, 错误原因)。

        这个固件**永远回 200**（连"雾化正在运行中，请先关闭！"也是 200），
        所以必须读响应体判断有没有真的执行 —— 只看状态码会把"拒绝启动"当成功。
        """
        target = self._mist_url_for(self._base_url(url), command)
        # 固件的 /start、/startDirect 里是 digitalWrite → delay(1000) → 模拟按键脉冲 200ms，
        # 要 1.2 秒以上才回包；而 SPRAY.http_timeout 配的是 1.0 秒 —— 用 1.0 秒会在
        # "设备其实已经喷了"的情况下报失败（现场会以为没喷，反复点 → 固件回"正在运行中"）。
        # 读超时给足 3.5 秒；/stop 是立即返回，多等不会有害。
        code, text = self._http_get(target, timeout=max(self.http_timeout, 3.5))
        if code is None:
            return False, str(text)
        if not (200 <= code < 300):
            return False, f'HTTP {code}'
        if '正在运行中' in text or '请先关闭' in text:
            return False, '节点正在喷雾中（固件拒绝重复启动，需先停止）'
        return True, ''

    def _write_json(self, url, command):
        """按项目固件协议 POST /spray，返回 (ok, 错误原因)。"""
        try:
            resp = (self._http or requests).post(url, json=command, timeout=self.http_timeout)
        except Exception as exc:
            return False, f'{type(exc).__name__}: {exc}'
        if 200 <= resp.status_code < 300:
            return True, ''
        return False, f'HTTP {resp.status_code}'

    @staticmethod
    def _is_start(command):
        """这条指令是不是"开始喷"（用于"定时喷雾接管持续模式"的计时器清理）。"""
        if str((command or {}).get('action') or '').lower() == 'stop':
            return False
        duration = (command or {}).get('duration')
        try:
            return int(duration or 0) > 0
        except (TypeError, ValueError):
            return False

    def _write_detail(self, command: dict):
        """写一条指令到目标设备，返回 (ok, 错误原因汇总)。"""
        if not self.available:
            return False, '链路不可用'
        try:
            if self.transport == 'serial':
                line = json.dumps(command, ensure_ascii=False) + '\n'
                with self._lock:
                    self._serial.write(line.encode('utf-8'))
                return True, ''

            if self.transport == 'http':
                pairs = self._targets_for(command.get('group'))
                if not pairs:
                    return False, '无可用目标地址（检查 SPRAY.http_targets）'
                ok = False
                errs = []
                for group, url in pairs:
                    if self.target_protocols.get(group, self.default_protocol) == 'mist':
                        good, err = self._write_mist(url, command)
                    else:
                        good, err = self._write_json(url, command)
                    ok = ok or good
                    if good and self._is_start(command):
                        # 定时喷雾成功 = 持续模式已被接管，撤掉兜底计时器免得它到点把这次喷关掉
                        self._cancel_direct_timer(group)
                    if not good and err:
                        errs.append(f'{group}: {err}')
                return ok, '; '.join(errs)

            if self.transport == 'mqtt':
                payload = json.dumps(command, ensure_ascii=False)
                info = self._mqtt.publish(self.mqtt_topic, payload, qos=self.mqtt_qos)
                return info is not None, '' if info is not None else 'MQTT publish 无回执'
        except Exception as exc:
            return False, f'{type(exc).__name__}: {exc}'
        return False, '未支持的传输方式'

    def _write(self, command: dict) -> bool:
        """写一条指令（只关心成败，供自动/手动喷淋的异步路径使用）。"""
        return self._write_detail(command)[0]

    def _send_async(self, command: dict):
        """后台线程发指令，不阻塞推理主流程。"""
        threading.Thread(target=self._write, args=(command,), daemon=True).start()

    # ==================== 持续模式兜底（mist 的 /startDirect 不会自停） ====================

    def _arm_direct_timer(self, group):
        """给某分组武装"持续模式兜底停止"计时器（direct_max_sec<=0 时不武装）。"""
        self._cancel_direct_timer(group)
        if self.direct_max_sec <= 0:
            return
        self._direct_started[group] = time.time()
        timer = threading.Timer(self.direct_max_sec, self._direct_timeout, args=(group,))
        timer.daemon = True
        self._direct_timers[group] = timer
        timer.start()

    def _cancel_direct_timer(self, group):
        """撤掉兜底计时器；group='all' 撤掉全部（多片区各有一个）。"""
        group = group or 'all'
        keys = list(self._direct_timers.keys()) if group == 'all' else [group]
        for key in keys:
            timer = self._direct_timers.pop(key, None)
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    pass
            self._direct_started.pop(key, None)

    def _direct_timeout(self, group):
        """兜底触发：固件不会自己停，时间到由服务器强制关（手机掉线/人走开也安全）。"""
        self._direct_timers.pop(group, None)
        self._direct_started.pop(group, None)
        try:
            ok, err = self._stop_now(group)
            print(f'[INFO] 雾化持续模式兜底停止 group={group} ok={ok} {err or ""}'.rstrip(),
                  flush=True)
        except Exception as exc:
            print(f'[WARN] 雾化持续模式兜底停止失败 group={group}: {exc}', flush=True)

    def _direct_remaining(self, group):
        """兜底停止还剩多少秒；未在定时中返回 None。"""
        if self.direct_max_sec <= 0 or group not in self._direct_started:
            return None
        left = self.direct_max_sec - (time.time() - self._direct_started[group])
        return max(0, int(round(left)))

    # ==================== 对外接口：自动/手动喷淋 ====================

    def spray(self, risk_level, detected_names=None, group_override=None):
        """按风险等级自动喷淋。

        group_override: 指定片区分组（如 'g2'），用于"多路定点监测 · 按片区定向喷淋"；
                        None 时使用 risk_map 中该风险等级配置的 group。
        返回 True 表示已下发指令；低/无风险、链路不可用、节流命中时返回 False。
        """
        if not self.enabled or not self.available:
            return False

        mapping = self.risk_map.get(risk_level)
        if not mapping:
            return False

        group = group_override or mapping.get('group')
        duration = mapping.get('duration', 0)
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            return False
        if not group or duration <= 0:
            return False
        if duration > self.max_duration:
            duration = self.max_duration  # 与手动喷淋同一道上限，配置写错也不会长时间喷

        # 自动喷淋节流：按分组独立计时，避免多片区互相压制
        now = time.time()
        if now - self._last_auto_spray.get(group, 0.0) < self.min_interval:
            return False
        self._last_auto_spray[group] = now

        self._send_async({'group': group, 'duration': duration})
        return True

    def manual_spray(self, group='all', duration=2):
        """手动喷淋（Client 按钮），不受自动节流限制。

        group: 'all' / 'g1' / 'g2' ...（对应片区A/片区B）；duration: 秒。
        非数字或 <=0 一律拒绝（调用方传 0 的语义是"别喷"，绝不能默认执行）。
        mist 协议下等价于 ``GET /start?time=duration``。
        """
        if not self.enabled or not self.available:
            return False
        group = group or 'all'
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            return False
        if duration <= 0:
            return False
        if duration > self.max_duration:
            duration = self.max_duration  # 安全上限，避免误触长时间喷水
        self._send_async({'group': group, 'duration': duration})
        return True

    def stop(self, group='all'):
        """立即停止该分组的喷洒（异步下发，只保证"已发出"）。

        mist 协议走 GET /stop，json 协议走 POST /stop；
        串口/MQTT 没有独立 stop 指令：发 duration=0 让节点立即停止
        （固件把 duration<=0 解释为 relay.stop()；发 1 是"再喷 1 秒"，语义反了）。
        手机页要"真结果"时用 mist_stop()/stop_detail()（同步、带回读到的错误原因）。
        """
        if not self.enabled or not self.available:
            return False
        group = group or 'all'
        self._cancel_direct_timer(group)
        if self.transport == 'http':
            if not self._targets_for(group):
                return False
            threading.Thread(target=self._stop_now, args=(group,), daemon=True).start()
            return True
        self._send_async({'group': group, 'duration': 0})
        return True

    def _stop_now(self, group='all'):
        """同步停止（可等待结果），返回 (ok, 错误原因汇总)。"""
        group = group or 'all'
        pairs = self._targets_for(group)
        if not pairs:
            return False, '无可用目标地址（检查 SPRAY.http_targets）'
        ok = False
        errs = []
        for g, url in pairs:
            if self.target_protocols.get(g, self.default_protocol) == 'mist':
                good, err = self._write_mist(url, {'group': g, 'action': 'stop'})
            else:
                try:
                    resp = (self._http or requests).post(self._stop_url(url), json={'group': g},
                                                         timeout=self.http_timeout)
                    good = 200 <= resp.status_code < 300
                    err = '' if good else f'HTTP {resp.status_code}'
                except Exception as exc:
                    good, err = False, f'{type(exc).__name__}: {exc}'
            ok = ok or good
            if not good and err:
                errs.append(f'{g}: {err}')
        return ok, '; '.join(errs)

    def stop_detail(self, group='all'):
        """同步停止并返回 (是否送达, 失败原因)——网页/手机要"真结果"时用这个。"""
        if not self.enabled or not self.available:
            return False, '喷淋链路未配置'
        group = group or 'all'
        self._cancel_direct_timer(group)
        if self.transport == 'http':
            return self._stop_now(group)
        # 串口/MQTT 协议：duration<=0 就是"立即停止"（绝不能发 1，那是"再喷 1 秒"）
        return self._write_detail({'group': group, 'duration': 0})

    def manual_spray_detail(self, group='all', duration=2):
        """手动喷淋并**同步等节点应答**，返回 (ok, 失败原因)。

        以前手动喷淋丢给后台线程就返回 True（"假成功"）；现场看页面提示成功、
        节点其实没动。现在把节点应答作为成功的唯一依据，失败原因原样回给页面。
        """
        if not self.enabled or not self.available:
            return False, '喷淋链路未配置'
        group = group or 'all'
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            return False, '时长必须是整数秒'
        if duration <= 0:
            return False, '时长必须为正数'
        if duration > self.max_duration:
            duration = self.max_duration  # 安全上限，避免误触长时间喷水
        return self._write_detail({'group': group, 'duration': duration})

    # ==================== 节点探活（/api/spray/status 用） ====================

    def probe_nodes(self, timeout=0.8, max_age=3.0):
        """并发探测每个 http 节点是否在线，带短缓存。

        返回 [{group, name, url, protocol, online, latency_ms, spraying, mode, remain, error}]。
        非 http 传输返回空表（串口/MQTT 没有逐节点探活的通道）。

        ⚠️ 探活路径按固件区分（现场踩过）：
        * ``mist``（手写 sketch）：**没有 /status 这个路由**，只有 ``/``（状态页）/
          ``/start`` / ``/startDirect`` / ``/stop``。以前统一打 /status → 404 →
          明明在线、手机能控制它喷的节点被判成"离线"，演示台一直 ❌。
          所以 mist 走 ``/``：状态页就在根路径，顺便读"在喷/空闲/剩余秒"。
        * ``json``（项目固件 http_node）：有 ``/status``，回 JSON。
        """
        if self.transport != 'http' or self._http is None or not self.http_targets:
            return []
        with self._probe_lock:
            if time.time() - self._probe_cache['ts'] < max_age:
                return [dict(n) for n in self._probe_cache['nodes']]
        items = list(self.http_targets.items())
        out = [None] * len(items)

        def _one(i, group, url):
            base = self._base_url(url)
            proto = self.target_protocols.get(group, self.default_protocol)
            row = {'group': group, 'name': self.node_names.get(group, ''), 'url': url,
                   'protocol': proto, 'online': False, 'latency_ms': None}
            t0 = time.time()
            try:
                if proto == 'mist':
                    resp = (self._http or requests).get(base + '/', timeout=timeout)
                    row['latency_ms'] = int((time.time() - t0) * 1000)
                    row['online'] = 200 <= resp.status_code < 300
                    if row['online']:
                        # ⚠️ 固件是 server.send(200, "text/html", page) —— **不带 charset**。
                        # Content-Type 没 charset 时 requests 的 resp.text 按 ISO-8859-1 解，
                        # 中文全变乱码，"空闲/正在雾化"解析不出来 → 会把空闲节点显示成
                        # "正在喷雾"。手写 sketch 输出的是 UTF-8，必须显式解码。
                        st = self._parse_mist_status(self._decode_utf8(resp.content))
                        row['spraying'] = bool(st.get('running'))
                        row['mode'] = st.get('mode')
                        row['remain'] = st.get('remain')
                    else:
                        row['error'] = f'返回 {resp.status_code}'
                else:
                    resp = (self._http or requests).get(base + '/status', timeout=timeout)
                    row['latency_ms'] = int((time.time() - t0) * 1000)
                    row['online'] = 200 <= resp.status_code < 300
                    try:
                        data = resp.json()
                    except ValueError:
                        data = {}
                    if isinstance(data, dict):
                        for k in ('ip', 'rssi', 'spraying', 'count'):
                            if k in data:
                                row[k] = data[k]
                        if data.get('name') and not row['name']:
                            row['name'] = str(data['name'])
                    if not row['online']:
                        row['error'] = f'返回 {resp.status_code}'
            except Exception as exc:
                row['error'] = f'{type(exc).__name__}: {exc}'
            out[i] = row

        threads = [threading.Thread(target=_one, args=(i, g, u), daemon=True)
                   for i, (g, u) in enumerate(items)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout + 0.5)
        nodes = [n for n in out if n]
        with self._probe_lock:
            self._probe_cache = {'ts': time.time(), 'nodes': nodes}
        return [dict(n) for n in nodes]

    # ==================== 对外接口：mist（手写 sketch）专有动作 ====================
    # 这几个都返回可直接丢给手机页的 dict，且是同步阻塞的（调用方的 FastAPI 端点要
    # 用普通 def，让 FastAPI 丢线程池，别阻塞事件循环）。

    def mist_start(self, seconds=3, group='all'):
        """定时喷雾：``GET /start?time=seconds``（seconds 受 max_duration 钳制）。"""
        group = group or 'all'
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            seconds = 3
        if seconds <= 0:
            seconds = 1
        requested = seconds
        clamped = seconds > self.max_duration
        if clamped:
            seconds = self.max_duration
        ok, err = self._write_detail({'group': group, 'duration': seconds})
        return {
            'success': bool(ok), 'group': group, 'duration': seconds,
            'requested': requested, 'clamped': bool(clamped),
            'max_duration': self.max_duration,
            'available': bool(self.available), 'error': err or None,
        }

    def mist_start_direct(self, group='all'):
        """持续喷雾：``GET /startDirect``（固件不自停，服务器 direct_max_sec 后兜底关）。"""
        group = group or 'all'
        if not self.enabled or not self.available:
            return {'success': False, 'group': group, 'available': False,
                    'direct_max_sec': self.direct_max_sec,
                    'error': '喷淋链路不可用（检查 SPRAY.transport / http_targets）'}
        pairs = [(g, u) for g, u in self._targets_for(group)
                 if self.target_protocols.get(g, self.default_protocol) == 'mist']
        if not pairs:
            return {'success': False, 'group': group, 'available': True,
                    'direct_max_sec': self.direct_max_sec,
                    'error': '没有 mist 协议节点（持续喷雾只适用于手写 sketch 固件）'}
        ok = False
        errs = []
        for g, url in pairs:
            good, err = self._write_mist(url, {'group': g, 'action': 'direct'})
            ok = ok or good
            if good:
                self._arm_direct_timer(g)
            elif err:
                errs.append(f'{g}: {err}')
        return {
            'success': bool(ok), 'group': group, 'nodes': [g for g, _ in pairs],
            'direct_max_sec': self.direct_max_sec, 'available': True,
            'error': '; '.join(errs) or None,
        }

    def mist_stop(self, group='all'):
        """停止雾化：同步 ``GET /stop``，并撤掉持续模式兜底计时器。"""
        group = group or 'all'
        if not self.enabled or not self.available:
            return {'success': False, 'group': group, 'available': False,
                    'error': '喷淋链路不可用（检查 SPRAY.transport / http_targets）'}
        self._cancel_direct_timer(group)
        ok, err = self._stop_now(group)
        return {'success': bool(ok), 'group': group, 'available': True, 'error': err or None}

    @staticmethod
    def _parse_mist_status(html):
        """解析 sketch 状态页（``GET /``）里的中文状态文本。

        页面里还有"⏱️ 定时开启雾化"这类按钮文案，所以只能认带「模式」的词
        （『定时模式』『持续模式』）与『空闲』，避免把按钮文字当成运行状态。
        """
        text = re.sub(r'<[^>]+>', ' ', str(html or ''))
        running = '空闲' not in text
        if '定时模式' in text:
            mode = 'timed'
        elif '持续模式' in text:
            mode = 'direct'
        else:
            mode = 'unknown' if running else 'idle'
        match = re.search(r'剩余[:：]\s*(\d+)', text)
        return {
            'running': running, 'mode': mode,
            'remain': int(match.group(1)) if match else None,
        }

    def mist_status(self, group='all'):
        """读回节点状态：连不上就如实报不可达（现场排查靠它，不静默）。"""
        group = group or 'all'
        out = {'group': group, 'nodes': [], 'reachable': False,
               'direct_max_sec': self.direct_max_sec, 'transport': self.transport,
               'available': bool(self.available)}
        if self.transport != 'http':
            out['error'] = f'当前 transport={self.transport}，没有 HTTP 节点可探测'
            return out
        pairs = self._targets_for(group)
        if not pairs:
            out['error'] = '无可用目标地址（检查 SPRAY.http_targets）'
            return out
        for g, url in pairs:
            node = {'group': g, 'url': url,
                    'protocol': self.target_protocols.get(g, self.default_protocol),
                    'reachable': False, 'direct_remaining': self._direct_remaining(g)}
            if node['protocol'] != 'mist':
                node['error'] = '该目标是 json 协议节点（状态页仅 mist 固件提供）'
                out['nodes'].append(node)
                continue
            code, text = self._http_get(self._base_url(url) + '/', timeout=self.status_timeout)
            if code is None:
                node['error'] = str(text)
            elif not (200 <= code < 300):
                node['error'] = f'HTTP {code}'
            else:
                node['reachable'] = True
                node.update(self._parse_mist_status(text))
                out['reachable'] = True
            out['nodes'].append(node)
        return out

    def close(self):
        self._cancel_direct_timer('all')
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
        if self._mqtt is not None:
            try:
                self._mqtt.loop_stop()
                self._mqtt.disconnect()
            except Exception:
                pass
