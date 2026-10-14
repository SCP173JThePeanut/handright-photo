# coding: utf-8
"""设置界面里的「纸张」页：选真纸 / 生成纸，在预览图上拖出写字区域。

一个"区域"= 纸上的一个矩形 + 一段正文。每块各自排版、各自翻页，最后贴回同一张纸。
抬头（姓名/班级/学号…）就是一个小区域，拖到纸上印好的下划线位置即可。

`make_paper()` 是生成纸的**唯一**画法，deal.py 和这里的预览共用，不会跑偏。
"""
import os
import time
import tkinter as tk
from tkinter import filedialog

from PIL import Image, ImageDraw, ImageFont, ImageTk
from mask_editor import _shared_root
from param_widgets import ParamPanel

PAPER_SPECS = [
    ("paper_color", "纸色", "color", 0, 0, 0),
    ("rule_color", "横线色", "color", 0, 0, 0),
    ("rule_width", "横线粗细", "int", 0, 12, 1),
    ("side_line_color", "竖线色", "color", 0, 0, 0),
    ("side_line_width", "竖线粗细", "int", 0, 12, 1),
    ("grain_sigma", "纸纹强度", "int", 0, 40, 1),
    ("grain_alpha", "纸纹浓度", "float", 0, 0.5, 0.01),
]

_HANDLE = 9                      # 右下角拖拽手柄的边长（屏幕像素）


def make_paper(vals):
    """按参数画一张生成纸。deal.py 出图和这里的预览都用它。"""
    w, h = int(vals["w"]), int(vals["h"])
    base = Image.new("RGB", (w, h), tuple(vals["paper_color"]))
    d = ImageDraw.Draw(base)
    fs = int(vals["font_size"])
    ls = max(1, int(vals["line_spacing"]))
    mg = int(vals["margin"])
    try:                          # 第一行横线的位置取决于字体的 ascent
        ascent = ImageFont.truetype(vals["font_path"], size=fs).getmetrics()[0]
    except (OSError, TypeError):
        ascent = int(fs * 0.8)
    y = mg + ls - fs + ascent
    rw = int(vals["rule_width"])
    if rw > 0:                    # 0 = 不要横线（以前会被强行当成 1）
        while y < h - 30:
            d.line((mg - 24, y, w - 30, y), fill=tuple(vals["rule_color"]), width=rw)
            y += ls
    sw = int(vals["side_line_width"])
    if sw > 0:                    # 0 = 不要竖线
        d.line((mg - 24, 0, mg - 24, h), fill=tuple(vals["side_line_color"]), width=sw)
    if vals.get("grain_sigma"):
        noise = Image.effect_noise((w, h), int(vals["grain_sigma"])).convert("RGB")
        base = Image.blend(base, noise, float(vals["grain_alpha"]))
    return base


