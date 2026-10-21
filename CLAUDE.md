# CropGuard 农智云 害虫检测系统

## 项目位置
- 工作目录: `<项目根目录>`（下文示例统一写作 `D:\CropGuard`）
- GitHub源码(仅代码): `<参考仓库>\Pest-detection-master`
- GitHub仓库: https://github.com/Stara-AI/Pest-detection
- 本项目仓库(开源): https://github.com/Sun-0810-yh/CropGuard（公开，含 best.pt，数据集未上传）
  - ⚠️ 2026-10-08 清理删掉了被 git 跟踪的 runs/train/pest27_final4/weights/best.onnx（与 睿抗国赛项目—农智云/best.onnx 同一份）。要恢复公开仓库里的 ONNX：`git restore runs/train/pest27_final4/weights/best.onnx`，或对比赛目录那份 `git add -f`
- 测试子仓库(公开，可独立克隆运行): https://github.com/Sun-0810-yh/CropGuard_Test
  - 内容 = `tests/`(迷你框架，当前 171 条用例) + `scripts/ask_eval.py` + 被测模块(`feedback/ llm/ tool/ config/ prompts/ main.py`)；
    不含权重/数据集/`serve/`；本地源在 `_dist/CropGuard_Test/`（已加进主仓库 .gitignore）
  - 缺 `ultralytics`/`PyQt5` 时 `test_gui_adapter_has_full_interface` 走 `requires()` → SKIP（59 passed + 1 skipped，退出码 0）

## Python 环境
- GPU环境: `<conda根>\envs\pest-gpu\python.exe`（示例 `D:\Miniconda\envs\pest-gpu\python.exe`）
- 系统Python: `<系统Python>\python.exe` (3.14, CPU PyTorch)
- Conda管家: `<conda根>`（示例 `D:\Miniconda`）
- PyCharm解释器: 右下角选 pest-gpu

## 竞赛背景 (2026 睿抗 CAIR赛道)
- 省赛评分: 20张实拍图全对(35分) + 180秒内跑完(15分) + 评估报告含Loss/mAP收敛曲线(10分) + GUI(10分) + PPT(15分)
- 平台部署: 只上传 best.onnx，必须 imgsz=640（480 会失败）
- 20张比赛图: `<比赛图目录>\pictures20\`（自行挑选，全部来自原始实拍池）
- 平台实拍问题: 相纸打印 + 摄像头拍照导致置信度从 0.8 掉到 0.45；斜着放比正着放置信度更高
- 时间线: 省赛一等奖，已晋级 2026 睿抗 CAIR 国赛（总决赛）

## 数据集 (当前)
- 27类精选: dataset_full/（从102类筛出，阈值每类≥150训练图）
- 训练/验证: 11,876 / 2,046
- data.yaml: dataset_full/data.yaml
- 遗留: dataset_102/（102类原始数据集，已停用但保留）

## 训练状态 (当前)
- 最佳模型: runs/train/pest27_final4/weights/best.pt
- mAP@0.5: 76.0%（整体 mAP50=0.7601 / mAP50-95=0.4899，precision=0.692 / recall=0.765）
- **每类 mAP50 ≥ 95% 的 8 类**（2026-10-13 复验，脚本 `scripts/per_class_val.py`，报告 `output/per_class_val_20261013_120802.md`）:
  | 类别(EN) | 中文 | mAP50 |
  | --- | --- | --- |
  | Lycorma_delicatula | 斑衣蜡蝉 | 0.995 |
  | mole_cricket | 蝼蛄 | 0.9946 |
  | Cicadellidae | 叶蝉科 | 0.9856 |
  | rice_leaf_roller | 水稻卷叶螟 | 0.9842 |
  | Potosiabre_vitarsis | 光肩星天牛（KB 口径） | 0.9803 |
  | flea_beetle | 跳甲 | 0.9715 |
  | grub | 蛴螬 | 0.9627 |
  | Ampelophaga | 葡萄天蛾 | 0.9506 |
- 中英文全表: `docs/27类中英文对照.md`；真实样本测试集: `real_testset20/`（20 张，实测 Top1 20/20）
- ONNX: 睿抗国赛项目—农智云/best.onnx（640，平台可用；runs 下的重复副本已于 2026-10-08 删除，两份 SHA256 相同）
- 续训: python train_640.py --resume

## 关键文件
- 训练脚本: train_640.py（摄像头场景增强：亮度/色相/旋转±25°/透视/缩放；从头训练需 COCO 权重 yolov8s.pt）
- 翻拍续训: train_finetune.py（复制比赛图x3份加PRINT_前缀 + 强退化增强，15轮）
- 配置: config/configs.yaml（WEIGHT 已指向 pest27_final4；AI.active_model=local 本地 Ollama qwen2.5:7b，离线合规）
- GUI入口: main.py（PyCharm 运行或 `python main.py`），界面类 UI.py
- 推理工具: tool/tools.py
- 相机采集: tool/camera_source.py（**共享单例 + 看门狗自愈**；GUI/服务器/手机共用，别再加第二套 VideoCapture）
- 相机探针: tool/camera_probe.py（现场认索引）；独立命令行识别: tool/camera_detect.py
- 本地LLM: llm/local_llm.py（Ollama，不可用时降级 knowledge_base 兜底）
- AI 网关: llm/ai_gateway.py（**唯一 AI 出入口**：RAG 检索 → 接地提示词 → Ollama → 后校验）
- 检索/防幻觉: llm/retriever.py（TF-IDF 字符 n-gram）、llm/kb_chunks.py、llm/guard.py
- 接地提示词: prompts/templates/grounded_expert.txt（取代旧 1500 字"报告型"模板）
- 手机端页面: serve/mobile.py（`GET /m`，含「🌫 雾化控制」卡片）；二维码: tool/qr_min.py；证书: tool/gen_cert.py
- 演示看板: serve/pages/dashboard.html（`GET /dashboard`；**数据是内联快照，可 file:// 离线单文件打开**，
  由 scripts/build_dashboard.py 从真实产物生成，**只改写 `CG-SNAPSHOT` 标记区**；页面只读不碰硬件写接口）
- 信号反馈: feedback/feedback.py（播报语义）+ feedback/tts.py（**专用线程 + 多后端真校验**）
- 喷淋控制: feedback/spray.py（serial/http/mqtt + stop；http 目标分 `protocol: 'json'|'mist'`）
- 硬件固件: ESP32/（PlatformIO 工程，8 个 env，见 ESP32/README.md）
- 测试: tests/run_tests.py（内置迷你框架，零依赖；`python tests/run_tests.py`）
- RAG 评测: scripts/ask_eval.py（库内召回 / 库外拒答 / 越权指令拦截）
- 标本采购单: docs/真实昆虫采购单.md（商家版 20 只清单）+ docs/specimens_plan.csv（机读单一真源，
  与文档逐行一致，`tests/test_specimen_plan.py` 守着）
- 标本验收: scripts/screen_specimens.py（按采购单编号拍照 → OK/LOW/WRONG/NONE/NOFILE + 换货建议，
  主选不合格退出码 1；`--conf` 默认 0.4 对齐 GUI）

## 启动方式
- **解释器（本机实测）**：PATH 上的 `python` 是 3.12.10，**缺 cv2/torch，跑不了服务**；
  能用的是 `py -3.14`（`D:\Dev Env\Python\python.exe`，torch **2.12.0+cpu、无 CUDA**）。
  config 里 `MODEL.DEVICE: 'cuda:0'` → CPU 机器上必须覆盖：
  `$env:CG_DEVICE='cpu'; py -3.14 api_server.py`（`app/state.py` 读 `CG_DEVICE` 环境变量，
  所以**不用改配置**，GPU 机器上照旧走 `cuda:0`）。
- GUI: 运行 main.py（PyCharm 或 `python main.py`）
- Web + 手机端: `py -3.14 api_server.py`（PC 首页 + 看板 `/dashboard` + `/m` 手机页 + REST/WS）；
  **HTTPS 默认同开**（8443，自签证书自动生成/按当前 IP 自动重签），纯 HTTP 加 `--no-https`；`--https` 保留兼容
- 看板刷新快照: `py -3.14 scripts/build_dashboard.py`（默认带 20 张缩略图；`--no-thumbs` 产物更小）
- 启动横幅要确认：`Spray transport/http_targets`、`雾化节点(mist)=[...] 持续模式兜底=Ns`、
  `[CERT] ✅ SAN 已覆盖当前局域网 IP: X`、`手机会话页(唯一入口): https://<本机IP>:8443/m`
  （**手机端唯一地址**：http 打开会自动升到这里，`?http=1` 强制留在 HTTP 拍照模式；
  HTTPS 没起来时页面不会给 https 死链，并在横幅写明原因）
