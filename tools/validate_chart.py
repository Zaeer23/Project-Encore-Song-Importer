"""Check that every line of a .chart matches one of the patterns the Lua
parser in Encore_ChartParser.lua actually uses. A line the Lua would
silently skip is reported here instead."""
import re, sys

HEADER   = re.compile(r"^\s*\[(.*?)\]\s*$")        # Lua: ^%s*%[(.-)%]%s*$
SONG_KV  = re.compile(r"^\s*([0-9A-Za-z_]+)\s*=\s*(.*?)\s*$")  # ^%s*([%w_]+)%s*=%s*(.-)%s*$
EVENT    = re.compile(r"^\s*(\d+)\s*=\s*(.+)$")    # ^%s*(%d+)%s*=%s*(.+)$
KIND     = re.compile(r"^([A-Za-z]+)\s*(.*)$")     # ^(%a+)%s*(.*)$
NUMS     = re.compile(r"-?\d+")                    # %-?%d+

DIFFS = ("Expert", "Hard", "Medium", "Easy")

bad = 0
for path in sys.argv[1:]:
    section = None
    stats = {}
    for n, raw in enumerate(open(path, encoding="utf-8"), 1):
        line = raw.rstrip("\n")
        if HEADER.match(line):
            section = HEADER.match(line).group(1)
            stats.setdefault(section, 0)
            continue
        if line.strip() in ("{", "}", ""):
            continue
        if section == "Song":
            if not SONG_KV.match(line):
                print("%s:%d: [Song] line the Lua would skip: %r" % (path, n, line)); bad += 1
            continue
        m = EVENT.match(line)
        if not m:
            print("%s:%d: not a 'tick = ...' line: %r" % (path, n, line)); bad += 1
            continue
        k = KIND.match(m.group(2))
        if not k:
            print("%s:%d: event with no kind: %r" % (path, n, line)); bad += 1
            continue
        kind, args = k.group(1).upper(), k.group(2)
        nums = [int(x) for x in NUMS.findall(args)]
        if section == "SyncTrack":
            if kind not in ("B", "TS") or not nums:
                print("%s:%d: SyncTrack line the Lua would skip: %r" % (path, n, line)); bad += 1
        elif section == "Events":
            if kind != "E":
                print("%s:%d: Events line the Lua would skip: %r" % (path, n, line)); bad += 1
        elif section and section.startswith(DIFFS):
            if kind == "N":
                if not nums:
                    print("%s:%d: N with no fret: %r" % (path, n, line)); bad += 1
                elif nums[0] > 8 or nums[0] < 0:
                    print("%s:%d: fret %d is outside 0-8: %r" % (path, n, nums[0], line)); bad += 1
                else:
                    stats[section] += 1
            elif kind != "S":
                print("%s:%d: track line the Lua would skip: %r" % (path, n, line)); bad += 1
        else:
            print("%s:%d: line in unknown section %r: %r" % (path, n, section, line)); bad += 1
    print("%s: %s" % (path, ", ".join("%s=%d" % (k, v) for k, v in stats.items() if v)))
print("---")
print("%d problem line(s)" % bad)
sys.exit(1 if bad else 0)
