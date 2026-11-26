import argparse
import os
import struct
import sys


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
        value = 0
        while True:
            b = self.byte()
            value = (value << 7) | (b & 0x7F)
            if not (b & 0x80):
                return value


def parse_midi(path):
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


DIFFICULTIES = [("Easy", 60), ("Medium", 72), ("Hard", 84), ("Expert", 96)]

TRACK_NAMES = {
    "PART GUITAR": "Single",
    "PART GUITAR COOP": "DoubleGuitar",
    "PART BASS": "DoubleBass",
    "PART RHYTHM": "DoubleRhythm",
    "PART KEYS": "Keyboard",
    "PART DRUMS": "Drums",
    "T1 GEMS": "Single",
}

STAR_POWER_NOTES = (103, 116)
TAP_NOTE = 104


def track_name(events):
    for tick, kind, *args in events:
        if kind == "name":
            return args[0].strip().upper()
    return ""


def paired_notes(events):
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
    return [(start, length) for note, start, length in notes if note in wanted]


def build_track(notes, base, is_drums, resolution):
    hopo_threshold = resolution / 3.0

    by_tick = {}
    forced_strum = set()
    forced_hopo = set()
    taps = set()

    for note, start, length in notes:
        if note == TAP_NOTE:
            taps.add(start)
            continue
        offset = note - base
        # MATH STUFF FOR .MIDI AHHHHH
        if offset == 5:
            forced_hopo.add(start)
            continue
        if offset == 6:
            forced_strum.add(start)
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
            if wanted != natural_hopo:
                lines.append((tick, "  %d = N 5 0" % tick))

        for fret in keys:
            length = frets[fret]
            lines.append((tick, "  %d = N %d %d" % (tick, fret, length)))

        prev_tick, prev_frets = tick, keys

    lines.sort(key=lambda l: l[0])
    return [text for _, text in lines]


def section_lines(events):
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
