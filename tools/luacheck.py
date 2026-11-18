"""A small Lua 5.1 structure checker, for a machine with no Lua interpreter.

Tokenizes Lua and reports:
  - unbalanced block keywords (function/if/for/while/do vs end, repeat/until)
  - unbalanced ( ) [ ] { }
  - unterminated strings and long comments
  - constructs Lua 5.1 / Kahlua does not have: goto, ::label::, //, bitwise ops,
    and a warning for math.huge / os.* which PZ's sandbox does not expose.

Not a parser: it will not catch every error. It catches the ones that come from
writing a lot of Lua by hand.
"""
import re
import sys

KEYWORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NUMBER = re.compile(r"0[xX][0-9a-fA-F]+|\d+\.?\d*([eE][-+]?\d+)?|\.\d+([eE][-+]?\d+)?")

OPENERS = {"function", "if", "for", "while", "do"}
# `do` after for/while is the same block, so for/while push and their `do` must not.


def tokenize(src, path, problems):
    i = 0
    n = len(src)
    tokens = []  # (kind, text, line)
    line = 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        # long comment / long string
        if src.startswith("--", i):
            j = i + 2
            m = re.match(r"\[(=*)\[", src[j:])
            if m:
                level = m.group(1)
                close = "]" + level + "]"
                end = src.find(close, j + m.end())
                if end == -1:
                    problems.append((path, line, "ERROR", "unterminated long comment"))
                    return tokens
                line += src.count("\n", i, end)
                i = end + len(close)
                continue
            end = src.find("\n", j)
            if end == -1:
                break
            i = end
            continue
        m = re.match(r"\[(=*)\[", src[i:])
        if m:
            level = m.group(1)
            close = "]" + level + "]"
            end = src.find(close, i + m.end())
            if end == -1:
                problems.append((path, line, "ERROR", "unterminated long string"))
                return tokens
            line += src.count("\n", i, end)
            tokens.append(("string", "", line))
            i = end + len(close)
            continue
        if c in "\"'":
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == c:
                    break
                if src[j] == "\n":
                    problems.append((path, line, "ERROR", "unterminated string"))
                    break
                j += 1
            else:
                problems.append((path, line, "ERROR", "unterminated string"))
            tokens.append(("string", src[i:j + 1], line))
            i = j + 1
            continue
        m = KEYWORD.match(src, i)
        if m:
            tokens.append(("name", m.group(0), line))
            i = m.end()
            continue
        m = NUMBER.match(src, i)
        if m:
            tokens.append(("number", m.group(0), line))
            i = m.end()
            continue
        for op in ("...", "::", "//", "==", "~=", "<=", ">=", "..", "<<", ">>"):
            if src.startswith(op, i):
                tokens.append(("op", op, line))
                i += len(op)
                break
        else:
            tokens.append(("op", c, line))
            i += 1
    return tokens


def check(path):
    problems = []
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    tokens = tokenize(src, path, problems)

    stack = []
    brackets = []
    pending_do = 0  # for/while seen, expecting a `do` that does not open a block
    for kind, text, line in tokens:
        if kind == "op":
            if text in "([{":
                brackets.append((text, line))
            elif text in ")]}":
                want = {")": "(", "]": "[", "}": "{"}[text]
                if not brackets:
                    problems.append((path, line, "ERROR", "stray '%s'" % text))
                elif brackets[-1][0] != want:
                    problems.append((path, line, "ERROR",
                                     "'%s' closes '%s' opened on line %d"
                                     % (text, brackets[-1][0], brackets[-1][1])))
                    brackets.pop()
                else:
                    brackets.pop()
            elif text == "::":
                problems.append((path, line, "ERROR", "'::label::' is Lua 5.2+, not in Kahlua"))
            elif text == "//":
                problems.append((path, line, "ERROR", "'//' integer division is Lua 5.3+"))
            elif text in ("<<", ">>"):
                problems.append((path, line, "ERROR", "bitwise shift is Lua 5.3+"))
            continue
        if kind != "name":
            continue
        if text == "goto":
            problems.append((path, line, "ERROR", "'goto' is Lua 5.2+, not in Kahlua"))
        elif text in ("for", "while"):
            stack.append((text, line))
            pending_do += 1
        elif text == "do":
            if pending_do > 0:
                pending_do -= 1   # the `do` of a for/while already counted
            else:
                stack.append(("do", line))
        elif text == "function":
            stack.append(("function", line))
        elif text == "if":
            stack.append(("if", line))
        elif text == "repeat":
            stack.append(("repeat", line))
        elif text == "until":
            if stack and stack[-1][0] == "repeat":
                stack.pop()
            else:
                problems.append((path, line, "ERROR", "'until' with no 'repeat'"))
        elif text == "end":
            if not stack:
                problems.append((path, line, "ERROR", "'end' with nothing open"))
            elif stack[-1][0] == "repeat":
                problems.append((path, line, "ERROR",
                                 "'end' closing the 'repeat' on line %d" % stack[-1][1]))
                stack.pop()
            else:
                stack.pop()

    for name, line in brackets:
        problems.append((path, line, "ERROR", "'%s' is never closed" % name))
    for name, line in stack:
        problems.append((path, line, "ERROR", "'%s' on line %d is never closed" % (name, line)))

    # Sandbox warnings.
    for pattern, note in (
        (r"\bmath\.huge\b", "math.huge is not in PZ's Kahlua sandbox"),
        (r"\bos\.(time|clock|date)\b", "os.* is not in PZ's Kahlua sandbox"),
        (r"\btable\.unpack\b", "table.unpack is Lua 5.2+; use unpack"),
        (r"#!\s*/", "shebang in a Lua file"),
    ):
        for m in re.finditer(pattern, src):
            problems.append((path, src.count("\n", 0, m.start()) + 1, "WARN", note))

    return problems


def main():
    bad = 0
    for path in sys.argv[1:]:
        for p, line, level, note in check(path):
            print("%s:%d: %s: %s" % (p, line, level, note))
            if level == "ERROR":
                bad += 1
    print("---")
    print("%d file(s) checked, %d error(s)" % (len(sys.argv) - 1, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
