---
name: plate-check
description: Check whether Oregon custom (vanity) license plate configurations are available, using the Oregon DMV2U Custom Plate Search. Use when the user asks if a vanity or custom plate is taken or available in Oregon, wants to check a list of plate ideas, or wants variants of a plate tried. Invoke on /plate-check, "is SAFARI available as a plate", "check these vanity plates", "find me an available custom plate like X".
---

# Plate check

    ~/.claude/skills/plate-check/scripts/plate_check.py SAFARI 'SAF-ARI' SAFAR1

Flags: `-f FILE` for one plate per line, `--json` for machine output,
`--delay N` for seconds between searches (default 2). Plates are upper-cased
and de-duplicated. The script is plain Python 3 standard library over HTTPS: no
browser, no dependencies.

Output carries state by shape and weight as well as the word, never hue alone:

    ● 'QZ7XK9'   AVAILABLE      filled, bold
    ○ 'SAFARI'   TAKEN          hollow, faint
    × 'SAF!'     INVALID        rejected locally, never sent
    ? 'XYZ'      UNKNOWN        site said something unrecognised, or failed twice

## How it talks to DMV2U

DMV2U runs on FAST Enterprises' WDC framework. The server keeps the form state
for the session; a cookie jar plus a rolling token is enough to drive it
without a browser (worked out on 2026-10-10, replacing a Playwright version):

1. `GET /eServices/_/` sets cookies. The page contains
   `FWDC.setVerLast('<token>')`.
2. `GET /eServices/_/?Load=1&...` returns JSON whose `contents[].manager` is the
   page HTML.
3. Every request carries `FAST_VERLAST__` (the token from the last response's
   `Fast-Ver-Last` header), a stable `FAST_CLIENT_WINDOW__`
   (`FWDC.WND-xxxx-xxxx-xxxx`) and an incrementing `FAST_CLIENT_AJAX_ID__`.
   Getting these out of step is what produces the "you have duplicated a
   browser tab" error.
4. A link click is `POST EventOccurred` with `EVENT__=<data-linkid>&TYPE__=0`
   plus the form fields; the response's `html` is the next page. Two clicks:
   *Order a new plate*, then *Check custom plate availability*.
5. A search posts the seven positions to `POST Recalc` (what the browser sends
   per keystroke; it enables Search on the server's copy of the form), then
   `EventOccurred` with the Search button's id.

Field and button ids are generated (`Dc-c`…`Dc-i` for positions, `Dc-k` for
Search today), so the script finds them by their labels "Position N" and
"Search".

## What to check if it breaks

- **Result text** is matched on two strings, verified against the live site:
  - taken: "The configuration provided is already taken."
  - available: "You may apply for a custom plate with the configuration
    selected; availability is subject to final DMV approval."

  Any other message comes back `UNKNOWN` with its text, which is how a new
  rejection message (for example, an objectionable-content rule) would first
  show up. Add it to the script once you've seen it.
- **A link or label not found**: the site changed its wording. The error names
  the caption it looked for.
- **Captcha**: the site's CSP allows hCaptcha, though the search didn't use one
  as of 2026-10-10. If one appears, this approach stops working.
- The session idles out after about 15 minutes (`Fast-Session-Idle` header).

A plate that fails is retried once from a fresh session. Set `PLATE_DEBUG=1` to
save the returned page HTML to `/tmp/plate-err-<PLATE>.html` when a result is
unrecognised.

## Rules (as printed on the DMV page)

Up to 6 letters or numbers, with at least one. Dashes and spaces are allowed,
plus one extra dash or space as a 7th character. The script checks these
before searching. Some specialty plate designs allow fewer characters. This
search doesn't take a design, so it doesn't check that.

## Reporting to the user

- "Available" means the DMV said *"availability is subject to final DMV
  approval"*. Pass that on, and don't present it as a reservation. Nothing is
  held until they apply.
- Dash and space variants of a taken plate have come back taken too
  (SAF-ARI, SAF ARI and SAFARI- all did while SAFARI was taken). Expect that
  when suggesting alternatives.
- This is a state website. Keep the default delay, and don't run hundreds of
  plates in one go without asking.
- Don't click through to *Click here to get started* or buy anything. Applying
  is for the user to do.
