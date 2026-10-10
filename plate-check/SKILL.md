---
name: plate-check
description: Check whether Oregon custom (vanity) license plate configurations are available, using the Oregon DMV2U Custom Plate Search. Use when the user asks if a vanity or custom plate is taken or available in Oregon, wants to check a list of plate ideas, or wants variants of a plate tried. Invoke on /plate-check, "is SAFARI available as a plate", "check these vanity plates", "find me an available custom plate like X".
---

# Plate check

    ~/.claude/skills/plate-check/scripts/plate_check.py SAFARI 'SAF-ARI' SAFAR1

Flags: `-f FILE` for one plate per line, `--json` for machine output,
`--delay N` for seconds between searches (default 2), `--headed` to watch the
browser. Plates are upper-cased and de-duplicated. The script runs through `uv`
with inline dependencies, so there is nothing to install. It drives the
**installed Google Chrome** (`channel="chrome"`), not Playwright's bundled
browser, so no browser download is needed and a Playwright upgrade can't
break it.

Output carries state by shape and weight as well as the word, never hue alone:

    ● 'QZ7XK9'   AVAILABLE      filled, bold
    ○ 'SAFARI'   TAKEN          hollow, faint
    × 'SAF!'     INVALID        rejected locally, never sent
    ? 'XYZ'      UNKNOWN        site said something unrecognised, or failed twice

## Why a browser and not an HTTP POST

Probed on 2026-09-29. DMV2U is a stateful single-page app, and a bare POST can't
reach the search:

- Search is `POST /eServices/_/EventOccurred`. Each character typed also posts to
  `/Recalc`, so the server keeps its own copy of the form.
- The server tracks your place in the session. Opening the page in a second tab
  gets "you have duplicated a browser tab… this is not allowed", so you can't
  jump straight to the search step.
- Field names are generated (`Dc-c`…`Dc-i` for positions 1–7).

The script walks Home → *Order a new plate* → *Check custom plate availability*
once, then loops over the plates in that one session.

## Site quirks the script handles (and what to check if it breaks)

- **Early clicks are dropped.** The home page shows its links before its scripts
  are ready. `click_until` retries a click until the next page's element appears.
- **Two `<main>` elements during re-render.** The outgoing copy of the page
  stays for about 250 ms, so every field briefly exists twice. The live one is
  `main#MANAGER_CONTROL__0`. `settled()` waits until only one is left.
- **CSP forbids `unsafe-eval`**, so `page.wait_for_function` fails at once.
  Poll from Python instead.
- **Result text** is matched on two strings, verified against the live site:
  - taken: "The configuration provided is already taken."
  - available: "You may apply for a custom plate with the configuration
    selected; availability is subject to final DMV approval."

  Any other message comes back `UNKNOWN` with its text, which is how a new
  rejection message (for example, an objectionable-content rule) would first
  show up. Add it to the script once you've seen it.

A plate that fails is retried once from a freshly loaded search page. Set
`PLATE_DEBUG=1` to save a full-page screenshot to `/tmp/plate-err-<PLATE>.png`
on each failure.

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
