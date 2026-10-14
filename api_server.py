"""
CropGuard Web API Server
27 类农作物害虫检测：REST/WebSocket 接口 + 前端单页应用（web/dist）托管

启动方式:
    python api_server.py
    # 或指定端口:
    python api_server.py --port 8080 --host 0.0.0.0
"""

import os
import sys
import json
import time
import asyncio
import base64
import threading
import traceback
from datetime import datetime
import cv2
import numpy as np

# 尝试导入FastAPI（可选依赖）
try:
    from fastapi import (FastAPI, File, UploadFile, Form, HTTPException, WebSocket,
                         WebSocketDisconnect, Request)
    from fastapi.responses import JSONResponse, Response
    from fastapi.concurrency import run_in_threadpool
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    HAS_WEB = True
except ImportError:
    HAS_WEB = False
    print("[WARN] FastAPI/uvicorn not installed. Install: pip install fastapi uvicorn python-multipart websockets")

# 应用级共享状态（模型、反馈设备、相机池、历史记录）
from app.state import (
    config, yolo_model, device, weights_path, conf_thres, imgsz,
    feedback, spray, cfg_spray, cfg_cameras, camera_num, cfg_camera,
    _CAM_SOURCES, _cam_kwargs, _camera_key, resolve_camera,
    _cam_subscribe, _cam_unsubscribe,
    cam_pool_state,
    spray_history, _last_result, _record_history,
)
# 推理与风险联动
from app.inference import (
    _predict_and_format, _with_advice, _linkage,
    _ensure_pump, _latest_result, _remember_sample,
)

# 防治建议：知识库秒出兜底 + RAG 接地生成（Ollama）
from llm import knowledge_base
# 问答网关（RAG + 防幻觉）：GUI 聊天 / 网页 / 手机端共用这一个入口
from llm import ai_gateway
from llm.retriever import gate_score
# 前端单页应用（web/dist）
from serve import spa

# ==================== FastAPI App ====================
app = FastAPI(
    title="CropGuard - 农作物害虫智能检测系统",
    description="27 类农作物害虫检测 REST API",
    version="2.0.0"
)

# ---------------- 前端页面：/ /stream /ask /spray /system /m 都交给前端路由 ----------------
if os.path.isdir(spa.ASSETS):
    app.mount("/assets", StaticFiles(directory=spa.ASSETS), name="assets")


def _spa_page():
    return spa.index_response()


for _path in spa.ROUTES:
    app.add_api_route(_path, _spa_page, methods=["GET"], include_in_schema=False)


@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    return spa.static_file('favicon.svg') or Response(status_code=404)


