# coding: utf-8
"""把每一页当成 PS 图层来编辑：擦掉不想要的，或者直接用笔写上去。

在 deal.py 里这样用：

    editor = MaskEditor(paper, fill=fill, pen_width=pen_width, ...)
    ...
    im = editor.edit(im, i)             # 返回改过的页面；返回 None 表示用户要收工

界面上能调的都在 __init__ 的参数里，deal.py 里的那些常量只是**默认值**：
    墨色 / 笔宽 / 压感最细最粗 / 橡皮大小

两个工具：
  擦除 —— 左键拖，把生成的墨迹擦掉露出纸面
  手写 —— 左键拖，用笔迹写上去；接了 Wacom 就跟着压感变粗细（鼠标则固定力度）

手写层和擦除层都在 opencv_photo_like 之前合成，所以会跟着一起吃透视/模糊/噪点/光照。
"""
import math
import tkinter as tk
from tkinter import colorchooser, filedialog

from PIL import Image, ImageChops, ImageDraw, ImageTk

import pen_pointer
import wintab
from param_widgets import ParamPanel, load_preset, save_preset

_ZOOMS = (0.2, 0.25, 0.35, 0.5, 0.7, 1.0)
_TILE = 256                     # 显示用的图块边长（像素）
_MOUSE_PRESSURE = 0.65          # 鼠标（或笔悬空）时按这个固定力度画
_PRESETS = [("黑", (20, 20, 20)), ("深灰", (30, 30, 35)), ("蓝黑", (26, 34, 62)),
            ("纯蓝", (28, 52, 140)), ("红", (150, 40, 40))]

# 压感来源。pen_pointer 走 Windows 自带的 WM_POINTER，实测能拿到满量程压感。
# wintab 在这台机器上坏了（WTInfo 每次 33 秒、WTOpen 返回 NULL），留着重装驱动后再试。
_PEN_BACKEND = "pointer"        # "pointer" | "wintab" | "none"

_ROOT = None


def _shared_root():
    """一个进程只能有一个 Tk 根：多开几次 Tk() 会让图片在别人的画布上"不存在"。"""
    global _ROOT
    if _ROOT is None or not _ROOT.winfo_exists():
        _ROOT = tk.Tk()
        _ROOT.withdraw()
    return _ROOT


def _rounded_rect(draw, x, y, r):
    draw.ellipse((x - r, y - r, x + r, y + r), fill=255)


def _draw_stroke(draw, pts, width):
    """等宽的一笔（橡皮用）；pts 用目标图自己的坐标。"""
    width = max(1, int(round(width)))
    if len(pts) > 1:
        draw.line(pts, fill=255, width=width, joint="curve")
    _rounded_rect(draw, pts[0][0], pts[0][1], width / 2.0)
    _rounded_rect(draw, pts[-1][0], pts[-1][1], width / 2.0)


def _draw_pen(draw, pts, base, lo=0.45, hi=2.0):
    """变宽的一笔；pts = [(x, y, pressure)]，base 是目标图里的笔宽。

    lo/hi 是压感 0 和 1 时的粗细倍数。PIL 只会画等宽线，所以自己拼：
    每段一个梯形，顶点补个圆当关节和笔头。实测 300 个点只要 0.7ms。
    """
    r = [max(0.5, base * (lo + (hi - lo) * p) / 2.0) for _, _, p in pts]
    xy = [(x, y) for x, y, _ in pts]
    if len(xy) == 1:
        _rounded_rect(draw, xy[0][0], xy[0][1], r[0])
        return
    for i in range(len(xy) - 1):
        (x0, y0), (x1, y1) = xy[i], xy[i + 1]
        r0, r1 = r[i], r[i + 1]
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy)
        if L < 1e-6:
            _rounded_rect(draw, x0, y0, r0)
            continue
        nx, ny = -dy / L, dx / L
        draw.polygon([(x0 + nx * r0, y0 + ny * r0), (x1 + nx * r1, y1 + ny * r1),
                      (x1 - nx * r1, y1 - ny * r1), (x0 - nx * r0, y0 - ny * r0)],
                     fill=255)
        _rounded_rect(draw, x0, y0, r0)
    _rounded_rect(draw, xy[-1][0], xy[-1][1], r[-1])


