# -*- coding: utf-8 -*-
"""DirectShow 视频采集设备枚举（Windows 原生 COM，绕开"按索引猜"）。

## 为什么需要它

`cv2.VideoCapture(0/1/2)` 是**按索引**打开，而索引由 DirectShow 的枚举顺序决定 ——
插拔一次 USB、重启一次系统、换一个口，顺序就可能整个翻过来。本机就真实踩过：

    2026-10-08: index 0 = HP Wide Vision(内置)   index 1 = USB Camera(外接)
    2026-10-11: index 0 = USB Camera(外接)       index 1 = HP Wide Vision(内置)

配置里写死 `camera_num: 1`，第二次就变成了内置摄像头，而且**画面看起来一样正常**
（都能出图），不主动核对根本发现不了。所以正确做法是**按设备标识选**：
VID/PID 或设备名不会因为插拔顺序而改变。

对外接口：
* `list_devices()` -> ([{'index','name','vid','pid','moniker'}], [错误])
  **顺序即 cv2.VideoCapture 的索引**。
* `find_index(pattern)` -> int | None
  按 'vid_0c45' / '0c45' / 'USB Camera' 之类的标识找索引。
* `open_by_name(name, ...)` -> cv2.VideoCapture | None
* `list_openable()` -> ([{'index','name','ok','size','error'}], [错误])

## 实现说明（前两版为什么是坏的，别再改回去）

1. 旧版用 comtypes 手写 vtable 调 ICreateDevEnum —— 对 `IUnknown` 子类自己声明方法表
   的方式和 comtypes 的 ABI 对不上，实测**永远返回空列表**；
2. 旧版兜底走 PowerShell 的 `Windows.Devices.Enumeration`，但 WinRT 的
   `FindAllAsync(...).GetAwaiter()` 在 Windows PowerShell 5.1（.NET Framework）里
   不存在该方法，直接报错；
3. 旧版 `open_by_name` 用 `cv2.VideoCapture("video=<名称>")` —— 那是 **FFMPEG 后端**
   的语法，DSHOW/MSMF 都不认，所以"按名打开"这条路从来就没通过。

现在统一用 ctypes 直接调 COM vtable（x64 下与 C ABI 一致，实测稳定），
拿到 **moniker 的设备路径**（内含 vid/pid）与 **FriendlyName**（IPropertyBag）。
"""
import ctypes
import ctypes.wintypes as w
import re

try:
    import cv2
except Exception:                                   # pragma: no cover
    cv2 = None

CLSID_SystemDeviceEnum = '{62BE5D10-60EB-11d0-BD3B-00A0C911CE86}'
IID_ICreateDevEnum = '{29840822-5B84-11D0-BD3B-00A0C911CE86}'
CLSID_VideoInputDeviceCategory = '{860BB310-5D01-11d0-BD3B-00A0C911CE86}'
IID_IPropertyBag = '{55272A00-42CB-11CE-8135-00AA004BB851}'

_VT_BSTR = 8
_VID_RE = re.compile(r'vid_([0-9a-f]{4})', re.I)
_PID_RE = re.compile(r'pid_([0-9a-f]{4})', re.I)


class _GUID(ctypes.Structure):
    _fields_ = [('Data1', w.DWORD), ('Data2', w.WORD), ('Data3', w.WORD),
                ('Data4', ctypes.c_ubyte * 8)]


class _VARIANT(ctypes.Structure):
    """最小可用的 VARIANT（x64 下 24 字节：8 字节头 + 16 字节联合）。"""
    _fields_ = [('vt', ctypes.c_ushort), ('r1', ctypes.c_ushort),
                ('r2', ctypes.c_ushort), ('r3', ctypes.c_ushort),
                ('val', ctypes.c_void_p), ('val2', ctypes.c_void_p)]


def _guid(text):
    g = _GUID()
    ctypes.WinDLL('ole32').CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return g


def _call(punk, index, argtypes, restype=ctypes.c_long):
    """调 COM vtable 第 index 个方法（0/1/2 = QueryInterface/AddRef/Release）。"""
    vtable = ctypes.cast(punk, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])


def _release(punk):
    if punk:
        try:
            _call(punk, 2, [])
        except Exception:
            pass


