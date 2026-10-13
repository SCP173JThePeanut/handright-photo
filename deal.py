# coding: utf-8
# ============================ 正文（text）怎么写 ============================
# 1. ~2~ 表示下标：两个 ~ 之间的字符画小并沉到基线以下，如 log~2~V
# 2. 乘号用 x 而不是 *
# ==========================================================================
import random
import os
import cv2
import numpy as np

import handright._core as hr_core
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from handright import Template, handwrite

# ============================== 可调参数 ==============================
# 下面这一坨只是**默认值**。正常跑的时候最前面会弹一个设置界面，
# 在那里改过的值会覆盖这里；界面上的「恢复默认」就是回到这里。
# 想跳过设置界面（批量出图 / 自动化测试）就把环境变量 HANDWRITE_SETTINGS 设成 0。

DEFAULTS = {
    # --- 版面 ---
    "w": 3072,
    "h": 4095,                  # 默认 = int(1.3333 * w)
    "margin": 70,
    "font_size": 87,            # 默认 = w // 35
    "line_spacing": 124,        # 默认 = int(1.43 * font_size)
    "font_path": "Bo Le Small and pure and fresh Handwriting Pen Chinese Font-Simplified Chinese Fonts.ttf",

    # --- 纸张 ---
    "paper_color": (250, 247, 238),
    "rule_color": (150, 168, 190),
    "rule_width": 2,
    "side_line_color": (198, 128, 128),
    "side_line_width": 3,
    "grain_sigma": 6,
    "grain_alpha": 0.05,

    # --- 手写抖动 ---
    "fill": (30, 30, 35),       # 墨色：生成的字和手写笔迹共用
    "word_spacing": 2,
    "line_spacing_sigma": 2,
    "font_size_sigma": 2,
    "word_spacing_sigma": 3,
    "perturb_x_sigma": 2,
    "perturb_y_sigma": 2,
    "perturb_theta_sigma": 0.05,
    "start_chars": "“（[<",
    "end_chars": "，。",

    # --- 下标 ---
    "subscript_scale": 0.6,
    "subscript_drop": 0.12,

    # --- 缺字回退 ---
    # 主字体（博乐手写体）里没有的符号，交给下面的字体来画，
    # 否则那个位置会整块空掉，在整页里非常突兀。按顺序取第一个存在的。
    "fallback_fonts": [
        ("C:/Windows/Fonts/cambria.ttc", 1),   # Cambria Math，数学符号最规范
        ("C:/Windows/Fonts/l_10646.ttf", 0),   # Lucida Sans Unicode
        ("C:/Windows/Fonts/seguisym.ttf", 0),  # Segoe UI Symbol，Windows 自带
    ],
    # 下面两个比例是按上面第一个字体调的，换成别的字体粗细会差一点
    "fallback_scale": 1.1,      # 回退字体相对主字体的字号比例
    "fallback_thin": 1,         # 磨细圈数：0=原样，1、2 越大笔画越细越淡

    # --- 页眉 ---
    # 每一页的第一行都写这个（写一行就好）；设成 "" 就不加页眉。
    # ⚠️ 下面是占位用的假信息，**发到公开仓库前记得确认这里不是你的真实姓名学号**。
    # 平时在设置界面里填一次就会被记住（handwrite_settings.json），不用改这里。
    "page_header": "\n张三       计算机科学与技术2701      20240000000000\n",

    # --- 手写笔 ---
    "pen_width": 6.0,           # 笔的基准宽度，和手写体自身细笔画 5.5~6px 对齐
    "pen_min": 0.25,            # 压感最轻时的粗细倍数
    "pen_max": 1.3,             # 压感最重时的粗细倍数
    "eraser": 45,               # 橡皮大小（原图像素）

    # --- 拍照感（OpenCV部分）---
    "blur_sigma": 1.5,
    "motion_blur_size": 7,
    "grain_strength": 15,

    # --- 透视 ---
    "PERSPECTIVE_OFFSET": 70,   # 数值越大，倾斜越夸张（推荐 50~90）

    # --- 光照 ---
    "GLOBAL_DARKNESS": 0.88,
    "LIGHT_BASE": 220,
    "VIGNETTE_STRENGTH": 80,

    # --- 阴影（环境光遮蔽 + 定向投影）---
    "SHADOW_A_OFFSET": 4,
    "SHADOW_A_BLUR": 12,
    "SHADOW_A_ALPHA": 0.15,     # 四周浅阴影
    "SHADOW_B_OFFSET": 35,
    "SHADOW_B_BLUR": 50,
    "SHADOW_B_ALPHA": 0.25,     # 右下方深阴影

    # --- 桌面（这些在最后出图那个窗口里调；前面用不到）---
    "WOOD_TEXTURE_PATH": "table2.jpg",
    "WOOD_ZOOM": 1.0,           # 木纹缩放：>1 纹理更粗，<1 更细
    "WOOD_SHIFT_X": 0.5,        # 取木纹的哪一块（0~1）
    "WOOD_SHIFT_Y": 0.5,
    "DESK_MARGIN": 0.06,        # 四周留多少桌面（占纸宽的比例）；0=出图正好是纸
    "BG_SCALE": 1.6,            # 透视余量：工作画布比出图大多少（不是看得见的留边）

    # --- 交互 / 输出 ---
    "interactive": True,        # 每页生成后弹窗擦除或手写
    "tune_photo": True,         # 第一页之后弹窗调随机真实化参数
    "seed": 20240101,           # 固定下来版面才可复现；设 None 则每次都不一样
    "mask_dir": "./mask",       # 不用弹窗的老做法：蒙版文件目录
    "out_dir": "./output_images",
    "show": True,
}

