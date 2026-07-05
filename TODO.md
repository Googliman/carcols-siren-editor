# Carcols Siren Editor - To Do / Open Items

- [ ] `<Lights>` (indicators/headlights/taillights) and `<Kits>` sections are preserved
      on import/export but not editable in the UI - passthrough only.
- [ ] Rotation `delta` value (and flashiness `delta`) is preserved on import/export
      but has no control in the UI - can't be viewed or edited, only carried through.
- [ ] No undo/redo while editing.
- [ ] No "Save Project" - only Export to carcols.meta. If the app is closed without
      exporting, in-progress siren edits are lost (only quick_colors/app_version/
      app_version persist across restarts via settings.json).
- [ ] Dev mode / Change Version verification is casual protection only (the check
      logic ships inside the exe and could be decompiled) - not real security.
- [ ] PyInstaller "onefile" build can trigger antivirus false positives for people
      you send the exe to.
- [ ] No automated test suite (pytest) - verification so far has been manual/ad hoc
      scripts during development sessions.
- [ ] The 32-step sequencer grid displays bit 0 on the left (LSB-first), which is
      mirrored compared to the external SirenTool's own grid convention (MSB-first) -
      cosmetic only, doesn't affect the exported sequencer value.
