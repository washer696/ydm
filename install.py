#!/usr/bin/env python3
"""Installs the YDM bridge on this machine (Linux, macOS or Windows), without administrator rights.

Usage: python3 install.py      (Windows: py install.py)

1. yt-dlp and deno: downloaded from their official release pages if missing, checksums verified
   (after that, the bridge updates them itself every day);
2. the bridge: copied to its folder, with a small launcher that sets which Python to use;
3. Firefox: the manifest that allows the YDM extension, and only that one, to start the bridge
   (in the registry on Windows);
4. ffmpeg (and zenity, notify-send on Linux): checked, with the command to install them if missing;
5. the extension: unless Firefox already has it, the latest signed version is saved to the Downloads
   folder and opened in Firefox, which asks you to confirm. Skip it with --no-extension.

Run it again to update the bridge: the installed copy is replaced. The extension updates itself.
"""
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from io import BytesIO

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "host"))
from ydm_paths import BIN_DIR, DENO, HOME, INSTALL_DIR, MACOS, WINDOWS, YTDLP, search_path  # noqa: E402

HOST_NAME = "ytdlp_bridge"
HOST_FILES = ["ytdlp_bridge.py", "ytdlp_fast.py", "selftest.py", "ydm_paths.py"]
YTDLP_BASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
DENO_BASE = "https://github.com/denoland/deno/releases/latest/download/"


def say(text):
    print(text, flush=True)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ydm-install"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def checked(data, expected, what):
    if hashlib.sha256(data).hexdigest() != expected.lower():
        sys.exit(f"Wrong checksum for {what}: download stopped, nothing was installed.")
    return data


