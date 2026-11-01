
"""PTT Connect Radio Gateway - Windows desktop testversie.

Werkt: desktopinterface, geluidskaartkeuze, audiometer en VOX-test.
Nog niet ingebouwd: TeamSpeak-spraakverbinding, SDR en crosslink.
"""

import json
import math
import os
from pathlib import Path
import queue
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import sounddevice as sd
except ImportError:
    sd = None


APP_NAME = "PTT Connect Radio Gateway"
CONFIG_DIR = Path(
    os.getenv("APPDATA") or (Path.home() / ".config")
) / "PTTConnectRadioGateway"
CONFIG_FILE = CONFIG_DIR / "settings.json"

DEFAULTS = {
    "server": "ptt.mijnts3.nl",
    "nickname": "Radio Gateway",
    "channel": "",
    "input_device": "",
    "output_device": "",
    "gain": 100,
    "threshold": 12,
    "attack_ms": 150,
    "release_ms": 950,
    "mode": "RX/TX",
    "vox_enabled": True,
}


def load_config():
    config = dict(DEFAULTS)
    try:
        saved = json.loads(
            CONFIG_FILE.read_text(encoding="utf-8")
        )
        if isinstance(saved, dict):
            config.update({
                k: v for k, v in saved.items()
                if k in DEFAULTS
            })
    except (OSError, ValueError, TypeError):
        pass
    return config


def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temp.replace(CONFIG_FILE)


def compute_vox(
    level, threshold, above_ms, below_ms,
    active, attack, release, frame_ms
):
    if level >= threshold:
        above_ms += frame_ms
        below_ms = 0
        if above_ms >= attack:
            active = True
    else:
        below_ms += frame_ms
        above_ms = 0
        if below_ms >= release:
            active = False
    return active, above_ms, below_ms


