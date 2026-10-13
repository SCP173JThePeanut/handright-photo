# coding: utf-8
# ============================ 正文（text）怎么写 ============================
# 1. ~2~ 表示下标：两个 ~ 之间的字符画小并沉到基线以下，如 log~2~V
# 2. 乘号用 x 而不是 * 
# ==========================================================================
import random
import os

import handright._core as hr_core
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from handright import Template, handwrite

# ============================== 可调参数 ==============================

# --- 版面 ---
w = 3072
k = 1.3333
h = int(k * w)
margin = 70
font_size = w // 35
line_spacing = int(1.43 * font_size)
font_path = "Bo Le Small and pure and fresh Handwriting Pen Chinese Font-Simplified Chinese Fonts.ttf"

# --- 纸张 ---
paper_color = (250, 247, 238)
rule_color = (150, 168, 190)
rule_width = 2
side_line_color = (198, 128, 128)
side_line_width = 3
grain_sigma = 6
grain_alpha = 0.05

# --- 手写抖动 ---
fill = (0, 0, 0)
word_spacing = 2
line_spacing_sigma = 2
font_size_sigma = 2
word_spacing_sigma = 3
perturb_x_sigma = 2
perturb_y_sigma = 2
perturb_theta_sigma = 0.05
start_chars = "“（[<"
end_chars = "，。"

# --- 拍照感 ---
shadow = 180
vignette = 80
blur = 0.35
sensor_grain = 0.05
photo_seed = None

# --- 下标 ---
subscript_scale = 0.6
subscript_drop = 0.12

# --- 输出 ---
out_dir = "./input_images"
show = True

# --- 桌面参数 ---
WOOD_TEXTURE_PATH = "wood_texture.jpg"  # 木纹背景图片路径
BG_SCALE = 1.04  # 桌面比纸张大多少（1.04 表示只留 4% 的边距，即“几乎不露出来”）
SHADOW_OFFSET = 15  # 阴影向右下偏移的像素量
SHADOW_BLUR = 15  # 阴影模糊程度

# ====================================================================

text = """
王盛宇       2414      202402811435
2-01 
要解决的问题：
(1) 如何在传输媒体上传输比特流（0/1），而非具体传输媒体本身。
(2) 屏蔽硬件差异，为数据链路层提供统一的比特流传输服务。
(3) 确定接口的机械、电气、规程、功能特性。
主要特点：
物理层传输的单位是比特；它不管所传比特的含义，也不管差错控制；传输方式为串行传输。

2-02 物理层接口的特性
(1) 机械特性：接口所用接线器的形状、尺寸、引脚数目与排列等。
(2) 电气特性：接口电缆上各条线的电压范围、传输速率、阻抗等。
(3) 功能特性：某条线上出现的某一电平表示何种意义。
(4) 规程特性：各条线的工作步骤，即事件出现的顺序。

2-03
数据：运送消息的实体。
信号：数据的电气或电磁表现。
模拟数据：取值连续的数据。
模拟信号：参数取值连续的信号。
基带信号：来自信源、未经过调制的原始信号。
带通信号：经载波调制后，频谱搬到较高频段、只占某段带宽的信号。
数字数据：取值离散的数据。
数字信号：参数取值离散的信号。
码元：承载信息的基本波形单元，一个码元可携带若干比特。
单工通信：只能单向传输。
半双工通信：双方都能收发，但不能同时进行。
全双工通信：双方可同时收发。

2-05 常用传输媒体及特点
(1) 双绞线：便宜、易安装，抗干扰一般，常用于局域网。
(2) 同轴电缆：抗干扰较好、带宽较高，曾用于有线电视与早期局域网。
(3) 光纤：带宽极大、损耗小、抗电磁干扰、保密好，成本较高。
(4) 无线电波/微波等无线媒体：无需布线、灵活，但受环境影响、易被窃听。

2-06 为什么要信道复用？常用复用技术？
原因：一条信道容量远大于一路信号所需，复用好可提高信道利用率、降低成本。
常用技术：频分复用 FDM、时分复用 TDM、统计时分复用 STDM、波分复用 WDM、码分复用 CDM。

T2-01
奈氏准则：C = 2W x log~2~V
每码元携带比特数 = log~2~16 = 4 bit
数据率 = 20000 x 4 = 80000 bit/s
所以可获得 80 kbit/s 的数据率。
"""

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


