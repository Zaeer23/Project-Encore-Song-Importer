#!/usr/bin/env python3
"""Run Project Encore's own Lua, outside the game, and play a chart with it.

    python tools/test_lua.py            every test
    python tools/test_lua.py -v         and say what each one measured

Needs `lupa` (a Lua 5.1 runtime for Python). It does not have to be installed into your Python:

    python -m pip install --target <some folder> lupa
    set ENCORE_PYLIB=<that folder>

Project Zomboid runs Kahlua, which is Lua 5.1 with a few holes in it, and until this existed nothing in the mod had
ever been executed before the game loaded it: a structure checker can tell an unbalanced `end` from a balanced one
and that is all. This loads the real files, in the order the game does, against a stub of the engine that is just
big enough -- a clock that only moves when told to, a sound manager that writes down what it was asked to play, a
panel whose draw calls are counted instead of drawn -- and then:

    parses the demo pack's chart and counts what it holds;
    builds all four difficulties from an Expert-only chart and checks they thin the way the design says;
    plays whole songs with bots: one that hits everything, one that hits nothing, one that strums chords;
    opens the highway and the menu and draws them, frame after frame, so a nil in a render path is found here
    and not in the middle of a song.

What it cannot do is tell you how any of it looks or feels. That still takes the game.
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
MODS = os.path.dirname(MOD)
VERBOSE = "-v" in sys.argv
if HERE not in sys.path:
    sys.path.insert(0, HERE)              # kahlua_stdlib, beside this file

for extra in (os.environ.get("ENCORE_PYLIB"),
              os.path.join(os.environ.get("TEMP", ""), "claude", "195b7a4b6fc3fe41",
                           "8a152969-73f4-444c-a8a5-2d9e12220e15", "scratchpad", "pylib")):
    if extra and os.path.isdir(extra) and extra not in sys.path:
        sys.path.insert(0, extra)
try:
    from lupa import lua51
except ImportError:
    print("lupa is not available. See the top of this file for how to get it without installing anything globally.")
    sys.exit(2)

LUA_ROOTS = [os.path.join(MOD, "42", "media", "lua"), os.path.join(MODS, "EncoreDemoPack", "42", "media", "lua")]
MOD_DIRS = {"ProjectEncore": MOD, "EncoreDemoPack": os.path.join(MODS, "EncoreDemoPack")}

PRELUDE = r'''
__now = 1000000
__keys = {}
__draws = 0
__sound = { played = {}, volumes = {}, stopped = 0 }
__queued = nil
__vars = {}

function getTimestampMs() return __now end
function getText(key, a, b, c)
    local s = tostring(key)
    if a ~= nil then s = s .. "|" .. tostring(a) end
    if b ~= nil then s = s .. "|" .. tostring(b) end
    return s
end

ModData = { store = {} }
function ModData.getOrCreate(name)
    ModData.store[name] = ModData.store[name] or {}
    return ModData.store[name]
end
function ModData.exists(name) return ModData.store[name] ~= nil end
function ModData.get(name) return ModData.store[name] end

Events = setmetatable({}, { __index = function(t, k)
    local e = { handlers = {} }
    e.Add = function(fn) table.insert(e.handlers, fn) end
    e.Remove = function(fn)
        for i = #e.handlers, 1, -1 do if e.handlers[i] == fn then table.remove(e.handlers, i) end end
    end
    rawset(t, k, e)
    return e
end })
LuaEventManager = { AddEvent = function(name) local _ = Events[name] end }
function triggerEvent(name, a, b, c)
    for _, fn in ipairs(Events[name].handlers) do fn(a, b, c) end
end

function instanceof(obj, cls) return false end
local seed = 7
function ZombRand(n) seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n end
function isClient() return false end
function isKeyDown(code) return __keys[code] == true end

Keyboard = {
    KEY_ESCAPE = 1, KEY_1 = 2, KEY_2 = 3, KEY_3 = 4, KEY_4 = 5, KEY_5 = 6,
    KEY_TAB = 15, KEY_Q = 16, KEY_W = 17, KEY_E = 18, KEY_R = 19, KEY_RETURN = 28,
    KEY_A = 30, KEY_S = 31, KEY_D = 32, KEY_F = 33, KEY_G = 34, KEY_H = 35, KEY_J = 36, KEY_K = 37, KEY_L = 38,
    KEY_SPACE = 57, KEY_UP = 200, KEY_PRIOR = 201, KEY_LEFT = 203, KEY_RIGHT = 205, KEY_DOWN = 208, KEY_NEXT = 209,
    KEY_BACK = 14, KEY_DELETE = 211, KEY_LSHIFT = 42,
}

-- A sound manager that writes down what it was asked to do.
local emitter = {}
function emitter.playSound(self, name) table.insert(__sound.played, name); return #__sound.played end
function emitter.stopSound(self, h) __sound.stopped = __sound.stopped + 1 end
function emitter.isPlaying(self, h) return true end
function emitter.setVolume(self, h, v) table.insert(__sound.volumes, v) end
local sm = {}
function sm.getUIEmitter(self) return emitter end
function sm.playUISound(self, name) table.insert(__sound.played, name); return #__sound.played end
function sm.stopUISound(self, h) end
function sm.isPlayingUISound(self, h) return true end
function getSoundManager() return sm end

-- Files: a reader is handed back even for a missing file, as the engine does.
function getModFileReader(dir, path, create)
    local lines = __readmodfile(dir, path)
    local i = 0
    local reader = {}
    function reader.readLine(self) i = i + 1; return lines and lines[i] or nil end
    function reader.close(self) end
    return reader
end
-- Files under the Zomboid folder that the mod writes (getFileWriter) and reads back.
__files = {}
function getFileWriter(path, create, append)
    local buf = {}
    return { write = function(self, text) buf[#buf + 1] = text end,
             close = function(self) __files[path] = table.concat(buf) end }
end
function getFileReader(path, create)
    local text = __files[path]
    if text == nil then return nil end
    local lines = {}
    for line in string.gmatch(text, "([^\n]*)\n") do lines[#lines + 1] = line end
    local i = 0
    return { readLine = function(self) i = i + 1; return lines[i] end, close = function(self) end }
end

-- Classes, the way ISBaseObject does them.
local function class(name, parent)
    local c = parent and setmetatable({}, { __index = parent }) or {}
    c.Type = name
    c.__index = c
    function c:derive(n)
        local d = setmetatable({}, { __index = self })
        d.Type = n
        d.__index = d
        return d
    end
    return c
end

ISBaseObject = class("ISBaseObject")
ISUIElement = class("ISUIElement", ISBaseObject)
function ISUIElement:new(x, y, w, h)
    local o = setmetatable({}, self)
    self.__index = self
    o.x, o.y, o.width, o.height = x or 0, y or 0, w or 0, h or 0
    o.children = {}
    -- The Java side of an element: only DrawTexture is called on it directly (PETheme.quad, as drawLine2 does).
    -- Its eight coordinates are SCREEN coordinates: unlike drawRect and the rest, the engine adds nothing to them.
    -- The first quad of each frame is remembered so a test can check the board is under the frets and not in a corner.
    o.javaObject = { DrawTexture = function(self, tex, x1, y1, x2, y2, x3, y3, x4, y4)
        __draws = __draws + 1
        if __quads then __quads[#__quads + 1] = { x1, y1, x2, y2, x3, y3, x4, y4 } end
    end }
    return o
end
function ISUIElement:getAbsoluteX() return self.x end
function ISUIElement:getAbsoluteY() return self.y end
local function draw() __draws = __draws + 1 end
for _, name in ipairs({ "drawRect", "drawRectBorder", "drawText", "drawTextCentre", "drawTextRight", "drawTextZoomed",
                        "drawTextureScaled", "drawTextureScaledAspect", "drawTexture", "drawTextureAllPoint",
                        "drawLine2", "drawPolygon", "drawSubTexture" }) do
    -- `...` is passed on rather than ignored: a vararg function that never touches `...` gets an `arg` table built
    -- on every call in Lua 5.1, which would count against the mod in the garbage test below.
    ISUIElement[name] = function(self, ...) return draw(...) end
end
-- Text is written down too, while a test has __texts set, so it can ask what the screen said.
for _, name in ipairs({ "drawText", "drawTextCentre", "drawTextRight", "drawTextZoomed" }) do
    ISUIElement[name] = function(self, text, ...)
        draw(...)
        if __texts then __texts[#__texts + 1] = tostring(text) end
    end
end
for _, name in ipairs({ "initialise", "instantiate", "addToUIManager", "removeFromUIManager", "setAlwaysOnTop",
                        "setWantKeyEvents", "setCapture", "setVisible", "setStencilRect", "clearStencilRect",
                        "bringToTop", "setX", "setY", "setWidth", "setHeight", "prerender", "render", "createChildren",
                        "setEnable", "setTitle", "clear", "setSelected", "addOption", "close" }) do
    ISUIElement[name] = function(self) end
end
function ISUIElement:addChild(c) table.insert(self.children, c) end
function ISUIElement:removeChild(c) end
function ISUIElement:getMouseX() return self.mouseX or -1 end
function ISUIElement:getMouseY() return self.mouseY or -1 end
function ISUIElement:getWidth() return self.width end
function ISUIElement:getHeight() return self.height end
function ISUIElement:getX() return self.x end
function ISUIElement:getY() return self.y end
function ISUIElement:isVisible() return true end
function ISUIElement:titleBarHeight() return 20 end
function ISUIElement:getInternalText() return "" end
function ISUIElement:addItem(text, item)
    self.items = self.items or {}
    local i = { text = text, item = item, index = #self.items + 1 }
    table.insert(self.items, i)
    return i
end

ISPanel = class("ISPanel", ISUIElement)
ISCollapsableWindow = class("ISCollapsableWindow", ISPanel)
ISButton = class("ISButton", ISPanel)
function ISButton:new(x, y, w, h, title, target, onclick)
    local o = ISUIElement.new(self, x, y, w, h)
    o.title, o.target, o.onclick = title, target, onclick
    return o
end
ISScrollingListBox = class("ISScrollingListBox", ISPanel)
ISTickBox = class("ISTickBox", ISPanel)
ISTextEntryBox = class("ISTextEntryBox", ISPanel)
ISContextMenu = class("ISContextMenu", ISPanel)
-- Options are called exactly as ISContextMenu.lua:70 calls them: onSelect(target, param1, param2, ...).
function ISContextMenu:getNew(parent)
    local o = setmetatable({ options = {} }, ISContextMenu)
    return o
end
function ISContextMenu:addOption(name, target, onSelect, p1, p2, p3, p4)
    self.options = self.options or {}
    local option = { name = name, target = target, onSelect = onSelect, params = { p1, p2, p3, p4 } }
    table.insert(self.options, option)
    return option
end
function ISContextMenu:addSubMenu(option, sub) option.sub = sub end
function __select(option)
    return option.onSelect(option.target, option.params[1], option.params[2], option.params[3], option.params[4])
end
ISToolTip = class("ISToolTip", ISPanel)

ISBaseTimedAction = class("ISBaseTimedAction", ISBaseObject)
function ISBaseTimedAction:new(character)
    local o = setmetatable({}, self)
    self.__index = self
    o.character = character
    o.action = {}
    return o
end
function ISBaseTimedAction:setActionAnim(name) __vars.PerformingAction = name end
function ISBaseTimedAction:setOverrideHandModels(a, b) __handModel = a end
function ISBaseTimedAction:stop() end
function ISBaseTimedAction:perform() end
ISTimedActionQueue = {}
function ISTimedActionQueue.add(action) __queued = action; action:start() end
function ISTimedActionQueue.clear(character) if __queued then __queued:stop(); __queued = nil end end
Metabolics = { LightDomestic = 1 }

UIFont = setmetatable({}, { __index = function(t, k) return k end })
local tm = {}
function tm.MeasureStringX(self, font, s) return #tostring(s) * 8 end
function tm.MeasureStringY(self, font, s) return 16 end
function tm.getFontHeight(self, font) return 16 end
function getTextManager() return tm end

local core = {}
function core.getScreenWidth(self) return 1920 end
function core.getScreenHeight(self) return 1080 end
function core.getZoom(self, n) return 1 end
function core.getAutoZoom(self, n) return true end
function core.setAutoZoom(self, n, v) end
function core.doZoomScroll(self, n, d) end
-- The game's "UI offscreen rendering" option, which the highway switches off for a song.
__uiFbo = true
function core.getOptionUIFBO(self) return __uiFbo end
function core.setOptionUIFBO(self, v) __uiFbo = v end
function getCore() return core end
function getPlayerScreenLeft(n) return 0 end
function getPlayerScreenTop(n) return 0 end
function getPlayerScreenWidth(n) return 1920 end
function getPlayerScreenHeight(n) return 1080 end
__texturesAsked = {}
function getTexture(path) __texturesAsked[path] = true; return { path = path } end
UIManager = nil
IsoCamera = nil

-- A survivor: enough of one for the session, the action and the watchdog.
CharacterStat = { BOREDOM = "BOREDOM", UNHAPPINESS = "UNHAPPINESS", STRESS = "STRESS" }
-- The engine clamps: boredom and unhappiness are 0-100, stress 0-1.
local STAT_MAX = { BOREDOM = 100, UNHAPPINESS = 100, STRESS = 1 }
function __newCharacter(name)
    local c = { vars = {}, modData = {}, transmits = 0, name = name or "survivor",
                stats = { BOREDOM = 50, UNHAPPINESS = 50, STRESS = 0.5 } }
    function c.getModData(self) return self.modData end
    function c.transmitModData(self) self.transmits = self.transmits + 1 end
    function c.getUsername(self) return self.name end
    function c.getStats(self)
        local who = self
        local st = {}
        local function clamp(stat, v)
            if v < 0 then v = 0 end
            if v > STAT_MAX[stat] then v = STAT_MAX[stat] end
            who.stats[stat] = v
            return true
        end
        function st.get(_, stat) return who.stats[stat] end
        function st.add(_, stat, v) return clamp(stat, who.stats[stat] + v) end
        function st.remove(_, stat, v) return clamp(stat, who.stats[stat] - v) end
        function st.set(_, stat, v) return clamp(stat, v) end
        return st
    end
    function c.isDead(self) return false end
    function c.isAsleep(self) return false end
    function c.getPlayerNum(self) return 0 end
    function c.setVariable(self, k, v) self.vars[k] = v; __vars[k] = v end
    function c.setMetabolicTarget(self, v) end
    function c.getBodyDamage(self) return nil end
    function c.getVehicle(self) return nil end
    function c.getCurrentSquare(self) return __square end
    function c.setBlockMovement(self, v) self.blocked = v; __blockLog[#__blockLog + 1] = v end
    function c.isBlockMovement(self) return self.blocked == true end
    function c.getPrimaryHandItem(self) return self.primary end
    function c.getSecondaryHandItem(self) return nil end
    function c.getInventory(self)
        local inv = {}
        function inv.getFirstTypeRecurse(i, itemType)
            for _, item in ipairs(self.carried or {}) do
                if item:getFullType() == itemType then return item end
            end
            return nil
        end
        return inv
    end
    return c
end
__blockLog = {}
__square = {}
function __newItem(fullType)
    local item = { items = nil }
    function item.getFullType(self) return fullType end
    return item
end
function getSpecificPlayer(n) return __player end
function getPlayer() return __player end
'''


class Harness:
    def __init__(self):
        self.rt = lua51.LuaRuntime(unpack_returned_tuples=True)
        self.loaded = {}
        g = self.rt.globals()
        g["__readmodfile"] = self.read_mod_file
        g["require"] = self.require
        self.rt.execute(PRELUDE)
        # The game's own table.sort, out of its stdlib.lbc, so a sort that is fine on C Lua and slow on Kahlua shows
        # up here; it also counts comparisons in __kahluaSortCalls. Without the game installed, C Lua's sort stays.
        try:
            import kahlua_stdlib
            self.kahlua = kahlua_stdlib.install(self.rt)
        except Exception as exc:                       # never let the harness fail on this
            print("(could not load the game's stdlib.lbc: %s)" % exc)
            self.kahlua = None
        if self.kahlua is None:
            self.rt.execute("__kahluaSortCalls = 0")
        g["__player"] = self.rt.eval("__newCharacter()")

    # ---- the engine's file and module loading
    def read_mod_file(self, mod_dir, path):
        root = MOD_DIRS.get(mod_dir)
        if not root:
            return None
        full = os.path.join(root, *str(path).split("/"))
        if not os.path.isfile(full):
            return None
        with open(full, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        return self.rt.table_from(lines)

    def find(self, name):
        for root in LUA_ROOTS:
            for side in ("shared", "client", "server"):
                path = os.path.join(root, side, *name.split("/")) + ".lua"
                if os.path.isfile(path):
                    return path
        return None

    def require(self, name):
        path = self.find(str(name))
        if path is None:
            return None                     # a vanilla file: its globals are stubbed in the prelude
        return self.load(path)

    def load(self, path):
        if path in self.loaded:
            return self.loaded[path]
        self.loaded[path] = True
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        loader = self.rt.eval("function(src, name) local f, err = loadstring(src, name); if not f then error(err, 0) end; return f end")
        chunk = loader(src, "@" + os.path.relpath(path, MODS).replace("\\", "/"))
        result = chunk()
        self.loaded[path] = result if result is not None else True
        return self.loaded[path]

    def load_all(self):
        """Shared first, then client, then server, alphabetically within each: the order the game uses."""
        for side in ("shared", "client", "server"):
            for root in LUA_ROOTS:
                files = sorted(glob.glob(os.path.join(root, side, "**", "*.lua"), recursive=True))
                for path in files:
                    self.load(path)

    def lua(self, code):
        return self.rt.execute(code)

    def ev(self, expr):
        return self.rt.eval(expr)


# ----------------------------------------------------------------------------------------------------------------------
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    mark = "ok  " if ok else "FAIL"
    if VERBOSE or not ok:
        print("  %s %s%s" % (mark, name, ("  -- " + str(detail)) if detail else ""))


BOT = r'''
-- Play a whole song with a bot. `mode`: "perfect" presses every note dead on time, "late" 60 ms late,
-- "none" presses nothing. Time is advanced a frame at a time, as the highway would.
function __play(songKey, instId, difficulty, mode, frameMs, hooks)
    local PE = ProjectEncore
    local song = PE.getSong(songKey)
    local inst = PE.getInstrument(instId)
    local session, why = PE.Session.new{ song = song, instrument = inst, difficulty = difficulty,
                                          character = __player, playerNum = 0 }
    if not session then return nil, why end
    assert(session:start())
    local binding = session.binding
    local late = (mode == "late") and 60 or 0
    local nextNote = 1
    local releaseAt = {}
    local frames = 0
    local guard = 0
    while session.state ~= "finished" do
        guard = guard + 1
        if guard > 2000000 then error("song never finished") end
        __now = __now + (frameMs or 16)
        session:update()
        if hooks and hooks.frame then hooks.frame(session) end
        frames = frames + 1
        local now = PE.Audio.inputMs()
        if mode ~= "none" then
            -- release what was held
            for lane, at in pairs(releaseAt) do
                if now >= at then
                    releaseAt[lane] = nil
                    if lane == -1 then session:openRelease() else
                        __keys[binding.fretCode[lane]] = nil
                        session:release(lane)
                    end
                end
            end
            -- press whatever has come due; chords are several notes at one time
            while session.notes[nextNote] and session.notes[nextNote].ms + late <= now do
                local first = session.notes[nextNote]
                local chord = {}
                while session.notes[nextNote] and session.notes[nextNote].chord == first.chord do
                    chord[#chord + 1] = session.notes[nextNote]
                    nextNote = nextNote + 1
                end
                local hold = 90
                for _, n in ipairs(chord) do
                    if n.sustainMs > 0 then hold = math.max(hold, n.sustainMs + 30) end
                end
                for _, n in ipairs(chord) do
                    if n.open then
                        session:openHit()
                        releaseAt[-1] = now + hold
                    else
                        __keys[binding.fretCode[n.lane]] = true
                        session:press(n.lane)
                        releaseAt[n.lane] = now + hold
                    end
                end
                if binding.needsStrum then session:strum() end
            end
        end
    end
    return session.result, frames, session
end
'''


def main():
    h = Harness()
    print("loading every Lua file the way the game does...")
    h.load_all()
    check("all %d files compiled and ran" % len(h.loaded), True)

    h.lua("triggerEvent('OnGameBoot')")
    songs = h.ev("#ProjectEncore.allSongs()")
    check("demo pack registered a song", songs == 1, "%d songs" % songs)
    check("five instruments registered, the drums switched off", h.ev("#ProjectEncore.InstrumentOrder") == 5
          and h.ev("ProjectEncore.getInstrument('drums') == nil"), "%d" % h.ev("#ProjectEncore.InstrumentOrder"))

    # ---- the demo chart
    h.lua("__song = ProjectEncore.getSong('EncoreDemo:apocalypse_run'); __chart, __err = ProjectEncore.Chart.get(__song)")
    check("demo chart parsed", h.ev("__chart ~= nil"), h.ev("tostring(__err)"))
    expected = {("Single", "Expert"): 147, ("Single", "Hard"): 135, ("Single", "Medium"): 74, ("Single", "Easy"): 43,
                ("DoubleBass", "Expert"): 84, ("Drums", "Expert"): 169}
    for (track, diff), want in expected.items():
        got = h.ev("#__chart.tracks['%s']['%s'].notes" % (track, diff))
        check("chart %s %s has %d notes" % (diff, track, want), got == want, "got %d" % got)
    check("tempo map: 120 BPM", abs(h.ev("__chart.bpms[1].bpm") - 120.0) < 1e-6)
    check("tick 768 is 2000 ms", abs(h.ev("ProjectEncore.Chart.tickToMs(__chart, 768)") - 2000.0) < 1e-6)
    check("sections and lyrics read", h.ev("#__chart.sections") == 5 and h.ev("#__chart.lyrics") > 20,
          "%d sections, %d lyric events" % (h.ev("#__chart.sections"), h.ev("#__chart.lyrics")))

    # ---- generated difficulties, from a chart that only has Expert
    h.lua(r'''
        local lines = { "[Song]", "{", "  Resolution = 192", "}", "[SyncTrack]", "{", "  0 = B 150000", "}", "[ExpertSingle]", "{" }
        local tick = 0
        local frets = { 0, 1, 2, 3, 4, 3, 2, 1 }
        for bar = 0, 39 do
            for i = 0, 15 do                                   -- sixteenth notes, with a chord at the top of every bar
                local t = bar * 768 + i * 48
                lines[#lines + 1] = "  " .. t .. " = N " .. frets[(i % 8) + 1] .. " 0"
                if i == 0 then
                    lines[#lines + 1] = "  " .. t .. " = N 2 0"
                    lines[#lines + 1] = "  " .. t .. " = N 4 0"
                end
            end
        end
        lines[#lines + 1] = "}"
        ProjectEncore.registerSongPack{ id = "T", modDir = "ProjectEncore", name = "Test" }
        __gen = ProjectEncore.registerSong{ pack = "T", id = "expertonly", title = "Expert only", sound = "X", chart = lines, lengthMs = 70000 }
        ProjectEncore.Config.guitarLanes = 5
        __counts = {}
        __maxChord = {}
        __maxLane = {}
        for _, d in ipairs({ "Easy", "Medium", "Hard", "Expert" }) do
            local notes, sp, info = ProjectEncore.Chart.buildNotes(__gen, ProjectEncore.getInstrument("guitar"), d)
            __counts[d] = #notes
            local mc, ml = 0, 0
            for _, n in ipairs(notes) do
                if n.chordSize > mc then mc = n.chordSize end
                if n.lane > ml then ml = n.lane end
            end
            __maxChord[d], __maxLane[d] = mc, ml
            __info = info
        end
        __dinfo = ProjectEncore.Chart.difficultyInfo(__gen, ProjectEncore.getInstrument("guitar"))
    ''')
    c = {d: h.ev("__counts.%s" % d) for d in ("Easy", "Medium", "Hard", "Expert")}
    check("an Expert-only chart offers four difficulties", h.ev("#__dinfo") == 4)
    check("only Expert is the charter's own", h.ev("__dinfo[4].native") and not h.ev("__dinfo[1].native"))
    check("fewer notes at each step down", c["Easy"] < c["Medium"] < c["Hard"] < c["Expert"], str(c))
    check("Hard keeps at most 82%% of Expert", c["Hard"] <= c["Expert"] * 0.83, "%.0f%%" % (100.0 * c["Hard"] / c["Expert"]))
    check("Medium keeps at most 58%%", c["Medium"] <= c["Expert"] * 0.59, "%.0f%%" % (100.0 * c["Medium"] / c["Expert"]))
    check("Easy keeps at most 36%%", c["Easy"] <= c["Expert"] * 0.37, "%.0f%%" % (100.0 * c["Easy"] / c["Expert"]))
    check("Easy is single notes on three frets", h.ev("__maxChord.Easy") == 1 and h.ev("__maxLane.Easy") <= 2,
          "chord %d, top lane %d" % (h.ev("__maxChord.Easy"), h.ev("__maxLane.Easy")))
    check("Medium is two-note chords on four frets", h.ev("__maxChord.Medium") <= 2 and h.ev("__maxLane.Medium") <= 3)
    check("Expert is untouched: three-note chords, five frets", h.ev("__maxChord.Expert") == 3 and h.ev("__maxLane.Expert") == 4)
    speeds = [h.ev("ProjectEncore.Chart.lookaheadFor('%s')" % d) for d in ("Easy", "Medium", "Hard", "Expert")]
    check("notes come faster at each step up", speeds[0] > speeds[1] > speeds[2] > speeds[3], str(speeds))
    h.lua("ProjectEncore.Config.hyperspeed = 2")
    check("hyperspeed 2 halves the runway", abs(h.ev("ProjectEncore.Chart.lookaheadFor('Expert')") - speeds[3] / 2) < 1e-6)
    h.lua("ProjectEncore.Config.hyperspeed = 1; ProjectEncore.Config.guitarLanes = 4")

    # ---- whole songs
    h.lua(BOT)
    for inst, diff in (("guitar", "Expert"), ("guitar", "Easy"), ("bass", "Hard"), ("vocals", "Expert")):
        h.lua("__r, __frames, __s = __play('EncoreDemo:apocalypse_run', '%s', '%s', 'perfect', 16)" % (inst, diff))
        ok = h.ev("__r ~= nil and __r.notesHit == __r.notesTotal and __r.fullCombo == true")
        check("perfect bot full-combos %s %s" % (inst, diff), ok,
              h.ev("__r and (__r.notesHit .. '/' .. __r.notesTotal .. ' score ' .. __r.score .. ' ' .. __r.letter) or tostring(__frames)"))
    h.lua("__r = __play('EncoreDemo:apocalypse_run', 'guitar', 'Expert', 'late', 16)")
    check("a bot 60 ms late still hits everything, graded down",
          h.ev("__r.notesHit == __r.notesTotal and __r.perfect == 0 and __r.great > 0"),
          h.ev("'perfect ' .. __r.perfect .. ' great ' .. __r.great .. ' good ' .. __r.good .. ' avg ' .. string.format('%.0f', __r.averageOffsetMs)"))
    check("and the results screen is told it was late", h.ev("__r.averageOffsetMs > 40"))

    h.lua("__sound.played = {}; __sound.volumes = {}; __r = __play('EncoreDemo:apocalypse_run', 'guitar', 'Expert', 'none', 16)")
    check("a bot that plays nothing misses everything", h.ev("__r.notesHit == 0 and __r.notesMissed == __r.notesTotal"))
    check("no-fail on: the song still runs to the end", h.ev("__r.reason") == "complete", h.ev("__r.reason"))
    check("the rock meter is on the floor", h.ev("__r.rock") == 0)
    played = list(h.ev("__sound.played").values())
    misses = [p for p in played if str(p).startswith("PE_Miss")]
    check("every miss made a clunk", len(misses) == h.ev("__r.notesMissed"), "%d clunks" % len(misses))
    check("more than one clunk sound is in use", len(set(misses)) >= 3, str(sorted(set(misses))))
    vols = list(h.ev("__sound.volumes").values())
    check("the song was muted on a miss", len(vols) > 0 and min(vols) == 0.0, "%d volume changes" % len(vols))

    h.lua("ProjectEncore.Config.noFail = false; __r = __play('EncoreDemo:apocalypse_run', 'guitar', 'Expert', 'none', 16)")
    check("no-fail off: the same bot is booed off early", h.ev("__r.reason") == "failed" and h.ev("__r.failed") is True,
          "%s after %d misses" % (h.ev("__r.reason"), h.ev("__r.notesMissed")))
    h.lua("ProjectEncore.Config.noFail = true")

    # a miss mutes, then a hit brings the song back
    h.lua(r'''
        __sound.volumes = {}
        local skipped = false
        __r = __play('EncoreDemo:apocalypse_run', 'guitar', 'Easy', 'perfect', 16)
    ''')
    check("a clean run never touches the volume", len(list(h.ev("__sound.volumes").values())) == 0)

    # ---- strum mode: chords need the shape and a strum
    h.lua("ProjectEncore.Config.requireStrum = true; __r = __play('EncoreDemo:apocalypse_run', 'guitar', 'Expert', 'perfect', 16)")
    check("strum mode: holding the chord and strumming full-combos", h.ev("__r.notesHit == __r.notesTotal"),
          h.ev("__r.notesHit .. '/' .. __r.notesTotal .. ' overstrums ' .. __r.overstrum"))
    check("strumming a hammer-on is not charged as an overstrum", h.ev("__r.overstrum") == 0, "%d" % h.ev("__r.overstrum"))
    h.lua("ProjectEncore.Config.requireStrum = false")

    # ---- the performer
    h.lua("__vars = {}; __r, __f, __s = __play('EncoreDemo:apocalypse_run', 'guitar', 'Hard', 'perfect', 16, { frame = function(s) if s.state ~= 'finished' and not ProjectEncore.Anim.current then ProjectEncore.Anim.begin(s, nil) end; ProjectEncore.Anim.update() end })")
    check("the performer was put into the action", h.ev("__vars.PerformingAction") == "PEPerform")
    check("and strummed at the chart's tempo", abs((h.ev("__vars.PETempo") or 0) - 1.0) < 0.03, "PETempo %s" % h.ev("tostring(__vars.PETempo)"))
    check("and was let go at the end", h.ev("__vars.PEPerform") == "", repr(h.ev("__vars.PEPerform")))

    return h


def ui_tests(h):
    # ---- the highway, drawn for a whole song
    h.lua(r'''
        __draws = 0
        local ui, why = ISEncoreHighway.openFor{ song = ProjectEncore.getSong('EncoreDemo:apocalypse_run'),
            instrument = ProjectEncore.getInstrument('guitar'), difficulty = 'Expert', character = __player, playerNum = 0 }
        __hw, __why = ui, why
        __frames = 0
        if ui then
            local session = ui.session
            local nextNote = 1
            while not ui.closed and __frames < 100000 do
                __now = __now + 16
                ui:prerender()
                if not ui.closed then ui:render() end
                __frames = __frames + 1
                -- press every other note, so hits, misses, flames and the mute all get drawn
                local now = ProjectEncore.Audio.inputMs()
                while session.notes[nextNote] and session.notes[nextNote].ms <= now do
                    local n = session.notes[nextNote]
                    if nextNote % 2 == 0 and not n.open then
                        ui:onKeyPress(session.binding.fretCode[n.lane])
                        ui:onKeyRelease(session.binding.fretCode[n.lane])
                    end
                    nextNote = nextNote + 1
                end
            end
        end
    ''')
    check("the highway opened", h.ev("__hw ~= nil"), h.ev("tostring(__why)"))
    check("and drew a whole song without an error", h.ev("__hw ~= nil and __hw.closed == true"),
          "%d frames, %d draw calls" % (h.ev("__frames"), h.ev("__draws")))
    per_frame = h.ev("__draws") / max(1, h.ev("__frames"))
    check("at a sane cost per frame", 20 < per_frame < 900, "%.0f draw calls a frame" % per_frame)
    check("it is not the whole screen", h.ev("__hw.width < 1920 * 0.8 and __hw.height < 1080 * 0.8"),
          "%dx%d of 1920x1080" % (h.ev("__hw.width"), h.ev("__hw.height")))

    # ---- the menu: walk it with the keyboard
    h.lua(r'''
        if ISEncoreResults and ISEncoreResults.instance then ISEncoreResults.instance:onDone() end
        __draws = 0
        __menu = ISEncoreMenu.openFor{ character = __player, playerNum = 0 }
        local m = __menu
        local function frame() m:prerender(); m:render() end
        frame()
        __page1 = m.page
        m:onKeyPress(Keyboard.KEY_DOWN); frame()
        m:onKeyPress(Keyboard.KEY_UP); frame()
        m:onKeyPress(Keyboard.KEY_RETURN); frame()
        __page2 = m.page
        m:onKeyPress(Keyboard.KEY_RETURN); frame()
        __page3 = m.page
        m:onKeyPress(Keyboard.KEY_ESCAPE); frame()
        m:onKeyPress(Keyboard.KEY_ESCAPE); frame()
        __page4 = m.page
        -- options, and binding a key
        m:onKeyPress(Keyboard.KEY_TAB); frame()
        __page5 = m.page
        for i = 1, 30 do m:onKeyPress(Keyboard.KEY_DOWN); frame() end
        for i = 1, 30 do m:onKeyPress(Keyboard.KEY_UP); frame() end
        m:onKeyPress(Keyboard.KEY_RIGHT); frame()
        m:onKeyPress(Keyboard.KEY_LEFT); frame()
        __menuDraws = __draws
    ''')
    check("the menu opens on the setlist", h.ev("__page1") == "songs", h.ev("__page1"))
    check("Enter on a song goes to the instrument", h.ev("__page2") == "instrument", h.ev("__page2"))
    check("then to the difficulty", h.ev("__page3") == "difficulty", h.ev("__page3"))
    check("Escape walks back out to the setlist", h.ev("__page4") == "songs", h.ev("__page4"))
    check("Tab opens the options", h.ev("__page5") == "options", h.ev("__page5"))
    check("the menu draws", h.ev("__menuDraws") > 100, "%d draw calls" % h.ev("__menuDraws"))

    h.lua(r'''
        local m = __menu
        m:openKeys(ProjectEncore.getInstrument("guitar"))
        m:prerender(); m:render()
        m:beginCapture(2)
        m:onKeyPress(Keyboard.KEY_Q)
        m:prerender(); m:render()
        __bound = ProjectEncore.Keys.namesFor(ProjectEncore.getInstrument("guitar")).frets[2]
        local b = ProjectEncore.Keys.build(ProjectEncore.getInstrument("guitar"))
        __boundLane = b.laneOf[Keyboard.KEY_Q]
        ProjectEncore.Keys.reset(ProjectEncore.getInstrument("guitar"))
    ''')
    check("a lane can be rebound from the menu", h.ev("__bound") == "KEY_Q", str(h.ev("__bound")))
    check("and the new key plays that lane", h.ev("__boundLane") == 1, str(h.ev("__boundLane")))

    h.lua(r'''
        local m = __menu
        m:goSongs()
        m:onKeyPress(Keyboard.KEY_RETURN); m:onKeyPress(Keyboard.KEY_RETURN)
        m:onKeyPress(Keyboard.KEY_RETURN)
        __started = ISEncoreHighway.instance ~= nil
        if ISEncoreHighway.instance then ISEncoreHighway.instance:quit() end
    ''')
    check("picking a difficulty starts the song", h.ev("__started") is True)

    # ---- everything below is a bug the game found and the harness did not, now pinned down
    ingame_tests(h)


def ingame_tests(h):
    # the context menu, called the way ISContextMenu calls it: onSelect(target, param1, ...)
    h.lua(r'''
        if ISEncoreResults.instance then ISEncoreResults.instance:onDone() end
        __guitar = __newItem("Base.GuitarElectric")
        __player.carried = { __guitar }
        __player.primary = nil
        local context = ISContextMenu:getNew()
        for _, fn in ipairs(Events.OnFillInventoryObjectContextMenu.handlers) do
            fn(0, context, { { items = { __guitar } } })
        end
        __root = context.options[1]
        __sub = __root and __root.sub
        __names = {}
        for i, option in ipairs(__sub and __sub.options or {}) do __names[i] = option.name end
        -- the first option is "play as <instrument>"
        __ok1, __err1 = pcall(__select, __sub.options[1])
        __m1 = ISEncoreMenu.instance
        __m1char = __m1 and __m1.character == __player
        __m1item = __m1 and __m1.item == __guitar
        __m1inst = __m1 and __m1.preferInstrument and __m1.preferInstrument.id
        if __m1 then __m1:closeMenu() end
        -- and the last is the options
        __ok2, __err2 = pcall(__select, __sub.options[#__sub.options])
        __m2page = ISEncoreMenu.instance and ISEncoreMenu.instance.page
        if ISEncoreMenu.instance then ISEncoreMenu.instance:closeMenu() end
    ''')
    check("right-clicking a guitar offers the menu", h.ev("__sub ~= nil and #__sub.options >= 3"),
          str(list(h.ev("__names").values())))
    check("its 'play as' option opens the menu (the engine passes target first)", h.ev("__ok1") is True and h.ev("__m1 ~= nil"),
          str(h.ev("tostring(__err1)")))
    check("with the survivor and the guitar attached", h.ev("__m1char") is True and h.ev("__m1item") is True)
    check("and the right instrument preselected", h.ev("__m1inst") == "guitar", str(h.ev("__m1inst")))
    check("its options entry opens the options", h.ev("__ok2") is True and h.ev("__m2page") == "options",
          str(h.ev("tostring(__err2)")))

    # a song opened with nothing said -- from the debug console, say -- still finds the survivor and the guitar
    h.lua(r'''
        __blockLog = {}
        __vars = {}
        __quads = {}
        local ui, why = ISEncoreHighway.openFor{ song = ProjectEncore.getSong('EncoreDemo:apocalypse_run'),
            instrument = ProjectEncore.getInstrument('guitar'), difficulty = 'Easy' }
        __bare, __bareWhy = ui, why
        __bareChar = ui and ui.session.character == __player
        __bareItem = ui and ui.session.item == __guitar
        __lockedDuring = __player:isBlockMovement()
        __consumesW = ui and ui:isKeyConsumed(Keyboard.KEY_W)
        for i = 1, 40 do __now = __now + 16; ui:prerender(); ui:render() end
        __actionUp = __vars.PerformingAction
        __variant = __vars.PEPerform
        -- the engine takes the action away mid-song: the performer must be put back
        ISTimedActionQueue.clear(__player)
        __droppedVariant = __vars.PEPerform
        for i = 1, 60 do __now = __now + 16; ui:prerender(); ui:render() end
        __restoredVariant = __vars.PEPerform
        -- where the board was drawn: the first quad of the last frame
        __quads = {}
        ui:render()
        __q = __quads[1]
        __panelX, __panelY, __panelW, __panelH = ui.x, ui.y, ui.width, ui.height
        __quads = nil
        ui:quit()
        __lockedAfter = __player:isBlockMovement()
        if ISEncoreResults.instance then ISEncoreResults.instance:onDone() end
    ''')
    check("a song opened with no character or item still opens", h.ev("__bare ~= nil"), str(h.ev("tostring(__bareWhy)")))
    check("and finds the survivor and the guitar they carry", h.ev("__bareChar") is True and h.ev("__bareItem") is True)
    check("the survivor is held still for the song", h.ev("__lockedDuring") is True)
    check("and let go when it ends", h.ev("__lockedAfter") is False, str(list(h.ev("__blockLog").values())))
    check("every key is the song's while it plays, W included", h.ev("__consumesW") is True)
    check("the performance action runs", h.ev("__actionUp") == "PEPerform" and h.ev("__variant") == "guitar",
          "%s / %s" % (h.ev("__actionUp"), h.ev("__variant")))
    check("and is put back if the engine drops it mid-song", h.ev("__droppedVariant") == "" and h.ev("__restoredVariant") == "guitar",
          "after drop %r, later %r" % (h.ev("__droppedVariant"), h.ev("__restoredVariant")))
    q = [h.ev("__q[%d]" % i) for i in range(1, 9)]
    px, py, pw, ph = h.ev("__panelX"), h.ev("__panelY"), h.ev("__panelW"), h.ev("__panelH")
    xs, ys = q[0::2], q[1::2]
    inside = min(xs) >= px - 1 and max(xs) <= px + pw + 1 and min(ys) >= py - 1 and max(ys) <= py + ph + 1
    check("the board is drawn in screen coordinates, inside its own panel", inside,
          "quad x %.0f..%.0f y %.0f..%.0f, panel at %d,%d %dx%d" % (min(xs), max(xs), min(ys), max(ys), px, py, pw, ph))
    centre = (min(xs) + max(xs)) / 2.0
    check("and centred on the screen, over the frets", abs(centre - 960) < 2, "centre x %.0f" % centre)

    # the menu: a mouse move between a page change and the next render used to index a row that was gone
    h.lua(r'''
        local m = ISEncoreMenu.openFor{ playerNum = 0 }
        m:prerender(); m:render()
        m.mouseX, m.mouseY = m.geo.listX + 20, m.hits[#m.hits].y + 4
        m:onKeyPress(Keyboard.KEY_TAB)              -- options: a different, longer page
        m:onKeyPress(Keyboard.KEY_ESCAPE)           -- and back, with stale hit boxes either way
        __moveOk, __moveErr = pcall(m.onMouseMove, m, 3, 3)
        m.hits = { { index = 999, y = m.mouseY - 2, h = 10 } }
        __moveOk2 = pcall(m.onMouseMove, m, 3, 3)
        __clickOk = pcall(m.onMouseDown, m, m.mouseX, m.mouseY)
        m:closeMenu()
    ''')
    check("a mouse move over a row that is gone is not an error", h.ev("__moveOk") is True and h.ev("__moveOk2") is True
          and h.ev("__clickOk") is True, str(h.ev("tostring(__moveErr)")))


CHART_HELPERS = r'''
-- A chart as lines, from a tempo list, signature list and note list, registered as a song in pack "R".
function __makeSong(id, opts)
    local lines = { "[Song]", "{", "  Resolution = 192", "}", "[SyncTrack]", "{" }
    for _, ts in ipairs(opts.ts or { { 0, 4 } }) do lines[#lines + 1] = "  " .. ts[1] .. " = TS " .. ts[2] end
    for _, b in ipairs(opts.bpm or { { 0, 120000 } }) do lines[#lines + 1] = "  " .. b[1] .. " = B " .. b[2] end
    lines[#lines + 1] = "}"
    lines[#lines + 1] = "[Events]"
    lines[#lines + 1] = "{"
    for _, e in ipairs(opts.sections or {}) do lines[#lines + 1] = "  " .. e[1] .. ' = E "section ' .. e[2] .. '"' end
    lines[#lines + 1] = "}"
    lines[#lines + 1] = "[ExpertSingle]"
    lines[#lines + 1] = "{"
    for _, n in ipairs(opts.notes) do lines[#lines + 1] = "  " .. n[1] .. " = N " .. n[2] .. " " .. (n[3] or 0) end
    lines[#lines + 1] = "}"
    if not ProjectEncore.Packs.R then ProjectEncore.registerSongPack{ id = "R", modDir = "ProjectEncore", name = "Regression" } end
    return ProjectEncore.registerSong{ pack = "R", id = id, title = id, sound = "X", chart = lines, lengthMs = opts.lengthMs or 120000 }
end
'''


def chart_regressions(h):
    """Bugs found from a video of a real song (2026-11-13), and the slow sort found while chasing them."""
    h.lua(CHART_HELPERS)
    have_kahlua = h.kahlua is not None

    # ---- the sort: a sorted list costs one pass, an unsorted one comes out sorted and stable
    h.lua(r'''
        local t = {}
        local seed = 12345
        for i = 1, 5000 do
            seed = (seed * 1103515245 + 12345) % 2147483648
            t[i] = { k = seed % 97, i = i }
        end
        ProjectEncore.sortBy(t, function(a, b) return a.k < b.k end)
        __sortedOk = true
        for i = 2, #t do
            if t[i].k < t[i - 1].k or (t[i].k == t[i - 1].k and t[i].i < t[i - 1].i) then __sortedOk = false end
        end
        local calls = 0
        ProjectEncore.sortBy(t, function(a, b) calls = calls + 1; return a.k < b.k end)
        __sortedAgainCalls = calls
    ''')
    check("sortBy sorts 5,000 items, ties kept in order", h.ev("__sortedOk") is True)
    check("and a list already in order costs one pass", h.ev("__sortedAgainCalls") == 4999, "%d comparisons" % h.ev("__sortedAgainCalls"))

    # ---- a 3,000-note part, parsed and built, with the game's own table.sort counting
    h.lua(r'''
        local notes = {}
        for i = 0, 2999 do notes[#notes + 1] = { i * 96, i % 5 } end
        __big = __makeSong("big", { notes = notes, lengthMs = 160000 })
        __kahluaSortCalls = 0
        ProjectEncore.Chart.get(__big)
        local inst = ProjectEncore.getInstrument("guitar")
        for _, d in ipairs({ "Expert", "Hard", "Medium", "Easy" }) do ProjectEncore.Chart.buildNotes(__big, inst, d) end
        __bigSorts = __kahluaSortCalls
        __bigCount = ProjectEncore.Chart.noteCount(__big, inst, "Expert")
    ''')
    check("a 3,000-note song parses and builds four parts with almost no table.sort work", h.ev("__bigSorts") < 20000,
          "%d comparisons through %s table.sort (it was millions)" % (h.ev("__bigSorts"), "Kahlua's" if have_kahlua else "C Lua's"))
    check("and all 3,000 notes are there", h.ev("__bigCount") == 3000, str(h.ev("__bigCount")))

    # ---- generated difficulties: in order, each inside the one above, no long silences
    h.lua(r'''
        -- 150 BPM: 16 bars of eighths, 8 bars of nothing but off-beat eighths, 16 bars of eighths.
        local notes = {}
        local frets = { 0, 1, 2, 3, 4, 3, 2, 1 }
        for bar = 0, 39 do
            for e = 0, 7 do
                local offbeatOnly = bar >= 16 and bar < 24
                if not offbeatOnly or e % 2 == 1 then
                    notes[#notes + 1] = { bar * 768 + e * 96, frets[e + 1] }
                end
            end
        end
        __synco = __makeSong("synco", { notes = notes, bpm = { { 0, 150000 } }, lengthMs = 70000 })
        local inst = ProjectEncore.getInstrument("guitar")
        local C = ProjectEncore.Chart
        local chart = C.get(__synco)
        __dc, __gapOk, __subsetOk, __syncoOk = {}, {}, true, {}
        local order = { "Easy", "Medium", "Hard", "Expert" }
        for i, d in ipairs(order) do
            local track = C.trackFor(chart, inst, d)
            __dc[d] = #track.notes
            local gap = 0
            for k = 2, #track.notes do
                local g = track.notes[k].ms - track.notes[k - 1].ms
                if g > gap then gap = g end
            end
            local rule = C.REDUCE[d]
            __gapOk[d] = rule == nil or gap <= rule.restMs + 400
            -- bars 16-23 are 25.6 s to 38.4 s
            local inSynco = 0
            for _, n in ipairs(track.notes) do if n.ms >= 25600 and n.ms < 38400 then inSynco = inSynco + 1 end end
            __syncoOk[d] = inSynco
            if i < 4 then
                local above = C.trackFor(chart, inst, order[i + 1])
                local times = {}
                for _, n in ipairs(above.notes) do times[n.ms] = true end
                for _, n in ipairs(track.notes) do if not times[n.ms] then __subsetOk = false end end
            end
        end
    ''')
    dc = {d: h.ev("__dc.%s" % d) for d in ("Easy", "Medium", "Hard", "Expert")}
    check("generated parts: fewer notes at every step down", dc["Easy"] < dc["Medium"] < dc["Hard"] < dc["Expert"], str(dc))
    check("each part is the one above it with notes taken out", h.ev("__subsetOk") is True)
    check("no generated part goes silent where the one above plays",
          all(h.ev("__gapOk.%s" % d) for d in ("Easy", "Medium", "Hard")))
    synco = {d: h.ev("__syncoOk.%s" % d) for d in ("Easy", "Medium", "Hard")}
    check("a riff with nothing on the beat keeps notes on every difficulty", min(synco.values()) >= 3, str(synco))

    # ---- a tempo of zero in the chart does not leave notes with no time
    h.lua(r'''
        local notes = {}
        for i = 0, 63 do notes[#notes + 1] = { i * 96, i % 4 } end
        __zero = __makeSong("zerotempo", { notes = notes, bpm = { { 0, 120000 }, { 1536, 0 }, { 3072, 140000 } } })
        local built = ProjectEncore.Chart.buildNotes(__zero, ProjectEncore.getInstrument("guitar"), "Expert")
        __zeroCount, __zeroFinite, __zeroOrder = #built, true, true
        for i, n in ipairs(built) do
            if not ProjectEncore.finite(n.ms) then __zeroFinite = false end
            if i > 1 and n.ms < built[i - 1].ms then __zeroOrder = false end
        end
    ''')
    check("a chart with a zero tempo in it still builds every note, in order, with a real time",
          h.ev("__zeroCount") == 64 and h.ev("__zeroFinite") is True and h.ev("__zeroOrder") is True,
          "%d notes" % h.ev("__zeroCount"))

    # ---- the beat grid: bars from the time signature, through a tempo change in the middle of a beat
    h.lua(r'''
        __grid = __makeSong("grid", { notes = { { 0, 0 }, { 6000, 1 } },
            bpm = { { 0, 120000 }, { 288, 90000 } }, ts = { { 0, 4 }, { 1536, 3 } } })
        local chart = ProjectEncore.Chart.get(__grid)
        local g = ProjectEncore.Chart.beatGrid(chart, 20000)
        __gridBars = {}
        for i = 1, 20 do __gridBars[i] = g.bar[i] and 1 or 0 end
        __gridMs3 = g.ms[3]
    ''')
    bars = [h.ev("__gridBars[%d]" % i) for i in range(1, 21)]
    want = [1 if i in (0, 4, 8, 11, 14, 17) else 0 for i in range(20)]
    check("bar lines follow the time signature (4/4, then 3/4 from bar 3)", bars == want, "".join(map(str, bars)))
    check("and a beat after a tempo change mid-beat is where the tempo map says",
          abs(h.ev("__gridMs3") - (750 + 96 / 192.0 * 60000 / 90)) < 0.01, "%.2f ms" % h.ev("__gridMs3"))


def feature_tests(h):
    """The ideas list of 2026-11-13: scores per character, mood after a song, YOU SUCK!"""
    # ---- high scores belong to the character who played
    h.lua(r'''
        ModData.store.ProjectEncoreScores = { ["EncoreDemo:apocalypse_run|guitar|Medium"] = { score = 1234, stars = 3 } }
        __alice, __bob = __newCharacter("alice"), __newCharacter("bob")
        local realPlayer = __player
        __player = __alice
        __ra = __play('EncoreDemo:apocalypse_run', 'guitar', 'Expert', 'perfect', 16)
        __player = realPlayer
        local song, inst = ProjectEncore.getSong('EncoreDemo:apocalypse_run'), ProjectEncore.getInstrument('guitar')
        __aliceBest = ProjectEncore.Score.best(song, inst, 'Expert', __alice)
        __bobBest = ProjectEncore.Score.best(song, inst, 'Expert', __bob)
        __aliceOld = ProjectEncore.Score.best(song, inst, 'Medium', __alice)
        __bobOld = ProjectEncore.Score.best(song, inst, 'Medium', __bob)
        __aliceNew = __ra.newBest
    ''')
    check("a high score is kept on the character who set it", h.ev("__aliceBest ~= nil and __aliceBest.score == __ra.score")
          and h.ev("__aliceNew") is True, str(h.ev("__aliceBest and __aliceBest.score")))
    check("and another character on the same save does not have it", h.ev("__bobBest == nil"))
    check("the save's old shared scores go to the first character to look, once",
          h.ev("__aliceOld ~= nil and __aliceOld.score == 1234") and h.ev("__bobOld == nil"))
    h.lua(r'''
        local realIsClient = isClient
        isClient = function() return true end
        local realPlayer = __player
        __player = __bob
        local before = __bob.transmits
        __rb = __play('EncoreDemo:apocalypse_run', 'guitar', 'Easy', 'perfect', 16, nil)
        __bobTransmits = __bob.transmits - before
        __player = realPlayer
        isClient = realIsClient
    ''')
    check("in multiplayer a new best is sent to the server with the character", h.ev("__rb.newBest") is True
          and h.ev("__bobTransmits") >= 1, "%d transmits" % h.ev("__bobTransmits"))

    # ---- mood, single player: a good song, a bad song, a song cut short
    h.lua(r'''
        __s0 = { b = __alice.stats.BOREDOM, u = __alice.stats.UNHAPPINESS, s = __alice.stats.STRESS }
        local realPlayer = __player
        __player = __alice
        __good = __play('EncoreDemo:apocalypse_run', 'guitar', 'Hard', 'perfect', 16)
        __s1 = { b = __alice.stats.BOREDOM, u = __alice.stats.UNHAPPINESS, s = __alice.stats.STRESS }
        __bad = __play('EncoreDemo:apocalypse_run', 'guitar', 'Hard', 'none', 16)
        __s2 = { b = __alice.stats.BOREDOM, u = __alice.stats.UNHAPPINESS, s = __alice.stats.STRESS }
        local s = ProjectEncore.Session.new{ song = ProjectEncore.getSong('EncoreDemo:apocalypse_run'), instrument = ProjectEncore.getInstrument('guitar'),
            difficulty = 'Hard', character = __alice, playerNum = 0 }
        s:start()
        for i = 1, 400 do __now = __now + 16; s:update() end
        __quit = s:finish("quit")
        __s3 = { b = __alice.stats.BOREDOM, u = __alice.stats.UNHAPPINESS, s = __alice.stats.STRESS }
        __player = realPlayer
        __trio = ProjectEncore.Mood.effect({ reason = "complete", accuracy = 0.9, lengthMs = 180000, notesTotal = 10 }, 3)
        __solo = ProjectEncore.Mood.effect({ reason = "complete", accuracy = 0.9, lengthMs = 180000, notesTotal = 10 }, 1)
        __low = ProjectEncore.Mood.effect({ reason = "complete", accuracy = 0.6, lengthMs = 180000, notesTotal = 10 }, 3)
        __off = ProjectEncore.Mood.effect({ reason = "interrupted", interrupted = true, accuracy = 1, lengthMs = 180000, notesTotal = 10 }, 1)
    ''')
    s0, s1, s2, s3 = ({k: h.ev("__s%d.%s" % (i, k)) for k in "bus"} for i in range(4))
    check("a song played well: less bored, happier, calmer", s1["b"] < s0["b"] and s1["u"] < s0["u"] and s1["s"] < s0["s"],
          "boredom %.1f -> %.1f, unhappiness %.1f -> %.1f, stress %.3f -> %.3f" % (s0["b"], s1["b"], s0["u"], s1["u"], s0["s"], s1["s"]))
    check("and the results screen is told", h.ev("__good.mood ~= nil and __good.mood.good == true"))
    check("a song played badly: more stressed and more bored", s2["b"] > s1["b"] and s2["s"] > s1["s"] and s2["u"] == s1["u"],
          "boredom %.1f -> %.1f, stress %.3f -> %.3f" % (s1["b"], s2["b"], s1["s"], s2["s"]))
    check("a song stopped early changes nothing", s3 == s2 and h.ev("__quit.mood == nil"))
    check("an interrupted one neither", h.ev("__off == nil"))
    check("a band of three makes a good song half as good again", abs(h.ev("__trio.boredom") / h.ev("__solo.boredom") - 1.5) < 1e-9,
          "%.1f vs %.1f boredom" % (h.ev("__trio.boredom"), h.ev("__solo.boredom")))
    check("and does not make a bad one worse", h.ev("__low.good == false and __low.band == 1"))

    # ---- mood, multiplayer: the client asks, the server decides
    h.lua(r'''
        local realIsClient, realSend = isClient, sendClientCommand
        __sent = {}
        isClient = function() return true end
        sendClientCommand = function(player, module, command, args) __sent[#__sent + 1] = { module = module, command = command, args = args } end
        local before = __bob.stats.BOREDOM
        __mpEffect = ProjectEncore.Mood.afterSong(__bob, { reason = "complete", accuracy = 1, lengthMs = 200000, notesTotal = 50, fullCombo = true }, 1)
        __mpClientUnchanged = __bob.stats.BOREDOM == before
        isClient, sendClientCommand = realIsClient, realSend

        -- the server: bob is in a band of three on its roster
        ProjectEncore.BandServer.memberOf = { alice = "alice", bob = "alice", carl = "alice" }
        ProjectEncore.BandServer.bands = { alice = { members = { alice = {}, bob = {}, carl = {} } } }
        local args = __sent[1] and __sent[1].args
        __srv1 = ProjectEncore.Mood.serverHandle(__bob, args)
        __bobAfter = __bob.stats.BOREDOM
        __srv2 = ProjectEncore.Mood.serverHandle(__bob, args)                      -- straight away: refused
        __now = __now + 60000
        __srv3 = ProjectEncore.Mood.serverHandle(__bob, { reason = "complete", accuracy = 1, lengthMs = 9000000, notesTotal = 50 })
        __srv3Solo = ProjectEncore.Mood.effect({ reason = "complete", accuracy = 1, lengthMs = 60000, notesTotal = 50 }, 3)
        ProjectEncore.BandServer.memberOf, ProjectEncore.BandServer.bands = {}, {}
    ''')
    check("in multiplayer the client sends the song to the server instead of changing stats itself",
          h.ev("__mpClientUnchanged") is True and h.ev("#__sent") == 1 and h.ev("__sent[1].command") == "Mood"
          and h.ev("__sent[1].module") == "ProjectEncore")
    check("the server applies it, with the band counted from its own roster", h.ev("__srv1 ~= nil and __srv1.bandSize == 3")
          and h.ev("__bobAfter") < 50, "band %s, boredom now %.1f" % (h.ev("__srv1 and __srv1.bandSize"), h.ev("__bobAfter")))
    check("a second claim straight after is refused", h.ev("__srv2 == nil"))
    check("and a song cannot be longer than the time since the last one",
          abs(h.ev("__srv3.boredom") - h.ev("__srv3Solo.boredom")) < 1e-9, "%.2f" % h.ev("__srv3.boredom"))

    # ---- two strum keys, down and up
    h.lua(r'''
        local Keys = ProjectEncore.Keys
        local guitar = ProjectEncore.getInstrument("guitar")
        Keys.reset(guitar)
        local names = Keys.namesFor(guitar)
        __strum1, __strum2, __openKey = names.strum[1], names.strum[2], names.open
        -- a binding saved back when there was one strum key
        Keys.save(guitar, names.frets, { "KEY_SPACE" }, "KEY_SPACE")
        local old = Keys.namesFor(guitar)
        __oldStrum = table.concat(old.strum, ",")
        Keys.reset(guitar)

        -- a whole song in strum mode through the highway's own key handling, alternating down and up
        ProjectEncore.Config.requireStrum = true
        local ui = ISEncoreHighway.openFor{ song = ProjectEncore.getSong('EncoreDemo:apocalypse_run'), instrument = guitar,
            difficulty = 'Easy', character = __player, playerNum = 0 }
        local s = ui.session
        local b = s.binding
        local downCode, upCode = Keyboard.KEY_DOWN, Keyboard.KEY_UP
        local nextNote, releases, useUp = 1, {}, false
        __usedDown, __usedUp = 0, 0
        local frames = 0
        while not ui.closed and frames < 20000 do
            __now = __now + 16
            frames = frames + 1
            ui:prerender()
            if ui.closed then break end
            local now = ProjectEncore.Audio.inputMs()
            for code, at in pairs(releases) do
                if now >= at then releases[code] = nil; __keys[code] = nil; ui:onKeyRelease(code) end
            end
            while s.notes[nextNote] and s.notes[nextNote].ms <= now do
                local first = s.notes[nextNote]
                local held = {}
                while s.notes[nextNote] and s.notes[nextNote].chord == first.chord do
                    local n = s.notes[nextNote]
                    if not n.open then held[#held + 1] = b.fretCode[n.lane] end
                    nextNote = nextNote + 1
                end
                for _, code in ipairs(held) do __keys[code] = true; ui:onKeyPress(code) end
                local strumCode = useUp and upCode or downCode
                if useUp then __usedUp = __usedUp + 1 else __usedDown = __usedDown + 1 end
                useUp = not useUp
                ui:onKeyPress(strumCode)
                ui:onKeyRelease(strumCode)
                for _, code in ipairs(held) do releases[code] = now + 90 end
            end
            ui:render()
        end
        __strumRun = s.result
        ProjectEncore.Config.requireStrum = false
        if ISEncoreResults.instance then ISEncoreResults.instance:onDone() end

        -- binding strum up and the open note from the key page
        local m = ISEncoreMenu.openFor{ character = __player, playerNum = 0 }
        m:openKeys(guitar)
        m:prerender(); m:render()
        local lanes = ProjectEncore.laneCount(guitar)
        __slotCount = m:keySlots()
        m:beginCapture(lanes + 2); m:onKeyPress(Keyboard.KEY_W)
        m:beginCapture(lanes + 3); m:onKeyPress(Keyboard.KEY_E)
        m:prerender(); m:render()
        local after = Keys.namesFor(guitar)
        __boundUp, __boundOpen, __keptDown = after.strum[2], after.open, after.strum[1]
        local built = Keys.build(guitar)
        __wStrums = built.isStrum[Keyboard.KEY_W] == true
        Keys.reset(guitar)
        m:closeMenu()
    ''')
    check("guitars strum down and up on the arrows, and keep Space for open notes",
          (h.ev("__strum1"), h.ev("__strum2"), h.ev("__openKey")) == ("KEY_DOWN", "KEY_UP", "KEY_SPACE"),
          "%s %s / open %s" % (h.ev("__strum1"), h.ev("__strum2"), h.ev("__openKey")))
    check("a binding saved with one strum key gets a second", h.ev("__oldStrum") == "KEY_SPACE,KEY_DOWN", h.ev("__oldStrum"))
    check("strum mode: a song strummed alternately down and up is a full combo",
          h.ev("__strumRun ~= nil and __strumRun.notesHit == __strumRun.notesTotal and __strumRun.overstrum == 0")
          and h.ev("__usedDown") > 5 and h.ev("__usedUp") > 5,
          h.ev("__strumRun and (__strumRun.notesHit .. '/' .. __strumRun.notesTotal .. ', ' .. __strumRun.overstrum .. ' overstrums') or 'no result'")
          + ", %d down / %d up" % (h.ev("__usedDown"), h.ev("__usedUp")))
    check("the key page has strum down, strum up and the open note after the lanes", h.ev("__slotCount") == 4 + 3,
          "%d guitar slots" % h.ev("__slotCount"))
    check("and binds each of them", (h.ev("__boundUp"), h.ev("__boundOpen"), h.ev("__keptDown")) == ("KEY_W", "KEY_E", "KEY_DOWN")
          and h.ev("__wStrums") is True, "%s %s %s" % (h.ev("__boundUp"), h.ev("__boundOpen"), h.ev("__keptDown")))

    # ---- the verdict
    h.lua(r'''
        local function headline(res)
            local ui = ISEncoreResults.openFor(res, nil)
            __now = __now + 500                       -- the headline fades in over its first quarter second
            __texts = {}
            ui:render()
            local said = __texts[1] or ""
            __texts = nil
            ui:onDone()
            return said
        end
        local base = { song = ProjectEncore.getSong('EncoreDemo:apocalypse_run'), instrument = ProjectEncore.getInstrument('guitar'),
            difficulty = 'Hard', score = 1000, accuracy = 0.8, notesHit = 80, notesTotal = 100, notesMissed = 20,
            bestStreak = 12, perfect = 10, great = 10, good = 60, letter = "C", averageOffsetMs = 0 }
        local function with(stars, extra)
            local r = {}
            for k, v in pairs(base) do r[k] = v end
            r.stars = stars
            for k, v in pairs(extra or {}) do r[k] = v end
            return r
        end
        __v0 = headline(with(0)); __v2 = headline(with(2)); __v3 = headline(with(3)); __v4 = headline(with(4))
        __vFail = headline(with(1, { failed = true }))
    ''')
    v = {k: h.ev("__v%s" % k) for k in ("0", "2", "3", "4", "Fail")}
    check("0 to 2 stars: YOU SUCK!", v["0"] == "IGUI_PE_YouSuck" and v["2"] == "IGUI_PE_YouSuck", str(v))
    check("3 stars and up: YOU ROCK!", v["3"] == "IGUI_PE_YouRock" and v["4"] == "IGUI_PE_YouRock")
    check("a failed song still says it failed", v["Fail"] == "IGUI_PE_SongFailed")


def band_tests(h):
    """A band, end to end, through the real server code: this client hosts, a second player's messages go straight to
    the server and its replies to him are written down. Commands travel the way the engine carries them."""
    h.lua(r'''
        local realIsClient = isClient
        isClient = function() return true end
        __player.name = "alice"
        __bob = __newCharacter("bob")
        __bobInbox = {}
        function getPlayerFromUsername(name)
            if name == "alice" then return __player end
            if name == "bob" then return __bob end
            return nil
        end
        function sendClientCommand(player, module, command, args)
            -- what the engine does: the server's OnClientCommand, with the sender
            for _, fn in ipairs(Events.OnClientCommand.handlers) do fn(module, command, player, args) end
        end
        function sendServerCommand(player, module, command, args)
            if player == __player then
                for _, fn in ipairs(Events.OnServerCommand.handlers) do fn(module, command, args) end
            else
                __bobInbox[#__bobInbox + 1] = { command = command, args = args }
            end
        end
        local function tick()
            for _, fn in ipairs(Events.OnTick.handlers) do fn() end
        end
        local BC = ProjectEncore.BandClient

        -- alice starts a band on rhythm guitar -- a part the demo song does not have -- and bob joins on bass
        BC.create("rhythm", "Easy")
        sendClientCommand(__bob, "ProjectEncore", "BandJoin", { host = "alice", role = "bass", difficulty = "Medium" })
        __members = BC.state and #BC.state.members or 0

        -- the host picks the song: straight off the setlist, no instrument or difficulty page
        local m = ISEncoreMenu.openFor{ character = __player, playerNum = 0 }
        m:prerender(); m:render()
        m:pickSong(ProjectEncore.getSong('EncoreDemo:apocalypse_run'))      -- what Enter on its row does
        __menuClosed = ISEncoreMenu.instance == nil
        __bobStart = nil
        for _, msg in ipairs(__bobInbox) do if msg.command == "BandStart" then __bobStart = msg.args end end

        -- the start is a delay on this client's own clock
        __now = __now + 2000
        tick()
        local ui = ISEncoreHighway.instance
        __bandHighway = ui ~= nil
        __bandPart = ui and ui.session.instrument.id
        -- play it through, every note
        local frames = 0
        while ui and not ui.closed and frames < 20000 do
            __now = __now + 16
            frames = frames + 1
            ui:prerender()
            if ui.closed then break end
            local s = ui.session
            local now = ProjectEncore.Audio.inputMs()
            local n = s.notes[s.active]
            while n and n.ms <= now + 8 do
                if n.open then ui:onKeyPress(s.binding.openCode); ui:onKeyRelease(s.binding.openCode)
                else ui:onKeyPress(s.binding.fretCode[n.lane]); ui:onKeyRelease(s.binding.fretCode[n.lane]) end
                if s.notes[s.active] == n then break end
                n = s.notes[s.active]
            end
            ui:render()
        end
        __aliceResult = ui and ui.session.result
        local res = ISEncoreResults.instance
        __resultsOpen = res ~= nil
        local function screenText()
            __texts = {}
            res:render()
            local all = table.concat(__texts, "\n")
            __texts = nil
            return all
        end
        __screen1 = res and screenText() or ""
        -- bob finishes after alice
        sendClientCommand(__bob, "ProjectEncore", "BandFinished", { score = 12345, accuracy = 0.9 })
        __screen2 = res and screenText() or ""
        __lobbyAgain = BC.state and BC.state.state
        if res then res:onDone() end
        BC.leave()
        sendClientCommand(__bob, "ProjectEncore", "BandLeave", {})
        isClient = realIsClient
        sendClientCommand, sendServerCommand, getPlayerFromUsername = nil, nil, nil
    ''')
    check("a band forms on the server with both players in it", h.ev("__members") == 2, str(h.ev("__members")))
    check("the host's Enter on a song starts it for the band, with no instrument page",
          h.ev("__menuClosed") is True and h.ev("__bobStart ~= nil and __bobStart.role == 'bass'"),
          str(h.ev("__bobStart and __bobStart.songKey")))
    check("the song opens on the host's screen after the start delay", h.ev("__bandHighway") is True)
    check("a part the song does not have falls back to one it does", h.ev("__bandPart") == "guitar", str(h.ev("__bandPart")))
    check("the host plays it through", h.ev("__aliceResult ~= nil and __aliceResult.notesHit == __aliceResult.notesTotal"),
          str(h.ev("__aliceResult and (__aliceResult.notesHit .. '/' .. __aliceResult.notesTotal)")))
    check("the results list the band, with bob still playing", h.ev("__resultsOpen") is True
          and "IGUI_PE_StillPlaying" in h.ev("__screen1") and "bob" in h.ev("__screen1"))
    check("and fill in his score when he finishes", "12,345" in h.ev("__screen2") and "IGUI_PE_BandScore" in h.ev("__screen2"))
    check("the band is back in the lobby for the next song", h.ev("__lobbyAgain") == h.ev("ProjectEncore.Band.LOBBY"),
          str(h.ev("__lobbyAgain")))
    check("the mood boost counted a band of two", h.ev("__aliceResult.mood ~= nil and __aliceResult.mood.bandSize == 2"),
          str(h.ev("__aliceResult.mood and __aliceResult.mood.bandSize")))


def anim_files_tests():
    """The animation nodes and clips, read as files: every hand-over matched, every loop seamless."""
    import re
    import xml.dom.minidom
    actions = os.path.join(MOD, "42", "media", "AnimSets", "player", "actions")
    anims = os.path.join(MOD, "42", "media", "anims_X", "Bob")
    nodes = {}
    for path in glob.glob(os.path.join(actions, "PE_*.xml")):
        doc = xml.dom.minidom.parse(path)
        def text(tag, root=doc):
            el = root.getElementsByTagName(tag)
            return el[0].firstChild.nodeValue.strip() if el and el[0].firstChild else None
        tr = doc.getElementsByTagName("m_Transitions")
        nodes[text("m_Name")] = dict(
            clip=text("m_AnimName"), blend=text("m_BlendTime"), out=text("m_BlendOutTime"),
            target=text("m_Target", tr[0]) if tr else None,
            tin=text("m_blendInTime", tr[0]) if tr else None, tout=text("m_blendOutTime", tr[0]) if tr else None)
    bad = []
    for name, n in sorted(nodes.items()):
        partner = nodes.get(n["target"])
        if not partner or partner["target"] != name:
            bad.append("%s -> %s is not answered" % (name, n["target"]))
        elif len({n["blend"], n["out"], n["tin"], n["tout"], partner["blend"], partner["tin"]}) != 1:
            bad.append("%s fades %s/%s, its transition %s/%s" % (name, n["blend"], n["out"], n["tin"], n["tout"]))
    check("every performance node hands over to its partner with one fade time both ways", not bad and len(nodes) == 10,
          "; ".join(bad) or "%d nodes" % len(nodes))
    ours = sorted({n["clip"] for n in nodes.values() if n["clip"].startswith("PE_")})
    missing = [c for c in ours if not os.path.isfile(os.path.join(anims, c + ".X"))]
    check("every clip of the mod's own that a node names exists", not missing and len(ours) == 4,
          "missing %s" % missing if missing else ", ".join(ours))

    # A loop has to end where it begins, bone for bone, or it jumps once a bar.
    seams = []
    for clip in ours:
        src = open(os.path.join(anims, clip + ".X"), encoding="utf-8", errors="replace").read()
        body = src[src.index("AnimationSet"):]
        for bone, block in re.findall(r"\{\s*(Bip01[\w]*)\s*\}(.*?)\n \}", body, re.S):
            m = re.search(r"AnimationKey R \{\s*0;\s*(\d+);(.*?)\}", block, re.S)
            if not m:
                continue
            keys = re.findall(r"(\d+);4;([-\d.e]+),([-\d.e]+),([-\d.e]+),([-\d.e]+);;", m.group(2))
            if len(keys) < 2:
                continue
            a = [float(v) for v in keys[0][1:]]
            b = [float(v) for v in keys[-1][1:]]
            d = abs(sum(x * y for x, y in zip(a, b)))
            if d < 0.99995:
                seams.append("%s %s" % (clip, bone))
    check("all four clips loop without a jump", not seams, ", ".join(seams[:6]))


def anim_sp_tests(h):
    # ---- the singer holds the microphone, and stays singing between words
    h.lua(r'''
        __handModel = nil
        local s = ProjectEncore.Session.new{ song = ProjectEncore.getSong('EncoreDemo:apocalypse_run'),
            instrument = ProjectEncore.getInstrument('vocals'), difficulty = 'Expert', character = __player, playerNum = 0 }
        s:start()
        ProjectEncore.Anim.begin(s, nil)
        ProjectEncore.Anim.update()
        __singerModel = __handModel
        __singerVariant = __vars.PEPerform
        ProjectEncore.Anim.hit()
        __now = __now + 900                      -- longer than a strum is held, shorter than a line's breath
        ProjectEncore.Anim.update()
        __stillSinging = __vars.PEHit
        __now = __now + 600
        ProjectEncore.Anim.update()
        __backToIdle = __vars.PEHit
        s:finish("quit")
        ProjectEncore.Anim.finish()
        -- a harmonica in hand still gets the harmonica, held as itself
        __handModel = nil
        local harp = __newItem("Base.Harmonica")
        local s2 = ProjectEncore.Session.new{ song = ProjectEncore.getSong('EncoreDemo:apocalypse_run'),
            instrument = ProjectEncore.getInstrument('vocals'), difficulty = 'Expert', character = __player, playerNum = 0, item = harp }
        s2:start()
        ProjectEncore.Anim.begin(s2, harp)
        __harpVariant = __vars.PEPerform
        __harpModel = __handModel
        s2:finish("quit")
        ProjectEncore.Anim.finish()
    ''')
    check("the singer holds the game's microphone", h.ev("__singerModel") == "Microphone" and h.ev("__singerVariant") == "vocals",
          "%s / %s" % (h.ev("tostring(__singerModel)"), h.ev("tostring(__singerVariant)")))
    check("and keeps singing across the gap between two words", h.ev("__stillSinging") == "hit" and h.ev("__backToIdle") == "idle",
          "%s then %s" % (h.ev("__stillSinging"), h.ev("__backToIdle")))
    check("a harmonica in hand is still played as a harmonica", h.ev("__harpVariant") == "harmonica"
          and h.ev("type(__harpModel)") == "table", "%s / %s" % (h.ev("__harpVariant"), h.ev("type(__harpModel)")))

    # ---- star power
    h.lua(r'''
        local S = ProjectEncore.Score
        local t = S.new(10)
        t.starPowerCharge = 0.75
        S.miss(t)
        __afterMiss = t.starPowerCharge

        local ui = ISEncoreHighway.openFor{ song = ProjectEncore.getSong('EncoreDemo:apocalypse_run'), instrument = ProjectEncore.getInstrument('guitar'),
            difficulty = 'Expert', character = __player, playerNum = 0 }
        local s = ui.session
        __texturesAsked = {}
        local function frame() __now = __now + 16; ui:prerender(); ui:render() end
        for i = 1, 260 do frame() end                 -- into the song
        -- a phrase note on its way down, drawn before star power
        __phraseNoteKey = nil
        for i = s.render, #s.notes do
            if s.notes[i].sp and not s.notes[i].hit and not s.notes[i].missed then __phraseNoteKey = ui:noteKey(s.notes[i]); break end
        end
        __tooEarly = (function() s.tally.starPowerCharge = 0.3; ui:onKeyPress(Keyboard.KEY_RETURN); return s.tally.starPower end)()
        s.tally.starPowerCharge = 0.5
        __texts = {}
        ui:onKeyPress(Keyboard.KEY_RETURN)
        __lit = s.tally.starPower
        __litMult = s.tally.multiplier
        frame()
        __shout = false
        for _, txt in ipairs(__texts) do if txt == "IGUI_PE_StarPowerGo" then __shout = true end end
        __texts = nil
        __litNoteKey = s.notes[s.active] and ui:noteKey(s.notes[s.active])
        -- the meter shakes: the dial is not in the same place two frames running
        __quads = {}
        frame()
        local m1x, m1y = ui.meterDrawnX, ui.meterDrawnY
        frame()
        local m2x, m2y = ui.meterDrawnX, ui.meterDrawnY
        __quads = nil
        __shakes = (m1x ~= m2x or m1y ~= m2y)
        -- half a meter is eight seconds, give or take a frame; nothing else charges it in a song with no phrase near
        local start = s:now()
        local guard = 0
        while s.tally.starPower and guard < 2000 do frame(); guard = guard + 1 end
        __litFor = s:now() - start
        __afterMult = s.tally.multiplier
        ui:quit()
        if ISEncoreResults.instance then ISEncoreResults.instance:onDone() end
    ''')
    check("a miss no longer empties banked star power", abs(h.ev("__afterMiss") - 0.75) < 1e-9, "%.2f" % h.ev("__afterMiss"))
    check("phrase notes are white stars until star power is lit", h.ev("__phraseNoteKey") == "w", str(h.ev("__phraseNoteKey")))
    check("Enter does nothing under half a meter", h.ev("__tooEarly") is False)
    check("Enter lights it from half a meter, doubling the multiplier", h.ev("__lit") is True and h.ev("__litMult") >= 2,
          "x%s" % h.ev("__litMult"))
    check("with STAR POWER! across the screen", h.ev("__shout") is True)
    check("every note is a blue star while it is lit", h.ev("__litNoteKey") == "sp", str(h.ev("__litNoteKey")))
    check("the meter shakes while it burns", h.ev("__shakes") is True)
    lit_for = h.ev("__litFor")
    check("half a meter burns for about eight seconds, then goes out", 7500 < lit_for < 9500 and h.ev("__afterMult") < h.ev("__litMult"),
          "%.1f s" % (lit_for / 1000.0))
    asked = [p for p in h.ev("__texturesAsked").keys()]
    textures = os.path.join(MOD, "42", "media")
    missing = sorted(p for p in asked if not os.path.isfile(os.path.join(textures, *str(p).replace("media/", "", 1).split("/"))))
    check("every sprite the highway asked for is a real file", not missing and any("star_sp" in str(p) for p in asked),
          ", ".join(missing) or "%d sprites" % len(asked))


def frame_rate_tests(h):
    """The highway on every frame: the game's offscreen UI rendering off for a song, and back after."""
    h.lua(r'''
        local song = ProjectEncore.getSong('EncoreDemo:apocalypse_run')
        local guitar = ProjectEncore.getInstrument('guitar')
        local function open() return ISEncoreHighway.openFor{ song = song, instrument = guitar, difficulty = 'Easy',
            character = __player, playerNum = 0 } end
        local function close(ui)
            ui:quit()
            if ISEncoreResults.instance then ISEncoreResults.instance:onDone() end
        end
        __uiFbo = true
        local ui = open()
        __offDuring = __uiFbo
        __guardDuring = __files[ProjectEncore.FrameRate.GUARD_FILE]
        close(ui)
        __backAfter = __uiFbo
        __guardAfter = __files[ProjectEncore.FrameRate.GUARD_FILE]
        -- a player who already had it off keeps it off, before and after
        __uiFbo = false
        ui = open(); close(ui)
        __stillOff = __uiFbo
        -- and one who opted out keeps it on through the song
        __uiFbo = true
        ProjectEncore.Config.fullFrameRate = false
        ui = open()
        __optOut = __uiFbo
        close(ui)
        ProjectEncore.Config.fullFrameRate = true
        -- the game closed mid-song: the next world start puts it back
        __uiFbo = false
        __files[ProjectEncore.FrameRate.GUARD_FILE] = "restore uiRenderOffscreen\n"
        ProjectEncore.FrameRate.checkGuard()
        __restoredOnStart = __uiFbo
        __guardCleared = __files[ProjectEncore.FrameRate.GUARD_FILE]
        __uiFbo = true
    ''')
    check("a song switches the game's offscreen UI rendering off, so the highway is drawn every frame",
          h.ev("__offDuring") is False and "restore" in str(h.ev("__guardDuring")))
    check("and switches it back on when the song closes", h.ev("__backAfter") is True and h.ev("__guardAfter") == "")
    check("a player who had it off already is left alone", h.ev("__stillOff") is False)
    check("and so is one who turned the option off", h.ev("__optOut") is True)
    check("if the game closed mid-song, the next start puts it back", h.ev("__restoredOnStart") is True
          and h.ev("__guardCleared") == "")


