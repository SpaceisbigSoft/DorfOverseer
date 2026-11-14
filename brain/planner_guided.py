"""planner_guided: the Design track's D1, Guided live (0.105.47).

At Guided (and Architect) every new level the scripts build follows the
fort's design language, not only the building ladder's: D0 styled the
ladder's level and the farm and strategist levels, and some 60 other
start_project proposers (the urgent levels, every rule's workshop level,
growth, homes, moods, food stores, wells, ...) sent no style at all, so the
bridge built them plain (a plain hall, no smoothing, no statues, the default
size). `guided_pass` (run by plan() after customs_pass, as that pass is)
gives each of them the language's style keys:

    hall, smooth, statues, entry_door, spacing (culture.layout_style),
    scale, aspect, arms, motif, grand (design.style_fields: the language,
    a kind in its emphasis grand), orient, rhythm (masterplan.variety: the
    language's symmetry).

A key the rule set itself is kept (a young fort's plain finish, a rule's own
door). An urgent level (a mood's workshop, the ghosts' tombs, a jail or
hospital the fort needs now) gets the language's form only (hall shape,
arms, motif, turn): no bigger hall, no statues or smoothing it would wait
for. A young fort builds plain (smooth 0, statues 0), as the ladder does.

`name_districts` (called by planner_design.design_rule at Guided and
Architect) gives the master plan's districts that have no level yet the
language's naming (its words, tone and pattern), so a fort switched to
Guided mid-life names what it builds next in its own words; a district with
a level keeps its name.

At Scripts nothing here changes anything (plan()'s proposals are main's,
byte for byte). Nothing here ever touches a level that stands or is under
way: a switch to Guided mid-life changes only the new levels.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import PLANNER_CONFIG, young_fort

try:
    import design
except ImportError:       # pragma: no cover
    design = None

# The keys an urgent level takes from the language: its form, never its size or finish
URGENT_KEYS = ("hall", "arms", "motif", "orient", "rhythm")


def language_of(s: dict, memory) -> dict | None:
    """The language the scripts follow now, or None (Scripts, or none yet)."""
    if memory is None or design is None:
        return None
    try:
        if design.mode(s) == "scripts":
            return None
        return design.current(memory.culture if isinstance(getattr(memory, "culture", None), dict) else None)
    except Exception:  # noqa: BLE001
        return None


def level_style(profile: dict, memory, kind: str, young: bool, urgent: bool) -> dict:
    """The language's style for one new level of this kind."""
    from culture import layout_style
    import masterplan
    want = dict(layout_style(profile, kind))
    try:
        want.update(masterplan.variety(memory, kind))
    except Exception:  # noqa: BLE001  (the turn is a detail)
        pass
    if young:
        want.update(smooth=0, statues=0)       # a young fort builds plain, as the ladder does
    if urgent:
        want = {k: v for k, v in want.items() if k in URGENT_KEYS}
    return want


def guided_pass(proposals: list, s: dict, memory, traits: dict, cfg: dict = PLANNER_CONFIG) -> None:
    """Every start_project in the language (module docstring). Keys a rule
    set itself are kept; at Scripts nothing changes."""
    if language_of(s, memory) is None:
        return
    from culture import new_history, profile_from
    profile = None
    young = None
    for p in proposals:
        a = p.action
        if not isinstance(a, dict) or a.get("type") != "start_project" or not isinstance(a.get("kind"), str):
            continue
        st = a.get("style") if isinstance(a.get("style"), dict) else {}
        if profile is None:
            profile = profile_from(traits, memory.culture or new_history())
            young = young_fort(s, cfg)
        want = level_style(profile, memory, a["kind"], bool(young), a.get("urgent") is True)
        merged = dict(want)
        merged.update(st)                      # the rule's own keys stand
        if merged != st:
            p.action = dict(a, style=merged)


def name_districts(s: dict, memory, traits: dict) -> list[str]:
    """The plan's districts with no level yet named in the language's words
    (once each). Returns lines for the notes."""
    if language_of(s, memory) is None:
        return []
    naming = design.naming(memory.culture)
    if not naming:
        return []
    atlas = memory.atlas if isinstance(getattr(memory, "atlas", None), dict) else {}
    plan = atlas.get("plan") if isinstance(atlas.get("plan"), dict) else None
    if not plan:
        return []
    import masterplan
    from culture import new_history, profile_from
    seed = _d(memory.culture).get("seed") or "fort"
    palette = profile_from(traits, memory.culture or new_history()).get("palette") or "any"
    out = []
    for d in _l(plan.get("districts")):
        if not isinstance(d, dict) or d.get("named_by") == "design" or _l(d.get("levels")) or d.get("missed"):
            continue
        kind = d.get("kind") if isinstance(d.get("kind"), str) else None
        if not kind:
            continue
        try:
            new = masterplan.district_name(kind, palette, seed, naming)
        except Exception:  # noqa: BLE001
            continue
        d["named_by"] = "design"
        if new and new != d.get("name"):
            out.append(f"design: the {kind} district, not built yet, is named {new} in the fort's words"
                       + (f" (was {d.get('name')})" if d.get("name") else ""))
            d["name"] = new
    return out
