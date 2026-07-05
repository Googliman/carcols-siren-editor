from __future__ import annotations

import copy
import datetime
import hashlib
import json
import re
import threading
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from tkinter import colorchooser, filedialog, messagebox, ttk
from urllib.parse import quote

from carcols_io import argb_to_tk, export_carcols, import_carcols, normalize_argb_hex
from model import (
    CarcolsDocument,
    Light,
    LightType,
    SEQUENCER_PRESETS,
    SirenSetting,
    bits_to_sequencer,
    sequencer_to_bits,
)
from sample_data import build_sample_settings
from settings_store import load_settings, save_settings
from sirentool_io import parse_sirentool_export

ARGB_HEX_RE = re.compile(r"^0x[0-9A-Fa-f]{8}$")
DEFAULT_QUICK_COLORS = ["0xFFFF0000", "0xFF0000FF", "0xFF00FF00", "0xFFFFFFFF", "0xFFFFA500", "0xFFFF00FF"]

DEFAULT_APP_VERSION = "0.1.0-alpha"
GITHUB_REPO = "Googliman/carcols-siren-editor"

# Confirmed across 33 real carcols.meta files: the siren-level <textureName> only ever
# uses these three. Other "VehicleLight_car_*" textures exist in GTA V, but those belong
# to the separate headlight/indicator <Lights> section, not this field.
SIREN_TEXTURE_OPTIONS = ["VehicleLight_sirenlight", "VehicleLight_searchlight", "VehicleLight_misc_searchlight"]

# Not a real security boundary (this ships inside the compiled exe, so it can be
# decompiled) - just enough friction that a friend clicking around won't stumble
# into the version-editing tool. The key rotates daily so a code seen once can't
# be reused indefinitely. The actual salt/email live in dev_secret.py, which is
# gitignored so they never end up in the public repo - see dev_secret.example.py.
try:
    from dev_secret import DEV_KEY_SALT as _DEV_KEY_SALT, DEV_EMAIL as HARDCODED_DEV_EMAIL
except ImportError:
    _DEV_KEY_SALT = "local-dev-secret-not-configured"
    HARDCODED_DEV_EMAIL = "not-configured@example.com"


def todays_dev_key() -> str:
    today = datetime.date.today().isoformat()
    digest = hashlib.sha256((_DEV_KEY_SALT + today).encode()).hexdigest()
    return digest[:6].upper()


