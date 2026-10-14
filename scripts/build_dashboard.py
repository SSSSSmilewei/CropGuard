# -*- coding: utf-8 -*-
"""生成「数据看板」快照：全部来自真实产物，网页 /dashboard 直接读取。

    python scripts/build_dashboard.py                       # 默认路径
    python scripts/build_dashboard.py --data D:/x/dataset_full/data.yaml --samples D:/x/pictures20

产出（output/dashboard/）：
    snapshot.json   训练曲线、验证集逐类 mAP、20 张实拍样本实测、RAG 评测、自检结果
    thumbs/*.jpg    样本缩略图（最长边 240px）

各步骤互相独立：某一项的输入找不到（比如这台机器没有数据集），就在快照里标注"未生成"并继续，
看板对应区块会显示原因，而不是整页报错。
"""
import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import cv2  # noqa: E402
import yaml  # noqa: E402

OUT = os.path.join(ROOT, 'output', 'dashboard')
THUMBS = os.path.join(OUT, 'thumbs')


def log(msg):
    print(f'[看板] {msg}', flush=True)


def load_cfg():
    with open(os.path.join(ROOT, 'config', 'configs.yaml'), encoding='utf-8') as f:
        return yaml.safe_load(f)


def short(path):
    """给网页显示的路径：项目内用相对路径；项目外只留最后 4 段，不把本机目录结构写进看板。"""
    p = os.path.abspath(path)
    if p.startswith(ROOT + os.sep):
        return os.path.relpath(p, ROOT).replace(os.sep, '/')
    keep = 2 if os.path.isdir(p) else 4
    return '/'.join(p.replace('\\', '/').split('/')[-keep:])


def pick_device(dev):
    try:
        import torch
        if str(dev).startswith('cuda') and not torch.cuda.is_available():
            return 'cpu'
    except ImportError:
        return 'cpu'
    return dev


# ---------------------------------------------------------------- 训练曲线
def read_results_csv(path):
    if not path or not os.path.isfile(path):
        return {'available': False, 'reason': f'找不到 {path}'}
    with open(path, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    norm = [{k.strip(): v.strip() for k, v in r.items() if k} for r in rows]

    def col(name):
        return [round(float(r[name]), 5) for r in norm if r.get(name) not in (None, '')]

    keys = {
        'epoch': 'epoch',
        'map50': 'metrics/mAP50(B)', 'map50_95': 'metrics/mAP50-95(B)',
        'precision': 'metrics/precision(B)', 'recall': 'metrics/recall(B)',
        'train_box': 'train/box_loss', 'train_cls': 'train/cls_loss', 'train_dfl': 'train/dfl_loss',
        'val_box': 'val/box_loss', 'val_cls': 'val/cls_loss', 'val_dfl': 'val/dfl_loss',
    }
    out = {'available': True, 'source': short(path)}
    for k, name in keys.items():
        out[k] = [int(v) for v in col(name)] if k == 'epoch' else col(name)
    m = out['map50']
    best = max(range(len(m)), key=lambda i: m[i]) if m else None
    out['best_epoch'] = out['epoch'][best] if best is not None else None
    return out


# ---------------------------------------------------------------- 验证集逐类 mAP
def count_images(d):
    if not d or not os.path.isdir(d):
        return 0
    n = 0
    for ext in ('jpg', 'jpeg', 'png', 'bmp', 'webp'):
        n += len(glob.glob(os.path.join(d, f'*.{ext}')))
    return n


def validate(model, data_yaml, device, imgsz, batch):
    if not data_yaml or not os.path.isfile(data_yaml):
        return {'available': False, 'reason': f'找不到数据集配置 {data_yaml}'}
    with open(data_yaml, encoding='utf-8') as f:
        d = yaml.safe_load(f)
    # data.yaml 里的 path 常常是训练机的绝对路径（D:/...），换到当前这份数据集所在目录
    base = os.path.dirname(os.path.abspath(data_yaml))
    d['path'] = base
    train_dir = os.path.join(base, d.get('train', 'images/train'))
    val_dir = os.path.join(base, d.get('val', 'images/val'))
    tmp = tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False, encoding='utf-8',
                                      dir=os.path.join(ROOT, 'output'))
    yaml.safe_dump(d, tmp, allow_unicode=True)
    tmp.close()
    log(f'验证集评估：{val_dir}（{count_images(val_dir)} 张，device={device}，CPU 上约几分钟）')
    t0 = time.time()
    try:
        m = model.val(data=tmp.name, imgsz=imgsz, batch=batch, device=device, split='val',
                      plots=False, verbose=False, save_json=False,
                      project=os.path.join(ROOT, 'output'), name='_dashboard_val', exist_ok=True)
    finally:
        os.unlink(tmp.name)
    names = model.names
    box = m.box
    per = []
    for i, cls in enumerate(box.ap_class_index):
        cls = int(cls)
        per.append({'id': cls, 'name': names[cls],
                    'ap50': round(float(box.ap50[i]), 4), 'ap50_95': round(float(box.ap[i]), 4),
                    'p': round(float(box.p[i]), 4), 'r': round(float(box.r[i]), 4)})
    per.sort(key=lambda x: -x['ap50'])
    return {
        'available': True,
        'map50': round(float(box.map50), 4), 'map50_95': round(float(box.map), 4),
        'precision': round(float(box.mp), 4), 'recall': round(float(box.mr), 4),
        'classes': per, 'num_classes': len(names),
        'train_images': count_images(train_dir), 'val_images': count_images(val_dir),
        'elapsed_s': round(time.time() - t0, 1),
        'source': short(data_yaml),
    }


