#!/usr/bin/env python3
"""Convert a Clone Hero notes.mid into the notes.chart Project Encore reads.

    python tools/midi2chart.py "path/to/notes.mid" [-o notes.chart]

Why this exists
---------------
Project Encore reads .chart and not .mid, and that is not a preference. Project
Zomboid's Lua sandbox opens a file through java.io.BufferedReader: readLine()
and close(), no byte access and no seek. A MIDI file is variable-length
quantities and delta times in binary. It cannot be read from in-game Lua at
all, by this mod or any other. So the conversion happens out here, once, on the
way into a pack.

Nothing is lost that Project Encore uses. .chart carries the tempo map, the time
signatures, sections, lyrics, every difficulty of every instrument, sustains
and star power, which is everything the mod plays.

What it reads
-------------
Standard MIDI format 0 and 1. Track names are the Rock Band / Clone Hero ones:

    PART GUITAR        -> [<Diff>Single]
    PART BASS          -> [<Diff>DoubleBass]
    PART RHYTHM        -> [<Diff>DoubleRhythm]
    PART GUITAR COOP   -> [<Diff>DoubleGuitar]
    PART KEYS          -> [<Diff>Keyboard]
    PART DRUMS         -> [<Diff>Drums]
    PART VOCALS        -> lyric and phrase events in [Events]
    EVENTS             -> section markers in [Events]

Note numbers, per difficulty base (Easy 60, Medium 72, Hard 84, Expert 96):

    base+0 .. base+4   the five frets
    base+5             force strum
    base+6             force HOPO
    104                tap
    103 / 116          star power (GH-era / Rock Band overdrive)

Drums take the same bases, with base+0 as the kick and base+1..+4 as the pads,
which is what .chart expects too.

The force flags are the one fiddly part. A .mid says "this note is a strum" or
"this note is a HOPO" outright; .chart's N 5 instead *flips* whatever the note
naturally is, where natural means "a single note, within a twelfth of a quarter
of the one before it, on a different fret". So the natural state is worked out
here and the flag is only written where the .mid disagrees with it. Getting
this wrong is how a converted chart ends up needing a strum on every note of a
HOPO run.
"""
import argparse
import os
import struct
import sys

# --------------------------------------------------------------------------
# Reading a standard MIDI file
# --------------------------------------------------------------------------


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def byte(self):
        b = self.data[self.pos]
        self.pos += 1
        return b

    def take(self, n):
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u16(self):
        return struct.unpack(">H", self.take(2))[0]

    def u32(self):
        return struct.unpack(">I", self.take(4))[0]

    def varlen(self):
        """A MIDI variable-length quantity: seven bits a byte, high bit means
        'another byte follows'."""
        value = 0
        while True:
            b = self.byte()
            value = (value << 7) | (b & 0x7F)
            if not (b & 0x80):
                return value


def parse_midi(path):
    """-> (division, [track]) where a track is a list of (tick, kind, *args)."""
    with open(path, "rb") as fh:
        data = fh.read()
    r = Reader(data)
    if r.take(4) != b"MThd":
        raise SystemExit("%s is not a MIDI file (no MThd header)" % path)
    header_len = r.u32()
    fmt = r.u16()
    ntracks = r.u16()
    division = r.u16()
    r.pos += header_len - 6
    if division & 0x8000:
        raise SystemExit("SMPTE time division is not supported; this needs a "
                         "ticks-per-quarter file, which is what every charting "
                         "tool writes")
    if fmt not in (0, 1):
        print("warning: MIDI format %d; treating it as format 1" % fmt)

    tracks = []
    for _ in range(ntracks):
        while r.pos < len(data) and r.take(4) != b"MTrk":
            # Skip any chunk that is not a track, as the spec requires.
            r.pos -= 4
            r.pos += 4 + struct.unpack(">I", data[r.pos + 4:r.pos + 8])[0]
        if r.pos >= len(data):
            break
        length = r.u32()
        end = r.pos + length
        tick = 0
        running = None
        events = []
        while r.pos < end:
            tick += r.varlen()
            status = r.byte()
            if status < 0x80:
                # Running status: the previous status byte applies and this
                # byte was already the first data byte.
                if running is None:
                    raise SystemExit("running status with no previous status")
                r.pos -= 1
                status = running
            if status < 0xF0:
                running = status
            kind = status & 0xF0

            if status == 0xFF:
                meta = r.byte()
                mlen = r.varlen()
                payload = r.take(mlen)
                if meta == 0x51 and mlen == 3:
                    micros = (payload[0] << 16) | (payload[1] << 8) | payload[2]
                    events.append((tick, "tempo", micros))
                elif meta == 0x58 and mlen >= 2:
                    events.append((tick, "timesig", payload[0], payload[1]))
                elif meta == 0x03:
                    events.append((tick, "name", payload.decode("latin-1")))
                elif meta in (0x01, 0x05):
                    # 0x01 text (section markers), 0x05 lyric.
                    events.append((tick, "text", payload.decode("latin-1")))
                elif meta == 0x2F:
                    events.append((tick, "end"))
            elif status in (0xF0, 0xF7):
                r.pos += r.varlen()
            elif kind in (0x80, 0x90):
                note = r.byte()
                vel = r.byte()
                if kind == 0x90 and vel > 0:
                    events.append((tick, "on", note))
                else:
                    events.append((tick, "off", note))
            elif kind in (0xA0, 0xB0, 0xE0):
                r.pos += 2
            elif kind in (0xC0, 0xD0):
                r.pos += 1
            else:
                raise SystemExit("unknown MIDI status 0x%02X at %d" % (status, r.pos))
        r.pos = end
        tracks.append(events)
    return division, tracks


