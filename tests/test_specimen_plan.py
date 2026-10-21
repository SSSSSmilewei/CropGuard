# -*- coding: utf-8 -*-
"""采购单一致性 + 到货验收判定 的回归用例（**不需要 torch/ultralytics**）。

守三件事：
1. `docs/specimens_plan.csv` 与 `docs/真实昆虫采购单.md` 的表格逐行一致（口径只有一份）；
2. 主选类目都在模型 27 类内、且每类 mAP50 ≥ 0.82、不踩已知错标/混淆类；
3. `scripts/screen_specimens.py` 的判定逻辑与文件名容错。
"""
import csv
import importlib.util
import sys

from _registry import test_case

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'docs' / 'specimens_plan.csv'
DOC = ROOT / 'docs' / '真实昆虫采购单.md'
SCREEN = ROOT / 'scripts' / 'screen_specimens.py'

# 每类 mAP50（来源：output/per_class_val_20261013_120802.md，2026-10-13 复验）
MP50 = {
    'Lycorma_delicatula': 0.9950, 'mole_cricket': 0.9946, 'Cicadellidae': 0.9856,
    'rice_leaf_roller': 0.9842, 'Potosiabre_vitarsis': 0.9803, 'flea_beetle': 0.9715,
    'grub': 0.9627, 'Ampelophaga': 0.9506, 'wireworm': 0.8798, 'aphids': 0.8700,
    'Cicadella_viridis': 0.8624, 'peach_borer': 0.8469, 'black_cutworm': 0.8267,
    'Miridae': 0.8246, 'corn_borer': 0.8232,
}
FLOOR = 0.82  # 主选 mAP50 下限

# 已知错标 / 混淆严重 / 低于下限 —— 一律不许进主选
BANNED = {
    'Locustoidea',            # mAP50 0.659，且实训图错标成绿色盲蝽
    'Potosiabre_vitarsis',    # 标签可疑（KB 名"光肩星天牛"，画面像花金龟）
    'Miridae', 'tarnished_plant_bug', 'alfalfa_plant_bug',   # 盲蝽集群，互混严重
    'blister_beetle', 'legume_blister_beetle', 'lytta_polita',  # 芫菁集群
    'Prodenia_litura', 'beet_army_worm', 'army_worm', 'cabbage_army_worm',
    'yellow_cutworm',         # 夜蛾集群低位
    'flax_budworm', 'peach_borer',   # 0.42 / 0.85 但混淆矩阵对角值偏低
}


def _plan_rows():
    with PLAN.open(encoding='utf-8-sig', newline='') as fh:
        rows = [{k: (v or '').strip() for k, v in r.items()} for r in csv.DictReader(fh)]
    return rows


def _doc_table(begin, end):
    text = DOC.read_text(encoding='utf-8')
    block = text.split(begin, 1)[1].split(end, 1)[0]
    out = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if cells and cells[0].isdigit():
            out.append(cells)
    return out


