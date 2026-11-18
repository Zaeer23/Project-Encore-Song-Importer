#!/usr/bin/env python3
"""Draw every sprite the highway and the menus use.

    python tools/make_textures.py            -> 42/media/textures/PE/*.png, 42/icon.png, 42/poster.png
    python tools/make_textures.py preview    -> and tools/out/highway_preview.png, a mock of the highway

Needs Pillow. Everything is drawn at four times its size and scaled down, which is all the anti-aliasing there is.

The look is Guitar Hero's, because that is what a note highway looks like to anybody who has played one: a note is
a round gem seen at an angle -- a dark base, a coloured body with some height to it, a white cap -- and not a
rectangle; the strike line is a row of ringed buttons that rise and light when held; a hit throws a flame. The
interface code can only stretch a picture into a rectangle, so the gem's foreshortening is drawn into the sprite:
each one is an ellipse about 1.6 times as wide as it is tall, which is the highway's own viewing angle.

Sprites are keyed by a fret letter (g r y b o p), not by a lane number, so a kit can put red on its first lane and
a guitar green without either needing art of its own.
"""
import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
OUT = os.path.join(MOD, "42", "media", "textures", "PE")
SS = 4                                   # supersampling

FRETS = {
    "g": (58, 208, 70),
    "r": (232, 52, 52),
    "y": (250, 222, 50),
    "b": (60, 140, 250),
    "o": (250, 148, 38),
    "p": (178, 104, 244),
}
STAR = (120, 232, 255)                   # star power's colour on the lamps and the old round phrase gems
SP_BLUE = (84, 178, 255)                 # every note while star power is lit: blue stars
PHRASE_WHITE = (232, 236, 246)           # a note inside a star-power phrase: white stars, as Clone Hero draws them
DEAD = (112, 112, 118)                   # a note that went by


def shade(c, k):
    """k < 1 darkens, k > 1 lightens towards white."""
    if k <= 1:
        return tuple(int(v * k) for v in c)
    t = k - 1
    return tuple(int(v + (255 - v) * t) for v in c)


def canvas(w, h):
    return Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))


def finish(img, w, h, name):
    out = img.resize((w, h), Image.LANCZOS)
    os.makedirs(OUT, exist_ok=True)
    out.save(os.path.join(OUT, name + ".png"))
    return out


def ell(d, cx, cy, rx, ry, fill, outline=None, width=0):
    d.ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS], fill=fill, outline=outline, width=width * SS)


# ---------------------------------------------------------------------------------------------------------------------- gems
GEM_W, GEM_H = 128, 84


def gem(name, colour, hopo=False):
    """A note. Built bottom to top, the way the thing itself is stacked."""
    img = canvas(GEM_W, GEM_H)
    d = ImageDraw.Draw(img)
    cx = GEM_W / 2.0
    # the base it sits on, and its shadow on the board
    ell(d, cx, 52, 60, 30, (0, 0, 0, 150))
    ell(d, cx, 49, 58, 28, (14, 14, 18, 255))
    # the wall of the gem: the colour, darker, a few pixels tall
    for i in range(10):
        ell(d, cx, 46 - i, 51, 24, shade(colour, 0.50 + 0.03 * i) + (255,))
    # the top face
    ell(d, cx, 36, 51, 24, shade(colour, 1.0) + (255,))
    ell(d, cx, 35, 46, 21, shade(colour, 1.18) + (255,))
    if hopo:
        # a hammer-on has no black ring: the cap runs out into the colour, lit
        ell(d, cx, 34, 30, 13.5, shade(colour, 1.55) + (255,))
        ell(d, cx, 33, 23, 10, (255, 255, 255, 255))
    else:
        ell(d, cx, 34, 29, 13, (16, 16, 20, 255))
        for i in range(5):
            ell(d, cx, 33 - i, 22, 9.5, shade((206, 206, 214), 0.86 + 0.035 * i) + (255,))
        ell(d, cx, 28, 22, 9.5, (252, 252, 255, 255))
    # the light on the near shoulder
    hl = canvas(GEM_W, GEM_H)
    hd = ImageDraw.Draw(hl)
    hd.arc([(cx - 44) * SS, (35 - 19) * SS, (cx + 44) * SS, (35 + 19) * SS], 200, 320, fill=(255, 255, 255, 150), width=3 * SS)
    img = Image.alpha_composite(img, hl.filter(ImageFilter.GaussianBlur(1.2 * SS)))
    return finish(img, GEM_W, GEM_H, name)


