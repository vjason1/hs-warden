# hs-warden

**W.A.R.D.E.N. — Wide-spectrum Access Rights & Directory Enforcement Navigator**

One menu-driven script for viewing, changing, comparing and undoing file permissions, whichever tool does the work underneath:

| Tool | Where it runs | WARDEN name |
|---|---|---|
| `nfs4_getfacl` / `nfs4_setfacl` | Linux NFSv4 clients | `nfs4` |
| Windows `icacls` | Windows | `icacls` |
| `chmod` (mode bits) | Linux, macOS, Anvil, DSX | `chmod` |
| Hammerspace `getrichacl` / `setrichacl` | **DSX only**: locally on a DSX, or from the active Anvil through salt | `richacl` |

Every tool shows permissions in the same table, takes the same Grant / Remove / Edit actions and goes through the same cycle:

```
read  ->  plan  ->  preview  ->  confirm  ->  apply  ->  log  ->  undo
```

It also has a separate **Compare** function that reads permissions from two copies of a tree (for example a migration source and its destination) and reports what changed.

- Single file, Python 3.6+ standard library only (Anvil / DSX ship Python 3.6.8)
- Every change is previewed, logged with before/after snapshots, and can be undone
- Hammerspace work always runs inside tmux

---

## Contents

- [Quick start](#quick-start)
- [Menu](#menu)
- [Hammerspace: DSX, Anvil, salt and tmux](#hammerspace-dsx-anvil-salt-and-tmux)
- [The standard view](#the-standard-view)
- [Preview, logging and undo](#preview-logging-and-undo)
- [Compare: migration permission check](#compare-migration-permission-check)
- [Rights mapping](#rights-mapping)
- [Files WARDEN writes](#files-warden-writes)
- [Command-line options](#command-line-options)
- [Limits and things to know](#limits-and-things-to-know)
- [Troubleshooting](#troubleshooting)

---

## Quick start

```bash
# Linux / macOS / Anvil / DSX
sudo python3 hs-warden.py

# Windows (elevated prompt for icacls on protected paths)
py hs-warden.py
```

1. **1 – Choose permission tool.** Only tools that work on this host are selectable; the others show why not.
2. **2 – Choose target path(s).** One or more paths, then whether to include everything below directories (recursive).
3. **3 – View**, **4 – Grant**, **5 – Remove** or **6 – Edit**.
4. Review the preview, then **a** (apply), **v** (view every native diff), **s** (save as a script without applying) or **c** (cancel).
5. Made a mistake? **9 – Undo a change**.

Type `b` at any prompt to go back.

## Menu

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

| Option | What it does |
|---|---|
| 3 View | Standard table for each target; with recursive, a count of objects below and how many distinct ACLs they have. Optional native text. |
| 4 Grant | Who → allow/deny → access level → applies to (inheritance) → replace or add. |
| 5 Remove | Pick entry numbers from the table; the same principal/type is removed from every object in scope. |
| 6 Edit | Opens the native ACL in `$EDITOR` (NFSv4 text, richacl text, SDDL for icacls, octal or symbolic mode for chmod). |
| 7 Compare | Read-only comparison of two trees; writes a report. |
| 8 Change log | Last 30 changes; pick one for details, commands and its snapshot file. |
| 9 Undo | Restore the "before" snapshot of a change. |

## Hammerspace: DSX, Anvil, salt and tmux

`getrichacl` and `setrichacl` must only run on a DSX node. WARDEN enforces that:

| WARDEN started on | How richacl work runs |
|---|---|
| A DSX (`pd-node-type` grain `dsx`) | Locally on that DSX. |
| The active Anvil (Salt master) | You pick a DSX from salt (`pd-node-type` grain `dsx`). WARDEN copies itself to the DSX with `salt-cp`, then starts each job in its **own detached tmux session on the DSX** and polls for the result. |
| Anywhere else | Not available (shown greyed out with the reason). |

**tmux.** On any Hammerspace node (Anvil or DSX), WARDEN relaunches itself inside a tmux session named `hs-warden` if it was started outside tmux. If that session already exists you can attach to it or start a new one. Detach with `Ctrl-b d`; reattach with `tmux attach -t hs-warden`. If tmux isn't installed, the Hammerspace option is turned off.

From the Anvil, each DSX job runs in a tmux session called `warden-<job id>` on the DSX. If you press Ctrl-C while waiting, WARDEN asks whether to keep waiting; the job keeps running on the DSX either way. A change you stop waiting for is logged as **UNCONFIRMED** with its before-snapshot, so it can still be undone.

**Paths.** On the Anvil a share is `/hs/<share>/...`; on a DSX the same share is `/mnt/smb-data-portal/<share>/...`. When working through salt you can type either; WARDEN shows the DSX path it will use.

**On the DSX**, WARDEN keeps its files in `/var/tmp/hs-warden/`:

| Path | Contents |
|---|---|
| `hs-warden.py` | Agent copy (re-copied when the Anvil's copy changes; checked by SHA-256) |
| `jobs/` | Job and result files while a job runs (removed when collected) |
| `agent.log` | One JSON line per change made on this DSX: change id, who, from which host, paths |

Salt discovery and calls follow the same pattern as `hs-cerberus.py`: `salt '*' grains.item pd-node-type`, `cmd.run` with `--out=json --static`, and `salt-cp`.

## The standard view

Every tool's permissions are shown in one table:

```
#   Principal                      Type   Access                        Applies to                         Inherited
+1  alice@ad.local [group]         allow  Modify (rwpxDaARWcS)          This folder, subfolders and files
 2  owner@                         allow  Full Control (rwpxDaARWcCoS)  This folder only                   yes
 3  domain users@ad.local [group]  allow  Read & Execute (rxaRcS)       This folder, subfolders and files  yes
    ACL flags: a
    + added   ~ changed   - removed
```

- **Principal**: `owner@`, `group@`, `everyone@`, or a named user / group.
- **Access**: a standard level name when the rights match one (Full Control, Modify, Read & Execute, Read, Write), followed by the native rights.
- **Applies to**: inheritance in Windows terms (`f` file_inherit = OI, `d` dir_inherit = CI, `i` inherit_only = IO, `n` no_propagate = NP).

### Standard levels per tool

| Level | richacl (Hammerspace labels) | NFSv4 | icacls | chmod |
|---|---|---|---|---|
| Full Control | `rwpxDaARWcCoS` | `rwaDdxtTnNcCoy` | `F` | `rwx` |
| Modify | `rwpxDaARWcS` | `rwadxtTnNcy` | `M` | `rwx` |
| Read & Execute | `rxaRcS` | `rxtncy` | `RX` | `r-x` |
| Read | `raRcS` | `rtncy` | `R` | `r--` |
| Write | `wpAWS` | `waTNy` | `W` | `-w-` |

The richacl levels are the "Regular file ACL labels" from the `getrichacl --help` / `setrichacl --help` text. Custom rights can always be entered instead.

### What each tool supports

| | richacl | NFSv4 | icacls | chmod |
|---|---|---|---|---|
| Named users / groups | yes | yes | yes | no |
| Deny entries | yes | yes | yes | no |
| Inheritance | yes | yes | yes | no |
| `group@` | yes | yes | no | yes |
| How changes are written | full ACL (`--set-file`) | full ACL (`-S file`) | `icacls /grant`, `/deny`, `/remove` | `chmod` |
| How undo restores | full ACL | full ACL | SDDL via `icacls /restore` | octal mode |

**How grants are placed.** "Replace" removes this principal's existing explicit entries of the same type and puts the new entry where the first one was. "Add" merges the rights into a matching entry. A new deny entry goes first; a new allow entry goes before the first inherited entry. Inheritance flags are only put on directories; files get the entry without them, and "inherit only" entries are skipped on files.

**Recursive.** With recursive on, each object below the target is read and changed on its own (its own ACL, edited the same way). For NFSv4 and richacl, setting an inheritable entry on a folder does **not** change existing contents; WARDEN says so in the preview and suggests recursive. With icacls, Windows passes inheritable entries on to existing children itself, and recursive adds `/T /C`.

## Preview, logging and undo

### Preview

Before anything changes you see, for the first targets: the before table, the after table with `+ ~ -` marks, how many objects will change (and how many already match), any notes, and the exact native commands. Then:

- **a** apply
- **v** view every change as a native diff
- **s** save the commands as a script in `plans/` without applying (bash, or `.cmd` on Windows; for a DSX, the header says which DSX to run it on)
- **c** cancel

### Safe apply

Each object's ACL is re-read just before it's written. If it changed since the preview, that object is **skipped** and reported, so you never overwrite a change you didn't see.

### Log

Every change gets an id (for example `20261124-191512-0fb8`) and is written to:

- `changes.jsonl`: one JSON record per change (time, user, host, tool, where it ran, summary, targets, recursive, object count, native commands, results).
- `changes.log`: the same in plain text, including commands.
- `snapshots/<id>.json`: for every object touched, the native ACL before and after and its status.

### Undo

**9 – Undo a change** lists recent changes, then:

1. Loads the snapshot and re-reads the current ACL of every object.
2. If an object changed again after that change, it says so and asks whether to overwrite it; the default is to leave it alone.
3. Shows the usual preview and asks before restoring.
4. Logs the undo as a change of its own, so an undo can be undone too.

Undo must run from the host that made the change. Changes made through salt are undone from the Anvil, through salt, on the same DSX.

## Compare: migration permission check

Menu **7** reads permissions from two copies of a tree and reports what differs. It is read-only.

1. **Source**: choose the tool and root path (for example NFSv4 on the old filer's mount, or richacl through salt on `/hs/projects`).
2. **Destination**: same, for the copy (for example richacl on `/hs/projects` after the migration).
3. **Options**:

| Option | Default | Use it when |
|---|---|---|
| Recursive / max depth | yes / no limit | Limit depth for a first pass on a big tree. |
| Match paths case-insensitively | on if icacls is involved | Windows-side copies. |
| Ignore the inherited flag | no | The migration turned inherited entries into explicit ones and you only care about effective rights. |
| Ignore domain parts of names | on for different tools | `alice@corp.local`, `CORP\alice` and `alice` should count as the same. |
| Name mapping | none | The domain or naming changed (for example `@old.local` → `@new.local`). Applied to source names. |
| Compare POSIX owner / group | yes (not with icacls) | By name or by uid/gid. |

**Matching.** Objects are matched by path relative to each root. Each object gets one result:

| Result | Meaning |
|---|---|
| Identical | Same entries in the same order |
| Entries / rights differ | Entries missing, extra, or with different rights or inheritance |
| Only the inherited flag differs | Same entries, but inherited on one side and explicit on the other |
| Same entries, different order | Can matter when deny entries are present |
| Only owner / group differs | ACL matches; uid/gid or names don't |
| Missing on destination / Only on destination | The file exists on one side only |
| Could not read | The tool returned an error for this object |

Each difference is spelled out, for example:

```
sub/b.txt  [different]
    ~ owner@ allow: rights gained: delete_child
    - missing on destination: alice allow [Modify] inherit=df
    + extra on destination:   bob deny [Write] inherit=df
    owner root:root -> daemon:daemon
```

**Different tools on each side.** Rights are compared by meaning (read_data, write_acl, …), not by letters. If one side is chmod, only read / write / execute for `owner@`, `group@` and `everyone@` can be compared.

**Report.** Written to `reports/compare-<id>/`:

- `summary.md`: run details, options, totals and the first 500 differences
- `differences.csv`: every difference with both ACLs (opens in Excel)
- `compare.json`: everything, for scripting

## Rights mapping

Used by Compare across tools, and to show level names.

| Right | richacl | NFSv4 | icacls | chmod |
|---|---|---|---|---|
| read_data / list_directory | r | r | RD | r |
| write_data / add_file | w | w | WD | w |
| append_data / add_subdirectory | p | a | AD | w |
| execute | x | x | X | x |
| delete_child | d | D | DC | |
| delete | D | d | DE | |
| read_attributes | a | t | RA | |
| write_attributes | A | T | WA | |
| read_named_attrs | R | n | REA | |
| write_named_attrs | W | N | WEA | |
| read_acl | c | c | RC | |
| write_acl | C | C | WDAC | |
| write_owner | o | o | WO | |
| synchronize | S | y | S | |
| write_retention | e | | | |
| write_retention_hold | E | | | |

Note that `d` and `D` are swapped between richacl and NFSv4.

## Files WARDEN writes

Default folder `~/.hs-warden` (change with `--log-dir` or `HS_WARDEN_HOME`):

```
~/.hs-warden/
  changes.jsonl          one JSON record per change
  changes.log            human-readable log (also lists compare runs)
  snapshots/<id>.json    before/after ACL of every object a change touched
  plans/<id>-<kind>.sh   scripts saved from the preview (s)
  reports/compare-<id>/  summary.md, differences.csv, compare.json
```

Keep this folder: undo needs the snapshots.

## Command-line options

```
python3 hs-warden.py [--log-dir DIR] [--max-items N] [--version]
```

| Option | Default | Meaning |
|---|---|---|
| `--log-dir DIR` | `~/.hs-warden` | Logs, snapshots, plans and reports |
| `--max-items N` | 20000 | Most objects read in one go (per side in Compare). If a change would go past it, WARDEN stops rather than change part of a tree. |
| `--version` | | Print the version |

Environment: `HS_WARDEN_HOME` (log folder), `EDITOR` / `VISUAL` (editor for menu 6), `NO_COLOR`.

## Limits and things to know

- **DACL only** for richacl; the SACL (audit / alarm) isn't read or changed.
- **Symbolic links** below a target are skipped; a target that is a link is refused (give the real path).
- **Scale.** Every object is read with one tool call, and remote results come back through salt. Tens of thousands of objects are fine; for millions, compare by share or depth, or raise `--max-items` and expect it to take a while.
- **icacls** names, inherited entries and output text depend on the Windows language. icacls can't remove inherited entries; WARDEN says so.
- **Group names with spaces in richacl** (`domain users@ad.local`) are written back the way `getrichacl` prints them (`group:domain users@ad.local`). Test this on your DSX version before a large change.
- **Full Control differs by tool.** The Hammerspace label leaves out `delete_child`; the NFSv4 level here includes it (`D`). Compare across tools will show that as "rights gained / lost: delete_child".

## Troubleshooting

| Message | What to do |
|---|---|
| `richacl … unavailable: run WARDEN on a Hammerspace Anvil or DSX` | Run it on the active Anvil or a DSX. |
| `… unavailable: needs tmux` | Install tmux on that node, or start WARDEN inside tmux. |
| `No DSX nodes answered salt` | Run on the active Anvil (`systemctl status salt-master`), and check `salt '*' test.ping`. |
| `dsx1 is missing: tmux` (or getrichacl …) | Install the missing tool on that DSX. |
| `salt-cp did not deliver the agent` | Check free space and permissions on `/var/tmp` on the DSX. |
| `skipped: changed since it was read` | Someone else changed that object after your preview. View it again and redo the change. |
| `Stopped at N objects (--max-items N)` | Narrow the target, or rerun with a larger `--max-items`. |
| `The job … ended without a result` | WARDEN shows the last lines of the job log from the DSX; the log is `/var/tmp/hs-warden/jobs/<id>.result.log`. |
| `Change … was made from <host>; run the undo there` | Undo on the host that made the change (its log folder has the snapshot). |

## Version

1.0.0 (2026-11-24): first release.
