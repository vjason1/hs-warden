#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Hammerspace PS Warden
# W.A.R.D.E.N. — Wide-spectrum Access Rights & Directory Enforcement Navigator
# File Permission Management, Undo & Migration Permission Audit
# ==============================================================================
# Project:         Hammerspace PS Warden (github.com/vjason1/hs-warden)
# Script:          hs-warden.py
# Version:         1.1.0
# Updated:         2026-11-24
# Authors:         Jason Ventresco, Hammerspace Solutions Engineering
#                  (with Claude)
# Core Engines:    nfs4_getfacl / nfs4_setfacl, icacls, chmod,
#                  Hammerspace getrichacl / setrichacl (DSX, local or via salt)
# Target Runtime:  Python 3.6+ (python3 on Hammerspace Anvil & DSX nodes: 3.6.8),
#                  Linux / macOS NFS clients, Windows (icacls)
#
# Description:
#   One menu for viewing, changing, comparing and undoing file permissions,
#   whatever tool does the work underneath. Every backend is shown in the same
#   table (principal, type, access level, applies-to, inherited), takes the
#   same Grant / Remove / Edit operations, and goes through the same cycle:
#
#       read  ->  plan  ->  preview  ->  confirm  ->  apply  ->  log  ->  undo
#
# Usage:
#   sudo python3 hs-warden.py [OPTIONS]
#
# Options:
#   (none)                  Interactive menu
#   --log-dir DIR           Logs, snapshots, saved plans and reports
#                           (default ~/.hs-warden, or $HS_WARDEN_HOME)
#   --max-items N           Most objects read in one go (default 20000)
#   --agent ...             Node-side job runner, started on a DSX through
#                           salt in a detached tmux session (internal)
#   -v, --version           Print the version and exit
#   -h, --help              Show this help dialogue and exit
# ==============================================================================
#
#  WHAT THIS IS:
#    Menu  Function
#    ----  ---------------------------------------------------------------
#     1    Choose permission tool (nfs4, icacls, chmod, Hammerspace richacl)
#     2    Choose target path(s) / recursive
#     3    View permissions (standard table + native text)
#     4    Grant or change access
#     5    Remove access
#     6    Edit the full ACL (native text, SDDL or mode)
#     7    Compare permissions: source vs destination (migration check)
#     8    Change log
#     9    Undo a change
#
#  BACKENDS:
#    nfs4     nfs4_getfacl / nfs4_setfacl             Linux NFSv4 clients
#    icacls   Windows icacls                          Windows
#    chmod    POSIX mode bits (owner / group / other) Linux, macOS, Anvil, DSX
#    richacl  Hammerspace getrichacl / setrichacl     DSX only
#
#  HAMMERSPACE RULES:
#    - getrichacl / setrichacl run only on a DSX node (pd-node-type grain dsx):
#      locally when WARDEN runs on a DSX, or from the active Anvil (Salt
#      master) through salt against a DSX picked from the grain list.
#    - On any Hammerspace node (Anvil or DSX) WARDEN runs inside tmux: it
#      relaunches itself in tmux session 'hs-warden' if started outside one.
#    - From the Anvil, every DSX job runs in its own detached tmux session on
#      the DSX ('warden-<id>'), started through salt; WARDEN polls for the
#      result, so a dropped salt call or SSH session doesn't stop a change.
#    - Paths: /hs/<share>/... on the Anvil is /mnt/smb-data-portal/<share>/...
#      on the DSX. Either form is accepted; WARDEN translates.
#    - DACL only; the SACL is not read or changed.
#
#  LOGS & UNDO:
#    Every change is previewed (before / after, exact native commands), then
#    logged with a before/after snapshot of every object it touched. Undo
#    restores the "before" snapshot after checking nothing changed since; an
#    undo is itself logged, so it can be undone too. Each object is re-read just
#    before it's written and skipped if it changed after the preview.
#
#  REQUIREMENTS:
#    Python 3.6+, standard library only. The tool for the chosen backend on the
#    host that runs it. Hammerspace: the active Anvil (salt, salt-cp) or a DSX;
#    tmux on the Anvil and the DSX; getrichacl / setrichacl and python3 on the
#    DSX; write access to /var/tmp/hs-warden on the DSX.
#
#  CHANGELOG:
#    1.1.0 (2026-11-24)  Hammerspace PS look and versioning, as in hs-cerberus:
#                        launch banner with the Hammerspace logo, title boxes,
#                        [INFO]/[OK]/[WARN]/[ERR] tags, grouped main menu,
#                        -v/--version and -h/--help, Python version check,
#                        UTF-8 output under salt / tmux / C locale. The WARDEN
#                        version is recorded in every change record, snapshot,
#                        saved plan, compare report and DSX agent log line.
#    1.0.0 (2026-11-24)  First release: nfs4, icacls, chmod and Hammerspace
#                        richacl backends; standard table; grant / remove /
#                        edit with preview; change log, snapshots and undo;
#                        source vs destination compare for migrations.
# ==============================================================================

from __future__ import print_function

import argparse
import base64
import csv
import datetime
import difflib
import getpass
import hashlib
import io
import json
import os
import platform
import random
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time

TOOLKIT_VERSION = "1.1.0"
VERSION = TOOLKIT_VERSION
PROG = "hs-warden"
DISPLAY_NAME = "Hammerspace PS Warden"
TITLE = "W.A.R.D.E.N. — Wide-spectrum Access Rights & Directory Enforcement Navigator"
SELF_PATH = os.path.abspath(__file__)
IS_WIN = os.name == "nt"
HOST = socket.gethostname().split(".")[0]
PORTAL = "/mnt/smb-data-portal"          # share root on a DSX
ANVIL_SHARES = "/hs"                     # share root on the Anvil
REMOTE_DIR = "/var/tmp/hs-warden"        # agent copy, jobs and results on a DSX
REMOTE_AGENT = REMOTE_DIR + "/hs-warden.py"
TMUX_SESSION = "hs-warden"
DEFAULT_MAX_ITEMS = 20000
STANDARD_LEVELS = ["Full Control", "Modify", "Read & Execute", "Read", "Write"]

# ==============================================================================
#  COMMON: UTF-8 STREAMS
# ==============================================================================
# Python 3.6 uses the locale's encoding for stdout/stdin. Under salt, cron or a
# fresh tmux the locale is often C/POSIX (ASCII), and the box-drawing characters
# would raise UnicodeEncodeError. Force UTF-8 with replacement (as hs-cerberus).
def _utf8_streams():
    if IS_WIN:
        return
    for name in ("stdout", "stderr"):
        st = getattr(sys, name)
        enc = (getattr(st, "encoding", "") or "").lower().replace("-", "")
        if enc != "utf8" and hasattr(st, "buffer"):
            setattr(sys, name, io.TextIOWrapper(st.buffer, encoding="utf-8", errors="replace",
                                                line_buffering=True))
    st = sys.stdin
    enc = (getattr(st, "encoding", "") or "").lower().replace("-", "")
    if st is not None and enc != "utf8" and hasattr(st, "buffer"):
        sys.stdin = io.TextIOWrapper(st.buffer, encoding="utf-8", errors="replace")


_utf8_streams()


# ==============================================================================
#  OUTPUT
# ==============================================================================
class C(object):
    B = R = G = Y = CY = D = X = ""


def _init_colors():
    """Colours only on a terminal (salt cmd.run output would show raw codes)."""
    try:
        tty = sys.stdout.isatty()
    except Exception:
        tty = False
    if not tty or os.environ.get("NO_COLOR"):
        return
    if IS_WIN:
        try:
            os.system("")  # turns on VT processing in Windows 10+ consoles
        except Exception:
            return
    C.B, C.R, C.G, C.Y, C.CY, C.D, C.X = ("\033[1m", "\033[0;31m", "\033[0;32m", "\033[1;33m",
                                          "\033[0;36m", "\033[2m", "\033[0m")


def out(s=""):
    """print() that never fails on a closed pipe."""
    try:
        print(s)
    except BrokenPipeError:
        pass


def info(s):
    out("{}[INFO]{}  {}".format(C.CY, C.X, s))


def ok(s):
    out("{}[OK]{}    {}".format(C.G, C.X, s))


def warn(s):
    out("{}[WARN]{}  {}".format(C.Y, C.X, s))


def err(s):
    out("{}[ERR]{}   {}".format(C.R, C.X, s))


def dim(s):
    out("{}{}{}".format(C.D, s, C.X))


def head(s):
    """Section header, hs-cerberus style."""
    out("\n{}{}══ {} ══{}".format(C.B, C.CY, s, C.X))


def sub(s):
    out("")
    out("{}── {} {}{}".format(C.B, s, "─" * max(3, 74 - len(s)), C.X))


def box(title):
    """The double-line title box used at the top of each tool (hs-cerberus)."""
    w = 52
    out("{}{}".format(C.B, C.CY))
    out("  ╔" + "═" * w + "╗")
    out("  ║" + title.center(w) + "║")
    out("  ╚" + "═" * w + "╝")
    out(C.X)


def clear():
    try:
        if sys.stdout.isatty():
            if IS_WIN:
                os.system("cls")
            else:
                sys.stdout.write("\033[H\033[2J")
                sys.stdout.flush()
    except Exception:
        pass


# ==============================================================================
#  INPUT
# ==============================================================================
class Back(Exception):
    """User typed b / back."""


class Abort(Exception):
    """Stop the current menu action with a message."""


BACK_HINT = "b = back"


def read_line(prompt):
    try:
        return input(prompt)
    except EOFError:
        raise Back()


def ask(prompt, default=None, required=True):
    d = " [{}]".format(default) if default not in (None, "") else ""
    while True:
        s = read_line("  {}{}: ".format(prompt, d)).strip()
        if s.lower() in ("b", "back"):
            raise Back()
        if not s and default is not None:
            return str(default)
        if s or not required:
            return s
        out("  A value is needed ({}).".format(BACK_HINT))


def confirm(q, default=False):
    d = "Y/n" if default else "y/N"
    while True:
        s = read_line("  {} [{}]: ".format(q, d)).strip().lower()
        if s in ("b", "back"):
            raise Back()
        if not s:
            return default
        if s in ("y", "yes"):
            return True
        if s in ("n", "no"):
            return False


def choose(title, options, default=None, allow_back=True):
    """options: list of (key, label). Returns the chosen key."""
    if title:
        out("")
        out("  {}{}{}".format(C.B, title, C.X))
    for k, label in options:
        out("    {:>3}) {}".format(k, label))
    keys = [str(k).lower() for k, _ in options]
    while True:
        d = " [{}]".format(default) if default is not None else ""
        s = read_line("  Choice{}{}: ".format(d, " (" + BACK_HINT + ")" if allow_back else "")).strip().lower()
        if not s and default is not None:
            s = str(default).lower()
        if allow_back and s in ("b", "back"):
            raise Back()
        if s in keys:
            return options[keys.index(s)][0]
        out("  Pick one of: " + ", ".join(str(k) for k, _ in options))


def pause():
    try:
        input("\n  Press Enter to continue...")
    except EOFError:
        pass


# ==============================================================================
#  PROCESS HELPERS
# ==============================================================================
def have(cmd):
    return shutil.which(cmd) is not None


