# -*- coding: utf-8 -*-
"""自签 HTTPS 证书生成（给手机端 getUserMedia 实时模式用）。

## 为什么需要

手机浏览器调用 `getUserMedia`（取手机摄像头）必须是**安全上下文**：
HTTPS 或 localhost。服务器是局域网 IP，所以只能上 HTTPS。

## 证书必须跟着局域网 IP 变（本机实测踩过）

自签证书的 SAN 里**必须写上手机实际访问的那个 IP**，否则手机会报
"证书名称不符"（Chrome 的「继续前往」有时点不了，现场很尴尬）。
以前只有当 `cert.pem` 不存在时才生成，换了热点/网段后 IP 变了却继续复用旧证书 ——
现在 `generate()` 会先 `needs_refresh()` 检查 SAN 是否覆盖**当前**所有局域网 IP，
不覆盖就自动重签（并打印原因）。

## 生成器优先级

1. `cryptography`（纯 Python，SAN 完全可控、无子进程；`py -3.14` 实测自带 49.0.0）；
2. `openssl`（conda 环境自带，如 `…\\envs\\pest-gpu\\Library\\bin\\openssl.exe`）—— `cryptography` 缺失时兜底。
   两个实测坑：
   - `openssl.exe` 会去读 `C:\\Program Files\\Common Files\\ssl\\openssl.cnf`（不存在），
     所以必须显式 `-config <env>\\Library\\ssl\\openssl.cnf`；
   - `New-SelfSignedCertificate` 这条路已被策略拒绝（NTE_PERM），不要走。

用法：

    python -m tool.gen_cert                 # 覆盖 config/certs/{cert,key}.pem
    python -m tool.gen_cert --force         # 强制重签
    python -m tool.gen_cert --ip 192.168.43.1   # 额外写进 SAN（手机走别的网段时用）

生成后 `api_server.py` 启动 HTTPS 时会自动复用/自动重签。
"""
import argparse
import datetime
import glob
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CA_NAME = 'localhost'


def _base_candidates():
    """按"当前解释器所属环境"优先列出 openssl.exe 候选路径。"""
    env_roots = []
    try:
        env_roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    except Exception:
        pass
    if os.environ.get('CONDA_PREFIX'):
        env_roots.append(os.path.abspath(os.environ['CONDA_PREFIX']))
    # 本机实测路径（conda 根 / 各 env）
    env_roots += [
        r'D:\Dev Env\Miniconda',
        r'D:\Dev Env\Python\Conda\envs\pest-gpu',
        r'D:\Miniconda',
        r'C:\ProgramData\Miniconda3',
    ]
    out = []
    for root in env_roots:
        if root:
            out.append(os.path.join(root, 'Library', 'bin', 'openssl.exe'))
    return out


def find_openssl():
    cands = [shutil.which('openssl')] + _base_candidates()
    for p in cands:
        if p and os.path.exists(p):
            return p
    # 兜底：常见根目录下按固定层级找（不用递归 glob，避免扫几百 MB 的 conda 目录）
    for root in (r'D:\Dev Env\Miniconda', r'D:\Dev Env\Python\Conda', r'D:\Miniconda',
                 r'C:\ProgramData\Miniconda3'):
        for pat in ('Library/bin/openssl.exe', 'envs/*/Library/bin/openssl.exe'):
            for hit in sorted(glob.glob(os.path.join(root, *pat.split('/')))):
                return hit
    return None


def find_conf(openssl_path=None):
    cands = []
    if os.environ.get('CONDA_PREFIX'):
        cands.append(os.path.join(os.environ['CONDA_PREFIX'], 'Library', 'ssl', 'openssl.cnf'))
    if openssl_path:
        # <env>\Library\bin\openssl.exe → <env>\Library\ssl\openssl.cnf
        env_root = os.path.dirname(os.path.dirname(os.path.dirname(openssl_path)))
        cands.append(os.path.join(env_root, 'Library', 'ssl', 'openssl.cnf'))
    cands += [
        r'D:\Dev Env\Miniconda\Library\ssl\openssl.cnf',
        r'D:\Dev Env\Python\Conda\envs\pest-gpu\Library\ssl\openssl.cnf',
        r'D:\Miniconda\Library\ssl\openssl.cnf',
        r'C:\ProgramData\Miniconda3\Library\ssl\openssl.cnf',
    ]
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None