- 训练: `python train_640.py`（新建）或 `python train_640.py --resume`（续训）
- 喷淋联调: `python api_server.py`（**唯一**接 SprayController 的入口；GUI 只做语音+串口反馈）
- 测试: `python tests/run_tests.py`；RAG 评测: `python scripts/ask_eval.py`（`--llm` 才真调大模型）
- 固件: VSCode 打开 ESP32/ 目录（不是仓库根）→ PlatformIO 选 env → Upload

## 软件端最小闭环（2026-10-08 第二批 · 已实现并实测）
| 需求 | 落点 | 实测结论 |
| --- | --- | --- |
| 外接相机识别 | `tool/camera_source.py` + `api_server.ws_stream` | 无设备时如实报 `dead + last_error`，不静默；有设备走 DSHOW/MJPG |
| 语音只响一次 | `feedback/tts.py` | 根因＝pyttsx3 SAPI5 的 COM 回调跨线程（`_busy` 永真）+ `_speak_lock` 永锁 + 异常被吞；改**专用线程内建引擎 + 真出声校验 + 多后端兜底**；本机 `SAPI.SPVoice` 不可用、`System.Speech`(powershell) 可用，auto 自动选中；连续 3 句播报通过 |
| 摄像头卡死 | 同上（看门狗：无新帧/画面指纹不变 → 换 handle；跨客户端引用计数共享） | 无相机时 `/api/camera/health` 显示 dead；`POST /api/camera/restart` 现场抢救 |
| 用户自由提问 | `llm/ai_gateway.answer` → `POST /api/ask` + GUI 聊天（`ChatWorker`） | GUI 与网页同一答案；`/api/kb/search` 可现场展示召回 |
| 防幻觉 | 召回闸门(`CHAT.refuse_below`=0.18，低于阈值**不调模型**) + 接地提示词 + `temperature=0.2`/固定 seed + `llm/guard.py` 后校验 | 库外问题直接拒答；编造药名/剂量被标注"请核实" |
| RAG（原待定项→已做） | `llm/kb_chunks.py` + `llm/retriever.py` + `scripts/ask_eval.py` | 110 片段 / 27 类 / 61 别名；评测：库内召回 20/20、库外拒答 10/10、越权拦截 4/4 |
| 手机实时+拍照 | `serve/mobile.py`（`/m`）+ `WS /ws/phone` | 二进制帧上传实测 0.15s 回检测 JSON；拍照档纯 HTTP 可用（`capture` 不需要 HTTPS） |
| 手机提问 → 控制喷洒 | `POST /api/ask_command`（**只解析**）→ 人工确认 → `/api/spray` | 危险词拦截、"100 秒"钳到 5 秒、未指定片区拒绝；大模型绝不直接驱动硬件 |
| 测试 | `tests/`（迷你框架）+ `scripts/ask_eval.py` | 171 用例全绿（`py -3.14 tests/run_tests.py`，退出码 0）；ask_eval 三项 100% |

