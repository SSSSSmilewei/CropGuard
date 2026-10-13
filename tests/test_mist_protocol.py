# -*- coding: utf-8 -*-
"""mist 协议适配测试：让手机页能驱动手写 sketch（sketch_oct12a.ino）。

被测对象是 feedback/spray.py 里新增的 http 子协议：

    'mist' : GET /start?time=N（定时）/ GET /startDirect（持续，不自停）/ GET /stop

这里用**真的 loopback HTTP 服务器**复刻 sketch 的端点与脾气（含"永远回 200"），
而不是打桩 requests —— 因为本项目踩过的坑之一恰恰就是"只看状态码判成败"：
sketch 在"雾化正在运行中，请先关闭！"时也回 200，必须读响应体才知道没执行。

另外覆盖两条安全线：
* 定时时长一律按 max_duration 钳制（雾化片怕连续通电）；
* 持续模式（/startDirect）固件不会自停 —— 服务器兜底计时器必须到点自动 /stop，
  且人工停止 / 后续定时喷雾都要能撤掉这个计时器（否则会把新的一次喷雾掐断）。
"""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from _registry import requires, test_case

from feedback.spray import SprayController


# ==================== 假 ESP32 节点（复刻 sketch_oct12a.ino） ====================
class _FakeNode:
    """假节点：端点、响应文案、以及"永远回 200"的行为都照 sketch 抄。"""

    def __init__(self, running=False, mode='timed', remain=None):
        self.state = {'running': running, 'mode': mode if running else 'idle', 'remain': remain}
        self.requests = []          # [{'method','path','body'}]
        self.lock = threading.Lock()
        self._handler = self._make_handler()
        self.httpd = None
        self.thread = None
        self.url = ''

    # ---------- 响应文案 ----------
    @staticmethod
    def status_page(st):
        """状态页：按钮文案里也有"定时开启雾化/持续喷雾"，用来验证解析不会认错。"""
        if st['running']:
            if st['mode'] == 'direct':
                text = '✅【持续模式】正在雾化，不会自动停止，请手动关闭'
            else:
                text = f"✅【定时模式】正在雾化，剩余：{st.get('remain') or 0} 秒"
        else:
            text = '❌空闲，等待启动'
        return ('<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body>'
                '<h2>ESP32 雾化控制器</h2>'
                '<button onclick="startTimer()">⏱️ 定时开启雾化</button>'
                '<button>▶️ 立即开始雾化（持续喷雾，不会自动停）</button>'
                '<button>⏹️ 立即关闭雾化</button>'
                f'<p id="status">{text}</p></body></html>')

    # ---------- 记录 ----------
    def _record(self, method, path, body=''):
        with self.lock:
            self.requests.append({'method': method, 'path': path, 'body': body})

    def paths(self):
        with self.lock:
            return [r['path'] for r in self.requests]

    def methods(self):
        with self.lock:
            return [r['method'] for r in self.requests]

    def bodies(self):
        with self.lock:
            return [r['body'] for r in self.requests]

    # ---------- HTTP 处理 ----------
    def _make_handler(self):
        node = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):        # 静音，别把测试输出刷满
                pass

            def _send(self, body, code=200):
                raw = body.encode('utf-8')
                self.send_response(code)
                # 故意**不带 charset**（与 sketch 的 server.send(200,"text/html",page) 一致），
                # 逼适配层自己按 UTF-8 解码，而不是让 requests 去猜编码。
                self.send_header('Content-Type', 'text/html')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                parts = urlsplit(self.path)
                node._record('GET', self.path)
                with node.lock:
                    st = dict(node.state)
                if parts.path == '/':
                    self._send(node.status_page(st))
                elif parts.path == '/start':
                    if st['running']:
                        self._send('<h3>雾化正在运行中，请先关闭！</h3><a href="/">返回</a>')
                        return
                    sec = int((parse_qs(parts.query).get('time') or ['30'])[0])
                    with node.lock:
                        node.state.update(running=True, mode='timed', remain=sec)
                    self._send('<h3>✅定时雾化已启动</h3><a href="/">返回</a>')
                elif parts.path == '/startDirect':
                    if st['running']:
                        self._send('<h3>雾化正在运行中，请先关闭！</h3><a href="/">返回</a>')
                        return
                    with node.lock:
                        node.state.update(running=True, mode='direct', remain=None)
                    self._send('<h3>✅持续雾化已开启，需要手动点关闭！</h3><a href="/">返回</a>')
                elif parts.path == '/stop':
                    with node.lock:
                        node.state.update(running=False, mode='idle', remain=None)
                    self._send('<h3>❌雾化已关闭</h3><a href="/">返回</a>')
                else:
                    self._send('{"ok":false,"err":"not found"}', code=404)

            def do_POST(self):
                length = int(self.headers.get('Content-Length') or 0)
                body = self.rfile.read(length).decode('utf-8') if length else ''
                node._record('POST', self.path, body)
                if urlsplit(self.path).path == '/spray':      # 项目固件的 json 协议
                    with node.lock:
                        node.state.update(running=True, mode='timed', remain=None)
                    self._send('{"ok":true}')
                elif urlsplit(self.path).path == '/stop':
                    with node.lock:
                        node.state.update(running=False, mode='idle', remain=None)
                    self._send('{"ok":true,"stopped":true}')
                else:
                    self._send('{"ok":false,"err":"not found"}', code=404)

        return Handler

    # ---------- 生命周期 ----------
    def __enter__(self):
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), self._handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = f'http://127.0.0.1:{self.port}'
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        finally:
            self.thread.join(timeout=3)
        return False