def run(cmd, input_text=None, timeout=None, encoding=None):
    """Run argv; returns (rc, stdout, stderr). Never raises for a missing tool."""
    enc = encoding or "utf-8"
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (OSError, ValueError) as e:
        return 127, "", "{}: {}".format(cmd[0], e)
    try:
        o, e = p.communicate(input_text.encode(enc) if input_text is not None else None, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        o, e = p.communicate()
        return 124, o.decode(enc, "replace"), "timed out after {}s".format(timeout)
    return p.returncode, o.decode(enc, "replace"), e.decode(enc, "replace")


def q(s):
    """Quote one argument for display / saved scripts."""
    if IS_WIN:
        return subprocess.list2cmdline([s])
    return shlex.quote(s)


def cmdline(argv):
    return " ".join(q(a) for a in argv)


def now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def new_id():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + "%04x" % random.getrandbits(16)


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def norm_text(raw):
    """Whitespace-insensitive form of a native ACL text, for comparisons."""
    return "\n".join(l.strip() for l in (raw or "").splitlines() if l.strip() and not l.strip().startswith("#"))


class AclError(Exception):
    pass


# ==============================================================================
#  CANONICAL RIGHTS (used for cross-tool comparison)
# ==============================================================================
CANON = ["read_data", "write_data", "append_data", "execute", "delete_child", "delete",
         "read_attributes", "write_attributes", "read_named_attrs", "write_named_attrs",
         "read_acl", "write_acl", "write_owner", "synchronize", "write_retention",
         "write_retention_hold"]

_IC_SPECIFIC = {"RD": "read_data", "WD": "write_data", "AD": "append_data", "X": "execute",
                "DC": "delete_child", "DE": "delete", "RA": "read_attributes",
                "WA": "write_attributes", "REA": "read_named_attrs", "WEA": "write_named_attrs",
                "RC": "read_acl", "WDAC": "write_acl", "WO": "write_owner", "S": "synchronize"}
_IC_R = {"read_data", "read_named_attrs", "read_attributes", "read_acl", "synchronize"}
_IC_W = {"write_data", "append_data", "write_named_attrs", "write_attributes", "synchronize"}
_IC_X = {"execute", "read_attributes", "read_acl", "synchronize"}
_IC_GENERIC = {"F": set(CANON[:14]), "GA": set(CANON[:14]), "R": _IC_R, "GR": _IC_R,
               "W": _IC_W, "GW": _IC_W, "GE": _IC_X, "RX": _IC_R | {"execute"},
               "M": _IC_R | _IC_W | {"execute", "delete"}, "D": {"delete"}, "N": set()}


# ==============================================================================
#  BACKENDS
# ==============================================================================
# Every backend reads a native "raw" form (what gets saved for undo and written
# back) and parses it into the shared entry model:
#   {"who": "owner@" | "group@" | "everyone@" | name, "group": bool,
#    "type": "allow"|"deny"|"audit"|"alarm", "perms": native rights string,
#    "inherit": subset of "fdin", "inherited": bool, "extra": other native flags,
#    "who_raw": native principal text (kept so it is written back unchanged)}
# Inherit letters, the same in NFSv4 and richacl: f file_inherit (OI),
# d dir_inherit (CI), i inherit_only (IO), n no_propagate (NP).
SPECIALS = ("owner@", "group@", "everyone@")


def mk_entry(who, type_="allow", perms="", inherit="", inherited=False, group=False, extra="", who_raw=None):
    return {"who": who, "type": type_, "perms": perms, "inherit": "".join(f for f in "fdin" if f in inherit),
            "inherited": bool(inherited), "group": bool(group), "extra": extra, "who_raw": who_raw}


def who_key(who):
    return (who or "").strip().lower()


class Backend(object):
    key = ""
    label = ""
    short = ""
    full_set = True            # False: changes are made with commands (icacls)
    supports_deny = True
    supports_named = True
    supports_inherit = True
    supports_group_special = True
    letters = ""               # allowed single-letter rights ("" = token based)
    levels = {}                # standard level name -> native rights
    native_hint = ""
    name_hint = "user name"

    def tools(self):
        return []

    # ---- rights handling -------------------------------------------------
    def perm_set(self, perms):
        return frozenset(c for c in (perms or "") if c != "-")

    def norm_perms(self, perms):
        s = self.perm_set(perms)
        return "".join(c for c in self.letters if c in s)

    def show_perms(self, perms):
        return self.norm_perms(perms) or "-"

    def merge_perms(self, a, b):
        return self.norm_perms("".join(self.perm_set(a) | self.perm_set(b)))

    def level_name(self, perms):
        s = self.perm_set(perms)
        for n in STANDARD_LEVELS:
            if n in self.levels and self.perm_set(self.levels[n]) == s:
                return n
        return None

    def access_text(self, perms):
        n = self.level_name(perms)
        shown = self.show_perms(perms)
        return "{} ({})".format(n, shown) if n else shown

    def validate_perms(self, text):
        t = text.strip().replace("-", "")
        bad = [c for c in t if c not in self.letters]
        if bad or not t:
            raise ValueError("Allowed letters: {}".format(self.letters))
        return self.norm_perms(t)

    def canon(self, perms):
        """Rights as a set of CANON names (cross-tool comparison)."""
        return frozenset()

    # ---- native I/O (run where the tool lives) ---------------------------
    def read_raw(self, path):
        raise NotImplementedError

    def read_display(self, path):
        return None

    def set_raw(self, path, raw):
        raise NotImplementedError

    def set_many(self, items):
        """items [{path, raw}] -> {path: error or None}"""
        res = {}
        for it in items:
            try:
                self.set_raw(it["path"], it["raw"])
                res[it["path"]] = None
            except AclError as e:
                res[it["path"]] = str(e)
        return res

    def set_display(self, path, raw):
        raise NotImplementedError

    # ---- parse / serialize ------------------------------------------------
    def parse(self, text, path=None):
        """-> (meta, entries)"""
        raise NotImplementedError

    def serialize(self, meta, entries):
        raise NotImplementedError

    def entry_native(self, e):
        return ""


# ---- NFSv4 -------------------------------------------------------------------
class Nfs4(Backend):
    key = "nfs4"
    label = "NFSv4 ACLs (nfs4_getfacl / nfs4_setfacl)"
    short = "NFSv4"
    letters = "rwaDdxtTnNcCoy"
    levels = {"Full Control": "rwaDdxtTnNcCoy", "Modify": "rwadxtTnNcy",
              "Read & Execute": "rxtncy", "Read": "rtncy", "Write": "waTNy"}
    name_hint = "user@domain (as nfs4_getfacl shows it)"
    native_hint = ("One ACE per line:  type:flags:principal:rights   e.g.  A:fd:alice@corp.local:rxtncy\n"
                   "  type A allow, D deny, U audit, L alarm;  flags f d n i g")
    TYPES = {"A": "allow", "D": "deny", "U": "audit", "L": "alarm"}
    _MAP = dict(zip("rwaxDdtTnNcCoy", ["read_data", "write_data", "append_data", "execute", "delete_child",
                                        "delete", "read_attributes", "write_attributes", "read_named_attrs",
                                        "write_named_attrs", "read_acl", "write_acl", "write_owner",
                                        "synchronize"]))

    def tools(self):
        return ["nfs4_getfacl", "nfs4_setfacl"]

    def canon(self, perms):
        return frozenset(self._MAP[c] for c in self.perm_set(perms) if c in self._MAP)

    def read_raw(self, path):
        rc, o, e = run(["nfs4_getfacl", path], timeout=60)
        if rc != 0:
            raise AclError((e or o).strip() or "nfs4_getfacl failed (rc {})".format(rc))
        return norm_text(o)

    def set_raw(self, path, raw):
        fd, tmp = tempfile.mkstemp(prefix="hs-warden-", suffix=".nfs4acl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(norm_text(raw) + "\n")
            rc, o, e = run(["nfs4_setfacl", "-S", tmp, path], timeout=120)
            if rc != 0:
                raise AclError((e or o).strip() or "nfs4_setfacl failed (rc {})".format(rc))
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def set_display(self, path, raw):
        return "nfs4_setfacl -s {} {}".format(q(",".join(norm_text(raw).splitlines())), q(path))

    def parse(self, text, path=None):
        ents = []
        for line in (text or "").splitlines():
            l = line.strip()
            if not l or l.startswith("#"):
                continue
            try:
                t, flags, rest = l.split(":", 2)
                who, perms = rest.rsplit(":", 1)
            except ValueError:
                raise AclError("Can't read NFSv4 ACE: " + l)
            if t not in self.TYPES:
                raise AclError("Unknown NFSv4 ACE type '{}': {}".format(t, l))
            wl = who.lower()
            special = wl in SPECIALS
            ents.append(mk_entry(wl if special else who, self.TYPES[t], perms,
                                 inherit="".join(c for c in flags if c in "fdin"),
                                 inherited=False, group="g" in flags and not special,
                                 extra="".join(c for c in flags if c not in "fding"),
                                 who_raw=who))
        return {}, ents

    def entry_native(self, e):
        t = dict((v, k) for k, v in self.TYPES.items())[e["type"]]
        flags = e["inherit"] + ("g" if e["group"] else "") + (e.get("extra") or "")
        who = e.get("who_raw") or (e["who"].upper() if e["who"] in SPECIALS else e["who"])
        return "{}:{}:{}:{}".format(t, flags, who, self.norm_perms(e["perms"]))

    def serialize(self, meta, entries):
        return "\n".join(self.entry_native(e) for e in entries)


# ---- Hammerspace richacl -----------------------------------------------------
class RichAcl(Backend):
    key = "richacl"
    label = "Hammerspace richacl (getrichacl / setrichacl on a DSX)"
    short = "Hammerspace"
    letters = "rwpxdDaARWcCoSeE"
    # From the getrichacl / setrichacl help: Windows-compatible labels.
    levels = {"Full Control": "rwpxDaARWcCoS", "Modify": "rwpxDaARWcS",
              "Read & Execute": "rxaRcS", "Read": "raRcS", "Write": "wpAWS"}
    name_hint = "user or group name, e.g. alice@ad.local or domain users@ad.local"
    native_hint = ("Optional first line  flags:<acl flags>  (a auto_inherit, p protected, d defaulted, m, w)\n"
                   "  then one ACE per line:  who:rights:flags:type   e.g.  everyone@:raRcS:fd:allow\n"
                   "  type allow / deny;  flags f d n i g a")
    _MAP = dict(zip("rwpxdDaARWcCoSeE", CANON))

    def tools(self):
        return ["getrichacl", "setrichacl"]

    def canon(self, perms):
        return frozenset(self._MAP[c] for c in self.perm_set(perms) if c in self._MAP)

    def read_raw(self, path):
        rc, o, e = run(["getrichacl", "--quick", "--dacl", path], timeout=60)
        if rc != 0:
            raise AclError((e or o).strip() or "getrichacl failed (rc {})".format(rc))
        return norm_text(o)

    def set_raw(self, path, raw):
        rc, o, e = run(["setrichacl", "--dacl", "--set-file", "-", path],
                       input_text=norm_text(raw) + "\n", timeout=120)
        if rc != 0:
            raise AclError((e or o).strip() or "setrichacl failed (rc {})".format(rc))

    def set_display(self, path, raw):
        return "setrichacl --dacl --set-file - {} <<'EOF'\n{}\nEOF".format(q(path), norm_text(raw))

    def parse(self, text, path=None):
        meta = {"flags": None}
        ents = []
        for line in (text or "").splitlines():
            l = line.strip()
            if not l or l.startswith("#"):
                continue
            if l.lower().startswith("flags:"):
                meta["flags"] = l.split(":", 1)[1].strip()
                continue
            parts = l.rsplit(":", 3)
            if len(parts) != 4:
                if l.endswith(":"):   # "file:" header (no --quick)
                    continue
                raise AclError("Can't read richacl ACE: " + l)
            who, mask, flags, typ = [p.strip() for p in parts]
            typ = typ.lower()
            if typ not in ("allow", "deny", "audit", "alarm"):
                raise AclError("Unknown richacl ACE type '{}': {}".format(typ, l))
            group = "g" in flags
            name = who
            m = re.match(r"^(user|group):(.*)$", who, re.I)
            if m:
                group = group or m.group(1).lower() == "group"
                name = m.group(2)
            wl = name.lower()
            special = wl in SPECIALS
            e = mk_entry(wl if special else name, typ, mask.replace("-", ""),
                         inherit="".join(c for c in flags if c in "fdin"),
                         inherited="a" in flags, group=group and not special,
                         extra="".join(c for c in flags if c not in "fdinga"), who_raw=who)
            e["gflag"] = "g" in flags
            ents.append(e)
        return meta, ents

    def entry_native(self, e):
        gflag = e.get("gflag", e["group"])
        flags = e["inherit"] + ("g" if gflag else "") + ("a" if e["inherited"] else "") + (e.get("extra") or "")
        who = e.get("who_raw") or e["who"]
        return "{}:{}:{}:{}".format(who, self.norm_perms(e["perms"]), flags, e["type"])

    def serialize(self, meta, entries):
        lines = []
        if meta.get("flags") is not None:
            lines.append("flags:" + meta["flags"])
        return "\n".join(lines + [self.entry_native(e) for e in entries])


# ---- chmod -------------------------------------------------------------------
class Chmod(Backend):
    key = "chmod"
    label = "POSIX mode bits (chmod)"
    short = "chmod"
    letters = "rwx"
    supports_deny = False
    supports_named = False
    supports_inherit = False
    levels = {"Full Control": "rwx", "Modify": "rwx", "Read & Execute": "rx", "Read": "r", "Write": "w"}
    native_hint = "Octal (e.g. 0750) or symbolic (e.g. u=rwx,g=rx,o=, g+s)"
    WHO = (("owner@", 6), ("group@", 3), ("everyone@", 0))

    def show_perms(self, perms):
        s = self.perm_set(perms)
        return "".join(c if c in s else "-" for c in "rwx")

    def canon(self, perms):
        s = self.perm_set(perms)
        r = set()
        if "r" in s:
            r.add("read_data")
        if "w" in s:
            r |= {"write_data", "append_data"}
        if "x" in s:
            r.add("execute")
        return frozenset(r)

    def read_raw(self, path):
        try:
            return "%04o" % stat.S_IMODE(os.lstat(path).st_mode)
        except OSError as e:
            raise AclError(str(e))

    def set_raw(self, path, raw):
        try:
            os.chmod(path, int(raw.strip(), 8))
        except (OSError, ValueError) as e:
            raise AclError(str(e))

    def set_display(self, path, raw):
        return "chmod {} {}".format(raw.strip(), q(path))

    def parse(self, text, path=None):
        mode = int((text or "0").strip(), 8)
        ents = []
        for who, sh in self.WHO:
            bits = (mode >> sh) & 7
            perms = ("r" if bits & 4 else "") + ("w" if bits & 2 else "") + ("x" if bits & 1 else "")
            ents.append(mk_entry(who, "allow", perms))
        return {"special": mode & 0o7000}, ents

    def serialize(self, meta, entries):
        mode = meta.get("special", 0)
        for who, sh in self.WHO:
            for e in entries:
                if e["who"] == who:
                    s = self.perm_set(e["perms"])
                    mode |= ((4 if "r" in s else 0) | (2 if "w" in s else 0) | (1 if "x" in s else 0)) << sh
        return "%04o" % mode

    def entry_native(self, e):
        return "{}={}".format({"owner@": "u", "group@": "g", "everyone@": "o"}[e["who"]], self.show_perms(e["perms"]))


def chmod_symbolic(mode, spec, is_dir):
    """Apply an octal or symbolic chmod spec to an int mode."""
    spec = spec.strip()
    if re.match(r"^[0-7]{1,4}$", spec):
        return int(spec, 8)
    for clause in spec.split(","):
        m = re.match(r"^([ugoa]*)([-+=])([rwxXst]*)$", clause.strip())
        if not m:
            raise ValueError("Can't read '{}'".format(clause))
        whos = "ugo" if (not m.group(1) or "a" in m.group(1)) else m.group(1)
        op, perms = m.group(2), m.group(3)
        bits = mask = 0
        for w in whos:
            sh = {"u": 6, "g": 3, "o": 0}[w]
            mask |= 7 << sh
            mask |= {"u": 0o4000, "g": 0o2000, "o": 0o1000}[w]
            for p in perms:
                if p == "r":
                    bits |= 4 << sh
                elif p == "w":
                    bits |= 2 << sh
                elif p == "x" or (p == "X" and (is_dir or mode & 0o111)):
                    bits |= 1 << sh
                elif p == "s" and w in "ug":
                    bits |= 0o4000 if w == "u" else 0o2000
                elif p == "t" and w == "o":
                    bits |= 0o1000
        if op == "+":
            mode |= bits
        elif op == "-":
            mode &= ~bits
        else:
            mode = (mode & ~mask) | bits
    return mode & 0o7777


# ---- Windows icacls ----------------------------------------------------------
class Icacls(Backend):
    key = "icacls"
    label = "Windows ACLs (icacls)"
    short = "icacls"
    full_set = False
    supports_group_special = False
    levels = {"Full Control": "F", "Modify": "M", "Read & Execute": "RX", "Read": "R", "Write": "W"}
    name_hint = r"DOMAIN\user, user@domain or *SID"
    native_hint = "SDDL string, e.g. D:PAI(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;WD)"
    SIMPLE = ("F", "M", "RX", "R", "W", "D", "N")
    TOKENS = SIMPLE + ("DE", "RC", "WDAC", "WO", "S", "AS", "MA", "GR", "GW", "GE", "GA", "RD", "WD",
                       "AD", "REA", "WEA", "X", "DC", "RA", "WA")
    SPECIAL_SID = {"owner@": "*S-1-3-4", "everyone@": "*S-1-1-0"}
    ENC = "oem" if IS_WIN else "utf-8"

    def tools(self):
        return ["icacls"]

    def perm_set(self, perms):
        return frozenset(t.strip().upper() for t in (perms or "").split(",") if t.strip())

    def norm_perms(self, perms):
        return ",".join(sorted(self.perm_set(perms), key=lambda t: self.TOKENS.index(t) if t in self.TOKENS else 99))

    def show_perms(self, perms):
        return self.norm_perms(perms) or "-"

    def validate_perms(self, text):
        toks = [t.strip().upper() for t in text.replace("(", "").replace(")", "").split(",") if t.strip()]
        bad = [t for t in toks if t not in self.TOKENS]
        if bad or not toks:
            raise ValueError("Use simple rights (F, M, RX, R, W) or a comma list of specific rights: "
                             + ", ".join(self.TOKENS[7:]))
        return self.norm_perms(",".join(toks))

    def canon(self, perms):
        r = set()
        for t in self.perm_set(perms):
            if t in _IC_GENERIC:
                r |= _IC_GENERIC[t]
            elif t in _IC_SPECIFIC:
                r.add(_IC_SPECIFIC[t])
            elif re.match(r"^0X[0-9A-F]+$", t):
                r.add("mask:" + t)
        return frozenset(r)

    # /save writes "name\r\nSDDL\r\n" pairs in UTF-16LE.
    @staticmethod
    def _read_save(fn):
        with open(fn, "rb") as f:
            data = f.read()
        text = data[2:].decode("utf-16-le", "replace") if data.startswith(b"\xff\xfe") else data.decode("utf-16-le", "replace")
        lines = [l for l in text.splitlines() if l.strip()]
        return [(lines[i], lines[i + 1].strip()) for i in range(0, len(lines) - 1, 2)]

    def save_tree(self, top, recursive):
        """[(path, sddl)] for top (and everything under it with recursive)."""
        fd, tmp = tempfile.mkstemp(prefix="hs-warden-", suffix=".acl")
        os.close(fd)
        try:
            argv = ["icacls", top, "/save", tmp, "/C", "/Q"]
            if recursive and os.path.isdir(top):
                argv.append("/T")
            rc, o, e = run(argv, timeout=3600, encoding=self.ENC)
            pairs = self._read_save(tmp) if os.path.getsize(tmp) else []
            if not pairs:
                raise AclError((e or o).strip() or "icacls /save failed (rc {})".format(rc))
            parent = os.path.dirname(top.rstrip("\\/")) or top
            return [(os.path.join(parent, n), s) for n, s in pairs]
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def read_raw(self, path):
        return self.save_tree(path, False)[0][1]

    def read_display(self, path):
        rc, o, e = run(["icacls", path], timeout=60, encoding=self.ENC)
        if rc != 0:
            raise AclError((e or o).strip() or "icacls failed (rc {})".format(rc))
        return o

    def set_many(self, items):
        res = {}
        groups = {}
        for it in items:
            p = it["path"].rstrip("\\/")
            parent = os.path.dirname(p)
            if not parent or parent == p:
                res[it["path"]] = "Can't restore a drive root with icacls /restore"
                continue
            groups.setdefault(parent, []).append((os.path.basename(p), it))
        for parent, lst in groups.items():
            fd, tmp = tempfile.mkstemp(prefix="hs-warden-", suffix=".acl")
            try:
                with os.fdopen(fd, "wb") as f:
                    for name, it in lst:
                        f.write((name + "\r\n" + it["raw"].strip() + "\r\n").encode("utf-16-le"))
                rc, o, e = run(["icacls", parent, "/restore", tmp, "/C", "/Q"], timeout=3600, encoding=self.ENC)
                for name, it in lst:
                    res[it["path"]] = None if rc == 0 else ((e or o).strip() or "icacls /restore rc {}".format(rc))
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return res

    def set_raw(self, path, raw):
        e = self.set_many([{"path": path, "raw": raw}])[path]
        if e:
            raise AclError(e)

    def set_display(self, path, raw):
        p = path.rstrip("\\/")
        return "REM restore SDDL on {}\nicacls {} /restore <file containing: {} / {}>".format(
            q(path), q(os.path.dirname(p)), os.path.basename(p), raw.strip())

    def parse(self, text, path=None):
        ents = []
        lines = (text or "").splitlines()
        for i, line in enumerate(lines):
            l = line.rstrip()
            if i == 0 and path and l.startswith(path):
                l = l[len(path):]
            l = l.strip()
            if not l or l.lower().startswith("successfully processed") or l.lower().startswith("failed processing"):
                continue
            m = re.match(r"^(.*?):((?:\([^)]*\))+)$", l)
            if not m:
                continue
            who = m.group(1).strip()
            toks = re.findall(r"\(([^)]*)\)", m.group(2))
            inherit = ""
            inherited = False
            typ = "allow"
            perms = []
            for t in toks:
                u = t.upper()
                if u == "OI":
                    inherit += "f"
                elif u == "CI":
                    inherit += "d"
                elif u == "IO":
                    inherit += "i"
                elif u == "NP":
                    inherit += "n"
                elif u == "I":
                    inherited = True
                elif u == "DENY":
                    typ = "deny"
                else:
                    perms.extend(x.strip() for x in t.split(","))
            wl = who.lower()
            canonical = {"everyone": "everyone@", "owner rights": "owner@"}.get(wl, who)
            ents.append(mk_entry(canonical, typ, ",".join(perms), inherit, inherited, who_raw=who))
        return {}, ents

    def entry_native(self, e):
        flags = "".join(t for f, t in (("f", "(OI)"), ("d", "(CI)"), ("i", "(IO)"), ("n", "(NP)")) if f in e["inherit"])
        return "{}:{}{}{}".format(e.get("who_raw") or e["who"], "(I)" if e["inherited"] else "", flags,
                                  "(DENY)" if e["type"] == "deny" else "") + "(" + self.norm_perms(e["perms"]) + ")"

    def serialize(self, meta, entries):
        return "\n".join(self.entry_native(e) for e in entries)

    def principal(self, who):
        if who in self.SPECIAL_SID:
            return self.SPECIAL_SID[who]
        return who

    def grant_cmd(self, path, is_dir, op, recursive):
        inherit = op["inherit"] if is_dir else ""
        flags = "".join(t for f, t in (("f", "(OI)"), ("d", "(CI)"), ("i", "(IO)"), ("n", "(NP)")) if f in inherit)
        perms = self.norm_perms(op["perms"])
        perm = perms if perms in self.SIMPLE else "(" + perms + ")"
        spec = "{}:{}{}".format(self.principal(op["who"]), flags, perm)
        if op["type"] == "deny":
            argv = ["icacls", path, "/deny", spec]
        else:
            argv = ["icacls", path, "/grant:r" if op["replace"] else "/grant", spec]
        if recursive and is_dir:
            argv += ["/T", "/C"]
        return argv

    def remove_cmd(self, path, is_dir, e, recursive):
        argv = ["icacls", path, "/remove:d" if e["type"] == "deny" else "/remove:g",
                e.get("who_raw") or self.principal(e["who"])]
        if recursive and is_dir:
            argv += ["/T", "/C"]
        return argv


BACKENDS = {"nfs4": Nfs4, "richacl": RichAcl, "chmod": Chmod, "icacls": Icacls}


# ==============================================================================
#  ENGINE (runs where the tools live: locally, or on a DSX as the agent)
# ==============================================================================
def owner_info(path):
    if IS_WIN:
        return None
    try:
        st = os.lstat(path)
    except OSError:
        return None
    d = {"uid": st.st_uid, "gid": st.st_gid}
    try:
        import pwd
        d["user"] = pwd.getpwuid(st.st_uid).pw_name
    except Exception:
        pass
    try:
        import grp
        d["groupname"] = grp.getgrgid(st.st_gid).gr_name
    except Exception:
        pass
    return d


def iter_tree(top, recursive, max_depth=None):
    """Yield (path, is_dir). Symbolic links below the top are skipped."""
    yield top, os.path.isdir(top)
    if not (recursive and os.path.isdir(top)):
        return
    base = top.rstrip("/\\").count(os.sep)
    for root, dirs, files in os.walk(top):
        dirs.sort(key=natural_key)
        if max_depth is not None and root.rstrip("/\\").count(os.sep) - base >= max_depth:
            dirs[:] = []
        keep = []
        for n in dirs:
            p = os.path.join(root, n)
            if os.path.islink(p):
                continue
            keep.append(n)
            yield p, True
        dirs[:] = keep
        for n in sorted(files, key=natural_key):
            p = os.path.join(root, n)
            if os.path.islink(p):
                continue
            yield p, False


def op_read(be, job):
    paths = job["paths"]
    recursive = job.get("recursive", False)
    limit = int(job.get("limit") or DEFAULT_MAX_ITEMS)
    want_owner = job.get("owner", False)
    items = []
    truncated = False
    for top in paths:
        if not os.path.lexists(top):
            items.append({"path": top, "top": True, "error": "No such file or directory"})
            continue
        if os.path.islink(top):
            items.append({"path": top, "top": True, "error": "Is a symbolic link; give the real path"})
            continue
        if be.key == "icacls":
            try:
                pairs = be.save_tree(top, recursive)
            except AclError as e:
                items.append({"path": top, "top": True, "error": str(e)})
                continue
            for p, sddl in pairs:
                if len(items) >= limit:
                    truncated = True
                    break
                items.append({"path": p, "top": os.path.normcase(p.rstrip("\\/")) == os.path.normcase(top.rstrip("\\/")),
                              "is_dir": os.path.isdir(p), "raw": sddl})
            display_all = job.get("display_all", False)
            for it in items:
                if (it.get("top") or display_all) and "raw" in it and "display" not in it:
                    try:
                        it["display"] = be.read_display(it["path"])
                    except AclError as e:
                        it["error"] = str(e)
        else:
            for p, is_dir in iter_tree(top, recursive, job.get("max_depth")):
                if len(items) >= limit:
                    truncated = True
                    break
                it = {"path": p, "is_dir": is_dir, "top": p == top}
                try:
                    it["raw"] = be.read_raw(p)
                except AclError as e:
                    it["error"] = str(e)
                if want_owner:
                    it["owner"] = owner_info(p)
                items.append(it)
        if truncated:
            break
    return {"items": items, "truncated": truncated, "host": HOST}


def op_set(be, job):
    results = []
    to_set = []
    for it in job["items"]:
        r = {"path": it["path"]}
        if it.get("expect") is not None:
            try:
                cur = be.read_raw(it["path"])
            except AclError as e:
                r.update(status="failed", error=str(e))
                results.append(r)
                continue
            if norm_text(cur) != norm_text(it["expect"]):
                r.update(status="skipped", error="changed since it was read", current=cur)
                results.append(r)
                continue
        to_set.append(it)
        results.append(r)
    errs = be.set_many(to_set) if to_set else {}
    for r in results:
        if "status" in r:
            continue
        e = errs.get(r["path"])
        r["status"] = "failed" if e else "ok"
        if e:
            r["error"] = e
        try:
            r["after"] = be.read_raw(r["path"])
        except AclError as x:
            r["after_error"] = str(x)
    return {"results": results, "host": HOST}


def op_cmds(be, job):
    bad = []
    for c in job.get("check", []):
        try:
            cur = be.read_raw(c["path"])
        except AclError as e:
            bad.append({"path": c["path"], "error": str(e)})
            continue
        if norm_text(cur) != norm_text(c["expect"]):
            bad.append({"path": c["path"], "error": "changed since it was read"})
    if bad:
        return {"check_failed": bad, "host": HOST}
    res = []
    for argv in job["cmds"]:
        rc, o, e = run(argv, timeout=7200, encoding=getattr(be, "ENC", None))
        res.append({"cmd": argv, "rc": rc, "out": (o + e).strip()[-4000:]})
    after = op_read(be, {"paths": job["after"]["paths"], "recursive": job["after"]["recursive"],
                         "limit": job["after"].get("limit")})
    return {"results": res, "after": dict((i["path"], i.get("raw")) for i in after["items"]), "host": HOST}


def op_probe(be, job):
    return {"tools": dict((t, have(t)) for t in be.tools()), "host": HOST,
            "python": platform.python_version()}


def dispatch(job):
    try:
        be = BACKENDS[job["backend"]]()
        fn = {"probe": op_probe, "read": op_read, "set": op_set, "cmds": op_cmds}[job["op"]]
        return fn(be, job)
    except Exception as e:  # report, don't crash the agent
        return {"error": "{}: {}".format(type(e).__name__, e)}


def agent_main(args):
    """Job runner on a DSX (started by WARDEN in a detached tmux session)."""
    with open(args.job_file) as f:
        job = json.load(f)
    res = dispatch(job)
    if job["op"] in ("set", "cmds"):
        try:
            with open(os.path.join(REMOTE_DIR, "agent.log"), "a") as lf:
                lf.write(json.dumps({"time": now_iso(), "warden_version": TOOLKIT_VERSION,
                                     "change": job.get("change_id"), "op": job["op"],
                                     "by": job.get("by"), "from": job.get("from"),
                                     "paths": [i["path"] for i in job.get("items", [])][:50] or job.get("cmds", [])[:20],
                                     "error": res.get("error")}) + "\n")
        except Exception:
            pass
    tmp = args.result_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(res, f)
    os.rename(tmp, args.result_file)
    return 0


# ==============================================================================
#  SALT (adapted from hs-cerberus.py: JSON output, pd-node-type grain)
# ==============================================================================
def salt_json(args, timeout=None):
    cmd = ["salt"]
    if timeout:
        cmd += ["-t", str(timeout)]
    cmd += list(args) + ["--out=json", "--static"]
    rc, o, e = run(cmd, timeout=(timeout + 60) if timeout else None)
    o = o.strip()
    if not o:
        return {}
    try:
        return json.loads(o)
    except ValueError:
        merged = {}
        for chunk in re.split(r"\n(?=\{)", o):
            try:
                merged.update(json.loads(chunk))
            except ValueError:
                pass
        return merged


def _salt_target(nodes):
    if nodes == "*" or nodes is None:
        return ["*"]
    if isinstance(nodes, str):
        nodes = [nodes]
    return ["-L", ",".join(nodes)]


def salt_cmd(nodes, command, timeout=None):
    d = salt_json(_salt_target(nodes) + ["cmd.run", command], timeout=timeout)
    return dict((k, v if isinstance(v, str) else json.dumps(v)) for k, v in d.items())


def salt_dsx_nodes():
    """[(node, num_cpus)] for nodes whose pd-node-type grain is dsx."""
    d = salt_json(["*", "grains.item", "pd-node-type", "num_cpus"], timeout=15)
    res = []
    for n in sorted(d, key=natural_key):
        g = d[n]
        if isinstance(g, dict) and str(g.get("pd-node-type", "")).lower() == "dsx":
            res.append(n)
    return res, d


def salt_cp(node, src, dst):
    rc, o, e = run(["salt-cp"] + _salt_target(node) + [src, dst], timeout=300)
    return rc == 0, o + e


def anvil_to_dsx(p):
    p = p.rstrip("/") or "/"
    if p == ANVIL_SHARES or p.startswith(ANVIL_SHARES + "/"):
        return PORTAL + p[len(ANVIL_SHARES):]
    return p


# ==============================================================================
#  EXECUTORS: where jobs run
# ==============================================================================
class ExecError(Exception):
    pass


class ExecAbandoned(Exception):
    """Stopped waiting for a remote job that may still finish."""


class LocalExec(object):
    def __init__(self):
        self.where = "local:" + HOST

    def describe(self):
        return "this host ({})".format(HOST)

    def run(self, job, what="Working"):
        res = dispatch(job)
        if "error" in res:
            raise ExecError(res["error"])
        return res

    def to_target(self, p):
        return os.path.abspath(os.path.expanduser(p))


class SaltExec(object):
    """Runs jobs on a DSX: salt starts the agent in a detached tmux session
    there; WARDEN polls for the result file."""

    def __init__(self, node):
        self.node = node
        self.where = "salt:" + node
        self.ready = False

    def describe(self):
        return "DSX {} (salt from {}, tmux on the DSX)".format(self.node, HOST)

    def to_target(self, p):
        return anvil_to_dsx(p)

    def _cmd(self, command, timeout=60):
        r = salt_cmd([self.node], command, timeout=timeout)
        if self.node not in r:
            raise ExecError("{} did not answer salt.".format(self.node))
        return r[self.node]

    def setup(self):
        if self.ready:
            return
        info("Checking {} (tmux, python3, getrichacl, setrichacl)...".format(self.node))
        o = self._cmd("mkdir -p {d}/jobs && for c in tmux python3 getrichacl setrichacl base64; do "
                      "command -v $c >/dev/null 2>&1 || echo MISSING:$c; done; echo WARDEN_OK".format(d=REMOTE_DIR))
        if "WARDEN_OK" not in o:
            raise ExecError("{} did not run the check: {}".format(self.node, o.strip()[:300]))
        miss = re.findall(r"MISSING:(\S+)", o)
        if miss:
            raise ExecError("{} is missing: {}".format(self.node, ", ".join(miss)))
        with open(SELF_PATH, "rb") as f:
            want = hashlib.sha256(f.read()).hexdigest()
        cur = self._cmd("sha256sum {} 2>/dev/null | cut -d' ' -f1".format(REMOTE_AGENT)).strip()
        if cur != want:
            info("Copying {} to {}:{} (salt-cp)...".format(PROG, self.node, REMOTE_AGENT))
            good, o = salt_cp(self.node, SELF_PATH, REMOTE_AGENT)
            cur = self._cmd("sha256sum {} 2>/dev/null | cut -d' ' -f1".format(REMOTE_AGENT)).strip()
            if cur != want:
                raise ExecError("salt-cp did not deliver the agent to {}: {}".format(self.node, o.strip()[:300]))
        ok("{} ready.".format(self.node))
        self.ready = True

    def run(self, job, what="Working"):
        self.setup()
        jid = new_id()
        sess = "warden-" + jid
        jf = "{}/jobs/{}.json".format(REMOTE_DIR, jid)
        rf = "{}/jobs/{}.result".format(REMOTE_DIR, jid)
        data = json.dumps(job)
        b64 = base64.b64encode(data.encode("utf-8")).decode("ascii")
        if len(b64) <= 60000:
            o = self._cmd("echo {} | base64 -d > {} && echo WARDEN_OK".format(b64, jf))
            if "WARDEN_OK" not in o:
                raise ExecError("Could not write the job file on {}: {}".format(self.node, o[:300]))
        else:
            fd, tmp = tempfile.mkstemp(prefix="hs-warden-job-", suffix=".json")
            with os.fdopen(fd, "w") as f:
                f.write(data)
            try:
                good, o = salt_cp(self.node, tmp, jf)
                if not good:
                    raise ExecError("salt-cp of the job file failed: " + o[:300])
            finally:
                os.unlink(tmp)
        inner = "python3 {} --agent --job-file {} --result-file {} > {}.log 2>&1".format(REMOTE_AGENT, jf, rf, rf)
        o = self._cmd("tmux new-session -d -s {} {} && echo WARDEN_STARTED".format(sess, q(inner)))
        if "WARDEN_STARTED" not in o:
            raise ExecError("Could not start the tmux job on {}: {}".format(self.node, o.strip()[:300]))
        poll = ("if [ -f {r} ]; then cat {r}; rm -f {r} {r}.log {j}; "
                "elif tmux has-session -t {s} 2>/dev/null; then echo WARDEN_PENDING; "
                "else echo WARDEN_GONE; tail -40 {r}.log 2>/dev/null; fi").format(r=rf, j=jf, s=sess)
        t0 = time.time()
        misses = 0
        while True:
            try:
                o = self._cmd(poll, timeout=120).strip()
            except ExecError:
                misses += 1
                if misses >= 5:
                    raise ExecError("{} stopped answering salt; the job may still be running in tmux session "
                                    "{} there (result file {}).".format(self.node, sess, rf))
                time.sleep(3)
                continue
            except KeyboardInterrupt:
                o = "WARDEN_PENDING"
                if self._stop_waiting(sess, rf):
                    raise ExecAbandoned("{} tmux session {} on {}".format(what, sess, self.node))
            if o.startswith("WARDEN_PENDING"):
                el = int(time.time() - t0)
                sys.stdout.write("\r  {}{} on {} ... {}s (Ctrl-C for options){}".format(C.D, what, self.node, el, C.X))
                sys.stdout.flush()
                try:
                    time.sleep(2)
                except KeyboardInterrupt:
                    if self._stop_waiting(sess, rf):
                        raise ExecAbandoned("{} tmux session {} on {}".format(what, sess, self.node))
                continue
            sys.stdout.write("\r" + " " * 78 + "\r")
            if o.startswith("WARDEN_GONE"):
                raise ExecError("The job on {} ended without a result:\n{}".format(self.node, o[11:].strip()))
            try:
                res = json.loads(o)
            except ValueError:
                raise ExecError("Unreadable result from {}: {}".format(self.node, o[:300]))
            if "error" in res:
                raise ExecError(res["error"])
            return res

    def _stop_waiting(self, sess, rf):
        out("")
        warn("The job keeps running on {} in tmux session {} (result: {}).".format(self.node, sess, rf))
        try:
            return not confirm("Keep waiting for it?", True)
        except Back:
            return True


# ==============================================================================
#  ENVIRONMENT: Hammerspace node detection and tmux
# ==============================================================================
class Ctx(object):
    node_type = None       # "dsx" | "anvil" | None
    in_tmux = False
    tmux_ok = False


def detect_node_type():
    if IS_WIN or sys.platform == "darwin":
        return None
    gtype = None
    try:
        with open("/etc/salt/grains") as f:
            m = re.search(r"^\s*pd-node-type\s*:\s*['\"]?([A-Za-z0-9_-]+)", f.read(), re.M)
            if m:
                gtype = m.group(1).lower()
    except (IOError, OSError):
        pass
    if gtype == "dsx":
        return "dsx"
    if have("salt") and have("systemctl") and run(["systemctl", "is-active", "--quiet", "salt-master"], timeout=10)[0] == 0:
        return "anvil"
    if gtype is None and os.path.isdir(PORTAL) and have("getrichacl"):
        return "dsx"
    return None


def ensure_tmux(ctx, argv):
    """On a Hammerspace node, run inside tmux (relaunch if needed)."""
    ctx.in_tmux = bool(os.environ.get("TMUX"))
    ctx.tmux_ok = ctx.in_tmux
    if not ctx.node_type or ctx.in_tmux:
        return
    if not sys.stdin.isatty():
        warn("Not in a terminal, so {} can't start tmux; Hammerspace options are off.".format(PROG))
        return
    if not have("tmux"):
        err("tmux is not installed on {}. Hammerspace (getrichacl / setrichacl) options need tmux "
            "and are turned off.".format(HOST))
        return
    name = TMUX_SESSION
    if run(["tmux", "has-session", "-t", name], timeout=10)[0] == 0:
        warn("A tmux session named '{}' already exists on {}.".format(name, HOST))
        c = choose("", [("a", "Attach to it"), ("n", "Start a new session"), ("q", "Quit")], "a", allow_back=False)
        if c == "q":
            sys.exit(0)
        if c == "a":
            os.execvp("tmux", ["tmux", "attach-session", "-t", name])
        name = "{}-{}".format(TMUX_SESSION, datetime.datetime.now().strftime("%H%M%S"))
    inner = "HS_WARDEN_TMUX=1 {} {}".format(" ".join(q(a) for a in [sys.executable, SELF_PATH] + argv), "")
    info("Hammerspace node ({}): starting {} in tmux session '{}'.".format(ctx.node_type.upper(), PROG, name))
    dim("  Detach with Ctrl-b d; reattach with: tmux attach -t {}".format(name))
    time.sleep(1)
    os.execvp("tmux", ["tmux", "new-session", "-s", name, inner])


# ==============================================================================
#  LOGS, SNAPSHOTS, REPORTS
# ==============================================================================
class Log(object):
    def __init__(self, base):
        self.base = base
        self.snap_dir = os.path.join(base, "snapshots")
        self.plan_dir = os.path.join(base, "plans")
        self.rep_dir = os.path.join(base, "reports")
        for d in (base, self.snap_dir, self.plan_dir, self.rep_dir):
            if not os.path.isdir(d):
                os.makedirs(d)
        self.jsonl = os.path.join(base, "changes.jsonl")
        self.text = os.path.join(base, "changes.log")

    def record(self, rec, snapshot=None):
        if snapshot is not None:
            fn = os.path.join(self.snap_dir, rec["id"] + ".json")
            with open(fn, "w") as f:
                json.dump(snapshot, f, indent=1)
            rec["snapshot"] = os.path.relpath(fn, self.base)
        with open(self.jsonl, "a") as f:
            f.write(json.dumps(rec) + "\n")
        with open(self.text, "a") as f:
            f.write("{time}  {id}  v{warden_version}  {user}@{host}  {backend} via {where}  {kind}: {summary}  "
                    "[ok {ok}, failed {failed}, skipped {skipped}]{undo}\n".format(
                        undo="  (undo of {})".format(rec["undo_of"]) if rec.get("undo_of") else "",
                        ok=rec["results"].get("ok", 0), failed=rec["results"].get("failed", 0),
                        skipped=rec["results"].get("skipped", 0), **rec))
            for c in rec.get("commands", [])[:20]:
                f.write("      $ " + c.replace("\n", "\n        ") + "\n")
        return rec

    def records(self):
        recs = []
        if os.path.isfile(self.jsonl):
            with open(self.jsonl) as f:
                for l in f:
                    try:
                        recs.append(json.loads(l))
                    except ValueError:
                        pass
        undone = dict((r["undo_of"], r["id"]) for r in recs if r.get("undo_of") and r["results"].get("ok"))
        for r in recs:
            r["undone_by"] = undone.get(r["id"])
        return recs

    def snapshot(self, rec):
        with open(os.path.join(self.base, rec["snapshot"])) as f:
            return json.load(f)


# ==============================================================================
#  SESSION STATE
# ==============================================================================
class S(object):
    ctx = None
    log = None
    be = None
    ex = None
    targets = []
    recursive = False
    max_items = DEFAULT_MAX_ITEMS
    salt_execs = {}


def backend_options(ctx):
    """[(key, label, available, reason, where)]"""
    res = []
    if IS_WIN:
        res.append(("icacls", Icacls.label, have("icacls"), "icacls not found", "local"))
    else:
        res.append(("icacls", Icacls.label, False, "Windows only", None))
    nf = have("nfs4_getfacl") and have("nfs4_setfacl")
    res.append(("nfs4", Nfs4.label, nf and not IS_WIN,
                "Windows" if IS_WIN else "nfs4_getfacl / nfs4_setfacl not installed (nfs4-acl-tools)", "local"))
    res.append(("chmod", Chmod.label, not IS_WIN, "not on Windows", "local"))
    if ctx.node_type == "dsx":
        okk = have("getrichacl") and have("setrichacl") and ctx.tmux_ok
        why = "needs tmux" if not ctx.tmux_ok else "getrichacl / setrichacl not found"
        res.append(("richacl", RichAcl.label + "  [this DSX]", okk, why, "local"))
    elif ctx.node_type == "anvil":
        res.append(("richacl", RichAcl.label + "  [via salt]", ctx.tmux_ok and have("salt-cp"),
                    "needs tmux" if not ctx.tmux_ok else "salt-cp not found", "salt"))
    else:
        res.append(("richacl", RichAcl.label, False, "run WARDEN on a Hammerspace Anvil or DSX", None))
    return res


def pick_dsx():
    info("Listing DSX nodes (salt grains pd-node-type)...")
    nodes, allg = salt_dsx_nodes()
    if not nodes:
        raise Abort("No DSX nodes answered salt (pd-node-type grain dsx). Run this on the active Anvil.")
    if len(nodes) == 1:
        ok("DSX node: " + nodes[0])
        return nodes[0]
    return choose("Run getrichacl / setrichacl on which DSX?", [(str(i + 1), n) for i, n in enumerate(nodes)], "1")


def select_backend(prompt="Which permission tool?", default_key=None):
    """-> (Backend, executor)"""
    opts = backend_options(S.ctx)
    menu = []
    for i, (k, label, avail, why, where) in enumerate(opts):
        menu.append((str(i + 1), label if avail else "{}{}  — unavailable: {}{}".format(C.D, label, why, C.X)))
    dflt = None
    for i, o in enumerate(opts):
        if o[2] and (o[0] == default_key or dflt is None):
            dflt = str(i + 1)
    while True:
        c = choose(prompt, menu, dflt)
        k, label, avail, why, where = opts[int(c) - 1]
        if not avail:
            err("{} is unavailable here: {}".format(label, why))
            continue
        be = BACKENDS[k]()
        if where == "salt":
            node = pick_dsx()
            ex = S.salt_execs.get(node) or SaltExec(node)
            S.salt_execs[node] = ex
            try:
                ex.setup()
            except ExecError as e:
                err(str(e))
                continue
        else:
            ex = LocalExec()
        return be, ex


def need_backend():
    if not S.be:
        S.be, S.ex = select_backend()


def need_targets():
    need_backend()
    if not S.targets:
        select_targets()
    if not S.targets:
        raise Abort("No target path set.")


def select_targets():
    need_backend()
    sub("Target paths")
    if isinstance(S.ex, SaltExec):
        dim("  Give /hs/<share>/... (Anvil view) or {}/<share>/... (DSX view).".format(PORTAL))
    dim("  One path per line; empty line when done.")
    paths = []
    while True:
        p = ask("Path {}".format(len(paths) + 1), required=not paths)
        if not p:
            break
        t = S.ex.to_target(p.strip().strip("'\""))
        if t != p.strip():
            dim("    -> {} on {}".format(t, S.ex.describe()))
        paths.append(t)
    S.targets = paths
    S.recursive = confirm("Include everything below directories (recursive)?", S.recursive)


# ==============================================================================
#  DISPLAY
# ==============================================================================
INHERIT_CHOICES = [("", "This folder only"),
                   ("fd", "This folder, subfolders and files"),
                   ("d", "This folder and subfolders"),
                   ("f", "This folder and files"),
                   ("fdi", "Subfolders and files only"),
                   ("di", "Subfolders only"),
                   ("fi", "Files only")]


def applies_text(inherit, is_dir):
    s = set(inherit or "")
    if not is_dir and not s:
        return "This file"
    base = s - {"n"}
    label = None
    for k, lbl in INHERIT_CHOICES:
        if set(k) == base:
            label = lbl
    label = label or "flags " + "".join(sorted(s))
    if "n" in s:
        label += " (one level)"
    return label


def entry_cells(be, e, is_dir):
    who = e["who"] + (" [group]" if e.get("group") else "")
    return [who, e["type"], be.access_text(e["perms"]),
            applies_text(e["inherit"], is_dir) if be.supports_inherit else "-",
            "yes" if e.get("inherited") else ""]


def entry_sig(e):
    return (who_key(e["who"]), e["type"], "".join(sorted(e["perms"] or "")), "".join(sorted(e["inherit"])),
            bool(e.get("inherited")), bool(e.get("group")), e.get("extra") or "")


def print_table(be, entries, is_dir, marks=None, removed=None, meta=None):
    hdr = ["#", "Principal", "Type", "Access", "Applies to", "Inherited"]
    rows = []
    for i, e in enumerate(entries):
        rows.append([(marks[i] if marks else "") + str(i + 1)] + entry_cells(be, e, is_dir))
    for e in removed or []:
        rows.append(["-"] + entry_cells(be, e, is_dir))
    if not rows:
        out("    (no entries)")
        return
    w = [max(len(str(r[c])) for r in rows + [hdr]) for c in range(len(hdr))]
    w[1] = min(w[1], 42)
    fmt = "    " + "  ".join("{:<%d}" % x for x in w)
    out(C.B + fmt.format(*hdr) + C.X)
    for r in rows:
        line = fmt.format(*[str(x)[:w[i]] if i == 1 and len(str(x)) > w[i] else x for i, x in enumerate(r)])
        if r[0].startswith("+"):
            line = C.G + line + C.X
        elif r[0].startswith("~"):
            line = C.Y + line + C.X
        elif r[0].startswith("-"):
            line = C.R + line + C.X
        out(line)
    if meta and meta.get("flags") is not None:
        dim("    ACL flags: {}".format(meta["flags"] or "(none)"))
    if meta and meta.get("special"):
        sp = meta["special"]
        dim("    Special bits: " + ", ".join(n for b, n in ((0o4000, "setuid"), (0o2000, "setgid"), (0o1000, "sticky")) if sp & b))


def parse_item(be, item):
    text = item.get("display") if be.key == "icacls" else item.get("raw")
    return be.parse(text, item["path"])


# ==============================================================================
#  READ / VIEW
# ==============================================================================
def read_state(paths=None, recursive=None, be=None, ex=None, owner=False, display_all=False, max_depth=None):
    be = be or S.be
    ex = ex or S.ex
    paths = paths or S.targets
    recursive = S.recursive if recursive is None else recursive
    info("Reading {} ACLs on {}{}...".format(be.short, ex.describe(), " (recursive)" if recursive else ""))
    res = ex.run({"op": "read", "backend": be.key, "paths": paths, "recursive": recursive,
                  "limit": S.max_items, "owner": owner, "display_all": display_all, "max_depth": max_depth},
                 what="Reading ACLs")
    items = res["items"]
    errs = [i for i in items if i.get("error")]
    if res.get("truncated"):
        warn("Stopped at {} objects (--max-items {}).".format(len(items), S.max_items))
    if errs:
        warn("{} object(s) could not be read:".format(len(errs)))
        for i in errs[:10]:
            out("      {}: {}".format(i["path"], i["error"]))
        if len(errs) > 10:
            out("      ... {} more".format(len(errs) - 10))
    return items, res.get("truncated", False)


def do_view():
    need_targets()
    items, trunc = read_state()
    tops = [i for i in items if i.get("top") and not i.get("error")]
    for it in tops:
        sub("{}  ({})".format(it["path"], "directory" if it["is_dir"] else "file"))
        meta, ents = parse_item(S.be, it)
        print_table(S.be, ents, it["is_dir"], meta=meta)
    if S.recursive and len(items) > len(tops):
        others = [i for i in items if not i.get("top") and not i.get("error")]
        groups = {}
        for i in others:
            groups.setdefault(norm_text(i.get("raw")), []).append(i)
        sub("Below the target(s): {} objects, {} distinct ACL(s)".format(len(others), len(groups)))
        for n, (raw, lst) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]))[:5]):
            out("    {} object(s), e.g. {}".format(len(lst), lst[0]["path"]))
        if len(groups) > 5:
            out("    ... {} more distinct ACLs".format(len(groups) - 5))
    if confirm("Show the native ({}) text as well?".format(S.be.short), False):
        for it in tops:
            sub("native: " + it["path"])
            out(it.get("display") or it.get("raw"))
            if S.be.key == "icacls":
                dim("SDDL: " + it.get("raw", ""))