### 这一批踩过的坑（下次别重踩）
1. `python tests/run_tests.py` 时 runner 是 `__main__`，测试里 `from run_tests import ...` 是**另一个模块实例**
   → 装饰器状态必须放 `tests/_registry.py` 共享；
2. 测试写临时文件**不要用 `%TEMP%`**（沙箱可能只允许工作区写，实测 `cv2.imwrite` 报 permission denied），
   也不要用长路径 + `cv2.VideoWriter`（Windows 报 `CAP_IMAGES: can't find starting number`）→ 用工作区内短路径 + 图片序列；
3. 手写 QR 时**定时图案要最先放**（否则定位图案的分隔符会覆盖第 8 个模块），
   且**填充与掩码必须共用同一张"功能区"表**（分开判定会把格式信息区当数据取反，扫码器读不出）；
   本机 OpenCV 的 `QRCodeDetector` **本身失效**（连它自己 `QRCodeEncoder` 生成的码都解不出），别用它做验证；
4. `openssl.exe` 必须带 `-config`（本机是 `<conda根>\Library\ssl\openssl.cnf`），
   且 `-config` 要放在 `req` 子命令**后面**；`New-SelfSignedCertificate` 这条路在本机被策略拒绝；
5. 本机 `SAPI.SPVoice`（win32com / pyttsx3 都走它）建对象成功但 `Speak` 报 COM 错 →
   语音后端**必须做"真出声"校验**，不能只看对象是否创建成功；
6. 相机"设备不在"是常态（硬件没配齐），所有相机相关入口都要能在无设备时给出可读原因，不能抛异常。


## 手写 sketch 雾化接入（2026-10-12 · 已实现并实测）
用户自写的 Arduino 固件 `sketch_oct12a.ino`（继电器 GPIO22 + 模拟雾化板按键 GPIO23，
接手机热点 `vivoX300`）接口与项目 PlatformIO 固件不同。**服务器侧做协议适配，手机页经服务器控制**——
不改动已烧录的固件，也不让手机直连节点（沿用"节点只接受服务器指令"的拓扑）。

| 项 | 落点 | 说明 |
| --- | --- | --- |
| 接口协议 | `feedback/spray.py`（target 项 `protocol: 'json'\|'mist'`） | `mist` = `GET /start?time=N`（定时）/ `GET /startDirect`（持续）/ `GET /stop`；`json` = 项目固件 `POST /spray` + `POST /stop` |
| **"永远回 200"** | 同上 `_write_mist` | 该固件连"雾化正在运行中，请先关闭！"也回 200 → **必须读响应体判成败**，只看状态码会把"拒绝启动"当成功 |
| 持续模式兜底 | 同上 `_arm_direct_timer` / `_direct_timeout` | `/startDirect` 固件不自停 → 服务器 `SPRAY.direct_max_sec`（默认 **300s**）到点自动 `/stop`；人工停止、成功的定时喷雾都会撤掉计时器 |
| 节点寻址 | `SPRAY.http_targets` + `SPRAY.status_timeout` | 每项可写 `protocol`；mist 固件**无分组过滤**（片区隔离靠 IP 寻址），地址是占位 `192.168.43.61/62`，按节点串口打印的 IP 改 |
| 手机页 | `serve/templates/mobile.html` + `static/mobile.js` 的「🌫 雾化控制」卡片 | 定时喷雾（上限 5s，后端再钳）/ 持续喷雾（确认框写明兜底秒数）/ 停止 / 每 3s 拉状态显示「定时模式 剩余 Ns、持续模式（兜底 Ns）、空闲、离线+原因」/ 节点自带页面链接 |
| REST | `GET /api/mist/status`、`POST /api/mist/start`、`/api/mist/direct`、`/api/mist/stop` | 都用**普通 `def`**（FastAPI 丢线程池），不阻塞推理/推流事件循环 |
| 测试 | `tests/test_mist_protocol.py`（26 条） | 用**真 loopback HTTP 假节点**复刻固件脾气：钳制、"200 但拒绝"、兜底自动停、计时器撤销、json 协议回归、手机页渲染 |

既有入口同样能驱动 mist 节点：`POST /api/spray`（手机页 A/B 区按钮）、语音指令 `POST /api/ask_command`
与自动联动 `risk_map` 都按目标协议分派（对 mist 节点就是"定时喷雾 N 秒"语义）。

