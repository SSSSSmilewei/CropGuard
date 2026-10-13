"""对 real_testset20/ 里的真实样本逐张跑识别，导出结果表 + JSON。

用法:
    py -3.14 scripts/eval_real_testset.py                      # 默认权重 conf=0.25
    py -3.14 scripts/eval_real_testset.py --conf 0.25 --imgsz 640
    py -3.14 scripts/eval_real_testset.py --weights runs/train/pest27_final4/weights/best.pt

输出: real_testset20/eval_<时间戳>.csv / .json / .md
判对口径：Top1 类别 == 文件名里的类别（文件名形如 `01_光肩星天牛-Potosiabre_vitarsis_conf0.95.jpg`）。
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

# 类别名自带下划线 → 按「已知类别名」交替匹配，别用 `(.+)_conf` 那种贪婪写法
CLASS_ALT = '|'.join(sorted((re.escape(c) for c in PEST_KB), key=len, reverse=True))
FNAME_RE = re.compile(
    rf'^(?P<no>\d+)_(?P<cn>.+)-(?P<cls>{CLASS_ALT})_conf(?P<conf>[0-9.]+)\.jpg$',
    re.I,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=str(ROOT / 'real_testset20'))
    ap.add_argument('--weights', default=str(ROOT / 'runs/train/pest27_final4/weights/best.pt'))
    ap.add_argument('--imgsz', type=int, default=640)
    ap.add_argument('--conf', type=float, default=0.25)
    ap.add_argument('--device', default='cpu')
    args = ap.parse_args()

    from ultralytics import YOLO

    folder = Path(args.dir)
    imgs = sorted(p for p in folder.glob('*.jpg'))
    if not imgs:
        print(f'!! {folder} 里没有 jpg，先跑 scripts/pick_real_testset.py')
        return 1

    model = YOLO(args.weights)
    print(f'权重 {args.weights} | 图片 {len(imgs)} 张 | imgsz={args.imgsz} conf={args.conf} device={args.device}\n')

    rows, ok, total_ms = [], 0, 0.0
    for p in imgs:
        m = FNAME_RE.match(p.name)
        gt_en = m.group('cls') if m else ''
        gt_cn = PEST_KB.get(gt_en, {}).get('cn', m.group('cn') if m else '?')

        t0 = time.perf_counter()
        res = model.predict(str(p), imgsz=args.imgsz, conf=args.conf, device=args.device, verbose=False)[0]
        ms = (time.perf_counter() - t0) * 1000
        total_ms += ms

        dets = []
        for b in res.boxes:
            cls_en = res.names[int(b.cls)]
            dets.append({
                'class_en': cls_en,
                'class_cn': PEST_KB.get(cls_en, {}).get('cn', cls_en),
                'conf': round(float(b.conf), 4),
            })
        dets.sort(key=lambda d: -d['conf'])
        top = dets[0] if dets else None
        hit = bool(top and top['class_en'] == gt_en)
        ok += int(hit)

        rows.append({
            'file': p.name,
            'gt_class_en': gt_en,
            'gt_class_cn': gt_cn,
            'file_conf': m.group('conf') if m else '',
            'top1_class_en': top['class_en'] if top else '',
            'top1_class_cn': top['class_cn'] if top else '',
            'top1_conf': f'{top["conf"]:.4f}' if top else '',
            'hit': 'Y' if hit else 'N',
            'n_boxes': len(dets),
            'all_dets': '; '.join(f'{d["class_cn"]}:{d["conf"]:.2f}' for d in dets) or '(无检出)',
            'ms': f'{ms:.0f}',
        })
        flag = 'OK ' if hit else 'NG '
        print(f'{flag}{p.name:<52} → {rows[-1]["top1_class_cn"] or "(无)":<8} '
              f'{rows[-1]["top1_conf"] or "-":<7} {ms:.0f}ms')

    acc = ok / len(rows)
    stamp = f'{datetime.now():%Y%m%d_%H%M%S}'
    csv_path = folder / f'eval_{stamp}.csv'
    json_path = folder / f'eval_{stamp}.json'

    with csv_path.open('w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    payload = {
        'weights': args.weights,
        'imgsz': args.imgsz,
        'conf_thres': args.conf,
        'n': len(rows),
        'top1_hit': ok,
        'top1_acc': round(acc, 4),
        'total_ms': round(total_ms, 1),
        'avg_ms': round(total_ms / len(rows), 1),
        'rows': rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'\nTop1 命中 {ok}/{len(rows)} = {acc * 100:.1f}% | 总耗时 {total_ms / 1000:.1f}s '
          f'| 平均 {total_ms / len(rows):.0f} ms/张')
    print(f'wrote: {csv_path.name} / {json_path.name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
