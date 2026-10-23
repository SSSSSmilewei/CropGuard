# -*- coding: utf-8 -*-
"""评分快照的落盘 / 读取（与桌面 GUI 的 ``output/snapshots`` 同一个目录）。

为什么要单独一个模块：``api_server`` 里那套端点要 import 模型（很重），
而"dataURL → 文件"、"文件名 → 安全路径"这两件事是纯逻辑，必须能被单测直接覆盖。
安全边界（现场机器会被评委/队友随手点）：
* 只收 ``data:image/(jpeg|png);base64,`` 开头的图片；
* 单张上限 8MB（一张 1280x720 JPEG 通常 <500KB，超了多半是误传原图/截图）；
* 读取只按 basename 取、只认图片后缀，绝不接受子目录或 ``..``。
"""
import base64
import os
import re
from datetime import datetime

MAX_BYTES = 8 * 1024 * 1024
_DATAURL = re.compile(r'^data:image/(jpeg|jpg|png);base64,(.+)$', re.IGNORECASE | re.DOTALL)
_IMG_EXT = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')


def _is_image(name):
    return str(name or '').lower().endswith(_IMG_EXT)


def save(data_url, out_dir):
    """把 dataURL 写成文件，返回 ``{'name', 'path'}``；不合法抛 ``ValueError``（由端点转 400）。"""
    m = _DATAURL.match(str(data_url or '').strip())
    if not m:
        raise ValueError('image 必须是 data:image/jpeg|png;base64,... 的 dataURL')
    ext = 'png' if m.group(1).lower() == 'png' else 'jpg'
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except Exception:
        raise ValueError('图片 base64 解不开')
    if not raw:
        raise ValueError('图片是空的')
    if len(raw) > MAX_BYTES:
        raise ValueError(f'图片太大（上限 {MAX_BYTES // 1024 // 1024}MB）')

    out_dir = str(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    # 命名与 GUI 的 _save_snapshot 同风格：年月日_时分秒_毫秒
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
    name = f'eval_{stamp}.{ext}'
    path = os.path.join(out_dir, name)
    with open(path, 'wb') as f:
        f.write(raw)
    return {'name': name, 'path': path}


def path_of(name, out_dir):
    """把 ``?name=`` 解析成安全路径；非法/不存在抛 ``ValueError``。"""
    base = os.path.basename(str(name or ''))
    if not base or base != str(name or ''):
        raise ValueError('非法文件名')
    if not _is_image(base):
        raise ValueError('只允许图片后缀')
    path = os.path.join(str(out_dir), base)
    if not os.path.isfile(path):
        raise ValueError('快照不存在')
    return path
