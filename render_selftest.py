# coding: utf-8
"""多区域渲染：等价性 / 多块 / 翻页 / 真纸。"""
import os
import sys

os.environ["HANDWRITE_SETTINGS"] = "0"

from PIL import Image, ImageChops

fail = []


def check(ok, msg):
    print("   [%s] %s" % ("ok" if ok else "FAIL", msg))
    if not ok:
        fail.append(msg)


SRC = "deal.py"
MARK = "# ================= 主程序 ================="
head = open(SRC, encoding="utf-8").read().split(MARK)[0]
ns = {"__name__": "blk", "__file__": os.path.abspath(SRC)}
exec(compile(head, SRC, "exec"), ns)
ns["_in_subscript"][0] = False

# 缩小一点，跑得快；比例不变
ns["w"], ns["h"] = 800, 1067
ns["font_size"], ns["line_spacing"] = 23, 33
ns["margin"] = 18
from handright import Template, handwrite
ns["font"] = __import__("PIL.ImageFont", fromlist=["ImageFont"]).truetype(
    ns["font_path"], ns["font_size"])
ns["text"] = "第三章 关系数据库\n" + "这是一段用来测试排版的正文。" * 12

print("1. blocks 为空时，必须和旧写法逐像素一致")
paper = ns["build_paper"]()
ns["paper"] = paper          # render_pages 读的是这个全局
old = Template(background=paper, font=ns["font"], line_spacing=ns["line_spacing"],
               fill=ns["fill"], left_margin=ns["margin"], top_margin=ns["margin"],
               right_margin=ns["margin"], bottom_margin=ns["margin"],
               word_spacing=ns["word_spacing"],
               line_spacing_sigma=ns["line_spacing_sigma"],
               font_size_sigma=ns["font_size_sigma"],
               word_spacing_sigma=ns["word_spacing_sigma"],
               start_chars=ns["start_chars"], end_chars=ns["end_chars"],
               perturb_x_sigma=ns["perturb_x_sigma"],
               perturb_y_sigma=ns["perturb_y_sigma"],
               perturb_theta_sigma=ns["perturb_theta_sigma"])
ns["blocks"] = []
new_pages = ns["render_pages"]()
old_pages = list(handwrite(ns["text"], old, seed=ns["seed"]))
check(len(new_pages) == len(old_pages),
      "页数一致：新 %d / 旧 %d" % (len(new_pages), len(old_pages)))
same = ImageChops.difference(new_pages[0], old_pages[0]).getbbox() is None
check(same, "第 1 页逐像素一致" + ("" if same else "  ← 有差异"))
if not same:
    print("      差异区域 %s" % (ImageChops.difference(new_pages[0],
                                                     old_pages[0]).getbbox(),))

print("\n2. 多块：给 paper2 的九个答题框各排一块")
ns["paper_mode"] = "photo"
ns["paper_image"] = "paper2.png"
paper2 = ns["build_paper"]()
check(paper2.size == (ns["w"], ns["h"]), "真纸被缩放到 %s" % (paper2.size,))

# paper2.png 原始 1080x1498，九个框大致均分
sx, sy = ns["w"] / 1080.0, ns["h"] / 1498.0
boxes = []
for r in range(3):
    for c in range(3):
        boxes.append({"name": "题%d" % (r * 3 + c + 1), "text": "答：%d" % (r * 3 + c + 1),
                      "x": int((40 + c * 345) * sx), "y": int((340 + r * 425) * sy),
                      "w": int(300 * sx), "h": int(300 * sy)})
ns["blocks"] = boxes
pages = ns["render_pages"]()
check(len(pages) == 1, "九个框都在第 1 页（实际 %d 页）" % len(pages))
# 每个框里都该有墨
import numpy as np
p0 = np.asarray(pages[0].convert("L"))
for b in boxes:
    sub = p0[b["y"]:b["y"] + b["h"], b["x"]:b["x"] + b["w"]]
    if (sub < 120).sum() == 0:
        check(False, "%s 里没写上字" % b["name"])
        break
