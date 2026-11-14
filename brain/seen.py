"""(0.105.46, I1) The "seen in game" ledger: what of the new versions the game
has actually shown working, refused, or not yet met.

    python brain/seen.py                         the DF-AI folders beside this one (or this one alone)
    python brain/seen.py --folders C:\\DF-AI C:\\DF-AI-B ...
    python brain/seen.py --since 0.105.40         from that version (default 0.105.32)
    python brain/seen.py --since 2026-11-13       from that date

For each DF-AI folder, from what is on disk (no game call, nothing changed):
- each report section that came in since the version (the bridge's SECTIONS
  table, dated by the version tags in its comments): in the last report
  (state.json; a full season copy when state.json is a pulse) present, an
  `{"error": ...}` with its text, or missing; and the counts of full reports
  it came through ok or as an error (the overseer's tally,
  logs/forts/<fort>/seen-sections.json, note_report below);
- each bridge action that came in since the version (ACTIONS): in the
  journals since the date, how often done, refused (the game said no),
  failed (no answer) or only dry-run, with the first time and the first
  reason of each;
- each Rules switch that came in since the version (the settings' defaults):
  its value now, from the report's `settings`;
- docs/watch-in-game.md's lines from the version on, matched to those by the
  names they mention in backticks (`hunt_send`, `killzones.threats`): seen
  (every name met), partly seen, refused, error, not met, or needs eyes (a
  line about how a thing looks or behaves in the game, or with nothing to
  match: the journal can't say it). A line is never ticked on less.

Writes <folder>/logs/seen-ledger.md, and with several folders a summary
across them (the first folder's logs/seen-ledger-all.md, or --out).
health_check.py runs ledger() on its own folder each day (the keeper's
daily check) and adds a short "seen" part.

Versions: a tag `(0.105.45)` on the entry's line, else the tag of the comment
block just above it (a group such as `-- (0.105.45) hunting: ...`); tags with
no version number (`(item5)`, `(D0)`) go through TAG_VERSIONS, names whose
tag misleads through NAME_VERSIONS (the hand table, the fallback only).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from util import load_json  # noqa: E402

DEFAULT_SINCE = "0.105.32"
LEDGER_NAME = "seen-ledger.md"
SUMMARY_NAME = "seen-ledger-all.md"
TALLY_NAME = "seen-sections.json"

# when each version reached the forts (the handoff's changelog; the date a
# --since version stands for). A version not here: the newest one before it.
VERSION_DATES = {
    "0.105.32": "2026-11-11", "0.105.33": "2026-11-11", "0.105.34": "2026-11-11",
    "0.105.35": "2026-11-11", "0.105.36": "2026-11-11", "0.105.37": "2026-11-12",
    "0.105.38": "2026-11-12", "0.105.39": "2026-11-12", "0.105.40": "2026-11-12",
    "0.105.41": "2026-11-12", "0.105.42": "2026-11-13", "0.105.43": "2026-11-14",
    "0.105.44": "2026-11-14", "0.105.45": "2026-11-14", "0.105.46": "2026-11-14",
}

# the hand table: tags without a version number, by the round they were built in
TAG_VERSIONS = {
    "item1": "0.105.44", "item3": "0.105.44", "item4": "0.105.44",
    "item5": "0.105.41", "item6": "0.105.41", "item8": "0.105.41", "item9": "0.105.41",
    "item10": "0.105.41", "item11": "0.105.41", "item12": "0.105.41",
    "fix41": "0.105.41", "fix6": "0.105.41",
    "d0": "0.105.37", "e4": "0.105.37",
}
# ... and names whose tag points at the wrong round
NAME_VERSIONS = {
    # old sections and actions under a group comment that tells of a change, not of their coming
    **{("section", n): None for n in ("paused", "fort", "date", "wealth", "dwarves", "units", "stocks",
                                      "supplies", "dead", "orders", "farms", "tools", "others_on_map", "deep")},
    ("action", "tool"): None, ("action", "civ_alert"): None,
    ("switch", "expel_vampires"): None,
    ("action", "release_prisoners"): "0.105.44",   # "(item5) no water for the jail": 0.105.44's G5, not the siege item5
    ("section", "weather"): "0.105.40",            # "(fix41)" moved it into the pulse; built in 0.105.40
    ("section", "perf"): "0.105.39",               # built outside SECTIONS (perf_section)
    ("switch", "squads_shelter"): None,            # an old switch whose meaning changed in 0.105.45
}

VERSION_RE = re.compile(r"\b0\.(\d+)\.(\d+)")
TAG_RE = re.compile(r"\(([^()]*)\)")
NAME_RE = re.compile(r"\b([A-Za-z_]\w*)\s*=(?!=)")


def vtuple(v: str | None) -> tuple:
    m = VERSION_RE.search(str(v or ""))
    return (0, int(m.group(1)), int(m.group(2))) if m else ()


def tag_version(text: str) -> str | None:
    """The version a comment's tags name: `(0.105.45)`, `(0.105.40b fix)`,
    `(0.105.41, item 4)`; `(item5)` / `(D0)` through TAG_VERSIONS; None when
    no tag dates it."""
    for tag in TAG_RE.findall(text or ""):
        m = VERSION_RE.search(tag)
        if m:
            return f"0.{m.group(1)}.{m.group(2)}"
        for word in re.split(r"[,;]\s*", tag):
            key = re.sub(r"\s+", "", word.strip().lower()).split("-")[0]
            if key in TAG_VERSIONS:
                return TAG_VERSIONS[key]
    return None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_table(lines: list[str], start: int) -> dict[str, str | None]:
    """Entries of a Lua table literal whose opening line is lines[start]:
    {name: version}. Entries are the lines at the table's own indent (the
    first entry's) that begin `name =`. A tag on the entry's line wins;
    else the tag of the comment block just above (a group header) dates the
    first entry under it and the ones after it of the same shape (one line
    each, or each a function over several lines: `hunt_send`, `hunt_recall`),
    until an entry with a tag of its own, a blank line or another comment.
    A single-line entry after a group of functions is not the group's
    (`tool` after `polish_room`)."""
    rows = []                 # [names, own tag, group tag, group id, multi]
    base = _indent(lines[start])
    ind = None
    group, gid = None, 0
    in_comment = False
    for line in lines[start + 1:]:
        s = line.strip()
        if not s:
            group, in_comment = None, False
            gid += 1
            continue
        if _indent(line) <= base and (s.startswith("}") or s.startswith(")")):
            break
        if ind is None and NAME_RE.match(s):
            ind = _indent(line)
        if ind is None:
            continue
        if _indent(line) > ind:
            if rows and not s.startswith("--"):
                rows[-1][4] = True            # the entry goes on: a function over several lines
            continue
        if _indent(line) < ind:
            continue
        if s.startswith("--"):
            v = tag_version(s)
            if not in_comment:
                group = v
                gid += 1
            elif group is None:
                group = v
            in_comment = True
            continue
        in_comment = False
        code, _, comment = s.partition("--")
        names = NAME_RE.findall(code)
        if not names or not re.match(r"[A-Za-z_]\w*\s*=", code):
            continue
        own = tag_version(comment) if comment else None
        rows.append([names, own, group, gid, False])
        if own:
            group = None
            gid += 1
    out: dict[str, str | None] = {}
    first_shape: dict = {}
    for names, own, grp, g, multi in rows:
        v = own
        if v is None and grp is not None:
            shape = first_shape.setdefault(g, multi)
            v = grp if shape == multi else None
            if shape != multi:
                first_shape[g] = "ended"
        for n in names:
            # `x = act_x, y = act_y` on one line; `a.kind ~= ...` never matches (=(?!=) and ~)
            out.setdefault(n, v)
    return out


def _find(lines: list[str], pattern: str) -> int | None:
    rx = re.compile(pattern)
    for i, line in enumerate(lines):
        if rx.search(line):
            return i
    return None


def registry(root: Path = ROOT) -> dict:
    """{"action": {name: version}, "section": {...}, "switch": {...}} from the
    code in `root` (lua/ai-bridge.lua's ACTIONS and SECTIONS, the defaults
    in lua/ai-overseer-settings.lua), the hand table applied."""
    out = {"action": {}, "section": {}, "switch": {}}

    def read(p: Path) -> list[str]:
        try:
            return p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
    bridge = read(root / "lua" / "ai-bridge.lua")
    for kind, pat in (("action", r"^ACTIONS\s*=\s*\{"), ("section", r"^SECTIONS\s*=\s*\{")):
        i = _find(bridge, pat)
        if i is not None:
            out[kind] = parse_table(bridge, i)
    settings = read(root / "lua" / "ai-overseer-settings.lua")
    i = _find(settings, r"^function defaults\(\)")
    if i is not None:
        j = _find(settings[i:], r"^\s*return\s*\{")
        if j is not None:
            sw = parse_table(settings, i + j)
            for k in ("version", "traits", "ai_sliders", "levels"):
                sw.pop(k, None)
            out["switch"] = sw
    out["section"].setdefault("perf", None)
    for (kind, name), v in NAME_VERSIONS.items():
        if name in out[kind]:
            out[kind][name] = v
    return out


def new_since(reg: dict, since_version: str | None) -> dict:
    """The registry's names that came in at since_version or later, by kind:
    {kind: [(version, name)]}, oldest first."""
    lo = vtuple(since_version) if since_version else ()
    out = {}
    for kind, names in reg.items():
        out[kind] = sorted(((v, n) for n, v in names.items() if v and vtuple(v) >= lo),
                           key=lambda vn: (vtuple(vn[0]), vn[1]))
    return out


def since_date(since: str | None) -> datetime | None:
    """A version's delivery date, or a date given as YYYY-MM-DD[THH:MM]."""
    if not since:
        return None
    if vtuple(since) and not re.match(r"^\d{4}-", since):
        best = None
        for v, d in VERSION_DATES.items():
            if vtuple(v) <= vtuple(since) and (best is None or vtuple(v) > vtuple(best[0])):
                best = (v, d)
        return datetime.fromisoformat(best[1]) if best else None
    try:
        return datetime.fromisoformat(since)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# the overseer's tally of report sections (each full report)
