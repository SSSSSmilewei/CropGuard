// ==================== 基础工具 ====================
const HTTP_PORT = "__HTTP_PORT__";
const HTTPS_PORT = "__HTTPS_PORT__";
const IS_HTTPS = location.protocol === 'https:';
// 同源优先；HTTPS 页面里调 HTTP 接口（检测/问答/喷洒）用同主机的 HTTP 端口
const API_BASE = IS_HTTPS ? ("http://" + location.hostname + ":" + HTTP_PORT) : "";
const WS_BASE = (IS_HTTPS ? "wss://" : "ws://") + location.host + "/ws/phone";
let mode = 'photo';
let lastContext = null;
let liveWS = null, liveStream = null, liveTimer = null, liveBusy = false;

function $(id) { return document.getElementById(id); }
function setStatus(online, text) {
  const el = $('status');
  el.className = 'status' + (online ? ' online' : '');
  el.innerHTML = '<span class="dot"></span>' + text;
}
function clsOfRisk(level) {
  if (level === '高风险') return 'high';
  if (level === '中风险') return 'medium';
  if (level === '低风险') return 'low';
  return 'none';
}
async function post(path, body) {
  const r = await fetch(API_BASE + path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {})
  });
  return await r.json();
}

// ==================== 模式切换 ====================
function setMode(m) {
  mode = m;
  $('btnModePhoto').className = (m === 'photo') ? 'active' : '';
  $('btnModeLive').className = (m === 'live') ? 'active' : '';
  $('photoPane').style.display = (m === 'photo') ? '' : 'none';
  $('livePane').style.display = (m === 'live') ? '' : 'none';
  $('resultWrap').style.display = (m === 'photo') ? $('resultWrap').style.display : 'none';
  if (m === 'photo') stopLive();
}
if (!window.isSecureContext) {
  $('secureTip').style.display = 'block';
  $('httpsLink').href = 'https://' + location.hostname + ':' + HTTPS_PORT + '/m';
  $('httpsLink').textContent = 'https://' + location.hostname + ':' + HTTPS_PORT + '/m';
  $('btnModeLive').setAttribute('title', '需要 HTTPS');
}

// ==================== 拍照识别 ====================
$('fileInput').addEventListener('change', async (ev) => {
  const file = ev.target.files && ev.target.files[0];
  if (!file) return;
  setStatus(true, '已选图，正在上传识别…');
  const form = new FormData();
  form.append('file', file, 'phone.jpg');
  try {
    const resp = await fetch(API_BASE + '/api/detect', {method: 'POST', body: form});
    const data = await resp.json();
    if (!data.success) { alert('识别失败: ' + (data.error || '未知错误')); setStatus(true, '识别失败'); return; }
    renderResult(data);
    setStatus(true, '识别完成 · ' + (data.count || 0) + ' 个目标');
  } catch (e) {
    alert('上传失败: ' + e.message);
    setStatus(false, '上传失败');
  } finally {
    ev.target.value = '';
  }
});

function renderResult(data) {
  const risk = data.risk || {};
  const bar = $('riskBar');
  bar.className = 'risk ' + clsOfRisk(risk.level);
  bar.textContent = '风险等级：' + (risk.level || '--') + (risk.detail ? '（' + risk.detail + '）' : '');

  if (data.result_image && mode === 'photo') {
    $('resultWrap').style.display = '';
    $('resultImage').src = 'data:image/jpeg;base64,' + data.result_image;
  }
  const list = data.detections || [];
  const box = $('detList');
  if (!list.length) {
    box.innerHTML = '<div class="empty">未检测到害虫目标</div>';
  } else {
    box.innerHTML = list.map(d =>
      '<div class="det"><span>' + (d.chinese_name || d.class_name) + '</span>' +
      '<span class="conf">' + (d.confidence * 100).toFixed(1) + '%</span></div>').join('');
  }
  if (data.advice) {
    $('adviceBox').style.display = '';
    $('adviceBox').textContent = data.advice;
  }
  lastContext = {detections: list, risk: risk};
}

