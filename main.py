
"""PTT Connect Radio Gateway: Windows audio test alongside installed TeamSpeak.

This application does NOT send audio to TeamSpeak. Its test tone uses the selected
output device; the audio monitor uses the selected input device. Configure the
same devices and voice activation in the installed TeamSpeak client.
"""
import json
import math
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from urllib.parse import urlencode

import numpy as np
import sounddevice as sd

SERVERS = {"TG-103 Voorburg": "ptt.mijnts3.nl", "TG-108 Heerlen": "heerlen.mijnts3.nl"}
PATH = Path(os.getenv("APPDATA", str(Path.home()))) / "PTTConnectRadioGateway" / "settings.json"
COL = {"bg": "#18191c", "side": "#111315", "card": "#292c31", "accent": "#dc8a39", "fg": "#f5eee6", "sub": "#b8aea6", "ok": "#61cf91"}
DEFAULT = {"server": "TG-103 Voorburg", "nickname": "Radio Gateway", "channel": "", "port": "9987", "input": "", "output": "", "gain": 100, "threshold": 12, "attack": 150, "release": 900, "mode": "RX/TX"}


def load():
    try:
        obj = json.loads(PATH.read_text(encoding="utf-8"))
        return {**DEFAULT, **{k: v for k, v in obj.items() if k in DEFAULT}}
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT)