# ==============================================================================
#  PLANNING
# ==============================================================================
def op_grant_entries(be, entries, op, is_dir):
    if not is_dir and "i" in op["inherit"]:
        return [dict(e) for e in entries]          # inherit-only means nothing on a file
    inherit = op["inherit"] if is_dir else ""
    new = [dict(e) for e in entries]
    key = who_key(op["who"])
    if be.key == "chmod":
        for e in new:
            if e["who"] == op["who"]:
                e["perms"] = op["perms"] if op["replace"] else be.merge_perms(e["perms"], op["perms"])
        return new

    def same(e):
        return (not e.get("inherited") and who_key(e["who"]) == key and e["type"] == op["type"]
                and bool(e.get("group")) == bool(op["group"]))
    idx = None
    if op["replace"]:
        keep = []
        for e in new:
            if same(e):
                if idx is None:
                    idx = len(keep)
                continue
            keep.append(e)
        new = keep
    else:
        for e in new:
            if same(e) and set(e["inherit"]) == set(inherit):
                e["perms"] = be.merge_perms(e["perms"], op["perms"])
                return new
    ent = mk_entry(op["who"], op["type"], be.norm_perms(op["perms"]), inherit, False, op["group"])
    if be.key == "richacl":
        ent["gflag"] = op["group"]
    if idx is None:
        if op["type"] == "deny":
            idx = 0
        else:
            idx = next((i for i, e in enumerate(new) if e.get("inherited")), len(new))
    new.insert(idx, ent)
    return new


