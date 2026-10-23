// 手机端入口：http → https 自动升级（原生 /m-classic 一直是这个行为，Vue 版补齐）。
//
// 为什么必须自动升：`getUserMedia`（实时识别）只在安全上下文开放；
// 而自签证书首次访问浏览器会拦一下 —— 所以探测失败时**不给死链**，
// 而是显示一条可点的提示，让操作员自己选"高级 → 继续前往"。
import { ref } from 'vue'
import { api } from '../lib/api'

export function usePhoneEntry() {
  const httpsUrl = ref('')
  const secureTip = ref('')

  async function ensureHttps() {
    if (location.protocol === 'https:') return
    if (new URLSearchParams(location.search).get('http') === '1') return
    let port = 0
    try {
      const lan = await api.lan()
      port = Number(lan.https_port || 0)
    } catch {
      port = 0
    }
    if (!port) return
    const hash = location.hash || ''
    const target = `https://${location.hostname}:${port}/m${hash}`
    httpsUrl.value = target
    try {
      // 只探活，不校验证书：证书没被信任时这里会失败，交给手动提示
      const r = await fetch(`https://${location.hostname}:${port}/api/health`, { cache: 'no-store' })
      if (r.ok) { location.replace(target); return }
    } catch { /* 自签证书未信任 / 端口不同：给提示 */ }
    secureTip.value = '当前是 HTTP 访问。实时识别需要 HTTPS，点这里切换（首次提示证书不受信任时选「高级 → 继续前往」）。'
  }

  return { httpsUrl, secureTip, ensureHttps }
}
