#!/usr/bin/env python3
"""Import Clone Hero songs into Project Encore.

    python tools/import_clonehero.py "D:\\Downloads\\Artist - Title.sng"           a .sng file (or several)
    python tools/import_clonehero.py "D:\\Clone Hero\\Songs\\Artist - Title"      a song folder (or several)
    python tools/import_clonehero.py --all "D:\\Clone Hero\\Songs"                 every song under it, either kind
    python tools/import_clonehero.py --list                                       what has been imported
    python tools/import_clonehero.py --remove <id>                                take one out again

    python tools/import_clonehero.py --pack "Rock Pack" song.sng ...              into a song pack for the Workshop
    python tools/import_clonehero.py --packs                                      the packs there are
    python tools/import_clonehero.py --pack "Rock Pack" --prepare-workshop        ready it for upload

Needs ffmpeg and ffprobe on PATH. The pack is switched on for new games and for every save that already plays
Project Encore (see enable_pack). Restart the game afterwards: sound scripts are read at startup, so a song imported
while the game is running is not there until then.

encore_importer.pyw, beside this file, is the same thing with a window and a file picker.

A .sng is Clone Hero's one-file song package (the format at github.com/mdsitton/SngFileFormat): the song folder's
files and its song.ini, in one file, each file XOR-masked. It is unpacked into a temporary folder and imported from
there exactly as a folder would be -- see read_sng.

What a Clone Hero song is, and what each part of it becomes:

    notes.chart / notes.mid   the chart. A .chart is copied as it is. A .mid is converted with midi2chart.py,
                              because the game's Lua can only read a file a line at a time and MIDI is binary.
    song.ini                  the title, artist, album, year, charter, genre and delay. Read for the setlist.
    song.ogg, guitar.ogg,     the audio, as stems: Clone Hero plays them all at once. Project Encore plays one sound
    bass.ogg, drums_1.ogg ... per song (a sound script names one file), so the stems are mixed down into one .ogg --
                              summed, not averaged, which is what playing them together does, with a limiter on the
                              end so a loud chorus does not clip. crowd.ogg is left out; .opus, .mp3 and .wav stems
                              are taken as well as .ogg.

Songs go into a pack. Unless one is named they go into "My Songs", Zomboid/mods/EncoreSongs, which is only ever on
this computer. A named pack is a Workshop item -- see Pack and create_pack -- that is playable here at once and can
be uploaded from the game's own Workshop screen. Every pack is a mod the importer owns outright, rewritten from its
songs.json on every run:

    songs.json                                       what is in the pack. The one file to trust.
    <mod>/42/mod.info                                require=\\ProjectEncore
    <media>/sound/<prefix><id>.ogg                   the mixed audio
    <media>/encore/<pack>/<id>/notes.chart         the chart
    <media>/scripts/<pack>_sounds.txt                a sound script per song
    <media>/lua/shared/<pack>.lua                    the registrations

Every one of those names carries the pack's own id or prefix. Two mods that ship a file at the same path do not both
load -- the later one replaces the earlier (console.txt says "mod X overrides media/...") -- so two packs that both
called their script encoresongs_sounds.txt, or both held a chart for the same song, would quietly break each other.

The length that goes into the registration is measured from the mixed file with ffprobe, not taken from song.ini:
the game ends a song on that number, and an ini's song_length is whatever the charter typed.
"""
import argparse
import configparser
import json
import os
import re
import glob
import shutil
import struct
import subprocess
import sys
import tempfile
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
MODS = os.path.dirname(MOD)

PACK_ID = "EncoreSongs"
PACK_NAME = "My Songs"
SOUND_PREFIX = "ENCS_"
PZ_VERSION = "42.22.2"
# B42's form of a dependency: the mod id with a backslash in front, as the 42.13-42.19 mods on this machine write it.
REQUIRE = "\\ProjectEncore"
# The Workshop tags a pack is filed under, from the game's media/WorkshopTags.txt.
WORKSHOP_TAGS = "Build 42;Audio"

AUDIO_EXT = (".ogg", ".opus", ".mp3", ".wav")
# The stems Clone Hero mixes. Everything that is music; the crowd track and the preview clip are not.
STEMS = ("song", "backing", "guitar", "bass", "rhythm", "keys", "vocals", "vocals_1", "vocals_2",
         "drums", "drums_1", "drums_2", "drums_3", "drums_4")

# Run from the window app (pythonw, no console), every ffmpeg call would otherwise flash up a console window of its own.
_NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}


def _python():
    """A console Python for the MIDI converter: under the window app sys.executable is pythonw.exe."""
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    return exe


# ---------------------------------------------------------------------------------------------------------------------- reading a song folder
def read_ini(folder):
    """song.ini as a dict of lower-case keys. Tolerant: these files are hand-written, in every encoding there is."""
    path = None
    for name in os.listdir(folder):
        if name.lower() == "song.ini":
            path = os.path.join(folder, name)
    if not path:
        return {}
    raw = open(path, "rb").read()
    text = None
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeError:
            continue
    out = {}
    parser = configparser.RawConfigParser(strict=False, interpolation=None, delimiters=("=",))
    try:
        parser.read_string(text)
        for section in parser.sections():
            for key, value in parser.items(section):
                out[key.strip().lower()] = value.strip()
    except configparser.Error:
        # No [song] header, or a line that is not key = value: take what can be taken.
        for line in text.splitlines():
            if "=" in line and not line.lstrip().startswith(("[", ";", "#")):
                key, value = line.split("=", 1)
                out[key.strip().lower()] = value.strip()
    return out


