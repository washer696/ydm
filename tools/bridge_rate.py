#!/usr/bin/env python3
"""Measures the throughput of a download started through the bridge, in an isolated environment.

Usage: bridge_rate.py <window in s> <url> [height]
Reads progress messages during the window, then cancels and removes the entry (partial files deleted).
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bridge_client import Bridge, cleanup, isolated_env, sandbox

window, url = int(sys.argv[1]), sys.argv[2]
payload = {"url": url, "mode": "video"}
if len(sys.argv) > 3:
    payload["height"] = int(sys.argv[3])

root = sandbox()
out = os.path.join(root, "out")
os.makedirs(out)
try:
    b = Bridge(isolated_env(root, zenity_answer=out))
    b.call("pickFolder")
    eid = b.call("download", **payload)["entry"]["id"]
    samples, t0, status, error = [], time.time(), "downloading", None
    while time.time() - t0 < window and status == "downloading":
        try:
            msg = b.inbox.get(timeout=1)
        except Exception:
            continue
        if msg["type"] == "entry" and msg["entry"]["id"] == eid:
            status, error = msg["entry"]["status"], msg["entry"].get("error")
            p = msg["entry"].get("progress")
            if p and p.get("downloaded") is not None and p.get("part") != "audio":
                samples.append((time.time(), p["downloaded"], p.get("percent")))
    engine = "chunks" if any(f.endswith(".ytdl") for f in os.listdir(out)) else "simple or finished"
    rate = (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0]) / 1e6 if len(samples) > 1 else 0
    print(json.dumps({"host": url.split("/")[2], "mb_per_s": round(rate, 2), "messages": len(samples),
                      "percent": samples[-1][2] if samples else None, "status": status, "error": error, "engine": engine}, ensure_ascii=False))
    if status == "downloading":
        b.send("cancel", entry=eid)
        b.entry_until(eid, lambda e: e["status"] != "downloading")
    b.call("remove", entry=eid)
    b.close()
finally:
    cleanup(root)