## 演示数据看板（2026-10-13 · 已实现并实测）
答辩/PPT 用的一屏看板，**两种形态同一份页面**：file:// 双击看内联快照（零联网请求），
经服务器打开则自动升为实时态（同源轮询 `/api/*`，实时画面按需订阅 `/ws/stream`）。

| 项 | 落点 | 说明 |
| --- | --- | --- |
| 页面 | `serve/pages/dashboard.html` + `api_server.py: GET /dashboard` | 快照 JSON 内联在 `CG-SNAPSHOT` 标记区；手写的结构/样式/脚本在标记区之外 |
| 生成器 | `scripts/build_dashboard.py` | 只改写标记区；来源：`output/per_class_val_*.json`、`runs/train/pest27_final4/results.csv`、`real_testset20/eval_*.json`、`dataset_full`、`llm/knowledge_base.PEST_KB`、`config/configs.yaml` |
| 内容 | — | KPI 卡 / Loss+mAP 收敛曲线（Canvas 手绘）/ 27 类 mAP50 条形（≥0.95 加★）/ 20 张实测（缩略图内嵌 data URI）/ 闭环与 RAG 口径 / 硬件拓扑 / 实时状态卡 + 实时画面 + 图片快检 + 喷淋历史 |
| 离线合规 | 无 CDN、无图表库、无外部脚本；唯一的 http 链接是 `127.0.0.1:8080` 回环（快照态提示"进入实时模式"） | 测试里硬性拦截外部依赖 |
| 安全边界 | **只读**：不提供喷淋/雾化启停按钮；唯一的 POST 是 `/api/detect` 图片快检 | 演示时不会误触发硬件 |
| 测试 | `tests/test_dashboard.py`（8 条） | 快照必须等于真实产物、离线合规、无写接口、路由已注册、生成器不动手写区、内嵌 JS 能解析 |

### 踩过的坑（别再重踩）
1. **可访问性/可达性**：file:// 下 `fetch('/api/health')` 必然失败（跨域）→ 快照态；
   实时态**必须同源**（经 `/dashboard` 访问），所以刻意**不加 CORS 中间件**（不为演示放开 `origin: null`）。
2. **快照里带点的 key 不能在 JS 里点出来**：`ge_0.95_count` 写成 `o.ge_0.95_count` 是**语法错误**，
   整个 IIFE 不执行 → 页面只剩静态外壳（KPI/曲线/20 张样本全空），而 CSS 看着一切正常，极易误判成"数据没生成"。
   → 用 `o['ge_0.95_count']`；并且加了 `node --check` 的内嵌 JS 语法用例（没装 node 就 SKIP）。
3. **CV2 读中文路径**：`cv2.imread` 在 Windows 读不了 `01_光肩星天牛-….jpg` → 缩略图必须
   `np.fromfile` + `cv2.imdecode`。
4. **实时画面别自动开**：GUI（main.py）与服务器是两个进程，各自占同一台 USB 相机；
   看板只在用户点按钮时才订阅 `/ws/stream`，避免演示时互相抢设备。
5. **无相机是常态**：服务端要跑完 DSHOW 多策略探测（约 10 秒）才回 `{"error": ...}`，
   所以按钮文案直接写明"无设备时约 10 秒后给原因"，页面照样给出可读原因（不白屏、不静默）。
6. 快照口径与 `CLAUDE.md`「训练 11,876」不一致：目录实测图/标注均为 **11,948 / 2,046**，看板显示实测值。

## 手机端 http/https 合一（2026-10-13 · 已实现并实测）
**现场故障**：`api_server.py` 没加 `--https` → 8443 根本没监听，而 `/m` 页面照样渲染
`https://<IP>:8443/m` 链接（`/api/lan` 也照给）→ 手机点进去打不开；即使 `--https` 起来，
证书 SAN 里是**旧网段** IP（手机报"证书名称不符"），且 https 页里 `API_BASE` 指向
`http://host:8080` → 浏览器按**混合内容**把 fetch 整块拦掉（detect/ask/mist/history/health 全废，
只有 wss 能通）→ https 页看起来像"另一个坏掉的页面"。