# ---------------------------------------------------------------------------

TALLY_WRITE_S = 600          # the tally file rewritten at least this often while it changes
_TALLY: dict = {}            # path -> {"data", "written", "dirty"}
SKIP_KEYS = ("tier", "_timing", "_errors", "_run")


def note_report(state: dict, folder: Path | None, now: float | None = None) -> None:
    """(0.105.46) Called by the overseer with each report before normalize():
    per section of a full report (not a pulse, which is merged over the last
    full one), ok or `{"error"}`, counted in <fort folder>/seen-sections.json
    with the first ok, the first and last error and its text. Written when a
    section is first met or a new error appears, else every TALLY_WRITE_S.
    Never raises."""
    try:
        if folder is None or not isinstance(state, dict) or state.get("tier") not in (None, "daily", "survey"):
            return
        now = time.time() if now is None else now
        stamp = datetime.fromtimestamp(now).isoformat(timespec="seconds")
        path = Path(folder) / TALLY_NAME
        c = _TALLY.get(str(path))
        if c is None:
            c = _TALLY[str(path)] = {"data": load_json(path, {}), "written": now, "dirty": False}
        data = c["data"]
        secs = data.setdefault("sections", {})
        bv = state.get("bridge_version") if isinstance(state.get("bridge_version"), str) else None
        urgent = False
        for k, v in state.items():
            if k in SKIP_KEYS or k.startswith("_"):
                continue
            e = secs.get(k)
            if not isinstance(e, dict):
                e = secs[k] = {"ok": 0, "error": 0}
            if isinstance(v, dict) and "error" in v and len(v) <= 2:
                text = str(v.get("error"))[:200]
                if not e.get("error"):
                    e["first_error"] = stamp
                    urgent = True
                if e.get("error_text") != text:
                    urgent = True
                e["error"] = int(e.get("error") or 0) + 1
                e["last_error"], e["error_text"] = stamp, text
            else:
                if not e.get("ok"):
                    e["first_ok"] = stamp
                    e["first_ok_bridge"] = bv
                    urgent = True
                e["ok"] = int(e.get("ok") or 0) + 1
                e["last_ok"] = stamp
        data["reports"] = int(data.get("reports") or 0) + 1
        data["last"] = stamp
        data["bridge_version"] = bv
        c["dirty"] = True
        if urgent or now - c["written"] >= TALLY_WRITE_S:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                from dfhack import write_atomic
                write_atomic(path, json.dumps(data, ensure_ascii=False, indent=1))
            except Exception:  # noqa: BLE001
                path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            c.update(written=now, dirty=False)
    except Exception:  # noqa: BLE001  (a tally never stops the fort)
        pass


