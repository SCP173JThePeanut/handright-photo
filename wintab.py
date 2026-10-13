# coding: utf-8
"""WinTab (wintab32.dll) 最小绑定 —— 只为了拿压感。

⚠️ 实测定论：**这台机器上 WinTab 用不了**（2026-xx，Wacom 正版 wintab32.dll
"Wintab Coordinator" v1.0.5-10，WTabletServicePro 在跑，平板已插上）：

    WTInfo(WTI_DEFCONTEXT) 第1次: 34.53s   第2次: 32.53s   <- 每次都要 30 多秒
    WTOpen(toplevel hwnd): 1.50s -> None
    WTOpen(canvas   hwnd): 1.50s -> None                  <- 两个句柄都开不出 context

另外它**必须在有消息泵的线程里调**：丢到后台线程会永久卡死（实测 25s 不返回）。
所以三条路全堵死 —— 主线程调用要冻 30 秒，后台线程调用永远不返回，
就算熬过去 WTOpen 还是 NULL。

结论：mask_editor 里 USE_WINTAB 默认 False。换机器 / 重装驱动后想再试，
先确认 WTInfo 能在 1 秒内返回，再把 USE_WINTAB 打开。

设计取舍（如果哪天能用了）：**位置和按键仍然交给 tkinter 的鼠标事件**，
WinTab 只提供压感。这样省掉坐标映射和按键编码这两块最容易出错的东西 ——
平板的笔在 Windows 上本来就会产生鼠标消息，tkinter 拿到的坐标已经是对的。
"""
import ctypes
import threading
import time
from ctypes import POINTER, Structure, byref, c_int, c_long, c_uint, c_ulong, c_void_p, c_wchar

# ---------------------------------------------------------------- 常量
WTI_DEVICES, WTI_DEFCONTEXT = 0, 3
DVC_X, DVC_Y, DVC_NPRESSURE = 1, 2, 15

PK_STATUS, PK_BUTTONS = 0x0002, 0x0040
PK_X, PK_Y, PK_NPRESSURE = 0x0080, 0x0100, 0x0400
# 包里的字段顺序由 PK_ 位的顺序决定，不是由请求顺序决定
FIELDS = (("status", PK_STATUS), ("buttons", PK_BUTTONS),
          ("x", PK_X), ("y", PK_Y), ("pressure", PK_NPRESSURE))
PKT_DATA = PK_STATUS | PK_BUTTONS | PK_X | PK_Y | PK_NPRESSURE

TPS_PROXIMITY = 0x0002          # status 里的"笔在感应范围内"
LCNAMELEN = 40


class AXIS(Structure):
    _fields_ = [("axMin", c_uint), ("axMax", c_uint),
                ("axUnits", c_uint), ("axResolution", c_ulong)]


class LOGCONTEXT(Structure):
    _fields_ = [
        ("lcName", c_wchar * LCNAMELEN),
        ("lcOptions", c_uint), ("lcStatus", c_uint), ("lcLocks", c_uint),
        ("lcMsgBase", c_uint), ("lcDevice", c_uint), ("lcPktRate", c_uint),
        ("lcPktData", c_ulong), ("lcPktMode", c_ulong), ("lcMoveMask", c_ulong),
        ("lcBtnDnMask", c_ulong), ("lcBtnUpMask", c_ulong),
        ("lcInOrgX", c_long), ("lcInOrgY", c_long), ("lcInOrgZ", c_long),
        ("lcInExtX", c_long), ("lcInExtY", c_long), ("lcInExtZ", c_long),
        ("lcOutOrgX", c_long), ("lcOutOrgY", c_long), ("lcOutOrgZ", c_long),
        ("lcOutExtX", c_long), ("lcOutExtY", c_long), ("lcOutExtZ", c_long),
        ("lcSensX", c_ulong), ("lcSensY", c_ulong), ("lcSensZ", c_ulong),
        ("lcSysMode", c_int),
        ("lcSysOrgX", c_int), ("lcSysOrgY", c_int),
        ("lcSysExtX", c_int), ("lcSysExtY", c_int),
        ("lcSysSensX", c_ulong), ("lcSysSensY", c_ulong),
    ]


class WinTabError(RuntimeError):
    pass


_DLL = None


def _dll():
    global _DLL
    if _DLL is None:
        try:
            d = ctypes.WinDLL("wintab32.dll")
        except OSError as ex:
            raise WinTabError("找不到 wintab32.dll（没装 Wacom 驱动？）：%s" % ex)
        d.WTInfoW.restype, d.WTInfoW.argtypes = c_uint, [c_uint, c_uint, c_void_p]
        d.WTOpenW.restype, d.WTOpenW.argtypes = c_void_p, [c_void_p, POINTER(LOGCONTEXT), c_int]
        d.WTClose.restype, d.WTClose.argtypes = c_int, [c_void_p]
        d.WTPacketsGet.restype, d.WTPacketsGet.argtypes = c_int, [c_void_p, c_int, c_void_p]
        _DLL = d
    return _DLL


def axes():
    """平板的 X/Y 原始范围，以及压感满量程 —— 调试用，也用来判断有没有设备。"""
    d = _dll()
    out = {}
    for name, cat, idx in (("x", WTI_DEVICES, DVC_X), ("y", WTI_DEVICES, DVC_Y),
                           ("pressure", WTI_DEVICES, DVC_NPRESSURE)):
        ax = AXIS()
        if d.WTInfoW(cat, idx, byref(ax)) == 0:
            raise WinTabError("WTInfo 拿不到 %s 轴信息：没接平板？" % name)
        out[name] = (ax.axMin, ax.axMax, ax.axResolution)
    return out