class PaperTab(object):
    def __init__(self, parent, values, on_change=None):
        self.values = values
        self.on_change = on_change
        self.sel = None
        self._photo = None
        self._img_item = None
        self._k = 1.0
        self._ox = self._oy = 0.0
        self._font_cache = {}
        self._base = None
        self._preview = None
        self._last_bake = 0.0
        self._drag = None
        self._quiet = False
        self.frame = tk.Frame(parent)
        self._build()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        top = tk.Frame(self.frame)
        top.pack(side="top", fill="x", pady=(0, 4))
        self.mode_var = tk.StringVar(value=self.values.get("paper_mode", "gen"))
        tk.Radiobutton(top, text="生成纸", value="gen", variable=self.mode_var,
                       command=self._mode_changed).pack(side="left")
        tk.Radiobutton(top, text="真纸图片", value="photo", variable=self.mode_var,
                       command=self._mode_changed).pack(side="left", padx=(8, 2))
        self.img_var = tk.StringVar(value=self.values.get("paper_image") or "")
        self.img_entry = tk.Entry(top, textvariable=self.img_var, width=34)
        self.img_entry.pack(side="left", padx=(4, 2))
        self.img_entry.bind("<Return>", lambda e: self._image_changed())
        self.img_entry.bind("<FocusOut>", lambda e: self._image_changed())
        self.browse_btn = tk.Button(top, text="浏览…", command=self._browse)
        self.browse_btn.pack(side="left")

        body = tk.Frame(self.frame)
        body.pack(side="top", fill="both", expand=True)

        self.canvas = tk.Canvas(body, bg="#3a3a3a", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.refit())
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        side = tk.Frame(body, width=290)
        side.pack(side="left", fill="y", padx=(6, 0))
        side.pack_propagate(False)

        self.gen_box = tk.LabelFrame(side, text="生成纸参数", padx=4, pady=2)
        self.gen_panel = ParamPanel(self.gen_box, self.values, PAPER_SPECS,
                                    on_change=self._gen_changed, debounce=400)
        self.gen_panel.frame.pack(fill="x")

        self._blocks_label = tk.Label(side, text="写字区域（在左边拖出一个框就是新区域）",
                                      anchor="w")
        self._blocks_label.pack(fill="x", pady=(6, 2))
        self.listbox = tk.Listbox(side, height=8, exportselection=False)
        self.listbox.pack(fill="x")
        self.listbox.bind("<<ListboxSelect>>", self._on_pick)

        btns = tk.Frame(side)
        btns.pack(fill="x", pady=3)
        tk.Button(btns, text="添加一块", command=self._add_block).pack(side="left")
        tk.Button(btns, text="删除选中", command=self._del_block).pack(side="left", padx=2)
        tk.Button(btns, text="铺满整页", command=self._full_block).pack(side="left")

        tk.Label(side, text="名称", anchor="w").pack(fill="x", pady=(4, 0))
        self.name_var = tk.StringVar()
        tk.Entry(side, textvariable=self.name_var).pack(fill="x")
        self.name_var.trace_add("write", lambda *a: self._name_changed())

        # 这一块是正文还是抬头：抬头只在第一页出现，正文写不下会往后翻页
        kind = tk.Frame(side)
        kind.pack(fill="x", pady=(4, 0))
        tk.Label(kind, text="这块是").pack(side="left")
        self.kind_var = tk.StringVar(value="body")
        for text, val in (("正文", "body"), ("抬头·仅首页", "head"),
                          ("抬头·每页", "headall")):
            tk.Radiobutton(kind, text=text, value=val, variable=self.kind_var,
                           command=self._kind_changed).pack(side="left")
        self.kind_tip = tk.Label(side, text="", fg="#777", anchor="w",
                                 wraplength=280, justify="left")
        self.kind_tip.pack(fill="x")

        # 字在框里怎么摆。默认左上角，和以前一样。
        ali = tk.Frame(side)
        ali.pack(fill="x", pady=(3, 0))
        tk.Label(ali, text="水平").pack(side="left")
        self.ah_var = tk.StringVar(value="left")
        for t, v in (("左", "left"), ("中", "center"), ("右", "right")):
            tk.Radiobutton(ali, text=t, value=v, variable=self.ah_var,
                           command=self._align_changed).pack(side="left")
        tk.Label(ali, text=" 垂直").pack(side="left")
        self.av_var = tk.StringVar(value="top")
        for t, v in (("上", "top"), ("中", "middle"), ("下", "bottom")):
            tk.Radiobutton(ali, text=t, value=v, variable=self.av_var,
                           command=self._align_changed).pack(side="left")

        # 微调：对齐只是粗放三段式，纸印好的横线未必落在行距整数倍上，得能自己 nudge
        self.tweak = {"dx": 0, "dy": 0}
        self.tweak_panel = ParamPanel(side, self.tweak,
                                      [("dx", "微调 左右（px）", "int", -400, 400, 1),
                                       ("dy", "微调 上下（px）", "int", -400, 400, 1)],
                                      on_change=self._tweak_changed, debounce=250)
        self.tweak_panel.frame.pack(fill="x", pady=(2, 0))

        # 这一块自己的字号 / 行距。0 = 跟随「常规」页里的全局值。
        # 字号改小，字形的笔画也会跟着变细（那是字体本身的粗细，不是笔变细了）。
        siz = tk.Frame(side)
        siz.pack(fill="x", pady=(4, 0))
        tk.Label(siz, text="字号").pack(side="left")
        self.size_var = tk.StringVar()
        e = tk.Entry(siz, textvariable=self.size_var, width=6, justify="right")
        e.pack(side="left", padx=(2, 8))
        e.bind("<Return>", lambda ev: self._num_changed())
        e.bind("<FocusOut>", lambda ev: self._num_changed())
        tk.Label(siz, text="行距").pack(side="left")
        self.space_var = tk.StringVar()
        e2 = tk.Entry(siz, textvariable=self.space_var, width=6, justify="right")
        e2.pack(side="left", padx=2)
        e2.bind("<Return>", lambda ev: self._num_changed())
        e2.bind("<FocusOut>", lambda ev: self._num_changed())
        self.size_hint = tk.Label(side, text="", fg="#777", anchor="w", justify="left",
                                  wraplength=270)
        self.size_hint.pack(fill="x")

        self.text_label = tk.Label(side, text="这一块写什么", anchor="w")
        self.text_label.pack(fill="x", pady=(6, 0))
        self.text = tk.Text(side, height=10, wrap="word", undo=True)
        self.text.pack(fill="both", expand=True)
        self.text.bind("<KeyRelease>", lambda e: self._text_changed())

        self._mode_changed(refit=False)
        self._select(None)

    # ------------------------------------------------------------------ 纸面
    def _gen_changed(self):
        self.refit()
        if self.on_change:
            self.on_change()

    def _mode_changed(self, refit=True):
        photo = self.mode_var.get() == "photo"
        self.values["paper_mode"] = self.mode_var.get()
        self.gen_box.pack_forget()
        if not photo:
            # 用 before= 固定插在最上面，否则来回切模式顺序会乱
            self.gen_box.pack(side="top", fill="x", pady=(0, 4),
                              before=self._blocks_label)
        self.img_entry.config(state="normal" if photo else "disabled")
        self.browse_btn.config(state="normal" if photo else "disabled")
        if refit:
            self.refit()
        if self.on_change:
            self.on_change()

    def _browse(self):
        p = filedialog.askopenfilename(
            parent=self.frame, title="选一张作业纸图片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp *.webp"), ("所有文件", "*.*")])
        if p:
            self.img_var.set(p.replace("\\", "/"))
            self._image_changed()

    def _image_changed(self):
        self.values["paper_image"] = self.img_var.get().strip()
        self.refit()
        if self.on_change:
            self.on_change()

    def _paper_at(self, dw, dh):
        """按显示尺寸弄一张纸出来（真纸直接缩放，生成纸按比例现画）。"""
        w, h = int(self.values["w"]), int(self.values["h"])
        if self.mode_var.get() == "photo":
            p = (self.values.get("paper_image") or "").strip()
            if p and os.path.exists(p):
                try:
                    return Image.open(p).convert("RGB").resize((dw, dh), Image.LANCZOS)
                except OSError:
                    pass
            ph = Image.new("RGB", (dw, dh), (60, 60, 60))
            ImageDraw.Draw(ph).text((10, 10), "找不到纸图片", fill=(230, 230, 230))
            return ph
        # 生成纸：按屏幕大小缩着画。3072×4095 每拖一下就整幅重画太慢。
        s = dw / float(w)
        small = dict(self.values)
        small["w"], small["h"] = dw, dh
        for key in ("font_size", "line_spacing", "margin"):
            small[key] = max(1, int(int(self.values[key]) * s))
        for key in ("rule_width", "side_line_width"):    # 0 就保持 0（=不要这条线）
            v = int(self.values[key])
            small[key] = max(1, int(v * s)) if v > 0 else 0
        return make_paper(small)

    def _sys_font(self, px):
        """预览用的普通字体（不是手写体）。看清楚大小和位置就够了。"""
        px = max(6, int(px))
        if px not in self._font_cache:
            f = None
            for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                         "C:/Windows/Fonts/simsun.ttc"):
                if os.path.exists(path):
                    try:
                        f = ImageFont.truetype(path, size=px)
                        break
                    except OSError:
                        pass
            self._font_cache[px] = f or ImageFont.load_default()
        return self._font_cache[px]

    def _draw_text_preview(self, img, k):
        """把每块的字用普通字体画上去 —— 这样改字号/行距/对齐能立刻看见效果。"""
        d = ImageDraw.Draw(img)
        for b in self.values.get("blocks") or []:
            text = (b.get("text") or "").strip()
            if not text:
                continue
            size = int(b.get("size") or 0) or int(self.values["font_size"])
            spacing = int(b.get("spacing") or 0) or int(self.values["line_spacing"])
            fnt = self._sys_font(size * k)
            x0, y0 = b["x"] * k, b["y"] * k
            maxw, maxh = b["w"] * k, b["h"] * k
            step = max(2.0, spacing * k)
            # 先按宽度折行
            lines, cur = [], ""
            for ch in text:
                if ch == "\n":
                    lines.append(cur)
                    cur = ""
                elif cur and d.textlength(cur + ch, font=fnt) > maxw:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            lines.append(cur)
            lines = lines[:max(1, int(maxh // step))]
            total = len(lines) * step
            ha = b.get("align_h") or "left"
            va = b.get("align_v") or "top"
            dy = {"top": 0.0, "middle": (maxh - total) / 2.0,
                  "bottom": maxh - total}.get(va, 0.0) + int(b.get("dy") or 0) * k
            xshift = int(b.get("dx") or 0) * k
            for i, ln in enumerate(lines):
                if not ln:
                    continue
                dx = {"left": 0.0, "center": (maxw - d.textlength(ln, font=fnt)) / 2.0,
                      "right": maxw - d.textlength(ln, font=fnt)}.get(ha, 0.0)
                d.text((x0 + dx + xshift, y0 + dy + i * step), ln,
                       fill=(90, 96, 110), font=fnt)

    def refit(self):
        cw = max(50, self.canvas.winfo_width())
        ch = max(50, self.canvas.winfo_height())
        w, h = int(self.values["w"]), int(self.values["h"])
        self._k = min(cw / float(w), ch / float(h))
        self._ox = (cw - w * self._k) / 2.0        # 画布比纸宽，就居中放
        self._oy = (ch - h * self._k) / 2.0
        dw, dh = max(1, int(w * self._k)), max(1, int(h * self._k))
        self._base = self._paper_at(dw, dh)        # 纸本身（不带字），文字每次现画
        self._rebake()
        self.redraw()
        self._refresh_list()

    def _rebake(self):
        """把字重新画到纸上。区域挪了位置就得重来一遍，否则字还留在原地。"""
        if self._base is None:
            return
        img = self._base.copy()
        self._draw_text_preview(img, self._k)
        self._preview = img                       # 留一份，方便排查/自检
        self._photo = ImageTk.PhotoImage(img)
        if self._img_item is not None and self.canvas.find_withtag(self._img_item):
            self.canvas.itemconfigure(self._img_item, image=self._photo)

    # ------------------------------------------------------------------ 画布
    def _to_img(self, cx, cy):
        return (cx - self._ox) / self._k, (cy - self._oy) / self._k

    def _to_cv(self, ix, iy):
        return ix * self._k + self._ox, iy * self._k + self._oy

    def redraw(self):
        c = self.canvas
        c.delete("all")
        self._img_item = c.create_image(self._ox, self._oy, anchor="nw",
                                        image=self._photo)
        step = max(4.0, float(self.values["line_spacing"]) * self._k)
        for i, b in enumerate(self.values.get("blocks") or []):
            x0, y0 = self._to_cv(b["x"], b["y"])
            x1, y1 = self._to_cv(b["x"] + b["w"], b["y"] + b["h"])
            on = (i == self.sel)
            # 抬头绿色、正文蓝色，选中的描红 —— 一眼看出哪块是干什么的
            base = "#12b76a" if (b.get("kind") or "body").startswith("head") \
                else "#2f9bff"
            col = "#ff4d4f" if on else base
            c.create_rectangle(x0, y0, x1, y1, outline=col, width=3 if on else 2,
                               dash=() if on else (5, 3))
            # 行位置参考线：照着纸上印好的横线对。这块有自己的行距就用自己的
            own = max(4.0, float(b.get("spacing") or 0) * self._k) if b.get("spacing") \
                else step
            yy = y0
            while yy < y1 - 1:
                c.create_line(x0, yy, x1, yy, fill="#9ad0ff", dash=(2, 5))
                yy += own
            c.create_text(x0 + 5, y0 - 2, anchor="sw",
                          text="%s %s" % ({"head": "抬", "headall": "抬*"}.get(
                              b.get("kind") or "body", "正"),
                              b.get("name") or "?"),
                          fill=col, font=("Microsoft YaHei", 9, "bold"))
            if on:                       # 右下角手柄
                c.create_rectangle(x1 - _HANDLE, y1 - _HANDLE, x1, y1,
                                   fill=col, outline=col)

    def _hit(self, ix, iy):
        """返回 (下标, 部位)；部位是 'move' 或 'resize'。"""
        blocks = self.values.get("blocks") or []
        pad = _HANDLE / self._k
        for i in range(len(blocks) - 1, -1, -1):
            b = blocks[i]
            if i == self.sel and abs(ix - (b["x"] + b["w"])) < pad \
                    and abs(iy - (b["y"] + b["h"])) < pad:
                return i, "resize"
            if b["x"] <= ix <= b["x"] + b["w"] and b["y"] <= iy <= b["y"] + b["h"]:
                return i, "move"
        return None, None

    def _on_press(self, e):
        ix, iy = self._to_img(e.x, e.y)
        i, part = self._hit(ix, iy)
        if i is None:                     # 空白处按下 = 拉一个新框
            self._drag = ("new", ix, iy, ix, iy)
        else:
            self._select(i)
            b = self.values["blocks"][i]
            self._drag = (part, ix, iy, b["x"], b["y"], b["w"], b["h"])
        self.redraw()

    def _on_motion(self, e):
        if not self._drag:
            return
        ix, iy = self._to_img(e.x, e.y)
        w, h = int(self.values["w"]), int(self.values["h"])
        ix = min(max(ix, 0), w)
        iy = min(max(iy, 0), h)
        d = self._drag
        if d[0] == "new":
            self._drag = ("new", d[1], d[2], ix, iy)
        elif d[0] == "move":
            b = self.values["blocks"][self.sel]
            b["x"] = int(min(max(d[3] + ix - d[1], 0), w - b["w"]))
            b["y"] = int(min(max(d[4] + iy - d[2], 0), h - b["h"]))
        else:
            b = self.values["blocks"][self.sel]
            b["w"] = int(min(max(d[5] + ix - d[1], 20), w - b["x"]))
            # 高度不能小于这一块的行距，否则 handright 排不下第一行会直接报错
            b["h"] = int(min(max(d[6] + iy - d[2], self._block_min_h(b)), h - b["y"]))
        # 拖动过程中顺手把字也重画一遍（限流 80ms，不然每个鼠标事件都整幅重画）
        now = time.time()
        if now - self._last_bake > 0.08:
            self._last_bake = now
            self._rebake()
        self.redraw()

    def _min_h(self):
        return max(8, int(self.values["line_spacing"]))

    def _block_min_h(self, b):
        """这块自己的行距（0 = 跟随全局）；handright 要求区域至少放得下一行。"""
        return max(8, int(b.get("spacing") or 0) or int(self.values["line_spacing"]))

    def _on_release(self, e):
        d, self._drag = self._drag, None
        if d and d[0] == "new":
            x0, y0, x1, y1 = d[1], d[2], d[3], d[4]
            if abs(x1 - x0) < 12 or abs(y1 - y0) < self._min_h():
                return                    # 点一下、或者框太扁，都不算
            self._add_block(int(min(x0, x1)), int(min(y0, y1)),
                            int(abs(x1 - x0)), int(abs(y1 - y0)))
            return
        self.refit()                      # 松手后按最终位置重画一遍，字跟着走

    # ------------------------------------------------------------------ 区域
    def _blocks(self):
        if self.values.get("blocks") is None:
            self.values["blocks"] = []
        return self.values["blocks"]

    def _add_block(self, x=None, y=None, bw=None, bh=None):
        w, h = int(self.values["w"]), int(self.values["h"])
        mg = int(self.values["margin"])
        b = {"name": "区域%d" % (len(self._blocks()) + 1), "text": "",
             "kind": "body",
             "x": mg if x is None else x, "y": mg if y is None else y,
             "w": (w - 2 * mg) if bw is None else bw,
             "h": max(self._min_h(), (h - 2 * mg) if bh is None else bh)}
        self._blocks().append(b)
        self._refresh_list()
        self._select(len(self._blocks()) - 1)
        self.refit()                      # 新框里的字也要画出来
        if self.on_change:
            self.on_change()

    def _full_block(self):
        w, h = int(self.values["w"]), int(self.values["h"])
        mg = int(self.values["margin"])
        self._add_block(mg, mg, w - 2 * mg, h - 2 * mg)

    def _del_block(self):
        if self.sel is None:
            return
        del self._blocks()[self.sel]
        self.sel = None
        self._refresh_list()
        self._select(None)
        self.refit()                      # 这块的字也要跟着消失
        if self.on_change:
            self.on_change()

    def _select(self, i):
        self.sel = i
        self.listbox.selection_clear(0, "end")
        if i is not None:
            self.listbox.selection_set(i)
            self.listbox.see(i)
        self._quiet = True
        b = None if i is None else self._blocks()[i]
        self.name_var.set("" if b is None else (b.get("name") or ""))
        self.kind_var.set("body" if b is None else (b.get("kind") or "body"))
        self.ah_var.set("left" if b is None else (b.get("align_h") or "left"))
        self.av_var.set("top" if b is None else (b.get("align_v") or "top"))
        self.tweak["dx"] = 0 if b is None else int(b.get("dx") or 0)
        self.tweak["dy"] = 0 if b is None else int(b.get("dy") or 0)
        if getattr(self, "tweak_panel", None) is not None:
            self.tweak_panel.refresh()
        self.size_var.set("" if b is None else str(int(b.get("size") or 0)))
        self.space_var.set("" if b is None else str(int(b.get("spacing") or 0)))
        self.text.delete("1.0", "end")
        if b is not None:
            self.text.insert("1.0", b.get("text") or "")
        self._quiet = False
        self._hint()

    def _hint(self):
        """把"0 就是跟随全局"和"这一块实际会用多少"说清楚。"""
        if self.sel is None:
            self.text_label.config(text="这一块写什么")
            self.kind_tip.config(text="")
            self.size_hint.config(
                text=("选中左边列表里的一块，就能改它的名称/类型/字号/内容。"
                      if self.values.get("blocks") else
                      "还没有区域 —— 在左边纸上拖一个框就是一块。"
                      "正文就拖一个大框（写不下会自动翻页），"
                      "抬头拖到印好的下划线上并选「抬头」（只在第一页出现）。"))
            return
        b = self._blocks()[self.sel]
        self.kind_tip.config(
            text={"body": "正文：写不下会顺着往后翻页",
                  "head": "抬头（仅首页）：只在第 1 页出现，翻页后不再写",
                  "headall": "抬头（每页）：每一页的同一位置都写一遍"
                  }.get(b.get("kind") or "body", ""))
        gs, gp = int(self.values["font_size"]), int(self.values["line_spacing"])
        s = int(b.get("size") or 0) or gs
        p = int(b.get("spacing") or 0) or gp
        self.text_label.config(text="「%s」写什么" % (b.get("name") or "?"))
        extra = ""
        if s > p:
            extra = "  ⚠ 行距必须 ≥ 字号"
        # 字号变了，字体本身的笔画粗细也跟着变（实测 ≈ 0.08 × 字号）——
        # 这不是笔变细了，是字形按比例缩了。想保持观感就往小了别调太多。
        note = ""
        if s != gs:
            note = ("　笔画粗细：全局约 %.1fpx，这一块约 %.1fpx（字体本身按比例缩，不是笔变细）"
                    % (gs * 0.08, s * 0.08))
        self.size_hint.config(
            text="字号/行距填 0 = 跟随全局（%d / %d），填了只影响这一块 → 实际 %d / %d%s%s"
                 % (gs, gp, s, p, extra, note))

    def _num_changed(self):
        if self._quiet or self.sel is None:
            return
        b = self._blocks()[self.sel]
        for var, key in ((self.size_var, "size"), (self.space_var, "spacing")):
            raw = var.get().strip()
            try:
                b[key] = max(0, int(float(raw))) if raw else 0
            except ValueError:
                var.set(str(int(b.get(key) or 0)))
        # handright 要求行距 ≥ 字号，否则直接报错。这里顺手把行距顶上去。
        gs, gp = int(self.values["font_size"]), int(self.values["line_spacing"])
        size = int(b.get("size") or 0) or gs
        space = int(b.get("spacing") or 0) or gp
        if size > space:
            b["spacing"] = size
            self._quiet = True
            self.space_var.set(str(size))
            self._quiet = False
        self._hint()
        self.refit()                     # 字号/行距变了，预览里的字要跟着重画
        self._refresh_list()
        if self.on_change:
            self.on_change()

    def _on_pick(self, _e):
        sel = self.listbox.curselection()
        if sel:
            self._select(sel[0])
            self.redraw()

    def _kind_changed(self):
        if self._quiet or self.sel is None:
            return
        self._blocks()[self.sel]["kind"] = self.kind_var.get()
        self._hint()
        self._refresh_list()
        self.redraw()
        if self.on_change:
            self.on_change()

    def _tweak_changed(self):
        if self._quiet or self.sel is None:
            return
        b = self._blocks()[self.sel]
        b["dx"] = int(self.tweak["dx"])
        b["dy"] = int(self.tweak["dy"])
        self.refit()
        if self.on_change:
            self.on_change()

    def _align_changed(self):
        if self._quiet or self.sel is None:
            return
        b = self._blocks()[self.sel]
        b["align_h"] = self.ah_var.get()
        b["align_v"] = self.av_var.get()
        self.refit()                  # 预览里的字要跟着挪
        if self.on_change:
            self.on_change()

    def _name_changed(self):
        if self._quiet or self.sel is None:
            return
        self._blocks()[self.sel]["name"] = self.name_var.get()
        self._refresh_list()
        self.redraw()

    def _text_changed(self):
        if self._quiet or self.sel is None:
            return
        self._blocks()[self.sel]["text"] = self.text.get("1.0", "end-1c")
        # 每敲一个字就整幅重画太浪费，等一下再画
        if getattr(self, "_tjob", None) is not None:
            self.frame.after_cancel(self._tjob)
        self._tjob = self.frame.after(400, self.refit)

    def _refresh_list(self):
        self.listbox.delete(0, "end")
        for i, b in enumerate(self.values.get("blocks") or []):
            n = (b.get("text") or "").strip().replace("\n", " ")
            self.listbox.insert("end", "[%s] %s   %s"
                                % ({"head": "抬", "headall": "抬*"}.get(
                                    b.get("kind") or "body", "正"),
                                   b.get("name") or "?",
                                   (n[:14] + "…") if len(n) > 14 else n))
        if self.sel is not None and self.sel < self.listbox.size():
            self.listbox.selection_set(self.sel)

    # ------------------------------------------------------------------ 收尾
    def reload(self):
        """values 被整体换过之后（载入预设 / 恢复默认设置），把控件同步过来。

        少了这一步，载入预设之后单选钮和图片路径还停在旧值上 ——
        refit() 和 commit() 读的都是控件，于是预览和出图都还是旧纸。
        """
        self.mode_var.set(self.values.get("paper_mode") or "gen")
        self.img_var.set(self.values.get("paper_image") or "")
        self.sel = None
        self._mode_changed(refit=False)
        self._refresh_list()
        self._select(None)
        self.refit()

    def commit(self):
        """确定前把文本控件里的内容收进来。"""
        self._text_changed()
        self.values["paper_mode"] = self.mode_var.get()
        self.values["paper_image"] = self.img_var.get().strip()
