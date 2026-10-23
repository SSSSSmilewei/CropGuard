# -*- coding: utf-8 -*-
"""现场改喷淋节点地址：``/api/spray/targets`` 背后的逻辑 + 覆盖文件。

现场痛点（2026-10-23 第一套演示）：``/demo`` 自检里「喷淋节点至少 1 个在线」是 ❌。
原因不是"程序没接喷淋"——transport/http_targets/探活/下发全都在——而是
``configs.yaml`` 里还是仓库的**占位地址**（172.23.153.231，且 g1/g2 写成同一台），
而节点的真实 IP 只有**节点串口**知道（热点 DHCP 每次都可能变）。

改 YAML 要重启服务，比赛现场太危险，所以：指挥台热改地址表 → 立刻重新探活 →
落到 ``config/spray_targets.local.json``（下次启动由 app.state 读回来），不碰 YAML。

这里锁住四条底线：
1. 地址不合法就**拒绝**，绝不能把人送到错误地址上（宁可报错，不许静默降级）；
2. 认不出的协议按 default_protocol，不偷偷当 mist；
3. 改完必须真的能连上（用本地假节点验证"服务器 → 节点"这条链路）；
4. 覆盖文件坏了不能拖垮启动（返回空表，退回 YAML）。
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from _registry import test_case

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feedback.spray import SprayController          # noqa: E402
from app import spray_targets as overlay            # noqa: E402


def _controller():
    return SprayController(
        transport='http',
        http_targets=[{'group': 'g1', 'url': 'http://127.0.0.1:1', 'protocol': 'mist'}],
        default_protocol='json',
        nodes=[{'group': 'g1', 'name': '片区A'}, {'group': 'g2', 'name': '片区B'}],
    )


class _SketchNode:
    """按现场那份 sketch_oct12a.ino 的行为起一个假节点。

    关键：**没有 /status 路由**（只有 / /start /startDirect /stop），
    /start 里还有 delay(1000)+模拟按键 200ms，所以 1.2 秒才回包。
    """

    def __init__(self, start_delay=0.0):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.paths = []
        node = self
        delay_sec = start_delay

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                from urllib.parse import urlparse
                path = urlparse(self.path).path
                node.paths.append(self.path)
                if path in ('/start', '/startDirect'):
                    if delay_sec:
                        import time as _t
                        _t.sleep(delay_sec)      # 固件的 delay(1000)+按键脉冲
                    body = '<h3>✅定时雾化已启动</h3>'
                elif path == '/stop':
                    body = '<h3>❌雾化已关闭</h3>'
                elif path == '/':
                    body = '<p id="status">❌空闲，等待启动</p>'
                else:
                    self.send_response(404)      # 真固件也没有 /status
                    self.end_headers()
                    return
                raw = body.encode('utf-8')
                self.send_response(200)
                # ⚠️ 真固件是 server.send(200, "text/html", page) —— **不带 charset**。
                # Content-Type 没有 charset 时 requests 的 resp.text 按 ISO-8859-1 解码，
                # 中文全变乱码，"空闲/正在雾化"就解析不出来 → 必须显式 decode('utf-8')。
                self.send_header('Content-Type', 'text/html')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self._srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = self._srv.server_address[1]
        self.url = f'http://127.0.0.1:{self.port}'
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._t.start()

    def close(self):
        self._srv.shutdown()


@test_case
def test_probe_works_with_real_sketch_that_has_no_status_route():
    """现场 ❌ 的真因：手写 sketch 没有 /status，探活打 /status 会 404 → 在线节点被判离线。"""
    node = _SketchNode()
    try:
        sp = _controller()
        sp.set_http_targets([{'group': 'g1', 'url': node.url, 'protocol': 'mist'}])
        rows = sp.probe_nodes(max_age=0)
        assert len(rows) == 1, rows
        assert rows[0]['online'] is True, f'节点在线却被判离线：{rows[0]}'
        assert rows[0]['protocol'] == 'mist'
        assert rows[0]['mode'] == 'idle', rows[0]       # 状态页是"空闲"
        assert rows[0]['spraying'] is False
        assert any(p == '/' for p in node.paths), f'应该打根路径状态页，实际：{node.paths}'
    finally:
        node.close()


@test_case
def test_mist_start_tolerates_firmware_blocking_1200ms():
    """固件 /start 要 1.2 秒才回包；超时用 1.0 秒会在"其实已经喷了"时报失败。"""
    node = _SketchNode(start_delay=1.2)
    try:
        sp = _controller()
        sp.set_http_targets([{'group': 'g1', 'url': node.url, 'protocol': 'mist'}])
        res = sp.mist_start(2, 'g1')
        assert res['success'] is True, res
        assert any('/start?time=2' in p for p in node.paths), node.paths
    finally:
        node.close()


@test_case
def test_bad_address_is_rejected_and_table_untouched():
    sp = _controller()
    before = dict(sp.http_targets)
    applied, errors = sp.set_http_targets([
        {'group': 'g1', 'url': '10.130.161.50'},          # 少了 http://
        {'group': '', 'url': 'http://10.0.0.9'},          # 没写分组
    ])
    assert applied == [], f'非法地址不该生效：{applied}'
    assert errors, '必须说明为什么被拒'
    assert sp.http_targets == before, '全部非法时不能把原地址表改坏'


@test_case
def test_good_addresses_apply_and_take_effect():
    sp = _controller()
    applied, errors = sp.set_http_targets([
        {'group': 'g1', 'url': 'http://10.0.0.11', 'protocol': 'mist'},
        {'group': 'g2', 'url': 'http://10.0.0.12', 'protocol': 'json'},
    ])
    assert errors == [], errors
    assert [t['group'] for t in applied] == ['g1', 'g2']
    assert sp.http_targets == {'g1': 'http://10.0.0.11', 'g2': 'http://10.0.0.12'}
    assert sp.protocol_of('g1') == 'mist' and sp.protocol_of('g2') == 'json'
    assert {'g1', 'g2', 'all'} <= set(sp.allowed_groups)
    assert sp._probe_cache['ts'] == 0.0, '改完地址必须清探活缓存（否则页面还显示旧状态）'
    rows = sp.http_target_rows()
    assert [r['protocol'] for r in rows] == ['mist', 'json']


@test_case
def test_unknown_protocol_falls_back_to_default():
    sp = _controller()
    applied, _ = sp.set_http_targets([{'group': 'g1', 'url': 'http://10.0.0.13', 'protocol': 'mqtt-ish'}])
    assert applied and applied[0]['protocol'] == 'json', '认不出的协议按 default_protocol'


@test_case
def test_probe_nodes_really_reaches_node():
    """起一个本地假节点（行为同 mist 固件），确认探活真能连上。"""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'<html>IDLE</html>'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        sp = _controller()
        sp.set_http_targets([{'group': 'g1', 'url': f'http://127.0.0.1:{port}', 'protocol': 'mist'}])
        nodes = sp.probe_nodes(max_age=0)
        assert len(nodes) == 1, nodes
        assert nodes[0]['online'] is True, f'假节点在线却没判出来：{nodes[0]}'
        assert nodes[0]['name'] == '片区A', '节点名要能显示（现场靠它认片区）'
    finally:
        srv.shutdown()


@test_case
def test_overlay_roundtrip_and_broken_file():
    # 不用 tmp_path：本机沙箱下系统临时目录可能不可写；output/ 是仓库内可写且已 gitignore
    import os
    import shutil
    tmp = os.path.join(str(ROOT), 'output', '_test_spray_targets')
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    old = overlay.PATH
    try:
        overlay.PATH = os.path.join(tmp, 'spray_targets.local.json')
        assert overlay.load() == [], '文件不存在时返回空表，不能抛'
        overlay.save([{'group': 'g1', 'url': 'http://10.0.0.21', 'protocol': 'mist'},
                      {'group': 'g2', 'url': 'http://10.0.0.22', 'protocol': 'mist'}])
        assert overlay.exists()
        rows = overlay.load()
        assert [r['group'] for r in rows] == ['g1', 'g2']
        assert rows[0]['url'] == 'http://10.0.0.21'

        overlay.PATH = os.path.join(tmp, 'broken.json')
        with open(overlay.PATH, 'w', encoding='utf-8') as f:
            f.write('{ 不是 json')
        assert overlay.load() == [], '坏文件必须退回 YAML，不能让服务起不来'
    finally:
        overlay.PATH = old
        shutil.rmtree(tmp, ignore_errors=True)
