"""跑一次验证，导出「每类」指标（mAP50 / mAP50-95 / P / R），供挑选高可靠类别。

用法:
    py -3.14 scripts/per_class_val.py                 # 默认 best.pt + dataset_full/data.yaml
    py -3.14 scripts/per_class_val.py --imgsz 640 --batch 4

产物: output/per_class_val_<时间戳>.csv / .json / .md
CPU 机器上 2046 张 val 图约需数分钟 ~ 十几分钟。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('TQDM_DISABLE', '1')  # 关掉验证进度条，日志才读得下去
# 本仓库根目录下有一份 vendored ultralytics；用 `py -3.14 scripts/xxx.py` 跑时
# sys.path[0] 是 scripts/，会 import 不到 → 显式把仓库根放最前
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--weights', default=str(ROOT / 'runs/train/pest27_final4/weights/best.pt'))
    ap.add_argument('--data', default=str(ROOT / 'dataset_full/data.yaml'))
    ap.add_argument('--imgsz', type=int, default=640)
    ap.add_argument('--batch', type=int, default=4)
    ap.add_argument('--workers', type=int, default=0)
    ap.add_argument('--device', default='cpu')
    args = ap.parse_args()

    from ultralytics import YOLO

    model = YOLO(args.weights)
    t0 = time.time()
    m = model.val(
        data=args.data,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        device=args.device,
        plots=False,
        verbose=False,
        # verbose=False 仍会刷 tqdm 进度条 → 直接关掉（日志可读，也省一点 IO）
        show_labels=False,
        show_conf=False,
        project=str(ROOT / 'runs/val'),
        name=f'perclass_{datetime.now():%Y%m%d_%H%M%S}',
        exist_ok=True,
    )
    dt = time.time() - t0

    def _flat(name, n):
        """把 m.box.<name> 变成定长 list；numpy 数组不能直接 `or []`（歧义真值）。"""
        v = getattr(m.box, name, None)
        if v is None:
            return [None] * n
        seq = v.tolist() if hasattr(v, 'tolist') else list(v)
        seq = list(seq) + [None] * max(0, n - len(seq))
        return seq

    n_cls = len(m.names)
    names = m.names if isinstance(m.names, dict) else {i: n for i, n in enumerate(m.names)}
    ap50 = _flat('ap50', n_cls)
    ap = _flat('ap', n_cls)
    p = _flat('p', n_cls)
    r = _flat('r', n_cls)

    def _num(x):
        return None if x is None else round(float(x), 4)

    rows = []
    for i in sorted(names):
        rows.append({
            'idx': i,
            'class_en': names[i],
            'mAP50': _num(ap50[i]),
            'mAP50_95': _num(ap[i]),
            'precision': _num(p[i]),
            'recall': _num(r[i]),
        })
    rows.sort(key=lambda x: (-(x['mAP50'] or 0)))

    out = ROOT / 'output'
    out.mkdir(exist_ok=True)
    stamp = f'{datetime.now():%Y%m%d_%H%M%S}'
    csv_path = out / f'per_class_val_{stamp}.csv'
    json_path = out / f'per_class_val_{stamp}.json'
    md_path = out / f'per_class_val_{stamp}.md'

    with csv_path.open('w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    payload = {
        'weights': args.weights,
        'data': args.data,
        'imgsz': args.imgsz,
        'seconds': round(dt, 1),
        'overall': {
            'mAP50': round(float(m.box.map50), 4),
            'mAP50_95': round(float(m.box.map), 4),
            'precision': round(float(m.box.mp), 4),
            'recall': round(float(m.box.mr), 4),
        },
        'per_class': rows,
        'ge_0.95_count': sum(1 for x in rows if (x['mAP50'] or 0) >= 0.95),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    lines = [
        f'# 每类验证指标（{stamp}）',
        '',
        f'- 权重: `{args.weights}`',
        f'- 数据: `{args.data}`（imgsz={args.imgsz}, batch={args.batch}, device={args.device}）',
        f'- 用时: {dt:.1f}s，整体 mAP50={payload["overall"]["mAP50"]}, mAP50-95={payload["overall"]["mAP50_95"]}',
        f'- mAP50 ≥ 0.95 的类别数: **{payload["ge_0.95_count"]}**',
        '',
        '| 排名 | 类别(EN) | mAP50 | mAP50-95 | Precision | Recall |',
        '| --- | --- | --- | --- | --- | --- |',
    ]
    for rank, x in enumerate(rows, 1):
        lines.append(
            f'| {rank} | {x["class_en"]} | {x["mAP50"]} | {x["mAP50_95"]} | '
            f'{x["precision"]} | {x["recall"]} |'
        )
    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    print(f'[{dt:.1f}s] overall mAP50={payload["overall"]["mAP50"]} '
          f'mAP50-95={payload["overall"]["mAP50_95"]}')
    print(f'per-class mAP50 >= 0.95 : {payload["ge_0.95_count"]} 类')
    for x in rows[:12]:
        print(f'  {x["mAP50"]:<7} {x["class_en"]}')
    print(f'\nwrote: {csv_path}\n       {json_path}\n       {md_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