@app.get("/api/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "model_loaded": True,
        "classes": len(yolo_model.names),
        "device": device,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/info")
async def info():
    """模型信息"""
    chinese_name = config.get('CONFIG', {}).get('chinese_name', {})
    return {
        "model": weights_path,
        "device": device,
        "num_classes": len(yolo_model.names),
        "classes": {str(k): v for k, v in yolo_model.names.items()},
        "chinese_names": {k: chinese_name.get(v, v) for k, v in yolo_model.names.items()},
        "default_conf_threshold": conf_thres,
        "image_size": imgsz,
    }


@app.post("/api/detect")
async def detect(file: UploadFile = File(...), conf: float = Form(None)):
    """
    上传图片进行害虫检测
    - file: 图片文件 (multipart upload)
    - conf: 置信度阈值 (可选, 默认使用配置文件值)
    """
    if conf is None:
        conf = conf_thres

    try:
        # 读取图片
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise HTTPException(status_code=400, detail="无法解析图片文件")

        # 推理是 CPU/GPU 重活：丢线程池，别阻塞事件循环（否则实时流/WS 全部卡住）
        res = await run_in_threadpool(_predict_and_format, img, conf)
        _remember_sample(res)
        return _with_advice(res)

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/detect_b64")
async def detect_base64(payload: dict):
    """
    Base64图片检测
    - image: Base64编码的图片字符串
    - conf: 置信度阈值 (可选)
    """
    image_b64 = payload.get("image", "")
    try:
        conf = float(payload.get("conf", conf_thres) or conf_thres)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="conf 必须是 0~1 的数字")

    if not image_b64:
        raise HTTPException(status_code=400, detail="缺少 'image' 字段")

    # 去除 data:image/...;base64, 前缀
    if ',' in image_b64:
        image_b64 = image_b64.split(',', 1)[1]

    try:
        try:
            img_bytes = base64.b64decode(image_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="Base64 格式不正确")
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise HTTPException(status_code=400, detail="无法解码Base64图片")

        res = await run_in_threadpool(_predict_and_format, img, conf)
        _remember_sample(res)
        return _with_advice(res)

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.post("/api/advice")
def advice(payload: dict):
    """防治建议：统一走 RAG + 本地 Ollama（与 /api/ask、GUI 聊天同一入口）。

    body: {"detections": [...], "risk": {"level": "...", "detail": "..."}}
    返回: {"success", "source": "llm"|"knowledge_base"|"refused", "advice": "文本", ...}

    故意用普通 def（不是 async def）：FastAPI 会把它丢进线程池，
    避免本地大模型那几秒阻塞事件循环、把推理接口一起拖慢。
    """
    dets = payload.get("detections") or []
    risk = payload.get("risk") or {}
    if not dets:
        return {
            "success": True,
            "source": "knowledge_base",
            "advice": knowledge_base.NO_PEST_MSG,
        }
    names = "、".join(
        f"{d.get('chinese_name') or d.get('class_name')}"
        f"(置信度:{float(d.get('confidence') or 0):.2f})"
        for d in dets
    )
    question = f"检测到 {names}，风险等级 {risk.get('level', '')}，请给出防治建议。"
    try:
        res = ai_gateway.answer(question, context=payload)
    except Exception as exc:
        traceback.print_exc()
        return {
            "success": False,
            "source": "error",
            "advice": f"建议生成失败：{type(exc).__name__}: {str(exc)[:160]}",
        }
    # 保持旧字段 advice 兼容
    res["advice"] = res.pop("answer", "")
    return res


# ==================== 手机端页面 /m ====================
_cfg_phone = config.get('PHONE', {}) or {}
# 真实监听端口（由 __main__ 里用 --port/--https-port 写入），
# 供 /m 页面与 /qr 生成正确的手机访问地址
_srv_ports = {'http': None, 'https': None}


def _lan_ips():
    """列出本机局域网 IPv4（手机要用它访问服务器，现场直接打印出来）。"""
    ips = []
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))          # 不会真的发包，只为拿到默认出口网卡
            ips.append(s.getsockname()[0])
        except Exception:
            pass
        finally:
            s.close()
    except Exception:
        pass
    try:
        import socket
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith('127.') and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def _phone_ports(request_host_port=None):
    """返回 (http_port, https_port)。

    HTTP 端口优先取"真实运行端口"（`--port` 指定的那个），
    其次才用请求头里的端口 —— 这样用 `--port 8090` 启动时，
    手机页里内嵌的接口地址会自动跟着变成 8090（否则页面调接口会连错端口）。
    """
    https_port = int(_srv_ports.get('https') or _cfg_phone.get('https_port', 8443) or 8443)
    # 优先用真实运行端口（__main__ 写入的 --port）；
    # 只有拿不到时（如 uvicorn api_server:app 方式启动）才回退请求头端口。
    # ⚠️ 不能反过来：用 https 端口打开 /m 时，请求头端口是 8443，
    #    若用它当 HTTP 端口，页面里的 http 接口地址会全部连错。
    http_port = int(_srv_ports.get('http') or 0)
    if not http_port and request_host_port:
        try:
            http_port = int(str(request_host_port).split(':')[-1])
        except Exception:
            pass
    return http_port or 8080, https_port


