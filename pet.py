#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面宠物 —— Windows 透明置顶窗口里的矢量小老鼠（杰瑞鼠风格原创棕色形象）。

纯标准库实现（tkinter + ctypes），零第三方依赖。

功能：
- 常驻桌面：无边框、不进任务栏、始终置顶、背景透明、点击不抢焦点
- 待机：呼吸起伏、随机眨眼、偶尔溜达、偶尔冒话泡
- 睡觉：长时间（150s）无互动自动入睡（闭眼 + Zzz），任何交互唤醒
- 交互：单击冒话泡（专注中显示倒计时）；双击弹出工具箱快捷菜单（直达各 Tab）；
  按住拖拽，轻放原地停留（可放屏幕任意位置），快速甩出则重力下落 + 落地弹跳（挤压变形）
- 联动（轮询 server.py，服务器关了就安静待着）：
  · 剪贴板有新内容 → 蹦一下 + 气泡预览内容
  · 番茄钟开始/暂停/停止/完成 → 气泡播报；专注中点击可看剩余时间
- 右键菜单：9 个工具箱 Tab 直达项平铺（浏览器打开 #tab-xxx hash）/ 重置位置 / 开机自启（注册表 HKCU Run 键开关，当前状态打勾显示）/ 退出
  - 服务器未启动时点菜单项：自动用 pythonw 拉起 server.py，就绪后开浏览器（最多等 10 秒）
- 中键（滚轮按下）：QQ 截图式区域框选——任意位置按下滚轮中键即触发（全局低级鼠标钩子 WH_MOUSE_LL，
  无需先点宠物）；宠物先溜出屏幕，全屏冻结后框选区域：
  · 主交互：按住左键拖到目标位置，松开即确认选区进入编辑模式
  · 备用交互：按下后几乎没拖就松开 → 移动鼠标（不按住）预览选区 → 再按一下定终点
  · 选区下方工具条可画矩形/椭圆/箭头/画笔/文字、调色、撤销，并支持 📌 钉到屏幕 / ✓ 复制到剪贴板
  · 钉到屏幕：置顶透明贴图窗口（Snipaste 风格），可拖拽移动；右键菜单支持：
    复制整图 / 框选复制局部 / 另存为 BMP / 回到原位 / 关闭；双击或 Esc 关闭
    （snip 模式下 Esc 仅退出 snip 不关窗）
  · Esc / 右键取消；截图会被服务器剪贴板历史自动收录