class GatewayApp:

    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME + " - Windows")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)
        self.root.configure(bg="#06152b")

        self.cfg = load_config()

        self.vars = {
            k: tk.StringVar(value=str(v))
            for k, v in self.cfg.items()
            if k != "vox_enabled"
        }

        self.vox_enabled = tk.BooleanVar(
            value=bool(self.cfg["vox_enabled"])
        )

        self.stream = None
        self.monitoring = False
        self.events = queue.Queue(maxsize=10)
        self.level = 0.0
        self.gain_value = float(self.cfg["gain"]) / 100.0
        self.vox_on = False
        self.above_ms = 0
        self.below_ms = 0

        self.device_names = {}
        self.output_names = {}

        self._build()
        self.refresh_devices()

        self.root.after(70, self.update_meter)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self):
        NAVY = "#06152b"
        PANEL = "#0b2747"
        CYAN = "#12c8ff"
        WHITE = "#eaf7ff"
        MUTED = "#a9c9df"

        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(
            "Dark.TCheckbutton",
            background=PANEL,
            foreground=WHITE
        )
        style.map(
            "Dark.TCheckbutton",
            background=[("active", PANEL)],
            foreground=[("active", WHITE)]
        )

        style.configure(
            "TEntry",
            fieldbackground="#f1faff",
            padding=5
        )
        style.configure("TCombobox", padding=5)

        style.configure(
            "TButton",
            padding=(11, 8),
            font=("Segoe UI Semibold", 10)
        )
        style.configure(
            "Blue.TButton",
            background="#086ddd",
            foreground="white"
        )
        style.map(
            "Blue.TButton",
            background=[("active", "#129fe8")]
        )

        style.configure(
            "Meter.Horizontal.TProgressbar",
            background="#19da6f",
            troughcolor="#143c60",
            borderwidth=0
        )

        shell = tk.Frame(self.root, bg=NAVY)
        shell.pack(fill="both", expand=True)

        # Zijmenu
        side = tk.Frame(
            shell,
            bg="#041329",
            width=218,
            highlightbackground="#065b90",
            highlightthickness=1
        )
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        tk.Label(
            side,
            text="◉  PTT Connect",
            bg="#041329",
            fg=WHITE,
            font=("Segoe UI", 19, "bold")
        ).pack(anchor="w", padx=19, pady=(26, 0))

        tk.Label(
            side,
            text="RADIO GATEWAY",
            bg="#041329",
            fg=CYAN,
            font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", padx=22, pady=(0, 29))

        menu = [
            ("▣   Overzicht", True),
            ("◉   TeamSpeak", False),
            ("◖   Audioapparaten", False),
            ("◉   VOX-instellingen", False),
            ("⚙   Radio modus", False),
            ("◈   Systeem", False),
        ]

        for label, active in menu:
            bg = "#0968bb" if active else "#041329"

            tk.Label(
                side,
                text=label,
                bg=bg,
                fg=WHITE if active else "#b4d4e9",
                anchor="w",
                padx=14,
                pady=12,
                font=(
                    "Segoe UI", 11,
                    "bold" if active else "normal"
                )
            ).pack(fill="x", padx=9, pady=3)

        tk.Label(
            side,
            text="WINDOWS DESKTOP",
            bg="#041329",
            fg="#65b7ed",
            font=("Segoe UI", 10, "bold")
        ).pack(side="bottom", pady=(0, 28))

        right = tk.Frame(shell, bg=NAVY)
        right.pack(side="left", fill="both", expand=True)

        # Bovenbalk
        header = tk.Frame(
            right,
            bg="#092a4e",
            height=86
        )
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="PTT Connect — Radio Gateway",
            bg="#092a4e",
            fg=WHITE,
            font=("Segoe UI", 20, "bold")
        ).pack(anchor="w", padx=20, pady=(12, 0))

        tk.Label(
            header,
            text="Windows  •  Audio Gateway  •  Testversie",
            bg="#092a4e",
            fg="#5bd4ff",
            font=("Segoe UI", 10)
        ).pack(anchor="w", padx=22)

        # Scrollbaar dashboard
        outer = tk.Frame(right, bg=NAVY)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(
            outer,
            bg=NAVY,
            highlightthickness=0,
            bd=0
        )

        scrollbar = ttk.Scrollbar(
            outer,
            orient="vertical",
            command=canvas.yview
        )

        canvas.configure(
            yscrollcommand=scrollbar.set
        )

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        content = tk.Frame(canvas, bg=NAVY)

        window_id = canvas.create_window(
            (0, 0),
            window=content,
            anchor="nw"
        )

        content.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(
                window_id,
                width=e.width
            )
        )

        def card(parent, title, row, col, colspan=1):
            frame = tk.Frame(
                parent,
                bg=PANEL,
                highlightthickness=1,
                highlightbackground="#168dc4",
                padx=14,
                pady=10
            )
            frame.grid(
                row=row,
                column=col,
                columnspan=colspan,
                sticky="nsew",
                padx=8,
                pady=8
            )

            tk.Label(
                frame,
                text=title,
                bg=PANEL,
                fg=CYAN,
                font=("Segoe UI", 12, "bold"),
                anchor="w"
            ).pack(fill="x", pady=(0, 10))

            return frame

        content.columnconfigure(
            0, weight=1, uniform="cards"
        )
        content.columnconfigure(
            1, weight=1, uniform="cards"
        )

        # Systeemstatus
        summary = card(
            content, "◉  Systeemstatus", 0, 0
        )

        statuses = [
            ("Windows", "Desktop test"),
            ("Audiokaart", "Kies hieronder"),
            ("TeamSpeak", "Niet verbonden"),
            ("VOX", "Beschikbaar"),
        ]

        for label, value in statuses:
            line = tk.Frame(summary, bg=PANEL)
            line.pack(fill="x", pady=3)

            tk.Label(
                line,
                text=label,
                bg=PANEL,
                fg=WHITE,
                width=16,
                anchor="w",
                font=("Segoe UI", 10, "bold")
            ).pack(side="left")

            tk.Label(
                line,
                text=value,
                bg=PANEL,
                fg="#42e79c",
                anchor="w"
            ).pack(side="left")

        # Live audio
        status = card(
            content, "▥  Live audio (ingang)", 0, 1
        )

        tk.Label(
            status,
            text="Ingang (Radio → audiotest)",
            bg=PANEL,
            fg=WHITE
        ).pack(anchor="w")

        self.meter = ttk.Progressbar(
            status,
            style="Meter.Horizontal.TProgressbar",
            maximum=100,
            mode="determinate"
        )
        self.meter.pack(fill="x", pady=(9, 8))

        self.level_text = tk.Label(
            status,
            text="Niveau: 0%  |  VOX: uit",
            bg=PANEL,
            fg="#62eac3",
            font=("Segoe UI", 11, "bold")
        )
        self.level_text.pack(anchor="w")

        tk.Label(
            status,
            text=(
                "Alleen lokale audiomonitor; "
                "nog geen TeamSpeak-audio"
            ),
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
            wraplength=340,
            justify="left"
        ).pack(anchor="w", pady=(13, 0))

        # Radio modus
        radio = card(
            content, "◉  Radio modus", 1, 0
        )

        modes = [
            ("Alleen RX (ontvanger)", "RX"),
            ("Alleen TX (zender)", "TX"),
            ("RX/TX (gateway)", "RX/TX"),
        ]

        for label, value in modes:
            tk.Radiobutton(
                radio,
                text=label,
                variable=self.vars["mode"],
                value=value,
                bg=PANEL,
                fg=WHITE,
                selectcolor="#0a5b9d",
                activebackground=PANEL,
                activeforeground=WHITE,
                font=("Segoe UI", 10)
            ).pack(anchor="w", pady=4)

        # VOX
        vox = card(
            content, "◉  VOX — Instellingen", 1, 1
        )

        self.make_slider(
            vox, "VOX-drempel (%)",
            "threshold", 1, 100
        )
        self.make_slider(
            vox, "Triggertijd (ms)",
            "attack_ms", 0, 2000
        )
        self.make_slider(
            vox, "Afvaltijd (ms)",
            "release_ms", 100, 5000
        )

        ttk.Checkbutton(
            vox,
            text="VOX inschakelen",
            variable=self.vox_enabled,
            style="Dark.TCheckbutton"
        ).pack(anchor="w", pady=(8, 2))

        # Audioapparaten
        audio = card(
            content,
            "◖  Audio — apparaten en niveau",
            2, 0, colspan=2
        )

        row = tk.Frame(audio, bg=PANEL)
        row.pack(fill="x", pady=4)

        tk.Label(
            row,
            text="Audio-ingang",
            bg=PANEL,
            fg=WHITE,
            width=17,
            anchor="w"
        ).pack(side="left")

        self.input_combo = ttk.Combobox(
            row,
            textvariable=self.vars["input_device"],
            state="readonly",
            width=58
        )
        self.input_combo.pack(
            side="left",
            fill="x",
            expand=True,
            padx=6
        )

        row = tk.Frame(audio, bg=PANEL)
        row.pack(fill="x", pady=4)

        tk.Label(
            row,
            text="Audio-uitgang",
            bg=PANEL,
            fg=WHITE,
            width=17,
            anchor="w"
        ).pack(side="left")

        self.output_combo = ttk.Combobox(
            row,
            textvariable=self.vars["output_device"],
            state="readonly",
            width=58
        )
        self.output_combo.pack(
            side="left",
            fill="x",
            expand=True,
            padx=6
        )

        ttk.Button(
            row,
            text="Vernieuwen",
            command=self.refresh_devices
        ).pack(side="left", padx=(7, 0))

        self.make_slider(
            audio,
            "Ingangsniveau (%)",
            "gain", 0, 200
        )

        # TeamSpeak-instellingen
        ts = card(
            content,
            "◉  TeamSpeak — Verbinding",
            3, 0, colspan=2
        )

        self.grid_entry(
            ts, "Serveradres", "server"
        )
        self.grid_entry(
            ts, "Gebruikersnaam", "nickname"
        )
        self.grid_entry(
            ts, "Kanaalnaam / ID", "channel"
        )

        bar = tk.Frame(ts, bg=PANEL)
        bar.pack(anchor="w", pady=(12, 3))

        ttk.Button(
            bar,
            text="Verbinden",
            style="Blue.TButton",
            command=self.connect
        ).pack(side="left", padx=(0, 9))

        ttk.Button(
            bar,
            text="Verbreken",
            command=self.disconnect
        ).pack(side="left")

        self.connection_text = tk.Label(
            ts,
            text=(
                "Status: niet verbonden "
                "(spraakclient nog niet ingebouwd)"
            ),
            bg=PANEL,
            fg="#ffc477",
            wraplength=650,
            justify="left"
        )
        self.connection_text.pack(
            anchor="w", pady=(9, 0)
        )

        # Actieknoppen
        actions = tk.Frame(content, bg=NAVY)
        actions.grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=8,
            pady=(10, 12)
        )

        self.monitor_button = ttk.Button(
            actions,
            text="▶  Start audiotest",
            style="Blue.TButton",
            command=self.toggle_monitor
        )
        self.monitor_button.pack(
            side="left", padx=(0, 12)
        )

        ttk.Button(
            actions,
            text="▣  Instellingen opslaan",
            style="Blue.TButton",
            command=self.save
        ).pack(side="left")

        tk.Label(
            content,
            text=(
                "TESTVERSIE — TeamSpeak-spraakverbinding, "
                "SDR en crosslink zijn nog niet aangesloten."
            ),
            bg=NAVY,
            fg="#f2bc7a",
            font=("Segoe UI", 9)
        ).grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="w",
            padx=10,
            pady=(0, 18)
        )

    def grid_entry(self, frame, label, key):
        line = tk.Frame(frame, bg="#0b2747")
        line.pack(fill="x", pady=3)

        tk.Label(
            line,
            text=label,
            bg="#0b2747",
            fg="#eaf7ff",
            width=20,
            anchor="w"
        ).pack(side="left")

        ttk.Entry(
            line,
            textvariable=self.vars[key]
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=8
        )

    def make_slider(
        self, frame, label, key, minimum, maximum
    ):
        line = tk.Frame(frame, bg="#0b2747")
        line.pack(fill="x", pady=3)

        tk.Label(
            line,
            text=label,
            bg="#0b2747",
            fg="#eaf7ff",
            width=22,
            anchor="w"
        ).pack(side="left")

        val = tk.DoubleVar(
            value=float(self.vars[key].get())
        )

        tk.Scale(
            line,
            from_=minimum,
            to=maximum,
            variable=val,
            orient="horizontal",
            length=240,
            resolution=1,
            bg="#0b2747",
            fg="#eaf7ff",
            troughcolor="#0767ac",
            highlightthickness=0,
            activebackground="#12c8ff",
            showvalue=True,
            command=lambda x, k=key: self.vars[k].set(
                str(int(float(x)))
            )
        ).pack(
            side="left",
            fill="x",
            expand=True
        )

    def refresh_devices(self):
        if sd is None:
            messagebox.showwarning(
                "Audio",
                "De sounddevice-module ontbreekt."
            )
            return

        try:
            devices = sd.query_devices()

            self.device_names = {
                f'{i}: {d["name"]}': i
                for i, d in enumerate(devices)
                if d["max_input_channels"] > 0
            }

            self.output_names = {
                f'{i}: {d["name"]}': i
                for i, d in enumerate(devices)
                if d["max_output_channels"] > 0
            }

            self.input_combo["values"] = list(
                self.device_names
            )
            self.output_combo["values"] = list(
                self.output_names
            )

            if (
                self.vars["input_device"].get()
                not in self.device_names
                and self.device_names
            ):
                self.vars["input_device"].set(
                    next(iter(self.device_names))
                )

            if (
                self.vars["output_device"].get()
                not in self.output_names
                and self.output_names
            ):
                self.vars["output_device"].set(
                    next(iter(self.output_names))
                )

        except Exception as exc:
            messagebox.showerror(
                "Audioapparaten", str(exc)
            )

    def current_config(self):
        config = {
            k: v.get()
            for k, v in self.vars.items()
        }

        for key in (
            "gain", "threshold",
            "attack_ms", "release_ms"
        ):
            config[key] = int(float(config[key]))

        config["vox_enabled"] = (
            self.vox_enabled.get()
        )
        return config

    def save(self):
        try:
            save_config(self.current_config())
            messagebox.showinfo(
                "Opgeslagen",
                f"Instellingen opgeslagen in:\n{CONFIG_FILE}"
            )
        except Exception as exc:
            messagebox.showerror(
                "Opslaan mislukt", str(exc)
            )

    def connect(self):
        messagebox.showinfo(
            "TeamSpeak — testversie",
            "De knop Verbinden is handmatig, "
            "zoals afgesproken.\n\n"
            "De echte TeamSpeak-spraakclient "
            "is nog NIET ingebouwd.\n\n"
            "Er wordt geen verbinding gemaakt.\n\n"
            "Test eerst de geluidskaart en VOX "
            "met Start audiotest."
        )

    def disconnect(self):
        self.connection_text.configure(
            text=(
                "Status: niet verbonden "
                "(spraakclient nog niet ingebouwd)"
            )
        )

    def toggle_monitor(self):
        if self.monitoring:
            self.stop_monitor()
            return

        if sd is None:
            messagebox.showerror(
                "Audio",
                "sounddevice is niet geïnstalleerd."
            )
            return

        device_label = self.vars[
            "input_device"
        ].get()

        if device_label not in self.device_names:
            messagebox.showwarning(
                "Audio",
                "Selecteer eerst een audio-ingang."
            )
            return

        device = self.device_names[device_label]

        try:
            self.stream = sd.InputStream(
                device=device,
                channels=1,
                samplerate=16000,
                blocksize=320,
                dtype="float32",
                callback=self.audio_callback
            )
            self.stream.start()

        except Exception as exc:
            self.stream = None
            messagebox.showerror(
                "Audiotest",
                f"Kan de ingang niet openen:\n{exc}"
            )
            return

        self.monitoring = True
        self.monitor_button.configure(
            text="Stop audiotest"
        )

    def audio_callback(
        self, indata, frames, time_info, status
    ):
        try:
            gain = self.gain_value

            rms = math.sqrt(
                sum(
                    float(x[0]) ** 2
                    for x in indata
                ) / max(len(indata), 1)
            )

            level = max(
                0.0,
                min(100.0, rms * gain * 100.0)
            )

            try:
                self.events.put_nowait(
                    (
                        level,
                        frames * 1000.0 / 16000.0
                    )
                )
            except queue.Full:
                pass

        except Exception:
            pass

    def update_meter(self):
        self.gain_value = (
            float(self.vars["gain"].get()) / 100.0
        )

        try:
            while True:
                level, frame_ms = (
                    self.events.get_nowait()
                )

                self.level = level

                (
                    self.vox_on,
                    self.above_ms,
                    self.below_ms
                ) = compute_vox(
                    level,
                    float(
                        self.vars["threshold"].get()
                    ),
                    self.above_ms,
                    self.below_ms,
                    self.vox_on,
                    float(
                        self.vars["attack_ms"].get()
                    ),
                    float(
                        self.vars["release_ms"].get()
                    ),
                    frame_ms
                )

        except queue.Empty:
            pass

        self.meter["value"] = self.level

        state = (
            "ACTIEF"
            if self.vox_on and self.vox_enabled.get()
            else "uit"
        )

        self.level_text.configure(
            text=(
                f"Niveau: {self.level:.1f}%  "
                f"|  VOX: {state}"
            )
        )

        self.root.after(
            70, self.update_meter
        )

    def stop_monitor(self):
        self.monitoring = False

        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass

            self.stream = None

        self.level = 0
        self.above_ms = 0
        self.below_ms = 0
        self.vox_on = False

        self.monitor_button.configure(
            text="Start audiotest"
        )

    def close(self):
        self.stop_monitor()

        try:
            save_config(self.current_config())
        except Exception:
            pass

        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    GatewayApp(root)
    root.mainloop()
