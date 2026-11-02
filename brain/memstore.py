"""Where the overseer's memory is kept: five kinds, each stored its own way.

    memory, bank = memstore.load(key, bridge)      # the save first, then logs/
    memstore.save(key, memory, bank, bridge)       # only the kinds that changed

The kinds (the sixth, raw observations, is the snapshots and bridge.log in
logs/, kept for debugging only and never read back as memory):

  working    cooldowns, counters, pending questions and events, the token bank
  timeline   one row of numbers a day, rolled up into seasons and years (timeline.py)
  atlas      the site survey, the master plan's home, the registry of what the AI
             built, entrances and their gate history, located events (atlas.py)
  chronicle  the fort's story, and the culture history beside it (chronicle.py)
  knowledge  what the AI learned: your preferences and lessons, the self-tuned
             targets, the outcome log (learning.py, calibrate.py, outcomes.py)

Storage rules:
  - In the save, one key per kind (ai-overseer/mem/<kind>), each holding the
    kind as JSON text with a schema version. Text passes through Lua untouched,
    so an empty {} no longer comes back as [] (the old repairs are still there,
    for old saves).
  - Each kind is written only when its text changed since it was read.
  - Old saves and the old logs/overseer-memory.json are read once and migrated.
  - In logs/, one folder per fort (logs/forts/<fort>/): memory.json (every kind),
    timeline.csv (two years of days), seasons.csv (every season), and the
    journal of decisions, rotated by size.
  - Each kind has a size budget (BUDGETS), checked by tests/test_memory.py.
  - The save stays the source of truth for the fort that's loaded: reloading
    an older save brings back what the AI knew then.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import fields
from datetime import datetime
from pathlib import Path

from bridge import LOG_DIR, BridgeError
from dfhack import DFHackError
from planner import Memory
from tokens import TokenBank

KINDS = ("working", "timeline", "atlas", "chronicle", "knowledge")
SCHEMA = {"working": 1, "timeline": 1, "atlas": 1, "chronicle": 1, "knowledge": 1}
# which of the Memory's fields live in which kind (everything else is working state)
KIND_FIELDS = {
    "timeline": ("timeline",),
    "atlas": ("atlas",),
    "chronicle": ("culture", "chronicle"),
    "knowledge": ("learning", "calibration", "outcomes"),
}
# bytes of text per kind, at most (a test plays a long fort against these)
# (the atlas is the biggest: up to 400 things the AI built, a year of located
# events and 80 clusters come to about 80 KB, small beside the save itself)
# (the chronicle at its cap, 300 entries of up to 140 characters, plus the
# culture history, stays under 64 KB)
BUDGETS = {"working": 32_000, "timeline": 40_000, "atlas": 96_000, "chronicle": 64_000, "knowledge": 40_000}
# Upgrades from one schema version to the next: kind -> {old version: fn(data) -> data}.
# Version 1 is the first; add a step here whenever a kind's shape changes.
MIGRATIONS: dict[str, dict] = {k: {} for k in KINDS}

FORTS_DIR = LOG_DIR / "forts"
LEGACY_FILE = LOG_DIR / "overseer-memory.json"     # all forts in one file, before 0.31
JOURNAL_MAX_BYTES = 2_000_000
JOURNAL_KEEP = 10                # (0.100.1) ~22 MB: a night of a growing fort stays whole for review
TIMELINE_LOG_DAYS = 20 * 336       # (0.100.1) twenty years of days (~1 MB)


def _field_kind() -> dict:
    out = {}
    for k, names in KIND_FIELDS.items():
        for n in names:
            out[n] = k
    return out


FIELD_KIND = _field_kind()
MEMORY_FIELDS = [f.name for f in fields(Memory)]


# --- encoding -------------------------------------------------------------------

def split(memory: Memory, bank: TokenBank) -> dict:
    """The memory as {kind: data}."""
    d = memory.to_dict()
    out = {k: {} for k in KINDS}
    for name, value in d.items():
        out[FIELD_KIND.get(name, "working")][name] = value
    out["working"]["bank"] = bank.to_dict()
    # fields a newer version of the brain wrote: kept, not dropped
    for kind, extra in (getattr(memory, "_unknown", None) or {}).items():
        for name, value in extra.items():
            out.setdefault(kind, {}).setdefault(name, value)
    return out


def encode(kind: str, data: dict, fort: str) -> str:
    """One kind as text: sorted keys and ASCII, so the same memory always gives
    the same text (that's how 'changed' is decided) and nothing is lost in Lua."""
    return json.dumps({"v": SCHEMA[kind], "kind": kind, "fort": fort, "data": data},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def decode(kind: str, text) -> dict | None:
    """Text back to data, upgraded to the current schema. None if unreadable."""
    data, status = decode_status(kind, text)
    return data if status in ("ok", "newer") else None


def decode_status(kind: str, text) -> tuple[dict | None, str]:
    """(data, status): "ok"; "newer" (written by a newer brain: readable, but
    this brain must not write it back as its own older version); "bad"."""
    try:
        obj = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None, "bad"
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), dict):
        return None, "bad"
    v = obj.get("v") if isinstance(obj.get("v"), int) else 1
    data = obj["data"]
    if v > SCHEMA[kind]:
        return data, "newer"
    while v < SCHEMA[kind]:
        step = MIGRATIONS[kind].get(v)
        if step is None:
            return None, "bad"            # no way up from this version: don't guess
        data = step(data)
        v += 1
    return data, "ok"


