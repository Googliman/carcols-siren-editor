# Carcols Siren Editor

A desktop tool for editing GTA V / FiveM vehicle `carcols.meta` siren settings — colors,
flash sequences, rotation, LED/Halogen/Rotator behavior — without hand-editing XML.

## Features

- Import/export real `carcols.meta` files (validated against real-world vehicle packs)
- Per-light color picker, quick-color presets (customizable, persisted)
- 32-step flash sequence editor with a live pattern preview
- Rotation controls (speed, direction, sync-to-BPM, multiples)
- Import [Siren Tool](https://doc.clickup.com/d/841f5-35/non-els-research/841f5-49/carcols-meta)
  exports and assign sequences to sirens
- Preserves the `<Lights>`/`<Kits>` sections and per-siren XML comments on round-trip

## Running from source

Requires Python 3.9+ with Tkinter (bundled with the standard python.org installer).

```
python main.py
```

## Building a standalone exe

```
pip install pyinstaller
pyinstaller --onefile --windowed --name "CarcolsSirenEditorAlpha" main.py
```

## Development

Copy `dev_secret.example.py` to `dev_secret.py` (gitignored) and set your own values
if you want the hidden developer tools to work locally.
