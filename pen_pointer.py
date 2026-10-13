# coding: utf-8
"""用 Windows 的 WM_POINTER 拿压感 —— 绕开 Wacom 驱动，不装任何东西。

为什么走这条路：WinTab 在这台机器上实测坏了（见 wintab.py），而 PyPI 连不上装不了 Qt。
WM_POINTER 是 Windows 8+ 系统自带的一套，笔、触摸、鼠标都归它管，
`GetPointerPenInfo` 直接给压感/倾斜，和哪家驱动无关。

代价（必须记住）：`EnableMouseInPointer(TRUE)` 是**进程级**的，它会把**鼠标输入也变成
WM_POINTER 消息**，而 Tk 不认这些消息。所以必须把 pointer 消息再翻译成
WM_MOUSEMOVE/WM_LBUTTONDOWN/UP 转发回去，否则鼠标和笔会一起失灵。

**关于"消息到底发给哪个窗口"**：pointer 消息默认投给指针底下的那个窗口（一般是画布）。
但只要有窗口抓着鼠标捕获（SetCapture），消息就会被转给抓捕获的窗口 —— 实测那可能是
**顶层窗口**而不是画布。所以这里同时挂画布和顶层两个窗口过程，并且记录
`hwndTarget`，出问题时一眼能看出消息被谁截走了。
"""
import collections
import ctypes
from ctypes import (WINFUNCTYPE, POINTER, Structure, byref, c_int, c_long,
                    c_size_t, c_ssize_t, c_uint, c_ulonglong, c_void_p)

WM_POINTERUPDATE, WM_POINTERDOWN, WM_POINTERUP = 0x0245, 0x0246, 0x0247
WM_POINTERENTER, WM_POINTERLEAVE = 0x0249, 0x024A
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
GWLP_WNDPROC = -4
MK_LBUTTON = 0x0001
PT_PEN = 3
PT_NAME = {2: "touch", 3: "pen", 4: "mouse"}
POINTER_FLAG_FIRSTBUTTON = 0x00000010
PEN_MASK_PRESSURE = 0x0001
POINTER_MSGS = (WM_POINTERUPDATE, WM_POINTERDOWN, WM_POINTERUP,
                WM_POINTERENTER, WM_POINTERLEAVE)
_MSG_NAME = {WM_POINTERUPDATE: "UPDATE", WM_POINTERDOWN: "DOWN", WM_POINTERUP: "UP",
             WM_POINTERENTER: "ENTER", WM_POINTERLEAVE: "LEAVE"}

LRESULT, WPARAM, LPARAM = c_ssize_t, c_size_t, c_ssize_t

user32 = ctypes.WinDLL("user32", use_last_error=True)
_WNDPROC = WINFUNCTYPE(LRESULT, c_void_p, c_uint, WPARAM, LPARAM)
_SetLong = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
_SetLong.restype, _SetLong.argtypes = c_void_p, [c_void_p, c_int, c_void_p]
user32.CallWindowProcW.restype = LRESULT
user32.CallWindowProcW.argtypes = [c_void_p, c_void_p, c_uint, WPARAM, LPARAM]
user32.GetPointerPenInfo.argtypes = [c_uint, c_void_p]
user32.ScreenToClient.argtypes = [c_void_p, c_void_p]
user32.GetWindowRect.argtypes = [c_void_p, c_void_p]
user32.PostMessageW.argtypes = [c_void_p, c_uint, WPARAM, LPARAM]

_MAX_PRESSURE = 1024.0

# 活着的窗口过程对象。被 Python GC 掉而窗口还活着的话，下一条消息就会让进程
# 直接崩掉（没有 traceback，就是这么没声没响地死）。所以这里死死抓住不放。
# 注意用 dict 按 id 索引：ctypes 的函数指针不可哈希，塞不进 set。
_LIVE = {}


class POINT(Structure):
    _fields_ = [("x", c_long), ("y", c_long)]


