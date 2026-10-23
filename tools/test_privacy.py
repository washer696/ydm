#!/usr/bin/env python3
"""Tests the bridge's privacy through its real protocol, in an isolated environment.

Usage: test_privacy.py
Fully offline (local server, see local_videos.py). Checks: log with no address or title,
log cleared along with the history, private downloads forgotten when private browsing ends,
no title in private notifications, state readable by the user only, videos with the usual permissions.
Does not touch the real history, settings or videos folder.
"""
import os, stat, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import local_videos
from bridge_client import WINDOWS, Bridge, cleanup, fake_command, isolated_env, sandbox

results = []


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL "), name, detail, flush=True)
    results.append(bool(ok))


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def start(b, url, title, private=False):
    reply = b.call("download", url=url, mode="video", title=title, pageTitle=True, private=private)
    assert reply["type"] == "started", reply
    return reply["entry"]


def finished(b, entry_id):
    return b.entry_until(entry_id, lambda e: e["status"] not in ("downloading", "queued"))


def partials(folder, stem):
    return [f for f in os.listdir(folder) if stem and f.startswith(stem + ".")]


server, base = local_videos.start()
root = sandbox()
out = os.path.join(root, "videos")
os.makedirs(out)
env = isolated_env(root, zenity_answer=out)
notes = os.path.join(root, "notifications.txt")
# record what would be shown on the desktop
fake_command(root, "notify-send", f"printf '%s\\n' \"$*\" >> '{notes}'\n", f'echo %* >> "{notes}"\n')
state = os.path.join(root, "state", "ytdlp-bridge")
log_file = os.path.join(state, "log.txt")
user_umask = os.umask(0)
os.umask(user_umask)
b = None
try:
    b = Bridge(env)
    assert b.call("pickFolder").get("download_dir") == out

    normal = finished(b, start(b, f"{base}/normal.mp4", "Titre secret normal")["id"])
    check("normal: finished", normal["status"] == "done", normal.get("error") or "")
    if not WINDOWS:  # Unix permissions; on Windows, %LOCALAPPDATA% is already restricted to the user
        check("normal: video with the usual permissions", mode(normal["file"]) == 0o666 & ~user_umask, oct(mode(normal["file"])))

    p_done = start(b, f"{base}/private.mp4", "Titre secret privé", private=True)
    check("private: marked as such", p_done.get("private") is True)
    p_done = finished(b, p_done["id"])
    check("private: finished", p_done["status"] == "done", p_done.get("error") or "")
    def shown_notes():
        try:  # on Windows, cmd writes in its own code page
            with open(notes, encoding="utf-8", errors="replace") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def private_note(text):  # in the system language, English or French
        return "Private browsing" in text or "Navigation priv" in text

    # The notification is sent from a separate process: it may arrive shortly after the download ends.
    end = time.time() + 15
    while not private_note(shown_notes()) and time.time() < end:
        time.sleep(0.2)
    shown = shown_notes()
    check("notification: title shown outside private browsing", "Titre secret normal" in shown)
    check("notification: no title in private browsing", "Titre secret priv" not in shown and private_note(shown))

    p_cancel = start(b, f"{base}/slow/private2.mp4", "Titre secret annulé", private=True)["id"]
    b.entry_until(p_cancel, lambda e: ((e.get("progress") or {}).get("percent") or 0) > 1, timeout=60)
    b.send("cancel", entry=p_cancel)
    p_cancel = b.entry_until(p_cancel, lambda e: e["status"] == "cancelled", timeout=30)
    check("cancelled private download: partial file present", bool(partials(out, p_cancel.get("stem"))))

    p_running = start(b, f"{base}/slow/private3.mp4", "Titre secret en cours", private=True)["id"]
    kept = {e["id"] for e in b.call("forgetPrivate")["entries"]}
    check("end of private browsing: finished download forgotten", p_done["id"] not in kept)
    check("end of private browsing: cancelled download forgotten", p_cancel["id"] not in kept)
    check("end of private browsing: partial file of the cancelled download deleted", partials(out, p_cancel.get("stem")) == [])
    check("end of private browsing: finished video kept on disk", os.path.isfile(p_done["file"]))
    check("end of private browsing: running download kept until it ends", p_running in kept)
    check("end of private browsing: normal download kept", normal["id"] in kept)

    b.send("cancel", entry=p_running)
    b.until(lambda m: m["type"] == "history" and p_running not in {e["id"] for e in m["entries"]}, timeout=30)
    check("running private download: forgotten when it ends", True)

    with open(log_file, encoding="utf-8") as f:
        log = f.read()
    check("log: written", "START" in log and "DONE" in log)
    check("log: no address", "127.0.0.1" not in log and "://" not in log and ".mp4" not in log)
    check("log: no title", "Titre secret" not in log)

    if not WINDOWS:
        check("state: folder readable by you only", mode(state) == 0o700 and mode(os.path.join(state, "jobs")) == 0o700)
        loose = [f for f in os.listdir(state) if os.path.isfile(os.path.join(state, f)) and mode(os.path.join(state, f)) != 0o600]
        check("state: files readable by you only", loose == [], str(loose))

    b.call("clear")
    check("clear history: log cleared", os.path.getsize(log_file) == 0)
finally:
    if b:
        b.close()
    server.shutdown()
    cleanup(root)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
