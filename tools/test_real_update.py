#!/usr/bin/env python3
"""Checks that yt-dlp can update itself on this system, as the bridge asks it to every day.

Usage: test_real_update.py
Network: downloads an old official release to a temporary folder, updates it with
`yt-dlp -U` (run through Python, as the bridge does), then checks that it changed and that it works.
Does not touch the installed yt-dlp. If the GitHub API refuses because of its rate limit (common on
the shared machines that run automated tests), the test is skipped rather than counted as a failure.
"""
import os, subprocess, sys, tempfile, time, urllib.request

OLD = "2024.12.23"


def run(path, *args):
    return subprocess.run([sys.executable, path, *args], capture_output=True, text=True, timeout=300)


with tempfile.TemporaryDirectory(prefix="ydm-real-update-") as d:
    path = os.path.join(d, "yt-dlp")
    request = urllib.request.Request(f"https://github.com/yt-dlp/yt-dlp/releases/download/{OLD}/yt-dlp",
                                     headers={"User-Agent": "ydm-tests"})
    with urllib.request.urlopen(request, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    before = run(path, "--version").stdout.strip()
    for attempt in range(3):
        update = run(path, "-U")
        if "rate limit" not in (update.stdout + update.stderr).lower():
            break
        time.sleep(30)
    else:
        print(f"SKIPPED real yt-dlp update: GitHub API rate limit reached on this machine")
        sys.exit(0)
    after = run(path, "--version").stdout.strip()
    ok = before == OLD and after not in ("", OLD) and update.returncode == 0
    print(("OK   " if ok else "FAIL "), f"real yt-dlp update: {before} -> {after}")
    if not ok:
        print(update.stdout, update.stderr)
    sys.exit(0 if ok else 1)
