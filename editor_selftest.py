# coding: utf-8
"""Self-check: 界面不会被 WinTab 卡住 + 手写层坐标/图层顺序 + 压感粗细。"""
import sys
import time

from PIL import Image, ImageChops, ImageDraw
import mask_editor
from mask_editor import MaskEditor, _draw_pen

fail = []


def check(ok, msg):
    print("   [%s] %s" % ("ok" if ok else "FAIL", msg))
    if not ok:
        fail.append(msg)


class Ev(object):
    def __init__(self, x, y):
        self.x, self.y = int(x), int(y)


PAPER = Image.new("RGB", (800, 600), (250, 247, 238))
PAGE = PAPER.copy()
d = ImageDraw.Draw(PAGE)
for i in range(0, 800, 37):
    d.line((i, 0, i, 600), fill=(30, 30, 35), width=3)
INK = (30, 30, 35)
ed = MaskEditor(PAPER, fill=INK)


def fresh(page=PAGE):
    ed.strokes, ed.pens, ed.result = [], [], page
    ed._hist, ed._hpos = [([], [])], 0
    ed.tool = "erase"
    ed._load_page(page)
    return ed


print("1. 建窗口绝不能被压感后端卡住")
fresh()
t0 = time.time()
ed._build(0)
dt = time.time() - t0
check(dt < 3.0, "默认后端下 _build 用时 %.2fs" % dt)
check(isinstance(ed._pen, mask_editor.pen_pointer.PointerPen),
      "默认后端是 WM_POINTER")
check(ed._pen.ready, "WM_POINTER 子类化装上了")

print("   坏掉的 WinTab 后端就算打开也只准卡后台线程：")
orig_flag = mask_editor._PEN_BACKEND
mask_editor._PEN_BACKEND = "wintab"
fresh()
t0 = time.time()
ed._build(0)
dt = time.time() - t0
check(dt < 3.0, "_PEN_BACKEND=wintab 时 _build 仍然只要 %.2fs" % dt)
check(isinstance(ed._pen, mask_editor.wintab.PenThread) and ed._pen.daemon,
      "WinTab 跑在 daemon 后台线程里，卡住也不挡退出")
ed._pen.stop()
mask_editor._PEN_BACKEND = orig_flag

print("\n2. 压感拿不到时回退到固定力度")
check(not ed._pen.ready, "没有可用的压感源")
p = ed._pressure()
check(abs(p - mask_editor._MOUSE_PRESSURE) < 1e-9,
      "pressure=%.2f（=固定力度 %.2f）" % (p, mask_editor._MOUSE_PRESSURE))

print("\n3. 压感真的改变笔画粗细")
img = Image.new("L", (400, 200), 0)
_draw_pen(ImageDraw.Draw(img), [(40, 100, 0.05), (360, 100, 1.0)], 12.0)
lo = sum(1 for y in range(200) if img.getpixel((45, y)))
hi = sum(1 for y in range(200) if img.getpixel((355, y)))
check(lo > 0 and hi > lo * 2, "轻笔 %d px -> 重笔 %d px" % (lo, hi))
img2 = Image.new("L", (400, 200), 0)
_draw_pen(ImageDraw.Draw(img2), [(40, 100, 0.5), (360, 100, 0.5)], 12.0)
mid = sum(1 for y in range(200) if img2.getpixel((200, y)))
check(lo < mid < hi, "中等力度 %d px 夹在中间" % mid)
img3 = Image.new("L", (100, 100), 0)
_draw_pen(ImageDraw.Draw(img3), [(50, 50, 1.0)], 12.0)
check(img3.getbbox() is not None, "只点一下也留下一个点")

print("\n4. 手写层：坐标对，墨色对，别处不动")
fresh()
ed._set_zoom(1.0)
ed.tool = "pen"
ed.pen_width = 20.0
ed._on_press(Ev(200, 300))
ed._on_drag(Ev(400, 300))
ed._on_release(Ev(400, 300))
check(len(ed.pens) == 1 and ed.strokes == [], "记下一笔手写，没混进擦除层")
out = ed._render_output()
diff = ImageChops.difference(out, PAGE).getbbox()
check(diff is not None and 180 <= diff[0] <= 200 and 400 <= diff[2] <= 420,
      "笔迹落在 (200,300)-(400,300) 附近 %s" % (diff,))