| 项 | 落点 | 说明 |
| --- | --- | --- |
| 唯一入口 | `api_server.py` + `serve/static/mobile.js` | **HTTPS 默认同开**（`--no-https` 关，`--https` 兼容保留，`--reload` 下默认不开）；http 打开 `/m` 先 no-cors 探测 https，可用才 `location.replace` 升级，不可用就留在 HTTP 页给可点链接（不会跳进打不开的页面，也没有"返回又跳回"的死循环）；`?http=1` 强制留 HTTP |
| 接口同源 | `serve/static/mobile.js` | `const API_BASE = ""` —— **永远同源**。别再写回 `"http://"+hostname+":8080"`：HTTPS 页里那是混合内容，浏览器必拦 |
| 不出死链 | `_srv_ports['https_on']` → `render(https_enabled=…)` / `/api/lan.https_enabled` / `phone_urls_https`（未启用返回 `[]`） | 只有 HTTPS 线程**真的 started 且自检通过**才算 true；false 时页面不渲染 https 链接，横幅写明原因 |
| 就绪自检 | `api_server.py: _port_busy / _start_https / _https_selfcheck` | 端口 preflight（被占则报 PID + `tool/port_check.py --kill`）→ 起线程等 `server.started`（≤8s）→ 用 `_create_unverified_context()` 真请求 `/api/health`；任一步失败即关掉监听，绝不留"8443 在听但状态说没开" |
| 证书跟着 IP 走 | `tool/gen_cert.py` | `needs_refresh_from_info()`（纯函数，好单测）判断 SAN 是否覆盖**当前**所有局域网 IP / 是否临近过期，不覆盖就自动重签；生成优先 `cryptography`（py3.14 自带 49），缺失走 openssl（`find_openssl()` 已按 `sys.executable` / `CONDA_PREFIX` 推导，命中 `…\envs\pest-gpu\Library\bin\openssl.exe`）；`api_server.py --cert-extra-ip` 可手工补 IP |
| 入口可视化 | `serve/pages/index.html` + `GET /qr` | PC 首页新增「手机端入口」卡片：地址+二维码取自 `/api/lan` 的 `phone_url`（HTTPS 可用即 https），不用手输 IP |
| 实时画面叠框 | `serve/static/mobile.js`（`drawDetections` / `fitRect` / `boxToViewRect`）+ `mobile.html` 的 `#liveCanvas` | `/ws/phone` **只回检测 JSON**（省流量），框由手机页 canvas 自己画 —— 这是后端早就写在 docstring 里的约定，之前前端没实现，所以"实时没有框"。bbox 是上传那一帧的像素坐标，映射时要减掉 `object-fit:contain` 的黑边；`sentFrame` 记下每次发送的帧尺寸 |
| 实时卡片 | 同上 | 画面比例按摄像头真实比例自适应（去 4:3 黑边）、双击/按钮放大、前后摄像头切换、显示检测框开关、截图(带框)保存、断线指数退避自动重连(≤6 次)、状态小面板（目标/风险/服务端耗时/往返/FPS）、检测列表按置信度降序 + 进度条 |
| 测试 | `tests/test_phone_https.py`（14 条） | 同源 API、占位符无泄漏、https 开/关两种渲染、内嵌 JS `node --check`、SAN 覆盖纯判断、真生成证书、重签/复用、服务端契约、PC 首页元素；另有两条 **node 运行时**用例：`CG-GEOMETRY` 段数值校验，以及给 `mobile.js` 打极简 DOM/canvas 桩后跑真实 `drawDetections()`，断言 `strokeRect` 坐标/标签文字/0 目标不画/关框不画（现场没浏览器自动化，这是唯一能自动守住"叠框"链路的办法） |

### 踩过的坑（别再重踩）
1. **同源是唯一解**：HTTP 页与 HTTPS 页是不同 origin，https 页只能调 https 接口。"共用一个页面" = **同源 API + http 入口自动升级**，绝不能让 https 页去调 8080（混合内容必被拦）。
2. 一个端口只能是 TLS **或**明文：`--https-port` 与 `--port` 相同必须**启动即报错**（已加）。
3. 证书 SAN 没写手机在用的那个 IP，手机上就是"证书名称不符"；`ensure_cert` 原来"文件存在就复用"，换网段后必炸 → 现在按 SAN 覆盖自动重签（重启服务即可）。
4. `curl.exe` 在本机沙箱里做 HTTPS 客户端会报 `schannel: SEC_E_NO_CREDENTIALS`（客户端凭据问题，不是服务端）→ 验证 HTTPS 用 `py -3.14 -c "…urllib + ssl._create_unverified_context…"` 或手机浏览器。
5. 内嵌 JS 少一个 `)`（`new Promise(` 忘了闭合）会让整段脚本不执行、页面只剩外壳 → `test_mobile_inline_js_parses` 用 `node --check` 挡住。

## 当前路线（2026-10-08 对齐 · 清理后重定）
主线：**先跑通单节点闭环，再扩面**。功能按"能不能现场演示"排序，不按"功能多少"排序。

### 硬件口径（2026-10-08 二次对齐）
| 设备 | 数量 | 用途 |
| --- | --- | --- |
| ESP32 Dev Module | 3（**2 用 + 1 备用**） | 片区A / 片区B 各一块，**同时支持 WiFi 与蓝牙**；实测芯片 `ESP32-D0WD-V3` rev v3.1，460800 波特率烧录正常 |
| 1 路 3.3V 继电器 | 3（2 用 + 1 备用） | **光耦隔离、低电平触发**（= `RELAY_ACTIVE` 默认 LOW，无需改代码）；GPIO13 控雾化通断 |
| 雾化模块套装 | 2 | **5V 超声雾化片 + 驱动板**（一件）；一路继电器控它。**必须浸没**，单次已收紧到 5 秒（`-DMAX_SPRAY_SEC=5`） |
| 工业摄像头 + 支架 + 补光灯（整套） | 2 | 定点标准化采集（A 档） |
| 声光报警器 | — | **暂不做**；`alarm` env 代码保留、不现场烧 |

### 两条业务线（比赛要求形态C：明确的外部设备联动）
- **方案一 定点自动**：工业摄像头A 常驻采集 → 推理 → 判定「大量害虫」(高风险) → 自动喷洒对应片区
- **方案二 手持人工确认**：农户手机拍照/视频上传 → 服务器检测 → 手机网页确认 → 喷洒对应片区
- 共同拓扑：**相机与手机都只连服务器；节点只接受服务器指令**（手机不直连节点）

