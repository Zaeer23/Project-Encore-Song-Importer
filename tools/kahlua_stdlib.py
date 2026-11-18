#!/usr/bin/env python3
"""Load the game's own Lua standard library into the test harness.

    python tools/kahlua_stdlib.py            say what the game's stdlib defines, and time its table.sort

Kahlua, the Lua Project Zomboid runs, is not the C Lua the harness runs. Most of its library is Java, but part of it
is written in Lua and shipped compiled, as `stdlib.lbc` in the game folder: `table.sort`, `ipairs`, `string.gmatch`,
`string.rep`, `math.max`/`min`, `coroutine.wrap`. Those behave differently from the C versions in ways a test passing
on C Lua will not show. The one that has cost something: Kahlua's `table.sort` is a quicksort that always takes the
leftmost element as its pivot, so a list that is already sorted -- every note list this mod builds -- is its worst
case. A 2,474-note part took 3,059,101 comparisons.

`stdlib.lbc` is Lua 5.1 bytecode written big-endian with 4-byte size_t, which the harness's Lua (little-endian,
8-byte size_t) will not load as it is. This re-writes the same chunk in the local layout; no instruction is changed.
"""
import os
import struct
import sys

GAME_DIRS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\ProjectZomboid",
    r"C:\Program Files\Steam\steamapps\common\ProjectZomboid",
    os.path.expanduser("~/.steam/steam/steamapps/common/ProjectZomboid"),
]


def find_stdlib():
    for d in [os.environ.get("ENCORE_GAME_DIR")] + GAME_DIRS:
        if d and os.path.isfile(os.path.join(d, "stdlib.lbc")):
            return os.path.join(d, "stdlib.lbc")
    return None


class _Reader:
    def __init__(self, data, big, size_t):
        self.d, self.p, self.e, self.st = data, 12, ">" if big else "<", size_t

    def take(self, n):
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def byte(self):
        return self.take(1)[0]

    def int(self):
        return struct.unpack(self.e + "i", self.take(4))[0]

    def size(self):
        return struct.unpack(self.e + ("I" if self.st == 4 else "Q"), self.take(self.st))[0]

    def string(self):
        n = self.size()
        return None if n == 0 else self.take(n)[:-1]


def _function(r):
    f = {"source": r.string(), "line": r.int(), "last": r.int(),
         "head": bytes([r.byte(), r.byte(), r.byte(), r.byte()])}
    f["code"] = [struct.unpack(r.e + "I", r.take(4))[0] for _ in range(r.int())]
    consts = []
    for _ in range(r.int()):
        t = r.byte()
        if t == 0:
            consts.append((0, None))
        elif t == 1:
            consts.append((1, r.byte()))
        elif t == 3:
            consts.append((3, struct.unpack(r.e + "d", r.take(8))[0]))
        elif t == 4:
            consts.append((4, r.string()))
        else:
            raise ValueError("constant type %d" % t)
    f["consts"] = consts
    f["protos"] = [_function(r) for _ in range(r.int())]
    f["lines"] = [r.int() for _ in range(r.int())]
    f["locals"] = [(r.string(), r.int(), r.int()) for _ in range(r.int())]
    f["upvalues"] = [r.string() for _ in range(r.int())]
    return f


def _put_string(out, s):
    if s is None:
        out += struct.pack("<Q", 0)
    else:
        out += struct.pack("<Q", len(s) + 1) + s + b"\0"


def _emit(out, f):
    _put_string(out, f["source"])
    out += struct.pack("<ii", f["line"], f["last"]) + f["head"]
    out += struct.pack("<i", len(f["code"])) + b"".join(struct.pack("<I", c) for c in f["code"])
    out += struct.pack("<i", len(f["consts"]))
    for t, v in f["consts"]:
        out += bytes([t])
        if t == 1:
            out += bytes([v])
        elif t == 3:
            out += struct.pack("<d", v)
        elif t == 4:
            _put_string(out, v)
    out += struct.pack("<i", len(f["protos"]))
    for p in f["protos"]:
        _emit(out, p)
    out += struct.pack("<i", len(f["lines"])) + b"".join(struct.pack("<i", n) for n in f["lines"])
    out += struct.pack("<i", len(f["locals"]))
    for name, a, b in f["locals"]:
        _put_string(out, name)
        out += struct.pack("<ii", a, b)
    out += struct.pack("<i", len(f["upvalues"]))
    for u in f["upvalues"]:
        _put_string(out, u)


def native_chunk(path):
    """The chunk at `path`, re-written for a little-endian Lua 5.1 with 8-byte size_t."""
    data = open(path, "rb").read()
    if data[:5] != b"\x1bLuaQ":
        raise ValueError("%s is not Lua 5.1 bytecode" % path)
    top = _function(_Reader(data, data[6] == 0, data[8]))
    out = bytearray(b"\x1bLuaQ\x00\x01\x04\x08\x04\x08\x00")
    _emit(out, top)
    return bytes(out)


# Runs the chunk with only what it reads in reach, and hands back the functions it defines; nothing it does touches
# the harness's own globals.
LOADER = r'''
function(blob)
    local f, err = loadstring(blob, "=stdlib.lbc")
    if not f then error(err, 0) end
    local env = {
        table = { pairs = pairs, concat = table.concat },
        string = {}, math = {},
        coroutine = { create = coroutine.create, resume = coroutine.resume },
        error = error, select = select, unpack = unpack,
    }
    setfenv(f, env)
    f()
    return env
end
'''


def install(runtime, counter="__kahluaSortCalls"):
    """Put the game's table.sort into a lupa runtime, counting comparisons in the global `counter`.
    Returns the stdlib path, or None when the game is not installed here (the harness then keeps C Lua's sort)."""
    path = find_stdlib()
    if not path:
        return None
    env = runtime.eval(LOADER)(native_chunk(path))
    g = runtime.globals()
    g["__kahluaSort"] = env.table.sort
    runtime.execute(r'''
        %s = 0
        local ksort = __kahluaSort
        local function lt(a, b) return a < b end
        table.sort = function(t, comp)
            comp = comp or lt
            return ksort(t, function(a, b)
                %s = %s + 1
                return comp(a, b)
            end)
        end
    ''' % (counter, counter, counter))
    return path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for extra in (os.environ.get("ENCORE_PYLIB"),):
        if extra and os.path.isdir(extra):
            sys.path.insert(0, extra)
    from lupa import lua51
    rt = lua51.LuaRuntime()
    where = install(rt)
    if not where:
        sys.exit("stdlib.lbc not found; set ENCORE_GAME_DIR to the game folder")
    print("loaded", where)
    print(rt.execute(r'''
        local t = {}
        for i = 1, 2474 do t[i] = { ms = i } end
        table.sort(t, function(a, b) return a.ms < b.ms end)
        return "sorting 2,474 notes already in order: " .. __kahluaSortCalls .. " comparisons"
    '''))
