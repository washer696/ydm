#!/usr/bin/env python3
"""Measures the actual download throughput of each downloader.

Usage: bench.py <window in s> <yt-dlp format> <url> <config> [<config>...]
Configs: native (yt-dlp alone), chunk2M (yt-dlp --http-chunk-size 2M), fast-N<k> (ytdlp_fast.py with k chunks).

Each config runs for the length of the window in a temporary folder, then is stopped.
The throughput is the slope of the bytes actually written to disk.
"""
import json, os, shutil, signal, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(os.environ, PATH=os.path.expanduser("~/.local/bin") + os.pathsep + os.environ["PATH"])


def command(config):
    if config == "native":
        return ["yt-dlp"]
    if config == "chunk2M":
        return ["yt-dlp", "--http-chunk-size", "2M"]
    if config.startswith("fast-N"):
        return [sys.executable, os.path.join(ROOT, "host", "ytdlp_fast.py"), "-N", config[6:]]
    sys.exit(f"unknown config: {config}")


def written(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            if not f.endswith((".ytdl", ".webp", ".jpg", ".png")):
                try:
                    total += os.stat(os.path.join(root, f)).st_blocks * 512
                except FileNotFoundError:
                    pass
    return total


def run(window, fmt, url, config):
    out = tempfile.mkdtemp(prefix="ytdlp-bench-")
    cmd = [*command(config), "--no-playlist", "-P", out, "--no-embed-thumbnail", "--no-embed-metadata", "-f", fmt, "--", url]
    with open(os.path.join(out, "log.txt"), "w") as log:
        t0 = time.monotonic()
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=ENV, start_new_session=True)
        samples, first = [], None
        while time.monotonic() - t0 < window and proc.poll() is None:
            time.sleep(1)
            b, t = written(out), time.monotonic() - t0
            if b > 4096 and first is None:
                first = t
            samples.append((t, b))
        finished = proc.poll() is not None
        if not finished:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait()
    with open(os.path.join(out, "log.txt"), errors="replace") as log:
        text = log.read().replace("\r", "\n")
    steady = [(t, b) for t, b in samples if first is not None and t >= first + 2]
    rate = (steady[-1][1] - steady[0][1]) / (steady[-1][0] - steady[0][0]) if len(steady) >= 2 else 0
    shutil.rmtree(out, ignore_errors=True)
    return {"config": config, "host": url.split("/")[2], "mb_per_s": round(rate / 1e6, 2),
            "total_mb": round(samples[-1][1] / 1e6, 1) if samples else 0, "first_byte_s": first and round(first, 1),
            "finished_early": finished, "errors": sum(1 for l in text.splitlines() if "ERROR" in l or "Got error" in l),
            "engine": "chunks" if "[ranges]" in text else "simple"}


if __name__ == "__main__":
    window, fmt, url = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    for config in sys.argv[4:]:
        print(json.dumps(run(window, fmt, url, config)), flush=True)
