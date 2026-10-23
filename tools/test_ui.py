#!/usr/bin/env python3
"""Tests the UI in a real Firefox: Settings section, folder picker, popup button, removal of a partial file.

Usage: YTDLP_TEST_CACHE=<cache> <cache>/venv/bin/python test_ui.py <screenshots folder>
The installed bridge is used, but its state and its download folder are isolated in a temporary folder.
"""
import os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bridge_client import cleanup, isolated_env, sandbox
from ff import ext_js, open_ext, start, stop
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

BIG = "https://archive.org/download/BigBuckBunny_124/Content/big_buck_bunny_720p_surround.mp4"
shots = sys.argv[1]
os.makedirs(shots, exist_ok=True)
results = []


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL "), name, detail, flush=True)
    results.append(bool(ok))


def wait(d, cond, t=60):
    return WebDriverWait(d, t, poll_frequency=0.1).until(cond)


def text(d, css):
    return d.find_element(By.CSS_SELECTOR, css).text


root = sandbox()
dir_a = os.path.join(root, "A")
os.makedirs(dir_a)
default = subprocess.run(["xdg-user-dir", "VIDEOS"], capture_output=True, text=True).stdout.strip()
d = start(env=isolated_env(root, zenity_answer=dir_a))
try:
    open_ext(d, "downloads.html#reglages")
    wait(d, lambda d: text(d, "#download-dir"))
    check("settings: default folder shown", text(d, "#download-dir") == default, text(d, "#download-dir"))
    check("settings: default folder button hidden", not d.find_element(By.ID, "reset-folder").is_displayed())
    engine = text(d, "#engine-info")
    check("engine: version and check date shown", engine.startswith("version 2") and "vérifié" in engine, engine)
    check("engine: accelerator active", "accélérateur désactivé" not in engine)
    check("engine: update button present", text(d, "#update-engine") == "Mettre à jour")
    d.save_screenshot(os.path.join(shots, "settings-default.png"))

    d.find_element(By.ID, "pick-folder").click()
    wait(d, lambda d: text(d, "#download-dir") == dir_a)
    check("settings: picked folder shown", True, dir_a)
    check("settings: default folder button visible", d.find_element(By.ID, "reset-folder").is_displayed())
    check("settings: pick button restored", text(d, "#pick-folder") == "Choisir…" and d.find_element(By.ID, "pick-folder").is_enabled())
    d.find_element(By.ID, "reglages").screenshot(os.path.join(shots, "settings-picked.png"))

    started = ext_js(d, f"done(await browser.runtime.sendMessage({{type:'download', url:'{BIG}', mode:'video'}}));")
    check("download started", started == {"ok": True}, str(started))
    wait(d, lambda d: "%" in text(d, "#list .entry-meta"))
    d.find_element(By.CSS_SELECTOR, '#list .entry-actions button[title^="Annuler"]').click()
    wait(d, lambda d: text(d, "#list .entry-meta").startswith("Annulé"))
    trash = d.find_element(By.CSS_SELECTOR, '#list .entry-actions button[title^="Retirer"]')
    check("cancelled entry: trash button label", trash.get_attribute("title") == "Retirer et supprimer le fichier partiel")
    check("cancelled entry: partial file in the picked folder", any(f.endswith(".part") for f in os.listdir(dir_a)))
    d.save_screenshot(os.path.join(shots, "settings-with-entry.png"))
    trash.click()
    wait(d, lambda d: not d.find_elements(By.CSS_SELECTOR, "#list .entry"))
    time.sleep(0.5)
    check("trash: partial file deleted", os.listdir(dir_a) == [], str(os.listdir(dir_a)))

    d.find_element(By.ID, "reset-folder").click()
    wait(d, lambda d: text(d, "#download-dir") == default)
    check("settings: back to the default folder", not d.find_element(By.ID, "reset-folder").is_displayed())

    d.set_window_size(600, 900)
    time.sleep(0.3)
    d.find_element(By.ID, "reglages").screenshot(os.path.join(shots, "settings-narrow.png"))
    d.set_window_size(1200, 900)

    tab_id = ext_js(d, "done((await browser.tabs.query({}))[0].id)")
    open_ext(d, f"popup.html?tab={tab_id}")
    gear = wait(d, lambda d: d.find_element(By.CSS_SELECTOR, 'header button[title="Réglages"]'))
    d.find_element(By.TAG_NAME, "body").screenshot(os.path.join(shots, "popup-header.png"))
    handles = set(d.window_handles)
    gear.click()
    wait(d, lambda d: set(d.window_handles) != handles or True)
    time.sleep(1)
    d.switch_to.window(d.window_handles[0])
    urls = []
    for h in d.window_handles:
        d.switch_to.window(h)
        urls.append(d.current_url)
    check("popup: the Settings button opens the section", any(u.endswith("downloads.html#reglages") for u in urls[1:]) and sum(u.endswith("#reglages") for u in urls) >= 2, str(len(urls)))
finally:
    stop(d)

d = start(dark=True, env=isolated_env(root))
try:
    open_ext(d, "downloads.html#reglages")
    wait(d, lambda d: text(d, "#download-dir"))
    time.sleep(0.4)
    d.save_screenshot(os.path.join(shots, "settings-dark.png"))
finally:
    stop(d)
    cleanup(root)
sys.exit(0 if all(results) else 1)
