"""(layout option B) The master plan's district-and-floor table.

The master plan (masterplan.py) gives each kind of level a district: a band
of elevations and directions from the main stair. From option B a new level
goes onto a *floor*: a z-level with a 3-wide main hall running out from the
stair, the level's rooms in slots along it. This module says, for every kind
of level, which floor of its district it belongs on (its role) and where
along the hall (its zone); which floors are offered to a level, in order;
and the `floor` hint a start_project carries (planner_floors.floor_action
puts it on the action at send time; lua/ai-builder-floors.lua follows it).

    masterplan_floors.role_of(kind, action)                 -> (district, role, zone) | None
    masterplan_floors.ensure(memory, traits, profile)       -> chronicle lines (the table made or redone)
    masterplan_floors.elevs_for(memory, kind, action, traits, floors, cfg) -> the floors offered, in order
    masterplan_floors.hint(memory, action, s, traits, cfg)  -> dict | False (classic on purpose) | None
    masterplan_floors.note_result(memory, action, result)   -> a chronicle line | None
    masterplan_floors.lines(memory, floors)                 -> the floors in words

Pure: reads memory (and the report's `floors` section when given), never the
bridge. The table lives in memory.atlas["plan"]["floors"]:

    {"v": 1, "vertical": "deep",
     "roles": {"sleeping": {"district": "homes", "elevs": [10, 9, 11], "band": [9, 11]}, ...},
     "placed": {"<project id>": {"floor": 3, "role": "sleeping", "elevation": 10}}}

The hint's grammar numbers (gap, run_max, arms_max, ...) are
floor_grammar.grammar's; when that module is missing or fails the hint
carries none and the builder's defaults stand.
"""

from __future__ import annotations

import re

import masterplan
from masterplan import DIRS, _district_of_kind, _peek, _plain

FLOORS_V = 1
PLACED_MAX = 80              # plan["floors"]["placed"] keeps the newest
ELEVS_MAX = 4                # floors offered for one level (PLANNER_CONFIG floor_elevs_max)
ELEVS_CAP = 6                # the bridge's parse_floor takes 1-6
ELEV_MIN, ELEV_MAX = -400, 400
XY_MAX = 999

# the district tags both sides use (lua/ai-builder-floors.lua FLOOR_TAGS)
TAGS = ("homes", "halls", "storage", "industry", "defence")
ZONES = ("near", "mid", "far", "any")

# kind -> (district, role, zone): the floor of its district a level belongs
# on and where along that floor's main hall. Workshops: the role by the first
# shop's group (ROLE_OF_GROUP); this row is the crafts'.
FLOOR_OF: dict[str, tuple[str, str, str]] = {
    "dining": ("homes", "common", "near"),
    "suites": ("homes", "common", "near"),
    "tavern": ("homes", "common", "mid"),
    "hospital": ("homes", "common", "far"),
    "bedrooms": ("homes", "sleeping", "any"),
    "temple": ("halls", "worship", "far"),
    "memorial": ("halls", "worship", "far"),
    "library": ("halls", "worship", "mid"),
    "garden": ("halls", "worship", "mid"),
    "tombs": ("halls", "crypt", "far"),
    "storage": ("storage", "stores", "near"),
    "workshops": ("industry", "crafts", "mid"),
    "barracks": ("defence", "guard", "near"),
    "archery": ("defence", "guard", "far"),
    "jail": ("defence", "guard", "far"),
}
# kinds that never go on a floor (and any kind not in FLOOR_OF)
CLASSIC_KINDS = frozenset({"farms", "landmark", "well", "way_in", "cistern"})
# a workshops level's role, by its first shop's group (planner_shopslots.WORKSHOP_GROUPS)
ROLE_OF_GROUP = {"crafts": "crafts", "cloth": "crafts", "soap": "crafts", "smithing": "forges", "food": "kitchens"}
# the order of the roles inside a district (role i gets the district's levels turned i places)
ROLES = {
    "homes": ("common", "sleeping"),
    "halls": ("worship", "crypt"),
    "industry": ("crafts", "forges", "kitchens"),
    "storage": ("stores",),
    "defence": ("guard",),
}
DEFENCE_FALLBACK = "halls"   # a plan without a defence district: the guard's floors among the halls
# customs that keep a level by the fields: placed the classic way
CLASSIC_CUSTOMS = ("field_hall", "field_kitchens")
QUIRK_RULES = ("narrow_ways", "great_shaft", "symmetric")
WORDS = {"homes": "the homes", "halls": "the halls", "storage": "the stores", "industry": "the workshops",
         "defence": "the guard"}


