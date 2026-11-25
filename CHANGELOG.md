# Changelog

## 1.0.0 — 2026-11-24
- First release.
- Backends: nfs4_getfacl/nfs4_setfacl, Windows icacls, chmod, Hammerspace getrichacl/setrichacl.
- Hammerspace tools run only on DSX nodes: locally on a DSX, or from the active Anvil through salt,
  with each DSX job in its own tmux session. WARDEN relaunches itself in tmux on any Hammerspace node.
- One standard table and the same Grant / Remove / Edit actions for every tool.
- Preview with before/after marks and native commands; save a plan as a script.
- Change log (text + JSON) with before/after snapshots; undo with drift check; undo is itself logged.
- Compare: source vs destination permission check for migrations, across tools, with CSV / Markdown / JSON reports.
