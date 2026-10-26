"""Defence that learns (milestone 5b). All scripts, no tokens.

Every gate the AI builds is already in the atlas's registry with its design
(the gate style, doors, a drawbridge, a water gate) and, since 5b, the traps
behind it. When a siege ends, each of those gates that saw the enemy is
judged from the located events the atlas kept during the siege:

    held     enemies came to it (threats at the gate) and no citizen died there
    costly   citizens died there, but at least twice as many enemies did
    failed   citizens died there and the enemy wasn't held off

A gate no enemy came to isn't judged (untested). The verdicts add up per
design ("plain gates: held 3 of 4 sieges") into design scores that lean the
weights engine's Defence and Traps areas toward what has worked and away
from what hasn't. Your other forts' verdicts count at half weight (kept in
logs/player-memory.json beside your preferences). How often the AI tries a
promising design it hasn't proved yet, instead of the best-known one, is set
by Caution: never at +100, about one year in seven at 0, more below.

    lines = judge_sieges(state, memory)      # after phases.update, each cycle
    memory.culture["design"] = engine_bonuses(memory)
    memory.culture["explore"] = explore(traits, year)
"""

from __future__ import annotations

import learning
import phases
from digest import _d, _l

DAY = 1200
GRACE = 2 * DAY            # events this long after the siege still count (the wounded die later)
MAX_PER_DESIGN = 50        # counts are capped so old wars fade a little against new ones
BONUS_MAX = 0.45           # how far a record can move a design's score
SHARED_WEIGHT = 0.5        # your other forts' verdicts
MAX_RECORDS = 5            # sieges kept on each gate's registry entry


def _state(memory) -> dict:
    lr = memory.learning if isinstance(memory.learning, dict) else {}
    memory.learning = lr
    d = lr.get("defence")
    if not isinstance(d, dict):
        d = lr["defence"] = {}
    if not isinstance(d.get("judged"), list):
        d["judged"] = []
    if not isinstance(d.get("scores"), dict):
        d["scores"] = {}
    return d


def _now(state: dict) -> int:
    d = state["date"]
    return d["year"] * 403200 + d["tick"]


def verdict(threats: int, deaths: int, kills: int) -> str | None:
    if threats <= 0 and deaths <= 0:
        return None                               # no enemy came: untested
    if deaths <= 0:
        return "held"
    if kills >= 2 * deaths:
        return "costly"
    return "failed"


REACH = 3                  # records and events this close (same level) are one gate's


def _spot(k: str):
    try:
        x, y, z = (int(v) for v in k.split(","))
        return x, y, z
    except ValueError:
        return None


def _close(a, b) -> bool:
    return a is not None and b is not None and a[2] == b[2] and max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= REACH


def _gates(a: dict, before: int) -> list[tuple[str, list[str]]]:
    """Each AI gate built before the siege began, with every design at it:
    [(spot, ['defence:plain', 'traps:cage'])]. Records filed a tile or two
    apart (walls move an entrance's first tile) count as one gate."""
    reg = a.get("registry") if isinstance(a.get("registry"), dict) else {}
    recs = []
    for rid, rec in reg.items():
        prefix, _, spot = rid.partition(":")
        if prefix not in ("gate", "doors", "traps") or not isinstance(rec, dict):
            continue
        if not isinstance(rec.get("tick"), int) or rec["tick"] > before or _spot(spot) is None:
            continue
        variant = str(rec.get("variant") or ("doors" if prefix == "doors" else "plain"))
        variant = variant.split(",")[0].strip()          # "plain, on the shore" -> plain
        if variant == "deep water":
            variant = "water"
        recs.append((prefix, spot, ("traps:" if prefix == "traps" else "defence:") + variant))
    out, used = [], set()
    for prefix, spot, design in sorted(recs, key=lambda r: r[0] != "gate"):
        if spot in used or prefix == "traps":
            continue
        group = [(s2, d2) for p2, s2, d2 in recs if _close(_spot(spot), _spot(s2))]
        for s2, _ in group:
            used.add(s2)
        designs = []
        for _, d2 in group:
            if d2 not in designs:
                designs.append(d2)
        # a gate's own design and its doors: the gate style is the design (its doors are part of it)
        if any(d.startswith("defence:") and d != "defence:doors" for d in designs):
            designs = [d for d in designs if d != "defence:doors"]
        out.append((spot, designs))
    return out


def _add(scores: dict, design: str, v: str) -> None:
    c = scores.setdefault(design, {"n": 0, "held": 0, "costly": 0, "failed": 0})
    if c["n"] >= MAX_PER_DESIGN:                     # fade the oldest a little
        for k in ("held", "costly", "failed"):
            c[k] = round(c[k] * 0.9, 2)
        c["n"] = round(c["n"] * 0.9, 2)
    c["n"] += 1
    c[v] = c.get(v, 0) + 1


