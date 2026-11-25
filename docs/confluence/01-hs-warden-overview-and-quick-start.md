# hs-warden: Overview and Quick Start

**W.A.R.D.E.N. — Wide-spectrum Access Rights & Directory Enforcement Navigator** (current version: 1.1.0; run `python3 hs-warden.py -v`)

## What it is

hs-warden is a single Python script with one menu for viewing, changing, comparing and undoing file permissions. It works the same way whichever tool does the work underneath:

| Tool | Where it runs |
|---|---|
| nfs4_getfacl / nfs4_setfacl | Linux NFSv4 clients |
| Windows icacls | Windows |
| chmod (mode bits) | Linux, macOS, Anvil, DSX |
| Hammerspace getrichacl / setrichacl | DSX only: locally on a DSX, or from the active Anvil through salt |

Every change follows the same cycle: **read → plan → preview → confirm → apply → log → undo**.

## Why use it

- **One view for every tool.** Permissions are shown as principal, allow/deny, access level (Full Control, Modify, Read & Execute, Read, Write), what the entry applies to, and whether it's inherited.
- **Nothing changes without a preview.** You see the before and after, how many objects will change, and the exact native commands.
- **Every change is logged and can be undone.** A snapshot of each object's ACL is saved before the change.
- **Migration checks.** Compare permissions between a source tree and its migrated copy, even when they are read with different tools.
- **Hammerspace-safe.** Hammerspace tools only run on DSX nodes, always inside tmux.

## Requirements

- Python 3.6 or later (Anvil and DSX nodes ship Python 3.6.8). Standard library only.
- The tool you want to use, on the host that runs it.
- For Hammerspace: run on the active Anvil (Salt master) or on a DSX, with tmux installed.

## Getting it

Copy `hs-warden.py` to the host (for example `/home/serviceadmin/`).

## Starting it

Linux, macOS, Anvil or DSX:

```
sudo python3 hs-warden.py
```

Windows (elevated prompt for protected paths):

```
py hs-warden.py
```

On an Anvil or DSX, hs-warden restarts itself inside a tmux session named `hs-warden`. Detach with `Ctrl-b d`; reattach with `tmux attach -t hs-warden`.

## The menu

```
  1) Choose permission tool
  2) Choose target path(s) / recursive
  3) View permissions
  4) Grant or change access
  5) Remove access
  6) Edit the full ACL (native text)
  7) Compare permissions: source vs destination (migration check)
  8) Change log
  9) Undo a change
  q) Quit
```

Type `b` at any prompt to go back one step.

## Your first change, step by step

1. **1 – Choose permission tool.** Tools that don't work on this host are greyed out with the reason.
2. **2 – Choose target path(s).** Enter one or more paths, then an empty line. Answer whether to include everything below directories (recursive).
3. **3 – View permissions** to see the current table.
4. **4 – Grant or change access**, then answer:
   - Who: owner@, group@, everyone@, a named user or a named group
   - Allow or deny
   - Access level, or custom rights
   - Applies to (for directories): this folder only; this folder, subfolders and files; and so on
   - Replace this principal's existing entries, or add rights to them
5. Read the preview, then choose:
   - **a** apply
   - **v** view every change as a native diff
   - **s** save the commands as a script without applying
   - **c** cancel
6. hs-warden shows the result and the new table, and logs the change with an id.

To reverse it: **9 – Undo a change**, pick the change, review, confirm.

## Where things are saved

By default in `~/.hs-warden` on the host where you ran it:

| Path | Contents |
|---|---|
| changes.log | Readable log of every change and compare run |
| changes.jsonl | The same as JSON, one record per line |
| snapshots/ | Before/after ACLs for every change (needed for undo) |
| plans/ | Scripts saved from the preview |
| reports/ | Compare reports |

Use `--log-dir DIR` or the `HS_WARDEN_HOME` variable to keep them elsewhere.

## Related articles

- hs-warden: Hammerspace Permissions (DSX, Anvil, salt and tmux)
- hs-warden: Migration Permission Check (Compare)
- hs-warden: Preview, Change Log and Undo
- hs-warden: Reference (levels, rights mapping, options, troubleshooting)