def find_chart(folder):
    """(path, kind) of the chart: a .chart if there is one, otherwise a .mid."""
    names = {n.lower(): n for n in os.listdir(folder)}
    for want in ("notes.chart",):
        if want in names:
            return os.path.join(folder, names[want]), "chart"
    for want in ("notes.mid", "notes.midi"):
        if want in names:
            return os.path.join(folder, names[want]), "mid"
    # Some songs name the file after themselves.
    for low, name in sorted(names.items()):
        if low.endswith(".chart"):
            return os.path.join(folder, name), "chart"
    for low, name in sorted(names.items()):
        if low.endswith((".mid", ".midi")):
            return os.path.join(folder, name), "mid"
    return None, None


def find_stems(folder):
    found = []
    for name in sorted(os.listdir(folder)):
        base, ext = os.path.splitext(name)
        if ext.lower() in AUDIO_EXT and base.lower() in STEMS:
            found.append(os.path.join(folder, name))
    return found


def is_song_folder(folder):
    return os.path.isdir(folder) and find_chart(folder)[0] is not None and len(find_stems(folder)) > 0


def slug(text):
    """An id safe to be a folder name, a sound name and a Lua table key."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:60] or "song"


# ---------------------------------------------------------------------------------------------------------------------- audio
def channels(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
                          "-of", "csv=p=0", path], capture_output=True, text=True, **_NO_WINDOW).stdout.strip()
    try:
        return int(out.split(",")[0])
    except ValueError:
        return 2


def mix(stems, out_path):
    """All the stems, played together, as one stereo .ogg, at the level they have when played together.

    Three things would each quietly change that level, and each is switched off:
      amix divides by the number of inputs unless told normalize=0, and a five-stem song comes out at a fifth;
      turning a mono stem into stereo the default way takes 3 dB off it, where a player puts it on both speakers
      at full level, so mono stems are copied to both channels by hand;
      and the limiter raises the whole mix to full scale unless told level=0. It is there for the peaks only:
      stems that sum past full scale would otherwise clip.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    parts, labels = [], []
    for i, stem in enumerate(stems):
        cmd += ["-i", stem]
        if channels(stem) == 1:
            parts.append("[%d:a]pan=stereo|c0=c0|c1=c0[s%d]" % (i, i))
        else:
            parts.append("[%d:a]aformat=channel_layouts=stereo[s%d]" % (i, i))
        labels.append("[s%d]" % i)
    if len(stems) == 1:
        graph = parts[0] + ";[s0]alimiter=limit=0.95:level=0[out]"
    else:
        graph = ";".join(parts) + ";" + "".join(labels) + \
            "amix=inputs=%d:normalize=0:duration=longest,alimiter=limit=0.95:level=0[out]" % len(stems)
    cmd += ["-filter_complex", graph, "-map", "[out]", "-ar", "44100", "-c:a", "libvorbis", "-q:a", "5", out_path]
    subprocess.run(cmd, check=True, capture_output=True, **_NO_WINDOW)


def need_tools():
    """ffmpeg and ffprobe convert a song's audio; say so plainly when they are not there, rather than failing
    with a "file not found" from deep inside the conversion."""
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise RuntimeError("Converting a song's audio needs ffmpeg, which is not installed (or not on the PATH). "
                           "Install it by running:\n\n    winget install ffmpeg\n\nthen close and reopen the importer.")


