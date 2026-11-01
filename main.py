"""PTT Connect Radio Gateway - Windows desktop prototype.

Hardware/audio setup test only. A native TeamSpeak voice transport is NOT implemented.
"""
import json
import math
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import sounddevice as sd
except ImportError:
    sd = None

APP_NAME = 'PTT Connect Radio Gateway'
CONFIG_DIR = Path(os.getenv('APPDATA') or (Path.home() / '.config')) / 'PTTConnectRadioGateway'
CONFIG_FILE = CONFIG_DIR / 'settings.json'
DEFAULTS = {
    'server': 'ptt.mijnts3.nl', 'nickname': 'Radio Gateway', 'channel': '',
    'input_device': '', 'output_device': '', 'gain': 100,
    'threshold': 12, 'attack_ms': 150, 'release_ms': 950,
    'mode': 'RX/TX', 'vox_enabled': True,
}


def load_config():
    config = dict(DEFAULTS)
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        if isinstance(saved, dict):
            config.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError, TypeError):
        pass
    return config


def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(CONFIG_FILE)


def compute_vox(level, threshold, above_ms, below_ms, active, attack, release, frame_ms):
    """Return VOX state with attack and release hysteresis."""
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
        self.root.title(APP_NAME + ' — Windows test')
        self.root.geometry('860x745')
        self.root.minsize(730, 660)
        self.root.configure(bg='#101827')
        self.cfg = load_config()
        self.vars = {k: tk.StringVar(value=str(v)) for k, v in self.cfg.items() if k != 'vox_enabled'}
        self.vox_enabled = tk.BooleanVar(value=bool(self.cfg['vox_enabled']))
        self.stream = None
        self.monitoring = False
        self.events = queue.Queue(maxsize=10)
        self.level = 0.0
        self.gain_value = float(self.cfg['gain']) / 100.0
        self.vox_on = False
        self.above_ms = 0
        self.below_ms = 0
        self.device_names = {}
        self.output_names = {}
        self._build()
        self.refresh_devices()
        self.root.after(70, self.update_meter)
        self.root.protocol('WM_DELETE_WINDOW', self.close)

    def _build(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('Dark.TFrame', background='#101827')
        style.configure('Dark.TLabel', background='#101827', foreground='#e9f2ff', font=('Segoe UI', 10))
        style.configure('Title.TLabel', background='#101827', foreground='#e9f2ff', font=('Segoe UI Semibold', 20))
        style.configure('Sub.TLabel', background='#101827', foreground='#9baec5', font=('Segoe UI', 9))
        style.configure('Dark.TLabelframe', background='#101827', foreground='#e9f2ff')
        style.configure('Dark.TLabelframe.Label', background='#101827', foreground='#84d6fa', font=('Segoe UI Semibold', 11))
        style.configure('Dark.TCheckbutton', background='#101827', foreground='#e9f2ff')
        style.configure('Dark.TCombobox', padding=4)
        top = ttk.Frame(self.root, style='Dark.TFrame', padding=18)
        top.pack(fill='both', expand=True)
        ttk.Label(top, text='PTT CONNECT  |  RADIO GATEWAY', style='Title.TLabel').pack(anchor='w')
        ttk.Label(top, text='Windows test • USB- of PC-geluidskaart • TeamSpeak-spraakbrug volgt later', style='Sub.TLabel').pack(anchor='w', pady=(0, 14))
        ts = ttk.LabelFrame(top, text=' TeamSpeak — instellingen ', style='Dark.TLabelframe', padding=12)
        ts.pack(fill='x', pady=(0, 10))
        self.grid_entry(ts, 'Serveradres', 'server', 0)
        self.grid_entry(ts, 'Gebruikersnaam', 'nickname', 1)
        self.grid_entry(ts, 'Kanaalnaam / ID', 'channel', 2)
        ttk.Label(ts, text='Modus', style='Dark.TLabel').grid(row=3, column=0, sticky='w', pady=4)
        ttk.Combobox(ts, textvariable=self.vars['mode'], values=['RX', 'TX', 'RX/TX'], state='readonly', width=25).grid(row=3, column=1, sticky='ew', padx=8)
        ts.columnconfigure(1, weight=1)
        bar = ttk.Frame(ts, style='Dark.TFrame')
        bar.grid(row=4, column=0, columnspan=2, sticky='w', pady=(10, 2))
        ttk.Button(bar, text='Verbinden', command=self.connect).pack(side='left', padx=(0, 8))
        ttk.Button(bar, text='Verbreken', command=self.disconnect).pack(side='left')
        self.connection_text = ttk.Label(ts, text='Status: niet verbonden (spraakclient nog niet ingebouwd)', style='Sub.TLabel')
        self.connection_text.grid(row=5, column=0, columnspan=2, sticky='w', pady=(7, 0))

        audio = ttk.LabelFrame(top, text=' Audioapparaten ', style='Dark.TLabelframe', padding=12)
        audio.pack(fill='x', pady=(0, 10))
        ttk.Label(audio, text='Audio-ingang', style='Dark.TLabel').grid(row=0, column=0, sticky='w', pady=5)
        self.input_combo = ttk.Combobox(audio, textvariable=self.vars['input_device'], state='readonly')
        self.input_combo.grid(row=0, column=1, sticky='ew', padx=8)
        ttk.Label(audio, text='Audio-uitgang', style='Dark.TLabel').grid(row=1, column=0, sticky='w', pady=5)
        self.output_combo = ttk.Combobox(audio, textvariable=self.vars['output_device'], state='readonly')
        self.output_combo.grid(row=1, column=1, sticky='ew', padx=8)
        ttk.Button(audio, text='Vernieuwen', command=self.refresh_devices).grid(row=0, column=2, rowspan=2, padx=3)
        audio.columnconfigure(1, weight=1)

        vox = ttk.LabelFrame(top, text=' Audio & VOX ', style='Dark.TLabelframe', padding=12)
        vox.pack(fill='x', pady=(0, 10))
        self.make_slider(vox, 'Ingangsvolume (%)', 'gain', 0, 200, 0)
        self.make_slider(vox, 'VOX-drempel (%)', 'threshold', 1, 100, 1)
        self.make_slider(vox, 'Triggertijd (ms)', 'attack_ms', 0, 2000, 2)
        self.make_slider(vox, 'Afvaltijd (ms)', 'release_ms', 100, 5000, 3)
        ttk.Checkbutton(vox, text='VOX inschakelen', variable=self.vox_enabled, style='Dark.TCheckbutton').grid(row=4, column=0, sticky='w', pady=6)
        self.meter = ttk.Progressbar(vox, maximum=100, length=400, mode='determinate')
        self.meter.grid(row=5, column=0, columnspan=2, sticky='ew', pady=6)
        self.level_text = ttk.Label(vox, text='Niveau: 0%  |  VOX: uit', style='Dark.TLabel')
        self.level_text.grid(row=6, column=0, columnspan=2, sticky='w')
        vox.columnconfigure(1, weight=1)

        actions = ttk.Frame(top, style='Dark.TFrame')
        actions.pack(fill='x', pady=8)
        self.monitor_button = ttk.Button(actions, text='Start audiotest', command=self.toggle_monitor)
        self.monitor_button.pack(side='left', padx=(0, 8))
        ttk.Button(actions, text='Instellingen opslaan', command=self.save).pack(side='left')
        ttk.Label(top, text='LET OP: audiotest meet alleen de INGANG. Er wordt nog geen geluid naar TeamSpeak verzonden.', style='Sub.TLabel').pack(anchor='w', pady=(6, 0))
        ttk.Label(top, text='Kies een ingebouwde microfoon/line-in of een USB-geluidskaart. Een zendende radio moet correct worden aangesloten.', style='Sub.TLabel').pack(anchor='w', pady=(2, 0))

    def grid_entry(self, frame, label, key, row):
        ttk.Label(frame, text=label, style='Dark.TLabel').grid(row=row, column=0, sticky='w', pady=4)
        ttk.Entry(frame, textvariable=self.vars[key]).grid(row=row, column=1, sticky='ew', padx=8, pady=4)

    def make_slider(self, frame, label, key, minimum, maximum, row):
        line = ttk.Frame(frame, style='Dark.TFrame')
        line.grid(row=row, column=0, columnspan=2, sticky='ew', pady=2)
        ttk.Label(line, text=label, style='Dark.TLabel', width=23).pack(side='left')
        val = tk.DoubleVar(value=float(self.vars[key].get()))
        tk.Scale(line, from_=minimum, to=maximum, variable=val, orient='horizontal', length=370,
                 resolution=1, bg='#101827', fg='#e9f2ff', troughcolor='#283e58',
                 highlightthickness=0, activebackground='#3abdeb', showvalue=True,
                 command=lambda x, k=key: self.vars[k].set(str(int(float(x))))).pack(side='left', fill='x', expand=True)

    def refresh_devices(self):
        if sd is None:
            messagebox.showwarning('Audio', 'De sounddevice-module ontbreekt. Installeer de requirements.')
            return
        try:
            devices = sd.query_devices()
            self.device_names = {f'{i}: {d["name"]}': i for i, d in enumerate(devices) if d['max_input_channels'] > 0}
            self.output_names = {f'{i}: {d["name"]}': i for i, d in enumerate(devices) if d['max_output_channels'] > 0}
            self.input_combo['values'] = list(self.device_names)
            self.output_combo['values'] = list(self.output_names)
            if self.vars['input_device'].get() not in self.device_names and self.device_names:
                self.vars['input_device'].set(next(iter(self.device_names)))
            if self.vars['output_device'].get() not in self.output_names and self.output_names:
                self.vars['output_device'].set(next(iter(self.output_names)))
        except Exception as exc:
            messagebox.showerror('Audioapparaten', str(exc))

    def current_config(self):
        c = {k: v.get() for k, v in self.vars.items()}
        for key in ('gain', 'threshold', 'attack_ms', 'release_ms'):
            c[key] = int(float(c[key]))
        c['vox_enabled'] = self.vox_enabled.get()
        return c

    def save(self):
        try:
            save_config(self.current_config())
            messagebox.showinfo('Opgeslagen', f'Instellingen opgeslagen in:\n{CONFIG_FILE}')
        except Exception as exc:
            messagebox.showerror('Opslaan mislukt', str(exc))

    def connect(self):
        messagebox.showinfo('TeamSpeak — testversie',
            'De knop Verbinden is handmatig, zoals afgesproken.\n\n'
            'De echte TeamSpeak-spraakclient is nog NIET ingebouwd. '
            'Er wordt dus geen verbinding gemaakt.\n\n'
            'Test eerst de geluidskaart en VOX met “Start audiotest”.')

    def disconnect(self):
        self.connection_text.configure(text='Status: niet verbonden (spraakclient nog niet ingebouwd)')

    def toggle_monitor(self):
        if self.monitoring:
            self.stop_monitor()
            return
        if sd is None:
            messagebox.showerror('Audio', 'sounddevice is niet geïnstalleerd.')
            return
        device_label = self.vars['input_device'].get()
        if device_label not in self.device_names:
            messagebox.showwarning('Audio', 'Selecteer eerst een audio-ingang.')
            return
        device = self.device_names[device_label]
        try:
            self.stream = sd.InputStream(device=device, channels=1, samplerate=16000,
                                         blocksize=320, dtype='float32', callback=self.audio_callback)
            self.stream.start()
        except Exception as exc:
            self.stream = None
            messagebox.showerror('Audiotest', f'Kan de ingang niet openen:\n{exc}')
            return
        self.monitoring = True
        self.monitor_button.configure(text='Stop audiotest')

    def audio_callback(self, indata, frames, time_info, status):
        try:
            # RMS input amplitude: 0..100%; gain applies to the measurement only.
            gain = self.gain_value
            rms = math.sqrt(sum(float(x[0]) ** 2 for x in indata) / max(len(indata), 1))
            level = max(0.0, min(100.0, rms * gain * 100.0))
            try:
                self.events.put_nowait((level, frames * 1000.0 / 16000.0))
            except queue.Full:
                pass
        except Exception:
            pass

    def update_meter(self):
        self.gain_value = float(self.vars['gain'].get()) / 100.0
        try:
            while True:
                level, frame_ms = self.events.get_nowait()
                self.level = level
                self.vox_on, self.above_ms, self.below_ms = compute_vox(
                    level, float(self.vars['threshold'].get()), self.above_ms,
                    self.below_ms, self.vox_on, float(self.vars['attack_ms'].get()),
                    float(self.vars['release_ms'].get()), frame_ms)
        except queue.Empty:
            pass
        self.meter['value'] = self.level
        state = 'ACTIEF' if (self.vox_on and self.vox_enabled.get()) else 'uit'
        self.level_text.configure(text=f'Niveau: {self.level:.1f}%  |  VOX: {state}')
        self.root.after(70, self.update_meter)

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
        self.above_ms = self.below_ms = 0
        self.vox_on = False
        self.monitor_button.configure(text='Start audiotest')

    def close(self):
        self.stop_monitor()
        try:
            save_config(self.current_config())
        except Exception:
            pass
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    GatewayApp(root)
    root.mainloop()
