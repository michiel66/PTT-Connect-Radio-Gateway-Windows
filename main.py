
"""PTT Connect Radio Gateway — Windows Copper Edition.

TeamSpeak-verbindingstest via geïnstalleerde TeamSpeak-client.
De lokale audiometer en VOX zijn nog niet gekoppeld aan TeamSpeak.
"""

import json
import os
import math
import queue
import tkinter as tk

from pathlib import Path
from tkinter import ttk, messagebox
from urllib.parse import urlencode

try:
    import sounddevice as sd
except ImportError:
    sd = None


APP = "PTT Connect Radio Gateway"

BG = "#17191c"
SIDE = "#111315"
PANEL = "#262a2e"
COPPER = "#da812f"
TEXT = "#f6f1e9"
SUB = "#b5aea5"
GREEN = "#53cb85"

SERVERS = {
    "TG-103 Voorburg": "ptt.mijnts3.nl",
    "TG-108 Heerlen": "heerlen.mijnts3.nl"
}

SETTINGS = (
    Path(os.getenv("APPDATA") or Path.home())
    / "PTTConnectRadioGateway"
    / "settings.json"
)

DEFAULT = {
    "server": "TG-103 Voorburg",
    "nickname": "Radio Gateway",
    "channel": "",
    "voice_port": 9987,
    "input_device": "",
    "output_device": "",
    "gain": 100,
    "threshold": 12,
    "attack_ms": 150,
    "release_ms": 950,
    "mode": "RX/TX"
}


def load():
    try:
        saved = json.loads(
            SETTINGS.read_text(encoding="utf8")
        )

        return {
            **DEFAULT,
            **{
                k: v
                for k, v in saved.items()
                if k in DEFAULT
            }
        }

    except (OSError, ValueError, TypeError):
        return DEFAULT.copy()