// ==================== 实时模式（手机摄像头 → 服务器） ====================
async function startLive() {
  if (!window.isSecureContext) {
    alert('实时模式需要 HTTPS 打开本页面（点击上方提示里的 https 地址）。\n也可以继续使用拍照模式。');
    return;
  }
  try {
    liveStream = await navigator.mediaDevices.getUserMedia({
      video: {facingMode: {ideal: 'environment'}, width: {ideal: 1280}, height: {ideal: 720}},
      audio: false
    });
  } catch (e) {
    alert('无法打开手机摄像头: ' + e.message + '\n请检查浏览器相机权限。');
    return;
  }
  $('phoneVideo').srcObject = liveStream;
  try {
    liveWS = new WebSocket(WS_BASE);
    liveWS.binaryType = 'arraybuffer';
  } catch (e) { alert('WebSocket 连接失败: ' + e.message); return; }

  liveWS.onopen = () => {
    setStatus(true, '实时识别中（手机画面 → 服务器）');
    $('liveOverlay').textContent = '实时识别中…';
    const interval = __FRAME_INTERVAL__;
    liveTimer = setInterval(captureAndSend, interval);
  };
  liveWS.onmessage = (ev) => {
    liveBusy = false;                      // 收到结果才允许发下一帧（单帧背压）
    try {
      const data = JSON.parse(ev.data);
      if (data.error) { $('liveOverlay').textContent = '服务器错误：' + data.error; return; }
      if (data.warning) { $('liveOverlay').textContent = data.warning; return; }
      const risk = data.risk || {};
      const names = (data.detections || []).map(d => d.chinese_name || d.class_name).join('、');
      $('liveOverlay').textContent = '风险：' + (risk.level || '--') + ' | 目标：' + (names || '无') +
                                     (data.elapsed != null ? ' | ' + data.elapsed + 's' : '');
      const bar = $('riskBar');
      bar.className = 'risk ' + clsOfRisk(risk.level);
      bar.textContent = '风险等级：' + (risk.level || '--') + (risk.detail ? '（' + risk.detail + '）' : '');
      const list = data.detections || [];
      $('detList').innerHTML = list.length
        ? list.map(d => '<div class="det"><span>' + (d.chinese_name || d.class_name) + '</span>' +
                        '<span class="conf">' + (d.confidence * 100).toFixed(1) + '%</span></div>').join('')
        : '<div class="empty">未检测到害虫目标</div>';
      if (list.length) lastContext = {detections: list, risk: risk};
    } catch (e) {}
  };
  liveWS.onclose = () => {
    $('liveOverlay').textContent = '已断开';
    setStatus(false, '实时连接已断开');
  };
  liveWS.onerror = () => { $('liveOverlay').textContent = '连接错误'; };
}

function captureAndSend() {
  if (!liveWS || liveWS.readyState !== 1 || liveBusy) return;
  const video = $('phoneVideo');
  if (!video.videoWidth) return;
  const maxSide = __UPLOAD_MAX_SIDE__;
  const scale = Math.min(1, maxSide / Math.max(video.videoWidth, video.videoHeight));
  const w = Math.round(video.videoWidth * scale), h = Math.round(video.videoHeight * scale);
  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  cv.getContext('2d').drawImage(video, 0, 0, w, h);
  cv.toBlob((blob) => {
    if (!blob || !liveWS || liveWS.readyState !== 1) return;
    liveBusy = true;
    liveWS.send(blob);                     // 直接发二进制 JPEG（比 base64 省 ~33%）
    // 1.5 秒还没回结果就解锁，避免卡死
    setTimeout(() => { liveBusy = false; }, 1500);
  }, 'image/jpeg', 0.7);
}

function stopLive() {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  if (liveWS) { try { liveWS.close(); } catch (e) {} liveWS = null; }
  if (liveStream) { liveStream.getTracks().forEach(t => t.stop()); liveStream = null; }
  $('phoneVideo').srcObject = null;
  $('liveOverlay').textContent = '未开始';
  if (mode === 'live') setStatus(true, '已停止实时识别');
}

// ==================== 大模型问答 ====================
async function askLLM() {
  const q = $('chatInput').value.trim();
  if (!q) return;
  $('chatInput').value = '';
  addChat('user', q);
  const thinking = addChat('assistant', '正在检索知识库并调用本地大模型…');
  try {
    const data = await post('/api/ask', {question: q, context: lastContext});
    thinking.remove();
    if (!data.success) { addChat('assistant', '问答失败：' + (data.error || '未知错误')); return; }
    const item = addChat('assistant', data.answer, data.citations, data);
    if (data.source === 'refused') item.classList.add('refuse');
  } catch (e) {
    thinking.remove();
    addChat('assistant', '请求失败：' + e.message);
  }
}
function addChat(who, text, citations, meta) {
  const el = document.createElement('div');
  el.className = 'chat-item';
  let html = '<div><span class="who">' + (who === 'user' ? '你' : 'AI') + '：</span>' +
             escapeHtml(text).replace(/\n/g, '<br>') + '</div>';
  const tips = [];
  if (meta) {
    const src = {llm: '本地大模型（已接地）', knowledge_base: '知识库兜底',
                 refused: '拒答（知识库未涵盖）'}[meta.source] || meta.source;
    if (src) tips.push('来源：' + src);
    if (meta.engine) tips.push('模型：' + meta.engine);
    if (meta.elapsed != null) tips.push('耗时 ' + meta.elapsed + 's');
    const g = meta.guard || {};
    if (g.unsupported && g.unsupported.length) tips.push('⚠已标注可疑药名：' + g.unsupported.join('、'));
    if (g.dosage_unsupported && g.dosage_unsupported.length) tips.push('⚠已标注可疑剂量');
    if (g.top_score != null) tips.push('召回分 ' + g.top_score);
  }
  if (citations && citations.length) {
    tips.push('依据：' + citations.map(c => c.title).join('；'));
  }
  if (tips.length) html += '<div class="meta">' + escapeHtml(tips.join(' | ')) + '</div>';
  el.innerHTML = html;
  $('chatBox').appendChild(el);
  el.scrollIntoView({block: 'end'});
  return el;
}
function clearChat() { $('chatBox').innerHTML = ''; }
function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

