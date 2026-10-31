"""Shared helpers for the Sabbora teacher and student apps.

Screen capture, JPEG encoding, wire protocol, input injection, keyboard
blocking and styling live here so that both programs speak the same language.
"""
import ctypes
import datetime
import io
import json
import os
import re
import struct
import subprocess
import sys
import traceback

from PIL import Image, ImageDraw, ImageGrab

APP_NAME = "Sabbora"
APP_NAME_AR = "سبّورة"
VERSION = "1.2.0"
AUTHOR_EN = "Dr. Mohammed Tawfik"
AUTHOR_AR = "د. محمد توفيق"
AUTHOR_EMAIL = "kmkhol01@gmail.com"
CREDIT_AR = f"تطوير: {AUTHOR_AR} — {AUTHOR_EMAIL}"

WS_PORT = 47000            # teacher WebSocket server (TCP)
DISCOVERY_PORT = 47001     # teacher beacon (UDP broadcast)
BEACON_TAG = "sabbora/1"

# First byte of every binary WebSocket message.
B_BROADCAST = 0x01         # teacher -> student : lecture frame (JPEG)
B_FILE = 0x03              # teacher -> student : file chunk (fid, index, data)
B_THUMB = 0x10             # student -> teacher : thumbnail (JPEG)
B_FRAME = 0x11             # student -> teacher : live high-resolution frame (JPEG)
B_UPLOAD = 0x12            # student -> teacher : assignment chunk (fid, index, data)

FILE_CHUNK = 256 * 1024
FILE_WINDOW = 8            # chunks in flight per student
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

IS_WIN = sys.platform.startswith("win")

# --------------------------------------------------------------------------
# Language: every UI string is written as L(arabic, english)
# --------------------------------------------------------------------------
LANG = "ar"


def set_lang(lang):
    global LANG
    LANG = "en" if lang == "en" else "ar"


def L(ar, en):
    return ar if LANG == "ar" else en


def system_lang():
    try:
        from PyQt5.QtCore import QLocale
        return "ar" if QLocale.system().language() == QLocale.Arabic else "en"
    except Exception:
        return "ar"


def load_lang(app_key):
    """Read the saved language for 'Teacher' or 'Student' before any UI is built."""
    from PyQt5.QtCore import QSettings
    set_lang(QSettings("Sabbora", app_key).value("lang", system_lang(), str))
    return LANG


def save_lang(app_key, lang):
    from PyQt5.QtCore import QSettings
    QSettings("Sabbora", app_key).setValue("lang", lang)


def app_title():
    return L(APP_NAME_AR, APP_NAME)


def credit():
    return L(f"تطوير: {AUTHOR_AR} — {AUTHOR_EMAIL}", f"Developed by {AUTHOR_EN} — {AUTHOR_EMAIL}")


def relaunch():
    """Start a fresh copy of this program with the same arguments."""
    from PyQt5.QtCore import QProcess
    if getattr(sys, "frozen", False):
        return QProcess.startDetached(sys.executable, sys.argv[1:])
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return QProcess.startDetached(exe, [os.path.abspath(sys.argv[0])] + sys.argv[1:])


# --------------------------------------------------------------------------
# Protocol helpers
# --------------------------------------------------------------------------
def jdump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def jload(text):
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def pack_chunk(kind, fid, index, data):
    return bytes((kind,)) + struct.pack(">II", fid, index) + data


def pack_file_chunk(fid, index, data):
    return pack_chunk(B_FILE, fid, index, data)


def unpack_file_chunk(body):
    """body = message without the leading kind byte."""
    if len(body) < 8:
        return None
    fid, index = struct.unpack(">II", body[:8])
    return fid, index, body[8:]


def clean_ip(text):
    text = (text or "").strip()
    if text.startswith("::ffff:"):
        text = text[7:]
    return text


def parse_hostport(text, default_port=WS_PORT):
    """'host', 'host:port' or '[v6]:port' -> (host, port) or None."""
    text = (text or "").strip()
    if not text:
        return None
    text = re.sub(r"^wss?://", "", text).rstrip("/")
    m = re.match(r"^\[([^\]]+)\](?::(\d+))?$", text)
    if m:
        return m.group(1), int(m.group(2) or default_port)
    if text.count(":") == 1:
        host, port = text.split(":")
        if not port.isdigit():
            return None
        return host.strip(), int(port)
    return text, default_port


