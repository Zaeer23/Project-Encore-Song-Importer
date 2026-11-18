import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import import_clonehero as IC

TITLE = "Project Encore Importer"


def _sharp_on_high_dpi():
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _icon(window):
    icon = os.path.join(HERE, "encore_importer.ico")
    if os.path.isfile(icon):
        try:
            window.iconbitmap(icon)
        except tk.TclError:
            pass


class App:
    def __init__(self, root, pack_dir=None, zomboid_dir=None):
        self.root = root
        self.zomboid_dir = zomboid_dir or os.path.dirname(IC.MODS)
        self.fixed_pack = pack_dir
        self.settings_path = os.path.join(self.zomboid_dir, "encore_importer.json")
        self.settings = self.load_settings()
        self.q = queue.Queue()
        self.busy = False
        self.last_dir = self.settings.get("lastDir") or os.path.join(os.path.expanduser("~"), "Downloads")
        self.packs = []
        self.pack = None

        root.title(TITLE)
        root.minsize(600, 460)
        root.geometry("720x540")
        _icon(root)

        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Project Encore Importer", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Add Clone Hero songs to the game, or make a song pack for the Workshop.").pack(
            anchor="w", pady=(0, 10))

        packs = ttk.Frame(outer)
        packs.pack(fill="x")
        ttk.Label(packs, text="Song pack:").pack(side="left")
        self.pack_box = ttk.Combobox(packs, state="readonly", width=38)
        self.pack_box.pack(side="left", padx=(6, 0))
        self.pack_box.bind("<<ComboboxSelected>>", lambda _e: self.choose_pack(self.pack_box.current()))
        self.new_btn = ttk.Button(packs, text="New pack...", command=self.new_pack)
        self.new_btn.pack(side="left", padx=(8, 0))
        self.publish_btn = ttk.Button(packs, text="Publish to Workshop...", command=self.publish)
        self.publish_btn.pack(side="right")

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 0))
        self.import_btn = ttk.Button(buttons, text="Import .sng files...", command=self.pick_files)
        self.import_btn.pack(side="left")
        self.folder_btn = ttk.Button(buttons, text="Import a song folder...", command=self.pick_folder)
        self.folder_btn.pack(side="left", padx=(8, 0))

        self.count_label = ttk.Label(outer, text="")
        self.count_label.pack(anchor="w", pady=(14, 4))

        table = ttk.Frame(outer)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("title", "artist", "length"), show="headings", selectmode="extended",
                                 height=8)
        self.tree.heading("title", text="Song")
        self.tree.heading("artist", text="Artist")
        self.tree.heading("length", text="Length")
        self.tree.column("title", width=320, anchor="w")
        self.tree.column("artist", width=200, anchor="w")
        self.tree.column("length", width=70, anchor="e", stretch=False)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Delete>", lambda _e: self.remove_selected())

        under = ttk.Frame(outer)
        under.pack(fill="x", pady=(6, 0))
        self.remove_btn = ttk.Button(under, text="Remove", command=self.remove_selected)
        self.remove_btn.pack(side="left")
        ttk.Button(under, text="Open the pack's folder", command=self.open_folder).pack(side="right")

        self.log_box = tk.Text(outer, height=6, wrap="word", state="disabled", relief="flat",
                               background=root.cget("background"), font=("Consolas", 9))
        self.log_box.pack(fill="x", pady=(12, 4))

        self.status = ttk.Label(outer, text="", foreground="#555555")
        self.status.pack(anchor="w")

        self.reload_packs(select_id=self.settings.get("lastPack"))
        self.check_tools()
        root.after(100, self.poll)

    def load_settings(self):
        try:
            return json.load(open(self.settings_path, encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_settings(self, **changes):
        self.settings.update(changes)
        try:
            with open(self.settings_path, "w", encoding="utf-8") as fh:
                json.dump(self.settings, fh, indent=1)
        except OSError:
            pass

    def reload_packs(self, select_id=None):
        if self.fixed_pack:
            self.packs = [IC.Pack(self.fixed_pack)]
        else:
            self.packs = IC.list_packs(self.zomboid_dir)
        self.pack_box["values"] = [p.label() for p in self.packs]
        index = 0
        for i, p in enumerate(self.packs):
            if p.pack_id == select_id:
                index = i
        self.choose_pack(index)

    def choose_pack(self, index):
        if index < 0 or index >= len(self.packs):
            index = 0
        self.pack = self.packs[index]
        self.pack_box.current(index)
        self.save_settings(lastPack=self.pack.pack_id)
        self.refresh()

    def refresh(self):
        pack = IC.Pack(self.pack.root)
        self.pack = pack
        self.tree.delete(*self.tree.get_children())
        order = sorted(pack.songs, key=lambda k: (pack.songs[k].get("artist", "").lower(), pack.songs[k]["title"].lower()))
        for song_id in order:
            s = pack.songs[song_id]
            ms = s.get("lengthMs", 0)
            self.tree.insert("", "end", iid=song_id,
                             values=(s["title"], s.get("artist", ""), "%d:%02d" % (ms // 60000, (ms // 1000) % 60)))
        n = len(order)
        where = "in %s" % pack.name
        self.count_label.config(text=("Songs %s (%d)" % (where, n)) if n else "No songs %s yet" % where)
        self.update_buttons()

    def update_buttons(self):
        idle = not self.busy
        for b in (self.import_btn, self.folder_btn, self.remove_btn, self.new_btn):
            b.state(["!disabled"] if idle and self.tools_ok else ["disabled"])
        self.remove_btn.state(["!disabled"] if idle else ["disabled"])
        self.new_btn.state(["!disabled"] if idle and not self.fixed_pack else ["disabled"])
        self.publish_btn.state(["!disabled"] if idle and self.pack and self.pack.workshop else ["disabled"])
        self.pack_box.state(["!disabled", "readonly"] if idle and not self.fixed_pack else ["disabled"])

    tools_ok = True

    def check_tools(self):
        missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
        self.tools_ok = not missing
        self.update_buttons()
        if missing:
            self.set_status("ffmpeg was not found, so songs cannot be converted. Install ffmpeg and open this again.",
                            error=True)
            return False
        self.set_status("Ready.")
        return True

    def new_pack(self):
        dlg = PackDialog(self.root, "New song pack", author=self.settings.get("author", ""),
                         confirm="Make the pack")
        if not dlg.result:
            return
        name, author, description = dlg.result
        try:
            pack = IC.create_pack(self.zomboid_dir, name, author, description)
        except Exception as exc:
            messagebox.showerror(TITLE, str(exc), parent=self.root)
            return
        self.save_settings(author=author)
        self.reload_packs(select_id=pack.pack_id)
        self.clear_log()
        self.log("Made the pack %s. Import songs into it, then Publish to Workshop when it is ready." % pack.name)
        self.set_status("New pack: %s." % pack.name)

    def publish(self):
        if not self.pack or not self.pack.workshop:
            return
        PublishDialog(self.root, self)
        self.reload_packs(select_id=self.pack.pack_id)

    def pick_files(self):
        paths = filedialog.askopenfilenames(parent=self.root, title="Choose .sng files to import",
                                            initialdir=self.last_dir,
                                            filetypes=[("Clone Hero songs", "*.sng"), ("All files", "*.*")])
        if paths:
            self.last_dir = os.path.dirname(paths[0])
            self.save_settings(lastDir=self.last_dir)
            self.start_import(list(paths))

    def pick_folder(self):
        path = filedialog.askdirectory(parent=self.root, title="Choose a Clone Hero song folder (or a folder of songs)",
                                       initialdir=self.last_dir, mustexist=True)
        if not path:
            return
        self.last_dir = path
        self.save_settings(lastDir=path)
        paths = [path] if IC.is_song_folder(path) else IC.find_songs(path)
        if not paths:
            messagebox.showinfo(TITLE, "No Clone Hero songs were found in that folder.\n\n"
                                       "A song folder has a notes.chart or notes.mid and its audio in it.",
                                parent=self.root)
            return
        self.start_import(paths)

    def start_import(self, paths):
        if self.busy or not paths:
            return
        self.busy = True
        self.update_buttons()
        self.clear_log()
        threading.Thread(target=self.work, args=(paths, self.pack.root), daemon=True).start()

    def work(self, paths, pack_root):
        q = self.q
        done = 0
        try:
            pack = IC.Pack(pack_root)
            for i, path in enumerate(paths, 1):
                q.put(("status", "Importing %d of %d into %s: %s" % (i, len(paths), pack.name,
                                                                      os.path.basename(path.rstrip("\\/")))))
                try:
                    song_id = IC.import_any(pack, path, log=lambda _m: None)
                    s = pack.songs[song_id]
                    ms = s.get("lengthMs", 0)
                    q.put(("log", "Added: %s%s  (%d:%02d, %s)" % (
                        s["title"], (" - " + s["artist"]) if s.get("artist") else "",
                        ms // 60000, (ms // 1000) % 60, ", ".join(s.get("parts", [])) or "no parts")))
                    done += 1
                except subprocess.CalledProcessError as exc:
                    err = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                    detail = err.strip().splitlines()
                    q.put(("log", "Could not convert %s: %s" % (os.path.basename(path),
                                                                 detail[-1] if detail else "ffmpeg failed")))
                except Exception as exc:
                    q.put(("log", "Could not import %s: %s" % (os.path.basename(path.rstrip("\\/")), exc)))
            if done:
                pack.write()
                switched = IC.enable_pack(self.zomboid_dir, log=lambda m: q.put(("log", m.strip())),
                                          pack_id=pack.pack_id)
                if switched:
                    q.put(("log", "Turned %s on for: %s." % (pack.name, ", ".join(switched))))
        except Exception:
            q.put(("log", traceback.format_exc()))
        q.put(("done", done, len(paths)))

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self.log(msg[1])
                elif kind == "status":
                    self.set_status(msg[1])
                elif kind == "done":
                    self.finished(msg[1], msg[2])
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def finished(self, done, total):
        self.busy = False
        self.refresh()
        if done == 0:
            self.set_status("Nothing was imported.", error=True)
            return
        failed = total - done
        text = "Imported %d song%s into %s." % (done, "" if done == 1 else "s", self.pack.name)
        if failed:
            text += " %d could not be imported (see above)." % failed
        if IC.game_running():
            text += " Project Zomboid is open: restart it to see the new songs."
        else:
            text += " They are in the setlist next time the game starts."
        self.set_status(text, error=bool(failed))

    def remove_selected(self):
        if self.busy:
            return
        ids = list(self.tree.selection())
        if not ids:
            self.set_status("Pick the songs to remove in the list first.")
            return
        pack = IC.Pack(self.pack.root)
        names = [pack.songs[i]["title"] for i in ids if i in pack.songs]
        what = names[0] if len(names) == 1 else "%d songs" % len(names)
        if not messagebox.askyesno(TITLE, "Remove %s from %s?\n\nYour original .sng files are not touched."
                                   % (what, pack.name), parent=self.root):
            return
        for song_id in ids:
            pack.remove(song_id)
        pack.write()
        self.refresh()
        self.set_status("Removed %s." % what)

    def open_folder(self):
        if os.path.isdir(self.pack.root):
            os.startfile(self.pack.root)
        else:
            self.set_status("Nothing has been imported into %s yet, so it has no folder." % self.pack.name)

    def log(self, text):
        self.log_box.config(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def clear_log(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    def set_status(self, text, error=False):
        self.status.config(text=text, foreground="#b00020" if error else "#555555")


class PackDialog:
    def __init__(self, parent, title, name="", author="", description="", confirm="OK"):
        self.result = None
        top = self.top = tk.Toplevel(parent)
        top.title(title)
        top.transient(parent)
        top.resizable(False, False)
        _icon(top)
        frame = ttk.Frame(top, padding=14)
        frame.pack(fill="both", expand=True)
        self.fields = PackFields(frame, name, author, description)
        self.fields.frame.pack(fill="both", expand=True)
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(12, 0))
        ttk.Button(row, text="Cancel", command=top.destroy).pack(side="right")
        ttk.Button(row, text=confirm, command=self.ok).pack(side="right", padx=(0, 8))
        top.bind("<Escape>", lambda _e: top.destroy())
        self.fields.name.focus_set()
        top.grab_set()
        parent.wait_window(top)

    def ok(self):
        name, author, description = self.fields.values()
        if not name:
            messagebox.showinfo(TITLE, "Give the pack a name.", parent=self.top)
            return
        self.result = (name, author, description)
        self.top.destroy()


class PackFields:
    def __init__(self, parent, name, author, description):
        self.frame = ttk.Frame(parent)
        ttk.Label(self.frame, text="Name").grid(row=0, column=0, sticky="w")
        self.name = ttk.Entry(self.frame, width=44)
        self.name.insert(0, name)
        self.name.grid(row=0, column=1, sticky="we", pady=2)
        ttk.Label(self.frame, text="Author").grid(row=1, column=0, sticky="w")
        self.author = ttk.Entry(self.frame, width=44)
        self.author.insert(0, author)
        self.author.grid(row=1, column=1, sticky="we", pady=2)
        ttk.Label(self.frame, text="Description").grid(row=2, column=0, sticky="nw", pady=(4, 0))
        self.description = tk.Text(self.frame, width=44, height=5, wrap="word", font=("Segoe UI", 9))
        self.description.insert("1.0", description)
        self.description.grid(row=2, column=1, sticky="we", pady=(4, 0))
        ttk.Label(self.frame, text="The song list is added to the Workshop page for you.",
                  foreground="#555555").grid(row=3, column=1, sticky="w")
        self.frame.columnconfigure(1, weight=1)

    def values(self):
        return (self.name.get().strip(), self.author.get().strip(), self.description.get("1.0", "end").strip())


class PublishDialog:
    def __init__(self, parent, app):
        self.app = app
        self.pack = IC.Pack(app.pack.root)
        self.cover = None
        self.clear_cover = False
        top = self.top = tk.Toplevel(parent)
        top.title("Publish %s to the Workshop" % self.pack.name)
        top.transient(parent)
        top.resizable(False, False)
        _icon(top)
        frame = ttk.Frame(top, padding=14)
        frame.pack(fill="both", expand=True)

        side = ttk.Frame(frame)
        side.grid(row=0, column=0, sticky="n", padx=(0, 14))
        self.preview = ttk.Label(side)
        self.preview.pack()
        pic = ttk.Frame(side)
        pic.pack(pady=(6, 0))
        ttk.Button(pic, text="Picture...", command=self.choose_cover).pack(side="left")
        ttk.Button(pic, text="Use the default", command=self.default_cover).pack(side="left", padx=(6, 0))

        self.fields = PackFields(frame, self.pack.name, self.pack.author, self.pack.description)
        self.fields.frame.grid(row=0, column=1, sticky="nwe")

        self.facts = ttk.Label(frame, text="", justify="left")
        self.facts.grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.steps = ttk.Label(frame, text="", justify="left", wraplength=560)
        self.steps.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        row = ttk.Frame(frame)
        row.grid(row=3, column=0, columnspan=2, sticky="we", pady=(14, 0))
        ttk.Button(row, text="Close", command=top.destroy).pack(side="right")
        self.ready_btn = ttk.Button(row, text="Get it ready to upload", command=self.ready)
        self.ready_btn.pack(side="right", padx=(0, 8))
        ttk.Button(row, text="Open the Workshop folder", command=lambda: os.startfile(self.pack.root)).pack(side="left")

        top.bind("<Escape>", lambda _e: top.destroy())
        self.show()
        top.grab_set()
        if not getattr(app, "no_wait", False):
            parent.wait_window(top)

    def show(self):
        preview = self.pack.art_paths()[0]
        if os.path.isfile(preview):
            self.image = tk.PhotoImage(file=preview).subsample(2)
            self.preview.config(image=self.image)
        n = len(self.pack.songs)
        self.facts.config(text="%d song%s, %.1f MB to upload.%s" % (
            n, "" if n == 1 else "s", self.pack.size_bytes() / 1048576.0,
            "" if n else "  Import some songs into it first."))
        self.ready_btn.state(["!disabled"] if n else ["disabled"])

    def choose_cover(self):
        pack_art = IC._sibling("pack_art")
        if not pack_art.HAVE_PIL:
            messagebox.showinfo(TITLE, pack_art.PILLOW_HINT, parent=self.top)
            return
        path = filedialog.askopenfilename(parent=self.top, title="Choose a picture for the pack",
                                          filetypes=[("Pictures", "*.png *.jpg *.jpeg *.bmp *.webp"), ("All files", "*.*")])
        if path:
            self.cover, self.clear_cover = path, False
            self.apply(redraw_only=True)

    def default_cover(self):
        self.cover, self.clear_cover = None, True
        self.apply(redraw_only=True)

    def apply(self, redraw_only=False):
        name, author, description = self.fields.values()
        try:
            IC.update_details(self.pack, name=name, author=author, description=description,
                              cover=self.cover, clear_cover=self.clear_cover)
        except Exception as exc:
            messagebox.showerror(TITLE, str(exc), parent=self.top)
            return False
        self.cover, self.clear_cover = None, False
        self.app.save_settings(author=author)
        self.pack = IC.Pack(self.pack.root)
        self.show()
        return True

    def ready(self):
        if not self.apply():
            return
        report = IC.prepare_workshop(self.pack)
        self.pack = IC.Pack(self.pack.root)
        self.show()
        if report["problems"]:
            self.steps.config(text="Not ready yet:\n" + "\n".join("  - " + p for p in report["problems"]),
                              foreground="#b00020")
            return
        steps = "\n".join("  %d. %s" % (i, s.format(name=self.pack.name)) for i, s in enumerate(IC.UPLOAD_STEPS, 1))
        self.steps.config(text="Ready. To upload it:\n" + steps, foreground="")


def main():
    _sharp_on_high_dpi()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
