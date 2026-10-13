# coding: utf-8
"""随机真实化参数的调参界面：拖滑块看预览，满意了再按全分辨率导出。

关键点（对应"预览和结果纸张位置、桌面位置相同"）：
  * 预览用的是**同一套** opencv_photo_like，只是把图纸缩到 preview_scale，
    并把所有以像素为单位的参数（透视、模糊、阴影偏移/模糊）同比例缩小，
    所以构图、纸在桌上的位置、透视角度都和最终出图一致。
  * 进预览前固定 numpy 随机种子，导出前也固定同一个种子 ——
    于是"预演的那一次摆位"就是"导出的那一次摆位"，不是重新摇一次。

用法（deal.py 里）：
    editor = PhotoEditor(ns)          # ns 是 deal.py 自己的命名空间
    editor.edit(im, i)                # 返回 True 表示用户点了导出
"""
import time
import tkinter as tk

import numpy as np
from PIL import Image, ImageTk

from mask_editor import _shared_root
from param_widgets import ParamPanel, load_preset, save_preset

# 预览比例 / 自动预览 —— 不是 ns 里的参数，所以单独放一个面板
OPTS = [("scale", "预览比例", "float", 0.1, 1.0, 0.02),
        ("auto", "改参数就自动重新预览", "bool", 0, 0, 0)]

# (键名, 名称, 种类, 最小, 最大, 步长, 是否随预览比例缩放)
PARAMS = [
    ("WOOD_TEXTURE_PATH",  "桌面贴图",      "file",  0,    0,    0,    False),
    ("WOOD_ZOOM",          "木纹缩放",      "float", 1.0,  8.0,  0.05, False),
    ("WOOD_SHIFT_X",       "木纹位置 X",    "float", 0.0,  1.0,  0.01, False),
    ("WOOD_SHIFT_Y",       "木纹位置 Y",    "float", 0.0,  1.0,  0.01, False),
    ("DESK_MARGIN",        "桌面留边",      "float", 0.0,  0.5,  0.01, False),
    ("BG_SCALE",           "透视余量",      "float", 1.0,  3.0,  0.01, False),
    ("PERSPECTIVE_OFFSET", "随机透视幅度",  "int",   0,    220,  1,    True),
    ("blur_sigma",         "虚焦",          "float", 0,    6.0,  0.05, True),
    ("motion_blur_size",   "手抖拖影",      "int",   0,    25,   1,    True),
    ("grain_strength",     "传感器噪点",    "int",   0,    60,   1,    False),
    ("GLOBAL_DARKNESS",    "整体亮度",      "float", 0.4,  1.25, 0.01, False),
    ("LIGHT_BASE",         "光照基准",      "int",   120,  255,  1,    False),
    ("VIGNETTE_STRENGTH",  "暗角",          "int",   0,    200,  1,    False),
    ("SHADOW_A_OFFSET",    "接触阴影偏移",  "int",   0,    40,   1,    True),
    ("SHADOW_A_BLUR",      "接触阴影模糊",  "int",   0,    60,   1,    True),
    ("SHADOW_A_ALPHA",     "接触阴影浓度",  "float", 0,    0.6,  0.01, False),
    ("SHADOW_B_OFFSET",    "投影偏移",      "int",   0,    120,  1,    True),
    ("SHADOW_B_BLUR",      "投影模糊",      "int",   0,    150,  1,    True),
    ("SHADOW_B_ALPHA",     "投影浓度",      "float", 0,    0.8,  0.01, False),
]

_KEYS = [p[0] for p in PARAMS]
_PX = {p[0]: p[6] for p in PARAMS}      # 这个参数是不是"以像素为单位"的


