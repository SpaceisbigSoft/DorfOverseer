"""The master plan: one design for the whole fort, drawn once by scripts.

    masterplan.ensure(state, memory, site)    # draws the plan if the fort has none
    masterplan.hint(memory, kind)             # where a new level of this kind belongs
    masterplan.note_result(memory, action, result, state)   # a level was started
    masterplan.lines(memory)                  # the plan in words (panel, strategist)

Instead of every new level going to the first safe rock by the busiest stair,
the plan says where each kind of level belongs:

  spine      the main stair the fort grows around (found by the bridge's survey)
  axis       the fort's main direction: from the main surface entrance into the
             rock (the "front" is the entrance side)
  pattern    grid, rings, branching or stacked (the weights engine's Layout area)
  vertical   flat (every district on a few levels, apart by direction),
             balanced, or deep (each district its own band of levels) - Verticality
  districts  homes, halls, storage, industry, farms, defence: each a band of
             elevations, a direction from the spine, and a name
  grammar    avenue width and straight or dog-leg corridors, sent with every
             hint (the builder applies them from bridge 0.33; the door rule
             is taken from the fort's current style each time)
  slots      where the great hall, the temple, the memorials (and with Last
             Stand an inner keep) will go

The plan lives in the atlas (memory.atlas["plan"]) and is never redrawn,
except when its formula (FORMULA) changes before anything was built in it. A new
era adds a new wing to each district (the next direction from the spine),
in the founding grammar, so old work keeps its style and new eras show as
new wings. The builder tries the hint first and falls back to its ordinary
search when the district has no room; a district that keeps missing grows by
two levels, away from the spine's middle, when the site allows.

The plan is elevations and directions from the spine, made by scripts from the
map; the AI strategist never sends coordinates.
"""

from __future__ import annotations

import hashlib

import customs
import design
from digest import _d, _l
from quirks import has_rule
from util import date_tick

DIRS = ("north", "east", "south", "west")
PLAN_EXTEND = 3            # the plan reaches at most this far below the spine's bottom
                           # (lua/ai-builder.lua PLAN_EXTEND: the band pass extends no further)
MIN_RANGE = 3              # fewer usable levels than this: no plan yet
# The plan's formula: when it changes, a plan with no level built in any of
# its districts yet is drawn again (one that has levels keeps its design).
FORMULA = 2
CAVERN_MARGIN = 3          # levels kept clear above the first cavern
GROW_AFTER_MISSES = 2      # a district grows after this many levels went elsewhere
GROW_BY = 2

# which district each kind of level belongs in
DISTRICT_OF = {
    "bedrooms": "homes", "dining": "homes", "tavern": "homes", "hospital": "homes",
    "temple": "halls", "library": "halls", "memorial": "halls", "garden": "halls", "tombs": "halls",
    "storage": "storage", "workshops": "industry", "farms": "farms", "barracks": "defence", "archery": "defence",
}
# top to bottom, the order districts are stacked in a deep fort
STACK = ("defence", "halls", "homes", "storage", "industry")
WORDS = {"homes": "homes", "halls": "halls", "storage": "storage", "industry": "industry",
         "farms": "farms", "defence": "defence"}
NOUNS = {
    "homes": ["Hearths", "Homesteads", "Sleeping Deeps", "Warm Halls"],
    "halls": ["Great Halls", "Halls of Memory", "High Halls", "Echoing Halls"],
    "storage": ["Vaults", "Stores", "Deep Larders", "Hoards"],
    "industry": ["Forges", "Workings", "Anvil Deeps", "Smoke Halls"],
    "farms": ["Fields", "Mud Gardens", "Under-farms", "Root Halls"],
    "defence": ["Gatehold", "Bulwark", "Wardens' Rise", "Shield Halls"],
}
ADJECTIVES = {"dark": "Dark", "light": "Pale", "warm": "Red", "cool": "Blue", "precious": "Gilded",
              "wood": "Timbered", "purpose": "Carved", "any": "Old"}
ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth"]


def _plan(memory) -> dict:
    a = memory.atlas if isinstance(memory.atlas, dict) else {}
    memory.atlas = a
    p = a.get("plan")
    if not isinstance(p, dict):
        p = a["plan"] = {}
    return p


def _peek(memory) -> dict:
    """The plan, read only (the planner must never change memory)."""
    a = memory.atlas if isinstance(memory.atlas, dict) else {}
    return a.get("plan") if isinstance(a.get("plan"), dict) else {}


def has_plan(memory) -> bool:
    return bool(_peek(memory).get("districts"))