def png_size(path):
    """(width, height) of a PNG, read from its header: no image library needed. None if it is not a PNG."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def duration_ms(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         check=True, capture_output=True, text=True, **_NO_WINDOW).stdout.strip()
    return int(round(float(out) * 1000))


# ---------------------------------------------------------------------------------------------------------------------- the chart
def chart_tracks(path):
    """Which parts a .chart holds: {track: [difficulties]}, for the report."""
    out = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r"\s*\[(Expert|Hard|Medium|Easy)(\w+)\]\s*$", line)
            if m:
                out.setdefault(m.group(2), []).append(m.group(1))
    return out


TRACK_NAMES = {"Single": "guitar", "DoubleBass": "bass", "DoubleRhythm": "rhythm", "DoubleGuitar": "co-op guitar",
               "Drums": "drums", "Keyboard": "keys", "GHLGuitar": "6-fret guitar", "GHLBass": "6-fret bass"}


def install_chart(src, kind, dest, title, artist):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if kind == "chart":
        # Re-written as UTF-8 without a byte-order mark: the game reads the file as lines of text, and a mark on
        # the front of "[Song]" is a first line that matches nothing.
        raw = open(src, "rb").read()
        text = None
        for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeError:
                continue
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text.replace("\r\n", "\n").replace("\r", "\n"))
        return
    # -I: the converter reads a downloaded file, and has no business picking modules up from beside it.
    result = subprocess.run([_python(), "-I", os.path.join(HERE, "midi2chart.py"), src, "-o", dest,
                             "--name", title, "--artist", artist], capture_output=True, text=True, **_NO_WINDOW)
    if result.returncode != 0 or not os.path.isfile(dest):
        raise RuntimeError("could not convert the MIDI:\n" + (result.stdout + result.stderr).strip())


# ---------------------------------------------------------------------------------------------------------------------- .sng packages
SNG_MAGIC = b"SNGPKG"


class SngPackage:
    """A parsed .sng: its metadata (the song.ini, as a dict) and an index of the files in it, still masked.

    The layout, all little-endian (from the format's README):

        header      "SNGPKG", uint32 version, 16-byte xorMask
        metadata    uint64 bytes-after-this-field, uint64 count, then count x (int32 len, utf-8 key, int32 len, value)
        file index  uint64 bytes-after-this-field, uint64 count, then count x
                    (uint8 name length, utf-8 name, uint64 contents length, uint64 contents offset)
        file data   uint64 length, then the files, each masked

    The contents offset is "from the start of the file": the .sng file, which is how the real ones read. A file
    whose offset only makes sense counted from the start of the data section is read that way instead, so a
    package from a tool that reads the spec the other way still opens.
    """

    def __init__(self, path):
        with open(path, "rb") as fh:
            data = fh.read()
        self.data = data
        size = len(data)

        def need(off, n, what):
            if off < 0 or n < 0 or off + n > size:
                raise RuntimeError("the .sng file is cut short or damaged (%s)" % what)

        if data[:6] != SNG_MAGIC:
            raise RuntimeError("not a .sng file (it does not start with SNGPKG)")
        need(0, 26, "header")
        self.version = struct.unpack_from("<I", data, 6)[0]
        self.mask = data[10:26]

        off = 26
        need(off, 16, "metadata")
        meta_len, meta_count = struct.unpack_from("<QQ", data, off)
        meta_end = off + 8 + meta_len
        off += 16
        self.metadata = {}
        for _ in range(meta_count):
            need(off, 4, "metadata")
            klen = struct.unpack_from("<i", data, off)[0]
            off += 4
            need(off, klen, "metadata")
            key = data[off:off + klen].decode("utf-8", "replace")
            off += klen
            need(off, 4, "metadata")
            vlen = struct.unpack_from("<i", data, off)[0]
            off += 4
            need(off, vlen, "metadata")
            value = data[off:off + vlen].decode("utf-8", "replace")
            off += vlen
            self.metadata[key.strip().lower()] = value.strip()

        off = meta_end
        need(off, 16, "file index")
        index_len, file_count = struct.unpack_from("<QQ", data, off)
        index_end = off + 8 + index_len
        off += 16
        self.files = []
        for _ in range(file_count):
            need(off, 1, "file index")
            nlen = data[off]
            off += 1
            need(off, nlen, "file index")
            name = data[off:off + nlen].decode("utf-8", "replace")
            off += nlen
            need(off, 16, "file index")
            clen, cidx = struct.unpack_from("<QQ", data, off)
            off += 16
            self.files.append((name, clen, cidx))

        off = index_end
        need(off, 8, "file data")
        self.data_start = off + 8

    def raw(self, clen, cidx):
        size = len(self.data)
        if cidx >= self.data_start and cidx + clen <= size:
            start = cidx
        elif self.data_start + cidx + clen <= size:
            start = self.data_start + cidx
        else:
            raise RuntimeError("the .sng file is cut short or damaged (a file runs off the end)")
        return self.data[start:start + clen]

    def read(self, name, clen, cidx):
        """One file's contents, unmasked.

        The mask, from the README: xorKey = xorMask[i % 16] XOR (i AND 0xFF), with i the byte's position within
        that file. The key repeats every 256 bytes, so it is built once and the whole file is XORed as one big
        integer -- byte by byte in Python, a 50 MB package would take the best part of a minute.
        """
        blob = self.raw(clen, cidx)
        n = len(blob)
        if n == 0:
            return b""
        key = bytes(self.mask[i % 16] ^ i for i in range(256))
        stream = (key * (n // 256 + 1))[:n]
        return (int.from_bytes(blob, "little") ^ int.from_bytes(stream, "little")).to_bytes(n, "little")


def _wanted(name):
    """The name to unpack a file from a package as, or None to leave it. Only the chart and the audio stems are
    wanted -- not the album art, not the background video -- and the name is rebuilt from a fixed list, so
    nothing in a package can write anywhere but the temporary folder it is unpacked into."""
    base = name.replace("\\", "/").split("/")[-1].lower()
    stem, ext = os.path.splitext(base)
    if base in ("notes.chart", "notes.mid", "notes.midi"):
        return base
    if ext in AUDIO_EXT and stem in STEMS:
        return stem + ext
    return None


def _looks_right(name, blob):
    """Whether an unpacked file is what its name says: a wrong unmasking produces noise, and noise handed to
    ffmpeg comes back as an error about the audio rather than about the package."""
    if name.endswith((".ogg", ".opus")):
        return blob[:4] == b"OggS"
    if name.endswith((".mid", ".midi")):
        return blob[:4] == b"MThd"
    if name.endswith(".wav"):
        return blob[:4] == b"RIFF"
    if name.endswith(".mp3"):
        return blob[:3] == b"ID3" or (len(blob) > 1 and blob[0] == 0xFF and (blob[1] & 0xE0) == 0xE0)
    if name.endswith(".chart"):
        return b"[" in blob[:16]
    return True


def unpack_sng(path, dest):
    """A .sng unpacked into `dest` as a Clone Hero song folder: the chart, the stems and a song.ini."""
    pkg = SngPackage(path)
    os.makedirs(dest, exist_ok=True)
    written = []
    for name, clen, cidx in pkg.files:
        out = _wanted(name)
        if not out or out in written:
            continue
        blob = pkg.read(name, clen, cidx)
        if not _looks_right(out, blob):
            raise RuntimeError("could not unpack %s from it: the file is damaged, or a newer .sng version (%d)"
                               % (out, pkg.version))
        with open(os.path.join(dest, out), "wb") as fh:
            fh.write(blob)
        written.append(out)
    with open(os.path.join(dest, "song.ini"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("[song]\n")
        for key, value in pkg.metadata.items():
            key = key.replace("=", "").replace("\r", " ").replace("\n", " ").strip()
            if key:
                fh.write("%s = %s\n" % (key, value.replace("\r", " ").replace("\n", " ")))
    return pkg.metadata, written


# ---------------------------------------------------------------------------------------------------------------------- the pack
class Pack:
    """One song pack, and what is in it.

    Two kinds. "My Songs" (Zomboid/mods/EncoreSongs) is only on this computer: songs go there unless a pack is
    chosen. A Workshop pack is made by create_pack and lives in Zomboid/Workshop/<id>/, laid out the way the game's
    own Workshop uploader wants it -- the layout of the user's published mods:

        Zomboid/Workshop/<id>/
            pack.json, songs.json        the pack's details and its songs. Here, and not under Contents, so they
                                         are never uploaded: songs.json remembers where on this computer each song
                                         was imported from, and that is nobody else's business
            cover.png                    the picture chosen for the art, if one was (also not uploaded)
            workshop.txt, preview.png    the Workshop page
            Contents/mods/<id>/          what is uploaded:
                42/mod.info, poster.png, icon.png
                common/media/...         the songs

    The game loads mods out of Zomboid/Workshop as well as Zomboid/mods -- ZomboidFileSystem searches
    "workshop,steam,mods" -- so a pack is playable straight away from where it will be uploaded from, and there is
    one copy of its audio, not two.
    """

    def __init__(self, root):
        self.root = root
        info = {}
        info_path = os.path.join(root, "pack.json")
        if os.path.isfile(info_path):
            info = json.load(open(info_path, encoding="utf-8"))
        self.workshop = bool(info.get("workshop"))
        self.pack_id = info.get("id") or PACK_ID
        self.name = info.get("name") or PACK_NAME
        self.author = info.get("author", "")
        self.description = info.get("description", "")
        self.prefix = info.get("soundPrefix") or SOUND_PREFIX
        self.mod_dir = os.path.join(root, "Contents", "mods", self.pack_id) if self.workshop else root
        self.media = os.path.join(self.mod_dir, "common" if self.workshop else "42", "media")
        self.manifest = os.path.join(root, "songs.json")
        self.songs = {}
        if os.path.isfile(self.manifest):
            self.songs = json.load(open(self.manifest, encoding="utf-8"))

    # ------------------------------------------------------------------------------------------------- names
    def label(self):
        """What the pack is called in a list."""
        return self.name if self.workshop else "%s (only on this computer)" % self.name

    def mod_name(self):
        return self.name if self.workshop else "Project Encore - " + self.name

    def sound_name(self, song_id):
        return self.prefix + song_id

    def sound_path(self, song_id):
        return os.path.join(self.media, "sound", self.sound_name(song_id) + ".ogg")

    def chart_rel(self, song_id):
        return "media/encore/%s/%s/notes.chart" % (self.pack_id, song_id)

    def chart_path(self, song_id):
        return os.path.join(self.mod_dir, "common" if self.workshop else "42", *self.chart_rel(song_id).split("/"))

    def art_paths(self):
        info = os.path.join(self.mod_dir, "42")
        return (os.path.join(self.root, "preview.png"), os.path.join(info, "poster.png"), os.path.join(info, "icon.png"))

    # ------------------------------------------------------------------------------------------------- songs
    def unique_id(self, wanted, source):
        """The id for a song. Importing the same folder twice replaces it; two different songs never share one."""
        for song_id, song in self.songs.items():
            if os.path.normcase(song.get("source", "")) == os.path.normcase(source):
                return song_id
        candidate, n = wanted, 2
        while candidate in self.songs:
            candidate = "%s_%d" % (wanted, n)
            n += 1
        return candidate

    def remove(self, song_id):
        if song_id not in self.songs:
            return False
        del self.songs[song_id]
        if os.path.isfile(self.sound_path(song_id)):
            os.remove(self.sound_path(song_id))
        shutil.rmtree(os.path.dirname(self.chart_path(song_id)), ignore_errors=True)
        return True

    def size_bytes(self):
        """How much would be uploaded: everything under the mod's folder."""
        total = 0
        for dirpath, _dirs, files in os.walk(self.mod_dir):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
        return total

    # ------------------------------------------------------------------------------------------------- writing
    def save_info(self):
        if not self.workshop:
            return
        with open(os.path.join(self.root, "pack.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"workshop": True, "id": self.pack_id, "name": self.name, "author": self.author,
                       "description": self.description, "soundPrefix": self.prefix}, fh, indent=1, ensure_ascii=False)

    def draw_art(self):
        """The preview, poster and icon, from the chosen cover if there is one. Only Workshop packs have art: My
        Songs is never shown to anybody."""
        if not self.workshop:
            return
        pack_art = _sibling("pack_art")
        cover = os.path.join(self.root, "cover.png")
        preview, poster, icon = self.art_paths()
        pack_art.make(self.name, preview, poster, icon, cover if os.path.isfile(cover) else None)

    def migrate(self):
        """Charts the importer's first version wrote sat at media/encore/<song>/notes.chart. They now sit under
        the pack's own id (chart_rel), so two packs holding the same song cannot overwrite each other's chart. A
        chart still in the old place is moved before the registrations, which point at the new place, are written
        -- otherwise the first import after updating would leave every older song pointing at nothing."""
        for song_id in self.songs:
            new = self.chart_path(song_id)
            old = os.path.join(self.media, "encore", song_id, "notes.chart")
            if os.path.normcase(new) == os.path.normcase(old) or os.path.isfile(new) or not os.path.isfile(old):
                continue
            os.makedirs(os.path.dirname(new), exist_ok=True)
            shutil.move(old, new)
            try:
                os.rmdir(os.path.dirname(old))
            except OSError:
                pass

    def write(self):
        """Everything generated, from pack.json and songs.json."""
        self.migrate()
        os.makedirs(os.path.join(self.mod_dir, "42"), exist_ok=True)
        if self.workshop:
            os.makedirs(os.path.join(self.mod_dir, "common", "media"), exist_ok=True)
            self.save_info()
            if not all(os.path.isfile(p) for p in self.art_paths()):
                self.draw_art()

        poster = os.path.isfile(self.art_paths()[1])
        about = self.description.splitlines()[0] if self.description else (
            "A song pack for Project Encore." if self.workshop else
            "Songs imported from Clone Hero with Project Encore's importer.")
        info = ["name=" + _one_line(self.mod_name()), "id=" + self.pack_id, "description=" + _one_line(about)]
        if poster:
            info += ["poster=poster.png", "icon=icon.png"]
        info += ["author=" + _one_line(self.author), "modversion=1.0", "pzversion=" + PZ_VERSION, "require=" + REQUIRE]
        with open(os.path.join(self.mod_dir, "42", "mod.info"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(info) + "\n")

        with open(self.manifest, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.songs, fh, indent=1, ensure_ascii=False, sort_keys=True)

        scripts = os.path.join(self.media, "scripts")
        os.makedirs(scripts, exist_ok=True)
        lines = ["/* Written by Project Encore's importer from songs.json. Do not edit. */", "",
                 "module Base", "{"]
        for song_id in sorted(self.songs):
            lines += ["    sound %s" % self.sound_name(song_id), "    {", "        category = Music,",
                      "        loop = false,", "        clip", "        {",
                      "            file = media/sound/%s.ogg," % self.sound_name(song_id),
                      "            volume = 1.0,", "        }", "    }", ""]
        lines.append("}")
        with open(os.path.join(scripts, "%s_sounds.txt" % self.pack_id.lower()), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")

        lua_dir = os.path.join(self.media, "lua", "shared")
        os.makedirs(lua_dir, exist_ok=True)
        out = ["-- Written by Project Encore's importer from songs.json.",
               "-- Do not edit: re-run the importer, or it will be overwritten.", "",
               'require "Encore_API"', "",
               "ProjectEncore.registerSongPack{",
               '    id = "%s",' % self.pack_id,
               # getModFileReader resolves this through the mod's id, and the folder has the same name, so either
               # reading of its first argument finds the charts.
               '    modDir = "%s",' % self.pack_id,
               "    name = %s," % lua_string(self.name)]
        if self.author:
            out.append("    author = %s," % lua_string(self.author))
        out += ["    sort = %d," % (60 if self.workshop else 50), "}", ""]
        for song_id in sorted(self.songs, key=lambda k: (self.songs[k].get("artist", "").lower(), self.songs[k]["title"].lower())):
            song = self.songs[song_id]
            out.append("ProjectEncore.registerSong{")
            out.append('    pack = "%s",' % self.pack_id)
            out.append('    id = "%s",' % song_id)
            for key in ("title", "artist", "album", "year", "charter", "genre"):
                if song.get(key):
                    out.append("    %s = %s," % (key, lua_string(song[key])))
            out.append('    sound = "%s",' % self.sound_name(song_id))
            out.append('    chart = "%s",' % self.chart_rel(song_id))
            out.append("    lengthMs = %d," % song["lengthMs"])
            if song.get("offsetMs"):
                out.append("    offsetMs = %d," % song["offsetMs"])
            out.append("}")
            out.append("")
        with open(os.path.join(lua_dir, "%s.lua" % self.pack_id), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(out))

        if self.workshop:
            self.write_workshop_txt()

    def write_workshop_txt(self):
        """The Workshop page. Rewritten every time from the pack's details, keeping the three things that are not
        the importer's to decide: the item's id (the game writes it in after the first upload; lose it and the next
        upload makes a second item instead of updating this one), its visibility, and its tags."""
        path = os.path.join(self.root, "workshop.txt")
        keep = {"id": "", "visibility": "public", "tags": WORKSHOP_TAGS}
        if os.path.isfile(path):
            for line in open(path, encoding="utf-8", errors="replace").read().splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip() in keep and value.strip():
                    keep[key.strip()] = value.strip()
        tags = [t for t in keep["tags"].split(";") if t.strip()]
        if "Build 42" not in tags:
            tags.insert(0, "Build 42")

        body = [l.rstrip() for l in self.description.splitlines()] if self.description else []
        if body:
            body.append("")
        body += ["A song pack for Project Encore, a Guitar Hero style rhythm game for Project Zomboid.",
                 "[b]Needs Project Encore[/b]: subscribe to it as well, and turn both on in the mod list.", "",
                 "[h1]Songs[/h1]", "[list]"]
        for song_id in sorted(self.songs, key=lambda k: (self.songs[k].get("artist", "").lower(), self.songs[k]["title"].lower())):
            song = self.songs[song_id]
            parts = ", ".join(song.get("parts", []))
            body.append("[*]%s%s%s" % (song["title"], (" - " + song["artist"]) if song.get("artist") else "",
                                       (" (%s)" % parts) if parts else ""))
        body.append("[/list]")

        out = ["version=1"]
        if keep["id"]:
            out.append("id=" + keep["id"])
        out.append("title=" + _one_line(self.name)[:128])
        out += ["description=" + _one_line(line) for line in body]
        out += ["tags=" + ";".join(tags), "visibility=" + keep["visibility"]]
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(out) + "\n")


def _sibling(name):
    """A module from this folder, loaded by its path. Not by `import`: run as `python -I` (or from the window
    app) this folder is not on sys.path, and an import by name would fail -- or find something else."""
    import importlib.util
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


def _one_line(text):
    return " ".join(str(text).replace("\r", " ").replace("\n", " ").split())


# ---------------------------------------------------------------------------------------------------------------------- packs
def list_packs(zomboid_dir):
    """My Songs first, then every Workshop pack the importer has made, by name."""
    packs = [Pack(os.path.join(zomboid_dir, "mods", PACK_ID))]
    found = []
    for info in glob.glob(os.path.join(zomboid_dir, "Workshop", "*", "pack.json")):
        try:
            pack = Pack(os.path.dirname(info))
        except (OSError, ValueError):
            continue
        if pack.workshop:
            found.append(pack)
    return packs + sorted(found, key=lambda p: p.name.lower())


def find_pack(zomboid_dir, name):
    for pack in list_packs(zomboid_dir):
        if pack.name.lower() == name.strip().lower():
            return pack
    return None


def create_pack(zomboid_dir, name, author="", description=""):
    """A new, empty song pack, ready to fill and upload.

    The mod id is the name in CamelCase plus six random hex digits: mod ids are one table across everything a player
    subscribes to, and two people's "Rock Pack" must not be the same mod. The sounds get a prefix from the same
    digits, for the same reason. Neither changes if the pack is renamed later: the id is what the Workshop item and
    every save that uses the pack know it by."""
    import hashlib
    import time
    name = _one_line(name)
    if not name:
        raise RuntimeError("Give the pack a name.")
    if find_pack(zomboid_dir, name):
        raise RuntimeError("There is already a pack called %s." % name)
    token = hashlib.sha1(("%s|%s|%f" % (name, author, time.time())).encode("utf-8")).hexdigest()[:6]
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    camel = "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", plain))[:28] or "Pack"
    pack_id = "Encore_%s_%s" % (camel, token)
    root = os.path.join(zomboid_dir, "Workshop", pack_id)
    os.makedirs(root)
    try:
        with open(os.path.join(root, "pack.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"workshop": True, "id": pack_id, "name": name, "author": _one_line(author),
                       "description": description.strip(), "soundPrefix": "ENC%s_" % token.upper()}, fh, indent=1,
                      ensure_ascii=False)
        pack = Pack(root)
        pack.write()
    except Exception:
        # A pack that failed half-way would still be listed (pack.json is there) and would upload broken.
        shutil.rmtree(root, ignore_errors=True)
        raise
    return pack


