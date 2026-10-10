#!/usr/bin/env python3
"""Check Oregon custom (vanity) plate availability on DMV2U.

Talks to the site's own AJAX endpoints over plain HTTPS, no browser: one session,
walked from the home page to Custom Plate Search once, then each plate is posted
and the result message read. See SKILL.md for the protocol.
"""

import argparse
import html as htmllib
import http.cookiejar
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://dmv2u.oregon.gov/eServices/_/"
POSITIONS = 7

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


def page_text(h):
    h = re.sub(r"<(script|style)\b.*?</\1>", " ", h, flags=re.S)
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", h)).split())


class Session:
    """One DMV2U session. The server keeps the form state; the client must send
    back the rolling Fast-Ver-Last token from the previous response, plus a
    stable window name, on every request."""

    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.ver_last = None
        self.ajax_id = 0
        h = secrets.token_hex(6)
        self.window = f"FWDC.WND-{h[:4]}-{h[4:8]}-{h[8:]}"

    def _common(self):
        self.ajax_id += 1
        return {
            "FAST_SCRIPT_VER__": "1",
            "FAST_VERLAST__": self.ver_last,
            "FAST_VERLAST_SOURCE__": "plate_check",
            "FAST_CLIENT_WHEN__": str(int(time.time() * 1000)),
            "FAST_CLIENT_WINDOW__": self.window,
            "FAST_CLIENT_AJAX_ID__": str(self.ajax_id),
            "FAST_CLIENT_TRIGGER__": "",
            "FAST_CLIENT_SOURCE_ID__": "",
        }

    def _request(self, url, form=None):
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        req = urllib.request.Request(url, data=data, headers={
            "User-Agent": "Mozilla/5.0 (plate_check.py)",
            "X-Requested-With": "XMLHttpRequest",
        })
        with self.opener.open(req, timeout=30) as r:
            if r.headers.get("Fast-Ver-Last"):
                self.ver_last = r.headers["Fast-Ver-Last"]
            return r.read().decode("utf-8")

    def _post(self, endpoint, fields):
        return json.loads(self._request(BASE + endpoint,
                                        {**fields, "DOC_MODAL_ID__": "0", **self._common()}))

    def _event(self, event_id, fields=None):
        r = self._post("EventOccurred", {**(fields or {}), "EVENT__": event_id,
                                         "TYPE__": "0", "CLOSECONFIRMED__": "false",
                                         "SCREENWIDTH__": "1200"})
        if "html" not in r:
            raise RuntimeError(f"EventOccurred returned no page: {json.dumps(r)[:200]}")
        return r["html"]

    def open_search(self):
        home = self._request(BASE)
        m = re.search(r"setVerLast\('([^']+)'", home)
        if not m:
            raise RuntimeError("home page has no setVerLast token")
        self.ver_last = m[1]
        load = json.loads(self._request(BASE + "?" + urllib.parse.urlencode(
            {"Load": "1", **self._common(), "FAST_CLIENT_TRIGGER__": "InitPage"})))
        page = next(c["manager"] for c in load["contents"] if "manager" in c)
        page = self._event(link_id(page, "Order a new plate"))
        self._read_form(self._event(link_id(page, "Check custom plate availability")))

    def _read_form(self, page):
        """Field and button ids are generated (Dc-c... today), so find them by label."""
        self.fields = [field_id(page, f"Position {i + 1}") for i in range(POSITIONS)]
        self.search_button = link_id(page, "Search")

    def check(self, plate):
        fields = {f: (plate[i] if i < len(plate) else "") for i, f in enumerate(self.fields)}
        fields["LASTFOCUSFIELD__"] = self.fields[-1]
        # Recalc is what the browser sends on each keystroke; it is what
        # enables the Search button on the server's copy of the form.
        self._post("Recalc", fields)
        page = self._event(self.search_button, fields)
        msg = result_message(page)
        if TAKEN_MARK in msg:
            return "TAKEN", msg
        if AVAILABLE_MARK in msg:
            return "AVAILABLE", msg
        if os.environ.get("PLATE_DEBUG"):
            with open(f"/tmp/plate-err-{plate}.html", "w") as fh:
                fh.write(page)
        return "UNKNOWN", msg


def link_id(page, caption):
    m = re.search(r'data-linkid="([^"]+)"(?:(?!</a>|</button>).)*?>\s*'
                  + re.escape(caption) + r"\s*<", page, re.S)
    if not m:
        raise RuntimeError(f"no link or button captioned {caption!r}")
    return m[1]


def field_id(page, label):
    m = re.search(r'<label[^>]*\bfor="([^"]+)"[^>]*>(?:(?!</label>).)*?>\s*'
                  + re.escape(label) + r"\s*<", page, re.S)
    if not m:
        raise RuntimeError(f"no field labelled {label!r}")
    return m[1]


def result_message(page):
    """The message sits between the Search button and the page footer."""
    tail = page_text(page).rsplit("Search", 1)[-1]
    for stop in ("Click here to get started", "Scroll for More", "Cancel"):
        tail = tail.split(stop, 1)[0]
    return " ".join(tail.split())


def attempt(session, plate):
    try:
        return session.check(plate)
    except Exception as e:  # keep going; report the plate as unknown
        return "UNKNOWN", f"error: {e.__class__.__name__}: {str(e).splitlines()[0]}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plates", nargs="*", help="plate texts, e.g. SAFARI 'SAF-ARI'")
    ap.add_argument("-f", "--file", help="file with one plate per line")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="seconds between searches (default 2; be polite to a state site)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
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
        session = Session()
        session.open_search()
        for n, p in enumerate(todo):
            if n:
                time.sleep(args.delay)
            status, msg = attempt(session, p)
            if status == "UNKNOWN":  # one retry from a fresh session
                try:
                    session = Session()
                    session.open_search()
                except Exception:
                    pass
                status, msg = attempt(session, p)
            results.append({"plate": p, "status": status, "message": msg})
            if not args.json:
                print_row(results[-1])

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
