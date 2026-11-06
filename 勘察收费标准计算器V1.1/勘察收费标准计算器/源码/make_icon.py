# -*- coding: utf-8 -*-
"""生成程序图标：蓝绿渐变圆角底 + 「费」字，导出 png / 多尺寸 ico。"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
S = 512
FONTS = [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
         r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\Deng.ttf"]

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# 渐变底
grad = Image.new("RGB", (S, S))
d = ImageDraw.Draw(grad)
c1, c2 = (37, 99, 168), (18, 158, 145)   # 蓝 → 青绿
for y in range(S):
    t = y / (S - 1)
    d.line([(0, y), (S, y)], fill=(
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t)))

# 圆角遮罩
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=104, fill=255)
img.paste(grad, (0, 0), mask)

# 内层高光边
d2 = ImageDraw.Draw(img)
d2.rounded_rectangle([10, 10, S - 11, S - 11], radius=96, outline=(255, 255, 255, 46), width=4)

# 「费」字
font = None
for f in FONTS:
    if os.path.exists(f):
        try:
            font = ImageFont.truetype(f, 296)
            break
        except Exception:
            continue
if font is None:
    raise SystemExit("找不到中文字体")

txt = "费"
bbox = d2.textbbox((0, 0), txt, font=font)
w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
x = (S - w) / 2 - bbox[0]
y = (S - h) / 2 - bbox[1] - 2

# 阴影
sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sh).text((x + 4, y + 5), txt, font=font, fill=(10, 40, 70, 90))
sh = sh.filter(__import__("PIL.ImageFilter", fromlist=["ImageFilter"]).GaussianBlur(7))
img = Image.alpha_composite(img, sh)

d3 = ImageDraw.Draw(img)
d3.text((x, y), txt, font=font, fill=(255, 255, 255, 255))

img.save(os.path.join(HERE, "icon.png"))
sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
img.save(os.path.join(HERE, "icon.ico"), sizes=sizes)
print("ok", os.path.getsize(os.path.join(HERE, "icon.png")),
      os.path.getsize(os.path.join(HERE, "icon.ico")))