def op_remove_entries(be, entries, keys, is_dir):
    def hit(e):
        return (who_key(e["who"]), e["type"], bool(e.get("group")), bool(e.get("inherited"))) in keys
    if be.key == "chmod":
        new = [dict(e) for e in entries]
        for e in new:
            if hit(e):
                e["perms"] = ""
        return new
    return [dict(e) for e in entries if not hit(e)]


def build_plan(kind, summary, items, fn):
    """Full-set backends: run fn(entries, is_dir, meta, item) on every item.
    fn returns new entries, or (meta, entries), or a raw string."""
    be = S.be
    plan = {"kind": kind, "summary": summary, "items": [], "cmds": [], "notes": []}
    for it in items:
        if it.get("error"):
            continue
        meta, ents = parse_item(be, it)
        r = fn(ents, it["is_dir"], meta, it)
        if isinstance(r, str):
            new_raw = r
            new_meta, new_ents = be.parse(new_raw, it["path"])
        else:
            new_meta, new_ents = r if isinstance(r, tuple) else (meta, r)
            same = [entry_sig(e) for e in new_ents] == [entry_sig(e) for e in ents] and new_meta == meta
            new_raw = it["raw"] if same else be.serialize(new_meta, new_ents)
        changed = norm_text(new_raw) != norm_text(it["raw"])
        plan["items"].append({"path": it["path"], "is_dir": it["is_dir"], "top": it.get("top"),
                              "before": it["raw"], "after": new_raw, "changed": changed,
                              "before_entries": ents, "after_entries": new_ents, "meta": new_meta,
                              "before_meta": meta})
    return plan