def join(datas: dict) -> tuple[Memory, TokenBank]:
    """{kind: data} back into a Memory and a TokenBank."""
    flat, unknown = {}, {}
    bank = {}
    for kind, data in datas.items():
        if not isinstance(data, dict):
            continue
        for name, value in data.items():
            if kind == "working" and name == "bank":
                bank = value if isinstance(value, dict) else {}
            elif name in MEMORY_FIELDS:
                flat[name] = value
            else:
                unknown.setdefault(kind, {})[name] = value
    m = Memory.from_dict(flat)
    m._unknown = unknown
    return m, TokenBank.from_dict(bank)


def texts_of(memory: Memory, bank: TokenBank, fort: str) -> dict:
    return {k: encode(k, v, fort) for k, v in split(memory, bank).items()}


def sizes(memory: Memory, bank: TokenBank, fort: str = "") -> dict:
    return {k: len(t) for k, t in texts_of(memory, bank, fort).items()}


def over_budget(memory: Memory, bank: TokenBank, fort: str = "") -> dict:
    return {k: n for k, n in sizes(memory, bank, fort).items() if n > BUDGETS[k]}


# --- loading ------------------------------------------------------------------------

ALIASES: dict[str, str] = {}          # fort key -> its logs folder, when the save was copied under a new name


TEST_SAVE_PREFIXES = ("ai run", "ai test")


def _remember_session(path: Path, wk: str, folder: str) -> None:
    """The folder of the named save last loaded for a world and site, for its
    autosaves (logs/forts/session.json). Never raises."""
    try:
        d = _read_json(path)
        if d.get(wk) == folder:
            return
        d[wk] = folder
        FORTS_DIR.mkdir(parents=True, exist_ok=True)
        from dfhack import write_atomic
        write_atomic(path, json.dumps(d, indent=1))
    except OSError:
        pass


def note_world(key: str, world: str | None) -> str | None:
    """The same fort loaded from a save copied under another folder name
    (region2 for AI Test Run 2) keeps its logs in one folder: the first
    folder used for that world and site is remembered in logs/forts/index.json.
    Returns the folder used, or None."""
    save_dir, _, site = key.rpartition("#")
    if not world or not site:
        return None
    if "@" in save_dir:
        # (0.105.0) a scenario copy marked with a run id: its own folder, always
        # (its autosaves carry the mark too), never the real fort's
        ALIASES.pop(key, None)
        return fort_dir(key).name
    index_path = FORTS_DIR / "index.json"
    index = _read_json(index_path)
    wk = f"{world}#{site}"
    session_path = FORTS_DIR / "session.json"
    if save_dir.lower().startswith(TEST_SAVE_PREFIXES):
        # (0.100.2) a test or scenario copy ("AI Run ...", "AI Test ...") keeps
        # its own folder: the second overnight run's logs went into the first
        # copy's folder, its timeline was cut back as if a save had been
        # reloaded, and its seasonal snapshots were skipped as already there
        ALIASES.pop(key, None)
        _remember_session(session_path, wk, fort_dir(key).name)
        return fort_dir(key).name
    if save_dir.lower().startswith("autosave"):
        # (0.100.2) DF's autosave of the save loaded last for this world and
        # site (a test copy's autosave stays with the test copy)
        sess = _read_json(session_path).get(wk)
        if isinstance(sess, str) and (FORTS_DIR / sess).is_dir():
            ALIASES[key] = sess
            return sess
        # (0.97.1, B5) an autosave goes to its own world's folder for that
        # site, never to whichever folder with that site id was used last
        # (another world's fort could have the same site id)
        folder = index.get(wk)
        if isinstance(folder, str) and (FORTS_DIR / folder).is_dir():
            ALIASES[key] = folder
            return folder
        ALIASES.pop(key, None)                 # (another world's mapping from earlier)
        return None
    default = fort_dir(key).name
    folder = index.get(wk)
    if isinstance(folder, str) and folder.lower().replace("_", " ").startswith(TEST_SAVE_PREFIXES):
        folder = None                          # (0.100.2) an old mapping to a test copy's folder: the fort's own instead
    _remember_session(session_path, wk, folder if isinstance(folder, str) and (FORTS_DIR / folder).is_dir()
                      else default)
    if not isinstance(folder, str) or not (FORTS_DIR / folder).is_dir():
        index[wk] = default
        try:
            FORTS_DIR.mkdir(parents=True, exist_ok=True)
            from dfhack import write_atomic
            write_atomic(index_path, json.dumps(index, indent=1))   # (0.100) whole or not at all
        except OSError:
            pass
        return default
    if folder != default:
        ALIASES[key] = folder
    return folder


