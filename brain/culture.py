"""Fortress culture: how this fort builds, decided by the player's trait
sliders and shaped by what happens to the fort. Pure logic, no tokens.

    profile = profile_from(traits, history)

A profile is a small dict of style choices that the planner hands to the
builder with every new level (see docs/culture.md):

  hall        'plain' | 'rounded' | 'pillared'   shape of big rooms (and, from a design
              language: 'octagonal' | 'round' | 'cruciform' | 'nave')
  smooth      0-3   0 rough, 1 smooth floors, 2 floors and walls, 3 and engrave halls
  statues     0-4   statues per hall
  palette     'any' | 'dark' | 'light' | 'warm' | 'cool' | 'precious'   furniture stone,
              'purpose' (a stone per kind of furniture) | 'wood' (wood where it will do)
  entry_doors bool  a door where each new level joins the fort
  temple      'none' | 'shrine' | 'grand'
  memorials   names of slain great beasts still waiting for a memorial hall

History (kept per fort) nudges the effective traits: sieges make the fort more
fortified, slain beasts make it prouder, deaths make it more devout. When the
style changes, a new era starts; the eras are the fort's architectural story.
"""

from __future__ import annotations

import colorsys
import copy
import pickle
import re

from weights import areas, choose_all, why_text

HALLS = ("plain", "rounded", "pillared", "octagonal", "round", "cruciform", "nave")   # (D0) + the Design track's 4
HALL_TITLES = {"plain": "Plain", "rounded": "Rounded", "pillared": "Pillared", "octagonal": "Octagonal",
               "round": "Round", "cruciform": "Cruciform", "nave": "Vaulted"}
HALL_GUIDE = {"plain": "Square, practical rooms", "rounded": "Halls with rounded corners",
              "pillared": "Grand pillared halls", "octagonal": "Eight-sided halls", "round": "Round halls",
              "cruciform": "Cross-shaped halls", "nave": "Long vaulted halls with pillared aisles"}
PALETTES = ("any", "dark", "light", "warm", "cool", "precious", "purpose", "wood")
# "Stone by purpose": which tone each kind of furniture is made in.
PURPOSE = {"Door": "dark", "Armorstand": "dark", "Weaponrack": "dark", "Table": "warm", "Chair": "warm",
           "Coffin": "light", "Statue": "light", "Bookcase": "cool"}
TEMPLES = ("none", "shrine", "grand")
STYLE_GUIDE_MAX = 400
MAX_ERAS = 12

# Creatures whose death earns a memorial hall.
GREAT_BEASTS = ("Forgotten Beast", "Titan", "Colossus", "Dragon", "Hydra", "Roc", "Demon")


def is_great_beast(e: dict) -> bool:
    """The game's own "great danger" flag when the bridge sends it; otherwise
    whole words of the creature type (so a "Giant Dragonfly" is not a dragon)."""
    if "great" in e:
        return e["great"] is True
    kind = (e.get("name") or "").split(",")[-1]
    words = set(re.findall(r"[A-Za-z]+", kind))
    return any(set(b.split()) <= words for b in GREAT_BEASTS)


def new_history() -> dict:
    return {"beasts_slain": [], "sieges": 0, "citizen_deaths": 0, "memorials_built": [],
            "eras": [], "overrides": {}, "guide": ""}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def beast_name(full: str) -> str:
    """'Shulmik Soshoshritas "Jackalowls", Forgotten Beast' -> 'Shulmik the Jackalowls'.
    Only letters, spaces and apostrophes survive (it ends up in a zone name)."""
    m = re.match(r'\s*([^"]+?)\s*"([^"]+)"', full or "")
    epithet = re.sub(r"(?i)^the\s+", "", m.group(2).strip()) if m else ""
    name = f"{m.group(1).split()[0]} the {epithet}" if m else (full or "").split(",")[0]
    name = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z' ]", "", name)).strip()
    return name[:40].strip() or "the Nameless"


def note_events(history: dict, events: list[dict]) -> list[str]:
    """Record the events that shape culture. Returns what changed, in words."""
    changed = []
    for e in events:
        kind, name = e.get("kind"), e.get("name") or ""
        if kind == "invasion":
            history["sieges"] = history.get("sieges", 0) + 1
            if isinstance(e.get("year"), int):
                history["last_siege_year"] = e["year"]      # (Grudge-keepers fade 3 years after)
            changed.append("a siege hardened the fort")
        elif kind == "death" and e.get("own_civ") and not e.get("animal") and not e.get("again"):
            history["citizen_deaths"] = history.get("citizen_deaths", 0) + 1
        elif kind == "death" and e.get("hostile") and is_great_beast(e) and '"' in name:
            # only named beasts (forgotten beasts, titans, megabeasts): not
            # every unnamed demon or night creature gets a hall
            n = beast_name(name)
            if n not in history.setdefault("beasts_slain", []):
                history["beasts_slain"].append(n)
                changed.append(f"{n} was slain and will be remembered")
    return changed