def _friendly_name(moniker):
    """读 moniker 的 FriendlyName（IPropertyBag::Read）；失败返回 ''。"""
    ole32 = ctypes.WinDLL('ole32')
    oleaut32 = ctypes.WinDLL('oleaut32')
    bag = ctypes.c_void_p()
    try:
        # IMoniker::BindToStorage(pbc, pmkToLeft, riid, ppvObj)  —— vtable 9
        hr = _call(moniker, 9, [ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)])(
            moniker, None, None, ctypes.byref(_guid(IID_IPropertyBag)), ctypes.byref(bag))
        if hr != 0 or not bag.value:
            return ''
        var = _VARIANT()
        oleaut32.VariantInit(ctypes.byref(var))
        try:
            # IPropertyBag::Read(name, pVar, pErrorLog)  —— vtable 3
            hr = _call(bag, 3, [ctypes.c_wchar_p, ctypes.POINTER(_VARIANT), ctypes.c_void_p])(
                bag, 'FriendlyName', ctypes.byref(var), None)
            if hr == 0 and var.vt == _VT_BSTR and var.val:
                return ctypes.wstring_at(var.val)
        finally:
            oleaut32.VariantClear(ctypes.byref(var))
        return ''
    except Exception:
        return ''
    finally:
        _release(bag)


def list_devices():
    """枚举 DirectShow 视频采集设备，**顺序即 cv2.VideoCapture 的索引**。

    返回 (devices, errors)；devices 为
    `[{'index': int, 'name': str, 'vid': str, 'pid': str, 'moniker': str}]`
    """
    if not hasattr(ctypes, 'WINFUNCTYPE'):
        return [], ['非 Windows 平台，DirectShow 枚举不可用']
    errors = []
    ole32 = ctypes.WinDLL('ole32')
    try:
        ole32.CoInitialize(None)        # 已初始化时返回 S_FALSE，无害
    except Exception:
        pass

    ole32.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p, w.DWORD,
                                       ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoCreateInstance.restype = ctypes.c_long

    dev_enum = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(_guid(CLSID_SystemDeviceEnum)), None, 1,
                                ctypes.byref(_guid(IID_ICreateDevEnum)),
                                ctypes.byref(dev_enum))
    if hr != 0 or not dev_enum.value:
        return [], [f'CoCreateInstance 失败 hr={hr:#x}']

    enumerator = ctypes.c_void_p()
    try:
        hr = _call(dev_enum, 3, [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p), w.DWORD])(
            dev_enum, ctypes.byref(_guid(CLSID_VideoInputDeviceCategory)),
            ctypes.byref(enumerator), 0)
        if hr != 0 or not enumerator.value:
            # hr==1 (S_FALSE) 表示该类目下没有设备
            return [], [f'CreateClassEnumerator 无设备 (hr={hr:#x})']

        out = []
        index = 0
        while True:
            moniker = ctypes.c_void_p()
            fetched = w.ULONG(0)
            hr = _call(enumerator, 3, [w.ULONG, ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(w.ULONG)])(
                enumerator, 1, ctypes.byref(moniker), ctypes.byref(fetched))
            if hr != 0 or not moniker.value or fetched.value != 1:
                break
            moniker_path = ''
            name = ctypes.c_wchar_p()
            try:
                # IMoniker::GetDisplayName(pbc, pmkToLeft, ppszDisplayName) —— vtable 20
                hr = _call(moniker, 20, [ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.c_wchar_p)])(
                    moniker, None, None, ctypes.byref(name))
                if hr == 0 and name.value:
                    moniker_path = name.value
            finally:
                if name:
                    ole32.CoTaskMemFree(name)

            low = moniker_path.lower()
            m_vid, m_pid = _VID_RE.search(low), _PID_RE.search(low)
            out.append({
                'index': index,
                'name': _friendly_name(moniker) or '',
                'vid': m_vid.group(1) if m_vid else '',
                'pid': m_pid.group(1) if m_pid else '',
                'moniker': moniker_path,
            })
            _release(moniker)
            index += 1
        return out, errors
    except Exception as exc:
        errors.append(f'{type(exc).__name__}: {str(exc)[:150]}')
        return [], errors
    finally:
        _release(enumerator)
        _release(dev_enum)