def judge_sieges(state: dict, memory) -> list[str]:
    """Judge every gate that saw the enemy in each siege that has ended.
    Returns lines for the chronicle."""
    d = _state(memory)
    now = _now(state)
    a = memory.atlas if isinstance(memory.atlas, dict) else {}
    if phases.current(memory) == "siege":
        return []
    out = []
    for start, end in phases.siege_spans(memory, now):
        if end in d["judged"] or end > now:
            continue
        if now - end < GRACE:
            continue                               # let the wounded die or recover first
        d["judged"].append(end)
        del d["judged"][:-40]
        events = [e for e in _l(a.get("events")) if isinstance(e, dict)
                  and isinstance(e.get("t"), int) and start <= e["t"] <= end + GRACE]
        for spot, designs in _gates(a, start):
            here = [e for e in events if str(e.get("near") or "").startswith("entrance:")
                    and _close(_spot(spot), _spot(str(e["near"])[len("entrance:"):]))]
            threats = sum(1 for e in here if e.get("k") == "threat_at_gate")
            deaths = sum(1 for e in here if e.get("k") == "death")
            kills = sum(1 for e in here if e.get("k") in ("kill", "beast_slain"))
            v = verdict(threats, deaths, kills)
            if not v:
                continue
            for design in designs:
                _add(d["scores"], design, v)
            gate = (a.get("registry") or {}).get("gate:" + spot) or (a.get("registry") or {}).get("doors:" + spot)
            if isinstance(gate, dict):
                gate.setdefault("sieges", []).append({"t": end, "threats": threats, "deaths": deaths,
                                                      "kills": kills, "verdict": v})
                del gate["sieges"][:-MAX_RECORDS]
            x, y, _z = spot.split(",")
            rec = _d(_d(a.get("entrances")).get(spot))
            el = rec.get("elevation")
            what = " and ".join(_label(x) for x in designs)
            out.append(f"the siege at the entrance x{x} y{y}" + (f" (elevation {el})" if el is not None else "")
                       + f": {what} {v} ({threats} enemies came to it, {deaths} citizens died there, "
                       f"{kills} enemies killed there)")
    if out:
        share(memory)
    return out


def _label(design: str) -> str:
    area, _, v = design.partition(":")
    if area == "traps":
        return f"{v} traps"
    return {"doors": "its doors", "water": "its deep water", "hatch": "its hatch"}.get(v, f"the {v} gate")


# --- design scores for the weights engine -------------------------------------------------

def _shared(memory) -> dict:
    """Your other forts' verdicts, summed: {design: counts}."""
    fort = str((memory.culture or {}).get("seed") or "")
    site = fort.rpartition("#")[2]
    out: dict = {}
    for key, scores in (_d(learning.load_player().get("design"))).items():
        if key == fort or (site and key.rpartition("#")[2] == site) or not isinstance(scores, dict):
            continue
        for design, c in scores.items():
            if isinstance(c, dict):
                o = out.setdefault(design, {"n": 0, "held": 0, "costly": 0, "failed": 0})
                for k in o:
                    o[k] += float(c.get(k) or 0)
    return out


def share(memory) -> None:
    """Keep this fort's verdicts in your memory, for your other forts."""
    fort = str((memory.culture or {}).get("seed") or "")
    if not fort:
        return
    p = learning.load_player()
    design = p.get("design") if isinstance(p.get("design"), dict) else {}
    design[fort] = _state(memory)["scores"]
    p["design"] = design
    learning.save_player(p)


def _combined(memory) -> dict:
    own = _state(memory)["scores"]
    try:
        other = _shared(memory)
    except Exception:  # noqa: BLE001  (a broken player file never stops the fort)
        other = {}
    out = {}
    for design in set(own) | set(other):
        o, s = own.get(design) or {}, other.get(design) or {}
        out[design] = {k: float(o.get(k) or 0) + SHARED_WEIGHT * float(s.get(k) or 0)
                       for k in ("n", "held", "costly", "failed")}
    return out


def bonus(c: dict) -> float:
    """A design's lean from its record: held pulls up, failed pulls down
    harder, costly a little; few sieges move it little."""
    n = c.get("n") or 0
    if n <= 0:
        return 0.0
    raw = (c.get("held", 0) - 0.5 * c.get("costly", 0) - 1.5 * c.get("failed", 0)) / (n + 2)
    return round(max(-BONUS_MAX, min(BONUS_MAX, raw * 0.9)), 3)


def engine_bonuses(memory) -> dict:
    """{area: {option: (bonus, 'held 3 of 4 sieges')}} for brain/weights.py."""
    out: dict = {}
    for design, c in _combined(memory).items():
        area, _, opt = design.partition(":")
        if area not in ("defence", "traps"):
            continue
        b = bonus(c)
        if b:
            n = round(c["n"], 1)
            out.setdefault(area, {})[opt] = [b, f"held {c['held']:g} of {n:g} siege(s)"
                                             + (f", failed {c['failed']:g}" if c["failed"] else "")]
    return out


def explore(traits: dict, year: int) -> dict:
    """How often to try a promising design instead of the best-known one:
    never at Caution +100, about 1 year in 7 at 0, up to 1 in 3 at -100."""
    try:
        caution = float((traits or {}).get("caution", 0) or 0)
    except (TypeError, ValueError):
        caution = 0.0
    rate = max(0.0, min(0.35, 0.15 - 0.0015 * caution))
    return {"rate": round(rate, 3), "turn": int(year)}


def lesson_lines(memory, limit: int = 4) -> list[str]:
    """'drawbridge gates: held 3 of 4 sieges' for the learned view."""
    lines = []
    for design, c in sorted(_state(memory)["scores"].items(), key=lambda kv: -(kv[1].get("n") or 0)):
        if not isinstance(c, dict) or (c.get("n") or 0) < 1:
            continue
        lines.append(f"{_label(design)}: held {c.get('held', 0):g} of {c.get('n', 0):g} siege(s)"
                     + (f", failed {c['failed']:g}" if c.get("failed") else "")
                     + (f", costly {c['costly']:g}" if c.get("costly") else ""))
    return lines[:limit]


# --- traps: how many and which, for the planner -------------------------------------------

def trap_count(traits: dict) -> int:
    """Traps behind each gate: 2 to 8, more with Fortification, Engineering
    and Caution."""
    def v(k):
        try:
            return float((traits or {}).get(k, 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    n = 3 + (0.5 * v("fortification") + 0.3 * v("engineering") + 0.2 * v("caution")) / 25
    return int(max(2, min(8, round(n))))