def hit_window_tests(h):
    """Fast runs on one fret ("spam notes"), and the hit window setting."""
    h.lua(CHART_HELPERS)
    h.lua(r"""
        -- sixteen notes on one fret, a tenth of a second apart (sixteenths at 150 BPM)
        local notes = {}
        for i = 0, 15 do notes[#notes + 1] = { 768 + i * 48, 0 } end
        __jack = __makeSong("jack", { notes = notes, bpm = { { 0, 150000 } }, lengthMs = 8000 })
        local single = __makeSong("single", { notes = { { 768, 0 } }, bpm = { { 0, 150000 } }, lengthMs = 5000 })

        -- play a song pressing lane 0 at the given offsets from each note (nil: skip that note)
        function __playOffsets(song, offsetOf)
            local s = ProjectEncore.Session.new{ song = song, instrument = ProjectEncore.getInstrument("guitar"), difficulty = "Expert",
                character = __player, playerNum = 0 }
            assert(s:start())
            local presses = {}
            for i, n in ipairs(s.notes) do
                local off = offsetOf(i)
                if off then presses[#presses + 1] = n.ms + off end
            end
            table.sort(presses)
            local k = 1
            local guard = 0
            while s.state ~= "finished" and guard < 100000 do
                guard = guard + 1
                __now = __now + 4
                s:update()
                local now = ProjectEncore.Audio.inputMs()
                while presses[k] and presses[k] <= now do
                    s:press(0); s:release(0)
                    k = k + 1
                end
            end
            return s.result
        end
    """)
    h.lua(r"""
        ProjectEncore.Config.hitWindow = "normal"
        __skip = __playOffsets(__jack, function(i) if i == 6 then return nil end return 0 end)
        __late = __playOffsets(__jack, function(i) return 60 end)
        __n160 = __playOffsets(ProjectEncore.getSong("R:single"), function(i) return 160 end)
        ProjectEncore.Config.hitWindow = "wide"
        __w160 = __playOffsets(ProjectEncore.getSong("R:single"), function(i) return 160 end)
        ProjectEncore.Config.hitWindow = "normal"
    """)
    skip = {k: h.ev("__skip.%s" % k) for k in ("notesHit", "notesMissed", "perfect", "good")}
    check("a skipped note in a fast run on one fret costs that note and nothing else",
          skip["notesHit"] == 15 and skip["notesMissed"] == 1 and skip["perfect"] == 15, str(skip))
    late = {k: h.ev("__late.%s" % k) for k in ("notesHit", "notesMissed", "great")}
    check("a run played 60 ms late still hits every note, each its own", late["notesHit"] == 16
          and late["notesMissed"] == 0 and late["great"] == 16, str(late))
    check("normal window: 160 ms late is a miss", h.ev("__n160.notesHit") == 0)
    check("wide window: 160 ms late still counts", h.ev("__w160.notesHit") == 1)
    check("the windows are wider than they were (perfect 40, great 85, good 135 ms)",
          h.ev("ProjectEncore.Config.windowPerfectMs") == 40 and h.ev("ProjectEncore.Config.windowGreatMs") == 85
          and h.ev("ProjectEncore.Config.windowGoodMs") == 135 and h.ev("ProjectEncore.Score.missAfterMs()") > h.ev("ProjectEncore.Score.hitWindowMs()"))


