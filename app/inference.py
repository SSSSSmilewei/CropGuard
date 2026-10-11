# -*- coding: utf-8 -*-
"""推理与风险联动：检测、格式化、防治建议、共享推理泵。

所有函数都假设 `app.state` 已完成初始化（模型、反馈设备、相机配置）。
"""
import asyncio
import base64
import threading
import time
import traceback
from datetime import datetime

import cv2
import numpy as np

from llm import knowledge_base
from tool.tools import format_data, draw_info, assess_risk
from app.state import (
    yolo_model, device, imgsz, conf_thres, chinese_name,
    spray, feedback, cfg_spray, cfg_camera, cfg_cameras,
    _CAM_SOURCES, _pump_lock, _pump_state, _last_result,
    _record_history,
)


# ---------------------------------------------------------------- 单次推理
def _predict_and_format(img, conf=None):
    """检测 + 风险评估 + 结果图，返回统一 JSON 结构（供 REST 与 WebSocket 复用）。"""
    if conf is None:
        conf = conf_thres
    t_start = time.time()
    results = yolo_model.predict(img, imgsz=imgsz, conf=conf, device=device)
    formatted = format_data(results)
    inference_time = round(time.time() - t_start, 3)

    risk_level, risk_color, risk_detail = assess_risk(formatted, img.shape[:2])

    result_img = draw_info(img.copy(), formatted)
    _, buffer = cv2.imencode('.jpg', result_img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    result_b64 = base64.b64encode(buffer).decode('utf-8')

    detections = []
    for r in formatted:
        cls_name = r[0]
        cn_name = chinese_name.get(cls_name, cls_name)
        detections.append({
            "class_name": cls_name,
            "chinese_name": cn_name,
            "confidence": round(r[1], 4),
            "bbox": [round(x, 1) for x in r[2]],
        })

    res = {
        "success": True,
        "count": len(detections),
        "detections": detections,
        "risk": {"level": risk_level, "detail": risk_detail},
        "inference_time": inference_time,
        "result_image": result_b64,
        "timestamp": datetime.now().isoformat(),
    }
    # 记下最近一次检测，供 /api/ask 在未显式传 context 时"结合当前虫情"回答
    _last_result["result"] = {"detections": detections,
                              "risk": res["risk"]}
    return res


def _kb_advice_from_result(res):
    """用检测结果拼知识库防治报告（秒回、离线、无网络依赖）。"""
    pests = [
        (d.get("class_name") or d.get("chinese_name"), float(d.get("confidence") or 0))
        for d in (res.get("detections") or [])
    ]
    risk = res.get("risk") or {}
    return knowledge_base.get_advice(pests, risk.get("level", ""), risk.get("detail", ""))


def _with_advice(res):
    """给检测结果挂上知识库版防治建议（失败静默，不影响检测本身）。

    注意：只挂在 /api/detect 与 /api/detect_b64 上，
    WebSocket 实时流那条路**不能挂**（每帧生成建议会拖垮推理）。
    """
    try:
        res["advice"] = _kb_advice_from_result(res)
        res["advice_source"] = "knowledge_base"
    except Exception:
        res["advice"] = ""
        res["advice_source"] = "none"
    return res


# ---------------------------------------------------------------- 风险联动
def _linkage(risk_level, detections, zone_group=None):
    """风险联动：语音播报 + 喷淋执行（均异步、失败静默、不阻塞推理）。

    zone_group: 触发该风险的片区对应分组（多路定点监测时由摄像头绑定）；
                None 时用 risk_map 配置的分组。
    返回是否已下发喷淋指令，用于历史记录。
    """
    names = [d.get('chinese_name') or d.get('class_name') for d in detections]

    mapping = cfg_spray.get('risk_map', {}).get(risk_level, {}) if cfg_spray.get('risk_map') else {}
    group = mapping.get('group')
    duration = mapping.get('duration', 0)

    # 片区定向：摄像头绑定了分组、且映射不是"全体"时，只喷该片区
    spray_group = zone_group if (zone_group and group and group != 'all') else group

    sprayed = False
    if risk_level in ('高风险', '中风险'):
        try:
            sprayed = spray.spray(risk_level, names, group_override=spray_group)
        except Exception:
            sprayed = False
    if sprayed:
        _record_history(risk_level, detections, group=spray_group, duration=duration, source='auto')

    # 语音播报：文案要与真实动作一致（"已给片区A喷淋3秒"），先算好再播
    if sprayed:
        zone_txt = '全体片区' if (spray_group or 'all') == 'all' else f'片区{spray_group}'
        spray_info = f'已给{zone_txt}喷淋{int(duration)}秒'
    else:
        spray_info = ''
    try:
        feedback.trigger(risk_level, names, '', spray_info=spray_info)
    except Exception:
        pass
    return sprayed


# ---------------------------------------------------------------- 共享推理泵（多客户端只跑一份推理）
async def _infer_pump(stop_event):
    """后台推理循环：按 infer_fps 从共享相机源取帧推理，结果供所有客户端读取。"""
    infer_fps = float(cfg_camera.get('infer_fps', 5) or 5)
    interval = 1.0 / max(infer_fps, 0.5)
    while not stop_event.is_set():
        item = None
        with _pump_lock:
            for key, src in _CAM_SOURCES.items():
                item = (key, src)
                break
            # 没有相机（比如 /ws/phone 只用手机画面）时退化为空转
            if not _CAM_SOURCES:
                item = None
        if item is None:
            await asyncio.sleep(0.3)
            continue
        key, src = item
        ok, frame = src.read()
        if not ok or frame is None:
            await asyncio.sleep(0.2)
            continue
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None, _predict_and_format, frame)
        except Exception:
            traceback.print_exc()
            await asyncio.sleep(0.5)
            continue
        zone_group = ''
        for c in cfg_cameras:
            if str(c.get('id', '')).strip().lower() == str(key[1]).strip().lower():
                zone_group = str(c.get('group', '') or '')
                break
        risk_level = result['risk']['level']
        if risk_level in ('高风险', '中风险'):
            await asyncio.get_running_loop().run_in_executor(
                None, _linkage, risk_level, result['detections'], zone_group)
        with _pump_lock:
            _pump_state['last'] = result
            _pump_state['last_ts'] = time.time()
            _pump_state['seq'] += 1
            _pump_state['count'] += 1
        await asyncio.sleep(interval)


def _ensure_pump():
    """确保推理泵在跑（在事件循环里调用）。"""
    with _pump_lock:
        task = _pump_state.get('task')
        if task is not None and not task.done():
            return task
        stop_event = asyncio.Event()
        _pump_state['stop'] = stop_event
        task = asyncio.create_task(_infer_pump(stop_event))
        _pump_state['task'] = task
        print('[INFO] 共享推理泵已启动', flush=True)
        return task


def _latest_result(max_age=None):
    """取共享推理的最新结果 (result, age)；age 过大视为过期。"""
    with _pump_lock:
        result = _pump_state.get('last')
        ts = _pump_state.get('last_ts') or 0.0
    age = time.time() - ts if ts else None
    if result is None:
        return None, None
    if max_age is not None and (age is None or age > max_age):
        return result, age
    return result, age