# ====================================================================

# text = """第二章
# 1. 关系模型由关系数据结构、关系操作集合和关系完整性约束三部分组成。数据结构是单一的关系（二维表）；关系操作的特点是集合操作方式，选择、投影、并、差、笛卡儿积为5种基本操作；完整性约束包括实体完整性、参照完整性和用户定义的完整性。
#
# 4. 关系模式是型，关系是值。关系模式是对关系的描述（R(U,D,DOM,F)），静态、稳定；关系是关系模式在某一时刻的状态或内容，动态、随时间变化。例：Student(Sno,Sname,Ssex,Sage,Sdept) 是关系模式，某时刻全部学生元组构成的表是它的一个关系。
#
# 6.
# I. πSNO(σJNO='J1'(SPJ))
# II. πSNO(σJNO='J1'∧PNO='P1'(SPJ))
# III. πSNO(σJNO='J1'(SPJ)⋈σCOLOR='红'(P))
# IV. πJNO(J)−πJNO(πSNO(σCITY='天津'(S))⋈πSNO,PNO,JNO(SPJ)⋈πPNO(σCOLOR='红'(P)))
# V. πJNO,PNO(SPJ)÷πPNO(σSNO='S1'(SPJ))
#
# 7. 等值连接：连接运算符为"="的连接运算，从R与S的广义笛卡儿积中选取A、B属性值相等的元组，不要求比较分量同名，结果保留全部属性列。
#    自然连接：特殊的等值连接，要求比较的分量必须是相同的属性组，并在结果中去掉重复的属性列。
#    联系：自然连接是等值连接的特例。
# """