def vocals_render_tests(h):
    """Vocals, drawn: currentLyric runs every frame, and once threw on every one of them."""
    h.lua(r'''
        local ui = ISEncoreHighway.openFor{ song = ProjectEncore.getSong('EncoreDemo:apocalypse_run'),
            instrument = ProjectEncore.getInstrument('vocals'), difficulty = 'Expert', character = __player, playerNum = 0 }
        __vocalErr = nil
        __vocalLines = 0
        local frames = 0
        while ui and not ui.closed and frames < 6000 do
            __now = __now + 16
            frames = frames + 1
            local ok, err = pcall(function()
                ui:prerender()
                if not ui.closed then
                    __texts = {}
                    ui:render()
                    for _, t in ipairs(__texts) do if string.find(t, " ", 1, true) and #t > 6 then __vocalLines = __vocalLines + 1 end end
                    __texts = nil
                end
            end)
            if not ok then __vocalErr = tostring(err); break end
        end
        __vocalFrames = frames
        if ui and not ui.closed then ui:quit() end
        if ISEncoreResults.instance then ISEncoreResults.instance:onDone() end
    ''')
    check("a vocal part draws a whole song without an error", h.ev("__vocalErr") is None,
          str(h.ev("__vocalErr")) + " after %d frames" % h.ev("__vocalFrames"))
    check("and shows the words of the line being sung", h.ev("__vocalLines") > 50, "%d frames with a line" % h.ev("__vocalLines"))

    # star power from three whole lamps, and not from two and a bit
    h.lua(r'''
        local S = ProjectEncore.Score
        local t = S.new(10)
        t.starPowerCharge = 0.45
        __sp45 = S.canUseStarPower(t)
        t.starPowerCharge = 0.1 + 0.4 - 1e-9          -- part-hit phrases summing to half, a hair short in a float
        __spHalf = S.canUseStarPower(t)
    ''')
    check("star power lights from half the meter (three whole lamps)", h.ev("__spHalf") is True)
    check("and not from two lamps and part of a third", h.ev("__sp45") is False)


