"""
Draw the app icon (an original, generic treasure chest - no game artwork) and write:
    src/fortnite_chest_counter/gui/assets/icon_<size>.png   window / taskbar icon used by the desktop app
    packaging/launcher/app.ico                               icon of "Fortnite Visual Chest Counter.exe"
Developers only (needs Pillow):   python packaging/make_icon.py
The outputs are committed, so a release build does not need Pillow.
"""

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
S = 1024                                            # drawing size; every output is a high-quality downscale


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # tile: rounded square with a vertical gradient
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp((44, 58, 104), (14, 17, 30), y / S) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([24, 24, S - 24, S - 24], radius=210, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([24, 24, S - 24, S - 24], radius=210, outline=(92, 120, 200, 120), width=10)

    # soft glow behind the chest
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([210, 250, 814, 860], fill=(251, 191, 36, 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(70)))
    d = ImageDraw.Draw(img)

    wood, wood_dark, gold, gold_dark, plate = (200, 128, 40), (110, 64, 16), (250, 208, 100), (170, 120, 30), (255, 244, 205)
    x0, x1 = 190, 834
    lid_top, lid_bottom, body_bottom = 290, 520, 812

    # body
    d.rounded_rectangle([x0, lid_bottom - 10, x1, body_bottom], radius=46, fill=wood, outline=wood_dark, width=22)
    # lid (rounded top)
    d.rounded_rectangle([x0, lid_top, x1, lid_bottom + 30], radius=150, fill=lerp(wood, (255, 255, 255), 0.08),
                        outline=wood_dark, width=22)
    d.rectangle([x0 + 11, lid_bottom - 6, x1 - 11, lid_bottom + 30], fill=wood)
    # rim between lid and body
    d.rounded_rectangle([x0 - 14, lid_bottom - 26, x1 + 14, lid_bottom + 26], radius=22, fill=gold, outline=gold_dark, width=12)
    # metal bands
    for bx in (318, 662):
        d.rounded_rectangle([bx - 34, lid_top + 22, bx + 34, body_bottom - 4], radius=18, fill=gold, outline=gold_dark, width=10)
    # lock plate + keyhole
    d.rounded_rectangle([432, 452, 592, 640], radius=34, fill=plate, outline=gold_dark, width=12)
    d.ellipse([487, 500, 537, 550], fill=(58, 36, 8))
    d.polygon([(496, 538), (528, 538), (540, 600), (484, 600)], fill=(58, 36, 8))

    # sparkle
    cx, cy, r = 790, 230, 70
    d.polygon([(cx, cy - r), (cx + 16, cy - 16), (cx + r, cy), (cx + 16, cy + 16), (cx, cy + r), (cx - 16, cy + 16),
               (cx - r, cy), (cx - 16, cy - 16)], fill=(255, 250, 230))
    return img


def main():
    big = draw()
    assets = ROOT / "src" / "fortnite_chest_counter" / "gui" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    for size in sizes:
        big.resize((size, size), Image.LANCZOS).save(assets / f"icon_{size}.png", optimize=True)
    ico = ROOT / "packaging" / "launcher" / "app.ico"
    ico.parent.mkdir(parents=True, exist_ok=True)
    big.resize((256, 256), Image.LANCZOS).save(ico, sizes=[(s, s) for s in sizes])
    shutil.copy2(ico, assets / "app.ico")       # the app's Windows window-class icon (gui/app.py set_class_icon)
    print(f"wrote {assets} and {ico}")


if __name__ == "__main__":
    main()