text = """第三章
1. 综合统一。 高度非过程化。面向集合的操作方式。操作对象、查询结果可以是元组的集合，一次插入、删除、更新的对象也可以是元组的集合。  以统一的语法结构提供多种使用方式。 语言简洁，易学易用

2. RESTRICT：表的删除是有限制条件的，要删除的基本表不能被其他表的约束所引用，不能有视图、触发器、存储过程或函数等，存在依赖对象则不能删除
CASCADE：删除没有限制条件，删除基本表的同时相关的依赖对象（如视图）都被删除

3. 1) SELECT * FROM S WHERE A=10
   2) SELECT DISTINCT A,B FROM S
   3) SELECT A,B,S.C,S.D,E,F FROM S,T WHERE S.C=T.C AND S.D=T.D
   4) SELECT * FROM S,T WHERE S.C=T.C
   5) SELECT * FROM S,T WHERE S.A<T.E
   6) SELECT S.C,S.D,T.* FROM S,T

4. 建表：
   CREATE TABLE S(SNO CHAR(3) PRIMARY KEY,SNAME CHAR(10),STATUS CHAR(2),CITY CHAR(10))
   CREATE TABLE P(PNO CHAR(3) PRIMARY KEY,PNAME CHAR(10),COLOR CHAR(4),WEIGHT INT)
   CREATE TABLE J(JNO CHAR(3) PRIMARY KEY,JNAME CHAR(10),CITY CHAR(10))
   CREATE TABLE SPJ(SNO CHAR(3),PNO CHAR(3),JNO CHAR(3),QTY INT,PRIMARY KEY(SNO,PNO,JNO),
     FOREIGN KEY(SNO) REFERENCES S(SNO),FOREIGN KEY(PNO) REFERENCES P(PNO),FOREIGN KEY(JNO) REFERENCES J(JNO))
   查询：
   1) SELECT SNO FROM SPJ WHERE JNO='J1'
   2) SELECT SNO FROM SPJ WHERE JNO='J1' AND PNO='P1'
   3) SELECT SNO FROM SPJ,P WHERE SPJ.PNO=P.PNO AND SPJ.JNO='J1' AND P.COLOR='红'
   4) SELECT JNO FROM J WHERE NOT EXISTS(SELECT * FROM SPJ,S,P
        WHERE SPJ.JNO=J.JNO AND SPJ.SNO=S.SNO AND SPJ.PNO=P.PNO AND S.CITY='天津' AND P.COLOR='红')
   5) SELECT DISTINCT JNO FROM SPJ SPJZ WHERE NOT EXISTS(SELECT * FROM SPJ SPJX
        WHERE SNO='S1' AND NOT EXISTS(SELECT * FROM SPJ SPJY WHERE SPJY.PNO=SPJX.PNO AND SPJY.JNO=SPJZ.JNO))

5.
   1) SELECT SNAME,CITY FROM S
   2) SELECT PNAME,COLOR,WEIGHT FROM P
   3) SELECT DISTINCT JNO FROM SPJ WHERE SNO='S1'
   4) SELECT P.PNAME,SPJ.QTY FROM P,SPJ WHERE P.PNO=SPJ.PNO AND SPJ.JNO='J2'
   5) SELECT DISTINCT PNO FROM SPJ WHERE SNO IN(SELECT SNO FROM S WHERE CITY='上海')
   6) SELECT JNAME FROM J,SPJ,S WHERE J.JNO=SPJ.JNO AND SPJ.SNO=S.SNO AND S.CITY='上海'
   7) SELECT JNO FROM J WHERE NOT EXISTS(SELECT * FROM SPJ,S
        WHERE SPJ.JNO=J.JNO AND SPJ.SNO=S.SNO AND S.CITY='天津')
   8) UPDATE P SET COLOR='蓝' WHERE COLOR='红'
   9) UPDATE SPJ SET SNO='S3' WHERE SNO='S5' AND JNO='J2' AND PNO='P6'
   10) DELETE FROM SPJ WHERE SNO='S2';  DELETE FROM S WHERE SNO='S2'
   11) INSERT INTO SPJ(SNO,PNO,JNO,QTY) VALUES('S2','P4','J6',200)

7.  视图能够简化用户的操作；使用户能以多种角度看待同一数据； 对重构数据库提供了一定程度的逻辑独立性；能够对机密数据提供安全保护。

8. 基本表的行列子集视图一般是可更新的。若视图的属性来自聚集函数、表达式，则该视图肯定是不可更新的。
   可更新：CREATE VIEW S_G1(Sno,Sname,Sage) AS SELECT Sno,Sname,Sage FROM Student WHERE Sdept='CS';
   不可更新：CREATE VIEW S_G(Sno,Gavg) AS SELECT Sno,AVG(Grade) FROM SC GROUP BY Sno;

9.
   1) SELECT PNO,QTY FROM V_SPJ;
   2) SELECT PNO,QTY FROM V_SPJ WHERE SNO='S1';
"""

DEFAULTS["text"] = text

# --- 设置界面 ---
# 放在这里是因为它要连正文一起编辑，而正文就是上面这一段。
# 改过的值会存进 handwrite_settings.json，下次开还记着；「恢复默认」清掉它。
if os.environ.get("HANDWRITE_SETTINGS", "1") != "0":
    from settings_editor import SettingsEditor
    _picked = SettingsEditor(DEFAULTS).edit()
    if _picked is None:
        print("已取消。")
        raise SystemExit(0)
    DEFAULTS = _picked

globals().update(DEFAULTS)

_flow_layout = hr_core._flow_layout
_in_subscript = [False]


