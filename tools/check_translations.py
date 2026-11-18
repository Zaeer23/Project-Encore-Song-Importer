#!/usr/bin/env python3
"""Check a B42 mod's Translate JSON files, strictly.

    python tools/check_translations.py [mod folder ...]    (default: this mod)

Two things, and the first is the one that matters.

DUPLICATE KEYS. B42 loads these files with org.json, which throws
JSONException on a duplicate key, and zombie.core.Translator turns that into
an unhandled RuntimeException in GameWindow.init -- the game dies before the
main menu with nothing on screen. One repeated key anywhere in a mod's
IG_UI.json is a hard crash for everyone who installs it.

A plain json.load will NOT find this: Python silently keeps the last value for
a repeated key, so the file looks fine and the game still will not start. That
is exactly how one got shipped here. object_pairs_hook is what catches it.

COVERAGE. Keys referenced from Lua but never defined (they render as the raw
key), and keys defined but never referenced (usually a rename left behind).
"""
import collections
import json
import os
import re
import sys

PLACEHOLDER = re.compile(r"%(\d+)")


def load_strict(path, problems):
    """Parse, rejecting duplicate keys the way the game does."""
    def hook(pairs):
        seen = {}
        for key, value in pairs:
            if key in seen:
                problems.append((path, "DUPLICATE KEY %r -- this is a hard crash "
                                       "on startup, not a warning" % key))
            seen[key] = value
        return seen
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        return json.loads(text, object_pairs_hook=hook)
    except ValueError as exc:
        problems.append((path, "not valid JSON: %s" % exc))
        return {}


def main():
    roots = sys.argv[1:] or [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    problems = []
    defined = {}

    for root in roots:
        for dirpath, _, files in os.walk(root):
            if os.path.sep + "Translate" + os.path.sep not in dirpath + os.path.sep:
                continue
            for name in files:
                if not name.endswith(".json"):
                    continue
                path = os.path.join(dirpath, name)
                table = load_strict(path, problems)
                for key, value in table.items():
                    if key in defined:
                        problems.append((path, "key %r is also defined in %s"
                                         % (key, defined[key][0])))
                    defined[key] = (path, value)
                print("  %-56s %d keys" % (os.path.relpath(path, root), len(table)))

    # Keys the Lua asks for.
    used = collections.defaultdict(list)
    for root in roots:
        for dirpath, _, files in os.walk(root):
            for name in files:
                if not name.endswith(".lua"):
                    continue
                path = os.path.join(dirpath, name)
                for n, line in enumerate(open(path, encoding="utf-8"), 1):
                    # A key quoted anywhere counts: these are passed to getText
                    # directly and also stored in registry fields.
                    for m in re.finditer(r'"((?:IGUI|ContextMenu|Tooltip|UI)_[A-Za-z0-9_]+)"', line):
                        used[m.group(1)].append("%s:%d" % (os.path.relpath(path, root), n))
                    # getText("Prefix_" .. something) -- can't be resolved here.
                    for m in re.finditer(r'"((?:IGUI|ContextMenu|Tooltip|UI)_[A-Za-z0-9_]*)"\s*\.\.', line):
                        used.setdefault(m.group(1) + "…", []).append(path)

    prefixes = [k[:-1] for k in used if k.endswith("…")]
    # A bare "IGUI_X_" that is also a concatenation stem is not a missing key:
    # it is the prefix half of getText("IGUI_X_" .. value).
    missing = sorted(k for k in used
                     if not k.endswith("…") and k not in defined
                     and k not in prefixes)
    unused = sorted(k for k in defined
                    if k not in used and not any(k.startswith(p) for p in prefixes))

    print()
    if missing:
        print("USED BUT NOT DEFINED (renders as the raw key):")
        for k in missing:
            print("  %-34s %s" % (k, used[k][0]))
    if unused:
        print("DEFINED BUT NEVER USED (%d): %s" % (len(unused), ", ".join(unused)))
    if prefixes:
        print("BUILT BY CONCATENATION, not checked: %s" % ", ".join(sorted(set(prefixes))))

    # Placeholder arity, as a nicety: %1 %2 must be contiguous from 1.
    for key, (path, value) in sorted(defined.items()):
        if not isinstance(value, str):
            continue
        nums = sorted(set(int(n) for n in PLACEHOLDER.findall(value)))
        if nums and nums != list(range(1, len(nums) + 1)):
            problems.append((path, "%r has non-contiguous placeholders %s" % (key, nums)))

    print()
    for path, note in problems:
        print("ERROR: %s: %s" % (os.path.basename(path), note))
    print("---")
    print("%d key(s) defined, %d error(s), %d missing" % (len(defined), len(problems), len(missing)))
    return 1 if (problems or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
