#!/usr/bin/env python3
"""Tests transcripts (subtitles without the video) through the bridge's real protocol, in an isolated environment.

Usage: test_subs.py
Fully offline: a local server serves a page whose video has French subtitles. Also checks, on
YouTube-like scrolling captions, that each line is kept once. Does not touch the real history,
settings or videos folder.
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import local_videos
from bridge_client import BRIDGE, Bridge, cleanup, isolated_env, sandbox

results = []


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL "), name, detail, flush=True)
    results.append(bool(ok))


# YouTube's automatic captions: each line shows up in several cues, and a cue can hold an empty line.
ROLLING = """1
00:00:00,000 --> 00:00:01,270

Bon, allez, on va parler

2
00:00:01,270 --> 00:00:01,280
Bon, allez, on va parler


3
00:00:01,280 --> 00:00:03,310
Bon, allez, on va parler
de notre pays.

4
00:00:03,310 --> 00:00:03,320
de notre pays.

"""

# Run in a separate process: importing the bridge creates its state folders, isolated here.
UNIT = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
import ytdlp_bridge as b
folder = sys.argv[2]
with open(os.path.join(folder, "v [x].fr-orig.srt"), "w", encoding="utf-8") as f:
    f.write(sys.argv[3])
e = {"dir": folder, "stem": "v [x]", "lang": "fr-orig", "auto": True}
srt = b.subtitle_file(e)
txt = b.write_transcript(e, srt)
print(json.dumps({"cues": b.read_cues(srt), "txt": open(txt, encoding="utf-8").read(),
                  "langs": [b.clean_lang(v) for v in ("es-419", "fr-orig", "all", "en.*", "-x", "")]}))
"""

server, base = local_videos.start()
page = f"{base}/subs/page.html"
root = sandbox()
out = os.path.join(root, "videos")
os.makedirs(out)
b = None
try:
    env = isolated_env(root, zenity_answer=out)
    unit = json.loads(subprocess.run(
        [sys.executable, "-c", UNIT, os.path.dirname(BRIDGE), out, ROLLING],
        env=env, capture_output=True, text=True, check=True).stdout)
    check("scrolling captions: each line once, at its first appearance",
          unit["cues"] == [["00:00:00,000", "00:00:01,270", ["Bon, allez, on va parler"]],
                           ["00:00:01,280", "00:00:03,310", ["de notre pays."]]], str(unit["cues"]))
    check("plain text: the lines joined", unit["txt"] == "Bon, allez, on va parler de notre pays.\n", repr(unit["txt"]))
    check("language codes: only plain codes, never 'all' or a pattern",
          unit["langs"] == ["es-419", "fr-orig", None, None, None, None], str(unit["langs"]))
    os.remove(os.path.join(out, "v [x].fr-orig.srt"))
    os.remove(os.path.join(out, "v [x].fr-orig.txt"))

    b = Bridge(env)
    assert b.call("pickFolder").get("download_dir") == out

    f = b.call("formats", url=page)
    check("formats lists the subtitles", f.get("subtitles") == [{"lang": "fr", "auto": False}], str(f.get("subtitles") or f.get("error")))

    refused = b.call("download", url=page, mode="subs", lang="all")
    check("language 'all' refused", refused.get("code") == "bad_lang", refused.get("error") or refused["type"])

    eid = b.call("download", url=page, mode="subs", lang="fr", label="Transcript · French")["entry"]["id"]
    e = b.entry_until(eid, lambda e: e["status"] not in ("downloading", "queued"), timeout=60)
    check("transcript downloaded", e["status"] == "done", e.get("error") or "")
    txt = e.get("file") or ""
    check("the file is the plain text", txt.endswith(".fr.txt") and os.path.isfile(txt), txt)
    if os.path.isfile(txt):
        with open(txt, encoding="utf-8") as fh:
            body = fh.read()
        check("plain text without timings or tags", body == "Bonjour à tous. Voici une vidéo de test.\n", repr(body))
        check("the .srt is kept next to it", os.path.isfile(txt[:-4] + ".srt"))
    videos = [n for n in os.listdir(out) if n.endswith((".mp4", ".part"))]
    check("no video downloaded", not videos, str(videos))

    eid = b.call("download", url=page, mode="subs", lang="de")["entry"]["id"]
    e = b.entry_until(eid, lambda e: e["status"] not in ("downloading", "queued"), timeout=60)
    check("missing language: a clear failure", e["status"] == "failed" and "no subtitles" in (e.get("error") or ""),
          f"{e['status']}: {e.get('error')}")
finally:
    if b:
        b.close()
    server.shutdown()
    cleanup(root)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
