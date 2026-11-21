"""(r3 g3) Floors and the soil: where a hallway floor's hall met soil or roots.

Near the surface a floor's hall can run into soil or tree roots, and the
builder refuses it: "floor 3: refused: not natural rock (ROOT) at x107 y177
z39" (fort A, 23 times at one tile in the 15-16 Nov run). Two things follow:

- `note(memory, action, result, state)`: after a start_project, each
  elevation whose floor the builder refused for soil or roots is kept in
  memory.atlas["floor_soil"] ({"<elevation>": {"tick", "n", "at"}}, the
  newest SOIL_MAX). Called from masterplan.note_result (the overseer's
  "masterplan" step after the actions), never from the planner.
- `filter_elevs(memory, kind, action, elevs, s, traits, cfg)`: the floors
  offered to a level (masterplan_floors.hint), without an elevation refused
  for soil lately (r3g3_soil_days, any kind; the list as it was when that
  would leave nothing), and for the holy kinds (the worship and crypt roles:
  temple, memorial, library, garden, tombs) never one near the surface
  (r3g3_sacred_surface_gap), with soil (the site survey's soil levels) or
  refused for soil within r3g3_sacred_soil_days; the elevations taken out
  are made up from those under the band (r3g3_sacred_deeper at most).

Pure but for note(); never raises. Switch: r3g3_soil_skip (filter_elevs
reads it from the hint's config: a config without it, as the layout-B
tests pass, keeps the floors offered as they were).
"""

from __future__ import annotations

import re

SOIL_KEY = "floor_soil"
SOIL_MAX = 24                # elevations remembered at most (the newest kept)
TICKS_PER_DAY = 1200
# DF tile materials that are soil or roots (not natural rock, and not the fort's own work)
SOIL_MATS = r"(?:ROOT|SOIL\w*|GRASS\w*|PLANT\w*|TREE\w*|MUSHROOM\w*)"
_SEG_RE = re.compile(r"^\s*(?:floor\s+(\d+)|z(-?\d+))\s*:\s*(.*)$", re.S)
_SOIL_RE = re.compile(r"not natural rock \(" + SOIL_MATS + r"\)(?:\s+at\s+x(\d+)\s+y(\d+)\s+z(-?\d+))?")
SACRED_ROLES = ("worship", "crypt")