def safe_filename(name):
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return (name or "file")[:180]


def unique_path(folder, name):
    base, ext = os.path.splitext(name)
    path = os.path.join(folder, name)
    n = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return path


def now_text():
    return datetime.datetime.now().strftime("%H:%M:%S")


# --------------------------------------------------------------------------
# Windows plumbing (private WinDLL instances so argtypes never leak)
# --------------------------------------------------------------------------
if IS_WIN:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class _RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                    ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    class _KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    _MONENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                      ctypes.POINTER(_RECT), wintypes.LPARAM)
    _HOOKPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    _user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(_RECT), _MONENUMPROC, wintypes.LPARAM]
    _user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    _user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ULONG_PTR]
    _user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ULONG_PTR]
    _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    _user32.MapVirtualKeyW.restype = wintypes.UINT
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    _user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    _user32.CallNextHookEx.restype = wintypes.LPARAM
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    _user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def enable_dpi_awareness():
    """Physical pixels everywhere: capture, cursor and SetCursorPos agree."""
    if not IS_WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Screen capture
# --------------------------------------------------------------------------
def list_monitors():
    """[(x, y, w, h, primary), ...] in physical virtual-desktop pixels, primary first."""
    mons = []
    if IS_WIN:
        def _cb(hmon, hdc, rect, lparam):
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if _user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                r = mi.rcMonitor
                mons.append((r.left, r.top, r.right - r.left, r.bottom - r.top, bool(mi.dwFlags & 1)))
            return True
        callback = _MONENUMPROC(_cb)
        _user32.EnumDisplayMonitors(None, None, callback, 0)
    if not mons:
        try:
            w, h = ImageGrab.grab().size
        except Exception:
            w, h = 1920, 1080
        mons = [(0, 0, w, h, True)]
    mons.sort(key=lambda m: (not m[4], m[0], m[1]))
    return mons


def grab_monitor(mon, layered=False):
    """layered=True also captures layered windows (pen overlay, menus, tooltips)."""
    x, y, w, h, _primary = mon
    if IS_WIN:
        if x == 0 and y == 0:
            return ImageGrab.grab(bbox=(0, 0, w, h), include_layered_windows=layered)
        return ImageGrab.grab(bbox=(x, y, x + w, y + h), include_layered_windows=layered, all_screens=True)
    return ImageGrab.grab()


def cursor_pos(mon=None):
    if not IS_WIN:
        return None
    pt = wintypes.POINT()
    if not _user32.GetCursorPos(ctypes.byref(pt)):
        return None
    if mon is not None:
        x, y, w, h, _ = mon
        if not (x <= pt.x < x + w and y <= pt.y < y + h):
            return None
    return pt.x, pt.y


def draw_pointer(img, mon, pos):
    """Draw a laser-pointer dot where the teacher's mouse is."""
    if not pos:
        return
    cx, cy = pos[0] - mon[0], pos[1] - mon[1]
    if not (0 <= cx < img.width and 0 <= cy < img.height):
        return
    r = max(7, img.width // 150)
    d = ImageDraw.Draw(img)
    d.ellipse((cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3), fill=(255, 255, 255))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(226, 40, 40))


def downscale(img, max_width):
    if max_width and img.width > max_width:
        h = max(1, round(img.height * max_width / img.width))
        img = img.resize((max_width, h), Image.Resampling.BILINEAR)
    return img


def encode_jpeg(img, max_width=0, quality=70, sharp=False):
    img = downscale(img, max_width)
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=int(quality), subsampling=0 if sharp else 2)
    return buf.getvalue()


_QT_JPEG = None


def jpeg_pixmap(data):
    """JPEG bytes -> QPixmap. Uses Qt's JPEG plugin when the Qt build has one,
    otherwise decodes with Pillow (some PyQt5 builds ship without qjpeg)."""
    global _QT_JPEG
    from PyQt5.QtGui import QImage, QImageReader, QPixmap
    if _QT_JPEG is None:
        _QT_JPEG = b"jpeg" in [bytes(f) for f in QImageReader.supportedImageFormats()]
    pm = QPixmap()
    if _QT_JPEG and pm.loadFromData(data, "JPG"):
        return pm
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
    except Exception:
        return None
    raw = img.tobytes("raw", "RGB")
    qimg = QImage(raw, img.width, img.height, 3 * img.width, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg)


