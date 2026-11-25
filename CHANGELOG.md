# Changelog

## 1.2.1 — 2026-11-24
- Fix: with more than one DSX, picking a DSX passed the menu number to salt instead of the node name
  ("1 did not answer salt").

## 1.2.0 — 2026-11-24
- Hammerspace targets (menu 2, and Compare): the shares in `/mnt/smb-data-portal` on the DSX are listed to pick
  from, then a folder browser (number = open, `..` = up, Enter = use it) or a typed path deeper inside the share.
- Paths are shown with their Anvil (`/hs/...`) equivalent.
- Menu 2 says the tool must be chosen first when it isn't.

## 1.1.0 — 2026-11-24
- Hammerspace PS look and versioning, as in hs-cerberus: launch banner with the Hammerspace logo
  (short header on narrow terminals), title boxes, `[INFO] [OK] [WARN] [ERR]` messages, grouped main menu.
- `-v` / `--version` and `-h` / `--help`; Python version check; header comment block with project,
  version, authors and changelog.
- UTF-8 output under salt, tmux or a C/POSIX locale.
- The version is recorded in every change record, snapshot, saved plan, compare report and DSX agent log line.

## 1.0.0 — 2026-11-24
- First release.
- Backends: nfs4_getfacl/nfs4_setfacl, Windows icacls, chmod, Hammerspace getrichacl/setrichacl.
- Hammerspace tools run only on DSX nodes: locally on a DSX, or from the active Anvil through salt,
  with each DSX job in its own tmux session. WARDEN relaunches itself in tmux on any Hammerspace node.
- One standard table and the same Grant / Remove / Edit actions for every tool.
- Preview with before/after marks and native commands; save a plan as a script.
- Change log (text + JSON) with before/after snapshots; undo with drift check; undo is itself logged.
- Compare: source vs destination permission check for migrations, across tools, with CSV / Markdown / JSON reports.
