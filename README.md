# car-tools

Small car-related tools, packaged as [Claude Code](https://claude.com/claude-code)
skills. Each directory is one skill: a `SKILL.md` that tells Claude when and how
to use it, plus the scripts it runs. The scripts also work on their own from a
shell.

## plate-check

Checks whether Oregon custom (vanity) plate configurations are available, using
the Oregon DMV2U Custom Plate Search.

    plate-check/scripts/plate_check.py SAFARI 'SAF-ARI' SAFAR1

```
● 'QZ7XK9'   AVAILABLE
○ 'SAFARI'   TAKEN
× 'SAF!'     INVALID
? 'XYZ'      UNKNOWN

1 available · 1 taken · 1 invalid
```

- `-f FILE` reads one plate per line, `--json` prints machine-readable output,
  and `--delay N` sets the seconds between searches (default 2).
- It needs Python 3 and nothing else: it uses only the standard library and
  plain HTTPS, with no browser.
- Plates are checked against the DMV's character rules before anything is sent.
- "Available" means the DMV says the plate is available subject to final DMV
  approval. Nothing is reserved until you apply.

`plate-check/SKILL.md` describes how the script drives DMV2U's session protocol
and what to check if the site changes.

## Installing a skill

Symlink the skill's directory into your Claude Code skills folder:

    ln -s "$PWD/plate-check" ~/.claude/skills/plate-check

Claude Code then picks it up by its description, or you can run it with
`/plate-check`.
