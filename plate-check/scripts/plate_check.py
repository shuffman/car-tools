#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Check Oregon custom (vanity) plate availability on DMV2U.

Drives the real site in headless Google Chrome: one session, walked from the home
page to Custom Plate Search once, then each plate is filled in, searched and read.
A bare HTTP POST does not work here -- see SKILL.md for why.
"""

import argparse
import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

HOME = "https://dmv2u.oregon.gov/eServices/_/"
POSITIONS = 7
LIVE_MAIN = "main#MANAGER_CONTROL__0"

TAKEN_MARK = "already taken"
AVAILABLE_MARK = "You may apply for a custom plate"

# State carried by shape, weight and word, never hue: filled + bright for
# available, hollow + faint for taken, "?" for anything the script did not
# recognise or could not submit.
MARK = {"AVAILABLE": "●", "TAKEN": "○", "INVALID": "×", "UNKNOWN": "?"}


def validate(plate):
    """Mirror the rules printed on the DMV page. Returns an error string or None."""
    if len(plate) > POSITIONS:
        return f"longer than {POSITIONS} characters"
    if not re.fullmatch(r"[A-Z0-9 -]+", plate):
        return "only letters, numbers, dashes and spaces are allowed"
    alnum = sum(c.isalnum() for c in plate)
    if alnum == 0:
        return "needs at least one letter or number"
    if alnum > 6:
        return "more than 6 letters/numbers"
    return None


def click_until(page, target, expect, tries=4):
    """Click `target` until `expect` shows up. The home page renders its links
    before its scripts are wired, so an early click is silently dropped."""
    for _ in range(tries):
        target.click()
        try:
            expect.wait_for(timeout=5000)
            return
        except Exception:
            pass
    expect.wait_for(timeout=5000)  # raise with a useful locator in the message


def open_search(page):
    page.goto(HOME, wait_until="networkidle")
    link = page.get_by_text("Check custom plate availability").first
    click_until(page, page.get_by_role("link", name="Order a new plate").first, link)
    click_until(page, link, page.get_by_label("Position 1", exact=True))


def settled(page):
    """While re-rendering, the site briefly keeps the outgoing copy of the page
    as a second <main>, so every field exists twice. Wait for the old one to go
    and return the live one."""
    page.wait_for_load_state("networkidle")
    # Polled from Python: the site's CSP forbids unsafe-eval, which
    # page.wait_for_function needs.
    for _ in range(60):
        if page.locator("main").count() == 1:
            break
        page.wait_for_timeout(250)
    else:
        raise TimeoutError("page did not settle to one <main> within 15s")
    return page.locator(LIVE_MAIN)


def result_message(main):
    """The message sits between the Search button and the page footer."""
    tail = main.inner_text().rsplit("Search", 1)[-1]
    for stop in ("Click here to get started", "Scroll for More", "Cancel"):
        tail = tail.split(stop, 1)[0]
    return " ".join(tail.split())


def check(page, plate):
    main = settled(page)
    for i in range(POSITIONS):
        box = main.get_by_label(f"Position {i + 1}", exact=True)
        box.fill("")
        if i < len(plate):
            box.fill(plate[i])
    # Each box change posts to /Recalc; let those finish before searching.
    main = settled(page)
    with page.expect_response(lambda r: "EventOccurred" in r.url):
        main.get_by_role("button", name="Search").click()
    msg = result_message(settled(page))
    if TAKEN_MARK in msg:
        return "TAKEN", msg
    if AVAILABLE_MARK in msg:
        return "AVAILABLE", msg
    return "UNKNOWN", msg


def attempt(page, plate):
    try:
        return check(page, plate)
    except Exception as e:  # keep going; report the plate as unknown
        if os.environ.get("PLATE_DEBUG"):
            page.screenshot(path=f"/tmp/plate-err-{plate}.png", full_page=True)
        return "UNKNOWN", f"error: {e.__class__.__name__}: {str(e).splitlines()[0]}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plates", nargs="*", help="plate texts, e.g. SAFARI 'SAF-ARI'")
    ap.add_argument("-f", "--file", help="file with one plate per line")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="seconds between searches (default 2; be polite to a state site)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    args = ap.parse_args()

    plates = [p.upper() for p in args.plates]
    if args.file:
        with open(args.file) as fh:
            plates += [ln.rstrip("\n").upper() for ln in fh if ln.strip()]
    plates = list(dict.fromkeys(plates))  # de-dupe, keep order
    if not plates:
        ap.error("give at least one plate")

    results = []
    todo = []
    for p in plates:
        err = validate(p)
        if err:
            results.append({"plate": p, "status": "INVALID", "message": err})
        else:
            todo.append(p)

    if todo:
        with sync_playwright() as pw:
            # Installed Chrome, not Playwright's bundled build: no browser download,
            # and a Playwright upgrade cannot leave the script pointing at a missing binary.
            browser = pw.chromium.launch(channel="chrome", headless=not args.headed)
            page = browser.new_page()
            open_search(page)
            for n, p in enumerate(todo):
                if n:
                    page.wait_for_timeout(args.delay * 1000)
                status, msg = attempt(page, p)
                if status == "UNKNOWN":  # one retry from a freshly loaded search page
                    try:
                        open_search(page)
                    except Exception:
                        pass
                    status, msg = attempt(page, p)
                results.append({"plate": p, "status": status, "message": msg})
                if not args.json:
                    print_row(results[-1])
            browser.close()

    order = {p: i for i, p in enumerate(plates)}
    results.sort(key=lambda r: order[r["plate"]])
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            if r["status"] == "INVALID":
                print_row(r)
        counts = {s: sum(r["status"] == s for r in results) for s in MARK}
        print(f"\n{counts['AVAILABLE']} available · {counts['TAKEN']} taken"
              + (f" · {counts['INVALID']} invalid" if counts["INVALID"] else "")
              + (f" · {counts['UNKNOWN']} unknown" if counts["UNKNOWN"] else ""))
    return 0


def print_row(r):
    tty = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    line = f"{MARK[r['status']]} {r['plate']!r:<10} {r['status']}"
    if r["status"] in ("INVALID", "UNKNOWN"):
        line += f"  {r['message']}"
    if tty and r["status"] != "AVAILABLE":
        line = f"\033[2m{line}\033[0m"  # faint: the absent state reads lighter
    elif tty:
        line = f"\033[1m{line}\033[0m"
    print(line, flush=True)


if __name__ == "__main__":
    sys.exit(main())