def _mist_ctl(node, **kw):
    """指向假节点的 mist 协议控制器。"""
    kw.setdefault('max_duration', 5)
    kw.setdefault('http_timeout', 2.0)
    kw.setdefault('status_timeout', 2.0)
    return SprayController(transport='http', http_targets=[
        {'group': 'g1', 'url': node.url, 'protocol': 'mist'}], **kw)


def _closed_port():
    """取一个确定没人监听的端口（比写死 9 号端口稳）。"""
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ==================== 地址翻译（纯逻辑，不需要网络） ====================
@test_case('http://192.168.43.61', 'http://192.168.43.61')
@test_case('http://192.168.43.61/', 'http://192.168.43.61')
@test_case('http://192.168.43.61/spray', 'http://192.168.43.61')
@test_case('http://192.168.43.61/start', 'http://192.168.43.61')
@test_case('http://192.168.43.61/startDirect', 'http://192.168.43.61')
def test_base_url_normalizes(url, want):
    """配置里写根地址、带 /spray、带尾斜杠都要能认（现场手改配置很容易写成任一种）。"""
    assert SprayController._base_url(url) == want, url


@test_case({'group': 'g1', 'duration': 3}, '/start?time=3')
@test_case({'group': 'g1', 'duration': '2'}, '/start?time=2')
@test_case({'group': 'g1', 'action': 'direct'}, '/startDirect')
@test_case({'group': 'g1', 'action': 'stop'}, '/stop')
@test_case({'group': 'g1', 'duration': 0}, '/stop')
@test_case({'group': 'g1', 'duration': None}, '/stop')
def test_mist_url_mapping(command, want):
    """一条通用指令 → sketch 的 GET 地址。"""
    ctl = SprayController(transport='http', http_targets=[])
    assert ctl._mist_url_for('http://node', command) == 'http://node' + want, command


@test_case
def test_status_parser_reads_real_sketch_page():
    """解析真实状态页文案：只能认『定时模式/持续模式/空闲』，不能被按钮文案骗到。"""
    timed = ('<h2>ESP32 雾化控制器</h2><button>⏱️ 定时开启雾化</button>'
             '<p id="status">✅【定时模式】正在雾化，剩余：7 秒</p>')
    r = SprayController._parse_mist_status(timed)
    assert r == {'running': True, 'mode': 'timed', 'remain': 7}, r

    direct = ('<button>▶️ 立即开始雾化（持续喷雾，不会自动停）</button>'
              '<p id="status">✅【持续模式】正在雾化，不会自动停止，请手动关闭</p>')
    r = SprayController._parse_mist_status(direct)
    assert r['running'] is True and r['mode'] == 'direct' and r['remain'] is None, r

    idle = ('<button>定时开启雾化</button><button>立即开始雾化（持续喷雾）</button>'
            '<p id="status">❌空闲，等待启动</p>')
    r = SprayController._parse_mist_status(idle)
    assert r['running'] is False and r['mode'] == 'idle', r


# ==================== 真 HTTP：定时喷雾 ====================
@test_case
def test_mist_start_uses_get_start_with_time():
    """定时喷雾必须用 GET /start?time=N —— sketch 只注册了这个（POST 会 404）。"""
    requires('requests')
    with _FakeNode() as node:
        ctl = _mist_ctl(node)
        res = ctl.mist_start(3, 'g1')
        assert res['success'] is True, res
        assert node.methods() == ['GET'], node.methods()
        assert node.paths() == ['/start?time=3'], node.paths()
        assert node.state['running'] is True and node.state['remain'] == 3