def fort_dir(key: str) -> Path:
    """logs/forts/<save folder>-<site id>/. DF's autosaves load as "autosave 1",
    "autosave 2"... in turn: those go to the fort's own folder (the newest
    folder with the same site id that isn't an autosave), so one fort's logs
    stay in one place over a long run."""
    if key in ALIASES:
        return FORTS_DIR / ALIASES[key]
    save_dir, _, site = key.rpartition("#")
    run = ""
    if "@" in save_dir:
        # (0.105.0) a marked scenario copy: "run-<id>-<site>", whatever the save
        # folder (an autosave of it included)
        save_dir, _, run = save_dir.rpartition("@")
        run = re.sub(r"[^A-Za-z0-9_-]+", "_", run).strip("_")
    if run:
        return FORTS_DIR / f"run-{run}-{site}"
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", save_dir or key).strip("_") or "fort"
    if site and slug.lower().startswith("autosave"):
        try:
            own = [d for d in FORTS_DIR.glob(f"*-{site}") if d.is_dir()
                   and not d.name.lower().startswith("autosave")]
            if own:
                return max(own, key=lambda d: d.stat().st_mtime)
        except OSError:
            pass
    return FORTS_DIR / (f"{slug}-{site}" if site else slug)


def _read_json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _from_legacy(entry: dict) -> tuple[Memory, TokenBank]:
    """The memory as one blob (before 0.31): {"memory": {...}, "bank": {...}},
    or older still, the memory's fields alone."""
    if "memory" not in entry and "bank" not in entry:
        entry = {"memory": entry}
    mem = entry.get("memory") if isinstance(entry.get("memory"), dict) else {}
    bank = entry.get("bank") if isinstance(entry.get("bank"), dict) else {}
    m = Memory.from_dict(mem)
    m._unknown = {}
    return m, TokenBank.from_dict(bank)


def _from_texts(texts: dict, fallback: dict | None = None) -> tuple[Memory, TokenBank, set]:
    """Join the kinds back up. A kind that can't be read is taken from the
    fallback texts (the copy in logs/) when that one reads; otherwise it starts
    empty and is FROZEN: never written over, so nothing unreadable is lost to
    defaults. A kind from a newer brain is used but frozen too."""
    datas, frozen = {}, set()
    for k in KINDS:
        if k not in texts:
            continue
        d, status = decode_status(k, texts[k])
        if status == "bad" and fallback and k in fallback:
            d2, st2 = decode_status(k, fallback[k])
            if st2 == "ok":
                d, status = d2, "fallback"
        if status == "bad":
            frozen.add(k)
            continue
        if status == "newer":
            frozen.add(k)
        datas[k] = d
    m, bank = join(datas)
    return m, bank, frozen


def same_site(a: str | None, b: str | None) -> bool:
    """Two fort keys ("<save folder>#<site id>") for the same fort: the save's
    own data belongs to whatever folder the save was loaded from (an autosave,
    a copied or renamed folder), so the site id is what counts there."""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    sa, sb = a.rpartition("#")[2], b.rpartition("#")[2]
    return a == b or (bool(sa) and sa == sb)