def flow_layout_with_subscript(draw, x, y, char, tpl, rand):
    if char == "~":
        _in_subscript[0] = not _in_subscript[0]
        return x
    if not _in_subscript[0]:
        return _flow_layout(draw, x, y, char, tpl, rand)
    font = tpl.get_font()
    small = font.font_variant(size=max(1, round(font.size * subscript_scale)))
    shift = font.getmetrics()[0] - small.getmetrics()[0]
    xy = (round(x), round(hr_core.gauss(rand, y, tpl.get_line_spacing_sigma()))
          + shift + round(font.size * subscript_drop))
    offset = hr_core._draw_char(draw, char, xy, small)
    return x + tpl.get_word_spacing() + offset


hr_core._flow_layout = flow_layout_with_subscript

# handright 画的每个字都要经过 _draw_char，在这里换字体最省事：
# 主字体本来就有的字完全不受影响（连随机数取用顺序都没动）。
_draw_char = hr_core._draw_char
_has_glyph_cache = {}
_fallback_cache = {}


def _pick_fallback():
    """挑第一个真的能打开的备用字体，都打不开就返回 None（照旧留空，不报错）。"""
    for path, index in fallback_fonts:
        if not os.path.exists(path):
            continue
        try:
            ImageFont.truetype(path, size=font_size, index=index)
        except OSError as ex:
            print("提示：回退字体 %s 打不开（%s），试下一个。" % (path, ex))
            continue
        return path, index
    return None


_fallback = _pick_fallback()
if _fallback is None:
    print("提示：没找到可用的回退字体，主字体缺失的符号仍会画不出来。")


def _has_glyph(font, char):
    """字体里没有这个字时，notdef 是空字形，画出来一点墨都没有。"""
    key = (getattr(font, "path", ""), char)
    if key not in _has_glyph_cache:
        _has_glyph_cache[key] = char.isspace() or font.getmask(char).getbbox() is not None
    return _has_glyph_cache[key]


def draw_char_with_fallback(draw, char, xy, font):
    """主字体画不出的字换成回退字体，补上基线差；嫌粗还能再磨细一点。"""
    if _fallback is None or _has_glyph(font, char):
        return _draw_char(draw, char, xy, font)
    size = max(1, round(font.size * fallback_scale))
    if size not in _fallback_cache:
        _fallback_cache[size] = ImageFont.truetype(
            _fallback[0], size=size, index=_fallback[1])
    alt = _fallback_cache[size]
    drop = font.getmetrics()[0] - alt.getmetrics()[0]
    xy = (xy[0], xy[1] + drop)
    left, top, right, bottom = alt.getbbox(char)
    if not fallback_thin:
        return _draw_char(draw, char, xy, alt)
    # draw.text 是整块填色的，想更细只能自己拿字形 mask 啃掉一圈：
    # MinFilter 取邻域最小值，白色区域就会缩水，笔画跟着变细变淡。
    mask, (ox, oy) = alt.getmask2(char, mode="L")
    glyph = Image.Image()._new(mask)
    glyph = glyph.filter(ImageFilter.MinFilter(2 * fallback_thin + 1))
    draw.bitmap((xy[0] + ox, xy[1] + oy),
                glyph.point(lambda v: 255 if v >= 128 else 0), fill=1)
    return right - left


hr_core._draw_char = draw_char_with_fallback

# 同理，_draw_page 是每一页的入口，在它前面插一行页眉最省事。
# _draw_page 只从 start 往后读文本，所以把页眉拼在 start 前面，
# 正文一个字都不用动，怎么分行、怎么翻页还是 handright 说了算。
_draw_page = hr_core._draw_page


def draw_page_with_header(page, text, start, tpl, rand):
    # strip() 是为了兼容 """\n姜铭远...\n""" 这种写法，免得第一行先空一行
    head = hr_core._preprocess_text(page_header).strip()
    if not head:
        return _draw_page(page, text, start, tpl, rand)
    head += "\n"
    end = _draw_page(page, head + text[start:], 0, tpl, rand)
    # end 是拼过页眉之后的坐标，减回去才是正文里的下标。
    # max() 只是保险：万一页眉本身长过一整页，也不会卡死在原地。
    return max(start + 1, start + end - len(head))


hr_core._draw_page = draw_page_with_header

# 每页合成之前，先把墨迹蒙版放出来给你改；改过的就用改过的。
# page.image 本来就是那张二值墨迹蒙版，直接换掉就行。
_perturb_and_merge = hr_core._Renderer._perturb_and_merge