def exclude_from_capture(widget, on=True):
    """Hide a top-level window from screen capture (Windows 10 2004+)."""
    if not IS_WIN:
        return False
    try:
        hwnd = int(widget.winId())
        return bool(_user32.SetWindowDisplayAffinity(hwnd, 0x11 if on else 0))
    except Exception:
        return False


# --------------------------------------------------------------------------
# Remote input
# --------------------------------------------------------------------------
_EXTENDED_VK = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E,
                0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5}


class InputInjector:
    """Moves the mouse and presses keys on this computer for the teacher."""
    _BTN = {"l": (0x0002, 0x0004), "r": (0x0008, 0x0010), "m": (0x0020, 0x0040)}

    def __init__(self):
        self._pyn = None
        if not IS_WIN:
            try:
                from pynput import keyboard, mouse
                self._pyn = (mouse.Controller(), keyboard.Controller(), mouse.Button)
            except Exception:
                self._pyn = None

    @property
    def available(self):
        return IS_WIN or self._pyn is not None

    def move_norm(self, mon, nx, ny):
        x0, y0, w, h, _ = mon
        nx = min(max(float(nx), 0.0), 1.0)
        ny = min(max(float(ny), 0.0), 1.0)
        x = x0 + int(round(nx * (w - 1)))
        y = y0 + int(round(ny * (h - 1)))
        if IS_WIN:
            _user32.SetCursorPos(x, y)
        elif self._pyn:
            self._pyn[0].position = (x, y)

    def button(self, b, down):
        if IS_WIN:
            flags = self._BTN.get(b, self._BTN["l"])
            _user32.mouse_event(flags[0] if down else flags[1], 0, 0, 0, 0)
        elif self._pyn:
            btn = {"l": self._pyn[2].left, "r": self._pyn[2].right, "m": self._pyn[2].middle}.get(b, self._pyn[2].left)
            (self._pyn[0].press if down else self._pyn[0].release)(btn)

    def wheel(self, delta):
        if IS_WIN:
            _user32.mouse_event(0x0800, 0, 0, int(delta) & 0xFFFFFFFF, 0)
        elif self._pyn:
            self._pyn[0].scroll(0, int(delta) // 120)

    def key(self, vk, down, text=""):
        if IS_WIN:
            if vk:
                vk &= 0xFF
                scan = _user32.MapVirtualKeyW(vk, 0) & 0xFF
                flags = (0x0001 if vk in _EXTENDED_VK else 0) | (0 if down else 0x0002)
                _user32.keybd_event(vk, scan, flags, 0)
            elif text and down:
                self._unicode(text)
        elif self._pyn and text and down:
            self._pyn[1].type(text)

    @staticmethod
    def _unicode(text):
        units = text.encode("utf-16-le")
        for i in range(0, len(units), 2):
            code = units[i] | (units[i + 1] << 8)
            for up in (0, 0x0002):
                inp = _INPUT(type=1)
                inp.u.ki = _KEYBDINPUT(0, code, 0x0004 | up, 0, 0)
                _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


class KeyboardBlocker:
    """Low-level keyboard hook that swallows the student's keys (Win, Alt+Tab,
    Alt+F4 ...) while the screen is locked. Keys injected by the teacher's
    remote control still pass. Ctrl+Alt+Del cannot be blocked by design."""

    def __init__(self):
        self._hook = None
        self._proc = None

    @property
    def active(self):
        return self._hook is not None

    def start(self):
        if not IS_WIN or self._hook:
            return
        def proc(n_code, w_param, l_param):
            if n_code == 0:
                info = ctypes.cast(l_param, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                if not info.flags & 0x10:      # LLKHF_INJECTED
                    return 1
            return _user32.CallNextHookEx(None, n_code, w_param, l_param)
        self._proc = _HOOKPROC(proc)
        self._hook = _user32.SetWindowsHookExW(13, self._proc, _kernel32.GetModuleHandleW(None), 0) or None

    def stop(self):
        if self._hook:
            _user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        self._proc = None


def mac_address():
    import uuid
    node = uuid.getnode()
    return ":".join(f"{(node >> s) & 0xFF:02X}" for s in range(40, -1, -8))


def wol_packet(mac):
    digits = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(digits) != 12:
        return None
    return b"\xff" * 6 + bytes.fromhex(digits) * 16


def send_wake_on_lan(mac, broadcasts=("255.255.255.255",)):
    """Magic packet on UDP 9 and 7; the PC must have WoL enabled in BIOS/NIC."""
    import socket
    pkt = wol_packet(mac)
    if not pkt:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for addr in broadcasts:
            for port in (9, 7):
                try:
                    s.sendto(pkt, (addr, port))
                except OSError:
                    pass
    return True


# --------------------------------------------------------------------------
# Window sharing (one window instead of the whole screen)
# --------------------------------------------------------------------------
if IS_WIN:
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    try:
        _dwmapi = ctypes.WinDLL("dwmapi")
        _dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    except OSError:
        _dwmapi = None

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    _ENUMWINDOWSPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_ENUMWINDOWSPROC, wintypes.LPARAM]
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
    _user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                 ctypes.POINTER(_BITMAPINFOHEADER), wintypes.UINT]