# ---------------------------------------------------------------- 实拍样本实测
_NAME_RE = re.compile(r'^\d+_(.+?)_conf[\d.]+_')


def expected_of(filename):
    """比赛样本文件名形如 0022_Potosiabre_vitarsis_conf0.89_IP025000510.jpg，中间段就是正确类别。"""
    m = _NAME_RE.match(os.path.basename(filename))
    return m.group(1) if m else None


def sample_test(model, folder, device, imgsz, conf, cn):
    files = sorted(f for f in glob.glob(os.path.join(folder or '', '*'))
                   if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp')))
    if not files:
        return {'available': False, 'reason': f'样本目录为空或不存在：{folder}'}
    os.makedirs(THUMBS, exist_ok=True)
    for old in glob.glob(os.path.join(THUMBS, '*.jpg')):
        os.remove(old)
    model.predict(files[0], imgsz=imgsz, conf=conf, device=device, verbose=False)   # 预热，不计时
    items, t_all = [], time.time()
    for i, f in enumerate(files, 1):
        img = cv2.imread(f)
        if img is None:
            continue
        t0 = time.time()
        r = model.predict(img, imgsz=imgsz, conf=conf, device=device, verbose=False)[0]
        ms = (time.time() - t0) * 1000
        boxes = r.boxes
        if len(boxes):
            k = int(boxes.conf.argmax())
            pred, pconf = model.names[int(boxes.cls[k])], float(boxes.conf[k])
        else:
            pred, pconf = None, 0.0
        exp = expected_of(f)
        h, w = img.shape[:2]
        s = 240 / max(h, w)
        thumb = f'{i:02d}.jpg'
        cv2.imwrite(os.path.join(THUMBS, thumb), cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s)))),
                    [cv2.IMWRITE_JPEG_QUALITY, 82])
        items.append({
            'no': i, 'file': os.path.basename(f), 'thumb': thumb,
            'expected': exp, 'expected_cn': cn.get(exp, exp) if exp else None,
            'pred': pred, 'pred_cn': cn.get(pred, pred) if pred else None,
            'conf': round(pconf, 4), 'boxes': int(len(boxes)), 'ms': round(ms, 1),
            'correct': (exp is not None and pred == exp),
        })
    total_s = time.time() - t_all
    labeled = [x for x in items if x['expected']]
    return {
        'available': True, 'folder': short(folder),
        'count': len(items), 'labeled': len(labeled),
        'correct': sum(1 for x in labeled if x['correct']),
        'avg_ms': round(sum(x['ms'] for x in items) / max(1, len(items)), 1),
        'total_s': round(total_s, 2), 'conf': conf, 'imgsz': imgsz, 'device': device,
        'items': items,
    }


