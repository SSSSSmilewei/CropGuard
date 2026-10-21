# -*- coding: utf-8 -*-
"""到货标本逐只验收：按采购单编号拍照 → 逐张跑模型 → 出"能不能进现场 20 张"的报告。

为什么要有这个脚本
------------------
国赛幕② 是"20 个实体样本，评委逐个判 ✓/✗，每错 1 只丢 1 分"。商家配的虫**可能货不对板**
（拿黄粉虫当金针虫、拿金龟子成虫当蛴螬），也可能太小/糊到检不出。到货当天用现场那台相机
按编号拍一遍、跑这个脚本，就能在赛前把不合格的换掉，而不是到台上才发现。

用法
----
    # 1) 每只拍一张，文件名就是采购单编号：01.jpg … 20.jpg（备用 21.jpg…）
    # 2) 跑：
    py -3.14 scripts/screen_specimens.py --dir specimens --plan docs/specimens_plan.csv

    # conf 默认 0.4（= GUI 现场阈值）；pass-conf 默认 0.7（留安全余量，抗打印/光照退化）
    py -3.14 scripts/screen_specimens.py --dir specimens --pass-conf 0.7 --device cuda:0

判定
----
    OK        类别对 且 置信度 ≥ pass-conf         → 可进现场
    LOW       类别对 但 < pass-conf（仍高于 conf）  → 先补拍/换光线，仍低则换备用
    WRONG     判成别的类                            → 换货
    NONE      conf 阈值下 0 检出                    → 换货（多半太小/糊）
    NOFILE    计划位没拍到                          → 补拍
    UNPLANNED 多出来的照片（非计划编号）             → 记录，可当备用

退出码：主选（tier=primary）出现 WRONG / NONE / NOFILE → 1（不合格，别带进现场）；否则 0。
报告：<dir>/screen_<时间戳>.csv / .json / .md
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm.knowledge_base import PEST_KB  # noqa: E402

IMG_EXT = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
FAIL_VERDICTS = {'WRONG', 'NONE', 'NOFILE'}
# 文件名容错：01.jpg / 1_蝼蛄.jpg / S01.jpg / #01-xxx.jpg
SLOT_RE = re.compile(r'^(?:#|S|s)?\s*(?P<slot>\d{1,2})(?![0-9])')


def cn_of(class_en: str) -> str:
    return PEST_KB.get(class_en, {}).get('cn', class_en)


def load_plan(path: str | Path) -> list[dict]:
    """读采购单 CSV（utf-8 / utf-8-sig 都认），返回按 slot 排序的行。"""
    rows: list[dict] = []
    with open(path, encoding='utf-8-sig', newline='') as fh:
        for raw in csv.DictReader(fh):
            slot = str(raw.get('slot', '')).strip()
            if not slot.isdigit():
                continue
            row = {k: (v or '').strip() for k, v in raw.items()}
            row['slot'] = int(slot)
            row.setdefault('tier', 'primary')
            row['tier'] = (row['tier'] or 'primary').lower()
            rows.append(row)
    rows.sort(key=lambda r: r['slot'])
    return rows


def parse_slot(name: str) -> int | None:
    """从文件名前导数字解析采购单编号；解析不出返回 None。"""
    m = SLOT_RE.match(Path(name).name)
    return int(m.group('slot')) if m else None


def verdict(top: dict | None, expected_en: str, pass_conf: float = 0.7) -> str:
    """单张判定。top = {'class_en':..., 'conf':...} 或 None。"""
    if not top:
        return 'NONE'
    if top.get('class_en') != expected_en:
        return 'WRONG'
    return 'OK' if float(top.get('conf', 0.0)) >= pass_conf else 'LOW'


def summarize(records: list[dict]) -> dict:
    """按 primary / spare 分别统计判定数量。"""
    out = {'primary': {}, 'spare': {}, 'unplanned': 0}
    for r in records:
        tier = r.get('tier')
        if tier not in ('primary', 'spare'):
            out['unplanned'] += 1
            continue
        out[tier][r['verdict']] = out[tier].get(r['verdict'], 0) + 1
    return out


def _suggest_replacements(records: list[dict]) -> list[str]:
    """给主选里不合格的位出"用备用第 N 号顶"的建议（缺图位不在这里说，单独提示）。"""
    spares: dict[str, list[dict]] = {}
    for r in records:
        if r.get('tier') == 'spare':
            spares.setdefault(r['class_en'], []).append(r)

    lines = []
    for r in records:
        if r.get('tier') != 'primary' or r['verdict'] not in FAIL_VERDICTS - {'NOFILE'}:
            continue
        cand = spares.get(r['class_en'], [])
        if cand:
            pick = sorted(cand, key=lambda x: (x['verdict'] != 'OK', x['slot']))[0]
            lines.append(
                f"#{r['slot']} {r['class_cn']}（{r['verdict']}）→ 用备用 #{pick['slot']}"
                f"（{pick['verdict']}）顶；备用也不合格就找商家同类别再换一只"
            )
        else:
            lines.append(
                f"#{r['slot']} {r['class_cn']}（{r['verdict']}）→ 没有同类备用，"
                f"找商家换同一类别；或用任一大体型备用位补"
            )
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description='到货昆虫标本逐只验收（对照 docs/specimens_plan.csv）')
    ap.add_argument('--dir', default=str(ROOT / 'specimens'), help='照片目录（文件名=采购单编号）')
    ap.add_argument('--plan', default=str(ROOT / 'docs/specimens_plan.csv'), help='采购单 CSV')
    ap.add_argument('--weights', default=str(ROOT / 'runs/train/pest27_final4/weights/best.pt'))
    ap.add_argument('--imgsz', type=int, default=640)
    ap.add_argument('--conf', type=float, default=0.4, help='检测阈值（默认对齐 GUI 的 0.4）')
    ap.add_argument('--pass-conf', type=float, default=0.7, help='验收安全线（建议 0.7）')
    ap.add_argument('--device', default='cpu')
    ap.add_argument('--report-dir', default=None, help='报告输出目录（默认同 --dir）')
    args = ap.parse_args()

    folder = Path(args.dir)
    plan_path = Path(args.plan)
    if not plan_path.exists():
        print(f'!! 找不到采购单：{plan_path}')
        return 2
    if not folder.exists():
        print(f'!! 找不到照片目录：{folder}\n   先把照片按编号放进去（01.jpg … 20.jpg）')
        return 2

    plan = load_plan(plan_path)
    if not plan:
        print(f'!! 采购单没解析出任何行：{plan_path}')
        return 2
    by_slot = {r['slot']: r for r in plan}

    # 收图 + 按编号归位（同编号多张时取排序第一个并提示）
    slot_files: dict[int, Path] = {}
    unplanned: list[Path] = []
    for p in sorted(folder.iterdir()):
        if not p.is_file() or p.suffix.lower() not in IMG_EXT:
            continue
        slot = parse_slot(p.name)
        if slot is None or slot not in by_slot:
            unplanned.append(p)
            continue
        if slot in slot_files:
            print(f'[WARN] 编号 {slot} 有多张图，用 {slot_files[slot].name}，忽略 {p.name}')
            continue
        slot_files[slot] = p

    from ultralytics import YOLO  # 惰性导入：没装 torch 也能跑 --help

    model = YOLO(args.weights)
    print(f'权重 {args.weights}')
    print(f'照片 {len(slot_files)} 张 / 采购单 {len(by_slot)} 位 | imgsz={args.imgsz} '
          f'conf={args.conf} pass={args.pass_conf} device={args.device}\n')
    print('现场口径：GUI 检测阈值 CONF=0.4（低于它=无检出）；验收要求 ≥%.2f 留余量\n' % args.pass_conf)

    def _predict(img: Path) -> tuple[dict | None, int, float]:
        t0 = time.perf_counter()
        res = model.predict(str(img), imgsz=args.imgsz, conf=args.conf,
                            device=args.device, verbose=False)[0]
        ms = (time.perf_counter() - t0) * 1000
        dets = [{'class_en': res.names[int(b.cls)],
                 'class_cn': cn_of(res.names[int(b.cls)]),
                 'conf': round(float(b.conf), 4)} for b in res.boxes]
        dets.sort(key=lambda d: -d['conf'])
        return (dets[0] if dets else None), len(dets), ms

    records: list[dict] = []
    for slot in sorted(by_slot):
        row = by_slot[slot]
        img = slot_files.get(slot)
        rec = {
            'slot': slot, 'tier': row['tier'], 'class_cn': row['class_cn'],
            'class_en': row['class_en'], 'stage': row.get('stage', ''),
            'form': row.get('form', ''), 'file': img.name if img else '',
            'top1_class_en': '', 'top1_class_cn': '', 'top1_conf': '', 'n_boxes': 0,
            'all_dets': '', 'verdict': 'NOFILE', 'ms': '',
        }
        if img is not None:
            top, n_boxes, ms = _predict(img)
            rec['n_boxes'] = n_boxes
            rec['ms'] = f'{ms:.0f}'
            rec['top1_class_en'] = top['class_en'] if top else ''
            rec['top1_class_cn'] = top['class_cn'] if top else ''
            rec['top1_conf'] = f'{top["conf"]:.4f}' if top else ''
            rec['verdict'] = verdict(top, row['class_en'], args.pass_conf)
        records.append(rec)

    # 多出来的照片也跑一遍，方便判断能不能当备用
    for img in unplanned:
        top, n_boxes, ms = _predict(img)
        records.append({
            'slot': '', 'tier': 'unplanned', 'class_cn': '', 'class_en': '', 'stage': '',
            'form': '', 'file': img.name,
            'top1_class_en': top['class_en'] if top else '',
            'top1_class_cn': top['class_cn'] if top else '',
            'top1_conf': f'{top["conf"]:.4f}' if top else '',
            'n_boxes': n_boxes,
            'all_dets': '; '.join(f'{d["class_cn"]}:{d["conf"]:.2f}'
                                  for d in ([top] if top else [])),
            'verdict': 'UNPLANNED', 'ms': f'{ms:.0f}',
        })

    mark = {'OK': 'OK  ', 'LOW': 'LOW ', 'WRONG': 'NG  ', 'NONE': 'NONE', 'NOFILE': '----'}
    for r in records:
        if r['tier'] == 'unplanned':
            print(f"{'????':<4} [额外] {r['file']:<28} → {r['top1_class_cn'] or '(无)':<8} "
                  f"{r['top1_conf'] or '-':<7}")
            continue
        print(f"{mark.get(r['verdict'], '?'):<4} #{r['slot']:<2} {r['class_cn']:<6} "
              f"{r['verdict']:<8} 期望 {r['class_cn']:<6} 实测 {(r['top1_class_cn'] or '(无)'):<6} "
              f"{r['top1_conf'] or '-':<7} {r['ms']}ms  [{r['file'] or '缺图'}]")

    stats = summarize(records)
    p = stats['primary']
    n_primary = sum(1 for r in plan if r['tier'] == 'primary')
    print(f"\n主选：OK {p.get('OK', 0)} / LOW {p.get('LOW', 0)} / WRONG {p.get('WRONG', 0)} / "
          f"NONE {p.get('NONE', 0)} / NOFILE {p.get('NOFILE', 0)}（共 {n_primary} 位）")
    s = stats['spare']
    print(f"备用：OK {s.get('OK', 0)} / LOW {s.get('LOW', 0)} / WRONG {s.get('WRONG', 0)} / "
          f"NONE {s.get('NONE', 0)} / NOFILE {s.get('NOFILE', 0)}")

    suggestions = _suggest_replacements(records)
    missing = [f"#{r['slot']} {r['class_cn']}" for r in records
               if r['tier'] == 'primary' and r['verdict'] == 'NOFILE']
    if missing:
        print(f"\n缺图 {len(missing)} 位（补拍后重跑）：{'、'.join(missing)}")
    if suggestions:
        print('\n换货 / 补位建议：')
        for line in suggestions:
            print('  - ' + line)
    elif not missing:
        print('\n主选全部通过（无 WRONG/NONE/NOFILE）。')

    # ---- 报告 ----
    out_dir = Path(args.report_dir) if args.report_dir else folder
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = f'{datetime.now():%Y%m%d_%H%M%S}'
    csv_path = out_dir / f'screen_{stamp}.csv'
    json_path = out_dir / f'screen_{stamp}.json'
    md_path = out_dir / f'screen_{stamp}.md'

    fields = ['slot', 'tier', 'class_cn', 'class_en', 'stage', 'form', 'file',
              'top1_class_en', 'top1_class_cn', 'top1_conf', 'n_boxes', 'all_dets',
              'verdict', 'ms']
    with csv_path.open('w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows([{k: r.get(k, '') for k in fields} for r in records])

    json_path.write_text(json.dumps({
        'plan': str(plan_path), 'weights': args.weights, 'imgsz': args.imgsz,
        'conf': args.conf, 'pass_conf': args.pass_conf, 'device': args.device,
        'stats': stats, 'suggestions': suggestions, 'records': records,
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    md = [f'# 标本到货验收（{stamp}）', '',
          f'- 采购单：`{plan_path}`',
          f'- 权重：`{args.weights}`（imgsz={args.imgsz}, conf={args.conf}, '
          f'pass={args.pass_conf}, device={args.device}）',
          f'- 主选：OK {p.get("OK", 0)} / LOW {p.get("LOW", 0)} / WRONG {p.get("WRONG", 0)} / '
          f'NONE {p.get("NONE", 0)} / NOFILE {p.get("NOFILE", 0)}',
          f'- 备用：OK {s.get("OK", 0)} / LOW {s.get("LOW", 0)} / WRONG {s.get("WRONG", 0)} / '
          f'NONE {s.get("NONE", 0)} / NOFILE {s.get("NOFILE", 0)}', '']
    if missing:
        md += [f'## 缺图（{len(missing)} 位，补拍后重跑）', ''] + [f'- {x}' for x in missing] + ['']
    if suggestions:
        md += ['## 换货 / 补位建议', ''] + [f'- {x}' for x in suggestions] + ['']
    md += ['## 逐只结果', '',
           '| 序 | 类别 | 期望 | 实测 | 置信度 | 判定 | 文件 | ms |',
           '| ---: | --- | --- | --- | --- | --- | --- | ---: |']
    for r in records:
        md.append(f"| {r['slot']} | {r['class_cn']} | {r['class_cn']} | "
                  f"{r['top1_class_cn'] or '(无)'} | {r['top1_conf'] or '-'} | "
                  f"{r['verdict']} | `{r['file'] or '-'}` | {r['ms'] or '-'} |")
    md_path.write_text('\n'.join(md) + '\n', encoding='utf-8')

    print(f'\nwrote: {csv_path.name} / {json_path.name} / {md_path.name}')
    primary_fail = any(r['verdict'] in FAIL_VERDICTS
                       for r in records if r['tier'] == 'primary')
    return 1 if primary_fail else 0


if __name__ == '__main__':
    raise SystemExit(main())