def _window_pid(hwnd):
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _process_name(pid):
    handle = _kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    size = wintypes.DWORD(1024)
    path = ctypes.create_unicode_buffer(1024)
    ok = _kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size))
    _kernel32.CloseHandle(handle)
    return os.path.basename(path.value) if ok else ""


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _cloaked(hwnd):
    if _dwmapi is None:
        return False
    val = wintypes.DWORD()
    _dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(val), ctypes.sizeof(val))   # DWMWA_CLOAKED
    return bool(val.value)


def is_window(hwnd):
    return bool(IS_WIN and hwnd and _user32.IsWindow(hwnd))


def window_rect(hwnd):
    r = _RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r.left, r.top, r.right - r.left, r.bottom - r.top, False


def list_windows():
    """Visible application windows: [{'hwnd', 'title', 'proc', 'cls'}]; own windows excluded."""
    if not IS_WIN:
        return []
    out, me = [], os.getpid()

    def _cb(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd) or _user32.GetWindowLongW(hwnd, -20) & 0x80:   # WS_EX_TOOLWINDOW
            return True
        n = _user32.GetWindowTextLengthW(hwnd)
        if n == 0 or _cloaked(hwnd):
            return True
        pid = _window_pid(hwnd)
        if pid == me:
            return True
        rect = window_rect(hwnd)
        if not rect or rect[2] < 120 or rect[3] < 80:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        out.append({"hwnd": int(hwnd), "title": buf.value, "proc": _process_name(pid), "cls": _class_name(hwnd)})
        return True

    _user32.EnumWindows(_ENUMWINDOWSPROC(_cb), 0)
    return out


def find_powerpoint():
    """The running slide show if there is one, otherwise the PowerPoint editor window."""
    best = None
    for w in list_windows():
        if w["proc"].lower() != "powerpnt.exe":
            continue
        if w["cls"] == "screenClass":           # slide show window
            return w["hwnd"]
        if w["cls"] == "PPTFrameClass" and best is None:
            best = w["hwnd"]
    return best


def grab_window(hwnd):
    """(image, rect) of one window even when other windows cover it; None if minimised."""
    if not is_window(hwnd) or _user32.IsIconic(hwnd):
        return None
    rect = window_rect(hwnd)
    if not rect or rect[2] <= 0 or rect[3] <= 0:
        return None
    w, h = rect[2], rect[3]
    screen_dc = _user32.GetDC(None)
    mem_dc = _gdi32.CreateCompatibleDC(screen_dc)
    bmp = _gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    old = _gdi32.SelectObject(mem_dc, bmp)
    try:
        _user32.PrintWindow(hwnd, mem_dc, 2)          # PW_RENDERFULLCONTENT: Office, browsers, DirectX
        bmi = _BITMAPINFOHEADER(biSize=ctypes.sizeof(_BITMAPINFOHEADER), biWidth=w, biHeight=-h,
                                biPlanes=1, biBitCount=32, biCompression=0)
        buf = ctypes.create_string_buffer(w * h * 4)
        _gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    finally:
        _gdi32.SelectObject(mem_dc, old)
        _gdi32.DeleteObject(bmp)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(None, screen_dc)
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    vis = visible_rect(hwnd)                       # drop the invisible resize border
    if vis and (vis[2], vis[3]) != (w, h):
        dx, dy = vis[0] - rect[0], vis[1] - rect[1]
        img = img.crop((dx, dy, dx + vis[2], dy + vis[3]))
        rect = vis
    if img.getbbox() is None and _user32.IsWindowVisible(hwnd):
        # a few GPU windows refuse PrintWindow: use the visible screen area instead
        img = ImageGrab.grab(bbox=(rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]), all_screens=True)
    return img, rect