def star_points(cx, cy, outer, inner, squash, scale=1.0, dy=0.0):
    """A five-pointed star lying on the board: seen from the same angle as the gems, so squashed top to bottom."""
    pts = []
    for i in range(10):
        r = (outer if i % 2 == 0 else inner) * scale
        a = math.radians(-90 + i * 36)
        pts.append(((cx + r * math.cos(a)) * SS, (cy + dy + r * math.sin(a) * squash) * SS))
    return pts


def star_gem(name, colour, hopo=False):
    """A note shaped as a star, the same size and built the same way as gem(): a shadow, a dark base, a wall a few
    pixels tall, the coloured top, and a white cap in the middle (a lit one, with no dark ring, on a hammer-on)."""
    img = canvas(GEM_W, GEM_H)
    d = ImageDraw.Draw(img)
    cx = GEM_W / 2.0
    outer, inner, squash = 60.0, 27.0, 0.47
    d.polygon(star_points(cx, 40, outer, inner, squash, 1.03, 8), fill=(0, 0, 0, 150))
    d.polygon(star_points(cx, 40, outer, inner, squash, 1.0, 5), fill=(14, 14, 18, 255))
    for i in range(9):
        d.polygon(star_points(cx, 40, outer, inner, squash, 0.97, 3 - i), fill=shade(colour, 0.50 + 0.03 * i) + (255,))
    d.polygon(star_points(cx, 40, outer, inner, squash, 0.97, -6), fill=shade(colour, 1.0) + (255,))
    d.polygon(star_points(cx, 40, outer, inner, squash, 0.80, -6), fill=shade(colour, 1.22) + (255,))
    if hopo:
        d.polygon(star_points(cx, 40, outer, inner, squash, 0.50, -7), fill=shade(colour, 1.6) + (255,))
        d.polygon(star_points(cx, 40, outer, inner, squash, 0.36, -8), fill=(255, 255, 255, 255))
    else:
        d.polygon(star_points(cx, 40, outer, inner, squash, 0.46, -7), fill=(16, 16, 20, 255))
        d.polygon(star_points(cx, 40, outer, inner, squash, 0.34, -9), fill=(252, 252, 255, 255))
    hl = canvas(GEM_W, GEM_H)
    hd = ImageDraw.Draw(hl)
    hd.line(star_points(cx, 40, outer, inner, squash, 0.90, -7)[5:9], fill=(255, 255, 255, 150), width=3 * SS)
    img = Image.alpha_composite(img, hl.filter(ImageFilter.GaussianBlur(1.2 * SS)))
    return finish(img, GEM_W, GEM_H, name)


# ---------------------------------------------------------------------------------------------------------------------- fret buttons
FRET_W, FRET_H = 144, 96


def fret(name, colour, down):
    img = canvas(FRET_W, FRET_H)
    d = ImageDraw.Draw(img)
    cx = FRET_W / 2.0
    ell(d, cx, 58, 68, 33, (0, 0, 0, 140))
    # the chrome collar
    for i in range(8):
        ell(d, cx, 55 - i, 64, 30, shade((120, 124, 134), 0.55 + 0.07 * i) + (255,))
    ell(d, cx, 47, 64, 30, (196, 200, 210, 255))
    ell(d, cx, 47, 58, 26.5, (40, 42, 50, 255))
    # the coloured ring
    ell(d, cx, 47, 54, 24.5, shade(colour, 0.80 if not down else 1.15) + (255,))
    ell(d, cx, 47, 42, 18.5, (10, 10, 14, 255))
    if down:
        # held: the button is up, and lit from inside
        for i in range(9):
            ell(d, cx, 47 - i, 39, 17, shade(colour, 0.70 + 0.05 * i) + (255,))
        ell(d, cx, 38, 39, 17, shade(colour, 1.25) + (255,))
        ell(d, cx, 37, 26, 10.5, shade(colour, 1.70) + (255,))
        glow = canvas(FRET_W, FRET_H)
        gd = ImageDraw.Draw(glow)
        ell(gd, cx, 42, 60, 28, colour + (90,))
        img = Image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5 * SS)), img)
    else:
        ell(d, cx, 47, 37, 15.5, (24, 26, 32, 255))
        ell(d, cx, 46, 30, 12, shade(colour, 0.34) + (255,))
    return finish(img, FRET_W, FRET_H, name)