def _seed(*parts) -> int:
    return int(hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


def _turn(d: str, steps: int) -> str:
    return DIRS[(DIRS.index(d) + steps) % 4]


def _axis(memory, spine: dict) -> str:
    """From the main surface entrance into the rock: the side facing away
    from the entrance is the fort's 'forward'. Without a known surface
    entrance: south (the game's own default view)."""
    ents = (memory.atlas or {}).get("entrances") or {}
    best, best_d = None, None
    for k, e in ents.items():
        if not isinstance(e, dict) or e.get("kind") != "surface":
            continue
        try:
            x, y, _z = (int(v) for v in k.split(","))
        except ValueError:
            continue
        d = abs(x - spine["x"]) + abs(y - spine["y"])
        if best_d is None or d < best_d:
            best, best_d = (x, y), d
    if not best:
        return "south"
    dx, dy = spine["x"] - best[0], spine["y"] - best[1]      # entrance -> spine, then onward
    if abs(dx) >= abs(dy):
        return "east" if dx >= 0 else "west"
    return "south" if dy >= 0 else "north"


DEEP_EXTEND = 20           # (0.105.14, 14.1 step 4c) a deep fort's plan reaches this far below the spine
# (0.105.23, 14.1 step 4c) Surface this low or lower (the Deep mine, -100):
# no level at or above the surface. The six-preset test (y257) found E with
# a level at the surface like every other fort: the plan's range began at
# the spine's top (the founding stair's top is the surface) and the
# builder's ordinary search tried every level the stair passes through.
DEEP_SURFACE = -80


def underground_only(traits: dict | None) -> bool:
    """(0.105.23) Surface -80 or lower: the fort lives under the ground."""
    return isinstance(traits, dict) and (traits.get("surface", 0) or 0) <= DEEP_SURFACE


def surface_elevation(memory, spine: dict | None = None) -> int | None:
    """(0.105.23) The elevation of the ground at the fort's way in: the
    surface entrance nearest the spine (the atlas keeps each entrance's
    elevation), else the lowest known surface entrance, else the top of the
    spine (the founding stair is dug down from the surface). None when
    nothing is known."""
    a = memory.atlas if isinstance(getattr(memory, "atlas", None), dict) else {}
    best, best_d = None, None
    for k, e in _d(a.get("entrances")).items():
        if not isinstance(e, dict) or e.get("kind") != "surface" or not isinstance(e.get("elevation"), int):
            continue
        d = 0
        if isinstance(spine, dict) and isinstance(spine.get("x"), int) and isinstance(spine.get("y"), int):
            try:
                x, y, _z = (int(v) for v in str(k).split(","))
            except ValueError:
                continue
            d = abs(x - spine["x"]) + abs(y - spine["y"])
        if best is None or d < best_d or (d == best_d and e["elevation"] < best):
            best, best_d = e["elevation"], d
    if best is not None:
        return best
    if isinstance(spine, dict) and isinstance(spine.get("top"), int):
        return spine["top"]
    return None


def ceiling(memory, traits: dict | None) -> int | None:
    """(0.105.23) The highest elevation a new level may use: one below the
    surface when the fort is underground only (Surface -80 or lower), else
    None (no limit). The plan's own ceiling when it was drawn with one.
    (0.105.29) The Hermit hold's `hidden_hold` custom too (the plan draw
    keeps `underground_only` only)."""
    if not (underground_only(traits) or customs.has(traits, "hidden_hold")):
        return None
    p = _peek(memory) if memory is not None else {}
    if isinstance(p.get("ceiling"), int):
        return p["ceiling"]
    surf = surface_elevation(memory, p.get("spine") if isinstance(p.get("spine"), dict) else None)
    if surf is None:
        sv = _d(_d((getattr(memory, "atlas", None) or {})).get("survey"))
        st = next((x for x in _l(_d(sv.get("site")).get("stairs")) if isinstance(x, dict)), None)
        if st and isinstance(st.get("elev_top"), int):
            surf = st["elev_top"]
    return surf - 1 if surf is not None else None


def _range(survey: dict, off: int, spine: dict, deep: bool = False) -> tuple[int, int] | None:
    """The elevations the plan may use: from the spine's top down to a few
    levels below its bottom, kept clear of every cavern above that. None
    when that leaves too little room. `off` is the survey's own elevation
    offset (the same one the spine's elevations came with)."""
    top = spine["top"]
    low = spine["bottom"] - (DEEP_EXTEND if deep else PLAN_EXTEND)
    for l in _l(survey.get("layers")):
        if isinstance(l, dict) and isinstance(l.get("z_top"), int) and str(l.get("name", "")).startswith("Cavern"):
            cav = l["z_top"] + off
            if cav < top:
                low = max(low, cav + CAVERN_MARGIN)
    if top - low + 1 < MIN_RANGE:
        return None
    return low, top


def _vertical(traits: dict) -> str:
    v = traits.get("verticality", 0) or 0
    return "deep" if v >= 40 else "flat" if v <= -40 else "balanced"


def _grammar(traits: dict, profile: dict) -> dict:
    g, sp, fo = (traits.get(k, 0) or 0 for k in ("grandeur", "spacing", "fortification"))
    # (0.104.107) never 1 wide: a fort of 300 jammed its 1-wide corridors
    return {"avenue": 3 if g >= 60 or sp >= 50 else 2,
            "corridors": "dog-leg" if fo >= 50 else "straight",
            "doors": "fortified" if fo >= 70 else ("doored" if profile.get("entry_doors") else "open")}


def _dirs_for(pattern: str, axis: str, index: int, kind: str) -> list[str]:
    """Which ways from the spine a district looks first."""
    forward, left, right, back = axis, _turn(axis, -1), _turn(axis, 1), _turn(axis, 2)
    if pattern == "stacked":
        return [forward]
    if pattern == "branching":
        # each district its own arm
        arm = [forward, left, right, back][index % 4]
        return [arm]
    if pattern == "rings":
        start = index % 4
        ring = [forward, right, back, left]
        return ring[start:] + ring[:start]
    # grid: homes and halls along the axis, work across it
    if kind in ("homes", "halls", "defence"):
        return [forward, back]
    return [left, right]


def draw(state: dict, memory, site: dict, traits: dict, profile: dict) -> dict | None:
    """Draw the plan from the survey and the fort's profile. None if the site
    isn't known well enough yet (no stair found)."""
    def whole(v):
        return isinstance(v, int) and not isinstance(v, bool)
    stairs = [s for s in _l(site.get("stairs")) if isinstance(s, dict)
              and all(whole(s.get(k)) for k in ("x", "y", "elev_top", "elev_bottom"))]
    sv = _d((memory.atlas or {}).get("survey"))
    off = site.get("elevation_offset")
    # the caverns must be known, and in the same terms as the stairs, or no plan yet
    if not stairs or not whole(off) or not isinstance(sv.get("layers"), list):
        return None
    st = stairs[0]
    spine = {"x": st["x"], "y": st["y"], "top": st["elev_top"], "bottom": st["elev_bottom"]}
    if spine["bottom"] > spine["top"]:
        return None
    heart = site.get("citizen_elevation")
    if not whole(heart):
        heart = (spine["top"] + spine["bottom"]) // 2
    vertical = _vertical(traits)
    rng = _range(sv, off, spine, deep=vertical == "deep")
    if rng is None:
        return None
    lo, hi = rng
    ceil = None
    if underground_only(traits):
        # (0.105.23) the Deep mine: the plan stops a level under the surface
        surf = surface_elevation(memory, spine)
        if surf is not None:
            ceil = surf - 1
            hi = min(hi, ceil)
            if hi - lo + 1 < MIN_RANGE:
                return None
    heart = max(lo, min(hi, heart))
    axis = _axis(memory, spine)
    pattern = profile.get("layout") if profile.get("layout") in ("grid", "rings", "branching", "stacked") else "grid"
    spread = 1 if (traits.get("spacing", 0) or 0) >= 50 else 0
    soil = sorted(e for e in _l(site.get("soil")) if isinstance(e, int)
                  and (ceil is None or e <= ceil))       # (0.105.23) no farm level at the surface either
    fort = traits.get("fortification", 0) or 0

    kinds = [k for k in STACK if k != "defence" or fort >= 30]
    bands: dict[str, list[int]] = {}
    if vertical == "flat":
        for k in kinds:
            bands[k] = [max(lo, heart - 1), min(hi, heart + 1)]
    else:
        height = 4 if (traits.get("verticality", 0) or 0) >= 100 else 3
        # each district its own band of levels; a deep fort leaves a level of rock between them
        step = height + (1 if vertical == "deep" else 0) + spread
        # too tall for the site: lower bands first, then closer ones (never overlapping more than a level)
        while (len(kinds) - 1) * step + height > hi - lo + 1 and (height > 1 or step > 1):
            if step > max(1, height - 1):
                step -= 1
            else:
                height -= 1
                step = min(step, max(1, height))
        # homes around the fort's heart; the others above and below in stack order
        order = list(kinds)
        at = order.index("homes")
        tops = {"homes": heart + height // 2}
        for i, k in enumerate(reversed(order[:at]), 1):      # above the homes: halls, then defence
            tops[k] = tops["homes"] + i * step
        for i, k in enumerate(order[at + 1:], 1):              # below: storage, industry
            tops[k] = tops["homes"] - i * step
        span_top = max(tops.values())
        span_bottom = min(tops.values()) - height + 1
        # squeeze into what the site allows
        shift = 0
        if span_top > hi:
            shift = hi - span_top
        if span_bottom + shift < lo:
            shift = lo - span_bottom
        for k in tops:
            tops[k] += shift
        for k in kinds:
            top = min(hi, tops[k])
            bands[k] = [max(lo, top - height + 1), top]
    # farms: where the soil is, nearest the heart
    if soil:
        best = min(soil, key=lambda e: abs(e - heart))
        bands["farms"] = [best, best]

    seed = (memory.culture or {}).get("seed") or "fort"
    palette = profile.get("palette") or "any"
    era = len((memory.culture or {}).get("eras") or [])
    naming = design.naming(memory.culture if isinstance(memory.culture, dict) else None)   # (D0) None at Scripts
    districts = []
    for i, k in enumerate(list(bands)):
        lo_k, hi_k = bands[k]
        districts.append({"id": k, "kind": k, "name": district_name(k, palette, seed, naming),
                          "lo": lo_k, "hi": hi_k, "target": (lo_k + hi_k + 1) // 2,
                          "dirs": _dirs_for(pattern, axis, i, k), "era": era, "levels": [], "missed": 0,
                          "wings": [{"era": era, "dir": _dirs_for(pattern, axis, i, k)[0]}]})
    slots = []
    if (traits.get("grandeur", 0) or 0) >= 0:
        slots.append({"kind": "great hall", "district": "halls"})
    if profile.get("temple") and profile.get("temple") != "none":
        slots.append({"kind": "temple", "district": "halls"})
    slots.append({"kind": "memorials", "district": "halls"})
    d = state.get("date") or {}
    plan = _plan(memory)
    plan.clear()
    plan.update({"v": 1, "drawn": f"{d.get('day')} {d.get('month')} y{d.get('year')}",
                 "tick": date_tick(d), "by": "scripts",
                 "spine": spine, "axis": axis, "pattern": pattern, "vertical": vertical,
                 "symmetry": (traits.get("grandeur", 0) or 0) >= 60 and (traits.get("craftsmanship", 0) or 0) >= 60,
                 "range": [lo, hi], "heart": heart, "grammar": _grammar(traits, profile), "formula": FORMULA,
                 "pop_at_draw": _d(state.get("dwarves")).get("total") or 0,
                 "districts": districts, "slots": slots, "era": era})
    if ceil is not None:
        plan["ceiling"] = ceil         # (0.105.23) underground only: hints never go above it
    return plan


# (D0) A design language's naming (design.TONES, design.PATTERNS): each tone
# its adjectives and, for some districts, its own nouns (else NOUNS).
TONE_ADJECTIVES = {"plain": ["Old", "Low", "Broad"], "solemn": ["Silent", "Hallowed", "Grey"],
                   "martial": ["Iron", "Unbroken", "Shielded"], "merry": ["Bright", "Golden", "Singing"],
                   "austere": ["Bare", "Stern", "Narrow"], "mythic": ["Ancient", "Starlit", "Endless"]}
TONE_NOUNS = {
    "solemn": {"homes": ["Quiet Cells", "Resting Halls"], "halls": ["Halls of Silence", "Vigil Halls"]},
    "martial": {"homes": ["Barrack Deeps", "Shield Hearths"], "defence": ["Iron Gate", "Last Wall"],
                "industry": ["War Forges", "Anvil Deeps"]},
    "merry": {"homes": ["Warm Hearths", "Merry Halls"], "halls": ["Feast Halls", "Singing Halls"]},
    "austere": {"homes": ["Cells", "Bare Halls"], "storage": ["Cellars", "Stores"]},
    "mythic": {"halls": ["Halls of Legend", "Star Halls"], "farms": ["Deep Gardens", "Root Halls"],
               "industry": ["Fire Deeps", "Workings"]},
}


def district_name(kind: str, palette: str, seed: str, naming: dict | None = None) -> str:
    """'the Dark Forges', 'the Pale Hearths': the fort's style and its seed.
    (D0) With a design language's naming: its tone's words and nouns, its own
    words and its pattern ('the Ashen Forges', 'the Forges of Ral', 'the
    Ashforges', "Ral's Forges"); with none, exactly as before."""
    if isinstance(naming, dict) and naming:
        return _named(kind, palette, seed, naming)
    nouns = NOUNS.get(kind) or [kind.title()]
    noun = nouns[_seed(seed, kind) % len(nouns)]
    adj = ADJECTIVES.get(palette, "")
    return f"the {adj} {noun}".replace("  ", " ") if adj else f"the {noun}"


def _named(kind: str, palette: str, seed: str, naming: dict) -> str:
    tone = naming.get("tone") if naming.get("tone") in TONE_ADJECTIVES else "plain"
    words = [w for w in naming.get("words") or [] if isinstance(w, str) and w.replace("'", "").isalpha()]
    nouns = (TONE_NOUNS.get(tone) or {}).get(kind) or NOUNS.get(kind) or [kind.title()]
    h = _seed(seed, kind, "naming")
    noun = nouns[h % len(nouns)]
    word = words[(h // 7) % len(words)] if words else None
    pattern = naming.get("pattern") or "adjective"
    if pattern == "of" and word:
        return f"the {noun} of {word}"
    if pattern == "possessive" and word:
        return f"{word}'s {noun}"
    if pattern == "compound" and word:
        last = noun.split()[-1]
        return " ".join(["the"] + noun.split()[:-1] + [word + last.lower()])
    adjs = TONE_ADJECTIVES[tone]
    adj = word or (ADJECTIVES.get(palette) if tone == "plain" and palette in ADJECTIVES else adjs[(h // 3) % len(adjs)])
    return f"the {adj} {noun}"


def open_slot(memory, kind: str) -> dict | None:
    """(0.98) The plan's place kept for this set piece, if nothing is built
    in it yet."""
    for sl in _l(_peek(memory).get("slots")):
        if isinstance(sl, dict) and sl.get("kind") == kind and not sl.get("built"):
            return sl
    return None


SLOT_OF = {"temple": "temple", "memorial": "memorials"}   # levels that fill a plan's set-piece place


def _district(memory, kind: str, slot: str | None = None) -> dict | None:
    if slot:
        sl = next((x for x in _l(_peek(memory).get("slots")) if isinstance(x, dict) and x.get("kind") == slot), None)
        want = sl.get("district") if sl else None
        for d in _l(_peek(memory).get("districts")):
            if isinstance(d, dict) and d.get("kind") == want:
                return d
    want = DISTRICT_OF.get(kind)
    for d in _l(_peek(memory).get("districts")):
        if isinstance(d, dict) and d.get("kind") == want:
            return d
    return None


def _district_of_kind(memory, dkind: str) -> dict | None:
    """(0.105.29) The plan's district of this kind ("halls", "farms"...)."""
    for d in _l(_peek(memory).get("districts")):
        if isinstance(d, dict) and d.get("kind") == dkind:
            return d
    return None


def _toward_way_in(memory, spine: dict) -> str | None:
    """(0.105.29) The direction from the spine to the nearest surface
    entrance (`_axis` reversed), or None when that entrance is within 2
    tiles of the spine or none is known (the founding stair is the way in)."""
    if not isinstance(spine, dict) or not isinstance(spine.get("x"), int) or not isinstance(spine.get("y"), int):
        return None
    a = memory.atlas if isinstance(getattr(memory, "atlas", None), dict) else {}
    best, best_d = None, None
    for k, e in _d(a.get("entrances")).items():
        if not isinstance(e, dict) or e.get("kind") != "surface":
            continue
        try:
            x, y, _z = (int(v) for v in str(k).split(","))
        except ValueError:
            continue
        d = abs(x - spine["x"]) + abs(y - spine["y"])
        if best_d is None or d < best_d:
            best, best_d = (x, y), d
    if best is None or best_d <= 2:
        return None
    dx, dy = best[0] - spine["x"], best[1] - spine["y"]      # spine -> entrance
    if abs(dx) >= abs(dy):
        return "east" if dx >= 0 else "west"
    return "south" if dy >= 0 else "north"


# (0.105.29 customs fixes) the top of each gate custom's band, in levels under
# the way in. The shelter keeps SHELTER_MARGIN_Z (2) levels round an unshut way
# in (lua/ai-society.lua): the tavern, a civilians' room, stays out of it
# (s-5 .. s-3); the barracks and range may take its last level (s-4 .. s-2):
# soldiers on duty are not held by the shelter, and s-1 (next to the way in,
# where an enemy comes in) is left to the gatehouse.
GATE_TOP = {"market_gate": 3, "gate_barracks": 2}
FIELD_TOP = 3       # field_hall / field_kitchens: no hall at or just under the surface (as the tavern)


def _gate_band(memory, traits: dict | None, gate: str = "market_gate") -> tuple[int, int, str | None] | None:
    """(0.105.29) The gate band: the GATE_BAND levels from GATE_TOP[gate]
    under the way in down, inside the plan's range and under any ceiling, as
    (lo, hi, toward); toward is the way from the spine to the way in (None:
    the founding stair is the way in). None when the surface isn't known."""
    p = _peek(memory)
    spine = p.get("spine") if isinstance(p.get("spine"), dict) else None
    s = surface_elevation(memory, spine)
    if s is None:
        return None
    rng = p.get("range") if isinstance(p.get("range"), list) and len(p["range"]) == 2 else [None, None]
    hi = s - GATE_TOP.get(gate, 3)
    if isinstance(rng[1], int):
        hi = min(hi, rng[1])
    ceil = ceiling(memory, traits)
    if ceil is not None:
        hi = min(hi, ceil)
    lo = hi - customs.GATE_BAND + 1
    if isinstance(rng[0], int):
        lo = max(lo, rng[0])
    if lo > hi:
        return None
    return lo, hi, _toward_way_in(memory, spine)


def _field_band(memory, farms: dict) -> tuple[int, int, int] | None:
    """(0.105.29 customs fixes) field_hall / field_kitchens: the farms
    district's band kept FIELD_TOP levels under the surface and inside the
    plan's range, as (lo, hi, target); None when none of it is (soil at or
    just under the surface: the custom doesn't apply)."""
    p = _peek(memory)
    spine = p.get("spine") if isinstance(p.get("spine"), dict) else None
    s = surface_elevation(memory, spine)
    if s is None or not isinstance(farms.get("lo"), int) or not isinstance(farms.get("hi"), int):
        return None
    rng = p.get("range") if isinstance(p.get("range"), list) and len(p["range"]) == 2 else [None, None]
    hi = min(int(farms["hi"]), s - FIELD_TOP)
    lo = int(farms["lo"])
    if isinstance(rng[1], int):
        hi = min(hi, rng[1])
    if isinstance(rng[0], int):
        lo = max(lo, rng[0])
    if lo > hi:
        return None
    tg = farms.get("target") if isinstance(farms.get("target"), int) else lo
    return lo, hi, max(lo, min(hi, tg))


def hint(memory, kind: str, slot: str | None = None, traits: dict | None = None,
         profile: dict | None = None, *, action: dict | None = None,
         citizens: int | None = None) -> dict | None:
    """The placement hint for a new level of this kind (lua/ai-builder.lua
    tries it first), or None when the plan has no district for it. slot: a
    set piece goes to its place's district (0.98: the great hall among the
    halls). traits and profile: the corridor grammar follows the fort as it
    is now, not as it was when the plan was drawn (0.98). (0.105.29) The
    fort's customs (customs.py) bend it first, the earned quirks after:
    action (the start_project, for its shops) and citizens (the fort's
    count) feed them; `out["customs"]` lists those applied (absent: none)."""
    p = _peek(memory)
    d = _district(memory, kind, slot)
    if not d or kind == "farms":
        return None                    # farm levels follow the soil (the builder's own search)
    applied: list[str] = []
    field = None                       # field_hall / field_kitchens: the farms band, clamped
    act = set(customs.active(traits)) if traits is not None else set()
    # (0.105.29) customs that send the level to another district
    if not slot:
        alt, cid = None, None
        if kind == "bedrooms" and "cells" in act:
            alt, cid = _district_of_kind(memory, "halls"), "cells"
        elif kind == "dining" and "deep_hall" in act and _district_of_kind(memory, "industry"):
            alt, cid = _district_of_kind(memory, "industry"), "deep_hall"
        elif kind == "dining" and "field_hall" in act:
            alt, cid = _district_of_kind(memory, "farms"), "field_hall"
        elif (kind == "workshops" and "field_kitchens" in act and isinstance(action, dict)
              and _l(action.get("shops")) and all(x in customs.FOOD_SHOPS for x in _l(action.get("shops")))):
            alt, cid = _district_of_kind(memory, "farms"), "field_kitchens"
        if alt is not None and (alt is d or alt.get("kind") == d.get("kind")):
            alt = None                 # (customs fixes) the default district already: nothing changed
        if alt and cid in ("field_hall", "field_kitchens"):
            field = _field_band(memory, alt)
            if field is None:
                alt = None             # no farms level 3 under the surface: the normal district
        if alt:
            d = alt
            applied.append(cid)
    spine = p.get("spine") or {}
    out = {"elev_lo": int(d["lo"]), "elev_hi": int(d["hi"]), "elev_target": int(d.get("target", d["lo"])),
           "district": _plain(d.get("name") or d["kind"])}
    if field:
        out["elev_lo"], out["elev_hi"], out["elev_target"] = field
    # (0.105.23) underground only (Surface -80 or lower): the band stops under
    # the surface, also for a plan drawn before (E's) or a district grown up
    ceil = ceiling(memory, traits)
    if ceil is not None:
        out["elev_hi"] = min(out["elev_hi"], ceil)
        out["elev_lo"] = min(out["elev_lo"], out["elev_hi"])
        out["elev_target"] = max(out["elev_lo"], min(out["elev_hi"], out["elev_target"]))
    if p.get("vertical") == "deep":
        out["extend"] = DEEP_EXTEND      # (0.105.14) the builder may take the stair this far down for it
    dirs = [x for x in (d.get("dirs") or []) if x in DIRS]
    if dirs:
        out["dirs"] = list(dict.fromkeys(dirs))[:4]
    if isinstance(spine.get("x"), int) and isinstance(spine.get("y"), int):
        out["spine"] = {"x": spine["x"], "y": spine["y"]}
    st = d.get("stair")
    if isinstance(st, dict) and isinstance(st.get("x"), int) and isinstance(st.get("y"), int):
        out["spine"] = {"x": st["x"], "y": st["y"]}      # (0.104.82) the district's own stairwell
    # (0.105.29) customs that put the level in the gate band, just under the way in
    aim = field[2] if field else None
    gate = None
    if kind == "tavern" and "market_gate" in act:
        gate = "market_gate"
    elif kind in ("barracks", "archery") and "gate_barracks" in act:
        gate = "gate_barracks"
    gb = _gate_band(memory, traits, gate) if gate else None
    if gb:
        lo, hi, toward = gb
        aim = hi                       # the band's top: as near the way in as the custom goes
        out["elev_lo"], out["elev_hi"], out["elev_target"] = lo, hi, aim
        if toward:
            out["dirs"] = list(dict.fromkeys([toward] + out.get("dirs", [])))[:4]
        applied.append(gate)
    # the corridor grammar (the builder applies it from bridge 0.33), as the quirks bend it
    g = _grammar(traits, profile or {}) if traits is not None else (p.get("grammar") or {})
    out["avenue"] = max(2, min(3, int(g.get("avenue") or 2)))     # (0.104.107) plans drawn before: 2 at least
    out["corridors"] = g.get("corridors") if g.get("corridors") in ("straight", "dog-leg") else "straight"
    if g.get("doors") in ("open", "doored", "fortified"):
        out["doors"] = g["doors"]
    culture = memory.culture if isinstance(memory.culture, dict) else {}

    def quirks(ways):
        """The earned quirks' last word on (avenue, corridors)."""
        if has_rule(culture, "narrow_ways"):            # Warren
            ways = (1, "dog-leg")
        if has_rule(culture, "great_shaft"):            # The Great Shaft: close around the stair
            ways = (3, ways[1])
        return ways
    # (0.105.29) customs of the ways (the earned quirks keep the last word);
    # (customs fixes) stamped only when they change the final ways
    plain = quirks((out["avenue"], out["corridors"]))
    ways = (out["avenue"], out["corridors"])
    for cid, on, new in (("wide_ways", "wide_ways" in act, (3, None)),
                         ("winding_ways", "winding_ways" in act and citizens is not None
                          and citizens <= customs.WINDING_MAX_CITIZENS, (1, "dog-leg"))):
        if on:
            ways = (new[0], new[1] or ways[1])
            if quirks(ways) != plain:
                applied.append(cid)
    out["avenue"], out["corridors"] = quirks(ways)
    if has_rule(culture, "great_shaft"):
        out["dirs"] = [p.get("axis")] if p.get("axis") in DIRS else out.get("dirs", [])[:1]
    # spread the district's levels through its band: the level used least so far
    used = [lv.get("elevation") for lv in d.get("levels") or [] if isinstance(lv, dict)]
    band = list(range(out["elev_lo"], out["elev_hi"] + 1))
    if band:
        out["elev_target"] = min(band, key=lambda e: (used.count(e), abs(e - (aim if aim is not None
                                                                      else out["elev_target"] if ceil is not None
                                                                      else d.get("target", e)))))
    if applied:
        out["customs"] = applied
    return out


def variety(memory, kind: str) -> dict:
    """A level's seeded details (lua/ai-layouts.lua, bridge 0.33): its
    orientation (0 as drawn, 1 mirrored east-west, 2 turned so the rooms run
    north-south, 3 both: a quarter turn) and the rhythm of its pillars (every
    3 to 6 tiles). Seeded by the fort, the kind and how many such levels the
    registry holds, so the same level gets the same details after a reload or
    a refused try. Mirror-minded forts only get 0 or 3 (never a mirror image)."""
    seed = (memory.culture or {}).get("seed") if isinstance(memory.culture, dict) else None
    reg = (memory.atlas or {}).get("registry") if isinstance(memory.atlas, dict) else None
    n = sum(1 for r in (reg or {}).values() if isinstance(r, dict) and r.get("kind") == kind)
    h = _seed(seed or "fort", kind, n)
    orient = h % 4
    if has_rule(memory.culture if isinstance(memory.culture, dict) else {}, "symmetric"):
        orient = 0 if orient in (0, 1) else 3     # as drawn, or turned a quarter: never a mirror image
    # (D0) the design language's symmetry: mirror as Mirror-minded, radial always as drawn
    sym = (design.current(memory.culture if isinstance(memory.culture, dict) else None) or {}).get("symmetry")
    if sym == "mirror":
        orient = 0 if orient in (0, 1) else 3
    elif sym == "radial":
        orient = 0
    return {"orient": orient, "rhythm": 3 + (h // 4) % 4}


def apply_quirks(memory) -> list[str]:
    """What the fort's quirks add to the plan (Last Stand: an inner keep's
    place beside the homes). Returns lines for the chronicle."""
    p = _plan(memory) if has_plan(memory) else None
    if not p:
        return []
    out = []
    culture = memory.culture if isinstance(memory.culture, dict) else {}
    slots = p.setdefault("slots", [])
    keep = any(isinstance(s, dict) and s.get("kind") == "inner keep" for s in slots)
    if has_rule(culture, "inner_keep") and not keep:
        slots.append({"kind": "inner keep", "district": "homes"})
        out.append("a place for an inner keep was set aside beside the homes")
    return out


def _plain(s: str) -> str:
    return "".join(c for c in s if c.isalnum() or c in " '-")[:40].strip() or "district"


def note_result(memory, action: dict, result: dict, state: dict) -> str | None:
    """After a start_project: which district got the level, or a miss. A
    district that keeps missing grows by GROW_BY levels when the site allows.
    Returns a line for the chronicle when a level opened a district or it grew."""
    if not isinstance(result, dict) or result.get("ok") is not True or action.get("type") != "start_project":
        return None
    if not isinstance(action.get("plan"), dict):
        return None                    # built without a hint (a mood's workshop, the strategist): not a miss
    # (0.105.29) the district the hint named (a custom may send a level elsewhere: cells, deep_hall)
    named = action["plan"].get("district")
    d = next((x for x in _l(_peek(memory).get("districts")) if isinstance(x, dict) and named
              and _plain(x.get("name") or x.get("kind") or "") == named), None) \
        or _district(memory, action.get("kind"), action.get("set_piece"))
    if not d:
        return None
    p = _plan(memory)
    # (0.98) a set piece built: its place in the plan is filled
    slot = action.get("set_piece") or SLOT_OF.get(action.get("kind"))
    sl = open_slot(memory, slot) if slot else None
    if sl is not None:
        sl["built"] = result.get("project_id") or True
    el = result.get("elevation")
    inside = result.get("in_district")
    if inside is None and isinstance(el, int):
        inside = d["lo"] <= el <= d["hi"]
    first = not d.get("levels")
    n = len(d.get("levels") or []) + 1
    d.setdefault("levels", []).append({"id": result.get("project_id"), "kind": action.get("kind"),
                                       "elevation": el, "in": bool(inside),
                                       "name": level_name(d, n)})
    del d["levels"][:-60]
    if inside:
        d["missed"] = 0
        if first:
            return f"the first level of {d['name']} was begun at elevation {el}"
        return None
    d["missed"] = d.get("missed", 0) + 1
    if d["missed"] >= GROW_AFTER_MISSES:
        lo, hi = p.get("range") or [d["lo"], d["hi"]]
        heart = p.get("heart", (lo + hi) // 2)
        mid = (d["lo"] + d["hi"]) / 2
        if mid <= heart and d["lo"] - GROW_BY >= lo:
            d["lo"] -= GROW_BY
        elif d["hi"] + GROW_BY <= hi:
            d["hi"] += GROW_BY
        elif d["lo"] - GROW_BY >= lo:
            d["lo"] -= GROW_BY
        else:
            d["missed"] = 0
            return None
        d["missed"] = 0
        return f"{d['name']} grew to elevations {d['lo']} to {d['hi']}"
    return None


def level_name(d: dict, n: int) -> str:
    """'the Third of the Dark Forges'."""
    o = ORDINALS[n - 1] if 1 <= n <= len(ORDINALS) else f"{n}th"
    return f"the {o} of {d.get('name') or 'the district'}"


def new_era(memory, era: int, profile: dict | None = None, traits: dict | None = None) -> list[str]:
    """A new era: each district opens a new wing (its next direction from the
    spine), so the era's work stands apart from the old. Returns lines.
    (0.98) The wing follows the fort as it is now: the layout pattern the
    engine picks today chooses its direction, and Depth now deepens (or
    flattens) each district's band by a level."""
    p = _plan(memory)
    if not p.get("districts"):
        return []
    if era < int(p.get("era", 0) or 0):
        # an older save: the later eras' wings never happened
        for d in p["districts"]:
            if isinstance(d, dict):
                d["wings"] = [w for w in d.get("wings") or [] if isinstance(w, dict) and w.get("era", 0) <= era]
                if d["wings"]:
                    first = d["wings"][-1]["dir"]
                    d["dirs"] = [first] + [x for x in d.get("dirs") or [] if x != first]
        p["era"] = era
        return []
    if era == int(p.get("era", 0) or 0):
        return []
    p["era"] = era
    out = []
    pattern = (profile or {}).get("layout")
    pattern = pattern if pattern in ("grid", "rings", "branching", "stacked") else p.get("pattern", "grid")
    vertical = _vertical(traits) if traits is not None else p.get("vertical")
    rng = p.get("range") if isinstance(p.get("range"), list) and len(p.get("range")) == 2 else [None, None]
    lo = rng[0]
    for i, d in enumerate(p["districts"]):
        if not isinstance(d, dict) or d.get("kind") == "farms":
            continue
        used = [w.get("dir") for w in d.get("wings") or [] if isinstance(w, dict)]
        prefer = _dirs_for(pattern, p.get("axis", "south"), i + era, d.get("kind"))
        ring = [_turn(p.get("axis", "south"), s) for s in (0, 1, 3, 2)]
        free = [x for x in prefer + ring if x not in used]
        if not free:
            continue
        nd = free[0]
        d.setdefault("wings", []).append({"era": era, "dir": nd, "pattern": pattern})
        d["dirs"] = [nd] + [x for x in d.get("dirs") or [] if x != nd]
        line = f"{d['name']} will grow a new wing to the {nd}" + (
            f", laid out {pattern}" if pattern != p.get("pattern") else "")
        # Depth acting after the plan: a deep fort's new wing goes a level deeper
        if vertical == "deep" and isinstance(lo, int) and d["lo"] - 1 >= lo:
            d["lo"] -= 1
            line += f", reaching down to elevation {d['lo']}"
        out.append(line)
    if pattern != p.get("pattern"):
        p["pattern_now"] = pattern
    return out


def needs_redraw(memory) -> bool:
    """A plan from an older formula that nothing has been built in yet."""
    p = _peek(memory)
    if not p.get("districts") or int(p.get("formula", 1) or 1) >= FORMULA:
        return False
    if any(d.get("levels") for d in p["districts"] if isinstance(d, dict)):
        return False
    # a level started with a hint whose answer was lost is still in the registry
    reg = (memory.atlas or {}).get("registry") if isinstance(memory.atlas, dict) else None
    return not any(isinstance(r, dict) and r.get("district") for r in (reg or {}).values())


def ensure(state: dict, memory, site: dict | None, traits: dict, profile: dict) -> list[str]:
    """Draw the plan once, when the survey knows the stairs (and again only
    when the formula changed before anything was built in it). Returns lines."""
    redraw = needs_redraw(memory)
    if (has_plan(memory) and not redraw) or not site:
        return []
    # (draw() changes the memory only once it has a plan: a None leaves the old one as it was)
    plan = draw(state, memory, site, traits, profile)
    if not plan:
        return []
    return [f"the master plan was {'redrawn' if redraw else 'drawn'}: {plan['pattern']} around the main stair "
            f"at x{plan['spine']['x']} y{plan['spine']['y']}, facing {plan['axis']}, {plan['vertical']}"]


def camera_districts(memory) -> list[dict]:
    """(0.104.90) The plan's districts by name and elevation, for the in-game
    camera's captions ("the meeting hall, in the Pale Hearths")."""
    out = []
    for d in _peek(memory).get("districts") or []:
        if isinstance(d, dict) and d.get("name") and isinstance(d.get("lo"), int) and isinstance(d.get("hi"), int):
            out.append({"name": str(d["name"])[:40], "lo": d["lo"], "hi": d["hi"]})
    return out[:12]


def lines(memory, limit: int = 9) -> list[str]:
    """The plan in words, for the panel and the strategist."""
    p = _peek(memory)
    if not p.get("districts"):
        return []
    g = p.get("grammar") or {}
    out = [f"{p.get('pattern')} plan, {p.get('vertical')}, around the main stair (x{p['spine']['x']} "
           f"y{p['spine']['y']}), facing {p.get('axis')}; avenues {g.get('avenue')} wide, "
           f"{g.get('corridors')} corridors, doors {g.get('doors')}"]
    slots = [s.get("kind") for s in p.get("slots") or [] if isinstance(s, dict) and s.get("kind")]
    if slots:
        out.append("places kept for: " + ", ".join(slots))
    for d in p["districts"]:
        if not isinstance(d, dict):
            continue
        n_in = sum(1 for lv in d.get("levels") or [] if lv.get("in"))
        span = f"elevation {d['lo']}" if d["lo"] == d["hi"] else f"elevations {d['lo']} to {d['hi']}"
        out.append(f"{d['name']} ({WORDS.get(d['kind'], d['kind'])}): {span}, "
                   f"{'/'.join(d.get('dirs') or []) or 'by the stair'}"
                   + (f", {n_in} level{'s' if n_in != 1 else ''}" if n_in else ""))
    return out[:limit]


def brief(memory) -> str:
    """One short line for the strategist."""
    p = _peek(memory)
    if not p.get("districts"):
        return ""
    parts = [f"{d['kind']} {d['lo']}..{d['hi']} {'/'.join((d.get('dirs') or [])[:2])}"
             for d in p["districts"] if isinstance(d, dict)]
    return f"{p.get('pattern')}/{p.get('vertical')} facing {p.get('axis')}: " + "; ".join(parts)


# --- stairwells (0.104.82) -----------------------------------------------------------

def stairwell_district(memory) -> dict | None:
    """The district to give a stairwell next: not the farms (they follow the
    soil) nor the homes (around the main stair), one without a stairwell,
    those with the most levels built first, then in the plan's order."""
    ds = [d for d in _l(_peek(memory).get("districts"))
          if isinstance(d, dict) and d.get("kind") not in ("farms", "homes") and not d.get("stair")
          and [x for x in (d.get("dirs") or []) if x in DIRS]]
    if not ds:
        return None
    order = {id(d): i for i, d in enumerate(ds)}
    return sorted(ds, key=lambda d: (-len(_l(d.get("levels"))), order[id(d)]))[0]


def note_stairwell(memory, district: str, x: int, y: int) -> None:
    for d in _l(_peek(memory).get("districts")):
        if isinstance(d, dict) and d.get("id") == district:
            d["stair"] = {"x": int(x), "y": int(y)}
