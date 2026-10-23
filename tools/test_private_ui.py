#!/usr/bin/env python3
"""Tests private browsing in a real Firefox: a private download only appears in private
windows, and it is forgotten when the last private window closes.

Usage: YTDLP_TEST_CACHE=<cache> <cache>/venv/bin/python test_private_ui.py
Offline (local server, see local_videos.py). The installed bridge is used, but its state and its
download folder are isolated in a temporary folder.
"""
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import local_videos
from bridge_client import cleanup, isolated_env, sandbox
from ff import EXT_ID, ext_js, open_ext, start, stop

results = []
PRIVATE_UTILS = 'const { PrivateBrowsingUtils } = ChromeUtils.importESModule("resource://gre/modules/PrivateBrowsingUtils.sys.mjs");'


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL "), name, detail, flush=True)
    results.append(bool(ok))


def allow_private(d):
    """Allows YDM in private windows (the box ticked at install time), then reloads it so that it takes effect."""
    with d.context(d.CONTEXT_CHROME):
        d.execute_async_script("""
          const done = arguments[arguments.length - 1];
          const id = arguments[0];
          const { ExtensionPermissions } = ChromeUtils.importESModule("resource://gre/modules/ExtensionPermissions.sys.mjs");
          const { AddonManager } = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
          (async () => {
            await ExtensionPermissions.add(id, {permissions: ["internal:privateBrowsingAllowed"], origins: []});
            await (await AddonManager.getAddonByID(id)).reload();
          })().then(() => done(true), (e) => done(String(e)));""", EXT_ID)
    time.sleep(2)


def entries(d, incognito):
    flag = "true" if incognito else "false"
    return ext_js(d, f"done((await browser.runtime.sendMessage({{type: 'getState', incognito: {flag}}})).entries)")


def poll(fn, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.5)
    return None


server, base = local_videos.start()
root = sandbox()
out = os.path.join(root, "videos")
os.makedirs(out)
d = start(env=isolated_env(root, zenity_answer=out))
try:
    allow_private(d)
    normal = open_ext(d, "downloads.html")
    ext_js(d, "done(await browser.runtime.sendMessage({type: 'pickFolder'}))")

    with d.context(d.CONTEXT_CHROME):
        d.execute_script("Services.wm.getMostRecentWindow('navigator:browser').OpenBrowserWindow({private: true});")
        # open_ext opens the page in the most recent window: wait until that is the private one.
        poll(lambda: d.execute_script(PRIVATE_UTILS + """
          const w = Services.wm.getMostRecentWindow('navigator:browser');
          return PrivateBrowsingUtils.isWindowPrivate(w) && w.document.readyState === 'complete';"""), timeout=20)
    open_ext(d, "downloads.html")
    check("page open in the private window", ext_js(d, "done(browser.extension.inIncognitoContext)") is True)
    res = ext_js(d, f"""done(await browser.runtime.sendMessage({{type: 'download', url: '{base}/private.mp4', mode: 'video',
                     title: 'Vidéo privée', pageTitle: true, private: true}}))""")
    check("private download started", res == {"ok": True}, str(res))
    done = poll(lambda: [e for e in entries(d, True) if e.get("private") and e["status"] == "done"])
    check("private download finished", bool(done))

    d.switch_to.window(normal)
    check("normal window: private download hidden", not any(e.get("private") for e in entries(d, False)))

    with d.context(d.CONTEXT_CHROME):
        d.execute_script(PRIVATE_UTILS + """
          for (const w of Services.wm.getEnumerator('navigator:browser'))
            if (PrivateBrowsingUtils.isWindowPrivate(w)) w.close();""")
    gone = poll(lambda: not any(e.get("private") for e in entries(d, True)), timeout=20)
    check("last private window closed: download forgotten", bool(gone))
    check("video kept on disk", bool(done) and os.path.isfile(done[0]["file"]))
finally:
    stop(d)
    server.shutdown()
    cleanup(root)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
