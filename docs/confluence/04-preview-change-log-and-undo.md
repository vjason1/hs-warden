# hs-warden: Preview, Change Log and Undo

Every change hs-warden makes is previewed first, logged with a snapshot, and can be undone. This article explains how.

## 1. Preview

Before anything changes, hs-warden shows:

- **Before**: the current table for the first targets.
- **After**: the table as it will be, marked:
  - `+` added
  - `~` changed (same principal and type, different rights or inheritance)
  - `-` removed
- **Summary**: how many objects will change, and how many already match and will be left alone.
- **Notes**: for example, that existing folder contents won't inherit a new entry unless recursive is on.
- **Native commands**: the exact nfs4_setfacl, setrichacl, icacls or chmod commands.

Example:

```
  PROPOSED CHANGE: Set allow Modify (rwpxDaARWcS) alice@ad.local (This folder, subfolders and files) on 1 target(s), recursive
  Tool: Hammerspace richacl (getrichacl / setrichacl on a DSX)   Runs on: DSX dsx1 (salt from anvil1, tmux on the DSX)

  After:
    #   Principal                      Type   Access                        Applies to                         Inherited
    +1  alice@ad.local [group]         allow  Modify (rwpxDaARWcS)          This folder, subfolders and files
     2  owner@                         allow  Full Control (rwpxDaARWcCoS)  This folder only                   yes

  Summary
  412 of 412 object(s) will change; 0 already match.
```

Then you choose:

| Key | Action |
|---|---|
| a | Apply |
| v | View every change as a native diff |
| s | Save the commands as a script (in plans/) and don't apply |
| c | Cancel (the default) |

> **Note:** for icacls the After table is a projection; icacls makes the change, and Windows passes inheritable entries on to existing children itself.

## 2. Safe apply

For every object, hs-warden reads the ACL again just before writing. If it changed after the preview (someone else, or another process), that object is **skipped** and listed. Nothing you didn't see gets overwritten.

The result line shows: changed, failed, skipped. The new table is shown afterwards.

## 3. The change log

Each change gets an id such as `20261124-191512-0fb8`. It is written to the log folder (`~/.hs-warden` by default) on the host where hs-warden ran:

| File | Contents |
|---|---|
| changes.log | Readable: time, id, user@host, tool, where it ran, summary, counts, commands |
| changes.jsonl | The same, as JSON, one change per line |
| snapshots/\<id\>.json | Every object the change touched: native ACL before, after, and status |

Example `changes.log` entry:

```
2026-11-24T19:15:12  20261124-191512-0fb8  root@anvil1  richacl via salt:dsx1  grant: Set allow Modify (rwpxDaARWcS) alice@ad.local ... [ok 412, failed 0, skipped 0]
      $ setrichacl --dacl --set-file - /mnt/smb-data-portal/projects/Lab <<'EOF'
        ...
```

Menu **8 – Change log** lists the last 30 changes. Pick one to see its details, commands and snapshot file. Changes that were undone show **UNDONE by \<id\>**; changes whose result wasn't collected show **UNCONFIRMED**.

Changes made on a DSX through salt are also recorded on the DSX in `/var/tmp/hs-warden/agent.log`.

> **Important:** keep the log folder. Undo needs the snapshots.

## 4. Undo

Menu **9 – Undo a change**:

1. Pick a change from the list.
2. hs-warden loads its snapshot and reads every affected object's current ACL.
3. If any object was changed again after that change, hs-warden tells you and asks whether to overwrite it. The default is no: those objects are left as they are.
4. You get the usual preview (current → restored) and confirm.
5. The undo is logged as a change of its own (kind **undo**, with **undo_of** pointing to the original), so you can undo the undo.

How each tool restores:

| Tool | Restored with |
|---|---|
| Hammerspace richacl | setrichacl --dacl --set-file with the saved ACL |
| NFSv4 | nfs4_setfacl -S with the saved ACL |
| icacls | icacls \<parent\> /restore with the saved SDDL |
| chmod | chmod with the saved octal mode |

Rules:

- Undo runs from the **same host** that made the change (that's where the snapshot is).
- A change made through salt is undone from the Anvil, through salt, on the same DSX.
- An UNCONFIRMED change can be undone; hs-warden restores the before state of every object it was going to touch.

## 5. Saved scripts

Choosing **s** at the preview writes `plans/<id>-<kind>.sh` (or `.cmd` on Windows) with a header saying what it does, who made it, the tool, and for salt work which DSX to run it on. Use it to get a change approved first, or to run it in a maintenance window.

A script run by hand isn't logged by hs-warden and has no undo snapshot. To keep undo, apply through hs-warden.