class RECT(Structure):
    _fields_ = [("left", c_long), ("top", c_long), ("right", c_long), ("bottom", c_long)]


class POINTER_INFO(Structure):
    _fields_ = [
        ("pointerType", c_uint), ("pointerId", c_uint), ("frameId", c_uint),
        ("pointerFlags", c_uint), ("sourceDevice", c_void_p), ("hwndTarget", c_void_p),
        ("ptPixelLocation", POINT), ("ptHimetricLocation", POINT),
        ("ptPixelLocationRaw", POINT), ("ptHimetricLocationRaw", POINT),
        ("dwTime", c_uint), ("historyCount", c_uint), ("InputData", c_int),
        ("dwKeyStates", c_uint), ("PerformanceCount", c_ulonglong),
        ("ButtonChangeType", c_int),
    ]


class POINTER_PEN_INFO(Structure):
    _fields_ = [("pointerInfo", POINTER_INFO), ("penFlags", c_uint), ("penMask", c_uint),
                ("pressure", c_uint), ("rotation", c_uint),
                ("tiltX", c_int), ("tiltY", c_int)]


class NullPen(object):
    """接口和 PointerPen 一样，拿不到压感时占位用。"""

    ready = False
    error = "WM_POINTER 不可用"
    pressure = 0.0
    tilt = (0, 0)
    kind = None
    count = 0
    pen_count = 0
    target_kind = "-"
    types = {}
    events = ()

    def close(self):
        pass

    stop = close                    # 和 wintab 的后端保持同一个接口


