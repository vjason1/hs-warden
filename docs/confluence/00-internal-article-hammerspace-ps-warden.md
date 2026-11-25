# Hammerspace PS Warden (hs-warden) v1.4.0

**W.A.R.D.E.N. — Wide-spectrum Access Rights & Directory Enforcement Navigator**
File permission management, undo, and migration permission audit for Hammerspace engagements.

| | |
|---|---|
| Version | 1.4.0 (2026-11-24) |
| Download | hs-warden.py (attached to this page) |
| Script | hs-warden.py (single file) |
| Runs on | Hammerspace Anvil and DSX, Linux / macOS NFS clients, Windows |
| Requires | Python 3.6+ (standard library only; Anvil and DSX ship 3.6.8) |
| Owner | Hammerspace Solutions Engineering — Jason Ventresco |
| Sister tool | Hammerspace PS Cerberus (hs-cerberus) |

```
***********************************************************************************
*                    Copyright (C) 2016-2026 Hammerspace, Inc.                    *
*                                  _____________                                  *
*                                 /             \                                 *
*                                 \     _____    \                                *
*                                  \    \    \    \                               *
*                                   \    \    \    \                              *
*                             ___    \____\    \    \                             *
*                            /   \              \    \                            *
*                            \    \     _____    \___/                            *
*                             \    \    \    \                                    *
*                              \    \    \    \                                   *
*                               \    \____\    \                                  *
*                                \              \                                 *
*                                 \_____________/                                 *
*                    H A M M E R S P A C E   P S   W A R D E N                    *
*                                   W.A.R.D.E.N.                                  *
*                                      v1.4.0                                     *
***********************************************************************************
```

---

## Summary

hs-warden is a menu-driven script for viewing, changing, comparing and undoing file permissions in customer environments. It gives you one consistent workflow across four permission tools:

| Tool | Where it runs |
|---|---|
| Hammerspace getrichacl / setrichacl | DSX only: locally on a DSX, or from the active Anvil through salt |
| nfs4_getfacl / nfs4_setfacl | Linux NFSv4 clients |
| Windows icacls | Windows |
| chmod (mode bits) | Linux, macOS, Anvil, DSX |

Every change goes through the same cycle: **read → plan → preview → confirm → apply → log → undo**.

The main uses are:

1. **Changing permissions safely on a customer system.** You see exactly what will change before it changes, every change is logged, and any change can be undone.
2. **Checking a data migration.** Compare the permissions of a source tree with its migrated copy and get a report of every difference, even when the two sides are read with different tools.

---

## Why we built it

- Permission work on engagements was spread across four tools, each with its own syntax, letters and output.
- getrichacl / setrichacl must only run on DSX nodes, and long changes need to survive dropped SSH sessions.
- Permission changes on customer data need a record of what changed and a fast way back.
- After a migration, customers ask "did the move change any permissions?" and we needed a repeatable answer.

---

## What you get

**One view for every tool.** Permissions are always shown as the same table:

```
#   Principal                      Type   Access                        Applies to                         Inherited
+1  alice@ad.local [group]         allow  Modify (rwpxDaARWcS)          This folder, subfolders and files
 2  owner@                         allow  Full Control (rwpxDaARWcCoS)  This folder only                   yes
 3  domain users@ad.local [group]  allow  Read & Execute (rxaRcS)       This folder, subfolders and files  yes
    ACL flags: a
```

Access is shown as a standard level (Full Control, Modify, Read & Execute, Read, Write) with the native rights next to it. Hammerspace levels use the Windows-compatible labels from the getrichacl / setrichacl help.

**Same actions for every tool.** View, Grant or change, Remove, Edit the full native ACL.

**Preview before every change.** Before and after tables marked `+` added, `~` changed, `-` removed; how many objects will change; the exact native commands. Apply, view every diff, save as a script for approval, or cancel.

**Safe apply.** Each object is re-read just before it's written. Anything that changed after your preview is skipped and reported, never overwritten.

