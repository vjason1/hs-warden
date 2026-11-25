# Changelog

## 1.5.0 — 2026-11-24
- Fix: `getrichacl --quick` prints the ACL on one line with commas between entries; it was read as a single entry.
  Entries are now split on commas (one-per-line output is still read), and ACLs are written back in the same form.
- View: **e** explains every letter of each entry (rights, not granted, applies to, flags, ACL flags); **l** shows the
  full legend for the tool; **n** the native text.

## 1.4.0 — 2026-11-24
- tmux on the Anvil only. Each DSX job is one salt `cmd.run` call (job file and run in the same call; the result
  comes back in the salt output). Nothing runs in tmux on the DSX, and the DSX no longer needs tmux.
- Ctrl-C while waiting for a DSX change logs it as UNCONFIRMED so it can still be undone.
- View (menu 3) shows only the chosen target and whether its permissions are recursive (from 1.3.0).

## 1.3.0 — 2026-11-24
- DSX jobs: the tmux server is started in its own systemd scope (`systemd-run --scope`, as hs-cerberus does), or
  with salt `cmd.run_bg`. A tmux server started straight from salt `cmd.run` was killed before the job ran.
  WARDEN checks each job really started and switches method if not; read-only jobs that stop part-way are retried.
- View (menu 3) reads only the chosen target(s), never the tree below, and says whether the permissions are passed
  on: recursive / partly / not, entries to subfolders and files, inherit-only, one level, explicit vs inherited,
  and richacl automatic inheritance / protected.

## 1.2.2 — 2026-11-24
- DSX jobs run on WARDEN's own tmux server on the DSX (`tmux -L hs-warden -f /dev/null`), so an existing tmux
  server or `~/.tmux.conf` can't interfere. Attach to a running job with `tmux -L hs-warden attach -t warden-<id>`.
- The job log records when tmux started the runner and its exit code.
- When a job ends without a result, WARDEN shows diagnostics from the DSX: job log, job folder, tmux sessions and
  version, python3 and agent version, user, /tmp and /var/tmp.

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
