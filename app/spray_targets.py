# -*- coding: utf-8 -*-
"""喷淋节点地址的「现场覆盖」文件（config/spray_targets.local.json）。

为什么需要它：节点 IP 是热点/路由器 DHCP 下发的，只印在**节点串口**上
（``WIFI_OK IP=x.x.x.x``），而 ``configs.yaml`` 里只能是占位地址。
比赛现场改 YAML 要重启服务——正在演示时非常危险，而且 YAML 里的注释
（各方案说明、协议差异）很容易被写坏。

所以：``/demo`` 指挥台的「节点地址」面板热改内存里的地址表（立即生效），
同时把结果落到这个文件；下次启动由 ``app.state`` 读回来覆盖 YAML。
只存真正需要的三个字段（group / url / protocol），不碰 configs.yaml。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, 'config', 'spray_targets.local.json')


def _clean(items):
    """只保留 group/url/protocol，顺便丢掉明显不完整的项（真正的校验在 spray 里）。"""
    out = []
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        group = str(item.get('group', '') or '').strip()
        url = str(item.get('url', '') or '').strip()
        if not group or not url:
            continue
        out.append({'group': group, 'url': url,
                    'protocol': str(item.get('protocol', '') or '').strip().lower()})
    return out


def load():
    """读覆盖文件；不存在 / 坏掉都返回 []（绝不能让演示起不来）。"""
    try:
        with open(PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as exc:
        print(f'[WARN] 喷淋覆盖文件读不出来（{type(exc).__name__}: {exc}）：只用 configs.yaml')
        return []
    items = data.get('targets') if isinstance(data, dict) else data
    return _clean(items)


def save(targets):
    """原子写（先写 .tmp 再 replace），失败抛异常由调用方转成 HTTP 提示。"""
    rows = _clean(targets)
    folder = os.path.dirname(PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'targets': rows}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)
    return PATH


def exists():
    return os.path.isfile(PATH)