# ---------------------------------------------------------------------------
# reading a DF-AI folder
# ---------------------------------------------------------------------------

def state_path(folder: Path, log_dir: Path | None = None) -> Path | None:
    """The game's state.json for a DF-AI folder: config.json `state_path`,
    `dfhack_config` (the game's dfhack-config folder), the game folder the
    keeper last saw (logs/last-fort.json `df_path`), or `df_launch`'s folder."""
    log_dir = log_dir or folder / "logs"
    cfg = load_json(folder / "config.json", {})
    cands = []
    if cfg.get("state_path"):
        cands.append(Path(cfg["state_path"]))
    if cfg.get("dfhack_config"):
        cands.append(Path(cfg["dfhack_config"]) / "ai-overseer" / "state.json")
    lf = load_json(log_dir / "last-fort.json", {})
    if lf.get("df_path"):
        cands.append(Path(lf["df_path"]) / "dfhack-config" / "ai-overseer" / "state.json")
    launch = str(cfg.get("df_launch") or "")
    if launch and "://" not in launch:
        cands.append(Path(launch).parent / "dfhack-config" / "ai-overseer" / "state.json")
    for p in cands:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def fort_dirs(log_dir: Path, since: datetime | None) -> list[Path]:
    """The forts with a journal written since the date, newest first."""
    forts = log_dir / "forts"
    if not forts.is_dir():
        return []
    lo = since.timestamp() if since else 0.0
    out = []
    for d in forts.iterdir():
        if not d.is_dir():
            continue
        newest = max([_mtime(p) for p in d.glob("journal*.jsonl")] + [_mtime(d / TALLY_NAME)])
        if newest and newest >= lo:
            out.append((newest, d))
    return [d for _, d in sorted(out, key=lambda x: -x[0])]


