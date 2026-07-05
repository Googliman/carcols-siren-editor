"""Local-only developer tool for the Carcols Siren Editor project.

Not part of the distributed app - lets the developer bump the app version and
push source + cut a new GitHub release in one click. Requires git and the
GitHub CLI (gh) to be installed and authenticated on this machine.

This file can live anywhere (e.g. copied to the Desktop for quick access) - it
always operates on PROJECT_DIR below, regardless of where it's actually run from.

Run with: python dev_tool.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

PROJECT_DIR = r"C:\Users\ozias\OneDrive\claude Code\GTAV Carcols Vehicle program"
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from settings_store import DEFAULT_APP_VERSION, GITHUB_REPO, load_settings, save_settings

EXE_NAME = "CarcolsSirenEditorAlpha"
DESKTOP_EXE_PATH = os.path.join(os.path.expanduser("~"), "Desktop", f"{EXE_NAME}.exe")
DIST_EXE_PATH = os.path.join(PROJECT_DIR, "dist", f"{EXE_NAME}.exe")

_GH_CANDIDATES = [r"C:\Program Files\GitHub CLI\gh.exe", "gh"]
GH = next((p for p in _GH_CANDIDATES if p == "gh" or os.path.exists(p)), "gh")


def run_command(args: list) -> tuple:
    result = subprocess.run(args, cwd=PROJECT_DIR, capture_output=True, text=True)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


class DevToolApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Carcols Dev Tool (local only)")
        root.geometry("720x520")

        settings = load_settings()
        self.version_var = tk.StringVar(value=settings.get("app_version", DEFAULT_APP_VERSION))

        top = ttk.Frame(root)
        top.pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(top, text="App Version:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.version_var, width=20).pack(side=tk.LEFT, padx=(6, 6))
        ttk.Button(top, text="Save Version", command=self.save_version).pack(side=tk.LEFT)

        ttk.Label(
            top,
            text=f"Repo: {GITHUB_REPO}",
            foreground="#555555",
        ).pack(side=tk.RIGHT)

        action_frame = ttk.Frame(root)
        action_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.push_button = ttk.Button(action_frame, text="Push to GitHub", command=self.push_to_github)
        self.push_button.pack(side=tk.LEFT)
        ttk.Label(
            action_frame,
            text="Commits + pushes source. If the version above doesn't have a "
                 "release yet, also builds the exe and publishes a new release.",
            foreground="#555555",
        ).pack(side=tk.LEFT, padx=(10, 0))

        self.log = scrolledtext.ScrolledText(root, wrap=tk.WORD, state="disabled")
        self.log.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

    def log_line(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def save_version(self) -> None:
        version = self.version_var.get().strip()
        if not version:
            messagebox.showerror("Invalid version", "Version can't be empty.")
            return
        data = load_settings()
        data["app_version"] = version
        save_settings(data)
        self.log_line(f"Saved app_version = {version} (this is what the public app will display).")

    def push_to_github(self) -> None:
        self.push_button.configure(state="disabled")
        threading.Thread(target=self._push_worker, daemon=True).start()

    def _log(self, text: str) -> None:
        self.root.after(0, self.log_line, text)

    def _done(self) -> None:
        self.root.after(0, lambda: self.push_button.configure(state="normal"))

    def _push_worker(self) -> None:
        version = self.version_var.get().strip()
        if not version:
            self._log("Version field is empty - aborting.")
            self._done()
            return
        tag = f"v{version}"

        self._log("Staging changes...")
        run_command(["git", "add", "-A"])
        code, out = run_command(["git", "commit", "-m", f"Update to {version}"])
        self._log(out if out else "(nothing new to commit)")

        self._log("Pushing to origin/master...")
        code, out = run_command(["git", "push", "origin", "master"])
        self._log(out)
        if code != 0:
            self._log("Push failed - stopping here.")
            self._done()
            return

        # Check the actual GitHub release, not local git refs - "gh release create" can
        # publish a release/tag on the remote without ever creating a local tag ref, so
        # checking local refs alone can wrongly think no release exists yet.
        code, _ = run_command([GH, "release", "view", tag])
        if code == 0:
            self._log(f"Release {tag} already exists on GitHub - no new one needed. Done.")
            self._done()
            return

        self._log(f"No release exists yet for {tag} - building and publishing one...")
        self._log("Running PyInstaller (this can take a minute)...")
        code, out = run_command([
            sys.executable, "-m", "PyInstaller", "--onefile", "--windowed",
            "--name", EXE_NAME, "--distpath", "./dist", "--workpath", "./build",
            "--specpath", "./build", "main.py",
        ])
        self._log(out[-3000:])
        if code != 0:
            self._log("Build failed - not creating a release.")
            self._done()
            return

        self._log(f"Tagging {tag} and pushing the tag...")
        run_command(["git", "tag", "-d", tag])  # clean up any stale local tag, ok if it doesn't exist
        run_command(["git", "tag", tag])
        code, out = run_command(["git", "push", "origin", tag])
        self._log(out)
        if code != 0:
            self._log("Tag push failed - not creating a release.")
            self._done()
            return

        self._log("Creating the GitHub release...")
        code, out = run_command([GH, "release", "create", tag, DIST_EXE_PATH,
                                  "--title", tag, "--notes", f"Release {tag}"])
        self._log(out)
        if code != 0:
            self._log("Release creation failed - check the output above.")
            self._done()
            return

        try:
            import shutil
            shutil.copyfile(DIST_EXE_PATH, DESKTOP_EXE_PATH)
            self._log(f"Copied the new build to {DESKTOP_EXE_PATH}")
        except OSError as exc:
            self._log(f"Could not copy exe to Desktop: {exc}")

        self._log("All done.")
        self._done()


def main() -> None:
    root = tk.Tk()
    DevToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
