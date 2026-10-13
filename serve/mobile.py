# -*- coding: utf-8 -*-
"""手机会话页（`GET /m`）的渲染入口。

页面资源拆成三份独立文件，便于维护：
- templates/mobile.html：页面骨架
- static/mobile.css：样式
- static/mobile.js：交互逻辑

本模块只负责读取、拼接占位符、返回完整 HTML。
"""
import os

_DIR = os.path.dirname(os.path.abspath(__file__))


def _read_file(*parts):
    path = os.path.join(_DIR, *parts)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def render(host, http_port, https_port=None, frame_interval_ms=400, upload_max_side=960,
           mist_url='', mist_max_sec=5, mist_direct_sec=300):
    """把占位符替换成现场实际参数，返回可直接由服务端返回的 HTML。

    mist_*: 「雾化控制」卡片用 —— 节点地址（节点自带状态页链接）、单次时长上限、
            持续喷雾的服务器兜底秒数。
    """
    html = _read_file('templates', 'mobile.html')
    css = _read_file('static', 'mobile.css')
    js = _read_file('static', 'mobile.js')

    js = js.replace('__HTTP_PORT__', str(http_port))
    js = js.replace('__HTTPS_PORT__', str(https_port or (int(http_port) + 360)))
    js = js.replace('__HOST__', host or '127.0.0.1')
    js = js.replace('__FRAME_INTERVAL__', str(int(frame_interval_ms or 400)))
    js = js.replace('__UPLOAD_MAX_SIDE__', str(int(upload_max_side or 960)))
    js = js.replace('__MIST_URL__', str(mist_url or ''))
    js = js.replace('__MIST_MAX_SEC__', str(int(mist_max_sec or 5)))
    js = js.replace('__MIST_DIRECT_SEC__', str(int(mist_direct_sec or 0)))

    html = html.replace('{{STYLE}}', css)
    html = html.replace('{{SCRIPT}}', js)
    return html
