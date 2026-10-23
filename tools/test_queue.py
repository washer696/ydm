#!/usr/bin/env python3
"""Tests the bridge's download queue through its real protocol, in an isolated environment.

Usage: test_queue.py
Fully offline: a local server serves slow "videos", so that downloads stay in progress
during the checks. Everything is cancelled before the end. Does not touch the real history,
settings or videos folder.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import local_videos
from bridge_client import BRIDGE, Bridge, cleanup, isolated_env, sandbox

# Read from the source rather than imported: importing the bridge would create its real state folders.
with open(BRIDGE, encoding="utf-8") as f:
    MAX_ACTIVE = int(re.search(r"^MAX_ACTIVE = (\d+)", f.read(), re.M)[1])

results = []


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL "), name, detail, flush=True)
    results.append(bool(ok))


server, base = local_videos.start()
urls = [f"{base}/slow/v{i}.mp4" for i in range(1, MAX_ACTIVE + 2)]

root = sandbox()
out = os.path.join(root, "videos")
os.makedirs(out)
b = None
try:
    b = Bridge(isolated_env(root, zenity_answer=out))
    assert b.call("pickFolder").get("download_dir") == out

    entries = [b.call("download", url=u, mode="video")["entry"] for u in urls]
    *first, last = entries
    check(f"the first {MAX_ACTIVE} start", all(e["status"] == "downloading" for e in first), str([e["status"] for e in first]))
    check("the next one waits its turn", last["status"] == "queued")
    waiting = last["id"]

    dup = b.call("download", url=urls[-1], mode="video")
    check("duplicate refused", dup.get("code") == "already_queued", dup.get("error") or dup["type"])

    b.send("cancel", entry=waiting)
    e = b.entry_until(waiting, lambda e: e["status"] != "queued", timeout=10)
    check("cancelled while queued: immediately", e["status"] == "cancelled")

    b.send("resume", entry=waiting)
    e = b.entry_until(waiting, lambda e: True, timeout=10)
    check("resumed: back in the queue", e["status"] == "queued")

    kept = {e["id"]: e["status"] for e in b.call("clear")["entries"]}
    check("clear history: keeps the queue", kept.get(waiting) == "queued" and len(kept) == len(entries), str(kept))

    b.send("cancel", entry=first[0]["id"])
    e = b.entry_until(waiting, lambda e: e["status"] == "downloading", timeout=30)
    check("slot freed: the next one starts", e["status"] == "downloading")

    for e in entries[1:]:
        b.send("cancel", entry=e["id"])
    left = {e["id"] for e in entries[1:]}

    def all_cancelled(m):
        if m["type"] == "entry" and m["entry"]["status"] == "cancelled":
            left.discard(m["entry"]["id"])
        return not left

    b.until(all_cancelled, timeout=30)
    states = {e["status"] for e in b.call("history")["entries"]}
    check("everything cancelled", states == {"cancelled"}, str(states))
finally:
    if b:
        b.close()
    server.shutdown()
    cleanup(root)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