@app.get("/api/lan")
async def lan_info():
    """给 PC 首页/手机页用：本机可被手机访问的地址清单。"""
    ips = _lan_ips()
    ports = _phone_ports()
    return {
        "success": True,
        "hosts": ips,
        "http_port": ports[0],
        "https_port": ports[1],
        "phone_urls": [f"http://{ip}:{ports[0]}/m" for ip in ips],
        "phone_urls_https": [f"https://{ip}:{ports[1]}/m" for ip in ips],
    }


@app.get("/qr")
async def qr_image(url: str = None, size: int = 6):
    """把网址渲染成二维码 PNG（纯 PIL 手写实现，见 tool/qr_min.py）。

    现场用法：PC 首页把手机入口的二维码显示出来，手机一扫就进 /m，不用手输 IP。
    """
    # 不传 url 时默认编码手机入口：HTTPS 已启用就编 https 地址（扫码直达安全页）
    if url is None:
        _http_port, _https_port = _phone_ports()
        if _srv_ports.get('https'):
            url = f"https://{(_lan_ips() or ['127.0.0.1'])[0]}:{_https_port}/m"
        else:
            url = f"http://{(_lan_ips() or ['127.0.0.1'])[0]}:{_http_port}/m"
    try:
        from io import BytesIO
        from tool.qr_min import to_pil
        img = to_pil(url, box_size=max(1, min(int(size or 6), 20)), border=3)
        buf = BytesIO()
        img.save(buf, format='PNG')
        return Response(content=buf.getvalue(), media_type='image/png')
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f'二维码生成失败: {exc}')


@app.get("/api/client_config")
async def client_config(request: Request):
    """前端运行参数（原先由服务端模板写进 /m 页面，现在统一走接口）。"""
    http_port, https_port = _phone_ports(request.url.port)
    cfg_eval = config.get('EVAL', {}) or {}
    risk_map = {}
    for level, m in (cfg_spray.get('risk_map') or {}).items():
        m = m or {}
        try:
            dur = int(m.get('duration') or 0)
        except (TypeError, ValueError):
            dur = 0
        risk_map[str(level)] = {"group": m.get('group'), "duration": dur}
    return {
        "http_port": http_port,
        "https_port": https_port if _srv_ports.get('https') else None,
        "frame_interval_ms": int(_cfg_phone.get('frame_interval_ms', 400) or 400),
        "upload_max_side": int(_cfg_phone.get('upload_max_side', 960) or 960),
        "conf_default": conf_thres,
        "imgsz": imgsz,
        "model": os.path.basename(os.path.dirname(os.path.dirname(str(weights_path)))) or str(weights_path),
        "max_spray": int(cfg_spray.get('max_duration', 5) or 5),
        "eval_target": int(cfg_eval.get('target_samples', 20) or 20),
        "eval_time_limit": int(cfg_eval.get('time_limit_sec', 180) or 180),
        "refuse_below": float((config.get('CHAT', {}) or {}).get('refuse_below', 0.18)),
        "risk_map": risk_map,
    }


# ==================== 数据看板（快照由 scripts/build_dashboard.py 从真实产物生成） ====================
_DASH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', 'dashboard')


@app.get("/api/dashboard")
def dashboard_snapshot():
    """看板快照：训练曲线、验证集逐类 mAP、实拍样本实测、RAG 评测、自检。没生成过就说明怎么生成。"""
    path = os.path.join(_DASH_DIR, 'snapshot.json')
    if not os.path.isfile(path):
        return {"available": False,
                "reason": "还没有生成看板快照：在项目根目录运行 python scripts/build_dashboard.py"}
    try:
        with open(path, encoding='utf-8') as f:
            snap = json.load(f)
    except Exception as exc:
        return {"available": False, "reason": f"快照文件读取失败：{exc}"}
    snap["available"] = True
    return snap


