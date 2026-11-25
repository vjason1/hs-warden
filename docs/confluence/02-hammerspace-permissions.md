# hs-warden: Hammerspace Permissions (DSX, Anvil and salt)

This article covers using hs-warden with the Hammerspace tools `getrichacl` and `setrichacl`.

## The rules hs-warden follows

1. **getrichacl / setrichacl run only on a DSX node.** A DSX is a node whose salt grain `pd-node-type` is `dsx`.
2. **The hs-warden session runs inside tmux** on the Anvil (or on the DSX when you run it there), so a dropped SSH session doesn't interrupt a change. Jobs sent to a DSX through salt don't use tmux on the DSX.
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
- hs-warden checks the DSX has `python3`, `getrichacl` and `setrichacl`, then copies itself to `/var/tmp/hs-warden/hs-warden.py` on the DSX with `salt-cp`. It only copies again when the Anvil's copy changes.

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

> **Note:** listing shares and folders is a plain directory listing through salt. getrichacl / setrichacl only ever run on the DSX.

## What happens on the DSX when you work from the Anvil

Each read or change is a **job**, run with one salt `cmd.run` call:

1. The job is written to `/var/tmp/hs-warden/jobs/<id>.json` on the DSX (by salt-cp for very large jobs).
2. The copy of hs-warden on the DSX runs it: getrichacl / setrichacl on each object.
3. The result comes back in the salt output, and the job files are removed.

Nothing runs in tmux on the DSX. hs-warden itself runs in tmux on the Anvil, so if your SSH session drops, the salt call keeps going; reattach with `tmux attach -t hs-warden`. salt waits up to 120 minutes for one job.

If you press **Ctrl-C** while waiting, hs-warden stops waiting but the job may still finish on the DSX. A change you stop waiting for is logged as **UNCONFIRMED** with its before-snapshot, so it can still be undone.

If a job ends without a result, hs-warden shows diagnostics from the DSX: the salt output, the job log, the job folder, python3 and agent versions, the user and /var/tmp.

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

## What the letters mean

In **3 – View permissions**, after the table:

| Key | Shows |
|---|---|
| e | Every entry of the target, letter by letter: the right's name and what it allows, the rights not granted, what the entry applies to, and the flags it uses |
| l | The full legend for the tool: all rights, the standard levels, entry flags and ACL flags |
| n | The native text, exactly as getrichacl prints it |

Example for `everyone@:rxdaRc:fd:allow`:

```
  2) everyone@:rxdaRc:fd:allow
        r     read_data / list_directory      read a file's contents / list a folder
        x     execute                         run a file / pass through (traverse) a folder
        d     delete_child                    delete files and folders inside this folder
        a     read_attributes                 read basic attributes (size, timestamps)
        R     read_named_attrs                read named / extended attributes
        c     read_acl                        read the permissions
        not granted: w p D A W C o S e E
              applies to                      This folder, subfolders and files
```

> **Note:** in the rights field `d` is delete_child and `D` is delete; in the flags field `d` is dir_inherit. NFSv4 swaps `d` and `D` in rights.

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
flags:a,alice@ad.local:rwpxDaARWcS:fdg:allow,owner@:rwpxDaARWcCoS:a:allow,group@:rwpxDaARWcS:a:allow,everyone@:raRcS:a:allow
EOF
```

The ACL is written in the same one-line, comma-separated form that `getrichacl --quick` prints (and that the setrichacl help uses: `flags:ap,everyone@:FullControl::allow`).

Just before writing, it reads the ACL again. If it changed since the preview, that object is skipped and reported.

> **Note:** names with spaces (such as `domain users@ad.local`) are written back the way getrichacl prints them. Test a change on one folder on your DSX version before a large recursive change.

## Saving instead of applying

At the preview, **s** saves the commands as a bash script in `~/.hs-warden/plans/` on the host you ran hs-warden on. For salt work the script header says which DSX to run it on, and the paths are DSX paths. Run it as root on that DSX (inside tmux for a long change).

## Requirements checklist

- [ ] Running on the active Anvil (salt-master running) or on a DSX
- [ ] tmux installed on the Anvil
- [ ] getrichacl and setrichacl on the DSX
- [ ] python3 on the DSX
- [ ] `salt '*' test.ping` answers from the DSX
- [ ] Write access to /var/tmp on the DSX
