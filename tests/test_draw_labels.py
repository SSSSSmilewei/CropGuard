# -*- coding: utf-8 -*-
"""检测框标签可读性的回归用例。

现场问题（2026-10-11）：拍照识别的框上文字太小，看不清类别和置信度。
根因：`draw_info` 里 font_scale 写死 0.5，不随图像尺寸缩放 ——
720p 勉强能看，但相机原图（1944x2580）缩到 660px 预览窗口后标签只剩 2~3px。

验收口径：**标签文字在预览窗口里至少要有 8px 高**（肉眼可读的下限）。
预览是按长边等比缩放到 label_img 宽度，所以这里用同一个缩放比例反推。
"""
import numpy as np

from _registry import test_case

from tool import tools

PREVIEW_W = 660        # main.py 里 label_img 的宽度
MIN_READABLE_PX = 8    # 预览窗口里标签文字的最小可读高度


def _on_screen_text_height(h, w):
    """标签文字缩到预览窗口后，在屏幕上大约有多高（px）。"""
    img = np.zeros((h, w, 3), np.uint8)
    scale, _, _ = tools._label_metrics(img)
    native_h = tools._HERSHEY_UNIT_HEIGHT * scale       # 原图上的文字高度
    preview_scale = PREVIEW_W / float(max(h, w))
    return native_h * preview_scale


# ==================== 尺寸自适应 ====================
@test_case
def test_label_readable_at_every_resolution():
    """各种分辨率下，缩到预览窗口后标签都要看得清。

    这正是原来的 bug：480p 时字号刚好，2580px 的相机原图就糊成一个色点了。
    """
    for (h, w) in ((480, 640), (720, 1280), (1080, 1920), (1944, 2580), (3000, 4000)):
        px = _on_screen_text_height(h, w)
        assert px >= MIN_READABLE_PX, \
            f'{w}x{h} 的图缩到预览后标签只有 {px:.1f}px（要求 >= {MIN_READABLE_PX}px）'


@test_case
def test_label_scale_grows_with_image_size():
    """字号必须随图像尺寸单调增大（原来是恒定 0.5）。"""
    sizes = [(480, 640), (720, 1280), (1944, 2580)]
    scales = [tools._label_metrics(np.zeros((h, w, 3), np.uint8))[0] for h, w in sizes]
    assert scales[0] < scales[1] < scales[2], scales
    assert scales[0] > 0.5, f'连最小的图都不该用原来那个 0.5：{scales}'


@test_case
def test_label_scale_is_clamped():
    """极端尺寸要夹住，别让标签大到盖满画面 / 小到看不见。"""
    tiny = tools._label_metrics(np.zeros((64, 64, 3), np.uint8))[0]
    huge = tools._label_metrics(np.zeros((12000, 16000, 3), np.uint8))[0]
    assert tiny == tools._LABEL_MIN_SCALE, tiny
    assert huge == tools._LABEL_MAX_SCALE, huge


@test_case
def test_line_thickness_scales_too():
    """框线和标签内边距也要跟着放大，否则大图上字大了框还是发丝。"""
    _, th_small, pad_small = tools._label_metrics(np.zeros((480, 640, 3), np.uint8))
    _, th_large, pad_large = tools._label_metrics(np.zeros((1944, 2580, 3), np.uint8))
    assert th_large > th_small >= 1, (th_small, th_large)
    assert pad_large > pad_small >= 3, (pad_small, pad_large)


# ==================== 对比度 ====================
@test_case
def test_text_color_picked_by_background_luma():
    """浅底配黑字、深底配白字 —— 保证任何类别色上都读得清。"""
    assert tools._text_color_for((200, 230, 240)) == (0, 0, 0), '亮底应黑字'
    assert tools._text_color_for((20, 20, 30)) == (255, 255, 255), '暗底应白字'


@test_case
def test_all_class_colors_get_readable_text():
    """所有类别色都要能选出有对比度的文字色（不是一律白字）。"""
    from tool.tools import compute_color_for_labels
    dark_bg_white_text = 0
    for i in range(80):
        color = compute_color_for_labels(i)
        text = tools._text_color_for(color)
        assert text in ((0, 0, 0), (255, 255, 255)), (i, color, text)
        if text == (255, 255, 255):
            dark_bg_white_text += 1
    # 既不能全是白字（说明没按亮度判断），也不能一个都没有
    assert 0 < dark_bg_white_text < 80, dark_bg_white_text


# ==================== 绘制本身 ====================
@test_case
def test_draw_info_renders_and_keeps_signature():
    """draw_info(frame, results) 的签名与返回帧不变（main.py / api_server 都在用）。"""
    img = np.zeros((720, 1280, 3), np.uint8)
    results = [['aphids', 0.81, [100, 100, 400, 300]]]
    out = tools.draw_info(img.copy(), results)
    assert out.shape == (720, 1280, 3)
    assert out.sum() > 0, '应该真的画上了东西'


@test_case
def test_draw_info_handles_empty_and_edge_cases():
    """没目标 / 框贴边 / 置信度不是浮点数，都不能抛异常。"""
    img = np.zeros((480, 640, 3), np.uint8)
    assert tools.draw_info(img.copy(), []) is not None
    # 框贴着上边缘：标签要往框内侧挪，不能被裁掉
    out = tools.draw_info(img.copy(), [['aphids', 0.9, [0, 0, 200, 150]]])
    assert out.shape == img.shape
    # 置信度是字符串（老数据）也不能崩
    tools.draw_info(img.copy(), [['aphids', '0.9', [10, 10, 100, 100]]])
    # 框超出画面
    tools.draw_info(img.copy(), [['aphids', 0.5, [-50, -50, 900, 900]]])


@test_case
def test_draw_info_output_is_bgr_uint8():
    """画完仍是 8UC3，后面 _display_image / imencode 才不会炸。"""
    img = np.zeros((720, 1280, 3), np.uint8)
    out = tools.draw_info(img.copy(), [['grub', 0.85, [10, 10, 300, 300]]])
    assert out.dtype == np.uint8, out.dtype
    assert out.ndim == 3 and out.shape[2] == 3, out.shape
