#!/usr/bin/env python3
"""Tests the bridge through its real protocol, in an isolated environment: settings, folder, chunks, cleanup of partial files.

Usage: test_bridge.py
Downloads two public test videos to a temporary folder. Does not touch the real history,
settings or videos folder.
"""
import os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bridge_client import Bridge, cleanup, isolated_env, sandbox

SMALL = "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/1080/Big_Buck_Bunny_1080_10s_30MB.mp4"
BIG = "https://archive.org/download/BigBuckBunny_124/Content/big_buck_bunny_720p_surround.mp4"
results = []


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL "), name, detail, flush=True)
    results.append(bool(ok))


def start(b, url):
    reply = b.call("download", url=url, mode="video")
    assert reply["type"] == "started", reply
    return reply["entry"]["id"]


def cancel_after_progress(b, eid, percent=3):
    b.entry_until(eid, lambda e: (e.get("progress") or {}).get("percent") and e["progress"]["percent"] > percent)
    b.send("cancel", entry=eid)
    return b.entry_until(eid, lambda e: e["status"] != "downloading")


root = sandbox()
dir_a, dir_b = os.path.join(root, "A"), os.path.join(root, "B")
os.makedirs(dir_a); os.makedirs(dir_b)
default = subprocess.run(["xdg-user-dir", "VIDEOS"], capture_output=True, text=True).stdout.strip()
try:
    b = Bridge(isolated_env(root))
    s = b.call("settings")
    check("engine: known version and accelerator validated", bool(s["ytdlp"]["version"]) and s["ytdlp"]["fast"], str(s["ytdlp"]))
    check("settings: default folder", s["is_default"] and s["download_dir"] == default, s["download_dir"])
    s = b.call("pickFolder")
    check("picker cancelled: nothing changes", s["type"] == "settings" and s["is_default"])
    b.close()

    b = Bridge(isolated_env(root, zenity_answer=os.path.join(root, "does-not-exist")))
    check("missing folder: refused", b.call("pickFolder").get("code") == "folder_unusable")
    b.close()

    env_a = isolated_env(root, zenity_answer=dir_a)
    b = Bridge(env_a)
    s = b.call("pickFolder")
    check("picked folder: saved", s.get("download_dir") == dir_a and not s["is_default"])
    b.close()
    b = Bridge(env_a)
    check("picked folder: kept after the bridge restarts", b.call("settings")["download_dir"] == dir_a)

    eid = start(b, SMALL)
    saw_state = False
    while True:
        saw_state = saw_state or any(f.endswith(".ytdl") for f in os.listdir(dir_a))
        try:
            msg = b.inbox.get(timeout=0.02)
        except Exception:
            continue
        if msg["type"] == "entry" and msg["entry"]["id"] == eid and msg["entry"]["status"] != "downloading":
            done = msg["entry"]
            break
    check("download: finished", done["status"] == "done", done.get("error") or "")
    check("download: in the picked folder", (done.get("file") or "").startswith(dir_a + os.sep) and os.path.isfile(done["file"]))
    check("download: in parallel chunks", saw_state)
    check("download: folder and name remembered", done.get("dir") == dir_a and bool(done.get("stem")), done.get("stem") or "")
    check("download: nothing left behind", [f for f in os.listdir(dir_a) if f != os.path.basename(done["file"])] == [])

    d1 = start(b, BIG)
    e1 = cancel_after_progress(b, d1)
    stem = e1.get("stem") or ""
    partials = lambda: sorted(f for f in os.listdir(dir_a) if f.startswith(stem + "."))
    check("cancel: partial files present", e1["status"] == "cancelled" and any(f.endswith(".part") for f in partials()), str(len(partials())))
    decoys = [stem + ".mkv", stem + " copy.mp4.part", "other.mp4.part"]
    for name in decoys:
        open(os.path.join(dir_a, name), "w").close()

    d2 = start(b, BIG)
    e2 = cancel_after_progress(b, d2, percent=e1["progress"]["percent"] if e1.get("progress") else 3)
    b.call("remove", entry=d1)
    check("removing the old entry: partial file kept for the restarted one", any(f.endswith(".part") for f in partials()))
    b.close()

    b = Bridge(isolated_env(root, zenity_answer=dir_b))
    check("folder change", b.call("pickFolder")["download_dir"] == dir_b)
    b.call("resume", entry=d2)
    cancel_after_progress(b, d2)
    check("resume: in the original folder", os.listdir(dir_b) == [] and any(f.endswith(".part") for f in partials()))
    b.call("remove", entry=d2)
    left = sorted(os.listdir(dir_a))
    check("remove: partial files deleted", not any(f in left for f in partials() if f != stem + ".mkv") and stem + ".mp4.part" not in left, str([f for f in left if f.startswith(stem)]))
    check("remove: other files untouched", all(f in left for f in decoys) and os.path.basename(done["file"]) in left)
    s = b.call("resetFolder")
    check("back to the default folder", s["is_default"] and s["download_dir"] == default)
    b.close()
finally:
    cleanup(root)
sys.exit(0 if all(results) else 1)
