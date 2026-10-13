# -*- coding: utf-8 -*-
"""演示看板用例：serve/pages/dashboard.html + scripts/build_dashboard.py。

看板有两种形态，两条都要守住：
* 快照态：内嵌 JSON 必须**跟真实产物一致**（不能手改数字、不能放旧数据），
  且页面零外部依赖（国赛离线合规：无 CDN、无图表库、无联网请求）；
* 实时态：页面只读 `/api/*`，**不许出现喷淋/雾化的写接口**（演示时误触发硬件是事故）。

这里刻意不 import torch/ultralytics：全是读文件与解析 JSON，跑得快、也不受模型环境影响。
生成器用例走 `--no-thumbs`，因此不碰 cv2（本机 PATH 上的 python 3.12 没有 cv2）。
"""
import ast
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from _registry import SkipTest, requires, test_case

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'serve' / 'pages' / 'dashboard.html'
SCRIPT = ROOT / 'scripts' / 'build_dashboard.py'
# 临时产物写工作区内短路径（沙箱可能只允许工作区写；%TEMP% 实测会被拒）
TMP_DIR = ROOT / 'output' / '_test_tmp' / 'dashboard'

REGION_RE = re.compile(r'<!--\s*CG-SNAPSHOT:BEGIN\s*-->(.*?)<!--\s*CG-SNAPSHOT:END\s*-->', re.S)
SNIPPET_RE = re.compile(r'<script id="cgSnapshot" type="application/json">(.*?)</script>', re.S)

# 看板允许出现的接口（只读）；写接口一个都不许有
FORBIDDEN_WRITE_APIS = ('/api/spray', '/api/mist/start', '/api/mist/direct', '/api/mist/stop')
READONLY_APIS = ('/api/health', '/api/info', '/api/camera/health', '/api/feedback/status',
                 '/api/mist/status', '/api/history', '/api/detect', '/ws/stream')


def _page_text() -> str:
    assert PAGE.exists(), f'看板页不存在: {PAGE}（先跑 scripts/build_dashboard.py）'
    return PAGE.read_text(encoding='utf-8')


def _snapshot() -> dict:
    """从页面标记区里取出内嵌快照 JSON。"""
    text = _page_text()
    regions = REGION_RE.findall(text)
    assert len(regions) == 1, f'CG-SNAPSHOT 标记区应恰好 1 个，实际 {len(regions)} 个'
    m = SNIPPET_RE.search(regions[0])
    assert m, '标记区里找不到 <script id="cgSnapshot">'
    return json.loads(m.group(1))


def _latest(pattern: str) -> Path:
    hits = sorted(ROOT.glob(pattern))
    assert hits, f'没有匹配 {pattern} 的产物'
    return hits[-1]


def _split_regions(text: str):
    m = REGION_RE.search(text)
    assert m, '页面里没有 CG-SNAPSHOT 标记区'
    return text[:m.start()], text[m.end():]


# ==================== 快照本身 ====================
@test_case
def test_dashboard_snapshot_is_valid_json():
    """内嵌快照必须能 JSON 解析，且是真数据（不是占位）。"""
    snap = _snapshot()
    assert not snap.get('placeholder'), '快照还是占位内容，先跑 scripts/build_dashboard.py'
    assert snap.get('generated_at'), '缺少 generated_at'
    assert snap.get('per_class'), '缺少 per_class'
    assert snap.get('testset', {}).get('rows'), '缺少 testset.rows'
    assert snap.get('curves', {}).get('epoch'), '缺少 curves.epoch'


@test_case
def test_dashboard_snapshot_matches_sources():
    """看板数字必须等于真实产物里的数字（防止手改/放旧数据）。"""
    snap = _snapshot()

    # --- 每类验证报告 ---
    per_src = json.loads(_latest('output/per_class_val_*.json').read_text(encoding='utf-8'))
    assert len(snap['per_class']) == len(per_src['per_class']), '每类条数与验证报告不一致'
    for got, want in zip(snap['per_class'], per_src['per_class']):
        assert got['en'] == want['class_en'], f"类别顺序不一致: {got['en']} != {want['class_en']}"
        assert abs(float(got['mAP50']) - float(want['mAP50'])) < 1e-9, f"{got['en']} 的 mAP50 与源不一致"
    for key in ('mAP50', 'mAP50_95', 'precision', 'recall'):
        assert abs(float(snap['overall'][key]) - float(per_src['overall'][key])) < 1e-9, f'overall.{key} 与源不一致'

    # --- 中文类名与知识库同源 ---
    from llm.knowledge_base import PEST_KB
    for row in snap['per_class']:
        assert row['cn'] == PEST_KB[row['en']]['cn'], f"{row['en']} 的中文名与 PEST_KB 不一致"

    # --- 训练曲线 ---
    with (_latest('runs/train/pest27_final4/results.csv')).open(encoding='utf-8-sig', newline='') as fh:
        n_rows = sum(1 for _ in csv.DictReader(fh))
    assert len(snap['curves']['epoch']) == n_rows, '曲线轮数与 results.csv 行数不一致'
    assert len(snap['curves']['mAP50']) == n_rows, 'mAP50 列长度不对'

    # --- 实测样本 ---
    eval_path = _latest('real_testset20/eval_*.json')
    ev = json.loads(eval_path.read_text(encoding='utf-8'))
    ts = snap['testset']
    assert ts['n'] == ev['n'] and len(ts['rows']) == ev['n'], '实测样本条数与源不一致'
    assert ts['top1_hit'] == ev['top1_hit'], 'Top1 命中数与源不一致'
    assert abs(float(ts['avg_ms']) - float(ev['avg_ms'])) < 1e-6, '平均耗时与源不一致'
    for got, want in zip(ts['rows'], ev['rows']):
        assert got['file'] == want['file'], '样本文件顺序不一致'
        assert got['hit'] == str(want['hit']).upper().startswith('Y'), f"{got['file']} 命中标记不一致"
    # 来源脚注里要能看到真实文件名（答辩可核对）
    assert eval_path.name in snap['sources']['eval_json']

    # --- 数据集计数（目录存在才核对） ---
    img_dir = ROOT / 'dataset_full' / 'images' / 'train'
    if img_dir.is_dir():
        n_img = sum(1 for f in img_dir.iterdir() if f.is_file())
        assert snap['dataset']['train'] == n_img, '训练图计数与目录不一致'