check(out.getpixel((300, 300)) == INK, "写上去的是墨色 %s" % (out.getpixel((300, 300)),))
check(ImageChops.difference(out.crop((0, 0, 100, 100)),
                            PAGE.crop((0, 0, 100, 100))).getbbox() is None, "远处没动")

print("\n5. 先擦后写：写在擦出来的空白上")
fresh()
ed.tool = "erase"
ed.brush = 200
ed._on_press(Ev(300, 300)); ed._on_drag(Ev(500, 300)); ed._on_release(Ev(500, 300))
ed.tool = "pen"
ed.pen_width = 30.0
ed._on_press(Ev(300, 300)); ed._on_drag(Ev(500, 300)); ed._on_release(Ev(500, 300))
out = ed._render_output()
check(out.getpixel((400, 300)) == INK, "擦过的地方又写上了墨 %s" % (out.getpixel((400, 300)),))
check(ImageChops.difference(out.crop((0, 500, 800, 600)),
                            PAGE.crop((0, 500, 800, 600))).getbbox() is None,
      "下半页没被误伤")

print("\n6. 撤销 / 重做 管两个层")
fresh()
ed.tool = "erase"
ed._on_press(Ev(100, 100)); ed._on_release(Ev(100, 100))
ed.tool = "pen"
ed._on_press(Ev(200, 200)); ed._on_release(Ev(200, 200))
check(len(ed.strokes) == 1 and len(ed.pens) == 1, "一擦一写")
ed._undo()
check(len(ed.strokes) == 1 and len(ed.pens) == 0, "撤销掉手写那笔")
ed._undo()
check(len(ed.strokes) == 0 and len(ed.pens) == 0, "再撤销掉擦除那笔")
ed._redo(); ed._redo()
check(len(ed.strokes) == 1 and len(ed.pens) == 1, "重做都回来")
ed._clear()
check(ed.strokes == [] and ed.pens == [], "清空两层")
ed._undo()
check(len(ed.strokes) == 1 and len(ed.pens) == 1, "清空也能撤销")

print("\n7. 建窗口时 Scale 回调先于状态栏触发，不能炸")
fresh()
try:
    ed._build(1)
    check(True, "_build 没抛异常（_say 的 getattr 兜住了）")
except Exception as ex:
    check(False, "_build 抛了 %s: %s" % (type(ex).__name__, ex))

print("\n8. 换墨色：生成的字和手写笔迹必须同时变色，纸不动")
fresh()
ed._set_zoom(1.0)
ed.tool = "pen"
ed._set_color((200, 30, 30))
out = ed._render_output()
# PAGE 里铺的是 (30,30,35) 的竖线，换色后它们应该变成新颜色
hit = None
for y in range(0, 600, 7):
    if out.getpixel((0, y)) == (200, 30, 30):
        hit = (0, y)
        break
check(hit is not None, "原来 (30,30,35) 的生成墨迹已经变成新色 %s" % (hit,))
check(out.getpixel((400, 300)) is not None, "纸面取样正常")
check(abs(out.getpixel((10, 10))[0] - PAPER.getpixel((10, 10))[0]) < 12,
      "没墨的地方还是纸（纸的纹理没被涂花）")
ed._set_color(INK)
check(ed.fill == INK, "切回原色")

print("\n9. 压感范围可调：最细/最粗改了，笔画粗细真的跟着变")
img = Image.new("L", (400, 200), 0)
_draw_pen(ImageDraw.Draw(img), [(40, 100, 0.0), (360, 100, 1.0)], 12.0, 0.2, 3.0)
lo2 = sum(1 for y in range(200) if img.getpixel((45, y)))
hi2 = sum(1 for y in range(200) if img.getpixel((355, y)))
check(hi2 > hi, "最粗调到 3.0 后笔迹更粗（%d -> %d）" % (hi, hi2))
check(lo2 < lo, "最细调到 0.2 后笔迹更细（%d -> %d）" % (lo, lo2))
fresh()
ed._build(2)
sc = ed.tools.rows["pen_min"]["scale"]
check(float(sc.cget("from")) <= 0.01 and float(sc.cget("to")) >= 4.0,
      "压感最细的范围放宽到 %s~%s（原来 5~150 是百分比，还容易够不到）"
      % (sc.cget("from"), sc.cget("to")))
