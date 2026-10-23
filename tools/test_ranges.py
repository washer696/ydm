#!/usr/bin/env python3
"""Proves that chunked downloading rebuilds the file byte for byte.

Usage: test_ranges.py [url of a direct video file that accepts range requests]
Compares the hash of the result with that of a reference download (curl), in three cases:
full download, interruption then resume, and resume of a partial file started without chunks.
"""
import glob, hashlib, json, os, shutil, signal, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAST = [sys.executable, os.path.join(ROOT, "host", "ytdlp_fast.py")]
PLAIN = [os.path.expanduser("~/.local/bin/yt-dlp")]
URL = sys.argv[1] if len(sys.argv) > 1 else "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/1080/Big_Buck_Bunny_1080_10s_30MB.mp4"
OPTS = ["--ignore-config", "--no-playlist", "-N", "8", "-o", "f.%(ext)s", "--fixup", "never"]
ENV = dict(os.environ, PATH=os.path.expanduser("~/.local/bin") + os.pathsep + os.environ["PATH"])


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(exe, out, extra=(), stop_at=None):
    """Runs the download. `stop_at`: interrupts it once the partial file reaches this size. Returns the log."""
    log_path = os.path.join(out, f"log-{time.monotonic_ns()}.txt")
    with open(log_path, "w") as log:
        proc = subprocess.Popen([*exe, *OPTS, *extra, "-P", out, "--", URL], stdout=log, stderr=subprocess.STDOUT,
                                env=ENV, start_new_session=True)
        while proc.poll() is None:
            part = os.path.join(out, "f.mp4.part")
            if stop_at and os.path.exists(part) and os.path.getsize(part) >= stop_at:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait()
                break
            time.sleep(0.05)
    with open(log_path, errors="replace") as f:
        return f.read()


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL "), name, detail, flush=True)
    return ok


root = tempfile.mkdtemp(prefix="ytdlp-ranges-")
results = []
try:
    ref = os.path.join(root, "ref.mp4")
    subprocess.run(["curl", "-sL", "-o", ref, URL], check=True)
    want, size = sha(ref), os.path.getsize(ref)
    print(f"reference: {size} bytes", flush=True)

    d = os.path.join(root, "full"); os.makedirs(d)
    log = run(FAST, d)
    results.append(check("full: chunked engine", "[ranges]" in log))
    results.append(check("full: identical to the reference", sha(os.path.join(d, "f.mp4")) == want))
    results.append(check("full: nothing left behind", sorted(f for f in os.listdir(d) if not f.startswith("log-")) == ["f.mp4"]))

    d = os.path.join(root, "resume"); os.makedirs(d)
    run(FAST, d, extra=["--limit-rate", "500K"], stop_at=size * 0.3)
    state = json.load(open(os.path.join(d, "f.mp4.ytdl")))["downloader"]
    done = state["current_fragment"]["index"]
    results.append(check("resume: interrupted midway", 0 < done < state["fragment_count"], f"({done}/{state['fragment_count']} chunks)"))
    log = run(FAST, d)
    results.append(check("resume: chunked engine", "[ranges]" in log))
    results.append(check("resume: identical to the reference", sha(os.path.join(d, "f.mp4")) == want))

    d = os.path.join(root, "plain-partial"); os.makedirs(d)
    run(PLAIN, d, extra=["--limit-rate", "3M"], stop_at=size * 0.3)
    had_part = os.path.exists(os.path.join(d, "f.mp4.part")) and not glob.glob(os.path.join(d, "*.ytdl"))
    results.append(check("plain partial: partial file without chunk state", had_part))
    log = run(FAST, d)
    results.append(check("plain partial: resumed without chunks", "[ranges]" not in log))
    results.append(check("plain partial: identical to the reference", sha(os.path.join(d, "f.mp4")) == want))
finally:
    shutil.rmtree(root, ignore_errors=True)
sys.exit(0 if all(results) else 1)
