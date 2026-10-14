# -*- coding: utf-8 -*-
"""手写二维码（tool/qr_min.py）必须真能被扫出来。

旧实现有三个 bug，同时让**所有版本**的码都扫不出：
格式信息写成了转置、功能区表多占两个数据格、v6~v9 分块表把总码字当每块码字。
这里用 OpenCV 的解码器逐版本（v1~v10）验证，而不是只看"生成没报错"。
"""
from _registry import requires, test_case


def _decode(text):
    import numpy as np
    import cv2
    from tool.qr_min import to_pil
    img = np.array(to_pil(text, box_size=6, border=4))
    for det in (cv2.QRCodeDetector(),
                getattr(cv2, 'QRCodeDetectorAruco', cv2.QRCodeDetector)()):
        val = det.detectAndDecode(img)[0]
        if val:
            return val
    return ''


@test_case(10)     # v1
@test_case(30)     # v2
@test_case(50)     # v3
@test_case(70)     # v4
@test_case(100)    # v5
@test_case(120)    # v6（旧分块表在这里开始出错）
@test_case(150)    # v7（含版本信息区）
@test_case(180)    # v8
@test_case(220)    # v9
@test_case(260)    # v10（两组不等长分块）
def test_qr_decodes_every_version(length):
    requires('cv2', 'PIL', 'numpy')
    text = ('https://192.168.1.23:8443/m?k=' + 'ab9Z' * 100)[:length]
    got = _decode(text)
    assert got == text, f'{length} 字节解码失败: {got!r}'