def effective_traits(traits: dict, history: dict) -> dict:
    """The sliders plus what the fort has lived through (each push is capped;
    brain/leanings.py history_pushes). The weights engine adds these itself,
    with its own leanings and the site's (0.95); this is for the direct
    effects that read them (spacing: a besieged fort huddles closer)."""
    from leanings import history_pushes
    t = dict(traits or {})
    for k, b in history_pushes(history or {}).items():
        t[k] = _clamp(t.get(k, 0) + b, -200, 200)
    return t


# (r33) profile_from is pure and a plan() asks for it 2-6 times with the same
# sliders and history: the answer is kept by the CONTENT of its inputs, never
# by which dict was passed (callers change memory.culture between calls). The
# key is the inputs' pickle: the same bytes only for the same values of the
# same types (a tuple is not a list, 1 is not 1.0 or True, "1" is not 1 as a
# key); the same values in another order only miss. Each caller gets its own
# copy, free to change it; the kept one shares nothing with the inputs.
_PROFILE_CACHE: dict = {}
_PROFILE_CACHE_MAX = 64


def profile_from(traits: dict, history: dict | None = None) -> dict:
    """The style choices for new building, made by the weights engine
    (brain/weights.py, brain/choices.json), plus the direct effects.
    Kept by the inputs' content (see _PROFILE_CACHE); always a fresh copy."""
    from weights import data
    try:
        key = pickle.dumps((traits, history, data().get("settings")), protocol=4)
    except Exception:  # noqa: BLE001  (something that can't be pickled: worked out, not kept)
        key = None
    if key is not None:
        hit = _PROFILE_CACHE.get(key)
        if hit is None:
            hit = copy.deepcopy(_profile_from(traits, history))   # (shares nothing with the inputs)
            if len(_PROFILE_CACHE) >= _PROFILE_CACHE_MAX:
                _PROFILE_CACHE.pop(next(iter(_PROFILE_CACHE)))
            _PROFILE_CACHE[key] = hit
        return _copy(hit)
    return _profile_from(traits, history)


_PLAIN = (str, int, float, bool, type(None))


def _copy(profile: dict) -> dict:
    """A copy the caller may change: the plain values as they are, the rest
    (the memorials, a strategist's value) copied deep."""
    return {k: v if type(v) in _PLAIN else copy.deepcopy(v) for k, v in profile.items()}


def _profile_from(traits: dict, history: dict | None = None) -> dict:
    h = history or new_history()
    t = effective_traits(traits, h)
    profile = {c["key"]: c["value"] for c in choose_all(traits, h).values()}
    profile["spacing"] = _clamp(t.get("spacing", 0), -200, 200)      # a direct effect, not a choice
    profile["memorials"] = [b for b in h.get("beasts_slain", []) if b not in h.get("memorials_built", [])]
    # The strategist may have set some choices itself (checked when it did).
    # Each one holds only while the sliders still give what they gave when it
    # was set: move a slider, and that choice is yours again.
    for k, ov in ai_choices(profile, h).items():
        profile[k] = ov.get("value")
    # (D0) the fort's design language, last (none at Scripts: nothing changes)
    import design
    design.apply(profile, h, traits)
    return profile


def ai_choices(profile: dict, history: dict) -> dict:
    """The strategist's choices that still hold: {profile key: override}."""
    return {k: ov for k, ov in (history.get("overrides") or {}).items()
            if k in profile and k != "memorials" and isinstance(ov, dict) and profile[k] == ov.get("base")}


def explain(traits: dict, history: dict | None = None) -> list[dict]:
    """Each area's choice for the panel and the strategist:
    {area, name, choice, why, by_ai, later}."""
    h = history or new_history()
    chosen = choose_all(traits, h)
    base = {c["key"]: c["value"] for c in chosen.values()}
    ai = ai_choices(base, h)
    out = []
    for a, c in chosen.items():
        ov = ai.get(c["key"])
        if ov:
            opt = next((o for o in areas()[a]["options"].values() if o["value"] == ov.get("value")), None)
            out.append({"area": a, "name": c["name"], "choice": opt["label"] if opt else str(ov.get("value")),
                        "why": ov.get("reason") or "chosen by the AI strategist", "by_ai": True,
                        "later": c["later"]})
        else:
            out.append({"area": a, "name": c["name"], "choice": c["label"], "why": why_text(c),
                        "by_ai": False, "later": c["later"]})
    return out