**Change log and undo.** Every change gets an id, a log entry (who, when, where, commands, results) and a snapshot of every object's ACL before and after. Undo restores the snapshot, warns you about anything changed again since, and is logged itself.

**Migration compare.** Source vs destination, matched by relative path, with a Markdown summary, a CSV of every difference and a JSON copy.

**Versioned.** Every log entry, snapshot, saved plan, compare report and DSX log line records the hs-warden version that wrote it.

---

## Hammerspace rules built in

| Rule | How hs-warden handles it |
|---|---|
| getrichacl / setrichacl only on a DSX | On a DSX it runs them locally. On the active Anvil you pick a DSX from salt (`pd-node-type` grain `dsx`) and it runs them there. Anywhere else the option is unavailable. |
| Session in tmux | On the Anvil (or a DSX when run there), hs-warden relaunches itself in tmux session `hs-warden`, so a dropped SSH session doesn't stop a change. From the Anvil, each DSX job is one salt `cmd.run` call; nothing runs in tmux on the DSX. |
| Survive dropped sessions | If SSH drops, the hs-warden session and its salt calls keep running in tmux on the Anvil. Reattach with `tmux attach -t hs-warden`. |
| Picking targets | Menu 2 lists the shares in `/mnt/smb-data-portal` on the DSX; pick one, then browse or type a path deeper inside it. Paths are shown with their Anvil (`/hs/...`) equivalent. |
| Same code on both ends | The Anvil copies itself to `/var/tmp/hs-warden/` on the DSX with salt-cp and checks it by SHA-256 each session. |
| Audit on the DSX | Each change made on a DSX is also logged in `/var/tmp/hs-warden/agent.log` there. |

Salt discovery and calls work the same way as in hs-cerberus.

---

## Quick start

1. Copy `hs-warden.py` to the Anvil (for example `/home/serviceadmin/`).
2. Run it as root:

```
python3 /home/serviceadmin/hs-warden.py
```

3. It opens in tmux with the Hammerspace banner and this menu:

```
  Setup
    1) Choose permission tool       (nfs4, icacls, chmod, Hammerspace richacl)
    2) Choose target path(s)        (and recursive)
  Permissions
    3) View permissions
    4) Grant or change access       (preview, apply, log)
    5) Remove access
    6) Edit the full ACL            (native text, SDDL or mode)
  Data migration
    7) Compare permissions          (source vs destination: did the migration change them?)
  History
    8) Change log
    9) Undo a change

    q) Quit
```

4. **1** → Hammerspace richacl [via salt] → pick the DSX.
5. **2** → pick the share from the list, then press Enter to use it, open sub-folders by number, or type a path inside it (e.g. `Lab/Smith`). Then choose whether to include everything below it.
6. **3** to see the target's permissions and whether they're passed on to subfolders and files, **4** to grant, **5** to remove. Read the preview, then **a** to apply.
7. Made a mistake? **9** → pick the change → confirm.

Type `b` at any prompt to go back. `python3 hs-warden.py -v` prints the version; `-h` prints help.

---

## Migration permission check (menu 7)

1. Choose the **source** tool and root, for example NFSv4 on `/mnt/oldfiler/projects` (mounted on the Anvil).
2. Choose the **destination** tool and root, for example Hammerspace richacl through salt on `/hs/projects`.
3. Set the options: recursive and depth; case-insensitive paths; ignore the inherited flag; ignore domain parts of names; name mappings such as `@old.local → @new.local`; compare owner/group by name or uid/gid.
4. Read the totals and the first differences on screen:

```
  Objects compared: 18234
    Identical                          18102
    Entries / rights differ               97
    Only the inherited flag differs       31
    Missing on destination                 4
```

```
  Lab/data  [different]
      ~ alice allow: Modify -> Read & Execute; rights lost: write_data,append_data,delete,...
      - missing on destination: domain users allow [Read & Execute] inherit=df
      owner alice:research -> root:root
```

5. Attach `summary.md` and `differences.csv` from `~/.hs-warden/reports/compare-<id>/` to the migration ticket.