def _whole(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _group(action: dict | None) -> str | None:
    """A workshops action's industry group: its first shop's."""
    shops = _l(_d(action).get("shops"))
    if not shops or not isinstance(shops[0], str):
        return None
    try:
        from planner_shopslots import WORKSHOP_GROUPS
    except Exception:  # noqa: BLE001
        return None
    g = WORKSHOP_GROUPS.get(shops[0])
    return g if isinstance(g, str) else None


def role_of(kind: str, action: dict | None = None) -> tuple[str, str, str] | None:
    """(district, role, zone) for a level of this kind; None for a kind that
    never goes on a floor. action: a workshops level's shops choose its role
    (the first shop's group; unknown: crafts)."""
    if not isinstance(kind, str) or kind in CLASSIC_KINDS:
        return None
    row = FLOOR_OF.get(kind)
    if row is None:
        return None
    if kind == "workshops":
        return (row[0], ROLE_OF_GROUP.get(_group(action) or "", row[1]), row[2])
    return row


# --- the table: from role to elevations ------------------------------------------------

def _band(d: dict | None) -> tuple[int, int, int] | None:
    """A district's (lo, hi, target), or None when it has no sound band."""
    if not isinstance(d, dict) or not _whole(d.get("lo")) or not _whole(d.get("hi")) or d["lo"] > d["hi"]:
        return None
    lo, hi = d["lo"], d["hi"]
    tg = d.get("target") if _whole(d.get("target")) else (lo + hi + 1) // 2
    return lo, hi, max(lo, min(hi, tg))


def _levels(lo: int, hi: int, target: int) -> list[int]:
    """The band's elevations, the nearest the target first (ties: the higher first)."""
    lo, hi = max(lo, ELEV_MIN), min(hi, ELEV_MAX)
    return sorted(range(lo, hi + 1), key=lambda e: (abs(e - target), -e))


def _roles_table(plan: dict) -> dict:
    """The pure half of ensure: {role: {district, elevs, band}} from the plan's
    districts as they are now. Changes nothing."""
    by_kind = {}
    for d in _l(plan.get("districts")):
        if isinstance(d, dict) and isinstance(d.get("kind"), str) and d["kind"] not in by_kind and _band(d):
            by_kind[d["kind"]] = d
    flat = plan.get("vertical") == "flat"
    out: dict = {}

    def deal(role: str, district: str, i: int) -> None:
        lo, hi, tg = _band(by_kind[district])
        lv = _levels(lo, hi, tg)
        if not lv:
            return
        k = 0 if flat else i % len(lv)
        out[role] = {"district": district, "elevs": lv[k:] + lv[:k], "band": [lo, hi]}

    for district, roles in ROLES.items():
        if district in by_kind:
            for i, role in enumerate(roles):
                deal(role, district, i)
        elif district == "defence" and DEFENCE_FALLBACK in by_kind:
            # no defence district: the guard's floors are dealt after the halls' own roles
            for i, role in enumerate(roles):
                deal(role, DEFENCE_FALLBACK, len(ROLES[DEFENCE_FALLBACK]) + i)
    return out


def _stored(plan: dict) -> dict | None:
    """plan["floors"] when it is a table this version reads."""
    f = plan.get("floors")
    if isinstance(f, dict) and f.get("v") == FLOORS_V and isinstance(f.get("roles"), dict):
        return f
    return None


def _roles(plan: dict) -> dict:
    """The roles' lists: the pure table for the plan as it is (the saved one
    is the same unless a district's band changed since ensure last ran)."""
    return _roles_table(plan)


def _roles_words(roles: dict, only: set | None = None, n: int = 3) -> str:
    parts = []
    for district, names in ROLES.items():
        for role in names:
            r = roles.get(role)
            if isinstance(r, dict) and _l(r.get("elevs")) and (only is None or role in only):
                parts.append(f"{role} on " + ", ".join(str(e) for e in r["elevs"][:n]))
    return "; ".join(parts)


def ensure(memory, traits: dict, profile: dict | None = None) -> list[str]:
    """plan["floors"] made when the plan has districts and no table of this
    version (a plan drawn before option B is migrated here, its districts
    untouched); the elevations redone when a district's band changed since
    (`placed` is kept). Returns chronicle lines. No plan: [] and nothing
    written. Never raises."""
    try:
        plan = _peek(memory)
        if not plan.get("districts"):
            return []
        old = plan.get("floors")
        if isinstance(old, dict) and _whole(old.get("v")) and old["v"] > FLOORS_V:
            return []                  # a newer version's table: left as it is
        roles = _roles_table(plan)
        if not roles:
            return []
        cur = _stored(plan)
        if cur is None:
            placed = old.get("placed") if isinstance(old, dict) and isinstance(old.get("placed"), dict) else {}
            plan["floors"] = {"v": FLOORS_V, "vertical": plan.get("vertical"), "roles": roles, "placed": placed}
            return ["the floors were laid out: " + _roles_words(roles)]
        if not isinstance(cur.get("placed"), dict):
            cur["placed"] = {}
        if cur["roles"] == roles and cur.get("vertical") == plan.get("vertical"):
            return []
        changed = {r for r in roles if cur["roles"].get(r) != roles[r]}
        cur["roles"] = roles
        cur["vertical"] = plan.get("vertical")
        if not changed:
            return []
        return ["the floors were laid out again: " + _roles_words(roles, changed)]
    except Exception:  # noqa: BLE001  (the plan stands without its table: hint works from the bands)
        return []


# --- the floors offered to a level ----------------------------------------------------

def _home(memory, kind: str, action: dict | None) -> tuple[str, str, str] | None:
    """role_of with the plan's own answer for the guard: (district, role,
    zone), the district `halls` when the plan has no defence district."""
    row = role_of(kind, action)
    if row is None:
        return None
    if row[0] == "defence" and not _district_of_kind(memory, "defence") \
            and _district_of_kind(memory, DEFENCE_FALLBACK):
        return (DEFENCE_FALLBACK, row[1], row[2])
    return row


def _named(memory, action: dict | None) -> dict | None:
    """The district the action's plan names (masterplan.hint's "district")."""
    name = _d(_d(action).get("plan")).get("district")
    if not isinstance(name, str) or not name:
        return None
    for d in _l(_peek(memory).get("districts")):
        if isinstance(d, dict) and _plain(str(d.get("name") or d.get("kind") or "")) == name:
            return d
    return None


def _tag_district(memory, kind: str, action: dict | None) -> tuple[str, dict | None] | None:
    """(tag, the plan's district of that tag): the kind's own, or the district
    the action's plan names when a custom (or a set piece's place) moved the
    level to another of the five."""
    home = _home(memory, kind, action)
    if home is None:
        return None
    tag = home[0]
    named = _named(memory, action)
    if named is not None and named.get("kind") in TAGS and named["kind"] != tag:
        return named["kind"], named
    return tag, _district_of_kind(memory, tag)


def _xy(v) -> dict | None:
    if isinstance(v, dict) and _whole(v.get("x")) and _whole(v.get("y")) \
            and 0 <= v["x"] <= XY_MAX and 0 <= v["y"] <= XY_MAX:
        return {"x": v["x"], "y": v["y"]}
    return None


def _spine(memory, action: dict | None, district: dict | None) -> dict | None:
    """The stair the level's floors hang on: the action's plan's, else the
    district's own stairwell, else the plan's spine."""
    return (_xy(_d(_d(action).get("plan")).get("spine")) or _xy(_d(district).get("stair"))
            or _xy(_peek(memory).get("spine")))


STAIRS_MAX = 4               # (r3 g1) other stairs named in the hint


def _stairs(memory, district: dict | None, spine: dict | None) -> list[dict]:
    """(r3 g1) The other stairs a floor may hang on, besides the spine: the
    level's district's own stairwell, the other districts' stairwells, the
    survey's stairs (the plan's spine and the stair list the bridge reports).
    STAIRS_MAX at most, none twice."""
    out: list[dict] = []
    seen = {(spine["x"], spine["y"])} if spine else set()

    def put(v):
        xy = _xy(v)
        if xy and (xy["x"], xy["y"]) not in seen and len(out) < STAIRS_MAX:
            seen.add((xy["x"], xy["y"]))
            out.append(xy)
    plan = _peek(memory)
    put(_d(district).get("stair"))
    put(plan.get("spine"))
    for d in _l(plan.get("districts")):
        if isinstance(d, dict):
            put(d.get("stair"))
    sv = _d(_d(getattr(memory, "atlas", None)).get("survey"))
    for st in _l(_d(sv.get("site")).get("stairs")):
        put(st)
    return out


def _dirs(action: dict | None, district: dict | None) -> list[str]:
    """The district's newest wing's way, then its ways, then the action's plan's."""
    out = []
    wings = [w for w in _l(_d(district).get("wings")) if isinstance(w, dict)]
    if wings:
        out.append(wings[-1].get("dir"))
    out.extend(_l(_d(district).get("dirs")))
    out.extend(_l(_d(_d(action).get("plan")).get("dirs")))
    return list(dict.fromkeys(x for x in out if isinstance(x, str) and x in DIRS))[:4]


def _plan_band(memory, kind: str, action: dict | None, traits: dict | None) -> list[int] | None:
    """The action's plan band as floors (nearest its target first) when it is
    not simply the kind's district band: a custom's band, the deep band, a
    set piece's place. None: the role's list stands."""
    pl = _d(_d(action).get("plan"))
    lo, hi = pl.get("elev_lo"), pl.get("elev_hi")
    if not _whole(lo) or not _whole(hi) or lo > hi:
        return None
    home = _home(memory, kind, action)
    own = _band(_district_of_kind(memory, home[0])) if home else None
    if own is not None and pl.get("deep") is not True:
        if (lo, hi) == own[:2]:
            return None
        ceil = masterplan.ceiling(memory, traits)
        if ceil is not None:
            c_hi = min(own[1], ceil)
            if (lo, hi) == (min(own[0], c_hi), c_hi):
                return None            # the district's band, cut under the ceiling
    tg = pl.get("elev_target") if _whole(pl.get("elev_target")) else lo + (hi - lo) // 2
    return _levels(lo, hi, max(lo, min(hi, tg)))


def _full(floors: dict | None, tag: str, spine: dict | None) -> set:
    """The elevations the report marks full for this tag (on this stair, when
    both the floor's and the level's are known)."""
    out = set()
    if not isinstance(floors, dict) or "error" in floors:
        return out
    for f in _l(floors.get("list")):
        if not isinstance(f, dict) or not _whole(f.get("elevation")) or tag not in _l(f.get("full")):
            continue
        st = _xy(f.get("stair"))
        if st and spine and st != spine:
            continue
        out.add(f["elevation"])
    return out


def _refused(floors: dict | None, spine: dict | None) -> set:
    """(r3 g1) The elevations the report's last fallback says were refused
    ("z42: refused: ...", "floor 3: refused: ..."): the builder's own note of
    them lasts only a few days in memory. Floors on another stair: not these."""
    out = set()
    if not isinstance(floors, dict) or "error" in floors:
        return out
    last = floors.get("last")
    if not isinstance(last, dict) or last.get("ok") is not False or not isinstance(last.get("why"), str):
        return out
    by_id = {}
    for f in _l(floors.get("list")):
        if isinstance(f, dict) and _whole(f.get("elevation")) and f.get("id") is not None:
            st = _xy(f.get("stair"))
            if not (st and spine and st != spine):
                by_id[str(f["id"])] = f["elevation"]
    for part in last["why"].split(";"):
        m = re.match(r"\s*(?:z(-?\d+)|floor (\d+))(?: \([^)]*\))?: refused", part)
        if not m:
            continue
        if m.group(1) is not None:
            out.add(int(m.group(1)))
        elif m.group(2) in by_id:
            out.add(by_id[m.group(2)])
    return out


def _no_hall(floors: dict | None, spine: dict | None) -> set:
    """(r3 g1) The elevations the report says no hall can start on (a fresh
    '*' mark: "no hall", the stair's hub refused; a floor with no hall left
    whose hub was refused is one too), on this stair."""
    out = set()
    if not isinstance(floors, dict) or "error" in floors:
        return out
    for f in _l(floors.get("list")):
        if not isinstance(f, dict) or not _whole(f.get("elevation")):
            continue
        if f.get("no_hall") is not True:
            continue
        st = _xy(f.get("stair"))
        if st and spine and st != spine:
            continue
        out.add(f["elevation"])
    return out


def _more_elevs(memory, district: dict | None, have: list[int], ceil: int | None, cfg: dict) -> list[int]:
    """(r3 g1) The elevations offered beyond the role's own once those are
    full or refused: the district's band, then deeper down to the plan's
    range (r3g1_floor_deeper_max at most below the band), the levels of no
    other district first; never above the ceiling."""
    b = _band(district)
    if b is None:
        return []
    lo, hi, tg = b
    plan = _peek(memory)
    rng = plan.get("range") if isinstance(plan.get("range"), list) and len(plan["range"]) == 2 else None
    deep = _d(cfg).get("r3g1_floor_deeper_max", 12)
    deep = max(0, min(60, deep)) if _whole(deep) else 12
    bottom = lo - deep
    if rng and _whole(rng[0]):
        bottom = max(bottom, min(rng[0], lo))
    others = set()
    for d in _l(plan.get("districts")):
        ob = _band(d) if d is not district else None
        if ob:
            others.update(range(max(ob[0], ELEV_MIN), min(ob[1], ELEV_MAX) + 1))
    band = [e for e in _levels(lo, hi, tg)]
    below = list(range(lo - 1, max(bottom, ELEV_MIN) - 1, -1))
    order = band + [e for e in below if e not in others] + [e for e in below if e in others]
    seen = set(have)
    return [e for e in order if e not in seen and (ceil is None or e <= ceil)]


def _elevs_max(cfg: dict | None) -> int:
    n = _d(cfg).get("floor_elevs_max", ELEVS_MAX)
    return max(1, min(ELEVS_CAP, n)) if _whole(n) else ELEVS_MAX


def elevs_for(memory, kind: str, action: dict | None, traits: dict, floors: dict | None, cfg: dict,
              extra_full: set | None = None) -> list[int]:
    """The floors (elevations) offered to a new level of this kind, in order:
    the action's plan band when it is not the kind's district band (a custom,
    the deep band), else its role's list from the table; floors the report
    marks full for the level's tag last; none above the fort's ceiling;
    floor_elevs_max at most. [] when there is none to offer. Never raises."""
    try:
        td = _tag_district(memory, kind, action)
        if td is None:
            return []
        tag, district = td
        elevs = _plan_band(memory, kind, action, traits)
        if elevs is None:
            home = _home(memory, kind, action)
            r = _roles(_peek(memory)).get(home[1])
            elevs = list(r["elevs"]) if isinstance(r, dict) else []
            if not elevs:
                b = _band(district)        # no role for it: the district's band as it is
                elevs = _levels(*b) if b else []
        ceil = masterplan.ceiling(memory, traits)
        elevs = [e for e in dict.fromkeys(elevs)
                 if _whole(e) and ELEV_MIN <= e <= ELEV_MAX and (ceil is None or e <= ceil)]
        spine = _spine(memory, action, district)
        full = _full(floors, tag, spine)
        cfg = _d(cfg)
        if cfg.get("r3g1_floor_skip_no_hall", True) is not False:
            # (r3 g1) a level no hall can start on, a floor with no hall left, one refused lately: as full
            full = full | _no_hall(floors, spine) | _refused(floors, spine)
        if extra_full:
            full = full | {e for e in extra_full if _whole(e)}   # (r3 V1) refused lately for soil: as full
        good = [e for e in elevs if e not in full]
        more = []
        if elevs and cfg.get("r3g1_floor_more_elevs", True) is not False:
            least = cfg.get("r3g1_floor_open_min", 2)
            least = least if _whole(least) else 2
            if len(good) < min(least, _elevs_max(cfg)):
                # (r3 g1) the planned floors full or refused: the band's others and deeper ones, free first
                more = [e for e in _more_elevs(memory, district, elevs, ceil, cfg) if e not in full]
        elevs = good + more + [e for e in elevs if e in full]
        return elevs[:_elevs_max(cfg)]
    except Exception:  # noqa: BLE001
        return []


# --- the hint ------------------------------------------------------------------------

def _doors(memory, action: dict, traits: dict) -> str | None:
    """The action's plan doors, else as planner_building.apply_customs sets them."""
    doors = _d(action.get("plan")).get("doors")
    if doors in ("open", "doored", "fortified"):
        return doors
    try:
        v = traits.get("fortification", 0) or 0
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 70:
            return "fortified"
        from culture import new_history, profile_from
        culture = memory.culture if isinstance(getattr(memory, "culture", None), dict) and memory.culture \
            else new_history()
        return "doored" if profile_from(traits, culture).get("entry_doors") else "open"
    except Exception:  # noqa: BLE001
        return None


def _grammar_keys(memory, action: dict, traits: dict, cfg: dict) -> dict:
    """floor_grammar.grammar's keys for this level; {} when the module is
    missing or fails (the builder's defaults stand)."""
    try:
        import floor_grammar
    except Exception:  # noqa: BLE001
        return {}
    try:
        import customs
        import design
        from quirks import has_rule
        culture = memory.culture if isinstance(getattr(memory, "culture", None), dict) else {}
        style = action.get("style") if isinstance(action.get("style"), dict) else None
        pattern = _peek(memory).get("pattern")
        seed = culture.get("seed")
        g = floor_grammar.grammar(
            traits, style, cfg,
            pattern=pattern if isinstance(pattern, str) else "grid",
            quirks=frozenset(r for r in QUIRK_RULES if has_rule(culture, r)),
            customs=frozenset(customs.active(traits)),
            doors=_doors(memory, action, traits),
            seed=seed if isinstance(seed, str) and seed else "fort",
            language=bool(design.current(culture)),
            grand=bool(_d(style).get("grand") or action.get("set_piece")),
            urgent=action.get("urgent") is True)
        return dict(g) if isinstance(g, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _soil_filter(memory, kind, action, elevs, s, traits, cfg) -> list:
    """(r3 g3) floor_soil.filter_elevs, guarded: elevs as given on any error."""
    try:
        import floor_soil
        out = floor_soil.filter_elevs(memory, kind, action, elevs, s, traits, cfg)
        return out if isinstance(out, list) else elevs
    except Exception:  # noqa: BLE001
        return elevs


def _soil_recent(memory, s, cfg) -> set:
    """(r3 V1) The elevations refused lately for soil or roots (floor_soil),
    so elevs_for counts them as full when it decides to offer more."""
    try:
        if _d(cfg).get("r3g3_soil_skip") is not True:
            return set()
        import floor_soil
        return set(floor_soil.remembered(memory, floor_soil._now(s), _d(cfg).get("r3g3_soil_days", 14)))
    except Exception:  # noqa: BLE001
        return set()


def hint(memory, action: dict, s: dict, traits: dict, cfg: dict) -> dict | bool | None:
    """A start_project's "floor" value: a dict (the floors offered, the tag,
    the zone, the stair, the ways, and floor_grammar's numbers); False for a
    level placed the classic way on purpose (a kind that never goes on a
    floor, `join` false, a landmark's level, a level by the fields; (r3 g3) a
    holy level whose floors are all soil or near the surface); None to
    say nothing (no master plan yet, nothing to offer: the builder's own
    default). Reads memory, the action, s["floors"] and cfg; never raises."""
    try:
        if not isinstance(action, dict):
            return None
        kind = action.get("kind")
        if role_of(kind, action) is None:
            return False
        if action.get("join") is False or action.get("landmark") is not None:
            return False
        if set(x for x in _l(action.get("customs")) if isinstance(x, str)) & set(CLASSIC_CUSTOMS):
            return False
        if not masterplan.has_plan(memory):
            return None
        traits = traits if isinstance(traits, dict) else {}
        cfg = cfg if isinstance(cfg, dict) else {}
        tag, district = _tag_district(memory, kind, action)
        zone = _home(memory, kind, action)[2]
        elevs = elevs_for(memory, kind, action, traits, _d(s).get("floors"), cfg, _soil_recent(memory, s, cfg))
        if not elevs:
            return None
        elevs = _soil_filter(memory, kind, action, elevs, s, traits, cfg)
        if not elevs:
            return False               # (r3 g3) a holy level with only soil or the surface to go to: classic
        out = _grammar_keys(memory, action, traits, cfg)
        for k in ("elevs", "tag", "group", "zone", "spine", "dirs"):
            out.pop(k, None)
        out.update({"elevs": elevs, "tag": tag, "zone": zone if zone in ZONES else "any"})
        if kind == "workshops":
            g = _group(action)
            if g:
                out["group"] = g
        spine = _spine(memory, action, district)
        if spine:
            out["spine"] = spine
        dirs = _dirs(action, district)
        if dirs:
            out["dirs"] = dirs
        # (r3 g1) every stair the fort's floors may start from, and the tries each one gets
        tries = cfg.get("r3g1_floor_stair_tries", 1)
        if _whole(tries) and tries > 0:
            out["stair_tries"] = min(3, tries)
            stairs = _stairs(memory, district, spine) if cfg.get("r3g1_floor_stairs", True) is not False else []
            if stairs:
                out["stairs"] = stairs
        elif _whole(tries):
            out["stair_tries"] = 0
        if cfg.get("r3g2_floor_spill", True) is False:
            out["spill"] = False           # (r3 g2) a full floor stays at its arms_max
        return _fit_big(memory, action, out, cfg)
    except Exception:  # noqa: BLE001
        return None


# --- (r3 g2) levels too big for a run ---------------------------------------------------
# The builder answers a level too big for any run of its grammar with `floor_big` ({need,
# run_max}: the run it would need, need None when no run up to 80 can take it). note_result
# keeps it by the level's kind and size in plan["floors"]["big"]; the next hint for a level of
# that kind and size asks for a run that holds it (run_max = need), or says False (the classic
# way at once, no floor tried) when none can.

SIZE_KEYS = ("rooms", "room_size", "tables", "beds", "cells", "size", "plots", "plot_w", "dormitory")
RUN_TOP = 80                 # the bridge's highest run_max


def size_key(action: dict | None) -> str | None:
    """A level's kind and size, as one key: "storage|room_size=7|piles=2"; None for no kind."""
    a = _d(action)
    kind = a.get("kind")
    if not isinstance(kind, str) or not kind:
        return None
    parts = [kind]
    for k in SIZE_KEYS:
        v = a.get(k)
        if isinstance(v, (bool, int, float, str)):
            parts.append(f"{k}={v}")
    for k in ("piles", "shops"):
        if isinstance(a.get(k), list):
            parts.append(f"{k}={len(a[k])}")
    if _d(a.get("style")).get("grand") is True or a.get("set_piece"):
        parts.append("grand")
    return "|".join(parts)[:120]


def _big_table(memory, make: bool = False) -> dict | None:
    plan = _peek(memory)
    table = _stored(plan)
    if table is None:
        return None
    big = table.get("big")
    if not isinstance(big, dict):
        if not make:
            return None
        big = table["big"] = {}
    return big


def note_big(memory, action: dict, result: dict, cfg: dict | None = None) -> str | None:
    """A start_project answered with `floor_big`: the size kept (the newest
    r3g2_floor_big_keep); a level of that size that later went onto a floor
    takes the note away. Returns a chronicle line the first time a size is
    found too big, else None. Never raises."""
    try:
        cfg = cfg if isinstance(cfg, dict) else {}
        if cfg.get("r3g2_floor_big", True) is False:
            return None
        if not isinstance(action, dict) or not isinstance(result, dict) or action.get("type") != "start_project":
            return None
        if action.get("dry_run") is True or result.get("dry_run") is True:
            return None
        key = size_key(action)
        if key is None:
            return None
        fb = result.get("floor_big")
        if isinstance(result.get("floor"), dict):
            big = _big_table(memory)
            if big is not None:
                big.pop(key, None)
            return None
        if not isinstance(fb, dict):
            return None
        need = fb.get("need") if _whole(fb.get("need")) and 12 <= fb["need"] <= RUN_TOP else None
        ensure(memory, {}, None)
        big = _big_table(memory, make=True)
        if big is None:
            return None
        first = key not in big
        big.pop(key, None)
        big[key] = {"need": need}
        keep = cfg.get("r3g2_floor_big_keep", 40)
        keep = keep if _whole(keep) and keep > 0 else 40
        for k in list(big)[:-keep]:
            del big[k]
        if not first:
            return None
        kind = action.get("kind")
        return (f"a {kind} level of that size needs a hall of {need} to stand on a floor" if need is not None
                else f"a {kind} level of that size is too big for any floor's hall: such levels are placed the old way")
    except Exception:  # noqa: BLE001
        return None


def _fit_big(memory, action: dict, out: dict, cfg: dict):
    """The hint for a level whose size was found too big: run_max raised to the
    run it needs, or False (classic at once) when no run can take it."""
    try:
        if cfg.get("r3g2_floor_big", True) is False:
            return out
        big = _big_table(memory)
        key = size_key(action)
        if not big or key is None or not isinstance(big.get(key), dict):
            return out
        need = big[key].get("need")
        if not _whole(need):
            return False
        if need > (out.get("run_max") if _whole(out.get("run_max")) else 0):
            out["run_max"] = min(RUN_TOP, need)
        return out
    except Exception:  # noqa: BLE001
        return out


# --- after the answer; in words -------------------------------------------------------

def note_result(memory, action: dict, result: dict) -> str | None:
    """After a start_project that went onto a floor: the level kept in
    plan["floors"]["placed"] (the newest 80). Returns a chronicle line when
    it began a new floor's main hall, else None. (r3 g2) A level too big for
    a run is kept first (note_big). Never raises."""
    try:
        from planner_config import PLANNER_CONFIG
        big_line = note_big(memory, action, result, PLANNER_CONFIG)
        if big_line:
            return big_line
    except Exception:  # noqa: BLE001
        pass
    try:
        if not isinstance(action, dict) or not isinstance(result, dict) or action.get("type") != "start_project":
            return None
        fl = result.get("floor")
        if result.get("ok") is not True or not isinstance(fl, dict):
            return None
        if action.get("dry_run") is True or result.get("dry_run") is True:
            return None
        plan = _peek(memory)
        if not plan.get("districts"):
            return None
        el = fl.get("elevation") if _whole(fl.get("elevation")) else result.get("elevation")
        el = el if _whole(el) else None
        kind = action.get("kind")
        home = _home(memory, kind, action)
        pid = result.get("project_id")
        if pid is not None and not isinstance(pid, (dict, list, bool)):
            ensure(memory, {}, None)
            table = _stored(plan)
            if table is not None:
                placed = table["placed"] if isinstance(table.get("placed"), dict) else {}
                table["placed"] = placed
                placed.pop(str(pid), None)
                placed[str(pid)] = {"floor": fl.get("id"), "role": home[1] if home else None, "elevation": el}
                for k in list(placed)[:-PLACED_MAX]:
                    del placed[k]
        if fl.get("new_floor") is not True or el is None:
            return None
        tag = _d(action.get("floor")).get("tag")
        if tag not in TAGS:
            td = _tag_district(memory, kind, action)
            tag = td[0] if td else None
        return f"a main hall was begun on elevation {el}" + (f" for {WORDS[tag]}" if tag in WORDS else "")
    except Exception:  # noqa: BLE001
        return None


def lines(memory, floors: dict | None = None, limit: int = 6) -> list[str]:
    """The floors in words, for the panel and the strategist: one line of the
    roles' floors ("floors: sleeping on 10, 9, 11; common on 11 (3 laid out,
    41 rooms)"), then, with the report's `floors` section, a line a floor.
    [] without a table. Never raises."""
    try:
        plan = _peek(memory)
        table = _stored(plan)
        if table is None or not plan.get("districts") or not _whole(limit) or limit <= 0:
            return []
        words = _roles_words(table["roles"])
        if not words:
            return []
        rep = floors if isinstance(floors, dict) and "error" not in floors else None
        placed = [v for v in _d(table.get("placed")).values() if isinstance(v, dict)]
        tail = []
        if rep is not None and _whole(rep.get("count")):
            if rep["count"] > 0:
                tail.append(f"{rep['count']} laid out")
                if _whole(rep.get("rooms")):
                    tail.append(f"{rep['rooms']} room{'s' if rep['rooms'] != 1 else ''}")
            if _whole(rep.get("fallbacks")) and rep["fallbacks"] > 0:
                tail.append(f"{rep['fallbacks']} level{'s' if rep['fallbacks'] != 1 else ''} placed the old way")
        elif placed:
            n = len({str(v.get("floor")) for v in placed})
            tail.append(f"{n} laid out")
            tail.append(f"{len(placed)} level{'s' if len(placed) != 1 else ''}")
        out = ["floors: " + words + (f" ({', '.join(tail)})" if tail else "")]
        for f in _l(_d(rep).get("list")):
            if not isinstance(f, dict) or not _whole(f.get("elevation")):
                continue
            if f.get("no_hall") is True:
                out.append(f"elevation {f['elevation']}: no main hall can start here")
                continue
            tags = [t for t in _l(f.get("tags")) if isinstance(t, str)]
            full = [t for t in _l(f.get("full")) if isinstance(t, str)]
            arms = [a.get("dir") for a in _l(f.get("arms")) if isinstance(a, dict) and a.get("dir") in DIRS]
            rooms = f.get("rooms") if _whole(f.get("rooms")) else 0
            out.append(f"elevation {f['elevation']}: {rooms} room{'s' if rooms != 1 else ''}"
                       + (f" ({', '.join(tags[:5])})" if tags else "")
                       + (f", halls {'/'.join(arms[:4])}" if arms else "")
                       + (f", full for {', '.join(full[:5])}" if full else ""))
        return [str(x)[:400] for x in out[:limit]]
    except Exception:  # noqa: BLE001
        return []