def _screen_module():
    if 'screen_specimens' in sys.modules:
        return sys.modules['screen_specimens']
    spec = importlib.util.spec_from_file_location('screen_specimens', SCREEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules['screen_specimens'] = mod
    return mod


@test_case
def test_plan_has_20_primary_and_6_spare():
    rows = _plan_rows()
    primary = [r for r in rows if r['tier'] == 'primary']
    spare = [r for r in rows if r['tier'] == 'spare']
    assert len(primary) == 20, f'主选必须 20 只，现在 {len(primary)}'
    assert len(spare) == 6, f'备用必须 6 只，现在 {len(spare)}'
    slots = [int(r['slot']) for r in rows]
    assert slots == list(range(1, len(rows) + 1)), f'编号必须 1..{len(rows)} 连续：{slots}'


@test_case
def test_plan_classes_exist_in_model_kb():
    from llm.knowledge_base import PEST_KB
    for r in _plan_rows():
        assert r['class_en'] in PEST_KB, f"#{r['slot']} 类别 {r['class_en']} 不在 27 类里"


@test_case
def test_primary_classes_are_reliable():
    for r in [x for x in _plan_rows() if x['tier'] == 'primary']:
        cls = r['class_en']
        assert cls not in BANNED, f"#{r['slot']} {cls} 属于禁用类（错标/混淆）"
        assert cls in MP50, f'#{r["slot"]} {cls} 没有 mAP50 记录，先补数据再下单'
        assert MP50[cls] >= FLOOR, f'#{r["slot"]} {cls} mAP50={MP50[cls]} 低于下限 {FLOOR}'


@test_case
def test_doc_order_table_matches_plan():
    rows = _plan_rows()[:20]
    table = _doc_table('<!-- ORDER-TABLE:BEGIN -->', '<!-- ORDER-TABLE:END -->')
    assert len(table) == 20, f'文档主选表应 20 行，实际 {len(table)}'
    for cells, row in zip(table, rows):
        assert int(cells[0]) == int(row['slot']), f"文档序号 {cells[0]} ≠ {row['slot']}"
        assert cells[1] == row['class_cn'], (
            f"#{row['slot']} 文档类别 {cells[1]!r} ≠ CSV {row['class_cn']!r}")


@test_case
def test_doc_spare_table_matches_plan():
    rows = _plan_rows()[20:]
    table = _doc_table('<!-- SPARE-TABLE:BEGIN -->', '<!-- SPARE-TABLE:END -->')
    assert len(table) == len(rows), f'文档备用表应 {len(rows)} 行，实际 {len(table)}'
    for cells, row in zip(table, rows):
        assert int(cells[0]) == int(row['slot'])
        assert cells[1] == row['class_cn'], f"#{row['slot']} 正文 {cells[1]!r} ≠ {row['class_cn']!r}"


@test_case
def test_verdict_six_cases():
    mod = _screen_module()
    v = mod.verdict
    assert v(None, 'grub') == 'NONE'
    assert v({'class_en': 'grub', 'conf': 0.91}, 'grub') == 'OK'
    assert v({'class_en': 'grub', 'conf': 0.70}, 'grub') == 'OK', '边界值应算通过'
    assert v({'class_en': 'grub', 'conf': 0.69}, 'grub') == 'LOW'
    assert v({'class_en': 'grub', 'conf': 0.45}, 'grub') == 'LOW', '高于 conf 但低于安全线 → LOW'
    assert v({'class_en': 'mole_cricket', 'conf': 0.95}, 'grub') == 'WRONG'


@test_case
def test_parse_slot_tolerances():
    mod = _screen_module()
    p = mod.parse_slot
    assert p('01.jpg') == 1
    assert p('1_蝼蛄.jpg') == 1
    assert p('S01.jpg') == 1
    assert p('#7-xx.png') == 7
    assert p('21_备用.jpg') == 21
    assert p('abc.jpg') is None
    assert p('123.jpg') is None, '三位数不该被截成 12'


@test_case
def test_summarize_counts_by_tier():
    mod = _screen_module()
    recs = [
        {'tier': 'primary', 'verdict': 'OK'},
        {'tier': 'primary', 'verdict': 'WRONG'},
        {'tier': 'spare', 'verdict': 'OK'},
        {'tier': 'unplanned', 'verdict': 'UNPLANNED'},
    ]
    s = mod.summarize(recs)
    assert s['primary'] == {'OK': 1, 'WRONG': 1}, s
    assert s['spare'] == {'OK': 1}, s
    assert s['unplanned'] == 1, s


@test_case
def test_plan_species_counts_match_doc_summary():
    """主选 10 类 / 备用 6 类（与采购单末尾"按类合计"口径一致）。"""
    rows = _plan_rows()
    primary = {r['class_en'] for r in rows if r['tier'] == 'primary'}
    spare = {r['class_en'] for r in rows if r['tier'] == 'spare'}
    assert len(primary) == 10, f'主选应为 10 类，实际 {len(primary)}：{sorted(primary)}'
    assert len(spare) == 6, f'备用应为 6 类，实际 {len(spare)}：{sorted(spare)}'

