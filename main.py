
import json
import math
import os
import queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import sounddevice as sd
except ImportError:
    sd = None

APP = 'PTT Connect Radio Gateway'
DATA = Path(os.getenv('APPDATA') or Path.home()) / 'PTTConnectRadioGateway'
SETTINGS = DATA / 'settings.json'

DEFAULT = dict(
    server='ptt.mijnts3.nl',
    nickname='Radio Gateway',
    channel='',
    input_device='',
    output_device='',
    gain=100,
    threshold=12,
    attack_ms=150,
    release_ms=950,
    mode='RX/TX',
    vox_enabled=True
)

BG = '#17191c'
SIDE = '#111315'
PANEL = '#262a2e'
COPPER = '#da812f'
TEXT = '#f6f1e9'
SUB = '#b5aea5'
GREEN = '#53cb85'


def load():
    config = DEFAULT.copy()
    try:
        saved = json.loads(
            SETTINGS.read_text(encoding='utf-8')
        )
        if isinstance(saved, dict):
            config.update({
                k: v for k, v in saved.items()
                if k in config
            })
    except (OSError, ValueError, TypeError):
        pass
    return config


def save(values):
    DATA.mkdir(parents=True, exist_ok=True)
    temp = SETTINGS.with_suffix('.tmp')
    temp.write_text(
        json.dumps(
            values,
            indent=2,
            ensure_ascii=False
        ),
        encoding='utf-8'
    )
    temp.replace(SETTINGS)


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP + ' — Copper Edition')
        root.geometry('1100x740')
        root.minsize(920, 620)
        root.configure(bg=BG)

        data = load()

        self.vars = {
            k: tk.StringVar(value=str(v))
            for k, v in data.items()
            if k != 'vox_enabled'
        }

        self.vox_enabled = tk.BooleanVar(
            value=bool(data['vox_enabled'])
        )

        self.stream = None
        self.events = queue.Queue(maxsize=20)
        self.level = 0
        self.vox = False
        self.above = 0
        self.below = 0

        self.input_devices = {}
        self.output_devices = {}
        self.nav = {}
        self.pages = {}

        self._style()
        self._layout()
        self.refresh_devices(show_error=False)
        self.show_page('Overzicht')

        root.after(70, self.update_meter)
        root.protocol(
            'WM_DELETE_WINDOW',
            self.close
        )

    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use('clam')

        s.configure(
            'TEntry',
            fieldbackground='#faf7f0',
            padding=7
        )

        s.configure(
            'TCombobox',
            padding=6
        )

        s.configure(
            'TButton',
            padding=(13, 9),
            font=('Segoe UI', 10, 'bold')
        )

        s.configure(
            'Copper.TButton',
            background='#b96522',
            foreground='white'
        )

        s.map(
            'Copper.TButton',
            background=[
                ('active', COPPER)
            ]
        )

        s.configure(
            'Copper.Horizontal.TProgressbar',
            background=GREEN,
            troughcolor='#4b3b2b',
            borderwidth=0
        )

        s.configure(
            'Copper.TCheckbutton',
            background=PANEL,
            foreground=TEXT
        )

        s.map(
            'Copper.TCheckbutton',
            background=[('active', PANEL)],
            foreground=[('active', TEXT)]
        )

    def _layout(self):
        side = tk.Frame(
            self.root,
            bg=SIDE,
            width=230
        )

        side.pack(
            side='left',
            fill='y'
        )
        side.pack_propagate(False)

        tk.Label(
            side,
            text='◉  PTT Connect',
            bg=SIDE,
            fg=TEXT,
            font=('Segoe UI', 19, 'bold')
        ).pack(
            anchor='w',
            padx=18,
            pady=(26, 0)
        )

        tk.Label(
            side,
            text='RADIO GATEWAY',
            bg=SIDE,
            fg='#ffb347',
            font=('Segoe UI', 11, 'bold')
        ).pack(
            anchor='w',
            padx=22,
            pady=(0, 30)
        )

        names = [
            ('Overzicht', '▣'),
            ('TeamSpeak', '◉'),
            ('Audioapparaten', '◖'),
            ('VOX-instellingen', '◎'),
            ('Radiomodus', '⚙'),
            ('Systeem', '◈')
        ]

        for name, symbol in names:
            btn = tk.Button(
                side,
                text=f'{symbol}   {name}',
                bg=SIDE,
                fg=TEXT,
                bd=0,
                relief='flat',
                anchor='w',
                padx=16,
                pady=13,
                activebackground='#885022',
                activeforeground='white',
                font=('Segoe UI', 11),
                cursor='hand2',
                command=lambda n=name: self.show_page(n)
            )

            btn.pack(
                fill='x',
                padx=9,
                pady=3
            )

            self.nav[name] = btn

        tk.Label(
            side,
            text='WINDOWS DESKTOP · TEST',
            bg=SIDE,
            fg='#d89a64',
            font=('Segoe UI', 9, 'bold')
        ).pack(
            side='bottom',
            pady=25
        )

        right = tk.Frame(
            self.root,
            bg=BG
        )
        right.pack(
            side='left',
            fill='both',
            expand=True
        )

        header = tk.Frame(
            right,
            bg='#24272a',
            height=91
        )

        header.pack(fill='x')
        header.pack_propagate(False)

        self.title = tk.Label(
            header,
            text='',
            bg='#24272a',
            fg=TEXT,
            font=('Segoe UI', 21, 'bold')
        )

        self.title.pack(
            anchor='w',
            padx=25,
            pady=(15, 0)
        )

        tk.Label(
            header,
            text='PTT Connect Radio Gateway  •  Copper Edition',
            bg='#24272a',
            fg='#ffc47d',
            font=('Segoe UI', 10)
        ).pack(
            anchor='w',
            padx=27
        )

        self.body = tk.Frame(
            right,
            bg=BG
        )

        self.body.pack(
            fill='both',
            expand=True,
            padx=22,
            pady=18
        )

        for name in self.nav:
            self.pages[name] = tk.Frame(
                self.body,
                bg=BG
            )

        self._overview()
        self._teamspeak()
        self._audio()
        self._vox_page()
        self._radio()
        self._system()

    def card(self, page, heading):
        box = tk.Frame(
            page,
            bg=PANEL,
            highlightbackground='#76512f',
            highlightthickness=1,
            padx=20,
            pady=18
        )

        box.pack(
            fill='x',
            pady=(0, 16)
        )

        tk.Label(
            box,
            text=heading,
            bg=PANEL,
            fg='#ffb347',
            font=('Segoe UI', 14, 'bold')
        ).pack(
            anchor='w',
            pady=(0, 14)
        )

        return box

    def note(self, parent, text, color=SUB):
        tk.Label(
            parent,
            text=text,
            bg=PANEL,
            fg=color,
            justify='left',
            wraplength=680,
            font=('Segoe UI', 10)
        ).pack(
            anchor='w',
            pady=5
        )

    def field(self, parent, label, name):
        row = tk.Frame(
            parent,
            bg=PANEL
        )

        row.pack(
            fill='x',
            pady=7
        )

        tk.Label(
            row,
            text=label,
            bg=PANEL,
            fg=TEXT,
            width=19,
            anchor='w',
            font=('Segoe UI', 10)
        ).pack(side='left')

        ttk.Entry(
            row,
            textvariable=self.vars[name]
        ).pack(
            side='left',
            fill='x',
            expand=True
        )

    def slider(
        self,
        parent,
        label,
        key,
        start,
        end
    ):
        row = tk.Frame(
            parent,
            bg=PANEL
        )
        row.pack(
            fill='x',
            pady=8
        )

        tk.Label(
            row,
            text=label,
            bg=PANEL,
            fg=TEXT,
            width=22,
            anchor='w'
        ).pack(side='left')

        control = tk.Scale(
            row,
            from_=start,
            to=end,
            orient='horizontal',
            bg=PANEL,
            fg=TEXT,
            troughcolor='#b96522',
            activebackground='#ffb347',
            highlightthickness=0,
            length=310,
            resolution=1,
            showvalue=True,
            command=lambda v, k=key: self.vars[k].set(
                str(int(float(v)))
            )
        )

        control.set(
            int(float(self.vars[key].get()))
        )

        control.pack(
            side='left',
            fill='x',
            expand=True
        )

    # OVERZICHT

    def _overview(self):
        page = self.pages['Overzicht']

        box = self.card(
            page,
            'Systeemstatus'
        )

        self.monitor_state = tk.Label(
            box,
            text='Audio-ingang: niet actief',
            bg=PANEL,
            fg=GREEN,
            font=('Segoe UI', 12, 'bold')
        )

        self.monitor_state.pack(anchor='w')

        self.note(
            box,
            'TeamSpeak: niet verbonden '
            '(spraakverbinding is nog niet ingebouwd)'
        )

        self.note(
            box,
            'Kies links een onderdeel om de instellingen te openen.'
        )

        audio = self.card(
            page,
            'Live ingangsniveau'
        )

        self.meter = ttk.Progressbar(
            audio,
            style='Copper.Horizontal.TProgressbar',
            maximum=100
        )

        self.meter.pack(
            fill='x',
            pady=10
        )

        self.meter_label = tk.Label(
            audio,
            text='Niveau: 0.0%  |  VOX: uit',
            bg=PANEL,
            fg=GREEN,
            font=('Segoe UI', 12, 'bold')
        )

        self.meter_label.pack(
            anchor='w',
            pady=5
        )

        row = tk.Frame(
            audio,
            bg=PANEL
        )

        row.pack(
            anchor='w',
            pady=12
        )

        self.monitor_button = ttk.Button(
            row,
            text='Start audiotest',
            style='Copper.TButton',
            command=self.toggle_monitor
        )

        self.monitor_button.pack(
            side='left',
            padx=(0, 8)
        )

        ttk.Button(
            row,
            text='Instellingen opslaan',
            command=self.save_settings
        ).pack(side='left')

        self.note(
            audio,
            'De audiotest leest alleen het gekozen invoerapparaat. '
            'Er wordt niets naar TeamSpeak verzonden.'
        )

    # TEAMSPEAK

    def _teamspeak(self):
        box = self.card(
            self.pages['TeamSpeak'],
            'TeamSpeak-server'
        )

        for label, key in [
            ('Serveradres', 'server'),
            ('Gebruikersnaam', 'nickname'),
            ('Kanaalnaam / ID', 'channel')
        ]:
            self.field(
                box,
                label,
                key
            )

        row = tk.Frame(
            box,
            bg=PANEL
        )

        row.pack(
            anchor='w',
            pady=13
        )

        ttk.Button(
            row,
            text='Verbinden',
            style='Copper.TButton',
            command=self.connect
        ).pack(
            side='left',
            padx=(0, 10)
        )

        ttk.Button(
            row,
            text='Verbreken',
            command=self.disconnect
        ).pack(side='left')

        self.connection_label = tk.Label(
            box,
            text='Status: niet verbonden',
            bg=PANEL,
            fg='#ffb347',
            font=('Segoe UI', 11, 'bold')
        )

        self.connection_label.pack(anchor='w')

        self.note(
            box,
            'Let op: de TeamSpeak-spraakclient en echte kanalenlijst '
            'worden in een volgende bouwstap toegevoegd.'
        )

        ttk.Button(
            box,
            text='Instellingen opslaan',
            command=self.save_settings
        ).pack(
            anchor='w',
            pady=12
        )

    # AUDIOAPPARATEN

    def _audio(self):
        box = self.card(
            self.pages['Audioapparaten'],
            'Ingang en uitgang'
        )

        for label, key, attr in [
            ('Audio-ingang', 'input_device', 'input_combo'),
            ('Audio-uitgang', 'output_device', 'output_combo')
        ]:
            row = tk.Frame(
                box,
                bg=PANEL
            )

            row.pack(
                fill='x',
                pady=8
            )

            tk.Label(
                row,
                text=label,
                bg=PANEL,
                fg=TEXT,
                width=19,
                anchor='w'
            ).pack(side='left')

            combo = ttk.Combobox(
                row,
                textvariable=self.vars[key],
                state='readonly'
            )

            combo.pack(
                side='left',
                fill='x',
                expand=True
            )

            setattr(
                self,
                attr,
                combo
            )

        ttk.Button(
            box,
            text='Geluidskaarten vernieuwen',
            command=self.refresh_devices
        ).pack(
            anchor='w',
            pady=10
        )

        self.slider(
            box,
            'Ingangsniveau (%)',
            'gain',
            0,
            200
        )

        self.note(
            box,
            'Ingangsniveau beïnvloedt nu alleen de audiometer/VOX-test; '
            'hardware-opnamevolume wordt niet gewijzigd.'
        )

        self.note(
            box,
            'De audio-uitgang is selecteerbaar, maar we sturen er '
            'in deze testversie nog geen TeamSpeak-audio naartoe.'
        )

        ttk.Button(
            box,
            text='Instellingen opslaan',
            command=self.save_settings
        ).pack(
            anchor='w',
            pady=10
        )

    # VOX-INSTELLINGEN

    def _vox_page(self):
        box = self.card(
            self.pages['VOX-instellingen'],
            'Voice Activated Transmission — test'
        )

        ttk.Checkbutton(
            box,
            text='VOX inschakelen',
            variable=self.vox_enabled,
            style='Copper.TCheckbutton'
        ).pack(
            anchor='w',
            pady=8
        )

        self.slider(
            box,
            'VOX-drempel (%)',
            'threshold',
            1,
            100
        )

        self.slider(
            box,
            'Triggertijd (ms)',
            'attack_ms',
            0,
            2000
        )

        self.slider(
            box,
            'Afvaltijd (ms)',
            'release_ms',
            100,
            5000
        )

        self.note(
            box,
            'Met Start audiotest op Overzicht kun je zien wanneer '
            'de VOX actief wordt. Er vindt nog geen uitzending plaats.'
        )

        ttk.Button(
            box,
            text='Instellingen opslaan',
            command=self.save_settings
        ).pack(
            anchor='w',
            pady=10
        )

    # RADIOMODUS

    def _radio(self):
        box = self.card(
            self.pages['Radiomodus'],
            'Radio bedrijfsmodus'
        )

        modes = [
            ('Alleen RX — ontvanger', 'RX'),
            ('Alleen TX — zender', 'TX'),
            ('RX/TX — gateway', 'RX/TX')
        ]

        for label, val in modes:
            tk.Radiobutton(
                box,
                text=label,
                value=val,
                variable=self.vars['mode'],
                bg=PANEL,
                fg=TEXT,
                activebackground=PANEL,
                activeforeground=TEXT,
                selectcolor='#654125',
                font=('Segoe UI', 11)
            ).pack(
                anchor='w',
                pady=9
            )

        self.note(
            box,
            'De modus wordt opgeslagen. De radio- en '
            'TeamSpeak-audiobrug is nog niet actief.'
        )

        ttk.Button(
            box,
            text='Instellingen opslaan',
            command=self.save_settings
        ).pack(
            anchor='w',
            pady=10
        )

    # SYSTEEM

    def _system(self):
        box = self.card(
            self.pages['Systeem'],
            'Programma-informatie'
        )

        self.note(
            box,
            'PTT Connect Radio Gateway — Windows Copper Edition'
        )

        self.note(
            box,
            'Lokale Windows-desktopapp; geen browser nodig.'
        )

        self.note(
            box,
            'Opgeslagen instellingen: ' + str(SETTINGS)
        )

        self.note(
            box,
            'Nog gepland: echte TeamSpeak-audio, RTL-SDR en server-crosslink.',
            '#ffb347'
        )

        ttk.Button(
            box,
            text='Alle instellingen opslaan',
            style='Copper.TButton',
            command=self.save_settings
        ).pack(
            anchor='w',
            pady=12
        )

    # MENUWISSELING

    def show_page(self, name):
        for page in self.pages.values():
            page.pack_forget()

        self.pages[name].pack(
            fill='both',
            expand=True
        )

        self.title.config(
            text=name
        )

        for n, button in self.nav.items():
            button.config(
                bg='#885022' if n == name else SIDE
            )

    # GELUIDSKAARTEN

    def refresh_devices(self, show_error=True):
        if sd is None:
            if show_error:
                messagebox.showerror(
                    'Audio',
                    'Installeer sounddevice via requirements.txt.'
                )
            return

        try:
            devices = sd.query_devices()

            self.input_devices = {
                f'{i}: {d["name"]}': i
                for i, d in enumerate(devices)
                if d['max_input_channels'] > 0
            }

            self.output_devices = {
                f'{i}: {d["name"]}': i
                for i, d in enumerate(devices)
                if d['max_output_channels'] > 0
            }

            options = [
                (
                    'input_device',
                    self.input_combo,
                    self.input_devices
                ),
                (
                    'output_device',
                    self.output_combo,
                    self.output_devices
                )
            ]

            for key, combo, mapping in options:
                combo['values'] = list(mapping)

                if (
                    self.vars[key].get() not in mapping
                    and mapping
                ):
                    self.vars[key].set(
                        next(iter(mapping))
                    )

        except Exception as exc:
            if show_error:
                messagebox.showerror(
                    'Audio',
                    str(exc)
                )

    # INSTELLINGEN OPSLAAN

    def current_settings(self):
        data = {
            k: v.get()
            for k, v in self.vars.items()
        }

        for key in (
            'gain',
            'threshold',
            'attack_ms',
            'release_ms'
        ):
            data[key] = int(
                float(data[key])
            )

        data['vox_enabled'] = (
            self.vox_enabled.get()
        )

        return data

    def save_settings(self):
        try:
            save(
                self.current_settings()
            )

            messagebox.showinfo(
                'Opgeslagen',
                'Instellingen zijn opgeslagen.'
            )

        except Exception as exc:
            messagebox.showerror(
                'Fout',
                str(exc)
            )

    # TEAMSPEAK TESTKNOPPEN

    def connect(self):
        messagebox.showinfo(
            'TeamSpeak — test',
            'TeamSpeak-spraak is nog niet ingebouwd. '
            'Er wordt geen verbinding gemaakt.'
        )

    def disconnect(self):
        self.connection_label.config(
            text='Status: niet verbonden'
        )

    # AUDIO TEST

    def toggle_monitor(self):
        if self.stream is not None:
            self.stop_monitor()
            return

        name = self.vars['input_device'].get()

        if (
            sd is None
            or name not in self.input_devices
        ):
            messagebox.showwarning(
                'Audio',
                'Selecteer een geldige audio-ingang.'
            )
            return

        try:
            self.stream = sd.InputStream(
                device=self.input_devices[name],
                channels=1,
                samplerate=16000,
                blocksize=320,
                dtype='float32',
                callback=self.on_audio
            )

            self.stream.start()

            self.monitor_button.config(
                text='Stop audiotest'
            )

            self.monitor_state.config(
                text='Audio-ingang: actief'
            )

        except Exception as exc:
            self.stream = None
            messagebox.showerror(
                'Audiotest',
                str(exc)
            )

    def on_audio(
        self,
        samples,
        frames,
        timing,
        status
    ):
        try:
            rms = math.sqrt(
                sum(
                    float(row[0]) ** 2
                    for row in samples
                ) / max(frames, 1)
            )

            try:
                self.events.put_nowait(
                    (
                        rms,
                        frames / 16.0
                    )
                )
            except queue.Full:
                pass

        except Exception:
            pass

    # AUDIOMETER EN VOX

    def update_meter(self):
        try:
            while True:
                rms, frame_ms = (
                    self.events.get_nowait()
                )

                self.level = min(
                    100.0,
                    rms * int(
                        self.vars['gain'].get()
                    )
                )

                threshold = int(
                    self.vars['threshold'].get()
                )

                if self.level >= threshold:
                    self.above += frame_ms
                    self.below = 0

                    if self.above >= int(
                        self.vars['attack_ms'].get()
                    ):
                        self.vox = True

                else:
                    self.below += frame_ms
                    self.above = 0

                    if self.below >= int(
                        self.vars['release_ms'].get()
                    ):
                        self.vox = False

        except queue.Empty:
            pass

        self.meter['value'] = self.level

        state = (
            'ACTIEF'
            if self.vox and self.vox_enabled.get()
            else 'uit'
        )

        self.meter_label.config(
            text=(
                f'Niveau: {self.level:.1f}%'
                f'  |  VOX: {state}'
            )
        )

        self.root.after(
            70,
            self.update_meter
        )

    # AUDIO STOPPEN

    def stop_monitor(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass

            self.stream = None

        self.monitor_button.config(
            text='Start audiotest'
        )

        self.monitor_state.config(
            text='Audio-ingang: niet actief'
        )

        self.level = 0
        self.vox = False
        self.above = 0
        self.below = 0

        while not self.events.empty():
            try:
                self.events.get_nowait()
            except queue.Empty:
                break

    # PROGRAMMA AFSLUITEN

    def close(self):
        self.stop_monitor()

        try:
            save(
                self.current_settings()
            )
        except Exception:
            pass

        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