# ---------------------------------------------------------------------------------------------------------------------- fire and light
def flame():
    w, h = 128, 176
    img = canvas(w, h)
    for colour, sx, sy, top, alpha, blur in (
            ((255, 70, 20), 1.00, 1.00, 10, 170, 5.0),
            ((255, 140, 30), 0.80, 0.86, 30, 215, 3.5),
            ((255, 214, 70), 0.56, 0.68, 58, 235, 2.5),
            ((255, 252, 220), 0.30, 0.44, 92, 255, 1.6)):
        layer = canvas(w, h)
        d = ImageDraw.Draw(layer)
        pts = []
        base_y, cx = h - 22, w / 2.0
        half = 50 * sx
        height = (base_y - top) * sy
        for i in range(0, 181, 4):                      # the bulb at the bottom
            a = math.radians(i)
            pts.append(((cx + half * math.cos(a)) * SS, (base_y + half * 0.42 * math.sin(a)) * SS))
        for i in range(1, 40):                          # the left side, up to the tip, with a lick in it
            t = i / 40.0
            x = cx - half * (1 - t) ** 1.25 + 7 * sx * math.sin(t * 9.0) * (1 - t)
            pts.append((x * SS, (base_y - height * t) * SS))
        for i in range(40, 0, -1):                      # and back down the right
            t = i / 40.0
            x = cx + half * (1 - t) ** 1.25 + 7 * sx * math.sin(t * 7.0 + 1.3) * (1 - t)
            pts.append((x * SS, (base_y - height * t) * SS))
        d.polygon(pts, fill=colour + (alpha,))
        img = Image.alpha_composite(img, layer.filter(ImageFilter.GaussianBlur(blur * SS)))
    return finish(img, w, h, "flame")


def glow(name, colour, size=128):
    img = canvas(size, size)
    d = ImageDraw.Draw(img)
    c = size / 2.0
    for i in range(40, 0, -1):
        r = c * i / 40.0
        a = int(255 * (1 - i / 40.0) ** 2.2)
        ell(d, c, c, r, r, colour + (a,))
    return finish(img, size, size, name)


def open_bar(name, colour):
    w, h = 256, 44
    img = canvas(w, h)
    d = ImageDraw.Draw(img)
    r = 15
    d.rounded_rectangle([4 * SS, 10 * SS, (w - 4) * SS, (h - 2) * SS], r * SS, fill=(0, 0, 0, 150))
    d.rounded_rectangle([4 * SS, 7 * SS, (w - 4) * SS, (h - 6) * SS], r * SS, fill=(14, 14, 18, 255))
    d.rounded_rectangle([8 * SS, 9 * SS, (w - 8) * SS, (h - 10) * SS], (r - 3) * SS, fill=shade(colour, 0.70) + (255,))
    d.rounded_rectangle([8 * SS, 7 * SS, (w - 8) * SS, (h - 15) * SS], (r - 3) * SS, fill=shade(colour, 1.05) + (255,))
    d.rounded_rectangle([20 * SS, 10 * SS, (w - 20) * SS, 15 * SS], 3 * SS, fill=(255, 255, 255, 130))
    return finish(img, w, h, name)