def perturb_and_merge_with_mask(self, page):
    path = os.path.join(mask_dir, "%d.png" % page.num)
    if not os.path.exists(path):
        os.makedirs(mask_dir, exist_ok=True)
        page.image.convert("L").save(path)
        print("已导出蒙版: %s（涂黑不想保留的地方，再跑一遍）" % path)
        return _perturb_and_merge(self, page)
    mask = Image.open(path)
    if mask.size != page.image.size:
        raise ValueError(
            "蒙版 %s 尺寸是 %s，页面是 %s，对不上：删掉重新导出，或按原尺寸改。"
            % (path, mask.size, page.image.size))
    if mask.mode in ("RGBA", "LA"):        # 在透明图层上画的情况
        mask = Image.alpha_composite(
            Image.new("RGBA", mask.size, (0, 0, 0, 255)), mask.convert("RGBA"))
    page.image = mask.convert("1")
    print("已套用蒙版: %s" % path)
    return _perturb_and_merge(self, page)


if interactive:
    pass                       # 改由弹窗编辑，蒙版文件这条路就不走了
elif seed is None:
    print("提示：seed 是 None，每次版面都不同，手改蒙版功能已关闭。")
else:
    hr_core._Renderer._perturb_and_merge = perturb_and_merge_with_mask

font = ImageFont.truetype(font_path, size=font_size)

ascent = font.getmetrics()[0]
y = margin + line_spacing - font_size + ascent
paper = Image.new(mode="RGB", size=(w, h), color=paper_color)
draw = ImageDraw.Draw(paper)
while y < h - 30:
    draw.line((margin - 24, y, w - 30, y), fill=rule_color, width=rule_width)
    y += line_spacing
draw.line((margin - 24, 0, margin - 24, h), fill=side_line_color, width=side_line_width)

if grain_sigma:
    noise = Image.effect_noise((w, h), grain_sigma).convert("RGB")
    paper = Image.blend(paper, noise, grain_alpha)

template = Template(
    background=paper,
    font=font,
    line_spacing=line_spacing,
    fill=fill,
    left_margin=margin,
    top_margin=margin,
    right_margin=margin,
    bottom_margin=margin,
    word_spacing=word_spacing,
    line_spacing_sigma=line_spacing_sigma,
    font_size_sigma=font_size_sigma,
    word_spacing_sigma=word_spacing_sigma,
    start_chars=start_chars,
    end_chars=end_chars,
    perturb_x_sigma=perturb_x_sigma,
    perturb_y_sigma=perturb_y_sigma,
    perturb_theta_sigma=perturb_theta_sigma,
)