// ==================== 喷洒控制 ====================
async function parseCommand() {
  const t = $('cmdInput').value.trim();
  if (!t) return;
  const data = await post('/api/ask_command', {text: t, execute: false});
  const box = $('cmdConfirm');
  if (!data.valid) {
    box.className = 'confirm show';
    box.innerHTML = '⚠ 未执行：' + escapeHtml(data.reply || data.reason || '无法解析');
    return;
  }
  const label = data.intent === 'stop' ? '停止喷洒'
              : ('执行喷洒：' + (data.group === 'all' ? '全体' : data.group) + ' / ' + data.duration + ' 秒');
  box.className = 'confirm show';
  box.innerHTML = escapeHtml(data.reply) +
    '<div class="row"><button id="btnExec" class="danger">✅ ' + escapeHtml(label) + '</button>' +
    '<button class="ghost" onclick="hideConfirm()">取消</button></div>';
  $('btnExec').onclick = () => executeCommand(t);
}
async function executeCommand(text) {
  const data = await post('/api/ask_command', {text: text, execute: true});
  $('cmdConfirm').className = 'confirm show';
  $('cmdConfirm').innerHTML = data.executed
    ? '✅ 已下发喷洒指令（' + escapeHtml(String(data.group)) + ' / ' + data.duration + ' 秒）'
    : '⚠ 指令未下发：' + (data.available ? '执行失败' : '节点链路不可用（喷雾节点未在线）');
  refreshHistory();
}
function hideConfirm() { $('cmdConfirm').className = 'confirm'; }
async function manualSpray(group, duration) {
  const name = group === 'all' ? '全体片区' : group;
  if (!confirm('确认给 ' + name + ' 喷洒 ' + duration + ' 秒？')) return;
  const data = await post('/api/spray', {group: group, duration: duration, via: 'phone'});
  $('sprayHint').textContent = data.success
    ? '✅ 已下发（' + name + ' / ' + duration + 's）'
    : '⚠ 下发失败：喷淋链路不可用（检查 SPRAY.http_targets 与节点是否在线）';
  refreshHistory();
}

// ==================== 历史 ====================
async function refreshHistory() {
  try {
    const r = await fetch(API_BASE + '/api/history');
    const data = await r.json();
    const list = (data.history || []).slice().reverse();
    const el = $('histList');
    if (!list.length) { el.innerHTML = '<div class="empty">暂无记录</div>'; return; }
    el.innerHTML = list.map(h => {
      const tag = h.source === 'manual' ? 'manual' : clsOfRisk(h.risk);
      const label = h.source === 'manual' ? '手动' : (h.risk || '');
      const act = h.group ? ' → ' + (h.group === 'all' ? '全体' : h.group) + ' 喷 ' + h.duration + 's' : '';
      const det = (h.detections && h.detections.length) ? '<br>' + escapeHtml(h.detections.join('、')) : '';
      return '<div class="hist"><span class="tag ' + tag + '">' + escapeHtml(label) + '</span>' +
             escapeHtml(h.ts || '') + escapeHtml(act) + det + '</div>';
    }).join('');
  } catch (e) {}
}

// ==================== 启动 ====================
(async function init() {
  try {
    const r = await fetch(API_BASE + '/api/health');
    const data = await r.json();
    setStatus(true, '已连接 · ' + (data.device || '') + ' · ' + (data.classes || 0) + ' 类');
  } catch (e) {
    setStatus(false, '服务器未连接（检查是否同一 WiFi）');
  }
  refreshHistory();
  setInterval(refreshHistory, 4000);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && mode === 'live') stopLive();
  });
})();