# --------------------------------------------------------------------------
# Chart layout
# --------------------------------------------------------------------------

DIFFICULTIES = [("Easy", 60), ("Medium", 72), ("Hard", 84), ("Expert", 96)]

TRACK_NAMES = {
    "PART GUITAR": "Single",
    "PART GUITAR COOP": "DoubleGuitar",
    "PART BASS": "DoubleBass",
    "PART RHYTHM": "DoubleRhythm",
    "PART KEYS": "Keyboard",
    "PART DRUMS": "Drums",
    "T1 GEMS": "Single",            # the GH1/GH2 name
}

STAR_POWER_NOTES = (103, 116)
TAP_NOTE = 104


def track_name(events):
    for tick, kind, *args in events:
        if kind == "name":
            return args[0].strip().upper()
    return ""


def paired_notes(events):
    """-> [(note, start_tick, length_ticks)] from on/off pairs.

    A note-on for a pitch already sounding closes the previous one, which is
    what charting tools emit for a tremolo written as back-to-back notes.
    """
    open_notes = {}
    out = []
    for tick, kind, *args in events:
        if kind == "on":
            note = args[0]
            if note in open_notes:
                out.append((note, open_notes[note], tick - open_notes[note]))
            open_notes[note] = tick
        elif kind == "off":
            note = args[0]
            if note in open_notes:
                start = open_notes.pop(note)
                out.append((note, start, tick - start))
    for note, start in open_notes.items():
        out.append((note, start, 0))
    out.sort(key=lambda n: (n[1], n[0]))
    return out


def phrases(notes, wanted):
    """Star-power / overdrive phrases as (tick, length)."""
    return [(start, length) for note, start, length in notes if note in wanted]


def build_track(notes, base, is_drums, resolution):
    """One difficulty of one instrument, as .chart event lines."""
    hopo_threshold = resolution / 3.0

    # Collect the frets, then the markers, then decide the flags, because a
    # marker can sit before or after the notes it applies to.
    by_tick = {}
    forced_strum = set()
    forced_hopo = set()
    taps = set()

    for note, start, length in notes:
        if note == TAP_NOTE:
            taps.add(start)
            continue
        offset = note - base
        if offset == 5:
            forced_strum.add(start)
            continue
        if offset == 6:
            forced_hopo.add(start)
            continue
        if 0 <= offset <= 4:
            slot = by_tick.setdefault(start, {})
            slot[offset] = max(slot.get(offset, 0), length)

    ticks = sorted(by_tick)
    lines = []
    prev_tick = None
    prev_frets = None

    for tick in ticks:
        frets = by_tick[tick]
        keys = sorted(frets)

        natural_hopo = False
        if len(keys) == 1 and prev_tick is not None and (tick - prev_tick) <= hopo_threshold:
            if not (prev_frets is not None and len(prev_frets) == 1 and prev_frets[0] == keys[0]):
                natural_hopo = True

        if tick in taps:
            lines.append((tick, "  %d = N 6 0" % tick))
        else:
            wanted = natural_hopo
            if tick in forced_hopo:
                wanted = True
            if tick in forced_strum:
                wanted = False
            # .chart's N 5 flips the natural state rather than setting it, so
            # it is only written where the two disagree.
            if wanted != natural_hopo:
                lines.append((tick, "  %d = N 5 0" % tick))

        for fret in keys:
            length = frets[fret]
            # A drum chart's kick is fret 0 and its pads are 1-4 in both
            # formats, so no shift is needed here -- only the base differs.
            lines.append((tick, "  %d = N %d %d" % (tick, fret, length)))

        prev_tick, prev_frets = tick, keys

    lines.sort(key=lambda l: l[0])
    return [text for _, text in lines]


