"""喷淋执行控制器：风险 → 片区/分组喷淋时长映射，下发指令到喷洒设备。

国赛形态C「物理反馈/外部设备联动」的喷淋执行链路，支持三种传输方式：

    serial : Server --USB串口--> 网关 ESP32 --ESP-NOW--> 节点（现状，含一根 USB 线）
    http   : Server --HTTP--> 目标设备（方案甲：节点直连 WiFi；方案丙：无线网关转发）
    mqtt   : Server --MQTT--> 目标设备（方案乙/丙，需 broker）

「田间无线」推荐 **方案丙**：transport=http，http_targets 只配一项 ``group='gateway'``，
全部指令发给无线网关，网关再经 ESP-NOW 广播/单播给节点——**节点固件（ESP32/src/espnow_node）零改动**。

与 feedback.Feedback 同一风格：异步执行、失败静默、不阻塞推理主流程。
链路不可用（无串口/无目标地址/broker 未连）时静默降级，仅推理不做喷淋。
"""
import json
import threading
import time

try:
    import serial
except ImportError:
    serial = None

try:
    import requests
except ImportError:
    requests = None


def _lan_session():
    """节点都在局域网里：发指令绝不能走系统代理。

    requests 默认读 Windows 注册表里的系统代理（trust_env）。现场机器上那个代理早已失效
    （CLAUDE.md 记录过 127.0.0.1:65532），走代理时 POST 到节点会直接失败，
    而 curl 联调时没有这个问题，所以之前一直没暴露。
    """
    if requests is None:
        return None
    sess = requests.Session()
    sess.trust_env = False
    return sess