else:
    check(True, "九个框里都写到字了")

print("\n3. 一块写不下会顺着往后翻，且落在同一位置")
ns["paper_mode"] = "gen"
ns["blocks"] = [{"name": "小框", "text": "测试翻页。" * 60,
                 "x": 60, "y": 60, "w": 300, "h": 200}]
pages = ns["render_pages"]()
check(len(pages) >= 3, "长文本翻成了 %d 页" % len(pages))
p1, p2 = (np.asarray(p.convert("L")) for p in pages[:2])
in1 = (p1[60:260, 60:360] < 120).sum()
in2 = (p2[60:260, 60:360] < 120).sum()
out2 = (p2[300:, :] < 120).sum()
check(in1 > 0 and in2 > 0, "第 1、2 页的小框里都有字（%d / %d 个墨点）" % (in1, in2))
check(out2 == 0, "第 2 页框外没有多余的字")

print("\n4. 空格子的块会被跳过，一块都没有也不崩")
ns["blocks"] = [{"name": "空的", "text": "   ", "x": 10, "y": 10, "w": 100, "h": 100}]
check(len(ns["render_pages"]()) == 1, "只剩纸，不报错")
ns["blocks"] = []
check(len(ns["render_pages"]()) >= 1, "空 blocks 也正常")

print("\n5. 每块可以有自己的字号和行距（0 = 跟随全局）")
txt = "手写测试"


def ink_of(blocks, y0=60, y1=440):
    ns["blocks"] = blocks
    a = np.asarray(ns["render_pages"]()[0].convert("L"))
    return (a[y0:y1, 60:660] < 120).sum()


base = {"name": "块", "text": txt, "x": 60, "y": 60, "w": 600, "h": 380}
n_global = ink_of([dict(base)])
n_big = ink_of([dict(base, size=40)])
n_small = ink_of([dict(base, size=12)])
check(n_big > n_global > n_small,
      "字号 40 / 全局(%d) / 12 的墨点递减：%d > %d > %d"
      % (ns["font_size"], n_big, n_global, n_small))

# 行距：一行字看不出差别，用长文本比总高度
long_txt = "测试排版。" * 20
def lines_with(spacing):
    b = dict(base, text=long_txt, h=380)
    if spacing:
        b["spacing"] = spacing
    ns["blocks"] = [b]
    a = np.asarray(ns["render_pages"]()[0].convert("L"))
    rows = (a[60:440, 60:660] < 120).sum(axis=1)
    return int((rows > 0).sum())


h_tight = lines_with(24)
h_loose = lines_with(52)
check(h_loose != h_tight, "行距 24 和 52 排出来的高度不同（%d vs %d 行像素）"
      % (h_tight, h_loose))

print("\n6. 高度检查用的是「这一块自己的」行距，不是全局的")
ns["line_spacing"] = 40
ns["blocks"] = [{"name": "矮", "text": txt, "x": 60, "y": 60, "w": 600, "h": 45}]
check((np.asarray(ns["render_pages"]()[0].convert("L"))[60:105, 60:660] < 120).sum() > 0,
      "行距 40、高 45 能放下")
ns["blocks"] = [{"name": "太矮", "text": txt, "x": 60, "y": 60, "w": 600, "h": 30}]
pages_h30 = ns["render_pages"]()
check((np.asarray(pages_h30[0].convert("L"))[60:90, 60:660] < 120).sum() == 0,
      "高 30 < 行距 40，这一块被跳过没有输出")
ns["blocks"] = [{"name": "矮但有自己行距", "text": txt, "x": 60, "y": 60,
                 "w": 600, "h": 30, "spacing": 24}]
pages_ok = ns["render_pages"]()
check((np.asarray(pages_ok[0].convert("L"))[60:90, 60:660] < 120).sum() > 0,
      "同一块把行距改成 24 之后就能写进去了")