启动：双击「启动宠物.bat」或运行 `pythonw pet.py`。
"""
import ctypes
import json
import math
import os
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import urllib.request
import webbrowser
import winreg

# ---------------- 常量 ----------------
PET_W, PET_H = 170, 180        # 窗口尺寸（加宽让常用气泡单行；加高给顶部气泡留白）
BODY_OFF = PET_H - 140         # 角色绘制下移量：脚底始终贴窗口底（屏幕站位不随气泡变化）
FLOOR_MARGIN = 50              # 屏幕底部预留高度（避开任务栏）
GRAVITY = 2400.0               # 重力加速度 px/s²
WALK_SPEED = 42.0              # 溜达速度 px/s
MAX_THROW = 1800.0             # 甩出初速度上限 px/s
TRANSPARENT = '#ff00ff'        # 透明色（画布背景，绘制时避开该色）
VK_LBUTTON = 0x01

SERVER = 'http://localhost:6868'   # 工具箱服务器（宠物与服务器同机，本机地址不随网络变化）
POLL_INTERVAL = 3.0                # 轮询周期（秒）
STALE_MS = 120 * 1000              # 番茄钟状态过期阈值：endsAt 超过 2 分钟视为陈旧
SLEEP_AFTER = 150.0                # 无互动多久后入睡（秒）

# 工具箱 Tab 直达表：Tab 标签 → tab id（对应前端 switchTab），右键/左键菜单共用
TOOL_TABS = [
    ('🧩 JSON 解析', 'parser'),
    ('⏳ 异步任务查询', 'task'),
    ('🔌 接口测试', 'apitest'),
    ('🔗 WebSocket', 'websocket'),
    ('🛠 开发者工具', 'devtools'),
    ('⭐ 书签管理', 'bookmarks'),
    ('⏱ 番茄钟', 'pomodoro'),
    ('📋 剪贴板', 'clipboard'),
    ('📱 滚动提醒', 'danmaku'),
]

PHRASES = ['吱~', '吱吱~', '奶酪呢？', '找奶酪中…', '嘿嘿~', '猫来啦？溜！',
           '奶酪万岁！', '小口吃奶酪', '今天也很机灵', '午睡时间~', '悄悄地…',
           '肚子饿扁了', '打个哈欠…', '机智如我', '别找我麻烦', '溜了溜了~']
SLEEP_PHRASES = ['Zzz…', '呼…Zzz', '做梦都在吃奶酪']

# 配色（杰瑞鼠风格：棕色小老鼠 + 奶白口鼻肚皮 + 大圆耳 + 卷尾）
C_BODY = '#b5824f'    # 棕色皮毛
C_LINE = '#8a5d35'    # 深棕描边
C_EAR_IN = '#e9b98e'  # 内耳浅棕
C_EYE = '#2b2320'     # 黑瞳
C_BLUSH = '#eda98d'   # 粉腮红
C_BELLY = '#f0d9ae'   # 口鼻/肚皮奶黄
C_NOSE = '#5b4030'    # 深棕小鼻

# ---------------- 开机自启（注册表 HKCU Run 键） ----------------
AUTOSTART_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
AUTOSTART_NAME = 'DevToolboxPet'


def autostart_cmd():
    """自启命令行：pythonw 绝对路径 + 脚本绝对路径（工作目录无关）"""
    exe = sys.executable if sys.executable.lower().endswith('pythonw.exe') else \
        os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    if not os.path.exists(exe):
        exe = sys.executable
    return f'"{exe}" "{os.path.abspath(__file__)}"'


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as k:
            return winreg.QueryValueEx(k, AUTOSTART_NAME)[0] == autostart_cmd()
    except OSError:
        return False


def autostart_set(on):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, AUTOSTART_NAME, 0, winreg.REG_SZ, autostart_cmd())
            else:
                try:
                    winreg.DeleteValue(k, AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False

user32 = ctypes.windll.user32

# ---------------- 截图（GDI，纯 ctypes 零依赖；64 位下显式声明句柄原型） ----------------
from ctypes import wintypes as _wt
_gdi32 = ctypes.windll.gdi32
_kernel32 = ctypes.windll.kernel32
_H = _wt.HANDLE
user32.GetDC.restype = _H;            user32.GetDC.argtypes = [_H]
user32.ReleaseDC.argtypes = [_H, _H]
_gdi32.CreateCompatibleDC.restype = _H; _gdi32.CreateCompatibleDC.argtypes = [_H]
_gdi32.CreateCompatibleBitmap.restype = _H
_gdi32.CreateCompatibleBitmap.argtypes = [_H, ctypes.c_int, ctypes.c_int]
_gdi32.SelectObject.restype = _H;    _gdi32.SelectObject.argtypes = [_H, _H]
_gdi32.BitBlt.restype = _wt.BOOL
_gdi32.BitBlt.argtypes = [_H, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, _H, ctypes.c_int, ctypes.c_int, _wt.DWORD]
_gdi32.GetDIBits.restype = ctypes.c_int
_gdi32.GetDIBits.argtypes = [_H, _H, _wt.UINT, _wt.UINT, ctypes.c_void_p,
                             ctypes.c_void_p, _wt.UINT]
_gdi32.DeleteObject.argtypes = [_H]
_gdi32.DeleteDC.argtypes = [_H]
_kernel32.GlobalAlloc.restype = _H
_kernel32.GlobalAlloc.argtypes = [_wt.UINT, ctypes.c_size_t]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = [_H]
_kernel32.GlobalUnlock.argtypes = [_H]
_kernel32.GlobalFree.restype = _H
_kernel32.GlobalFree.argtypes = [_H]
user32.OpenClipboard.restype = _wt.BOOL; user32.OpenClipboard.argtypes = [_H]
user32.SetClipboardData.restype = _H
user32.SetClipboardData.argtypes = [_wt.UINT, _H]

# ---- GDI 绘图（标注合成用） ----
_gdi32.CreateDIBSection.restype = _H
_gdi32.CreateDIBSection.argtypes = [_H, ctypes.c_void_p, _wt.UINT,
                                    ctypes.POINTER(ctypes.c_void_p), _H, _wt.DWORD]
_gdi32.CreatePen.restype = _H
_gdi32.CreatePen.argtypes = [_wt.INT, _wt.INT, _wt.DWORD]
_gdi32.CreateSolidBrush.restype = _H
_gdi32.CreateSolidBrush.argtypes = [_wt.DWORD]
_gdi32.Rectangle.restype = _wt.BOOL
_gdi32.Rectangle.argtypes = [_H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
_gdi32.Ellipse.restype = _wt.BOOL
_gdi32.Ellipse.argtypes = [_H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
_gdi32.MoveToEx.restype = _wt.BOOL
_gdi32.MoveToEx.argtypes = [_H, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
_gdi32.LineTo.restype = _wt.BOOL
_gdi32.LineTo.argtypes = [_H, ctypes.c_int, ctypes.c_int]
_gdi32.SetTextColor.restype = _wt.DWORD
_gdi32.SetTextColor.argtypes = [_H, _wt.DWORD]
_gdi32.SetBkMode.argtypes = [_H, _wt.INT]
_gdi32.TextOutW.restype = _wt.BOOL
_gdi32.TextOutW.argtypes = [_H, ctypes.c_int, ctypes.c_int, _wt.LPCWSTR, _wt.INT]
_gdi32.CreateFontW.restype = _H
_gdi32.CreateFontW.argtypes = [_wt.LONG] * 13 + [_wt.LPCWSTR]
_gdi32.PolylineTo.restype = _wt.BOOL
_gdi32.PolylineTo.argtypes = [_H, ctypes.c_void_p, _wt.DWORD]
_gdi32.GetStockObject.restype = _H
_gdi32.GetStockObject.argtypes = [_wt.INT]

# ---- 全局鼠标低级钩子（WH_MOUSE_LL，监听中键任意位置按下）----
_kernel32.GetModuleHandleW.restype = _H
_kernel32.GetModuleHandleW.argtypes = [_wt.LPCWSTR]
user32.SetWindowsHookExW.restype = _H
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, _H, _wt.DWORD]
user32.UnhookWindowsHookEx.restype = _wt.BOOL
user32.UnhookWindowsHookEx.argtypes = [_H]
user32.CallNextHookEx.restype = ctypes.c_long   # LRESULT
user32.CallNextHookEx.argtypes = [_H, ctypes.c_int, _wt.WPARAM, _wt.LPARAM]
user32.GetMessageW.restype = _wt.BOOL
user32.GetMessageW.argtypes = [ctypes.c_void_p, _H, _wt.UINT, _wt.UINT]
user32.TranslateMessage.restype = _wt.BOOL
user32.TranslateMessage.argtypes = [ctypes.c_void_p]
user32.DispatchMessageW.restype = _wt.LONG
user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
user32.PostThreadMessageW.restype = _wt.BOOL
user32.PostThreadMessageW.argtypes = [_wt.DWORD, _wt.UINT, _wt.WPARAM, _wt.LPARAM]

WM_QUIT = 0x0012
WM_MBUTTONDOWN = 0x0207
WH_MOUSE_LL = 14


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('pt', _wt.POINT),
        ('mouseData', _wt.DWORD),
        ('flags', _wt.DWORD),
        ('time', _wt.DWORD),
        ('dwExtraInfo', ctypes.c_void_p),
    ]


class GlobalMidButtonHook:
    """监听鼠标中键按下事件：任意位置按下滚轮中键都会触发回调。

    用 WH_MOUSE_LL 低级钩子实现，无需点击宠物本体。回调通过
    `tk_root.after(0, ...)` 调度到 Tk 主线程，避免跨线程 GUI 操作。

    用法：GlobalMidButtonHook(tk_root, callback)
    """
    def __init__(self, tk_root, callback):
        self.tk_root = tk_root
        self.callback = callback
        self.hook = None
        self._thread_id = 0
        self._running = False
        # 钩子函数原型：LRESULT (*)(int nCode, WPARAM wParam, LPARAM lParam)
        self._proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_int, _wt.WPARAM, _wt.LPARAM)
        self._proc_ref = self._proc_type(self._hook_proc)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self._thread_id = _kernel32.GetCurrentThreadId()
        hinst = _kernel32.GetModuleHandleW(None)
        self.hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc_ref, hinst, 0)
        if not self.hook:
            return
        self._running = True
        msg = (_wt.MSG * 1)()
        while True:
            # 阻塞等消息；收到 WM_QUIT 时 ret == 0，错误时 ret == -1
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
            if not self._running:
                break
        if self.hook:
            try:
                user32.UnhookWindowsHookEx(self.hook)
            except Exception:
                pass
            self.hook = None

    def stop(self):
        self._running = False
        # 给钩子线程发 WM_QUIT 让 GetMessage 退出
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _hook_proc(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam == WM_MBUTTONDOWN:
            try:
                self.tk_root.after(0, self._safe_callback)
            except Exception:
                pass
        return user32.CallNextHookEx(self.hook, nCode, wParam, lParam)

    def _safe_callback(self):
        try:
            self.callback()
        except Exception:
            pass


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', _wt.DWORD), ('biWidth', _wt.LONG),
        ('biHeight', _wt.LONG), ('biPlanes', _wt.WORD),
        ('biBitCount', _wt.WORD), ('biCompression', _wt.DWORD),
        ('biSizeImage', _wt.DWORD), ('biXPelsPerMeter', _wt.LONG),
        ('biYPelsPerMeter', _wt.LONG), ('biClrUsed', _wt.DWORD),
        ('biClrImportant', _wt.DWORD),
    ]


def _grab_virtual_screen():
    """抓取虚拟屏幕（覆盖所有显示器）。返回 (x0, y0, w, h, pixels_bgra)。

    pixels 为自下而上的 BGRA 行序列；失败返回 None。
    """
    x0 = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    y0 = user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
    w = user32.GetSystemMetrics(78)    # SM_CXVIRTUALSCREEN
    h = user32.GetSystemMetrics(79)    # SM_CYVIRTUALSCREEN
    if w <= 0 or h <= 0:
        x0 = y0 = 0
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
    if w <= 0 or h <= 0:
        return None
    hdc_screen = user32.GetDC(None)
    hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = _gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    _gdi32.SelectObject(hdc_mem, hbmp)
    ok = _gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x0, y0, 0x00CC0020)
    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight = w, h
    bmi.biPlanes, bmi.biBitCount = 1, 32
    bmi.biSizeImage = w * h * 4
    buf = ctypes.create_string_buffer(bmi.biSizeImage)
    got = _gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0) if ok else 0
    _gdi32.DeleteObject(hbmp)
    _gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(None, hdc_screen)
    if not ok or got == 0:
        return None
    return x0, y0, w, h, buf.raw


def _clip_dib(pixels, w, h, rx, ry, rw, rh):
    """从底-up BGRA 像素中裁剪矩形（坐标自动夹取），返回 (新像素, 宽, 高)。"""
    rx = max(0, min(rx, w)); ry = max(0, min(ry, h))
    rw = max(0, min(rw, w - rx)); rh = max(0, min(rh, h - ry))
    if rw == 0 or rh == 0:
        return None, 0, 0
    out = bytearray(rw * rh * 4)
    s_stride, d_stride = w * 4, rw * 4
    for i in range(rh):
        src = (h - 1 - (ry + i)) * s_stride + rx * 4
        dst = (rh - 1 - i) * d_stride
        out[dst:dst + d_stride] = pixels[src:src + d_stride]
    return bytes(out), rw, rh


def _set_clipboard_dib(pixels, w, h):
    """把底-up BGRA 像素以 CF_DIB 写入系统剪贴板。成功返回 True。"""
    try:
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = w, h
        bmi.biPlanes, bmi.biBitCount = 1, 32
        bmi.biSizeImage = len(pixels)
        dib = ctypes.string_at(ctypes.addressof(bmi), bmi.biSize) + pixels
        hg = _kernel32.GlobalAlloc(0x0002, len(dib))
        if not hg:
            return False
        ptr = _kernel32.GlobalLock(hg)
        if not ptr:
            _kernel32.GlobalFree(hg)
            return False
        ctypes.memmove(ptr, dib, len(dib))
        _kernel32.GlobalUnlock(hg)
        if not user32.OpenClipboard(None):
            _kernel32.GlobalFree(hg)
            return False
        user32.EmptyClipboard()
        res = user32.SetClipboardData(8, hg)   # 成功后内存归系统
        user32.CloseClipboard()
        if not res:
            _kernel32.GlobalFree(hg)
            return False
        return True
    except Exception:
        return False


def _save_bmp_file(pixels_bgra, w, h, path):
    """把底-up BGRA 像素写成 BMP 文件（24 位 BGR + alpha padding → 32 位 BGRA）。
    BMP 标准只接受 BGR 不接受 BGRA，但 Windows 32 位 BMP 兼容 BGRA，多数图片软件能正常打开。
    """
    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight = w, h
    bmi.biPlanes, bmi.biBitCount = 1, 32
    bmi.biCompression = 0
    bmi.biSizeImage = w * h * 4
    # BITMAPFILEHEADER: 'BM' + bfSize(4) + bfReserved1(2) + bfReserved2(2) + bfOffBits(4)
    bf_size = 14 + bmi.biSize + len(pixels_bgra)
    bfh = b'BM' + bf_size.to_bytes(4, 'little') + (0).to_bytes(4, 'little') + \
        (14 + bmi.biSize).to_bytes(4, 'little')
    with open(path, 'wb') as f:
        f.write(bfh)
        f.write(ctypes.string_at(ctypes.addressof(bmi), bmi.biSize))
        f.write(pixels_bgra)


def _hex_to_colorref(hx):
    """'#rrggbb' → COLORREF (0x00bbggrr)"""
    hx = hx.lstrip('#')
    r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    return r | (g << 8) | (b << 16)


def _compose_with_annotations(pixels_bgra, w, h, annots):
    """把标注（rect/ellipse/arrow/freehand/text，坐标相对选区左上角）用 GDI
    合成到裁剪后的截图上，返回新的底-up BGRA 像素。

    实现：CreateDIBSection 建 top-down 32 位 DIB → 拷入像素 → GDI 绘图 → 读回
    （top-down → 底-up 翻转）。失败返回原像素。
    """
    try:
        DIB_RGB_COLORS = 0
        NULL_BRUSH = 5
        TRANSPARENT = 1

        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = w, -h   # 负高 = top-down
        bmi.biPlanes, bmi.biBitCount = 1, 32
        bmi.biSizeImage = w * h * 4

        hdc_screen = user32.GetDC(None)
        hdc = _gdi32.CreateCompatibleDC(hdc_screen)
        bits = ctypes.c_void_p()
        hbmp = _gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                       ctypes.byref(bits), None, 0)
        if not hbmp or not bits.value:
            _gdi32.DeleteDC(hdc)
            user32.ReleaseDC(None, hdc_screen)
            return pixels_bgra
        _gdi32.SelectObject(hdc, hbmp)
        # 拷入像素（源是底-up，DIB 是 top-down：逐行翻转拷贝）
        stride = w * 4
        for y in range(h):
            src = (h - 1 - y) * stride
            ctypes.memmove(bits.value + y * stride, pixels_bgra[src:src + stride], stride)

        # GDI 绘图
        _gdi32.SelectObject(hdc, _gdi32.GetStockObject(NULL_BRUSH))  # 空心
        _gdi32.SetBkMode(hdc, TRANSPARENT)
        old_font = None
        PEN_W = 3
        for a in annots:
            kind = a[0]
            col = _hex_to_colorref(a[-1] if kind != 'freehand' else a[2])
            pen = _gdi32.CreatePen(0, PEN_W, col)
            _gdi32.SelectObject(hdc, pen)
            if kind in ('rect', 'ellipse'):
                x1, y1, x2, y2 = a[1], a[2], a[3], a[4]
                if x2 < x1: x1, x2 = x2, x1
                if y2 < y1: y1, y2 = y2, y1
                (_gdi32.Rectangle if kind == 'rect' else _gdi32.Ellipse)(
                    hdc, x1, y1, x2, y2)
            elif kind == 'arrow':
                x1, y1, x2, y2 = a[1], a[2], a[3], a[4]
                _gdi32.MoveToEx(hdc, x1, y1, None)
                _gdi32.LineTo(hdc, x2, y2)
                # 箭头头部（两条短线）
                ang = math.atan2(y2 - y1, x2 - x1)
                al = 14
                for da in (math.pi / 7, -math.pi / 7):
                    hx2 = int(x2 - al * math.cos(ang + da))
                    hy2 = int(y2 - al * math.sin(ang + da))
                    _gdi32.MoveToEx(hdc, x2, y2, None)
                    _gdi32.LineTo(hdc, hx2, hy2)
            elif kind == 'freehand':
                pts = a[1]
                if len(pts) >= 2:
                    _gdi32.MoveToEx(hdc, pts[0][0], pts[0][1], None)
                    for px, py in pts[1:]:
                        _gdi32.LineTo(hdc, px, py)
            elif kind == 'text':
                tx, ty, txt = a[1], a[2], a[3]
                if old_font is None:
                    font = _gdi32.CreateFontW(20, 0, 0, 0, 700, 0, 0, 0,
                                              1, 0, 0, 0, 0, 'Microsoft YaHei UI')
                    old_font = _gdi32.SelectObject(hdc, font)
                _gdi32.SetTextColor(hdc, col)
                _gdi32.TextOutW(hdc, tx, ty, txt, len(txt))
            _gdi32.DeleteObject(pen)

        # 读回（top-down → 底-up）
        raw = ctypes.string_at(bits.value, w * h * 4)
        out = bytearray(w * h * 4)
        for y in range(h):
            dst = (h - 1 - y) * stride
            out[dst:dst + stride] = raw[y * stride:y * stride + stride]

        _gdi32.DeleteObject(hbmp)
        _gdi32.DeleteDC(hdc)
        user32.ReleaseDC(None, hdc_screen)
        return bytes(out)
    except Exception:
        return pixels_bgra


def _encode_ppm(pixels_bgra, w, h):
    """底-up BGRA 像素 → PPM 字节（P6）。tkinter PhotoImage 原生支持，免压缩、速度快。"""
    out = bytearray(f'P6\n{w} {h}\n255\n'.encode())
    stride = w * 4
    for y in range(h - 1, -1, -1):
        row = pixels_bgra[y * stride:(y + 1) * stride]
        rgb = bytearray(stride * 3 // 4)
        rgb[0::3] = row[2::4]   # R
        rgb[1::3] = row[1::4]   # G
        rgb[2::3] = row[0::4]   # B
        out += rgb
    return bytes(out)


def capture_screen_to_clipboard():
    """全屏截图写入剪贴板（CF_DIB）。成功返回 True。"""
    try:
        g = _grab_virtual_screen()
        if not g:
            return False
        _x0, _y0, w, h, px = g
        return _set_clipboard_dib(px, w, h)
    except Exception:
        return False


class RegionSnipper:
    """QQ 截图式区域框选：全屏冻结背景 + 半透明遮罩 + 框选区域，确认后裁剪入剪贴板。

    交互：按一下定起点 → 移到终点（无需按住）再按一下定终点 → 工具栏标注/钉图/复制。
    仍兼容按住拖拽：按住画到合适区域，松开后再按一下定终点。

    用法：RegionSnipper(on_done=lambda ok: ...)。on_done(True) 表示已截图，False 表示取消。
    """

    def __init__(self, on_done):
        self.on_done = on_done
        g = _grab_virtual_screen()
        self.top = None
        if not g:
            self._finish(False)
            return
        self.vx, self.vy, self.vw, self.vh, self.px = g
        self._ppm_path = None
        try:
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix='.ppm', delete=False)
            tf.write(_encode_ppm(self.px, self.vw, self.vh))
            tf.close()
            self._ppm_path = tf.name
            self.bg = tk.PhotoImage(file=self._ppm_path)   # 冻结的屏幕画面
        except Exception:
            self._cleanup()
            self._finish(False)
            return
        self.top = tk.Toplevel()
        self.top.overrideredirect(True)
        self.top.attributes('-topmost', True)
        self.top.geometry(f'{self.vw}x{self.vh}+{self.vx}+{self.vy}')
        self.cv = tk.Canvas(self.top, width=self.vw, height=self.vh,
                            highlightthickness=0, bd=0, cursor='crosshair')
        self.cv.pack()
        self.cv.create_image(0, 0, anchor='nw', image=self.bg)
        # 半透明暗化遮罩：选区四周 4 块（gray50 点阵），选区内露出清晰底图
        for t in ('mtop', 'mbot', 'mleft', 'mright'):
            self.cv.create_rectangle(0, 0, 0, 0, fill='gray50', stipple='gray50',
                                     outline='', tags=t)
        self.sel = None        # 选区边框 id
        self.size_tag = None   # 尺寸标签 id
        self.x0 = self.y0 = 0
        self.has_start = False  # 是否已记录起点（两次点击模式：第一次按下后置 True）
        self.dragging = False   # 是否处于按住拖拽中（兼容原按住拖拽）
        self.done = False
        self.mode = 'select'   # select（框选中）/ edit（标注中）
        self.hint_tag = None   # 起始提示文字（首次按下前的「按下确定起点」提示）
        # ---- 编辑模式状态 ----
        self.srect = None      # 锁定的选区 (x1,y1,x2,y2)
        self.tool = 'rect'     # rect / ellipse / arrow / brush / text
        self.color = '#ff3b30'
        self.annots = []       # 已提交标注（坐标相对选区左上角）
        self.tb_ids = []       # 工具栏画布项 id
        self.draw_item = None  # 当前正在画的预览项
        self.draw_pts = None   # freehand 点集
        self.text_entry = None
        # 框选：按下（确定起点/终点）+ 任意移动（无需按住）+ 松开（拖拽完成）
        self.cv.bind('<ButtonPress-1>', self._down)
        self.cv.bind('<Motion>', self._move)         # 鼠标移动时（无论是否按住）实时更新选区
        self.cv.bind('<ButtonRelease-1>', self._up)
        self.top.bind('<Escape>', lambda _e: self._on_escape())
        self.top.bind('<Button-3>', lambda _e: self._cancel())
        self.top.focus_force()
        self._show_hint()
        self._update_mask(0, 0, 0, 0)

    # ---------------- 框选阶段 ----------------
    def _rect(self):
        x1, y1 = self.cv.winfo_pointerx() - self.vx, self.cv.winfo_pointery() - self.vy
        return min(self.x0, x1), min(self.y0, y1), max(self.x0, x1), max(self.y0, y1)

    def _update_mask(self, x1, y1, x2, y2):
        """遮罩 = 选区外的四块矩形"""
        vw, vh = self.vw, self.vh
        self.cv.coords('mtop', 0, 0, vw, y1)
        self.cv.coords('mbot', 0, y2, vw, vh)
        self.cv.coords('mleft', 0, y1, x1, y2)
        self.cv.coords('mright', x2, y1, vw, y2)

    def _show_hint(self):
        """首次框选前在屏幕中央显示提示文字。"""
        if self.hint_tag is not None:
            return
        self.hint_tag = self.cv.create_text(
            self.vw // 2, self.vh // 2, text='按一下鼠标定起点 · 移到终点再按一下定终点\n（也支持按住拖拽）',
            fill='#ffffff', font=('Microsoft YaHei UI', 14, 'bold'),
            justify='center', anchor='center')
        # 文字背景遮罩（半透明）
        self.top.update_idletasks()
        box = self.cv.bbox(self.hint_tag) or (0, 0, 1, 1)
        bg = self.cv.create_rectangle(box[0] - 8, box[1] - 6, box[2] + 8, box[3] + 6,
                                      fill='#000000', stipple='gray50', outline='')
        self.cv.tag_lower(bg, self.hint_tag)
        self.hint_bg = bg

    def _clear_hint(self):
        if self.hint_tag is not None:
            self.cv.delete(self.hint_tag)
            self.hint_tag = None
        if getattr(self, 'hint_bg', None) is not None:
            self.cv.delete(self.hint_bg)
            self.hint_bg = None

    def _down(self, e):
        """按下事件：
        · 未定起点 → 记录起点（has_start=True），进入「待定终点」状态
        · 已定起点且当前指针距离起点 ≥4px → 确认终点，进入编辑模式
        · 已定起点但距离 <4px（在原地小按一下）→ 把当前点作为新起点重新框选
        """
        if not self.has_start:
            self.x0, self.y0 = e.x, e.y
            self.has_start = True
            self.dragging = True
            self._clear_hint()
            return
        # 已经有起点：判断当前指针位置（用屏幕坐标避免 e.x 在 mask 项上的偏差）
        cx = self.cv.winfo_pointerx() - self.vx
        cy = self.cv.winfo_pointery() - self.vy
        rw, rh = abs(cx - self.x0), abs(cy - self.y0)
        if rw >= 4 or rh >= 4:
            x1, y1, x2, y2 = (min(self.x0, cx), min(self.y0, cy),
                              max(self.x0, cx), max(self.y0, cy))
            self._enter_edit(x1, y1, x2, y2)
        else:
            # 在原地小按一下：把当前点作为新起点重新框选
            self.x0, self.y0 = e.x, e.y
            self.dragging = True
            # 清掉旧选区视觉，从 0×0 开始
            if self.sel is not None:
                self.cv.delete(self.sel)
                self.cv.delete(self.size_tag)
                self.sel = None
                self.size_tag = None
            self._update_mask(0, 0, 0, 0)

    def _move(self, _e):
        # 只在框选阶段响应；进入编辑模式后解绑/不更新，避免选区/遮罩跟着鼠标跑
        if self.mode != 'select' or not self.has_start:
            return
        x1, y1, x2, y2 = self._rect()
        self._update_mask(x1, y1, x2, y2)
        if self.sel is None:
            self.sel = self.cv.create_rectangle(
                x1, y1, x2, y2, outline='#22c55e', width=2)
            self.size_tag = self.cv.create_text(
                0, 0, anchor='sw', fill='#ffffff',
                font=('Microsoft YaHei UI', 10, 'bold'), text='')
        else:
            self.cv.coords(self.sel, x1, y1, x2, y2)
        self.cv.coords(self.size_tag, x1 + 2, max(14, y1 - 4))
        self.cv.itemconfigure(self.size_tag, text=f'{x2-x1} × {y2-y1}')
        self.cv.tag_raise(self.sel)
        self.cv.tag_raise(self.size_tag)

    def _up(self, _e):
        """松开事件：按住拖拽时松开即确认选区进入编辑模式。
        若按下后几乎没拖（<4px）就松开，则保持 has_start=True，
        进入「两次点击」模式：移动鼠标（不按住）实时预览，再次按下确认终点。
        """
        if not self.has_start:
            return
        if not self.dragging:
            return
        self.dragging = False
        x1, y1, x2, y2 = self._rect()
        rw, rh = x2 - x1, y2 - y1
        if rw >= 4 and rh >= 4:
            self._enter_edit(x1, y1, x2, y2)
        # 否则保持 has_start=True，进入两次点击模式，等用户移动后再次按下定终点

    # ---------------- 编辑阶段（标注工具栏） ----------------
    TOOLS = [('rect', '▭', '矩形'), ('ellipse', '◯', '椭圆'), ('arrow', '→', '箭头'),
             ('brush', '✎', '画笔'), ('text', 'T', '文字')]
    COLORS = ['#ff3b30', '#ff9500', '#ffcc00', '#34c759', '#0a84ff', '#ffffff', '#000000']

    def _enter_edit(self, x1, y1, x2, y2):
        self.mode = 'edit'
        self.srect = (x1, y1, x2, y2)
        self.has_start = False
        self.dragging = False
        if self.sel is not None:
            self.cv.delete(self.sel)
            self.sel = None
        if self.size_tag is not None:
            self.cv.delete(self.size_tag)
            self.size_tag = None
        self._clear_hint()
        self._update_mask(x1, y1, x2, y2)
        self.cv.configure(cursor='pencil')
        self._build_toolbar()
        # 重绑事件到编辑处理
        self.cv.bind('<ButtonPress-1>', self._edit_down)
        self.cv.bind('<B1-Motion>', self._edit_move)
        self.cv.bind('<ButtonRelease-1>', self._edit_up)

    def _build_toolbar(self):
        """选区下方（空间不足则上方）画深色工具条"""
        for i in self.tb_ids:
            self.cv.delete(i)
        self.tb_ids = []
        x1, y1, x2, y2 = self.srect
        bw, bh = 30, 30
        gap = 4
        # 工具 5 + 颜色 7 + 撤销/钉图/确认/取消 4 = 16 格
        n = len(self.TOOLS) + len(self.COLORS) + 4
        total_w = n * bw + (n + 1) * gap
        bar_h = bh + gap * 2
        cx = (x1 + x2) // 2
        bx1 = max(4, min(cx - total_w // 2, self.vw - total_w - 4))
        if y2 + bar_h + 8 <= self.vh:
            by1 = y2 + 8
        else:
            by1 = max(4, y1 - bar_h - 8)
        bg = self.cv.create_rectangle(bx1, by1, bx1 + total_w, by1 + bar_h,
                                      fill='#2b2b2b', outline='#555555', width=1)
        self.tb_ids.append(bg)
        x = bx1 + gap
        mid_y = by1 + bar_h // 2

        def box(x0, tag, fill='#3a3a3a', outline=''):
            r = self.cv.create_rectangle(x0, by1 + gap, x0 + bw, by1 + gap + bh,
                                         fill=fill, outline=outline, width=2,
                                         tags=('tb', tag))
            self.tb_ids.append(r)
            return r

        for tid, sym, _name in self.TOOLS:
            fill = '#0a84ff' if self.tool == tid else '#3a3a3a'
            box(x, 'tool:' + tid, fill=fill)
            t = self.cv.create_text(x + bw // 2, mid_y, text=sym, fill='#ffffff',
                                    font=('Microsoft YaHei UI', 13, 'bold'),
                                    tags=('tb', 'tool:' + tid))
            self.tb_ids.append(t)
            x += bw + gap
        # 颜色
        for c in self.COLORS:
            tag = 'color:' + c
            ring = '#ffffff' if c == '#000000' else '#888888'
            oc = '#ffffff' if self.color == c else ring
            o = self.cv.create_oval(x + 5, mid_y - 10, x + bw - 5, mid_y + 10,
                                    fill=c, outline=oc, width=3, tags=('tb', tag))
            self.tb_ids.append(o)
            x += bw + gap
        # 撤销 / 钉图 / 确认 / 取消
        for sym, tag, fill in (('↩', 'act:undo', '#3a3a3a'),
                               ('📌', 'act:pin', '#0a84ff'),
                               ('✓', 'act:ok', '#34c759'),
                               ('✕', 'act:cancel', '#ff3b30')):
            box(x, tag, fill=fill)
            t = self.cv.create_text(x + bw // 2, mid_y, text=sym, fill='#ffffff',
                                    font=('Microsoft YaHei UI', 14, 'bold'),
                                    tags=('tb', tag))
            self.tb_ids.append(t)
            x += bw + gap
        self.cv.tag_raise('tb')

    def _tb_hit(self, e):
        """点中工具栏返回 action 字符串，否则 None"""
        cur = self.cv.find_withtag('current')
        if not cur:
            return None
        for t in self.cv.gettags(cur[0]):
            if t.startswith('tool:') or t.startswith('color:') or t.startswith('act:'):
                return t
        return None

    def _in_sel(self, x, y):
        x1, y1, x2, y2 = self.srect
        return x1 <= x <= x2 and y1 <= y <= y2

    def _edit_down(self, e):
        act = self._tb_hit(e)
        if act:
            kind, val = act.split(':', 1)
            if kind == 'tool':
                self.tool = val
                self._build_toolbar()
            elif kind == 'color':
                self.color = val
                self._build_toolbar()
            elif kind == 'act':
                if val == 'undo':
                    self._undo()
                elif val == 'pin':
                    self._pin_to_screen()
                elif val == 'ok':
                    self._confirm()
                elif val == 'cancel':
                    self._cancel()
            return
        if not self._in_sel(e.x, e.y):
            return
        if self.tool == 'text':
            self._open_text_entry(e.x, e.y)
            return
        # 形状/画笔：开始画
        self.draw_start = (e.x, e.y)
        self.draw_pts = [(e.x, e.y)] if self.tool == 'brush' else None
        col = self.color
        if self.tool == 'rect':
            self.draw_item = self.cv.create_rectangle(e.x, e.y, e.x, e.y,
                                                      outline=col, width=3)
        elif self.tool == 'ellipse':
            self.draw_item = self.cv.create_oval(e.x, e.y, e.x, e.y,
                                                 outline=col, width=3)
        elif self.tool == 'arrow':
            self.draw_item = self.cv.create_line(e.x, e.y, e.x, e.y, fill=col,
                                                 width=3, arrow='last',
                                                 arrowshape=(14, 16, 6))
        elif self.tool == 'brush':
            self.draw_item = self.cv.create_line(e.x, e.y, e.x, e.y, fill=col,
                                                 width=3, capstyle='round',
                                                 smooth=True)

    def _edit_move(self, e):
        if self.draw_item is None:
            return
        sx, sy = self.draw_start
        if self.tool in ('rect', 'ellipse'):
            self.cv.coords(self.draw_item, sx, sy, e.x, e.y)
        elif self.tool == 'arrow':
            self.cv.coords(self.draw_item, sx, sy, e.x, e.y)
        elif self.tool == 'brush':
            self.draw_pts.append((e.x, e.y))
            flat = [c for p in self.draw_pts for c in p]
            self.cv.coords(self.draw_item, *flat)
        self.cv.tag_raise('tb')

    def _edit_up(self, _e):
        if self.draw_item is None:
            return
        coords = self.cv.coords(self.draw_item)
        x1, y1 = self.srect[0], self.srect[1]
        idx = len(self.annots)
        tag = f'ann{idx}'
        self.cv.itemconfigure(self.draw_item, tags=('ann', tag))
        if self.tool in ('rect', 'ellipse'):
            self.annots.append((self.tool,
                                int(coords[0] - x1), int(coords[1] - y1),
                                int(coords[2] - x1), int(coords[3] - y1), self.color))
        elif self.tool == 'arrow':
            self.annots.append(('arrow',
                                int(coords[0] - x1), int(coords[1] - y1),
                                int(coords[2] - x1), int(coords[3] - y1), self.color))
        elif self.tool == 'brush' and len(self.draw_pts) >= 2:
            pts = [(p[0] - x1, p[1] - y1) for p in self.draw_pts]
            self.annots.append(('freehand', pts, self.color))
        else:
            self.cv.delete(self.draw_item)
        self.draw_item = None
        self.draw_pts = None

    def _open_text_entry(self, cx, cy):
        if self.text_entry is not None:
            self.text_entry.destroy()
        ent = tk.Entry(self.top, font=('Microsoft YaHei UI', 13, 'bold'),
                       fg=self.color, bg='#ffffff', relief='solid', bd=1,
                       width=12, insertbackground=self.color)
        ent.place(x=cx, y=cy)
        ent.focus_set()
        self.text_entry = ent

        def commit(_ev=None):
            if self.text_entry is not ent:   # 已提交/取消/被新输入框取代
                return
            val = ent.get()
            self.text_entry = None
            ent.destroy()
            txt = val.strip()
            if txt:
                idx = len(self.annots)
                x1, y1 = self.srect[0], self.srect[1]
                self.cv.create_text(cx, cy, text=txt, fill=self.color, anchor='nw',
                                    font=('Microsoft YaHei UI', 14, 'bold'),
                                    tags=('ann', f'ann{idx}'))
                self.annots.append(('text', cx - x1, cy - y1, txt, self.color))

        def cancel_entry(_ev=None):
            if self.text_entry is not ent:
                return
            self.text_entry = None
            ent.destroy()

        ent.bind('<Return>', commit)
        ent.bind('<Escape>', lambda e: cancel_entry())
        ent.bind('<FocusOut>', lambda e: commit())

    def _undo(self):
        if self.text_entry is not None:
            self.text_entry.destroy()
            self.text_entry = None
            return
        if not self.annots:
            return
        idx = len(self.annots) - 1
        self.annots.pop()
        self.cv.delete(f'ann{idx}')

    def _on_escape(self):
        if self.text_entry is not None:
            self.text_entry.destroy()
            self.text_entry = None
        else:
            self._cancel()

    def _confirm(self):
        x1, y1, x2, y2 = self.srect
        rw, rh = x2 - x1, y2 - y1
        cropped, cw, ch = _clip_dib(self.px, self.vw, self.vh, x1, y1, rw, rh)
        if not cropped:
            self._finish(False)
            return
        if self.annots:
            cropped = _compose_with_annotations(cropped, cw, ch, self.annots)
        ok = _set_clipboard_dib(cropped, cw, ch)
        self._finish(ok)

    def _pin_to_screen(self):
        """把当前选区（含标注）裁剪后钉到屏幕上：置顶透明窗口、可拖拽。"""
        x1, y1, x2, y2 = self.srect
        rw, rh = x2 - x1, y2 - y1
        cropped, cw, ch = _clip_dib(self.px, self.vw, self.vh, x1, y1, rw, rh)
        if not cropped:
            self._finish(False)
            return
        if self.annots:
            cropped = _compose_with_annotations(cropped, cw, ch, self.annots)
        # 屏幕坐标：选区左上角绝对位置（虚拟屏幕偏移 + 选区偏移）
        ax = self.vx + x1
        ay = self.vy + y1
        PinnedImage(cropped, cw, ch, ax, ay)
        self._finish(True)

    def _cancel(self):
        self._finish(False)

    def _cleanup(self):
        """删除临时 PPM 文件"""
        p = getattr(self, '_ppm_path', None)
        if p:
            self._ppm_path = None
            try:
                os.unlink(p)
            except Exception:
                pass

    def _finish(self, ok):
        if self.done:
            return
        self.done = True
        if self.top is not None:
            try:
                self.top.destroy()
            except Exception:
                pass
        self._cleanup()
        cb = self.on_done
        self.on_done = None
        if cb:
            cb(ok)


def snip_region(on_done):
    """启动区域截图框选。on_done(ok: bool) 在主线程回调。"""
    RegionSnipper(on_done)


class PinnedImage:
    """把截图钉在屏幕上的置顶透明窗口（Snipaste 风格）。

    用法：PinnedImage(pixels_bgra, w, h, screen_x, screen_y)
    · normal 模式：按住左键拖拽移动窗口；双击关闭
    · snip 模式（点右键「框选复制局部」进入）：按下拖拽选局部 → 松开自动复制到剪贴板
    · 右键菜单：复制整图 / 框选复制局部 / 另存为 / 回到原位 / 关闭
    · Esc 关闭窗口（snip 模式下 Esc 退出 snip 而不关窗）
    """

    def __init__(self, pixels_bgra, w, h, screen_x, screen_y):
        self.pixels = pixels_bgra
        self.w = w
        self.h = h
        self.orig_x = int(screen_x)
        self.orig_y = int(screen_y)
        self.top = tk.Toplevel()
        self.top.overrideredirect(True)
        self.top.attributes('-topmost', True)
        self.top.geometry(f'{w}x{h}+{self.orig_x}+{self.orig_y}')
        # 底-up BGRA → PPM 临时文件 → PhotoImage
        self._ppm_path = None
        try:
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix='.ppm', delete=False)
            tf.write(_encode_ppm(pixels_bgra, w, h))
            tf.close()
            self._ppm_path = tf.name
            self.photo = tk.PhotoImage(file=self._ppm_path)
        except Exception:
            self._cleanup()
            try:
                self.top.destroy()
            except Exception:
                pass
            return
        # 用 Canvas 显示图片 + 1px 边框（hover 变红）
        self.cv = tk.Canvas(self.top, width=w, height=h, bd=0,
                            highlightthickness=1,
                            highlightbackground='#888888',
                            highlightcolor='#ff3b30')
        self.cv.pack()
        self.cv.create_image(0, 0, anchor='nw', image=self.photo)
        # 不抢焦点 + 不进任务栏（WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW）
        try:
            self.top.update_idletasks()
            hwnd = user32.GetParent(self.top.winfo_id())
            style = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000080)
        except Exception:
            pass
        # 交互状态
        self._mode = 'normal'        # normal / snip
        self._drag_dx = 0
        self._drag_dy = 0
        self._sel_id = None          # snip 模式选区矩形
        self._snip_start = None      # snip 模式起点 (x, y) 相对 canvas
        self._size_tag = None        # snip 模式尺寸标签
        # 事件绑定
        self.cv.bind('<Button-1>', self._on_down)
        self.cv.bind('<B1-Motion>', self._on_move)
        self.cv.bind('<ButtonRelease-1>', self._on_release)
        self.cv.bind('<Button-3>', self._on_menu)
        self.cv.bind('<Double-Button-1>', lambda _e: self._close())
        self.cv.bind('<Enter>', lambda _e: self.cv.configure(highlightbackground='#ff3b30'))
        self.cv.bind('<Leave>', lambda _e: self.cv.configure(highlightbackground='#888888'))
        self.top.bind('<Escape>', lambda _e: self._on_escape())
        self.cv.bind('<Escape>', lambda _e: self._on_escape())
        self.cv.configure(cursor='hand2')
        # 任意按键按下时尝试抢键盘焦点（让 Esc 能在 NOACTIVATE 窗口里工作）
        self.cv.bind('<Button-1>', lambda _e: self.cv.focus_set(), add='+')
        self.top.focus_force()

    # ---------------- 拖拽 / 框选 ----------------
    def _on_down(self, e):
        if self._mode == 'snip':
            self._snip_start = (e.x, e.y)
            self._sel_id = self.cv.create_rectangle(e.x, e.y, e.x, e.y,
                                                     outline='#ff3b30', width=2)
            self._size_tag = self.cv.create_text(
                e.x + 2, max(0, e.y - 6), anchor='sw', fill='#ffffff',
                font=('Microsoft YaHei UI', 9, 'bold'), text='')
            return
        self._drag_dx = e.x_root - self.top.winfo_x()
        self._drag_dy = e.y_root - self.top.winfo_y()
        self.cv.configure(cursor='fleur')

    def _on_move(self, e):
        if self._mode == 'snip' and self._sel_id is not None:
            sx, sy = self._snip_start
            x1, y1, x2, y2 = min(sx, e.x), min(sy, e.y), max(sx, e.x), max(sy, e.y)
            self.cv.coords(self._sel_id, x1, y1, x2, y2)
            self.cv.coords(self._size_tag, x1 + 2, max(8, y1 - 6))
            self.cv.itemconfigure(self._size_tag, text=f'{x2-x1} × {y2-y1}')
            return
        if self._drag_dx is None or self._mode != 'normal':
            return
        x = e.x_root - self._drag_dx
        y = e.y_root - self._drag_dy
        self.top.geometry(f'+{x}+{y}')

    def _on_release(self, e):
        if self._mode == 'snip' and self._sel_id is not None:
            self._do_snip_copy(e.x, e.y)
            return
        self.cv.configure(cursor='hand2' if self._mode == 'normal' else 'crosshair')

    # ---------------- snip 模式 ----------------
    def _enter_snip_mode(self):
        self._mode = 'snip'
        self.cv.configure(cursor='crosshair')
        self.cv.configure(highlightbackground='#ff9500')
        self._snip_start = None
        self._sel_id = None
        self._size_tag = None

    def _exit_snip_mode(self):
        if self._sel_id is not None:
            self.cv.delete(self._sel_id)
            self._sel_id = None
        if self._size_tag is not None:
            self.cv.delete(self._size_tag)
            self._size_tag = None
        self._snip_start = None
        self._mode = 'normal'
        self.cv.configure(cursor='hand2')
        self.cv.configure(highlightbackground='#888888')

    def _do_snip_copy(self, ex, ey):
        sx, sy = self._snip_start
        x1, y1 = max(0, min(sx, ex)), max(0, min(sy, ey))
        x2, y2 = min(self.w, max(sx, ex)), min(self.h, max(sy, ey))
        rw, rh = x2 - x1, y2 - y1
        if rw >= 4 and rh >= 4:
            sub, sw, sh = _clip_dib(self.pixels, self.w, self.h, x1, y1, rw, rh)
            if sub:
                ok = _set_clipboard_dib(sub, sw, sh)
                if ok:
                    self._flash('#34c759')
        self._exit_snip_mode()

    # ---------------- 菜单 ----------------
    def _on_menu(self, e):
        # 在 snip 模式下右键直接退出 snip
        if self._mode == 'snip':
            self._exit_snip_mode()
            return
        m = tk.Menu(self.top, tearoff=0)
        m.add_command(label='复制到剪贴板（整图）', command=self._copy_all)
        m.add_command(label='框选复制局部…', command=self._enter_snip_mode)
        m.add_command(label='另存为 BMP…', command=self._save_as_bmp)
        m.add_separator()
        m.add_command(label='回到原位置', command=self._reset_pos)
        m.add_separator()
        m.add_command(label='关闭 (Esc)', command=self._close)
        m.tk_popup(e.x_root, e.y_root)

    def _copy_all(self):
        ok = _set_clipboard_dib(self.pixels, self.w, self.h)
        if ok:
            self._flash('#34c759')

    def _save_as_bmp(self):
        try:
            from tkinter import filedialog
            path = filedialog.asksaveasfilename(
                defaultextension='.bmp',
                filetypes=[('BMP 图片', '*.bmp'), ('所有文件', '*.*')],
                title='保存截图')
            if not path:
                return
            _save_bmp_file(self.pixels, self.w, self.h, path)
            self._flash('#34c759')
        except Exception:
            self._flash('#ff3b30')

    # ---------------- 杂项 ----------------
    def _reset_pos(self):
        self.top.geometry(f'+{self.orig_x}+{self.orig_y}')

    def _flash(self, color):
        orig = '#888888' if self._mode == 'normal' else '#ff9500'
        self.cv.configure(highlightbackground=color)
        self.top.after(400, lambda: self.cv.configure(highlightbackground=orig))

    def _on_escape(self):
        if self._mode == 'snip':
            self._exit_snip_mode()
        else:
            self._close()

    def _close(self):
        try:
            self.top.destroy()
        except Exception:
            pass
        self._cleanup()

    def _cleanup(self):
        p = getattr(self, '_ppm_path', None)
        if p:
            self._ppm_path = None
            try:
                os.unlink(p)
            except Exception:
                pass


# ---------------- 形象系统（插件式：每个形象一个 Sprite 子类） ----------------
class SpriteContext:
    """姿态参数上下文，由 Pet.draw 计算后传给 sprite.draw。
    所有 sprite 都接收同一组通用参数（state/bob/l_dy/l_swing/...），
    自己决定怎么用，也可以基于 t/state 再算形象特有的参数（如尾巴/裙摆摆幅）。
    """
    __slots__ = ('t', 'state', 'leg_phase', 'bob', 'l_dy', 'r_dy',
                 'l_swing', 'r_swing', 'sleeping', 'blink', 'surprised', 'squash')

    def __init__(self):
        self.t = 0.0
        self.state = 'idle'
        self.leg_phase = 0.0
        self.bob = 0.0
        self.l_dy = self.r_dy = 0.0
        self.l_swing = self.r_swing = 0.0
        self.sleeping = False
        self.blink = False
        self.surprised = False
        self.squash = 0.0


class PetSprite:
    """桌面宠物形象基类。子类实现 draw() 画形象。

    约定：使用 110×140 局部画布坐标系（原点在画布左上角），Pet.draw
    会把整体平移到画布中央并下移到 BODY_OFF 位置。
    """
    name = 'base'
    label = '基础形象'

    def draw(self, cv, ctx):
        raise NotImplementedError

    def cleanup(self):
        """切换形象或退出时清理资源（图片、临时文件等）"""
        pass


class JerryMouseSprite(PetSprite):
    """小杰瑞鼠：棕色矢量形象（项目原始形象）。"""
    name = 'jerry'
    label = '杰瑞鼠'

    def draw(self, cv, ctx):
        t = ctx.t
        st = ctx.state
        bob = ctx.bob
        l_dy, r_dy = ctx.l_dy, ctx.r_dy
        l_swing, r_swing = ctx.l_swing, ctx.r_swing
        sleeping = ctx.sleeping
        blink = ctx.blink
        surprised = ctx.surprised
        hy = bob

        # 尾巴摆幅（形象特有，自己算）
        if st == 'fall':
            tsway = -16.0
        elif st == 'walk':
            tsway = math.sin(t * 6.0) * 9.0
        elif sleeping:
            tsway = math.sin(t * 1.4) * 3.0
        else:
            tsway = math.sin(t * 3.2) * 7.0
        ear_sway = math.sin(t * 6.0) * 2.0 if st == 'walk' else 0.0

        # 尾巴
        cv.create_line(74, 116 + bob * 0.5, 90, 118 - tsway * 0.6 + bob * 0.5,
                       99, 100 - tsway + bob * 0.5,
                       smooth=True, width=5, capstyle='round', fill=C_LINE)
        # 脚
        cv.create_oval(44 - 8.5, 130 - 6.5 + l_dy, 44 + 8.5, 130 + 6.5 + l_dy,
                       fill=C_BODY, outline=C_LINE, width=2)
        cv.create_oval(66 - 8.5, 130 - 6.5 + r_dy, 66 + 8.5, 130 + 6.5 + r_dy,
                       fill=C_BODY, outline=C_LINE, width=2)
        # 身体
        cv.create_oval(33, 90 + hy * 0.6, 77, 136 + hy * 0.6,
                       fill=C_BODY, outline=C_LINE, width=2)
        # 肚皮
        cv.create_oval(41, 100 + hy * 0.6, 69, 132 + hy * 0.6,
                       fill=C_BELLY, outline='')
        # 手
        lhx, lhy2 = 34 + l_swing * 0.45, 116 + abs(l_swing) * 0.18
        cv.create_line(36, 108 + hy * 0.6, lhx, lhy2 + hy * 0.6,
                       width=7, capstyle='round', fill=C_BODY)
        cv.create_oval(lhx - 4.5, lhy2 - 4.5 + hy * 0.6, lhx + 4.5, lhy2 + 4.5 + hy * 0.6,
                       fill=C_BODY, outline=C_LINE, width=1.5)
        rhx, rhy2 = 76 + r_swing * 0.45, 116 + abs(r_swing) * 0.18
        cv.create_line(74, 108 + hy * 0.6, rhx, rhy2 + hy * 0.6,
                       width=7, capstyle='round', fill=C_BODY)
        cv.create_oval(rhx - 4.5, rhy2 - 4.5 + hy * 0.6, rhx + 4.5, rhy2 + 4.5 + hy * 0.6,
                       fill=C_BODY, outline=C_LINE, width=1.5)
        # 耳
        cv.create_oval(26 + ear_sway, 12 + hy, 52 + ear_sway, 38 + hy,
                       fill=C_BODY, outline=C_LINE, width=2)
        cv.create_oval(32 + ear_sway, 18 + hy, 46 + ear_sway, 32 + hy,
                       fill=C_EAR_IN, outline='')
        cv.create_oval(58 - ear_sway, 12 + hy, 84 - ear_sway, 38 + hy,
                       fill=C_BODY, outline=C_LINE, width=2)
        cv.create_oval(64 - ear_sway, 18 + hy, 78 - ear_sway, 32 + hy,
                       fill=C_EAR_IN, outline='')
        # 头
        cv.create_oval(24, 32 + hy, 86, 98 + hy,
                       fill=C_BODY, outline=C_LINE, width=2)
        # 口鼻
        cv.create_oval(37, 60 + hy, 73, 97 + hy,
                       fill=C_BELLY, outline='')
        # 眼
        ey = 54 + hy
        if sleeping:
            for ex in (45, 65):
                cv.create_arc(ex - 6, ey - 3, ex + 6, ey + 4, start=180, extent=180,
                              style='arc', outline=C_EYE, width=2.2)
        elif blink:
            cv.create_line(40, ey, 50, ey, width=2.5, capstyle='round', fill=C_EYE)
            cv.create_line(60, ey, 70, ey, width=2.5, capstyle='round', fill=C_EYE)
        else:
            for ex in (45, 65):
                r = 6.4 if surprised else 5.6
                cv.create_oval(ex - r, ey - r * 1.1, ex + r, ey + r * 1.1,
                               fill='#ffffff', outline='')
                pr = 2.6 if surprised else 3.2
                cv.create_oval(ex - pr, ey - pr * 1.05, ex + pr, ey + pr * 1.05,
                               fill=C_EYE, outline='')
        # 鼻
        cv.create_oval(52, 62 + hy, 58, 68 + hy, fill=C_NOSE, outline='')
        # 嘴
        my = 76 + hy
        if surprised:
            cv.create_oval(50, my, 60, my + 8, outline=C_EYE, width=2)
        else:
            cv.create_arc(48, my - 2, 62, my + 5, start=180, extent=180,
                          style='arc', outline=C_EYE, width=2)
        # 胡须
        for x0, y0, x1, y1 in ((38, 72 + hy, 20, 66 + hy), (38, 78 + hy, 18, 78 + hy),
                               (38, 84 + hy, 20, 90 + hy),
                               (72, 72 + hy, 90, 66 + hy), (72, 78 + hy, 92, 78 + hy),
                               (72, 84 + hy, 90, 90 + hy)):
            cv.create_line(x0, y0, x1, y1, width=1.5, capstyle='round', fill=C_LINE)
        # 腮红
        cv.create_oval(30, 68 + hy, 38, 73 + hy, fill=C_BLUSH, outline='')
        cv.create_oval(72, 68 + hy, 80, 73 + hy, fill=C_BLUSH, outline='')
        # Zzz
        if sleeping:
            cv.create_text(88, 34 + math.sin(t * 1.5) * 3, text='Z',
                           font=('Segoe UI', 12, 'bold'), fill='#94a3b8')
            cv.create_text(98, 20 + math.sin(t * 1.5 + 1.2) * 3, text='z',
                           font=('Segoe UI', 9, 'bold'), fill='#b0bcc9')


class ImageSprite(PetSprite):
    """通用图片帧动画形象：从 sprites/<name>/ 目录加载 frame_001.png/.gif 等图片序列。
    按状态/帧号映射播放。便于后续用真实美术素材替换矢量形象。

    目录约定：
      sprites/<name>/idle_001.png, idle_002.png, ...     待机循环
      sprites/<name>/walk_001.png, ...                  走路循环
      sprites/<name>/drag_001.png, ...                  拖拽循环
      sprites/<name>/fall_001.png, ...                 下落
      sprites/<name>/sleep_001.png, ...                睡觉循环
    缺失时回退到 idle 序列或单张 idle_001。
    """
    name = 'image'
    label = '图片形象'

    def __init__(self, dir_path):
        import os
        self.dir = dir_path
        self.name = os.path.basename(dir_path.rstrip('/\\'))
        self.label = self.name
        self.frames = {}      # state -> [(PhotoImage, dur_ms), ...]
        self._load()

    def _load(self):
        try:
            from PIL import Image as _PILImage  # type: ignore
            _HAS_PIL = True
        except Exception:
            _HAS_PIL = False
        for st in ('idle', 'walk', 'drag', 'fall', 'sleep'):
            seq = []
            i = 1
            while True:
                # 支持 png/gif；PIL 可加载更多格式
                found = None
                for ext in ('png', 'gif', 'PNG', 'GIF'):
                    p = os.path.join(self.dir, f'{st}_{i:03d}.{ext}')
                    if os.path.exists(p):
                        found = p
                        break
                if not found:
                    break
                try:
                    # PNG/GIF 直接用 tk.PhotoImage（原生支持 alpha 透明）
                    try:
                        ph = tk.PhotoImage(file=found)
                    except Exception:
                        # tk 不认识的格式（webp 等）：PIL 转存临时 PNG 保留透明通道
                        if not _HAS_PIL:
                            raise
                        im = _PILImage.open(found).convert('RGBA')
                        import tempfile
                        tf = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                        im.save(tf, format='PNG')
                        tf.close()
                        ph = tk.PhotoImage(file=tf.name)
                        try:
                            os.unlink(tf.name)
                        except Exception:
                            pass
                    seq.append((ph, 120))
                except Exception:
                    break
                i += 1
            if seq:
                self.frames[st] = seq
        # 回退到 idle
        if 'idle' not in self.frames:
            for st in self.frames:
                self.frames['idle'] = self.frames[st]
                break

    def draw(self, cv, ctx):
        if not self.frames:
            return
        st = ctx.state
        seq = self.frames.get(st) or self.frames.get('idle')
        if not seq:
            return
        idx = int(ctx.t * 1000 // 120) % len(seq)
        ph = seq[idx][0]
        # 居中放在 110×140 画布底部
        img_w = ph.width()
        img_h = ph.height()
        cv.create_image((110 - img_w) // 2, 140 - img_h, anchor='nw', image=ph)


# 形象注册表：name -> 类（或工厂）。要新增形象，往这里塞一行即可。
def _discover_image_sprites():
    """扫描 sprites/ 目录下所有子目录，自动注册为 ImageSprite 实例。"""
    out = []
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sprites')
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if os.path.isdir(full):
                out.append((name, full))
    return out


SPRITE_REGISTRY = {
    'jerry': JerryMouseSprite,
}


def list_sprites():
    """列出所有可用形象 [(name, label, factory_or_class), ...]，含自动发现的图片形象。"""
    out = []
    for name, cls in SPRITE_REGISTRY.items():
        out.append((name, cls.label, cls))
    # 自动发现的图片形象
    for name, path in _discover_image_sprites():
        if name in SPRITE_REGISTRY:
            continue
        # 延迟构造（避免目录为空时报错）
        out.append((name, name, ('image', path)))
    return out


def make_sprite(name):
    """根据 name 构造 sprite 实例。找不到时回退到杰瑞鼠。"""
    for n, label, thing in list_sprites():
        if n == name:
            try:
                if isinstance(thing, tuple) and thing[0] == 'image':
                    return ImageSprite(thing[1])
                return thing()
            except Exception:
                return JerryMouseSprite()
    return JerryMouseSprite()


SPRITE_CHOICE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  'sprite_choice.json')


def load_sprite_choice():
    """读上次保存的形象名；失败返回 None。"""
    try:
        with open(SPRITE_CHOICE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get('sprite')
    except Exception:
        return None


def save_sprite_choice(name):
    """持久化当前形象名。"""
    try:
        with open(SPRITE_CHOICE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'sprite': name}, f, ensure_ascii=False)
    except Exception:
        pass


def set_dpi_aware():
    """高分屏（125%/150% 缩放）下保证像素坐标不错位"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