def lan_ips():
    """本机所有可用于手机访问的局域网 IPv4（写进证书 SAN）。

    三种来源取并集：
    1. `psutil` 枚举全部网卡（最全：WLAN / 热点 / 有线都能拿到，实测本机 WLAN=172.23.153.11）；
    2. UDP 默认路由法（不真发包，只为拿到出口网卡）；
    3. 主机名解析。
    排除回环与 169.254.* 链路本地地址（写进 SAN 毫无意义）。
    """
    ips = []

    def add(ip):
        if not ip or ip.startswith('127.') or ip.startswith('169.254.'):
            return
        if ip not in ips:
            ips.append(ip)

    try:
        import psutil
        for _name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if getattr(getattr(a, 'family', None), 'name', '') == 'AF_INET':
                    add(a.address)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except Exception:
        pass
    return ips


def san_names(ips=None):
    """完整 SAN 列表：DNS:localhost + IP:127.0.0.1 + 各局域网 IP。"""
    names = [f'DNS:{CA_NAME}', 'IP:127.0.0.1']
    for ip in (ips if ips is not None else lan_ips()):
        if ip and ip != '127.0.0.1':
            names.append(f'IP:{ip}')
    return names


def _parse_asn1_time(text):
    """把 `ssl` 解码出的 'Oct  9 04:43:59 2029 GMT' 转成 epoch 秒；失败返回 None。"""
    try:
        return float(ssl.cert_time_to_seconds(text))
    except Exception:
        return None


def cert_info(cert_path):
    """读 PEM 证书，返回 {'sans': [ip...], 'not_before_ts': float, 'not_after_ts': float}。

    读不出来（文件缺失/解析失败）返回 None —— 调用方必须把它当"未知"处理。
    """
    if not cert_path or not os.path.exists(cert_path):
        return None
    try:
        with open(cert_path, 'rb') as f:
            data = f.read()
    except Exception:
        return None

    # 1) cryptography（首选，能同时拿到 SAN 与有效期）
    try:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID
        crt = x509.load_pem_x509_certificate(data)
        sans = []
        try:
            ext = crt.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
            sans = [str(v) for v in ext.value.get_values_for_type(x509.IPAddress)]
        except x509.ExtensionNotFound:
            pass
        nb = getattr(crt, 'not_valid_before_utc', None) or crt.not_valid_before
        na = getattr(crt, 'not_valid_after_utc', None) or crt.not_valid_after
        if nb.tzinfo is None:
            nb = nb.replace(tzinfo=datetime.timezone.utc)
        if na.tzinfo is None:
            na = na.replace(tzinfo=datetime.timezone.utc)
        return {'sans': sans, 'not_before_ts': nb.timestamp(), 'not_after_ts': na.timestamp()}
    except Exception:
        pass

    # 2) 标准库私有接口（CPython 一直有；pest-gpu 无 cryptography 时走这里）
    try:
        info = ssl._ssl._test_decode_cert(cert_path)
        return {
            'sans': [v for k, v in info.get('subjectAltName', ()) if k == 'IP Address'],
            'not_before_ts': _parse_asn1_time(info.get('notBefore')),
            'not_after_ts': _parse_asn1_time(info.get('notAfter')),
        }
    except Exception:
        pass
    return None


def needs_refresh_from_info(info, ips, min_days=30, now=None):
    """纯判断：给定 `cert_info()` 的结果，判断该不该重签（不碰文件系统，可直接单测）。

    info 为 None 表示证书读不出来（缺失/解析失败）→ 按"该重签"处理。
    reason 取值：undecidable / not_yet_valid / expired / expiring_<N>d / san_missing:<ip> / ok
    """
    if not info:
        return True, 'undecidable'
    now = time.time() if now is None else float(now)
    nb, na = info.get('not_before_ts'), info.get('not_after_ts')
    if nb and nb > now + 300:
        return True, 'not_yet_valid'
    if na:
        if na <= now:
            return True, 'expired'
        if na - now < int(min_days) * 86400:
            return True, f'expiring_{int((na - now) / 86400)}d'
    have = [str(x) for x in (info.get('sans') or [])]
    for ip in (ips or []):
        if ip not in have:
            return True, f'san_missing:{ip}'
    return False, 'ok'


