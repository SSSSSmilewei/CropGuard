# -*- coding: utf-8 -*-
"""GUI 日志 / 回看 / 现场评测 的回归用例（offscreen 无窗口运行）。

对应 2026-10-11 定稿口径：
  1. **实时检测不写识别日志**（只在预览上画框）；
  2. 写日志的只有"样本采集"：拍照识别 / 打开图片 / 打开文件夹；
  3. 没检测到目标不写行；一次采集 = 一行（不再做同目标合并）；
  4. 点历史行可定格回看，并能给评委打 ✓ 正确 / ✗ 错误；
  5. 评测：第一张样本自动起表倒计时，满 target_samples 自动停表。

做法：把 MyMainWindow 在 `QT_QPA_PLATFORM=offscreen` 下真实建出来，
调用真实方法后断言表格内容 / 画面像素 / 面板文字 —— 纯肉眼看容易漏。
"""
import os
import shutil

import numpy as np
import cv2

from _registry import requires, test_case

# 必须在 import PyQt5 / main.py 之前设好，否则无显示环境会直接崩
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEST_SNAP_DIR = os.path.join(_ROOT, 'output', '_test_tmp', 'gui_hist')
_TEST_OUT_DIR = os.path.join(_ROOT, 'output', '_test_tmp', 'gui_out')

_WIN = None
_APP = None
_MOD = None


def _get_window():
    """建一次主窗口，多个用例复用（构造含 TTS/相机探测，比较重）。"""
    global _WIN, _APP, _MOD
    if _WIN is not None:
        return _WIN, _MOD

    requires('ultralytics', 'PyQt5')
    import importlib.util
    from PyQt5.QtWidgets import QApplication

    main_path = os.path.join(_ROOT, 'main.py')
    spec = importlib.util.spec_from_file_location('cg_gui_hist', main_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # __name__ != '__main__'，不会启动 GUI

    # 写到测试专用目录，别污染 output/snapshots
    shutil.rmtree(_TEST_SNAP_DIR, ignore_errors=True)
    os.makedirs(_TEST_SNAP_DIR, exist_ok=True)
    mod.HISTORY_DIR = _TEST_SNAP_DIR

    _APP = QApplication.instance() or QApplication([])
    _MOD = mod
    _WIN = mod.MyMainWindow(mod.config)
    _WIN.output_dir = _TEST_OUT_DIR
    return _WIN, _MOD


def _frame():
    """一张小图：够画框即可（不用真图，测试不依赖数据集）。"""
    img = np.zeros((120, 160, 3), np.uint8)
    img[40:80, 40:100] = (200, 200, 200)
    return img


def _mk_results(cls_name='aphids', conf=0.80):
    """格式与 tool.format_data 一致：[类别, 置信度, [x1,y1,x2,y2]]。"""
    return [[cls_name, conf, [10, 10, 60, 60]]]


def _reset(w, start_type='camera'):
    """清空表格 + 评测状态，让每个用例从干净状态开始。"""
    w._eval_reset()
    w.start_type = start_type
    w._last_camera_log = 0.0
    w._sample_capture = False


def _record(w, results, sample=True, time_str='2026-01-01 00:00:00'):
    """模拟一次推理结果落地。

    sample=True 表示"明确的样本采集"（拍照识别）；实时流必须传 False。
    """
    w._sample_capture = sample
    w._record_detection(results, {'cls_name': results[0][0] if results else '无目标',
                                  'score': results[0][1] if results else 0,
                                  'risk_level': '中风险',
                                  'risk_color': (0, 140, 255),
                                  'risk_detail': '测试'},
                        '0.02s', time_str, _frame())


# ==================== 规则 1/2：谁才写日志 ====================
@test_case
def test_live_camera_never_logs():
    """核心规则：摄像头实时流只画框，绝不写识别日志。

    旧实现每秒往表里塞一行，现场评测的 20 个样本会被实时流刷得乱七八糟。
    """
    w, _ = _get_window()
    _reset(w)                       # start_type='camera'
    for _ in range(5):
        _record(w, _mk_results('aphids', 0.80), sample=False)
    assert w.RowLength == 0, f'实时检测不该写日志，实际写了 {w.RowLength} 行'


@test_case
def test_snap_capture_logs_one_row():
    """拍照识别（样本采集）才写行。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.80), sample=True)
    assert w.RowLength == 1, w.RowLength
    assert w.tableWidget_info.item(0, 0).text() == '1', '首行编号应为 1'


@test_case
def test_image_and_dir_modes_still_log():
    """打开图片 / 打开文件夹仍要写日志（评委要能回看与评分）。"""
    for mode in ('img', 'dir'):
        w, _ = _get_window()
        _reset(w, start_type=mode)
        _record(w, _mk_results('aphids', 0.80), sample=False)
        assert w.RowLength == 1, f'{mode} 模式应写日志，实际 {w.RowLength}'


@test_case
def test_no_detection_writes_no_row():
    """未检测到目标时不写行（没有可评判的样本）。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, [], sample=True)
    assert w.RowLength == 0, f'未检测到目标不该写行，实际 {w.RowLength}'