### BLE 的定位（重要，别做错方向）
BLE 走 **服务器 → 节点**（Python `bleak`），**不做手机直连节点**：
手机直连必须用 Web Bluetooth，而 iOS Safari 不支持（见 `国赛购买清单.md` 第 219 行），
且需要页面拿到节点 BLE 地址、离开 ~10m 就断链、无法留痕。
服务器直连零手机约束、可写 history、可做"WiFi 主 + BLE 备"降级。

- **Phase 0 固件可编译**：✅ **已完成并上板验证（2026-10-08）** —— 8 个 env 全部 `SUCCESS`（`pio run` 退出码 0），
  `ENABLE_SERIAL_ALARM=1` 那条可选路径也单独验证过。产物在 `ESP32/.pio/build/<env>/firmware.bin`。
  **真机验证**：片区A 板烧 `selftest` → 串口输出 `SELFTEST_PASS`（29 项断言、0 失败）；
  芯片 `ESP32-D0WD-V3` rev v3.1，MAC `<板子MAC>`（做 ESP-NOW 单播时登记用），
  串口设备为 **COM5**（COM3/COM4 是系统蓝牙虚拟串口，别搞混），460800 波特率烧录一次成功。
  - 踩过的坑与修法（下次别重踩）：
    1. **平台钉 `espressif32@7.1.3`**（Arduino 核心 2.0.17），别升级；
    2. 共享头文件必须放 **`ESP32/include/`**（PlatformIO 只自动加这个目录），放 `src/common/` 会 `fatal error: cg_protocol.h not found`；
    3. **全局变量不能叫 `alarm`** —— 与 POSIX `alarm()` 冲突（经 unistd.h→pthread→Arduino.h 引入），已改名 `alarmUnit`；
    4. `platformio.ini` 加了 `build_cache_dir = .pio/build_cache`，8 个 env 共享框架目标文件（每个 env 3–9 秒）；
    5. 本机系统代理 `127.0.0.1:65532` 已失效但会被 `requests`/PlatformIO 自动使用 → 必须设 `NO_PROXY` 绕开；
       pio 自己的镜像列表含 `github.com`（被拒）与 `usc1.contabostorage.com`（DNS 不通），**下载基本得靠绕代理直连**；
    6. 工具链（115MB）与框架（735MB）是**手工喂进** `~/.platformio/packages/` 的（`ESP32/tools/fetch_toolchain.py` 下载、
       `install_toolchain.py` 写缓存），框架 `.piopm` 必须**无 BOM**，否则报 `InvalidJSONFile`。
- **Phase 1 单节点闭环（当前重点）**：烧 `http_node_g1` + `alarm` → `python api_server.py`，验收四条：
  1. `curl` POST `/spray` → 继电器吸合 2 秒后自动断开
  2. 组不匹配（把 `g2` 发给 `g1` 节点）→ 继电器**不动**
  3. 高风险样本 → 语音播报（声光报警器**暂不做**；`alarm` env 保留代码、不烧）
  4. 拔 USB 改充电宝供电 → 仍能远程触发（真无线）
  - **进度（2026-10-08）**：✅ **继电器控制侧已真机验证通过** —— 1 路光耦隔离模块（丝印 `DC+/DC−/IN`、`COM/NO/NC`、`H/L` 跳线帽）
    接 `3V3→DC+`、`GND→DC−`、`GPIO13→IN`，**跳线帽拨 `L`**（低电平触发，与 `RELAY_ACTIVE` 默认一致）；
    用 `env:relaytest`（不依赖 WiFi，每 2 秒吸合/断开循环）验证：每 2 秒咔哒一次、板载 LED 同步闪烁。
    雾化负载侧（`COM`+`NO`）尚未接线。
  - **进度（2026-10-08 晚）**：✅ **HTTP 链路 + 继电器真机闭环已跑通**（Phase 1 验收前两条已证）：
    节点 `http_node_g1` DHCP 拿到 `<节点IP>`（网关 `<热点网关>`、RSSI −37dBm）→
    `GET /status` 200；`POST /spray {"group":"g1","duration":2}` → 串口 `SPRAY_ON group=g1 duration=2` + `SPRAY_OFF`
    （**继电器吸合 2 秒后自动断开**）；`{"group":"g2"}` → `SKIP group=g2`（**片区隔离，继电器不动**）；
    `{"group":"g1","duration":60}` → 实际 `duration=5`（**安全钳制**）；空 body → 400、未知路径 → 404。
    ⚠️ **关键坑（已解）**：手机热点若处于「共享已连接的 WiFi / 桥接」模式，会把上游网络地址直接发给接入设备
    （网段由上游 DHCP 决定，不一定是热点网段）。此时节点用写死的 `192.168.43.61`
    会「`WIFI_OK` 但服务器 ping 不到、curl 超时」→ 已加 `USE_DHCP` 开关，两个节点 env 默认 `-DUSE_DHCP=1`，
    **节点 IP 以串口打印的为准**，并同步填进 `SPRAY.http_targets`（按现场串口打印的 IP 填）。
    诊断口诀：看服务器从哪个 DHCP 服务器拿到地址 —— 手机当热点时应是 `x.x.x.1`，若是别的地址说明热点在桥接。
