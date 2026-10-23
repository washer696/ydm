#!/usr/bin/env python3
"""Checks the installation done by install.py, as Firefox will see it: manifest in place (in the
registry on Windows), restricted to YDM, and a launcher that answers the protocol with the real installed yt-dlp.

Usage: test_install.py   (after install.py)
Offline. The state of the launched bridge is isolated in a temporary folder.
"""
import json, os, sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.dirname(TOOLS))
import install
from bridge_client import WINDOWS, Bridge, cleanup, isolated_env, sandbox

results = []


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL "), name, detail, flush=True)
    results.append(bool(ok))


path = install.manifest_path()
if WINDOWS:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Mozilla\NativeMessagingHosts\{install.HOST_NAME}") as key:
        registered = winreg.QueryValueEx(key, "")[0]
    check("registry: points to the manifest", os.path.normcase(registered) == os.path.normcase(path), registered)
with open(path, encoding="utf-8") as f:
    manifest = json.load(f)
check("manifest: restricted to YDM", manifest["allowed_extensions"] == [install.extension_id()], str(manifest["allowed_extensions"]))
check("manifest: launcher present", os.path.isfile(manifest["path"]), manifest["path"])

root = sandbox()
b = None
try:
    b = Bridge(isolated_env(root), cmd=[manifest["path"]])
    s = b.call("settings", timeout=180)  # on first launch, the bridge runs its self-test
    check("installed bridge: answers", s["type"] == "settings")
    check("installed bridge: yt-dlp found", bool(s["ytdlp"]["version"]), str(s["ytdlp"]))
    check("installed bridge: accelerator validated", s["ytdlp"]["fast"] is True, str(s["ytdlp"]))
    c = b.call("check", url="https://archive.org/details/BigBuckBunny_124")
    check("installed bridge: yt-dlp library loaded", c.get("extractor") == "archive.org", str(c))
finally:
    if b:
        b.close()
    cleanup(root)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