@test_case
def test_mist_start_clamps_duration():
    """要 60 秒也只能喷 max_duration（雾化片怕连续通电）。"""
    requires('requests')
    with _FakeNode() as node:
        ctl = _mist_ctl(node, max_duration=5)
        res = ctl.mist_start(60, 'g1')
        assert res['success'] and res['duration'] == 5 and res['requested'] == 60, res
        assert res['clamped'] is True and res['max_duration'] == 5, res
        assert node.paths() == ['/start?time=5'], node.paths()


@test_case
def test_mist_busy_is_reported_as_failure_despite_http_200():
    """关键坑：节点"正在喷雾中"也回 200，绝不能当成功。"""
    requires('requests')
    with _FakeNode(running=True, mode='timed', remain=10) as node:
        ctl = _mist_ctl(node)
        res = ctl.mist_start(3, 'g1')
        assert res['success'] is False, res
        assert '正在' in (res['error'] or ''), res
        assert node.state['remain'] == 10, '被拒绝时不该改动节点状态'


@test_case
def test_mist_unreachable_node_reports_reason():
    """节点不在线时必须给出可读原因（现场排查靠它），不能静默成功。"""
    requires('requests')
    ctl = SprayController(transport='http', http_timeout=1.0, status_timeout=1.0,
                          http_targets=[{'group': 'g1',
                                         'url': f'http://127.0.0.1:{_closed_port()}',
                                         'protocol': 'mist'}])
    res = ctl.mist_start(3, 'g1')
    assert res['success'] is False, res
    assert res['error'], res
    st = ctl.mist_status('g1')
    assert st['reachable'] is False and st['nodes'][0]['error'], st
    assert ctl.mist_stop('g1')['success'] is False


# ==================== 真 HTTP：停止 / 持续模式兜底 ====================
@test_case
def test_mist_stop_hits_get_stop():
    requires('requests')
    with _FakeNode(running=True, mode='timed', remain=30) as node:
        ctl = _mist_ctl(node)
        res = ctl.mist_stop('g1')
        assert res['success'] is True, res
        assert node.paths() == ['/stop'], node.paths()
        assert node.state['running'] is False


@test_case
def test_mist_direct_arms_watchdog_and_auto_stops():
    """持续喷雾（/startDirect）不会自停 —— 兜底计时器到点必须自动 /stop。"""
    requires('requests')
    with _FakeNode() as node:
        ctl = _mist_ctl(node, direct_max_sec=1)
        res = ctl.mist_start_direct('g1')
        assert res['success'] and res['direct_max_sec'] == 1, res
        assert node.paths() == ['/startDirect'], node.paths()
        node_st = ctl.mist_status('g1')['nodes'][0]
        assert node_st['reachable'] and node_st['mode'] == 'direct', node_st
        assert node_st['direct_remaining'] is not None, node_st

        deadline = time.time() + 8
        while time.time() < deadline and '/stop' not in node.paths():
            time.sleep(0.1)
        assert '/stop' in node.paths(), node.paths()
        assert node.state['running'] is False, node.state
        assert ctl.mist_status('g1')['nodes'][0]['direct_remaining'] is None


@test_case
def test_manual_stop_cancels_watchdog():
    """人工停止后兜底计时器必须撤销，否则到点会多发一条 /stop。"""
    requires('requests')
    with _FakeNode() as node:
        ctl = _mist_ctl(node, direct_max_sec=1)
        assert ctl.mist_start_direct('g1')['success']
        assert ctl.mist_stop('g1')['success']
        assert node.paths().count('/stop') == 1, node.paths()
        time.sleep(1.8)
        assert node.paths().count('/stop') == 1, f'兜底计时器没被撤销: {node.paths()}'
        assert node.state['running'] is False


@test_case
def test_timed_start_cancels_pending_watchdog():
    """持续模式 → 停止 → 定时喷雾：上一个会话的兜底计时器不能把这次喷掐断。"""
    requires('requests')
    with _FakeNode() as node:
        ctl = _mist_ctl(node, direct_max_sec=1)
        assert ctl.mist_start_direct('g1')['success']
        assert ctl.mist_stop('g1')['success']
        assert ctl.mist_start(3, 'g1')['success']
        time.sleep(1.8)
        assert node.paths().count('/stop') == 1, f'多出一条 /stop: {node.paths()}'
        assert node.state['running'] is True and node.state['remain'] == 3, node.state