def read_actions(forts: list[Path], since: datetime | None) -> dict:
    """Per action type, from the journals' decisions since the date:
    {type: {"ok", "refused", "failed", "waiting", "dry", "proposed",
    "first_ok", "first_refused", "refused_why", "first_failed", "failed_why"}}."""
    acts: dict = defaultdict(lambda: {"ok": 0, "refused": 0, "failed": 0, "waiting": 0, "dry": 0, "proposed": 0})
    lo = since.isoformat() if since else ""
    for d in forts:
        for path in sorted(d.glob("journal*.jsonl")):
            if since and _mtime(path) < since.timestamp():
                continue
            try:
                f = path.open(encoding="utf-8", errors="replace")
            except OSError:
                continue
            with f:
                for line in f:
                    if '"decision"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(e, dict) or e.get("kind") != "decision":
                        continue
                    t = str(e.get("time") or "")
                    if lo and t < lo:
                        continue
                    a = e.get("action") if isinstance(e.get("action"), dict) else {}
                    typ = a.get("type")
                    if not isinstance(typ, str):
                        continue
                    r = e.get("result") if isinstance(e.get("result"), dict) else None
                    x = acts[typ]
                    if r is None:
                        x["proposed"] += 1                # a dry-run cycle: proposed, not sent
                        continue
                    ok = r.get("ok")
                    why = str(r.get("error") or "")[:200]
                    if ok is True and (a.get("dry_run") or r.get("dry_run")):
                        x["dry"] += 1
                    elif ok is True:
                        x["ok"] += 1
                        if t and (not x.get("first_ok") or t < x["first_ok"]):
                            x["first_ok"] = t
                    elif r.get("waiting"):
                        x["waiting"] += 1
                        if t and (not x.get("first_waiting") or t < x["first_waiting"]):
                            x["first_waiting"], x["waiting_why"] = t, why
                    elif ok is False:
                        x["refused"] += 1
                        if t and (not x.get("first_refused") or t < x["first_refused"]):
                            x["first_refused"], x["refused_why"] = t, why
                    else:
                        x["failed"] += 1
                        if t and (not x.get("first_failed") or t < x["first_failed"]):
                            x["first_failed"], x["failed_why"] = t, why
    return dict(acts)


def read_tally(forts: list[Path]) -> dict:
    """The overseer's section tally, summed over the folder's forts."""
    out: dict = {}
    for d in forts:
        data = load_json(d / TALLY_NAME, {})
        for k, e in (data.get("sections") or {}).items():
            if not isinstance(e, dict):
                continue
            o = out.setdefault(k, {"ok": 0, "error": 0})
            o["ok"] += int(e.get("ok") or 0)
            o["error"] += int(e.get("error") or 0)
            for f, pick in (("first_ok", min), ("first_error", min), ("last_error", max), ("last_ok", max)):
                if e.get(f):
                    o[f] = pick(o[f], e[f]) if o.get(f) else e[f]
            if e.get("error_text") and (not o.get("error_text") or (e.get("last_error") or "") >= (o.get("_et") or "")):
                o["error_text"], o["_et"] = e["error_text"], e.get("last_error") or ""
    for o in out.values():
        o.pop("_et", None)
    return out


def season_states(forts: list[Path], since: datetime | None) -> list[tuple[float, Path]]:
    lo = since.timestamp() if since else 0.0
    out = []
    for d in forts:
        for p in (d / "states").glob("*.json"):
            m = _mtime(p)
            if m >= lo:
                out.append((m, p))
    return sorted(out)


def _is_error(v) -> bool:
    return isinstance(v, dict) and "error" in v and len(v) <= 2


def load_report(folder: Path, log_dir: Path, forts: list[Path], since: datetime | None) -> tuple[dict, str, int]:
    """(the last report, where it came from, season copies with errors seen):
    state.json; when that is a pulse (most sections missing) or absent, the
    newest season copy of a full report fills the sections it lacks."""
    sp = state_path(folder, log_dir)
    st = load_json(sp, {}) if sp else {}
    src = f"state.json ({sp})" if st else ""
    seasons = season_states(forts, since)
    if seasons and (not st or st.get("tier") == "pulse"):
        full = load_json(seasons[-1][1], {})
        if full:
            merged = dict(full)
            merged.update(st)
            st = merged
            src = (src + " + " if src else "") + f"season copy {seasons[-1][1].name}"
    return st, src or "no report found", len(seasons)


def season_errors(forts: list[Path], since: datetime | None) -> dict:
    """{section: count of season copies (full reports) since the date where it was an error}."""
    out: dict = defaultdict(int)
    for _, p in season_states(forts, since):
        s = load_json(p, {})
        for k, v in s.items():
            if _is_error(v):
                out[k] += 1
    return dict(out)


# ---------------------------------------------------------------------------
# docs/watch-in-game.md
# ---------------------------------------------------------------------------

EYES = re.compile(r"on the map|in game\b|in the game\b|look at|\bscreen\b|Rules tab|Army tab|the window|\bfits?\b|"
                  r"\bwalks?\b|\bwalk to\b|check (it|that)|\?|look in|watch (that|how)|in DF|\bnever\b|\bnothing\b", re.I)