- **Phase 2 双片区**：加 `http_node_g2`；验收 片区隔离 + 20 样本 180 秒内 + 实测时长与 `risk_map` 一致。
- **Phase 3 BLE 冗余通道（两片区都要，Phase 1 之后再动）**：固件 `cg_ble.h`
  （GATT：`CMD` 写 JSON / `STATE` 读+notify，广播名 `CropGuard-g1|g2`）+ 服务器 `feedback/ble_link.py`
  （bleak，Windows 原生，不需要手机 App、绕开 iOS Safari 不支持 Web Bluetooth 的限制）
  + `SPRAY.transport: 'http+ble'`（WiFi 主通道，失败降级蓝牙）。
  接口已在 `cg_config.h` 预留 `ENABLE_BLE`；**ESP-NOW 节点不要开 BLE**（三开有共存毛病）。
- **Phase 4 文档口径**：`国赛方案.md` 按仓库实况整体重写（现在仍是"方案丙为默认推荐"的旧口径）。

已定口径（不要再改）：
- GUI 主线 `main.py` + `UI.py`；固件唯一源 `ESP32/`（`.ino` 已删）；喷淋走**方案甲 HTTP**
- `dataset_102` 留原地（不删、不外移）；备用 ESP-NOW 三个 env 保留、现场可烧
- 明确不做：MQTT、OTA、ESP32-CAM 图像采集、旋转机构、WiFiManager 配网门户、升级 ultralytics

外部阻塞：`CropGuard/`（另一会话进程占用，删不掉）。

## 真实样本测试集（2026-10-13 · 已建并实测）
- **目录**: `real_testset20/`（20 张，命名 `NN_中文名-英文类_confX.XX.jpg`；`manifest.csv` + `README.md` 一并生成）
- **选样脚本**: `scripts/pick_real_testset.py` —— 从 `competition_all_sorted/`（1808 张、文件名自带置信度）
  每类取本类置信度最高的一张，按置信度降序取前 N，中文类别不重复；`--dry-run` 只看不复制
- **测样脚本**: `scripts/eval_real_testset.py` —— 逐张推理，出 `eval_<时间戳>.csv/.json`（含每张耗时，可核对 180 秒）
- **实测**: best.pt + imgsz=640 + CPU(无 CUDA)：Top1 **20/20**、平均 **112 ms/张**（机器空闲；同机并发时约 240 ms）、
  20 张共 2.2 s；置信度与文件名里记录的一致（0.78–0.95），**未被相纸打印/摄像头退化**（这是"数据集实拍图"，不是现场翻拍）
- 中英文类别全表: `docs/27类中英文对照.md`
- ⚠️ **标签噪声（重要，实测踩到）**: 挑出来的最高置信度样本里有肉眼可见的错标，例：
  - `06_蝗虫-Locustoidea_conf0.88.jpg` 画面是**绿色盲蝽(半翅目)**，与蝗虫（直翅目）不符 —— 模型跟着学错了
    （旁证：该类 val mAP50 只有 **0.6586**，而它却能给这张 0.88）
  - `01_光肩星天牛-Potosiabre_vitarsis_conf0.95.jpg` 的形态更像**花金龟类**，不像天牛；KB 里的中文名"光肩星天牛"本身也可疑
  - → `competition_all_sorted` 的**文件名置信度不能当"标注正确"的证据**；现场/答辩前务必人工对照植保图鉴筛一遍
- 用法:
  ```powershell
  py -3.14 scripts/pick_real_testset.py --dry-run    # 先看选了谁
  py -3.14 scripts/pick_real_testset.py              # 复制成 real_testset20/
  py -3.14 scripts/eval_real_testset.py --conf 0.25  # 跑识别，出 csv/json
  ```

### 本机跑推理/验证的环境坑（2026-10-13 踩到）
1. 仓库根有一份 **vendored `ultralytics/`（8.2.0）**，靠 cwd 优先级被 import；`py -3.14 scripts/xxx.py`
   时 `sys.path[0]` 是 `scripts/` → 必须脚本内 `sys.path.insert(0, ROOT)`，否则 `ModuleNotFoundError: ultralytics`
2. 本机 numpy 是 2.x，而该 vendored 版本用 `np.trapz`（2.x 已删）→ 验证跑到算 mAP 时崩。
   已在 `ultralytics/utils/metrics.py` 改成 `getattr(np,'trapezoid',None) or np.trapz`（**这处改动别回滚**）
3. 离线拉不到 `Arial.ttf` 会把 `val()` 直接搞崩 → 已让 `ultralytics/utils/checks.py:check_font` 失败即返回 None、
   `ultralytics/data/utils.py` 里 check_font 包 try（字体只影响绘图观感）
4. `python -m ultralytics` 在本机不可用（无 console script）；`scripts/per_class_val.py --help` 要能跑说明环境对
5. 每类验证一次约 **6 分钟**（CPU，2046 张 val 图）；报告落 `output/per_class_val_<时间戳>.{csv,json,md}`

## 真实昆虫标本采购（2026-10-20 · 已定稿）
国赛幕② 是「20 个**实体样本**，评委按实物逐个判 ✓/✗，每错 1 只丢 1 分」→ 选型按**准确度优先**，
不是按"类别越多越好"。商家版清单 `docs/真实昆虫采购单.md`（机读 `docs/specimens_plan.csv`），
两份逐行一致由 `tests/test_specimen_plan.py` 守着。

**20 只主选 = 10 类**（每类 ≥2 只"同类别不同形态"，天然互为换货备份）：

