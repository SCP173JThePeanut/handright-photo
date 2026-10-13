# coding: utf-8
"""通用参数行：滑块 + 手动输入框（+ 文件选择 / 颜色）。

滑块用来快速试，输入框用来打准确值，两边双向同步 ——
所以任何参数都不再受滑块两端范围的限制，直接敲数字就行。

三个界面（设置 / 逐页编辑 / 调参）共用这一套，加参数只要往 spec 列表里加一行。
"""
import json
import tkinter as tk
from tkinter import colorchooser, filedialog

COLOR_PRESETS = [("黑", (20, 20, 20)), ("深灰", (30, 30, 35)), ("蓝黑", (26, 34, 62)),
                 ("纯蓝", (28, 52, 140)), ("红", (150, 40, 40))]

# 色值在 JSON 里是 list，读回来要转成 tuple 才能喂给 PIL
COLOR_KEYS = ("paper_color", "rule_color", "side_line_color", "fill")

_LABEL_W = 14
_SCALE_LEN = 170
_ENTRY_W = 8


class ParamPanel(object):
    """一堆参数行的集合。

    specs: [(key, 显示名, 种类, lo, hi, step)]
      种类 = "float" / "int" / "color" / "file" / "text" / "bool"
      lo/hi/step 对 text/file/color/bool 无效，填 0 即可。
    values: 字典，**就地修改**；界面显示的就是它当前的值。
    """

    def __init__(self, parent, values, specs, on_change=None, debounce=300,
                 row_pack="top", label_w=_LABEL_W, scale_len=_SCALE_LEN):
        self.values = values
        self.specs = specs
        self.on_change = on_change
        self.debounce = debounce
        self.row_pack = row_pack          # "top" 竖着一列，"left" 横着一条工具栏
        self.label_w = label_w
        self.scale_len = scale_len
        self.frame = tk.Frame(parent)
        self.rows = {}
        self._job = None
        self._quiet = False
        self._build()

    # ------------------------------------------------------------------ 构建
    def _build(self):
        for key, label, kind, lo, hi, step in self.specs:
            row = tk.Frame(self.frame)
            row.pack(side=self.row_pack, fill="x" if self.row_pack == "top" else None,
                     pady=1 if self.row_pack == "top" else 0,
                     padx=0 if self.row_pack == "top" else 3)
            tk.Label(row, text=label, width=self.label_w, anchor="w").pack(side="left")
            v = self.values.get(key)
            if kind == "bool":
                var = tk.BooleanVar(value=bool(v))
                tk.Checkbutton(row, variable=var,
                               command=lambda k=key: self._typed(k)
                               ).pack(side="left")
                self.rows[key] = {"kind": kind, "var": var}
                continue
            if kind in ("text", "file"):
                var = tk.StringVar(value="" if v is None else str(v))
                ent = tk.Entry(row, textvariable=var, width=42)
                ent.pack(side="left", fill="x", expand=True)
                ent.bind("<Return>", lambda e, k=key: self._typed(k))
                ent.bind("<FocusOut>", lambda e, k=key: self._typed(k))
                if kind == "file":
                    tk.Button(row, text="浏览…", command=lambda k=key: self._browse(k)
                              ).pack(side="left", padx=2)
                self.rows[key] = {"kind": kind, "var": var, "entry": ent}
                continue
            if kind == "color":
                btn = tk.Button(row, text="      ", relief="raised",
                                command=lambda k=key: self._pick_color(k))
                btn.pack(side="left")
                ent = None
                self.rows[key] = {"kind": kind, "btn": btn}
                self._paint(key)
                continue
            # 数值：滑块 + 输入框
            var = tk.StringVar(value=self._fmt(v))
            sc = tk.Scale(row, from_=lo, to=hi, resolution=step, orient="horizontal",
                          length=self.scale_len, showvalue=False,
                          command=lambda val, k=key: self._slid(k, val))
            # 滑块的 resolution 会把值对齐到步长（3072 会变成 3070），
            # 初始化时先静音，保证 values 里留的是原值、输入框显示的也是原值。
            self._quiet = True
            sc.set(v)
            self._quiet = False
            sc.pack(side="left")
            ent = tk.Entry(row, textvariable=var, width=_ENTRY_W, justify="right")
            ent.pack(side="left", padx=(4, 0))
            ent.bind("<Return>", lambda e, k=key: self._typed(k))
            ent.bind("<FocusOut>", lambda e, k=key: self._typed(k))
            self.rows[key] = {"kind": kind, "var": var, "scale": sc, "entry": ent}

    @staticmethod
    def _fmt(v):
        if isinstance(v, float):
            return ("%.4f" % v).rstrip("0").rstrip(".")
        return str(v)

    # ------------------------------------------------------------------ 交互
    def _slid(self, key, value):
        if self._quiet:
            return
        r = self.rows[key]
        v = float(value) if r["kind"] == "float" else int(float(value))
        self.values[key] = v
        r["var"].set(self._fmt(v))
        self._changed()

    def _typed(self, key):
        """输入框里敲的值优先，滑块跟着跳过去（超出滑块范围也认）。"""
        r = self.rows[key]
        if r["kind"] == "bool":
            self.values[key] = bool(r["var"].get())
            self._changed()
            return
        if r["kind"] in ("text", "file"):
            self.values[key] = r["var"].get()
            self._changed()
            return
        raw = r["var"].get().strip()
        try:
            v = float(raw) if r["kind"] == "float" else int(float(raw))
        except ValueError:
            r["var"].set(self._fmt(self.values[key]))     # 敲了非法值就还原
            return
        self.values[key] = v
        sc = r["scale"]
        lo, hi = float(sc.cget("from")), float(sc.cget("to"))
        self._quiet = True
        sc.set(min(max(v, lo), hi))     # 滑块到头了就停在端点，但值仍是真实值
        self._quiet = False
        self._changed()

    def _browse(self, key):
        cur = self.values.get(key) or ""
        path = filedialog.askopenfilename(
            title="选择文件", parent=self.frame,
            filetypes=[("字体 / 图片", "*.ttf *.ttc *.otf *.jpg *.jpeg *.png *.bmp"),
                       ("所有文件", "*.*")],
            initialdir=cur.rsplit("/", 1)[0] if "/" in cur else None)
        if path:
            path = path.replace("\\", "/")
            self.values[key] = path
            self.rows[key]["var"].set(path)
            self._changed()

    def _pick_color(self, key):
        cur = self.values.get(key) or (0, 0, 0)
        rgb, _ = colorchooser.askcolor(color="#%02x%02x%02x" % tuple(cur),
                                       title="选颜色", parent=self.frame)
        if rgb:
            self.values[key] = tuple(int(v) for v in rgb)
            self._paint(key)
            self._changed()

    def _paint(self, key):
        rgb = tuple(self.values.get(key) or (0, 0, 0))
        self.rows[key]["btn"].config(bg="#%02x%02x%02x" % rgb,
                                     fg="#fff" if sum(rgb) < 380 else "#000")

    def _changed(self):
        if self.on_change is None:
            return
        if self._job is not None:
            self.frame.after_cancel(self._job)
        self._job = self.frame.after(self.debounce, self._fire)

    def _fire(self):
        self._job = None
        self.on_change()

    def fire_now(self):
        if self._job is not None:
            self.frame.after_cancel(self._job)
            self._job = None
        if self.on_change is not None:
            self.on_change()

    # ------------------------------------------------------------------ 外部
    def refresh(self):
        """values 被外部改过之后，把界面同步过来。"""
        self._quiet = True
        for key, label, kind, lo, hi, step in self.specs:
            r = self.rows[key]
            v = self.values.get(key)
            if kind == "bool":
                r["var"].set(bool(v))
            elif kind in ("text", "file"):
                r["var"].set("" if v is None else str(v))
            elif kind == "color":
                self._paint(key)
            else:
                r["var"].set(self._fmt(v))
                r["scale"].set(v)
        self._quiet = False


# ---------------------------------------------------------------- 预设存取
def save_preset(parent, values, filename="预设.json", title="保存预设"):
    """把 values 存成 json；返回保存路径，取消或失败返回 None。"""
    path = filedialog.asksaveasfilename(
        parent=parent, title=title, defaultextension=".json",
        filetypes=[("预设", "*.json")], initialfile=filename)
    if not path:
        return None
    dump = {k: (list(v) if k in COLOR_KEYS and isinstance(v, (list, tuple)) else v)
            for k, v in values.items()}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dump, f, ensure_ascii=False, indent=2)
        return path
    except OSError as ex:
        print("保存预设失败：%s" % ex)
        return None


def load_preset(parent, values, title="载入预设"):
    """从 json 读进 values（只覆盖 values 里已有的键）；返回路径或 None。"""
    path = filedialog.askopenfilename(parent=parent, title=title,
                                      filetypes=[("预设", "*.json")])
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as ex:
        print("载入预设失败：%s" % ex)
        return None
    for key, val in data.items():
        if key not in values:
            continue
        if key in COLOR_KEYS and isinstance(val, (list, tuple)):
            val = tuple(int(v) for v in val)
        values[key] = val
    return path