class PointerPen(object):
    """收 WM_POINTER，取压感，翻译成鼠标消息投给画布，交给 Tk 自己的鼠标管线画。

    同时挂在**画布**和**顶层窗口**上：pointer 消息本该投给指针底下的窗口，但只要
    有窗口抓着鼠标捕获（SetCapture），消息就会被转给抓捕获的窗口 —— 实测
    `POINTER_INFO.hwndTarget` 就是**顶层窗口**。两个都挂上，谁收到都能处理。

    `EnableMouseInPointer(TRUE)` 是进程级的，会把鼠标也变成 pointer 消息，所以
    鼠标和笔走的是同一条路，行为一致。代价是 Tk 收不到原始鼠标消息了，必须靠
    上面这套合成消息补回去 —— 否则画布会完全没反应。
    """

    def __init__(self, canvas_hwnd, extra_hwnds=()):
        if not hasattr(user32, "EnableMouseInPointer"):
            raise OSError("系统没有 EnableMouseInPointer（需要 Windows 8+）")
        self.canvas_hwnd = canvas_hwnd
        self.extra = [h for h in extra_hwnds if h and h != canvas_hwnd]
        # 窗口过程只往这里塞数据，绘制由 Tk 的 after 回调 drain 出来做。
        # 有上限，Tk 万一卡住也不会无限堆积（deque 不支持切片，上限得用 maxlen）。
        self.events = collections.deque(maxlen=4000)
        self.pressure = 0.0
        self.tilt = (0, 0)
        self.kind = None                # 最近一次的 pointerType
        self.count = 0                  # 收到的 pointer 消息数
        self.pen_count = 0              # 其中真正是"笔"的
        self.types = {}                 # 消息名 -> 次数，诊断用
        self.hits = {}                  # 窗口 -> 收到多少条，诊断用
        self.target = None              # 最近一次 POINTER_INFO.hwndTarget
        self.error = None
        self._rect = None
        self._rect_age = 0
        self._pen = POINTER_PEN_INFO()

        user32.EnableMouseInPointer(True)
        self._proc = _WNDPROC(self._on_message)
        _LIVE[id(self._proc)] = self._proc
        self._old = {}
        for h in [canvas_hwnd] + self.extra:
            self._old[h] = _SetLong(c_void_p(h), GWLP_WNDPROC, self._proc)

    @property
    def ready(self):
        return self.error is None

    @property
    def target_kind(self):
        h = self.target
        if not h:
            return "-"
        if h == self.canvas_hwnd:
            return "画布"
        if h in self.extra:
            return "顶层"
        return "其它"

    def _canvas_rect(self):
        """画布的屏幕矩形，偶尔刷新一下（窗口可能被拖动/缩放）。"""
        self._rect_age += 1
        if self._rect is None or self._rect_age % 200 == 0:
            r = RECT()
            if user32.GetWindowRect(c_void_p(self.canvas_hwnd), byref(r)):
                self._rect = r
        return self._rect

    def _on_message(self, hwnd, msg, wp, lp):
        """子类化的窗口过程。**绝不能抛异常**，否则整个消息循环会崩。"""
        try:
            if msg in POINTER_MSGS:
                name = _MSG_NAME.get(msg, hex(msg))
                self.types[name] = self.types.get(name, 0) + 1
                self.hits[hwnd] = self.hits.get(hwnd, 0) + 1
                pen = self._pen
                if not user32.GetPointerPenInfo(wp & 0xFFFF, byref(pen)):
                    return 0                     # 拿不到信息就吞掉，别乱转发
                info = pen.pointerInfo
                self.kind = info.pointerType
                self.target = info.hwndTarget
                self.count += 1
                if info.pointerType == PT_PEN:
                    self.pen_count += 1
                    if pen.penMask & PEN_MASK_PRESSURE:
                        self.pressure = min(1.0, pen.pressure / _MAX_PRESSURE)
                    self.tilt = (pen.tiltX, pen.tiltY)
                else:
                    self.pressure = 0.0         # 鼠标没有压感
                sx, sy = info.ptPixelLocation.x, info.ptPixelLocation.y
                # 消息落到别的窗口（捕获之类）时，只有指针确实压在画布上才处理，
                # 否则会把手点在按钮上的操作也吃成画布笔迹
                if hwnd != self.canvas_hwnd:
                    r = self._canvas_rect()
                    if not (r and r.left <= sx < r.right and r.top <= sy < r.bottom):
                        return user32.CallWindowProcW(self._old[hwnd], hwnd, msg, wp, lp)
                if msg == WM_POINTERENTER or msg == WM_POINTERLEAVE:
                    return 0
                # 只把事件塞进队列，**不**碰 Tk/PIL。
                # 为什么不再转成鼠标消息 PostMessage 给画布：实测 hwndTarget 会是
                # 顶层窗口（有人抓着鼠标捕获），这时 Tk 的抓取逻辑会把合成消息吃掉，
                # 笔就没笔迹了。所以绕开 Tk 的鼠标管线，由 Tk 的 after 回调来取。
                # 为什么不能在这里直接画：窗口过程是 Tk 自己的消息分发调起来的，
                # 在里面回调 Python 再调 Tcl 会重入，实测直接把解释器搞崩。
                pt = POINT(sx, sy)
                user32.ScreenToClient(c_void_p(self.canvas_hwnd), byref(pt))
                self.events.append(
                    ("down" if msg == WM_POINTERDOWN else
                     "up" if msg == WM_POINTERUP else "move",
                     pt.x, pt.y, self.pressure))
                return 0
        except Exception as ex:
            self.error = "%s: %s" % (type(ex).__name__, ex)
        old = self._old.get(hwnd)
        return user32.CallWindowProcW(old, hwnd, msg, wp, lp) if old else 0

    def close(self):
        for h, old in list(self._old.items()):
            try:
                _SetLong(c_void_p(h), GWLP_WNDPROC, old)
            except Exception:
                pass
        self._old = {}
        _LIVE.pop(id(self._proc), None)
        self._proc = None

    stop = close                    # 和 wintab 的后端保持同一个接口


def open_pen(canvas_hwnd, extra_hwnds=()):
    """成功返回 pen，失败返回 NullPen（不抛），并把原因带在 error 里。"""
    try:
        return PointerPen(canvas_hwnd, extra_hwnds)
    except Exception as ex:
        null = NullPen()
        null.error = "%s: %s" % (type(ex).__name__, ex)
        return null