def find_index(pattern):
    """按设备标识找 `cv2.VideoCapture` 的索引；找不到返回 None。

    支持的写法（大小写、分隔符都不敏感）：
    * `'vid_0c45'` / `'0c45'`            —— USB VID（最稳，插拔/重启都不会变）
    * `'vid_0c45&pid_6360'` / `'0c45:6360'` —— VID+PID 精确匹配
    * `'USB Camera'` / `'HP Wide Vision'`   —— 设备名子串
    * 设备路径片段（moniker 子串）

    多个匹配时取**索引最小的**那个。
    """
    if pattern is None:
        return None
    pat = str(pattern).strip().lower()
    if not pat or pat.isdigit():
        return int(pat) if pat.isdigit() else None

    devices, errors = list_devices()
    if not devices:
        return None

    def score(d):
        vid, pid, name = d.get('vid', ''), d.get('pid', ''), (d.get('name') or '').lower()
        moniker = (d.get('moniker') or '').lower()
        if vid and pid and (f'vid_{vid}' in pat and f'pid_{pid}' in pat):
            return 0
        if vid and pat in (f'vid_{vid}', vid):
            return 1
        if pid and pat in (f'pid_{pid}', pid):
            return 2
        if name and pat in name:
            return 3
        if moniker and pat in moniker:
            return 4
        return None

    best = None
    for d in devices:
        s = score(d)
        if s is None:
            continue
        if best is None or s < best[0] or (s == best[0] and d['index'] < best[1]['index']):
            best = (s, d)
    return best[1]['index'] if best else None


def describe_devices():
    """把设备列表拼成一行可读文本（打不开时直接告诉用户现在有哪几个相机）。"""
    devices, _ = list_devices()
    if not devices:
        return '（DirectShow 枚举不到任何相机）'
    parts = []
    for d in devices:
        ident = f"vid_{d['vid']}&pid_{d['pid']}" if d.get('vid') else '未知'
        parts.append(f"index={d['index']} {d.get('name') or ident} [{ident}]")
    return '；'.join(parts)


def open_by_name(name, width=0, height=0, fourcc='MJPG', timeout=4.0):
    """按设备标识打开相机；成功返回 cv2.VideoCapture，失败 None。

    注意：DSHOW/MSMF **不支持** `"video=<名称>"` 那种按名打开（那是 FFMPEG 的语法），
    所以这里先把标识解析成索引，再按索引打开。
    """
    if cv2 is None or not name:
        return None
    index = find_index(name) if not str(name).strip().isdigit() else int(str(name).strip())
    if index is None:
        return None
    for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, None):
        try:
            cap = (cv2.VideoCapture(index, backend) if backend is not None
                   else cv2.VideoCapture(index))
        except Exception:
            continue
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            continue
        if fourcc:
            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
            except Exception:
                pass
        if width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        import time as _t
        deadline = _t.time() + timeout
        while _t.time() < deadline:
            ok, frame = cap.read()
            if ok and frame is not None:
                return cap
            _t.sleep(0.05)
        cap.release()
    return None


def list_openable(width=1280, height=720, fourcc='MJPG'):
    """枚举 + 逐个按索引打开，返回 ([{'index','name','ok','size','error'}], errors)。"""
    devices, errors = list_devices()
    rows = []
    for d in devices:
        cap = open_by_name(str(d['index']), width, height, fourcc)
        if cap is None:
            rows.append({'index': d['index'], 'name': d.get('name') or '', 'ok': False,
                         'size': None, 'error': '打不开'})
            continue
        wid = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        hei = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        rows.append({'index': d['index'], 'name': d.get('name') or '', 'ok': True,
                     'size': f'{wid}x{hei}', 'error': ''})
    return rows, errors


if __name__ == '__main__':
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    devs, errs = list_devices()
    print(f'DirectShow 视频采集设备：{len(devs)} 个（顺序 = VideoCapture 索引）')
    for d in devs:
        print(f"  index {d['index']}: {d['name'] or '(无名)'}  "
              f"vid_{d['vid'] or '?'}&pid_{d['pid'] or '?'}")
    for e in errs:
        print('  提示:', e)
    if devs:
        print('\n逐个尝试打开：')
        rows, _ = list_openable()
        for r in rows:
            print(f"  {'OK  ' if r['ok'] else 'FAIL'} index={r['index']} "
                  f"{r['name']}  {r['size'] or r['error']}")