@app.get("/api/dashboard/thumb/{name}")
def dashboard_thumb(name: str):
    """样本缩略图。只认 build_dashboard.py 生成的 NN.jpg，不允许读别的路径。"""
    import re
    from fastapi.responses import FileResponse
    if not re.fullmatch(r'\d{1,4}\.jpg', name or ''):
        raise HTTPException(status_code=404)
    path = os.path.join(_DASH_DIR, 'thumbs', name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control': 'no-cache'})


# ==================== 本地大模型问答（RAG + 防幻觉） ====================
_chat_cfg = config.get('CHAT', {}) or {}
_rag_cfg = config.get('RAG', {}) or {}


@app.post("/api/ask")
def ask(payload: dict):
    """自由提问（网页 / 手机 / GUI 同一个网关）。

    body:
      {"question": "...",
       "history": [{"role":"user|assistant","content":"..."}],   # 可选
       "context": {"detections": [...], "risk": {...}}}          # 可选；缺省用最近一次检测

    返回：{"success","answer","source":"llm|knowledge_base|refused",
           "citations":[...],"engine","elapsed","guard":{...}}

    这里刻意用**普通 def**（不是 async def）：FastAPI 会丢进线程池执行，
    本地 7B 一次要几秒到几十秒，不能阻塞事件循环去拖慢推理与推流。
    """
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="缺少 'question' 字段")
    history = payload.get("history") or []
    context = payload.get("context") or None
    if context is None and _last_result.get("result"):
        # 没显式给上下文时，用最近一次检测结果，做到"结合当前虫情回答"
        context = _last_result["result"]
    try:
        return ai_gateway.answer(question, history=history, context=context)
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "success": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "source": "error", "answer": "问答服务异常，请稍后重试。",
        })


@app.get("/api/kb/search")
def kb_search(q: str, top_k: int = None):
    """只做检索（不调用大模型）：现场展示 RAG 召回与分数用。"""
    try:
        r = ai_gateway.get_retriever()
        chunks = r.search(q or '', top_k=int(top_k or _rag_cfg.get('top_k', 4)))
        return {
            "success": True,
            "question": q,
            "rewritten": r.rewrite(q or '')[0],
            "detected_pests": r.detect_pests(q or ''),
            "refuse_below": float(_chat_cfg.get('refuse_below', 0.18)),
            # 闸门真实判据是 gate_score（见 llm/retriever.gate_score），预览口径必须一致
            "gate_score": gate_score(chunks),
            "will_refuse": (not chunks) or gate_score(chunks) < float(_chat_cfg.get('refuse_below', 0.18)),
            "chunks": [{"id": c['id'], "title": c['title'], "type": c['type'],
                        "cn": c['cn'], "score": c['score'],
                        "raw_score": c.get('raw_score', c['score']),
                        "gate_score": c.get('gate_score', c.get('raw_score', c['score'])),
                        "text": c['text'],
                        "source": c.get('source', '')} for c in chunks],
            "stats": r.stats(),
        }
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@app.post("/api/ask_command")
def ask_command(payload: dict):
    """自然语言 → 喷洒意图（**默认只解析不执行**，需人工确认）。

    body: {"text": "给片区A喷3秒", "execute": false}
      * execute=false（默认）：只返回解析结果，前端弹确认按钮；
      * execute=true：确认后真正下发（等价于 /api/spray），并写历史。

    安全要点：大模型的自由文本永远不能直接驱动硬件；
    分组必须在白名单内、时长必须被钳制（SPRAY.max_duration）。
    """
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="缺少 'text' 字段")
    max_duration = int((cfg_spray.get('max_duration') or 5))
    parsed = ai_gateway.parse_command(text, max_duration=max_duration)

    # 白名单跨传输形态：http 用 http_targets，serial/mqtt 用 nodes 登记表（见 spray.allowed_groups）
    allowed_groups = spray.allowed_groups
    if parsed.get('group') and parsed['group'] not in allowed_groups:
        parsed.update(valid=False, reason=f'分组 {parsed["group"]} 不在白名单',
                      reply='该片区未配置喷洒节点，无法执行。')

    executed = False
    if bool(payload.get("execute")) and parsed.get('valid') and parsed.get('group'):
        # 同步等节点应答：executed=True 只代表指令**真的送达**，不是"已丢给后台线程"
        if parsed.get('intent') == 'stop':
            executed, reason = spray.stop_detail(parsed['group'])
        else:
            executed, reason = spray.manual_spray_detail(parsed['group'], parsed['duration'])
        if not executed and reason:
            parsed['reply'] = f'指令未送达：{reason}'
        if executed:
            _record_history('语音指令喷洒', [], group=parsed['group'],
                            duration=parsed.get('duration') or 0,
                            source='phone-chat', via='chat')
    parsed.update(executed=bool(executed), available=bool(spray.available))
    return {"success": True, **parsed}


