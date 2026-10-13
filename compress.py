# coding: utf-8
import os
import io
from PIL import Image

# ================= 配置区域 =================
INPUT_DIR = "output_images"  # 输入文件夹
OUTPUT_DIR = "compressed_images"  # 输出文件夹
MAX_SIZE_BYTES = 2 * 1024 * 1024  # 目标大小：2MB
MIN_QUALITY = 30  # 最低JPEG质量限制，低于此值则开始缩小分辨率


# ===========================================

def compress_image(input_path, output_path, max_size):
    """
    将单张图片压缩到指定大小以下
    """
    try:
        with Image.open(input_path) as img:
            # 如果是PNG且有透明通道，转为RGB（JPEG不支持透明）
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')

            quality = 95
            scale_factor = 1.0

            # 循环直到文件大小满足要求
            while True:
                # 按比例缩放图片（第一次scale_factor=1.0时不缩放）
                if scale_factor < 1.0:
                    new_w = int(img.width * scale_factor)
                    new_h = int(img.height * scale_factor)
                    resized_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                else:
                    resized_img = img

                # 将图片保存到内存中测试大小
                buffer = io.BytesIO()
                # optimize=True 和 progressive=True 可以进一步减小体积
                resized_img.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
                size = buffer.tell()

                # 判断是否达标
                if size <= max_size:
                    break

                # 如果还没达标，降低质量
                if quality > MIN_QUALITY:
                    quality -= 5
                else:
                    # 如果质量已经降到最低还不达标，则开始缩小分辨率（每次缩小10%）
                    scale_factor -= 0.1
                    quality = 95  # 重置质量，用高画质去渲染更小的尺寸

                    # 防止死循环（如果图片实在太大或太小，加一个保底退出）
                    if scale_factor < 0.1:
                        break

            # 保存最终图片到输出目录
            resized_img.save(output_path, format="JPEG", quality=quality, optimize=True, progressive=True)
            final_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"[成功] {os.path.basename(input_path)} -> {os.path.basename(output_path)} "
                  f"(最终质量: {quality}, 大小: {final_size_mb:.2f} MB)")

    except Exception as e:
        print(f"[错误] 处理 {input_path} 时出错: {e}")


def main():
    # 检查输入目录
    if not os.path.exists(INPUT_DIR):
        print(f"错误：找不到输入目录 '{INPUT_DIR}'，请确认路径是否正确。")
        return

    # 创建输出目录
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"已创建输出目录：{OUTPUT_DIR}")

    # 获取所有图片文件
    valid_exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff')
    files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(valid_exts)]

    if not files:
        print(f"在 '{INPUT_DIR}' 中没有找到可处理的图片文件。")
        return

    print(f"共找到 {len(files)} 张图片，开始压缩...\n" + "-" * 40)

    # 遍历并压缩
    for filename in files:
        input_path = os.path.join(INPUT_DIR, filename)
        # 统一输出为 .jpg 格式以获得最佳的压缩率
        output_filename = os.path.splitext(filename)[0] + ".jpg"
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        compress_image(input_path, output_path, MAX_SIZE_BYTES)

    print("-" * 40 + f"\n全部处理完成！压缩后的图片保存在 '{OUTPUT_DIR}' 文件夹中。")


if __name__ == "__main__":
    main()