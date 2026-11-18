#!/usr/bin/env python3
"""Synthesise the missed-note sounds.

    python tools/make_sfx.py      -> 42/media/sound/PE_miss1.ogg .. PE_miss5.ogg, 42/media/scripts/encore_sounds.txt

Needs ffmpeg on PATH (to encode) and nothing else.

These are the fumbled-string clunks a rhythm game plays when a note goes by. They are made here, from nothing, rather
than lifted from a game that already has them: the ones everybody knows are that game's own recordings and are not
this mod's to ship. What makes the sound is not hard to describe, though, so it is not hard to build:

    a string that is plucked while it is being damped -- a Karplus-Strong string with the loss turned right up, so it
    is a thud with a pitch rather than a note;
    a second string a semitone or a tritone off, because a wrong note is two notes that disagree;
    and the scrape of the pick, a few milliseconds of filtered noise at the front.

Five of them, at different pitches and lengths, picked at random in play: the same clunk twice running is the first
thing the ear notices.

To use your own instead, drop files of the same names over these. The sound script does not care what is in them.
"""
import math
import os
import random
import struct
import subprocess
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
SOUND = os.path.join(MOD, "42", "media", "sound")
SCRIPTS = os.path.join(MOD, "42", "media", "scripts")
RATE = 44100

# (base pitch in Hz, the clashing interval in semitones, seconds, how hard the string is damped)
VARIANTS = [
    (98.0, 1, 0.34, 0.972),
    (110.0, 6, 0.30, 0.968),
    (82.4, 1, 0.40, 0.976),
    (130.8, 6, 0.26, 0.962),
    (146.8, 2, 0.28, 0.966),
]


def string(freq, seconds, damping, rng, brightness=0.5):
    """Karplus-Strong: a burst of noise going round a delay line, losing a little each time."""
    n = int(seconds * RATE)
    period = max(2, int(RATE / freq))
    buf = [rng.uniform(-1.0, 1.0) for _ in range(period)]
    # soften the burst first, or the pluck is all click
    for _ in range(2):
        buf = [(buf[i] + buf[i - 1]) * 0.5 for i in range(period)]
    out = [0.0] * n
    for i in range(n):
        j = i % period
        nxt = (j + 1) % period
        v = buf[j]
        out[i] = v
        buf[j] = damping * (brightness * v + (1.0 - brightness) * buf[nxt])
    return out


def scrape(seconds, rng):
    n = int(seconds * RATE)
    out = []
    last = 0.0
    for i in range(n):
        t = i / float(n)
        white = rng.uniform(-1.0, 1.0)
        last = last * 0.55 + white * 0.45                 # take the top off it
        out.append(last * (1.0 - t) ** 2)
    return out


def clunk(index, base, interval, seconds, damping):
    rng = random.Random(1000 + index)
    n = int(seconds * RATE)
    a = string(base, seconds, damping, rng)
    b = string(base * (2.0 ** (interval / 12.0)), seconds, damping * 0.992, rng, brightness=0.42)
    s = scrape(0.022, rng)
    mix = [0.0] * n
    for i in range(n):
        t = i / float(RATE)
        # the hand coming down on the strings: a fast clamp on top of the string's own decay
        env = math.exp(-t * 9.0)
        mix[i] = (a[i] * 0.62 + b[i] * 0.50) * env
        if i < len(s):
            mix[i] += s[i] * 0.55
        if i < 96:                                          # no click at the very start
            mix[i] *= i / 96.0
    peak = max(abs(v) for v in mix) or 1.0
    frames = bytearray()
    for v in mix:
        x = math.tanh(v / peak * 1.5) / math.tanh(1.5) * 0.86
        frames += struct.pack("<h", int(max(-32767, min(32767, x * 32767))))
    return bytes(frames)


def main():
    os.makedirs(SOUND, exist_ok=True)
    os.makedirs(SCRIPTS, exist_ok=True)
    names = []
    for i, (base, interval, seconds, damping) in enumerate(VARIANTS, 1):
        name = "PE_miss%d" % i
        wav = os.path.join(HERE, name + ".wav")
        with wave.open(wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(RATE)
            wf.writeframes(clunk(i, base, interval, seconds, damping))
        ogg = os.path.join(SOUND, name + ".ogg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "libvorbis", "-q:a", "5", ogg], check=True)
        os.remove(wav)
        names.append(name)
        print("wrote", ogg)

    lines = [
        "/*",
        "    Project Encore's own sounds. Written by tools/make_sfx.py.",
        "",
        "    The missed-note clunks. Sound names are one engine-wide table with no module",
        "    namespacing, so every one carries the mod's prefix.",
        "",
        "    category = Music, the same as a song pack's audio, so the clunk sits on the same",
        "    volume slider as the song it is interrupting and the two stay in balance.",
        "*/",
        "",
        "module Base",
        "{",
    ]
    for i, name in enumerate(names, 1):
        lines += [
            "    sound PE_Miss%d" % i,
            "    {",
            "        category = Music,",
            "        loop = false,",
            "        clip",
            "        {",
            "            file = media/sound/%s.ogg," % name,
            "            volume = 1.0,",
            "        }",
            "    }",
            "",
        ]
    lines.append("}")
    path = os.path.join(SCRIPTS, "encore_sounds.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
