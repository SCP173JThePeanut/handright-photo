# coding: utf-8
"""最前面的设置界面：出图尺寸、字体、纸张、手写抖动、手写笔、页眉、桌面、开关。

跑在 deal.py 生成任何东西**之前**，所以字号、尺寸这类会影响版面的参数改了立刻生效。
每一行都是「滑块 + 输入框」：滑块快速试，输入框直接敲准确值。

预设：可以把当前这一整套存成 .json，之后载回来；「恢复默认」回到代码里的初值。
"""
import json
import os
import tkinter as tk
from tkinter import filedialog

from mask_editor import _shared_root
from param_widgets import COLOR_KEYS, ParamPanel, load_preset, save_preset

SETTINGS_FILE = "handwrite_settings.json"       # 「记住修改」存这里

SIZE_PRESETS = [("2048×2731", 2048, 2731), ("2480×3508（A4 300dpi）", 2480, 3508),
                ("3072×4095（默认）", 3072, 4095), ("3500×4667", 3500, 4667),
                ("4096×5461", 4096, 5461)]

SECTIONS = [
    ("出图尺寸", [
        ("w", "图片宽", "int", 800, 8000, 1),
        ("h", "图片高", "int", 800, 11000, 1),
        ("margin", "页边距", "int", 0, 400, 1),
        ("font_size", "字号", "int", 20, 400, 1),
        ("line_spacing", "行距", "int", 20, 600, 1),
    ]),
    ("字体", [
        ("font_path", "手写字体", "file", 0, 0, 0),
        ("fallback_scale", "回退字号比例", "float", 0.3, 3.0, 0.05),
        ("fallback_thin", "回退笔画磨细", "int", 0, 4, 1),
    ]),
    ("纸张", [
        ("paper_color", "纸色", "color", 0, 0, 0),
        ("rule_color", "横线色", "color", 0, 0, 0),
        ("rule_width", "横线粗细", "int", 0, 12, 1),
        ("side_line_color", "竖线色", "color", 0, 0, 0),
        ("side_line_width", "竖线粗细", "int", 0, 12, 1),
        ("grain_sigma", "纸纹强度", "int", 0, 40, 1),
        ("grain_alpha", "纸纹浓度", "float", 0, 0.5, 0.01),
    ]),
    ("手写抖动", [
        ("fill", "墨色", "color", 0, 0, 0),
        ("word_spacing", "字间距", "int", -20, 60, 1),
        ("line_spacing_sigma", "行位置抖动", "float", 0, 20, 0.5),
        ("font_size_sigma", "字号抖动", "float", 0, 20, 0.5),
        ("word_spacing_sigma", "字距抖动", "float", 0, 20, 0.5),
        ("perturb_x_sigma", "笔画 X 抖动", "float", 0, 20, 0.5),
        ("perturb_y_sigma", "笔画 Y 抖动", "float", 0, 20, 0.5),
        ("perturb_theta_sigma", "笔画旋转抖动", "float", 0, 0.5, 0.005),
    ]),
    ("手写笔", [
        ("pen_width", "笔宽", "float", 0.5, 40, 0.5),
        ("pen_min", "压感最细（倍）", "float", 0.01, 4.0, 0.01),
        ("pen_max", "压感最粗（倍）", "float", 0.05, 8.0, 0.05),
        ("eraser", "橡皮大小", "int", 6, 400, 1),
    ]),
    ("页眉", [
        ("page_header", "每页第一行", "text", 0, 0, 0),
    ]),
    # 桌面贴图 / 木纹缩放 / 桌面留边这些放到最后出图那个窗口（PhotoEditor）里调，
    # 前面生成时用不到。
    ("开关", [
        ("interactive", "逐页编辑（擦除/手写）", "bool", 0, 0, 0),
        ("tune_photo", "生成后调光照阴影", "bool", 0, 0, 0),
        ("seed", "随机种子", "int", 0, 99999999, 1),
    ]),
]


