import hashlib
import json
import os
import re
import shutil
import socket
import struct
import sys
import time
import threading
import urllib.request
import urllib.error
import zlib
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

SAVED_REQUESTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saved_requests.json')
BOOKMARKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bookmarks.json')
WHITEBOARD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'whiteboard.json')
POMODORO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pomodoro.json')
CLIPBOARD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'clipboard.json')
UI_PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui_prefs.json')


def load_ui_prefs():
    """通用 UI 偏好（tab 顺序等），跨浏览器/设备共享，不随浏览器缓存清除而丢"""
    try:
        with open(UI_PREFS_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_ui_prefs(data):
    tmp = UI_PREFS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, UI_PREFS_FILE)


def _migrate_items(items):
    changed = False
    for it in items:
        if 'type' not in it:
            it['type'] = 'apitest'
            changed = True
        if 'category' not in it:
            it['category'] = '默认分类'
            changed = True
        if it.get('method') is None:
            it['method'] = 'GET'
        if it.get('headers') is None:
            it['headers'] = {}
        if it.get('body') is None:
            it['body'] = ''
    return items, changed


def load_saved_requests():
    if not os.path.exists(SAVED_REQUESTS_FILE):
        return []
    try:
        with open(SAVED_REQUESTS_FILE, 'r', encoding='utf-8') as f:
            items = json.load(f)
        items, changed = _migrate_items(items)
        if changed:
            save_saved_requests(items)
        return items
    except Exception:
        return []


