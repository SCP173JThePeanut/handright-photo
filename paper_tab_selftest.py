# coding: utf-8
"""设置界面「纸张」页：拖框建区域 / 选中改名改内容 / 删除 / 真纸切换 / 存进 values。"""
import os
import sys

os.environ["HANDWRITE_SETTINGS"] = "0"

import mask_editor
from settings_editor import SETTINGS_FILE, SettingsEditor

fail = []


def check(ok, msg):
    print("   [%s] %s" % ("ok" if ok else "FAIL", msg))
    if not ok:
        fail.append(msg)


SRC = "deal.py"
MARK = "# ================= 主程序 ================="
head = open(SRC, encoding="utf-8").read().split(MARK)[0]
ns = {"__name__": "pt", "__file__": os.path.abspath(SRC)}
exec(compile(head, SRC, "exec"), ns)
D = dict(ns["DEFAULTS"])
D["w"], D["h"] = 800, 1067          # 缩小，跑得快


class E(object):
    def __init__(self, x, y):
        self.x, self.y = int(x), int(y)


if os.path.exists(SETTINGS_FILE):
    os.remove(SETTINGS_FILE)

se = SettingsEditor(D)
se._build()
se._win.geometry("1100x820+20+20")
se._win.update_idletasks()
se._win.update()
se.nb.select(1)                      # 必须真的切到「纸张」页，画布才有尺寸
se._win.update_idletasks()
se._win.update()
pt = se.paper_tab
pt.refit()

print("1. 默认是生成纸，参数面板在")
check(pt.mode_var.get() == "gen", "默认模式 = %s" % pt.mode_var.get())
check(pt.gen_box.winfo_ismapped(), "生成纸参数面板显示着")
check(not pt._blocks(), "一开始没有写字区域")

print("\n2. 在画布上拖一个框 -> 变成一块区域")
print("   画布 %.0fx%.0f，缩放 %.3f" % (pt.canvas.winfo_width(),
                                        pt.canvas.winfo_height(), pt._k))
pt._on_press(E(120, 200))
pt._on_motion(E(420, 460))
pt._on_release(E(420, 460))
check(len(pt._blocks()) == 1, "建了 1 块")
b = pt._blocks()[0]
check(b["w"] > 0 and b["h"] > 0, "矩形有效 %dx%d @ (%d,%d)"
      % (b["w"], b["h"], b["x"], b["y"]))
check(pt.sel == 0, "自动选中了新建的这块")

print("\n3. 点一下（没拖动）不该生成一像素的碎块")
n = len(pt._blocks())
pt._on_press(E(600, 700))
pt._on_release(E(602, 702))
check(len(pt._blocks()) == n, "点一下没建新块（还是 %d 块）" % n)

print("\n4. 改名 / 写内容会回到 values")
pt.name_var.set("姓名")
pt.text.delete("1.0", "end")
pt.text.insert("1.0", "张三")
pt._text_changed()
check(pt._blocks()[0]["name"] == "姓名", "名称同步了")
check(pt._blocks()[0]["text"] == "张三", "内容同步了")
check("姓名" in pt.listbox.get(0), "列表里显示 %r" % pt.listbox.get(0))

print("\n5. 再拖一块，九宫格那样多块共存")
for (x0, y0, x1, y1) in ((120, 500, 300, 640), (350, 500, 530, 640)):
    pt._on_press(E(x0, y0))
    pt._on_motion(E(x1, y1))
    pt._on_release(E(x1, y1))
check(len(pt._blocks()) == 3, "现在有 %d 块" % len(pt._blocks()))
xs = sorted(round(b["x"]) for b in pt._blocks())
check(len(set(xs)) >= 2, "各块的 x 不一样：%s" % xs)

print("\n6. 拖动已有的一块 = 移动，不是新建")
n = len(pt._blocks())
b = pt._blocks()[1]
old = (b["x"], b["y"])
cx, cy = pt._to_cv(b["x"] + 20, b["y"] + 20)
pt._on_press(E(cx, cy))
pt._on_motion(E(cx + 40, cy + 25))
pt._on_release(E(cx + 40, cy + 25))
check(len(pt._blocks()) == n, "没多出块（还是 %d 块）" % n)
check((pt._blocks()[1]["x"], pt._blocks()[1]["y"]) != old,
      "位置从 %s 挪到了 %s" % (old, (pt._blocks()[1]["x"], pt._blocks()[1]["y"])))

print("\n7. 切到真纸")
pt.mode_var.set("photo")
pt._mode_changed()
pt.img_var.set("paper2.png")
pt._image_changed()
check(se.values["paper_mode"] == "photo", "模式写进 values")
check(se.values["paper_image"] == "paper2.png", "图片路径写进 values")
check(not pt.gen_box.winfo_ismapped(), "生成纸参数面板收起来了")
check(pt._photo is not None and pt._photo.width() > 10, "真纸预览图载入了")

print("\n8. 删除 / 铺满整页")
n = len(pt._blocks())
pt._select(0)
pt._del_block()
check(len(pt._blocks()) == n - 1, "删掉一块，剩 %d 块" % len(pt._blocks()))
pt._full_block()
fb = pt._blocks()[-1]
check(fb["x"] == int(D["margin"]) and fb["y"] == int(D["margin"]),
      "铺满整页从页边距开始 (%d,%d)" % (fb["x"], fb["y"]))