def update_details(pack, name=None, author=None, description=None, cover=None, clear_cover=False):
    """Change a Workshop pack's name, author, description or cover picture, and redraw what shows them."""
    if not pack.workshop:
        raise RuntimeError("My Songs is only on this computer; make a pack to publish songs.")
    if name is not None:
        name = _one_line(name)
        if not name:
            raise RuntimeError("Give the pack a name.")
        other = find_pack(os.path.dirname(os.path.dirname(pack.root)), name)
        if other and other.pack_id != pack.pack_id:
            raise RuntimeError("There is already a pack called %s." % name)
        pack.name = name
    if author is not None:
        pack.author = _one_line(author)
    if description is not None:
        pack.description = description.strip()
    cover_path = os.path.join(pack.root, "cover.png")
    if clear_cover and os.path.isfile(cover_path):
        os.remove(cover_path)
    if cover:
        pack_art = _sibling("pack_art")
        if not pack_art.HAVE_PIL:
            raise RuntimeError(pack_art.PILLOW_HINT)
        from PIL import Image
        img = Image.open(cover).convert("RGB")
        img.thumbnail((1024, 1024))
        img.save(cover_path)
    pack.save_info()
    pack.draw_art()
    pack.write()


def prepare_workshop(pack):
    """Make a pack ready for the game's uploader, and say whether anything stops it. Returns a dict:
    songs, size (bytes), folder, problems (sentences; empty means it is ready)."""
    if not pack.workshop:
        raise RuntimeError("My Songs is only on this computer; make a pack to publish songs.")
    pack.draw_art()
    pack.write()
    problems = []
    if not pack.songs:
        problems.append("The pack has no songs in it yet.")
    preview = pack.art_paths()[0]
    size = png_size(preview)
    if size is None:
        problems.append("There is no preview.png.")
    elif tuple(size) != (256, 256):
        problems.append("preview.png is not 256 x 256.")
    for song_id in pack.songs:
        if not os.path.isfile(pack.sound_path(song_id)) or not os.path.isfile(pack.chart_path(song_id)):
            problems.append("%s is missing its audio or its chart: import it again." % pack.songs[song_id]["title"])
    return {"songs": len(pack.songs), "size": pack.size_bytes(), "folder": pack.root, "problems": problems}


