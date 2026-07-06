# Carcols Siren Editor - To Do / Open Items

- [ ] No automated test suite (pytest) - verification so far has been manual/ad hoc
      scripts during development sessions.
- [ ] The 32-step sequencer grid displays bit 0 on the left (LSB-first), which is
      mirrored compared to the external SirenTool's own grid convention (MSB-first) -
      cosmetic only, doesn't affect the exported sequencer value.
- [x] ~~PyInstaller "onefile" build can trigger antivirus false positives~~ - switched
      to a folder-based (--onedir) build + Desktop shortcut, which also fixed an
      intermittent launch failure caused by AV scanning racing with onefile's
      every-launch temp extraction.