class PhotoEditor(object):
    def __init__(self, ns, preview_scale=0.32):
        self.ns = ns
        # values 从 ns 抄一份；ParamPanel 就地改它，点导出时才写回 ns
        self.values = {k: ns[k] for k in _KEYS}
        self.defaults = dict(self.values)
        self.opts = {"scale": preview_scale, "auto": True}
        self.root = _shared_root()
        self._job = None
        self._small = None
        self._page = None
        self._page_id = None
        self._stale = False
        self._cache = {}            # 预览参数指纹 -> 图，省得来回拖重复算

    # ------------------------------------------------------------------ 对外
    def edit(self, page, index=0):
        """返回 True = 用户点了导出（ns 里已经是调好的值）；False = 取消。"""
        self.ok = False             # 窗口以任何别的方式关掉时，edit() 也不能炸
        self.seed = 1000 + index
        self.full = page.size
        self._page = page
        self._rescale_small()       # 缩略图必须先建好，预览要拿它去算
        self._build(index)
        self._refresh_now()
        self.root.wait_window(self._win)
        return self.ok

    def _rescale_small(self):
        s = max(0.05, float(self.opts["scale"]))
        self._small = self._page.resize(
            (max(1, round(self._page.width * s)),
             max(1, round(self._page.height * s))), Image.LANCZOS)
        self._cache.clear()

    # ------------------------------------------------------------ 界面搭建
    def _build(self, index):
        win = self._win = tk.Toplevel(self.root)
        win.title("第 %d 页 · 调整随机真实化（预览是同一套管线，只是缩小了）"
                  % (index + 1))
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = min(1420, sw - 60), min(940, sh - 100)
        win.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, max(10, (sh - h) // 3)))

        left = tk.Frame(win)
        left.pack(side="left", fill="y", padx=6, pady=6)
        tk.Label(left, text="随机真实化参数", font=("Microsoft YaHei", 11, "bold")
                 ).pack(anchor="w")
        specs = [(k, name, kind, lo, hi, step)
                 for k, name, kind, lo, hi, step, _px in PARAMS]
        self.panel = ParamPanel(left, self.values, specs,
                                on_change=self._params_changed, debounce=260)
        self.panel.frame.pack(fill="x")
        tk.Frame(left, height=6).pack()
        self.opt_panel = ParamPanel(left, self.opts, OPTS,
                                    on_change=self._opts_changed, debounce=260)
        self.opt_panel.frame.pack(fill="x")
        btns = tk.Frame(left)
        btns.pack(fill="x", pady=6)
        tk.Button(btns, text="重新预览", command=self._refresh_now).pack(side="left", padx=2)
        tk.Button(btns, text="换一个角度", command=self._reroll).pack(side="left", padx=2)
        tk.Button(btns, text="恢复默认", command=self._reset).pack(side="left", padx=2)
        btns2 = tk.Frame(left)
        btns2.pack(fill="x")
        tk.Button(btns2, text="保存预设", command=self._save).pack(side="left", padx=2)
        tk.Button(btns2, text="载入预设", command=self._load).pack(side="left", padx=2)
        tk.Button(btns2, text="导出本页 ▶", command=self._do_ok).pack(side="left", padx=2)

        right = tk.Frame(win)
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        self.canvas = tk.Canvas(right, bg="#333", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        # 窗口刚建时画布是 1x1，等它长出来要重新贴合一次（图有缓存，不重算）
        self.canvas.bind("<Configure>", lambda e: self._refresh_now())
        self.status = tk.Label(right, anchor="w", font=("Consolas", 10))
        self.status.pack(fill="x")
        win.protocol("WM_DELETE_WINDOW", self._do_cancel)

    # ------------------------------------------------------------------ 预览
    def _fingerprint(self):
        return (self.seed,) + tuple(self.values[k] for k in _KEYS)

    def _render_preview(self):
        ns = self.ns
        s = float(self.opts["scale"])
        for key in _KEYS:                       # 像素量纲的参数跟着缩小
            v = self.values[key]
            ns[key] = round(v * s) if _PX[key] else v
        ns["motion_blur_size"] = int(ns["motion_blur_size"])
        np.random.seed(self.seed)               # 同一个种子 = 同一个摆位
        return ns["opencv_photo_like"](self._small, seed=self.seed)

    def _params_changed(self):
        """参数动了。没勾自动预览就只标记一下，等用户点「重新预览」。"""
        if self.opts["auto"]:
            self._refresh_now()
        else:
            self._stale = True
            self._status("参数已改，点「重新预览」看效果（或勾上自动预览）。")

    def _opts_changed(self):
        self._rescale_small()
        self._refresh_now()

    def _refresh_now(self):
        self._job = None
        if not (self._win is not None and self._win.winfo_exists()):
            return
        self._stale = False
        fp = self._fingerprint()
        t0 = time.perf_counter()
        img = self._cache.get(fp)
        if img is None:
            img = self._render_preview()
            if len(self._cache) > 6:
                self._cache.clear()
            self._cache[fp] = img
        ms = (time.perf_counter() - t0) * 1000
        cw = max(50, self.canvas.winfo_width())
        ch = max(50, self.canvas.winfo_height())
        k = min(cw / img.width, ch / img.height, 1.0)
        show = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))),
                          Image.LANCZOS) if k < 1 else img
        self._photo = ImageTk.PhotoImage(show)
        if self._page_id is None:
            self._page_id = self.canvas.create_image(cw // 2, ch // 2, image=self._photo)
        else:
            self.canvas.itemconfigure(self._page_id, image=self._photo)
            # 画布尺寸会变（刚建时是 1x1），每次都得重新居中，否则图会跑到角上被裁掉
            self.canvas.coords(self._page_id, cw // 2, ch // 2)
        self._status("预览 %dx%d（%.0f%% 比例，实际出图 %dx%d）   本次 %s   种子 %d"
                     % (img.width, img.height, float(self.opts["scale"]) * 100,
                        self.full[0], self.full[1],
                        ("缓存 %.1f ms" % ms) if ms < 3 else ("计算 %.0f ms" % ms),
                        self.seed))

    def _status(self, msg):
        if getattr(self, "status", None) is not None:
            self.status.config(text=msg)

    # ------------------------------------------------------------ 交互
    def _reroll(self):
        self.seed += 1
        self._refresh_now()

    def _reset(self):
        self.values.update(self.defaults)
        self.panel.refresh()
        self._refresh_now()

    def _save(self):
        path = save_preset(self._win, self.values, "真实化预设.json")
        if path:
            self._status("已保存预设：%s" % path)

    def _load(self):
        path = load_preset(self._win, self.values)
        if path:
            self.panel.refresh()
            self._refresh_now()
            self._status("已载入预设：%s" % path)

    # ------------------------------------------------------------ 收尾
    def _do_ok(self):
        self.panel.fire_now()
        # 真正写回 ns 的是**没缩放过**的值
        for key in _KEYS:
            self.ns[key] = self.values[key]
        self.ns["motion_blur_size"] = int(self.values["motion_blur_size"])
        # 导出时要用同一个种子重摇，预览里看到的那个摆位才是最终摆位
        self.ns["photo_seed"] = self.seed
        self.ok = True
        self._win.destroy()

    def _do_cancel(self):
        self.ok = False
        self._win.destroy()