# ---------------------------------------------------------------- RAG 评测 / 自检
def run_ask_eval():
    path = os.path.join(OUT, '_ask_eval.json')
    p = subprocess.run([sys.executable, 'scripts/ask_eval.py', '--json', path],
                       cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if not os.path.isfile(path):
        return {'available': False, 'reason': (p.stderr or p.stdout)[-300:]}
    with open(path, encoding='utf-8') as f:
        res = json.load(f)
    os.remove(path)
    try:
        from llm.retriever import Retriever
        res['kb'] = Retriever().stats()
    except Exception as exc:
        res['kb'] = {'error': str(exc)}
    res['available'] = True
    return res


def run_tests():
    p = subprocess.run([sys.executable, 'tests/run_tests.py'], cwd=ROOT, capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    out = (p.stdout or '') + (p.stderr or '')
    m = re.search(r'=== (\d+) passed, (\d+) failed(?:, (\d+) skipped)? ===', out)
    if not m:
        return {'available': False, 'reason': out[-300:]}
    return {'available': True, 'passed': int(m.group(1)), 'failed': int(m.group(2)),
            'skipped': int(m.group(3) or 0), 'exit_code': p.returncode}


# ---------------------------------------------------------------- 主流程
def main():
    cfg = load_cfg()
    weights = cfg['MODEL']['WEIGHT']
    ap = argparse.ArgumentParser(description='生成数据看板快照（output/dashboard/snapshot.json）')
    ap.add_argument('--weights', default=weights)
    ap.add_argument('--data', default='dataset_full/data.yaml', help='数据集 data.yaml（验证集逐类 mAP）')
    ap.add_argument('--samples', default='pictures20', help='实拍样本目录（文件名含正确类别）')
    ap.add_argument('--results', default='', help='训练 results.csv（默认取权重所在训练目录）')
    ap.add_argument('--device', default=str(cfg['MODEL'].get('DEVICE', 'cpu')))
    ap.add_argument('--batch', type=int, default=16)
    ap.add_argument('--skip-val', action='store_true', help='跳过验证集评估（最慢的一步）')
    ap.add_argument('--skip-tests', action='store_true', help='跳过单元测试')
    args = ap.parse_args()

    from ultralytics import YOLO
    device = pick_device(args.device)
    imgsz = int(cfg['MODEL'].get('IMGSZ', 640))
    conf = float(cfg['MODEL'].get('CONF', 0.4))
    cn = cfg.get('CONFIG', {}).get('chinese_name', {}) or {}
    os.makedirs(OUT, exist_ok=True)

    prev = {}
    snap_path = os.path.join(OUT, 'snapshot.json')
    if os.path.isfile(snap_path):
        with open(snap_path, encoding='utf-8') as f:
            prev = json.load(f)

    model = YOLO(args.weights)
    results_csv = args.results or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(args.weights))),
                                               'results.csv')
    snap = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'model': {'weights': args.weights, 'run': os.path.basename(os.path.dirname(os.path.dirname(args.weights))),
                  'num_classes': len(model.names), 'imgsz': imgsz, 'conf': conf, 'device': device,
                  'names': {str(k): v for k, v in model.names.items()},
                  'chinese': {v: cn.get(v, v) for v in model.names.values()}},
    }
    log('读取训练曲线')
    snap['training'] = read_results_csv(results_csv)
    if args.skip_val and prev.get('validation', {}).get('available'):
        log('跳过验证集评估，沿用上次结果')
        snap['validation'] = dict(prev['validation'], source=short(prev['validation'].get('source') or ''))
    elif args.skip_val:
        snap['validation'] = {'available': False, 'reason': '本次用 --skip-val 跳过'}
    else:
        snap['validation'] = validate(model, args.data, device, imgsz, args.batch)
    log('实拍样本实测')
    snap['samples'] = sample_test(model, args.samples, device, imgsz, conf, cn)
    log('RAG 评测')
    snap['rag'] = run_ask_eval()
    if args.skip_tests:
        snap['tests'] = prev.get('tests') or {'available': False, 'reason': '本次用 --skip-tests 跳过'}
    else:
        log('单元测试（约 1~2 分钟）')
        snap['tests'] = run_tests()

    with open(snap_path, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    s = snap['samples']
    v = snap['validation']
    log(f'完成 → {snap_path}')
    if v.get('available'):
        log(f"验证集 mAP@0.5 = {v['map50']:.3f}  mAP@0.5:0.95 = {v['map50_95']:.3f}")
    if s.get('available'):
        log(f"实拍样本 {s['correct']}/{s['labeled']}  平均 {s['avg_ms']} ms/张  总 {s['total_s']} s")


if __name__ == '__main__':
    main()