def save_saved_requests(items):
    with open(SAVED_REQUESTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def load_bookmarks():
    default = {
        "categories": [{"id": "default", "name": "未分类"}],
        "bookmarks": []
    }
    if not os.path.exists(BOOKMARKS_FILE):
        return default
    try:
        with open(BOOKMARKS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default
        if not isinstance(data.get('categories'), list):
            data['categories'] = default['categories']
        if not isinstance(data.get('bookmarks'), list):
            data['bookmarks'] = []
        if not any(c.get('id') == 'default' for c in data['categories']):
            data['categories'].insert(0, {"id": "default", "name": "未分类"})
        return data
    except Exception:
        return default


def save_bookmarks(data):
    with open(BOOKMARKS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# 白板矢量页校验参数：单页 strokes JSON 序列化上限 2MB（矢量数据远小于位图）
WHITEBOARD_MAX_BYTES = 2 * 1024 * 1024
WB_STROKE_TOOLS = {'p', 'e', 'l', 'r', 'o', 't', 'c'}  # 画笔/橡皮/直线/矩形/椭圆/文本/清空标记
WB_MAX_STROKES = 5000    # 单页操作数上限
WB_MAX_PTS = 20000       # 单笔点数上限
WB_COORD_EPS = 0.1       # 归一化坐标容差（允许拖出画布边界）
WB_MAX_TEXT = 500        # 单条文本长度上限


def _wb_coord(v):
    """校验单个归一化坐标数字，合法返回 float，否则 None"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float('inf'), float('-inf')):  # NaN / Inf 防御
        return None
    if not (-WB_COORD_EPS <= f <= 1 + WB_COORD_EPS):
        return None
    return f


def _wb_point(p):
    """校验 [x, y] 点对，合法返回 [float, float]，否则 None"""
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        return None
    x, y = _wb_coord(p[0]), _wb_coord(p[1])
    if x is None or y is None:
        return None
    return [x, y]


def _clean_whiteboard_page(p):
    """校验并清洗单页矢量数据（strokes 操作序列），非法返回 None。
    操作格式：{t:'p'|'e', c?, w, pts} 画笔/橡皮路径
              {t:'l'|'r'|'o', c, w, a, b} 直线/矩形/椭圆
              {t:'t', c, f, a, str} 文本（f 归一化字号，str ≤500 字）
              {t:'c'} 清空标记
    旧位图格式（仅含 dataUrl 字段、无 strokes 键）的页直接丢弃。"""
    if not isinstance(p, dict) or not p.get('id'):
        return None
    if 'strokes' not in p:  # 旧位图格式页：废弃丢弃
        return None
    strokes = p['strokes']
    if strokes is None:
        strokes = []
    if not isinstance(strokes, list) or len(strokes) > WB_MAX_STROKES:
        return None
    clean = []
    for s in strokes:
        if not isinstance(s, dict):
            return None
        t = s.get('t')
        if t not in WB_STROKE_TOOLS:
            return None
        if t == 'c':
            clean.append({'t': 'c'})
            continue
        if t == 't':  # 文本操作：{t,c,f,a,str}，f 为归一化字号
            txt = s.get('str')
            if not isinstance(txt, str) or not txt or len(txt) > WB_MAX_TEXT:
                return None
            if any(ord(ch) < 32 and ch != '\n' for ch in txt):
                return None
            try:
                f = float(s.get('f'))
            except (TypeError, ValueError):
                return None
            if not (0 < f <= 0.5):
                return None
            a = _wb_point(s.get('a'))
            if a is None:
                return None
            c = s.get('c')
            if not isinstance(c, str) or not re.fullmatch(r'#[0-9a-fA-F]{3,8}', c):
                return None
            clean.append({'t': 't', 'c': c, 'f': f, 'a': a, 'str': txt})
            continue
        try:
            w = float(s.get('w'))
        except (TypeError, ValueError):
            return None
        if not (0 < w <= 0.5):  # 归一化线宽范围
            return None
        item = {'t': t, 'w': w}
        if t in ('p', 'e'):
            pts = s.get('pts')
            if not isinstance(pts, list) or not pts or len(pts) > WB_MAX_PTS:
                return None
            ok_pts = []
            for pt in pts:
                q = _wb_point(pt)
                if q is None:
                    return None
                ok_pts.append(q)
            item['pts'] = ok_pts
        else:  # 'l' / 'r' / 'o'
            a = _wb_point(s.get('a'))
            b = _wb_point(s.get('b'))
            if a is None or b is None:
                return None
            item['a'], item['b'] = a, b
        if t != 'e':  # 橡皮无颜色
            c = s.get('c')
            if not isinstance(c, str) or not re.fullmatch(r'#[0-9a-fA-F]{3,8}', c):
                return None
            item['c'] = c
        clean.append(item)
    try:
        updated_at = int(p.get('updatedAt') or 0)
    except (TypeError, ValueError):
        updated_at = 0
    page = {"id": str(p['id']), "strokes": clean, "updatedAt": updated_at}
    if len(json.dumps(page, ensure_ascii=False)) > WHITEBOARD_MAX_BYTES:
        return None
    return page


def load_whiteboard():
    default = {"pages": [], "updatedAt": 0}
    if not os.path.exists(WHITEBOARD_FILE):
        return default
    try:
        with open(WHITEBOARD_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default
        pages = []
        for p in (data.get('pages') or []):
            clean = _clean_whiteboard_page(p)
            if clean:
                pages.append(clean)
        return {"pages": pages, "updatedAt": int(data.get('updatedAt') or 0)}
    except Exception:
        return default


def save_whiteboard(data):
    with open(WHITEBOARD_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------- 番茄钟数据 ----------------
def _clean_pomodoro(data):
    """校验并规范化番茄钟数据"""
    if not isinstance(data, dict):
        return {"tasks": [], "history": [], "settings": {"focus": 25, "break": 5}}
    out = {"tasks": [], "history": [], "settings": {"focus": 25, "break": 5}}
    if isinstance(data.get('tasks'), list):
        for t in data['tasks']:
            if isinstance(t, dict) and t.get('name'):
                out['tasks'].append({
                    "id": str(t.get('id') or ('pm_' + str(len(out['tasks'])))),
                    "name": str(t['name'])[:200],
                    "done": bool(t.get('done')),
                    "pomodoros": max(0, int(t.get('pomodoros') or 0)),
                    "createdAt": int(t.get('createdAt') or 0),
                })
    if isinstance(data.get('history'), list):
        seen = set()
        for h in data['history']:
            if (isinstance(h, dict) and isinstance(h.get('date'), str)
                    and len(h['date']) == 10 and h['date'] not in seen):
                seen.add(h['date'])
                out['history'].append({
                    "date": h['date'],
                    "count": max(0, int(h.get('count') or 0)),
                    "minutes": max(0, int(h.get('minutes') or 0)),
                })
        out['history'].sort(key=lambda x: x['date'], reverse=True)
        out['history'] = out['history'][:366]
    s = data.get('settings') if isinstance(data.get('settings'), dict) else {}
    out['settings']['focus'] = min(180, max(1, int(s.get('focus') or 25)))
    out['settings']['break'] = min(60, max(1, int(s.get('break') or 5)))
    return out


def load_pomodoro():
    default = {"tasks": [], "history": [], "settings": {"focus": 25, "break": 5}}
    if not os.path.exists(POMODORO_FILE):
        return default
    try:
        with open(POMODORO_FILE, 'r', encoding='utf-8') as f:
            return _clean_pomodoro(json.load(f))
    except Exception:
        return default


def save_pomodoro(data):
    with open(POMODORO_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------- 宠物联动状态（番茄钟运行态，供桌面宠物轮询） ----------------
PET_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pet_state.json')


def _clean_pet_state(data):
    """校验并规范化宠物联动状态 {running, paused, mode, endsAt, left, note, noteAt}
    - running/paused: 计时是否进行中 / 是否暂停
    - mode: focus | break
    - endsAt: 运行中的结束时间戳（ms）；暂停时为 0
    - left: 暂停时的剩余秒数；运行中为 0
    - note/noteAt: 一次性通知文本与时间戳（如「专注完成」），宠物按 noteAt 变化触发气泡
    """
    default = {"running": False, "paused": False, "mode": "focus", "endsAt": 0, "left": 0,
               "note": "", "noteAt": 0, "updatedAt": 0}
    if not isinstance(data, dict):
        return default
    note = data.get('note')
    try:
        ends_at = max(0, int(data.get('endsAt') or 0))
        left = min(24 * 3600, max(0, int(data.get('left') or 0)))
        note_at = max(0, int(data.get('noteAt') or 0))
    except (TypeError, ValueError):
        return default
    return {
        "running": bool(data.get('running')),
        "paused": bool(data.get('paused')),
        "mode": 'break' if data.get('mode') == 'break' else 'focus',
        "endsAt": ends_at,
        "left": left,
        "note": str(note)[:60] if isinstance(note, str) and note.strip() else '',
        "noteAt": note_at,
        "updatedAt": int(time.time() * 1000),
    }


def load_pet_state():
    if not os.path.exists(PET_STATE_FILE):
        return _clean_pet_state({})
    try:
        with open(PET_STATE_FILE, 'r', encoding='utf-8') as f:
            return _clean_pet_state(json.load(f))
    except Exception:
        return _clean_pet_state({})


def save_pet_state(data):
    tmp = PET_STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, PET_STATE_FILE)


# ---------------- 剪贴板历史（Windows 系统级监听，文本 + 图片） ----------------
CLIP_MAX_ITEMS = 200      # 最多保留条数
CLIP_MAX_TEXT = 100000    # 单条文本长度上限（字符）
CLIP_MAX_IMG_BYTES = 10 * 1024 * 1024   # 单张图片 PNG 上限（10MB）
CLIP_IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'clipboard_files')

# ---- 系统状态采集（/api/sysinfo）：ctypes + 标准库，零第三方依赖 ----
_SERVER_START = time.time()
_sys_cpu_last = None
_sys_net_cache = {'t': 0.0, 'data': None}
_sys_pubip_cache = {}   # {'v4': (时间, ip), 'v6': (时间, ip)}


def _sys_cpu_percent():
    """GetSystemTimes 两次采样差值算 CPU 使用率；基线超 10 秒作废重来"""
    global _sys_cpu_last
    if sys.platform != 'win32':
        return None
    import ctypes
    class FT(ctypes.Structure):
        _fields_ = [('lo', ctypes.c_uint32), ('hi', ctypes.c_uint32)]
    idle, kern, user = FT(), FT(), FT()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
        return None
    now = (idle.lo | (idle.hi << 32), kern.lo | (kern.hi << 32),
           user.lo | (user.hi << 32), time.time())
    last = _sys_cpu_last
    _sys_cpu_last = now
    if not last or now[3] - last[3] > 10:
        return None
    total = (now[1] + now[2]) - (last[1] + last[2])
    if total <= 0:
        return None
    return round((total - (now[0] - last[0])) * 100.0 / total, 1)


def _sys_cpu_name():
    if sys.platform != 'win32':
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:
            return str(winreg.QueryValueEx(k, 'ProcessorNameString')[0]).strip()
    except Exception:
        return None


def _sys_mem():
    if sys.platform != 'win32':
        return None
    import ctypes
    class MSEX(ctypes.Structure):
        _fields_ = [('len', ctypes.c_uint32), ('load', ctypes.c_uint32),
                    ('total', ctypes.c_uint64), ('avail', ctypes.c_uint64),
                    ('tp', ctypes.c_uint64), ('ap', ctypes.c_uint64),
                    ('tv', ctypes.c_uint64), ('av', ctypes.c_uint64),
                    ('ae', ctypes.c_uint64)]
    m = MSEX()
    m.len = ctypes.sizeof(MSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    return {'percent': m.load, 'total': m.total, 'avail': m.avail}


def _sys_disks():
    """仅固定磁盘（GetDriveTypeW==3），跳过光驱/网络盘/可移动盘"""
    out = []
    if sys.platform == 'win32':
        import ctypes
        import string
        for ch in string.ascii_uppercase:
            drive = ch + ':\\'
            if not os.path.exists(drive):
                continue
            if ctypes.windll.kernel32.GetDriveTypeW(drive) != 3:
                continue
            try:
                du = shutil.disk_usage(drive)
            except Exception:
                continue
            pct = round(du.used * 100.0 / du.total, 1) if du.total else 0
            out.append({'drive': ch + ':', 'total': du.total, 'free': du.free,
                        'used': du.used, 'percent': pct})
    else:
        try:
            du = shutil.disk_usage('/')
            pct = round(du.used * 100.0 / du.total, 1) if du.total else 0
            out.append({'drive': '/', 'total': du.total, 'free': du.free,
                        'used': du.used, 'percent': pct})
        except Exception:
            pass
    return out


def _sys_public_ip():
    """公网出口 IPv4/IPv6：成功缓存 10 分钟，失败缓存 60 秒（断网不反复卡超时）"""
    now = time.time()
    out = {}
    for fam, url in (('v4', 'https://api-ipv4.ip.sb/ip'),
                     ('v6', 'https://api-ipv6.ip.sb/ip')):
        t, ip = _sys_pubip_cache.get(fam, (0.0, None))
        if now - t < (600 if ip else 60):
            out[fam] = ip
            continue
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'curl/8.0'})
            with urllib.request.urlopen(req, timeout=2) as r:
                v = r.read().decode('utf-8', 'ignore').strip()
            ip = v or None
        except Exception:
            ip = None
        _sys_pubip_cache[fam] = (now, ip)
        out[fam] = ip
    return out['v4'], out['v6']


def _sys_net():
    """本机出口 IP + 外网 TCP 连接延迟（3 秒缓存，避免高频轮询反复探测）"""
    global _sys_net_cache
    if time.time() - _sys_net_cache['t'] < 3 and _sys_net_cache['data']:
        return _sys_net_cache['data']
    info = {'localIp': None, 'publicIp': None, 'publicIp6': None, 'latencyMs': None, 'ok': False}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('223.5.5.5', 80))
            info['localIp'] = s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        pass
    t0 = time.time()
    try:
        s = socket.create_connection(('223.5.5.5', 443), timeout=1.2)
        s.close()
        info['latencyMs'] = round((time.time() - t0) * 1000, 1)
        info['ok'] = True
    except Exception:
        pass
    v4, v6 = _sys_public_ip()
    info['publicIp'] = v4
    info['publicIp6'] = v6
    # 缓存时间戳记「完成时刻」而非开始时刻：探测约 2 秒，若记开始时刻，
    # 浏览器 2 秒轮询的下一次请求到达时 age 已按开始时刻计算而恒 miss
    _sys_net_cache = {'t': time.time(), 'data': info}
    return info


def _sys_uptime():
    if sys.platform != 'win32':
        return None
    import ctypes
    return int(ctypes.windll.kernel32.GetTickCount64() // 1000)


def _sys_os_name():
    if sys.platform == 'win32':
        # Python 进程无 manifest 时 GetVersionEx 返回兼容假版本（6.2.9200），
        # 须读注册表拿真实版本号；Win11 的 ProductName 仍是 "Windows 10 xxx"，按 build 区分
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r'SOFTWARE\Microsoft\Windows NT\CurrentVersion') as k:
                build = int(winreg.QueryValueEx(k, 'CurrentBuildNumber')[0])
                name = str(winreg.QueryValueEx(k, 'ProductName')[0])
            disp = ''
            try:
                disp = ' ' + str(winreg.QueryValueEx(k, 'DisplayVersion')[0])
            except Exception:
                pass
            if build >= 22000:
                name = name.replace('Windows 10', 'Windows 11')
            return '%s%s (Build %d)' % (name, disp, build)
        except Exception:
            pass
        v = sys.getwindowsversion()
        nm = 'Windows 11' if v.build >= 22000 else 'Windows 10' if v.major == 10 else 'Windows %d' % v.major
        return '%s (Build %d)' % (nm, v.build)
    return sys.platform


def collect_sysinfo():
    return {
        'cpu': {'percent': _sys_cpu_percent(), 'cores': os.cpu_count(), 'name': _sys_cpu_name()},
        'mem': _sys_mem(),
        'disks': _sys_disks(),
        'os': _sys_os_name(),
        'hostname': socket.gethostname(),
        'python': sys.version.split()[0],
        'uptimeSec': _sys_uptime(),
        'serverUptimeSec': int(time.time() - _SERVER_START),
        'net': _sys_net(),
    }


_clip_lock = threading.Lock()
_clip_last_text = None            # 上一次记录的文本（去重）
_clip_last_img_hash = None        # 上一次记录图片的 md5（去重）


def _clip_load():
    if not os.path.exists(CLIPBOARD_FILE):
        return []
    try:
        with open(CLIPBOARD_FILE, 'r', encoding='utf-8') as f:
            items = json.load(f)
        if isinstance(items, list):
            # 合法条目：文本条（含 text 字段）或图片条（type=image 且有文件名）
            return [i for i in items if isinstance(i, dict) and i.get('id') and (
                isinstance(i.get('text'), str)
                or (i.get('type') == 'image' and isinstance(i.get('file'), str) and i.get('file')))]
    except Exception:
        pass
    return []


def _clip_save(items):
    tmp = CLIPBOARD_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp, CLIPBOARD_FILE)


def _clip_remove_files(items):
    """删除记录对应的图片文件（记录被裁剪 / 删除 / 清空时调用）"""
    for it in items:
        if isinstance(it, dict) and it.get('type') == 'image' and it.get('file'):
            try:
                os.remove(os.path.join(CLIP_IMG_DIR, os.path.basename(it['file'])))
            except OSError:
                pass


def _clip_add(text, announce=True):
    """记录一条剪贴板文本（线程安全，自动去重）"""
    global _clip_last_text
    text = text[:CLIP_MAX_TEXT]
    if not text.strip():
        return None
    with _clip_lock:
        items = _clip_load()
        if items and items[0].get('text') == text:
            return items[0]   # 最新一条相同，跳过（双通道去重）
        item = {
            "id": 'clip_' + str(int(time.time() * 1000)) + '_' + str(len(items)),
            "text": text,
            "time": int(time.time() * 1000),
        }
        items.insert(0, item)
        removed = items[CLIP_MAX_ITEMS:]
        del items[CLIP_MAX_ITEMS:]
        _clip_save(items)
        _clip_remove_files(removed)
        _clip_last_text = text
        return item


def _dib_to_png(dib):
    """CF_DIB 位图数据（BITMAPINFOHEADER + 像素）转 PNG 字节（纯标准库实现）。
    支持 BI_RGB(0) 与 BI_BITFIELDS(3)（截图工具常用，头后跟 3 个 DWORD 颜色掩码），
    24/32bpp（BITFIELDS 仅 32bpp）；返回 (png_bytes, width, height)，失败返回 None。"""
    if not dib or len(dib) < 40:
        return None
    bi_size, width, height, _planes, bpp, compression = struct.unpack_from('<IiiHHI', dib, 0)[:6]
    if width <= 0 or height == 0 or bpp not in (24, 32):
        return None
    top_down = height < 0          # 负高度 = 自顶向下存储
    height = -height if top_down else height
    px_off = bi_size               # 像素数据起始偏移
    rsh = gsh = bsh = None         # 颜色掩码移位（BI_BITFIELDS 用）
    if compression == 3:           # BI_BITFIELDS：掩码定义像素内各通道位置
        if bpp != 32:
            return None
        if bi_size in (40, 52, 56):      # 经典头：3 个掩码 DWORD 紧跟头之后
            if len(dib) < bi_size + 12:
                return None
            rm, gm, bm = struct.unpack_from('<III', dib, bi_size)
            px_off = bi_size + 12
        elif bi_size >= 108:             # V4/V5 头：掩码在头内偏移 40 处
            rm, gm, bm = struct.unpack_from('<III', dib, 40)
        else:
            return None

        def _mask_shift(m):
            if not m:
                return None
            s = 0
            while not (m & 1):
                m >>= 1
                s += 1
            return s if m == 0xFF else None   # 掩码须为连续 8 位

        rsh, gsh, bsh = _mask_shift(rm), _mask_shift(gm), _mask_shift(bm)
        if None in (rsh, gsh, bsh):
            return None
    elif compression != 0:
        return None
    row_size = ((bpp // 8 * width + 3) // 4) * 4   # 每行按 4 字节对齐
    data = dib[px_off:]             # 24/32bpp 无调色板，像素紧跟头/掩码
    if len(data) < row_size * height:
        return None
    # 标准掩码（R=16/G=8/B=0 位）与 BI_RGB 32bpp 内存布局相同（BGRA），走快速切片路径
    bgra_fast = bpp == 32 and (rsh, gsh, bsh) in ((16, 8, 0), (None, None, None))
    rows = []
    for y in range(height):
        sy = y if top_down else height - 1 - y
        row = data[sy * row_size: sy * row_size + width * (bpp // 8)]  # 裁掉行尾对齐填充
        rgb = bytearray(width * 3)
        if bpp == 24:              # BGR → RGB
            rgb[0::3] = row[2::3]
            rgb[1::3] = row[1::3]
            rgb[2::3] = row[0::3]
        elif bgra_fast:            # BGRA → RGB（忽略 alpha，剪贴板 alpha 常为无效值）
            rgb[0::3] = row[2::4]
            rgb[1::3] = row[1::4]
            rgb[2::3] = row[0::4]
        else:                      # 非标准掩码：逐像素按 DWORD 移位提取
            for x in range(width):
                v = int.from_bytes(row[x * 4:x * 4 + 4], 'little')
                rgb[x * 3] = (v >> rsh) & 0xFF
                rgb[x * 3 + 1] = (v >> gsh) & 0xFF
                rgb[x * 3 + 2] = (v >> bsh) & 0xFF
        rows.append(bytes(rgb))
    raw = b''.join(b'\x00' + r for r in rows)   # 每扫描行前置过滤字节 0

    def chunk(tag, payload):
        return (struct.pack('>I', len(payload)) + tag + payload
                + struct.pack('>I', zlib.crc32(tag + payload) & 0xffffffff))

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)   # 8bit 真彩色
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
           + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))
    return png, width, height


def _png_size(png):
    """解析 PNG IHDR，返回 (width, height)，非法返回 None"""
    if not png or png[:8] != b'\x89PNG\r\n\x1a\n' or len(png) < 24:
        return None
    return struct.unpack('>II', png[16:24])


def _png_trim(png):
    """校验 PNG 完整性并裁掉 IEND 之后的多余字节（GlobalSize 可能大于实际数据），
    完整返回裁剪后的 PNG 字节，否则 None"""
    if not png or png[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    i = 8
    while i + 12 <= len(png):
        (ln,) = struct.unpack_from('>I', png, i)
        tag = png[i + 4:i + 8]
        i += 12 + ln
        if tag == b'IEND':
            return png[:i]
    return None


def _clip_add_image(png, w, h):
    """记录一张剪贴板图片（PNG 存 clipboard_files/，线程安全去重）"""
    global _clip_last_img_hash
    if not png or len(png) > CLIP_MAX_IMG_BYTES:
        return None
    hsh = hashlib.md5(png).hexdigest()
    with _clip_lock:
        if hsh == _clip_last_img_hash:
            return None
        items = _clip_load()
        try:
            os.makedirs(CLIP_IMG_DIR, exist_ok=True)
            fname = 'clip_img_' + str(int(time.time() * 1000)) + '_' + str(len(items)) + '.png'
            with open(os.path.join(CLIP_IMG_DIR, fname), 'wb') as f:
                f.write(png)
        except OSError:
            return None
        item = {
            "id": 'clipimg_' + str(int(time.time() * 1000)) + '_' + str(len(items)),
            "type": "image",
            "file": fname,
            "w": int(w),
            "h": int(h),
            "time": int(time.time() * 1000),
        }
        items.insert(0, item)
        removed = items[CLIP_MAX_ITEMS:]
        del items[CLIP_MAX_ITEMS:]
        _clip_save(items)
        _clip_remove_files(removed)
        _clip_last_img_hash = hsh
        return item


def clipboard_watcher():
    """后台线程：轮询 Windows 剪贴板序号，变化时读取文本或位图记录（仅 Windows）"""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
    except ImportError:
        return
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13
    CF_DIB = 8
    # 截图工具（Win+Shift+S / 飞书 / 微信等）普遍会放一份原生 PNG 格式，优先直读（无损）
    user32.RegisterClipboardFormatW.restype = ctypes.c_uint
    user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
    CF_PNG = user32.RegisterClipboardFormatW('PNG')
    # 64 位下必须显式声明指针类型，否则 HANDLE 被 int 截断导致 GlobalLock 失败
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
    last_seq = user32.GetClipboardSequenceNumber()
    global _clip_last_text
    while True:
        try:
            seq = user32.GetClipboardSequenceNumber()
            if seq != last_seq:
                last_seq = seq
                text = None
                png = None
                dib = None
                if user32.OpenClipboard(None):
                    try:
                        handle = user32.GetClipboardData(CF_UNICODETEXT)
                        if handle:
                            ptr = kernel32.GlobalLock(ctypes.c_void_p(handle))
                            if ptr:
                                try:
                                    text = ctypes.wstring_at(ptr)
                                finally:
                                    kernel32.GlobalUnlock(ctypes.c_void_p(ptr))
                        if not text:
                            # 无文本 → 图片：优先读原生 PNG 格式（无损直存）
                            if CF_PNG:
                                hp = user32.GetClipboardData(CF_PNG)
                                if hp:
                                    pp = kernel32.GlobalLock(ctypes.c_void_p(hp))
                                    if pp:
                                        try:
                                            size = kernel32.GlobalSize(ctypes.c_void_p(hp))
                                            if size:
                                                png = ctypes.string_at(pp, size)
                                        finally:
                                            kernel32.GlobalUnlock(ctypes.c_void_p(pp))
                            # CF_DIB 位图兜底（仅提供位图格式的应用）
                            if not png:
                                hdib = user32.GetClipboardData(CF_DIB)
                                if hdib:
                                    pdib = kernel32.GlobalLock(ctypes.c_void_p(hdib))
                                    if pdib:
                                        try:
                                            size = kernel32.GlobalSize(ctypes.c_void_p(hdib))
                                            if size:
                                                dib = ctypes.string_at(pdib, size)
                                        finally:
                                            kernel32.GlobalUnlock(ctypes.c_void_p(pdib))
                    finally:
                        user32.CloseClipboard()
                # 剪贴板已关闭，再做耗时的解析/转换与写盘（避免长时间占用剪贴板锁）
                if text:
                    if text != _clip_last_text:
                        _clip_add(text)
                elif png or dib:
                    img = None
                    if png:
                        trimmed = _png_trim(png)
                        sz = _png_size(trimmed) if trimmed else None
                        if trimmed and sz:
                            img = (trimmed, sz[0], sz[1])
                    if img is None and dib:
                        img = _dib_to_png(dib)
                    if img:
                        _clip_add_image(*img)
        except Exception:
            pass
        time.sleep(0.5)


# ---------------- 公共聊天频道（文本 + 图片/文件附件，局域网共享） ----------------
CHAT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat.json')
CHAT_FILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat_files')
CHAT_MAX_ITEMS = 300                  # 最多保留消息条数
CHAT_MAX_TEXT = 5000                  # 单条文本长度上限（字符）
CHAT_MAX_NAME = 24                    # 昵称长度上限
# 附件不设大小上限：上传/下载均为流式分块读写，内存占用与文件大小无关（受磁盘约束）
CHAT_IMG_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}

_chat_lock = threading.Lock()

# 附件扩展名 → Content-Type（未知类型按下载处理）
_CHAT_CT = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
    '.txt': 'text/plain; charset=utf-8', '.json': 'application/json; charset=utf-8',
    '.pdf': 'application/pdf', '.zip': 'application/zip',
}


def _chat_load():
    if not os.path.exists(CHAT_FILE):
        return []
    try:
        with open(CHAT_FILE, 'r', encoding='utf-8') as f:
            items = json.load(f)
        if isinstance(items, list):
            return [i for i in items if isinstance(i, dict) and i.get('id')
                    and (isinstance(i.get('text'), str) or i.get('file'))]
    except Exception:
        pass
    return []


def _chat_save(items):
    tmp = CHAT_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp, CHAT_FILE)


def _chat_remove_files(items):
    """消息被裁剪/删除时，删除对应的附件文件"""
    for it in items:
        if isinstance(it, dict) and it.get('file'):
            try:
                os.remove(os.path.join(CHAT_FILES_DIR, os.path.basename(it['file'])))
            except OSError:
                pass


def _chat_clean_name(v):
    s = str(v or '').strip()[:CHAT_MAX_NAME]
    return s or '匿名用户'


def _chat_clean_color(v):
    s = str(v or '').strip()
    return s if re.fullmatch(r'#[0-9a-fA-F]{6}', s) else '#60a5fa'


def _chat_add_text(client_id, name, color, text):
    """追加一条文本消息（调用方无需持锁）"""
    if not isinstance(text, str):
        return None
    text = text.strip()[:CHAT_MAX_TEXT]
    if not text:
        return None
    with _chat_lock:
        items = _chat_load()
        item = {
            "id": 'm_' + str(int(time.time() * 1000)) + '_' + str(len(items)),
            "clientId": str(client_id or '')[:64],
            "name": _chat_clean_name(name),
            "color": _chat_clean_color(color),
            "type": "text",
            "text": text,
            "time": int(time.time() * 1000),
        }
        items.insert(0, item)
        removed = items[CHAT_MAX_ITEMS:]
        del items[CHAT_MAX_ITEMS:]
        _chat_save(items)
        _chat_remove_files(removed)
        return item


def _chat_add_attachment(client_id, name, color, fname, is_image, src, length):
    """流式落盘一个附件并生成对应消息（1MB 分块边收边写，内存占用与文件大小无关，不设上限）。
    src: 请求 body 流（read(n)），length: Content-Length。返回 (item, error)，成功时 error 为 None"""
    if not length:
        return None, 'empty file'
    ext = os.path.splitext(os.path.basename(str(fname or '')))[1].lower()
    if len(ext) > 10:
        ext = ''
    os.makedirs(CHAT_FILES_DIR, exist_ok=True)
    # 文件名带随机后缀：落盘在锁外进行（不能持锁等网络），随机串避免并发同名
    stored = 'chat_' + str(int(time.time() * 1000)) + '_' + os.urandom(3).hex() + ext
    path = os.path.join(CHAT_FILES_DIR, stored)
    size = 0
    try:
        with open(path, 'wb') as f:
            remaining = length
            while remaining > 0:
                chunk = src.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ConnectionError('client aborted')
                f.write(chunk)
                size += len(chunk)
                remaining -= len(chunk)
    except (OSError, ConnectionError):
        try:
            os.remove(path)
        except OSError:
            pass
        return None, 'save failed'
    w = h = None
    if ext == '.png':
        try:
            with open(path, 'rb') as f:
                head = f.read(24)  # IHDR 尺寸只需前 24 字节
            sz = _png_size(head)
            if sz:
                w, h = sz
        except OSError:
            pass
    disp_name = os.path.basename(str(fname or stored))[:120]
    with _chat_lock:
        items = _chat_load()
        item = {
            "id": 'm_' + str(int(time.time() * 1000)) + '_' + str(len(items)),
            "clientId": str(client_id or '')[:64],
            "name": _chat_clean_name(name),
            "color": _chat_clean_color(color),
            "type": "image" if is_image else "file",
            "file": stored,
            "fileName": disp_name,
            "fileSize": size,
            "w": w,
            "h": h,
            "time": int(time.time() * 1000),
        }
        items.insert(0, item)
        removed = items[CHAT_MAX_ITEMS:]
        del items[CHAT_MAX_ITEMS:]
        _chat_save(items)
        _chat_remove_files(removed)
        return item, None


def _chat_delete(msg_id, client_id):
    """删除消息：仅消息发送者本人可删（clientId 匹配）"""
    with _chat_lock:
        items = _chat_load()
        removed = [i for i in items if i.get('id') == msg_id and i.get('clientId') == client_id]
        if not removed:
            return False
        items = [i for i in items if i.get('id') != msg_id or i.get('clientId') != client_id]
        _chat_save(items)
        _chat_remove_files(removed)
        return True


# ---------------- 本地媒体库（音乐 + 视频，扫描 / 分类 / Range 流式播放） ----------------
# 所有媒体库数据收拢到 media_data/ 目录：library.json / danmaku.json / thumbs/ / covers/
MEDIA_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'media_data')
MEDIA_FILE = os.path.join(MEDIA_DATA_DIR, 'library.json')
MEDIA_THUMBS_DIR = os.path.join(MEDIA_DATA_DIR, 'thumbs')
MEDIA_COVERS_DIR = os.path.join(MEDIA_DATA_DIR, 'covers')


def _media_migrate_data_dir():
    """首次升级：把散落在工程根目录的旧数据迁移进 media_data/（幂等，已存在则合并）"""
    try:
        os.makedirs(MEDIA_DATA_DIR, exist_ok=True)
        os.makedirs(MEDIA_THUMBS_DIR, exist_ok=True)
        os.makedirs(MEDIA_COVERS_DIR, exist_ok=True)
        base = os.path.dirname(os.path.abspath(__file__))

        def _move_file(old, new):
            if os.path.isfile(old) and not os.path.exists(new):
                shutil.move(old, new)

        def _move_dir_contents(old_dir, new_dir):
            if not os.path.isdir(old_dir):
                return
            for name in os.listdir(old_dir):
                op, np_ = os.path.join(old_dir, name), os.path.join(new_dir, name)
                if not os.path.exists(np_):
                    try:
                        shutil.move(op, np_)
                    except OSError:
                        pass
            try:
                os.rmdir(old_dir)
            except OSError:
                pass

        _move_file(os.path.join(base, 'media_library.json'), MEDIA_FILE)
        _move_file(os.path.join(base, 'danmaku.json'), os.path.join(MEDIA_DATA_DIR, 'danmaku.json'))
        _move_dir_contents(os.path.join(base, 'media_thumbs'), MEDIA_THUMBS_DIR)
        _move_dir_contents(os.path.join(base, 'media_covers'), MEDIA_COVERS_DIR)
    except Exception:
        pass


_media_migrate_data_dir()
MEDIA_MUSIC_EXTS = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma'}
MEDIA_VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.wmv', '.flv', '.m4v', '.ts', '.mpg', '.mpeg'}

_media_lock = threading.Lock()

_MEDIA_CT = {
    '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.flac': 'audio/flac',
    '.aac': 'audio/aac', '.ogg': 'audio/ogg', '.m4a': 'audio/mp4', '.wma': 'audio/x-ms-wma',
    '.mp4': 'video/mp4', '.mkv': 'video/x-matroska', '.avi': 'video/x-msvideo',
    '.mov': 'video/quicktime', '.webm': 'video/webm', '.wmv': 'video/x-ms-wmv',
    '.flv': 'video/x-flv', '.m4v': 'video/x-m4v', '.ts': 'video/mp2t',
    '.mpg': 'video/mpeg', '.mpeg': 'video/mpeg',
}


def _media_load():
    """读取媒体库 JSON，返回完整 dict 结构"""
    if not os.path.exists(MEDIA_FILE):
        return {'scanRoots': {'music': [], 'video': []},
                'categories': {'music': [{'id': 'default', 'name': '未分类'}],
                               'video': [{'id': 'default', 'name': '未分类'}]},
                'files': [], 'updatedAt': 0}
    try:
        with open(MEDIA_FILE, 'r', encoding='utf-8') as f:
            lib = json.load(f)
        if not isinstance(lib, dict):
            raise ValueError
        lib.setdefault('scanRoots', {'music': [], 'video': []})
        lib.setdefault('categories', {'music': [{'id': 'default', 'name': '未分类'}],
                                     'video': [{'id': 'default', 'name': '未分类'}]})
        lib.setdefault('files', [])
        lib.setdefault('updatedAt', 0)
        return lib
    except Exception:
        return {'scanRoots': {'music': [], 'video': []},
                'categories': {'music': [{'id': 'default', 'name': '未分类'}],
                               'video': [{'id': 'default', 'name': '未分类'}]},
                'files': [], 'updatedAt': 0}


def _media_save(lib):
    tmp = MEDIA_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(lib, f, ensure_ascii=False)
    os.replace(tmp, MEDIA_FILE)


def _media_gen_id(abs_path, mtime):
    """根据路径 + 修改时间生成稳定 ID"""
    h = hashlib.md5(abs_path.encode('utf-8')).hexdigest()[:8]
    return 'm_{}_{}'.format(int(mtime), h)


def _media_stable_key(name, size):
    """稳定关联键：文件名 + 大小。
    文件被移动/改名目录/复制导致 mtime 或路径变化时，ID 会变，但同名同大小文件可凭此键找回
    封面/弹幕/分类/标签/简介等用户数据"""
    return (name or '').lower() + '|' + str(int(size or 0))


def _media_migrate_assets(old_id, new_id):
    """ID 变化时迁移关联资产：封面图、音乐封面图、弹幕记录（按新 ID 重命名/改键）"""
    if old_id == new_id:
        return
    for d in (MEDIA_THUMBS_DIR, MEDIA_COVERS_DIR):
        old_p = os.path.join(d, old_id + '.jpg')
        new_p = os.path.join(d, new_id + '.jpg')
        try:
            if os.path.isfile(old_p) and not os.path.exists(new_p):
                shutil.move(old_p, new_p)
        except OSError:
            pass
    # 弹幕：danmaku.json 改键
    try:
        dm_path = os.path.join(MEDIA_DATA_DIR, 'danmaku.json')
        if os.path.isfile(dm_path):
            with open(dm_path, 'r', encoding='utf-8') as f:
                dm = json.load(f)
            if isinstance(dm, dict) and old_id in dm and new_id not in dm:
                dm[new_id] = dm.pop(old_id)
                tmp = dm_path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(dm, f, ensure_ascii=False)
                os.replace(tmp, dm_path)
    except Exception:
        pass


# ---------------- 视频弹幕存储 ----------------
DANMAKU_FILE = os.path.join(MEDIA_DATA_DIR, 'danmaku.json')
DANMAKU_MAX_PER_VIDEO = 8000


def _danmaku_load():
    if not os.path.exists(DANMAKU_FILE):
        return {}
    try:
        with open(DANMAKU_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _danmaku_save(data):
    tmp = DANMAKU_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, DANMAKU_FILE)


def _danmaku_parse_bili_xml(raw):
    """解析 B站弹幕 XML（<d p="time,mode,size,color,...">内容</d>），返回归一化弹幕列表。
    mode 归一：1/2/3/6→1滚动，4→4底部，5→5顶部；高级弹幕(7/8/9)忽略"""
    items = []
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(raw)
        nodes = root.iter('d')
        for d in nodes:
            p = d.get('p', '')
            text = (d.text or '').strip()
            if not p or not text:
                continue
            parts = p.split(',')
            if len(parts) < 4:
                continue
            try:
                t = float(parts[0])
                raw_mode = int(parts[1])
                color_int = int(parts[3])
            except ValueError:
                continue
            if raw_mode in (1, 2, 3, 6):
                mode = 1
            elif raw_mode == 4:
                mode = 4
            elif raw_mode == 5:
                mode = 5
            else:
                continue
            items.append({'time': round(max(0.0, t), 2), 'text': text[:100],
                          'mode': mode, 'color': '#%06x' % (color_int & 0xFFFFFF)})
    except Exception:
        # XML 结构不标准时的正则兜底
        try:
            txt = raw.decode('utf-8', errors='ignore')
        except Exception:
            return items
        import html as _html
        for m in re.finditer(r'<d\s+p="([^"]*)"[^>]*>([^<]*)</d>', txt):
            parts = m.group(1).split(',')
            text = _html.unescape(m.group(2)).strip()
            if len(parts) < 4 or not text:
                continue
            try:
                t = float(parts[0])
                raw_mode = int(parts[1])
                color_int = int(parts[3])
            except ValueError:
                continue
            if raw_mode in (1, 2, 3, 6):
                mode = 1
            elif raw_mode == 4:
                mode = 4
            elif raw_mode == 5:
                mode = 5
            else:
                continue
            items.append({'time': round(max(0.0, t), 2), 'text': text[:100],
                          'mode': mode, 'color': '#%06x' % (color_int & 0xFFFFFF)})
    return items


def _is_under(path, root):
    """判断 path 是否在 root 目录内（防目录穿越）"""
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except (ValueError, OSError):
        return False


def _media_scan_roots(roots, media_type):
    """扫描指定目录列表，返回符合扩展名的文件信息列表。
    roots 条目支持 '路径字符串' 或 {'path': 路径, 'categoryId': 分类ID}（目录绑定分类）"""
    exts = MEDIA_MUSIC_EXTS if media_type == 'music' else MEDIA_VIDEO_EXTS
    results = []
    for root in roots:
        if isinstance(root, dict):
            root_cat = str(root.get('categoryId') or 'default')
            root = root.get('path', '')
        else:
            root_cat = 'default'
        root = os.path.abspath(root)
        if not os.path.isdir(root):
            continue
        # 拒绝扫描盘根和系统目录
        parent = os.path.dirname(root)
        if root == parent or root.lower() in ('c:\\', 'd:\\', 'e:\\', 'f:\\', '/', 'c:'):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                # 跳过隐藏目录
                dirnames[:] = [d for d in dirnames if not d.startswith('.')]
                for fn in filenames:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in exts:
                        continue
                    fp = os.path.join(dirpath, fn)
                    try:
                        st = os.stat(fp)
                    except OSError:
                        continue
                    results.append({
                        'id': _media_gen_id(fp.replace('\\', '/'), st.st_mtime),
                        'stableKey': _media_stable_key(fn, st.st_size),
                        'absPath': fp.replace('\\', '/'),
                        'name': fn,
                        'dir': os.path.dirname(fp).replace('\\', '/'),
                        'ext': ext,
                        'type': media_type,
                        'size': st.st_size,
                        'mtime': int(st.st_mtime),
                        'categoryId': root_cat,
                        'duration': None,
                        'thumbFile': None,
                        'tags': [],
                        'desc': '',
                        'hasLrc': (media_type == 'music' and os.path.isfile(os.path.splitext(fp)[0] + '.lrc')),
                        'addedAt': int(time.time() * 1000),
                    })
        except (OSError, PermissionError):
            continue
    return results


class ProxyHandler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def end_headers(self):
        # 本地开发工具：禁用缓存，保证 HTML/CSS/JS 改动即时生效；
        # 媒体文件响应已显式声明自己的缓存策略（长缓存），不再追加 no-cache（否则 no-cache 优先、缓存失效）
        if not getattr(self, '_own_cache_policy', False):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def _serve_media_file(self, abs_path, content_type):
        """流式播放媒体文件（支持 HTTP Range 请求，用于拖动进度条）"""
        self._own_cache_policy = True  # end_headers 不再追加 no-cache
        try:
            size = os.path.getsize(abs_path)
        except OSError:
            self.send_error(404, 'Not Found')
            return
        range_hdr = self.headers.get('Range')
        start, end = 0, size - 1
        is_range = False
        if range_hdr:
            m = re.match(r'bytes=(\d*)-(\d*)', range_hdr.strip())
            if m:
                start = int(m.group(1)) if m.group(1) else 0
                end = int(m.group(2)) if m.group(2) else size - 1
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header('Content-Range', 'bytes */{}'.format(size))
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                end = min(end, size - 1)
                is_range = True
        length = end - start + 1
        self.send_response(206 if is_range else 200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Access-Control-Allow-Origin', '*')
        # id 含 mtime：文件内容一变 ID/URL 就变，长缓存安全；浏览器媒体缓存命中后同视频再开近乎秒开
        self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
        if is_range:
            self.send_header('Content-Range', 'bytes {}-{}/{}'.format(start, end, size))
        self.end_headers()
        try:
            with open(abs_path, 'rb') as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/proxy':
            self.handle_proxy(parsed, 'GET', None)
        elif parsed.path == '/api/saved-requests':
            self.handle_list_saved(parsed)
        elif parsed.path == '/api/bookmarks':
            self.handle_get_bookmarks()
        elif parsed.path == '/api/whiteboard':
            self.handle_get_whiteboard()
        elif parsed.path == '/api/pomodoro':
            self.handle_get_pomodoro()
        elif parsed.path == '/api/pet-state':
            self.handle_get_pet_state()
        elif parsed.path == '/api/ui-prefs':
            self.handle_get_ui_prefs()
        elif parsed.path == '/api/clipboard':
            self.handle_get_clipboard()
        elif parsed.path.startswith('/clipboard_files/'):
            self.handle_clip_file(parsed)
        elif parsed.path == '/api/chat':
            self.handle_chat_get()
        elif parsed.path.startswith('/chat_files/'):
            self.handle_chat_file(parsed)
        elif parsed.path == '/api/media':
            self.handle_media_get()
        elif parsed.path.startswith('/media_file'):
            self.handle_media_file(parsed)
        elif parsed.path.startswith('/media_thumb'):
            self.handle_media_thumb_file(parsed)
        elif parsed.path.startswith('/media_cover'):
            self.handle_media_cover_file(parsed)
        elif parsed.path == '/api/media/lrc':
            self.handle_media_lrc(parsed)
        elif parsed.path == '/api/danmaku/list':
            self.handle_danmaku_list(parsed)
        elif parsed.path == '/api/sysinfo':
            self.handle_sysinfo()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/proxy':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else None
            self.handle_proxy(parsed, 'POST', body)
        elif parsed.path == '/api/saved-requests':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_save_request(body)
        elif parsed.path == '/api/bookmarks':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_save_bookmarks(body)
        elif parsed.path == '/api/whiteboard':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_save_whiteboard(body)
        elif parsed.path == '/api/pomodoro':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_save_pomodoro(body)
        elif parsed.path == '/api/pet-state':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_save_pet_state(body)
        elif parsed.path == '/api/ui-prefs':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_save_ui_prefs(body)
        elif parsed.path == '/api/clipboard':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_clipboard_action(body)
        elif parsed.path == '/api/chat':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_chat_post(body)
        elif parsed.path == '/api/chat/attach':
            self.handle_chat_attach(parsed)  # 流式上传：body 不预读，直接分块落盘
        elif parsed.path == '/api/media':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_media_save(body)
        elif parsed.path == '/api/media/scan':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_media_scan(body)
        elif parsed.path == '/api/media/file-meta':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_media_meta(body)
        elif parsed.path == '/api/media/thumb':
            self.handle_media_thumb_upload()
        elif parsed.path == '/api/media/cover':
            self.handle_media_cover_upload()
        elif parsed.path == '/api/danmaku/add':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_danmaku_add(body)
        elif parsed.path == '/api/danmaku/delete':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            self.handle_danmaku_delete(body)
        elif parsed.path == '/api/danmaku/import':
            self.handle_danmaku_import()
        else:
            self.send_json(404, {"error": "not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/saved-requests/'):
            parts = parsed.path.split('/')
            if len(parts) >= 5:
                req_type = unquote(parts[3])
                name = unquote(parts[4])
                self.handle_delete_saved(req_type, name)
            else:
                self.send_json(400, {"error": "invalid path"})
        else:
            self.send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Proxy-Method, X-Proxy-Headers')
        self.end_headers()

    def handle_proxy(self, parsed, method, body):
        qs = parse_qs(parsed.query)
        target = qs.get('url', [''])[0]
        target = unquote(target)

        if not target:
            self.send_json(400, {"error": "missing url parameter"})
            return

        if not target.startswith(('http://', 'https://')):
            target = 'http://' + target

        custom_headers_raw = self.headers.get('X-Proxy-Headers', '')
        req_headers = {
            'User-Agent': 'Mozilla/5.0 JSON-Proxy',
        }
        if custom_headers_raw:
            try:
                custom = json.loads(unquote(custom_headers_raw))
                for k, v in custom.items():
                    if k.lower() in ('host', 'content-length', 'connection'):
                        continue
                    req_headers[k] = str(v)
            except Exception:
                pass

        if body and 'Content-Type' not in req_headers:
            req_headers['Content-Type'] = 'application/json'

        try:
            req = urllib.request.Request(target, data=body, headers=req_headers, method=method)
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp_body = resp.read()
                content_type = resp.headers.get('Content-Type', 'application/json')
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            resp_body = e.read()
            self.send_response(e.code)
            self.send_header('Content-Type', e.headers.get('Content-Type', 'application/json'))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
        except Exception as e:
            self.send_json(502, {"error": str(e)})

    def handle_list_saved(self, parsed):
        qs = parse_qs(parsed.query)
        req_type = qs.get('type', [None])[0]
        items = load_saved_requests()
        if req_type:
            items = [it for it in items if it.get('type') == req_type]
        self.send_json(200, {"data": items})

    def handle_save_request(self, body):
        try:
            item = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON body"})
            return

        name = (item.get('name') or '').strip()
        req_type = (item.get('type') or 'apitest').strip()
        if not name:
            self.send_json(400, {"error": "name is required"})
            return
        if req_type not in ('apitest', 'async', 'websocket'):
            self.send_json(400, {"error": "invalid type"})
            return

        category = (item.get('category') or '默认分类').strip()

        items = load_saved_requests()
        record = {
            "name": name,
            "type": req_type,
            "category": category,
            "method": item.get('method', 'GET'),
            "url": item.get('url', ''),
            "headers": item.get('headers', {}),
            "body": item.get('body', ''),
        }
        replaced = False
        for i, existing in enumerate(items):
            if existing.get('name') == name and existing.get('type') == req_type:
                items[i] = record
                replaced = True
                break
        if not replaced:
            items.append(record)
        save_saved_requests(items)
        self.send_json(200, {"success": True, "data": record})

    def handle_delete_saved(self, req_type, name):
        items = load_saved_requests()
        items = [it for it in items if not (it.get('name') == name and it.get('type') == req_type)]
        save_saved_requests(items)
        self.send_json(200, {"success": True})

    def handle_get_bookmarks(self):
        data = load_bookmarks()
        self.send_json(200, {"success": True, "data": data})

    def handle_save_bookmarks(self, body):
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON body"})
            return
        if not isinstance(data, dict):
            self.send_json(400, {"error": "invalid data"})
            return
        categories = data.get('categories')
        bookmarks = data.get('bookmarks')
        if not isinstance(categories, list) or not isinstance(bookmarks, list):
            self.send_json(400, {"error": "categories and bookmarks must be arrays"})
            return
        clean_categories = []
        for c in categories:
            if isinstance(c, dict) and c.get('id') and c.get('name'):
                clean_categories.append({"id": str(c['id']), "name": str(c['name'])})
        if not any(c.get('id') == 'default' for c in clean_categories):
            clean_categories.insert(0, {"id": "default", "name": "未分类"})
        valid_ids = {c['id'] for c in clean_categories}
        clean_bookmarks = []
        for b in bookmarks:
            if not isinstance(b, dict) or not b.get('url'):
                continue
            cat_id = b.get('categoryId') if b.get('categoryId') in valid_ids else 'default'
            clean_bookmarks.append({
                "id": str(b.get('id') or ('bm_' + str(len(clean_bookmarks)))),
                "name": str(b.get('name') or b.get('url')),
                "url": str(b.get('url')),
                "icon": str(b.get('icon') or ''),
                "categoryId": cat_id,
                "createdAt": int(b.get('createdAt') or 0),
            })
        to_save = {"categories": clean_categories, "bookmarks": clean_bookmarks}
        save_bookmarks(to_save)
        self.send_json(200, {"success": True, "data": to_save})

    def handle_get_whiteboard(self):
        data = load_whiteboard()
        self.send_json(200, {"success": True, "data": data})

    def handle_save_whiteboard(self, body):
        """页级保存协议（矢量）：
        - {"page": {"id","strokes":[...],"updatedAt"}} 按 id 替换或追加单页
        - {"deletePageId": "xxx"} 删除指定页
        """
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON body"})
            return
        if not isinstance(data, dict):
            self.send_json(400, {"error": "invalid data"})
            return
        doc = load_whiteboard()
        pages = doc['pages']
        if data.get('deletePageId'):
            pid = str(data['deletePageId'])
            pages = [p for p in pages if p['id'] != pid]
            to_save = {"pages": pages, "updatedAt": int(time.time() * 1000)}
            save_whiteboard(to_save)
            self.send_json(200, {"success": True, "data": to_save})
            return
        page = _clean_whiteboard_page(data.get('page'))
        if page is None:
            self.send_json(400, {"error": "page must be {id, strokes(array of vector ops), updatedAt}"})
            return
        for i, p in enumerate(pages):
            if p['id'] == page['id']:
                pages[i] = page
                break
        else:
            pages.append(page)
        to_save = {"pages": pages, "updatedAt": int(time.time() * 1000)}
        save_whiteboard(to_save)
        self.send_json(200, {"success": True, "data": to_save})

    def handle_get_pomodoro(self):
        self.send_json(200, {"success": True, "data": load_pomodoro()})

    def handle_save_pomodoro(self, body):
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON body"})
            return
        clean = _clean_pomodoro(data)
        save_pomodoro(clean)
        self.send_json(200, {"success": True, "data": clean})

    def handle_get_pet_state(self):
        """GET /api/pet-state — 桌面宠物轮询番茄钟运行态"""
        self.send_json(200, {"success": True, "data": load_pet_state()})

    def handle_get_ui_prefs(self):
        """GET /api/ui-prefs — 通用 UI 偏好（tab 顺序等）"""
        self.send_json(200, {"success": True, "data": load_ui_prefs()})

    def handle_save_ui_prefs(self, body):
        """POST /api/ui-prefs — 合并保存（只覆盖传入的键），上限 64KB 防滥用"""
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON body"})
            return
        if not isinstance(data, dict) or len(body) > 64 * 1024:
            self.send_json(400, {"error": "invalid data"})
            return
        merged = load_ui_prefs()
        merged.update(data)
        save_ui_prefs(merged)
        self.send_json(200, {"success": True, "data": merged})

    def handle_save_pet_state(self, body):
        """POST /api/pet-state — 前端番茄钟开始/暂停/停止/完成时上报运行态"""
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON body"})
            return
        clean = _clean_pet_state(data if isinstance(data, dict) else {})
        save_pet_state(clean)
        self.send_json(200, {"success": True, "data": clean})

    def handle_get_clipboard(self):
        with _clip_lock:
            items = _clip_load()
        self.send_json(200, {"success": True, "data": items})

    def handle_sysinfo(self):
        """GET /api/sysinfo — 服务器电脑的 CPU/内存/磁盘/网络实时状态"""
        self.send_json(200, {"success": True, "data": collect_sysinfo()})

    def handle_clipboard_action(self, body):
        """剪贴板操作：
        - {"action":"add","text":"..."} 添加记录（前端页面内复制上报）
        - {"action":"delete","id":"..."} 删除单条
        - {"action":"clear"} 清空全部
        """
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON body"})
            return
        if not isinstance(data, dict):
            self.send_json(400, {"error": "invalid data"})
            return
        action = data.get('action')
        if action == 'add':
            text = data.get('text')
            if not isinstance(text, str):
                self.send_json(400, {"error": "text must be string"})
                return
            _clip_add(text)  # 内部自带锁，勿在外层再加（Lock 不可重入）
            with _clip_lock:
                items = _clip_load()
            self.send_json(200, {"success": True, "data": items})
            return
        with _clip_lock:
            if action == 'clear':
                old = _clip_load()
                _clip_save([])
                _clip_remove_files(old)
                self.send_json(200, {"success": True, "data": []})
                return
            if action == 'delete':
                pid = str(data.get('id') or '')
                items = _clip_load()
                removed = [i for i in items if i['id'] == pid]
                items = [i for i in items if i['id'] != pid]
                _clip_save(items)
                _clip_remove_files(removed)
                self.send_json(200, {"success": True, "data": items})
                return
        self.send_json(400, {"error": "unknown action"})

    def handle_clip_file(self, parsed):
        """提供剪贴板图片文件（basename 防目录穿越 + 仅允许 .png）"""
        name = os.path.basename(unquote(parsed.path[len('/clipboard_files/'):]))
        path = os.path.join(CLIP_IMG_DIR, name)
        if not name.lower().endswith('.png') or not os.path.isfile(path):
            self.send_error(404, 'Not Found')
            return
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError:
            self.send_error(404, 'Not Found')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    # ---------------- 公共聊天频道 ----------------
    def handle_chat_get(self):
        with _chat_lock:
            items = _chat_load()
        self.send_json(200, {"success": True, "data": items})

    def handle_chat_post(self, body):
        """文本消息 / 删除：
        - 发送文本：{"clientId","name","color","text"}
        - 删除本人消息：{"action":"delete","id","clientId"}
        """
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON body"})
            return
        if not isinstance(data, dict):
            self.send_json(400, {"error": "invalid data"})
            return
        if data.get('action') == 'delete':
            ok = _chat_delete(str(data.get('id') or ''), str(data.get('clientId') or ''))
            with _chat_lock:
                items = _chat_load()
            self.send_json(200 if ok else 403, {"success": ok, "data": items})
            return
        item = _chat_add_text(
            data.get('clientId'), data.get('name'), data.get('color'), data.get('text'))
        if item is None:
            self.send_json(400, {"error": "text is empty"})
            return
        with _chat_lock:
            items = _chat_load()
        self.send_json(200, {"success": True, "data": items})

    def handle_chat_attach(self, parsed):
        """附件上传（流式，不设大小限制）：元数据走 query string，原始二进制 body 1MB 分块写盘"""
        qs = parse_qs(parsed.query)
        q = lambda k: qs.get(k, [''])[0]
        fname = unquote(q('fname'))
        is_image = q('isImage') in ('1', 'true', 'yes')
        length = int(self.headers.get('Content-Length', 0) or 0)
        item, err = _chat_add_attachment(
            unquote(q('clientId')), unquote(q('name')), unquote(q('color')),
            fname, is_image, self.rfile, length)
        if err:
            self.send_json(400, {"error": err})
            return
        with _chat_lock:
            items = _chat_load()
        self.send_json(200, {"success": True, "data": items})

    def handle_chat_file(self, parsed):
        """提供聊天附件（basename 防目录穿越，按扩展名给 Content-Type）；流式分块回写，内存占用与文件大小无关"""
        name = os.path.basename(unquote(parsed.path[len('/chat_files/'):]))
        path = os.path.join(CHAT_FILES_DIR, name)
        if not name or not os.path.isfile(path):
            self.send_error(404, 'Not Found')
            return
        try:
            f = open(path, 'rb')
        except OSError:
            self.send_error(404, 'Not Found')
            return
        with f:
            try:
                size = os.fstat(f.fileno()).st_size
            except OSError:
                self.send_error(404, 'Not Found')
                return
            ext = os.path.splitext(name)[1].lower()
            ctype = _CHAT_CT.get(ext, 'application/octet-stream')
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(size))
            self.send_header('Access-Control-Allow-Origin', '*')
            if ctype == 'application/octet-stream':
                self.send_header('Content-Disposition', 'attachment')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                shutil.copyfileobj(f, self.wfile, 1024 * 1024)
            except (BrokenPipeError, ConnectionResetError):
                pass  # 对端中途取消下载

    # ==================== 本地媒体库 Handler ====================

    def handle_media_get(self):
        with _media_lock:
            lib = _media_load()
        self.send_json(200, {"success": True, "data": lib})

    def handle_media_save(self, body):
        """保存分类和文件分配（客户端只发 categories + files 中的 categoryId/customName）"""
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON"})
            return
        with _media_lock:
            lib = _media_load()
            # 更新分类
            if 'categories' in data:
                for mtype in ('music', 'video'):
                    cats = data['categories'].get(mtype)
                    if isinstance(cats, list) and cats:
                        # 保留 default
                        has_default = any(c.get('id') == 'default' for c in cats)
                        if not has_default:
                            cats.insert(0, {'id': 'default', 'name': '未分类'})
                        lib['categories'][mtype] = cats
            # 更新文件分类分配
            if 'files' in data:
                id_map = {f['id']: f for f in data['files'] if isinstance(f, dict) and 'id' in f}
                for f in lib['files']:
                    upd = id_map.get(f['id'])
                    if upd:
                        if 'categoryId' in upd:
                            f['categoryId'] = upd['categoryId']
                        if 'customName' in upd:
                            f['customName'] = upd['customName']
                        if 'duration' in upd and upd['duration'] is not None:
                            f['duration'] = upd['duration']
                        if 'thumbFile' in upd and upd['thumbFile'] is not None:
                            f['thumbFile'] = upd['thumbFile']
                        if 'desc' in upd and upd['desc'] is not None:
                            f['desc'] = str(upd['desc'])[:5000]
                        if 'tags' in upd and isinstance(upd['tags'], list):
                            f['tags'] = [str(t).strip()[:20] for t in upd['tags'] if str(t).strip()][:20]
            lib['updatedAt'] = int(time.time() * 1000)
            _media_save(lib)
        self.send_json(200, {"success": True, "data": lib})

    def handle_media_scan(self, body):
        """扫描指定目录列表，合并入库"""
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON"})
            return
        roots = data.get('roots', [])
        mtype = data.get('type', 'music')
        remove_roots = data.get('removeRoots', [])
        if not isinstance(remove_roots, list):
            remove_roots = []
        if mtype not in ('music', 'video'):
            self.send_json(400, {"error": "invalid type"})
            return
        if not isinstance(roots, list) or (not roots and not remove_roots):
            self.send_json(400, {"error": "roots must be a non-empty list"})
            return
        # 归一化 roots 条目：支持 '路径' 或 {'path', 'categoryId'}（目录绑定分类）
        def _binding(item):
            if isinstance(item, dict):
                return str(item.get('path') or ''), str(item.get('categoryId') or 'default')
            return str(item), 'default'
        bindings = [_binding(r) for r in roots]
        remove_paths = [_binding(r)[0] for r in remove_roots]
        # 扫描文件（新文件自动归入目录绑定的分类）
        scanned = _media_scan_roots([{'path': p, 'categoryId': c} for p, c in bindings], mtype) if bindings else []
        scanned_ids = {f['id'] for f in scanned}
        with _media_lock:
            lib = _media_load()
            # 更新扫描路径：规范化（normpath + 统一斜杠）后去重合并，再剔除移除项
            def _root_key(p):
                try:
                    return os.path.normpath(str(p)).replace('\\', '/').rstrip('/').lower()
                except Exception:
                    return str(p).replace('\\', '/').rstrip('/').lower()
            # 旧绑定 {normKey: (normPath, categoryId)}；旧字符串条目视为未分类
            old_bindings = {}
            for r in lib['scanRoots'].get(mtype, []):
                if isinstance(r, dict):
                    rp, rc = r.get('path', ''), str(r.get('categoryId') or 'default')
                else:
                    rp, rc = r, 'default'
                old_bindings[_root_key(rp)] = (os.path.normpath(str(rp)), rc)
            roots_map = dict(old_bindings)
            for p, c in bindings:
                roots_map[_root_key(p)] = (os.path.normpath(p), c)
            for rp in remove_paths:
                roots_map.pop(_root_key(rp), None)
            lib['scanRoots'][mtype] = [{'path': p, 'categoryId': c} for p, c in roots_map.values()]
            # 移除目录时，同步删掉其下所有文件记录
            if remove_paths:
                def _norm(p):
                    return str(p).replace('\\', '/').rstrip('/').lower()
                removed_norms = [_norm(rp) for rp in remove_paths]
                keep = [f for f in lib['files'] if f.get('type') != mtype or
                        not any(_norm(f.get('absPath', '')).startswith(rn + '/') or
                                _norm(f.get('absPath', '')) == rn for rn in removed_norms)]
                lib['files'] = keep
            # 绑定分类变化 → 同步归类该目录下的文件：
            # 仅移动「旧绑定分类」或「未分类」的文件，用户手动设置的其它分类不受影响
            recategorized = 0
            for p, c in bindings:
                old_cat = old_bindings.get(_root_key(p), (None, None))[1]
                if old_cat == c:
                    continue
                pn = str(os.path.normpath(p)).replace('\\', '/').rstrip('/').lower()
                for f in lib['files']:
                    if f.get('type') != mtype:
                        continue
                    fn = str(f.get('absPath', '')).replace('\\', '/').rstrip('/').lower()
                    if (fn.startswith(pn + '/') or fn == pn) and f.get('categoryId', 'default') in (old_cat, 'default'):
                        f['categoryId'] = c
                        recategorized += 1
            # 合并文件：保留旧分类分配，加入新文件，移除已不存在的
            old_by_id = {f['id']: f for f in lib['files'] if f.get('type') == mtype}
            # 稳定键索引：文件被移动/复制导致 ID 变化时，凭 文件名+大小 找回用户数据
            old_by_key = {}
            for of in lib['files']:
                if of.get('type') == mtype:
                    sk = of.get('stableKey') or _media_stable_key(of.get('name', ''), of.get('size', 0))
                    old_by_key.setdefault(sk, of)
            other_files = [f for f in lib['files'] if f.get('type') != mtype]
            migrated = 0
            merged = []
            for sf in scanned:
                of = old_by_id.get(sf['id'])
                if not of:
                    # ID 对不上（路径/mtime 变化）→ 按稳定键找
                    cand = old_by_key.get(sf.get('stableKey'))
                    if cand and cand['id'] not in scanned_ids:
                        of = cand
                if of:
                    # 保留用户设置的分类、名称、时长、封面、标签、简介
                    sf['categoryId'] = of.get('categoryId', 'default')
                    sf['customName'] = of.get('customName', '')
                    sf['duration'] = of.get('duration')
                    sf['tags'] = of.get('tags') or []
                    sf['desc'] = of.get('desc', '')
                    sf['addedAt'] = of.get('addedAt', sf['addedAt'])
                    if of.get('thumbFile'):
                        sf['thumbFile'] = of['thumbFile'] if of['id'] == sf['id'] else (sf['id'] + '.jpg')
                    if of.get('coverFile'):
                        sf['coverFile'] = of['coverFile'] if of['id'] == sf['id'] else (sf['id'] + '.jpg')
                    if of['id'] != sf['id']:
                        # ID 变了：迁移封面文件与弹幕记录到新 ID
                        _media_migrate_assets(of['id'], sf['id'])
                        migrated += 1
                # 兜底：磁盘上已有封面文件但记录字段缺失（库重建/记录丢失）时自动重连
                if not sf.get('thumbFile') and os.path.isfile(os.path.join(MEDIA_THUMBS_DIR, sf['id'] + '.jpg')):
                    sf['thumbFile'] = sf['id'] + '.jpg'
                if not sf.get('coverFile') and os.path.isfile(os.path.join(MEDIA_COVERS_DIR, sf['id'] + '.jpg')):
                    sf['coverFile'] = sf['id'] + '.jpg'
                merged.append(sf)
            lib['files'] = other_files + merged
            lib['updatedAt'] = int(time.time() * 1000)
            _media_save(lib)
        added = len(scanned)
        self.send_json(200, {"success": True, "data": lib, "scanned": added, "migrated": migrated, "recategorized": recategorized})

    def handle_media_meta(self, body):
        """更新单文件时长/缩略图"""
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON"})
            return
        file_id = str(data.get('id', ''))
        if not re.fullmatch(r'm_\d+_[0-9a-f]+', file_id):
            self.send_json(400, {"error": "bad id"})
            return
        with _media_lock:
            lib = _media_load()
            for f in lib['files']:
                if f['id'] == file_id:
                    if 'duration' in data and data['duration'] is not None:
                        f['duration'] = data['duration']
                    if 'thumbFile' in data and data['thumbFile'] is not None:
                        f['thumbFile'] = data['thumbFile']
                    if 'desc' in data and data['desc'] is not None:
                        f['desc'] = str(data['desc'])[:5000]
                    if 'tags' in data and isinstance(data['tags'], list):
                        f['tags'] = [str(t).strip()[:20] for t in data['tags'] if str(t).strip()][:20]
                    break
            lib['updatedAt'] = int(time.time() * 1000)
            _media_save(lib)
        self.send_json(200, {"success": True})

    # ---------------- 视频弹幕（本地存储 + B站 XML 导入） ----------------
    # danmaku.json 结构：{ "<file_id>": [ {id, time, text, mode, color, createdAt}, ... ] }
    # mode：1=滚动 4=底部 5=顶部（对齐 B站规范，导入时归一）

    def handle_danmaku_list(self, parsed):
        qs = parse_qs(parsed.query)
        file_id = qs.get('id', [''])[0]
        if not re.fullmatch(r'm_\d+_[0-9a-f]+', file_id):
            self.send_json(400, {"error": "bad id"})
            return
        with _media_lock:
            data = _danmaku_load()
            items = sorted(data.get(file_id, []), key=lambda x: x.get('time', 0))
        self.send_json(200, {"success": True, "data": items})

    def handle_danmaku_add(self, body):
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON"})
            return
        file_id = str(data.get('id', ''))
        text = str(data.get('text', '')).strip()
        if not re.fullmatch(r'm_\d+_[0-9a-f]+', file_id) or not text:
            self.send_json(400, {"error": "bad params"})
            return
        try:
            t = float(data.get('time', 0))
            mode = int(data.get('mode', 1))
        except (TypeError, ValueError):
            self.send_json(400, {"error": "bad params"})
            return
        color = str(data.get('color', '#ffffff'))
        if mode not in (1, 4, 5):
            mode = 1
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            color = '#ffffff'
        item = {'id': 'd_{}_{}'.format(int(time.time() * 1000), os.urandom(4).hex()),
                'time': round(max(0.0, t), 2), 'text': text[:100], 'mode': mode, 'color': color,
                'createdAt': int(time.time() * 1000)}
        with _media_lock:
            lib = _danmaku_load()
            items = lib.setdefault(file_id, [])
            if len(items) >= DANMAKU_MAX_PER_VIDEO:
                self.send_json(400, {"error": "该视频弹幕已达上限"})
                return
            items.append(item)
            lib['updatedAt'] = int(time.time() * 1000)
            _danmaku_save(lib)
        self.send_json(200, {"success": True, "data": item})

    def handle_danmaku_delete(self, body):
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            self.send_json(400, {"error": "invalid JSON"})
            return
        file_id = str(data.get('id', ''))
        dm_id = str(data.get('dmId', ''))
        if not re.fullmatch(r'm_\d+_[0-9a-f]+', file_id) or not dm_id:
            self.send_json(400, {"error": "bad params"})
            return
        with _media_lock:
            lib = _danmaku_load()
            items = lib.get(file_id, [])
            lib[file_id] = [d for d in items if d.get('id') != dm_id]
            lib['updatedAt'] = int(time.time() * 1000)
            _danmaku_save(lib)
        self.send_json(200, {"success": True})

    def handle_danmaku_import(self):
        """接收 multipart/form-data（id + file），解析 B站弹幕 XML 导入（按 时间+内容 去重）"""
        ctype = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in ctype:
            self.send_json(400, {"error": "expect multipart/form-data"})
            return
        boundary = ctype.split('boundary=')[1].strip() if 'boundary=' in ctype else ''
        if not boundary:
            self.send_json(400, {"error": "no boundary"})
            return
        length = int(self.headers.get('Content-Length', 0))
        if not length or length > 20 * 1024 * 1024:
            self.send_json(400, {"error": "invalid content length"})
            return
        body = self.rfile.read(length)
        delim = b'--' + boundary.encode()
        file_id = None
        file_data = None
        for part in body.split(delim):
            if b'name="id"' in part:
                m = re.search(rb'\r\n\r\n(.+?)\r\n', part, re.DOTALL)
                if m:
                    file_id = m.group(1).decode('utf-8').strip()
            elif b'name="file"' in part:
                idx = part.find(b'\r\n\r\n')
                if idx >= 0:
                    file_data = part[idx + 4:]
                    if file_data.endswith(b'\r\n'):
                        file_data = file_data[:-2]
        if not file_id or not re.fullmatch(r'm_\d+_[0-9a-f]+', file_id):
            self.send_json(400, {"error": "bad id"})
            return
        if not file_data:
            self.send_json(400, {"error": "no file data"})
            return
        parsed_items = _danmaku_parse_bili_xml(file_data)
        if not parsed_items:
            self.send_json(400, {"error": "未解析到有效弹幕，请确认是 B站弹幕 XML 文件"})
            return
        with _media_lock:
            lib = _danmaku_load()
            existing = lib.setdefault(file_id, [])
            seen = {(round(float(d.get('time', 0)), 2), d.get('text', '')) for d in existing}
            added = 0
            skipped = 0
            for it in parsed_items:
                key = (it['time'], it['text'])
                if key in seen or len(existing) >= DANMAKU_MAX_PER_VIDEO:
                    skipped += 1
                    continue
                seen.add(key)
                existing.append({'id': 'd_{}_{}'.format(int(time.time() * 1000), os.urandom(4).hex()),
                                 'time': it['time'], 'text': it['text'], 'mode': it['mode'],
                                 'color': it['color'], 'createdAt': int(time.time() * 1000)})
                added += 1
            lib['updatedAt'] = int(time.time() * 1000)
            _danmaku_save(lib)
        self.send_json(200, {"success": True, "imported": added, "skipped": skipped})

    def handle_media_thumb_upload(self):
        """接收缩略图上传（multipart/form-data），保存为 media_thumbs/<id>.jpg"""
        ctype = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in ctype:
            self.send_json(400, {"error": "expect multipart/form-data"})
            return
        boundary = ctype.split('boundary=')[1].strip() if 'boundary=' in ctype else ''
        if not boundary:
            self.send_json(400, {"error": "no boundary"})
            return
        length = int(self.headers.get('Content-Length', 0))
        if not length or length > 2 * 1024 * 1024:
            self.send_json(400, {"error": "invalid content length"})
            return
        body = self.rfile.read(length)
        # 简易 multipart 解析：提取 id 和 file
        delim = b'--' + boundary.encode()
        parts = body.split(delim)
        file_id = None
        file_data = None
        for part in parts:
            if b'name="id"' in part:
                m = re.search(rb'\r\n\r\n(.+?)\r\n', part, re.DOTALL)
                if m:
                    file_id = m.group(1).decode('utf-8').strip()
            elif b'name="file"' in part:
                idx = part.find(b'\r\n\r\n')
                if idx >= 0:
                    file_data = part[idx + 4:]
                    # 去掉结尾的 \r\n
                    if file_data.endswith(b'\r\n'):
                        file_data = file_data[:-2]
        if not file_id or not re.fullmatch(r'm_\d+_[0-9a-f]+', file_id):
            self.send_json(400, {"error": "bad id"})
            return
        if not file_data:
            self.send_json(400, {"error": "no file data"})
            return
        os.makedirs(MEDIA_THUMBS_DIR, exist_ok=True)
        thumb_name = file_id + '.jpg'
        thumb_path = os.path.join(MEDIA_THUMBS_DIR, thumb_name)
        with open(thumb_path, 'wb') as f:
            f.write(file_data)
        with _media_lock:
            lib = _media_load()
            for f in lib['files']:
                if f['id'] == file_id:
                    f['thumbFile'] = thumb_name
                    break
            lib['updatedAt'] = int(time.time() * 1000)
            _media_save(lib)
        self.send_json(200, {"success": True, "thumbFile": thumb_name})

    def handle_media_file(self, parsed):
        """流式播放媒体文件（id → 路径 → Range 206）"""
        qs = parse_qs(parsed.query)
        file_id = qs.get('id', [''])[0]
        if not file_id or not re.fullmatch(r'm_\d+_[0-9a-f]+', file_id):
            self.send_error(400, 'Bad id')
            return
        with _media_lock:
            lib = _media_load()
        f = next((x for x in lib['files'] if x['id'] == file_id), None)
        if not f:
            self.send_error(404, 'Not Found')
            return
        abs_path = f['absPath']
        # 安全校验：路径必须在 scanRoots 内（条目兼容字符串与 {path, categoryId} 对象）
        roots = lib['scanRoots'].get(f.get('type', ''), [])
        real = os.path.realpath(abs_path)
        root_paths = [(r.get('path', '') if isinstance(r, dict) else r) for r in roots]
        if root_paths and not any(_is_under(real, os.path.realpath(r)) for r in root_paths):
            self.send_error(403, 'Forbidden')
            return
        if not os.path.isfile(real):
            self.send_error(404, 'Not Found')
            return
        ctype = _MEDIA_CT.get(f.get('ext', ''), 'application/octet-stream')
        self._serve_media_file(real, ctype)

    def handle_media_thumb_file(self, parsed):
        """提供缩略图文件"""
        qs = parse_qs(parsed.query)
        file_id = qs.get('id', [''])[0]
        if not file_id or not re.fullmatch(r'm_\d+_[0-9a-f]+', file_id):
            self.send_error(400, 'Bad id')
            return
        thumb_path = os.path.join(MEDIA_THUMBS_DIR, file_id + '.jpg')
        if not os.path.isfile(thumb_path):
            self.send_error(404, 'Not Found')
            return
        try:
            with open(thumb_path, 'rb') as f:
                data = f.read()
        except OSError:
            self.send_error(404, 'Not Found')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def handle_media_cover_upload(self):
        """接收封面+标签上传（multipart/form-data），保存为 media_covers/<id>.jpg"""
        ctype = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in ctype:
            self.send_json(400, {"error": "expect multipart/form-data"})
            return
        boundary = ctype.split('boundary=')[1].strip() if 'boundary=' in ctype else ''
        if not boundary:
            self.send_json(400, {"error": "no boundary"})
            return
        length = int(self.headers.get('Content-Length', 0))
        if not length or length > 2 * 1024 * 1024:
            self.send_json(400, {"error": "invalid content length"})
            return
        body = self.rfile.read(length)
        delim = b'--' + boundary.encode()
        parts = body.split(delim)
        file_id = None
        file_data = None
        tags = {}
        for part in parts:
            if b'name="id"' in part:
                m = re.search(rb'\r\n\r\n(.+?)\r\n', part, re.DOTALL)
                if m:
                    file_id = m.group(1).decode('utf-8').strip()
            elif b'name="tags"' in part:
                m = re.search(rb'\r\n\r\n(.+?)\r\n', part, re.DOTALL)
                if m:
                    try:
                        raw = json.loads(m.group(1).decode('utf-8'))
                        tags = {k: str(raw.get(k, ''))[:200] for k in ('title', 'artist', 'album')}
                    except Exception:
                        tags = {}
            elif b'name="file"' in part:
                idx = part.find(b'\r\n\r\n')
                if idx >= 0:
                    file_data = part[idx + 4:]
                    if file_data.endswith(b'\r\n'):
                        file_data = file_data[:-2]
        if not file_id or not re.fullmatch(r'm_\d+_[0-9a-f]+', file_id):
            self.send_json(400, {"error": "bad id"})
            return
        if not file_data:
            self.send_json(400, {"error": "no file data"})
            return
        os.makedirs(MEDIA_COVERS_DIR, exist_ok=True)
        cover_name = file_id + '.jpg'
        cover_path = os.path.join(MEDIA_COVERS_DIR, cover_name)
        with open(cover_path, 'wb') as f:
            f.write(file_data)
        with _media_lock:
            lib = _media_load()
            for f in lib['files']:
                if f['id'] == file_id:
                    f['coverFile'] = cover_name
                    f['tags'] = tags
                    break
            lib['updatedAt'] = int(time.time() * 1000)
            _media_save(lib)
        self.send_json(200, {"success": True, "coverFile": cover_name, "tags": tags})

    def handle_media_cover_file(self, parsed):
        """提供封面图文件"""
        qs = parse_qs(parsed.query)
        file_id = qs.get('id', [''])[0]
        if not file_id or not re.fullmatch(r'm_\d+_[0-9a-f]+', file_id):
            self.send_error(400, 'Bad id')
            return
        cover_path = os.path.join(MEDIA_COVERS_DIR, file_id + '.jpg')
        if not os.path.isfile(cover_path):
            self.send_error(404, 'Not Found')
            return
        try:
            with open(cover_path, 'rb') as f:
                data = f.read()
        except OSError:
            self.send_error(404, 'Not Found')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def handle_media_lrc(self, parsed):
        """读取歌曲同目录同名 .lrc 歌词文本"""
        qs = parse_qs(parsed.query)
        file_id = qs.get('id', [''])[0]
        if not file_id or not re.fullmatch(r'm_\d+_[0-9a-f]+', file_id):
            self.send_json(400, {"error": "bad id"})
            return
        with _media_lock:
            lib = _media_load()
        f = next((x for x in lib['files'] if x['id'] == file_id), None)
        if not f or f.get('type') != 'music':
            self.send_json(404, {"error": "not found"})
            return
        lrc_path = os.path.splitext(f['absPath'])[0] + '.lrc'
        real = os.path.realpath(lrc_path)
        # 安全：歌词文件必须在歌曲所在目录内
        if not _is_under(real, os.path.realpath(f.get('dir', f['absPath']))):
            self.send_json(403, {"error": "forbidden"})
            return
        if not os.path.isfile(real) or os.path.getsize(real) > 512 * 1024:
            self.send_json(404, {"error": "lrc not found"})
            return
        try:
            with open(real, 'rb') as lf:
                raw = lf.read()
        except OSError:
            self.send_json(404, {"error": "lrc not found"})
            return
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('gbk', errors='replace')
        self.send_json(200, {"success": True, "lrc": text})

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ToolboxHTTPServer(ThreadingHTTPServer):
    # Windows 下 HTTPServer 默认 allow_reuse_address=1（SO_REUSEADDR）会放行多个进程
    # 同时绑定 6868，导致每个实例都跑一份剪贴板监听线程，一次截图被记成多条。
    # 关闭后第二个实例绑定即失败退出，保证全机只有一个监听者。
    allow_reuse_address = 0
    daemon_threads = True


if __name__ == '__main__':
    import socket
    port = 6868
    server = ToolboxHTTPServer(('0.0.0.0', port), ProxyHandler)
    # 绑定成功后才启动剪贴板监听线程（绑定失败的实例直接退出，不会残留）
    threading.Thread(target=clipboard_watcher, daemon=True).start()
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = 'localhost'
    print('=' * 50)
    print('  接口调试工具箱 (DevToolbox) 已启动')
    print('  本机访问:   http://localhost:%d/' % port)
    print('  局域网访问: http://%s:%d/' % (local_ip, port))
    print('=' * 50)
    print('  功能: JSON解析 | 异步任务查询 | 接口测试 | WebSocket | 开发者工具 | 书签管理 | 在线白板 | 番茄钟 | 剪贴板历史')
    print('  API 代理已启用，支持 GET/POST/DELETE 和自定义请求头')
    if sys.platform == 'win32':
        print('  剪贴板监听已启动（Windows 系统级，记录文本复制历史）')
    print('=' * 50)
    server.serve_forever()
