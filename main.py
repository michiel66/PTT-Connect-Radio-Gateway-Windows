
import json
import math
import os
import queue
import socket
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

try:
    import sounddevice as sd
except ImportError:
    sd = None


# ==========================================
# PTT CONNECT RADIO GATEWAY - WINDOWS
# Copper Edition - TeamSpeak 3 kanalen
# ==========================================

APP = "PTT Connect Radio Gateway"

SERVERS = {
    "TG-103 Voorburg": "ptt.mijnts3.nl",
    "TG-108 Heerlen": "heerlen.mijnts3.nl"
}

DATA = Path(
    os.getenv("APPDATA") or Path.home()
) / "PTTConnectRadioGateway"

SETTINGS = DATA / "settings.json"

DEFAULT = {
    "server_choice": "TG-103 Voorburg",
    "server": "ptt.mijnts3.nl",
    "query_port": "10011",
    "voice_port": "9987",
    "query_user": "",
    "nickname": "Radio Gateway",
    "channel": "",
    "channel_id": "",
    "input_device": "",
    "output_device": "",
    "gain": 100,
    "threshold": 12,
    "attack_ms": 150,
    "release_ms": 950,
    "mode": "RX/TX",
    "vox_enabled": True
}

BG = "#17191c"
SIDE = "#111315"
PANEL = "#262a2e"
COPPER = "#da812f"
TEXT = "#f6f1e9"
SUB = "#b5aea5"
GREEN = "#53cb85"


# ==========================================
# INSTELLINGEN
# ==========================================

def load_settings():
    data = DEFAULT.copy()

    try:
        saved = json.loads(
            SETTINGS.read_text(encoding="utf-8")
        )

        if isinstance(saved, dict):
            data.update({
                key: value
                for key, value in saved.items()
                if key in DEFAULT
            })

    except (OSError, ValueError, TypeError):
        pass

    return data


def save_settings(data):
    DATA.mkdir(parents=True, exist_ok=True)

    temp = SETTINGS.with_suffix(".tmp")

    temp.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    temp.replace(SETTINGS)


# ==========================================
# TEAMSPEAK 3 SERVERQUERY
# ==========================================

def ts_unescape(value):
    replacements = {
        "s": " ",
        "p": "|",
        "/": "/",
        "\\": "\\",
        "n": "\n",
        "r": "\r",
        "t": "\t"
    }

    result = []
    i = 0

    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            result.append(
                replacements.get(
                    value[i + 1],
                    value[i + 1]
                )
            )
            i += 2
        else:
            result.append(value[i])
            i += 1

    return "".join(result)


