from __future__ import annotations

import tkinter as tk

from gui import CarcolsEditorApp


def main() -> None:
    root = tk.Tk()
    CarcolsEditorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
