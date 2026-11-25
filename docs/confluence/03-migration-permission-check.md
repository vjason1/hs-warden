# hs-warden: Migration Permission Check (Compare)

Use menu **7 – Compare permissions: source vs destination** to check whether moving data changed its permissions. Compare only reads; it never changes anything.

## What it does

1. Reads the permissions of every file and folder in a **source** tree.
2. Reads the same for a **destination** tree.
3. Matches objects by path relative to each root (`Lab/data/run1.csv` on both sides).
4. Reports what differs, object by object, and writes a report.

Each side can use a different tool on a different host. For example:

| Source | Destination |
|---|---|
| NFSv4 on a Linux client with the old filer mounted | Hammerspace richacl through salt, on /hs/projects |
| Hammerspace richacl on /hs/projects (before) | Hammerspace richacl on /hs/projects-copy (after) |
| icacls on a Windows server | icacls on the Hammerspace SMB share |

> **Note:** both sides are read from wherever hs-warden is running. To compare an NFSv4 source with a Hammerspace destination, run hs-warden on the Anvil with the source mounted there and nfs4-acl-tools installed.

## Running a comparison

1. Start hs-warden and choose **7**.
2. **Source**: choose the tool, then the root path (for example `/mnt/oldfiler/projects`).
3. **Destination**: choose the tool, then the root path. For Hammerspace, pick the share from the list and browse to the folder (for example `projects`).
4. Answer the options:

| Question | Default | Choose yes when |
|---|---|---|
| Compare everything below the roots (recursive)? | yes | Almost always |
| Max depth below the root | no limit | A quick first pass on a large tree (try 2 or 3) |
| Match paths case-insensitively? | yes if icacls is used | One side is Windows |
| Ignore the 'inherited' flag? | no | The migration made inherited entries explicit and you only care about effective rights |
| Ignore domain parts of names? | yes for different tools | `alice@corp.local`, `CORP\alice` and `alice` are the same person |
| Add a name mapping? | no | The domain or naming changed, e.g. `@old.local` → `@new.local` (applied to source names) |
| Also compare POSIX owner / group? | yes (not with icacls) | You want uid/gid or owner names checked too; compare by name or by number |

## Reading the results

On screen you get the totals and the first 15 differences:

```
  COMPARE RESULT
  Source:       /mnt/oldfiler/projects  (NFSv4 on this host (anvil1))
  Destination:  /mnt/smb-data-portal/projects  (Hammerspace on DSX dsx1 (salt from anvil1))
  Objects compared: 18234
    Identical                          18102
    Entries / rights differ               97
    Only the inherited flag differs       31
    Missing on destination                 4
```

| Result | Meaning |
|---|---|
| Identical | Same entries in the same order |
| Entries / rights differ | Entries missing, extra, or with different rights or inheritance |
| Only the inherited flag differs | Same entries, but inherited on one side and explicit on the other |
| Same entries, different order | Can matter when deny entries are present |
| Only owner / group differs | The ACL matches; owner or group doesn't |
| Missing on destination | Exists on the source only: the migration may not have copied it |
| Only on destination | Exists on the destination only |
| Could not read | The tool returned an error for this object |

Each difference is listed line by line:

```
  Lab/data  [different]
      ~ alice allow: Modify -> Read & Execute; rights lost: write_data,append_data,delete,write_attributes,write_named_attrs
      - missing on destination: domain users allow [Read & Execute] inherit=df
      + extra on destination:   everyone@ allow [Read]
      owner alice:research -> root:root
```

- `~` the same principal has different rights or inheritance
- `-` an entry on the source is missing on the destination
- `+` an entry on the destination isn't on the source

## Comparing different tools

When the two sides use different tools, rights are compared by meaning (read_data, write_acl, …), not by letters. Some differences are expected:

- **Full Control**: the Hammerspace label doesn't include delete_child; NFSv4 and icacls Full Control do. Expect "rights gained / lost: delete_child" on Full Control entries.
- **chmod on one side**: only read, write and execute for owner@, group@ and everyone@ can be compared.
- **Windows names**: icacls shows `BUILTIN\Administrators`, `NT AUTHORITY\SYSTEM` and so on; use name mappings if the other side shows them differently.

## The report

Saved in `~/.hs-warden/reports/compare-<id>/`:

| File | Use |
|---|---|
| summary.md | Run details, options, totals, the first 500 differences. Paste it into a ticket or Confluence. |
| differences.csv | Every difference, with both sides' ACLs. Open in Excel and filter on status. |
| compare.json | Everything, for scripts. |

The run is also noted in `changes.log`.

## Large trees

- Each side reads at most 20,000 objects by default. Raise it with `--max-items`, for example `python3 hs-warden.py --max-items 200000`.
- If a side stops at the limit, the rest shows up as missing; hs-warden warns you.
- For very large shares, compare one subfolder at a time, or start with a depth limit.

## Suggested migration workflow

1. Before cutover, run Compare with a depth of 2 to catch systematic problems (wrong owner mapping, lost groups, broken inheritance).
2. Fix the mapping in the migration tool if needed and recopy.
3. After cutover, run a full Compare per share.
4. Attach summary.md and differences.csv to the migration ticket.
5. Fix individual differences with **4 – Grant** or **5 – Remove**; every fix is logged and can be undone.
