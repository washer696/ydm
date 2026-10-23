#!/usr/bin/env python3
"""Tests engine updates through the real protocol, with a fake yt-dlp and a fake HOME.

Usage: test_update.py
Fully offline: the fake yt-dlp (an executable zip archive) "updates" itself by rewriting
itself with the requested version. Does not touch the real yt-dlp, history or settings.
"""
import json, os, subprocess, sys, time, zipapp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bridge_client import Bridge, cleanup, isolated_env, sandbox

results = []

MAIN = '''import os, sys, tempfile, zipapp, zipfile

from yt_dlp.version import __version__

HOME = os.environ["HOME"]
ME = os.path.dirname(os.path.abspath(__file__))


def rebuild(version):
    src = tempfile.mkdtemp()
    os.makedirs(os.path.join(src, "yt_dlp"))
    open(os.path.join(src, "yt_dlp", "__init__.py"), "w").close()
    with open(os.path.join(src, "yt_dlp", "version.py"), "w") as f:
        f.write("__version__ = '" + version + "'\\n")
    with zipfile.ZipFile(ME) as z, open(os.path.join(src, "__main__.py"), "wb") as f:
        f.write(z.read("__main__.py"))
    tmp = ME + ".new"
    zipapp.create_archive(src, tmp, interpreter="/usr/bin/env python3")
    os.chmod(tmp, 0o755)
    os.replace(tmp, ME)


if "--version" in sys.argv:
    print(__version__)
elif "-U" in sys.argv:
    wanted = os.path.join(HOME, "next_version")
    if os.path.exists(os.path.join(HOME, "fail_update")):
        print("ERROR: network unavailable", file=sys.stderr)
        sys.exit(1)
    version = open(wanted).read().strip() if os.path.exists(wanted) else __version__
    if version != __version__:
        rebuild(version)
        print("Updated yt-dlp to " + version)
    else:
        print("yt-dlp is up to date")
'''


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL "), name, detail, flush=True)
    results.append(bool(ok))


def bin_dir(home):
    """Where the bridge looks for yt-dlp with this fake home folder (see host/ydm_paths.py)."""
    if sys.platform == "win32":
        return os.path.join(home, "AppData", "Local", "YDM", "bin")
    return os.path.join(home, ".local", "bin")


def fake_ytdlp(home, version):
    """Installs a fake yt-dlp (zipapp) of this version where the bridge looks for it."""
    src = os.path.join(home, "fake-src")
    os.makedirs(os.path.join(src, "yt_dlp"), exist_ok=True)
    open(os.path.join(src, "yt_dlp", "__init__.py"), "w").close()
    with open(os.path.join(src, "yt_dlp", "version.py"), "w") as f:
        f.write(f"__version__ = '{version}'\n")
    with open(os.path.join(src, "__main__.py"), "w", encoding="utf-8") as f:  # Python reads the script as UTF-8
        f.write(MAIN)
    os.makedirs(bin_dir(home), exist_ok=True)
    target = os.path.join(bin_dir(home), "yt-dlp")
    zipapp.create_archive(src, target, interpreter="/usr/bin/env python3")
    os.chmod(target, 0o755)


def set_next(home, version):
    with open(os.path.join(home, "next_version"), "w") as f:
        f.write(version)


def set_checked(root, ts):
    with open(os.path.join(root, "state", "ytdlp-bridge", "update.json"), "w") as f:
        json.dump({"checked": ts}, f)


def engine(b):
    return b.call("settings")["ytdlp"]


root = sandbox()
home = os.path.join(root, "home")
os.makedirs(home)
bridges = []


try:
    fake_ytdlp(home, "2026.01.01")
    env = isolated_env(root, home=home)
    os.remove(os.path.join(root, "state", "ytdlp-bridge", "update.json"))

    b = Bridge(env)
    bridges.append(b)
    y = engine(b)
    check("never checked: update at startup", y["version"] == "2026.01.01" and y["error"] is None
          and y["checked"] and time.time() - y["checked"] < 60, str(y))
    check("never checked: accelerator disabled (self-test failed)", y["fast"] is False)
    checked = y["checked"]
    b.close()

    b = Bridge(env)
    bridges.append(b)
    check("restart: no new check", engine(b)["checked"] == checked)
    b.close()

    b = Bridge(env)
    bridges.append(b)
    set_next(home, "2026.02.02")
    y = b.call("update", timeout=200)["ytdlp"]
    check("manual update: new version", y["version"] == "2026.02.02", str(y))
    check("manual update: the bridge still answers", engine(b)["version"] == "2026.02.02")

    open(os.path.join(home, "fail_update"), "w").close()
    set_next(home, "2026.02.03")
    y = b.call("update", timeout=200)["ytdlp"]
    check("failed update: error reported, version unchanged", bool(y["error"]) and y["version"] == "2026.02.02", str(y))
    os.remove(os.path.join(home, "fail_update"))
    b.close()

    set_checked(root, time.time() - 25 * 3600)
    set_next(home, "2026.03.03")
    b = Bridge(env)
    bridges.append(b)
    y = engine(b)
    check("over 24 h: automatic update at startup", y["version"] == "2026.03.03" and y["error"] is None, str(y))
    b.close()

    b = Bridge(env)
    bridges.append(b)
    b.call("check", url="https://example.com/")  # loads yt_dlp in the bridge; the fake one is expected to fail
    set_next(home, "2026.04.04")
    y = b.call("update", timeout=200)["ytdlp"]
    check("library loaded: new version", y["version"] == "2026.04.04", str(y))
    try:
        code = b.proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        code = None
    check("library loaded: the bridge restarts itself", code == 0, f"code {code}")
finally:
    for b in bridges:
        try:
            b.proc.stdin.close()
            b.proc.wait(timeout=20)
        except Exception:
            b.proc.kill()
    cleanup(root)
sys.exit(0 if all(results) else 1)
