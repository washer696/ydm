"""YDM locations on each system (Linux, macOS, Windows), shared by the bridge, the accelerator and the installer.

- programs (yt-dlp, deno): ~/.local/bin, or %LOCALAPPDATA%\\YDM\\bin on Windows;
- state (history, log, settings): ~/.local/state/ytdlp-bridge, ~/Library/Application Support/YDM
  on macOS, %LOCALAPPDATA%\\YDM\\state on Windows; XDG_STATE_HOME overrides it everywhere (tests);
- installed bridge: ~/.local/share/ytdlp-bridge, ~/Library/Application Support/YDM/bridge, %LOCALAPPDATA%\\YDM\\bridge.
"""
import os
import sys

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
HOME = os.path.expanduser("~")

if WINDOWS:
    _APP = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local"), "YDM")
    BIN_DIR = os.path.join(_APP, "bin")
    _STATE = os.path.join(_APP, "state")
    INSTALL_DIR = os.path.join(_APP, "bridge")
elif MACOS:
    _APP = os.path.join(HOME, "Library", "Application Support", "YDM")
    BIN_DIR = os.path.join(HOME, ".local", "bin")
    _STATE = os.path.join(_APP, "state")
    INSTALL_DIR = os.path.join(_APP, "bridge")
else:
    BIN_DIR = os.path.join(HOME, ".local", "bin")
    _STATE = os.path.join(os.path.join(HOME, ".local", "state"), "ytdlp-bridge")
    INSTALL_DIR = os.path.join(HOME, ".local", "share", "ytdlp-bridge")

STATE_DIR = os.path.join(os.environ["XDG_STATE_HOME"], "ytdlp-bridge") if os.environ.get("XDG_STATE_HOME") else _STATE

# yt-dlp: the official zip archive, run by Python on every system (and importable as a library).
YTDLP = os.path.join(BIN_DIR, "yt-dlp")
DENO = os.path.join(BIN_DIR, "deno.exe" if WINDOWS else "deno")


def search_path():
    """Folders to put in front of the PATH: Firefox doesn't always pass on the terminal's.

    macOS: an app launched from the Dock doesn't see Homebrew (ffmpeg).
    Windows: winget puts its shortcuts (ffmpeg) in WinGet\\Links."""
    extra = [BIN_DIR]
    if MACOS:
        extra += ["/opt/homebrew/bin", "/usr/local/bin"]
    if WINDOWS:
        extra.append(os.path.join(os.path.dirname(_APP), "Microsoft", "WinGet", "Links"))
    return [p for p in extra if os.path.isdir(p)]
