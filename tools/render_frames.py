#!/usr/bin/env python3
"""Pictures of the real screens, drawn from the real Lua, without the game.

    python tools/render_frames.py      -> tools/out/frame_*.png

tools/test_lua.py runs the mod's Lua against a stub of the engine and counts the draw calls. This records them
instead -- every rectangle, quad, sprite and string, with its coordinates and colour, exactly as the Lua issued them
for a 1920x1080 screen -- and paints them with Pillow. So the layout in these pictures is not a mock-up of the
highway: it is the highway, as the code that ships will place it. A gem that overlaps a fret button here overlaps it
in the game.

Two things are approximations, and only two. The type: the game's fonts are not available out here, so strings are
set in Arial at about the size the game's Small, Medium and Large come out at, and the stub's text measurement is
taught the same metrics so that centred and right-aligned text lands where it will. And the backdrop: a flat green
stands in for the world, with a block where the survivor stands, so it is obvious what the highway covers.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.argv = [sys.argv[0], "--no-ui"]          # test_lua reads argv at import; nothing here wants its verbose output
import test_lua as TL  # noqa: E402

OUT = os.path.join(HERE, "out")
W, H = 1920, 1080
FONT_PX = {"Small": 15, "NewSmall": 15, "Medium": 19, "NewMedium": 19, "Large": 26, "NewLarge": 26}


def font(name, zoom=1.0):
    px = max(6, int(round(FONT_PX.get(str(name), 15) * zoom)))
    for path in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.isfile(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default()


RECORDER = r'''
__rec = nil
local function rec(kind, self, ...)
    if __rec then __rec[#__rec + 1] = { kind = kind, ox = self.x or 0, oy = self.y or 0, args = { ... } } end
end
for _, name in ipairs({ "drawRect", "drawRectBorder", "drawText", "drawTextCentre", "drawTextRight", "drawTextZoomed",
                        "drawTextureScaled" }) do
    ISUIElement[name] = function(self, ...) __draws = __draws + 1; rec(name, self, ...) end
end
local oldNew = ISUIElement.new
function ISUIElement:new(x, y, w, h)
    local o = oldNew(self, x, y, w, h)
    -- Screen coordinates already (the engine adds nothing to this call), so no panel offset is recorded with it.
    o.javaObject = { DrawTexture = function(j, tex, ...) __draws = __draws + 1; rec("quad", { x = 0, y = 0 }, ...) end }
    return o
end
local tm = getTextManager()
function tm.MeasureStringX(self, f, s) return __measure(tostring(f), tostring(s)) end
function tm.getFontHeight(self, f) return __fontheight(tostring(f)) end
'''


def paint(calls, base):
    img = base.copy()
    for call in calls:
        kind, ox, oy, a = call["kind"], call["ox"], call["oy"], call["args"]
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)

        def rgba(alpha, r, g, b):
            return (int(max(0, min(1, r)) * 255), int(max(0, min(1, g)) * 255), int(max(0, min(1, b)) * 255),
                    int(max(0, min(1, alpha)) * 255))

        if kind == "drawRect":
            x, y, w, h, al, r, g, b = a[:8]
            d.rectangle([ox + x, oy + y, ox + x + w, oy + y + h], fill=rgba(al, r, g, b))
        elif kind == "drawRectBorder":
            x, y, w, h, al, r, g, b = a[:8]
            d.rectangle([ox + x, oy + y, ox + x + w, oy + y + h], outline=rgba(al, r, g, b))
        elif kind == "quad":
            x1, y1, x2, y2, x3, y3, x4, y4, r, g, b, al = a[:12]
            d.polygon([(ox + x1, oy + y1), (ox + x2, oy + y2), (ox + x3, oy + y3), (ox + x4, oy + y4)], fill=rgba(al, r, g, b))
        elif kind == "drawTextureScaled":
            tex, x, y, w, h, al = a[0], a[1], a[2], a[3], a[4], a[5]
            tint = (a[6] if len(a) > 6 else 1, a[7] if len(a) > 7 else 1, a[8] if len(a) > 8 else 1)
            path = os.path.join(MOD, "42", *str(tex["path"]).split("/"))
            if os.path.isfile(path) and w >= 1 and h >= 1:
                spr = Image.open(path).convert("RGBA").resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
                r_, g_, b_, a_ = spr.split()
                r_ = r_.point(lambda v: int(v * tint[0]))
                g_ = g_.point(lambda v: int(v * tint[1]))
                b_ = b_.point(lambda v: int(v * tint[2]))
                a_ = a_.point(lambda v: int(v * max(0, min(1, al))))
                layer.alpha_composite(Image.merge("RGBA", (r_, g_, b_, a_)), (int(ox + x), int(oy + y)))
        elif kind in ("drawText", "drawTextCentre", "drawTextRight"):
            s, x, y, r, g, b, al, f = a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7] if len(a) > 7 else "Small"
            fnt = font(f)
            tw = d.textlength(str(s), font=fnt)
            if kind == "drawTextCentre":
                x = x - tw / 2
            elif kind == "drawTextRight":
                x = x - tw
            d.text((ox + x, oy + y), str(s), font=fnt, fill=rgba(al, r, g, b))
        elif kind == "drawTextZoomed":
            s, x, y, zoom, r, g, b, al, f = a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8] if len(a) > 8 else "Small"
            d.text((ox + x, oy + y), str(s), font=font(f, zoom), fill=rgba(al, r, g, b))
        img = Image.alpha_composite(img, layer)
    return img


def world():
    """Something to stand behind the screens: grass, a road, and where the survivor is."""
    img = Image.new("RGBA", (W, H), (62, 88, 48, 255))
    d = ImageDraw.Draw(img)
    d.polygon([(0, 700), (W, 420), (W, 560), (0, 880)], fill=(70, 70, 74, 255))
    # the engine keeps the player's feet at the middle of the screen
    d.rectangle([W // 2 - 26, H // 2 - 118, W // 2 + 26, H // 2], fill=(200, 170, 140, 255), outline=(20, 20, 20, 255))
    d.text((W // 2 - 60, H // 2 - 140), "the survivor", fill=(255, 255, 255, 255), font=font("Small"))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    h = TL.Harness()
    g = h.rt.globals()
    g["__measure"] = lambda f, s: font(f).getlength(s)
    g["__fontheight"] = lambda f: FONT_PX.get(f, 15) + 4
    h.lua(RECORDER)
    h.load_all()
    h.lua("triggerEvent('OnGameBoot')")
    base = world()

    def shoot(name, lua, dim=False):
        h.lua("__rec = {}")
        h.lua(lua)
        calls = []
        rec = h.ev("__rec")
        for i in range(1, len(rec) + 1):
            c = rec[i]
            calls.append({"kind": c["kind"], "ox": c["ox"], "oy": c["oy"], "args": [c["args"][k] for k in range(1, len(c["args"]) + 1)]})
        h.lua("__rec = nil")
        path = os.path.join(OUT, "frame_%s.png" % name)
        paint(calls, base).convert("RGB").save(path)
        print("%-12s %4d draw calls -> %s" % (name, len(calls), path))

    # ---- the highway, part-way through the demo song on Expert, with some notes hit, one held and some missed
    h.lua(r'''
        ProjectEncore.Config.showJudgements = true
        __ui = ISEncoreHighway.openFor{ song = ProjectEncore.getSong('EncoreDemo:apocalypse_run'),
            instrument = ProjectEncore.getInstrument('guitar'), difficulty = 'Expert', character = __player, playerNum = 0 }
        local s = __ui.session
        local nextNote = 1
        function __advance(untilMs, hitEvery)
            while s.state ~= 'finished' and s:now() < untilMs do
                __now = __now + 16
                __ui:prerender()
                local now = ProjectEncore.Audio.inputMs()
                while s.notes[nextNote] and s.notes[nextNote].ms <= now do
                    local n = s.notes[nextNote]
                    if nextNote % hitEvery ~= 0 and not n.open then
                        __ui:onKeyPress(s.binding.fretCode[n.lane])
                        if n.sustainMs == 0 then __ui:onKeyRelease(s.binding.fretCode[n.lane]) end
                    end
                    nextNote = nextNote + 1
                end
            end
        end
    ''')
    h.lua("__advance(-1500, 99)")
    shoot("countin", "__ui:render()")
    h.lua("__advance(10060, 99)")
    shoot("highway", "__ui:render()")
    h.lua("__advance(25300, 7)")
    shoot("chords", "__ui:render()")
    h.lua("__ui.session.tally.starPowerCharge = 1; __ui.session:useStarPower(); __advance(33100, 5)")
    shoot("starpower", "__ui:render()")
    h.lua("__advance(999999, 3)")
    shoot("results", "ISEncoreResults.instance:render()")
    h.lua("ISEncoreResults.instance:onDone()")

    # ---- the menu
    h.lua("__m = ISEncoreMenu.openFor{ character = __player, playerNum = 0 }")
    shoot("setlist", "__m:prerender(); __m:render()")
    h.lua("__m:onKeyPress(Keyboard.KEY_RETURN)")
    shoot("instrument", "__m:prerender(); __m:render()")
    h.lua("__m:onKeyPress(Keyboard.KEY_RETURN)")
    shoot("difficulty", "__m:prerender(); __m:render()")
    h.lua("__m:onKeyPress(Keyboard.KEY_TAB)")
    shoot("options", "__m:prerender(); __m:render()")
    h.lua("__m:openKeys(ProjectEncore.getInstrument('guitar')); __m.keySel = 2")
    shoot("keys", "__m:prerender(); __m:render()")


if __name__ == "__main__":
    main()