# ---------------------------------------------------------------------------------------------------------------------- the rock meter and its lamps
def rock_meter():
    w, h = 256, 168
    img = canvas(w, h)
    d = ImageDraw.Draw(img)
    cx, cy, R = w / 2.0, 136, 112
    # the housing
    d.pieslice([(cx - R - 10) * SS, (cy - R - 10) * SS, (cx + R + 10) * SS, (cy + R + 10) * SS], 180, 360, fill=(8, 8, 10, 235))
    d.rounded_rectangle([(cx - R - 10) * SS, (cy - 2) * SS, (cx + R + 10) * SS, (cy + 26) * SS], 8 * SS, fill=(8, 8, 10, 235))
    d.arc([(cx - R - 8) * SS, (cy - R - 8) * SS, (cx + R + 8) * SS, (cy + R + 8) * SS], 180, 360, fill=(190, 194, 204, 255), width=4 * SS)
    # the three zones: red, amber, green, left to right
    for a0, a1, col in ((180 + 12, 180 + 62, (214, 44, 40)), (180 + 62, 180 + 118, (238, 196, 44)), (180 + 118, 360 - 12, (60, 200, 70))):
        d.pieslice([(cx - R + 6) * SS, (cy - R + 6) * SS, (cx + R - 6) * SS, (cy + R - 6) * SS], a0, a1, fill=col + (255,))
    # the dark middle the needle sweeps over
    d.pieslice([(cx - R + 34) * SS, (cy - R + 34) * SS, (cx + R - 34) * SS, (cy + R - 34) * SS], 180, 360, fill=(18, 18, 22, 255))
    # tick marks
    for i in range(13):
        a = math.radians(192 + i * (156 / 12.0))
        x0, y0 = cx + (R - 8) * math.cos(a), cy + (R - 8) * math.sin(a)
        x1, y1 = cx + (R - 30) * math.cos(a), cy + (R - 30) * math.sin(a)
        d.line([x0 * SS, y0 * SS, x1 * SS, y1 * SS], fill=(10, 10, 12, 255), width=2 * SS)
    ell(d, cx, cy, 15, 15, (190, 194, 204, 255))
    ell(d, cx, cy, 9, 9, (30, 30, 36, 255))
    return finish(img, w, h, "rock_meter")


def lamp(name, colour, lit):
    s = 40
    img = canvas(s, s)
    d = ImageDraw.Draw(img)
    c = s / 2.0
    if lit:
        g = canvas(s, s)
        ell(ImageDraw.Draw(g), c, c, 17, 17, colour + (150,))
        img = Image.alpha_composite(img, g.filter(ImageFilter.GaussianBlur(3 * SS)))
        d = ImageDraw.Draw(img)
    ell(d, c, c, 11, 11, (18, 18, 22, 255))
    ell(d, c, c, 9, 9, (shade(colour, 1.1) if lit else shade(colour, 0.22)) + (255,))
    if lit:
        ell(d, c - 2.5, c - 3, 3.5, 3, (255, 255, 255, 210))
    return finish(img, s, s, name)


def star(name, fill, edge):
    s = 72
    img = canvas(s, s)
    d = ImageDraw.Draw(img)
    c = s / 2.0
    pts = []
    for i in range(10):
        r = 31 if i % 2 == 0 else 13
        a = math.radians(-90 + i * 36)
        pts.append(((c + r * math.cos(a)) * SS, (c + 2 + r * math.sin(a)) * SS))
    d.polygon(pts, fill=fill, outline=edge)
    d.line(pts + [pts[0]], fill=edge, width=3 * SS, joint="curve")
    return finish(img, s, s, name)


