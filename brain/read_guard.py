"""read_guard (F4): unread is not zero, stale is not fresh.

A report section that failed arrives as its empty default and a name in
`_errors` (digest.normalize). About 30 rules run without a `can_use()` gate,
so an unread `orders` read as "0 queued" and an unread `buildings` as "no
Kiln". plan() now hands every rule it calls through its `_guard` a
TrackedState: a view of the report that records which top-level sections
the rule read. After the rule, hold() drops the rule's new non-emergency
proposals when it read a section listed in `_errors` ("held: <rule> read
failed section <name>", once a cycle), or when an action that names ids or
tiles came from a section copy older than `read_cache_cap_days` (the
bridge's cache ages, perf.cache_age; a pulse cycle's merged sections aged
by digest.age_merged).

An emergency step always goes: an EMERGENCY rule, a release or a stop, a
step that makes a work safe (hold_classes.SAFE_FLAGS) and every defence step
(hold_classes.step_class).
"""

from __future__ import annotations

from planner_core import EMERGENCY, PLANNER_CONFIG

# Config (defaults here only; merged into PLANNER_CONFIG as alarm_caution does)
READ_GUARD_CONFIG = {
    "read_guard": True,          # False: the rules' reads are not tracked, nothing held
    # an action naming ids or tiles is held when a section its rule read is
    # older than this many game days (the bridge's longest SECTION_CACHE_DAYS is 7;
    # SECTION_MAX_DAYS goes to 12); 0 or None: no cap
    "read_cache_cap_days": 7.0,
}
PLANNER_CONFIG.update({k: v for k, v in READ_GUARD_CONFIG.items() if k not in PLANNER_CONFIG})

# rules that judge a failed section themselves (their step on it is deliberate):
# hospital_burrow runs on the burrow's own status when `health` failed
OWN_GUARD_RULES = frozenset({"hospital_burrow"})

# action fields that name a thing or a place in the game (a stale copy's id
# or tile may be gone, taken or built over)
ID_TILE_KEYS = frozenset({"id", "ids", "x", "y", "z", "pos", "tile", "tiles", "unit", "units",
                          "building", "buildings", "x1", "y1", "x2", "y2", "bounds", "area", "at"})


class TrackedState(dict):
    """A per-rule view of the report: reads come from a shallow copy (the
    sections are the same objects, so nested changes are shared), top-level
    writes go to both the copy and the report itself. `read` holds the keys
    the rule asked for by name (get, [], setdefault, pop); bulk reads
    (iteration, items, json) are not counted."""

    def __init__(self, base: dict | None = None):
        base = {} if base is None else base
        super().__init__(base)
        self._base = base
        self.read: set = set()

    # reads
    def __getitem__(self, k):
        self.read.add(k)
        return super().__getitem__(k)

    def get(self, k, default=None):
        self.read.add(k)
        return super().get(k, default)

    # writes (mirrored to the report)
    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self._base[k] = v

    def __delitem__(self, k):
        super().__delitem__(k)
        self._base.pop(k, None)

    def setdefault(self, k, default=None):
        self.read.add(k)
        v = super().setdefault(k, default)
        self._base.setdefault(k, v)
        return v

    def pop(self, k, *default):
        self.read.add(k)
        self._base.pop(k, None)
        return super().pop(k, *default)

    def popitem(self):
        k, v = super().popitem()
        self._base.pop(k, None)
        return k, v

    def update(self, *a, **kw):
        d = dict(*a, **kw)
        super().update(d)
        self._base.update(d)

    def clear(self):
        super().clear()
        self._base.clear()

    # copies are plain dicts (never the whole report twice, never a tracked view)
    def copy(self):
        return dict(self)

    def __copy__(self):
        return dict(self)

    def __deepcopy__(self, memo):
        import copy
        return copy.deepcopy(dict(self), memo)

    def __reduce__(self):
        return (dict, (dict(self),))


def wrap_args(s: dict, args: tuple, kw: dict, enabled: bool = True):
    """(view, args, kw) with every argument that is the report itself swapped
    for one new TrackedState; view is None when the report isn't passed."""
    if not enabled or not any(a is s for a in args) and not any(v is s for v in kw.values()):
        return None, args, kw
    view = TrackedState(s)
    return (view, tuple(view if a is s else a for a in args),
            {k: (view if v is s else v) for k, v in kw.items()})


def is_emergency(p) -> bool:
    """A step never held for an unread or stale section."""
    rule = getattr(p, "rule", None)
    a = getattr(p, "action", None)
    a = a if isinstance(a, dict) else {}
    if rule in EMERGENCY or a.get("release") or a.get("stop"):
        return True
    try:
        import hold_classes as hc
        if any(a.get(k) for k in hc.SAFE_FLAGS):
            return True
        return hc.step_class(p) == hc.DEFENCE
    except Exception:  # noqa: BLE001  (never hold by mistake)
        return True