def create_desk_scene(paper_img):
    """将平整的纸张贴到木纹桌面上，加入微小倾斜和阴影，桌面只露一条窄边"""
    # 1. 计算背景尺寸（只比纸张大一点点）
    bg_w = int(paper_img.width * BG_SCALE)
    bg_h = int(paper_img.height * BG_SCALE)

    # 2. 加载木纹背景
    if os.path.exists(WOOD_TEXTURE_PATH):
        wood = Image.open(WOOD_TEXTURE_PATH).convert("RGB")
        wood = wood.resize((bg_w, bg_h), Image.LANCZOS)
    else:
        print(f"提示：未找到 '{WOOD_TEXTURE_PATH}'，使用纯色桌面代替。可下载木纹图重命名为该路径。")
        wood = Image.new("RGB", (bg_w, bg_h), (180, 150, 120))
        noise_bg = Image.effect_noise((bg_w, bg_h), 5).convert("RGB")
        wood = Image.blend(wood, noise_bg, 0.1)

    # 3. 纸张随机微倾斜（由于留白很少，旋转角度要小，避免露白）
    angle = random.uniform(-1.5, 1.5)
    paper_rgba = paper_img.convert("RGBA")
    # expand=True 确保旋转后不会被裁剪，四周填充透明
    rotated_paper = paper_rgba.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))

    # 4. 生成阴影
    # 从纸张的 alpha 通道提取轮廓
    alpha = rotated_paper.split()[3]
    shadow_layer = Image.new("RGBA", rotated_paper.size, (0, 0, 0, 0))
    shadow_layer.paste((0, 0, 0, 180), mask=alpha)  # 黑色阴影
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))

    # 5. 计算居中粘贴的坐标
    x = (bg_w - rotated_paper.width) // 2
    y = (bg_h - rotated_paper.height) // 2

    # 6. 将阴影和纸张依次贴到木纹上
    wood.paste(shadow_layer, (x + SHADOW_OFFSET, y + SHADOW_OFFSET), shadow_layer)
    wood.paste(rotated_paper, (x, y), rotated_paper)

    return wood


def photo_like(im, seed=0):
    """把渲染好的整页做出手机拍纸的观感：光照不均 + 暗角 + 轻微虚焦 + 传感器噪点"""
    rnd = random.Random(seed)
    # 光照不均：在很小的画布上画光斑再放大，得到的就是平滑的低频明暗
    light = Image.new("L", (24, 34), 255)
    spot = ImageDraw.Draw(light)
    spot.ellipse((-10, -14, 20, 22), fill=255)
    spot.ellipse((14, -14, 40, 6), fill=min(255, shadow + 14))
    spot.ellipse((12 + rnd.randint(-5, 5), 16, 40, 46), fill=shadow + rnd.randint(-4, 4))
    spot.ellipse((-14, 20, 10, 46), fill=min(255, shadow + 10))
    light = light.filter(ImageFilter.GaussianBlur(3))
    light = light.resize(im.size, Image.BICUBIC)

    vig = Image.radial_gradient("L").resize(im.size).point(lambda v: 255 - v * vignette // 255)
    im = ImageChops.multiply(im, ImageChops.multiply(light, vig).convert("RGB"))

    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))

    return Image.blend(im, Image.effect_noise(im.size, 4).convert("RGB"), sensor_grain)


# ================= 主程序 =================
images = handwrite(text, template)

if not os.path.exists(out_dir):
    os.makedirs(out_dir)

for i, im in enumerate(images):
    assert isinstance(im, Image.Image)

    # 1. 先合成桌面与纸张（含阴影）
    im_with_desk = create_desk_scene(im)

    # 2. 将整张图（桌面+纸张）送入 photo_like 做统一的拍照滤镜处理
    im_final = photo_like(im_with_desk, seed=i if photo_seed is None else photo_seed)

    if show:
        im_final.show()

    im_final.save("{}/{}.png".format(out_dir, i))
    print(f"已生成: {out_dir}/{i}.png")