def render_regressions(h):
    # ---- a long rest says so, and the session logs the longest one
    h.lua(r'''
        local notes = {}
        for i = 0, 15 do notes[#notes + 1] = { i * 192, i % 4 } end
        for i = 0, 15 do notes[#notes + 1] = { 7680 + i * 192, i % 4 } end      -- 12.5 s of rest at 120 BPM
        __rest = __makeSong("rest", { notes = notes, sections = { { 0, "Verse" }, { 2880, "Breakdown" } }, lengthMs = 30000 })
        local logged = {}
        local realLog = ProjectEncore.log
        ProjectEncore.log = function(msg) logged[#logged + 1] = tostring(msg) end
        local ui = ISEncoreHighway.openFor{ song = __rest, instrument = ProjectEncore.getInstrument("guitar"),
            difficulty = "Expert", character = __player, playerNum = 0 }
        ProjectEncore.log = realLog
        __restLog = table.concat(logged, "\n")
        __restTexts = {}
        local sawRest = false
        local frames = 0
        -- play every note, so the countdown is about the rest and not about misses
        while not ui.closed and frames < 3000 do
            __now = __now + 16
            frames = frames + 1
            ui:prerender()
            if ui.closed then break end
            local s = ui.session
            local n = s.notes[s.active]
            if n and math.abs(n.ms - ProjectEncore.Audio.inputMs()) < 20 then
                ui:onKeyPress(s.binding.fretCode[n.lane]); ui:onKeyRelease(s.binding.fretCode[n.lane])
            end
            __texts = {}
            ui:render()
            for _, t in ipairs(__texts) do
                if string.find(t, "IGUI_PE_RestFor", 1, true) then sawRest = true; __restTexts[#__restTexts + 1] = t end
            end
            __texts = nil
            if s:now() > 9000 then break end
        end
        __sawRest = sawRest
        if not ui.closed then ui:quit() end
        if ISEncoreResults and ISEncoreResults.instance then ISEncoreResults.instance:onDone() end
    ''')
    check("an empty highway in a long rest says when the next note is", h.ev("__sawRest") is True,
          (h.ev("__restTexts[1]") or "") + " ... " + (h.ev("__restTexts[#__restTexts]") or ""))
    check("and the song's start is logged with its longest rest", "longest rest 12.5s at 0:08 (Breakdown)" in h.ev("__restLog"),
          h.ev("__restLog"))

    # ---- what a frame of the highway leaves for the garbage collector: tables, strings and closures (C Lua does not
    # allocate numbers, so this is a floor on what Kahlua makes, not the whole of it)
    h.lua(r'''
        local bpm = {}
        for beat = 0, 899 do bpm[#bpm + 1] = { beat * 192, 110000 + (beat % 7) * 1000 } end   -- a tempo change every beat
        local notes = {}
        for i = 0, 1799 do notes[#notes + 1] = { i * 96, i % 5, (i % 16 == 0) and 192 or 0 } end
        __churn = __makeSong("churn", { notes = notes, bpm = bpm, lengthMs = 400000 })
        local ui = ISEncoreHighway.openFor{ song = __churn, instrument = ProjectEncore.getInstrument("guitar"),
            difficulty = "Expert", character = __player, playerNum = 0 }
        for i = 1, 450 do __now = __now + 16; ui:prerender(); ui:render() end     -- past the count-in and the banner
        collectgarbage("collect")
        collectgarbage("stop")
        local before = collectgarbage("count")
        local frames = 300
        for i = 1, frames do __now = __now + 16; ui:prerender(); ui:render() end
        __churnKb = (collectgarbage("count") - before) / frames
        collectgarbage("restart")
        -- Java calls: every draw, and every text measured. Each is a reflective call from Kahlua, every frame.
        local tm = getTextManager()
        local realX = tm.MeasureStringX
        __measured = 0
        tm.MeasureStringX = function(...) __measured = __measured + 1; return realX(...) end
        __draws = 0
        for i = 1, frames do __now = __now + 16; ui:prerender(); ui:render() end
        tm.MeasureStringX = realX
        __churnDraws = __draws / frames
        __churnMeasures = __measured / frames
        -- And the Lua instructions a frame runs: in Kahlua every number an instruction makes is a new object, so this
        -- is the closer measure of what the game's collector sees. Before the beat grid and the cached board it was
        -- about 29,000 on this chart, 15,000 of them walking the tempo map.
        local ticks = 0
        debug.sethook(function() ticks = ticks + 1 end, "", 100)
        for i = 1, frames do __now = __now + 16; ui:prerender(); ui:render() end
        debug.sethook()
        __churnIns = ticks * 100 / frames
        ui:quit()
        if ISEncoreResults and ISEncoreResults.instance then ISEncoreResults.instance:onDone() end
    ''')
    check("a frame of the highway makes under 1 KB of tables and strings", h.ev("__churnKb") < 1.0,
          "%.2f KB a frame on a chart with a tempo change every beat" % h.ev("__churnKb"))
    check("and runs under 10,000 Lua instructions", h.ev("__churnIns") < 10000,
          "%d a frame (it was about 29,000)" % h.ev("__churnIns"))
    check("and makes under 100 draw calls, measuring no text", h.ev("__churnDraws") < 100 and h.ev("__churnMeasures") < 0.5,
          "%.0f draw calls, %.1f measures a frame (it was 147 and 12)" % (h.ev("__churnDraws"), h.ev("__churnMeasures")))


if __name__ == "__main__":
    harness = main()
    chart_regressions(harness)
    anim_files_tests()
    hit_window_tests(harness)
    if "--no-ui" not in sys.argv:
        ui_tests(harness)
        render_regressions(harness)
        feature_tests(harness)
        band_tests(harness)
        vocals_render_tests(harness)
        frame_rate_tests(harness)
        anim_sp_tests(harness)
    failed = [r for r in RESULTS if not r[1]]
    print("---")
    print("%d checks, %d failed" % (len(RESULTS), len(failed)))
    sys.exit(1 if failed else 0)