@test_case
def test_dashboard_page_renders_and_is_not_missing():
    """页面必须能被服务端加载器读出来（/dashboard 路由就靠它）。"""
    from serve import pages
    html = pages.load('dashboard')
    assert 'page dashboard not found' not in html, 'serve/pages/dashboard.html 没被加载到'
    assert 'cgSnapshot' in html and '数据看板' in html
    for api in READONLY_APIS:
        assert api in html, f'页面缺少只读接口引用 {api}'


@test_case
def test_dashboard_is_offline_safe():
    """国赛离线合规：零外部依赖（无 CDN / 无外部脚本 / 无外链样式）。"""
    text = _page_text()
    for bad in ('cdn.', 'googleapis', 'unpkg', 'jsdelivr', '<script src=', '<link rel="stylesheet"'):
        assert bad not in text, f'页面出现了外部依赖痕迹: {bad}'
    # 允许出现在快照 JSON（节点地址）与注释里的 http，但不允许是外部资源引用；
    # 唯一的例外是指向本机 api_server 的回环链接（快照态提示"进入实时模式"那个）
    refs = re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)', text)
    external = [u for u in refs
                if not re.match(r'https?://(127\.0\.0\.1|localhost)([:/]|$)', u)]
    assert not external, f'页面里有外部资源引用: {external}'


@test_case
def test_dashboard_has_no_hardware_write_calls():
    """看板只读：不许出现喷淋/雾化的写接口（演示时误触发硬件是事故）。"""
    text = _page_text()
    for bad in FORBIDDEN_WRITE_APIS:
        assert bad not in text, f'看板不该调用写接口 {bad}'
    # 唯一的写请求必须是图片快检 /api/detect
    posts = re.findall(r"getJSON\(\s*'([^']+)'\s*,\s*\d+\s*,\s*\{\s*method:\s*'POST'", text)
    assert posts == ['/api/detect'], f'看板里的 POST 只允许 /api/detect，实际: {posts}'


@test_case
def test_dashboard_route_registered():
    """api_server.py 必须注册 /dashboard（用 ast 解析，不 import 重依赖）。"""
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
    assert '/dashboard' in paths, f'api_server.py 没注册 /dashboard（现有: {sorted(paths)}）'
    assert '/dashboard' in src.split('数据看板')[0] or '数据看板' in src, '启动横幅里应提示看板地址'


@test_case
def test_dashboard_inline_js_parses():
    """内嵌 JS 必须能解析 —— 这条是踩过坑才加的。

    真实事故：快照里有个带点的 key `ge_0.95_count`，前端顺手写成 `o.ge_0.95_count`，
    JS 直接语法错误 → 整个 IIFE 不执行，页面**只剩静态外壳**（KPI 全空、曲线全空、
    20 张样本一张不显示），而 CSS/HTML 又都正常，肉眼很容易以为"数据没生成"。
    所以这里用 node 做一次语法检查（没装 node 就跳过，与项目 requires() 的口径一致）。
    """
    node = shutil.which('node')
    if not node:
        raise SkipTest('未安装 node，跳过内嵌 JS 语法检查')
    text = _page_text()
    blocks = re.findall(r'<script(?![^>]*application/json)[^>]*>(.*?)</script>', text, re.S)
    assert blocks, '页面里找不到内联 JS 块'
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    js_path = TMP_DIR / 'app_check.js'
    try:
        js_path.write_text('\n'.join(blocks), encoding='utf-8')
        proc = subprocess.run([node, '--check', str(js_path)],
                              capture_output=True, text=True, encoding='utf-8', errors='replace')
        assert proc.returncode == 0, f'内嵌 JS 语法错误：\n{proc.stdout}\n{proc.stderr}'
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)


@test_case
def test_build_dashboard_preserves_handwritten_parts():
    """生成器只许改标记区：标记区之外必须逐字节不动，且产物仍是合法 JSON。"""
    requires('yaml')
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    target = TMP_DIR / 'dashboard_gen_test.html'
    try:
        shutil.copyfile(PAGE, target)
        before = target.read_text(encoding='utf-8')
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), '--out', str(target), '--no-thumbs'],
            cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8', errors='replace')
        assert proc.returncode == 0, f'生成器退出码 {proc.returncode}\n{proc.stdout}\n{proc.stderr}'

        after = target.read_text(encoding='utf-8')
        head_b, tail_b = _split_regions(before)
        head_a, tail_a = _split_regions(after)
        assert head_a == head_b, '标记区之前的内容被改动了（生成器只该改标记区）'
        assert tail_a == tail_b, '标记区之后的内容被改动了（生成器只该改标记区）'

        m = SNIPPET_RE.search(REGION_RE.search(after).group(1))
        assert m, '产物标记区里没有快照脚本'
        snap = json.loads(m.group(1))
        assert len(snap['testset']['rows']) == snap['testset']['n'] == 20
        assert all(r['thumb'] is None for r in snap['testset']['rows']), '--no-thumbs 不该内嵌缩略图'
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)