def write_executable(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.chmod(tmp, os.stat(tmp).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(tmp, path)


def install_ytdlp():
    if os.path.isfile(YTDLP):
        say(f"yt-dlp: already installed ({YTDLP})")
        return
    sums = fetch(YTDLP_BASE + "SHA2-256SUMS").decode()
    expected = next(line.split()[0] for line in sums.splitlines() if line.split()[-1:] == ["yt-dlp"])
    write_executable(YTDLP, checked(fetch(YTDLP_BASE + "yt-dlp"), expected, "yt-dlp"))
    say(f"yt-dlp: installed ({YTDLP})")


def deno_asset():
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if WINDOWS:
        return "deno-x86_64-pc-windows-msvc.zip"  # also on Windows ARM, through emulation
    if MACOS:
        return f"deno-{'aarch64' if arm else 'x86_64'}-apple-darwin.zip"
    return f"deno-{'aarch64' if arm else 'x86_64'}-unknown-linux-gnu.zip"


def install_deno():
    if os.path.isfile(DENO):
        say(f"deno: already installed ({DENO})")
        return
    asset = deno_asset()
    # The checksum file's format depends on the system that produced it: just pick out the hash.
    expected = re.search(r"\b[0-9a-fA-F]{64}\b", fetch(DENO_BASE + asset + ".sha256sum").decode("utf-8", "replace"))
    if not expected:
        sys.exit("deno checksum not found: nothing was installed.")
    archive = checked(fetch(DENO_BASE + asset), expected[0], "deno")
    with zipfile.ZipFile(BytesIO(archive)) as z:
        write_executable(DENO, z.read(os.path.basename(DENO)))
    say(f"deno: installed ({DENO})")


def install_bridge():
    os.makedirs(INSTALL_DIR, exist_ok=True)
    for name in HOST_FILES:
        shutil.copyfile(os.path.join(ROOT, "host", name), os.path.join(INSTALL_DIR, name))
    bridge = os.path.join(INSTALL_DIR, "ytdlp_bridge.py")
    # The launcher pins the Python interpreter: Firefox, started from the desktop, doesn't always have the same PATH as a terminal.
    if WINDOWS:
        launcher = os.path.join(INSTALL_DIR, "ydm-bridge.bat")
        with open(launcher, "w", newline="") as f:
            f.write(f'@echo off\r\n"{sys.executable}" "{bridge}" %*\r\n')
    else:
        launcher = os.path.join(INSTALL_DIR, "ydm-bridge")
        with open(launcher, "w") as f:
            f.write(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(bridge)} \"$@\"\n")
        os.chmod(launcher, 0o755)
    say(f"Bridge: installed ({INSTALL_DIR})")
    return launcher


def extension_id():
    with open(os.path.join(ROOT, "extension", "manifest.json"), encoding="utf-8") as f:
        return json.load(f)["browser_specific_settings"]["gecko"]["id"]


def manifest_path():
    if WINDOWS:
        return os.path.join(INSTALL_DIR, HOST_NAME + ".json")
    if MACOS:
        return os.path.join(HOME, "Library", "Application Support", "Mozilla", "NativeMessagingHosts", HOST_NAME + ".json")
    return os.path.join(HOME, ".mozilla", "native-messaging-hosts", HOST_NAME + ".json")


def register_with_firefox(launcher):
    manifest = {
        "name": HOST_NAME,
        "description": "Bridge between Firefox and yt-dlp (YDM)",
        "path": launcher,
        "type": "stdio",
        "allowed_extensions": [extension_id()],  # only the YDM extension can start the bridge
    }
    path = manifest_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    if WINDOWS:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Mozilla\NativeMessagingHosts\{HOST_NAME}") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, path)
    say(f"Firefox: manifest installed ({path})")


def public_repo():
    """owner/name of the public repository, read from the extension's update address."""
    with open(os.path.join(ROOT, "extension", "manifest.json"), encoding="utf-8") as f:
        url = json.load(f)["browser_specific_settings"]["gecko"]["update_url"]
    return "/".join(url.split("/")[3:5])


def firefox_profiles():
    if WINDOWS:
        roots = [os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles")]
    elif MACOS:
        roots = [os.path.join(HOME, "Library", "Application Support", "Firefox", "Profiles")]
    else:
        roots = [os.path.join(HOME, base, "firefox")
                 for base in (".mozilla", "snap/firefox/common/.mozilla", ".var/app/org.mozilla.firefox/.mozilla")]
    return [os.path.join(root, name) for root in roots if os.path.isdir(root) for name in os.listdir(root)]


def extension_installed():
    ext = extension_id()
    for profile in firefox_profiles():
        try:
            with open(os.path.join(profile, "extensions.json"), encoding="utf-8") as f:
                if any(addon.get("id") == ext for addon in json.load(f).get("addons", [])):
                    return True
        except (OSError, ValueError):
            pass
    return False


def downloads_dir():
    if not (WINDOWS or MACOS):
        try:
            out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        # A Firefox snap can't read hidden folders: the Downloads folder is safe on every system.
        # Without a user-dirs config, xdg-user-dir answers with the home folder itself.
        if out and os.path.isdir(out) and os.path.normpath(out) != os.path.normpath(HOME):
            return out
    return os.path.join(HOME, "Downloads")


def firefox_command():
    if WINDOWS:
        import winreg

        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe") as key:
                    return [winreg.QueryValueEx(key, "")[0]]
            except OSError:
                pass
        return None
    if MACOS:
        return ["open", "-a", "Firefox"] if os.path.isdir("/Applications/Firefox.app") else None
    firefox = shutil.which("firefox")
    return [firefox] if firefox else None


def install_extension():
    if extension_installed():
        say("Extension: already in Firefox (it updates itself)")
        return
    repo = public_repo()
    page = f"https://github.com/{repo}/releases/latest"
    try:
        data = fetch(f"{page}/download/ydm.xpi")
    except OSError:
        say(f"Extension: download failed. Get ydm.xpi from {page}")
        return
    folder = downloads_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "ydm.xpi")
    with open(path, "wb") as f:
        f.write(data)
    command = firefox_command()
    if command:
        subprocess.Popen(command + [path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=not WINDOWS)
        say('Extension: opened in Firefox. Click "Add" to finish.')
    else:
        say(f'Extension: saved to {path}. Drag it onto a Firefox window and click "Add".')


def check_tools():
    path = os.pathsep.join(search_path() + [os.environ.get("PATH", "")])
    if WINDOWS:
        needed, hint = ["ffmpeg"], "winget install Gyan.FFmpeg"
    elif MACOS:
        needed, hint = ["ffmpeg"], "brew install ffmpeg"
    else:
        needed, hint = ["ffmpeg", "zenity", "notify-send"], "sudo apt install ffmpeg zenity libnotify-bin"
    missing = [tool for tool in needed if not shutil.which(tool, path=path)]
    if missing:
        say(f"\nStill to install: {', '.join(missing)}\n    {hint}")
    return not missing


def main():
    if sys.version_info < (3, 9):
        sys.exit("YDM requires Python 3.9 or newer.")
    install_ytdlp()
    install_deno()
    register_with_firefox(install_bridge())
    complete = check_tools()
    if "--no-extension" in sys.argv[1:] or os.environ.get("YDM_NO_EXTENSION"):
        say("Extension: skipped")
    else:
        install_extension()
    if not complete:
        say("Install the tools above, then restart Firefox.")

if __name__ == "__main__":
    main()