@test_case
def test_direct_refused_on_json_only_target():
    """持续喷雾只对手写 sketch 有意义，纯 json 目标要给明确拒绝而不是假装成功。"""
    requires('requests')
    with _FakeNode() as node:
        ctl = SprayController(transport='http', http_timeout=2.0, http_targets=[
            {'group': 'g1', 'url': node.url + '/spray', 'protocol': 'json'}])
        res = ctl.mist_start_direct('g1')
        assert res['success'] is False and 'mist' in (res['error'] or ''), res
        assert node.requests == [], '被拒绝时不该打扰节点'


# ==================== 回归：json 协议（项目固件）原样可用 ====================
@test_case
def test_json_protocol_still_posts_spray():
    """加了 mist 协议之后，项目固件的 POST /spray 路径不能被改坏。"""
    requires('requests')
    with _FakeNode() as node:
        ctl = SprayController(transport='http', http_timeout=2.0, max_duration=5,
                              http_targets=[{'group': 'g1', 'url': node.url + '/spray',
                                             'protocol': 'json'}])
        ok, err = ctl._write_detail({'group': 'g1', 'duration': 2})
        assert ok is True, err
        assert node.methods() == ['POST'] and node.paths() == ['/spray'], node.requests
        assert json.loads(node.bodies()[0])['duration'] == 2, node.bodies()
        ok, err = ctl._stop_now('g1')
        assert ok is True, err
        assert node.paths()[-1] == '/stop', node.paths()


@test_case
def test_default_protocol_is_json_when_unspecified():
    """老配置（target 里没有 protocol 字段）必须继续按项目固件的 json 协议走。"""
    ctl = SprayController(transport='http', http_targets=[
        {'group': 'g1', 'url': 'http://192.168.43.61/spray'}])
    assert ctl.protocol_of('g1') == 'json', ctl.target_protocols
    assert ctl.mist_targets() == [], ctl.mist_targets()
    ctl2 = SprayController(transport='http', default_protocol='mist', http_targets=[
        {'group': 'g1', 'url': 'http://192.168.43.61'}])
    assert ctl2.protocol_of('g1') == 'mist'
    assert ctl2.mist_targets() == [{'group': 'g1', 'url': 'http://192.168.43.61',
                                    'protocol': 'mist'}], ctl2.mist_targets()


# ==================== 前端接线（渲染层，不需要服务器） ====================
@test_case
def test_mobile_page_renders_mist_card():
    """手机页必须带上雾化控制卡片，且占位符一个都不能漏。"""
    from serve import mobile as mobile_page
    html = mobile_page.render(host='192.168.43.10', http_port=8080, https_port=8443,
                              mist_url='http://192.168.43.61', mist_max_sec=5,
                              mist_direct_sec=300)
    assert '雾化控制' in html
    for endpoint in ('/api/mist/start', '/api/mist/direct', '/api/mist/stop', '/api/mist/status'):
        assert endpoint in html, endpoint
    assert '"http://192.168.43.61"' in html, '节点地址没注入'
    for leaked in ('__MIST_URL__', '__MIST_MAX_SEC__', '__MIST_DIRECT_SEC__',
                   '__HTTP_PORT__', '__HTTPS_PORT__', '__HTTPS_ENABLED__',
                   '__FRAME_INTERVAL__', '__UPLOAD_MAX_SIDE__'):
        assert leaked not in html, f'占位符没替换: {leaked}'


@test_case
def test_mobile_page_without_mist_node_still_renders():
    """没配 mist 节点时页面也要能打开（只显示"未配置"，不能报错）。"""
    from serve import mobile as mobile_page
    html = mobile_page.render(host='127.0.0.1', http_port=8080)
    assert '雾化控制' in html and '__MIST_URL__' not in html


@test_case
def test_api_server_declares_mist_endpoints():
    """api_server 的雾化端点是对外契约：删/改名要能被这条用例挡住。"""
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'api_server.py')
    with open(path, encoding='utf-8') as fh:
        src = fh.read()
    for decl in ('@app.get("/api/mist/status")', '@app.post("/api/mist/start")',
                 '@app.post("/api/mist/direct")', '@app.post("/api/mist/stop")'):
        assert decl in src, f'api_server.py 缺少 {decl}'