@app.get("/api/feedback/status")
async def feedback_status():
    """语音/串口反馈状态：现场排查"到底响不响"用。"""
    try:
        return {"success": True, "feedback": feedback.status()}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/history")
async def history():
    """联动/喷淋历史回看。"""
    return {"history": spray_history}


def _check_group(group):
    """分组白名单：手动喷淋/停止与聊天指令同一口径（spray.allowed_groups）。"""
    group = str(group or 'all').strip()
    if group not in spray.allowed_groups:
        raise HTTPException(status_code=400,
                            detail=f"分组 {group} 不在白名单 {sorted(spray.allowed_groups)}")
    return group


@app.get("/api/spray/status")
def spray_status():
    """喷淋链路概况：页面据此渲染片区按钮（不再在前端写死 g1/g2）。

    available 只表示"链路已配置"；节点此刻在不在线看 nodes（http 节点 GET /status 探活，3 秒缓存）。
    普通 def：探活要等网络，丢线程池。
    """
    groups = sorted(g for g in spray.allowed_groups if g != 'all')
    return {
        "success": True,
        "available": bool(spray.available),
        "transport": spray.transport,
        "groups": groups,
        "max_duration": int(cfg_spray.get('max_duration', 5) or 5),
        "zones": [{"id": c.get('id'), "name": c.get('name') or c.get('id'),
                   "group": c.get('group')} for c in cfg_cameras],
        "nodes": spray.probe_nodes() if spray.enabled else [],
    }


@app.post("/api/spray")
def manual_spray(payload: dict):
    """手动喷淋端点（Client 按钮 / 语音指令确认后）。

    body: {"group": "all"|"g1"|"g2", "duration": 秒, "via": "web|phone|chat"}

    普通 def：下发走 HTTP/串口，可能阻塞到超时，丢线程池执行。
    """
    group = _check_group(payload.get("group", "all"))
    via = str(payload.get("via") or "manual")
    max_duration = int(cfg_spray.get('max_duration', 5) or 5)
    try:
        duration = int(payload.get("duration", 2))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="duration 必须是正整数（秒）")
    if duration <= 0:
        # 传 0/负数的语义是"别喷"，绝不能默默改成默认值去执行
        raise HTTPException(status_code=400, detail="duration 必须为正数；要停止喷淋请用 /api/spray/stop")
    if duration > max_duration:
        duration = max_duration
    # 同步等节点应答：success 只在指令真的送达时为 True（以前丢给后台线程就报成功）
    ok, reason = spray.manual_spray_detail(group, duration)
    if ok:
        _record_history('手动喷淋', [], group=group, duration=duration, source='manual', via=via)
    return {
        "success": ok,
        "reason": reason,
        "gateway_available": spray.available,
        "group": group,
        "duration": duration,
        "max_duration": max_duration,
    }


@app.post("/api/spray/stop")
def spray_stop(payload: dict = None):
    """立即停止喷淋（紧急停止入口）。

    body: {"group": "all"|"g1"|"g2"}（缺省 all）
    http 节点走固件 /stop；serial/mqtt 走 duration=0（固件协议：<=0 即停止）。
    """
    payload = payload or {}
    group = _check_group(payload.get("group", "all"))
    ok, reason = spray.stop_detail(group)
    _record_history('手动停止喷淋', [], group=group, duration=0, source='manual',
                    via=str(payload.get("via") or "manual"))
    return {"success": bool(ok), "reason": reason, "group": group,
            "gateway_available": spray.available}