STYLE_KEYS = ("hall", "smooth", "statues", "palette", "entry_doors", "temple")

# How a fort closes a wide opening (lua/ai-gates.lua fortify; the weights
# engine's Defence area picks one): plain, walls with a 2-tile gap (1 to a
# cavern) and doors in it; narrow, a 1-tile gap and one door; fortified, two
# doors one behind the other; gatehouse, fortified plus cage traps behind it;
# grand, a 2-tile gap, 2 doors, statues inside; drawbridge, a 2-tile gap closed
# by a raising drawbridge and its lever. Walls first, doors once the walls
# beside them stand (DF builds a door only next to a wall).
GATE_STYLES = ("plain", "narrow", "fortified", "gatehouse", "grand", "drawbridge")


def era_title(p: dict) -> str:
    shape = HALL_TITLES.get(p["hall"]) or str(p["hall"]).title()
    finish = ["Rough", "Smoothed", "Polished", "Engraved"][p["smooth"]]
    tone = {"any": "", "dark": "Dark ", "light": "Pale ", "warm": "Warm ", "cool": "Cool ",
            "precious": "Gilded ", "purpose": "Crafted ", "wood": "Timbered "}.get(p["palette"], "")
    title = f"{tone}{finish} {shape} era".replace("  ", " ")
    name = (p.get("design") or {}).get("name") if isinstance(p.get("design"), dict) else None
    return f"{name}: {title}" if name else title      # (D0) the design language's own name first


def update_eras(history: dict, profile: dict, year: int) -> str | None:
    """Start a new era when the style changes. Returns the new era's title."""
    eras = history.setdefault("eras", [])
    style = {k: profile[k] for k in STYLE_KEYS}
    if eras and eras[-1].get("style") == style:
        return None
    title = era_title(profile)
    eras.append({"year": year, "title": title, "style": style})
    del eras[:-MAX_ERAS]
    return title


def style_guide(profile: dict, stone_name: str | None = None, history: dict | None = None) -> str:
    """The written style guide: the strategist's own if it wrote one, else
    generated from the profile."""
    if history and history.get("guide"):
        return history["guide"][:STYLE_GUIDE_MAX]
    p = profile
    parts = []
    parts.append(HALL_GUIDE.get(p["hall"]) or f"{p['hall']} halls".capitalize())
    parts.append(["left as rough rock", "with smoothed floors", "with smoothed floors and walls",
                  "smoothed and richly engraved"][p["smooth"]])
    s = "; ".join(parts)
    if p["statues"]:
        s += f"; {p['statues']} statue{'s' if p['statues'] > 1 else ''} in every hall"
    if p["palette"] == "purpose":
        s += ". Each kind of furniture in its own stone: dark doors, warm tables, pale coffins"
    elif p["palette"] == "wood":
        s += ". Furniture in wood where wood will do"
    elif p["palette"] != "any":
        s += f". Furniture in {p['palette']} stone" + (f" ({stone_name})" if stone_name else "")
    if p["entry_doors"]:
        s += ". Every level is closed off by a door"
    s += ". " + {"plain": "Entrances are walled to a plain doorway",
                 "narrow": "Entrances are walled to a single narrow door",
                 "fortified": "Entrances have two doors, one behind the other",
                 "gatehouse": "Entrances are gatehouses: double doors and cage traps",
                 "grand": "Entrances are grand double doors flanked by statues",
                 "drawbridge": "Entrances are walled to drawbridges, worked by levers deep inside"}[p.get("gate", "plain")]
    if p["temple"] != "none":
        s += f". The gods have a {'grand temple' if p['temple'] == 'grand' else 'shrine'}"
    if p["memorials"]:
        s += ". Memorial halls honour " + ", ".join(p["memorials"][:3])
    return (s + ".")[:STYLE_GUIDE_MAX]


# --- the material picker ----------------------------------------------------------

def _tone(rgb) -> dict:
    r, g, b = (float(c) for c in (list(rgb) + [0, 0, 0])[:3])
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    deg = hue * 360
    return {"dark": light < 0.3, "light": light > 0.7,
            "warm": sat > 0.2 and (deg < 60 or deg > 330),
            "cool": sat > 0.2 and 150 <= deg <= 270}