print("\n7. 抬头只在第 1 页出现，正文会一直翻下去")
ns["w"], ns["h"] = 800, 1067
ns["font_size"], ns["line_spacing"] = 23, 33
ns["blocks"] = [
    # 抬头这块的文字故意写长，好验证"抬头只留第一页"是不是真的在起作用
    {"name": "抬头", "text": "抬头排版测试。" * 40, "kind": "head",
     "x": 40, "y": 40, "w": 400, "h": 40},
    {"name": "正文", "text": "正文排版测试。" * 60, "kind": "body",
     "x": 40, "y": 120, "w": 700, "h": 200}]
pages = ns["render_pages"]()
check(len(pages) >= 3, "正文翻出了 %d 页" % len(pages))


def ink(p, y0, y1, x0=40, x1=440):
    a = np.asarray(p.convert("L"))
    return int((a[y0:y1, x0:x1] < 120).sum())


check(ink(pages[0], 40, 80) > 0, "抬头在第 1 页（%d 个墨点）" % ink(pages[0], 40, 80))
check(ink(pages[1], 40, 80) == 0, "抬头不在第 2 页")
check(ink(pages[1], 120, 320) > 0, "正文在第 2 页继续")
# 同一块区域，把 kind 换成 body 之后就该跟着翻页
ns["blocks"][0]["kind"] = "body"
pages2 = ns["render_pages"]()
check(ink(pages2[1], 40, 80) > 0, "把抬头改成正文后，它也会翻到第 2 页")

print("\n8. 小字号不能再崩（曾经字号 5 就抛 font size must be greater than 0）")
ns["w"], ns["h"] = 800, 1067
ns["line_spacing"] = 40
bad = []
for s in (2, 3, 5, 8, 12):
    ns["blocks"] = [{"name": "小", "text": "小字号排版测试。" * 6, "size": s,
                     "spacing": max(8, s + 4), "x": 40, "y": 40, "w": 700, "h": 300}]
    try:
        pages = ns["render_pages"]()
        n = int((np.asarray(pages[0].convert("L"))[40:340, 40:740] < 120).sum())
        if n == 0:
            bad.append("字号%d 没墨" % s)
    except Exception as ex:                      # noqa: BLE001 - 自检里就要看它崩不崩
        bad.append("字号%d 抛 %s" % (s, type(ex).__name__))
check(not bad, "字号 2/3/5/8/12 都能排出来" + ("；问题：" + "、".join(bad) if bad else ""))

print("\n9. 对齐：靠上/居中/靠下、靠左/居中/靠右，按块各算各的")
ns["w"], ns["h"] = 800, 1067
ns["font_size"], ns["line_spacing"] = 23, 33
BASE = {"name": "块", "text": "第一行\n第二行", "x": 60, "y": 60, "w": 680, "h": 400}


def ink_bbox(**kw):
    ns["blocks"] = [dict(BASE, **kw)]
    a = np.asarray(ns["render_pages"]()[0].convert("L"))
    ys, xs = np.where(a < 120)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(ys) else None


tl = ink_bbox()
mid = ink_bbox(align_v="middle", align_h="center")
bot = ink_bbox(align_v="bottom", align_h="right")
check(tl[1] < mid[1] < bot[1], "垂直：上 %d < 中 %d < 下 %d" % (tl[1], mid[1], bot[1]))
check(tl[0] < mid[0] < bot[0], "水平：左 %d < 中 %d < 右 %d" % (tl[0], mid[0], bot[0]))
# 垂直居中时，上下留白应该差不多
box_top = BASE["y"]
box_bot = BASE["y"] + BASE["h"]
gap_up = mid[1] - box_top
gap_dn = box_bot - mid[3]
check(abs(gap_up - gap_dn) < 12, "垂直居中：上留白 %d ≈ 下留白 %d" % (gap_up, gap_dn))