def ts_escape(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(" ", "\\s")
        .replace("|", "\\p")
        .replace("/", "\\/")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def ts_records(line):
    records = []

    for part in line.strip().split("|"):
        record = {}

        for fragment in part.split(" "):
            if "=" in fragment:
                key, value = fragment.split("=", 1)
                record[key] = ts_unescape(value)

        if record:
            records.append(record)

    return records


def query_channels(
    host,
    query_port,
    voice_port,
    username="",
    password=""
):
    """Alleen-lezen ServerQuery-verbinding."""

    with socket.create_connection(
        (host, int(query_port)),
        timeout=7
    ) as sock:

        sock.settimeout(10)
        reader = sock.makefile("rb")

        def command(text):
            sock.sendall(
                (text + "\n").encode("utf-8")
            )

            lines = []

            for _ in range(1000):
                raw = reader.readline()

                if not raw:
                    raise ConnectionError(
                        "ServerQuery heeft de verbinding gesloten."
                    )

                line = raw.decode(
                    "utf-8", "replace"
                ).strip()

                if line.startswith("error id="):
                    error = ts_records(line)
                    error = error[0] if error else {}

                    if error.get("id") != "0":
                        raise PermissionError(
                            error.get(
                                "msg",
                                "Geen ServerQuery-toegang"
                            )
                        )

                    result = []

                    for item in lines:
                        result.extend(ts_records(item))

                    return result

                if (
                    line
                    and line != "TS3"
                    and not line.startswith("Welcome to")
                    and not line.startswith(
                        "TeamSpeak 3 ServerQuery"
                    )
                ):
                    lines.append(line)

            raise TimeoutError(
                "ServerQuery gaf te veel regels terug."
            )

        if username:
            command(
                "login client_login_name="
                + ts_escape(username)
                + " client_login_password="
                + ts_escape(password)
            )

        command("use port=" + str(int(voice_port)))

        channels = command("channellist")
        clients = command("clientlist")

        return channels, clients


# ==========================================
# WINDOWS DESKTOP APP
# ==========================================

class App:

    def __init__(self, root):
        self.root = root

        root.title(APP + " - Copper Edition")
        root.geometry("1150x780")
        root.minsize(950, 650)
        root.configure(bg=BG)

        data = load_settings()

        self.vars = {
            key: tk.StringVar(value=str(value))
            for key, value in data.items()
            if key != "vox_enabled"
        }

        self.vox_enabled = tk.BooleanVar(
            value=bool(data["vox_enabled"])
        )

        self.query_password = tk.StringVar()
        self.query_events = queue.Queue()
        self.audio_events = queue.Queue(maxsize=30)

        self.stream = None
        self.level = 0.0
        self.vox_active = False
        self.above_ms = 0
        self.below_ms = 0

        self.inputs = {}
        self.outputs = {}

        self.pages = {}
        self.nav = {}
        self.query_busy = False
        self.closing = False

        self.setup_style()
        self.build_ui()
        self.refresh_devices(False)

        self.show_page("Overzicht")

        root.after(70, self.update_audio)
        root.after(100, self.poll_query)

        root.protocol(
            "WM_DELETE_WINDOW",
            self.close
        )

    # ======================================
    # STIJL
    # ======================================

    def setup_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(
            "TEntry",
            fieldbackground="#faf7f0",
            padding=7
        )

        style.configure(
            "TCombobox",
            padding=7
        )

        style.configure(
            "TButton",
            padding=(13, 9),
            font=("Segoe UI", 10, "bold")
        )

        style.configure(
            "Copper.TButton",
            background="#b96522",
            foreground="white"
        )

        style.map(
            "Copper.TButton",
            background=[("active", COPPER)]
        )

        style.configure(
            "Audio.Horizontal.TProgressbar",
            background=GREEN,
            troughcolor="#4b3b2b"
        )

        style.configure(
            "Dark.Treeview",
            background="#30353a",
            foreground=TEXT,
            fieldbackground="#30353a",
            rowheight=29,
            font=("Segoe UI", 10)
        )

        style.configure(
            "Dark.Treeview.Heading",
            background="#885022",
            foreground="white",
            font=("Segoe UI", 10, "bold")
        )

        style.map(
            "Dark.Treeview",
            background=[
                ("selected", "#b96522")
            ]
        )

    # ======================================
    # HOOFDVENSTER
    # ======================================

    def build_ui(self):
        sidebar = tk.Frame(
            self.root,
            bg=SIDE,
            width=235
        )

        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(
            sidebar,
            text="◉ PTT Connect",
            bg=SIDE,
            fg=TEXT,
            font=("Segoe UI", 19, "bold")
        ).pack(
            anchor="w",
            padx=18,
            pady=(25, 0)
        )

        tk.Label(
            sidebar,
            text="RADIO GATEWAY",
            bg=SIDE,
            fg="#ffb347",
            font=("Segoe UI", 11, "bold")
        ).pack(
            anchor="w",
            padx=20,
            pady=(0, 30)
        )

        menus = [
            ("Overzicht", "▣"),
            ("TeamSpeak", "◉"),
            ("Audioapparaten", "◖"),
            ("VOX-instellingen", "◎"),
            ("Radiomodus", "⚙"),
            ("Systeem", "◈")
        ]

        for name, symbol in menus:
            button = tk.Button(
                sidebar,
                text=f"{symbol}   {name}",
                bg=SIDE,
                fg=TEXT,
                bd=0,
                anchor="w",
                padx=16,
                pady=13,
                font=("Segoe UI", 11),
                activebackground="#885022",
                activeforeground="white",
                cursor="hand2",
                command=lambda n=name: self.show_page(n)
            )

            button.pack(
                fill="x",
                padx=9,
                pady=3
            )

            self.nav[name] = button

        tk.Label(
            sidebar,
            text="WINDOWS DESKTOP",
            bg=SIDE,
            fg="#d89a64"
        ).pack(
            side="bottom",
            pady=25
        )

        right = tk.Frame(self.root, bg=BG)
        right.pack(
            side="left",
            fill="both",
            expand=True
        )

        header = tk.Frame(
            right,
            bg="#24272a",
            height=90
        )

        header.pack(fill="x")
        header.pack_propagate(False)

        self.title = tk.Label(
            header,
            bg="#24272a",
            fg=TEXT,
            font=("Segoe UI", 21, "bold")
        )

        self.title.pack(
            anchor="w",
            padx=25,
            pady=(15, 0)
        )

        tk.Label(
            header,
            text="PTT Connect Radio Gateway • Copper Edition",
            bg="#24272a",
            fg="#ffc47d"
        ).pack(anchor="w", padx=27)

        outer = tk.Frame(right, bg=BG)
        outer.pack(
            fill="both",
            expand=True
        )

        canvas = tk.Canvas(
            outer,
            bg=BG,
            highlightthickness=0
        )

        scroll = ttk.Scrollbar(
            outer,
            orient="vertical",
            command=canvas.yview
        )

        canvas.configure(
            yscrollcommand=scroll.set
        )

        scroll.pack(side="right", fill="y")
        canvas.pack(
            side="left",
            fill="both",
            expand=True
        )

        self.body = tk.Frame(canvas, bg=BG)
        window = canvas.create_window(
            (0, 0),
            window=self.body,
            anchor="nw"
        )

        self.body.bind(
            "<Configure>",
            lambda e: canvas.configure(
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
                self.body,
                bg=BG
            )

        self.build_overview()
        self.build_teamspeak()
        self.build_audio_page()
        self.build_vox_page()
        self.build_radio_page()
        self.build_system_page()

    def card(self, page, heading):
        box = tk.Frame(
            page,
            bg=PANEL,
            highlightbackground="#76512f",
            highlightthickness=1,
            padx=20,
            pady=18
        )

        box.pack(
            fill="x",
            padx=20,
            pady=(15, 3)
        )

        tk.Label(
            box,
            text=heading,
            bg=PANEL,
            fg="#ffb347",
            font=("Segoe UI", 14, "bold")
        ).pack(
            anchor="w",
            pady=(0, 13)
        )

        return box

    def note(self, parent, text):
        tk.Label(
            parent,
            text=text,
            bg=PANEL,
            fg=SUB,
            anchor="w",
            justify="left",
            wraplength=690
        ).pack(anchor="w", pady=6)

    def field(self, parent, label, key):
        line = tk.Frame(parent, bg=PANEL)
        line.pack(fill="x", pady=6)

        tk.Label(
            line,
            text=label,
            bg=PANEL,
            fg=TEXT,
            width=20,
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

    def slider(self, parent, label, key, low, high):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=7)

        tk.Label(
            row,
            text=label,
            bg=PANEL,
            fg=TEXT,
            width=22,
            anchor="w"
        ).pack(side="left")

        control = tk.Scale(
            row,
            from_=low,
            to=high,
            orient="horizontal",
            bg=PANEL,
            fg=TEXT,
            troughcolor="#b96522",
            activebackground=COPPER,
            highlightthickness=0,
            length=320,
            resolution=1,
            command=lambda value, k=key:
                self.vars[k].set(
                    str(int(float(value)))
                )
        )

        control.set(
            int(float(self.vars[key].get()))
        )

        control.pack(
            side="left",
            fill="x",
            expand=True
        )

    # ======================================
    # OVERZICHT
    # ======================================

    def build_overview(self):
        page = self.pages["Overzicht"]

        box = self.card(page, "Systeemstatus")

        self.monitor_status = tk.Label(
            box,
            text="Audio-ingang: niet actief",
            bg=PANEL,
            fg=GREEN,
            font=("Segoe UI", 12, "bold")
        )

        self.monitor_status.pack(anchor="w")

        self.note(
            box,
            "TeamSpeak-spraakverbinding: nog niet actief."
        )

        audio = self.card(page, "Live audiometer")

        self.meter = ttk.Progressbar(
            audio,
            style="Audio.Horizontal.TProgressbar",
            maximum=100
        )

        self.meter.pack(fill="x", pady=12)

        self.meter_label = tk.Label(
            audio,
            text="Niveau: 0% | VOX: uit",
            bg=PANEL,
            fg=GREEN,
            font=("Segoe UI", 12, "bold")
        )

        self.meter_label.pack(anchor="w")

        self.monitor_button = ttk.Button(
            audio,
            text="Start audiotest",
            style="Copper.TButton",
            command=self.toggle_monitor
        )

        self.monitor_button.pack(
            anchor="w",
            pady=14
        )

        self.note(
            audio,
            "De audiotest gebruikt de geselecteerde "
            "microfoon of USB-geluidskaart."
        )

    # ======================================
    # TEAMSPEAK
    # ======================================

    def build_teamspeak(self):
        page = self.pages["TeamSpeak"]

        box = self.card(
            page,
            "TeamSpeak 3 — Server en kanaal"
        )

        self.note(box, "Selecteer een TeamSpeak-server.")

        self.server_combo = ttk.Combobox(
            box,
            textvariable=self.vars["server_choice"],
            values=list(SERVERS),
            state="readonly"
        )

        self.server_combo.pack(
            fill="x",
            pady=7
        )

        self.server_combo.bind(
            "<<ComboboxSelected>>",
            self.change_server
        )

        self.field(box, "Serveradres", "server")
        self.field(box, "Gebruikersnaam", "nickname")
        self.field(box, "Spraakpoort", "voice_port")
        self.field(box, "ServerQuery-poort", "query_port")
        self.field(box, "Query-gebruikersnaam", "query_user")

        line = tk.Frame(box, bg=PANEL)
        line.pack(fill="x", pady=5)

        tk.Label(
            line,
            text="Query-wachtwoord",
            bg=PANEL,
            fg=TEXT,
            width=20,
            anchor="w"
        ).pack(side="left")

        ttk.Entry(
            line,
            textvariable=self.query_password,
            show="*"
        ).pack(
            side="left",
            fill="x",
            expand=True
        )

        self.note(
            box,
            "Query-inloggegevens zijn optioneel. "
            "Het Query-wachtwoord wordt niet opgeslagen."
        )

        self.query_button = ttk.Button(
            box,
            text="Kanalen ophalen",
            style="Copper.TButton",
            command=self.fetch_channels
        )

        self.query_button.pack(
            anchor="w",
            pady=10
        )

        columns = ("id", "name", "users")

        self.channels = ttk.Treeview(
            box,
            columns=columns,
            show="headings",
            height=9,
            style="Dark.Treeview",
            selectmode="browse"
        )

        self.channels.heading("id", text="ID")
        self.channels.heading("name", text="Kanaalnaam")
        self.channels.heading("users", text="Gebruikers")

        self.channels.column(
            "id", width=65, stretch=False
        )
        self.channels.column(
            "name", width=330
        )
        self.channels.column(
            "users", width=95, stretch=False
        )

        self.channels.pack(
            fill="both",
            expand=True,
            pady=10
        )

        self.channels.bind(
            "<<TreeviewSelect>>",
            self.select_channel
        )

        self.query_status = tk.Label(
            box,
            text="Nog geen kanalen opgehaald.",
            bg=PANEL,
            fg="#ffb347",
            wraplength=680,
            justify="left"
        )

        self.query_status.pack(anchor="w", pady=7)

        self.field(box, "Gekozen kanaal", "channel")

        ttk.Button(
            box,
            text="Gekozen kanaal bewaren",
            command=self.save_current
        ).pack(anchor="w", pady=9)

        buttons = tk.Frame(box, bg=PANEL)
        buttons.pack(anchor="w", pady=10)

        ttk.Button(
            buttons,
            text="Verbinden",
            style="Copper.TButton",
            command=self.connect
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            buttons,
            text="Verbreken",
            command=self.disconnect
        ).pack(side="left")

        self.connection_status = tk.Label(
            box,
            text="Status: niet verbonden",
            bg=PANEL,
            fg="#ffb347"
        )

        self.connection_status.pack(anchor="w", pady=6)

        self.note(
            box,
            "De kanalenlijst gebruikt ServerQuery. "
            "De echte spraakverbinding wordt later toegevoegd."
        )

    def change_server(self, event=None):
        choice = self.vars["server_choice"].get()

        if choice in SERVERS:
            self.vars["server"].set(SERVERS[choice])

        self.vars["channel"].set("")
        self.vars["channel_id"].set("")

        for row in self.channels.get_children():
            self.channels.delete(row)

        self.query_status.config(
            text="Server gewijzigd. Klik op Kanalen ophalen."
        )

    def fetch_channels(self):
        if self.query_busy:
            return

        host = self.vars["server"].get().strip()
        query_port = self.vars["query_port"].get()
        voice_port = self.vars["voice_port"].get()
        user = self.vars["query_user"].get()
        password = self.query_password.get()

        if not host:
            messagebox.showwarning(
                "TeamSpeak",
                "Vul eerst een serveradres in."
            )
            return

        self.query_busy = True
        self.query_button.config(state="disabled")
        self.query_status.config(
            text="Kanalen worden opgehaald..."
        )

        def worker():
            try:
                result = query_channels(
                    host,
                    query_port,
                    voice_port,
                    user,
                    password
                )

                self.query_events.put(
                    ("success", result)
                )

            except Exception as exc:
                self.query_events.put(
                    ("error", str(exc))
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def poll_query(self):
        if self.closing:
            return

        try:
            while True:
                status, result = self.query_events.get_nowait()

                self.query_busy = False
                self.query_button.config(state="normal")

                if status == "error":
                    self.query_status.config(
                        text="Kanalen ophalen mislukt: " + result
                    )
                    continue

                channels, clients = result

                for item in self.channels.get_children():
                    self.channels.delete(item)

                counts = {}

                for client in clients:
                    if client.get("client_type") == "0":
                        cid = client.get("cid", "")
                        counts[cid] = counts.get(cid, 0) + 1

                for channel in sorted(
                    channels,
                    key=lambda c: int(c.get("cid", "0"))
                ):
                    cid = channel.get("cid", "")
                    name = channel.get(
                        "channel_name", "(zonder naam)"
                    )

                    self.channels.insert(
                        "",
                        "end",
                        values=(
                            cid,
                            name,
                            counts.get(cid, 0)
                        )
                    )

                self.query_status.config(
                    text=f"{len(channels)} kanalen opgehaald."
                )

        except queue.Empty:
            pass

        self.root.after(100, self.poll_query)

    def select_channel(self, event=None):
        selected = self.channels.selection()

        if not selected:
            return

        cid, name, users = self.channels.item(
            selected[0], "values"
        )

        self.vars["channel"].set(str(name))
        self.vars["channel_id"].set(str(cid))

        self.query_status.config(
            text=f"Geselecteerd: {name} (ID {cid})"
        )

    def connect(self):
        messagebox.showinfo(
            "TeamSpeak",
            "De server en het gekozen kanaal "
            "kunnen worden opgeslagen.\n\n"
            "De echte TeamSpeak-spraakclient "
            "is nog niet ingebouwd.\n\n"
            "Er wordt nog geen spraakverbinding gemaakt."
        )

    def disconnect(self):
        self.connection_status.config(
            text="Status: niet verbonden"
        )

    # ======================================
    # AUDIOAPPARATEN
    # ======================================

    def build_audio_page(self):
        box = self.card(
            self.pages["Audioapparaten"],
            "Geluidskaart instellen"
        )

        for label, key, attr in [
            ("Audio-ingang", "input_device", "input_combo"),
            ("Audio-uitgang", "output_device", "output_combo")
        ]:
            line = tk.Frame(box, bg=PANEL)
            line.pack(fill="x", pady=9)

            tk.Label(
                line,
                text=label,
                bg=PANEL,
                fg=TEXT,
                width=18,
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

            setattr(self, attr, combo)

        ttk.Button(
            box,
            text="Geluidskaarten vernieuwen",
            command=self.refresh_devices
        ).pack(anchor="w", pady=12)

        self.slider(
            box,
            "Ingangsniveau (%)",
            "gain",
            0,
            200
        )

        self.note(
            box,
            "Het ingangsniveau beïnvloedt momenteel "
            "de audiometer en VOX-test."
        )

        self.note(
            box,
            "De audio-uitgang is alvast instelbaar. "
            "Afspelen van TeamSpeak-audio komt later."
        )

        ttk.Button(
            box,
            text="Instellingen opslaan",
            command=self.save_current
        ).pack(anchor="w", pady=12)

    def refresh_devices(self, show_error=True):
        if sd is None:
            if show_error:
                messagebox.showerror(
                    "Audio",
                    "De module sounddevice ontbreekt."
                )
            return

        try:
            devices = sd.query_devices()

            self.inputs = {
                f'{i}: {device["name"]}': i
                for i, device in enumerate(devices)
                if device["max_input_channels"] > 0
            }

            self.outputs = {
                f'{i}: {device["name"]}': i
                for i, device in enumerate(devices)
                if device["max_output_channels"] > 0
            }

            for key, combo, mapping in [
                ("input_device", self.input_combo, self.inputs),
                ("output_device", self.output_combo, self.outputs)
            ]:
                combo["values"] = list(mapping)

                if self.vars[key].get() not in mapping:
                    if mapping:
                        self.vars[key].set(
                            next(iter(mapping))
                        )

        except Exception as exc:
            if show_error:
                messagebox.showerror(
                    "Audioapparaten", str(exc)
                )

    # ======================================
    # VOX
    # ======================================

    def build_vox_page(self):
        box = self.card(
            self.pages["VOX-instellingen"],
            "Voice Activated Transmission"
        )

        tk.Checkbutton(
            box,
            text="VOX inschakelen",
            variable=self.vox_enabled,
            bg=PANEL,
            fg=TEXT,
            selectcolor="#654125",
            activebackground=PANEL,
            activeforeground=TEXT
        ).pack(anchor="w", pady=10)

        self.slider(
            box, "VOX-drempel (%)",
            "threshold", 1, 100
        )

        self.slider(
            box, "Triggertijd (ms)",
            "attack_ms", 0, 2000
        )

        self.slider(
            box, "Afvaltijd (ms)",
            "release_ms", 100, 5000
        )

        self.note(
            box,
            "Test de VOX via de audiometer op Overzicht. "
            "Er wordt nog niet uitgezonden."
        )

        ttk.Button(
            box,
            text="Instellingen opslaan",
            command=self.save_current
        ).pack(anchor="w", pady=10)

    # ======================================
    # RADIOMODUS
    # ======================================

    def build_radio_page(self):
        box = self.card(
            self.pages["Radiomodus"],
            "Radio bedrijfsmodus"
        )

        for title, value in [
            ("RX - alleen ontvanger", "RX"),
            ("TX - alleen zender", "TX"),
            ("RX/TX - gateway", "RX/TX")
        ]:
            tk.Radiobutton(
                box,
                text=title,
                variable=self.vars["mode"],
                value=value,
                bg=PANEL,
                fg=TEXT,
                selectcolor="#654125",
                activebackground=PANEL,
                activeforeground=TEXT,
                font=("Segoe UI", 11)
            ).pack(anchor="w", pady=8)

        self.note(
            box,
            "De bedrijfsmodus wordt opgeslagen. "
            "De echte radio-audiobrug is nog niet actief."
        )

        ttk.Button(
            box,
            text="Instellingen opslaan",
            command=self.save_current
        ).pack(anchor="w", pady=10)

    # ======================================
    # SYSTEEM
    # ======================================

    def build_system_page(self):
        box = self.card(
            self.pages["Systeem"],
            "Programma-informatie"
        )

        self.note(
            box,
            "PTT Connect Radio Gateway - Windows Copper Edition"
        )

        self.note(
            box,
            "TeamSpeak 3: TG-103 Voorburg en TG-108 Heerlen."
        )

        self.note(
            box,
            "Instellingen worden opgeslagen in:"
        )

        self.note(box, str(SETTINGS))

        self.note(
            box,
            "Gepland: TeamSpeak-spraak, RTL-SDR en crosslink."
        )

        ttk.Button(
            box,
            text="Alle instellingen opslaan",
            style="Copper.TButton",
            command=self.save_current
        ).pack(anchor="w", pady=15)

    # ======================================
    # NAVIGATIE
    # ======================================

    def show_page(self, name):
        for page in self.pages.values():
            page.pack_forget()

        self.pages[name].pack(
            fill="both",
            expand=True
        )

        self.title.config(text=name)

        for title, button in self.nav.items():
            button.config(
                bg="#885022" if title == name else SIDE
            )

    # ======================================
    # AUDIO EN VOX TEST
    # ======================================

    def toggle_monitor(self):
        if self.stream is not None:
            self.stop_monitor()
            return

        name = self.vars["input_device"].get()

        if sd is None or name not in self.inputs:
            messagebox.showwarning(
                "Audio",
                "Selecteer eerst een geldige audio-ingang."
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

            self.monitor_button.config(
                text="Stop audiotest"
            )

            self.monitor_status.config(
                text="Audio-ingang: actief"
            )

        except Exception as exc:
            if self.stream is not None:
                try:
                    self.stream.close()
                except Exception:
                    pass
            self.stream = None

            messagebox.showerror(
                "Audiotest", str(exc)
            )

    def on_audio(
        self, samples, frames, timing, status
    ):
        try:
            rms = math.sqrt(
                sum(
                    float(sample[0]) ** 2
                    for sample in samples
                ) / max(frames, 1)
            )

            try:
                self.audio_events.put_nowait(
                    (rms, frames * 1000.0 / 16000.0)
                )
            except queue.Full:
                pass

        except Exception:
            pass

    def update_audio(self):
        if self.closing:
            return

        try:
            while True:
                rms, frame_ms = (
                    self.audio_events.get_nowait()
                )

                gain = float(
                    self.vars["gain"].get()
                )

                self.level = min(
                    100.0,
                    rms * gain
                )

                threshold = float(
                    self.vars["threshold"].get()
                )

                if self.level >= threshold:
                    self.above_ms += frame_ms
                    self.below_ms = 0

                    if self.above_ms >= float(
                        self.vars["attack_ms"].get()
                    ):
                        self.vox_active = True

                else:
                    self.below_ms += frame_ms
                    self.above_ms = 0

                    if self.below_ms >= float(
                        self.vars["release_ms"].get()
                    ):
                        self.vox_active = False

        except queue.Empty:
            pass

        self.meter["value"] = self.level

        state = (
            "ACTIEF"
            if self.vox_active and self.vox_enabled.get()
            else "uit"
        )

        self.meter_label.config(
            text=(
                f"Niveau: {self.level:.1f}% "
                f"| VOX: {state}"
            )
        )

        self.root.after(70, self.update_audio)

    def stop_monitor(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass

            self.stream = None

        self.level = 0
        self.vox_active = False
        self.above_ms = 0
        self.below_ms = 0

        while not self.audio_events.empty():
            try:
                self.audio_events.get_nowait()
            except queue.Empty:
                break

        self.monitor_button.config(
            text="Start audiotest"
        )

        self.monitor_status.config(
            text="Audio-ingang: niet actief"
        )

    # ======================================
    # OPSLAAN EN AFSLUITEN
    # ======================================

    def current_settings(self):
        values = {
            key: value.get()
            for key, value in self.vars.items()
        }

        for key in [
            "gain",
            "threshold",
            "attack_ms",
            "release_ms"
        ]:
            values[key] = int(float(values[key]))

        values["vox_enabled"] = (
            self.vox_enabled.get()
        )

        return values

    def save_current(self):
        try:
            save_settings(
                self.current_settings()
            )

            messagebox.showinfo(
                "Opgeslagen",
                "Alle instellingen zijn opgeslagen."
            )

        except Exception as exc:
            messagebox.showerror(
                "Opslaan mislukt", str(exc)
            )

    def close(self):
        self.closing = True
        self.stop_monitor()

        try:
            save_settings(
                self.current_settings()
            )
        except Exception:
            pass

        self.root.destroy()


# ==========================================
# START PROGRAMMA
# ==========================================

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
