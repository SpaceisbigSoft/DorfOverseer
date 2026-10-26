"""The weights engine: how the fort's sliders, history and quirks become
choices in each decision area. Pure logic, no tokens (see docs/culture.md).

    result = choose("halls", traits, history)
    every  = choose_all(traits, history)

The areas, options and affinities live in brain/choices.json (data, not
code). An option's score is

    bias + sum(affinity x (slider + leanings) / 100)
         + sum(history weight x count, capped) + quirk bonuses

The leanings (0.95, brain/leanings.py) are the fort's own (seeded), the
site's and its history's pushes, each shown in the "why" with its reason.

The top option wins. Two things keep forts individual but steady:

  * a close call (the runner-up within `near` of the top) is settled by a
    number seeded from the fort, so two forts with the same sliders differ a
    little, but the same fort always gets the same answer;
  * a choice already made is kept until a new option beats it by
    `stickiness`, so small slider nudges don't flip the fort's style.
Quirks can change both (Restless: changes readily; Traditionalist: rarely).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent / "choices.json"

TRAIT_NAMES = {     # (0.94) the panel's names
    "greed": "Greed", "outsiders": "Outsiders", "caution": "Caution",
    "piety": "Piety", "industriousness": "Industry", "craftsmanship": "Craft",
    "surface": "Surface", "size": "Room size", "spacing": "Spacing", "verticality": "Depth",
    "grandeur": "Grandeur", "fortification": "Fortification", "mining": "Mining ambition",
    "engineering": "Engineering", "trade": "Trade focus", "stockpile": "Reserves",
    "agriculture": "Farming", "husbandry": "Animals", "militarism": "Militarism",
    "growth": "Growth", "welfare": "Welfare", "deference": "Noble deference", "justice": "Justice",
}
HISTORY_NAMES = {"sieges": ("siege", "sieges"), "beasts_slain": ("great beast slain", "great beasts slain"),
                 "citizen_deaths": ("citizen death", "citizen deaths")}

_DATA: dict | None = None
EXPLORE_AREAS = ("defence", "traps")    # where the AI tries designs it hasn't proved yet
EXPLORE_GAP = 0.25                      # only a runner-up this close is "promising"


def data() -> dict:
    global _DATA
    if _DATA is None:
        _DATA = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return _DATA


def areas() -> dict:
    return data()["areas"]


def history_counts(history: dict | None) -> dict:
    h = history or {}
    return {"sieges": int(h.get("sieges", 0) or 0),
            "beasts_slain": len(h.get("beasts_slain") or []),
            "citizen_deaths": int(h.get("citizen_deaths", 0) or 0)}


def held_quirks(history: dict | None) -> list[str]:
    q = (history or {}).get("quirks")
    return [k for k in q if k in data()["quirks"]] if isinstance(q, dict) else []


def _slider(traits: dict, k: str) -> float:
    try:
        return max(-200.0, min(200.0, float((traits or {}).get(k, 0) or 0)))
    except (TypeError, ValueError):
        return 0.0


def score_area(area_id: str, traits: dict, history: dict | None = None,
               quirks: list[str] | None = None) -> list[dict]:
    """Every option of an area with its score and what made it, best first."""
    area = areas()[area_id]
    counts = history_counts(history)
    quirks = held_quirks(history) if quirks is None else quirks
    learned = (history or {}).get("learned")
    learned = learned.get(area_id) if isinstance(learned, dict) else None
    design = (history or {}).get("design")
    design = design.get(area_id) if isinstance(design, dict) else None
    from leanings import extras         # (here: leanings imports this module)
    extra = extras(history)
    out = []
    for oid, o in area["options"].items():
        parts = []          # (text, amount)
        score = float(o.get("bias", 0))
        for s, a in (o.get("sliders") or {}).items():
            v = _slider(traits, s)
            if v and a:
                score += a * v / 100
                parts.append((f"{TRAIT_NAMES.get(s, s)} {int(v):+d}", a * v / 100))
            # (0.95) the fort's own leaning, the site's and its history, on
            # top of your slider (the sum kept within -200..200)
            room_hi, room_lo = 200 - v, -200 - v
            for label, d in extra:
                e = d.get(s)
                if not e or not a:
                    continue
                e = max(room_lo, min(room_hi, float(e)))
                room_hi, room_lo = room_hi - e, room_lo - e
                if e:
                    score += a * e / 100
                    parts.append((f"{label} ({TRAIT_NAMES.get(s, s)} {int(e):+d})", a * e / 100))
        for k, (w, cap) in (o.get("history") or {}).items():
            n = min(counts.get(k, 0), cap)
            if n:
                score += w * n
                one, many = HISTORY_NAMES.get(k, (k, k))
                parts.append((f"{n} {one if n == 1 else many}", w * n))
        for q in quirks:
            bonus = ((data()["quirks"][q].get("weights") or {}).get(area_id) or {}).get(oid)
            if bonus:
                score += bonus
                parts.append((data()["quirks"][q]["name"], bonus))
        # what the AI learned from you (brain/learning.py): it leans away from what you turned down
        lean = learned.get(oid) if isinstance(learned, dict) else None
        if isinstance(lean, (int, float)) and lean:
            score += lean
            parts.append(("you turned this down", lean))
        # how this design held up in sieges (brain/defence.py), here and in your other forts
        rec = design.get(oid) if isinstance(design, dict) else None
        if isinstance(rec, list) and len(rec) == 2 and isinstance(rec[0], (int, float)) and rec[0]:
            score += rec[0]
            parts.append((str(rec[1]), rec[0]))
        out.append({"id": oid, "label": o["label"], "value": o["value"], "score": round(score, 4),
                    "parts": parts})
    out.sort(key=lambda r: -r["score"])
    return out


def _seeded(seed: str, area_id: str) -> float:
    """A number in [0, 1) fixed for this fort and area."""
    h = hashlib.sha256(f"{seed}|{area_id}".encode()).hexdigest()
    return int(h[:8], 16) / 0x100000000


def _setting(name: str, quirks: list[str]) -> float:
    v = data()["settings"][name]
    for q in quirks:                      # a quirk that sets it wins (the first held one)
        qd = data()["quirks"][q]
        if name in qd:
            return float(qd[name])
    return float(v)


def choose(area_id: str, traits: dict, history: dict | None = None) -> dict:
    """The area's choice: {area, name, key, id, value, label, score, drivers,
    kept, runner_up}. drivers: up to 3 texts for what pushed it most."""
    h = history or {}
    quirks = held_quirks(h)
    ranked = score_area(area_id, traits, h, quirks)
    top = ranked[0]
    pick = top
    seed = h.get("seed")
    near = _setting("near", quirks)
    if seed and len(ranked) > 1 and near > 0:
        gap = top["score"] - ranked[1]["score"]
        if gap < near and _seeded(str(seed), area_id) < 0.5 * (1 - gap / near):
            pick = ranked[1]
    kept = False
    trying = False
    # defence designs: now and then a promising one is tried instead of the
    # best-known (how often: Caution, brain/defence.py), seeded by the year so
    # a reload never changes it. Never one that has failed more than it held.
    ex = h.get("explore") if isinstance(h.get("explore"), dict) else None
    if (ex and area_id in EXPLORE_AREAS and seed and len(ranked) > 1
            and isinstance(ex.get("rate"), (int, float)) and ex["rate"] > 0):
        alt = next((r for r in ranked if r is not pick), None)
        bad = any(amt < 0 and "siege" in t for t, amt in alt["parts"]) if alt else True
        if (alt and not bad and pick["score"] - alt["score"] < EXPLORE_GAP
                and _seeded(f"{seed}|{ex.get('turn')}", area_id + ":try") < ex["rate"]):
            pick, trying = alt, True
    current = h.get("choices") if isinstance(h.get("choices"), dict) else {}
    current = current.get(area_id)
    cur = next((r for r in ranked if r["id"] == current), None)
    if (not trying and cur and cur is not pick
            and pick["score"] - cur["score"] < _setting("stickiness", quirks)):
        pick, kept = cur, True
    drivers = [t for t, amt in sorted(pick["parts"], key=lambda p: -p[1]) if amt > 0][:3]
    if trying:
        drivers = ["trying something new this year (Caution)"] + drivers[:2]
    area = areas()[area_id]
    avoided = [r["label"] for r in ranked if any(t == "you turned this down" for t, _ in r["parts"])]
    return {"area": area_id, "name": area["name"], "key": area["key"], "id": pick["id"],
            "value": pick["value"], "label": pick["label"], "score": pick["score"],
            "drivers": drivers, "kept": kept, "trying": trying, "later": area.get("later"), "avoided": avoided,
            "runner_up": next((r["label"] for r in ranked if r is not pick), None)}


def choose_all(traits: dict, history: dict | None = None) -> dict:
    return {a: choose(a, traits, history) for a in areas()}


def why_text(c: dict) -> str:
    """'Grandeur +150, Craftsmanship +40' or why it's the default."""
    if c["kept"]:
        text = "kept: the sliders don't push hard enough to change it"
    else:
        text = ", ".join(c["drivers"]) or "the default: no slider leans another way"
    if c.get("avoided"):
        text += "; leaning away from " + ", ".join(a.lower() for a in c["avoided"][:2]) + " (you turned it down)"
    return text
