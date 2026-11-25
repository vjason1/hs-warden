# hs-warden: Hammerspace Permissions (DSX, Anvil, salt and tmux)

This article covers using hs-warden with the Hammerspace tools `getrichacl` and `setrichacl`.

## The rules hs-warden follows

1. **getrichacl / setrichacl run only on a DSX node.** A DSX is a node whose salt grain `pd-node-type` is `dsx`.
2. **Everything runs inside tmux** on Hammerspace nodes, so a dropped SSH session doesn't interrupt a change.
3. **Only the DACL is read and changed.** The SACL (audit/alarm) isn't touched.

## Two ways to run it

### Option A: on a DSX

```
ssh root@<dsx>
python3 /home/serviceadmin/hs-warden.py
```

- hs-warden detects the DSX and restarts itself in a tmux session named `hs-warden`.
- Choose **1 – Choose permission tool → Hammerspace richacl [this DSX]**.
- Menu 2 lists the shares in `/mnt/smb-data-portal` to pick from.

### Option B: on the active Anvil (recommended for most work)

```
ssh root@<anvil>
python3 /home/serviceadmin/hs-warden.py
```

- hs-warden detects the Anvil (Salt master running) and restarts itself in tmux.
- Choose **1 – Choose permission tool → Hammerspace richacl [via salt]**.
- Pick the DSX that will run the commands (listed from salt; picked for you if there is only one).
- hs-warden checks the DSX has `tmux`, `python3`, `getrichacl` and `setrichacl`, then copies itself to `/var/tmp/hs-warden/hs-warden.py` on the DSX with `salt-cp`. It only copies again when the Anvil's copy changes.

## Choosing the target (menu 2)

With the Hammerspace tool, menu 2 lists the shares in `/mnt/smb-data-portal` on the DSX. Pick a share, then browse into it or type a path deeper inside it:

```
  Target 1: which share? (/mnt/smb-data-portal on dsx1)
      1) archive                                  (Anvil: /hs/archive)
      2) home                                     (Anvil: /hs/home)
      3) projects                                 (Anvil: /hs/projects)
      p) Type a full path instead
  Choice: 3

  Folder: /mnt/smb-data-portal/projects   (Anvil: /hs/projects)
      1) Eng/
      2) Lab/
  Enter = use this folder   number = open that folder   .. = up   or type a path inside it
  Use: Lab/Smith
```

| Type | To |
|---|---|
| Enter | Use the folder shown |
| a number | Open that sub-folder |
| .. | Go up one level (not above the share) |
| a path inside the share | Go straight there, e.g. `Lab/Smith`; a file such as `Lab/Smith/data.csv` is used as the target directly |
| p (at the share list) | Type a full path instead |

Up to 60 sub-folders are listed; type a name to open one beyond that. Hidden folders such as `.snapshot` are left out. You can add more targets, then choose whether to include everything below them (recursive). Compare (menu 7) uses the same picker.

| On the Anvil | On a DSX |
|---|---|
| /hs/projects/Lab | /mnt/smb-data-portal/projects/Lab |

hs-warden works with the DSX path and shows the Anvil path next to it. A typed full path can use either form.

> **Note:** listing shares and folders is a plain directory listing through salt. getrichacl / setrichacl only ever run in tmux on the DSX.

## What happens on the DSX when you work from the Anvil

Each read or change is a **job**:

1. The job is written to `/var/tmp/hs-warden/jobs/<id>.json` on the DSX.
2. salt starts it in a **detached tmux session** on the DSX, named `warden-<id>`, on WARDEN's own tmux server (`tmux -L hs-warden ls` lists them; `tmux -L hs-warden attach -t warden-<id>` attaches).
3. The Anvil checks for the result every couple of seconds and shows a timer.
4. The result is collected and the job files are removed.

If you press **Ctrl-C** while waiting, hs-warden tells you the tmux session and result file on the DSX and asks whether to keep waiting. The job keeps running either way. If you stop waiting for a change, it is logged as **UNCONFIRMED** with its before-snapshot, so it can still be undone.

Each change made on a DSX is also recorded there, in `/var/tmp/hs-warden/agent.log` (change id, who, from which host, paths).

## Access levels for Hammerspace

These come from the Windows-compatible labels in the `getrichacl` / `setrichacl` help:

| Level | Rights |
|---|---|
| Full Control | rwpxDaARWcCoS |
| Modify | rwpxDaARWcS |
| Read & Execute | rxaRcS |
| Read | raRcS |
| Write | wpAWS |

You can also enter custom letters:

| Letter | Right | Letter | Right |
|---|---|---|---|
| r | read_data / list_directory | R | read_named_attrs |
| w | write_data / add_file | W | write_named_attrs |
| p | append_data / add_subdirectory | c | read_acl |
| x | execute | C | write_acl |
| d | delete_child | o | write_owner |
| D | delete | S | synchronize |
| a | read_attributes | e | write_retention |
| A | write_attributes | E | write_retention_hold |

## Inheritance and ACL flags

The "Applies to" choices map to richacl ACE flags:

| Applies to | Flags |
|---|---|
| This folder only | (none) |
| This folder, subfolders and files | fd |
| This folder and subfolders | d |
| This folder and files | f |
| Subfolders and files only | fdi |
| Subfolders only | di |
| Files only | fi |
| …one level only | adds n |

Other flags shown: `g` group, `a` inherited. The ACL's own flags (for example `flags:a`, auto_inherit) are shown under the table and kept as they are unless you edit them in **6 – Edit the full ACL**.

> **Note:** setting an inheritable entry on a folder doesn't change files and folders already inside it; only new ones inherit it. Turn on **recursive** (menu 2) to change existing contents too. The preview reminds you.

## How a change is written

hs-warden reads the ACL with `getrichacl --quick --dacl <path>`, makes your change in its own copy, and writes the whole ACL back:

```
setrichacl --dacl --set-file - /mnt/smb-data-portal/projects/Lab <<'EOF'
flags:a
alice@ad.local:rwpxDaARWcS:fdg:allow
owner@:rwpxDaARWcCoS:a:allow
group@:rwpxDaARWcS:a:allow
group:domain users@ad.local:rxaRcS:fda:allow
everyone@:raRcS:a:allow
EOF
```

Just before writing, it reads the ACL again. If it changed since the preview, that object is skipped and reported.

> **Note:** names with spaces (such as `domain users@ad.local`) are written back the way getrichacl prints them. Test a change on one folder on your DSX version before a large recursive change.

## Saving instead of applying

At the preview, **s** saves the commands as a bash script in `~/.hs-warden/plans/` on the host you ran hs-warden on. For salt work the script header says which DSX to run it on, and the paths are DSX paths. Run it inside tmux on that DSX.

## Requirements checklist

- [ ] Running on the active Anvil (salt-master running) or on a DSX
- [ ] tmux installed on the Anvil and on the DSX
- [ ] getrichacl and setrichacl on the DSX
- [ ] python3 on the DSX
- [ ] `salt '*' test.ping` answers from the DSX
- [ ] Write access to /var/tmp on the DSX