def _whole(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _now(s) -> int | None:
    try:
        from planner_core import abs_tick
        t = abs_tick(s)
        return t if _whole(t) else None
    except Exception:  # noqa: BLE001
        return None


def soil_refusals(why, floors=None) -> list[tuple[int, str]]:
    """[(elevation, "x107 y177")] for each floor the builder refused for soil
    or roots in a `not_on_floor` text. The elevation: the tile's own (the
    message's "z<elevation>"), else the label's ("z39: ..."), else the floor's
    in the report's `floors` list ("floor 3: ..."). Never raises."""
    out: list[tuple[int, str]] = []
    try:
        if not isinstance(why, str):
            return out
        elev_of = {}
        for f in _l(_d(floors).get("list")):
            if isinstance(f, dict) and _whole(f.get("id")) and _whole(f.get("elevation")):
                elev_of[f["id"]] = f["elevation"]
        for seg in why.split(";"):
            m = _SEG_RE.match(seg)
            if not m:
                continue
            fid, zlab, rest = m.group(1), m.group(2), m.group(3)
            sm = _SOIL_RE.search(rest)
            if not sm:
                continue
            at = f"x{sm.group(1)} y{sm.group(2)}" if sm.group(1) else ""
            if sm.group(3) is not None:
                e = int(sm.group(3))
            elif zlab is not None:
                e = int(zlab)
            elif fid is not None and int(fid) in elev_of:
                e = elev_of[int(fid)]
            else:
                continue
            if -400 <= e <= 400 and all(x[0] != e for x in out):
                out.append((e, at))
    except Exception:  # noqa: BLE001
        return out
    return out


def note(memory, action, result, state, cfg=None) -> list[int]:
    """Keep the elevations a start_project's answer refused for soil or roots
    (memory.atlas["floor_soil"]). Returns them. No answer with `not_on_floor`,
    a dry run, the switch off or no clock: [] and nothing written."""
    try:
        if cfg is None:
            from planner_config import PLANNER_CONFIG as cfg
        if not _d(cfg).get("r3g3_soil_skip", True):
            return []
        if not isinstance(action, dict) or action.get("type") != "start_project" or not isinstance(result, dict):
            return []
        if action.get("dry_run") is True or result.get("dry_run") is True:
            return []
        found = soil_refusals(result.get("not_on_floor"), _d(state).get("floors"))
        now = _now(state)
        if not found or now is None or not isinstance(getattr(memory, "atlas", None), dict):
            return []
        book = memory.atlas.get(SOIL_KEY)
        if not isinstance(book, dict):
            book = memory.atlas[SOIL_KEY] = {}
        for e, at in found:
            old = book.pop(str(e), None)
            n = old.get("n") if isinstance(old, dict) and _whole(old.get("n")) else 0
            book[str(e)] = {"tick": now, "n": n + 1, **({"at": at} if at else {})}
        for k in list(book)[:-SOIL_MAX]:
            del book[k]
        return [e for e, _ in found]
    except Exception:  # noqa: BLE001
        return []


def remembered(memory, now: int | None, days) -> set[int]:
    """The elevations refused for soil within `days` game days of now (all of
    them when the clock can't be read; none from a tick ahead of now: another
    calendar, or the game went back)."""
    out: set[int] = set()
    try:
        book = _d(_d(getattr(memory, "atlas", None)).get(SOIL_KEY))
        lim = float(days) * TICKS_PER_DAY
        for k, v in book.items():
            try:
                e = int(k)
            except (TypeError, ValueError):
                continue
            t = _d(v).get("tick")
            if now is None or (_whole(t) and 0 <= now - t <= lim):
                out.add(e)
    except Exception:  # noqa: BLE001
        return out
    return out


def _surface(memory, action, kind) -> int | None:
    try:
        import masterplan
        import masterplan_floors as MF
        td = MF._tag_district(memory, kind, action)
        spine = MF._spine(memory, action, td[1] if td else None)
        sp = dict(spine) if spine else None
        pl = masterplan._peek(memory).get("spine")
        if sp is not None and isinstance(pl, dict) and _whole(pl.get("top")) \
                and pl.get("x") == sp["x"] and pl.get("y") == sp["y"]:
            sp["top"] = pl["top"]
        elif sp is None and isinstance(pl, dict):
            sp = pl
        e = masterplan.surface_elevation(memory, sp)
        return e if _whole(e) else None
    except Exception:  # noqa: BLE001
        return None


def _survey_soil(memory) -> set[int]:
    sv = _d(_d(_d(getattr(memory, "atlas", None)).get("survey")).get("site"))
    return {e for e in _l(sv.get("soil")) if _whole(e)}


def sacred(kind, action=None, cfg=None) -> bool:
    """A holy kind: its role is one of r3g3_sacred_roles (worship, crypt)."""
    try:
        import masterplan_floors as MF
        row = MF.role_of(kind, action)
        roles = _l(_d(cfg).get("r3g3_sacred_roles")) or list(SACRED_ROLES)
        return row is not None and row[1] in roles
    except Exception:  # noqa: BLE001
        return False


def filter_elevs(memory, kind, action, elevs, s, traits, cfg) -> list:
    """The floors offered, as the module docstring says. Never raises: on
    any error, elevs as given."""
    try:
        cfg = _d(cfg)
        # the switch as the hint's config has it (PLANNER_CONFIG: on); a bare config is the old way
        if cfg.get("r3g3_soil_skip") is not True or not isinstance(elevs, list) or not elevs:
            return elevs
        now = _now(s)
        recent = remembered(memory, now, cfg.get("r3g3_soil_days", 14))
        out = [e for e in elevs if e not in recent]
        if not sacred(kind, action, cfg):
            return out if out else list(elevs)
        bad = remembered(memory, now, cfg.get("r3g3_sacred_soil_days", 336)) | recent | _survey_soil(memory)
        surf = _surface(memory, action, kind)
        gap = cfg.get("r3g3_sacred_surface_gap", 3)
        top = surf - gap if surf is not None and _whole(gap) else None

        def ok(e):
            return _whole(e) and e not in bad and (top is None or e <= top)
        kept = [e for e in out if ok(e)]
        if len(kept) == len(elevs):
            return kept
        # the ones taken out: made up from the elevations under the band
        import masterplan
        import masterplan_floors as MF
        cap = MF._elevs_max(cfg)
        deeper = cfg.get("r3g3_sacred_deeper", 4)
        deeper = deeper if _whole(deeper) and deeper >= 0 else 0
        ceil = masterplan.ceiling(memory, traits)
        e = min(x for x in elevs if _whole(x)) - 1
        tried = 0
        while len(kept) < min(cap, len(elevs)) and tried < deeper and e >= MF.ELEV_MIN:
            if ok(e) and e not in kept and (ceil is None or e <= ceil):
                kept.append(e)
            e -= 1
            tried += 1
        return kept
    except Exception:  # noqa: BLE001
        return elevs
