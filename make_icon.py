"""
Generate icon.ico for RamBo — Rambo-themed, multi-resolution.
Design: dark rounded-square bg, green Rambo silhouette, red headband, silver knife.
Sizes: 16, 32, 48, 256.
"""
from PIL import Image, ImageDraw
import math


BG      = '#141414'
GREEN   = '#4caf50'
RED     = '#e05252'
SILVER  = '#c0c0c0'
OUTLINE = '#2a2a2a'


def draw_icon(size: int) -> Image.Image:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    s   = size / 256  # scale factor

    def sc(v):
        return max(1, round(v * s))

    # ── Background rounded square ──────────────────────────────────────────
    r = sc(40)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)

    # ── Head ──────────────────────────────────────────────────────────────
    cx = size // 2
    hcx, hcy = cx, sc(68)
    hrx, hry = sc(30), sc(35)
    d.ellipse([hcx - hrx, hcy - hry, hcx + hrx, hcy + hry], fill=GREEN)

    # ── Headband (red) ─────────────────────────────────────────────────────
    band_y1 = hcy - sc(8)
    band_y2 = hcy + sc(8)
    # clip headband to head width at that vertical slice (rough ellipse clamp)
    for y in range(band_y1, band_y2 + 1):
        dy = (y - hcy) / hry
        if abs(dy) > 1:
            continue
        bx = hrx * math.sqrt(max(0, 1 - dy * dy))
        d.line([(int(hcx - bx), y), (int(hcx + bx), y)], fill=RED)
    # Trailing cloth flap to the right
    flap_pts = [
        (hcx + hrx - sc(4), band_y1 + sc(2)),
        (hcx + hrx + sc(22), band_y1 - sc(6)),
        (hcx + hrx + sc(26), band_y2 + sc(4)),
        (hcx + hrx - sc(4), band_y2 - sc(2)),
    ]
    d.polygon(flap_pts, fill=RED)

    # ── Neck ───────────────────────────────────────────────────────────────
    neck_top = hcy + hry - sc(4)
    neck_bot = sc(126)
    d.rectangle([cx - sc(12), neck_top, cx + sc(12), neck_bot], fill=GREEN)

    # ── Torso (trapezoid — wide shoulders) ─────────────────────────────────
    sh_y  = sc(126)
    wa_y  = sc(195)
    sh_w  = sc(68)
    wa_w  = sc(44)
    torso = [
        (cx - sh_w, sh_y), (cx + sh_w, sh_y),
        (cx + wa_w, wa_y), (cx - wa_w, wa_y),
    ]
    d.polygon(torso, fill=GREEN)

    # ── Left arm — raised (holding knife overhead) ─────────────────────────
    la = [
        (cx - sh_w,        sh_y),
        (cx - sh_w - sc(8), sh_y + sc(10)),
        (cx - sh_w - sc(52), sh_y - sc(55)),
        (cx - sh_w - sc(36), sh_y - sc(68)),
        (cx - sh_w + sc(4), sh_y - sc(10)),
    ]
    d.polygon(la, fill=GREEN)

    # ── Right arm — down/angled ─────────────────────────────────────────────
    ra = [
        (cx + sh_w,         sh_y),
        (cx + sh_w + sc(8), sh_y + sc(10)),
        (cx + sh_w + sc(42), sh_y + sc(75)),
        (cx + sh_w + sc(22), sh_y + sc(85)),
        (cx + sh_w - sc(4), sh_y + sc(30)),
    ]
    d.polygon(ra, fill=GREEN)

    # ── Knife in raised left hand ──────────────────────────────────────────
    # Blade tip and guard/handle positions
    tip_x   = cx - sh_w - sc(48)
    tip_y   = sh_y - sc(80)
    guard_x = cx - sh_w - sc(24)
    guard_y = sh_y - sc(35)
    hilt_x  = cx - sh_w - sc(14)
    hilt_y  = sh_y - sc(20)

    # Blade (thin tapered polygon)
    angle  = math.atan2(guard_y - tip_y, guard_x - tip_x)
    perp   = angle + math.pi / 2
    hw     = sc(4)  # half-width at guard
    blade = [
        (tip_x, tip_y),
        (guard_x + hw * math.cos(perp), guard_y + hw * math.sin(perp)),
        (guard_x - hw * math.cos(perp), guard_y - hw * math.sin(perp)),
    ]
    d.polygon(blade, fill=SILVER)

    # Guard crosspiece
    gperp_x = math.cos(perp) * sc(7)
    gperp_y = math.sin(perp) * sc(7)
    d.line([
        (int(guard_x - gperp_x), int(guard_y - gperp_y)),
        (int(guard_x + gperp_x), int(guard_y + gperp_y)),
    ], fill=SILVER, width=sc(3))

    # Handle
    d.line([
        (int(guard_x), int(guard_y)),
        (int(hilt_x),  int(hilt_y)),
    ], fill='#8B4513', width=sc(5))

    return img


def main():
    # Pillow ICO: save one large RGBA image and let it resize down for each size
    img = draw_icon(256)
    img.save(
        'Z:/RamBo/icon.ico',
        format='ICO',
        sizes=[(256, 256), (48, 48), (32, 32), (16, 16)],
    )
    # Also save a PNG preview
    img.save('Z:/RamBo/icon_preview.png')
    print("icon.ico + icon_preview.png saved")


if __name__ == '__main__':
    main()