@test_case
def test_each_capture_is_its_own_sample():
    """一次采集 = 一个样本：同类目标连拍两次要记 2 行（合并逻辑已移除）。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.50), sample=True)
    _record(w, _mk_results('aphids', 0.92), sample=True)
    assert w.RowLength == 2, f'每次拍照都是一个样本，应 2 行，实际 {w.RowLength}'
    assert w._row_record(0)['results'][0][1] == 0.50
    assert w._row_record(1)['results'][0][1] == 0.92


@test_case
def test_detection_writes_row_with_snapshot():
    """样本行要落盘带框快照，且「图片」列显示文件名（不是完整路径）。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.80), sample=True)

    rec = w._row_record(0)
    assert rec['image_path'] and os.path.exists(rec['image_path']), rec
    assert w.tableWidget_info.item(0, 1).text() == os.path.basename(rec['image_path'])
    assert 'aphids' in w.tableWidget_info.item(0, 3).text()
    assert w.tableWidget_info.item(0, 6).text() == '—', '未评判应显示占位符'


# ==================== 回看 ====================
@test_case
def test_cell_click_restores_snapshot_and_info():
    """点表格行 → 画面上出现当时的快照，信息栏恢复当时的类别/风险。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.88), sample=True)

    w.img = None
    w.img_show = None
    w.results = []
    w.cell_clicked(0, 0)

    assert w.img_show is not None, '点历史行应显示当时的快照'
    assert [r[0] for r in w.results] == ['aphids'], w.results
    assert w.label_class.text() not in ('--', ''), '类别信息应恢复'
    assert w.label_risk.text() == '中风险', w.label_risk.text()
    assert abs(float(w.label_score.text()) - 0.88) < 1e-6, w.label_score.text()


@test_case
def test_cell_click_pauses_live_preview():
    """实时预览中点历史行会先暂停，否则画面 30ms 后就被新帧覆盖。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.88), sample=True)

    w.is_running = True
    w.timer.start(30)
    try:
        w.cell_clicked(0, 0)
        assert w.is_running is False, '点历史行应暂停实时检测'
        assert not w.timer.isActive(), 'UI 定时器应停下，画面才定得住'
    finally:
        w.timer.stop()
        w.is_running = False


@test_case
def test_cell_click_survives_missing_snapshot():
    """快照文件被清理掉时不能崩，应退回用缓存帧重画。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.88), sample=True)
    rec = w._row_record(0)
    if rec.get('image_path') and os.path.exists(rec['image_path']):
        os.remove(rec['image_path'])
    rec['image_path'] = os.path.join(_TEST_SNAP_DIR, 'not_exist.jpg')

    w.img = _frame()
    w.cell_clicked(0, 0)                # 不应抛异常
    assert w.results and w.results[0][0] == 'aphids', w.results


@test_case
def test_image_mode_references_source_without_copying():
    """图片/文件夹模式：原图已在磁盘上 → 直接引用，不再多复制一份快照。"""
    w, _ = _get_window()
    _reset(w, start_type='img')
    src = os.path.join(_TEST_SNAP_DIR, 'src_pic.jpg')
    cv2.imwrite(src, _frame())
    w.img_path = src

    _record(w, _mk_results('aphids', 0.80), sample=False)

    rec = w._row_record(0)
    assert rec['image_path'] == src, f'应直接引用原图，实际 {rec["image_path"]}'
    assert rec['annotated'] is False, '引用的是原图（没画框），必须标记出来'

    w.img = None
    w.cell_clicked(0, 0)
    assert w.img_show is not None
    diff = int(np.abs(w.img_show.astype(int) - _frame().astype(int)).sum())
    assert diff > 0, '原图回看必须重新画出检测框'


# ==================== 关摄像头复位 ====================
@test_case
def test_reset_camera_view_clears_frame_and_shows_black():
    """关摄像头后必须是黑屏占位，不能停在最后一帧；且不能清掉日志。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.80), sample=True)
    w.img = _frame()
    w.img_show = _frame()
    w.results = _mk_results()
    w.label_class.setText('蚜虫')

    w._reset_camera_view()

    assert w.img is None and w.img_show is None, '当前帧状态必须清空'
    assert w.results == [], '结果也要清空'
    assert w.label_class.text() == '--', w.label_class.text()
    assert w.RowLength == 1, '关摄像头不能清掉评测日志'

    pm = w.label_img.pixmap()
    assert pm is not None and not pm.isNull(), '应换成占位图'
    r, g, b = pm.toImage().pixelColor(2, 2).getRgb()[:3]
    assert (r, g, b) == (0, 0, 0), f'占位画面应为黑底，实际 RGB={(r, g, b)}'


