# CropGuard 农智云 · 害虫检测与联动处置系统（整合版）

> 2026-10-21 整合：本仓库 = 主线最新（手机端 http/https 合一、离线看板、mist 雾化、相机看门狗）
> **+ 学弟 PR#1（Vue 3 前端 + 喷淋/流修复）+ 队友 PR#3（EdgeJev 本地决策 + 测评页）**。
> 分支 `main`，提交 `merge: 接入队友 EdgeJev…` 之后为整合结果。比赛演示流程见
> `docs/国赛最终演示流程.md`；一页速查见 `docs/演示速查卡.md`。

## 项目位置 / 仓库
- 工作目录：`D:\Dev Projects\Pycharm\yolov8`
- 开源仓库：https://github.com/Sun-0810-yh/CropGuard （含 `best.pt`；数据集/`pictures20`/`edge_models` 不入库）
- 测试子仓库：https://github.com/Sun-0810-yh/CropGuard_Test （`_dist/CropGuard_Test/`，已 gitignore）

## Python 环境（本机实测）
- 能跑服务的只有 **`py -3.14`**（`D:\Dev Env\Python\python.exe`，torch 2.12.0+cpu、无 CUDA）。
  PATH 上的 `python` 是 3.12，缺 cv2/torch。
- CPU 机器起服务：`$env:CG_DEVICE='cpu'; py -3.14 api_server.py`（`app/state.py` 读环境变量，不改配置）。
  `app/state.py` 也会在 CUDA 不可用时自动回退 CPU。
- GPU 环境：`<conda根>\envs\pest-gpu\python.exe`（PyCharm 解释器选它）。

## 一屏架构（评委看到的四层）
```
摄像头/手机 ──► FastAPI(8080 HTTP + 8443 HTTPS) ──► YOLOv8 27类（best.pt, CPU 100–250ms/张）
                        │                            └─ 风险评估 assess_risk
                        ├─ 前端 web/dist（Vue3，离线打包）: / /stream /ask /spray /system /dashboard
                        ├─ 手机端原生页 /m（唯一入口，http→https 自动升级、canvas 叠框、雾化卡片）
                        ├─ EdgeJev 本地类型化决策（规则优先 + 高置信兜底，只理解不下发）
                        └─ 执行层 HTTP─► ESP32 节点（mist: GET /start?time=N；json: POST /spray）
```

## 路由总表（整合后）
| 路径 | 页面 | 说明 |
| --- | --- | --- |
| `/` `/stream` `/ask` `/spray` `/system` | Vue SPA（`web/dist`） | 检测台/实时监测/问答/喷淋/设备 |
| `/dashboard` | Vue 看板 | 数据来自 `GET /api/dashboard`（`output/dashboard/snapshot.json`） |
| `/dashboard-offline` | 原生单文件看板 | 快照内联，可 `file://` 双击打开，断网兜底 |
| `/m` | 原生手机页 | **唯一手机入口**（保留主线实测版，非 Vue） |
| `/eval` | 测评动效页 | 20 样本 / 180 秒计时 + 判分 + CSV 导出，评分口径与 GUI 共用 |
| `/edge` | EdgeJev 决策点页 | 选择题式（指令解析/虫情研判实验性/决策点规划），不做自由问答 |
| `/classic` | 旧版 PC 首页 | 前端出问题时的兜底页（上传 + 手机二维码） |
| `/api/mist/*` | 雾化 REST | status/start/direct/stop（mist 固件适配在本页后端） |

## 启动 / 自检
```powershell
py -3.14 tool/port_check.py            # 端口 + Ollama（本机曾因 emoji 编码崩，已修）
py -3.14 tool/camera_probe.py          # 认相机 → 把 VID 写进 config CAMERA
$env:CG_DEVICE='cpu'; py -3.14 api_server.py
py -3.14 scripts/build_snapshot.py --samples pictures20   # 看板快照（验证集约 6–8 分钟）
py -3.14 scripts/build_dashboard.py                      # 离线看板 HTML（读现成产物，秒级）
py -3.14 tests/run_tests.py                              # 234 passed / 1 skipped
python main.py                                           # PyQt5 GUI（现场评测面板）
```
启动横幅必须看到：`Spray transport/http_targets`、`雾化节点(mist)=[…]`、`[CERT] ✅ SAN…`、
`手机会话页(唯一入口): https://<IP>:8443/m`、`语音: engine=… ready=True`。

## 整合口径（重要，别改回去）
1. **手机端保留主线 `serve/mobile.py` 一整套**，不从 SPA 接管 `/m`（`serve/spa.py` 的 ROUTES 已删 `/m`）。
   Vue 里有 `MobileView`/`MobileDetect` 源码，但没路由——它们没有 http→https 自动升级、断线重连、雾化卡片。
2. **`/dashboard` 归 Vue（实时），`/dashboard-offline` 是离线快照**；旧的 `scripts/build_dashboard.py`
   继续生成 HTML，新加的 `scripts/build_snapshot.py` 生成 `output/dashboard/snapshot.json + thumbs/`。
3. **`/ws/stream` 推原始帧 + `image_size`**，框由前端叠；`result_image` 里不含框。
   离线看板也只把它当画面用（它不叠框），不要再改回"服务端画框"。