def needs_refresh(cert_path, ips=None, min_days=30):
    """现有证书是否该重签。返回 (bool, reason)。reason 见 needs_refresh_from_info。"""
    if not cert_path or not os.path.exists(cert_path):
        return True, 'missing'
    return needs_refresh_from_info(cert_info(cert_path),
                                   lan_ips() if ips is None else ips, min_days)


def _generate_cryptography(cert_path, key_path, days, cn, ips):
    """用 cryptography 生成自签证书（SAN 可控）。失败直接抛异常，由调用方兜底。"""
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn or 'CropGuard')])
    sans = [x509.DNSName(CA_NAME), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]
    for ip in (ips or []):
        if ip == '127.0.0.1':
            continue
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            sans.append(x509.DNSName(ip))       # 传进来是域名也照样写 SAN

    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (x509.CertificateBuilder()
               .subject_name(subject)
               .issuer_name(issuer)
               .public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .add_extension(x509.SubjectAlternativeName(sans), critical=False)
               .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True))
    # cryptography 42+ 用 *_utc 版本（naive 版已弃用）；旧版走 else 分支
    if hasattr(builder, 'not_valid_before_utc'):
        builder = (builder.not_valid_before_utc(now)
                   .not_valid_after_utc(now + datetime.timedelta(days=int(days))))
    else:
        builder = (builder.not_valid_before(now)
                   .not_valid_after(now + datetime.timedelta(days=int(days))))
    cert = builder.sign(key, hashes.SHA256())

    with open(key_path, 'wb') as f:
        f.write(key.private_bytes(encoding=serialization.Encoding.PEM,
                                  format=serialization.PrivateFormat.PKCS8,
                                  encryption_algorithm=serialization.NoEncryption()))
    with open(cert_path, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def _generate_openssl(cert_path, key_path, days, cn, san):
    """openssl 兜底生成。返回错误字符串，成功返回 None。"""
    openssl = find_openssl()
    if not openssl:
        return '找不到 openssl.exe（conda 自带，路径见本文件 _base_candidates）'
    conf = find_conf(openssl)
    cmd = [openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-sha256',
           '-days', str(int(days)), '-nodes',
           '-keyout', key_path, '-out', cert_path,
           '-subj', f'/CN={cn or "CropGuard"}', '-addext', f'subjectAltName={san}']
    if conf:
        # -config 必须跟在 req 子命令后面（放最前面会被解析成全局参数而报错）
        cmd[2:2] = ['-config', conf]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:
        return f'openssl 执行失败: {type(exc).__name__}: {exc}'
    if proc.returncode != 0 or not os.path.exists(cert_path):
        return (proc.stderr or proc.stdout or '').strip()[:300]
    return None


def generate(cert_dir, days=1095, force=False, cn='CropGuard', extra_names=None):
    """生成/刷新自签证书。返回 (cert_path, key_path, error)。

    已存在且 SAN 覆盖当前局域网 IP、且未临近过期时直接复用；
    否则自动重签（打印原因），因为手机访问的 IP 必须落在 SAN 里。
    """
    cert_path = os.path.join(cert_dir, 'cert.pem')
    key_path = os.path.join(cert_dir, 'key.pem')
    ips = lan_ips()
    for n in (extra_names or []):
        if n and n not in ips:
            ips.append(n)

    if not force and os.path.exists(cert_path) and os.path.exists(key_path):
        need, reason = needs_refresh(cert_path, ips)
        if not need:
            return cert_path, key_path, None
        print(f'[CERT] 需要重新生成证书：{reason}'
              f'（当前局域网 IP: {", ".join(ips) or "未识别"}）', flush=True)

    os.makedirs(cert_dir, exist_ok=True)
    san = ','.join(san_names(ips))

    # 1) 纯 Python（SAN 完全可控，无子进程）
    try:
        _generate_cryptography(cert_path, key_path, days, cn, ips)
        return cert_path, key_path, None
    except Exception as exc:
        err = f'cryptography 生成失败: {type(exc).__name__}: {exc}'

    # 2) openssl 兜底（cryptography 缺失或失败）
    err2 = _generate_openssl(cert_path, key_path, days, cn, san)
    if not err2:
        return cert_path, key_path, None
    return None, None, f'{err}；openssl 兜底也失败: {err2}'


def ensure_cert(cert_dir=None, days=1095, extra_ips=None):
    """api_server 启动 HTTPS 用：拿到可用证书，失败返回错误字符串。

    顺带打印有效期与 **SAN/IP 覆盖结论** —— 现场一眼看出手机该用哪个地址。
    """
    cert_dir = cert_dir or os.path.join(ROOT, 'config', 'certs')
    if not os.path.isabs(cert_dir):
        cert_dir = os.path.join(ROOT, cert_dir.lstrip('./'))
    cert, key, err = generate(cert_dir, days=days, extra_names=extra_ips)
    if err:
        return None, None, err

    info = cert_info(cert) or {}
    if info.get('not_after_ts'):
        print(f'[CERT] {cert}  有效期至 '
              f'{datetime.datetime.fromtimestamp(info["not_after_ts"]):%Y-%m-%d}'
              f'（{max(0, int((info["not_after_ts"] - time.time()) / 86400))} 天）', flush=True)
    else:
        print(f'[CERT] {cert}', flush=True)

    ips = lan_ips()
    for ip in (extra_ips or []):
        if ip and ip not in ips:
            ips.append(ip)
    have = [str(x) for x in (info.get('sans') or [])]
    if not have:
        print(f'[CERT] ⚠ 读不出证书 SAN，无法确认 IP 是否覆盖；'
              f'手机若报"证书名称不符"，执行 python tool/gen_cert.py --force', flush=True)
        return cert, key, None
    missing = [ip for ip in ips if ip not in have]
    print(f'[CERT] SAN: {", ".join(have)}', flush=True)
    if missing:
        print(f'[CERT] ⚠ SAN 未覆盖当前 IP: {", ".join(missing)} —— 手机访问会报"证书名称不符"。'
              f'补救：python tool/gen_cert.py --force', flush=True)
    else:
        print(f'[CERT] ✅ SAN 已覆盖当前局域网 IP: {", ".join(ips) or "未识别"}', flush=True)
    return cert, key, None


def main():
    ap = argparse.ArgumentParser(description='生成自签 HTTPS 证书（手机实时模式用）')
    ap.add_argument('--dir', default=os.path.join(ROOT, 'config', 'certs'), help='证书目录')
    ap.add_argument('--days', type=int, default=1095, help='有效期（天）')
    ap.add_argument('--cn', default='CropGuard', help='证书 CN')
    ap.add_argument('--force', action='store_true', help='已存在也重新生成')
    ap.add_argument('--ip', action='append', default=[], help='额外写入 SAN 的 IP（可多次）')
    args = ap.parse_args()

    cert, key, err = generate(args.dir, days=args.days, force=args.force,
                              cn=args.cn, extra_names=args.ip)
    if err:
        print(f'[ERROR] {err}')
        return 1
    info = cert_info(cert) or {}
    print(f'[OK] cert: {cert}')
    print(f'[OK] key : {key}')
    print(f'[OK] SAN : {", ".join(str(x) for x in (info.get("sans") or [])) or san_names()}')
    days_left = int((info.get('not_after_ts', 0) - time.time()) / 86400) if info.get('not_after_ts') else '?'
    print(f'[OK] 有效期剩余: {days_left} 天')
    print('\n启动 HTTPS:  python api_server.py（默认已同时开 HTTPS；纯 HTTP 用 --no-https）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
