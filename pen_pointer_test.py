# coding: utf-8
"""WM_POINTER 独立测试窗口 —— 验证能不能绕过 Wacom 驱动拿到压感。

    .venv\\Scripts\\python.exe pen_pointer_test.py [--no-enable] [--seconds 60]

它自己一个进程、自己一个窗口，碰不到编辑器，写坏了也只炸它自己。

做三件事：
  1. EnableMouseInPointer(TRUE) —— 之后鼠标和笔都会变成 WM_POINTER 消息
  2. 子类化画布的窗口过程，收 WM_POINTER*，用 GetPointerPenInfo 读压感/倾斜
  3. 把 pointer 消息翻译回 WM_MOUSEMOVE/LBUTTONDOWN/UP 转发给 Tk，
     否则 Tk 收不到鼠标事件，画布就"死"了

窗口里能用鼠标 / 笔画线 = 第 3 步成功；读数里出现 pen + 非零压感 = 拿到压感了。
"""
import argparse
import ctypes
import sys
import time
import tkinter as tk
from ctypes import (WINFUNCTYPE, POINTER, Structure, byref, c_int, c_long, c_size_t,
                    c_ssize_t, c_uint, c_ulonglong, c_void_p)

# ------------------------------------------------------------------ 常量
WM_POINTERUPDATE, WM_POINTERDOWN, WM_POINTERUP = 0x0245, 0x0246, 0x0247
WM_POINTERENTER, WM_POINTERLEAVE = 0x0249, 0x024A
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
GWLP_WNDPROC = -4
MK_LBUTTON = 0x0001
PT_TOUCH, PT_PEN, PT_MOUSE = 2, 3, 4
PT_NAME = {2: "touch", 3: "pen", 4: "mouse"}
PEN_MASK_PRESSURE = 0x0001
POINTER_MSGS = {WM_POINTERUPDATE: "UPDATE", WM_POINTERDOWN: "DOWN",
                WM_POINTERUP: "UP", WM_POINTERENTER: "ENTER",
                WM_POINTERLEAVE: "LEAVE"}

LRESULT, WPARAM, LPARAM = c_ssize_t, c_size_t, c_ssize_t


# ------------------------------------------------------------------ 结构体
class POINT(Structure):
    _fields_ = [("x", c_long), ("y", c_long)]


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


user32 = ctypes.WinDLL("user32", use_last_error=True)
_WNDPROC = WINFUNCTYPE(LRESULT, c_void_p, c_uint, WPARAM, LPARAM)
_SetLong = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
_SetLong.restype, _SetLong.argtypes = c_void_p, [c_void_p, c_int, c_void_p]
user32.CallWindowProcW.restype = LRESULT
user32.CallWindowProcW.argtypes = [c_void_p, c_void_p, c_uint, WPARAM, LPARAM]
user32.GetPointerPenInfo.argtypes = [c_uint, POINTER(POINTER_PEN_INFO)]
user32.GetPointerInfo.argtypes = [c_uint, POINTER(POINTER_INFO)]
user32.ScreenToClient.argtypes = [c_void_p, POINTER(POINT)]
user32.PostMessageW.argtypes = [c_void_p, c_uint, WPARAM, LPARAM]
user32.EnableMouseInPointer.argtypes = [c_int]

state = {"msgs": {}, "types": set(), "maxp": 0, "pen_seen": 0, "tk_motion": 0,
         "tk_down": 0, "tk_up": 0, "last": None, "forwarded": 0, "hwnd": None,
         "old": None, "t0": time.time()}


def _proc(hwnd, msg, wp, lp):
    """子类化后的窗口过程。**绝不能抛异常**，否则消息循环会崩。"""
    try:
        if msg in POINTER_MSGS:
            name = POINTER_MSGS[msg]
            state["msgs"][name] = state["msgs"].get(name, 0) + 1
            pid = wp & 0xFFFF
            ptype, press, tx, ty, sx, sy = 0, 0, 0, 0, 0, 0
            pen = POINTER_PEN_INFO()
            if user32.GetPointerPenInfo(pid, byref(pen)):
                ptype = pen.pointerInfo.pointerType
                press = pen.pressure if (pen.penMask & PEN_MASK_PRESSURE) else 0
                tx, ty = pen.tiltX, pen.tiltY
                sx, sy = pen.pointerInfo.ptPixelLocation.x, pen.pointerInfo.ptPixelLocation.y
            else:
                info = POINTER_INFO()
                if user32.GetPointerInfo(pid, byref(info)):
                    ptype = info.pointerType
                    sx, sy = info.ptPixelLocation.x, info.ptPixelLocation.y
            state["types"].add(ptype)
            if press:
                state["maxp"] = max(state["maxp"], press)
            if ptype == PT_PEN:
                state["pen_seen"] += 1
            state["last"] = (name, PT_NAME.get(ptype, ptype), press, tx, ty, sx, sy)

            # 翻译成鼠标消息转发给 Tk，否则画布收不到事件
            pt = POINT(sx, sy)
            user32.ScreenToClient(hwnd, byref(pt))
            elp = ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)
            if msg == WM_POINTERDOWN:
                user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, elp)
            elif msg == WM_POINTERUP:
                user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, elp)
            else:
                user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, elp)
            state["forwarded"] += 1
            return 0
    except Exception as ex:                        # 吞掉，绝不让它冒到消息循环
        state["err"] = repr(ex)
    return user32.CallWindowProcW(state["old"], hwnd, msg, wp, lp)


