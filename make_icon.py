"""
Generate icon.ico and logo.png for RamBo.

Design: Rambo in profile — head-and-shoulders silhouette on a dark plate, red
headband with two tails streaming back, and a green rim light that matches the
app's accent colour.

Everything is drawn at 4x supersample and downsampled with LANCZOS; drawing
straight at 16/32px gives jagged edges, drawing large and resizing does not.
"""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageChops

SS = 4
S = 256 * SS            # working canvas edge
K = S / 1024.0          # geometry below is authored in a 1024 space

RED = '#c8322f'
RED_LT = '#ef5350'
GREEN = '#4caf50'

# Profile facing left. The brow, nose, lips and chin are what make this read as
# a face at a glance, so those are the points carrying the detail.
PROFILE = [
    (520, 158), (430, 190), (382, 250), (360, 320), (346, 354),
    (378, 378), (368, 400), (318, 462), (372, 484), (360, 504),
    (376, 520), (358, 542), (376, 562), (368, 596), (442, 638),
    (534, 660),                            # jaw angle
    (516, 690), (500, 762), (452, 800),    # neck front
    (318, 836), (176, 918), (106, 1040), (932, 1040), (930, 906),
    (826, 816), (690, 776),                # trapezius / shoulder back
    (642, 706), (704, 662), (752, 556), (764, 424), (744, 296),
    (700, 208), (620, 164),                # back of hair
]


def hx(h):
    """'#rrggbb' -> (r, g, b)."""
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp(a, b, t):
    return a + (b - a) * t


def vgrad(w, h, c1, c2):
    """Vertical two-stop gradient as an RGB image."""
    col = Image.new('RGB', (1, h))
    d = ImageDraw.Draw(col)
    a, b = hx(c1), hx(c2)
    for y in range(h):
        t = y / max(1, h - 1)
        d.point((0, y), fill=tuple(int(lerp(a[i], b[i], t)) for i in range(3)))
    return col.resize((w, h), Image.BILINEAR)


def P(pts):
    """Scale a 1024-space point list into canvas space."""
    return [(x * K, y * K) for x, y in pts]


def blank_mask():
    m = Image.new('L', (S, S), 0)
    return m, ImageDraw.Draw(m)


def plate():
    """Dark rounded-square base plate and its mask."""
    r = int(S * 0.185)
    mask = Image.new('L', (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=255)
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    img.paste(vgrad(S, S, '#2b2b2b', '#0b0b0b'), (0, 0), mask)
    return img, mask


def vignette(img, strength=90):
    """Darken the corners so the subject sits forward off the plate."""
    v = Image.new('L', (S, S), 0)
    ImageDraw.Draw(v).ellipse([-S * 0.30, -S * 0.30, S * 1.30, S * 1.30], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(S * 0.10))
    shade = Image.new('RGBA', (S, S), (0, 0, 0, strength))
    shade.putalpha(ImageChops.multiply(shade.getchannel('A'), ImageChops.invert(v)))
    img.alpha_composite(shade)


def rim(img, mask, colour, dx=-15, dy=-10):
    """Offset copy of the silhouette in the accent colour — a rim light."""
    shifted = mask.transform(mask.size, Image.AFFINE,
                             (1, 0, -dx * K, 0, 1, -dy * K))
    img.paste(Image.new('RGB', (S, S), hx(colour)), (0, 0), shifted)


def headband():
    """(wrap, tails) — the brow wrap, and two tails streaming off the back."""
    wrap, wd = blank_mask()
    wd.polygon(P([(330, 306), (770, 276), (776, 344), (338, 372)]), fill=255)
    tails, td = blank_mask()
    td.polygon(P([(730, 284), (906, 236), (948, 288), (844, 322), (738, 336)]), fill=255)
    td.polygon(P([(736, 328), (896, 380), (920, 452), (832, 416), (742, 368)]), fill=255)
    return wrap, tails


def draw_icon():
    """Render the full-size (1024px) master artwork."""
    img, pmask = plate()
    vignette(img)

    fig, d = blank_mask()
    d.polygon(P(PROFILE), fill=255)

    rim(img, fig, GREEN)
    img.paste(vgrad(S, S, '#191919', '#060606'), (0, 0), fig)

    # The wrap is clipped to the skull; the tails fly free beyond it.
    wrap, tails = headband()
    band = ImageChops.lighter(
        ImageChops.darker(wrap, fig.filter(ImageFilter.MaxFilter(9))), tails)
    img.paste(vgrad(S, S, RED_LT, RED), (0, 0), band)

    # Clip to the plate, then a hairline edge highlight for depth.
    img.putalpha(ImageChops.darker(img.getchannel('A'), pmask))
    ring = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    w = max(2, S // 170)
    ImageDraw.Draw(ring).rounded_rectangle(
        [w // 2, w // 2, S - 1 - w // 2, S - 1 - w // 2],
        radius=int(S * 0.185), outline=(255, 255, 255, 38), width=w)
    img.alpha_composite(ring)
    return img


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    master = draw_icon()

    # Resize each ICO frame ourselves — Pillow's internal ICO downscaling is
    # lower quality than an explicit LANCZOS pass per size.
    sizes = [256, 128, 64, 48, 32, 16]
    frames = [master.resize((n, n), Image.LANCZOS) for n in sizes]
    frames[0].save(os.path.join(here, 'icon.ico'), format='ICO',
                   sizes=[(n, n) for n in sizes],
                   append_images=frames[1:])

    # Topbar mark used by main.pyw, plus a full-size preview.
    master.resize((40, 40), Image.LANCZOS).save(os.path.join(here, 'logo.png'))
    master.resize((256, 256), Image.LANCZOS).save(
        os.path.join(here, 'icon_preview.png'))
    print('icon.ico, logo.png and icon_preview.png saved')


if __name__ == '__main__':
    main()
