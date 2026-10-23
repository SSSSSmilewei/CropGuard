"""把仓库里的真实产物汇总成看板快照，写进 serve/pages/dashboard.html 的标记区。

用法:
    py -3.14 scripts/build_dashboard.py                    # 生成（含 20 张缩略图）
    py -3.14 scripts/build_dashboard.py --no-thumbs        # 不嵌缩略图，产物更小
    py -3.14 scripts/build_dashboard.py --thumb-width 320 --thumb-quality 78
    py -3.14 scripts/build_dashboard.py --print-json       # 顺带把快照打到 stdout
    py -3.14 scripts/build_dashboard.py --allow-missing    # 缺来源时保留旧快照（默认直接报错退出）

只改写两个标记之间的内容：

    <!-- CG-SNAPSHOT:BEGIN -->
    <script id="cgSnapshot" type="application/json">{ ... }</script>
    <!-- CG-SNAPSHOT:END -->

标记区之外（手写的结构/样式/脚本）**逐字节保留**，所以可以放心手改页面。

数据来源（都在本机、都可复核）：
* output/per_class_val_*.json      每类 + 整体指标（scripts/per_class_val.py 产物）
* runs/train/pest27_final4/results.csv   训练收敛曲线（每轮）
* real_testset20/eval_*.json       20 张真实样本实测（scripts/eval_real_testset.py 产物）
* real_testset20/*.jpg             缩略图（内嵌为 data URI，页面才能离线单文件打开）
* dataset_full/data.yaml + images/labels 计数
* llm/knowledge_base.py PEST_KB    中文类名（与 README 的 27 类对照表同源）
* config/configs.yaml              喷淋/相机/RAG 运行口径

⚠️ Windows 上 cv2.imread 读不了中文路径，所以缩略图用 np.fromfile + cv2.imdecode（踩过）。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAGE = ROOT / 'serve' / 'pages' / 'dashboard.html'
REGION_RE = re.compile(
    r'(<!--\s*CG-SNAPSHOT:BEGIN\s*-->)(.*?)(<!--\s*CG-SNAPSHOT:END\s*-->)',
    re.S,
)
SNIPPET = '<script id="cgSnapshot" type="application/json">{payload}</script>'

DEFAULT_WEIGHTS = 'runs/train/pest27_final4/weights/best.pt'


# ------------------------------------------------------------------ 小工具
def rel(p) -> str:
    """转成相对仓库根的展示路径（数据来源脚注用）。"""
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace('\\', '/')
    except Exception:
        return str(p)


def latest(pattern: str):
    """取匹配到的最新一份（按文件名排序，时间戳在名字里）。"""
    hits = sorted(ROOT.glob(pattern))
    return hits[-1] if hits else None


def load_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        raise SystemExit(f'[ERROR] 解析 {what} 失败: {path}\n        {type(exc).__name__}: {exc}')


def read_csv_rows(path: Path):
    with path.open('r', encoding='utf-8-sig', newline='') as fh:
        rd = csv.DictReader(fh)
        # 训练导出的表头带前导空格（'         epoch'），必须 strip
        keys = [(k or '').strip() for k in (rd.fieldnames or [])]
        rows = []
        for raw in rd:
            rows.append({(k or '').strip(): (v or '').strip() for k, v in raw.items()})
    return keys, rows


def fnum(v, default=None):
    try:
        if v is None or v == '':
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ 各部分快照
def grab_per_class(path: Path, cn_map: dict) -> tuple[dict, list]:
    data = load_json(path, '每类验证报告')
    per = []
    for r in data.get('per_class') or []:
        en = r.get('class_en') or ''
        per.append({
            'idx': int(r.get('idx', -1)),
            'en': en,
            'cn': cn_map.get(en, en),
            'mAP50': fnum(r.get('mAP50')),
            'mAP50_95': fnum(r.get('mAP50_95')),
            'precision': fnum(r.get('precision')),
            'recall': fnum(r.get('recall')),
        })
    overall = dict(data.get('overall') or {})
    overall['ge_0.95_count'] = data.get('ge_0.95_count')
    overall['val_seconds'] = data.get('seconds')
    model = {
        'weights': rel(data.get('weights') or DEFAULT_WEIGHTS),
        'imgsz': data.get('imgsz'),
        'device': 'cpu',
    }
    return {'overall': overall, 'per_class': per, 'model': model}, data


def grab_curves(path: Path) -> dict:
    _, rows = read_csv_rows(path)
    cols = {
        'epoch': 'epoch',
        'train_box': 'train/box_loss',
        'train_cls': 'train/cls_loss',
        'train_dfl': 'train/dfl_loss',
        'val_box': 'val/box_loss',
        'mAP50': 'metrics/mAP50(B)',
        'mAP50_95': 'metrics/mAP50-95(B)',
        'precision': 'metrics/precision(B)',
        'recall': 'metrics/recall(B)',
    }
    out = {k: [] for k in cols}
    for r in rows:
        for key, col in cols.items():
            v = fnum(r.get(col))
            if key == 'epoch':
                out[key].append(int(v) if v is not None else None)
            else:
                out[key].append(round(v, 6) if v is not None else None)
    return out


def grab_dataset() -> dict:
    import yaml
    yml_path = ROOT / 'dataset_full' / 'data.yaml'
    names = {}
    if yml_path.exists():
        try:
            names = (yaml.safe_load(yml_path.read_text(encoding='utf-8')) or {}).get('names') or {}
        except Exception as exc:
            print(f'[WARN] 读 data.yaml 失败（{type(exc).__name__}: {exc}），类别数按每类报告计')
    counts = {}
    for split in ('train', 'val'):
        n_img = n_lab = 0
        for sub, exts in (('images', ('.jpg', '.jpeg', '.png', '.bmp')), ('labels', ('.txt',))):
            d = ROOT / 'dataset_full' / sub / split
            if d.is_dir():
                n = sum(1 for f in d.iterdir() if f.is_file() and f.suffix.lower() in exts)
            else:
                n = 0
            if sub == 'images':
                n_img = n
            else:
                n_lab = n
        counts[split] = {'images': n_img, 'labels': n_lab}
    return {
        'root': 'dataset_full',
        'classes': len(names) or None,
        'train': counts['train']['images'],
        'val': counts['val']['images'],
        'train_labels': counts['train']['labels'],
        'val_labels': counts['val']['labels'],
    }


def make_thumb(path: Path, width: int, quality: int):
    """读图 → 等比缩到 width 宽 → data URI；失败返回 None（页面显示"缩略图缺失"）。"""
    try:
        import cv2
        import numpy as np
        buf = np.fromfile(str(path), dtype=np.uint8)   # 中文路径必须走 fromfile
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            return None
        h, w = img.shape[:2]
        if w > width:
            img = cv2.resize(img, (width, max(1, int(round(h * width / w)))), interpolation=cv2.INTER_AREA)
        ok, enc = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            return None
        import base64
        return 'data:image/jpeg;base64,' + base64.b64encode(enc.tobytes()).decode('ascii')
    except Exception as exc:
        print(f'[WARN] 缩略图失败 {path.name}: {type(exc).__name__}: {exc}')
        return None


def grab_testset(path: Path, img_dir: Path, thumbs: bool, thumb_w: int, thumb_q: int) -> dict:
    data = load_json(path, '真实样本实测')
    rows = []
    n_thumb = 0
    for i, r in enumerate(data.get('rows') or [], start=1):
        file = r.get('file') or ''
        thumb = None
        if thumbs and file:
            thumb = make_thumb(img_dir / file, thumb_w, thumb_q)
            n_thumb += int(bool(thumb))
        rows.append({
            'no': i,
            'file': file,
            'en': r.get('gt_class_en') or '',
            'cn': r.get('gt_class_cn') or r.get('gt_class_en') or '',
            'file_conf': fnum(r.get('file_conf')),
            'top1_cn': r.get('top1_class_cn') or '',
            'top1_conf': fnum(r.get('top1_conf')),
            'hit': str(r.get('hit', '')).upper().startswith('Y'),
            'n_boxes': int(fnum(r.get('n_boxes'), 0) or 0),
            'ms': int(fnum(r.get('ms'), 0) or 0),
            'thumb': thumb,
        })
    out = {
        'n': data.get('n') or len(rows),
        'top1_hit': data.get('top1_hit'),
        'top1_acc': data.get('top1_acc'),
        'total_ms': data.get('total_ms'),
        'avg_ms': data.get('avg_ms'),
        'conf': data.get('conf_thres'),
        'imgsz': data.get('imgsz'),
        'rows': rows,
    }
    return out, n_thumb


def grab_runtime() -> dict:
    import yaml
    path = ROOT / 'config' / 'configs.yaml'
    cfg = {}
    if path.exists():
        try:
            cfg = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        except Exception as exc:
            print(f'[WARN] 读 configs.yaml 失败: {type(exc).__name__}: {exc}')
    spray = cfg.get('SPRAY') or {}
    cam = cfg.get('CAMERA') or {}
    chat = cfg.get('CHAT') or {}
    rag = cfg.get('RAG') or {}
    targets = []
    for t in (spray.get('http_targets') or []):
        if isinstance(t, dict):
            targets.append({'group': t.get('group'), 'url': t.get('url'), 'protocol': t.get('protocol')})
    return {
        'spray_transport': spray.get('transport'),
        'http_targets': targets,
        'risk_map': {k: {'group': (v or {}).get('group'), 'duration': (v or {}).get('duration')}
                     for k, v in (spray.get('risk_map') or {}).items()},
        'nodes': spray.get('nodes') or [],
        'max_duration': spray.get('max_duration'),
        'direct_max_sec': spray.get('direct_max_sec'),
        'min_interval': spray.get('min_interval'),
        'infer_fps': cam.get('infer_fps'),
        'stream_fps': cam.get('stream_fps'),
        'refuse_below': chat.get('refuse_below'),
        'rag_top_k': rag.get('top_k'),
        'model_conf': (cfg.get('MODEL') or {}).get('CONF'),
        'model_device_cfg': (cfg.get('MODEL') or {}).get('DEVICE'),
    }


# ------------------------------------------------------------------ 组装 / 写入
def build_snapshot(args) -> dict:
    from llm.knowledge_base import PEST_KB
    cn_map = {k: (v or {}).get('cn', k) for k, v in PEST_KB.items()}

    per_path = Path(args.per_class) if args.per_class else latest('output/per_class_val_*.json')
    csv_path = Path(args.results) if args.results else (ROOT / 'runs/train/pest27_final4/results.csv')
    eval_path = Path(args.eval) if args.eval else latest('real_testset20/eval_*.json')

    missing = [str(p) for p, name in ((per_path, '每类验证报告'), (csv_path, '训练 results.csv'), (eval_path, '实测 eval.json'))
               if not p or not Path(p).exists()]
    if missing:
        msg = '[ERROR] 缺少必要来源：\n        - ' + '\n        - '.join(missing)
        if args.allow_missing:
            print(msg + '\n        --allow-missing：保留旧快照，不改写标记区。')
            return None
        raise SystemExit(msg + '\n        提示：先跑 scripts/per_class_val.py / scripts/eval_real_testset.py，'
                               '或用 --allow-missing 保留旧快照。')

    per_block, per_raw = grab_per_class(per_path, cn_map)
    curves = grab_curves(csv_path)
    dataset = grab_dataset()
    if not dataset.get('classes'):
        dataset['classes'] = len(per_block['per_class'])

    thumbs = not args.no_thumbs
    testset, n_thumb = grab_testset(eval_path, ROOT / 'real_testset20', thumbs, args.thumb_width, args.thumb_quality)

    model = per_block['model']
    model['epochs'] = len([e for e in curves.get('epoch', []) if e is not None])
    model['conf'] = testset.get('conf')
    if not model.get('imgsz'):
        model['imgsz'] = testset.get('imgsz')

    print(f'  每类指标 : {rel(per_path)}  （{len(per_block["per_class"])} 类，mAP50={per_block["overall"].get("mAP50")}）')
    print(f'  收敛曲线 : {rel(csv_path)}  （{model["epochs"]} 轮）')
    print(f'  实测样本 : {rel(eval_path)}  （{testset["top1_hit"]}/{testset["n"]} 命中，'
          f'平均 {testset["avg_ms"]} ms；缩略图 {n_thumb}/{len(testset["rows"])} 张）')
    print(f'  数据集   : dataset_full  train={dataset["train"]} / val={dataset["val"]}  （标注 {dataset["train_labels"]}/{dataset["val_labels"]}）')

    runtime = grab_runtime()
    return {
        'generated_at': f'{datetime.now():%Y-%m-%d %H:%M:%S}',
        'placeholder': False,
        'sources': {
            'per_class': rel(per_path),
            'results_csv': rel(csv_path),
            'eval_json': rel(eval_path),
            'data_yaml': 'dataset_full/data.yaml',
        },
        'model': model,
        'dataset': dataset,
        'overall': per_block['overall'],
        'per_class': per_block['per_class'],
        'curves': curves,
        'testset': testset,
        'runtime': runtime,
        'hardware': {'nodes': (runtime.get('nodes') or [])},
    }


def render_page(page_text: str, snapshot: dict) -> str:
    m = REGION_RE.search(page_text)
    if not m:
        raise SystemExit(f'[ERROR] {rel(PAGE)} 里找不到 CG-SNAPSHOT 标记区，无法写入。')
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    body = '\n' + SNIPPET.replace('{payload}', payload) + '\n'
    return page_text[:m.start(2)] + body + page_text[m.end(2):]


def main() -> int:
    ap = argparse.ArgumentParser(description='生成看板快照（只改写 dashboard.html 的标记区）')
    ap.add_argument('--out', default=str(PAGE), help='目标页面（默认 serve/pages/dashboard.html）')
    ap.add_argument('--per-class', default=None, help='每类验证 JSON（默认取 output/ 下最新）')
    ap.add_argument('--results', default=None, help='训练 results.csv')
    ap.add_argument('--eval', default=None, help='实测 eval JSON（默认取 real_testset20/ 下最新）')
    ap.add_argument('--thumb-width', type=int, default=240, help='缩略图宽度（像素）')
    ap.add_argument('--thumb-quality', type=int, default=72, help='缩略图 JPEG 质量')
    ap.add_argument('--no-thumbs', action='store_true', help='不内嵌缩略图（产物更小，卡片显示"缩略图缺失"）')
    ap.add_argument('--allow-missing', action='store_true', help='来源缺失时保留旧快照，不报错')
    ap.add_argument('--print-json', action='store_true', help='把快照 JSON 打到 stdout')
    args = ap.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    if not out.exists():
        raise SystemExit(f'[ERROR] 页面不存在: {out}')

    print(f'构建看板快照 → {rel(out)}')
    snapshot = build_snapshot(args)
    if snapshot is None:
        return 0

    page = out.read_text(encoding='utf-8')
    new_page = render_page(page, snapshot)
    out.write_text(new_page, encoding='utf-8')

    size = out.stat().st_size
    thumb_bytes = sum(len(r['thumb'] or '') for r in snapshot['testset']['rows'])
    print(f'  最终页面 : {size / 1024:.0f} KB（其中缩略图 data URI 约 {thumb_bytes / 1024:.0f} KB）')
    if args.print_json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