print("\n9. commit() 把控件内容收进 values，并且能存住")
pt.text.delete("1.0", "end")
pt.text.insert("1.0", "最后写的")
pt.commit()
check(pt._blocks()[-1]["text"] == "最后写的", "commit 收到了文本控件里的内容")
se._do_ok()
check(os.path.exists(SETTINGS_FILE), "设置文件写出了 %s" % SETTINGS_FILE)
se2 = SettingsEditor(D)
check(se2.values["paper_mode"] == "photo", "下次打开记住了真纸模式")
check(len(se2.values["blocks"]) == len(pt._blocks()),
      "记住了 %d 块区域" % len(se2.values["blocks"]))
check(se2.values["blocks"][-1]["text"] == "最后写的", "区域内容也记住了")

print("\n10. 重置不该动到 DEFAULTS 里那份（blocks 是嵌套结构，浅拷贝会出问题）")
D["blocks"].append({"name": "污染", "text": "x", "x": 0, "y": 0, "w": 1, "h": 1})
se3 = SettingsEditor(D)
se3._build()
se3._win.withdraw()
check(se3.values["blocks"] is not D["blocks"], "values 里的 blocks 不是同一个对象")
se3._reset()
check(se3.values["blocks"] is not D["blocks"], "reset 之后仍不是同一个对象")
se3.values["blocks"].append({"name": "乱改", "text": "y", "x": 0, "y": 0, "w": 1, "h": 1})
check(len(D["blocks"]) == 1, "改 values 不会影响 DEFAULTS（现在 %d 项）"
      % len(D["blocks"]))

print("\n11. 区域挪位置，预览里的字要跟着走（曾经会留在原地）")
import numpy as np

# 前面 se 的窗口已经关掉了，这里另开一个
D2 = dict(ns["DEFAULTS"])
D2["w"], D2["h"] = 600, 800
D2["font_size"], D2["line_spacing"] = 20, 30
# 用一张没有横线/纸纹的空白纸，这样"不是背景"的像素就是字，好量
D2["rule_width"] = 0
D2["side_line_width"] = 0
D2["grain_sigma"] = 0
D2["paper_color"] = (250, 247, 238)
D2["blocks"] = [{"name": "块", "text": "答案写在这里", "kind": "body",
                 "x": 50, "y": 50, "w": 400, "h": 120}]
se4 = SettingsEditor(D2)
se4._build()
se4._win.geometry("1000x700+20+20")
se4._win.update_idletasks()
se4._win.update()
se4.nb.select(1)
se4._win.update_idletasks()
se4._win.update()
pt = se4.paper_tab
pt.refit()


def ink_box():
    a = np.asarray(pt._preview.convert("L"))
    ys, _xs = np.where(a < 200)          # 空白纸 ~248，字是深灰
    return (int(ys.min()), int(ys.max())) if len(ys) else None


b0 = ink_box()
bb = pt._blocks()[0]
cx, cy = pt._to_cv(bb["x"] + 10, bb["y"] + 10)
pt._on_press(E(cx, cy))
pt._on_motion(E(cx, cy + 150 * pt._k))
pt._on_release(E(cx, cy + 150 * pt._k))
b1 = ink_box()
check(b0 and b1 and b1[0] > b0[0] + 50,
      "预览里的字跟着下移：y 从 %s 到 %s" % (b0, b1))

print("\n12. 改字号，预览里的字也要跟着变")
pt._select(0)
pt.size_var.set("8")
pt._num_changed()
s = ink_box()
pt.size_var.set("45")
pt._num_changed()
g = ink_box()
check(s and g and (g[1] - g[0]) > (s[1] - s[0]),
      "字号 45 的字比字号 8 的高（%d > %d）" % (g[1] - g[0], s[1] - s[0]))

print("\n13. 载入预设之后纸张要生效（曾经控件不同步，出图还是旧纸）")
pt.img_var.set("paper.jpg")
pt.mode_var.set("photo")
pt._image_changed()
se4.values["paper_mode"] = "photo"
se4.values["paper_image"] = "paper2.png"
se4.values["blocks"] = [{"name": "新的", "text": "新内容", "kind": "head",
                         "x": 10, "y": 10, "w": 200, "h": 60}]
se4._reload_widgets()
check(pt.img_var.get() == "paper2.png", "图片路径同步到控件（%r）" % pt.img_var.get())
check(pt.mode_var.get() == "photo", "模式同步到控件")
check(len(pt._blocks()) == 1 and pt._blocks()[0]["name"] == "新的",
      "区域列表也同步了（%d 块）" % len(pt._blocks()))
pt.commit()
check(se4.values["paper_image"] == "paper2.png",
      "commit 不会把旧路径写回去（%r）" % se4.values["paper_image"])

if os.path.exists(SETTINGS_FILE):
    os.remove(SETTINGS_FILE)
if mask_editor._ROOT is not None:
    mask_editor._ROOT.destroy()
print("\n%s" % ("全部通过" if not fail else "有 %d 项失败: %s" % (len(fail), fail)))
sys.exit(1 if fail else 0)