class SettingsEditor(object):
    def __init__(self, defaults):
        self.defaults = dict(defaults)
        self.values = dict(defaults)
        self.root = _shared_root()
        self.remembered = self._load_remembered()

    # -------------------------------------------------------- 记住上次的修改
    def _load_remembered(self):
        if not os.path.exists(SETTINGS_FILE):
            return False
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        for key, val in data.items():
            if key not in self.values:
                continue
            if key in COLOR_KEYS and isinstance(val, (list, tuple)):
                val = tuple(int(v) for v in val)
            self.values[key] = val
        return True

    def _forget(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                os.remove(SETTINGS_FILE)
        except OSError:
            pass

    def edit(self):
        """返回改好的值字典；用户取消返回 None。"""
        self.ok = False
        self._build()
        self.root.wait_window(self._win)
        return self.values if self.ok else None

    # ------------------------------------------------------------------ 构建
    def _build(self):
        win = self._win = tk.Toplevel(self.root)
        win.title("生成设置的默认值 · 每一行都能直接在右边输入框里敲数字")
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = min(1000, sw - 80), min(940, sh - 100)
        win.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, max(10, (sh - h) // 4)))

        size = tk.Frame(win)
        size.pack(side="top", fill="x", padx=8, pady=(6, 0))
        tk.Label(size, text="常用尺寸：").pack(side="left")
        for text, pw, ph in SIZE_PRESETS:
            tk.Button(size, text=text, command=lambda a=pw, b=ph: self._set_size(a, b)
                      ).pack(side="left", padx=2)
        tk.Button(size, text="字号/行距按宽度重算", command=self._rescale_font
                  ).pack(side="left", padx=8)

        # 参数区做成可滚动的：参数多，窗口放不下
        body = tk.Frame(win)
        body.pack(side="top", fill="both", expand=True, padx=8, pady=6)
        canvas = tk.Canvas(body, highlightthickness=0)
        vsb = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        for wgt in (canvas, inner):
            wgt.bind("<MouseWheel>",
                     lambda e: canvas.yview_scroll(-e.delta // 120, "units"))

        self.panels = []
        for title, specs in SECTIONS:
            box = tk.LabelFrame(inner, text=title, padx=6, pady=3)
            box.pack(fill="x", pady=3)
            p = ParamPanel(box, self.values, specs, on_change=self._changed)
            p.frame.pack(fill="x")
            self.panels.append(p)

        # 正文：直接在这里写，或者整套导入/导出成 .txt 当模板
        tbox = tk.LabelFrame(inner, text="正文", padx=6, pady=3)
        tbox.pack(fill="both", expand=True, pady=3)
        tbar = tk.Frame(tbox)
        tbar.pack(fill="x")
        tk.Button(tbar, text="导入模板 .txt", command=self._import_text).pack(side="left")
        tk.Button(tbar, text="导出模板 .txt", command=self._export_text).pack(side="left", padx=2)
        tk.Label(tbar, text="（也可以直接在下面改；改过的会被记住）",
                 fg="#777").pack(side="left", padx=6)
        self.text_widget = tk.Text(tbox, height=12, wrap="word", undo=True)
        self.text_widget.pack(fill="both", expand=True, pady=(3, 0))
        self.text_widget.insert("1.0", self.values.get("text") or "")

        foot = tk.Frame(win)
        foot.pack(side="bottom", fill="x", padx=8, pady=6)
        self.status = tk.Label(foot, anchor="w", fg="#555")
        self.status.pack(side="left")
        tk.Button(foot, text="开始生成 ▶", command=self._do_ok).pack(side="right", padx=2)
        tk.Button(foot, text="取消", command=self._do_cancel).pack(side="right", padx=2)
        tk.Button(foot, text="载入预设", command=self._load_preset).pack(side="right", padx=2)
        tk.Button(foot, text="保存预设", command=self._save_preset).pack(side="right", padx=2)
        tk.Button(foot, text="恢复默认设置", command=self._reset).pack(side="right", padx=2)
        win.protocol("WM_DELETE_WINDOW", self._do_cancel)
        self._say("改完点「开始生成」。每行右边的输入框可以直接敲准确值；"
                  + ("上次的修改已经帮你载入了。" if self.remembered else ""))

    # ------------------------------------------------------------------ 正文
    def _grab_text(self):
        self.values["text"] = self.text_widget.get("1.0", "end-1c")

    def _import_text(self):
        path = filedialog.askopenfilename(
            parent=self._win, title="导入正文模板",
            filetypes=[("文本", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                body = f.read()
        except OSError as ex:
            self._say("导入失败：%s" % ex)
            return
        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", body)
        self._grab_text()
        self._say("已导入正文：%s" % path)

    def _export_text(self):
        path = filedialog.asksaveasfilename(
            parent=self._win, title="导出正文模板", defaultextension=".txt",
            filetypes=[("文本", "*.txt")], initialfile="正文模板.txt")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text_widget.get("1.0", "end-1c"))
            self._say("已导出正文：%s" % path)
        except OSError as ex:
            self._say("导出失败：%s" % ex)

    # ------------------------------------------------------------------ 快捷
    def _set_size(self, pw, ph):
        self.values["w"], self.values["h"] = pw, ph
        self._sync()
        self._rescale_font()

    def _rescale_font(self):
        w = int(self.values["w"])
        self.values["font_size"] = max(20, w // 35)
        self.values["line_spacing"] = int(1.43 * self.values["font_size"])
        self.values["margin"] = max(0, round(w / 43.9))
        self._sync()
        self._say("字号/行距/页边距已按宽度 %d 重算。" % w)

    def _sync(self):
        for p in self.panels:
            p.refresh()

    def _changed(self):
        self._say("")

    def _say(self, msg):
        if getattr(self, "status", None) is not None:
            self.status.config(text=msg)

    # ------------------------------------------------------------------ 预设
    def _save_preset(self):
        self._grab_text()
        path = save_preset(self._win, self.values, "我的生成设置.json")
        if path:
            self._say("已保存预设：%s" % path)

    def _load_preset(self):
        path = load_preset(self._win, self.values)
        if not path:
            return
        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", self.values.get("text") or "")
        self._sync()
        self._say("已载入预设：%s" % path)

    def _reset(self):
        for key, val in self.defaults.items():
            self.values[key] = tuple(val) if key in COLOR_KEYS and isinstance(val, (list, tuple)) \
                else val
        self._forget()                  # 连"记住的修改"一起清掉，否则下次又冒出来
        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", self.values.get("text") or "")
        self._sync()
        self._say("已恢复成代码里的默认值，并清掉了记住的修改。")

    # ------------------------------------------------------------------ 收尾
    def _do_ok(self):
        for p in self.panels:
            p.fire_now()
        self._grab_text()
        try:                            # 记住这次的修改，下次开自动带出来
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({k: (list(v) if k in COLOR_KEYS and isinstance(v, (list, tuple)) else v)
                           for k, v in self.values.items()},
                          f, ensure_ascii=False, indent=2)
        except OSError as ex:
            print("保存设置失败（下次不会记住）：%s" % ex)
        self.ok = True
        self._win.destroy()

    def _do_cancel(self):
        self.ok = False
        self._win.destroy()