def load(key: str, bridge=None, prefer_logs: bool = False) -> tuple[Memory, TokenBank]:
    """The memory stored in the loaded save comes first: it matches the game
    exactly, even after reloading an older save. The copy in logs/ is the
    fallback (first run, a save made before this existed, a kind the save lacks
    or can't be read). prefer_logs: a dry run, which never writes into the
    save, carries on from its own copy in logs/ when there is one.

    If the save couldn't be read at all, nothing is written into it this
    cycle (memory._texts["save_unread"]): an unreadable answer is not an empty save."""
    save_texts, legacy, source, unread = {}, None, "new", False
    why = None
    if bridge is not None and hasattr(bridge, "load_memory"):
        try:
            data = bridge.load_memory()
        except (BridgeError, DFHackError, OSError, ValueError) as e:
            data, unread = None, True
            why = f"{type(e).__name__}: {str(e)[:200]}"   # (0.104.43) said in the log
        if isinstance(data, dict):
            kinds = data.get("kinds") if isinstance(data.get("kinds"), dict) else {}
            for k, v in kinds.items():
                if k in KINDS and isinstance(v, dict) and same_site(v.get("fort"), key) \
                        and isinstance(v.get("text"), str):
                    save_texts[k] = v["text"]
            old = data.get("legacy") if isinstance(data.get("legacy"), dict) else None
            if old is None and data.get("fort") and ("memory" in data or "bank" in data):
                old = data                    # a bridge from before 0.31
            if isinstance(old, dict) and same_site(old.get("fort"), key):
                legacy = old
        elif data is not None:
            unread = True
            why = f"the answer was a {type(data).__name__}, not a table"
    log_file = _read_json(fort_dir(key) / "memory.json")
    log_texts = log_file.get("kinds") if log_file.get("fort") == key and isinstance(log_file.get("kinds"), dict) else {}
    log_texts = {k: v for k, v in log_texts.items() if k in KINDS and isinstance(v, str)}

    frozen: set = set()
    if prefer_logs and log_texts:
        m, bank, frozen = _from_texts(log_texts)
        source = "logs (dry run)"
    elif save_texts:
        texts = dict(save_texts)
        for k in KINDS:                       # a kind the save lacks (a write that failed)
            if k not in texts and k in log_texts:
                texts[k] = log_texts[k]
        m, bank, frozen = _from_texts(texts, log_texts)
        source = "save"
    elif legacy is not None:
        m, bank = _from_legacy(legacy)
        source = "save (migrated)"
    elif log_texts:
        m, bank, frozen = _from_texts(log_texts)
        source = "logs"
    else:
        entry = _read_json(LEGACY_FILE).get(key)
        if isinstance(entry, dict):
            m, bank = _from_legacy(entry)
            source = "logs (migrated)"
        else:
            m, bank = Memory(), TokenBank()
    m._texts = {"save": save_texts, "logs": log_texts, "legacy_in_save": legacy is not None,
                "source": source, "frozen": frozen, "save_unread": unread, "save_unread_why": why,
                # what each frozen kind holds, kept as it is
                "frozen_text": {k: save_texts.get(k, log_texts.get(k)) for k in frozen}}
    return m, bank


def _older_bridge(bridge) -> bool:
    """A bridge from before 0.31 keeps the memory as one piece (it would store
    the per-kind payload whole, where a 0.31 brain can't read it back)."""
    v = getattr(bridge, "version", None)
    bv = v.get("bridge_version") if isinstance(v, dict) else None
    if not isinstance(bv, str):
        return False
    try:
        return tuple(int(x) for x in bv.split(".")[:3]) < (0, 31, 0)
    except ValueError:
        return False


# --- saving ------------------------------------------------------------------------