def visible_rect(hwnd):
    """Window bounds without the invisible border (DWMWA_EXTENDED_FRAME_BOUNDS)."""
    if _dwmapi is None:
        return None
    r = _RECT()
    if _dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        return None
    if r.right <= r.left or r.bottom <= r.top:
        return None
    return r.left, r.top, r.right - r.left, r.bottom - r.top, False


def grab_window_area(hwnd, layered=True):
    """Screen pixels where the window is (used while the pen overlay is open)."""
    rect = visible_rect(hwnd) or window_rect(hwnd)
    if not rect:
        return None
    x, y, w, h, _ = rect
    return ImageGrab.grab(bbox=(x, y, x + w, y + h), include_layered_windows=layered, all_screens=True), rect


def monitor_of_rect(rect):
    """The monitor that contains the centre of a rect (falls back to the primary)."""
    mons = list_monitors()
    cx, cy = rect[0] + rect[2] // 2, rect[1] + rect[3] // 2
    for m in mons:
        if m[0] <= cx < m[0] + m[2] and m[1] <= cy < m[1] + m[3]:
            return m
    return mons[0]


def foreground_window():
    """(process name, window title) of the window the user is working in."""
    if not IS_WIN:
        return "", ""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    n = _user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32.GetWindowTextW(hwnd, buf, n + 1)
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ""
    handle = _kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        size = wintypes.DWORD(1024)
        path = ctypes.create_unicode_buffer(1024)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            name = os.path.basename(path.value)
        _kernel32.CloseHandle(handle)
    return name, buf.value


_PROTECTED = {"explorer.exe", "winlogon.exe", "csrss.exe", "lsass.exe", "svchost.exe", "services.exe",
              "smss.exe", "wininit.exe", "dwm.exe", "sabborastudent.exe", "system", "registry"}


def kill_program(name):
    """Close every running copy of a program by its executable name."""
    name = os.path.basename((name or "").strip().strip('"'))
    if IS_WIN and name and "." not in name:
        name += ".exe"
    if not name or name.lower() in _PROTECTED:
        return False
    try:
        if IS_WIN:
            subprocess.Popen(["taskkill", "/IM", name, "/F", "/T"], creationflags=0x08000000,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["pkill", "-f", name])
        return True
    except OSError:
        return False


def run_program(command):
    """Start a program, document or folder on this computer."""
    command = (command or "").strip()
    if not command:
        return False
    try:
        if IS_WIN and os.path.exists(command.strip('"')):
            os.startfile(command.strip('"'))
        else:
            subprocess.Popen(command, shell=True, creationflags=0x08000000 if IS_WIN else 0)
        return True
    except OSError:
        return False


def power_action(action):
    if IS_WIN:
        cmds = {"shutdown": ["shutdown", "/s", "/t", "10"],
                "restart": ["shutdown", "/r", "/t", "10"],
                "logoff": ["shutdown", "/l"]}
    elif sys.platform == "darwin":
        cmds = {"shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'],
                "restart": ["osascript", "-e", 'tell app "System Events" to restart'],
                "logoff": ["osascript", "-e", 'tell app "System Events" to log out']}
    else:
        cmds = {"shutdown": ["systemctl", "poweroff"], "restart": ["systemctl", "reboot"],
                "logoff": ["loginctl", "terminate-session", os.environ.get("XDG_SESSION_ID", "")]}
    cmd = cmds.get(action)
    if not cmd:
        return False
    try:
        subprocess.Popen(cmd, creationflags=0x08000000 if IS_WIN else 0)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# Logging, icon, style
# --------------------------------------------------------------------------
def data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def install_excepthook(tag):
    """PyQt5 aborts on an exception inside a slot; log it and keep running."""
    log_path = os.path.join(data_dir(), f"{tag}.log")

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}")
        except OSError:
            pass
        sys.__stderr__ and sys.__stderr__.write(text)

    sys.excepthook = hook
    return log_path