TOKEN = re.compile(r"`([^`]+)`")
IDENT = re.compile(r"^[A-Za-z_]\w*(\.[\w\[\]]+)*$")


def watch_blocks(path: Path, since_version: str | None) -> list[dict]:
    """The watch file's blocks from the version on: [{"title", "version",
    "lines": [text]}]. A block starts at a `## ` heading or a bold lead
    line `**0.105.45 (H5): ...**`; its version is the heading's (`item1`
    through TAG_VERSIONS)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    lo = vtuple(since_version) if since_version else ()
    blocks, cur = [], None
    for line in text:
        s = line.strip()
        head = None
        if s.startswith("## "):
            head = s[3:].strip()
        elif s.startswith("**") and re.match(r"^\*\*(0\.\d+\.\d+|item\s*\d+)", s):
            head = s.strip("*").strip()
        if head is not None:
            m = VERSION_RE.search(head.split(":")[0]) or VERSION_RE.search(head)
            v = f"0.{m.group(1)}.{m.group(2)}" if m else tag_version(f"({head.split()[0]})")
            cur = {"title": head[:120], "version": v, "lines": []}
            blocks.append(cur)
            continue
        if cur is not None and re.match(r"^\s*- ", line):
            cur["lines"].append(s[2:].strip())
    return [b for b in blocks if b["lines"] and b["version"] and vtuple(b["version"]) >= lo]


def _path_in(v, parts: list[str]) -> bool:
    """Whether a dotted path is in a report value: a list matches when any
    element holds the rest."""
    if not parts:
        return v is not None and v != [] and v != {}
    if isinstance(v, list):
        return any(_path_in(x, parts) for x in v)
    if isinstance(v, dict):
        return parts[0] in v and _path_in(v[parts[0]], parts[1:])
    return False


def _has_name(v, name: str, budget: list) -> bool:
    """Whether a key (or a string value) called `name` is anywhere in a
    report value; at most budget[0] nodes walked."""
    stack = [v]
    while stack and budget[0] > 0:
        x = stack.pop()
        budget[0] -= 1
        if isinstance(x, dict):
            if name in x:
                return True
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x[:200])
        elif isinstance(x, str) and x == name:
            return True
    return False


FIELD_SKIP = {"error", "errors"}     # "no `error`": the section's own status says it
FIELD_BUDGET = 50000


def action_status(x: dict | None) -> str:
    x = x or {}
    if x.get("ok"):
        return "seen"
    if x.get("refused"):
        return "refused"
    if x.get("failed"):
        return "failed"
    if x.get("waiting"):
        return "waiting"
    return "not yet met"


def section_status(name: str, st: dict, tally: dict) -> tuple[str, str]:
    """(status, detail) of a report section: error now, present now, met
    earlier (the tally), or not yet met."""
    v = st.get(name)
    t = tally.get(name) or {}
    if _is_error(v):
        return "error", str(v.get("error"))[:160]
    if name in st and v is not None:
        return "seen", ""
    if t.get("ok"):
        return "seen", "earlier reports"
    if t.get("error"):
        return "error", str(t.get("error_text") or "")[:160]
    return "not yet met", ""


def match_line(text: str, reg: dict, acts: dict, st: dict, tally: dict) -> dict:
    """A watch line's verdict from the names it mentions in backticks."""
    ev, states = [], []
    seen_names = set()
    fields: list[str] = []       # backticked names that are no section, action or switch
    paths: list[str] = []        # the sections the line names
    for tok in TOKEN.findall(text):
        tok = tok.strip().split(" ")[0].split("(")[0].split("{")[0].rstrip(".,:;")
        if not IDENT.match(tok):
            continue
        parts = [p for p in tok.replace("[]", "").split(".") if p]
        head = parts[0]
        if tok in seen_names:
            continue
        seen_names.add(tok)
        if head in reg["action"] and len(parts) == 1:
            x = acts.get(head) or {}
            s = action_status(x)
            states.append(s)
            bits = [f"{k} {x[k]}" for k in ("ok", "refused", "failed", "waiting", "dry") if x.get(k)]
            why = f": {x.get('refused_why')}" if s == "refused" and x.get("refused_why") else ""
            ev.append(f"{head} {s}" + (f" ({', '.join(bits)})" if bits else "") + why[:120])
        elif head in reg["section"]:
            paths.append(head)
            s, detail = section_status(head, st, tally)
            if s == "seen" and len(parts) > 1 and head in st:
                if not _path_in(st.get(head), parts[1:]):
                    s = "not yet met"
                    detail = "field not in the report"
            states.append(s)
            ev.append(f"{tok} {s}" + (f" ({detail})" if detail else ""))
        elif head in reg["switch"] and len(parts) == 1:
            sv = (st.get("settings") or {}) if isinstance(st.get("settings"), dict) else {}
            if head in sv:
                ev.append(f"{head} = {json.dumps(sv[head])}")
        elif head not in FIELD_SKIP:
            fields.append(tok)
    # the line's other names (`facts`, `attacks`) looked for inside the sections
    # it names: a section there is not yet its new fields
    secs_named = [p for p in paths if p in st and not _is_error(st.get(p))]
    if secs_named:
        missing = []
        budget = [FIELD_BUDGET]
        for tok in fields:
            parts = [p for p in tok.replace("[]", "").split(".") if p]
            if not any(_path_in(st[p], parts) or _has_name(st[p], parts[0], budget) for p in secs_named):
                missing.append(tok)
        if missing:
            states.append("not yet met")
            ev.append("not in the report: " + ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else ""))
    eyes = bool(EYES.search(text))
    if not states:
        status = "needs eyes"
    elif all(s == "seen" for s in states):
        status = "seen"
    elif any(s == "seen" for s in states):
        status = "partly seen"
    else:
        status = next((s for s in ("error", "refused", "failed", "waiting") if s in states), "not met")
    if eyes and status in ("seen", "partly seen"):
        status = "needs eyes"
    return {"status": status, "evidence": ev, "eyes": eyes}


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------

