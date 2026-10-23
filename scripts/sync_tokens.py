# -*- coding: utf-8 -*-
"""把站点的设计令牌同步给原生页（``serve/static/tokens.css``）。

单一事实来源是 ``web/src/styles/tokens.css``（Vue 侧 ``base.css`` 里 ``@import`` 的就是它）。
原生页（``/m-classic``、``/demo``、``/eval-classic``）没有构建步骤，只能读一份静态 CSS，
所以这里做「复制 + 加头注释」。

⚠️ 改了令牌却没跑这个脚本 → 原生页与站点会慢慢漂移，``tests/test_design_tokens.py``
   会直接失败（故意做成硬失败，而不是让人肉眼看出来）。

用法：``py -3.14 scripts/sync_tokens.py``
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SRC = os.path.join(ROOT, 'web', 'src', 'styles', 'tokens.css')
DST = os.path.join(ROOT, 'serve', 'static', 'tokens.css')

HEADER = """/* 由 scripts/sync_tokens.py 从 web/src/styles/tokens.css 生成 —— 不要手改这个文件。
 * 原生页（/m-classic、/demo、/eval-classic）没有构建步骤，靠这份 CSS 与站点保持同一套视觉。
 */
"""


def main():
    with open(SRC, 'r', encoding='utf-8') as f:
        body = f.read()
    text = HEADER + body
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print(f'[TOKENS] {os.path.relpath(SRC, ROOT)} → {os.path.relpath(DST, ROOT)}'
          f'（{len(text.splitlines())} 行）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
