import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
MODS = os.path.dirname(MOD)
ZOMBOID = os.path.dirname(MODS)
ITEM = os.path.join(ZOMBOID, "Workshop", "ProjectEncore")
PARTS = [("ProjectEncore", MOD), ("EncoreDemoPack", os.path.join(MODS, "EncoreDemoPack"))]

TITLE = "Project Encore (Build 42)"
TAGS = "Build 42;Audio;Framework;Interface;Multiplayer;Silly/Fun"
DESCRIPTION = [
    "Guitar Hero in Project Zomboid. Grab a guitar, pick a song and play it on a note highway while your guy rocks out behind it.",
    "",
    "[h1]What's in it[/h1]",
    "[list]",
    "[*]Guitar, bass, rhythm, keys and vocals (yes you get a mic)",
    "[*]Easy to Expert on every song, even charts that only came with Expert",
    "[*]Tap mode by default, strum mode with strum up and down if you want the real thing",
    "[*]Star power, rock meter, streaks, full combos. Get 2 stars or less and it tells you YOU SUCK!",
    "[*]Songs mess with your mood. Play well and you're happier, flop and you're stressed",
    "[*]High scores per character",
    "[*]Band mode in multiplayer, everyone plays their own part",
    "[*]Sync check in the options so the notes actually line up with your speakers",
    "[/list]",
    "",
    "[h1]Songs[/h1]",
    "Comes with one demo song so you can try it straight away. Song packs from the workshop show up in the setlist on their own.",
    "",
    "Right click a guitar in your inventory and hit Play music to start.",
    "",
    "Bugs go in the Bug Reports discussion. Your console.txt helps a lot.",
]


def strip_lua(src):
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == "-" and src.startswith("--", i):
            m = re.match(r"\[(=*)\[", src[i + 2:i + 64])
            if m:
                close = "]" + m.group(1) + "]"
                k = src.find(close, i + 2 + len(m.group(0)))
                i = n if k < 0 else k + len(close)
                out.append(" ")
            else:
                k = src.find("\n", i)
                i = n if k < 0 else k
            continue
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(src[i:j])
            i = j
            continue
        if c == "[":
            m = re.match(r"\[(=*)\[", src[i:i + 64])
            if m:
                close = "]" + m.group(1) + "]"
                k = src.find(close, i + len(m.group(0)))
                k = n if k < 0 else k + len(close)
                out.append(src[i:k])
                i = k
                continue
        out.append(c)
        i += 1
    return tidy("".join(out))


def tidy(text):
    lines, blank = [], 0
    for line in text.split("\n"):
        line = line.rstrip()
        if not line:
            blank += 1
            if blank > 1 or not lines:
                continue
        else:
            blank = 0
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def strip_xml(src):
    return tidy(re.sub(r"<!--.*?-->", "", src, flags=re.S))


def strip_script(src):
    return tidy(re.sub(r"/\*.*?\*/", "", src, flags=re.S))


STRIP = {".lua": strip_lua, ".xml": strip_xml, ".txt": strip_script}


def copy_part(src_root, dst_root):
    for root, dirs, files in os.walk(src_root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel = os.path.relpath(root, src_root)
        out_dir = os.path.join(dst_root, rel)
        os.makedirs(out_dir, exist_ok=True)
        for f in files:
            if f.startswith("."):
                continue
            src = os.path.join(root, f)
            dst = os.path.join(out_dir, f)
            fn = STRIP.get(os.path.splitext(f)[1].lower())
            if fn:
                with open(src, encoding="utf-8") as fh:
                    text = fn(fh.read())
                with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
            else:
                shutil.copy2(src, dst)


def keep(field, default):
    path = os.path.join(ITEM, "workshop.txt")
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8", errors="replace").read().splitlines():
            if line.startswith(field + "="):
                return line[len(field) + 1:]
    return default


def write_workshop_txt():
    item_id = keep("id", "")
    lines = ["version=1"]
    if item_id:
        lines.append("id=" + item_id)
    lines.append("title=" + keep("title", TITLE))
    lines += ["description=" + d for d in DESCRIPTION]
    lines.append("tags=" + keep("tags", TAGS))
    lines.append("visibility=" + keep("visibility", "public"))
    with open(os.path.join(ITEM, "workshop.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def check():
    problems = []
    contents = os.path.join(ITEM, "Contents")
    for root, dirs, files in os.walk(contents):
        for name in dirs + files:
            low = name.lower()
            if name.startswith(".") or low.startswith("readme") or low.endswith((".py", ".pyw", ".md", ".pyc")):
                problems.append(os.path.relpath(os.path.join(root, name), ITEM))
        for f in files:
            path = os.path.join(root, f)
            ext = os.path.splitext(f)[1].lower()
            if ext not in STRIP:
                continue
            text = open(path, encoding="utf-8").read()
            if STRIP[ext](text) != text or (ext == ".lua" and "--" in strip_strings(text)):
                problems.append("comment left in " + os.path.relpath(path, ITEM))
    for name in ("workshop.txt", "preview.png"):
        if not os.path.isfile(os.path.join(ITEM, name)):
            problems.append("missing " + name)
    return problems


def strip_strings(src):
    return re.sub(r"\[(=*)\[.*?\]\1\]|\"(\\.|[^\"\\\n])*\"|'(\\.|[^'\\\n])*'", "", src, flags=re.S)


def main():
    contents = os.path.join(ITEM, "Contents", "mods")
    if os.path.isdir(os.path.join(ITEM, "Contents")):
        shutil.rmtree(os.path.join(ITEM, "Contents"))
    os.makedirs(contents, exist_ok=True)
    for mod_id, root in PARTS:
        copy_part(os.path.join(root, "42"), os.path.join(contents, mod_id, "42"))
    shutil.copyfile(os.path.join(HERE, "art", "workshop_preview.png"), os.path.join(ITEM, "preview.png"))
    write_workshop_txt()
    problems = check()
    for p in problems:
        print("problem:", p)
    print("synced to", ITEM, "-", "ready" if not problems else "%d problem(s)" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
