"""Playwright screenshot batch using the pre-installed chromium.

Usage: python shots.py [--mobile] <out-prefix> URL [URL ...]
Writes full-page PNGs to <out-prefix>01.png, 02.png, ...
"""
import glob
import sys
import time

from playwright.sync_api import sync_playwright

args = sys.argv[1:]
mobile = "--mobile" in args
if mobile:
    args.remove("--mobile")
prefix, urls = args[0], args[1:]
viewport = {"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900}

chrome = sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux/chrome"))
exe = chrome[-1] if chrome else "/opt/pw-browsers/chromium"

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=exe)
    page = browser.new_page(viewport=viewport)
    for i, url in enumerate(urls, 1):
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(1.5)
        out = f"{prefix}{i:02d}.png"
        page.screenshot(path=out, full_page=True)
        print(out)
    browser.close()
