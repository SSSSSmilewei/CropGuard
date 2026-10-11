# -*- coding: utf-8 -*-
"""静态 HTML 页面加载器。

把原先内联在 api_server.py 里的 PC 首页、/stream 实时监测页拆到
serve/pages/ 目录下，api_server.py 只负责路由注册，降低单文件行数。
"""
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
_PAGES_DIR = os.path.join(_DIR, 'pages')


def load(name):
    """按文件名（不含扩展名）加载 serve/pages/ 下的 HTML 页面。"""
    path = os.path.join(_PAGES_DIR, f'{name}.html')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return f'<!-- page {name} not found -->'