def save(key: str, memory: Memory, bank: TokenBank, bridge=None, limit: int | None = None) -> dict:
    """Write the kinds that changed: into the save when a bridge is given,
    and always to logs/. Returns {"save": [kinds], "logs": [kinds]}.
    Frozen kinds (unreadable, or from a newer brain) are never written over."""
    texts = texts_of(memory, bank, key)
    known = getattr(memory, "_texts", None) or {}
    frozen = set(known.get("frozen") or ())
    out = {"save": [], "logs": []}
    if bridge is not None and hasattr(bridge, "save_memory") and not known.get("save_unread"):
        if _older_bridge(bridge):
            try:          # the one-piece memory, as that bridge expects
                if bridge.save_memory({"fort": key, "memory": memory.to_dict(), "bank": bank.to_dict()}):
                    out["save"] = ["legacy"]
            except (BridgeError, DFHackError, OSError):
                pass
        else:
            had = known.get("save") or {}
            changed = {k: t for k, t in texts.items() if had.get(k) != t and k not in frozen}
            if limit and len(changed) > limit:
                # a few kinds a call, the smallest first: each write freezes the
                # game while DFHack encodes it (Oct 23: all five took 1-3 s)
                # (0.104.0) the kind written longest ago first, then the smallest: a
                # kind that changes every cycle (working) could otherwise keep the
                # larger ones out of the save for good, and the throttle with them
                order = known.get("save_order") or {}
                keep = sorted(changed, key=lambda k: (order.get(k, -1), len(changed[k])))[:limit]
                out["save_left"] = len(changed) - len(keep)
                changed = {k: changed[k] for k in keep}
            if changed or known.get("legacy_in_save"):
                payload = {"fort": key, "kinds": changed}
                # the old one-piece copy goes once every kind is safely in its own key
                if known.get("legacy_in_save") and set(had) | set(changed) >= set(KINDS):
                    payload["drop_legacy"] = True
                try:
                    if (changed or payload.get("drop_legacy")) and bridge.save_memory(payload):
                        out["save"] = sorted(changed)
                        known.setdefault("save", {}).update(changed)
                        seq = known.setdefault("save_order", {})
                        top = max(seq.values(), default=0)
                        for i, k in enumerate(sorted(changed)):
                            seq[k] = top + 1 + i
                        if payload.get("drop_legacy"):
                            known["legacy_in_save"] = False
                except (BridgeError, DFHackError, OSError):
                    pass
    for k in frozen:                          # what can't be read stays exactly as it was
        if (known.get("frozen_text") or {}).get(k):
            texts[k] = known["frozen_text"][k]
    had_logs = known.get("logs") or {}
    changed_logs = [k for k, t in texts.items() if had_logs.get(k) != t]
    if changed_logs:
        d = fort_dir(key)
        d.mkdir(parents=True, exist_ok=True)
        try:
            # (0.100) a name per process (two overseers shared "memory.json.tmp"),
            # and a full or locked disk is said, not raised out of the cycle's
            # cleanup (where it hid the real error and failed every cycle)
            from dfhack import write_atomic
            write_atomic(d / "memory.json", json.dumps({"fort": key, "saved": datetime.now().isoformat(timespec="seconds"),
                                                        "kinds": texts}, indent=0))
        except OSError as e:
            out["error"] = f"couldn't write {d / 'memory.json'}: {e}"
            memory._texts = known
            return out
        known.setdefault("logs", {}).update({k: texts[k] for k in changed_logs})
        out["logs"] = sorted(changed_logs)
    memory._texts = known
    return out


def read_logged(key: str) -> dict:
    """The copy in logs/ as {"memory": {...}, "bank": {...}} (for tests and tools)."""
    f = _read_json(fort_dir(key) / "memory.json")
    if f.get("fort") != key:
        return {}
    m, bank, _ = _from_texts(f.get("kinds") or {})
    return {"memory": m.to_dict(), "bank": bank.to_dict()}


# --- finding it again -----------------------------------------------------------------

def brief(memory) -> list[str]:
    """What the fort's memory adds to a review, in a few short lines (trends,
    notable places, the latest of the story): a few dozen tokens."""
    import atlas
    import chronicle
    import masterplan
    import phases
    import timeline
    out = [f"phase: {phases.line(memory)}"]
    plan = masterplan.brief(memory)
    if plan:
        out.append("plan: " + plan)
    tl = timeline.trend_lines(memory, 4)
    if tl:
        out.append("trends this season: " + "; ".join(tl))
    places = atlas.notable(memory, 2)
    if places:
        out.append("notable places: " + "; ".join(places))
    story = chronicle.lines(memory, 2, kinds=chronicle.MAJOR)
    if story:
        out.append("lately: " + "; ".join(story))
    return out


# --- the long copies in logs/ --------------------------------------------------------

def journal_path(key: str | None) -> Path:
    return (fort_dir(key) if key else LOG_DIR) / ("journal.jsonl" if key else "decisions.jsonl")