| 类别 | 只数 | 形态差异 | mAP50 |
| --- | ---: | --- | ---: |
| 蝼蛄 | 3 | 大/中/小 + 深浅 | 0.9946 |
| 蛴螬 | 3 | 两种金龟幼虫（头壳色/胖瘦/C 弯） | 0.9627 |
| 斑衣蜡蝉 | 2 | 大小/深浅 | 0.9950 |
| 水稻卷叶螟 | 2 | 展翅 / 合翅 | 0.9842 |
| 葡萄天蛾 | 2 | 展翅 / 合翅，浅褐型 | 0.9506 |
| 金针虫 | 2 | 深褐 / 橙黄 | 0.8798 |
| 叶蝉科 | 2 | 褐绿 / 绿（**必须非大青叶蝉**） | 0.9856 |
| 黑切叶虫 | 2 | 展翅 / 合翅 | 0.8267 |
| 跳甲 | 1 | 黄条纹（**可替换位**，2–3mm 太小） | 0.9715 |
| 绿蝉 | 1 | 大青叶蝉亮绿（**可替换位**） | 0.8624 |

另加 **6 只备用**：蝼蛄/蛴螬/斑衣蜡蝉/金针虫各 1（同类换货位）+ 玉米螟 1（仅备用，与稻纵同科易混）+
带虫叶片蚜虫 1（兼做"真实带虫叶片"真实性展示）。预算 ~¥420（申请 ≤450）。

**明确不买**（买了就是丢分）：蝗虫（mAP50 0.66 且图错标成绿色盲蝽）、光肩星天牛（标签可疑）、
盲蝽科/花盲蝽/苜蓿盲蝽、芫菁/豆类芫菁/丽缘红姬甲、斜纹夜蛾/甜菜夜蛾/粘虫/甘蓝夜蛾/黄切叶虫、
亚麻蕾虫、桃蛀螟。

**验收流程（到货当天做）**：
1. 用**现场那台相机**、浅灰哑光底、固定距离、斜 30–45° 每只拍一张，文件名 = 采购单编号（`01.jpg`…`20.jpg`，备用 21–26），放 `specimens/`；
2. `py -3.14 scripts/screen_specimens.py --dir specimens --plan docs/specimens_plan.csv`
   （`--conf` 默认 **0.4 = GUI 现场阈值**；`--pass-conf` 默认 0.7 留余量）；
3. 判定 `OK / LOW / WRONG / NONE / NOFILE / UNPLANNED`；主选出现 `WRONG/NONE/NOFILE` → 退出码 1，
   按脚本给的「换货建议」用备用位顶，**别把有风险的样本带进现场**。

**踩过的坑 / 口径**
- 教学标本厂常拿**黄粉虫/大麦虫冒充金针虫/蛴螬**、拿**金龟子/叩头虫成虫**当幼虫 → 清单里已写死"必须是幼虫"。
- 幼虫**不要针插**（干瘪变形）→ 活体或酒精浸制；成虫针插；跳甲用微针粘卡；不要树脂包埋。
- 蛾类**翅完整**，展翅/合翅各配一半（两种姿态都覆盖）。
- 针插展翅标本在训练分布内：置信度最高的实测图里就有针插标本（斑衣蜡蝉 0.90、葡萄天蛾 0.90）。
- 小体型（跳甲 2–3mm、绿蝉 7–9mm、蚜虫 1–2mm）在固定机位下像素占比低、置信度会掉 → 只做"可替换位"或备用。

## 清理记录 (2026-10-08 · 目录对齐)
- 删除 GUI v2 线: main_v2.py、UI_v2.py（均未提交 git，**永久删除**；主线定为 main.py + UI.py）
- 删除冗余模型: runs/…/best.onnx（与比赛目录那份 SHA256 相同）、best.onnx.data（best.onnx 内无 external_data 引用）、best.onnx.bak、yolov8s.pt
- 删除死代码: auto_copy_model.sh（源路径 pest102_run1 已不存在）、platform_camera.py（全仓库零引用）
- 删除 5 个 Arduino `.ino`（已移植进 ESP32/）及 feedback/spray_executor/ 整棵子树
- 删除: .venv/（Python 3.14 残留）、img/111.mp4、fonts/Arial.ttf、空目录 weights/ 与 prompts/templates/、30 个 __pycache__
- 未动（有争议）: dataset_102（777MB）、output/、runs/detect/
- 未完成: CropGuard/（espidf 脚手架）被另一进程占用删不掉；其 scripts/pio_seed_cache.py 已抢救到 ESP32/tools/
- 共释放约 188 MB

## 清理记录 (2026-09-21)
- 已删旧模型/训练产物: yolov8n.pt(+partial)、runs/train/pest27_v2(480)、pest102_run1、pest27_soup.pt、weights/yolov8s、YOLOv8/
- 已删 102 类遗留脚本/配置: train_102.py、train.py、val.py、启动训练.bat、config/traindata.yaml、config/traindata_102.yaml
- 保留(重要): dataset_102、dataset_full、competition_all_sorted、pictures20、selected_real_scenes、睿抗国赛项目—农智云(PPT/规则)
- README.md 已重写（面向他人本地运行）

## 注意事项
- Windows 下训练脚本必须用 if __name__=='__main__': 包起来（multiprocessing）
- hsv_s 最大 1.0，不能超过
- 更换模型后记得改 config/configs.yaml 的 WEIGHT，否则 GUI 会加载旧模型
- generate_ppt.py 曾误删，需从原完整包恢复（原包非GitHub，是CSDN/博客下载，含UI.py+weights+icon）