def diff_marks(before, after):
    """Marks for the 'after' table (+ added, ~ changed) and the removed entries."""
    bsig = [entry_sig(e) for e in before]
    asig = [entry_sig(e) for e in after]
    unmatched = [i for i, s in enumerate(bsig)]
    marks = [None] * len(asig)
    for j, s in enumerate(asig):          # exact matches first
        for i in unmatched:
            if bsig[i] == s:
                unmatched.remove(i)
                marks[j] = " "
                break
    for j, s in enumerate(asig):          # then same principal + type = changed
        if marks[j] is None:
            for i in unmatched:
                if bsig[i][:2] == s[:2]:
                    unmatched.remove(i)
                    marks[j] = "~"
                    break
            else:
                marks[j] = "+"
    return marks, [before[i] for i in unmatched]


def show_plan(plan):
    be = S.be
    head("PROPOSED CHANGE: " + plan["summary"])
    out("  Tool: {}   Runs on: {}".format(be.label, S.ex.describe()))
    changed = [i for i in plan["items"] if i["changed"]]
    tops = [i for i in plan["items"] if i.get("top")]
    for it in tops[:3]:
        sub("{}  ({})".format(it["path"], "directory" if it["is_dir"] else "file"))
        out("  Before:")
        print_table(be, it["before_entries"], it["is_dir"], meta=it.get("before_meta"))
        out("  After{}:".format(" (projected)" if not be.full_set else ""))
        marks, removed = diff_marks(it["before_entries"], it["after_entries"])
        print_table(be, it["after_entries"], it["is_dir"], marks, removed, meta=it.get("meta"))
        dim("    + added   ~ changed   - removed")
    if len(tops) > 3:
        out("  ... and {} more target(s)".format(len(tops) - 3))
    sub("Summary")
    if be.full_set:
        out("  {} of {} object(s) will change; {} already match.".format(len(changed), len(plan["items"]),
                                                                          len(plan["items"]) - len(changed)))
    else:
        out("  {} icacls command(s); {} object(s) snapshotted for undo.".format(len(plan["cmds"]), len(plan["items"])))
    for n in plan["notes"]:
        warn(n)
    sub("Native commands")
    cmds = plan_commands(plan)
    for c in cmds[:4]:
        out("  " + c.replace("\n", "\n  "))
    if len(cmds) > 4:
        dim("  ... {} more (v to view all, s to save as a script)".format(len(cmds) - 4))
    return changed


def plan_commands(plan):
    be = S.be
    if be.full_set:
        return [be.set_display(i["path"], i["after"]) for i in plan["items"] if i["changed"]]
    return [cmdline(c) for c in plan["cmds"]]


