# -*- coding: utf-8 -*-
"""喷淋安全链路回归（不接硬件：拦截下发指令后断言内容）。

对应代码审查的高危/中危项：
* 自动喷淋必须经过 max_duration 钳制（雾化片单次通电硬上限）；
* stop() 在串口/MQTT 上必须发 duration=0（固件协议的"停止"），不能发 1（= 再喷 1 秒）；
* duration<=0 / 非数字一律拒绝，不能被默默改成"喷 2 秒"；
* 分组白名单跨 serial/http/mqtt 一致（spray.allowed_groups）。
"""
from _registry import test_case

from feedback.spray import SprayController


class _Capture(SprayController):
    """把下发动作截下来；available 恒真，模拟"链路已连上"。"""

    def __init__(self, **kw):
        kw.setdefault('enabled', False)       # 不去真开串口/HTTP
        super().__init__(**kw)
        self.enabled = True
        self.sent = []

    @property
    def available(self):
        return True

    def _send_async(self, command):
        self.sent.append(dict(command))


def _ctl(**kw):
    kw.setdefault('transport', 'serial')
    kw.setdefault('max_duration', 5)
    kw.setdefault('min_interval', 0)
    return _Capture(**kw)


@test_case
def test_auto_spray_is_clamped_to_max_duration():
    c = _ctl(risk_map={'高风险': {'group': 'g1', 'duration': 30}})
    assert c.spray('高风险', ['蚜虫']) is True
    assert c.sent == [{'group': 'g1', 'duration': 5}], c.sent


@test_case
def test_auto_spray_bad_duration_does_not_spray():
    c = _ctl(risk_map={'高风险': {'group': 'g1', 'duration': 'abc'}})
    assert c.spray('高风险', ['蚜虫']) is False
    assert c.sent == []


@test_case(0)
@test_case(-3)
@test_case('x')
@test_case(None)
def test_manual_spray_rejects_non_positive(duration):
    c = _ctl()
    assert c.manual_spray('g1', duration) is False
    assert c.sent == [], f'duration={duration!r} 不该下发任何指令: {c.sent}'


@test_case
def test_manual_spray_clamps():
    c = _ctl()
    assert c.manual_spray('g1', 100) is True
    assert c.sent == [{'group': 'g1', 'duration': 5}], c.sent


@test_case
def test_serial_stop_sends_zero_duration():
    c = _ctl()
    assert c.stop('g2') is True
    assert c.sent == [{'group': 'g2', 'duration': 0}], \
        f'串口 stop 必须发 duration=0（固件停止语义），实际 {c.sent}'


@test_case
def test_allowed_groups_cross_transport():
    serial = _ctl(nodes=[{'group': 'g1'}, {'group': 'g2'}])
    assert serial.allowed_groups == {'all', 'g1', 'g2'}, serial.allowed_groups
    http = _ctl(transport='http', http_targets=[{'group': 'g1', 'url': 'http://x/spray'},
                                                {'group': 'gateway', 'url': 'http://gw/spray'}])
    assert 'gateway' not in http.allowed_groups, '网关是转发通道，不是片区'
    assert http.allowed_groups == {'all', 'g1'}, http.allowed_groups


# ---------------- 送达口径：节点不在线时绝不能报"已下发" ----------------
def _closed_port_url():
    """拿一个本机确定没人监听的端口（连接会被立即拒绝，测试不用等超时）。"""
    import socket
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return f'http://127.0.0.1:{port}/spray'


@test_case
def test_manual_spray_reports_undelivered_when_node_offline():
    c = SprayController(transport='http', max_duration=5, http_timeout=0.5,
                        http_targets=[{'group': 'g1', 'url': _closed_port_url()}],
                        nodes=[{'group': 'g1', 'name': '片区A'}])
    ok, reason = c.manual_spray_detail('g1', 2)
    assert ok is False, '节点不在线时同步下发必须返回 False（以前丢给后台线程就报成功）'
    assert reason, '失败要给出原因，页面据此提示'
    ok, _ = c.stop_detail('g1')
    assert ok is False


@test_case
def test_probe_nodes_marks_offline_node():
    c = SprayController(transport='http', http_timeout=0.5,
                        http_targets=[{'group': 'g1', 'url': _closed_port_url()}],
                        nodes=[{'group': 'g1', 'name': '片区A'}])
    nodes = c.probe_nodes(timeout=0.5)
    assert len(nodes) == 1 and nodes[0]['online'] is False, nodes
    assert nodes[0]['name'] == '片区A' and nodes[0].get('error'), nodes


@test_case
def test_node_requests_ignore_system_proxy():
    c = SprayController(transport='http', http_targets=[{'group': 'g1', 'url': 'http://10.0.0.9/spray'}])
    assert c._http is not None and c._http.trust_env is False, '局域网节点不能走系统代理'
