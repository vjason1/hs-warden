# hs-warden: Reference

Levels, rights mapping, tool support, options and troubleshooting.

## Standard access levels per tool

| Level | Hammerspace richacl | NFSv4 | icacls | chmod |
|---|---|---|---|---|
| Full Control | rwpxDaARWcCoS | rwaDdxtTnNcCoy | F | rwx |
| Modify | rwpxDaARWcS | rwadxtTnNcy | M | rwx |
| Read & Execute | rxaRcS | rxtncy | RX | r-x |
| Read | raRcS | rtncy | R | r-- |
| Write | wpAWS | waTNy | W | -w- |

The Hammerspace levels are the "Regular file ACL labels" from the getrichacl / setrichacl help. Custom rights can always be entered instead.

## Rights mapping

Used by Compare across tools and to name levels.

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

> **Note:** `d` and `D` mean opposite things in richacl and NFSv4.

## Inheritance ("Applies to")

| Applies to | richacl / NFSv4 flags | icacls |
|---|---|---|
| This folder only | (none) | (none) |
| This folder, subfolders and files | fd | (OI)(CI) |
| This folder and subfolders | d | (CI) |
| This folder and files | f | (OI) |
| Subfolders and files only | fdi | (OI)(CI)(IO) |
| Subfolders only | di | (CI)(IO) |
| Files only | fi | (OI)(IO) |
| …one level only | adds n | adds (NP) |

Inheritance flags are only set on directories. Files get the entry without them; "inherit only" entries are skipped on files.

## What each tool supports

| | richacl | NFSv4 | icacls | chmod |
|---|---|---|---|---|
| Named users / groups | yes | yes | yes | no |
| Deny entries | yes | yes | yes | no |
| Inheritance | yes | yes | yes | no |
| group@ | yes | yes | no | yes |
| owner@ / everyone@ | yes | yes | Owner Rights (S-1-3-4) / Everyone (S-1-1-0) | owner / other |
| How changes are written | whole ACL | whole ACL | /grant, /grant:r, /deny, /remove | chmod |
| How undo restores | whole ACL | whole ACL | SDDL via /restore | octal mode |
| Edit full ACL (menu 6) | richacl text | NFSv4 text | SDDL | octal or symbolic mode |

## Grant behaviour

- **Replace**: removes this principal's existing explicit entries of the same type (allow or deny) and puts the new entry where the first one was. icacls uses `/grant:r`.
- **Add**: merges the rights into a matching explicit entry with the same inheritance, or adds a new one. icacls uses `/grant`.
- New **deny** entries go first. New **allow** entries go before the first inherited entry.
- Inherited entries are never edited by Grant.

## Remove behaviour

Pick entry numbers from the table of the first target. Every entry with the same principal, type and inherited state is removed from each object in scope. For chmod, "remove" sets that class to `---`. icacls can't remove inherited entries.

## Recursive

With recursive on, each object below a target is read and changed on its own. Symbolic links below a target are skipped; a target that is itself a link is refused. icacls adds `/T /C`.

## Command-line options

```
python3 hs-warden.py [--log-dir DIR] [--max-items N] [--version]
```

| Option | Default | Meaning |
|---|---|---|
| --log-dir DIR | ~/.hs-warden | Logs, snapshots, saved scripts and reports |
| --max-items N | 20000 | Most objects read at once (per side in Compare). A change that would go past it is refused rather than half done. |
| --version | | Print the version |

| Environment variable | Meaning |
|---|---|
| HS_WARDEN_HOME | Log folder |
| EDITOR / VISUAL | Editor for menu 6 (default nano, vim or vi; notepad on Windows) |
| NO_COLOR | Turn off colours |

## Files

On the host running hs-warden (`~/.hs-warden`):

| Path | Contents |
|---|---|
| changes.log | Readable log of changes and compare runs |
| changes.jsonl | One JSON record per change |
| snapshots/\<id\>.json | Before/after ACL of every object a change touched |
| plans/\<id\>-\<kind\>.sh | Scripts saved from the preview |
| reports/compare-\<id\>/ | summary.md, differences.csv, compare.json |

On a DSX used through salt (`/var/tmp/hs-warden`):

| Path | Contents |
|---|---|
| hs-warden.py | Agent copy (checked by SHA-256, re-copied when it changes) |
| jobs/ | Job and result files while a job runs |
| agent.log | One JSON line per change made on this DSX |

## Known limits

- Hammerspace: DACL only; the SACL isn't read or changed.
- One tool call per object. Tens of thousands of objects are fine; for millions, work per share or folder.
- icacls names and output depend on the Windows language.
- Hammerspace group names with spaces are written back the way getrichacl prints them; test on one folder first.

## Troubleshooting

| Message | What to do |
|---|---|
| richacl unavailable: run WARDEN on a Hammerspace Anvil or DSX | Run it on the active Anvil or a DSX. |
| unavailable: needs tmux | Install tmux on the Anvil (or the DSX you run hs-warden on), or start hs-warden inside tmux. |
| nfs4_getfacl / nfs4_setfacl not installed | Install nfs4-acl-tools. |
| No DSX nodes answered salt | Run on the active Anvil (`systemctl status salt-master`); check `salt '*' test.ping`. |
| \<dsx\> is missing: getrichacl (or setrichacl, python3) | Install the missing tool on that DSX. |
| salt-cp did not deliver the agent | Check space and permissions in /var/tmp on the DSX. |
| skipped: changed since it was read | Another change happened after your preview. View it again and redo the change. |
| Stopped at N objects (--max-items N) | Narrow the target or raise --max-items. |
| The job … ended without a result | Diagnostics from the DSX are shown (salt output, job log, job folder, python3, agent version, user, /var/tmp). The job log is /var/tmp/hs-warden/jobs/\<id\>.result.log. |
| Change … was made from \<host\>; run the undo there | Undo on the host that made the change. |
| Operation to request attribute not supported (NFSv4) | The path isn't on an NFSv4 mount with ACL support. |