def save_script(plan, cmds):
    ext = ".cmd" if IS_WIN else ".sh"
    fn = os.path.join(S.log.plan_dir, "{}-{}{}".format(new_id(), plan["kind"], ext))
    c = "REM" if IS_WIN else "#"
    with open(fn, "w") as f:
        if not IS_WIN:
            f.write("#!/bin/bash\n")
        f.write("{c} {p} v{v} plan: {s}\n{c} Created {t} by {u}@{h}\n{c} Tool: {b}\n".format(
            c=c, p=DISPLAY_NAME, v=TOOLKIT_VERSION, s=plan["summary"], t=now_iso(), u=getpass.getuser(), h=HOST,
            b=S.be.label))
        if isinstance(S.ex, SaltExec):
            f.write("{c} Run on DSX {n} (inside tmux). Paths are DSX paths.\n".format(c=c, n=S.ex.node))
        f.write("\n" + "\n".join(cmds) + "\n")
    ok("Saved: " + fn)


def review_and_apply(plan):
    """Preview -> confirm -> apply -> log. Returns the log record or None."""
    changed = show_plan(plan)
    if S.be.full_set and not changed:
        ok("Nothing to change: the ACLs already match.")
        return None
    while True:
        c = choose("Apply this change?", [("a", "Apply"), ("v", "View every change (native diff)"),
                                          ("s", "Save as a script (don't apply)"), ("c", "Cancel")], "c")
        if c == "c":
            info("Cancelled; nothing changed.")
            return None
        if c == "s":
            save_script(plan, plan_commands(plan))
            continue
        if c == "v":
            for it in [i for i in plan["items"] if i["changed"]][:200] if S.be.full_set else []:
                sub(it["path"])
                for l in difflib.unified_diff(norm_text(it["before"]).splitlines(),
                                              norm_text(it["after"]).splitlines(), "before", "after", lineterm="", n=1):
                    out("  " + (C.G if l.startswith("+") else C.R if l.startswith("-") else "") + l + C.X)
            if not S.be.full_set:
                for x in plan_commands(plan):
                    out("  " + x)
            continue
        break
    return apply_plan(plan)


def apply_plan(plan, kind=None, undo_of=None):
    be, ex = S.be, S.ex
    cid = new_id()
    meta = {"change_id": cid, "by": "{}@{}".format(getpass.getuser(), HOST), "from": HOST,
            "warden_version": TOOLKIT_VERSION}
    snap_items = []
    tally = {"ok": 0, "failed": 0, "skipped": 0}
    unconfirmed = False
    try:
        if be.full_set or plan.get("force_set"):
            todo = [i for i in plan["items"] if i["changed"]]
            job = dict(meta, op="set", backend=be.key,
                       items=[{"path": i["path"], "raw": i["after"], "expect": i.get("expect", i["before"])} for i in todo])
            info("Applying to {} object(s)...".format(len(todo)))
            res = ex.run(job, what="Applying")
            by_path = dict((i["path"], i) for i in todo)
            for r in res["results"]:
                tally[r["status"]] += 1
                snap_items.append({"path": r["path"], "before": by_path[r["path"]]["before"],
                                   "after": r.get("after"), "status": r["status"], "error": r.get("error")})
        else:
            tops = [i for i in plan["items"] if i.get("top")]
            job = dict(meta, op="cmds", backend=be.key, cmds=plan["cmds"],
                       check=[{"path": i["path"], "expect": i["before"]} for i in tops],
                       after={"paths": [i["path"] for i in tops], "recursive": plan.get("recursive", False),
                              "limit": S.max_items})
            info("Running {} icacls command(s)...".format(len(plan["cmds"])))
            res = ex.run(job, what="Applying")
            if res.get("check_failed"):
                for b in res["check_failed"]:
                    err("{}: {}".format(b["path"], b["error"]))
                raise Abort("Nothing was changed: the ACL changed after the preview. Run the action again.")
            for r in res["results"]:
                (ok if r["rc"] == 0 else err)("{}  -> rc {}".format(cmdline(r["cmd"]), r["rc"]))
                if r["rc"] != 0 or ("failed processing" in r["out"].lower() and "0 files" not in r["out"].lower()):
                    out("      " + r["out"].replace("\n", "\n      ")[:2000])
            after = res["after"]
            for i in plan["items"]:
                a = after.get(i["path"])
                st = "ok" if a is not None and norm_text(a) != norm_text(i["before"]) else "unchanged"
                if st == "ok":
                    tally["ok"] += 1
                snap_items.append({"path": i["path"], "before": i["before"], "after": a, "status": st})
            tally["failed"] = sum(1 for r in res["results"] if r["rc"] != 0)
    except ExecAbandoned as e:
        unconfirmed = True
        warn("Not waiting any longer ({}). The change is logged as UNCONFIRMED so it can still be undone.".format(e))
        for i in plan["items"]:
            if i["changed"] or not be.full_set:
                snap_items.append({"path": i["path"], "before": i["before"], "after": None, "status": "unconfirmed"})
        tally["unconfirmed"] = len(snap_items)
    rec = {"id": cid, "time": now_iso(), "warden_version": TOOLKIT_VERSION, "user": getpass.getuser(),
           "host": HOST, "backend": be.key,
           "where": ex.where, "kind": kind or plan["kind"], "summary": plan["summary"],
           "targets": [i["path"] for i in plan["items"] if i.get("top")][:50],
           "recursive": plan.get("recursive", S.recursive), "objects": len(snap_items),
           "commands": plan_commands(plan)[:200], "results": tally}
    if undo_of:
        rec["undo_of"] = undo_of
    S.log.record(rec, {"id": cid, "warden_version": TOOLKIT_VERSION, "backend": be.key, "where": ex.where,
                       "items": snap_items})
    if not unconfirmed:
        (ok if not tally["failed"] else warn)("Done: {ok} changed, {failed} failed, {skipped} skipped "
                                              "(changed since the preview).".format(**tally))
        for s in [x for x in snap_items if x["status"] in ("failed", "skipped")][:10]:
            out("      {}: {}".format(s["path"], s.get("error")))
    info("Logged as change {}  ({}).".format(cid, S.log.text))
    return rec


def show_after(paths):
    try:
        items, _ = read_state(paths, recursive=False)
    except ExecError as e:
        warn("Could not re-read: {}".format(e))
        return
    for it in items:
        if it.get("error"):
            continue
        sub("Now: " + it["path"])
        meta, ents = parse_item(S.be, it)
        print_table(S.be, ents, it["is_dir"], meta=meta)


# ==============================================================================
#  ACTIONS: GRANT / REMOVE / EDIT
# ==============================================================================
def ask_principal(be):
    opts = [("1", "owner@     (file owner)"), ("2", "group@     (owning group)"), ("3", "everyone@  (everyone / other)")]
    if not be.supports_group_special:
        opts = [o for o in opts if o[0] != "2"]
    if be.supports_named:
        opts += [("4", "A named user"), ("5", "A named group")]
    c = choose("Who?", opts)
    if c in ("1", "2", "3"):
        return {"1": "owner@", "2": "group@", "3": "everyone@"}[c], False
    name = ask("{} name ({})".format("User" if c == "4" else "Group", be.name_hint))
    return name, c == "5"


def ask_access(be):
    opts = []
    for i, n in enumerate(STANDARD_LEVELS):
        if n in be.levels:
            opts.append((str(i + 1), "{:<15} {}{}{}".format(n, C.D, be.show_perms(be.levels[n]), C.X)))
    opts.append(("c", "Custom rights ({})".format("letters: " + be.letters if be.letters else "icacls rights")))
    c = choose("Access level?", opts)
    if c != "c":
        return be.levels[STANDARD_LEVELS[int(c) - 1]]
    while True:
        try:
            return be.validate_perms(ask("Rights"))
        except ValueError as e:
            err(str(e))


def ask_inherit(be, any_dir):
    if not be.supports_inherit or not any_dir:
        return ""
    c = choose("Applies to (directories; files get no inheritance flags)?",
               [(str(i + 1), l) for i, (k, l) in enumerate(INHERIT_CHOICES)], "2")
    inh = INHERIT_CHOICES[int(c) - 1][0]
    if inh and confirm("Only the immediate contents (no_propagate)?", False):
        inh += "n"
    return inh


def do_grant():
    need_targets()
    be = S.be
    items, trunc = read_state()
    if trunc:
        raise Abort("Too many objects; raise --max-items or narrow the target.")
    good = [i for i in items if not i.get("error")]
    if not good:
        raise Abort("Nothing readable to change.")
    for it in [i for i in good if i.get("top")][:2]:
        sub("Current: " + it["path"])
        meta, ents = parse_item(be, it)
        print_table(be, ents, it["is_dir"], meta=meta)
    who, group = ask_principal(be)
    typ = "allow"
    if be.supports_deny:
        typ = choose("Allow or deny?", [("1", "Allow"), ("2", "Deny")], "1")
        typ = "allow" if typ == "1" else "deny"
    perms = ask_access(be)
    inherit = ask_inherit(be, any(i["is_dir"] for i in good))
    replace = True
    if be.key != "chmod":
        replace = choose("If {} already has {} entries:".format(who, typ),
                         [("1", "Replace them with this one"), ("2", "Add these rights to them")], "1") == "1"
    op = {"who": who, "group": group, "type": typ, "perms": perms, "inherit": inherit, "replace": replace}
    summary = "{} {} {} {}{}{}".format("Set" if replace else "Add", typ, be.access_text(perms), who,
                                       " ({})".format(applies_text(inherit, True)) if inherit else "",
                                       " on {} target(s){}".format(len(S.targets), ", recursive" if S.recursive else ""))
    if be.full_set:
        plan = build_plan("grant", summary, good, lambda ents, is_dir, meta, it: op_grant_entries(be, ents, op, is_dir))
        if inherit and any(i["is_dir"] for i in good) and not S.recursive:
            plan["notes"].append("Existing files and folders inside won't change; only new ones inherit this. "
                                 "Turn on recursive to change existing contents too.")
    else:
        plan = icacls_plan("grant", summary, good, lambda it: [be.grant_cmd(it["path"], it["is_dir"], op, S.recursive)],
                           lambda ents, is_dir: op_grant_entries(be, ents, op, is_dir))
    rec = review_and_apply(plan)
    if rec:
        show_after(S.targets[:2])


def icacls_plan(kind, summary, items, cmd_fn, proj_fn):
    be = S.be
    plan = {"kind": kind, "summary": summary, "items": [], "cmds": [], "notes": [], "recursive": S.recursive}
    for it in items:
        e = {"path": it["path"], "is_dir": it["is_dir"], "top": it.get("top"), "before": it["raw"],
             "after": None, "changed": True}
        if it.get("top"):
            meta, ents = parse_item(be, it)
            e["before_entries"] = ents
            e["after_entries"] = proj_fn(ents, it["is_dir"])
            plan["cmds"].extend(cmd_fn(it))
        plan["items"].append(e)
    plan["notes"].append("icacls makes the change; the 'After' table is a projection. "
                         "Windows passes inheritable entries on to existing children automatically.")
    return plan


def do_remove():
    need_targets()
    be = S.be
    items, trunc = read_state()
    if trunc:
        raise Abort("Too many objects; raise --max-items or narrow the target.")
    good = [i for i in items if not i.get("error")]
    tops = [i for i in good if i.get("top")]
    if not tops:
        raise Abort("Nothing readable to change.")
    top = tops[0]
    meta, ents = parse_item(be, top)
    sub("Entries on " + top["path"])
    print_table(be, ents, top["is_dir"], meta=meta)
    if be.key == "chmod":
        dim("  chmod: removing an entry sets its rights to ---.")
    s = ask("Entry number(s) to remove, e.g. 2 or 2,4")
    try:
        picks = [ents[int(x) - 1] for x in re.split(r"[,\s]+", s) if x]
    except (ValueError, IndexError):
        raise Abort("No such entry number.")
    keys = set((who_key(e["who"]), e["type"], bool(e.get("group")), bool(e.get("inherited"))) for e in picks)
    if any(e.get("inherited") for e in picks):
        warn("Inherited entries come back if the parent still passes them on" +
             ("; icacls can't remove inherited entries at all." if be.key == "icacls" else "."))
    summary = "Remove {} on {} target(s){}".format(", ".join("{} {}".format(e["type"], e["who"]) for e in picks),
                                                   len(S.targets), ", recursive" if S.recursive else "")
    if be.full_set:
        plan = build_plan("remove", summary, good, lambda e2, is_dir, m, it: op_remove_entries(be, e2, keys, is_dir))
    else:
        def cmds(it):
            return [be.remove_cmd(it["path"], it["is_dir"], e, S.recursive) for e in picks if not e.get("inherited")]
        plan = icacls_plan("remove", summary, good, cmds, lambda e2, is_dir: op_remove_entries(be, e2, keys, is_dir))
        if not plan["cmds"]:
            raise Abort("Nothing icacls can remove (only inherited entries were picked).")
    rec = review_and_apply(plan)
    if rec:
        show_after(S.targets[:2])