wrapper = _WNDPROC(_proc)          # 必须留引用，否则被 GC 掉会直接崩


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-enable", action="store_true",
                    help="不调 EnableMouseInPointer（看笔自己会不会产生 pointer 消息）")
    ap.add_argument("--seconds", type=int, default=60)
    args = ap.parse_args()

    print("POINTER_INFO     sizeof=%d (x64 应为 96)" % ctypes.sizeof(POINTER_INFO))
    print("POINTER_PEN_INFO sizeof=%d (x64 应为 120)" % ctypes.sizeof(POINTER_PEN_INFO))
    print("SetWindowLongPtrW:", "有" if hasattr(user32, "SetWindowLongPtrW") else "没有，用 SetWindowLongW")

    root = tk.Tk()
    root.title("WM_POINTER 测试 · 用鼠标或笔画线")
    root.geometry("760x560+120+80")
    lab = tk.Label(root, anchor="w", justify="left", font=("Consolas", 10))
    lab.pack(fill="x", padx=8, pady=4)
    cv = tk.Canvas(root, bg="white", highlightthickness=1)
    cv.pack(fill="both", expand=True, padx=8, pady=4)
    root.update()

    hwnd = cv.winfo_id()
    state["hwnd"] = hwnd
    state["old"] = _SetLong(c_void_p(hwnd), GWLP_WNDPROC, wrapper)
    print("画布 hwnd=%s  原窗口过程=%s" % (hwnd, state["old"]))

    if args.no_enable:
        print("按 --no-enable 跳过 EnableMouseInPointer（鼠标仍是普通鼠标消息）")
    else:
        ok = user32.EnableMouseInPointer(True)
        print("EnableMouseInPointer(True) -> %s  err=%s" % (ok, ctypes.get_last_error()))

    # Tk 这边的事件：转发成功的话这些计数会涨，画布上也能画出线
    def on_motion(e):
        state["tk_motion"] += 1
        cv.create_oval(e.x - 2, e.y - 2, e.x + 2, e.y + 2, fill="#06c", width=0)

    cv.bind("<Motion>", on_motion)
    cv.bind("<B1-Motion>", on_motion)
    cv.bind("<Button-1>", lambda e: state.__setitem__("tk_down", state["tk_down"] + 1))
    cv.bind("<ButtonRelease-1>", lambda e: state.__setitem__("tk_up", state["tk_up"] + 1))

    def tick():
        last = state["last"]
        lab.config(text=(
            "pointer 消息 %s      转发合成鼠标 %d\n"
            "Tk 收到 Motion=%d  ButtonPress=%d  Release=%d\n"
            "见过类型 %s      笔消息 %d      最大压感 %d/1024\n"
            "最近: %s"
            % (state["msgs"], state["forwarded"], state["tk_motion"], state["tk_down"],
               state["tk_up"], sorted(PT_NAME.get(t, t) for t in state["types"]),
               state["pen_seen"], state["maxp"], last)))
        if time.time() - state["t0"] < args.seconds:
            root.after(120, tick)
        else:
            root.destroy()

    def bye():
        if state["old"]:
            _SetLong(c_void_p(hwnd), GWLP_WNDPROC, state["old"])
        if not args.no_enable:
            user32.EnableMouseInPointer(False)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", bye)
    root.after(200, tick)
    root.mainloop()

    print("\n================ 结果 ================")
    print("pointer 消息统计 : %s" % state["msgs"])
    print("见过 pointer 类型: %s" % sorted(PT_NAME.get(t, t) for t in state["types"]))
    print("转发合成鼠标消息 : %d" % state["forwarded"])
    print("Tk 事件 Motion=%d Press=%d Release=%d（>0 说明转发有效）"
          % (state["tk_motion"], state["tk_down"], state["tk_up"]))
    print("笔消息 %d 条，最大压感 %d/1024" % (state["pen_seen"], state["maxp"]))
    if state.get("err"):
        print("窗口过程里出过异常: %s" % state["err"])
    if not state["msgs"]:
        print("=> 一个 pointer 消息都没收到：这条路在这台机器上也不通")
    elif not state["pen_seen"]:
        print("=> pointer 通了，但只有鼠标（type=mouse）。用笔在窗口里划一下再看")
    elif state["maxp"] == 0:
        print("=> 收到笔消息了，但压感恒为 0：驱动没把压力报上来")
    else:
        print("=> ✓ 拿到压感了，可以用这条路")
    return 0


if __name__ == "__main__":
    sys.exit(main())