UPLOAD_STEPS = [
    "Start Project Zomboid.",
    "On the main menu, click Workshop, then Create and update items.",
    "Pick \"{name}\" in the list and click Upload.",
    "Once it is up, open its Steam page and add Project Encore as a Required item, so subscribers get it too.",
]


def lua_string(text):
    text = str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")
    return '"%s"' % text


# ---------------------------------------------------------------------------------------------------------------------- importing
def import_song(pack, folder, log=print, source=None, fallback_name=None):
    """Import one song folder. `source` is what the song is remembered as having come from (so importing it again
    replaces it): the folder, or the .sng it was unpacked from. Returns the song's id."""
    folder = os.path.abspath(folder)
    source = source or folder
    ini = read_ini(folder)
    chart_src, kind = find_chart(folder)
    stems = find_stems(folder)
    if not chart_src:
        raise RuntimeError("no notes.chart or notes.mid in it")
    if not stems:
        raise RuntimeError("no audio in it (song.ogg, guitar.ogg, ... in .ogg, .opus, .mp3 or .wav)")
    need_tools()

    name = fallback_name or os.path.basename(folder.rstrip("\\/"))
    title = ini.get("name") or name
    artist = ini.get("artist") or ""
    # Clone Hero lets these carry colour tags: <color=#ff0000>Title</color>.
    title = re.sub(r"<[^>]+>", "", title).strip() or name
    artist = re.sub(r"<[^>]+>", "", artist).strip()

    song_id = pack.unique_id(slug((artist + " " + title).strip()), source)
    install_chart(chart_src, kind, pack.chart_path(song_id), title, artist)
    tracks = chart_tracks(pack.chart_path(song_id))
    if not tracks:
        shutil.rmtree(os.path.dirname(pack.chart_path(song_id)), ignore_errors=True)
        raise RuntimeError("the chart has no instrument parts in it")

    mix(stems, pack.sound_path(song_id))
    length = duration_ms(pack.sound_path(song_id))

    # song.ini's delay is in milliseconds and moves the chart against the audio, the way [Song] Offset (seconds) in
    # a .chart does; the .chart's own is read by the game, so only the ini's is carried here.
    try:
        offset = int(float(ini.get("delay", "0") or 0))
    except ValueError:
        offset = 0

    pack.songs[song_id] = {
        "title": title, "artist": artist,
        "album": ini.get("album", ""), "year": re.sub(r"^,\s*", "", ini.get("year", "")),
        "charter": ini.get("charter") or ini.get("frets", ""), "genre": ini.get("genre", ""),
        "lengthMs": length, "offsetMs": offset, "source": source, "chartFrom": kind, "stems": len(stems),
        "parts": [TRACK_NAMES.get(t, t) for t in sorted(tracks)],
    }
    order = ("Easy", "Medium", "Hard", "Expert")
    parts = ", ".join("%s (%s)" % (TRACK_NAMES.get(t, t), "/".join(d for d in order if d in ds))
                      for t, ds in sorted(tracks.items()))
    log("  + %s%s  [%d:%02d, %d stem%s, from .%s]" % (title, (" - " + artist) if artist else "",
                                                      length // 60000, (length // 1000) % 60,
                                                      len(stems), "" if len(stems) == 1 else "s", kind))
    log("      parts: " + parts)
    return song_id