def run_selftest(tag):
    """`--selftest`: check Qt, WebSockets (loopback only), capture and JPEG on
    this PC without a GUI. Result -> %LOCALAPPDATA%/Sabbora/selftest_<tag>.txt
    and the exit code (0 = OK)."""
    import time
    from PyQt5.QtCore import QCoreApplication, QUrl
    from PyQt5.QtNetwork import QHostAddress
    from PyQt5.QtWebSockets import QWebSocket, QWebSocketServer

    lines, ok = [f"{APP_NAME} {VERSION} selftest ({tag})"], True

    def check(name, fn):
        nonlocal ok
        try:
            lines.append(f"OK   {name}: {fn()}")
        except Exception as exc:
            ok = False
            lines.append(f"FAIL {name}: {exc!r}")

    check("monitors", list_monitors)
    check("capture+jpeg", lambda: len(jpeg_pixmap(encode_jpeg(grab_monitor(list_monitors()[0]), 640, 60))
                                       .toImage().bits().asstring(4) or b"") == 4)

    def ws_roundtrip():
        srv = QWebSocketServer("t", QWebSocketServer.NonSecureMode)
        if not srv.listen(QHostAddress.LocalHost, 0):
            raise RuntimeError("listen failed")
        got = []
        srv.newConnection.connect(lambda: (lambda s: (got.append(s), s.textMessageReceived.connect(
            lambda t: s.sendTextMessage(t + "!"))))(srv.nextPendingConnection()))
        cli, reply = QWebSocket(), []
        cli.connected.connect(lambda: cli.sendTextMessage("ping"))
        cli.textMessageReceived.connect(reply.append)
        cli.open(QUrl(f"ws://127.0.0.1:{srv.serverPort()}/"))
        end = time.monotonic() + 5
        while not reply and time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        cli.close()
        srv.close()
        if reply != ["ping!"]:
            raise RuntimeError(f"no echo {reply}")
        return "echo ok"

    check("websocket", ws_roundtrip)

    def icon_font():
        from . import icons
        if icons.qta is None or icons.make("lock").isNull():
            raise RuntimeError("icon font missing")
        return "mdi6 ok"

    check("icons", icon_font)
    lines.append("RESULT: " + ("PASS" if ok else "FAIL"))
    with open(os.path.join(data_dir(), f"selftest_{tag}.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 0 if ok else 1


def app_icon(accent="#F2A541"):
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#9A6A3A"))
        p.drawRoundedRect(QRectF(s * .04, s * .10, s * .92, s * .70), s * .10, s * .10)
        p.setBrush(QColor("#1E4D3A"))
        p.drawRoundedRect(QRectF(s * .11, s * .17, s * .78, s * .56), s * .06, s * .06)
        pen = QPen(QColor("#F4F1E8"))
        pen.setWidthF(max(1.0, s * .055))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(s * .20, s * .62), QPointF(s * .36, s * .44),
                                  QPointF(s * .50, s * .54), QPointF(s * .70, s * .30)]))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(accent))
        p.drawEllipse(QPointF(s * .70, s * .30), s * .07, s * .07)
        p.setBrush(QColor("#9A6A3A"))
        p.drawRect(QRectF(s * .30, s * .80, s * .07, s * .14))
        p.drawRect(QRectF(s * .63, s * .80, s * .07, s * .14))
        p.end()
        icon.addPixmap(pm)
    return icon


