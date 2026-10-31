"""The fort's own leanings and the site's leanings (phase 14.1, 0.95): what
makes a fort left at default sliders still its own (Design Notes, "Fort
identity", 3b). Pure logic, no tokens.

    own  = own_leanings(seed)              {trait: -15..+15}, fixed for the fort
    site = site_leanings(state)            [{"trait", "amount", "why"}]
    all_ = extras(history)                 [(label, {trait: amount})] for the engine

Both lean the weights engine (brain/weights.py) on top of your sliders, and
are shown with their reasons: in each choice's "why" on the Culture page and
on the "Leans:" line under the selected slider. They never touch the
planner's direct effects (your soldier share, population target, reserves
and the rest stay exactly what you set): they decide the close calls of
style, so two forts with the same sliders build differently.

They're kept in the fort's culture history (the save):
  leanings  {"own": {trait: n}, "site": [{"trait", "amount", "why"}]}
The own leaning is drawn once from the fort's seed and never changes; the
site's are read again from each full report (a cavern found, a war declared)
and keep the last known when a report section is missing.
"""

from __future__ import annotations

import hashlib

from weights import TRAIT_NAMES

OWN_MAX = 15            # an own leaning is at most this, either way
SITE_MAX = 20           # the site's leanings on one trait, summed, at most this
# Your targets, not character: never leaned (the planner reads them directly)
NOT_LEANED = ("militarism", "growth")

PRECIOUS = ("GOLD", "SILVER", "PLATINUM", "ALUMINUM")
WAR_WORDS = ("war",)


def own_leanings(seed: str) -> dict:
    """Each trait's own leaning for this fort, -15..+15, from its seed: the
    same fort always gets the same numbers."""
    out = {}
    for tid in TRAIT_NAMES:
        if tid in NOT_LEANED:
            continue
        h = hashlib.sha256(f"{seed}|lean|{tid}".encode()).hexdigest()
        n = round((int(h[:8], 16) / 0xFFFFFFFF) * 2 * OWN_MAX - OWN_MAX)
        if n:
            out[tid] = int(n)
    return out


def _d(x):
    return x if isinstance(x, dict) else {}


def _l(x):
    return x if isinstance(x, list) else []


def site_leanings(state: dict) -> list | None:
    """What the land and the neighbours lean the fort toward, with why. None
    when the report has none of the sections it reads (keep the old ones)."""
    have = [k for k in ("industry", "water", "deep", "map", "diplomacy") if isinstance(state.get(k), dict)]
    if not have:
        return None
    out = []

    def lean(trait, amount, why, short):
        out.append({"trait": trait, "amount": amount, "why": why, "short": short})

    # ore: a fort on rich ore leans to fine metal work and arms
    ores = _d(_d(state.get("industry")).get("ores"))
    tiles = {m: int(_d(v).get("tiles") or 0) for m, v in ores.items()}
    base = sum(n for m, n in tiles.items() if m in ("IRON", "COPPER", "TIN", "ZINC", "NICKEL", "LEAD", "BISMUTH"))
    if base >= 300:
        lean("craftsmanship", 10, "rich ore near the fort", "rich ore")
    precious = sum(n for m, n in tiles.items() if m in PRECIOUS)
    if precious >= 50:
        lean("greed", 10, "precious metal in the rock", "precious metal")
    # magma: a forge-born fort
    if int(_d(_d(state.get("water")).get("magma")).get("tiles") or 0) > 0:
        lean("craftsmanship", 5, "magma below", "magma")
        lean("engineering", 5, "magma below", "magma")
    # running water near the fort: water works
    for b in _l(_d(state.get("water")).get("bodies")):
        b = _d(b)
        if b.get("kind") in ("river", "surface") and int(b.get("tiles") or 0) >= 50 \
                and int(b.get("stagnant_share") or 0) < 50:
            lean("engineering", 10, "running water near the fort", "running water")
            break
    # caverns close under the fort: careful
    m = _d(state.get("map"))
    low = _d(m.get("dwarves")).get("z_bottom")
    if isinstance(low, int):
        for layer in _l(m.get("layers")):
            layer = _d(layer)
            if str(layer.get("name", "")).startswith("Cavern") and isinstance(layer.get("z_top"), int) \
                    and 0 <= low - layer["z_top"] <= 15:
                lean("caution", 10, "a cavern close under the fort", "a cavern below")
                break
            if str(layer.get("name", "")).startswith("Cavern") and isinstance(layer.get("z_top"), int) \
                    and layer["z_top"] >= low and _d(m.get("dwarves")).get("by_layer", {}).get(layer.get("name")):
                lean("caution", 10, "dwarves already at work in a cavern", "the caverns")
                break
    # the neighbours
    civs = [_d(c) for c in _l(_d(state.get("diplomacy")).get("civs"))]
    at_war = [c for c in civs if str(c.get("relation", "")).lower() in WAR_WORDS]
    goblins = [c for c in civs if c.get("race") == "GOBLIN"]
    if at_war:
        lean("fortification", 15, f"at war with {at_war[0].get('name') or 'a neighbour'}", "at war")
    elif goblins:
        lean("fortification", 10, "goblins in the world", "goblins")
    if any(c.get("race") == "ELF" for c in civs) and _d(state.get("diplomacy")).get("elves"):
        lean("mining", 10, "the elves count every tree: stone over wood", "the elves' trees")
    if any(c.get("race") == "HUMAN" for c in civs) and not at_war:
        lean("outsiders", 5, "human traders in the world", "human traders")
    out = [x for x in out if x["amount"] and x["trait"] not in NOT_LEANED]
    # at most SITE_MAX on one trait, either way (the reasons kept)
    total = {}
    capped = []
    for x in out:
        t = total.get(x["trait"], 0)
        room = SITE_MAX - abs(t)
        if room <= 0:
            continue
        a = max(-room, min(room, x["amount"]))
        total[x["trait"]] = t + a
        capped.append(dict(x, amount=a))
    return capped