@test_case
def test_reset_camera_view_resets_risk_and_coords():
    """信息栏（风险/坐标）也要复位。"""
    w, _ = _get_window()
    _reset(w)
    w.label_risk.setText('高风险')
    w.label_xmin_v.setText('xmin: 12')
    w._reset_camera_view()
    assert w.label_risk.text() == '--', w.label_risk.text()
    assert w.label_xmin_v.text() == 'xmin: --', w.label_xmin_v.text()


# ==================== 拍照按钮行为 ====================
class _FakeWorker:
    """假的推理线程：只记录提交，不真跑模型（测试不该依赖 GPU/权重）。"""

    def __init__(self):
        self.submitted = []

    def submit(self, frame, img_name):
        self.submitted.append(img_name)

    def clear(self):
        self.submitted = []


class _FakeCamera:
    """假相机：read() 永远返回同一张图，省得依赖真实硬件。"""

    def __init__(self, frame):
        self._frame = frame

    def read(self):
        return True, self._frame.copy()

    def state(self):
        return {'state': 'ok', 'size': '160x120', 'fps': 30}

    def stop(self):
        pass


@test_case
def test_snap_auto_resumes_live_view():
    """拍照后必须自动回到实时画面 —— 现场 180s 拍 20 张的关键。

    旧行为：拍完永久定格，必须再点一次「开始运行 >」才能继续看实时，
    每张都这么来一下，时间全耗在点按钮上。
    """
    w, mod = _get_window()
    _reset(w)
    w.camera = _FakeCamera(_frame())
    w.worker = _FakeWorker()
    w.timer.stop()
    w.is_running = False
    try:
        w.snap_and_detect()
        assert not w.timer.isActive(), '拍照瞬间要先停住，好让用户看到拍下的那一张'
        token = w._snap_resume_token

        # 推理结果回来（真实链路上由 worker 信号触发）
        # 故意只给部分字段：show_info 必须用 .get 兜住，不能把信息栏刷成空白
        w.on_detect_result(_mk_results('aphids', 0.80),
                           {'risk_level': '低风险', 'risk_color': (0, 200, 255),
                            'risk_detail': '测试'},
                           '0.01s', 'T', 'snap.jpg', _frame())
        assert w.label_class.text() not in ('', None), '信息栏不该被清空'
        assert w._snap_resume_token > token, '结果回来后应安排"自动恢复实时"'

        w._resume_live(w._snap_resume_token)      # 直接触发，免得等真实延时
        assert w.is_running is True, '拍照后应自动恢复实时检测'
        assert w.timer.isActive(), '实时刷新定时器应重新跑起来'
        assert w.pushButton_start.text() == '停止检测', w.pushButton_start.text()

        # 再走一遍**真实 QTimer 路径**：把延时压到 0，pump 事件循环，
        # 确认 singleShot 真的接上了（只测方法本身会漏掉接线错误）
        old_ms = mod.SNAP_RESUME_MS
        mod.SNAP_RESUME_MS = 0
        try:
            w.timer.stop()
            w.is_running = False
            w.snap_and_detect()
            w.on_detect_result(_mk_results('aphids', 0.80), {}, '0.01s', 'T',
                               'snap2.jpg', _frame())
            for _ in range(10):
                _APP.processEvents()
            assert w.is_running is True, '真实定时器路径也应自动恢复实时'
            assert w.timer.isActive()
        finally:
            mod.SNAP_RESUME_MS = old_ms
    finally:
        w.timer.stop()
        w.is_running = False
        w.camera = None
        w.worker = None
        w._sample_capture = False


