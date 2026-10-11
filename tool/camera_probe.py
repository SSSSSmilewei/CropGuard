# -*- coding: utf-8 -*-
"""摄像头探针：枚举索引 0..N，找出外接摄像头是哪个号，并存一张快照。

用法：
    python tool/camera_probe.py            # 扫 0..5
    python tool/camera_probe.py 0 1 2 3    # 只扫指定索引
    python tool/camera_probe.py -n 8       # 扫 0..7

输出：
    output/camera_probe/cam_<idx>.jpg      # 每个能打开的索引各存一帧，用来肉眼确认画面
    output/camera_probe/report.txt         # 文本结论，方便贴给别人看

为什么用 CAP_DSHOW：Windows 上 MSMF 后端长跑容易卡死（cap_msmf OnReadSample 报错后
彻底读不到帧），DirectShow 更稳，main.py 里也是这么选的。
"""
import os
import sys
import time
import platform

import cv2

# 允许 `python tool/camera_probe.py` 直接运行时也能 import 到项目内的模块
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


CAP_BACKENDS = []
if platform.system() == 'Windows':
    CAP_BACKENDS.append(('DSHOW', cv2.CAP_DSHOW))
CAP_BACKENDS.append(('默认', None))


def probe(index, backend_name, flag, out_dir, frames=8):
    """试着打开一个索引，成功则返回信息 dict，失败返回 None。"""
    try:
        cap = cv2.VideoCapture(index, flag) if flag is not None else cv2.VideoCapture(index)
    except Exception as e:
        return {'index': index, 'backend': backend_name, 'ok': False, 'err': repr(e)}
    if cap is None or not cap.isOpened():
        if cap is not None:
            cap.release()
        return {'index': index, 'backend': backend_name, 'ok': False, 'err': 'isOpened()=False'}

    # 读若干帧，等驱动真正出图（第一帧常是黑的/空的）
    frame = None
    for _ in range(frames):
        ok, f = cap.read()
        if ok and f is not None:
            frame = f
        time.sleep(0.05)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    if frame is None:
        return {'index': index, 'backend': backend_name, 'ok': False,
                'err': '打不开出图（isOpened 为真但 read 一直失败）'}

    path = os.path.join(out_dir, f'cam_{index}.jpg')
    cv2.imwrite(path, frame)
    return {
        'index': index, 'backend': backend_name, 'ok': True,
        'size': f'{w}x{h}',
        'frame_size': f'{frame.shape[1]}x{frame.shape[0]}',
        'fps': round(fps, 1) if fps else 0.0,
        'snapshot': path,
    }


def main():
    args = sys.argv[1:]
    indices = list(range(6))
    if args:
        if args[0] == '-n':
            indices = list(range(int(args[1])))
        else:
            indices = [int(a) for a in args]

    out_dir = os.path.join('output', 'camera_probe')
    os.makedirs(out_dir, exist_ok=True)

    lines = []
    lines.append(f'OpenCV {cv2.__version__} / Python {sys.version.split()[0]} / {platform.system()}')
    lines.append(f'扫描索引: {indices}')
    lines.append('')

    # 先给"索引 ↔ 设备名/VID"对照表 —— 这才是稳定的选择依据。
    # 索引会因插拔/重启而重排（本机实测翻过一次），设备标识不会。
    try:
        from tool.ds_enum import list_devices
        devices, derrs = list_devices()
        lines.append(f'DirectShow 设备表（{len(devices)} 个，顺序即 VideoCapture 索引）：')
        for d in devices:
            ident = f"vid_{d['vid']}&pid_{d['pid']}" if d.get('vid') else '未知'
            lines.append(f"  索引 {d['index']}: {d.get('name') or '(无名)'}   [{ident}]")
            if d.get('vid'):
                lines.append(f"           config 里可写: camera_device: 'vid_{d['vid']}'")
        lines.append('  ⚠️ 工具无法自动判断哪个是"外接"——请配合下面的快照肉眼确认。')
        for e in derrs:
            lines.append(f'  （枚举提示：{e}）')
        lines.append('')
    except Exception as exc:
        lines.append(f'（DirectShow 设备表枚举失败：{type(exc).__name__}: {exc}）')
        lines.append('')

    good = []
    for idx in indices:
        got = None
        for name, flag in CAP_BACKENDS:
            info = probe(idx, name, flag, out_dir)
            if info['ok']:
                got = info
                break
        if got:
            good.append(got)
            lines.append(f"  [OK]   索引 {idx}  后端={got['backend']}  "
                         f"报告={got['size']}  实际={got['frame_size']}  "
                         f"fps={got['fps']}  快照={got['snapshot']}")
        else:
            lines.append(f"  [空]   索引 {idx}  打不开")

    lines.append('')
    if not good:
        lines.append('结论：一个摄像头都没打开。检查：USB 是否插好、'
                     '是否被其他程序占用（浏览器/微信/QQ/另一个 Python 进程）、'
                     'Windows 设置 → 隐私 → 相机 是否允许桌面应用访问。')
    else:
        lines.append('结论：')
        lines.append('  1) 打开上面的快照 jpg，肉眼确认哪一张是你要用的外接摄像头；')
        lines.append('  2) 【推荐】在 config/configs.yaml 里写**设备标识**而不是索引：')
        lines.append('       CONFIG.camera_device: \'vid_xxxx\'      # 取上面设备表里的 VID')
        lines.append('     索引会因插拔/重启而重排（本机实测翻转过一次），标识不会；')
        lines.append('  3) 只有确实想按索引时才用 CONFIG.camera_num（并把 camera_device 留空）：')
        for g in good:
            lines.append(f"       索引 {g['index']}  ->  {g['snapshot']}")

    report = '\n'.join(lines)
    print(report)
    with open(os.path.join(out_dir, 'report.txt'), 'w', encoding='utf-8') as f:
        f.write(report + '\n')
    print(f'\n报告已存: {os.path.join(out_dir, "report.txt")}')


if __name__ == '__main__':
    main()