def cap_file(path: Path, max_bytes: int) -> None:
    """A log that only grows (soak.jsonl, overseer-errors.log): past max_bytes
    it becomes <name>.old<suffix> (one old copy, the one before dropped), so a
    fort run for decades never fills the disk. Never raises."""
    try:
        if path.exists() and path.stat().st_size > max_bytes:
            path.replace(path.with_name(f"{path.stem}.old{path.suffix}"))
    except OSError:
        pass


def keep_newest(folder: Path, pattern: str, keep: int) -> None:
    """Only the newest `keep` files matching `pattern` stay. Never raises."""
    try:
        files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime)
        for old in files[:-keep] if keep > 0 else files:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def append_journal(path: Path, entry: dict) -> None:
    """One line; the file is rotated when it passes JOURNAL_MAX_BYTES
    (journal.jsonl -> journal.1.jsonl -> ... -> journal.3.jsonl, the oldest dropped)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size > JOURNAL_MAX_BYTES:
            for i in range(JOURNAL_KEEP, 0, -1):
                older = path.with_name(f"{path.stem}.{i}{path.suffix}")
                newer = path if i == 1 else path.with_name(f"{path.stem}.{i - 1}{path.suffix}")
                if i == JOURNAL_KEEP:
                    older.unlink(missing_ok=True)
                if newer.exists():
                    newer.replace(older)
    except OSError:
        pass
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass                                  # (0.100.1) a locked journal never ends the cycle


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    try:
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
    except OSError:
        return [], []
    return (rows[0], rows[1:]) if rows else ([], [])


def _write_csv(path: Path, head: list[str], rows: list[list]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)
    tmp.replace(path)


def log_day(key: str, row: dict, field_names: list[str]) -> None:
    """A finished day into logs/forts/<fort>/timeline.csv. Days after it (from a
    later save that was dropped by reloading) are removed; days older than two
    years leave this file (their seasons are in seasons.csv)."""
    path = fort_dir(key) / "timeline.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    head, rows = _read_csv(path)
    if head != field_names:
        rows = []
    day = row.get("day")
    rewound = [r for r in rows if r and r[0].lstrip("-").isdigit() and int(r[0]) >= day]
    kept = [r for r in rows if r and r[0].lstrip("-").isdigit() and day - TIMELINE_LOG_DAYS < int(r[0]) < day]
    line = ["" if row.get(f) is None else row.get(f) for f in field_names]
    if head == field_names and not rewound and len(kept) == len(rows):
        with path.open("a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(line)
    else:
        _write_csv(path, field_names, kept + [line])


SEASON_FIELDS = ["season", "name", "days", "deaths", "threat_days", "avg_pop", "high_pop", "avg_drink_pd",
                 "low_drink_pd", "avg_meals_pd", "low_meals_pd", "avg_unhappy_pct", "high_unhappy_pct",
                 "avg_idle_pct", "avg_wealth"]


def log_seasons(key: str, seasons: list[dict], season_name) -> None:
    """Every finished season into logs/forts/<fort>/seasons.csv (kept for ever).
    The memory's seasons are the truth: rows for the same season are replaced,
    and seasons after the newest one it has (a future dropped by reloading an
    older save) are removed."""
    path = fort_dir(key) / "seasons.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    mine = [x for x in seasons if isinstance(x, dict) and isinstance(x.get("season"), int)]
    if not mine:
        return
    head, rows = _read_csv(path)
    if head != SEASON_FIELDS:
        rows = []
    newest = max(x["season"] for x in mine)
    by_season = {int(r[0]): r for r in rows if r and r[0].lstrip("-").isdigit() and int(r[0]) <= newest}
    for x in mine:
        a, lo, hi = x.get("avg") or {}, x.get("low") or {}, x.get("high") or {}
        by_season[x["season"]] = ["" if v is None else v for v in (
            x["season"], season_name(x["season"]), x.get("n"), x.get("deaths"), x.get("threat_days"),
            a.get("pop"), hi.get("pop"), a.get("drink_pd"), lo.get("drink_pd"), a.get("meals_pd"),
            lo.get("meals_pd"), a.get("unhappy_pct"), hi.get("unhappy_pct"), a.get("idle_pct"), a.get("wealth"))]
    new = [by_season[k] for k in sorted(by_season)]
    if [[str(v) for v in r] for r in new] != rows:
        _write_csv(path, SEASON_FIELDS, new)