def edit_text(initial, hint):
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("notepad" if IS_WIN else
                                                                    next((e for e in ("nano", "vim", "vi") if have(e)), None))
    if editor:
        fd, tmp = tempfile.mkstemp(prefix="hs-warden-edit-", suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write("# " + hint.replace("\n", "\n# ") + "\n# Lines starting with # are ignored.\n" + initial + "\n")
        try:
            subprocess.call(shlex.split(editor) + [tmp] if not IS_WIN else [editor, tmp])
            with open(tmp) as f:
                return "\n".join(l for l in f.read().splitlines() if not l.strip().startswith("#"))
        finally:
            os.unlink(tmp)
    out("  " + hint.replace("\n", "\n  "))
    out("  Current:\n" + initial)
    out("  Type the new text; finish with a line containing only a dot.")
    lines = []
    while True:
        l = read_line("")
        if l.strip() == ".":
            return "\n".join(lines)
        lines.append(l)


def do_edit():
    need_targets()
    be = S.be
    tgt = S.targets[0]
    if len(S.targets) > 1:
        tgt = S.targets[int(choose("Edit which target?", [(str(i + 1), t) for i, t in enumerate(S.targets)], "1")) - 1]
    items, _ = read_state([tgt], recursive=False)
    it = items[0]
    if it.get("error"):
        raise Abort(it["error"])
    meta, ents = parse_item(be, it)
    sub("Current: " + tgt)
    print_table(be, ents, it["is_dir"], meta=meta)
    if be.key == "chmod":
        spec = ask("New mode ({})".format(be.native_hint), it["raw"])
        try:
            new_raw = "%04o" % chmod_symbolic(int(it["raw"], 8), spec, it["is_dir"])
        except ValueError as e:
            raise Abort(str(e))
    else:
        new_raw = edit_text(it["raw"], be.native_hint).strip()
        if not new_raw:
            raise Abort("Empty ACL; nothing changed. (Use Remove to drop entries.)")
    try:
        nmeta, nents = be.parse(new_raw, tgt) if be.key != "icacls" else ({}, [])
    except AclError as e:
        raise Abort("Can't use that ACL: {}".format(e))
    if be.key != "icacls" and not nents:
        raise Abort("No entries found in the new ACL.")
    plan = {"kind": "edit", "summary": "Edit native ACL of " + tgt, "notes": [], "cmds": [], "force_set": True,
            "items": [{"path": tgt, "is_dir": it["is_dir"], "top": True, "before": it["raw"], "after": new_raw,
                       "changed": norm_text(new_raw) != norm_text(it["raw"]), "before_entries": ents,
                       "after_entries": nents, "meta": nmeta, "before_meta": meta}]}
    if be.key == "icacls":
        plan["items"][0]["after_entries"] = ents
        plan["notes"].append("icacls: the new SDDL is written with icacls /restore; the table shows the current entries.")
    if not plan["items"][0]["changed"]:
        ok("No change.")
        return
    if review_and_apply_set(plan):
        show_after([tgt])


def review_and_apply_set(plan):
    """Preview / apply for plans written with set_raw (edit, undo) on any backend."""
    full = S.be.full_set
    S.be.full_set = True
    try:
        return review_and_apply(plan)
    finally:
        S.be.full_set = full


# ==============================================================================
#  LOG VIEW & UNDO
# ==============================================================================
def rec_line(r):
    st = "UNDONE by " + r["undone_by"] if r.get("undone_by") else ("UNCONFIRMED" if r["results"].get("unconfirmed") else "")
    return "{}  {:<7} {:<14} {:<6} {}  {}{}{}".format(
        r["time"].replace("T", " "), r["backend"], r["where"][:14], r["kind"], r["summary"][:60],
        C.Y, st, C.X)


def do_log():
    recs = S.log.records()
    if not recs:
        info("No changes logged yet in " + S.log.base)
        return
    dim("  Log folder: " + S.log.base)
    shown = recs[-30:][::-1]
    for i, r in enumerate(shown):
        out("  {:>3}) {}".format(i + 1, rec_line(r)))
    s = ask("Number to see details (Enter to go back)", required=False)
    if not s:
        return
    try:
        r = shown[int(s) - 1]
    except (ValueError, IndexError):
        return
    sub("Change " + r["id"])
    for k in ("time", "user", "host", "backend", "where", "kind", "summary", "recursive", "objects", "undo_of", "undone_by"):
        if r.get(k) not in (None, ""):
            out("  {:<10} {}".format(k, r[k]))
    out("  results    " + ", ".join("{} {}".format(k, v) for k, v in r["results"].items()))
    out("  snapshot   " + os.path.join(S.log.base, r.get("snapshot", "")))
    for c in r.get("commands", [])[:10]:
        out("  $ " + c.replace("\n", "\n    "))


def do_undo():
    recs = [r for r in S.log.records() if r.get("snapshot")]
    if not recs:
        info("No changes to undo in " + S.log.base)
        return
    shown = recs[-20:][::-1]
    for i, r in enumerate(shown):
        out("  {:>3}) {}".format(i + 1, rec_line(r)))
    s = ask("Change to undo")
    try:
        r = shown[int(s) - 1]
    except (ValueError, IndexError):
        raise Abort("No such change.")
    if r.get("undone_by"):
        warn("This change was already undone by {}.".format(r["undone_by"]))
        if not confirm("Undo it again anyway?", False):
            return
    if r["host"] != HOST:
        raise Abort("Change {} was made from {}; run the undo there.".format(r["id"], r["host"]))
    snap = S.log.snapshot(r)
    be = BACKENDS[r["backend"]]()
    if r["where"].startswith("salt:"):
        node = r["where"][5:]
        if S.ctx.node_type != "anvil" or not S.ctx.tmux_ok:
            raise Abort("This change ran on DSX {} through salt; undo it from the Anvil (in tmux).".format(node))
        ex = S.salt_execs.get(node) or SaltExec(node)
        S.salt_execs[node] = ex
    else:
        ex = LocalExec()
    todo = [i for i in snap["items"] if i["status"] in ("ok", "unconfirmed") and i.get("before") is not None
            and (i.get("after") is None or norm_text(i["after"]) != norm_text(i["before"]))]
    if not todo:
        raise Abort("The snapshot has nothing to restore.")
    S.be, S.ex = be, ex
    cur, _ = read_state([i["path"] for i in todo], recursive=False)
    cur_by = dict((c["path"], c) for c in cur)
    drift = []
    items = []
    for i in todo:
        c = cur_by.get(i["path"], {})
        if c.get("error"):
            warn("{}: {}".format(i["path"], c["error"]))
            continue
        if i.get("after") is not None and norm_text(c.get("raw")) != norm_text(i["after"]):
            drift.append(i["path"])
        items.append({"path": i["path"], "is_dir": c.get("is_dir"), "top": len(items) < 3, "before": c["raw"],
                      "after": i["before"], "changed": norm_text(c["raw"]) != norm_text(i["before"]),
                      "expect": c["raw"], "display": c.get("display")})
    force = False
    if drift:
        warn("{} object(s) changed again after change {} (e.g. {}).".format(len(drift), r["id"], drift[0]))
        force = confirm("Restore them to the snapshot anyway (overwrites the later change)?", False)
        if not force:
            items = [i for i in items if i["path"] not in drift]
    for i in items:
        if be.key == "icacls":
            i["before_entries"] = parse_item(be, {"path": i["path"], "display": i.get("display") or ""})[1] if i.get("display") else []
            i["after_entries"] = i["before_entries"]
        else:
            i["before_meta"], i["before_entries"] = be.parse(i["before"], i["path"])
            i["meta"], i["after_entries"] = be.parse(i["after"], i["path"])
    plan = {"kind": "undo", "summary": "Undo change {} ({})".format(r["id"], r["summary"]), "items": items,
            "cmds": [], "notes": ["Each object is set back to its snapshot from before change {}.".format(r["id"])],
            "force_set": True}
    if be.key == "icacls":
        plan["notes"].append("icacls: SDDL is written back with icacls /restore.")
    full = be.full_set
    be.full_set = True
    try:
        changed = show_plan(plan)
        if not changed:
            ok("Everything already matches the snapshot.")
            return
        if confirm("Restore {} object(s) now?".format(len(changed)), False):
            apply_plan(plan, kind="undo", undo_of=r["id"])
        else:
            info("Cancelled; nothing changed.")
    finally:
        be.full_set = full


# ==============================================================================
#  COMPARE TWO TREES
# ==============================================================================
def strip_domain(who):
    w = who
    if "\\" in w:
        w = w.split("\\", 1)[1]
    if "@" in w and not w.endswith("@"):
        w = w.split("@", 1)[0]
    return w


def canon_entries(be, entries, opts):
    """Comparable form of an ACL: list of (who, type, rights, inherit, inherited)."""
    res = []
    for e in entries:
        who = who_key(e["who"])
        for a, b in opts["map"]:
            if a in who:
                who = who.replace(a, b)
        if opts["strip_domain"] and who not in SPECIALS:
            who = strip_domain(who)
        rights = be.canon(e["perms"])
        if opts["rights_mode"] == "rwx":
            rights = frozenset(x for x in rights if x in ("read_data", "write_data", "execute"))
        inh = "".join(sorted(e["inherit"])) if opts["inherit_flags"] else ""
        res.append((who, e["type"], rights, inh, bool(e.get("inherited")) if not opts["ignore_inherited"] else False))
    return res


def canon_label(rights):
    """A standard level name when the rights match one in any tool, else the list."""
    for cls in (RichAcl, Nfs4, Icacls):
        be = cls()
        for n in STANDARD_LEVELS:
            if be.canon(be.levels[n]) == rights:
                return n
    return ",".join(x for x in CANON if x in rights) + "".join("," + x for x in sorted(rights) if x not in CANON)


def canon_str(t):
    who, typ, rights, inh, inherited = t
    r = canon_label(rights)
    return "{} {} [{}]{}{}".format(who, typ, r.strip(",") or "none", " inherit=" + inh if inh else "",
                                   " (inherited)" if inherited else "")


def compare_one(ca, cb, opts):
    """-> (status, details[])"""
    if ca == cb:
        return "identical", []
    if sorted(ca, key=str) == sorted(cb, key=str):
        return "order", ["Same entries, different order (matters when deny entries are present)"]
    strip = [t[:4] + (False,) for t in ca], [t[:4] + (False,) for t in cb]
    if sorted(strip[0], key=str) == sorted(strip[1], key=str):
        return "inherited-flag", ["Same entries; the inherited flag differs"]
    det = []
    rest_b = list(cb)
    only_a = []
    for t in ca:
        if t in rest_b:
            rest_b.remove(t)
        else:
            only_a.append(t)
    changed_keys = set()
    for t in list(only_a):
        m = [u for u in rest_b if u[0] == t[0] and u[1] == t[1]]
        if m:
            u = m[0]
            parts = []
            if u[2] != t[2]:
                la, lb = canon_label(t[2]) or "none", canon_label(u[2]) or "none"
                if la != lb:
                    parts.append("{} -> {}".format(la, lb))
                lost = [x for x in CANON if x in t[2] and x not in u[2]]
                gained = [x for x in CANON if x in u[2] and x not in t[2]]
                parts.append("rights" + (" lost: " + ",".join(lost) if lost else "") +
                             (" gained: " + ",".join(gained) if gained else ""))
            if u[3] != t[3]:
                parts.append("inherit {} -> {}".format(t[3] or "none", u[3] or "none"))
            if u[4] != t[4]:
                parts.append("inherited {} -> {}".format(t[4], u[4]))
            det.append("~ {} {}: {}".format(t[0], t[1], "; ".join(parts)))
            only_a.remove(t)
            rest_b.remove(u)
            changed_keys.add((t[0], t[1]))
    for t in only_a:
        det.append("- missing on destination: " + canon_str(t))
    for u in rest_b:
        det.append("+ extra on destination:   " + canon_str(u))
    return "different", det


def compare_side(label, default_key=None):
    sub(label)
    be, ex = select_backend("{}: which tool reads it?".format(label), default_key)
    if isinstance(ex, SaltExec):
        dim("  Give /hs/<share>/... (Anvil view) or {}/<share>/... (DSX view).".format(PORTAL))
    root = ex.to_target(ask("{} root path".format(label)).strip().strip("'\""))
    return be, ex, root


def rel_of(path, root, fold):
    r = os.path.relpath(path, root) if not root.endswith(":\\") else path[len(root):]
    r = r.replace("\\", "/")
    if r == ".":
        r = ""
    return r.lower() if fold else r


def do_compare():
    dim("  Reads both trees, matches files by path relative to each root, and reports")
    dim("  what differs. Read-only: nothing is changed.")
    be_a, ex_a, root_a = compare_side("Source (e.g. before migration)", S.be.key if S.be else None)
    be_b, ex_b, root_b = compare_side("Destination (e.g. after migration)", be_a.key)
    sub("Options")
    recursive = confirm("Compare everything below the roots (recursive)?", True)
    depth = None
    if recursive:
        d = ask("Max depth below the root (Enter = no limit)", required=False)
        depth = int(d) if d.isdigit() else None
    cross = be_a.key != be_b.key
    opts = {"map": [], "strip_domain": False, "inherit_flags": True, "ignore_inherited": False,
            "rights_mode": "rwx" if "chmod" in (be_a.key, be_b.key) else "full"}
    if cross:
        info("Different tools: rights are compared by meaning (read_data, write_acl, ...), not by letters.")
        if opts["rights_mode"] == "rwx":
            warn("chmod on one side: only read / write / execute and owner@ / group@ / everyone@ can be compared.")
    fold = confirm("Match paths case-insensitively?", "icacls" in (be_a.key, be_b.key))
    opts["ignore_inherited"] = confirm("Ignore the 'inherited' flag (count inherited vs explicit as the same)?", False)
    opts["strip_domain"] = confirm("Ignore domain parts of names (alice@corp.local = CORP\\alice = alice)?", cross)
    while confirm("Add a name mapping (e.g. @old.local -> @new.local)?", False):
        a = ask("Replace (source text)").lower()
        b = ask("With (destination text)", "", required=False).lower()
        opts["map"].append((a, b))
    owner = not IS_WIN and be_a.key != "icacls" and be_b.key != "icacls" and \
        confirm("Also compare POSIX owner / group (uid, gid)?", True)
    if owner:
        owner_by = choose("Compare owner/group by:", [("1", "Name (user / group name)"), ("2", "Number (uid / gid)")], "1")
    saved = (S.be, S.ex)
    try:
        S.be, S.ex = be_a, ex_a
        items_a, tr_a = read_state([root_a], recursive, be_a, ex_a, owner=owner, display_all=True, max_depth=depth)
        S.be, S.ex = be_b, ex_b
        items_b, tr_b = read_state([root_b], recursive, be_b, ex_b, owner=owner, display_all=True, max_depth=depth)
    finally:
        S.be, S.ex = saved
    if tr_a or tr_b:
        warn("At least one side stopped at --max-items {}; files past that show as missing.".format(S.max_items))
    map_a = dict((rel_of(i["path"], root_a, fold), i) for i in items_a)
    map_b = dict((rel_of(i["path"], root_b, fold), i) for i in items_b)
    rows = []
    counts = {}
    for rel in sorted(set(map_a) | set(map_b), key=natural_key):
        a, b = map_a.get(rel), map_b.get(rel)
        row = {"path": rel or ".", "status": "", "details": [], "source": "", "destination": ""}
        if a is None:
            row["status"] = "missing-on-source"
        elif b is None:
            row["status"] = "missing-on-destination"
        elif a.get("error") or b.get("error"):
            row["status"] = "error"
            row["details"] = [x for x in ("source: " + a["error"] if a.get("error") else "",
                                          "destination: " + b["error"] if b.get("error") else "") if x]
        else:
            ma, ea = parse_item(be_a, a)
            mb, eb = parse_item(be_b, b)
            ca, cb = canon_entries(be_a, ea, opts), canon_entries(be_b, eb, opts)
            row["status"], row["details"] = compare_one(ca, cb, opts)
            row["source"] = " | ".join(canon_str(t) for t in ca)
            row["destination"] = " | ".join(canon_str(t) for t in cb)
            if not cross and be_a.key == "richacl" and ma.get("flags") != mb.get("flags"):
                row["details"].append("ACL flags {} -> {}".format(ma.get("flags"), mb.get("flags")))
                if row["status"] == "identical":
                    row["status"] = "different"
            if owner and a.get("owner") and b.get("owner"):
                oa, ob = a["owner"], b["owner"]
                ku, kg = ("user", "groupname") if owner_by == "1" else ("uid", "gid")
                ua, ub = oa.get(ku, oa["uid"]), ob.get(ku, ob["uid"])
                ga, gb = oa.get(kg, oa["gid"]), ob.get(kg, ob["gid"])
                if str(ua) != str(ub) or str(ga) != str(gb):
                    row["details"].append("owner {}:{} -> {}:{}".format(ua, ga, ub, gb))
                    if row["status"] in ("identical", "order", "inherited-flag"):
                        row["status"] = "owner"
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        rows.append(row)
    write_compare_report(rows, counts, opts, (be_a, ex_a, root_a), (be_b, ex_b, root_b), recursive, depth, owner)


STATUS_TEXT = [("identical", "Identical"), ("different", "Entries / rights differ"),
               ("inherited-flag", "Only the inherited flag differs"), ("order", "Same entries, different order"),
               ("owner", "Only owner / group differs"), ("missing-on-destination", "Missing on destination"),
               ("missing-on-source", "Only on destination"), ("error", "Could not read")]


def write_compare_report(rows, counts, opts, A, B, recursive, depth, owner):
    rid = new_id()
    d = os.path.join(S.log.rep_dir, "compare-" + rid)
    os.makedirs(d)
    diffs = [r for r in rows if r["status"] != "identical"]
    head("COMPARE RESULT")
    out("  Source:       {}  ({} on {})".format(A[2], A[0].short, A[1].describe()))
    out("  Destination:  {}  ({} on {})".format(B[2], B[0].short, B[1].describe()))
    out("  Objects compared: {}".format(len(rows)))
    for k, t in STATUS_TEXT:
        if counts.get(k):
            color = C.G if k == "identical" else C.Y
            out("    {}{:<34}{} {}".format(color, t, C.X, counts[k]))
    if diffs:
        sub("First differences")
        for r in diffs[:15]:
            out("  {}{}{}  [{}]".format(C.B, r["path"], C.X, r["status"]))
            for x in r["details"][:6]:
                out("      " + x)
        if len(diffs) > 15:
            dim("  ... {} more in the report".format(len(diffs) - 15))
    else:
        ok("No permission differences found.")
    csv_fn = os.path.join(d, "differences.csv")
    with open(csv_fn, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "status", "details", "source_acl", "destination_acl"])
        for r in diffs:
            w.writerow([r["path"], r["status"], " ; ".join(r["details"]), r["source"], r["destination"]])
    md = os.path.join(d, "summary.md")
    with open(md, "w") as f:
        f.write("# {} permission comparison {}\n\n".format(DISPLAY_NAME, rid))
        f.write("| | |\n|---|---|\n")
        f.write("| Run | {} by {}@{} (Warden v{}) |\n".format(now_iso(), getpass.getuser(), HOST, TOOLKIT_VERSION))
        f.write("| Source | `{}` ({} on {}) |\n".format(A[2], A[0].label, A[1].describe()))
        f.write("| Destination | `{}` ({} on {}) |\n".format(B[2], B[0].label, B[1].describe()))
        f.write("| Scope | {}{} |\n".format("recursive" if recursive else "top only",
                                            ", depth {}".format(depth) if depth is not None else ""))
        f.write("| Options | rights compared: {}; inherited flag {}; domains {}; name maps: {}; owner/group: {} |\n\n".format(
            "read/write/execute only" if opts["rights_mode"] == "rwx" else "all",
            "ignored" if opts["ignore_inherited"] else "compared",
            "ignored" if opts["strip_domain"] else "compared",
            ", ".join("{} -> {}".format(a, b) for a, b in opts["map"]) or "none", "yes" if owner else "no"))
        f.write("## Totals\n\n| Result | Objects |\n|---|---:|\n")
        for k, t in STATUS_TEXT:
            if counts.get(k):
                f.write("| {} | {} |\n".format(t, counts[k]))
        f.write("| **Compared** | **{}** |\n\n".format(len(rows)))
        if diffs:
            f.write("## Differences (first 500; all in differences.csv)\n\n")
            for r in diffs[:500]:
                f.write("### `{}` — {}\n\n".format(r["path"], r["status"]))
                for x in r["details"]:
                    f.write("- {}\n".format(x.replace("|", "\\|")))
                f.write("\n")
    with open(os.path.join(d, "compare.json"), "w") as f:
        json.dump({"id": rid, "warden_version": TOOLKIT_VERSION, "source": {"root": A[2], "backend": A[0].key, "where": A[1].where},
                   "destination": {"root": B[2], "backend": B[0].key, "where": B[1].where},
                   "options": dict(opts, map=[list(x) for x in opts["map"]]), "counts": counts, "rows": rows}, f, indent=1)
    with open(S.log.text, "a") as f:
        f.write("{}  {}  v{}  {}@{}  compare: {} ({}) vs {} ({})  {}\n".format(
            now_iso(), rid, TOOLKIT_VERSION, getpass.getuser(), HOST, A[2], A[1].where, B[2], B[1].where,
            ", ".join("{} {}".format(k, v) for k, v in sorted(counts.items()))))
    ok("Report: {}".format(d))
    dim("  summary.md, differences.csv (opens in Excel), compare.json")