def _fetch_latest_release():
    """Unauthenticated call to GitHub's public API - no token needed since the repo
    is public. Returns (tag_name, html_url) or None if unreachable/no releases yet."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                "User-Agent": "CarcolsSirenEditor"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag_name = data.get("tag_name")
    html_url = data.get("html_url")
    if not tag_name or not html_url:
        return None
    return tag_name, html_url


def _open_gmail_compose_draft(to_address: str, code: str) -> None:
    """Opens Gmail's web compose view pre-filled in the default browser. More reliable
    than the OS 'mailto:' handler, which on this system (new Outlook) doesn't actually
    pre-fill a compose window - it just opens the Drafts folder."""
    subject = quote("Your Carcols Siren Editor developer code")
    body = quote(f"Today's developer key is: {code}")
    to = quote(to_address)
    url = f"https://mail.google.com/mail/?view=cm&fs=1&to={to}&su={subject}&body={body}"
    webbrowser.open(url)


def _is_valid_color_list(colors) -> bool:
    return (
        isinstance(colors, list)
        and len(colors) > 0
        and all(isinstance(c, str) and ARGB_HEX_RE.match(c) for c in colors)
    )


class LightRowWidget:
    def __init__(self, parent, light: Light, on_remove, quick_colors=None):
        self.light = light
        self.on_remove = on_remove
        self.quick_colors = quick_colors if quick_colors is not None else list(DEFAULT_QUICK_COLORS)
        self._preview_window = None
        self._preview_after_id = None
        self._preview_step = 0

        self.frame = ttk.LabelFrame(parent, text=light.name)
        self._build_widgets()

    def _build_widgets(self) -> None:
        light = self.light
        f = self.frame

        top = ttk.Frame(f)
        top.pack(fill=tk.X, padx=6, pady=(6, 2))

        self.name_var = tk.StringVar(value=light.name)
        name_entry = ttk.Entry(top, textvariable=self.name_var, width=16)
        name_entry.grid(row=0, column=0, padx=(0, 10))
        name_entry.bind("<KeyRelease>", self._on_name_change)

        ttk.Label(top, text="Color:").grid(row=0, column=1, sticky="e")
        self.color_btn = tk.Button(top, width=4, bg=argb_to_tk(light.color), command=self._pick_color,
                                    relief=tk.RAISED)
        self.color_btn.grid(row=0, column=2, padx=(4, 10))

        presets_frame = ttk.Frame(top)
        presets_frame.grid(row=0, column=3, padx=(0, 10))
        for hexcol in self.quick_colors:
            b = tk.Button(presets_frame, bg=argb_to_tk(hexcol), width=2, relief=tk.FLAT,
                          command=lambda c=hexcol: self._set_color(c))
            b.pack(side=tk.LEFT, padx=1)

        ttk.Label(top, text="Type:").grid(row=0, column=4, sticky="e")
        self.type_var = tk.StringVar(value=light.light_type.value)
        type_combo = ttk.Combobox(top, textvariable=self.type_var, width=9, state="readonly",
                                   values=[t.value for t in LightType])
        type_combo.grid(row=0, column=5, padx=(4, 10))
        type_combo.bind("<<ComboboxSelected>>", self._on_type_change)

        ttk.Button(top, text="Remove", command=self._on_remove_click).grid(row=0, column=6, padx=(10, 0))

        # Row 1: intensity + core flags
        mid = ttk.Frame(f)
        mid.pack(fill=tk.X, padx=6, pady=2)

        ttk.Label(mid, text="Intensity:").grid(row=0, column=0, sticky="w")
        self.intensity_var = tk.DoubleVar(value=light.intensity)
        intensity_spin = ttk.Spinbox(mid, from_=0.0, to=1000.0, increment=0.1, textvariable=self.intensity_var,
                                      width=8, command=self._on_intensity_change)
        intensity_spin.grid(row=0, column=1, padx=(4, 16))
        intensity_spin.bind("<KeyRelease>", self._on_intensity_change)
        intensity_spin.bind("<FocusOut>", self._on_intensity_change)

        self.rotate_var = tk.BooleanVar(value=light.rotate)
        ttk.Checkbutton(mid, text="Rotate", variable=self.rotate_var,
                        command=self._on_flags_change).grid(row=0, column=2, padx=(0, 10))

        self.flash_var = tk.BooleanVar(value=light.flash)
        ttk.Checkbutton(mid, text="Flash", variable=self.flash_var,
                        command=self._on_flags_change).grid(row=0, column=3, padx=(0, 10))

        self.emits_var = tk.BooleanVar(value=light.emits_light)
        ttk.Checkbutton(mid, text="Emits Light", variable=self.emits_var,
                        command=self._on_flags_change).grid(row=0, column=4, padx=(0, 10))

        self.spot_var = tk.BooleanVar(value=light.spot_light)
        ttk.Checkbutton(mid, text="Spotlight", variable=self.spot_var,
                        command=self._on_flags_change).grid(row=0, column=5, padx=(0, 10))

        self.shadows_var = tk.BooleanVar(value=light.cast_shadows)
        ttk.Checkbutton(mid, text="Cast Shadows", variable=self.shadows_var,
                        command=self._on_flags_change).grid(row=0, column=6)

        # Row 2: scale trick (fake-rotation via texture scaling) + corona glow
        mid2 = ttk.Frame(f)
        mid2.pack(fill=tk.X, padx=6, pady=2)

        self.scale_var = tk.BooleanVar(value=light.scale)
        ttk.Checkbutton(mid2, text="Scale Trick", variable=self.scale_var,
                        command=self._on_flags_change).grid(row=0, column=0, padx=(0, 6))

        ttk.Label(mid2, text="Scale Factor:").grid(row=0, column=1, sticky="e")
        self.scale_factor_var = tk.DoubleVar(value=light.scale_factor)
        scale_factor_spin = ttk.Spinbox(mid2, from_=0.0, to=1000.0, increment=0.5,
                                         textvariable=self.scale_factor_var, width=8, command=self._on_flags_change)
        scale_factor_spin.grid(row=0, column=2, padx=(4, 16))
        scale_factor_spin.bind("<KeyRelease>", self._on_flags_change)
        scale_factor_spin.bind("<FocusOut>", self._on_flags_change)

        ttk.Label(mid2, text="Corona Intensity:").grid(row=0, column=3, sticky="e")
        self.corona_intensity_var = tk.DoubleVar(value=light.corona.intensity)
        corona_intensity_spin = ttk.Spinbox(mid2, from_=0.0, to=1000.0, increment=0.1,
                                             textvariable=self.corona_intensity_var, width=8,
                                             command=self._on_corona_change)
        corona_intensity_spin.grid(row=0, column=4, padx=(4, 16))
        corona_intensity_spin.bind("<KeyRelease>", self._on_corona_change)
        corona_intensity_spin.bind("<FocusOut>", self._on_corona_change)

        ttk.Label(mid2, text="Corona Size:").grid(row=0, column=5, sticky="e")
        self.corona_size_var = tk.DoubleVar(value=light.corona.size)
        corona_size_spin = ttk.Spinbox(mid2, from_=0.0, to=1000.0, increment=0.1,
                                        textvariable=self.corona_size_var, width=8, command=self._on_corona_change)
        corona_size_spin.grid(row=0, column=6, padx=(4, 0))
        corona_size_spin.bind("<KeyRelease>", self._on_corona_change)
        corona_size_spin.bind("<FocusOut>", self._on_corona_change)

        # Sequencer grid (drives <flashiness><sequencer>, the actual on/off flash pattern)
        seq_frame = ttk.LabelFrame(f, text="Flash Sequence (32-step cycle)")
        seq_frame.pack(fill=tk.X, padx=6, pady=4)

        self.seq_vars = [tk.BooleanVar(value=bit) for bit in sequencer_to_bits(light.flashiness.sequencer)]
        self.seq_checkbuttons = []
        grid_frame = ttk.Frame(seq_frame)
        grid_frame.pack(side=tk.LEFT, padx=4, pady=4)
        for i, var in enumerate(self.seq_vars):
            cb = tk.Checkbutton(grid_frame, variable=var, command=self._on_sequencer_change,
                                 onvalue=True, offvalue=False, indicatoron=False,
                                 width=2, selectcolor=argb_to_tk(light.color),
                                 relief=tk.SUNKEN if var.get() else tk.RAISED, borderwidth=2)
            cb.grid(row=i // 16, column=i % 16, padx=1, pady=1)
            self.seq_checkbuttons.append(cb)

        preset_frame = ttk.Frame(seq_frame)
        preset_frame.pack(side=tk.LEFT, padx=10)
        ttk.Label(preset_frame, text="Preset:").pack(anchor="w")
        self.preset_var = tk.StringVar()
        preset_combo = ttk.Combobox(preset_frame, textvariable=self.preset_var,
                                     values=list(SEQUENCER_PRESETS.keys()), width=16, state="readonly")
        preset_combo.pack(anchor="w")
        preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)

        self.hex_label = ttk.Label(preset_frame, text=self._sequencer_hex_text())
        self.hex_label.pack(anchor="w", pady=(4, 0))

        ttk.Button(preset_frame, text="▶ Play", command=self._open_pattern_preview).pack(anchor="w", pady=(6, 0))

        # Rotation panel (<rotation> block: only meaningful when Rotate is checked)
        self.rotation_frame = ttk.LabelFrame(f, text="Rotation")
        self.rotation_frame.pack(fill=tk.X, padx=6, pady=(0, 6))

        ttk.Label(self.rotation_frame, text="Speed:").grid(row=0, column=0, sticky="w", padx=4)
        self.speed_var = tk.DoubleVar(value=light.rotation.speed)
        speed_spin = ttk.Spinbox(self.rotation_frame, from_=0.0, to=1000.0, increment=0.1,
                                  textvariable=self.speed_var, width=8, command=self._on_rotation_change)
        speed_spin.grid(row=0, column=1, padx=4)
        speed_spin.bind("<KeyRelease>", self._on_rotation_change)
        speed_spin.bind("<FocusOut>", self._on_rotation_change)

        self.direction_var = tk.StringVar(value="CW" if light.rotation.direction_cw else "CCW")
        ttk.Label(self.rotation_frame, text="Direction:").grid(row=0, column=2, sticky="w", padx=(16, 4))
        ttk.Radiobutton(self.rotation_frame, text="CW", value="CW", variable=self.direction_var,
                         command=self._on_rotation_change).grid(row=0, column=3)
        ttk.Radiobutton(self.rotation_frame, text="CCW", value="CCW", variable=self.direction_var,
                         command=self._on_rotation_change).grid(row=0, column=4)

        self.sync_var = tk.BooleanVar(value=light.rotation.sync_to_bpm)
        ttk.Checkbutton(self.rotation_frame, text="Sync to BPM", variable=self.sync_var,
                        command=self._on_rotation_change).grid(row=0, column=5, padx=(16, 4))

        ttk.Label(self.rotation_frame, text="Multiples:").grid(row=0, column=6, sticky="w", padx=(16, 4))
        self.multiples_var = tk.StringVar(value=str(light.rotation.multiples))
        multiples_entry = ttk.Entry(self.rotation_frame, textvariable=self.multiples_var, width=4)
        multiples_entry.grid(row=0, column=7)
        multiples_entry.bind("<KeyRelease>", self._on_rotation_change)

        self._update_rotation_enabled()

    def _sequencer_hex_text(self) -> str:
        return f"Pattern: 0x{self.light.flashiness.sequencer:08X}"

    def _on_name_change(self, event=None) -> None:
        self.light.name = self.name_var.get()
        self.frame.configure(text=self.light.name)

    def _pick_color(self) -> None:
        result = colorchooser.askcolor(initialcolor=argb_to_tk(self.light.color), title="Choose siren color")
        if result and result[1]:
            normalized = normalize_argb_hex(result[1])
            if normalized:
                self._set_color(normalized)

    def _set_color(self, argb_color: str) -> None:
        self.light.color = argb_color
        tk_color = argb_to_tk(argb_color)
        self.color_btn.configure(bg=tk_color)
        for cb in self.seq_checkbuttons:
            cb.configure(selectcolor=tk_color)

    def _on_type_change(self, event=None) -> None:
        self.light.light_type = LightType(self.type_var.get())
        self.light.apply_light_type_preset()
        self.rotate_var.set(self.light.rotate)
        self.flash_var.set(self.light.flash)
        self.scale_var.set(self.light.scale)
        self.scale_factor_var.set(self.light.scale_factor)
        self.corona_intensity_var.set(self.light.corona.intensity)
        self.corona_size_var.set(self.light.corona.size)
        self._update_rotation_enabled()

    def _on_intensity_change(self, event=None) -> None:
        try:
            self.light.intensity = round(float(self.intensity_var.get()), 2)
        except (tk.TclError, ValueError):
            pass

    def _on_flags_change(self, event=None) -> None:
        self.light.rotate = self.rotate_var.get()
        self.light.flash = self.flash_var.get()
        self.light.emits_light = self.emits_var.get()
        self.light.spot_light = self.spot_var.get()
        self.light.cast_shadows = self.shadows_var.get()
        self.light.scale = self.scale_var.get()
        try:
            self.light.scale_factor = round(float(self.scale_factor_var.get()), 2)
        except (tk.TclError, ValueError):
            pass
        self._update_rotation_enabled()

    def _on_corona_change(self, event=None) -> None:
        try:
            self.light.corona.intensity = round(float(self.corona_intensity_var.get()), 2)
        except (tk.TclError, ValueError):
            pass
        try:
            self.light.corona.size = round(float(self.corona_size_var.get()), 2)
        except (tk.TclError, ValueError):
            pass

    def _on_sequencer_change(self) -> None:
        bits = [v.get() for v in self.seq_vars]
        self.light.flashiness.sequencer = bits_to_sequencer(bits)
        self.hex_label.configure(text=self._sequencer_hex_text())
        self._refresh_sequencer_relief()

    def _refresh_sequencer_relief(self) -> None:
        for cb, var in zip(self.seq_checkbuttons, self.seq_vars):
            cb.configure(relief=tk.SUNKEN if var.get() else tk.RAISED)

    def _open_pattern_preview(self) -> None:
        if self._preview_window is not None and self._preview_window.winfo_exists():
            self._preview_window.lift()
            self._preview_window.focus_force()
            return

        win = tk.Toplevel(self.frame)
        win.title(f"Pattern Preview - {self.light.name}")
        win.resizable(False, False)
        self._preview_window = win
        self._preview_step = 0

        canvas = tk.Canvas(win, width=360, height=140, bg="#1e1e1e", highlightthickness=0)
        canvas.pack(padx=10, pady=10)

        light_circle = canvas.create_oval(150, 10, 210, 70, fill="#3a3a3a", outline="")

        cell_w = 10
        start_x = 20
        step_rects = [
            canvas.create_rectangle(start_x + i * cell_w, 95, start_x + i * cell_w + cell_w - 2, 115,
                                     fill="#555555", outline="")
            for i in range(32)
        ]

        speed_frame = ttk.Frame(win)
        speed_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Label(speed_frame, text="Speed (steps/sec):").pack(side=tk.LEFT)
        speed_var = tk.IntVar(value=8)
        ttk.Spinbox(speed_frame, from_=1, to=240, increment=1, textvariable=speed_var,
                    width=6).pack(side=tk.LEFT, padx=6)
        close_button = ttk.Button(speed_frame, text="Close")
        close_button.pack(side=tk.RIGHT)

        def tick():
            if not win.winfo_exists():
                return
            bits = sequencer_to_bits(self.light.flashiness.sequencer)
            step = self._preview_step
            is_on = bits[step]
            tk_color = argb_to_tk(self.light.color)
            canvas.itemconfig(light_circle, fill=tk_color if is_on else "#3a3a3a")
            for i, rect in enumerate(step_rects):
                on = bits[i]
                if i == step:
                    canvas.itemconfig(rect, fill=tk_color if on else "#555555", outline="#ffffff", width=2)
                else:
                    canvas.itemconfig(rect, fill=tk_color if on else "#555555", outline="")
            self._preview_step = (step + 1) % 32
            try:
                speed = max(1, speed_var.get())
            except (tk.TclError, ValueError):
                speed = 8
            delay_ms = int(1000 / speed)
            self._preview_after_id = win.after(delay_ms, tick)

        def on_close():
            if self._preview_after_id is not None:
                try:
                    win.after_cancel(self._preview_after_id)
                except tk.TclError:
                    pass
                self._preview_after_id = None
            win.destroy()
            self._preview_window = None

        close_button.configure(command=on_close)
        win.protocol("WM_DELETE_WINDOW", on_close)
        tick()

    def _on_preset_selected(self, event=None) -> None:
        name = self.preset_var.get()
        value = SEQUENCER_PRESETS.get(name)
        if value is None:
            return
        self.light.flashiness.sequencer = value
        for var, bit in zip(self.seq_vars, sequencer_to_bits(value)):
            var.set(bit)
        self.hex_label.configure(text=self._sequencer_hex_text())
        self._refresh_sequencer_relief()

    def _on_rotation_change(self, event=None) -> None:
        try:
            self.light.rotation.speed = round(float(self.speed_var.get()), 3)
        except (tk.TclError, ValueError):
            pass
        self.light.rotation.direction_cw = (self.direction_var.get() == "CW")
        self.light.rotation.sync_to_bpm = self.sync_var.get()
        try:
            self.light.rotation.multiples = int(self.multiples_var.get())
        except (tk.TclError, ValueError):
            pass

    def _update_rotation_enabled(self) -> None:
        state = "normal" if self.rotate_var.get() else "disabled"
        for child in self.rotation_frame.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

    def _on_remove_click(self) -> None:
        self.on_remove(self)


class CarcolsEditorApp:
    BASE_TITLE = "Carcols Siren Editor (Alpha)"

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(self.BASE_TITLE)
        root.geometry("1250x760")

        self.settings = build_sample_settings()
        self.raw_kits_element = None
        self.raw_lights_element = None
        self.current_index = None
        self.current_file_path = None
        self.light_rows = []
        saved = load_settings()
        saved_colors = saved.get("quick_colors")
        self.quick_colors = list(saved_colors) if _is_valid_color_list(saved_colors) else list(DEFAULT_QUICK_COLORS)
        self.app_version = saved.get("app_version") if isinstance(saved.get("app_version"), str) else DEFAULT_APP_VERSION
        self._settings_window = None
        self._dev_change_version_unlocked = False

        self._build_menu()
        self._build_layout()
        self._refresh_settings_list()
        if self.settings:
            self._select_setting(0)

        self.root.bind_all("<Control-Alt-F12>", self._open_dev_key_prompt)
        self._check_for_updates()

    def _check_for_updates(self) -> None:
        def worker():
            try:
                result = _fetch_latest_release()
            except (urllib.error.URLError, TimeoutError, ValueError, OSError):
                return
            if result is None:
                return
            tag_name, html_url = result
            self.root.after(0, lambda: self._maybe_show_update_notice(tag_name, html_url))

        threading.Thread(target=worker, daemon=True).start()

    def _maybe_show_update_notice(self, latest_tag: str, release_url: str) -> None:
        latest_version = latest_tag.lstrip("vV")
        if latest_version == self.app_version:
            return

        win = tk.Toplevel(self.root)
        win.title("Update Available")
        win.resizable(False, False)

        ttk.Label(win, text=f"A new version is available: {latest_tag}",
                  font=("Segoe UI", 10, "bold")).pack(padx=20, pady=(16, 4))
        ttk.Label(win, text=f"You're currently on {self.app_version}.").pack(padx=20, pady=(0, 12))

        button_frame = ttk.Frame(win)
        button_frame.pack(pady=(0, 16))
        ttk.Button(button_frame, text="Open Release Page",
                   command=lambda: webbrowser.open(release_url)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="Dismiss", command=win.destroy).pack(side=tk.LEFT)

    def _build_menu(self) -> None:
        self.menubar = tk.Menu(self.root, tearoff=0)
        file_menu = tk.Menu(self.menubar, tearoff=0)
        file_menu.add_command(label="New Siren Setting", command=self.new_setting)
        file_menu.add_separator()
        file_menu.add_command(label="Import carcols.meta...", command=self.import_file)
        file_menu.add_command(label="Export carcols.meta...", command=self.export_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        self.menubar.add_cascade(label="File", menu=file_menu)
        self.menubar.add_command(label="Import SirenTool", command=self.import_sirentool_file)
        self.menubar.add_command(label="Settings", command=self.open_settings_window)
        self.menubar.add_command(label="Version", command=self.open_version_window)
        self.root.config(menu=self.menubar)

    def _build_layout(self) -> None:
        paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(paned, width=250)
        paned.add(left_frame, weight=1)

        ttk.Label(left_frame, text="Siren Settings", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self.settings_listbox = tk.Listbox(left_frame, exportselection=False)
        self.settings_listbox.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.settings_listbox.bind("<<ListboxSelect>>", self._on_setting_selected)

        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, padx=8, pady=4)
        ttk.Button(btn_frame, text="Add", command=self.new_setting).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(btn_frame, text="Duplicate", command=self.duplicate_setting).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(btn_frame, text="Remove", command=self.remove_setting).pack(side=tk.LEFT, expand=True, fill=tk.X)

        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=4)

        header = ttk.Frame(right_frame)
        header.pack(fill=tk.X, padx=10, pady=8)

        self.name_var = tk.StringVar()
        self.id_var = tk.StringVar()
        self.texture_var = tk.StringVar()

        ttk.Label(header, text="Name:").grid(row=0, column=0, sticky="w")
        name_entry = ttk.Entry(header, textvariable=self.name_var, width=28)
        name_entry.grid(row=0, column=1, sticky="w", padx=(4, 16))
        name_entry.bind("<KeyRelease>", self._on_header_changed)

        ttk.Label(header, text="ID:").grid(row=0, column=2, sticky="w")
        id_entry = ttk.Entry(header, textvariable=self.id_var, width=10)
        id_entry.grid(row=0, column=3, sticky="w", padx=(4, 16))
        id_entry.bind("<KeyRelease>", self._on_header_changed)

        ttk.Label(header, text="Texture:").grid(row=0, column=4, sticky="w")
        texture_combo = ttk.Combobox(header, textvariable=self.texture_var, width=26,
                                      values=SIREN_TEXTURE_OPTIONS)
        texture_combo.grid(row=0, column=5, sticky="w", padx=(4, 0))
        texture_combo.bind("<KeyRelease>", self._on_header_changed)
        texture_combo.bind("<<ComboboxSelected>>", self._on_header_changed)

        ttk.Separator(right_frame).pack(fill=tk.X, padx=10, pady=(0, 6))

        lights_container = ttk.Frame(right_frame)
        lights_container.pack(fill=tk.BOTH, expand=True, padx=10)

        canvas = tk.Canvas(lights_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(lights_container, orient=tk.VERTICAL, command=canvas.yview)
        self.lights_frame = ttk.Frame(canvas)

        self.lights_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.lights_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        add_light_bar = ttk.Frame(right_frame)
        add_light_bar.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(add_light_bar, text="+ Add Light", command=self.add_light).pack(side=tk.LEFT)

    def _refresh_settings_list(self) -> None:
        self.settings_listbox.delete(0, tk.END)
        for s in self.settings:
            self.settings_listbox.insert(tk.END, f"[{s.id}] {s.name}")

    def _on_setting_selected(self, event=None) -> None:
        sel = self.settings_listbox.curselection()
        if not sel:
            return
        self._select_setting(sel[0])

    def _select_setting(self, index: int) -> None:
        self.current_index = index
        setting = self.settings[index]
        self.name_var.set(setting.name)
        self.id_var.set(str(setting.id))
        self.texture_var.set(setting.texture_name)
        self._rebuild_light_rows()
        self.settings_listbox.selection_clear(0, tk.END)
        self.settings_listbox.selection_set(index)

    def _current_setting(self):
        if self.current_index is None:
            return None
        return self.settings[self.current_index]

    def _on_header_changed(self, event=None) -> None:
        setting = self._current_setting()
        if setting is None:
            return
        setting.name = self.name_var.get()
        try:
            setting.id = int(self.id_var.get())
        except ValueError:
            pass
        setting.texture_name = self.texture_var.get()

        idx = self.current_index
        self.settings_listbox.delete(idx)
        self.settings_listbox.insert(idx, f"[{setting.id}] {setting.name}")
        self.settings_listbox.selection_set(idx)

    def _rebuild_light_rows(self) -> None:
        for row in self.light_rows:
            row.frame.destroy()
        self.light_rows.clear()
        setting = self._current_setting()
        if setting is None:
            return
        for light in setting.lights:
            self._add_light_row(light)

    def _add_light_row(self, light: Light) -> None:
        row = LightRowWidget(self.lights_frame, light, on_remove=self._remove_light_row,
                              quick_colors=self.quick_colors)
        row.frame.pack(fill=tk.X, pady=6, padx=2)
        self.light_rows.append(row)

    def add_light(self) -> None:
        setting = self._current_setting()
        if setting is None:
            messagebox.showinfo("No siren selected", "Add or select a siren setting first.")
            return
        new_light = Light(name=f"Light {len(setting.lights) + 1}", color=self.quick_colors[0])
        setting.lights.append(new_light)
        self._add_light_row(new_light)

    def _remove_light_row(self, row: LightRowWidget) -> None:
        setting = self._current_setting()
        if setting is None:
            return
        if row.light in setting.lights:
            setting.lights.remove(row.light)
        row.frame.destroy()
        self.light_rows.remove(row)

    def new_setting(self) -> None:
        new_id = max([s.id for s in self.settings], default=0) + 1
        setting = SirenSetting(id=new_id, name=f"New Siren {new_id}")
        setting.lights.append(Light(name="Light 1", color=self.quick_colors[0]))
        self.settings.append(setting)
        self._refresh_settings_list()
        self._select_setting(len(self.settings) - 1)

    def duplicate_setting(self) -> None:
        setting = self._current_setting()
        if setting is None:
            return
        new_setting = copy.deepcopy(setting)
        new_setting.id = max(s.id for s in self.settings) + 1
        new_setting.name = f"{setting.name} Copy"
        self.settings.append(new_setting)
        self._refresh_settings_list()
        self._select_setting(len(self.settings) - 1)

    def remove_setting(self) -> None:
        if self.current_index is None:
            return
        if not messagebox.askyesno("Remove Siren Setting", "Remove the selected siren setting?"):
            return
        del self.settings[self.current_index]
        self._refresh_settings_list()
        if self.settings:
            self._select_setting(0)
        else:
            self.current_index = None
            self._rebuild_light_rows()
            self.name_var.set("")
            self.id_var.set("")
            self.texture_var.set("")

    def import_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Import carcols.meta",
            filetypes=[("Carcols meta files", "*.meta *.xml"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            document = import_carcols(path)
        except Exception as exc:
            messagebox.showerror("Import failed", f"Could not import file:\n{exc}")
            return
        if not document.siren_settings:
            messagebox.showwarning("Import", "No siren settings were found in that file.")
            return
        self.settings = document.siren_settings
        self.raw_kits_element = document.raw_kits_element
        self.raw_lights_element = document.raw_lights_element
        self.current_file_path = path
        self._refresh_settings_list()
        self._select_setting(0)
        messagebox.showinfo("Import complete", f"Imported {len(document.siren_settings)} siren setting(s).")

    def import_sirentool_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Import SirenTool Export",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            sequences = parse_sirentool_export(path)
        except Exception as exc:
            messagebox.showerror("Import failed", f"Could not import SirenTool export:\n{exc}")
            return
        setting = self._current_setting()
        if setting is None or not setting.lights:
            messagebox.showinfo(
                "No sirens to assign",
                "Select (or create) a siren setting with at least one light first, then import again.",
            )
            return
        self._open_sirentool_assign_window(sequences, setting)

    def _open_sirentool_assign_window(self, sequences, setting: SirenSetting) -> None:
        win = tk.Toplevel(self.root)
        win.title("Assign SirenTool Sequences")
        win.resizable(False, False)

        ttk.Label(win, text=f"Assign a sequence to each siren in \"{setting.name}\"",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 2))
        ttk.Label(
            win,
            text="Multiple sirens can share the same sequence. Leave \"-- none --\" to keep a "
                 "siren's current flash pattern.",
            wraplength=440,
        ).pack(anchor="w", padx=10, pady=(0, 8))

        none_label = "-- none --"
        seq_labels = [none_label] + [
            f"Seq {i + 1}: {seq.color_name} (0x{seq.sequencer:08X})" for i, seq in enumerate(sequences)
        ]

        rows_frame = ttk.Frame(win)
        rows_frame.pack(fill=tk.BOTH, padx=10, pady=4)

        assignments = []
        for light in setting.lights:
            row = ttk.Frame(rows_frame)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, width=2, relief=tk.SUNKEN, bg=argb_to_tk(light.color)).pack(side=tk.LEFT, padx=(0, 6))
            ttk.Label(row, text=light.name, width=20).pack(side=tk.LEFT)
            var = tk.StringVar(value=none_label)
            combo = ttk.Combobox(row, textvariable=var, values=seq_labels, state="readonly", width=34)
            combo.pack(side=tk.LEFT, padx=(6, 0))
            assignments.append((light, var))

        button_frame = ttk.Frame(win)
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        def apply_and_close():
            applied = 0
            for light, var in assignments:
                label = var.get()
                if label == none_label:
                    continue
                idx = seq_labels.index(label) - 1
                light.flashiness.sequencer = sequences[idx].sequencer
                applied += 1
            self._rebuild_light_rows()
            win.destroy()
            messagebox.showinfo("Sequences applied", f"Updated {applied} siren(s).")

        ttk.Button(button_frame, text="Apply", command=apply_and_close).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(button_frame, text="Cancel", command=win.destroy).pack(side=tk.RIGHT)

    def export_file(self) -> None:
        if not self.settings:
            messagebox.showinfo("Nothing to export", "Add at least one siren setting first.")
            return
        path = filedialog.asksaveasfilename(
            title="Export carcols.meta",
            defaultextension=".meta",
            initialfile="carcols.meta",
            filetypes=[("Carcols meta files", "*.meta"), ("XML files", "*.xml"), ("All files", "*.*")],
        )
        if not path:
            return
        document = CarcolsDocument(
            siren_settings=self.settings,
            raw_kits_element=self.raw_kits_element,
            raw_lights_element=self.raw_lights_element,
        )
        try:
            export_carcols(document, path)
        except Exception as exc:
            messagebox.showerror("Export failed", f"Could not export file:\n{exc}")
            return
        self.current_file_path = path
        messagebox.showinfo("Export complete", f"Saved to:\n{path}")

    def open_settings_window(self) -> None:
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.resizable(False, False)
        self._settings_window = win

        ttk.Label(win, text="Light Color Presets", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=10, pady=(10, 2))
        ttk.Label(
            win,
            text="Hex values (0xAARRGGBB) used for the quick color-swatch buttons on each light row.",
            wraplength=320,
        ).pack(anchor="w", padx=10, pady=(0, 8))

        entries_frame = ttk.Frame(win)
        entries_frame.pack(fill=tk.X, padx=10)

        hex_vars = []
        for i, color in enumerate(self.quick_colors):
            row = ttk.Frame(entries_frame)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"Preset {i + 1}:", width=10).pack(side=tk.LEFT)

            var = tk.StringVar(value=color)
            hex_vars.append(var)
            entry = ttk.Entry(row, textvariable=var, width=14)
            entry.pack(side=tk.LEFT, padx=(4, 8))

            swatch = tk.Label(row, width=3, relief=tk.SUNKEN, bg=argb_to_tk(color))
            swatch.pack(side=tk.LEFT)

            def on_key(event, v=var, s=swatch):
                normalized = normalize_argb_hex(v.get())
                if normalized:
                    s.configure(bg=argb_to_tk(normalized))

            def on_focus_out(event, v=var, s=swatch):
                normalized = normalize_argb_hex(v.get())
                if normalized:
                    v.set(normalized)
                    s.configure(bg=argb_to_tk(normalized))

            entry.bind("<KeyRelease>", on_key)
            entry.bind("<FocusOut>", on_focus_out)

        button_frame = ttk.Frame(win)
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        def collect_valid_values():
            raw_values = [v.get().strip() for v in hex_vars]
            normalized = [normalize_argb_hex(v) for v in raw_values]
            invalid = [raw for raw, norm in zip(raw_values, normalized) if norm is None]
            if invalid:
                messagebox.showerror(
                    "Invalid color",
                    "These aren't valid hex colors (use 0xAARRGGBB or #RRGGBB):\n" + ", ".join(invalid),
                )
                return None
            return normalized

        def save_and_close():
            values = collect_valid_values()
            if values is None:
                return
            self.quick_colors[:] = values
            self._rebuild_light_rows()
            data = load_settings()
            data["quick_colors"] = self.quick_colors
            save_settings(data)
            win.destroy()
            self._settings_window = None

        def cancel():
            win.destroy()
            self._settings_window = None

        ttk.Button(button_frame, text="Save & Close", command=save_and_close).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(button_frame, text="Cancel", command=cancel).pack(side=tk.RIGHT)

        win.protocol("WM_DELETE_WINDOW", cancel)

    def open_version_window(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Version")
        win.resizable(False, False)

        ttk.Label(win, text="Carcols Siren Editor", font=("Segoe UI", 12, "bold")).pack(padx=24, pady=(20, 4))
        ttk.Label(win, text=f"Version {self.app_version}").pack(padx=24, pady=(0, 16))
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 16))

    def _open_dev_key_prompt(self, event=None) -> None:
        if self._dev_change_version_unlocked:
            return

        win = tk.Toplevel(self.root)
        win.title("Developer Verification")
        win.resizable(False, False)

        ttk.Label(win, text="Enter your developer email:").pack(padx=16, pady=(16, 4))
        email_var = tk.StringVar()
        entry = ttk.Entry(win, textvariable=email_var, width=28)
        entry.pack(padx=16, pady=(0, 8))
        entry.focus_set()

        def submit_email(event=None):
            if email_var.get().strip().lower() == HARDCODED_DEV_EMAIL.lower():
                win.destroy()
                _open_gmail_compose_draft(HARDCODED_DEV_EMAIL, todays_dev_key())
                self._open_dev_code_prompt()
            else:
                messagebox.showerror("Not recognized", "That email isn't recognized.")

        entry.bind("<Return>", submit_email)
        button_frame = ttk.Frame(win)
        button_frame.pack(pady=(0, 16))
        ttk.Button(button_frame, text="Submit", command=submit_email).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="Cancel", command=win.destroy).pack(side=tk.LEFT)

    def _open_dev_code_prompt(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Enter Developer Code")
        win.resizable(False, False)

        ttk.Label(
            win,
            text="A Gmail compose draft with your code has been opened in your\nbrowser - send it, then enter the code below:",
            justify=tk.LEFT,
        ).pack(padx=16, pady=(16, 4))
        key_var = tk.StringVar()
        entry = ttk.Entry(win, textvariable=key_var, show="*", width=20)
        entry.pack(padx=16, pady=(0, 8))
        entry.focus_set()

        def submit(event=None):
            if key_var.get().strip().upper() == todays_dev_key():
                win.destroy()
                self._enter_dev_mode()
            else:
                messagebox.showerror("Incorrect code", "That code isn't valid.")

        entry.bind("<Return>", submit)
        button_frame = ttk.Frame(win)
        button_frame.pack(pady=(0, 16))
        ttk.Button(button_frame, text="Submit", command=submit).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="Cancel", command=win.destroy).pack(side=tk.LEFT)

    def _enter_dev_mode(self) -> None:
        if self._dev_change_version_unlocked:
            return
        self._dev_change_version_unlocked = True
        self._dev_menu_start_index = self.menubar.index("end") + 1
        self.menubar.add_command(label="Change Version", command=self._open_change_version_window)
        self.menubar.add_command(label="Exit Dev Mode", command=self._exit_dev_mode)
        self.root.title(f"{self.BASE_TITLE} - dev mode")

    def _exit_dev_mode(self) -> None:
        if not self._dev_change_version_unlocked:
            return
        self._dev_change_version_unlocked = False
        self.menubar.delete(self._dev_menu_start_index, self._dev_menu_start_index + 1)
        self.root.title(self.BASE_TITLE)

    def _open_change_version_window(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Change Version")
        win.resizable(False, False)

        ttk.Label(win, text="New version string:").pack(padx=16, pady=(16, 4))
        version_var = tk.StringVar(value=self.app_version)
        entry = ttk.Entry(win, textvariable=version_var, width=24)
        entry.pack(padx=16, pady=(0, 8))
        entry.focus_set()

        def save_version(event=None):
            new_version = version_var.get().strip()
            if not new_version:
                messagebox.showerror("Invalid version", "Version can't be empty.")
                return
            self.app_version = new_version
            data = load_settings()
            data["app_version"] = new_version
            save_settings(data)
            win.destroy()
            messagebox.showinfo("Version updated", f"Version changed to: {new_version}")

        entry.bind("<Return>", save_version)
        button_frame = ttk.Frame(win)
        button_frame.pack(pady=(0, 16))
        ttk.Button(button_frame, text="Save", command=save_version).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="Cancel", command=win.destroy).pack(side=tk.LEFT)