def names_ids_or_tiles(p) -> bool:
    a = getattr(p, "action", None)
    if not isinstance(a, dict):
        return False
    for k, v in a.items():
        if v is None or v is False:
            continue
        if k in ID_TILE_KEYS or k.endswith("_id") or k.endswith("_ids"):
            return True
    return False


def _filtered(p) -> tuple:
    """The failed sections planner_guards.unknown_filter already holds this
    proposal for (with its own note, after every rule): left to it."""
    try:
        from planner_guards import _needs
        return tuple(_needs(p))
    except Exception:  # noqa: BLE001
        return ()


def _age(s: dict, name: str):
    try:
        import perf
        return perf.section_age(s, name)
    except Exception:  # noqa: BLE001
        return None


def hold(s: dict, read: set, proposals: list, before: set, cfg: dict, rule_name: str,
         notes: list, said: set) -> list:
    """The proposals list with the rule's new non-emergency proposals taken
    out when it read a failed section, or a section older than the cap for an
    action that names ids or tiles. `before`: id() of the proposals there
    before the rule ran. Each hold is said once a cycle (`said`)."""
    errors = s.get("_errors") if isinstance(s.get("_errors"), dict) else {}
    # a LISTED_ONLY section stays {"error": ...} (the rules read it through their
    # own guards): only a section swapped for its empty default reads as zero
    from digest import LISTED_ONLY
    failed = sorted(k for k in read if isinstance(k, str) and k in errors and k not in LISTED_ONLY)
    cap = cfg.get("read_cache_cap_days", READ_GUARD_CONFIG["read_cache_cap_days"]) if isinstance(cfg, dict) else None
    stale = []
    if cap:
        for k in sorted(x for x in read if isinstance(x, str) and not x.startswith("_")):
            age = _age(s, k)
            if age is not None and age > cap:
                stale.append((k, age))
    if not failed and not stale:
        return proposals
    new = [p for p in proposals if id(p) not in before]
    if not new:
        return proposals
    drop = []
    for p in new:
        rule = getattr(p, "rule", None) or rule_name
        if is_emergency(p) or rule in OWN_GUARD_RULES:
            continue
        mine = [k for k in failed if k not in _filtered(p)]
        if mine:
            drop.append(p)
            msg = f"held: {rule} read failed section {mine[0]}"
        elif stale and names_ids_or_tiles(p):
            drop.append(p)
            k, age = stale[0]
            msg = (f"held: {rule} read section {k} {age:g} game days old (past read_cache_cap_days {cap:g}) "
                   "for an action naming ids or tiles")
        else:
            continue
        if msg not in said:
            said.add(msg)
            notes.append(msg)
    if not drop:
        return proposals
    gone = {id(p) for p in drop}
    proposals[:] = [p for p in proposals if id(p) not in gone]
    return proposals


def call(fn, args: tuple, kw: dict, s: dict, proposals: list, notes: list, cfg: dict, said: set):
    """plan()'s _guard: the rule run on a TrackedState of the report; a rule
    that raises is a note ("rule <fn> failed ...; the others ran") and the
    others run; then hold() on what it read. `said`: plan's once-a-cycle set."""
    on = cfg.get("read_guard", True) if isinstance(cfg, dict) else True
    view, args, kw = wrap_args(s, args, kw, on)
    before = {id(p) for p in proposals} if view is not None else None
    try:
        return fn(*args, **kw)
    except Exception as e:  # noqa: BLE001
        notes.append(f"rule {fn.__name__} failed ({type(e).__name__}: {str(e)[:120]}); the others ran")
        return None
    finally:
        if view is not None:
            try:
                hold(s, view.read, proposals, before, cfg, getattr(fn, "__name__", "rule"), notes, said)
            except Exception as e:  # noqa: BLE001
                notes.append(f"rule read_guard failed ({type(e).__name__}: {str(e)[:120]}); nothing held")


def fresh(s: dict, sections, max_age, said: set, notes: list) -> bool:
    """can_use(max_age=): False when a section's copy is older than max_age
    game days (perf.cache_age), said once a cycle."""
    old = too_old(s, sections, max_age)
    new = [(x, a) for x, a in old if ("age", x, max_age) not in said]
    if new:
        said.update(("age", x, max_age) for x, _ in new)
        notes.append("skipped rules that need report section(s) "
                     + ", ".join(f"{x} ({a:g} days old)" for x, a in new) + f" under {max_age:g} days old")
    return not old


def too_old(s: dict, sections, max_age) -> list:
    """(F4) can_use(max_age=): the sections whose copy is older than max_age
    game days, as (name, age)."""
    if max_age is None:
        return []
    out = []
    for x in sections:
        age = _age(s, x)
        if age is not None and age > max_age:
            out.append((x, age))
    return out