class App:

    def __init__(self, root):
        self.root = root

        self.root.title(
            APP + " — Copper Edition"
        )

        self.root.geometry("1070x735")
        self.root.minsize(900, 600)
        self.root.configure(bg=BG)

        self.vars = {
            k: tk.StringVar(value=str(v))
            for k, v in load().items()
        }

        self.pages = {}
        self.nav = {}

        self.inputs = {}
        self.outputs = {}

        self.stream = None
        self.audio_q = queue.Queue(maxsize=15)

        self.level = 0.0
        self.vox = False
        self.above = 0
        self.below = 0
        self.closed = False

        self._style()
        self._layout()
        self.refresh_devices()

        self.show("Overzicht")

        self.root.after(70, self.tick)

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.close
        )

    # ======================================
    # STIJL
    # ======================================

    def _style(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")

        st.configure(
            "TButton",
            padding=(12, 8),
            font=("Segoe UI", 10, "bold")
        )

        st.configure(
            "Copper.TButton",
            foreground="white",
            background="#b96522"
        )

        st.map(
            "Copper.TButton",
            background=[("active", COPPER)]
        )

        st.configure(
            "TEntry",
            padding=6,
            fieldbackground="#faf7f0"
        )

        st.configure(
            "TCombobox",
            padding=6
        )

        st.configure(
            "Copper.Horizontal.TProgressbar",
            background=GREEN,
            troughcolor="#49382a"
        )

    # ======================================
    # HOOFDVENSTER
    # ======================================

    def _layout(self):
        side = tk.Frame(
            self.root,
            bg=SIDE,
            width=225
        )

        side.pack(
            side="left",
            fill="y"
        )

        side.pack_propagate(False)

        tk.Label(
            side,
            text="◉ PTT Connect",
            bg=SIDE,
            fg=TEXT,
            font=("Segoe UI", 18, "bold")
        ).pack(
            anchor="w",
            padx=16,
            pady=(24, 0)
        )

        tk.Label(
            side,
            text="RADIO GATEWAY",
            bg=SIDE,
            fg="#ffb347",
            font=("Segoe UI", 10, "bold")
        ).pack(
            anchor="w",
            padx=20,
            pady=(0, 28)
        )

        menu_items = [
            "Overzicht",
            "TeamSpeak",
            "Audioapparaten",
            "VOX-instellingen",
            "Radiomodus",
            "Systeem"
        ]

        for name in menu_items:
            btn = tk.Button(
                side,
                text="  " + name,
                bg=SIDE,
                fg=TEXT,
                bd=0,
                padx=13,
                pady=13,
                anchor="w",
                font=("Segoe UI", 11),
                activebackground="#885022",
                activeforeground="white",
                command=lambda n=name: self.show(n)
            )

            btn.pack(
                fill="x",
                padx=8,
                pady=3
            )

            self.nav[name] = btn

        right = tk.Frame(
            self.root,
            bg=BG
        )

        right.pack(
            fill="both",
            expand=True
        )

        header = tk.Frame(
            right,
            bg="#24272a",
            height=85
        )

        header.pack(fill="x")
        header.pack_propagate(False)

        self.heading = tk.Label(
            header,
            bg="#24272a",
            fg=TEXT,
            font=("Segoe UI", 21, "bold")
        )

        self.heading.pack(
            anchor="w",
            padx=24,
            pady=(15, 0)
        )

        tk.Label(
            header,
            text=(
                "Windows • TeamSpeak-verbindingstest "
                "• Copper Edition"
            ),
            bg="#24272a",
            fg="#ffc47d"
        ).pack(
            anchor="w",
            padx=26
        )

        wrapper = tk.Frame(
            right,
            bg=BG
        )

        wrapper.pack(
            fill="both",
            expand=True
        )

        canvas = tk.Canvas(
            wrapper,
            bg=BG,
            highlightthickness=0
        )

        scroll = ttk.Scrollbar(
            wrapper,
            orient="vertical",
            command=canvas.yview
        )

        canvas.configure(
            yscrollcommand=scroll.set
        )

        scroll.pack(
            side="right",
            fill="y"
        )

        canvas.pack(
            side="left",
            fill="both",
            expand=True
        )

        body = tk.Frame(
            canvas,
            bg=BG
        )

        window = canvas.create_window(
            (0, 0),
            anchor="nw",
            window=body
        )

        body.bind(
            "<Configure>",
            lambda _: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(
                window,
                width=e.width
            )
        )

        for name in self.nav:
            self.pages[name] = tk.Frame(
                body,
                bg=BG
            )

        self.overview()
        self.teamspeak()
        self.audio()
        self.vox_page()
        self.mode_page()
        self.system()

    # ======================================
    # ALGEMENE COMPONENTEN
    # ======================================

    def card(self, page, title):
        frame = tk.Frame(
            page,
            bg=PANEL,
            highlightthickness=1,
            highlightbackground="#76512f",
            padx=20,
            pady=18
        )

        frame.pack(
            fill="x",
            padx=20,
            pady=(16, 0)
        )

        tk.Label(
            frame,
            text=title,
            bg=PANEL,
            fg="#ffb347",
            font=("Segoe UI", 14, "bold")
        ).pack(
            anchor="w",
            pady=(0, 12)
        )

        return frame

    def note(self, page, txt, color=SUB):
        tk.Label(
            page,
            text=txt,
            bg=PANEL,
            fg=color,
            font=("Segoe UI", 10),
            justify="left",
            wraplength=690
        ).pack(
            anchor="w",
            pady=7
        )

    def entry(self, page, label, key):
        line = tk.Frame(
            page,
            bg=PANEL
        )

        line.pack(
            fill="x",
            pady=6
        )

        tk.Label(
            line,
            text=label,
            bg=PANEL,
            fg=TEXT,
            width=19,
            anchor="w"
        ).pack(side="left")

        ttk.Entry(
            line,
            textvariable=self.vars[key]
        ).pack(
            side="left",
            fill="x",
            expand=True
        )

    def slider(self, parent, title, key, low, high):
        line = tk.Frame(
            parent,
            bg=PANEL
        )

        line.pack(
            fill="x",
            pady=5
        )

        tk.Label(
            line,
            text=title,
            bg=PANEL,
            fg=TEXT,
            width=22,
            anchor="w"
        ).pack(side="left")

        scale = tk.Scale(
            line,
            from_=low,
            to=high,
            orient="horizontal",
            length=300,
            bg=PANEL,
            fg=TEXT,
            troughcolor="#b96522",
            highlightthickness=0,
            command=lambda value, k=key:
                self.vars[k].set(str(int(float(value))))
        )

        scale.set(
            int(self.vars[key].get())
        )

        scale.pack(
            side="left",
            fill="x",
            expand=True
        )

    # ======================================
    # OVERZICHT
    # ======================================

    def overview(self):
        box = self.card(
            self.pages["Overzicht"],
            "Live audio — ingangstest"
        )

        self.meter = ttk.Progressbar(
            box,
            style="Copper.Horizontal.TProgressbar",
            maximum=100
        )

        self.meter.pack(
            fill="x",
            pady=10
        )

        self.level_label = tk.Label(
            box,
            text="Niveau: 0,0% | VOX: uit",
            bg=PANEL,
            fg=GREEN,
            font=("Segoe UI", 12, "bold")
        )

        self.level_label.pack(anchor="w")

        self.test_button = ttk.Button(
            box,
            text="Start audiotest",
            style="Copper.TButton",
            command=self.toggle_audio
        )

        self.test_button.pack(
            anchor="w",
            pady=12
        )

        self.note(
            box,
            "De audiometer en VOX zijn lokaal. "
            "Dit is nog geen zelfstandige TeamSpeak-gateway."
        )

        status = self.card(
            self.pages["Overzicht"],
            "Verbindingsstatus"
        )

        self.note(
            status,
            "TeamSpeak kan worden geopend met de "
            "geïnstalleerde TeamSpeak-client."
        )

        self.note(
            status,
            "Een zelfstandige TeamSpeak-audioconnector "
            "bouwen we in een volgende stap."
        )

    # ======================================
    # TEAMSPEAK
    # ======================================

    def teamspeak(self):
        box = self.card(
            self.pages["TeamSpeak"],
            "TeamSpeak 3 — Handmatig verbinden"
        )

        self.note(
            box,
            "Kies TG-103 Voorburg of TG-108 Heerlen."
        )

        ttk.Combobox(
            box,
            textvariable=self.vars["server"],
            values=list(SERVERS),
            state="readonly"
        ).pack(
            fill="x",
            pady=8
        )

        self.entry(
            box,
            "Gebruikersnaam",
            "nickname"
        )

        self.entry(
            box,
            "Kanaalnaam (optioneel)",
            "channel"
        )

        self.entry(
            box,
            "Spraakpoort",
            "voice_port"
        )

        self.note(
            box,
            "Vul eventueel de exacte kanaalnaam in. "
            "Een beveiligd kanaal kan een wachtwoord vragen."
        )

        row = tk.Frame(
            box,
            bg=PANEL
        )

        row.pack(
            anchor="w",
            pady=12
        )

        ttk.Button(
            row,
            text="Verbinden via TeamSpeak",
            style="Copper.TButton",
            command=self.connect
        ).pack(
            side="left",
            padx=(0, 8)
        )

        ttk.Button(
            row,
            text="Instellingen bewaren",
            command=self.save
        ).pack(side="left")

        self.ts_status = tk.Label(
            box,
            text="Nog niet gestart",
            bg=PANEL,
            fg="#ffb347",
            justify="left",
            wraplength=680
        )

        self.ts_status.pack(
            anchor="w",
            pady=8
        )

        self.note(
            box,
            "Dit opent de geïnstalleerde TeamSpeak-app "
            "op Windows. Verbreken doe je voorlopig "
            "in TeamSpeak zelf.",
            "#ffb347"
        )

    # ======================================
    # AUDIOAPPARATEN
    # ======================================

    def audio(self):
        box = self.card(
            self.pages["Audioapparaten"],
            "Interne of USB-geluidskaart"
        )

        audio_options = [
            (
                "Audio-ingang",
                "input_device",
                "in_combo"
            ),
            (
                "Audio-uitgang",
                "output_device",
                "out_combo"
            )
        ]

        for title, key, prop in audio_options:
            line = tk.Frame(
                box,
                bg=PANEL
            )

            line.pack(
                fill="x",
                pady=8
            )

            tk.Label(
                line,
                text=title,
                bg=PANEL,
                fg=TEXT,
                width=19,
                anchor="w"
            ).pack(side="left")

            combo = ttk.Combobox(
                line,
                textvariable=self.vars[key],
                state="readonly"
            )

            combo.pack(
                side="left",
                fill="x",
                expand=True
            )

            setattr(
                self,
                prop,
                combo
            )

        ttk.Button(
            box,
            text="Geluidskaarten vernieuwen",
            command=self.refresh_devices
        ).pack(
            anchor="w",
            pady=8
        )

        self.slider(
            box,
            "Meetversterking (%)",
            "gain",
            0,
            200
        )

        self.note(
            box,
            "De gekozen ingang werkt voor de lokale "
            "audiotest. TeamSpeak gebruikt voorlopig "
            "zijn eigen geluidsinstellingen."
        )

        ttk.Button(
            box,
            text="Instellingen bewaren",
            command=self.save
        ).pack(
            anchor="w",
            pady=10
        )

    # ======================================
    # VOX-INSTELLINGEN
    # ======================================

    def vox_page(self):
        box = self.card(
            self.pages["VOX-instellingen"],
            "VOX — testinstellingen"
        )

        sliders = [
            (
                "VOX-drempel (%)",
                "threshold",
                1,
                100
            ),
            (
                "Triggertijd (ms)",
                "attack_ms",
                0,
                2000
            ),
            (
                "Afvaltijd (ms)",
                "release_ms",
                100,
                5000
            )
        ]

        for title, key, low, high in sliders:
            self.slider(
                box,
                title,
                key,
                low,
                high
            )

        self.note(
            box,
            "De VOX is voorlopig een lokale test. "
            "Deze schakelt de TeamSpeak-microfoon "
            "nog niet in of uit."
        )

        ttk.Button(
            box,
            text="Instellingen bewaren",
            command=self.save
        ).pack(
            anchor="w",
            pady=10
        )

    # ======================================
    # RADIOMODUS
    # ======================================

    def mode_page(self):
        box = self.card(
            self.pages["Radiomodus"],
            "RX / TX / RX-TX"
        )

        modes = [
            (
                "RX — alleen ontvanger",
                "RX"
            ),
            (
                "TX — alleen zender",
                "TX"
            ),
            (
                "RX/TX — gateway",
                "RX/TX"
            )
        ]

        for label, value in modes:
            tk.Radiobutton(
                box,
                text=label,
                value=value,
                variable=self.vars["mode"],
                bg=PANEL,
                fg=TEXT,
                activebackground=PANEL,
                activeforeground=TEXT,
                selectcolor="#654125",
                font=("Segoe UI", 11)
            ).pack(
                anchor="w",
                pady=8
            )

        self.note(
            box,
            "De gekozen radiomodus wordt opgeslagen. "
            "Het daadwerkelijke routeren van radio-audio "
            "wordt later aangesloten."
        )

        ttk.Button(
            box,
            text="Instellingen bewaren",
            command=self.save
        ).pack(
            anchor="w",
            pady=10
        )

    # ======================================
    # SYSTEEM
    # ======================================

    def system(self):
        box = self.card(
            self.pages["Systeem"],
            "Programma-informatie"
        )

        self.note(
            box,
            "PTT Connect Radio Gateway — "
            "Windows Copper Edition"
        )

        self.note(
            box,
            "TeamSpeak-linktest: opent de "
            "geïnstalleerde TeamSpeak-client."
        )

        self.note(
            box,
            "Lokale testfuncties: "
            "audio-ingang, audiometer en VOX."
        )

        self.note(
            box,
            "Instellingenbestand: " + str(SETTINGS)
        )

        ttk.Button(
            box,
            text="Alles opslaan",
            style="Copper.TButton",
            command=self.save
        ).pack(
            anchor="w",
            pady=10
        )

    # ======================================
    # LINKERMENU
    # ======================================

    def show(self, name):
        for page in self.pages.values():
            page.pack_forget()

        self.pages[name].pack(
            fill="both",
            expand=True
        )

        self.heading.config(
            text=name
        )

        for n, btn in self.nav.items():
            btn.config(
                bg="#885022" if n == name else SIDE
            )

    # ======================================
    # INSTELLINGEN OPSLAAN
    # ======================================

    def save(self):
        try:
            SETTINGS.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            SETTINGS.write_text(
                json.dumps(
                    {
                        k: v.get()
                        for k, v in self.vars.items()
                    },
                    ensure_ascii=False,
                    indent=2
                ),
                encoding="utf8"
            )

            messagebox.showinfo(
                "Opgeslagen",
                "Instellingen zijn opgeslagen."
            )

        except Exception as exc:
            messagebox.showerror(
                "Opslaan mislukt",
                str(exc)
            )

    # ======================================
    # TEAMSPEAK OPENEN
    # ======================================

    def connect(self):
        server_name = self.vars["server"].get()

        host = SERVERS.get(server_name)

        if not host:
            messagebox.showerror(
                "TeamSpeak",
                "Selecteer eerst een TeamSpeak-server."
            )
            return

        try:
            port = int(
                self.vars["voice_port"].get()
            )

            if not 1 <= port <= 65535:
                raise ValueError()

        except ValueError:
            messagebox.showerror(
                "TeamSpeak",
                "Vul een geldige spraakpoort in."
            )
            return

        nickname = (
            self.vars["nickname"].get().strip()
        )

        if len(nickname) < 3:
            messagebox.showerror(
                "TeamSpeak",
                "Gebruikersnaam moet minimaal "
                "3 tekens bevatten."
            )
            return

        params = {
            "port": port,
            "nickname": nickname
        }

        channel = (
            self.vars["channel"].get().strip()
        )

        if channel:
            params["channel"] = channel

        uri = (
            "ts3server://"
            + host
            + "?"
            + urlencode(params)
        )

        try:
            os.startfile(uri)

        except (OSError, AttributeError) as exc:
            messagebox.showerror(
                "TeamSpeak",
                "Kan TeamSpeak niet openen.\n\n"
                "Controleer of TeamSpeak 3 is "
                "geïnstalleerd en of ts3server-links "
                "zijn geregistreerd.\n\n"
                + str(exc)
            )
            return

        self.ts_status.config(
            text=(
                "TeamSpeak-openverzoek verstuurd voor "
                + server_name
                + ". Controleer in TeamSpeak "
                  "of je verbonden bent."
            )
        )

    # ======================================
    # GELUIDSKAARTEN
    # ======================================

    def refresh_devices(self):
        if sd is None:
            return

        try:
            devices = sd.query_devices()

            self.inputs = {
                f'{i}: {d["name"]}': i
                for i, d in enumerate(devices)
                if d["max_input_channels"] > 0
            }

            self.outputs = {
                f'{i}: {d["name"]}': i
                for i, d in enumerate(devices)
                if d["max_output_channels"] > 0
            }

            options = [
                (
                    "input_device",
                    self.in_combo,
                    self.inputs
                ),
                (
                    "output_device",
                    self.out_combo,
                    self.outputs
                )
            ]

            for key, combo, mapping in options:
                combo["values"] = list(mapping)

                if (
                    self.vars[key].get() not in mapping
                    and mapping
                ):
                    self.vars[key].set(
                        next(iter(mapping))
                    )

        except Exception as exc:
            messagebox.showerror(
                "Audio",
                str(exc)
            )

    # ======================================
    # AUDIO TEST
    # ======================================

    def toggle_audio(self):
        if self.stream is not None:
            self.stop_audio()
            return

        name = (
            self.vars["input_device"].get()
        )

        if sd is None or name not in self.inputs:
            messagebox.showerror(
                "Audio",
                "Kies eerst een werkende audio-ingang."
            )
            return

        try:
            self.stream = sd.InputStream(
                device=self.inputs[name],
                channels=1,
                samplerate=16000,
                blocksize=320,
                dtype="float32",
                callback=self.on_audio
            )

            self.stream.start()

            self.test_button.config(
                text="Stop audiotest"
            )

        except Exception as exc:
            if self.stream is not None:
                try:
                    self.stream.close()
                except Exception:
                    pass

            self.stream = None

            messagebox.showerror(
                "Audio",
                str(exc)
            )

    def on_audio(
        self,
        frames,
        count,
        time_info,
        status
    ):
        try:
            rms = math.sqrt(
                sum(
                    float(s[0]) ** 2
                    for s in frames
                ) / max(count, 1)
            )

            self.audio_q.put_nowait(
                (
                    rms,
                    count * 1000.0 / 16000
                )
            )

        except queue.Full:
            pass

    # ======================================
    # AUDIOMETER EN VOX
    # ======================================

    def tick(self):
        if self.closed:
            return

        try:
            while True:
                rms, ms = (
                    self.audio_q.get_nowait()
                )

                self.level = min(
                    100.0,
                    rms * float(
                        self.vars["gain"].get()
                    )
                )

                if self.level >= float(
                    self.vars["threshold"].get()
                ):
                    self.above += ms
                    self.below = 0

                    if self.above >= float(
                        self.vars["attack_ms"].get()
                    ):
                        self.vox = True

                else:
                    self.below += ms
                    self.above = 0

                    if self.below >= float(
                        self.vars["release_ms"].get()
                    ):
                        self.vox = False

        except queue.Empty:
            pass

        self.meter["value"] = self.level

        self.level_label.config(
            text=(
                f"Niveau: {self.level:.1f}% | "
                f'VOX: {"ACTIEF" if self.vox else "uit"}'
            )
        )

        self.root.after(
            70,
            self.tick
        )

    # ======================================
    # AUDIO STOPPEN
    # ======================================

    def stop_audio(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()

            finally:
                self.stream = None

        self.level = 0.0
        self.above = 0
        self.below = 0
        self.vox = False

        self.test_button.config(
            text="Start audiotest"
        )

        while True:
            try:
                self.audio_q.get_nowait()

            except queue.Empty:
                break

    # ======================================
    # AFSLUITEN
    # ======================================

    def close(self):
        self.closed = True

        self.stop_audio()

        try:
            SETTINGS.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            SETTINGS.write_text(
                json.dumps(
                    {
                        k: v.get()
                        for k, v in self.vars.items()
                    },
                    ensure_ascii=False,
                    indent=2
                ),
                encoding="utf8"
            )

        except Exception:
            pass

        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