4. **喷淋以 HEAD 的 mist-aware `feedback/spray.py` 为底**，只移植 PR1 的：`_lan_session(trust_env=False)`、
   `manual_spray_detail` / `stop_detail`（同步等节点应答、失败带原因）、`probe_nodes`、`allowed_groups`。
   `manual_spray(duration<=0)` 一律拒绝；`stop()` 串口/MQTT 发 `duration=0`（发 1 是"再喷 1 秒"，语义反了）。
5. **`/api/lan` 保留 `https_enabled` / `phone_url` / 条件返回 `phone_urls_https`**（PR1 会无条件给 https → 死链）。
6. **HTTPS 启动保留 HEAD 的 `_start_https` + `_https_selfcheck` + 证书按 IP 重签**。
7. EdgeJev：`EDGE.mode: 'local'`（没拷模型时毫秒级失败，不会白等 5s HTTP 超时）；
   `/api/ask_command` **规则优先，规则拿不准才调模型**；大模型永远不直接驱动硬件。
8. 控制台统一 `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`（api_server/port_check），
   否则 GBK 控制台下横幅里的 ✅ 会直接 `UnicodeEncodeError`。

## 训练与模型
- 权重：`runs/train/pest27_final4/weights/best.pt`（mAP50 0.7601 / mAP50-95 0.4899，27 类）
- 平台 ONNX：`睿抗国赛项目—农智云/best.onnx`（640；只传这个，480 会失败）
- 数据集：`dataset_full/`（11,948 训练 / 2,046 验证）；遗留 `dataset_102/` 停用保留
- 8 类 mAP50≥95%：斑衣蜡蝉 .995 / 蝼蛄 .9946 / 叶蝉科 .9856 / 水稻卷叶螟 .9842 /
  光肩星天牛 .9803 / 跳甲 .9715 / 蛴螬 .9627 / 葡萄天蛾 .9506
- 本机验证坑：vendored ultralytics 需 `np.trapz` 兼容补丁、`check_font` 容错（**别回滚**）；
  `scripts/*.py` 要 `sys.path.insert(0, ROOT)`。

## 现场硬件
- ESP32 ×3（2 用 1 备）+ 光耦继电器（低电平触发）+ 5V 超声雾化片 ×2；`ESP32/` PlatformIO，8 env。
- 喷淋走 HTTP 方案甲：`config/configs.yaml` 的 `SPRAY.http_targets`，每项带 `protocol: json|mist`。
  **仓库里是占位 IP（172.23.153.231）且 g1/g2 相同**——现场必须按节点串口打印的 IP 改，改完重启服务。
- mist 固件（手写 sketch）：`GET /start?time=N`、`/startDirect`（不自停，服务器 300s 兜底）、`/stop`；
  **永远回 200**，必须读响应体判成败。

## 样本与测试集
- 比赛 20 图：`pictures20/`（20 张 jpg，文件名 `NNNN_类别_confX.XX_*.jpg`；不入 git）
- 真实样本测试集：`real_testset20/`（20 张，Top1 20/20，平均 112ms）
- 标本采购：`docs/真实昆虫采购单.md` + `docs/specimens_plan.csv`；验收 `scripts/screen_specimens.py`
- ⚠️ 标签噪声：蝗虫（mAP50 .66，图错标成盲蝽）、光肩星天牛（标签可疑）——别拿去现场凑数

## EdgeJev（队友 PR#3）
- 包：`edgejev/`（Apache-2.0，上游 yzfly/edgejev）；适配层 `app/edge_engine.py`；文档 `docs/edgejev.md`
- 模型：`edge_models/jev-int8/`（335MB，**不入 git**，需从队友机器拷 3 个文件或联网构建一次）
- 缺模型时：`/api/edge/status` 如实 `available=false + hint`；`ask_command` 自动回规则；不崩
- 口径：零样本弱（intent 8–10/13），**只演固定 3 条**（"把泵关了吧"/"给片区A喷3秒"/"一直喷不要停"）

## 已知坑（整合时踩到的）
1. `serve/pages.py` 被 PR1 删了，但 `static_pages.load()` 还在用 → 已从主线恢复；别删。
2. `api_server` 的 `HTMLResponse` 导入被 PR1 漏掉 → 已补。
3. `pictures20/*` 被 PR3 的 `.gitignore` 忽略（只提交 README）→ 新克隆没有 20 图，看板/测评要本机有图。
4. Vue 源码改动必须 `cd web && npm install && npm run build` 重新生成 `web/dist`（dist 随仓库提交，现场无 Node）。
5. 内嵌 JS / dist 资源改动后建议 `node --check`，并在浏览器实开一次（本机 Edge headless 不可用，
   用 Playwright 校验，见 `scripts/web_smoke.py` 如存在）。
6. 手机端 http 打开 `/m` 会自动升级 https；不想升级加 `?http=1`。HTTPS 没起来时页面不会给 https 死链。

## 测试
- `py -3.14 tests/run_tests.py`：234 passed / 1 skipped（2026-10-21 整合后）
- `py -3.14 scripts/ask_eval.py`：库内召回 20/20、库外拒答 10/10、越权拦截 4/4
- `py -3.14 scripts/ask_eval.py --llm` 才真调 Ollama