def stone_for(stones: list[dict], palette: str, kind: str, need: int = 20,
              by_kind: dict | None = None, signature: str | None = None) -> dict | None:
    """The stone for one kind of furniture: the design language's tone for
    this kind (by_kind), then its signature stone when `need` of it is on
    hand, then by purpose, or the fort's one stone."""
    tone = (by_kind or {}).get(kind) if isinstance(by_kind, dict) else None
    if tone:
        hit = pick_stone(stones, tone, need)
        if hit:
            return hit
    if signature:
        hit = next((s for s in stones or [] if isinstance(s, dict) and s.get("token") == signature
                    and (s.get("count") or 0) >= need), None)
        if hit:
            return hit
    if palette == "purpose":
        return pick_stone(stones, PURPOSE.get(kind, "any"), need)
    return pick_stone(stones, palette, need)


def pick_stone(stones: list[dict], palette: str, need: int = 20) -> dict | None:
    """Choose the fort's signature stone from what's in stock.
    stones: [{token, name, count, rgb, value}]. Only stone with at least
    `need` boulders is considered, so furniture orders won't stall."""
    ok = [s for s in stones or [] if isinstance(s, dict) and s.get("token")
          and (s.get("count") or 0) >= need]
    if not ok:
        return None
    if palette == "precious":
        return max(ok, key=lambda s: (s.get("value") or 0, s["count"]))
    if palette in ("dark", "light", "warm", "cool"):
        fit = [s for s in ok if _tone(s.get("rgb") or (0.5, 0.5, 0.5))[palette]]
        if fit:
            return max(fit, key=lambda s: s["count"])
    return max(ok, key=lambda s: s["count"])


# --- checking what the strategist asks for ------------------------------------------------

def check_style(obj) -> tuple[dict, list[str]]:
    """The strategist's set_style action -> (accepted fields, rejections).
    Fields: guide (text), hall, palette, temple, gate, smooth, statues,
    entry_doors, and reason (why it goes against the sliders; shown on the panel)."""
    out, rejected = {}, []
    if not isinstance(obj, dict):
        return out, ["set_style: not an object"]
    for k, v in obj.items():
        if k == "type":
            continue
        if k == "guide":
            if isinstance(v, str) and v.strip():
                # plain words only: it's shown in the game's panel
                out["guide"] = re.sub(r"[^\w .,;:'()!?-]", "", v)[:STYLE_GUIDE_MAX].strip()
            else:
                rejected.append("set_style: guide must be text")
        elif k == "reason":
            if isinstance(v, str) and v.strip():
                out["reason"] = re.sub(r"[^\w .,;:'()!?+-]", "", v)[:160].strip()
        elif (k == "hall" and v in HALLS or k == "palette" and v in PALETTES or k == "temple" and v in TEMPLES
              or k == "gate" and v in GATE_STYLES):
            out[k] = v
        elif k in ("smooth", "statues") and isinstance(v, int) and not isinstance(v, bool):
            out[k] = _clamp(v, 0, 3 if k == "smooth" else 4)
        elif k == "entry_doors" and isinstance(v, bool):
            out[k] = v
        else:
            rejected.append(f"set_style: {k}={v!r} is not allowed")
    return out, rejected


def apply_style(history: dict, accepted: dict, traits: dict | None = None) -> None:
    """Store the strategist's choices, each with what the sliders gave at the
    time (see profile_from)."""
    if "guide" in accepted:
        history["guide"] = accepted["guide"]
    if not isinstance(history.get("overrides"), dict):     # the save turns an empty {} into []
        history["overrides"] = {}
    over = history["overrides"]
    # (D0) what the sliders give, before the design language (profile_from compares there)
    base = profile_from(traits or {}, {k: v for k, v in dict(history, overrides={}).items() if k != "design"})
    reason = accepted.get("reason") or ""
    for k, v in accepted.items():
        if k not in ("guide", "reason"):
            over[k] = {"value": v, "base": base.get(k), "reason": reason}


def layout_style(profile: dict, kind: str | None = None) -> dict:
    """What the builder needs for one new level. (D0) With a design language
    (profile["design"]) the new keys too (design.style_fields); a kind in its
    emphasis gets a statue more and engraved halls, within one step."""
    out = {"hall": profile["hall"], "smooth": profile["smooth"], "statues": profile["statues"],
           "entry_door": bool(profile["entry_doors"]), "spacing": int(profile.get("spacing", 0))}
    if isinstance(profile.get("design"), dict):
        import design
        extra = design.style_fields(profile, kind)
        if extra.get("grand"):
            out["statues"] = min(4, int(out["statues"] or 0) + 1)
            out["smooth"] = min(3, int(out["smooth"] or 0) + 1)
        out.update(extra)
    return out