def ledger(folder: Path | str, since_version: str | None = DEFAULT_SINCE, since: str | None = None,
           log_dir: Path | None = None, code_root: Path | None = None, watch: Path | None = None,
           write: bool = True, label: str | None = None, now: datetime | None = None) -> dict:
    """One DF-AI folder's ledger. since_version picks what is new (and, with
    no `since`, the date the journals are read from); `since` a date or a
    version for the journals. Returns {"label", "since", "sections",
    "actions", "switches", "watch", "counts", "errors_now", "text"} and
    writes <log_dir>/seen-ledger.md."""
    folder = Path(folder)
    log_dir = Path(log_dir) if log_dir else folder / "logs"
    code_root = Path(code_root) if code_root else (folder if (folder / "lua" / "ai-bridge.lua").is_file() else ROOT)
    watch = Path(watch) if watch else (code_root / "docs" / "watch-in-game.md")
    now = now or datetime.now()
    label = label or folder.name
    start = since_date(since or since_version)
    reg = registry(code_root)
    new = new_since(reg, since_version)
    forts = fort_dirs(log_dir, start)
    acts = read_actions(forts, start)
    tally = read_tally(forts)
    st, src, n_seasons = load_report(folder, log_dir, forts, start)
    s_err = season_errors(forts, start)
    bridge_v = st.get("bridge_version") if isinstance(st.get("bridge_version"), str) else None

    sections = []
    for v, name in new["section"]:
        status, detail = section_status(name, st, tally)
        if status == "not yet met" and bridge_v and vtuple(bridge_v) < vtuple(v):
            detail = f"the game runs bridge {bridge_v}"
        elif status == "not yet met" and st.get("tier") == "pulse" and name not in st:
            detail = "only a pulse report on disk"
        t = tally.get(name) or {}
        sections.append({"version": v, "name": name, "status": status, "detail": detail,
                         "ok": t.get("ok", 0), "errors": t.get("error", 0), "season_errors": s_err.get(name, 0),
                         "first_ok": t.get("first_ok"), "first_error": t.get("first_error"),
                         "last_error": t.get("last_error"), "error_text": t.get("error_text")})
    actions = []
    for v, name in new["action"]:
        x = acts.get(name) or {}
        actions.append({"version": v, "name": name, "status": action_status(x),
                        **{k: 0 for k in ("ok", "refused", "failed", "waiting", "dry", "proposed")}, **x})
    sv = st.get("settings") if isinstance(st.get("settings"), dict) else {}
    switches = [{"version": v, "name": n, "value": sv.get(n), "known": n in sv} for v, n in new["switch"]]
    watch_out = []
    for b in watch_blocks(watch, since_version):
        rows = [{"text": ln, **match_line(ln, reg, acts, st, tally)} for ln in b["lines"]]
        watch_out.append({"title": b["title"], "version": b["version"], "lines": rows})
    errors_now = {k: str(v.get("error"))[:200] for k, v in st.items() if _is_error(v)}

    counts = {"seen": 0, "refused": 0, "not yet met": 0, "errors": 0}
    for s in sections:
        counts["errors" if s["status"] == "error" else "seen" if s["status"] == "seen" else "not yet met"] += 1
    for a in actions:
        k = a["status"]
        counts["seen" if k == "seen" else "not yet met" if k == "not yet met" else "refused"] += 1
    wcounts = defaultdict(int)
    for b in watch_out:
        for r in b["lines"]:
            wcounts[r["status"]] += 1

    out = {"label": label, "folder": str(folder), "since_version": since_version,
           "since": start.isoformat(timespec="minutes") if start else None, "report": src,
           "bridge_version": bridge_v, "tier": st.get("tier"), "forts": [d.name for d in forts],
           "sections": sections, "actions": actions, "switches": switches, "watch": watch_out,
           "counts": counts, "watch_counts": dict(wcounts), "errors_now": errors_now,
           "season_copies": n_seasons, "time": now.isoformat(timespec="minutes")}
    out["text"] = render(out)
    if write:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            _write(log_dir / LEDGER_NAME, out["text"])
        except OSError:
            pass
    return out