THEMES = {
    # Modern: deep ocean header, teal actions, warm amber accents (default)
    "modern": {
        "name_ar": "عصري", "name_en": "Modern",
        "hdr1": "#0B3B5C", "hdr2": "#0E7C86", "hdr_text": "#FFFFFF", "hdr_muted": "#BFE3EA",
        "info": "#082C45", "accent": "#FBBF24",
        "bg": "#F3F6FA", "card": "#FFFFFF", "border": "#DCE3EC", "input_border": "#C9D3DF",
        "text": "#0F172A", "muted": "#64748B", "title": "#0B3B5C",
        "primary": "#0E7C86", "primary_hover": "#0A6670", "primary_soft": "#DDF4F4",
        "danger": "#E11D48", "danger_hover": "#BE123C",
        "warn": "#F59E0B", "warn_hover": "#D97706", "warn_text": "#1F1300",
        "ok": "#059669", "err": "#DC2626", "pick": "#7C3AED", "pick_soft": "#F3EEFF",
        "status": "#E8EEF5", "icon": "#334155", "disabled": "#EEF2F6", "disabled_text": "#94A3B8",
        "bar": "#0B3B5C", "bar_btn": "#14527A", "bar_btn_border": "#2A6E96",
        "thumb_bg": "#111827", "lock1": "#0B3B5C", "lock2": "#06202F",
    },
    # Classic: the original chalkboard green
    "classic": {
        "name_ar": "كلاسيكي أخضر", "name_en": "Classic green",
        "hdr1": "#1E4D3A", "hdr2": "#2E6A50", "hdr_text": "#FFFFFF", "hdr_muted": "#CFE3D8",
        "info": "#163A2C", "accent": "#F2C14E",
        "bg": "#F3F6F4", "card": "#FFFFFF", "border": "#D3DCD8", "input_border": "#C6D1CC",
        "text": "#1F2A26", "muted": "#5E6B66", "title": "#1E4D3A",
        "primary": "#2E7D5B", "primary_hover": "#24684A", "primary_soft": "#DCEFE5",
        "danger": "#C0392B", "danger_hover": "#A63024",
        "warn": "#F2A541", "warn_hover": "#E0932F", "warn_text": "#2B1B00",
        "ok": "#1E7A4F", "err": "#B03A2E", "pick": "#8E44AD", "pick_soft": "#F6EEFB",
        "status": "#E6ECE9", "icon": "#2F3E38", "disabled": "#EEF1EF", "disabled_text": "#9AA6A1",
        "bar": "#1E4D3A", "bar_btn": "#2E6A50", "bar_btn_border": "#3F8A68",
        "thumb_bg": "#18221E", "lock1": "#163A2C", "lock2": "#0B1C15",
    },
    # Dark: easy on the eyes in a dim lab
    "dark": {
        "name_ar": "داكن", "name_en": "Dark",
        "hdr1": "#020617", "hdr2": "#0F766E", "hdr_text": "#F1F5F9", "hdr_muted": "#99C9C4",
        "info": "#0B1220", "accent": "#FBBF24",
        "bg": "#0F172A", "card": "#1E293B", "border": "#334155", "input_border": "#475569",
        "text": "#E2E8F0", "muted": "#94A3B8", "title": "#5EEAD4",
        "primary": "#14B8A6", "primary_hover": "#0D9488", "primary_soft": "#134E4A",
        "danger": "#F43F5E", "danger_hover": "#E11D48",
        "warn": "#FBBF24", "warn_hover": "#F59E0B", "warn_text": "#1F1300",
        "ok": "#34D399", "err": "#F87171", "pick": "#A78BFA", "pick_soft": "#2E1065",
        "status": "#111827", "icon": "#CBD5E1", "disabled": "#1F2937", "disabled_text": "#64748B",
        "bar": "#020617", "bar_btn": "#1E293B", "bar_btn_border": "#334155",
        "thumb_bg": "#020617", "lock1": "#0F172A", "lock2": "#020617",
    },
}
THEME = "modern"


def set_theme(name):
    global THEME
    THEME = name if name in THEMES else "modern"


def T(key):
    """Colour token of the current theme."""
    return THEMES[THEME][key]