# ---------------------------------------------------------------------------------------------------------------------- the name on the door
def font(size):
    for path in (r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\ariblk.ttf", r"C:\Windows\Fonts\arialbd.ttf"):
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def logo():
    """The mod's name in poster lettering: the menu's header, and the middle of the mod's poster."""
    w, h = 560, 150
    img = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    text = "PROJECT ENCORE"
    # The biggest size the name fits the plate at, with room for its edge and shadow.
    size = 220
    f = font(size)
    probe = ImageDraw.Draw(img)
    while size > 40:
        f = font(size)
        box = probe.textbbox((0, 0), text, font=f)
        if box[2] - box[0] <= w * 2 - 60 and box[3] - box[1] <= h * 2 - 50:
            break
        size -= 4
    d = ImageDraw.Draw(img)
    box = d.textbbox((0, 0), text, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    x, y = (w * 2 - tw) / 2 - box[0], (h * 2 - th) / 2 - box[1]
    # a hard drop shadow, a black edge, then the face in a top-to-bottom burn from yellow to red
    d.text((x + 10, y + 12), text, font=f, fill=(0, 0, 0, 200))
    d.text((x, y), text, font=f, fill=(12, 10, 10, 255), stroke_width=12, stroke_fill=(12, 10, 10, 255))
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text((x, y), text, font=f, fill=255)
    grad = Image.new("RGBA", img.size)
    gp = grad.load()
    y0, y1 = int(y + box[1]), int(y + box[3])
    for yy in range(img.size[1]):
        t = min(1.0, max(0.0, (yy - y0) / float(max(1, y1 - y0))))
        col = (255, int(236 - 150 * t), int(70 - 50 * t), 255)
        for xx in range(img.size[0]):
            gp[xx, yy] = col
    img.paste(grad, (0, 0), mask)
    out = img.resize((w, h), Image.LANCZOS)
    out.save(os.path.join(OUT, "logo.png"))
    return out


def mod_art(logo_img, gems):
    """icon.png and poster.png beside mod.info, which named both before either existed."""
    root = os.path.join(MOD, "42")
    icon = Image.new("RGBA", (64, 64), (16, 16, 22, 255))
    g = gems["g"].resize((58, 38), Image.LANCZOS)
    icon.alpha_composite(g, (3, 14))
    icon.save(os.path.join(root, "icon.png"))

    poster = Image.new("RGBA", (512, 512), (14, 14, 20, 255))
    d = ImageDraw.Draw(poster)
    for i in range(512):                                 # a spotlight coming down from the top
        a = int(60 * (1 - i / 512.0))
        d.line([0, i, 512, i], fill=(40 + a, 30 + a // 2, 60 + a, 255))
    # a highway running away up the poster
    d.polygon([(96, 512), (416, 512), (300, 200), (212, 200)], fill=(10, 10, 14, 255))
    for k in range(5):
        xa = 96 + 80 * k
        xb = 212 + 22 * k
        d.line([xa, 512, xb, 200], fill=(70, 72, 84, 255), width=2)
    for t, key in ((0.12, "g"), (0.30, "y"), (0.50, "r"), (0.68, "b"), (0.86, "g")):
        yy = 512 - 312 * t
        scale = 1 - 0.64 * t
        lane = "gryb".index(key)
        cxn = 136 + 80 * lane
        cxf = 223 + 22 * lane
        cx = cxn + (cxf - cxn) * t
        gw_ = int(76 * scale)
        gh_ = int(50 * scale)
        poster.alpha_composite(gems[key].resize((gw_, gh_), Image.LANCZOS), (int(cx - gw_ / 2), int(yy - gh_ / 2)))
    lg = logo_img.resize((480, 129), Image.LANCZOS)
    poster.alpha_composite(lg, (16, 40))
    poster.save(os.path.join(root, "poster.png"))


def app_icon():
    """tools/encore_importer.ico, for the importer's window and its desktop shortcut: a green gem on a dark tile."""
    gem_path = os.path.join(OUT, "gem_g.png")
    if not os.path.isfile(gem_path):
        gem("gem_g", FRETS["g"])
    size = 256
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(tile).rounded_rectangle([8, 8, size - 8, size - 8], 44, fill=(22, 20, 30, 255),
                                           outline=(232, 52, 52, 255), width=10)
    g = Image.open(gem_path).convert("RGBA").resize((212, 139), Image.LANCZOS)
    tile.alpha_composite(g, ((size - 212) // 2, (size - 139) // 2 + 6))
    out = os.path.join(HERE, "encore_importer.ico")
    tile.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return out


# ---------------------------------------------------------------------------------------------------------------------- everything
def build():
    gems = {}
    for key, colour in FRETS.items():
        gems[key] = gem("gem_" + key, colour)
        gem("gemh_" + key, colour, hopo=True)
        fret("fret_" + key, colour, False)
        fret("fretd_" + key, colour, True)
        lamp("lamp_" + key, colour, True)
    gem("gem_sp", STAR)
    gem("gemh_sp", STAR, hopo=True)
    gem("gem_x", DEAD)
    # Star power: every note a blue star while it is lit, and the notes of a phrase white stars until then.
    star_gem("star_sp", SP_BLUE)
    star_gem("starh_sp", SP_BLUE, hopo=True)
    star_gem("star_w", PHRASE_WHITE)
    star_gem("starh_w", PHRASE_WHITE, hopo=True)
    flame()
    glow("glow", (255, 255, 255))
    open_bar("open", FRETS["p"])
    open_bar("open_sp", SP_BLUE)
    open_bar("open_w", PHRASE_WHITE)
    open_bar("open_x", DEAD)
    rock_meter()
    lamp("lamp_off", (120, 124, 134), False)
    lamp("lamp_sp", SP_BLUE, True)
    star("star_on", (255, 214, 60, 255), (120, 80, 10, 255))
    star("star_off", (44, 44, 52, 255), (90, 90, 100, 255))
    lg = logo()
    mod_art(lg, gems)
    app_icon()
    names = sorted(os.listdir(OUT))
    print("%d sprites in %s" % (len(names), OUT))
    return names


def preview():
    """A mock of the highway with these sprites, using the same perspective the Lua does."""
    build()
    W, H = 1280, 720
    img = Image.new("RGBA", (W, H), (58, 84, 44, 255))          # grass: the world shows through around the highway
    d = ImageDraw.Draw(img)
    hh = int(H * 0.56)
    near = int(H * 0.42)
    far = int(near * 0.36)
    cx = W // 2
    bottom = H - 10
    top = bottom - hh
    strike = bottom - int(hh * 0.13)
    DEPTH = 2.6

    def depth(p):
        return (1 - 1 / (1 + p * DEPTH)) / (1 - 1 / (1 + DEPTH))

    def place(p):
        dd = depth(p)
        return strike - (strike - top) * dd, 1 - (1 - 0.36) * dd

    d.polygon([(cx - far / 2, top), (cx + far / 2, top), (cx + near / 2, bottom), (cx - near / 2, bottom)], fill=(16, 15, 20, 240))
    for b in range(0, 9):                                        # fret wires
        y, s = place(b / 8.0)
        d.line([cx - near * s / 2, y, cx + near * s / 2, y], fill=(90, 92, 104, 255), width=2 if b % 4 == 0 else 1)
    lanes = 4
    for k in range(lanes):                                       # strings
        o = (k - (lanes - 1) / 2.0) * near / lanes
        d.line([cx + o, bottom, cx + o * 0.36, top], fill=(120, 122, 132, 255), width=1)
    for side in (-1, 1):                                         # rails
        d.line([cx + side * near / 2, bottom, cx + side * far / 2, top], fill=(200, 204, 214, 255), width=4)
    keys = ["g", "r", "y", "b"]
    for k in range(lanes):
        o = (k - (lanes - 1) / 2.0) * near / lanes
        spr = Image.open(os.path.join(OUT, ("fretd_" if k == 1 else "fret_") + keys[k] + ".png"))
        w = int(near / lanes * 0.98)
        h = int(w * 96 / 144)
        img.alpha_composite(spr.resize((w, h), Image.LANCZOS), (int(cx + o - w / 2), int(strike - h / 2)))
    fl = Image.open(os.path.join(OUT, "flame.png"))
    o = (1 - 1.5) * near / lanes
    fw = int(near / lanes * 0.9)
    img.alpha_composite(fl.resize((fw, int(fw * 176 / 128)), Image.LANCZOS), (int(cx + o - fw / 2), int(strike - fw * 176 / 128 + 12)))
    notes = [(0.95, 0, "gem_"), (0.80, 2, "gem_"), (0.62, 1, "gemh_"), (0.62, 3, "gem_"), (0.45, 0, "gem_"), (0.30, 2, "gem_"), (0.16, 3, "gemh_"), (0.16, 1, "gem_")]
    for p, lane, kind in notes:
        y, s = place(p)
        o = (lane - (lanes - 1) / 2.0) * near / lanes * s
        spr = Image.open(os.path.join(OUT, kind + keys[lane] + ".png"))
        w = int(near / lanes * s * 0.92)
        h = int(w * GEM_H / GEM_W)
        img.alpha_composite(spr.resize((max(4, w), max(3, h)), Image.LANCZOS), (int(cx + o - w / 2), int(y - h * 0.55)))
    rm = Image.open(os.path.join(OUT, "rock_meter.png"))
    img.alpha_composite(rm.resize((200, 131), Image.LANCZOS), (cx + near // 2 + 30, bottom - 150))
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    out = os.path.join(HERE, "out", "highway_preview.png")
    img.convert("RGB").save(out)
    print("preview", out)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "preview":
        preview()
    else:
        build()
