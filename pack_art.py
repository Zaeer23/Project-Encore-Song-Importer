import os
import shutil

try:
    from PIL import Image, ImageDraw, ImageFont
    HAVE_PIL = True
except ImportError:
    Image = ImageDraw = ImageFont = None
    HAVE_PIL = False

HERE = os.path.dirname(os.path.abspath(__file__))
SPRITES = os.path.join(os.path.dirname(HERE), "42", "media", "textures", "PE")
DEFAULT_ART = os.path.join(HERE, "pack_art_default")
PLACEHOLDER = os.path.join(HERE, "art", "pack_placeholder.png")
PILLOW_HINT = ("Using your own picture needs Pillow, an image library for Python, which this Python does not have. "
               "Install it by running:\n\n    py -m pip install pillow\n\nand open the importer again. Until then the "
               "pack keeps the standard picture.")

GOLD = (255, 205, 70, 255)
WHITE = (255, 255, 255, 255)
INK = (14, 12, 16, 255)


def _font(size):
    for name in ("impact.ttf", "ariblk.ttf", "arialbd.ttf"):
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _fit(draw, text, max_w, max_h, start, smallest=10):
    words = text.split()
    for size in range(start, smallest - 1, -2):
        font = _font(size)
        line_h = sum(font.getmetrics())
        options = [[text]]
        if len(words) > 1:
            best = min(([" ".join(words[:i]), " ".join(words[i:])] for i in range(1, len(words))),
                       key=lambda pair: max(draw.textlength(p, font=font) for p in pair))
            options.append(best)
        for lines in options:
            if max(draw.textlength(l, font=font) for l in lines) <= max_w and line_h * len(lines) <= max_h:
                return font, lines, line_h
    font = _font(smallest)
    return font, [text], sum(font.getmetrics())