STYLE = """
QWidget { font-family: 'Segoe UI', 'Tahoma'; font-size: 10pt; color: $text; }
QMainWindow, QDialog, #Page { background: $bg; }
QScrollArea, QScrollArea > QWidget > QWidget { background: $bg; border: none; }
#Header { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $hdr1, stop:1 $hdr2); }
#Header QLabel { color: $hdr_text; background: transparent; }
#Brand { font-size: 18pt; font-weight: 700; }
#Credit { color: $hdr_muted; font-size: 9pt; }
#InfoBox { background: $info; border-radius: 12px; }
#InfoBox QLabel { color: $hdr_text; }
#Big { font-size: 17pt; font-weight: 800; color: $accent; letter-spacing: 2px; }
#Title { font-size: 15pt; font-weight: 700; color: $title; }
#Section { font-weight: 700; color: $title; }
#Muted { color: $muted; }
#Ok { color: $ok; font-weight: 600; }
#Err { color: $err; font-weight: 600; }
QLineEdit, QComboBox, QSpinBox { background: $card; color: $text; border: 1px solid $input_border; border-radius: 8px; padding: 6px 9px; selection-background-color: $primary; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid $primary; }
QComboBox QAbstractItemView { background: $card; color: $text; selection-background-color: $primary_soft; selection-color: $text; }
QPushButton, QToolButton { background: $card; color: $text; border: 1px solid $input_border; border-radius: 9px; padding: 7px 13px; }
QPushButton:hover, QToolButton:hover { background: $primary_soft; border-color: $primary; }
QPushButton:pressed { background: $primary_soft; }
QPushButton:checked { background: $primary; color: #FFFFFF; border-color: $primary; }
QPushButton:disabled { color: $disabled_text; background: $disabled; border-color: $border; }
QPushButton#Primary { background: $primary; color: #FFFFFF; border: none; font-weight: 600; }
QPushButton#Primary:hover { background: $primary_hover; }
QPushButton#Danger { background: $danger; color: #FFFFFF; border: none; font-weight: 600; }
QPushButton#Danger:hover { background: $danger_hover; }
QPushButton#Warn { background: $warn; color: $warn_text; border: none; font-weight: 600; }
QPushButton#Warn:hover { background: $warn_hover; }
QPushButton#HeaderBtn { background: rgba(255,255,255,0.14); color: $hdr_text; border: 1px solid rgba(255,255,255,0.35); }
QPushButton#HeaderBtn:hover { background: rgba(255,255,255,0.26); }
QPushButton::menu-indicator { subcontrol-position: center $MENU_SIDE; width: 0px; }
QGroupBox { font-weight: 700; color: $title; border: 1px solid $border; border-radius: 12px; margin-top: 15px; padding: 12px 8px 8px 8px; background: $card; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top $TITLE_SIDE; padding: 0 8px; color: $title; }
QCheckBox { color: $text; spacing: 6px; }
QListWidget { background: $card; color: $text; border: 1px solid $border; border-radius: 10px; }
QListWidget::item { padding: 6px; border-bottom: 1px solid $border; }
QListWidget::item:selected { background: $primary_soft; color: $text; }
QMenu { background: $card; color: $text; border: 1px solid $border; padding: 4px; }
QMenu::item { padding: 6px 22px 6px 22px; border-radius: 6px; }
QMenu::item:selected { background: $primary_soft; color: $text; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }
QFrame#Tile { background: $card; border: 1px solid $border; border-radius: 12px; }
QFrame#Tile[sel="true"] { border: 2px solid $primary; background: $primary_soft; }
QFrame#Tile[hand="true"] { border: 2px solid $warn; }
QFrame#Tile[pick="true"] { border: 3px solid $pick; background: $pick_soft; }
QProgressBar { border: 1px solid $border; border-radius: 7px; background: $bg; text-align: center; color: $text; height: 20px; }
QProgressBar::chunk { background: $primary; border-radius: 6px; }
QSlider::groove:horizontal { height: 6px; background: $border; border-radius: 3px; }
QSlider::handle:horizontal { background: $primary; width: 16px; margin: -6px 0; border-radius: 8px; }
QSplitter::handle { background: transparent; }
#Bar { background: $bar; border-radius: 14px; border: 1px solid $bar_btn_border; }
#Bar QLabel { color: #FFFFFF; font-weight: 600; background: transparent; }
#Bar QPushButton { background: $bar_btn; color: #FFFFFF; border: 1px solid $bar_btn_border; padding: 5px 10px; }
#Bar QPushButton:hover { background: $primary; }
#Bar QPushButton:checked { background: $warn; color: $warn_text; }
QStatusBar { background: $status; color: $muted; }
QToolTip { background: $card; color: $text; border: 1px solid $border; padding: 4px; }
"""


def style():
    from string import Template
    tokens = dict(THEMES[THEME])
    tokens["TITLE_SIDE"] = "right" if LANG == "ar" else "left"
    tokens["MENU_SIDE"] = "left" if LANG == "ar" else "right"
    return Template(STYLE).substitute(tokens)


def load_prefs(app_key):
    """Language and theme, read before any widget is built."""
    from PyQt5.QtCore import QSettings
    s = QSettings("Sabbora", app_key)
    set_lang(s.value("lang", system_lang(), str))
    set_theme(s.value("theme", "modern", str))


def save_theme(app_key, name):
    from PyQt5.QtCore import QSettings
    QSettings("Sabbora", app_key).setValue("theme", name)


def apply_theme(name, app_key=None):
    """Switch theme live: stylesheet + icon colours."""
    from PyQt5.QtWidgets import QApplication
    set_theme(name)
    if app_key:
        save_theme(app_key, name)
    QApplication.instance().setStyleSheet(style())
    from . import icons
    icons.refresh_all()


def layout_direction():
    from PyQt5.QtCore import Qt
    return Qt.RightToLeft if LANG == "ar" else Qt.LeftToRight