def _write(path: Path, text: str) -> None:
    try:
        from dfhack import write_atomic
        write_atomic(path, text)
    except Exception:  # noqa: BLE001
        path.write_text(text, encoding="utf-8")


def _cell(x) -> str:
    return str("" if x is None else x).replace("|", "/").replace("\n", " ")


def _when(t) -> str:
    return str(t or "")[:16].replace("T", " ")


def short_status(a: dict) -> str:
    s = a["status"]
    if s == "refused" and a.get("refused_why"):
        return f"refused ({a['refused_why'][:90]})"
    if s == "failed" and a.get("failed_why"):
        return f"failed ({a['failed_why'][:90]})"
    if s == "waiting" and a.get("waiting_why"):
        return f"waiting ({a['waiting_why'][:90]})"
    if s == "not yet met" and a.get("dry"):
        return f"not yet met (dry run ok x{a['dry']})"
    if s == "not yet met" and a.get("proposed"):
        return f"not yet met (proposed x{a['proposed']} in a dry-run cycle)"
    return s


def render(L: dict) -> str:
    c = L["counts"]
    lines = [f"# Seen in game: {L['label']}", "",
             f"Since {L['since_version'] or 'the start'} (journals from {L['since'] or 'the start'}); written "
             f"{_when(L['time'])}. Forts: {', '.join(L['forts']) or 'none with a journal since'}. "
             f"Report: {L['report']}" + (f", bridge {L['bridge_version']}" if L['bridge_version'] else "")
             + (f", tier {L['tier']}" if L.get("tier") else "") + ".", "",
             f"**{c['seen']} seen, {c['refused']} refused or failed, {c['not yet met']} not yet met, "
             f"{c['errors']} section errors** (of {len(L['sections'])} sections and {len(L['actions'])} actions).",
             "Seen means the game answered: a section present in a report, an action done. How it looks "
             "and whether it worked as meant still needs eyes (docs/watch-in-game.md below).", ""]
    if L["errors_now"]:
        lines += ["## Sections in error in the last report", ""]
        lines += [f"- `{k}`: {_cell(v)}" for k, v in sorted(L["errors_now"].items())] + [""]
    lines += ["## Report sections", "", "| version | section | status | reports ok / error | season copies in error | first ok | error |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for s in L["sections"]:
        err = s.get("error_text") or (s["detail"] if s["status"] == "error" else "")
        st = s["status"] + (f" ({s['detail']})" if s["detail"] and s["status"] != "error" else "")
        lines.append(f"| {s['version']} | `{s['name']}` | {_cell(st)} | {s['ok']} / {s['errors']} | "
                     f"{s['season_errors']} | {_when(s.get('first_ok'))} | {_cell(err)[:160]} |")
    lines += ["", "## Bridge actions", "",
              "| version | action | status | done | refused | failed | first done | first refused |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for a in L["actions"]:
        lines.append(f"| {a['version']} | `{a['name']}` | {_cell(short_status(a))} | {a.get('ok', 0)} | "
                     f"{a.get('refused', 0)} | {a.get('failed', 0)} | {_when(a.get('first_ok'))} | "
                     f"{_when(a.get('first_refused'))} |")
    lines += ["", "## Rules switches", "", "| version | switch | value now |", "| --- | --- | --- |"]
    for s in L["switches"]:
        lines.append(f"| {s['version']} | `{s['name']}` | "
                     + (_cell(json.dumps(s['value'])) if s["known"] else "not in the report") + " |")
    wc = L["watch_counts"]
    lines += ["", "## docs/watch-in-game.md", "",
              "Ticked only when every name a line mentions was met; a line about how a thing looks or "
              "behaves in the game stays \"needs eyes\" whatever the journal shows. "
              + (", ".join(f"{k} {v}" for k, v in sorted(wc.items())) if wc else "No lines from the version on."), ""]
    for b in L["watch"]:
        lines += [f"### {b['title']}", ""]
        for r in b["lines"]:
            mark = "x" if r["status"] == "seen" else " "
            ev = f" [{'; '.join(r['evidence'])}]" if r["evidence"] else ""
            lines.append(f"- [{mark}] **{r['status']}**: {r['text'][:220]}{_cell(ev)[:400]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def summary(ledgers: list[dict], now: datetime | None = None) -> str:
    """One table across the folders: each new section and action's status per folder."""
    now = now or datetime.now()
    labels = [L["label"] for L in ledgers]
    lines = [f"# Seen in game: {len(ledgers)} folders", "",
             f"Since {ledgers[0]['since_version'] if ledgers else '?'}; written {now:%Y-%m-%d %H:%M}. "
             "Each folder's own page: logs/seen-ledger.md.", "",
             "| folder | seen | refused or failed | not yet met | section errors | report |",
             "| --- | --- | --- | --- | --- | --- |"]
    for L in ledgers:
        c = L["counts"]
        lines.append(f"| {L['label']} | {c['seen']} | {c['refused']} | {c['not yet met']} | {c['errors']} | "
                     f"{_cell(L['bridge_version'] or '?')} |")
    abbrev = {"seen": "seen", "refused": "refused", "failed": "failed", "waiting": "waiting",
              "not yet met": "-", "error": "ERROR"}
    for kind, key in (("Report sections", "sections"), ("Bridge actions", "actions")):
        rows: dict = {}
        for i, L in enumerate(ledgers):
            for x in L[key]:
                r = rows.setdefault((x["version"], x["name"]), [""] * len(ledgers))
                r[i] = abbrev.get(x["status"], x["status"])
        lines += ["", f"## {kind}", "", "| version | name | " + " | ".join(labels) + " | any |",
                  "| --- | --- | " + " | ".join("---" for _ in labels) + " | --- |"]
        for (v, n), r in sorted(rows.items(), key=lambda kv: (vtuple(kv[0][0]), kv[0][1])):
            anyw = "seen" if "seen" in r else ("ERROR" if "ERROR" in r else
                                               "refused" if any(x in ("refused", "failed", "waiting") for x in r) else "-")
            lines.append(f"| {v} | `{n}` | " + " | ".join(r) + f" | {anyw} |")
    never = sorted({(x["version"], x["name"]) for L in ledgers for x in L["actions"] + L["sections"]}
                   - {(x["version"], x["name"]) for L in ledgers for x in L["actions"] + L["sections"]
                      if x["status"] == "seen"}, key=lambda vn: (vtuple(vn[0]), vn[1]))
    if never:
        lines += ["", "## Not seen in any folder", "", ", ".join(f"`{n}` ({v})" for v, n in never)]
    return "\n".join(lines).rstrip() + "\n"


def health_part(L: dict, hours: float = 24.0, now: datetime | None = None) -> tuple[list[str], list[str]]:
    """The health check's "seen" part: (flags, plain lines). Flagged: a
    section in error in the last report, or one of the new sections with
    an error in the tally within the window."""
    now = now or datetime.now()
    c = L["counts"]
    wc = L.get("watch_counts") or {}
    plain = [f"seen since {L['since_version']}: {c['seen']} seen, {c['refused']} refused or failed, "
             f"{c['not yet met']} not yet met, {c['errors']} section errors (logs/{LEDGER_NAME})"]
    if wc:
        plain.append("watch-in-game lines: " + ", ".join(f"{k} {v}" for k, v in sorted(wc.items())))
    flags = []
    for k, v in sorted((L.get("errors_now") or {}).items()):
        flags.append(f"report section '{k}' returns an error: {v[:160]}")
    lo = (now.timestamp() - hours * 3600)
    for s in L["sections"]:
        if s["name"] in (L.get("errors_now") or {}) or not s.get("last_error"):
            continue
        try:
            t = datetime.fromisoformat(s["last_error"]).timestamp()
        except ValueError:
            continue
        if t >= lo:
            flags.append(f"report section '{s['name']}' ({s['version']}) returned an error {s['errors']} time(s), "
                         f"last {_when(s['last_error'])}: {str(s.get('error_text') or '')[:140]}")
    return flags, plain


# ---------------------------------------------------------------------------
# the command line
# ---------------------------------------------------------------------------

def default_folders(here: Path = ROOT) -> list[Path]:
    """DF-AI and DF-AI-<x> beside this folder (as the scorecard finds them), else this one."""
    out = [p for p in sorted(here.parent.glob("DF-AI*")) if p.is_dir() and (p / "logs").is_dir()]
    return out or [here]


def _label(p: Path) -> str:
    tail = p.name[len("DF-AI"):].lstrip("-") if p.name.startswith("DF-AI") else p.name
    return tail or "A"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--folders", nargs="+", help="DF-AI folders (default: those beside this one)")
    ap.add_argument("--since", default=None, help="a version (0.105.40) or a date (2026-11-13); default 0.105.32")
    ap.add_argument("--out", help="the summary's path with several folders")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    folders = [Path(p) for p in a.folders] if a.folders else default_folders()
    since = a.since or DEFAULT_SINCE
    since_version = since if vtuple(since) and not re.match(r"^\d{4}-", since) else DEFAULT_SINCE
    ledgers = []
    for f in folders:
        L = ledger(f, since_version=since_version, since=since, label=_label(f.resolve()))
        ledgers.append(L)
        c = L["counts"]
        print(f"{L['label']}: {c['seen']} seen, {c['refused']} refused or failed, {c['not yet met']} not yet met, "
              f"{c['errors']} section errors -> {Path(f) / 'logs' / LEDGER_NAME}")
    if len(ledgers) > 1:
        out = Path(a.out) if a.out else Path(folders[0]) / "logs" / SUMMARY_NAME
        out.parent.mkdir(parents=True, exist_ok=True)
        _write(out, summary(ledgers))
        print(f"summary -> {out}")
    elif ledgers:
        print(ledgers[0]["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
