"""
CropGuard Web API Server
102类农业害虫检测 REST API 服务
用于生产环境部署（Linux服务器/Docker）

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
from io import BytesIO

import cv2
import numpy as np

# 尝试导入FastAPI（可选依赖）
try:
    from fastapi import (FastAPI, File, UploadFile, Form, HTTPException, WebSocket,
                         WebSocketDisconnect, Request)
    from fastapi.responses import JSONResponse, HTMLResponse, Response
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
    cam_get_source, cam_release_source, cam_pool_state,
    spray_history, _pump_lock, _pump_state, _last_result, _record_history,
)
# 推理与风险联动
from app.inference import (
    _predict_and_format, _with_advice, _linkage,
    _ensure_pump, _latest_result,
)

# 防治建议：知识库秒出兜底 + RAG 接地生成（Ollama）
from llm import knowledge_base
# 问答网关（RAG + 防幻觉）：GUI 聊天 / 网页 / 手机端共用这一个入口
from llm import ai_gateway
# 页面渲染
from serve import mobile as mobile_page
from serve import pages as static_pages

# ==================== FastAPI App ====================
app = FastAPI(
    title="CropGuard - 农作物害虫智能检测系统",
    description="102类农业害虫检测 REST API",
    version="1.0.0"
)

@app.get("/", response_class=HTMLResponse)
async def index():
    """Web演示页面"""
    return static_pages.load('index')


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """演示数据看板（快照数据已内联在页面里，实时态复用同源 /api/* 与 /ws/stream）。

    快照由 scripts/build_dashboard.py 从真实产物生成；直接用浏览器打开
    serve/pages/dashboard.html 也能看（此时只有快照态，因为 file:// 跨域取不到接口）。
    """
    return static_pages.load('dashboard')


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

        return _with_advice(_predict_and_format(img, conf))

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
    conf = payload.get("conf", conf_thres)

    if not image_b64:
        raise HTTPException(status_code=400, detail="缺少 'image' 字段")

    # 去除 data:image/...;base64, 前缀
    if ',' in image_b64:
        image_b64 = image_b64.split(',', 1)[1]

    try:
        img_bytes = base64.b64decode(image_b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise HTTPException(status_code=400, detail="无法解码Base64图片")

        return _with_advice(_predict_and_format(img, conf))

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


@app.get("/stream", response_class=HTMLResponse)
async def stream_page():
    """移动端实时监测页（C/S Client，保留兼容）。"""
    return static_pages.load('stream')


# ==================== 手机端页面 /m ====================
_cfg_phone = config.get('PHONE', {}) or {}
# 真实监听端口（由 __main__ 里用 --port/--https-port 写入），
# 供 /m 页面与 /qr 生成正确的手机访问地址。
# https_on 只有 HTTPS 监听**真的**起来了才为 True：页面据此决定要不要升级到 HTTPS，
# 绝不能拿配置里的 8443 当"能用"（那样 http 页会给出一个打不开的死链）。
_srv_ports = {'http': None, 'https': None, 'https_on': False}


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


def _https_on():
    """HTTPS 监听是否真的在服务（不是"配置里写了 8443"）。"""
    return bool(_srv_ports.get('https_on'))


def _phone_ports(request_host_port=None):
    """返回 (http_port, https_port)。

    HTTP 端口优先取"真实运行端口"（`--port` 指定的那个），
    其次才用请求头里的端口 —— 这样用 `--port 8090` 启动时，
    手机页里内嵌的接口地址会自动跟着变成 8090（否则页面调接口会连错端口）。
    """
    https_port = int(_srv_ports.get('https') or _cfg_phone.get('https_port', 8443) or 8443)
    http_port = int(_srv_ports.get('http') or 0) or 8080
    if request_host_port:
        try:
            http_port = int(str(request_host_port).split(':')[-1])
        except Exception:
            pass
    return http_port, https_port


def _phone_url(ip=None, scheme=None):
    """手机端**唯一入口**地址（http/https 合一的那个）。

    HTTPS 可用就给 https（实时模式必须安全上下文），否则退回 http 拍照模式。
    """
    host = ip or (_lan_ips() or ['127.0.0.1'])[0]
    http_port, https_port = _phone_ports()
    if scheme is None:
        scheme = 'https' if _https_on() else 'http'
    port = https_port if scheme == 'https' else http_port
    return f'{scheme}://{host}:{port}/m'


@app.get("/api/lan")
async def lan_info(request=None):
    """给 PC 首页/手机页用：本机可被手机访问的地址清单。

    `https_enabled` 只在 HTTPS 监听真的起来后才为 true；未启用时
    `phone_urls_https` 返回空列表 —— 免得页面给出一个打不开的地址。
    """
    ips = _lan_ips()
    ports = _phone_ports()
    https_on = _https_on()
    first = (ips or ['127.0.0.1'])[0]
    return {
        "success": True,
        "hosts": ips,
        "http_port": ports[0],
        "https_port": ports[1],
        "https_enabled": https_on,
        "phone_url": _phone_url(first),
        "phone_url_http": f"http://{first}:{ports[0]}/m",
        "phone_urls": [f"http://{ip}:{ports[0]}/m" for ip in ips],
        "phone_urls_https": [f"https://{ip}:{ports[1]}/m" for ip in ips] if https_on else [],
    }


@app.get("/qr")
async def qr_image(url: str = None, size: int = 6):
    """把网址渲染成二维码 PNG（纯 PIL 手写实现，见 tool/qr_min.py）。

    现场用法：PC 首页把手机入口的二维码显示出来，手机一扫就进 /m，不用手输 IP。
    不传 url 时默认用"手机端唯一入口"（HTTPS 可用就是 https，扫码即实时模式）。
    """
    url = url or _phone_url()
    try:
        from io import BytesIO
        from tool.qr_min import to_pil
        img = to_pil(url, box_size=int(size or 6), border=3)
        buf = BytesIO()
        img.save(buf, format='PNG')
        return Response(content=buf.getvalue(), media_type='image/png')
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f'二维码生成失败: {exc}')


@app.get("/m", response_class=HTMLResponse)
async def mobile_home(request: Request):
    """手机会话页：拍照识别 / 实时识别 / 问答 / 喷洒控制 / 雾化控制（ESP32 直连）。"""
    host = (request.url.hostname or '')
    http_port, https_port = _phone_ports(request.url.port)
    mist_url = ''
    mist_targets = spray.mist_targets()
    if mist_targets:
        mist_url = str(mist_targets[0].get('url') or '')
    html = mobile_page.render(
        host=host, http_port=http_port, https_port=https_port,
        https_enabled=_https_on(),
        frame_interval_ms=int(_cfg_phone.get('frame_interval_ms', 400) or 400),
        upload_max_side=int(_cfg_phone.get('upload_max_side', 960) or 960),
        mist_url=mist_url,
        mist_max_sec=int(cfg_spray.get('max_duration', 5) or 5),
        mist_direct_sec=int(spray.direct_max_sec or 0),
    )
    return HTMLResponse(html)


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
            "will_refuse": (not chunks) or chunks[0]['score'] < float(_chat_cfg.get('refuse_below', 0.18)),
            "chunks": [{"id": c['id'], "title": c['title'], "type": c['type'],
                        "cn": c['cn'], "score": c['score'], "text": c['text'],
                        "source": c.get('source', '')} for c in chunks],
            "stats": r.stats(),
        }
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@app.post("/api/ask_command")
async def ask_command(payload: dict):
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

    allowed_groups = set(spray.http_targets.keys()) | {'all'}
    if parsed.get('group') and parsed['group'] not in allowed_groups:
        parsed.update(valid=False, reason=f'分组 {parsed["group"]} 不在白名单',
                      reply='该片区未配置喷洒节点，无法执行。')

    executed = False
    if bool(payload.get("execute")) and parsed.get('valid') and parsed.get('group'):
        if parsed.get('intent') == 'stop':
            executed = spray.stop(parsed['group'])
        else:
            executed = spray.manual_spray(parsed['group'], parsed['duration'])
        if executed:
            _record_history('语音指令喷洒', [], group=parsed['group'],
                            duration=parsed.get('duration') or 0,
                            source='phone-chat')
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


@app.post("/api/spray")
async def manual_spray(payload: dict):
    """手动喷淋端点（Client 按钮 / 语音指令确认后）。

    body: {"group": "all"|"g1"|"g2", "duration": 秒, "via": "web|phone|chat"}
    """
    group = payload.get("group", "all")
    via = str(payload.get("via") or "manual")
    max_duration = int(cfg_spray.get('max_duration', 5) or 5)
    try:
        duration = int(payload.get("duration", 2))
    except (TypeError, ValueError):
        duration = 2
    if duration > max_duration:
        duration = max_duration
    if duration <= 0:
        duration = 2
    ok = spray.manual_spray(group, duration)
    _record_history('手动喷淋', [], group=group, duration=duration, source='manual', via=via)
    return {
        "success": ok,
        "gateway_available": spray.available,
        "group": group,
        "duration": duration,
        "max_duration": max_duration,
    }


# ==================== 雾化控制（手写 sketch 固件接口） ====================
# 手写固件（sketch_oct12a.ino）的接口与项目固件不同：
#   GET /start?time=N 定时喷雾 / GET /startDirect 持续喷雾（不自停）/ GET /stop 停止
# 而且它**永远回 200**（连"雾化正在运行中，请先关闭"也是 200），所以适配层读响应体判成败
# （见 feedback/spray.py 的 _write_mist）。
#
# ⚠️ 这几个端点刻意用**普通 def**：内部会同步访问节点 HTTP，FastAPI 会把它丢进线程池，
#    不会阻塞事件循环把推理/推流一起拖慢（与 /api/ask 同一个理由）。

@app.get("/api/mist/status")
def mist_status(group: str = None):
    """读回雾化节点状态（GET 节点的状态页并解析"定时/持续/空闲"与剩余秒数）。

    连不上时**如实返回 reachable=false + 原因**，不静默（现场排查靠它）。
    """
    try:
        return {"success": True, **spray.mist_status(group or "all")}
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "success": False, "error": f"{type(exc).__name__}: {exc}"})


@app.post("/api/mist/start")
def mist_start(payload: dict):
    """定时喷雾：body {"seconds": 3, "group": "all"}。

    seconds 由后端按 SPRAY.max_duration 钳制（雾化片怕连续通电），返回里带 clamped 标记。
    """
    payload = payload or {}
    group = str(payload.get("group") or "all")
    try:
        seconds = int(payload.get("seconds", payload.get("duration", 3)))
    except (TypeError, ValueError):
        seconds = 3
    res = spray.mist_start(seconds, group)
    if res.get("success"):
        _record_history('雾化·定时', [], group=group, duration=res.get("duration") or 0,
                        source='mist', via='phone-mist')
    return {"success": bool(res.get("success")), **res}


@app.post("/api/mist/direct")
def mist_direct(payload: dict = None):
    """持续喷雾（固件的 /startDirect 不会自停）。

    服务器武装兜底计时器，SPRAY.direct_max_sec 秒后自动 GET /stop ——
    手机掉线、页面被关掉、人走开都不会让继电器一直吸合。
    """
    payload = payload or {}
    group = str(payload.get("group") or "all")
    res = spray.mist_start_direct(group)
    if res.get("success"):
        _record_history('雾化·持续', [], group=group, duration=None,
                        source='mist', via='phone-mist')
    return {"success": bool(res.get("success")), **res}


@app.post("/api/mist/stop")
def mist_stop(payload: dict = None):
    """停止雾化（同步等结果，并撤掉持续模式兜底计时器）。"""
    payload = payload or {}
    group = str(payload.get("group") or "all")
    res = spray.mist_stop(group)
    if res.get("success"):
        _record_history('雾化·停止', [], group=group, duration=None,
                        source='mist', via='phone-mist')
    return {"success": bool(res.get("success")), **res}


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
async def camera_restart(payload: dict = None):
    """手动强制重开相机（现场抢救用）：换 handle + 重建采集线程。"""
    payload = payload or {}
    cam_id = payload.get("cam")
    key = _camera_key(cam_id)
    src = _CAM_SOURCES.get(key)
    if src is None:
        # 还没人订阅过：直接开一个（同时顺便验证设备能不能开）
        source, _zone_group, zone_label = resolve_camera(cam_id)
        src = cam_get_source(key, source=source, name=zone_label or str(source), **_cam_kwargs())
        _CAM_SOURCES[key] = src
    ok = src.restart()
    return {"success": bool(ok), "key": str(key), "state": src.state()}


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

    try:
        # 注意：每次都调一次 get_source，保证引用计数与 finally 里的 release 一一对应
        cam = cam_get_source(key, source=source, name=zone_label or str(source), **_cam_kwargs())
        _CAM_SOURCES[key] = cam
    except Exception as exc:
        traceback.print_exc()
        await websocket.send_text(json.dumps(
            {"error": f"无法打开摄像头 {zone_label or source}: {exc}"},
            ensure_ascii=False))
        await websocket.close()
        return

    if not cam.wait_first_frame(timeout=float(cfg_camera.get('probe_timeout', 8.0) or 5.0)):
        st = cam.state()
        await websocket.send_text(json.dumps(
            {"error": f"无法打开摄像头 {zone_label or source}（{st.get('last_error') or '拿不到首帧'}）",
             "camera": st}, ensure_ascii=False))
        await websocket.close()
        cam_release_source(key)
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

            result, age = _latest_result()
            with _pump_lock:
                seq = _pump_state.get('seq', 0)
            if result is None or seq == last_seq:
                # 引擎还没产出结果：先把画面本身推给客户端
                now = time.time()
                if now - last_push >= 1.0 / stream_fps:
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    payload = {
                        "success": True, "count": 0, "detections": [],
                        "risk": {"level": "无风险", "detail": "正在推理中…"},
                        "result_image": base64.b64encode(buffer).decode('utf-8'),
                        "timestamp": datetime.now().isoformat(),
                        "camera": cam.state(),
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
        # 只减引用计数：最后一个订阅者离开才真正关设备
        cam_release_source(key)
        _CAM_SOURCES.pop(key, None)

# ==================== 手机端实时上传（二进制帧） ====================
@app.websocket("/ws/phone")
async def ws_phone(websocket: WebSocket):
    """手机摄像头实时识别：手机上传 JPEG 二进制帧，服务端只回检测 JSON。

    为什么不用 HTTP 轮询：手机 2~3 帧/秒上传，用 WebSocket 省掉每帧的握手开销，
    而且能天然做"单帧背压"（客户端收到结果才发下一帧）。
    为什么**不回传图像**：手机流量与延迟都金贵，检测框由前端自己叠在预览上
    —— 见 `serve/static/mobile.js` 的 `drawDetections()`（canvas 叠加，已实现）；
    bbox 是"上传那一帧"的绝对像素坐标，前端按 `sentFrame` 尺寸 + `object-fit:contain`
    的实际显示矩形映射（`fitRect` / `boxToViewRect`）。改这里要同步改前端。

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
                try:
                    _linkage(risk_level, result["detections"])
                except Exception:
                    pass
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


# ==================== HTTPS 启动辅助 ====================
def _port_busy(host, port):
    """preflight：这个端口能不能 bind。True=被占用/不可用。"""
    import socket as _socket
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        s.bind((host or '0.0.0.0', int(port)))
        return False
    except OSError:
        return True
    finally:
        try:
            s.close()
        except Exception:
            pass


def _https_selfcheck(port, timeout=8):
    """起完 HTTPS 后真发一次请求（跳过证书校验）。

    只看"线程还在跑"是不够的 —— 端口被占时 uvicorn 会静默退出，
    必须真连一次才能说 HTTPS 可用。
    """
    import ssl as _ssl
    import urllib.request
    try:
        ctx = _ssl._create_unverified_context()
        with urllib.request.urlopen(f'https://127.0.0.1:{int(port)}/api/health',
                                    context=ctx, timeout=timeout) as r:
            return True, f'HTTP {r.status}'
    except Exception as exc:
        return False, f'{type(exc).__name__}: {str(exc)[:120]}'


def _start_https(args):
    """起 HTTPS 监听：证书 → 端口 preflight → 线程 → 等就绪 → 自检。

    返回 (uvicorn.Server | None, 原因字符串)。失败时一定把已经起来的监听关掉，
    绝不让"8443 在听但 _srv_ports['https_on'] 是 False"这种自相矛盾的状态出现。
    """
    from tool.gen_cert import ensure_cert
    cert_file, key_file, err = ensure_cert(args.cert_dir, days=1095,
                                           extra_ips=list(args.cert_extra_ip or []))
    if err:
        return None, f'证书不可用（{err}）'
    if _port_busy(args.host, args.https_port):
        who = ''
        try:
            from tool.port_check import who_listens
            procs = who_listens(args.https_port)
            if procs:
                who = '，占用进程 PID=' + ', '.join(p[0] for p in procs)
        except Exception:
            pass
        return None, (f'HTTPS 端口 :{args.https_port} 已被占用{who}。'
                      f'处理：python tool/port_check.py --kill，或换 --https-port')

    errors = []
    try:
        cfg = uvicorn.Config(app, host=args.host, port=args.https_port,
                             ssl_keyfile=key_file, ssl_certfile=cert_file,
                             log_level='info')
    except Exception as exc:
        return None, f'uvicorn 配置失败: {type(exc).__name__}: {exc}'
    srv = uvicorn.Server(cfg)

    def _run():
        try:
            srv.run()
        except Exception as exc:                      # 进程/绑定级失败
            errors.append(f'{type(exc).__name__}: {exc}')

    threading.Thread(target=_run, name='HTTPS', daemon=True).start()
    deadline = time.time() + 8
    while time.time() < deadline and not getattr(srv, 'started', False) and not errors:
        time.sleep(0.1)

    def _shutdown(reason):
        try:
            srv.should_exit = True
        except Exception:
            pass
        return None, reason

    if errors:
        return _shutdown('HTTPS 线程启动失败：' + errors[0])
    if not getattr(srv, 'started', False):
        return _shutdown('8 秒内没就绪（端口被占 / 证书不被 ssl 接受，看上面的 uvicorn 日志）')
    ok, detail = _https_selfcheck(args.https_port)
    if not ok:
        return _shutdown(f'端口在听但自检失败：{detail}')
    return srv, ''


# ==================== 程序入口 ====================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CropGuard Web API Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument("--https", dest="https", action="store_true", default=True,
                        help="开 HTTPS（手机实时模式需要；默认已开，保留是为了兼容旧命令）")
    parser.add_argument("--no-https", dest="https", action="store_false",
                        help="只跑 HTTP（手机实时模式不可用，拍照模式照常）")
    parser.add_argument("--https-port", type=int,
                        default=int((config.get('PHONE', {}) or {}).get('https_port', 8443) or 8443),
                        help="HTTPS 端口")
    parser.add_argument("--cert-dir",
                        default=str((config.get('PHONE', {}) or {}).get('cert_dir', './config/certs')),
                        help="证书目录（不存在会自动生成自签证书）")
    parser.add_argument("--cert-extra-ip", action="append", default=[],
                        help="额外写进证书 SAN 的 IP（手机走别的网段时用，可多次）")
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
    https_wanted = bool(args.https)
    if args.reload and '--https' not in sys.argv:
        # 热重载下 uvicorn 会另起子进程，HTTPS 线程会失控 → 开发模式默认只跑 HTTP
        https_wanted = False
        _https_reason = '开发模式 --reload 下默认不开（要开就显式写 --https）'
    else:
        _https_reason = '已用 --no-https 关闭' if not https_wanted else ''
    _srv_ports['https'] = int(args.https_port) if https_wanted else None

    if https_wanted and int(args.https_port) == int(args.port):
        print(f"[ERROR] --https-port({args.https_port}) 与 --port({args.port}) 相同："
              f"一个端口只能二选一（TLS 或明文）。请换端口。", flush=True)
        sys.exit(2)

    if https_wanted:
        _https_server, _https_err = _start_https(args)
        _srv_ports['https_on'] = _https_server is not None
    else:
        _srv_ports['https_on'] = False
        _https_err = _https_reason

    _listeners = f"http://{args.host}:{args.port}"
    if _srv_ports['https_on']:
        _listeners += f"  +  https://{args.host}:{args.https_port}"
    _canon = _phone_url(_ips[0])
    if _srv_ports['https_on']:
        _https_note = '（HTTPS 就绪：实时摄像头 / 拍照 / 问答 / 雾化 都在同一个页面里）'
    else:
        _https_note = f'⚠ HTTPS 未启用：{_https_err} → 手机实时模式不可用，拍照模式照常'
    print(f"""
============================================================
  CropGuard - 农作物害虫智能检测系统 Web API
============================================================
  模型: {weights_path}
  类别数: {len(yolo_model.names)}
  设备: {device}
  喷淋: transport={spray.transport} available={spray.available}
  语音: engine={_fb_st['tts'].get('engine')} ready={_fb_st['tts'].get('ready')}
  监听: {_listeners}
  Web演示: http://{args.host}:{args.port}/
  数据看板: http://{args.host}:{args.port}/dashboard
  手机监测页(旧): http://{_ips[0]}:{args.port}/stream
  API文档: http://{args.host}:{args.port}/docs
------------------------------------------------------------
  手机会话页(唯一入口): {_canon}
  {_https_note}
  （http 打开也会自动升到上面这个地址；不想升级就加 ?http=1 留在 HTTP 拍照模式）
============================================================
""", flush=True)

    # HTTP 与 HTTPS 共享同一个 app（相机/模型/历史都是单实例）；HTTP 跑主线程，
    # HTTPS 由 _start_https 起的守护线程负责（见上面的 _srv_ports['https_on']）。
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