class WinTabPen(object):
    """在某个窗口上开一个 WinTab context，轮询压感。

    drain() 要在 Tk 的 after() 里定期调；要压感的时候读 .pressure。
    """

    def __init__(self, hwnd, max_packets=64):
        self.hwnd = hwnd
        self.max_packets = max_packets
        self.pressure = 0.0
        self.tip = False
        self.in_range = False
        self.raw = None                 # (x, y, pressure_raw, buttons, status) 最后一次
        self.seen = 0                   # 收到过多少包
        self._buf = (c_ulong * (len(FIELDS) * max_packets))()

        d = _dll()
        lc = LOGCONTEXT()
        if d.WTInfoW(WTI_DEFCONTEXT, 0, byref(lc)) == 0:
            raise WinTabError("WTInfo(WTI_DEFCONTEXT) 失败：没接平板？")
        # 拿驱动给的默认 context，只改我们关心的几项，其余保持驱动推荐值
        lc.lcPktData = PKT_DATA
        lc.lcPktMode = 0
        lc.lcMoveMask = PKT_DATA
        lc.lcBtnDnMask = 0
        lc.lcBtnUpMask = 0
        lc.lcOutOrgX = lc.lcOutOrgY = 0
        lc.lcOutExtX = lc.lcOutExtY = 0          # 0 = 不做输出缩放，给原始坐标
        self.h = d.WTOpenW(c_void_p(hwnd), byref(lc), True)
        if not self.h:
            raise WinTabError("WTOpen 失败（窗口句柄 %s）" % hwnd)
        try:
            self._ax = axes()
            self._pmax = max(1, self._ax["pressure"][1])
        except WinTabError:
            # 有些驱动开了 context 也读不到轴信息；满量程按常见的 1023 兜底，
            # 拿不到就只是个比例问题，比直接罢工好。
            self._ax, self._pmax = None, 1023

    def drain(self):
        """把驱动队列里的包读干净，返回这次读到的包数。"""
        d = _dll()
        n = d.WTPacketsGet(c_void_p(self.h), self.max_packets, byref(self._buf))
        if n <= 0:
            return 0
        n = min(n, self.max_packets)
        w = len(FIELDS)
        for i in range(n):
            v = self._buf[i * w:(i + 1) * w]
            status, buttons, x, y, press = v[0], v[1], v[2], v[3], v[4]
            self.raw = (x, y, press, buttons, status)
            self.in_range = bool(status & TPS_PROXIMITY)
            self.pressure = min(1.0, press / float(self._pmax))
            self.tip = bool((buttons >> 16) & 1) or self.pressure > 0
        self.seen += n
        return n

    def close(self):
        if getattr(self, "h", None):
            _dll().WTClose(c_void_p(self.h))
            self.h = None


def try_open(hwnd):
    """成功返回 (pen, None)，失败返回 (None, 原因)。绝不抛给调用方。"""
    try:
        return WinTabPen(hwnd), None
    except WinTabError as ex:
        return None, str(ex)
    except Exception as ex:                       # 驱动抽风也别把整个程序带崩
        return None, "%s: %s" % (type(ex).__name__, ex)


class NullPen(object):
    """没启用/接不上时的占位，接口和 PenThread 一样，调用方不用到处判空。"""

    ready = False
    error = None
    elapsed = 0.0
    events = ()                     # 和 pen_pointer 的后端保持同一个接口

    @property
    def pressure(self):
        return 0.0

    def start(self):
        pass

    def stop(self):
        pass

    close = stop                    # 和 pen_pointer 的后端保持同一个接口


class PenThread(threading.Thread):
    """在后台线程里开 context 并轮询压感。

    **绝不能**在界面线程上直接 WTOpen：驱动状态不对时它会一直不返回，
    整个窗口就白屏"未响应"了。放后台线程里，卡住也只是这一路没有压感，
    界面照常用鼠标按固定力度画。
    """

    daemon = True

    def __init__(self, hwnd, interval=0.008):
        threading.Thread.__init__(self, name="wintab-poll")
        self.daemon = True
        self.hwnd = hwnd
        self.interval = interval
        self.ready = False          # context 开好了、正在收包
        self.error = None           # 开不起来的原因
        self.started_at = time.time()
        self.events = ()            # 和 pen_pointer 的后端保持同一个接口
        self._stop = threading.Event()
        self._pen = None

    @property
    def pressure(self):
        p = self._pen
        return p.pressure if (self.ready and p is not None) else 0.0

    @property
    def elapsed(self):
        return time.time() - self.started_at

    def run(self):
        pen, err = try_open(self.hwnd)           # 这里可能卡很久
        if pen is None:
            self.error = err
            return
        if self._stop.is_set():                  # 卡的时候用户已经关掉了
            pen.close()
            return
        self._pen, self.ready = pen, True
        while not self._stop.is_set():
            try:
                pen.drain()
            except Exception as ex:
                self.error = "%s: %s" % (type(ex).__name__, ex)
                break
            time.sleep(self.interval)
        self.ready = False
        try:
            pen.close()
        except Exception:
            pass

    def stop(self):
        self._stop.set()

    close = stop                    # 和 pen_pointer 的后端保持同一个接口