def import_any(pack, path, log=print):
    """A .sng file or a song folder, whichever `path` is."""
    path = os.path.abspath(path)
    if os.path.isfile(path) and path.lower().endswith(".sng"):
        tmp = tempfile.mkdtemp(prefix="encore_sng_")
        try:
            unpack_sng(path, tmp)
            return import_song(pack, tmp, log=log, source=path,
                               fallback_name=os.path.splitext(os.path.basename(path))[0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if os.path.isdir(path):
        return import_song(pack, path, log=log)
    raise RuntimeError("not a .sng file or a Clone Hero song folder")


# ---------------------------------------------------------------------------------------------------------------------- switching it on
_MOD_LINE = r"(?m)^\s*mod\s*=\s*%s\s*,"


def _add_mods(text, names):
    """`text` (a default.txt or a save's mods.txt) with any of `names` that are missing added to its mods block,
    in the game's own format. None if there is no mods block to add them to."""
    m = re.search(r"(?ms)^(\s*mods\s*\{)(.*?)^(\s*\})", text)
    if not m:
        return None
    body = m.group(2)
    add = "".join("    mod = %s,\n" % n for n in names if not re.search(_MOD_LINE % re.escape(n), body))
    if not add:
        return text
    if not body.endswith("\n"):
        body += "\n"
    return text[:m.start(2)] + body + add + text[m.end(2):]


def enable_pack(zomboid_dir, log=print, pack_id=PACK_ID):
    """Switch the song pack on where it will be played. Returns where it was switched on, as labels.

    Every save keeps its own mod list (Saves/<mode>/<save>/mods.txt) and mods/default.txt is only the list a new
    game starts with, so turning it on in the default alone would leave the save being played without it. It is
    added to the default and to every save that already plays Project Encore -- a save with ProjectEncore in its list --
    and nowhere else. Each file is backed up the first time it is changed, as <file>.encore-backup.
    """
    targets = []
    default = os.path.join(zomboid_dir, "mods", "default.txt")
    if os.path.isfile(default):
        targets.append(("new games", default, ["ProjectEncore", pack_id]))
    saves = os.path.join(zomboid_dir, "Saves")
    for mods_txt in sorted(glob.glob(os.path.join(saves, "*", "*", "mods.txt"))):
        try:
            text = open(mods_txt, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if re.search(_MOD_LINE % "ProjectEncore", text):
            label = "save " + os.path.relpath(os.path.dirname(mods_txt), saves).replace("\\", "/")
            targets.append((label, mods_txt, [pack_id]))

    changed = []
    for label, path, names in targets:
        text = open(path, encoding="utf-8", errors="replace").read()
        new = _add_mods(text, names)
        if new is None:
            log("  ? could not find the mod list in " + path)
            continue
        if new == text:
            continue
        backup = path + ".encore-backup"
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
        changed.append(label)
    return changed


def game_running():
    """Whether Project Zomboid is open: a song imported now only shows up after a restart."""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ProjectZomboid64.exe", "/NH"],
                             capture_output=True, text=True, **_NO_WINDOW).stdout
    except OSError:
        return False
    return "projectzomboid64.exe" in out.lower()


def find_songs(root):
    """Every song under a library folder, however deep the charters nested them: song folders and .sng files."""
    found = []
    for dirpath, dirnames, files in os.walk(root):
        if is_song_folder(dirpath):
            found.append(dirpath)
            dirnames[:] = []                 # a song folder has no songs inside it
            continue
        for name in sorted(files):
            if name.lower().endswith(".sng"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def main():
    ap = argparse.ArgumentParser(description="Import Clone Hero songs into Project Encore")
    ap.add_argument("folders", nargs="*", help="Clone Hero .sng files or song folders")
    ap.add_argument("--all", metavar="LIBRARY", help="import every song found under this folder")
    ap.add_argument("--list", action="store_true", help="list what has been imported")
    ap.add_argument("--remove", metavar="ID", action="append", default=[], help="remove an imported song by id")
    ap.add_argument("--pack", metavar="NAME", help="import into this song pack, making it if it does not exist")
    ap.add_argument("--packs", action="store_true", help="list the song packs")
    ap.add_argument("--author", default="", help="the author, for a new pack")
    ap.add_argument("--description", default="", help="the description, for a new pack")
    ap.add_argument("--prepare-workshop", action="store_true", help="ready the --pack for upload")
    ap.add_argument("--pack-dir", help=argparse.SUPPRESS)
    ap.add_argument("--zomboid-dir", default=os.path.dirname(MODS), help=argparse.SUPPRESS)
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print("%s is not on PATH; the importer needs it to mix and measure the audio." % tool)
            return 2

    if args.packs:
        for p in list_packs(args.zomboid_dir):
            print("%-44s %3d song(s)  %s" % (p.label(), len(p.songs), p.root))
        return 0

    if args.pack_dir:
        pack = Pack(args.pack_dir)
    elif args.pack:
        pack = find_pack(args.zomboid_dir, args.pack)
        if pack is None:
            pack = create_pack(args.zomboid_dir, args.pack, args.author, args.description)
            print("made the pack %s at %s" % (pack.name, pack.root))
    else:
        pack = list_packs(args.zomboid_dir)[0]

    if args.list:
        if not pack.songs:
            print("Nothing imported yet.")
        for song_id in sorted(pack.songs):
            s = pack.songs[song_id]
            print("%-40s %s%s" % (song_id, s["title"], (" - " + s["artist"]) if s.get("artist") else ""))
        return 0

    changed = False
    for song_id in args.remove:
        if pack.remove(song_id):
            print("  - removed " + song_id)
            changed = True
        else:
            print("  ? no imported song has the id '%s' (see --list)" % song_id)

    folders = [os.path.abspath(f) for f in args.folders]
    if args.all:
        found = find_songs(args.all)
        print("%d song(s) under %s" % (len(found), args.all))
        folders += found

    failed = 0
    for folder in folders:
        if not os.path.exists(folder):
            print("  ! %s: no such file or folder" % folder)
            failed += 1
            continue
        try:
            import_any(pack, folder)
            changed = True
        except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
            print("  ! %s: %s" % (os.path.basename(folder.rstrip("\\/")), exc))
            failed += 1

    if not folders and not args.remove and not args.prepare_workshop:
        ap.print_help()
        return 1

    if changed:
        pack.write()
        print()
        print("%d song(s) in the pack at %s" % (len(pack.songs), pack.root))
        for where in enable_pack(args.zomboid_dir, pack_id=pack.pack_id):
            print("  switched the pack on for " + where)
        print("Restart the game to see new songs." if game_running() else "The songs are there next time the game starts.")

    if args.prepare_workshop:
        report = prepare_workshop(pack)
        print()
        print("%s: %d song(s), %.1f MB, at %s" % (pack.name, report["songs"], report["size"] / 1048576.0, report["folder"]))
        if report["problems"]:
            for problem in report["problems"]:
                print("  ! " + problem)
            return 1
        print("Ready to upload:")
        for i, step in enumerate(UPLOAD_STEPS, 1):
            print("  %d. %s" % (i, step.format(name=pack.name)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
