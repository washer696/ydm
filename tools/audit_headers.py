#!/usr/bin/env python3
"""Records what a site actually receives, from the browser and then from the extension, for the same video.

Usage: YTDLP_TEST_CACHE=<cache> <cache>/venv/bin/python audit_headers.py
Two fake local sites log every request: a "page" site (localhost) that sets a cookie
and carries a token in its address, and a "media" site (127.0.0.1) that serves the video.
The browser opens the page, then the extension downloads the detected video and analyzes the page.
"""
import http.server, json, os, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bridge_client import cleanup, isolated_env, sandbox
from ff import ext_js, open_ext, start, stop
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

VIDEO = os.urandom(2 * 1024 * 1024 + 7)
log = []
issued = {}  # cookie value -> client the site gave it to
phase = ["browser"]


def handler(site, respond):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_HEAD(self):
            self.answer(False)

        def do_GET(self):
            self.answer(True)

        def answer(self, body):
            log.append({"phase": phase[0], "site": site, "method": self.command, "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()}})
            respond(self, body)

        def log_message(self, *args):
            pass
    return H


def serve(site, respond):
    class Quiet(http.server.ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            pass
    server = Quiet(("127.0.0.1", 0), handler(site, respond))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


def give_cookie(h, name):
    """Each response sets a unique cookie, so we can later tell who sends back whose cookie."""
    if name + "=" in (h.headers.get("Cookie") or ""):
        return
    value = f"{name}-{len(issued) + 1}"
    issued[value] = "browser" if "Firefox/" in (h.headers.get("User-Agent") or "") else "yt-dlp"
    h.send_header("Set-Cookie", f"{name}={value}; Path=/")


def media(h, body):
    rng = h.headers.get("Range") or ""
    data = VIDEO
    if rng.startswith("bytes="):
        a, _, b = rng[6:].partition("-")
        start_, end = int(a), min(int(b) if b else len(VIDEO) - 1, len(VIDEO) - 1)
        data = VIDEO[start_:end + 1]
        h.send_response(206)
        h.send_header("Content-Range", f"bytes {start_}-{end}/{len(VIDEO)}")
    else:
        h.send_response(200)
    h.send_header("Content-Type", "video/mp4")
    h.send_header("Accept-Ranges", "bytes")
    give_cookie(h, "media_id")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    if body:
        h.wfile.write(data)


media_port = serve("media", media)


def page(h, body):
    html = (f'<!doctype html><title>Test page</title><video src="http://127.0.0.1:{media_port}/media/video.mp4" '
            'autoplay muted playsinline></video>').encode()
    h.send_response(200)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    give_cookie(h, "site_session")
    h.send_header("Content-Length", str(len(html)))
    h.end_headers()
    if body:
        h.wfile.write(html)


page_port = serve("page", page)
page_url = f"http://localhost:{page_port}/watch?v=1&token=SECRET-TOKEN"

root = sandbox()
out = os.path.join(root, "out")
os.makedirs(out)
d = start(env=isolated_env(root, zenity_answer=out))
try:
    d.get(page_url)
    time.sleep(2)
    d.get(page_url)  # second visit: the browser now sends its cookies back
    time.sleep(3)
    tab_id = ext_js_tab = None
    open_ext(d, "downloads.html")
    ext_js(d, "done(await browser.runtime.sendMessage({type:'pickFolder'}))")
    tab_id = ext_js(d, "done((await browser.tabs.query({})).find(t => t.url.includes('SECRET-TOKEN')).id)")
    state = ext_js(d, f"done(await browser.runtime.sendMessage({{type:'getState', tabId:{tab_id}}}))")
    print("streams detected by the extension:", [m["url"].split("/", 3)[-1] for m in state["media"]], flush=True)

    phase[0] = "extension: stream download"
    open_ext(d, f"popup.html?tab={tab_id}")
    WebDriverWait(d, 30).until(lambda d: d.find_elements(By.CSS_SELECTOR, "#streams .stream"))
    d.find_element(By.CSS_SELECTOR, '#streams .stream button[title^="Télécharger"]').click()
    WebDriverWait(d, 90).until(lambda d: any(e.text.startswith(("Terminé", "Échec")) for e in d.find_elements(By.CSS_SELECTOR, "#downloads .entry-meta")))
    print("result:", d.find_element(By.CSS_SELECTOR, "#downloads .entry-meta").text.split("\n")[0], "| files:", os.listdir(out), flush=True)

    phase[0] = "browser: direct visit to the media site"
    d.switch_to.new_window("tab")
    d.get(f"http://127.0.0.1:{media_port}/home")
    time.sleep(1)
    phase[0] = "extension: thumbnail shown in the history"
    open_ext(d, "downloads.html")
    ext_js(d, f"""
      const img = document.createElement('img');
      img.referrerPolicy = 'no-referrer';
      img.src = 'http://127.0.0.1:{media_port}/thumbnail.jpg';
      document.body.append(img);
      await new Promise(r => setTimeout(r, 1500));
      done(true);
    """)

    phase[0] = "extension: page analysis"
    res = ext_js(d, f"done(await browser.runtime.sendMessage({{type:'formats', url:'{page_url}'}}))")
    print("page analysis:", "error" if res.get("error") else f"{len(res.get('qualities', []))} quality option(s)", flush=True)
    time.sleep(1)
finally:
    stop(d)
    cleanup(root)

SHOW = ["user-agent", "referer", "cookie", "accept-language", "origin", "range"]
seen = {}
for r in log:
    key = (r["phase"], r["site"])
    entry = seen.setdefault(key, {"count": 0, "paths": set(), "headers": {}, "names": set()})
    entry["count"] += 1
    entry["paths"].add(r["path"].split("?")[0])
    entry["names"].update(r["headers"])
    for name in SHOW:
        if name in r["headers"]:
            entry["headers"].setdefault(name, set()).add(r["headers"][name] if name != "range" else "present")
for (ph, site), e in seen.items():
    print(f"\n=== {ph} -> {site} site: {e['count']} request(s) to {sorted(e['paths'])}")
    for name in SHOW:
        values = sorted(e["headers"].get(name, []))
        print(f"   {name:16} {values if values else 'ABSENT'}")
    print("   other headers:", sorted(e["names"] - set(SHOW) - {"host", "connection", "accept", "accept-encoding"}))

print("\n=== cookies: given to whom, sent back by whom")
for value, owner in issued.items():
    senders = sorted({("browser" if "Firefox/" in r["headers"].get("user-agent", "") else "yt-dlp")
                      for r in log if value in r["headers"].get("cookie", "")})
    print(f"   {value:18} given to {owner:10} sent back by {senders or 'nobody'}")
leak = [v for v, owner in issued.items() if owner == "browser"
        and any(v in r["headers"].get("cookie", "") and "Firefox/" not in r["headers"].get("user-agent", "") for r in log)]
print("   browser cookie seen in a yt-dlp request:", leak or "none")
