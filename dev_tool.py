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
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

PROJECT_DIR = r"C:\Users\ozias\OneDrive\claude Code\GTAV Carcols Vehicle program"
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from settings_store import DEFAULT_APP_VERSION, GITHUB_REPO, load_settings, save_settings

# Built as a folder (--onedir), not a single exe - PyInstaller's onefile mode has to
# re-extract itself to a fresh temp folder on every launch, which was observed to
# intermittently race with antivirus real-time scanning and fail to start. onedir lays
# everything out on disk once, so there's nothing to extract on subsequent launches.
EXE_NAME = "CarcolsSirenEditorAlpha"
DESKTOP_DIR = os.path.join(os.path.expanduser("~"), "Desktop", EXE_NAME)
DESKTOP_SHORTCUT = os.path.join(os.path.expanduser("~"), "Desktop", "Carcols Siren Editor.lnk")
DIST_DIR = os.path.join(PROJECT_DIR, "dist", EXE_NAME)
DIST_ZIP_PATH = os.path.join(PROJECT_DIR, "dist", f"{EXE_NAME}.zip")

_GH_CANDIDATES = [r"C:\Program Files\GitHub CLI\gh.exe", "gh"]
GH = next((p for p in _GH_CANDIDATES if p == "gh" or os.path.exists(p)), "gh")

# gh's normal keyring-based login doesn't always get picked up when gh is launched as a
# subprocess of a Python GUI script (a Windows/keyring quirk, not specific to this repo).
# As a fallback, a token saved here gets passed via the GH_TOKEN env var instead, which
# bypasses the keyring lookup entirely. Lives outside the project folder, never committed.
TOKEN_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "CarcolsSirenEditor", "dev_gh_token.txt")


def load_gh_token() -> str:
    try:
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_gh_token(token: str) -> None:
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(token.strip())

# A version string becomes part of a git tag (vX.Y.Z), so it can't contain spaces or
# other characters git refs disallow. Spaces are common typos (e.g. "0.1.2 alpha"
# instead of "0.1.2-alpha") - normalize those to hyphens rather than just rejecting them.
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")


def normalize_version(raw: str) -> str:
    return re.sub(r"\s+", "-", raw.strip())


def run_command(args: list, extra_env: dict = None) -> tuple:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(args, cwd=PROJECT_DIR, capture_output=True, text=True, env=env)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def run_gh(args: list) -> tuple:
    token = load_gh_token()
    extra_env = {"GH_TOKEN": token} if token else None
    return run_command([GH] + args, extra_env=extra_env)


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

        token_frame = ttk.Frame(root)
        token_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Label(token_frame, text="GitHub Token:").pack(side=tk.LEFT)
        self.token_var = tk.StringVar()
        ttk.Entry(token_frame, textvariable=self.token_var, show="*", width=30).pack(side=tk.LEFT, padx=(6, 6))
        ttk.Button(token_frame, text="Save Token", command=self.save_token).pack(side=tk.LEFT)
        ttk.Label(
            token_frame,
            text="Only needed if 'Push to GitHub' fails with a gh auth error. Get one from "
                 "github.com > Settings > Developer settings > Personal access tokens (repo scope).",
            foreground="#555555",
        ).pack(side=tk.LEFT, padx=(10, 0))

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

    def save_token(self) -> None:
        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("Empty token", "Paste a GitHub personal access token first.")
            return
        save_gh_token(token)
        self.token_var.set("")
        self.log_line("GitHub token saved locally - it'll be used automatically for gh commands from now on.")

    def log_line(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def save_version(self) -> None:
        version = normalize_version(self.version_var.get())
        if not version or not VERSION_RE.match(version):
            messagebox.showerror(
                "Invalid version",
                "Version can only contain letters, numbers, dots, and hyphens (e.g. "
                "0.1.2-alpha) - no spaces or other symbols, since it becomes a git tag.",
            )
            return
        self.version_var.set(version)
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
        version = normalize_version(self.version_var.get())
        if not version or not VERSION_RE.match(version):
            self._log(
                f"'{self.version_var.get()}' isn't a valid version (letters/numbers/dots/"
                f"hyphens only, e.g. 0.1.2-alpha) - fix the Version field and try again."
            )
            self._done()
            return
        self.root.after(0, self.version_var.set, version)

        # Keep the persisted version in sync with what's about to be tagged/released,
        # even if "Save Version" was never clicked separately.
        data = load_settings()
        data["app_version"] = version
        save_settings(data)

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
        code, _ = run_gh(["release", "view", tag])
        if code == 0:
            self._log(f"Release {tag} already exists on GitHub - no new one needed. Done.")
            self._done()
            return

        self._log(f"No release exists yet for {tag} - building and publishing one...")
        self._log("Running PyInstaller (this can take a minute)...")
        shutil.rmtree(DIST_DIR, ignore_errors=True)
        code, out = run_command([
            sys.executable, "-m", "PyInstaller", "--onedir", "--windowed",
            "--name", EXE_NAME, "--distpath", "./dist", "--workpath", "./build",
            "--specpath", "./build", "main.py",
        ])
        self._log(out[-3000:])
        if code != 0:
            self._log("Build failed - not creating a release.")
            self._done()
            return

        self._log("Zipping the build for the release...")
        try:
            if os.path.exists(DIST_ZIP_PATH):
                os.remove(DIST_ZIP_PATH)
            shutil.make_archive(DIST_ZIP_PATH[:-4], "zip", root_dir=os.path.dirname(DIST_DIR), base_dir=EXE_NAME)
        except OSError as exc:
            self._log(f"Could not create the zip: {exc}")
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
        code, out = run_gh(["release", "create", tag, DIST_ZIP_PATH,
                            "--title", tag, "--notes", f"Release {tag}"])
        self._log(out)
        if code != 0:
            self._log("Release creation failed - check the output above.")
            self._done()
            return

        try:
            shutil.rmtree(DESKTOP_DIR, ignore_errors=True)
            shutil.copytree(DIST_DIR, DESKTOP_DIR)
            self._create_desktop_shortcut()
            self._log(f"Copied the new build to {DESKTOP_DIR} and refreshed the Desktop shortcut.")
        except OSError as exc:
            self._log(f"Could not update the Desktop copy: {exc}")

        self._log("All done.")
        self._done()

    def _create_desktop_shortcut(self) -> None:
        target = os.path.join(DESKTOP_DIR, f"{EXE_NAME}.exe")
        ps_script = (
            "$WshShell = New-Object -ComObject WScript.Shell; "
            f'$shortcut = $WshShell.CreateShortcut("{DESKTOP_SHORTCUT}"); '
            f'$shortcut.TargetPath = "{target}"; '
            f'$shortcut.WorkingDirectory = "{DESKTOP_DIR}"; '
            f'$shortcut.IconLocation = "{target}"; '
            "$shortcut.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True)


def main() -> None:
    root = tk.Tk()
    DevToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
