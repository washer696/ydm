"""Drives an official Firefox build (throwaway profile) with the extension loaded, for UI tests.

Prepare the cache once with tools/setup_test_env.sh <cache>, then run the tests with
<cache>/venv/bin/python and the variable YTDLP_TEST_CACHE=<cache>.
"""
import json, os, shutil, tempfile, time

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ["YTDLP_TEST_CACHE"]
UUID = "1b2c3d4e-0000-4000-8000-00000000abcd"
with open(os.path.join(ROOT, "extension", "manifest.json"), encoding="utf-8") as f:
    EXT_ID = json.load(f)["browser_specific_settings"]["gecko"]["id"]
BASE = f"moz-extension://{UUID}/"


def start(dark=False, env=None):
    """`env`: the browser's environment, and so also that of the bridge it launches (see bridge_client.isolated_env)."""
    profile = tempfile.mkdtemp(prefix="ytdlp-ff-profile-")
    o = Options()
    o.add_argument("-headless")
    o.add_argument("-profile")
    o.add_argument(profile)
    o.set_preference("extensions.webextensions.uuids", json.dumps({EXT_ID: UUID}))
    o.set_preference("intl.accept_languages", "fr-FR, fr")
    if dark:
        o.set_preference("layout.css.prefers-color-scheme.content-override", 0)
        o.set_preference("ui.systemUsesDarkTheme", 1)
    o.binary_location = os.path.join(CACHE, "firefox", "firefox")
    service = Service(os.path.join(CACHE, "geckodriver"), service_args=["--allow-system-access"], env=env)
    d = webdriver.Firefox(options=o, service=service)
    d._profile_dir = profile
    d.set_window_size(1200, 900)
    d.install_addon(os.path.join(ROOT, "extension"), temporary=True)
    time.sleep(2)
    return d


def stop(d):
    profile = d._profile_dir
    d.quit()
    shutil.rmtree(profile, ignore_errors=True)


def open_ext(d, path):
    """Opens an extension page in a new tab. Selenium cannot navigate to moz-extension:// directly."""
    before = set(d.window_handles)
    with d.context(d.CONTEXT_CHROME):
        d.execute_script("""
          const win = Services.wm.getMostRecentWindow('navigator:browser');
          win.gBrowser.selectedTab = win.gBrowser.addTab(arguments[0], {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});
        """, BASE + path)
    for _ in range(50):
        new = set(d.window_handles) - before
        if new:
            handle = new.pop()
            d.switch_to.window(handle)
            return handle
        time.sleep(0.1)
    raise RuntimeError("tab did not open")


def ext_js(d, script):
    """Runs async JS in the current extension page; `done(value)` returns the result."""
    return d.execute_async_script(
        "const done = arguments[arguments.length-1]; (async () => {" + script + "})().catch(e => done({jsError: String(e)}));")
