#!/usr/bin/env python3
"""Checks that the range downloader works with the installed yt-dlp version.

Usage: selftest.py [path to ytdlp_fast.py]
Serves a random file on 127.0.0.1, downloads it with the accelerator and compares the hashes.
Everything stays local: no Internet access. Exit code 0 if the file is identical and
ranges were actually requested in parallel.
"""
import hashlib
import http.server
import os
import re
import subprocess
import sys
import tempfile
import threading

FAST = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.realpath(__file__)), "ytdlp_fast.py")
PAYLOAD = os.urandom(5 * 1024 * 1024 + 123)  # three ranges, the last one incomplete
ranges = []


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_HEAD(self):
        self.reply(body=False)

    def do_GET(self):
        self.reply(body=True)

    def reply(self, body):
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range") or "")
        if match:
            start = int(match[1])
            end = min(int(match[2]) if match[2] else len(PAYLOAD) - 1, len(PAYLOAD) - 1)
            ranges.append((start, end))
            data = PAYLOAD[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(PAYLOAD)}")
        else:
            data = PAYLOAD
            self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if body:
            self.wfile.write(data)

    def log_message(self, *args):
        pass


class Server(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # yt-dlp closes some connections before the end (first read, end of a range): that's expected.
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


def main():
    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/selftest.mp4"
    with tempfile.TemporaryDirectory(prefix="ytdlp-selftest-") as out:
        try:
            run = subprocess.run(
                [sys.executable, FAST, "--ignore-config", "--no-playlist", "-N", "8", "--fixup", "never",
                 "-P", out, "-o", "f.%(ext)s", "--", url],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"could not start ({e})"
        path = os.path.join(out, "f.mp4")
        if run.returncode != 0 or not os.path.isfile(path):
            return "the download failed: " + (run.stderr.strip().splitlines() or ["no message"])[-1][:200]
        with open(path, "rb") as f:
            if hashlib.sha256(f.read()).digest() != hashlib.sha256(PAYLOAD).digest():
                return "the rebuilt file differs from the original"
    if len({r for r in ranges if r != (0, 0)}) < 2:
        return "no range was requested: the accelerator is not active"
    return None


if __name__ == "__main__":
    problem = main()
    print("FAILED: " + problem if problem else "OK")
    sys.exit(1 if problem else 0)
