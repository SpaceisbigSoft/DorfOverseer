"""(0.105.40b) Raw adamantine and the underworld: never dug.

Digging raw adamantine opens the spire it stands in, and below the spire
(or any breach into the underworld) wait the demons: a fort ends there. The
bridge's dig guard (lua/ai-util.lua dig_forbidden) refuses every dig the AI
marks on such a tile, beside it (the 8 around on its level) or over or under
it: quickfort's dig blueprints (every level, hall, well, cistern, way in,
landmark), the joins and widenings, the ore veins, drifts and quarries, and
DFHack's dig-now.

The `deep` report carries `deep_hazard` (lua/ai-util.lua deep_hazard): the
raw adamantine the dwarves have uncovered (tiles, the highest level, the
nearest tile to the citizens), whether the spire or the underworld has been
seen, and the guard's refusals since the game loaded.

Here the brain:
  * never proposes a vein of adamantine (a mine_ore whose metal or ore is
    adamantine is dropped, with a note why);
  * says, while adamantine has been seen or the guard refused a dig,
    "adamantine: left alone: it guards the underworld";
  * reads the Rules switch `mine_adamantine` (off by default): kept for a
    sealed breach plan that isn't built yet; on, the note says so and
    adamantine is still left alone.

Without `deep_hazard` in the report (an older bridge, the fixtures) nothing
here proposes or says anything: decisions stay as they were.
"""

from __future__ import annotations

from digest import _d, game_text

__all__ = ["deep_hazard", "_deep_hazard_rule", "deep_hazard_line", "is_adamantine", "LEFT_ALONE"]

LEFT_ALONE = "adamantine: left alone: it guards the underworld"
NOT_BUILT = ("mine_adamantine is on, but the sealed breach plan is not built yet: "
             "adamantine is still left alone")


def deep_hazard(s: dict) -> dict:
    """The report's deep_hazard ({} when there is none)."""
    d = s.get("deep")
    if not isinstance(d, dict) or "error" in d:
        return {}
    return _d(d.get("deep_hazard"))


def is_adamantine(name) -> bool:
    """A metal or ore name that is adamantine (ADAMANTINE, RAW_ADAMANTINE...)."""
    return isinstance(name, str) and "ADAMANTINE" in name.upper()


def _elev(s: dict, z):
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) and not isinstance(off, bool) else 0
    return z + off if isinstance(z, int) and not isinstance(z, bool) else None


def _mine_on(s: dict) -> bool:
    return _d(s.get("settings")).get("mine_adamantine") is True


def _deep_hazard_rule(s: dict, proposals: list, notes: list) -> None:
    """Drops any proposal to mine adamantine; notes why adamantine is left alone."""
    ores = _d(_d(s.get("industry")).get("ores"))
    dropped = []
    for p in list(proposals):
        a = p.action if isinstance(getattr(p, "action", None), dict) else {}
        if a.get("type") != "mine_ore":
            continue
        metal = a.get("metal")
        ore = _d(ores.get(metal)).get("ore") if isinstance(metal, str) else None
        if is_adamantine(metal) or is_adamantine(ore):
            dropped.append(p)
    for p in dropped:
        proposals.remove(p)
    h = deep_hazard(s)
    on = _mine_on(s)
    if not (dropped or h.get("adamantine_seen") or (h.get("refused") or 0) > 0 or (on and h)):
        return
    bits = []
    if h.get("adamantine_seen"):
        e = _elev(s, h.get("nearest_z"))
        bits.append(f"{h.get('tiles', 0)} tile(s) uncovered" + (f", the nearest at elevation {e}" if e is not None else ""))
    if (h.get("refused") or 0) > 0:
        last = _d(h.get("refused_last"))
        bits.append(f"the dig guard refused {h['refused']} tile(s)"
                    + (f" (last: {game_text(last.get('why'), 40)})" if last.get("why") else ""))
    if dropped:
        bits.append("no vein of it is mined")
    note = LEFT_ALONE + (f" ({'; '.join(bits)})" if bits else "")
    if on:
        note += f"; {NOT_BUILT}"
    notes.append(note)


def deep_hazard_line(s: dict) -> str:
    """The digest's DEEP_HAZARD line; "" when nothing has been seen or refused."""
    h = deep_hazard(s)
    if not h or not (h.get("adamantine_seen") or h.get("underworld_seen") or (h.get("refused") or 0) > 0
                     or h.get("mine_adamantine")):
        return ""
    parts = []
    if h.get("adamantine_seen"):
        e = _elev(s, h.get("nearest_z"))
        parts.append(f"adamantine seen ({h.get('tiles', 0)} tiles"
                     + (f", nearest at elevation {e}" if e is not None else "") + ")")
    if h.get("spire_seen"):
        parts.append("the spire is open to view")
    if h.get("underworld_seen"):
        parts.append("the underworld seen")
    if (h.get("refused") or 0) > 0:
        by = _d(h.get("refused_by"))
        parts.append(f"dig guard refused {h['refused']}"
                     + (" (" + " ".join(f"{k}:{v}" for k, v in sorted(by.items()) if isinstance(v, int)) + ")" if by else ""))
    if h.get("mine_adamantine"):
        parts.append("mine_adamantine on: not built yet, still refused")
    return "DEEP_HAZARD " + "; ".join(parts) + " | " + LEFT_ALONE