class Pet:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)                        # 无边框
        self.root.attributes('-topmost', True)                  # 置顶
        self.root.attributes('-transparentcolor', TRANSPARENT)  # 背景透明

        self.sw = self.root.winfo_screenwidth()
        self.sh = self.root.winfo_screenheight()
        self.floor_y = self.sh - PET_H - FLOOR_MARGIN           # 站立时窗口左上角 y

        self.canvas = tk.Canvas(self.root, width=PET_W, height=PET_H,
                                bg=TRANSPARENT, highlightthickness=0, bd=0,
                                cursor='hand2')
        self.canvas.pack()

        # 不抢焦点 + 不进任务栏/Alt-Tab（WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW）
        try:
            self.root.update_idletasks()
            hwnd = user32.GetParent(self.root.winfo_id())
            style = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000080)
        except Exception:
            pass

        # ---- 状态 ----
        self.state = 'idle'       # idle / walk / drag / fall / sleep
        self.x = self.sw - PET_W - 24
        self.y = self.floor_y
        self.vx = self.vy = 0.0
        self.dir = random.choice((-1, 1))
        self.t = 0.0              # 全局时钟（秒）
        self.leg_phase = 0.0
        self.squash = 0.0         # 落地挤压量
        self.blink_left = random.uniform(1.5, 4.0)
        self.blinking = 0.0

        # ---- 形象系统：从 sprite_choice.json 加载上次选择，找不到时默认杰瑞鼠 ----
        self._sprite_ctx = SpriteContext()
        chosen = load_sprite_choice() or 'jerry'
        self.sprite = make_sprite(chosen)
        self.sprite_name = self.sprite.name if self.sprite else 'jerry'
        self.idle_timer = random.uniform(2.0, 5.0)
        self.walk_timer = 0.0
        self.chat_timer = random.uniform(20.0, 45.0)
        self.speak_text = None
        self.speak_left = 0.0

        # 蹲跳反应（剪贴板/番茄钟事件触发的原地小跳）
        self.hop_y = 0.0          # 垂直偏移（负值向上）
        self.hop_v = 0.0

        # 睡觉
        self.awake_t = 0.0        # 距上次互动的秒数
        self.sleep_chat = 0.0     # 睡觉话泡计时

        # 拖拽
        self.grab_dx = self.grab_dy = 0
        self.press_t = 0.0
        self.drag_moved = 0.0
        self.hist = []            # 指针轨迹 [(t, x, y)]，用于估算出手速度
        self._last_click_t = 0.0  # 上次单击时刻（双击判定）
        self._click_job = None    # 延迟触发的单击气泡（等待双击窗口）
        self._pending_menu = False  # 双击松手后是否弹快捷菜单
        self._capture_hidden = False  # 截图期间窗口临时移出屏幕（tick 不更新位置）

        # 服务器联动（后台线程轮询，主线程消费事件）
        self.events = []          # 待处理事件 [(kind, payload)]
        self._ev_lock = threading.Lock()
        self.pm_state = None      # 服务器最新番茄钟状态
        self._pm_prev = None      # 上一轮状态（转换检测）
        self._note_seen = 0       # 已读过的 noteAt（一次性通知去重）
        self._clip_last_id = None  # 已读过的最新剪贴板 id
        self.server_ok = False    # 服务器健康状态（轮询线程维护）
        threading.Thread(target=self._poll_worker, daemon=True).start()

        # 右键菜单：Tab 直达项直接平铺 + 宠物设置
        self.menu = tk.Menu(self.root, tearoff=0)
        for label, tab in TOOL_TABS:
            self.menu.add_command(label=label,
                                  command=lambda t=tab: self.open_toolbox(t))
        self.menu.add_separator()
        self.menu.add_command(label='重置位置', command=self.reset_pos)
        self.menu.add_checkbutton(label='开机自启', command=self.toggle_autostart)
        self.update_menu_state()
        # 切换形象子菜单（每次弹出前重建，确保自动发现的图片形象也列出来）
        self.sprite_menu = tk.Menu(self.menu, tearoff=0)
        self._rebuild_sprite_menu()
        self.menu.add_cascade(label='切换形象 →', menu=self.sprite_menu)
        self.menu.add_separator()
        self.menu.add_command(label='退出', command=self.root.destroy)

        # 左键单击快捷菜单：直达工具箱常用功能（每次弹出前重建，顶部动态显示番茄钟倒计时）
        self.quick_menu = tk.Menu(self.root, tearoff=0)

        self.canvas.bind('<Button-1>', self.on_press)
        self.canvas.bind('<Button-2>', self.on_mid_click)   # 中键（滚轮按下）截图
        self.canvas.bind('<Button-3>', self.on_menu)

        # 全局鼠标中键钩子：任意位置按下滚轮中键即触发截图
        self._mid_hook = GlobalMidButtonHook(self.root, lambda: self.on_mid_click(None))

        self.root.geometry(f'{PET_W}x{PET_H}+{int(self.x)}+{int(self.y)}')
        self.last = time.monotonic()
        self.topmost_cnt = 0
        self.tick()

    # ---------------- 事件 ----------------
    def on_press(self, _e):
        now = time.monotonic()
        self.wake()
        self.press_t = now
        self.grab_dx = self.root.winfo_pointerx() - self.x
        self.grab_dy = self.root.winfo_pointery() - self.y
        self.drag_moved = 0.0
        self.hist = [(now, self.root.winfo_pointerx(), self.root.winfo_pointery())]
        # 双击（间隔 <0.32s）→ 松手后弹快捷菜单：取消待定的单击气泡
        if now - self._last_click_t < 0.32:
            if self._click_job is not None:
                try:
                    self.root.after_cancel(self._click_job)
                except Exception:
                    pass
                self._click_job = None
            self._pending_menu = True
        else:
            # 单击延迟触发：给双击留出判定窗口
            if self._click_job is not None:
                try:
                    self.root.after_cancel(self._click_job)
                except Exception:
                    pass
            self._click_job = self.root.after(330, self._single_click)
            self._pending_menu = False
        self._last_click_t = now
        # 双击第二击按住也能继续拖拽（拖走了就不算双击）
        self.state = 'drag'
        self.hop_y = self.hop_v = 0.0

    def _single_click(self):
        self._click_job = None
        if self.state in ('drag', 'fall'):
            return
        left = self.pm_left_sec()
        if left > 0:
            mode = (self.pm_state or {}).get('mode') == 'break'
            m, s = divmod(left, 60)
            self.speak(f'{"☕ 休息中" if mode else "🎯 专注中"} · 剩 {m:02d}:{s:02d}')
        else:
            self.speak(random.choice(PHRASES))

    def wake(self):
        self.awake_t = 0.0
        if self.state == 'sleep':
            self.state = 'idle'
            self.idle_timer = random.uniform(2.0, 6.0)
            self.speak('呼哇…醒啦！')

    def on_mid_click(self, _e):
        """中键（滚轮按下）→ 区域截图（QQ 截图式框选）。

        宠物先溜出屏幕（保证冻结画面里没有自己），然后全屏抓图弹出框选窗：
        拖拽选区域、松开即裁剪入剪贴板；Esc / 右键取消。
        """
        self.wake()
        if self._capture_hidden:
            return
        self.speak('框选截图~')
        self._capture_hidden = True
        self.root.geometry(f'+{self.sw + 200}+0')   # 溜出屏幕
        self.root.after(220, self._start_snip)

    def _start_snip(self):
        try:
            snip_region(self._snip_done)
        except Exception:
            self._snip_done(False)

    def _snip_done(self, ok):
        self._capture_hidden = False               # tick 下一帧把窗口移回原位
        self.speak('截图好啦~ 已在剪贴板' if ok else '已取消截图')

    def hop(self):
        """原地小跳（事件反应）"""
        if self.state in ('drag', 'fall', 'sleep'):
            return
        self.hop_v = -430.0

    def pm_left_sec(self):
        """番茄钟剩余秒数（未运行/状态过期返回 0）"""
        st = self.pm_state or {}
        if not st.get('running'):
            return 0
        if st.get('paused'):
            return max(0, int(st.get('left') or 0))
        ends = st.get('endsAt') or 0
        if ends <= 0:
            return 0
        now_ms = time.time() * 1000
        if ends < now_ms - STALE_MS:   # 页面关闭导致的陈旧状态
            return 0
        return max(0, int((ends - now_ms) / 1000))

    # ---------------- 服务器轮询（后台线程） ----------------
    def _push_event(self, kind, payload=None):
        with self._ev_lock:
            self.events.append((kind, payload))

    def _poll_worker(self):
        while True:
            ok = False
            # 剪贴板：最新一条 id 变化 → 通知
            try:
                with urllib.request.urlopen(SERVER + '/api/clipboard', timeout=2.5) as r:
                    items = json.loads(r.read().decode('utf-8')).get('data') or []
                ok = True
                if items:
                    top = items[0]
                    if self._clip_last_id is not None and top.get('id') != self._clip_last_id:
                        if top.get('type') == 'image':
                            preview = '📋 [截图]'
                        else:
                            txt = (top.get('text') or '').replace('\n', ' ').strip()
                            preview = '📋 ' + (txt[:14] + '…' if len(txt) > 14 else txt or '[空]')
                        self._push_event('clip', preview)
                    self._clip_last_id = top.get('id')
            except Exception:
                pass
            # 番茄钟运行态
            try:
                with urllib.request.urlopen(SERVER + '/api/pet-state', timeout=2.5) as r:
                    st = json.loads(r.read().decode('utf-8')).get('data') or {}
                ok = True
                self._on_pm_state(st)
            except Exception:
                pass
            self.server_ok = ok
            time.sleep(POLL_INTERVAL)

    # ---------------- 打开工具箱（菜单项） ----------------
    def open_toolbox(self, tab):
        """浏览器打开工具箱指定 Tab（URL hash 直达）；服务器未启动时先拉起再打开"""
        url = SERVER + '/#tab-' + tab
        if self.server_ok:
            webbrowser.open(url)
            self.speak('打开工具箱~')
            return
        # 服务器没跑：用 pythonw 无窗口启动 server.py，就绪后自动开浏览器
        self.speak('服务器启动中…')
        base = os.path.dirname(os.path.abspath(__file__))
        exe = sys.executable
        if not exe.lower().endswith('pythonw.exe'):
            cand = os.path.join(os.path.dirname(exe), 'pythonw.exe')
            if os.path.exists(cand):
                exe = cand
        try:
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            subprocess.Popen([exe, os.path.join(base, 'server.py')],
                             cwd=base, creationflags=flags)
        except Exception:
            self.speak('服务器启动失败…')
            return
        threading.Thread(target=self._wait_server_and_open, args=(url,), daemon=True).start()

    def _wait_server_and_open(self, url):
        """后台等服务器就绪（最多 10 秒），成功后开浏览器"""
        for _ in range(20):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(SERVER + '/api/pet-state', timeout=2) as r:
                    if r.status == 200:
                        webbrowser.open(url)
                        return
            except Exception:
                continue
        self._push_event('note', '服务器没起来…检查下？')

    def _on_pm_state(self, st):
        """线程侧：番茄钟状态转换检测（只做数据比较，UI 反应交给主线程）"""
        prev = self._pm_prev
        self.pm_state = st
        if prev is None:                 # 首次：只记录基线，不反应
            self._pm_last_note(st)
            self._pm_prev = st
            return
        # 一次性通知（专注完成等）：noteAt 出现新值即触发
        note_at = st.get('noteAt') or 0
        if st.get('note') and note_at > self._note_seen:
            self._push_event('note', st['note'])
        self._pm_last_note(st)
        # 运行状态转换
        was = (bool(prev.get('running')), bool(prev.get('paused')))
        now_ = (bool(st.get('running')), bool(st.get('paused')))
        if was != now_:
            if now_[0]:
                self._push_event('pm_start', st.get('mode'))
            elif now_[1]:
                self._push_event('pm_pause')
            else:
                self._push_event('pm_stop')
        self._pm_prev = st

    def _pm_last_note(self, st):
        note_at = st.get('noteAt') or 0
        if note_at > self._note_seen:
            self._note_seen = note_at

    def on_menu(self, e):
        # 弹出前重建形象子菜单（自动发现新放的图片素材）
        try:
            self._rebuild_sprite_menu()
        except Exception:
            pass
        try:
            x = e.x_root if e is not None else int(self.x)
            y = e.y_root if e is not None else int(self.y)
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    # ---------------- 双击快捷菜单 ----------------
    def show_quick_menu(self):
        """双击松手后弹出的工具箱快捷菜单（宠物头顶附近，按估算高度防出屏）"""
        self._build_quick_menu()
        x = min(max(int(self.x) + PET_W // 2, 8), self.sw - 8)
        y = int(self.y) + 6
        est_h = 26 * (self.quick_menu.index('end') + 1) + 6   # 粗估菜单高度
        if y + est_h > self.sh:
            y = max(6, self.sh - est_h - 8)
        try:
            self.quick_menu.tk_popup(x, y)
        finally:
            self.quick_menu.grab_release()

    def _build_quick_menu(self):
        """重建快捷菜单：番茄钟运行中顶部显示倒计时快照，主体为工具箱各 Tab 直达项"""
        m = self.quick_menu
        m.delete(0, 'end')
        left = self.pm_left_sec()
        if left > 0:
            mode = (self.pm_state or {}).get('mode') == 'break'
            mm, ss = divmod(left, 60)
            m.add_command(label=f'{"☕ 休息中" if mode else "🎯 专注中"} · 剩 {mm:02d}:{ss:02d}',
                          state='disabled')
            m.add_separator()
        for label, tab in TOOL_TABS:
            m.add_command(label=label, command=lambda t=tab: self.open_toolbox(t))
        m.add_separator()
        m.add_command(label='💬 逗一下', command=lambda: self.speak(random.choice(PHRASES)))

    def reset_pos(self):
        self.wake()
        self.x = self.sw - PET_W - 24
        self.y = self.floor_y
        self.vx = self.vy = 0.0
        self.hop_y = self.hop_v = 0.0
        self.state = 'idle'
        self.idle_timer = random.uniform(2.0, 5.0)

    # ---------------- 开机自启 ----------------
    def toggle_autostart(self):
        on = not autostart_enabled()
        if autostart_set(on) and autostart_enabled() == on:
            self.speak('开机自启已开启' if on else '开机自启已关闭')
        else:
            self.speak('设置失败…')
        self.update_menu_state()

    def update_menu_state(self):
        self.menu.entryconfigure('开机自启', variable=tk.IntVar(value=1 if autostart_enabled() else 0))

    def _rebuild_sprite_menu(self):
        """重建切换形象子菜单：列出所有注册 + 自动发现的形象，当前选中打钩。"""
        self.sprite_menu.delete(0, 'end')
        for name, label, thing in list_sprites():
            var = tk.IntVar(value=1 if name == self.sprite_name else 0)
            self.sprite_menu.add_radiobutton(
                label=label, variable=var, value=1,
                command=lambda n=name: self.set_sprite(n))

    def set_sprite(self, name):
        """切换到指定形象，持久化选择。"""
        if name == self.sprite_name and self.sprite is not None:
            return
        try:
            if self.sprite is not None:
                self.sprite.cleanup()
        except Exception:
            pass
        new_sp = make_sprite(name)
        if new_sp is None:
            return
        self.sprite = new_sp
        self.sprite_name = new_sp.name or name
        save_sprite_choice(self.sprite_name)
        self._rebuild_sprite_menu()
        # 切形象时让宠物说一句话反馈一下
        try:
            self.speak(f'我是 {getattr(new_sp, "label", name)}')
        except Exception:
            pass

    def speak(self, text):
        self.speak_text = text
        self.speak_left = 3.0

    def end_drag(self, now):
        dur = now - self.press_t
        pending = self._pending_menu
        self._pending_menu = False
        if self.drag_moved < 8.0 and dur < 0.35:
            # 单击：气泡由 _single_click 延迟触发；双击：松手后在这里弹快捷菜单
            self.state = 'idle'
            self.idle_timer = random.uniform(2.0, 5.0)
            if pending:
                self.show_quick_menu()
            return
        # 出手速度：取 ~0.1s 前的轨迹点估算
        px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
        self.hist.append((now, px, py))
        vx = vy = 0.0
        for pt, hx, hy in self.hist:
            d = now - pt
            if d > 0.03:
                vx = (px - hx) / d
                vy = (py - hy) / d
                break
        self.vx = max(-MAX_THROW, min(MAX_THROW, vx))
        self.vy = max(-MAX_THROW, min(MAX_THROW, vy))
        if math.hypot(self.vx, self.vy) < 300.0:
            # 轻放：原地停留（可放置在屏幕任意高度，不强制落底）
            self.vx = self.vy = 0.0
            self.state = 'idle'
            self.idle_timer = random.uniform(2.0, 6.0)
        else:
            self.state = 'fall'

    # ---------------- 主循环 ----------------
    def tick(self):
        now = time.monotonic()
        dt = min(0.05, now - self.last)
        self.last = now
        self.t += dt
        try:
            self.update(dt, now)
            self.draw()
        except Exception:
            # after 回调内的异常不会传到 mainloop 外，这里单独留痕
            self._log_crash()
            return
        self.root.after(16, self.tick)

    @staticmethod
    def _log_crash():
        try:
            log = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pet_error.log')
            with open(log, 'a', encoding='utf-8') as f:
                f.write(traceback.format_exc() + '\n')
        except Exception:
            pass

    def update(self, dt, now):
        # 眨眼
        if self.blinking > 0:
            self.blinking -= dt
        else:
            self.blink_left -= dt
            if self.blink_left <= 0:
                self.blinking = 0.13
                self.blink_left = random.uniform(2.0, 5.0)
        # 话泡倒计时 / 挤压回弹 / 清醒计时
        if self.speak_left > 0:
            self.speak_left -= dt
        self.awake_t += dt
        self.squash *= math.exp(-8.0 * dt)

        # ---- 服务器事件反应（主线程消费） ----
        with self._ev_lock:
            events = self.events[:]
            self.events.clear()
        for kind, payload in events:
            self.wake()                      # 有动静就醒
            if kind == 'clip':
                self.speak(payload)
                self.hop()
            elif kind == 'pm_start':
                left = self.pm_left_sec()
                mins = max(1, left // 60) if left else ''
                if payload == 'break':
                    self.speak(f'☕ 休息开始~ {mins}分钟')
                else:
                    self.speak(f'🎯 专注开始！{mins}分钟，加油')
                self.hop()
            elif kind == 'pm_pause':
                self.speak('暂停了？歇口气~')
            elif kind == 'pm_stop':
                self.speak('计时结束啦~')
            elif kind == 'note':
                self.speak(payload)
                self.hop()

        # ---- 小跳物理（原地垂直弹起，回落带轻微挤压） ----
        if self.hop_v != 0.0 or self.hop_y < 0.0:
            self.hop_v += GRAVITY * dt
            self.hop_y += self.hop_v * dt
            if self.hop_y >= 0.0:
                self.hop_y = 0.0
                self.hop_v = 0.0
                self.squash = max(self.squash, 0.10)

        if self.state == 'drag':
            # 窗外松开也能感知（轮询左键状态）
            if not (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
                self.end_drag(now)
                return
            px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
            nx = min(max(px - self.grab_dx, 0), self.sw - PET_W)
            ny = min(max(py - self.grab_dy, 0), self.sh - PET_H)
            self.drag_moved = max(self.drag_moved, abs(nx - self.x) + abs(ny - self.y))
            self.x, self.y = nx, ny
            self.hist.append((now, px, py))
            if len(self.hist) > 12:
                self.hist.pop(0)
        elif self.state == 'fall':
            self.vy += GRAVITY * dt
            self.x += self.vx * dt
            self.y += self.vy * dt
            # 左右墙反弹
            if self.x <= 0:
                self.x = 0
                self.vx = abs(self.vx) * 0.7
            elif self.x >= self.sw - PET_W:
                self.x = self.sw - PET_W
                self.vx = -abs(self.vx) * 0.7
            # 顶部反弹（往上甩）
            if self.y <= 0:
                self.y = 0
                self.vy = abs(self.vy) * 0.5
            # 落地
            if self.y >= self.floor_y:
                self.y = self.floor_y
                if self.vy > 140.0:
                    self.squash = min(0.35, self.vy / 3000.0 + 0.08)
                    self.vy = -self.vy * 0.42
                    self.vx *= 0.75
                else:
                    self.vy = 0.0
                    self.vx *= math.exp(-5.0 * dt)   # 地面摩擦
                    if abs(self.vx) < 25.0:
                        self.vx = 0.0
                        self.state = 'idle'
                        self.idle_timer = random.uniform(2.0, 6.0)
        elif self.state == 'walk':
            self.x += self.dir * WALK_SPEED * dt
            self.leg_phase += dt * 11.0
            self.walk_timer -= dt
            if self.x <= 2 or self.x >= self.sw - PET_W - 2:
                self.dir *= -1
            if self.walk_timer <= 0:
                self.state = 'idle'
                self.idle_timer = random.uniform(2.0, 7.0)
            if self.awake_t > SLEEP_AFTER:   # 走着走着困了
                self.state = 'sleep'
                self.sleep_chat = random.uniform(4.0, 8.0)
        elif self.state == 'sleep':
            # 睡觉：偶尔冒 Zzz 泡泡，不做其他动作
            self.sleep_chat -= dt
            if self.sleep_chat <= 0:
                self.sleep_chat = random.uniform(6.0, 12.0)
                self.speak(random.choice(SLEEP_PHRASES))
        else:  # idle
            self.idle_timer -= dt
            if self.awake_t > SLEEP_AFTER:   # 久无互动 → 入睡
                self.state = 'sleep'
                self.sleep_chat = random.uniform(4.0, 8.0)
            elif self.idle_timer <= 0:
                if random.random() < 0.6:
                    self.state = 'walk'
                    self.dir = random.choice((-1, 1))
                    self.walk_timer = random.uniform(2.0, 6.0)
                else:
                    self.idle_timer = random.uniform(2.0, 6.0)
            self.chat_timer -= dt
            if self.chat_timer <= 0:
                self.chat_timer = random.uniform(25.0, 60.0)
                self.speak(random.choice(PHRASES))

        # 截图期间窗口临时躲到屏幕外，不更新位置（下一帧 _do_capture 复位标志后移回）
        if not self._capture_hidden:
            self.root.geometry(f'+{int(self.x)}+{int(max(0, self.y + self.hop_y))}')
        # 定期刷新置顶（防止被其他置顶窗口压住）
        self.topmost_cnt += 1
        if self.topmost_cnt >= 240:   # ~4s
            self.topmost_cnt = 0
            self.root.attributes('-topmost', True)

    # ---------------- 绘制 ----------------
    def draw(self):
        cv = self.canvas
        cv.delete('all')
        t = self.t
        st = self.state

        # 姿态参数（通用，所有形象共用：bob/l_dy/r_dy/l_swing/r_swing/surprised/sleeping/blink）
        if st == 'walk':
            bob = abs(math.sin(self.leg_phase)) * 2.2       # 走路颠簸
        elif st == 'idle':
            bob = math.sin(t * 2.2) * 1.6                   # 呼吸起伏
        elif st == 'sleep':
            bob = math.sin(t * 1.1) * 2.8                   # 睡觉深呼吸
        else:
            bob = 0.0
        surprised = st in ('drag', 'fall')
        sleeping = st == 'sleep'
        blink = self.blinking > 0 and not sleeping

        # 脚：走路交替抬 / 拖拽下垂晃 / 下落乱蹬
        if st == 'walk':
            l_dy = -max(0.0, math.sin(self.leg_phase)) * 5.0
            r_dy = -max(0.0, -math.sin(self.leg_phase)) * 5.0
        elif st == 'drag':
            l_dy = r_dy = 4.0 + math.sin(t * 14.0) * 3.0
        elif st == 'fall':
            l_dy = math.sin(t * 22.0) * 5.0 - 2.0
            r_dy = -math.sin(t * 22.0) * 5.0 - 2.0
        else:
            l_dy = r_dy = 0.0

        # 手：走路前后交替摆 / 拖拽跟着乱晃 / 下落向上举 / 待机轻贴身前
        if st == 'walk':
            l_swing = math.sin(self.leg_phase) * 10.0
            r_swing = -math.sin(self.leg_phase) * 10.0
        elif st == 'drag':
            l_swing = math.sin(t * 15.0) * 14.0 - 6.0
            r_swing = -math.sin(t * 15.0) * 14.0 + 6.0
        elif st == 'fall':
            l_swing = -26.0 + math.sin(t * 22.0) * 6.0   # 向上举
            r_swing = 26.0 - math.sin(t * 22.0) * 6.0
        else:
            l_swing = -5.0
            r_swing = 5.0

        # 打包姿态上下文交给当前形象绘制（形象特有参数如尾巴/裙摆由 sprite 自己算）
        ctx = self._sprite_ctx
        ctx.t = t
        ctx.state = st
        ctx.leg_phase = self.leg_phase
        ctx.bob = bob
        ctx.l_dy = l_dy
        ctx.r_dy = r_dy
        ctx.l_swing = l_swing
        ctx.r_swing = r_swing
        ctx.sleeping = sleeping
        ctx.blink = blink
        ctx.surprised = surprised
        ctx.squash = self.squash

        # 调用当前形象绘制（110×140 局部坐标系）
        if self.sprite is not None:
            try:
                self.sprite.draw(cv, ctx)
            except Exception:
                # 形象绘制异常时回退到杰瑞鼠，避免主循环崩溃
                try:
                    JerryMouseSprite().draw(cv, ctx)
                except Exception:
                    pass

        # 至此画布上全是角色元素：统一打 tag，整体居中右移并下移到画布下半部分
        cv.addtag_all('body')
        cv.move('body', (PET_W - 110) / 2, BODY_OFF)

        # ---- 话泡（白云气泡：固定画布顶部留白区，单行不挡眼；两行时云尾最多遮耳尖） ----
        if self.speak_left > 0 and self.speak_text:
            text = self.speak_text
            font = ('Microsoft YaHei UI', 10)
            bx, by = 85, 2
            # 先按窗口最大宽度测量文字，确定是否换行及实际高度
            tid = cv.create_text(0, 0, text=text, font=font, width=PET_W - 18)
            tb = cv.bbox(tid)
            cv.delete(tid)
            text_w = tb[2] - tb[0] if tb else 40
            text_h = tb[3] - tb[1] if tb else 14
            # 云身宽度 = 文字宽度 + 左右内边距 50px，最小 80px，最大不超过窗口
            w = max(80, min(text_w + 50, PET_W - 8))
            # 云身高度 = 文字高度 + 上下内边距 10px，最小 22px
            h = max(22, text_h + 10)
            # 云身：大椭圆（白色填充 + 浅灰描边）
            cv.create_oval(bx - w / 2, by, bx + w / 2, by + h,
                           fill='#ffffff', outline='#b8c4ce', width=1.5)
            # 云尾：下方小椭圆（指向角色）
            cv.create_oval(bx - 6, by + h - 4, bx + 6, by + h + 8,
                           fill='#ffffff', outline='#b8c4ce', width=1.5)
            # 云尾连接处：用白色矩形遮住两椭圆交界线，形成一体
            cv.create_rectangle(bx - 5, by + h - 4, bx + 5, by + h,
                                fill='#ffffff', outline='')
            # 文字（垂直居中，超出宽度自动换行）
            cv.create_text(bx, by + h / 2, text=text, font=font,
                           fill='#2d3748', width=w - 10)

        # 落地挤压 / 拖拽拉伸（只作用于角色，以角色脚底中心为锚点）
        body_cx = 55 + (PET_W - 110) / 2
        anchor_y = 136 + BODY_OFF
        if self.squash > 0.01:
            cv.scale('body', body_cx, anchor_y, 1 + self.squash * 0.7, 1 - self.squash)
        elif st == 'drag':
            cv.scale('body', body_cx, anchor_y, 0.97, 1.05)


def main():
    set_dpi_aware()
    try:
        Pet().root.mainloop()
    except Exception:
        # pythonw 无控制台：崩溃原因写入日志便于排查
        log = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pet_error.log')
        with open(log, 'w', encoding='utf-8') as f:
            f.write(traceback.format_exc())
        raise


if __name__ == '__main__':
    main()