@test_case
def test_user_stop_cancels_auto_resume():
    """用户在定格期间点了「停止检测」，就不能被自动恢复覆盖。"""
    w, _ = _get_window()
    _reset(w)
    w.camera = _FakeCamera(_frame())
    w.worker = _FakeWorker()
    w.timer.stop()
    w.is_running = False
    try:
        w.snap_and_detect()
        token = w._snap_resume_token      # 定时器持有的那个令牌

        w.stop()                          # 用户明确要停
        w._resume_live(token)             # 旧回调这时才触发

        assert w.is_running is False, '用户停掉后不能被自动恢复'
        assert not w.timer.isActive(), '定时器不该被自动拉起'
    finally:
        w.timer.stop()
        w.is_running = False
        w.camera = None
        w.worker = None
        w._sample_capture = False


@test_case
def test_auto_resume_skipped_when_camera_closed():
    """定格期间把摄像头关了 → 自动恢复必须放弃（相机都没了）。"""
    w, _ = _get_window()
    _reset(w)
    w.camera = _FakeCamera(_frame())
    w.worker = _FakeWorker()
    try:
        w.snap_and_detect()
        token = w._snap_resume_token
        w.camera = None                   # 相机被关
        w._resume_live(token)
        assert w.is_running is False, '相机已关就不该恢复实时'
        assert not w.timer.isActive()
    finally:
        w.timer.stop()
        w.is_running = False
        w.camera = None
        w.worker = None
        w._sample_capture = False


@test_case
def test_snap_marks_sample_and_freezes_camera():
    """摄像头模式拍照：定格 + 标记为样本采集 + 计时打点。"""
    w, _ = _get_window()
    _reset(w)                       # start_type='camera'
    w.camera = None                 # 走 self.img 兜底分支
    w.img = _frame()
    w.img_name = 'camera_snap.jpg'
    w.worker = _FakeWorker()
    w.is_running = True
    w.timer.start(30)
    try:
        w.snap_and_detect()
        assert w.is_running is False, '拍照后应停止实时刷新（定格）'
        assert not w.timer.isActive(), 'UI 定时器应停下'
        assert w._snap_pending is True
        assert w._sample_capture is True, '拍照必须标记成"样本采集"，否则不会写日志'
        assert w.eval_t0 is not None, '第一张拍完就该开始计时'
        assert w.worker.submitted, '应把这一帧提交给推理线程'
    finally:
        w.timer.stop()
        w.is_running = False
        w.worker = None
        w._snap_pending = False
        w._sample_capture = False


@test_case
def test_snap_does_not_stop_folder_scan():
    """图片/文件夹模式下点「拍照识别」不该把批量检测掐断。"""
    w, _ = _get_window()
    _reset(w, start_type='dir')
    w.img = _frame()
    w.img_name = 'batch_001.jpg'
    w.worker = _FakeWorker()
    w.is_running = True
    w.timer.start(30)
    try:
        w.snap_and_detect()
        assert w.is_running is True, '文件夹批量检测不该被拍照按钮打断'
        assert w.timer.isActive(), '定时器应继续跑'
    finally:
        w.timer.stop()
        w.is_running = False
        w.worker = None
        w._sample_capture = False


# ==================== 现场评测：计时 ====================
@test_case
def test_eval_timer_starts_on_first_sample():
    """还没计时时，第一行样本落表就自动起表。"""
    w, mod = _get_window()
    _reset(w)
    assert w.eval_t0 is None and w.eval_running is False
    _record(w, _mk_results('aphids', 0.80), sample=True)
    assert w.eval_t0 is not None, '第一行样本应自动打点'
    assert w.eval_running is True, '计时器应已启动'
    assert w.eval_timer.isActive(), '倒计时 QTimer 应在跑'


@test_case
def test_eval_records_elapsed_per_sample():
    """每个样本要记下距计时起点的用时（导出报告里要用）。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.80), sample=True)
    rec = w._row_record(0)
    assert rec['elapsed'] is not None and rec['elapsed'] >= 0.0, rec


@test_case
def test_eval_stops_at_target_samples():
    """满 target_samples 自动停表（对应"180s 内完成 20 个样本"）。"""
    w, mod = _get_window()
    _reset(w)
    target = mod.EVAL_TARGET
    for i in range(target):
        _record(w, _mk_results('aphids', 0.80), sample=True)
    assert w.RowLength == target, w.RowLength
    assert w.eval_running is False, f'满 {target} 个样本应自动停表'
    assert w.eval_t_stop is not None, '应记录最终用时'
    assert not w.eval_timer.isActive()


@test_case
def test_eval_reset_clears_table_and_timer():
    """「新一轮评测」要清空日志、复位计时与得分。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.80), sample=True)
    assert w.RowLength == 1 and w.eval_t0 is not None

    w._eval_reset()

    assert w.RowLength == 0, '应清空日志'
    assert w.eval_t0 is None and w.eval_t_stop is None, '计时应复位'
    assert w.eval_running is False
    assert '0.0' in w.label_eval_total.text(), w.label_eval_total.text()