SITE_DROP_AFTER = 20      # (0.104.141) reads a site lean may be missing before it goes


def update(history: dict, state: dict | None) -> list:
    """Keep the fort's leanings in its culture history: the own leaning drawn
    once (from the seed), the site's read again. Returns what changed, in
    words (for the journal)."""
    lean = history.get("leanings") if isinstance(history.get("leanings"), dict) else {}
    changed = []
    if not isinstance(lean.get("own"), dict) and history.get("seed"):
        lean["own"] = own_leanings(str(history["seed"]))
        if lean["own"]:
            changed.append("the fort's own leanings: " + ", ".join(
                f"{TRAIT_NAMES.get(k, k)} {v:+d}" for k, v in sorted(lean["own"].items(), key=lambda kv: -abs(kv[1]))[:4])
                + (" ..." if len(lean["own"]) > 4 else ""))
    site = site_leanings(state or {})
    if site is not None:
        prev = [x for x in _l(lean.get("site")) if isinstance(x, dict)]
        old = {(x.get("trait"), x.get("why")) for x in prev}
        new = {(x["trait"], x["why"]) for x in site}
        for t, why in sorted(new - old):
            changed.append(f"the site leans it: {why} ({TRAIT_NAMES.get(t, t)})")
        # (0.104.141) a lean kept until it has been missing SITE_DROP_AFTER
        # reads in a row: "a cavern close under the fort" came and went with
        # wherever the lowest dwarf stood (60 times in 639 cycles), and the
        # gate style flipped with it
        miss = lean.get("missing") if isinstance(lean.get("missing"), dict) else {}
        kept = []
        for x in prev:
            k = f"{x.get('trait')}|{x.get('why')}"
            if (x.get("trait"), x.get("why")) in new:
                miss.pop(k, None)
                continue
            c = int(miss.get(k) or 0) + 1
            if c < SITE_DROP_AFTER and isinstance(x.get("amount"), (int, float)):
                miss[k] = c
                kept.append(x)
            else:
                miss.pop(k, None)
        # (review) kept ones within the cap on their trait, as the new ones are
        total = {}
        for x in site:
            total[x["trait"]] = total.get(x["trait"], 0) + x["amount"]
        fit = []
        for x in kept:
            t_ = total.get(x["trait"], 0)
            if abs(t_ + x["amount"]) <= SITE_MAX:
                total[x["trait"]] = t_ + x["amount"]
                fit.append(x)
        lean["site"] = site + fit
        lean["missing"] = miss
    history["leanings"] = lean
    return changed


def history_pushes(history: dict) -> dict:
    """What the fort has lived through, as slider pushes (each capped): sieges
    make it more fortified and huddled, slain beasts prouder, deaths more
    devout. (Until 0.95 these were worked out and then thrown away.)"""
    h = history or {}
    return {k: v for k, v in {
        "fortification": min(60, 20 * int(h.get("sieges", 0) or 0)),
        "grandeur": min(40, 10 * len(h.get("beasts_slain") or [])),
        "piety": min(25, 5 * (int(h.get("citizen_deaths", 0) or 0) // 5)),
        "spacing": -min(45, 15 * int(h.get("sieges", 0) or 0)),
    }.items() if v}


def extras(history: dict | None, short: bool = False) -> list:
    """Everything that leans the engine beyond your sliders, each with the
    label the "why" text shows: [(label, {trait: amount})]; with short=True,
    [(label, {trait: amount}, short label)] for the panel."""
    h = history or {}
    out = []
    lean = _d(h.get("leanings"))
    own = {k: v for k, v in _d(lean.get("own")).items() if isinstance(v, (int, float)) and k not in NOT_LEANED}
    if own:
        out.append(("its own leaning", own, "own"))
    for x in _l(lean.get("site")):
        x = _d(x)
        if x.get("trait") and isinstance(x.get("amount"), (int, float)) and x["trait"] not in NOT_LEANED:
            out.append((f"the site: {x.get('why')}", {x["trait"]: x["amount"]}, x.get("short") or x.get("why")))
    push = history_pushes(h)
    if push:
        out.append(("its history", push, "history"))
    return [x[:2] for x in out] if not short else out


def totals(history: dict | None) -> dict:
    """Each trait's lean beyond your slider: {trait: total}."""
    t = {}
    for _, d in extras(history):
        for k, v in d.items():
            t[k] = t.get(k, 0) + v
    return t


def words(history: dict | None, tid: str) -> str:
    """This trait's leanings in words, for the panel ("" when none):
    'leans +18: own +8, rich ore +10'."""
    parts = []
    total = 0
    for _, d, name in extras(history, short=True):
        v = d.get(tid)
        if not v:
            continue
        total += v
        parts.append(f"{name} {int(v):+d}")
    if not parts:
        return ""
    return f"leans {int(total):+d}: " + ", ".join(parts)


def panel(history: dict | None) -> dict:
    """Every leaned trait's words, for the panel's "Leans:" line: {trait: text}."""
    out = {}
    for tid in TRAIT_NAMES:
        w = words(history, tid)
        if w:
            out[tid] = w
    return out