When the two sides use different tools, rights are compared by meaning (read_data, write_acl, …), not by letters. Compare never changes anything.

**Suggested workflow:** a depth-2 compare before cutover to catch systematic problems (owner mapping, lost groups, broken inheritance); a full compare per share after cutover; fix individual differences with menu 4 or 5 so every fix is logged and undoable.

---

## Where things are saved

On the host where you ran hs-warden, in `~/.hs-warden` (change with `--log-dir`):

| Path | Contents |
|---|---|
| changes.log | Readable log of every change and compare run, with version |
| changes.jsonl | One JSON record per change |
| snapshots/ | Before/after ACL of every object each change touched — **needed for undo** |
| plans/ | Scripts saved from the preview |
| reports/ | Compare reports |

> **Important:** undo runs from the host that made the change, using its snapshots. Don't delete `~/.hs-warden` on the Anvil during an engagement. Include it in the engagement hand-off if the customer may need to reverse changes later.

---

## Before you use it on a customer system

- [ ] Running on the active Anvil (salt-master running) or a DSX, as root
- [ ] tmux on the Anvil; getrichacl, setrichacl and python3 on the DSX
- [ ] `salt '*' test.ping` answers from the DSX you'll use
- [ ] Try the change on one test folder first, then check it with menu 3
- [ ] For large recursive changes, save the plan (**s**) and get it approved first
- [ ] Note the change ids in your engagement notes

---

## Known limits

- Hammerspace: DACL only. The SACL (audit/alarm) isn't read or changed.
- One tool call per object. Tens of thousands of objects are fine; for millions, work per share or folder and raise `--max-items` (default 20,000).
- Setting an inheritable entry on a folder doesn't change what's already inside unless you turn on recursive (NFSv4 and Hammerspace). The preview reminds you.
- Hammerspace group names with spaces (e.g. `domain users@ad.local`) are written back as getrichacl prints them. Test on one folder on the customer's DSX version first.
- Full Control differs slightly between tools: the Hammerspace label leaves out delete_child, NFSv4 and Windows include it. Compare across tools reports this.
- icacls output and names depend on the Windows language; icacls can't remove inherited entries.

---

## Version history

| Version | Date | Changes |
|---|---|---|
| 1.4.0 | 2026-11-24 | tmux on the Anvil only: each DSX job is one salt cmd.run call; the DSX no longer needs tmux. |
| 1.3.0 | 2026-11-24 | DSX jobs start their tmux server in a systemd scope (or salt cmd.run_bg) so it survives the salt call. View shows only the chosen target and whether its permissions are passed on (recursive). |
| 1.2.2 | 2026-11-24 | DSX jobs use their own tmux server (`tmux -L hs-warden`); diagnostics from the DSX when a job fails. |
| 1.2.1 | 2026-11-24 | Fix: picking a DSX when there is more than one. |
| 1.2.0 | 2026-11-24 | Hammerspace targets: shares in /mnt/smb-data-portal are listed to pick from, with a folder browser or a typed path deeper inside the share (menu 2 and Compare). |
| 1.1.0 | 2026-11-24 | Hammerspace PS look and versioning as in hs-cerberus: logo banner, title boxes, `[INFO] [OK] [WARN] [ERR]`, grouped menu, `-v` / `-h`, Python version check, UTF-8 output under salt/tmux. Version recorded in every log, snapshot, plan, report and DSX log line. |
| 1.0.0 | 2026-11-24 | First release: four backends, standard table, grant / remove / edit with preview, change log, snapshots, undo, migration compare. |

---

## More documentation

Child pages:

- hs-warden: Overview and Quick Start
- hs-warden: Hammerspace Permissions (DSX, Anvil and salt)
- hs-warden: Migration Permission Check (Compare)
- hs-warden: Preview, Change Log and Undo
- hs-warden: Reference

`python3 hs-warden.py -h` prints the built-in help.

## Support and feedback

Questions, problems or ideas: contact Hammerspace Solutions Engineering. Include the hs-warden version (`-v`), the change id, and the relevant lines from `changes.log`.