@app.get("/api/camera/health")
async def camera_health(cam: str = None):
    """相机健康：状态/帧龄/重开次数/实测 fps。

    不传 cam 时返回整个相机池（多路片区时能一眼看到哪路死了）。
    """
    pool = cam_pool_state()
    if cam:
        return {"success": True, "key": str(_camera_key(cam)), "pool": pool}
    return {"success": True, "pool": pool, "camera_num": camera_num,
            "configured_zones": [c.get('id') for c in cfg_cameras]}


@app.post("/api/camera/restart")
def camera_restart(payload: dict = None):
    """手动强制重开相机（现场抢救用）：换 handle + 重建采集线程。

    普通 def：开设备/等首帧要好几秒，不能卡住事件循环。
    没人订阅时只做"能不能打开"的验证，用完即释放（不再泄漏一份引用计数）。
    """
    payload = payload or {}
    cam_id = payload.get("cam")
    key = _camera_key(cam_id)
    source, _zone_group, zone_label = resolve_camera(cam_id)
    src = _cam_subscribe(key, source=source, name=zone_label or str(source))
    try:
        ok = src.restart()
        src.wait_first_frame(timeout=3.0)
        return {"success": bool(ok), "key": str(key), "state": src.state()}
    finally:
        _cam_unsubscribe(key)


@app.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket):
    """摄像头实时流：共享采集 → 推理 → 推 JPEG + 结果 + 风险；中/高风险自动联动喷淋 + 语音。

    可选 query 参数 cam（片区 id，如 'A'/'B'）：多路定点监测时选择片区摄像头。

    与旧版本的区别（重要）：
    * 多个客户端（手机 + PC）共享同一个采集源，不再各开一个 VideoCapture；
    * 掉线/黑屏由看门狗自愈，客户端不会被卡死（只会收到 camera_down 提示）。
    """
    await websocket.accept()

    cam_id = websocket.query_params.get('cam') or websocket.query_params.get('zone')
    source, zone_group, zone_label = resolve_camera(cam_id)
    key = _camera_key(cam_id)

    loop = asyncio.get_running_loop()
    try:
        # 每个连接订阅一次，与 finally 里的退订一一对应。
        # 打开设备可能要好几秒（冷启动/多策略解析）→ 放线程池，别卡住其它连接
        cam = await loop.run_in_executor(
            None, lambda: _cam_subscribe(key, source=source, name=zone_label or str(source)))
    except Exception as exc:
        traceback.print_exc()
        await websocket.send_text(json.dumps(
            {"error": f"无法打开摄像头 {zone_label or source}: {exc}"},
            ensure_ascii=False))
        await websocket.close()
        return

    got = await loop.run_in_executor(
        None, cam.wait_first_frame, float(cfg_camera.get('probe_timeout', 8.0) or 5.0))
    if not got:
        st = cam.state()
        await websocket.send_text(json.dumps(
            {"error": f"无法打开摄像头 {zone_label or source}（{st.get('last_error') or '拿不到首帧'}）",
             "camera": st}, ensure_ascii=False))
        await websocket.close()
        _cam_unsubscribe(key)
        return

    stream_fps = float(cfg_camera.get('stream_fps', 15) or 15)
    # 共享推理泵：多个客户端只跑一份推理，避免 GPU 重复计算
    _ensure_pump()

    last_push = 0.0
    last_seq = -1
    try:
        while True:
            ok, frame = cam.read()
            if not ok or frame is None:
                # 看门狗正在自愈：告诉客户端一声，等帧，不退出
                st = cam.state()
                if st.get('state') != 'ok':
                    await websocket.send_text(json.dumps(
                        {"warning": "摄像头暂时无帧，正在自动重连",
                         "camera": st}, ensure_ascii=False))
                await asyncio.sleep(0.2)
                continue

            # 只读**本路相机**的推理结果：多片区时 A 区虫情不会出现在 B 区画面上
            result, age, seq = _latest_result(key)
            if result is None or seq == last_seq:
                # 两次推理之间（推流 15fps、推理 5fps）推最新画面 + **最近一次**检测结果。
                # 以前这里一律发"无风险 / 0 个目标"，页面上的风险等级在真实值与无风险之间来回闪。
                now = time.time()
                if now - last_push >= 1.0 / stream_fps:
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if result is not None:
                        last = {"count": result.get("count", 0),
                                "detections": result.get("detections") or [],
                                "risk": result.get("risk")}
                    else:
                        last = {"count": 0, "detections": [],
                                "risk": {"level": "无风险", "detail": "正在推理中…"}}
                    payload = {
                        "success": True, **last,
                        "result_image": base64.b64encode(buffer).decode('utf-8'),
                        "image_size": [int(frame.shape[1]), int(frame.shape[0])],
                        "timestamp": datetime.now().isoformat(),
                        "camera": cam.state(),
                        "result_age": round(age, 2) if age is not None else None,
                    }
                    if zone_label:
                        payload["zone"] = zone_label
                    await websocket.send_text(json.dumps(payload, ensure_ascii=False))
                    last_push = now
                await asyncio.sleep(0.02)
                continue

            now = time.time()
            if now - last_push >= 1.0 / stream_fps:
                payload = dict(result)
                if zone_label:
                    payload["zone"] = zone_label
                payload["camera"] = cam.state()
                payload["result_age"] = round(age, 2) if age is not None else None
                await websocket.send_text(json.dumps(payload, ensure_ascii=False))
                last_push = now
                last_seq = seq

            await asyncio.sleep(0.005)
    except WebSocketDisconnect:
        pass
    except Exception:
        traceback.print_exc()
    finally:
        # 只减引用计数：最后一个订阅者离开才真正关设备、才从推理泵里摘掉。
        # （旧代码第一个客户端断开就把 key 从 _CAM_SOURCES 删了，另一个客户端还在看，
        #   推理泵却从此不再推理这一路 —— 画面还在、检测框永远不动。）
        _cam_unsubscribe(key)

