# -*- coding: utf-8 -*-
"""把三套中文字体裁剪成网页用的 woff2，输出到 web/src/assets/fonts/（随前端一起打包，现场离线可用）。

    python scripts/build_webfonts.py --src <放原始字体的目录>

需要的原始字体（均为 SIL OFL 开源字体）：
    SarasaGothicSC-Regular.ttf / SarasaGothicSC-Bold.ttf   更纱黑体（正文）
        npm 包 @fontpkg/sarasa-gothic-sc，或 https://github.com/be5invis/Sarasa-Gothic
    SourceHanSerifCN-Bold.otf                               思源宋体（标题、重点）
        https://github.com/adobe-fonts/source-han-serif （SubsetOTF/CN）
    SmileySans-Oblique.ttf                                  得意黑（数字、品牌字等特殊字）
        https://github.com/atelier-anchor/smiley-sans

裁剪口径：
* 正文（更纱）：要显示任意内容（知识库原文、大模型回答），保留 GB2312 全部 6763 个汉字 + 常用符号 + 项目源码里出现的所有字；
* 标题（思源宋体）与特殊字（得意黑）：只出现在标题、读数、标本名上，只保留项目源码/知识库/配置里出现过的字，体积很小。
  个别不在子集里的字会按字回退到系统字体，不会显示成方框。
改了界面文案或知识库后重跑一次本脚本，再 `cd web && npm run build`。
"""
import argparse
import glob
import os
import sys

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'web', 'src', 'assets', 'fonts')

# 项目里会出现在页面上的文字来源
TEXT_GLOBS = [
    'web/src/**/*.vue', 'web/src/**/*.ts', 'web/index.html',
    'llm/*.py', 'config/*.yaml', 'prompts/**/*.txt', 'api_server.py', 'app/*.py',
    'feedback/*.py', 'tool/tools.py', 'scripts/build_dashboard.py',
]

BASE_RANGES = [
    (0x0020, 0x007E),   # ASCII
    (0x00A0, 0x00FF),   # Latin-1（°、×、· 等）
    (0x2000, 0x206F),   # 常用标点（— … ‘’ “”）
    (0x2100, 0x214F),   # 字母式符号（℃ №）
    (0x2190, 0x21FF),   # 箭头 →
    (0x2200, 0x22FF),   # 数学符号 ≥ ≤
    (0x2460, 0x24FF),   # 带圈数字 ①
    (0x25A0, 0x25FF),   # 几何形状 ■ ◆ ●
    (0x2600, 0x26FF),   # 杂项符号 ★ ☆
    (0x3000, 0x303F),   # 中文标点
    (0xFF00, 0xFFEF),   # 全角字符
]


def gb2312_chars():
    out = set()
    for hi in range(0xA1, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                out.add(bytes([hi, lo]).decode('gb2312'))
            except UnicodeDecodeError:
                pass
    return out


def project_chars():
    chars = set()
    for pat in TEXT_GLOBS:
        for path in glob.glob(os.path.join(ROOT, pat), recursive=True):
            try:
                with open(path, encoding='utf-8') as f:
                    chars.update(f.read())
            except (UnicodeDecodeError, OSError):
                continue
    return {c for c in chars if ord(c) >= 0x20}


def base_chars():
    return {chr(cp) for a, b in BASE_RANGES for cp in range(a, b + 1)}


def rename(font, pairs):
    """改字体内部名称。OFL 规定：声明了保留字体名（Reserved Font Name）的字体，
    修改版（裁剪子集也算）不能再用该名字，例如思源宋体保留了 'Source'。"""
    for rec in font['name'].names:
        try:
            text = rec.toUnicode()
        except UnicodeDecodeError:
            continue
        new = text
        for a, b in pairs:
            new = new.replace(a, b)
        if new != text:
            rec.string = new


def build(src, out_name, chars, family, renames=None):
    if not os.path.isfile(src):
        print(f'  [跳过] 找不到 {src}')
        return
    font = TTFont(src)
    cmap = font.getBestCmap()
    unicodes = sorted(ord(c) for c in chars if ord(c) in cmap)
    opts = subset.Options()
    opts.flavor = 'woff2'
    opts.layout_features = ['*']          # 保留标点挤压、竖排等 OpenType 特性
    opts.name_IDs = ['*']
    opts.notdef_outline = True
    opts.hinting = False                  # 网页渲染不需要 TrueType hinting，体积小很多
    opts.desubroutinize = True
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=unicodes)
    sub.subset(font)
    if renames:
        rename(font, renames)
    dst = os.path.join(OUT, out_name)
    font.flavor = 'woff2'
    font.save(dst)
    print(f'  {family:<12} {out_name:<26} {len(unicodes):>5} 字  {os.path.getsize(dst) / 1024:>7.0f} KB')


def main():
    ap = argparse.ArgumentParser(description='裁剪网页字体')
    ap.add_argument('--src', required=True, help='原始字体所在目录')
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    def find(pattern):
        hits = sorted(glob.glob(os.path.join(args.src, '**', pattern), recursive=True))
        return hits[0] if hits else os.path.join(args.src, pattern)

    proj = project_chars()
    body = gb2312_chars() | proj | base_chars()
    display = proj | base_chars()
    print(f'项目文字 {len(proj)} 个；正文字符集 {len(body)} 个；标题/特殊字字符集 {len(display)} 个')
    build(find('SarasaGothicSC-Regular.ttf'), 'sarasa-sc-400.woff2', body, '更纱黑体')
    build(find('SarasaGothicSC-Bold.ttf'), 'sarasa-sc-700.woff2', body, '更纱黑体')
    build(find('SourceHanSerif*-Bold.otf'), 'source-han-serif-700.woff2', display, '思源宋体',
          renames=[('Source Han Serif', 'CG Serif'), ('SourceHanSerif', 'CGSerif')])
    build(find('SmileySans-Oblique.ttf'), 'smiley-sans.woff2', display, '得意黑')
    return 0


if __name__ == '__main__':
    sys.exit(main())