# ==============================================================================
#  MAIN MENU
# ==============================================================================
BANNER_W = 87
LOGO = r"""        _____________
       /             \
       \     _____    \
        \    \    \    \
         \    \    \    \
   ___    \____\    \    \
  /   \              \    \
  \    \     _____    \___/
   \    \    \    \
    \    \    \    \
     \    \____\    \
      \              \
       \_____________/"""


def banner():
    """Launch banner: Hammerspace logo in a star frame; a short header on
    terminals narrower than the frame (same layout as hs-cerberus)."""
    inner = BANNER_W - 2
    year = time.strftime("%Y")
    cols = shutil.get_terminal_size((80, 24)).columns
    L = [""]
    if cols >= BANNER_W:
        stars = "*" * BANNER_W

        def line(t):
            return "*{:<{w}}*".format(t, w=inner)

        def center(t):
            return "*" + t.center(inner) + "*"
        L += [stars, center("Copyright (C) 2016-{} Hammerspace, Inc.".format(year)), line("")]
        L += [line(" " * 28 + l) for l in LOGO.splitlines()]
        L += [line(""), center("H A M M E R S P A C E   P S   W A R D E N"), line(""), center("W.A.R.D.E.N."),
              center("Wide-spectrum Access Rights"), center("& Directory Enforcement Navigator"),
              line(""), center("v" + TOOLKIT_VERSION), line(""), stars]
    else:
        L += ["{}  v{}".format(DISPLAY_NAME, TOOLKIT_VERSION),
              "Wide-spectrum Access Rights & Directory Enforcement Navigator",
              "Copyright (C) 2016-{} Hammerspace, Inc.".format(year)]
    out(C.Y + "\n".join(L) + C.X)
    out("")


def status_lines():
    nt = {"dsx": "Hammerspace DSX", "anvil": "Hammerspace Anvil (Salt master)"}.get(S.ctx.node_type, "")
    dim("  Host: {}{}{}   Log folder: {}".format(HOST, "  [{}]".format(nt) if nt else "",
                                                 "  [tmux]" if os.environ.get("TMUX") else "", S.log.base))
    out("  Tool:     {}".format(S.be.label + "  on " + S.ex.describe() if S.be else "(not chosen: option 1)"))
    t = ", ".join(S.targets[:3]) + (" +{} more".format(len(S.targets) - 3) if len(S.targets) > 3 else "")
    out("  Targets:  {}{}".format(t or "(none: option 2)", "   [recursive]" if S.recursive and S.targets else ""))


TOOL_TITLES = {"3": "View Permissions", "4": "Grant or Change Access", "5": "Remove Access",
               "6": "Edit the Full ACL", "7": "Compare: Source vs Destination", "8": "Change Log",
               "9": "Undo a Change"}


def main_menu():
    actions = {"1": lambda: setattr_pair(select_backend()), "2": select_targets, "3": do_view, "4": do_grant,
               "5": do_remove, "6": do_edit, "7": do_compare, "8": do_log, "9": do_undo}
    first = True
    while True:
        clear()
        if first:
            banner()
            first = False
        else:
            out("{}{}".format(C.B, C.CY))
            out("  ╔════════════════════════════════════════════════════╗")
            out("  ║         Hammerspace PS Warden  {:<9}           ║".format("v" + TOOLKIT_VERSION))
            out("  ╚════════════════════════════════════════════════════╝")
            out(C.X)
        status_lines()
        out("")
        out("  {}Setup{}".format(C.B, C.X))
        out("    1) Choose permission tool       (nfs4, icacls, chmod, Hammerspace richacl)")
        out("    2) Choose target path(s)        (and recursive)")
        out("  {}Permissions{}".format(C.B, C.X))
        out("    3) View permissions")
        out("    4) Grant or change access       (preview, apply, log)")
        out("    5) Remove access")
        out("    6) Edit the full ACL            (native text, SDDL or mode)")
        out("  {}Data migration{}".format(C.B, C.X))
        out("    7) Compare permissions          (source vs destination: did the migration change them?)")
        out("  {}History{}".format(C.B, C.X))
        out("    8) Change log")
        out("    9) Undo a change")
        out("")
        out("    q) Quit")
        out("")
        try:
            c = read_line("  Select [1-9, q]: ").strip().lower()
        except Back:
            out("")
            return 0
        except KeyboardInterrupt:
            out("")
            return 130
        if c in ("q", "quit", "exit", "0"):
            out("")
            return 0
        if c not in actions:
            err("Invalid selection.")
            time.sleep(1)
            continue
        if c in TOOL_TITLES:
            box(TOOL_TITLES[c])
        try:
            actions[c]()
        except Back:
            continue
        except Abort as e:
            err(str(e))
        except (ExecError, AclError) as e:
            err(str(e))
        except KeyboardInterrupt:
            out("")
            warn("Interrupted.")
        pause()


def setattr_pair(pair):
    old = S.be.key if S.be else None
    S.be, S.ex = pair
    if old and old != S.be.key and S.targets:
        info("Tool changed; check the target paths still make sense (menu 2).")


def usage():
    out("""{name} v{v}
{title}

Usage: sudo python3 {s} [OPTIONS]

  (none)                Interactive menu
  --log-dir DIR         Logs, snapshots, saved plans and compare reports
                        (default ~/.hs-warden, or $HS_WARDEN_HOME)
  --max-items N         Most objects read in one go, per side in Compare
                        (default {mi})
  -h, --help            Show this help
  -v, --version         Show version

Backends: nfs4_getfacl/nfs4_setfacl, Windows icacls, chmod, and Hammerspace
getrichacl/setrichacl. The Hammerspace tools run only on a DSX: locally on a
DSX, or from the active Anvil (Salt master) through salt. On any Hammerspace
node WARDEN runs inside tmux and relaunches itself in one if needed.

Requires Python 3.6 or newer (python3 on Hammerspace nodes).""".format(
        name=DISPLAY_NAME, v=TOOLKIT_VERSION, title=TITLE, s=os.path.basename(SELF_PATH), mi=DEFAULT_MAX_ITEMS))


def main(argv=None):
    if sys.version_info < (3, 6):
        sys.stderr.write("{} needs Python 3.6 or newer.\n".format(DISPLAY_NAME))
        return 1
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog=PROG, add_help=False)
    ap.add_argument("--log-dir", default=os.environ.get("HS_WARDEN_HOME") or os.path.join(os.path.expanduser("~"), ".hs-warden"))
    ap.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    ap.add_argument("-v", "--version", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    ap.add_argument("--agent", action="store_true")
    ap.add_argument("--job-file")
    ap.add_argument("--result-file")
    args, unknown = ap.parse_known_args(argv)
    if unknown:
        err("Unknown option: " + " ".join(unknown))
        usage()
        return 1
    if args.help:
        usage()
        return 0
    if args.version:
        out(TOOLKIT_VERSION)
        return 0
    if args.agent:
        return agent_main(args)
    _init_colors()
    S.ctx = Ctx()
    S.ctx.node_type = detect_node_type()
    ensure_tmux(S.ctx, argv)
    S.log = Log(os.path.abspath(os.path.expanduser(args.log_dir)))
    S.max_items = args.max_items
    rc = 0
    try:
        rc = main_menu() or 0
    except KeyboardInterrupt:
        out("")
        rc = 130
    if os.environ.get("HS_WARDEN_TMUX"):
        try:
            input("\n  {} finished. Press Enter to close this tmux session.".format(DISPLAY_NAME))
        except (EOFError, KeyboardInterrupt):
            pass
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