# ==================== 手机端实时上传（二进制帧） ====================
@app.websocket("/ws/phone")
async def ws_phone(websocket: WebSocket):
    """手机摄像头实时识别：手机上传 JPEG 二进制帧，服务端只回检测 JSON。

    为什么不用 HTTP 轮询：手机 2~3 帧/秒上传，用 WebSocket 省掉每帧的握手开销，
    而且能天然做"单帧背压"（客户端收到结果才发下一帧）。
    为什么**不回传图像**：手机流量与延迟都金贵，检测框由前端自己叠在预览上。

    协议：客户端每帧发一个二进制消息（JPEG/PNG 原始字节）；
         服务端回文本 JSON：{success, count, detections, risk, elapsed, ts}
         出问题时回 {"error": "..."} 或 {"warning": "..."}。
    """
    await websocket.accept()
    n_frames = 0
    try:
        while True:
            msg = await websocket.receive()
            if msg.get('type') == 'websocket.disconnect':
                break
            data = msg.get('bytes')
            if not data:
                # 文本消息：当作心跳/控制
                txt = msg.get('text') or ''
                if txt.strip() in ('ping', '"ping"'):
                    await websocket.send_text(json.dumps({"pong": True}))
                continue

            nparr = np.frombuffer(data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                await websocket.send_text(json.dumps(
                    {"error": "无法解析手机上传的图像帧"}, ensure_ascii=False))
                continue

            t0 = time.time()
            try:
                result = await asyncio.get_running_loop().run_in_executor(
                    None, _predict_and_format, img)
            except Exception as exc:
                traceback.print_exc()
                await websocket.send_text(json.dumps(
                    {"error": f"推理失败: {exc}"}, ensure_ascii=False))
                continue

            n_frames += 1
            payload = {
                "success": True,
                "count": result["count"],
                "detections": result["detections"],
                "risk": result["risk"],
                "elapsed": round(time.time() - t0, 3),
                "frame_no": n_frames,
                "ts": datetime.now().strftime('%H:%M:%S'),
            }
            # 手机实时流同样做风险联动（语音 + 喷淋），与定点相机一致的口径
            risk_level = result["risk"]["level"]
            if risk_level in ('高风险', '中风险'):
                # 联动里有喷淋 HTTP 下发（可能阻塞到超时）→ 不等它，先把结果回给手机
                asyncio.get_running_loop().run_in_executor(
                    None, _linkage, risk_level, result["detections"])
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    except Exception:
        traceback.print_exc()
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ==================== 程序入口 ====================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CropGuard Web API Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument("--https", action="store_true", default=True,
                        help="监听 HTTPS 端口（默认已开启；手机入口打印 https 地址，"
                             "getUserMedia 实时模式需要）")
    parser.add_argument("--no-https", action="store_false", dest="https",
                        help="只监听 HTTP，不启 HTTPS（手机实时识别将不可用）")
    parser.add_argument("--https-port", type=int,
                        default=int((config.get('PHONE', {}) or {}).get('https_port', 8443) or 8443),
                        help="HTTPS 端口")
    parser.add_argument("--cert-dir",
                        default=str((config.get('PHONE', {}) or {}).get('cert_dir', './config/certs')),
                        help="证书目录（不存在会自动生成自签证书）")
    args = parser.parse_args()

    if not HAS_WEB:
        print("[ERROR] 需要安装 FastAPI 和 uvicorn:")
        print("  pip install fastapi uvicorn python-multipart")
        sys.exit(1)

    _ips = _lan_ips() or ['<本机IP>']
    _fb_st = feedback.status()
    # 把真实端口告诉页面层：这样 `--port 8090` 启动时，手机页里内嵌的
    # 接口地址会自动跟着变成 8090（否则页面会去连 8080，调接口全失败）
    _srv_ports['http'] = int(args.port)

    # 先确保证书可用、再打印入口 —— 保证打印出来的手机地址真实可访问。
    # 证书生成失败时如实降级为 HTTP（手机页打印 http 地址，实时模式不可用）。
    _cert_file = _key_file = None
    if args.https:
        from tool.gen_cert import ensure_cert
        _cert_file, _key_file, _err = ensure_cert(args.cert_dir)
        if _err:
            print(f"[WARN] HTTPS 证书不可用（{_err}）；本次只启动 HTTP，"
                  f"手机页打印 http 地址（实时模式不可用）。", flush=True)
            args.https = False
    _srv_ports['https'] = int(args.https_port) if args.https else None

    # 手机入口协议跟真实监听走：HTTPS 起来了就打印 https
    if args.https:
        _phone_scheme, _phone_port = 'https', int(args.https_port)
    else:
        _phone_scheme, _phone_port = 'http', int(args.port)

    print(f"""
============================================================
  CropGuard - 农作物害虫智能检测系统 Web API
============================================================
  模型: {weights_path}
  类别数: {len(yolo_model.names)}
  设备: {device}
  喷淋: transport={spray.transport} available={spray.available}
  语音: engine={_fb_st['tts'].get('engine')} ready={_fb_st['tts'].get('ready')}
  服务地址: http://{args.host}:{args.port}
  Web演示: http://{args.host}:{args.port}/
  手机会话页: {_phone_scheme}://{_ips[0]}:{_phone_port}/m
  手机监测页: {_phone_scheme}://{_ips[0]}:{_phone_port}/stream
  API文档: http://{args.host}:{args.port}/docs
============================================================
""", flush=True)

    if not args.https:
        uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    else:
        # HTTP 与 HTTPS 同时监听（共享同一个 app：相机/模型/历史都是单实例）
        print(f"[INFO] HTTPS 证书: {_cert_file}", flush=True)
        print(f"[INFO] 手机实时模式: https://{_ips[0]}:{args.https_port}/m"
              f"（首次访问会提示证书不受信任，选「继续访问」即可）", flush=True)
        http_server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port))
        https_server = uvicorn.Server(uvicorn.Config(
            app, host=args.host, port=args.https_port,
            ssl_keyfile=_key_file, ssl_certfile=_cert_file))
        threading.Thread(target=https_server.run, name='HTTPS', daemon=True).start()
        http_server.run()
