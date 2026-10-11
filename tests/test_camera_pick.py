# -*- coding: utf-8 -*-
"""摄像头"按设备标识选"的回归用例（不需要真实出图，枚举即可）。

背景（现场真实事故）：`camera_num: 1` 在 2026-10-08 指向外接 USB 相机，
到 10-11 系统把两个相机的索引整个翻了过来，`1` 变成了笔记本内置摄像头。
因为两种相机都能正常出图，程序没有任何报错，**画面看起来完全正常**，
直到有人发现"用的不是我的外接相机"。

所以这里锁住两条：
1. 设备标识（VID/设备名）必须能稳定解析到正确索引；
2. 标识解析失败时**必须报错中止**，绝不能退化去扫别的索引、静默换一台相机。
"""
from _registry import SkipTest, test_case

from tool import camera_source as cam


# ==================== 标识 -> 索引 ====================
@test_case
def test_resolve_source_numeric():
    """数字/数字串就是索引本身。"""
    assert cam.resolve_source(1)[0] == 1
    assert cam.resolve_source('2')[0] == 2
    assert cam.resolve_source(None)[0] == 0
    assert cam.resolve_source('')[0] == 0


@test_case
def test_resolve_source_url_and_path_untouched():
    """RTSP/HTTP 流、视频文件、图片路径原样透传，不做设备枚举。"""
    for spec in ('rtsp://admin:pw@192.168.4.51:554/Streaming/Channels/101',
                 'http://10.0.0.5:8080/video',
                 './output/movie.mp4',
                 r'D:\clips\a.avi',
                 'frames/frame_%05d.png'):
        got, err, name = cam.resolve_source(spec)
        assert got == spec, (spec, got)
        assert err == '', (spec, err)
        assert name == ''


@test_case
def test_resolve_source_unknown_device_reports_available():
    """找不到的标识要给出错误 + 当前可用设备清单（不能静默返回个索引）。"""
    got, err, name = cam.resolve_source('vid_ffff')
    assert got is None, got
    assert '找不到匹配' in err, err
    # 错误信息要能指导排查：把现有相机列出来
    assert 'vid_ffff' in err, err


@test_case
def test_resolve_source_matches_real_devices():
    """有相机时：按 VID / 设备名解析出的索引，必须就是枚举表里那台设备。"""
    from tool.ds_enum import list_devices
    devices, _ = list_devices()
    if not devices:
        raise SkipTest('本机枚举不到 DirectShow 相机，跳过')
    for d in devices:
        if d.get('vid'):
            index, err, _ = cam.resolve_source('vid_' + d['vid'])
            assert err == '', (d, err)
            assert index == d['index'], (d, index)
        if d.get('name'):
            index, err, _ = cam.resolve_source(d['name'])
            assert err == '', (d, err)
            assert index == d['index'], (d, index)


@test_case
def test_find_index_case_insensitive():
    """设备名匹配不区分大小写。"""
    from tool.ds_enum import find_index, list_devices
    devices, _ = list_devices()
    named = [d for d in devices if d.get('name')]
    if not named:
        raise SkipTest('本机没有可枚举出名字的相机，跳过')
    d = named[0]
    assert find_index(d['name'].upper()) == d['index'], d
    assert find_index(d['name'].lower()) == d['index'], d


# ==================== 解析失败必须"停下来"，不能换相机 ====================
@test_case
def test_bad_selector_does_not_open_another_camera():
    """核心回归：标识匹配不上时，绝不能退化成"扫一遍索引挑一个能开的"。

    旧行为正是这样：写死的索引失效后，resolve_camera 会从 0 开始扫，
    哪个能打开就用哪个 —— 于是静默启用了另一个摄像头。
    """
    src = cam.CameraSource('vid_ffff', width=0, height=0, probe_timeout=0.5)
    try:
        src.start()                       # 会走 _open_best
        st = src.state()
        assert st['index'] is None, f'不该解析出任何索引: {st}'
        assert st['opened_once'] is False, f'不该打开任何设备: {st}'
        assert '找不到匹配' in (st['last_error'] or ''), st
        report = st.get('resolve') or {}
        assert '不会改用其它相机' in str(report.get('capture')), report
        # 关键：不能有"扫其它索引"的痕迹
        tried = report.get('tried') or []
        assert not any('index=' in str(t) and '✅' in str(t) for t in tried), tried
    finally:
        src.close()


@test_case
def test_valid_selector_records_device_and_index():
    """标识解析成功时，state() 里要能看出"选中的是哪台设备、落在哪个索引"。"""
    from tool.ds_enum import list_devices
    devices, _ = list_devices()
    with_vid = [d for d in devices if d.get('vid')]
    if not with_vid:
        raise SkipTest('本机没有带 VID 的相机，跳过')
    d = with_vid[0]
    spec = 'vid_' + d['vid']
    index, err, name = cam.resolve_source(spec)
    assert err == '' and index == d['index'], (spec, index, err, d)

    src = cam.CameraSource(spec, width=0, height=0, probe_timeout=0.5)
    try:
        st = src.state()
        assert st['source_spec'] == spec, st
        assert st['index'] == d['index'], st
        assert st['device'] == spec, st
        assert not st['last_error'], st
    finally:
        src.close()


@test_case
def test_camera_label_prefers_device_name():
    """GUI 状态栏标签要显示设备名（分不清外接/内置就是栽在这上面）。"""
    import importlib.util
    import os
    from _registry import requires
    requires('ultralytics', 'PyQt5')
    main_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'main.py')
    spec = importlib.util.spec_from_file_location('cg_cam_label', main_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # __name__ != '__main__'，不会启动 GUI

    label = mod.MyMainWindow._camera_label
    assert 'USB Camera' in label({'device': 'USB Camera', 'size': '1280x720'})
    # 名字太长要截断（状态栏只有 240px 宽）
    long_name = label({'device': 'A' * 60, 'size': '640x480'})
    assert len(long_name) < 40, long_name
    assert '640x480' in long_name, long_name
    # 没有设备名时退回索引
    assert 'index' not in label({'index': 0}).lower() or '索引' in label({'index': 0})
    assert '索引0' in label({'index': 0}), label({'index': 0})
