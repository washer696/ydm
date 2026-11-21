"""Local server of "videos" for offline tests.

- /slow/...: 16 MB of random bytes served slowly (~80 KB/s per connection), to keep downloads in progress;
- /subs/page.html: a web page playing that video with French subtitles (/subs/fr.vtt), for transcripts;
- any other path: a real small mp4 video (fixtures/tiny.mp4, 1 s), for downloads that run to completion.
Byte ranges (Range header) are supported, as on a real site.
"""
import http.server, os, re, sys, threading, time

SLOW = os.urandom(16 * 1024 * 1024)
TINY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "tiny.mp4")
SUBS_PAGE = b"""<!doctype html><html><head><title>Subtitled video</title></head><body>
<video controls src="/subs/video.mp4"><track kind="subtitles" srclang="fr" label="Fran\xc3\xa7ais" src="/subs/fr.vtt"></video>
</body></html>"""
SUBS_VTT = """WEBVTT

00:00:00.000 --> 00:00:01.500
Bonjour à tous.

00:00:01.500 --> 00:00:03.000
<i>Voici</i> une vidéo de test.
""".encode()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_HEAD(self):
        self.reply(body=False)

    def do_GET(self):
        self.reply(body=True)

    def reply(self, body):
        if self.path in ("/subs/page.html", "/subs/fr.vtt"):
            page = self.path.endswith(".html")
            data = SUBS_PAGE if page else SUBS_VTT
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8" if page else "text/vtt; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if body:
                self.wfile.write(data)
            return
        slow = self.path.startswith("/slow/")
        payload = SLOW if slow else self.server.video
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range") or "")
        start = int(match[1]) if match else 0
        end = min(int(match[2]) if match and match[2] else len(payload) - 1, len(payload) - 1)
        self.send_response(206 if match else 200)
        if match:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        if not body:
            return
        try:
            step = 16384 if slow else len(payload)
            for i in range(start, end + 1, step):
                self.wfile.write(payload[i:min(i + step, end + 1)])
                if slow:
                    time.sleep(0.2)
        except ConnectionError:
            pass  # download cancelled

    def log_message(self, *args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # yt-dlp closes some connections before the end: this is expected.
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


def start():
    """Starts the server; returns (server, base URL). To stop it: server.shutdown()."""
    server = Server(("127.0.0.1", 0), Handler)
    with open(TINY, "rb") as f:
        server.video = f.read()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
