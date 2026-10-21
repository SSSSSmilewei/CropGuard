# -*- coding: utf-8 -*-
"""构建产物自洽性检查：index.html 引用的资源都要存在、chunk 间的相对 import 都要能找到。"""
import os
import re

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'web', 'dist')
idx = open(os.path.join(D, 'index.html'), encoding='utf-8').read()
refs = re.findall(r'(?:src|href)="([^"]+)"', idx)
missing = [r for r in refs if not os.path.isfile(os.path.join(D, r.lstrip('/')))]
print('index refs:', refs)
print('missing:', missing)

bad = []
n = 0
assets = os.path.join(D, 'assets')
for root, _, files in os.walk(assets):
    for f in files:
        if not f.endswith('.js'):
            continue
        n += 1
        text = open(os.path.join(root, f), encoding='utf-8', errors='replace').read()
        for m in re.findall(r'from"(\./[^"]+\.js)"', text):
            p = os.path.normpath(os.path.join(root, m))
            if not os.path.isfile(p):
                bad.append((f, m))
print('js files:', n, 'missing imports:', bad[:5])

joined = ''
for f in os.listdir(assets):
    if f.endswith('.js'):
        joined += open(os.path.join(assets, f), encoding='utf-8', errors='replace').read()
for key in ('/api/client_config', '/api/spray/status', '/api/ask_command', '/api/dashboard', '/ws/stream'):
    print(key, key in joined)