def opencv_photo_like(im_pil, seed=0):
    rnd = random.Random(seed)

    # 1. PIL 转 OpenCV (BGR)
    im = cv2.cvtColor(np.array(im_pil), cv2.COLOR_RGB2BGR)
    h, w = im.shape[:2]

    # 出图尺寸 = 纸 + 四周留出来的桌面。
    # DESK_MARGIN=0 就是老样子（出图正好等于纸），所以以前改 BG_SCALE 看不出任何
    # 效果 —— 那只是"透视余量"，最后裁剪切回来的还是纸那么大一块。
    out_w = int(round(w * (1 + 2 * DESK_MARGIN)))
    out_h = int(round(h * (1 + 2 * DESK_MARGIN)))

    # 2. 加载木纹背景（比出图再大一圈，给透视变换留余量）
    bg_w = int(out_w * BG_SCALE)
    bg_h = int(out_h * BG_SCALE)

    if os.path.exists(WOOD_TEXTURE_PATH):
        src = cv2.imread(WOOD_TEXTURE_PATH)
        sh, sw = src.shape[:2]
        # 木纹缩放：先从源图上抠一块再拉伸到画布，等于把纹理放大 / 缩小；
        # 位置参数决定抠的是木纹的哪一块（只有缩放 >1、也就是抠得比源图小时才挪得动）。
        # 夹住上下限：<1 等于想要一块比源图还大的区域，没有意义。
        z = max(1.0, WOOD_ZOOM)
        ch = min(sh, max(16, int(sh / z)))
        cw = min(sw, max(16, int(sw / z)))
        y0 = int(max(0, sh - ch) * min(max(WOOD_SHIFT_Y, 0.0), 1.0))
        x0 = int(max(0, sw - cw) * min(max(WOOD_SHIFT_X, 0.0), 1.0))
        bg = cv2.resize(src[y0:y0 + ch, x0:x0 + cw], (bg_w, bg_h),
                        interpolation=cv2.INTER_LANCZOS4)
    else:
        print(f"提示：未找到 '{WOOD_TEXTURE_PATH}'，使用纯色桌面代替。")
        bg = np.zeros((bg_h, bg_w, 3), dtype=np.uint8)
        bg[:] = (180, 150, 120)
        noise_bg = np.random.normal(0, 5, bg.shape).astype(np.uint8)
        bg = cv2.add(bg, noise_bg)

    # 3. 将纸张居中放置在大画布上
    canvas = np.zeros((bg_h, bg_w, 3), dtype=np.uint8)
    mask = np.zeros((bg_h, bg_w), dtype=np.uint8)
    pad_x = (bg_w - w) // 2
    pad_y = (bg_h - h) // 2
    canvas[pad_y:pad_y + h, pad_x:pad_x + w] = im
    mask[pad_y:pad_y + h, pad_x:pad_x + w] = 255

    # 4. 生成纸张阴影并合成到背景上（这部分不变）
    # 4.1 四周接触阴影（环境光遮蔽）
    mask_a = cv2.GaussianBlur(mask, (SHADOW_A_BLUR * 2 + 1, SHADOW_A_BLUR * 2 + 1), 0)
    M_a = np.float32([[1, 0, SHADOW_A_OFFSET], [0, 1, SHADOW_A_OFFSET]])
    shadow_a = cv2.warpAffine(mask_a, M_a, (bg_w, bg_h))
    alpha_a = shadow_a.astype(np.float32) / 255.0 * SHADOW_A_ALPHA

    # 4.2 右下定向阴影（差集提取阴影带）
    M_b_shift = np.float32([[1, 0, SHADOW_B_OFFSET], [0, 1, SHADOW_B_OFFSET]])
    mask_b_shifted = cv2.warpAffine(mask, M_b_shift, (bg_w, bg_h))
    shadow_region_b = cv2.subtract(mask_b_shifted, mask)
    shadow_region_b = cv2.GaussianBlur(shadow_region_b, (SHADOW_B_BLUR * 2 + 1, SHADOW_B_BLUR * 2 + 1), 0)
    alpha_b = shadow_region_b.astype(np.float32) / 255.0 * SHADOW_B_ALPHA

    alpha_shadow = np.clip(alpha_a + alpha_b, 0, 1)
    alpha_shadow = np.stack([alpha_shadow] * 3, axis=-1)
    bg_with_shadow = (bg.astype(np.float32) * (1 - alpha_shadow) + np.zeros_like(bg) * alpha_shadow).astype(np.uint8)

    # 4.3 将纸张贴到带阴影的背景上
    alpha_paper = mask.astype(np.float32) / 255.0
    alpha_paper = np.stack([alpha_paper] * 3, axis=-1)
    merged = (bg_with_shadow.astype(np.float32) * (1 - alpha_paper) + canvas.astype(
        np.float32) * alpha_paper).astype(np.uint8)

    # 5. 整体透视变换（修改点：连带背景一起透视）
    # 以纸张的四个角为基准，计算透视矩阵，并作用于整张图
    pts1 = np.float32([
        [pad_x, pad_y],
        [pad_x + w, pad_y],
        [pad_x, pad_y + h],
        [pad_x + w, pad_y + h]
    ])
    offset = PERSPECTIVE_OFFSET
    o = PERSPECTIVE_OFFSET
    if o > 0:
        pts2 = pts1 + np.random.randint(-o, o, size=(4, 2)).astype(np.float32)
    else:
        pts2 = pts1.copy()          # 0 = 不做透视；randint(-0, 0) 会直接抛异常
    M = cv2.getPerspectiveTransform(pts1, pts2)

    # 对整个画面（背景+阴影+纸张）应用透视
    # 使用 BORDER_REPLICATE 让边缘木纹自然延伸，避免出现黑边
    warped_whole = cv2.warpPerspective(merged, M, (bg_w, bg_h), borderMode=cv2.BORDER_REPLICATE)

    # 6. 裁中心：纸在正中，四周留 DESK_MARGIN 那一圈桌面
    crop_x1 = (bg_w - out_w) // 2
    crop_y1 = (bg_h - out_h) // 2
    merged = warped_whole[crop_y1:crop_y1 + out_h, crop_x1:crop_x1 + out_w]

    # 7. 模糊处理（对焦不实 + 手抖）
    if blur_sigma > 0:
        ksize = int(blur_sigma * 3) * 2 + 1
        merged = cv2.GaussianBlur(merged, (ksize, ksize), blur_sigma)

    if motion_blur_size > 1:
        k = np.zeros((motion_blur_size, motion_blur_size))
        k[int((motion_blur_size - 1) / 2), :] = np.ones(motion_blur_size)
        k = k / motion_blur_size
        angle = rnd.uniform(0, 360)
        M_rot = cv2.getRotationMatrix2D((motion_blur_size / 2, motion_blur_size / 2), angle, 1)
        k = cv2.warpAffine(k, M_rot, (motion_blur_size, motion_blur_size))
        # 旋转会把核的一部分推出边界，核和就不再是 1，直接卷积会把整幅图压暗。
        total = k.sum()
        if total > 1e-6:
            merged = cv2.filter2D(merged, -1, k / total)
        # 核小的时候（预览会把它按比例缩到 2 左右）遇上倒霉角度，旋转后可能几乎
        # 什么都不剩 —— 这时候卷上去会把整页变黑，所以宁可跳过这一步。
        # （之前的写法只归一化、不跳过，核和≈0 时照样卷，就出现了"预览黑、输出正常"）

    # 8. 真实环境光照（随机漫反射 + 高频噪点）
    light_w, light_h = 64, 80
    light_pil = Image.new("L", (light_w, light_h), LIGHT_BASE)
    spot = ImageDraw.Draw(light_pil)
    spot.ellipse((-20, -20, 60, 60), fill=255)
    spot.ellipse((30, 40, 100, 100), fill=max(0, LIGHT_BASE - 60))
    spot.ellipse((0, 20, 60, 80), fill=max(0, LIGHT_BASE - 20))

    light_pil = light_pil.filter(ImageFilter.GaussianBlur(8))
    light_pil = light_pil.resize((out_w, out_h), Image.BICUBIC)

    light_np = np.array(light_pil, dtype=np.float32) / 255.0
    noise_light = np.random.normal(0, 0.04, light_np.shape)
    light_np = np.clip(light_np + noise_light, 0, 1)
    light_np = np.stack([light_np] * 3, axis=-1)

    vig_pil = Image.radial_gradient("L").resize((out_w, out_h)).point(
        lambda v: 255 - v * VIGNETTE_STRENGTH // 255)
    vig_np = np.array(vig_pil, dtype=np.float32) / 255.0
    vig_np = np.stack([vig_np] * 3, axis=-1)

    merged = (merged.astype(np.float32) * light_np * vig_np * GLOBAL_DARKNESS).astype(np.uint8)

    # 9. 传感器噪点
    if grain_strength > 0:
        noise = np.random.normal(0, grain_strength, merged.shape)
        merged = np.clip(merged.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    # 10. 转回 PIL
    return Image.fromarray(cv2.cvtColor(merged, cv2.COLOR_BGR2RGB))


# ================= 主程序 =================
images = handwrite(text, template, seed=seed)

if not os.path.exists(out_dir):
    os.makedirs(out_dir)

if interactive:
    from mask_editor import MaskEditor
    from photo_editor import PhotoEditor
    editor = MaskEditor(paper, fill=fill, pen_width=pen_width, pen_min=pen_min,
                        pen_max=pen_max, brush=eraser)
    photo = PhotoEditor(globals()) if tune_photo else None
else:
    editor = photo = None

photo_seed = None

for i, im in enumerate(images):
    assert isinstance(im, Image.Image)
    if editor is not None:
        im = editor.edit(im, i)
        if im is None:
            print("已退出，剩下的页没输出。")
            break
    if photo is not None:
        # 参数是全局的，只在第一页调一次；后面的页沿用调好的值
        if not photo.edit(im, i):
            print("已取消，剩下的页没输出。")
            break
        photo_seed = photo.seed
        photo = None
    if photo_seed is not None:
        # 和预览里同一个种子 -> 导出时纸张摆位就是预览里看到的那个
        np.random.seed(photo_seed + i)
    im_final = opencv_photo_like(im, seed=i)
    if show:
        im_final.show()
    save_path = os.path.join(out_dir, f"{i}.png")
    im_final.save(save_path)
    print(f"已生成: {save_path}")