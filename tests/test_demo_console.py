# -*- coding: utf-8 -*-
"""演示指挥台 /demo 的回归：三个大按钮、四个开关/动作接口、自动喷洒总闸。

现场只有一个"小白"操作员：指挥台必须做到
* 一个页面覆盖三套演示（20 样本评分 / 定点自动 / 手机人机协同）；
* 所有"会动硬件"的开关都能在页面上关掉（安全底线）；
* 页面是单文件原生 HTML（不依赖 web/dist，前端坏了也能开）。
"""
import ast
import os
import re
import shutil
import subprocess
from pathlib import Path

from _registry import test_case

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / 'serve' / 'pages' / 'demo.html'


def _page_text():
    return PAGE.read_text(encoding='utf-8')


@test_case
def test_demo_page_exists_and_has_three_cards():
    assert PAGE.is_file(), 'serve/pages/demo.html 不存在'
    text = _page_text()
    for anchor in ('id="card1"', 'id="card2"', 'id="card3"'):
        assert anchor in text, f'指挥台缺少 {anchor}'
    for label in ('20 个实体样本', '定点监控', '手机拍照/实时', '打开评分 GUI', '开始定点监控'):
        assert label in text, f'指挥台缺少文案/按钮：{label}'


@test_case
def test_demo_page_has_safety_switches():
    """自动喷洒总闸、手机自动喷开关、立即停止按钮——任何一个都不能少。"""
    text = _page_text()
    for key in ('id="autoSpray"', 'id="phoneAuto"', 'id="btnStopSpray"'):
        assert key in text, f'缺少安全开关 {key}'
    assert '/api/spray/stop' in text, '缺少"立即停止喷洒"的调用'
    assert '大模型只给建议' in text, '页面必须写明安全边界'


@test_case
def test_demo_routes_registered():
    src = (ROOT / 'api_server.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    paths = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                if not isinstance(deco, ast.Call):
                    continue
                fn = deco.func
                if isinstance(fn, ast.Attribute) and fn.attr in ('get', 'post'):
                    if deco.args and isinstance(deco.args[0], ast.Constant):
                        paths.add(deco.args[0].value)
    for p in ('/demo', '/api/demo/status', '/api/demo/auto_spray',
              '/api/demo/phone_auto', '/api/demo/launch_gui', '/api/demo/close_gui',
              '/api/demo/last_command'):
        assert p in paths, f'api_server.py 没注册 {p}（现有 {sorted(paths)}）'


@test_case
def test_demo_inline_js_parses():
    """内嵌 JS 必须能解析（少个括号整页按钮就全废）。没装 node 就跳过。"""
    node = shutil.which('node')
    if not node:
        return 'SKIP'
    m = re.search(r'<script>(.*?)</script>', _page_text(), re.S)
    assert m, '页面里没找到 <script>'
    out = ROOT / 'output' / '_test_tmp'
    out.mkdir(parents=True, exist_ok=True)
    js = out / 'demo_inline.js'
    js.write_text(m.group(1), encoding='utf-8')
    p = subprocess.run([node, '--check', str(js)], capture_output=True, text=True)
    assert p.returncode == 0, f'demo.html 内嵌 JS 语法错误：{p.stderr[-400:]}'


@test_case
def test_auto_spray_gate_blocks_linkage():
    """总闸关掉后，自动联动只播语音、不下发喷淋。"""
    import app.inference as inf

    calls = []

    class _FakeSpray:
        def spray(self, *a, **k):
            calls.append((a, k))
            return True

    class _FakeFeedback:
        def trigger(self, *a, **k):
            return None

    old_spray, old_fb = inf.spray, inf.feedback
    inf.spray, inf.feedback = _FakeSpray(), _FakeFeedback()
    try:
        inf.set_auto_spray(False)
        inf._linkage('高风险', [{'chinese_name': '蚜虫'}])
        assert calls == [], f'总闸关掉后仍然喷了：{calls}'
        inf.set_auto_spray(True)
        inf._linkage('高风险', [{'chinese_name': '蚜虫'}])
        assert calls, '总闸打开后应该下发喷淋'
    finally:
        inf.spray, inf.feedback = old_spray, old_fb
        inf.set_auto_spray(True)


@test_case
def test_phone_live_auto_spray_defaults_off():
    """方案二/第三套都要求人工确认：手机实时默认不自动喷。"""
    text = (ROOT / 'config' / 'configs.yaml').read_text(encoding='utf-8')
    assert 'live_auto_spray: false' in text, 'PHONE.live_auto_spray 默认必须是 false'
    src = (ROOT / 'api_server.py').read_text(encoding='utf-8')
    assert '_phone_auto_spray' in src and 'live_auto_spray' in src
    assert 'if _phone_auto_spray and risk_level' in src, '手机实时联动必须受开关控制'


@test_case
def test_launch_gui_refuses_when_script_missing():
    """/api/demo/launch_gui 的失败路径要可读，不能抛 500。"""
    src = (ROOT / 'api_server.py').read_text(encoding='utf-8')
    assert "找不到 {script}" in src or '找不到' in src
    assert 'gui_launch.log' in src, 'GUI 启动失败要留下日志路径'
    assert 'CREATE_NEW_PROCESS_GROUP' in src, 'GUI 应是独立进程，服务重启不影响它'