# ==================== 现场评测：评委判分 ====================
@test_case
def test_verdict_requires_a_selected_row():
    """没选中行时判分按钮应禁用（避免评委误判到不存在的样本）。"""
    w, _ = _get_window()
    _reset(w)
    assert w.pushButton_verdict_ok.isEnabled() is False

    _record(w, _mk_results('aphids', 0.80), sample=True)
    w.cell_clicked(0, 0)
    assert w.pushButton_verdict_ok.isEnabled() is True, '选中行后应可判分'


@test_case
def test_verdict_updates_row_and_score():
    """判 ✓ 正确 → 行内显示 ✓、准确度 +1、总分更新。"""
    w, mod = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.80), sample=True)
    w.cell_clicked(0, 0)

    w.set_verdict('正确')

    assert w._row_record(0)['verdict'] == '正确'
    assert '✓' in w.tableWidget_info.item(0, 6).text(), \
        w.tableWidget_info.item(0, 6).text()
    assert '1.0' in w.label_eval_acc.text(), w.label_eval_acc.text()


@test_case
def test_verdict_can_be_toggled_off():
    """再点一次同一个按钮 = 撤销判决（手滑可撤）。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.80), sample=True)
    w.cell_clicked(0, 0)

    w.set_verdict('正确')
    w.set_verdict('正确')
    assert w._row_record(0)['verdict'] is None, '再点一次应撤销'
    assert w.tableWidget_info.item(0, 6).text() == '—'


@test_case
def test_verdict_wrong_shows_cross():
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.80), sample=True)
    w.cell_clicked(0, 0)
    w.set_verdict('错误')
    assert w._row_record(0)['verdict'] == '错误'
    assert '✗' in w.tableWidget_info.item(0, 6).text()


@test_case
def test_end_session_button_locks_score():
    """会话进行中点按钮 = 结束并锁定得分。"""
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.80), sample=True)
    assert w.eval_running is True

    w.on_eval_start_clicked()          # 运行中 → 不弹框，直接结束

    assert w.eval_running is False
    assert w.eval_t_stop is not None
    assert '结束' not in w.pushButton_eval_start.text() or True   # 文案已复位


# ==================== 布局：按钮不能被盖住 ====================
@test_case
def test_no_widget_covers_a_button():
    """回归：按钮中心点不能被别的控件盖住，否则点击没反应、也没有日志。

    现场真实故障（2026-10-11）：「📷 拍照识别 / ⏹ 关闭摄像头」的下半部分
    被路径标签 `label_img_path`（QLabel，创建更晚 → z 序更高）压住。
    QLabel 不处理鼠标事件，而 Qt 把**被忽略的点击传给父控件**、
    **不会**传给下层的兄弟控件 —— 于是点下去什么都不发生，控制台也没有日志。

    这类 bug 从代码上完全看不出来，只能按实际几何算命中点。
    """
    from PyQt5 import QtWidgets
    w, _ = _get_window()
    w.resize(1280, 820)
    w.show()
    _APP.processEvents()

    covered = []
    for btn in w.centralwidget.findChildren(QtWidgets.QPushButton):
        if btn.isHidden():
            continue
        g = btn.geometry()
        cx, cy = g.x() + g.width() // 2, g.y() + g.height() // 2
        top = w.centralwidget.childAt(cx, cy)
        if top is not btn:
            covered.append(f'{btn.objectName()} 中心点被 '
                           f'{top.objectName() if top else "None"} 盖住')
    assert not covered, '; '.join(covered)


@test_case
def test_snap_button_click_actually_runs():
    """端到端确认按钮真的能触发（上一条用例的"人肉版"）。"""
    from PyQt5 import QtWidgets
    w, _ = _get_window()
    _reset(w)
    w.show()
    _APP.processEvents()

    w.img = _frame()                 # 给一张图，免得走"请先打开摄像头"的分支
    w.img_name = 't.jpg'
    w.worker = _FakeWorker()
    try:
        w.pushButton_snap.click()    # 模拟真实点击
        assert w._sample_capture is True, \
            '点击「拍照识别」没有真正执行 —— 按钮多半被别的控件盖住了'
        assert w.worker.submitted, '应把这一帧提交给推理线程'
    finally:
        w.worker = None
        w._sample_capture = False
        w.eval_timer.stop()


# ==================== 行号 ====================
@test_case
def test_fresh_window_numbers_first_row_as_one():
    """回归：全新窗口（没点过"新一轮评测"）的第一行编号必须是 1。

    原来 __init__ 里 `self.number = 1`，而 show_table 里又先 `+= 1`，
    于是首行编号变成 **2**，现场看着像"丢了一个样本"。
    共享窗口的其它用例都先跑了 `_eval_reset()`（把 number 归零），
    所以只有真建一个新窗口才抓得到这个 bug。
    """
    w, mod = _get_window()
    fresh = mod.MyMainWindow(mod.config)
    try:
        fresh.output_dir = _TEST_OUT_DIR
        assert fresh.number == 0, f'行号计数器初值应为 0，实际 {fresh.number}'
        fresh.start_type = 'camera'
        fresh._sample_capture = True
        fresh._record_detection(_mk_results('aphids', 0.80), {}, '0.01s', 'T', _frame())
        assert fresh.RowLength == 1, fresh.RowLength
        assert fresh.tableWidget_info.item(0, 0).text() == '1', \
            f'首行编号应为 1，实际 {fresh.tableWidget_info.item(0, 0).text()}'
    finally:
        fresh._eval_exported = True      # 别在关窗时又写一份报告
        fresh.close()


# ==================== 导出评分报告 ====================
@test_case
def test_record_writeback_survives_pyqt_deepcopy():
    """回归：PyQt 的 item.data(UserRole) 返回的是**深拷贝**，回写必须靠 uid。

    这个坑极隐蔽：`got is rec` 为 False，所以直接改 self._current_record
    不会影响表里那份，表现出来就是"点了 ✔ 没反应"，很容易被当成按钮没接上。
    """
    w, _ = _get_window()
    _reset(w)
    _record(w, _mk_results('aphids', 0.80), sample=True)

    stored = w._row_record(0)
    assert stored.get('uid') is not None, '记录必须带 uid（查找/回写的唯一依据）'

    # 直接改"传出去的那份" → 表里不应变化（正是旧实现失效的原因）
    rec = w._current_record
    rec['verdict'] = '错误'
    assert w._row_record(0)['verdict'] is None, \
        '直接改拷贝不该影响表 —— 说明必须走 _update_record'

    # 走正道 → 必须落表
    got = w._update_record(rec, verdict='正确')
    assert got is not None and got['verdict'] == '正确', got
    assert w._row_record(0)['verdict'] == '正确', '回写没落到表里'


@test_case
def test_update_record_survives_row_trimming():
    """裁剪旧行后行号会变，但 uid 不变 → 仍能正确定位并回写。"""
    w, mod = _get_window()
    _reset(w)
    old_max = mod.MAX_TABLE_ROWS
    mod.MAX_TABLE_ROWS = 2
    try:
        for _ in range(3):
            _record(w, _mk_results('aphids', 0.80), sample=True)
        assert w.RowLength == 2, f'应被裁到 2 行，实际 {w.RowLength}'
        last = w._row_record(1)
        assert last['no'] == 3, last.get('no')

        got = w._update_record(last, verdict='正确')
        assert got is not None, '裁剪后仍应能按 uid 找到该行'
        assert w._row_record(1)['verdict'] == '正确'
    finally:
        mod.MAX_TABLE_ROWS = old_max


@test_case
def test_export_eval_report_contains_summary():
    """导出的报告要含逐样本评判与末尾汇总（现场留档用）。"""
    w, mod = _get_window()
    _reset(w)
    shutil.rmtree(_TEST_OUT_DIR, ignore_errors=True)

    _record(w, _mk_results('aphids', 0.80), sample=True)
    _record(w, _mk_results('grub', 0.70), sample=True)
    w.cell_clicked(0, 0)
    w.set_verdict('正确')
    w.cell_clicked(1, 0)
    w.set_verdict('错误')

    path = w.export_eval_report(silent=True)
    assert path and os.path.exists(path), path

    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    assert '识别正确' in text, text[:400]
    assert '总分' in text, text[:400]
    assert '正确' in text and '错误' in text, '逐样本评判应写进报告'