print("\n9b. 微调：对齐只是粗放三段式，还得能自己 nudge 几十像素对上纸印的横线")
mid_c = ink_bbox(align_v="middle", align_h="center")
up40 = ink_bbox(align_v="middle", align_h="center", dy=-40)
dn40 = ink_bbox(align_v="middle", align_h="center", dy=40)
lf40 = ink_bbox(align_v="middle", align_h="center", dx=-40)
rt40 = ink_bbox(align_v="middle", align_h="center", dx=40)
check(mid_c[1] - up40[1] == 40 and dn40[1] - mid_c[1] == 40,
      "dy ±40 精确生效（%d / %d）" % (mid_c[1] - up40[1], dn40[1] - mid_c[1]))
check(mid_c[0] - lf40[0] == 40 and rt40[0] - mid_c[0] == 40,
      "dx ±40 精确生效（%d / %d）" % (mid_c[0] - lf40[0], rt40[0] - mid_c[0]))
check(ink_bbox(align_v="middle", align_h="center", dy=-400) is None,
      "微调把字推出区域后就被裁光，不会溢到别的地方")

print("\n10. 透视：对边必须收敛，不能两两平行（以前就是平行地看着很假）")
import random as _random

W, H = 3000, 4000
P1 = np.float32([[0, 0], [W, 0], [0, H], [W, H]])       # TL TR BL BR


def _sin(a, b):
    return abs(a[0] * b[1] - a[1] * b[0]) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)


worst = 1.0
widths = []
for sd in range(15):
    p = ns["perspective_corners"](P1, 70, _random.Random(sd))
    TL, TR, BL, BR = p
    top, bot, lft, rgt = TR - TL, BR - BL, BL - TL, BR - TR
    worst = min(worst, max(_sin(top, bot), _sin(lft, rgt)))
    widths.append(abs(np.linalg.norm(top) - np.linalg.norm(bot)) / W)
check(np.median(widths) > 0.005,
      "上下边长度差中位 %.2f%%（=有近大远小）" % (np.median(widths) * 100))
check(worst > 0, "没有任何一次退化成平行（最小夹角正弦 %.4f）" % worst)

print("\n11. 抬头三种模式：仅首页 / 每页都写 / 正文翻页")
ns["w"], ns["h"] = 800, 1067
ns["font_size"], ns["line_spacing"] = 23, 33
HEAD = {"name": "抬头", "text": "抬头排版测试。" * 40, "x": 40, "y": 40,
        "w": 400, "h": 40}
BODY = {"name": "正文", "text": "正文排版测试。" * 60, "kind": "body",
        "x": 40, "y": 120, "w": 700, "h": 200}


def pages_with(kind):
    ns["blocks"] = [dict(HEAD, kind=kind), BODY]
    return ns["render_pages"]()


def head_ink(p):
    a = np.asarray(p.convert("L"))
    return int((a[40:80, 40:440] < 120).sum())


pg = pages_with("head")
check(len(pg) >= 3, "正文翻出了 %d 页" % len(pg))
check(head_ink(pg[0]) > 0 and head_ink(pg[1]) == 0, "仅首页：第 1 页有、第 2 页没有")

pg = pages_with("headall")
check(head_ink(pg[0]) > 0 and head_ink(pg[1]) > 0 and head_ink(pg[2]) > 0,
      "每页都写：第 1/2/3 页都有（%d / %d / %d）"
      % (head_ink(pg[0]), head_ink(pg[1]), head_ink(pg[2])))
check(len(pg) == len(pages_with("head")), "每页抬头不会把页数改掉（%d 页）" % len(pg))

pg = pages_with("body")
check(head_ink(pg[1]) > 0, "正文模式：第 2 页继续写")

print("\n%s" % ("全部通过" if not fail else "有 %d 项失败: %s" % (len(fail), fail)))
sys.exit(1 if fail else 0)