class GUI:
    def __init__(self, root):
        self.root = root
        self.root.title("PTT Connect Radio Gateway — Copper Audio Test")
        self.root.geometry("1100x740")
        self.root.minsize(920, 610)
        self.root.configure(bg=COL["bg"])
        self.v = {k: tk.StringVar(value=str(val)) for k, val in load().items()}
        self.devices_in, self.devices_out = {}, {}
        self.events = queue.Queue(maxsize=8)
        self.stream = None
        self.vox = False
        self.high_ms = self.low_ms = 0.0
        self.level = 0.0
        self.peak = 0.0
        self.pages, self.buttons = {}, {}
        self.closed = False
        self.tone_running = False
        self.setup()
        self.refresh_devices()
        self.page("Overzicht")
        self.root.after(70, self.tick)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def setup(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure("TButton", padding=(12, 8))
        st.configure("Copper.TButton", background="#ad6128", foreground="white")
        st.map("Copper.TButton", background=[("active", COL["accent"])])
        st.configure("TCombobox", padding=6)
        st.configure("TEntry", padding=6)
        st.configure("Bar.Horizontal.TProgressbar", background=COL["ok"], troughcolor="#46372b")
        base = tk.Frame(self.root, bg=COL["bg"])
        base.pack(fill="both", expand=True)
        side = tk.Frame(base, bg=COL["side"], width=220)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="◉ PTT Connect", bg=COL["side"], fg=COL["fg"], font=("Segoe UI", 18, "bold")).pack(padx=16, pady=(24, 3), anchor="w")
        tk.Label(side, text="RADIO GATEWAY", bg=COL["side"], fg=COL["accent"], font=("Segoe UI", 11, "bold")).pack(padx=18, pady=(0, 25), anchor="w")
        for name in ("Overzicht", "TeamSpeak", "Audioapparaten", "VOX-instellingen", "Radiomodus", "Systeem"):
            b = tk.Button(side, text="  " + name, anchor="w", bg=COL["side"], fg=COL["fg"], bd=0, relief="flat", padx=10, pady=13, font=("Segoe UI", 11), command=lambda n=name: self.page(n))
            b.pack(fill="x", padx=7, pady=2)
            self.buttons[name] = b
        main = tk.Frame(base, bg=COL["bg"])
        main.pack(side="left", fill="both", expand=True)
        head = tk.Frame(main, bg="#24272a", height=90)
        head.pack(fill="x")
        head.pack_propagate(False)
        self.title = tk.Label(head, bg="#24272a", fg=COL["fg"], font=("Segoe UI", 21, "bold"))
        self.title.pack(anchor="w", padx=24, pady=(13, 0))
        tk.Label(head, text="Windows • TeamSpeak externe client • USB audio test", bg="#24272a", fg=COL["accent"]).pack(anchor="w", padx=26)
        outer = tk.Frame(main, bg=COL["bg"])
        outer.pack(fill="both", expand=True)
        cv = tk.Canvas(outer, bg=COL["bg"], highlightthickness=0)
        scr = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        scr.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        cv.configure(yscrollcommand=scr.set)
        holder = tk.Frame(cv, bg=COL["bg"])
        win = cv.create_window((0, 0), anchor="nw", window=holder)
        holder.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        for name in self.buttons:
            self.pages[name] = tk.Frame(holder, bg=COL["bg"])
        self.overview()
        self.teamspeak()
        self.audio()
        self.vox_page()
        self.mode_page()
        self.system()

    def card(self, name, title):
        x = tk.Frame(self.pages[name], bg=COL["card"], padx=20, pady=16, highlightthickness=1, highlightbackground="#66503c")
        x.pack(fill="x", padx=20, pady=(15, 0))
        tk.Label(x, text=title, bg=COL["card"], fg=COL["accent"], font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 12))
        return x

    def label(self, parent, text):
        tk.Label(parent, text=text, bg=COL["card"], fg=COL["sub"], justify="left", wraplength=690).pack(anchor="w", pady=7)

    def entry(self, box, title, key):
        r = tk.Frame(box, bg=COL["card"])
        r.pack(fill="x", pady=5)
        tk.Label(r, text=title, width=19, anchor="w", bg=COL["card"], fg=COL["fg"]).pack(side="left")
        ttk.Entry(r, textvariable=self.v[key]).pack(side="left", fill="x", expand=True)

    def slider(self, box, title, key, lo, hi):
        r = tk.Frame(box, bg=COL["card"])
        r.pack(fill="x", pady=5)
        tk.Label(r, text=title, width=22, anchor="w", bg=COL["card"], fg=COL["fg"]).pack(side="left")
        s = tk.Scale(r, from_=lo, to=hi, orient="horizontal", resolution=1, bg=COL["card"], fg=COL["fg"], troughcolor="#ad6128", highlightthickness=0, command=lambda val, k=key: self.v[k].set(str(int(float(val)))))
        s.set(int(float(self.v[key].get())))
        s.pack(side="left", fill="x", expand=True)

    def overview(self):
        b = self.card("Overzicht", "Live audio-ingang en VOX")
        self.meter = ttk.Progressbar(b, maximum=100, style="Bar.Horizontal.TProgressbar")
        self.meter.pack(fill="x", pady=10)
        self.meter_label = tk.Label(b, text="Niveau: 0% | VOX: uit", bg=COL["card"], fg=COL["ok"], font=("Segoe UI", 12, "bold"))
        self.meter_label.pack(anchor="w")
        self.monitor_btn = ttk.Button(b, text="Start audiotest", style="Copper.TButton", command=self.toggle_monitor)
        self.monitor_btn.pack(anchor="w", pady=14)
        self.label(b, "De meter en VOX zijn een lokale test: er wordt niets naar TeamSpeak gestuurd.")
        c = self.card("Overzicht", "Status")
        self.label(c, "TeamSpeak-spraak loopt via de afzonderlijk geïnstalleerde TeamSpeak-client.")
        self.label(c, "Een zelfstandige TeamSpeak-audiobrug moet nog worden ontwikkeld.")

    def teamspeak(self):
        b = self.card("TeamSpeak", "Handmatig verbinden met TeamSpeak")
        ttk.Combobox(b, textvariable=self.v["server"], values=list(SERVERS), state="readonly").pack(fill="x", pady=7)
        self.entry(b, "Gebruikersnaam", "nickname")
        self.entry(b, "Kanaalnaam (optioneel)", "channel")
        self.entry(b, "Spraakpoort", "port")
        ttk.Button(b, text="Verbinden via TeamSpeak", style="Copper.TButton", command=self.connect).pack(anchor="w", pady=12)
        self.ts_label = tk.Label(b, text="TeamSpeak niet vanuit deze app geopend", bg=COL["card"], fg=COL["accent"], wraplength=670)
        self.ts_label.pack(anchor="w")
        self.label(b, "Gebruik in TeamSpeak zelf de juiste opname- en afspeelapparaten en de ingebouwde spraakactivatie.")
        self.label(b, "Er is nog geen rechtstreekse audioverbinding met onze app.")

    def audio(self):
        b = self.card("Audioapparaten", "Windows / USB-geluidskaart")
        for title, key, attr in (("Audio-ingang", "input", "combo_in"), ("Audio-uitgang", "output", "combo_out")):
            r = tk.Frame(b, bg=COL["card"])
            r.pack(fill="x", pady=6)
            tk.Label(r, text=title, width=19, anchor="w", bg=COL["card"], fg=COL["fg"]).pack(side="left")
            cb = ttk.Combobox(r, textvariable=self.v[key], state="readonly")
            cb.pack(side="left", fill="x", expand=True)
            setattr(self, attr, cb)
        ttk.Button(b, text="Geluidskaarten vernieuwen", command=self.refresh_devices).pack(anchor="w", pady=12)
        self.slider(b, "Meetversterking (%)", "gain", 0, 200)
        ttk.Button(b, text="Testtoon via gekozen uitgang", style="Copper.TButton", command=self.start_tone).pack(anchor="w", pady=10)
        self.label(b, "Let op: de meetversterking regelt alleen de meter/VOX-test; niet het Windows-opnameniveau of TeamSpeak-volume.")
        self.label(b, "De testtoon speelt kort af via de geselecteerde audio-uitgang. Zet het volume laag als een radiozender is aangesloten.")

    def vox_page(self):
        b = self.card("VOX-instellingen", "VOX-test")
        for title, key, lo, hi in (("VOX-drempel (%)", "threshold", 1, 100), ("Triggertijd (ms)", "attack", 0, 2000), ("Afvaltijd (ms)", "release", 100, 5000)):
            self.slider(b, title, key, lo, hi)
        self.label(b, "Deze VOX bestuurt nog niet de microfoon van TeamSpeak. Stel daarvoor momenteel ook Voice Activation Detection in TeamSpeak in.")

    def mode_page(self):
        b = self.card("Radiomodus", "Modus opslaan (nog geen audiobrug)")
        for label, value in (("RX — ontvanger", "RX"), ("TX — zender", "TX"), ("RX/TX — gateway", "RX/TX")):
            tk.Radiobutton(b, text=label, value=value, variable=self.v["mode"], bg=COL["card"], fg=COL["fg"], selectcolor="#765030", activebackground=COL["card"], activeforeground=COL["fg"]).pack(anchor="w", pady=7)
        self.label(b, "De gekozen modus wordt bewaard, maar stuurt in deze versie nog geen spraak naar of van TeamSpeak.")

    def system(self):
        b = self.card("Systeem", "Instellingen")
        self.label(b, "Instellingenbestand: " + str(PATH))
        ttk.Button(b, text="Instellingen opslaan", style="Copper.TButton", command=self.save).pack(anchor="w", pady=10)
        self.label(b, "TeamSpeak opent extern. USB-audio en VOX-test werken lokaal.")

    def page(self, name):
        for p in self.pages.values():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.title.config(text=name)
        for n, btn in self.buttons.items():
            btn.config(bg="#885022" if n == name else COL["side"])

    def refresh_devices(self):
        try:
            found = sd.query_devices()
            self.devices_in = {f"{i}: {d['name']}": i for i, d in enumerate(found) if d["max_input_channels"] > 0}
            self.devices_out = {f"{i}: {d['name']}": i for i, d in enumerate(found) if d["max_output_channels"] > 0}
            for key, combo, items in (("input", self.combo_in, self.devices_in), ("output", self.combo_out, self.devices_out)):
                combo["values"] = list(items)
                if self.v[key].get() not in items and items:
                    self.v[key].set(next(iter(items)))
        except Exception as exc:
            messagebox.showerror("Audioapparaten", str(exc))

    def connect(self):
        choice = self.v["server"].get()
        try:
            port = int(self.v["port"].get())
            if choice not in SERVERS or not 1 <= port <= 65535:
                raise ValueError("Ongeldige serverkeuze of poort")
            nick = self.v["nickname"].get().strip()
            if len(nick) < 3:
                raise ValueError("Gebruikersnaam moet minimaal 3 tekens hebben")
            params = {"port": port, "nickname": nick}
            if self.v["channel"].get().strip():
                params["channel"] = self.v["channel"].get().strip()
            uri = "ts3server://" + SERVERS[choice] + "?" + urlencode(params)
            os.startfile(uri)
            self.ts_label.config(text="Openverzoek verstuurd. Controleer de verbinding in TeamSpeak.")
        except Exception as exc:
            messagebox.showerror("TeamSpeak", str(exc))

    def toggle_monitor(self):
        if self.stream is not None:
            self.stop_monitor()
            return
        key = self.v["input"].get()
        if key not in self.devices_in:
            messagebox.showerror("Audio", "Selecteer eerst een geldige audio-ingang")
            return
        try:
            self.stream = sd.InputStream(device=self.devices_in[key], channels=1, samplerate=16000, blocksize=320, callback=self.audio_cb, dtype="float32")
            self.stream.start()
            self.monitor_btn.config(text="Stop audiotest")
        except Exception as exc:
            if self.stream is not None:
                self.stream.close()
            self.stream = None
            messagebox.showerror("Audio", str(exc))

    def audio_cb(self, data, frames, time_info, status):
        try:
            rms = float(np.sqrt(np.mean(data[:, 0] ** 2)))
            self.events.put_nowait((rms, frames * 1000 / 16000))
        except queue.Full:
            pass

    def stop_monitor(self):
        stream, self.stream = self.stream, None
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self.level = self.peak = 0
        self.vox = False
        self.high_ms = self.low_ms = 0
        self.monitor_btn.config(text="Start audiotest")
        while not self.events.empty():
            try:
                self.events.get_nowait()
            except queue.Empty:
                break

    def start_tone(self):
        if self.tone_running:
            return
        key = self.v["output"].get()
        if key not in self.devices_out:
            messagebox.showwarning("Audio", "Selecteer eerst een audio-uitgang")
            return
        if not messagebox.askyesno("Testtoon", "Speel een korte, zachte testtoon af op de gekozen uitgang?\n\nKoppel eerst eventuele zendapparatuur los of schakel zenden uit."):
            return
        self.tone_running = True
        idx = self.devices_out[key]

        def work():
            try:
                sr = 44100
                t = np.arange(int(sr * .3), dtype=np.float32) / sr
                edge = np.minimum(1, np.minimum(np.arange(t.size), np.arange(t.size)[::-1]) / (sr * .025))
                tone = (.06 * np.sin(2 * np.pi * 700 * t) * edge).astype(np.float32)
                sd.play(tone, samplerate=sr, device=idx, blocking=True)
            except Exception as exc:
                if not self.closed:
                    self.root.after(0, lambda m=str(exc): messagebox.showerror("Testtoon", m))
            finally:
                self.tone_running = False
        threading.Thread(target=work, daemon=True).start()

    def tick(self):
        if self.closed:
            return
        try:
            while True:
                rms, ms = self.events.get_nowait()
                gain = float(self.v["gain"].get()) / 100
                self.level = min(100, rms * gain * 100)
                if self.level >= float(self.v["threshold"].get()):
                    self.high_ms += ms
                    self.low_ms = 0
                    if self.high_ms >= float(self.v["attack"].get()):
                        self.vox = True
                else:
                    self.low_ms += ms
                    self.high_ms = 0
                    if self.low_ms >= float(self.v["release"].get()):
                        self.vox = False
        except queue.Empty:
            pass
        self.meter["value"] = self.level
        self.meter_label.config(text=f"Niveau: {self.level:.1f}% | VOX: {'ACTIEF' if self.vox else 'uit'}")
        self.root.after(70, self.tick)

    def save(self):
        try:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps({k: v.get() for k, v in self.v.items()}, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(PATH)
            messagebox.showinfo("Opgeslagen", "Instellingen bewaard")
        except Exception as exc:
            messagebox.showerror("Fout", str(exc))

    def close(self):
        self.closed = True
        self.stop_monitor()
        try:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            PATH.write_text(json.dumps({k: v.get() for k, v in self.v.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    GUI(root)
    root.mainloop()