class SprayController:
    """喷淋控制器：按风险等级/手动触发下发指令，支持 serial / http / mqtt 三种传输。"""

    def __init__(self, serial_port=None, baud=115200, enabled=True,
                 risk_map=None, min_interval=3.0,
                 transport='serial', http_targets=None, http_timeout=1.0,
                 mqtt=None, max_duration=30, nodes=None):
        self.enabled = bool(enabled)
        self.serial_port = serial_port
        self.baud = int(baud or 115200)
        self.risk_map = risk_map or {}
        self.min_interval = float(min_interval)
        self.max_duration = int(max_duration or 30)

        # ---------- 传输方式 ----------
        self.transport = str(transport or 'serial').lower()
        if self.transport not in ('serial', 'http', 'mqtt'):
            self.transport = 'serial'

        # http 目标表：{group: url}；group='gateway' 表示方案丙的无线网关（承接全部指令）
        self.http_targets = {}
        for item in (http_targets or []):
            try:
                g = str(item.get('group', '') or '').strip()
                u = str(item.get('url', '') or '').strip()
            except AttributeError:
                continue
            if g and u:
                self.http_targets[g] = u
        self.http_timeout = float(http_timeout or 1.0)

        # mqtt 配置
        mqtt = mqtt or {}
        self.mqtt_host = str(mqtt.get('host', '') or '')
        self.mqtt_port = int(mqtt.get('port', 1883) or 1883)
        self.mqtt_topic = str(mqtt.get('topic', 'cropguard/spray') or 'cropguard/spray')
        self.mqtt_qos = int(mqtt.get('qos', 0) or 0)

        self._serial = None
        self._mqtt = None
        self._lock = threading.Lock()
        # 自动喷淋节流时间戳，按分组独立计时（多片区不会互相压制）
        self._last_auto_spray = {}
        # 喷头节点登记表里的分组（serial/mqtt 形态下唯一能知道"有哪些片区"的地方）
        self.node_groups = set()
        self.node_names = {}             # 分组 -> 片区名（界面显示用）
        for n in (nodes or []):
            try:
                g = str(n.get('group', '') or '').strip()
                name = str(n.get('name', '') or '').strip()
            except AttributeError:
                continue
            if g:
                self.node_groups.add(g)
                if name:
                    self.node_names.setdefault(g, name)

        self._http = _lan_session()
        self._probe_cache = {'ts': 0.0, 'nodes': []}
        self._probe_lock = threading.Lock()

        if self.enabled:
            self._init_transport()

    # ==================== 初始化 ====================

    def _init_transport(self):
        """按传输方式初始化；失败静默（链路不可用时降级为纯推理）。"""
        if self.transport == 'serial':
            self._init_serial()
        elif self.transport == 'mqtt':
            self._init_mqtt()
        # http 无需预先连接，调用时直接 POST

    def _init_serial(self):
        """打开网关串口，失败静默（无网关时降级为纯推理）。"""
        if serial is None or not self.serial_port:
            return
        try:
            self._serial = serial.Serial(self.serial_port, self.baud, timeout=0.1)
        except Exception:
            self._serial = None

    def _init_mqtt(self):
        """初始化 MQTT 客户端（需 paho-mqtt）；失败静默。"""
        if not self.mqtt_host:
            return
        try:
            import paho.mqtt.client as mqtt_client
        except ImportError:
            return
        try:
            client = mqtt_client.Client()
            client.connect(self.mqtt_host, self.mqtt_port, keepalive=30)
            client.loop_start()
            self._mqtt = client
        except Exception:
            self._mqtt = None

    @property
    def available(self):
        """链路是否可用（按传输方式判定）。"""
        if not self.enabled:
            return False
        if self.transport == 'serial':
            return bool(self._serial and self._serial.is_open)
        if self.transport == 'http':
            return bool(self.http_targets) and requests is not None
        if self.transport == 'mqtt':
            return bool(self._mqtt)
        return False

    @property
    def allowed_groups(self):
        """可下发的分组白名单（聊天/语音指令解析用，跨传输形态）。

        http 直连：http_targets 里的分组；配了 'gateway' 转发时节点登记表也有效；
        serial/mqtt：只认 nodes 登记表里的分组。'gateway' 是转发通道不算片区。
        """
        groups = set(self.http_targets.keys()) | set(self.node_groups)
        groups.discard('gateway')
        groups.add('all')
        return groups

    # ==================== 下发 ====================

    def _targets_for(self, group):
        """按分组取出 http 目标地址列表。

        方案丙：只配了 'gateway' 时，所有指令都发网关，由网关 ESP-NOW 转发。
        方案甲：按 group 精确寻址，实现片区间故障隔离。
        """
        group = group or 'all'
        if group in self.http_targets:
            return [self.http_targets[group]]
        if 'gateway' in self.http_targets:
            return [self.http_targets['gateway']]
        if group == 'all':
            return list(self.http_targets.values())
        return []

    def _stop_url(self, url):
        """把节点 /spray 地址换成 /stop（固件 http_node 提供 /stop）。"""
        u = str(url or '')
        if u.endswith('/spray'):
            return u[:-len('/spray')] + '/stop'
        return u.rstrip('/') + '/stop'

    def _write(self, command: dict) -> bool:
        """写一条指令到目标设备（按传输方式分派）。"""
        return self._deliver(command)[0]

    def _deliver(self, command: dict, url_of=None):
        """下发并返回 (是否送达, 失败原因)。

        送达口径：serial 写进串口、mqtt 发布成功、http 至少一个节点回 2xx。
        url_of: http 下把 /spray 地址换成别的端点（停止用 /stop）。
        """
        if not self.available:
            return False, '喷淋链路未配置'
        try:
            if self.transport == 'serial':
                line = json.dumps(command, ensure_ascii=False) + '\n'
                with self._lock:
                    self._serial.write(line.encode('utf-8'))
                return True, ''

            if self.transport == 'http':
                urls = self._targets_for(command.get('group'))
                if not urls:
                    return False, f"分组 {command.get('group')} 没有配置节点地址"
                ok, errors = False, []
                for url in urls:
                    target = url_of(url) if url_of else url
                    try:
                        resp = self._http.post(target, json=command, timeout=self.http_timeout)
                        if 200 <= resp.status_code < 300:
                            ok = True
                        else:
                            errors.append(f'{target} 返回 {resp.status_code}')
                    except Exception as exc:
                        errors.append(f'{target} {_reason(exc)}')
                return ok, '' if ok else '；'.join(errors)

            if self.transport == 'mqtt':
                payload = json.dumps(command, ensure_ascii=False)
                info = self._mqtt.publish(self.mqtt_topic, payload, qos=self.mqtt_qos)
                return (info is not None), ('' if info is not None else 'MQTT 发布失败')
        except Exception as exc:
            return False, _reason(exc)
        return False, '未知传输方式'

    def _send_async(self, command: dict):
        """后台线程发指令，不阻塞推理主流程。"""
        threading.Thread(target=self._write, args=(command,), daemon=True).start()

    # ==================== 对外接口 ====================

    def spray(self, risk_level, detected_names=None, group_override=None):
        """按风险等级自动喷淋。

        group_override: 指定片区分组（如 'g2'），用于"多路定点监测 · 按片区定向喷淋"；
                        None 时使用 risk_map 中该风险等级配置的 group。
        返回 True 表示已下发指令；低/无风险、链路不可用、节流命中时返回 False。
        """
        if not self.enabled or not self.available:
            return False

        mapping = self.risk_map.get(risk_level)
        if not mapping:
            return False

        group = group_override or mapping.get('group')
        duration = mapping.get('duration', 0)
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            return False  # 配置写坏不喷，也不打断检测主循环
        # 安全钳制：与手动喷淋同一上限（雾化片单次通电必须 ≤ max_duration）
        if duration > self.max_duration:
            duration = self.max_duration
        if not group or duration <= 0:
            return False

        # 自动喷淋节流：按分组独立计时，避免多片区互相压制
        now = time.time()
        if now - self._last_auto_spray.get(group, 0.0) < self.min_interval:
            return False
        self._last_auto_spray[group] = now

        self._send_async({'group': group, 'duration': int(duration)})
        return True

    def manual_spray(self, group='all', duration=2, wait=False):
        """手动喷淋（Client 按钮），不受自动节流限制。

        group: 'all' / 'g1' / 'g2' ...（对应片区A/片区B）；duration: 秒。
        非数字或 <=0 一律拒绝（调用方传 0 的语义是"别喷"，绝不能默认执行）。
        wait=True：同步等节点应答，返回值表示**真的送达**（网页"已下发"提示据此给出）；
        wait=False：后台发送，返回值只表示"已受理"。
        """
        return self.manual_spray_detail(group, duration, wait=wait)[0]

    def manual_spray_detail(self, group='all', duration=2, wait=True):
        """同 manual_spray，额外返回失败原因：(ok, reason)。"""
        if not self.enabled or not self.available:
            return False, '喷淋链路未配置'
        group = group or 'all'
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            return False, '时长必须是整数秒'
        if duration <= 0:
            return False, '时长必须为正数'
        if duration > self.max_duration:
            duration = self.max_duration  # 安全上限，避免误触长时间喷水
        command = {'group': group, 'duration': duration}
        if wait:
            return self._deliver(command)
        self._send_async(command)
        return True, ''

    def stop_detail(self, group='all'):
        """同步停止并返回 (是否送达, 失败原因)。"""
        if not self.enabled or not self.available:
            return False, '喷淋链路未配置'
        group = group or 'all'
        if self.transport == 'http':
            return self._deliver({'group': group}, url_of=self._stop_url)
        # 串口/MQTT 协议：duration<=0 就是"立即停止"
        return self._deliver({'group': group, 'duration': 0})

    def stop(self, group='all'):
        """立即停止该分组的喷洒（http 节点走固件 /stop；串口/MQTT 发 duration=0 = 停止）。"""
        if not self.enabled or not self.available:
            return False
        group = group or 'all'
        if self.transport == 'http':
            urls = [self._stop_url(u) for u in self._targets_for(group)]
            if not urls:
                return False

            def _job():
                for url in urls:
                    try:
                        self._http.post(url, json={'group': group}, timeout=self.http_timeout)
                    except Exception:
                        continue
            threading.Thread(target=_job, daemon=True).start()
            return True
        # 串口/MQTT 协议：duration<=0 就是"立即停止"（espnow_node/http_node 固件
        # 均把 duration<=0 解释为 relay.stop()）。绝不能发 duration=1 —— 那是"再喷 1 秒"。
        self._send_async({'group': group, 'duration': 0})
        return True

    # ==================== 节点探活 ====================

    def probe_nodes(self, timeout=0.8, max_age=3.0):
        """并发探测每个 http 节点的 GET /status（固件 http_node 提供），带短缓存。

        返回 [{group, name, url, online, latency_ms, ip, rssi, spraying, count, error}]。
        非 http 传输返回空表（串口/MQTT 没有逐节点探活的通道）。
        """
        if self.transport != 'http' or self._http is None or not self.http_targets:
            return []
        with self._probe_lock:
            if time.time() - self._probe_cache['ts'] < max_age:
                return [dict(n) for n in self._probe_cache['nodes']]
        items = list(self.http_targets.items())
        out = [None] * len(items)

        def _one(i, group, url):
            base = url[:-len('/spray')] if url.endswith('/spray') else url.rstrip('/')
            row = {'group': group, 'name': self.node_names.get(group, ''), 'url': url,
                   'online': False, 'latency_ms': None}
            t0 = time.time()
            try:
                resp = self._http.get(base + '/status', timeout=timeout)
                row['latency_ms'] = int((time.time() - t0) * 1000)
                row['online'] = 200 <= resp.status_code < 300
                try:
                    data = resp.json()
                except ValueError:
                    data = {}
                for k in ('ip', 'rssi', 'spraying', 'count'):
                    if k in data:
                        row[k] = data[k]
                if data.get('name') and not row['name']:
                    row['name'] = str(data['name'])
                if not row['online']:
                    row['error'] = f'返回 {resp.status_code}'
            except Exception as exc:
                row['error'] = _reason(exc)
            out[i] = row

        threads = [threading.Thread(target=_one, args=(i, g, u), daemon=True)
                   for i, (g, u) in enumerate(items)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout + 0.5)
        nodes = [r for r in out if r is not None]
        with self._probe_lock:
            self._probe_cache = {'ts': time.time(), 'nodes': nodes}
        return [dict(n) for n in nodes]

    def close(self):
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
        if self._mqtt is not None:
            try:
                self._mqtt.loop_stop()
                self._mqtt.disconnect()
            except Exception:
                pass


def _reason(exc):
    """把 requests/串口异常翻成现场看得懂的一句话。"""
    name = type(exc).__name__
    if 'Timeout' in name:
        return '连接超时（节点没上电或不在同一网络）'
    if 'ConnectionError' in name or 'ConnectError' in name:
        return '无法连接（检查节点 IP 是否与串口打印一致）'
    return f'{name}: {str(exc)[:80]}'