def section_lines(events):
    """Section markers and lyrics out of EVENTS and PART VOCALS."""
    out = []
    for tick, kind, *args in events:
        if kind != "text":
            continue
        text = args[0].strip()
        if text.startswith("[") and text.endswith("]"):
            inner = text[1:-1]
            if inner.startswith("section ") or inner.startswith("prc_"):
                name = inner[8:] if inner.startswith("section ") else inner[4:]
                out.append((tick, '  %d = E "section %s"' % (tick, name)))
            elif inner in ("end",):
                out.append((tick, '  %d = E "end"' % tick))
    return out


def vocal_lines(events):
    out = []
    for tick, kind, *args in events:
        if kind == "text":
            text = args[0].strip()
            if text.startswith("[") or text == "":
                continue
            out.append((tick, '  %d = E "lyric %s"' % (tick, text)))
    # Phrase markers are notes 105 and 106 in PART VOCALS.
    for note, start, length in paired_notes(events):
        if note in (105, 106):
            out.append((start, '  %d = E "phrase_start"' % start))
            out.append((start + length, '  %d = E "phrase_end"' % (start + length)))
    return out


def main():
    ap = argparse.ArgumentParser(description="Convert notes.mid to notes.chart")
    ap.add_argument("midi")
    ap.add_argument("-o", "--out", help="output path (default: notes.chart beside the input)")
    ap.add_argument("--name", default="")
    ap.add_argument("--artist", default="")
    ap.add_argument("--charter", default="")
    ap.add_argument("--offset", type=float, default=0.0,
                    help="seconds the chart's tick 0 sits into the audio")
    args = ap.parse_args()

    division, tracks = parse_midi(args.midi)
    out_path = args.out or os.path.join(os.path.dirname(os.path.abspath(args.midi)), "notes.chart")

    # The tempo map and time signatures live on the first track of a format 1
    # file, but a tempo change anywhere is still a tempo change, so every track
    # is scanned.
    tempos = []
    timesigs = []
    for events in tracks:
        for tick, kind, *rest in events:
            if kind == "tempo":
                tempos.append((tick, 60000000.0 / rest[0]))
            elif kind == "timesig":
                numerator, denom_pow = rest[0], rest[1]
                timesigs.append((tick, numerator, denom_pow))
    tempos.sort()
    timesigs.sort()
    if not tempos or tempos[0][0] != 0:
        tempos.insert(0, (0, 120.0))
    if not timesigs or timesigs[0][0] != 0:
        timesigs.insert(0, (0, 4, 2))

    lines = [
        "[Song]",
        "{",
        '  Name = "%s"' % (args.name or os.path.basename(os.path.dirname(os.path.abspath(args.midi)))),
        '  Artist = "%s"' % args.artist,
        '  Charter = "%s"' % args.charter,
        "  Offset = %g" % args.offset,
        "  Resolution = %d" % division,
        "}",
        "[SyncTrack]",
        "{",
    ]
    sync = []
    for tick, bpm in tempos:
        sync.append((tick, "  %d = B %d" % (tick, int(round(bpm * 1000)))))
    for tick, numerator, denom_pow in timesigs:
        if denom_pow == 2:
            sync.append((tick, "  %d = TS %d" % (tick, numerator)))
        else:
            sync.append((tick, "  %d = TS %d %d" % (tick, numerator, denom_pow)))
    sync.sort(key=lambda s: s[0])
    lines += [text for _, text in sync]
    lines.append("}")

    # Events: sections from EVENTS, lyrics from PART VOCALS.
    events_out = []
    for events in tracks:
        name = track_name(events)
        if name == "EVENTS":
            events_out += section_lines(events)
        elif name == "PART VOCALS":
            events_out += vocal_lines(events)
    events_out.sort(key=lambda e: e[0])
    lines.append("[Events]")
    lines.append("{")
    lines += [text for _, text in events_out]
    lines.append("}")

    written = 0
    for events in tracks:
        name = track_name(events)
        chart_track = TRACK_NAMES.get(name)
        if not chart_track:
            continue
        notes = paired_notes(events)
        star_power = phrases(notes, STAR_POWER_NOTES)

        for diff_name, base in DIFFICULTIES:
            body = build_track(notes, base, chart_track == "Drums", division)
            if not body:
                continue
            section = []
            for tick, length in star_power:
                section.append((tick, "  %d = S 2 %d" % (tick, length)))
            merged = [(int(line.strip().split()[0]), line) for line in body] + section
            merged.sort(key=lambda m: m[0])
            lines.append("[%s%s]" % (diff_name, chart_track))
            lines.append("{")
            lines += [text for _, text in merged]
            lines.append("}")
            written += 1
            print("  %s%s: %d lines" % (diff_name, chart_track, len(body)))

    if written == 0:
        print("No instrument tracks were found. Track names seen:")
        for events in tracks:
            print("  %r" % track_name(events))
        return 1

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print("wrote %s (%d sections, resolution %d)" % (out_path, written, division))
    print("Remember to measure the audio's length for lengthMs:")
    print("  ffprobe -v error -show_entries format=duration -of csv=p=0 song.ogg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
