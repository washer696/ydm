#!/usr/bin/env python3
"""Tests the language setting in a real Firefox: "auto" follows Firefox (French here), and choosing
English or French switches the open Downloads page at once.

Usage: YTDLP_TEST_CACHE=<cache> <cache>/venv/bin/python test_language.py
Offline. The installed bridge is used, but its state is isolated in a temporary folder.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bridge_client import cleanup, isolated_env, sandbox
from ff import ext_js, open_ext, start, stop
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

results = []


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL "), name, detail, flush=True)
    results.append(bool(ok))


def text(d, css):
    return d.find_element(By.CSS_SELECTOR, css).text


def choose(d, value):
    """Picks a language in the settings, as the user would, and waits for the page to reload in it."""
    d.execute_script("document.documentElement.dataset.before = '1'")
    ext_js(d, f"done(await browser.storage.local.set({{lang: '{value}'}}))")
    WebDriverWait(d, 20, poll_frequency=0.1).until(
        lambda d: d.execute_script("return !document.documentElement.dataset.before && document.readyState === 'complete'"))
    WebDriverWait(d, 20, poll_frequency=0.1).until(lambda d: text(d, "#update-engine"))


root = sandbox()
d = start(env=isolated_env(root))
try:
    open_ext(d, "downloads.html")
    WebDriverWait(d, 20).until(lambda d: text(d, "#update-engine"))
    check("auto: follows Firefox (French)", text(d, "#update-engine") == "Mettre à jour" and text(d, "h1") == "Téléchargements")
    check("auto: selected in the picker", d.find_element(By.ID, "language").get_attribute("value") == "auto")

    choose(d, "en")
    check("English: buttons", text(d, "#update-engine") == "Update" and text(d, "#pick-folder") == "Choose…", text(d, "#update-engine"))
    check("English: headings and note", text(d, "h1") == "Downloads" and text(d, ".footnote").startswith("Clearing the history"))
    check("English: page language", d.execute_script("return document.documentElement.lang") == "en")
    check("English: selected in the picker", d.find_element(By.ID, "language").get_attribute("value") == "en")

    choose(d, "fr")
    check("French: buttons", text(d, "#update-engine") == "Mettre à jour" and text(d, "#pick-folder") == "Choisir…")
    check("French: page language", d.execute_script("return document.documentElement.lang") == "fr")

    choose(d, "auto")
    check("back to auto", d.find_element(By.ID, "language").get_attribute("value") == "auto" and text(d, "h1") == "Téléchargements")
finally:
    stop(d)
    cleanup(root)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