ed.tool_vals.update({"pen_min": 0.8, "pen_max": 1.2})
ed._tools_changed()
check(ed.pen_min == 0.8 and ed.pen_max == 1.2, "工具栏参数同步到 pen_min/pen_max")
ed.tool_vals["pen_min"] = 3.0
ed._tools_changed()
check(ed.pen_min == ed.pen_max == 1.2, "最细超过最粗时被夹住，不会反")

print("\n9b. 输入框能直接敲滑块范围外的值（这才是「手动输入」的意义）")
ed.tools.rows["pen_max"]["var"].set("12.5")
ed.tools._typed("pen_max")
ed.tools.fire_now()                     # 界面是防抖的，测试里手动触发
check(ed.tool_vals["pen_max"] == 12.5 and ed.pen_max == 12.5,
      "敲 12.5（超出滑块上限 8.0）也认，值变成 %s" % ed.pen_max)
check(float(ed.tools.rows["pen_max"]["scale"].get()) == 8.0,
      "滑块停在上限，但真实值仍是 12.5")
ed.tools.rows["pen_min"]["var"].set("0.005")
ed.tools._typed("pen_min")
ed.tools.fire_now()
check(ed.pen_min == 0.005, "低于滑块下限 0.01 也能敲（0.005）")
ed.tools.rows["pen_min"]["var"].set("abc")
ed.tools._typed("pen_min")
check(ed.pen_min == 0.005, "敲了非法值就还原，不会把参数搞坏")

print("\n10. 切块重画：局部重画的结果必须和整幅重画逐像素一致（放大后卡顿的修复）")
fresh()
ed._set_zoom(1.0)
ed.tool = "pen"
ed.pen_width = 20.0
ed.pen_down(600.0, 800.0)
for i in range(1, 6):
    ed.pen_move(600.0 + i * 20, 800.0 + i * 12)     # 每步都走局部重画
ed.pen_up()
partial = ed.disp.copy()
ed._redraw()                                        # 整幅重画
check(ImageChops.difference(partial, ed.disp).getbbox() is None,
      "局部重画 == 整幅重画（没有缝、没有漏块）")
check(len(ed._tiles) == len(range(0, ed._disp_size[0], mask_editor._TILE)) *
      len(range(0, ed._disp_size[1], mask_editor._TILE)),
      "图块铺满整幅（%d 块）" % len(ed._tiles))
t0 = time.perf_counter()
for _ in range(20):
    ed._redraw(ed._dirty_box((600.0, 800.0), (620.0, 812.0)))
ms = (time.perf_counter() - t0) / 20 * 1000
check(ms < 20, "画一小段 %.3f ms（局部重画，随缩放不变）" % ms)
check(ed.zoom == 1.0, "缩放仍是 100%")

print("\n11. 回归：PhotoEditor.edit() 自己得把缩略图建出来")
# 曾经把建缩略图挪进 _rescale_small() 却忘了在 edit() 里调，结果一开调参界面就崩
# （_small 是 None -> cvtColor 收到 object 数组）。所以这里从真入口 edit() 走一遍。
import os
os.environ["HANDWRITE_SETTINGS"] = "0"
import photo_editor
from photo_editor import PhotoEditor

_src = open("deal.py", encoding="utf-8").read().split(
    "# ================= 主程序 =================")[0]
_ns = {"__name__": "st", "__file__": os.path.abspath("deal.py")}
exec(compile(_src, "deal.py", "exec"), _ns)      # 拿到真正的默认值
pe = PhotoEditor(_ns, preview_scale=0.25)
pe.root.wait_window = lambda w: None             # 别真的阻塞在窗口上
pe.edit(PAGE, 0)
check(pe._small is not None and pe._small.size == (200, 150),
      "edit() 里缩略图建好了：%s" % (getattr(pe._small, "size", None),))
check(pe._photo is not None, "并且真的渲染出了预览图")
pe._win.destroy()

if getattr(ed, "_win", None) is not None and ed._win.winfo_exists():
    ed._win.destroy()
ed._pen.stop()
if mask_editor._ROOT is not None:
    mask_editor._ROOT.destroy()

print("\n%s" % ("全部通过" if not fail else "有 %d 项失败: %s" % (len(fail), fail)))
sys.exit(1 if fail else 0)