class MaskEditor(object):
    """一次编辑一页；edit() 会一直阻塞到用户点「输出本页」/「跳过本页」/「退出」。"""

    def __init__(self, paper, fill=(30, 30, 35), pen_width=6.0, pen_min=0.45,
                 pen_max=2.0, brush=45):
        self.paper = paper
        self.fill = tuple(fill)         # 墨色：生成的字和手写的笔迹**同一个色**
        self.pen_width = pen_width      # 手写体自身细笔画约 5.5~6px，默认对齐
        self.pen_min = pen_min          # 压感最轻时的倍数
        self.pen_max = pen_max          # 压感最重时的倍数
        self.brush = brush              # 橡皮大小
        self._root = _shared_root()

    # ------------------------------------------------------------------ 对外
    def _load_page(self, page):
        """记住这一页，并算出"纸上哪些像素是生成的字"。

        改墨色时靠这张全分辨率蒙版精确重上色 —— 不用重新渲染，也不会把纸的纹理弄脏。
        """
        self.page = page
        diff = ImageChops.difference(page.convert("RGB"),
                                     self.paper.convert("RGB")).convert("L")
        self.ink_mask = diff.point(lambda v: 255 if v > 24 else 0)
        # base_mask 是"这一页原本的字"，导入蒙版会把它整个换掉
        self.base_mask = self.ink_mask.copy()

    def edit(self, page, index=0):
        self._load_page(page)
        self.strokes = []               # 擦除笔画 [{"w", "pts": [(x, y)]}]
        self.pens = []                  # 手写笔画 [{"w", "pts": [(x, y, p)]}]
        self._hist = [([], [])]
        self._hpos = 0
        self.tool = "erase"
        self.result = page
        self._tiles = {}
        self._build(index)
        try:
            self._root.wait_window(self._win)
        finally:
            self._pen.close()           # 把窗口过程还回去，别留给死窗口
        return self.result

    # ------------------------------------------------------------ 界面搭建
    def _build(self, index):
        win = self._win = tk.Toplevel(self._root)
        win.title("第 %d 页 · 擦掉不想要的，或者直接写" % (index + 1))
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = min(1560, sw - 80), min(980, sh - 120)
        win.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, max(10, (sh - h) // 3)))
        win.protocol("WM_DELETE_WINDOW", self._do_quit)

        bar = tk.Frame(win)
        bar.pack(side="top", fill="x", padx=6, pady=(4, 0))
        self._tool_var = tk.StringVar(value="erase")
        for text, val in (("擦除", "erase"), ("手写", "pen")):
            tk.Radiobutton(bar, text=text, value=val, variable=self._tool_var,
                           command=self._pick_tool).pack(side="left")
        self._color_btn = tk.Button(bar, text="  墨色  ", relief="raised",
                                    command=self._pick_color)
        self._color_btn.pack(side="left", padx=(8, 2))
        for name, rgb in _PRESETS:
            tk.Button(bar, text=name, bg="#%02x%02x%02x" % rgb, fg="#fff" if sum(rgb) < 380 else "#000",
                      relief="flat", command=lambda c=rgb: self._set_color(c)
                      ).pack(side="left", padx=1)
        tk.Button(bar, text="退出", command=self._do_quit).pack(side="right", padx=2)
        tk.Button(bar, text="跳过本页", command=self._do_skip).pack(side="right", padx=2)
        self._out_btn = tk.Button(bar, text="输出本页 ▶", command=self._do_output,
                                  default="active")
        self._out_btn.pack(side="right", padx=2)

        bar2 = tk.Frame(win)
        bar2.pack(side="top", fill="x", padx=6)
        # 橡皮 / 笔宽 / 压感最细最粗：滑块旁边就是输入框，范围不够就直接敲数字
        self.tool_vals = {"brush": int(self.brush), "pen_width": float(self.pen_width),
                          "pen_min": float(self.pen_min), "pen_max": float(self.pen_max)}
        self.tools = ParamPanel(
            bar2, self.tool_vals,
            [("brush", "橡皮", "int", 1, 400, 1),
             ("pen_width", "笔宽", "float", 0.2, 60, 0.2),
             ("pen_min", "压感最细", "float", 0.01, 4.0, 0.01),
             ("pen_max", "压感最粗", "float", 0.05, 8.0, 0.05)],
            on_change=self._tools_changed, debounce=200,
            row_pack="left", label_w=8, scale_len=92)
        self.tools.frame.pack(side="left")

        bar3 = tk.Frame(win)
        bar3.pack(side="top", fill="x", padx=6)
        for text, cmd in (("撤销", self._undo), ("重做", self._redo),
                          ("清空本页", self._clear)):
            tk.Button(bar3, text=text, command=cmd).pack(side="left", padx=2)
        tk.Label(bar3, text="  缩放").pack(side="left")
        for text, cmd in (("－", lambda: self._step_zoom(-1)),
                          ("＋", lambda: self._step_zoom(1)),
                          ("适应窗口", self._fit)):
            tk.Button(bar3, text=text, command=cmd).pack(side="left", padx=2)
        self._zoom_lab = tk.Label(bar3, text="")
        self._zoom_lab.pack(side="left", padx=4)
        tk.Button(bar3, text="导出蒙版", command=self._export_mask).pack(side="right", padx=2)
        tk.Button(bar3, text="导入蒙版", command=self._import_mask).pack(side="right", padx=2)
        tk.Button(bar3, text="保存预设", command=self._save_preset).pack(side="right", padx=2)
        tk.Button(bar3, text="载入预设", command=self._load_preset).pack(side="right", padx=2)

        body = tk.Frame(win)
        body.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg="#3a3a3a", highlightthickness=0)
        xbar = tk.Scrollbar(body, orient="horizontal", command=self.canvas.xview)
        ybar = tk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.config(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        foot = tk.Frame(win)
        foot.pack(side="bottom", fill="x")
        self.status = tk.Label(foot, anchor="w")
        self.status.pack(side="left", padx=8, pady=3)
        self.pen_lab = tk.Label(foot, anchor="e")
        self.pen_lab.pack(side="right", padx=8, pady=3)

        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(-e.delta // 120, "units"))
        win.bind("<Control-z>", lambda e: self._undo())
        win.bind("<Control-y>", lambda e: self._redo())
        win.bind("<Escape>", lambda e: self._do_skip())
        win.bind("<Return>", lambda e: self._do_output())
        win.bind("<bracketleft>", lambda e: self._nudge(-1))
        win.bind("<bracketright>", lambda e: self._nudge(1))

        self._sync_color_btn()
        win.update_idletasks()
        self._tiles = {}                # 每页一块新画布，旧的图块 id 不能留
        self._want_fit = True
        self.canvas.bind("<Configure>", lambda e: self._fit())
        # 这会儿窗口往往还没真正长出来（winfo_width() 只有 1），先按标称尺寸估一个，
        # 等 <Configure> 拿到真实尺寸再校正 —— 否则会缩成 6% 而且坐标全飘。
        pw, ph = self.page.size
        self._set_zoom(min((w - 24) / float(pw), (h - 130) / float(ph)) * 0.98)
        self._fit()

        if getattr(self, "_pen", None) is not None:
            self._pen.close()           # 上一页的窗口过程先还回去，别留给死窗口
        if _PEN_BACKEND == "pointer":
            # 画布 + 顶层都挂上（实测 hwndTarget 可能是顶层）。窗口过程只负责
            # 把事件塞进队列，绘制由 _poll_pen 在 Tk 回调里做。
            self._pen = pen_pointer.open_pen(self.canvas.winfo_id(),
                                             (win.winfo_id(),))
        elif _PEN_BACKEND == "wintab":
            self._pen = wintab.PenThread(self.canvas.winfo_id())
            self._pen.start()
        else:
            self._pen = wintab.NullPen()
        self._ticks = 0
        self._poll_pen()

    # ------------------------------------------------------------------ 缩放
    def _fit(self):
        if not getattr(self, "_want_fit", False):
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 50 or ch < 50:
            return                      # 画布还没长出来，等 <Configure>
        self._want_fit = False
        pw, ph = self.page.size
        self._set_zoom(min(cw / float(pw), ch / float(ph)) * 0.98)

    def _step_zoom(self, d):
        self._want_fit = False
        bigger = [z for z in _ZOOMS if z > self.zoom + 1e-6]
        smaller = [z for z in _ZOOMS if z < self.zoom - 1e-6]
        if d > 0 and bigger:
            self._set_zoom(bigger[0])
        elif d < 0 and smaller:
            self._set_zoom(smaller[-1])

    def _set_zoom(self, zoom):
        self.zoom = max(0.05, min(1.0, zoom))
        pw, ph = self.page.size
        self._disp_size = (max(1, round(pw * self.zoom)), max(1, round(ph * self.zoom)))
        self.disp_base = self.page.convert("RGB").resize(self._disp_size, Image.LANCZOS)
        self.disp_paper = self.paper.convert("RGB").resize(self._disp_size, Image.LANCZOS)
        self.disp_mask = Image.new("L", self._disp_size, 0)
        self.disp_ink = Image.new("L", self._disp_size, 0)
        self.disp = self.disp_base.copy()
        self.canvas.config(scrollregion=(0, 0) + self._disp_size)
        self._zoom_lab.config(text="%d%%" % round(self.zoom * 100))
        self._drop_tiles()
        self._rebuild_mask()
        self._redraw()

    # 显示层切成图块：画一笔只需要重画压到的那一两块。
    # 不切块的话，放大到 100% 时每次鼠标移动都要重画整页 3072x4095
    # （合成 ~45ms + 建 PhotoImage ~40ms），拖起来就明显卡；切块后是 ~1ms。
    def _drop_tiles(self):
        for item, _box, _photo in self._tiles.values():
            self.canvas.delete(item)
        self._tiles = {}

    def _tile_box(self, tx, ty):
        w, h = self._disp_size
        return (tx, ty, min(tx + _TILE, w), min(ty + _TILE, h))

    def _push_tile(self, key, tbox):
        photo = ImageTk.PhotoImage(self.disp.crop(tbox))
        item = self._tiles[key][0]
        self.canvas.itemconfigure(item, image=photo)
        self._tiles[key] = (item, tbox, photo)

    # ------------------------------------------------------------------ 绘制
    def _rebuild_mask(self):
        k = self.zoom
        self.disp_mask = Image.new("L", self._disp_size, 0)
        self.disp_ink = Image.new("L", self._disp_size, 0)
        de = ImageDraw.Draw(self.disp_mask)
        for s in self.strokes:
            _draw_stroke(de, [(x * k, y * k) for x, y in s["pts"]], s["w"] * k)
        di = ImageDraw.Draw(self.disp_ink)
        for s in self.pens:
            _draw_pen(di, [(x * k, y * k, p) for x, y, p in s["pts"]], s["w"] * k,
                      self.pen_min, self.pen_max)

    def _redraw(self, box=None):
        """按擦除蒙版露出纸面，再把笔迹按墨色盖上去。

        box 给定时只重画那一块（原地的图块），不给就整幅重画。
        """
        if box is None:
            self.disp = Image.composite(self.disp_paper, self.disp_base, self.disp_mask)
            self.disp.paste(self.fill, (0, 0), self.disp_ink)
            w, h = self._disp_size
            hit = [(tx, ty) for ty in range(0, h, _TILE) for tx in range(0, w, _TILE)]
        else:
            w, h = self._disp_size
            x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
            x1, y1 = min(w, int(box[2]) + 1), min(h, int(box[3]) + 1)
            if x1 <= x0 or y1 <= y0:
                return
            b = (x0, y0, x1, y1)
            region = Image.composite(self.disp_paper.crop(b), self.disp_base.crop(b),
                                     self.disp_mask.crop(b))
            self.disp.paste(region, (x0, y0))
            self.disp.paste(self.fill, (x0, y0), self.disp_ink.crop(b))
            hit = [(tx, ty) for ty in range(y0 // _TILE * _TILE, y1, _TILE)
                   for tx in range(x0 // _TILE * _TILE, x1, _TILE)
                   if tx < w and ty < h]
        for key in hit:
            tbox = self._tile_box(*key)
            if key not in self._tiles:          # 第一次：建图块
                photo = ImageTk.PhotoImage(self.disp.crop(tbox))
                item = self.canvas.create_image(tbox[0], tbox[1], anchor="nw", image=photo)
                self._tiles[key] = (item, tbox, photo)
            else:
                self._push_tile(key, tbox)

    def _to_image(self, event):
        return self._wx_to_image(event.x, event.y)

    def _wx_to_image(self, wx, wy):
        return (self.canvas.canvasx(wx) / self.zoom,
                self.canvas.canvasy(wy) / self.zoom)

    def _force(self, pressure=None):
        """有事件自带压感就用它，否则回退（鼠标 / 笔悬空）。"""
        if pressure and pressure > 0:
            return pressure
        return _MOUSE_PRESSURE

    def _pressure(self):
        p = self._pen.pressure
        return p if p > 0 else _MOUSE_PRESSURE   # 鼠标 / 笔悬空时按固定力度

    # 落笔 / 移动 / 抬笔：压感后端把事件塞进队列，由 _poll_pen 在 Tk 的
    # after 回调里 drain 出来调这三个（不能从窗口过程里直接调，会重入 Tcl 崩掉）。
    # Tk 自己的鼠标事件也调它们，所以两条路行为一致。
    def pen_down(self, wx, wy, pressure=None):
        # pointer 队列和 Tk 事件可能对同一次落笔各报一次（系统有时会把 pointer
        # 输入降级成普通鼠标消息），所以正在画的时候不重开新的一笔。
        if getattr(self, "_drawing", False):
            return
        p = self._wx_to_image(wx, wy)
        self._cur = [(p[0], p[1], self._force(pressure)) if self.tool == "pen" else p]
        self._last = p
        self._drawing = True

    def pen_move(self, wx, wy, pressure=None, redraw=True):
        """把这一小段并进当前笔画。redraw=False 时只返回脏区，由调用方合并后一次重画
        —— pointer 队列一 tick 可能攒了几十条，逐条重画会白花掉大量时间。"""
        if not getattr(self, "_drawing", False):
            return None
        p = self._wx_to_image(wx, wy)
        # 太近的点直接丢：笔一秒能发一百多条，其中大部分是重复位置
        if abs(p[0] - self._last[0]) < 0.5 and abs(p[1] - self._last[1]) < 0.5:
            return None
        self._cur.append((p[0], p[1], self._force(pressure)) if self.tool == "pen" else p)
        prev, self._last = self._last, p
        # 拖动中只补这一小段，保证跟手；松手后再按整笔重画，结果才一致
        if self.tool == "pen":
            _draw_pen(ImageDraw.Draw(self.disp_ink),
                      [(x * self.zoom, y * self.zoom, pr) for x, y, pr in self._cur[-2:]],
                      self.pen_width * self.zoom, self.pen_min, self.pen_max)
        else:
            _draw_stroke(ImageDraw.Draw(self.disp_mask),
                         [(x * self.zoom, y * self.zoom) for x, y in self._cur[-2:]],
                         self.brush * self.zoom)
        box = self._dirty_box(prev, self._cur[-1])
        if redraw:
            self._redraw(box)
        return box

    @staticmethod
    def _union_box(a, b):
        if a is None:
            return b
        if b is None:
            return a
        return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))

    def _dirty_box(self, a, b):
        """a、b 是这一小段的两端（原图坐标），返回要重画的显示区域。"""
        k = self.zoom
        if self.tool == "pen":
            r = self.pen_width * max(self.pen_max, 1.0) / 2.0 + 3
        else:
            r = self.brush / 2.0 + 3
        ax, ay = a[0], a[1]
        bx, by = b[0], b[1]
        return ((min(ax, bx) - r) * k - 2, (min(ay, by) - r) * k - 2,
                (max(ax, bx) + r) * k + 2, (max(ay, by) + r) * k + 2)

    def pen_up(self, wx=None, wy=None):
        if not getattr(self, "_drawing", False):
            return
        self._drawing = False
        if self.tool == "pen":
            self.pens.append({"w": self.pen_width, "pts": list(self._cur)})
        else:
            self.strokes.append({"w": self.brush, "pts": list(self._cur)})
        self._commit()
        self._rebuild_mask()
        self._redraw()
        self._say()

    def _on_press(self, event):
        self.canvas.focus_set()
        self.pen_down(event.x, event.y)

    def _on_drag(self, event):
        self.pen_move(event.x, event.y)

    def _on_release(self, event):
        self.pen_up()

    def _on_motion(self, event):
        """普通移动。系统有时会把 pointer 的移动降级成普通鼠标消息送来，
        这里接住它，保证已经是落笔状态的那一笔不会断。"""
        if getattr(self, "_drawing", False):
            self.pen_move(event.x, event.y)

    # -------------------------------------------------------------- 撤销等
    def _commit(self):
        del self._hist[self._hpos + 1:]
        self._hist.append((list(self.strokes), list(self.pens)))
        self._hpos += 1

    def _restore(self):
        self.strokes = list(self._hist[self._hpos][0])
        self.pens = list(self._hist[self._hpos][1])
        self._rebuild_mask()
        self._redraw()
        self._say()

    def _undo(self):
        if self._hpos > 0:
            self._hpos -= 1
            self._restore()

    def _redo(self):
        if self._hpos < len(self._hist) - 1:
            self._hpos += 1
            self._restore()

    def _clear(self):
        if self.strokes or self.pens:
            self.strokes, self.pens = [], []
            self._commit()
            self._restore()

    # ------------------------------------------------------------------ 墨色
    def _sync_color_btn(self):
        if getattr(self, "_color_btn", None) is not None:
            self._color_btn.config(bg="#%02x%02x%02x" % self.fill,
                                   fg="#fff" if sum(self.fill) < 380 else "#000")

    def _set_color(self, rgb):
        """换墨色：只把"生成的字"那些像素重新上色，纸的纹理一点不动。"""
        self.fill = tuple(rgb)
        fresh = self.paper.convert("RGB").copy()
        fresh.paste(self.fill, (0, 0), self.ink_mask)
        self.page = fresh
        self._sync_color_btn()
        if getattr(self, "disp_base", None) is not None:
            pw, ph = self.page.size
            del pw, ph
            self.disp_base = self.page.resize(self._disp_size, Image.LANCZOS)
            self._redraw()
        self._say()

    def _pick_color(self):
        rgb, _ = colorchooser.askcolor(color="#%02x%02x%02x" % self.fill,
                                       title="墨色（生成的字和手写笔迹都用这个色）",
                                       parent=self._win)
        if rgb:
            self._set_color(tuple(int(v) for v in rgb))

    # ------------------------------------------------------------ 工具与笔宽
    def _pick_tool(self, *_):
        self.tool = self._tool_var.get()
        self._say()

    def _tools_changed(self):
        """工具栏四个参数变了：同步到属性，必要时重画笔迹。"""
        v = self.tool_vals
        self.brush = max(1, int(v["brush"]))
        self.pen_width = float(v["pen_width"])
        self.pen_min = float(v["pen_min"])
        self.pen_max = float(v["pen_max"])
        if self.pen_min > self.pen_max:          # 夹住，别让粗细曲线反过来
            self.pen_min = self.pen_max
            v["pen_min"] = self.pen_min
            self.tools.refresh()
        self._rebuild_mask()
        self._redraw()
        self._say()

    # ------------------------------------------------------------ 蒙版存取
    def _current_mask(self):
        """当前的全分辨率墨迹蒙版（白=有墨）：原本的字 − 擦掉的 + 手写的。"""
        size = self.page.size
        base = self.base_mask
        if self.strokes:
            er = Image.new("L", size, 0)
            d = ImageDraw.Draw(er)
            for s in self.strokes:
                _draw_stroke(d, s["pts"], s["w"])
            base = ImageChops.subtract(base, er)
        m = base.copy()
        if self.pens:
            d = ImageDraw.Draw(m)
            for s in self.pens:
                _draw_pen(d, s["pts"], s["w"], self.pen_min, self.pen_max)
        return m

    def _export_mask(self):
        """导出成 PNG 拿去 PS 里涂黑（涂黑=擦掉），再导回来。"""
        path = filedialog.asksaveasfilename(
            parent=self._win, title="导出蒙版（白=有墨）", defaultextension=".png",
            filetypes=[("PNG 图片", "*.png")],
            initialfile="mask_%d.png" % (getattr(self, "index", 0) + 1))
        if not path:
            return
        try:
            self._current_mask().save(path)
            self._say("已导出蒙版：%s" % path)
        except OSError as ex:
            self._say("导出失败：%s" % ex)

    def _import_mask(self):
        path = filedialog.askopenfilename(
            parent=self._win, title="导入蒙版（白=有墨）",
            filetypes=[("图片", "*.png *.bmp *.jpg *.jpeg"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            mask = Image.open(path).convert("L")
        except OSError as ex:
            self._say("导入失败：%s" % ex)
            return
        if mask.size != self.page.size:
            mask = mask.resize(self.page.size, Image.LANCZOS)
        mask = mask.point(lambda v: 255 if v > 127 else 0)
        self._apply_mask(mask)
        self._say("已导入蒙版：%s（%d 个墨点）" % (path, mask.histogram()[255]))

    def _apply_mask(self, mask):
        """把蒙版变成这一页的墨迹；编辑记录清空，之后照样能接着擦/写。"""
        self.page = self.paper.convert("RGB").copy()
        self.page.paste(self.fill, (0, 0), mask)
        self.ink_mask = mask.copy()
        self.base_mask = mask.copy()
        self.strokes, self.pens = [], []
        self._hist, self._hpos = [([], [])], 0
        self._set_zoom(self.zoom)

    # ------------------------------------------------------------ 预设
    def _save_preset(self):
        vals = dict(self.tool_vals)
        vals["fill"] = tuple(self.fill)
        path = save_preset(self._win, vals, "手写笔预设.json")
        if path:
            self._say("已保存预设：%s" % path)

    def _load_preset(self):
        vals = dict(self.tool_vals)
        vals["fill"] = tuple(self.fill)
        path = load_preset(self._win, vals)
        if not path:
            return
        self.tool_vals.update({k: vals[k] for k in self.tool_vals})
        self.tools.refresh()
        self._set_color(tuple(vals["fill"]))
        self._tools_changed()
        self._say("已载入预设：%s" % path)

    def _nudge(self, d):
        if self.tool == "pen":
            self.tool_vals["pen_width"] = max(0.2, min(60, self.pen_width + d))
        else:
            self.tool_vals["brush"] = max(1, min(400, self.brush + d * 6))
        self.tools.refresh()
        self._tools_changed()

    # ------------------------------------------------------------ 压感轮询
    def _poll_pen(self):
        if not (self._win is not None and self._win.winfo_exists()):
            return
        # 消费窗口过程攒下的 pointer 事件。这里是 Tk 的 after 回调，可以安全地
        # 碰 Tcl/PIL；窗口过程里不行（会重入 Tcl，直接崩）。
        # 一 tick 可能攒几十上百条，所以先全部并进笔画、脏区合并，最后只重画一次。
        box = None
        n = 0
        while self._pen.events and n < 4000:
            kind, wx, wy, pr = self._pen.events.popleft()
            if kind == "down":
                self.pen_down(wx, wy, pr)
            elif kind == "up":
                self.pen_up()
            else:
                box = self._union_box(box, self.pen_move(wx, wy, pr, redraw=False))
            n += 1
        if box is not None:
            self._redraw(box)
        self._ticks += 1
        if self._ticks % 4 == 0:            # 约 30Hz 刷一次读数就够了
            p = self._pen.pressure
            n = int(round(p * 10))
            if self._pen.ready:
                t = getattr(self._pen, "types", {})
                txt = "压感 %s %.2f  %s  指针 %d/笔 %d  %s  目标%s" % (
                    "▮" * n + "▯" * (10 - n), p, self._pen.tilt,
                    self._pen.count, self._pen.pen_count,
                    " ".join("%s%d" % (k, v) for k, v in sorted(t.items())) or "-",
                    self._pen.target_kind)
            elif self._pen.error:
                txt = "压感：接不上（%s）" % self._pen.error
            else:
                txt = "压感：未启用（固定力度 %.2f）" % _MOUSE_PRESSURE
            self.pen_lab.config(text=txt)
        self._win.after(8, self._poll_pen)

    def _say(self):
        # 这个会在控件还没建好时被 Scale 回调触发，所以一律 getattr 兜住
        st = getattr(self, "status", None)
        if st is not None:
            st.config(
                text="%s    已擦 %d 笔 / 已写 %d 笔（Ctrl+Z 撤销，[ ] 调笔宽）    "
                     "橡皮 %d px   笔 %g px   压感 %g~%g×   缩放 %d%%"
                     % ("擦除" if self.tool == "erase" else "手写",
                        len(self.strokes), len(self.pens), self.brush,
                        self.pen_width, self.pen_min, self.pen_max,
                        round(self.zoom * 100)))

    # ---------------------------------------------------------------- 收尾
    def _render_output(self):
        """先把擦掉的用纸补回来，再把手写笔迹按墨色盖上去。"""
        if not self.strokes and not self.pens:
            return self.page
        out = self.page.copy()
        size = self.page.size
        if self.strokes:
            m = Image.new("L", size, 0)
            d = ImageDraw.Draw(m)
            for s in self.strokes:
                _draw_stroke(d, s["pts"], s["w"])
            out.paste(self.paper, (0, 0), m)
        if self.pens:
            m = Image.new("L", size, 0)
            d = ImageDraw.Draw(m)
            for s in self.pens:
                _draw_pen(d, s["pts"], s["w"], self.pen_min, self.pen_max)
            out.paste(self.fill, (0, 0), m)
        return out

    def _finish(self, page):
        self.result = page
        self._win.destroy()

    def _do_output(self):
        self._finish(self._render_output())

    def _do_skip(self):
        self._finish(self.page)

    def _do_quit(self):
        self._finish(None)