def _lines(img, lines, font, line_h, cx, top, fill):
    draw = ImageDraw.Draw(img)
    edge = max(2, line_h // 14)
    y = top
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text((cx - w / 2 + edge, y + edge), line, font=font, fill=(0, 0, 0, 170))
        draw.text((cx - w / 2, y), line, font=font, fill=fill, stroke_width=edge, stroke_fill=INK)
        y += line_h


def _highway(size):
    img = Image.new("RGBA", (size, size), INK)
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / float(size)
        draw.line([(0, y), (size, y)], fill=(int(70 - 52 * t), int(32 - 20 * t), int(104 - 78 * t), 255))
    k = size / 512.0
    near, far, top, bottom = 330 * k, 96 * k, 250 * k, size
    cx = size / 2.0
    draw.polygon([(cx - far / 2, top), (cx + far / 2, top), (cx + near / 2, bottom), (cx - near / 2, bottom)],
                 fill=(10, 10, 14, 255))
    for side in (-1, 1):
        draw.line([(cx + side * near / 2, bottom), (cx + side * far / 2, top)], fill=(200, 204, 214, 255),
                  width=max(1, int(4 * k)))
    for i in range(1, 4):
        o = (i / 4.0 - 0.5)
        draw.line([(cx + o * near, bottom), (cx + o * far, top)], fill=(80, 82, 94, 255), width=1)
    keys = "gryb"
    for t, lane in ((0.10, 0), (0.30, 2), (0.48, 1), (0.66, 3), (0.84, 0)):
        path = os.path.join(SPRITES, "gem_%s.png" % keys[lane])
        if not os.path.isfile(path):
            continue
        y = bottom - (bottom - top) * t
        width = near + (far - near) * t
        x = cx + (lane + 0.5 - 2) * width / 4.0
        gw = max(4, int(width / 4.0 * 0.9))
        gh = max(3, int(gw * 84 / 128.0))
        gem = Image.open(path).convert("RGBA").resize((gw, gh), Image.LANCZOS)
        img.alpha_composite(gem, (int(x - gw / 2), int(y - gh / 2)))
    return img


def _cover(path, size):
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    s = min(w, h)
    img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    img = img.resize((size, size), Image.LANCZOS)
    shade = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(shade)
    start = int(size * 0.52)
    for y in range(start, size):
        t = (y - start) / float(size - start)
        draw.line([(0, y), (size, y)], fill=(0, 0, 0, int(225 * min(1.0, t * 1.4))))
    return Image.alpha_composite(img, shade)


def _placeholder(name, size):
    art = Image.open(PLACEHOLDER).convert("RGBA")
    img = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    if not name.strip():
        img.alpha_composite(art.resize((size, size), Image.LANCZOS))
        return img
    side = int(size * 0.78)
    img.alpha_composite(art.resize((side, side), Image.LANCZOS), ((size - side) // 2, 0))
    draw = ImageDraw.Draw(img)
    margin = int(size * 0.05)
    box_top, box_h = int(size * 0.79), int(size * 0.19)
    font, lines, line_h = _fit(draw, name, size - 2 * margin, box_h, int(size * 0.16))
    top = box_top + (box_h - line_h * len(lines)) / 2
    _lines(img, lines, font, line_h, size / 2, top, WHITE)
    return img


def render(name, size=512, cover=None):
    if not cover:
        return _placeholder(name, size)
    img = _cover(cover, size)
    draw = ImageDraw.Draw(img)
    k = size / 512.0
    label_font = _font(int(30 * k))
    label = "PROJECT ENCORE SONG PACK"
    margin = 26 * k
    if cover:
        name_box_top, name_box_h = size * 0.66, size * 0.26
        label_y = size * 0.60
    else:
        label_y = 30 * k
        name_box_top, name_box_h = 72 * k, 160 * k
    lw = draw.textlength(label, font=label_font)
    draw.text((size / 2 - lw / 2 + 2, label_y + 2), label, font=label_font, fill=(0, 0, 0, 170))
    draw.text((size / 2 - lw / 2, label_y), label, font=label_font, fill=GOLD)
    if name.strip():
        font, lines, line_h = _fit(draw, name, size - 2 * margin, name_box_h, int(120 * k))
        top = name_box_top + (name_box_h - line_h * len(lines)) / 2
        _lines(img, lines, font, line_h, size / 2, top, WHITE)
    return img


def icon(size=64):
    if os.path.isfile(PLACEHOLDER):
        return Image.open(PLACEHOLDER).convert("RGBA").resize((size, size), Image.LANCZOS)
    return _gem_icon(size)


def _gem_icon(size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([1, 1, size - 2, size - 2], int(size * 0.18), fill=(22, 20, 30, 255),
                                          outline=(232, 52, 52, 255), width=max(1, size // 24))
    path = os.path.join(SPRITES, "gem_g.png")
    if os.path.isfile(path):
        gw = int(size * 0.82)
        gh = int(gw * 84 / 128.0)
        gem = Image.open(path).convert("RGBA").resize((gw, gh), Image.LANCZOS)
        img.alpha_composite(gem, ((size - gw) // 2, (size - gh) // 2 + size // 24))
    return img


def make(name, preview_path, poster_path, icon_path, cover=None):
    for path in (preview_path, poster_path, icon_path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    if not HAVE_PIL:
        for file_name, path in (("poster.png", poster_path), ("preview.png", preview_path), ("icon.png", icon_path)):
            shutil.copyfile(os.path.join(DEFAULT_ART, file_name), path)
        return False
    poster = render(name, 512, cover)
    poster.convert("RGB").save(poster_path)
    poster.resize((256, 256), Image.LANCZOS).convert("RGB").save(preview_path)
    icon(64).save(icon_path)
    return True


def make_defaults():
    os.makedirs(DEFAULT_ART, exist_ok=True)
    poster = render("", 512)
    poster.convert("RGB").save(os.path.join(DEFAULT_ART, "poster.png"))
    poster.resize((256, 256), Image.LANCZOS).convert("RGB").save(os.path.join(DEFAULT_ART, "preview.png"))
    icon(64).save(os.path.join(DEFAULT_ART, "icon.png"))
    print("wrote", DEFAULT_ART)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "defaults":
        make_defaults()
