# -*- coding: utf-8 -*-
"""设计令牌单一来源：站点与原生页必须用同一套变量，否则页面"看着不像一个产品"。

* 事实来源：`web/src/styles/tokens.css`（Vue 的 base.css `@import` 它）
* 原生页副本：`serve/static/tokens.css`（由 scripts/sync_tokens.py 生成）

改了令牌却忘了跑脚本 → 这里直接失败（不靠肉眼对比）。
"""
import os
import re

from _registry import test_case

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_TOKENS = os.path.join(ROOT, 'web', 'src', 'styles', 'tokens.css')
NATIVE_TOKENS = os.path.join(ROOT, 'serve', 'static', 'tokens.css')
VAR_RE = re.compile(r'(--[a-zA-Z0-9-]+)\s*:\s*([^;]+);')


def _vars(path):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    return {k: ' '.join(v.split()) for k, v in VAR_RE.findall(text)}


@test_case
def test_native_tokens_file_exists_and_defines_core_palette():
    assert os.path.isfile(NATIVE_TOKENS), '缺 serve/static/tokens.css（原生页没有令牌可引）'
    got = _vars(NATIVE_TOKENS)
    for key in ('--ground', '--panel', '--ink', '--brand', '--risk-high', '--font-cn'):
        assert key in got, f'tokens 缺 {key}'


@test_case
def test_native_tokens_in_sync_with_web():
    web = _vars(WEB_TOKENS)
    native = _vars(NATIVE_TOKENS)
    missing = sorted(set(web) - set(native))
    extra = sorted(set(native) - set(web))
    assert not missing, f'serve/static/tokens.css 少了 {missing}（跑 py -3.14 scripts/sync_tokens.py）'
    assert not extra, f'serve/static/tokens.css 多了 {extra}（跑 py -3.14 scripts/sync_tokens.py）'
    drift = {k: (web[k], native[k]) for k in web if web[k] != native[k]}
    assert not drift, f'令牌值漂移（跑 py -3.14 scripts/sync_tokens.py）：{drift}'


@test_case
def test_native_pages_link_shared_tokens():
    for rel in (os.path.join('serve', 'templates', 'mobile.html'),
                os.path.join('serve', 'templates', 'eval.html'),
                os.path.join('serve', 'pages', 'demo.html')):
        with open(os.path.join(ROOT, rel), 'r', encoding='utf-8') as f:
            html = f.read()
        assert '/static/tokens.css' in html, f'{rel} 没引用站点令牌'
