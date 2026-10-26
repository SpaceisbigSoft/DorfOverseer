"""Print a readable fort report and save the raw snapshot.

Run from the project folder, with a fort loaded in DF:

    python brain/show_fort.py

The full report is also saved to logs/snapshots/ so we can compare forts over time.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bridge import LOG_DIR, Bridge, BridgeError, as_dict, as_list  # noqa: E402
from dfhack import DFHackError  # noqa: E402
from digest import normalize  # noqa: E402
from tokens import ai_plan  # noqa: E402

LAYER_NAMES = {"upper_levels": "upper levels", "between_layers": "rock between layers",
               "fort_levels": "upper levels", "Cavern1": "cavern 1", "Cavern2": "cavern 2",
               "Cavern3": "cavern 3", "MagmaSea": "magma sea", "Underworld": "underworld"}


def reach_text(reaches: set, flier: bool) -> str:
    """How to describe whether a group of threats can reach the dwarves.
    True = DF's walking map connects them; False = it doesn't; None = DF's
    walking map can't say (the creature is flying, swimming or in open air)."""
    if reaches == {True}:
        return "CAN REACH YOUR DWARVES"
    if True in reaches:
        return "SOME CAN REACH YOUR DWARVES"
    if reaches == {False}:
        return "no walking path to your dwarves" + (" (but they fly)" if flier else "")
    return "no walking path found" + (" (they fly, so DF can't tell)" if flier else " (DF can't tell for some)")

STRESS_ORDER = ["miserable", "very_unhappy", "unhappy", "fine", "content", "happy", "ecstatic"]


def top(counts: dict, n: int) -> str:
    items = sorted(as_dict(counts).items(), key=lambda kv: -kv[1])[:n]
    return ", ".join(f"{name} {count}" for name, count in items) or "none"


def report(s: dict) -> str:
    s = normalize(s)
    d, dw, st = s["date"], s["dwarves"], as_dict(s["stocks"])
    b, j, o = s["buildings"], s["jobs"], s["others_on_map"]
    stress = as_dict(dw["stress"])
    unhappy = stress.get("miserable", 0) + stress.get("very_unhappy", 0) + stress.get("unhappy", 0)
    threats = as_list(o["threats"])

    lines = [
        f"=== Fort report: {d['day']} {d['month']}, year {d['year']} ({d['season']}) ===",
        f"Game is {'PAUSED' if s['paused'] else 'running'}.  Fort wealth: {s['wealth']:,}",
        "",
        "DWARVES",
        f"  {dw['total']} citizens: {dw['adults']} adults, {dw['children']} children",
        f"  Idle adults (no job, not soldiers): {dw['idle_adults']}",
        f"  In squads: {dw['in_squads']}   Need medical care: {dw['needs_medical_care']}",
        "  Mood: " + ", ".join(f"{k.replace('_', ' ')} {stress.get(k, 0)}" for k in STRESS_ORDER),
        f"  Unhappy or worse: {unhappy}",
        f"  Top professions: {top(dw['professions'], 6)}",
        "",
        "STOCKS (not forbidden, rotten, owned or built into something)",
        f"  Drink {st.get('drink', 0)}   Meals {st.get('prepared_meals', 0)}   "
        f"Meat {st.get('meat', 0)}   Fish {st.get('fish', 0)}   Plants {st.get('plants', 0)}   "
        f"Seeds {st.get('seeds', 0)}",
        f"  Wood {st.get('wood', 0)}   Boulders {st.get('boulders', 0)}   "
        f"Blocks {st.get('blocks', 0)}   Metal bars {st.get('metal_bars', 0)}",
        f"  Cloth {st.get('cloth', 0)}   Thread {st.get('thread', 0)}   "
        f"Leather {st.get('leather', 0)}   Gems {st.get('rough_gems', 0)} rough / "
        f"{st.get('cut_gems', 0)} cut",
        f"  Weapons {st.get('weapons', 0)}   Armor {st.get('armor', 0)}   "
        f"Ammo {st.get('ammo', 0)}   Barrels {st.get('barrels', 0)}   Bins {st.get('bins', 0)}",
        "",
        "BUILDINGS",
        f"  Workshops: {top(b['workshops'], 8)}",
        f"  Furnaces: {top(b['furnaces'], 5)}",
        f"  Stockpiles: {b['stockpiles']}   Zones: {top(b['zones'], 6)}",
        f"  Under construction: {b['under_construction']}   "
        f"Jobs queued at workshops: {b['workshop_jobs_queued']}",
        "",
        "JOBS",
        f"  {j['total']} jobs, {j['suspended']} suspended. Most common: {top(j['by_type'], 5)}",
        "",
        "ON THE MAP",
        f"  Loose threats: {len(threats)} ({o.get('threats_that_can_reach_dwarves', 0)} can reach your dwarves)"
        f"   Caged or chained dangers: {o.get('contained_dangers', 0)}",
        f"  Merchants: {o['merchants']}   Diplomats: {o['diplomats']}   "
        f"Visitors: {o['visitors']}   Tame animals: {o['tame_animals']}",
    ]
    # Group identical threats: "Specter Of Steam x30, z-levels 12 to 15"
    groups: dict[str, dict] = {}
    for t in threats:
        g = groups.setdefault((t["name"], t.get("layer")),
                              {"count": 0, "zs": [], "t": t, "reaches": set(), "flier": False})
        g["count"] += 1
        g["zs"].append(as_dict(t.get("pos")).get("z"))
        g["reaches"].add(t.get("can_reach_dwarves"))
        g["flier"] = g["flier"] or bool(t.get("flier"))
    # Threats that can reach the dwarves come first, whatever their numbers.
    for (name, _layer), g in sorted(groups.items(),
                                    key=lambda kv: (True not in kv[1]["reaches"], -kv[1]["count"]))[:12]:
        t = g["t"]
        tag = " (GREAT DANGER)" if t.get("great_danger") else (" (invader)" if t.get("invader") else "")
        zs = [z for z in g["zs"] if z is not None]
        where = ""
        if zs:
            where = f", z-level {min(zs)}" if min(zs) == max(zs) else f", z-levels {min(zs)} to {max(zs)}"
        if t.get("layer"):
            where += f" ({LAYER_NAMES.get(t['layer'], t['layer'])})"
        count = f" x{g['count']}" if g["count"] > 1 else ""
        lines.append(f"    - {name}{count}{tag}{where} - {reach_text(g['reaches'], g['flier'])}")

    m = as_dict(s.get("map"))
    if m:
        dw_at = as_dict(m.get("dwarves"))
        # DFHack counts levels from 0 at the map's bottom; the game shows elevation
        off = m.get("elevation_offset") if isinstance(m.get("elevation_offset"), int) else 0
        lv = lambda z: z + off if isinstance(z, int) else z  # noqa: E731
        lines += ["", "MAP (level numbers as the game shows them)"]
        lines.append(f"  Dwarves are between levels {lv(dw_at.get('z_bottom'))} and {lv(dw_at.get('z_top'))}"
                     " (higher numbers are closer to the surface)"
                     f" ({', '.join(f'{LAYER_NAMES.get(k, k)} {v}' for k, v in as_dict(dw_at.get('by_layer')).items())})")
        for layer in as_list(m.get("layers")):
            seen = "discovered" if layer.get("discovered") else "not discovered yet"
            lines.append(f"  {LAYER_NAMES.get(layer['name'], layer['name']):12s} levels "
                         f"{lv(layer.get('z_top'))} to {lv(layer.get('z_bottom'))}, {seen}")

    nobles = as_list(s.get("nobles"))
    mandates = as_list(s.get("mandates"))
    if nobles or mandates or s.get("civ_alert"):
        lines += ["", "NOBLES AND ORDERS"]
        if s.get("civ_alert"):
            lines.append("  CIVILIAN ALERT IS ON")
        if nobles:
            lines.append("  Positions: " + ", ".join(sorted({n["position"].replace("_", " ").title()
                                                              for n in nobles})))
        for x in mandates:
            what = " ".join(p for p in (x.get("material"), x["item"].lower()) if p)
            lines.append(f"  Mandate ({x['kind']}): {x['remaining']} of {x['total']} {what},"
                         f" {x['days_left']} days left" + (f", from {x['by']}" if x.get("by") else ""))

    pr = as_dict(s.get("projects"))
    if pr and "error" not in pr:
        lines += ["", "AI BUILDING PROJECTS"]
        for p in as_list(pr.get("open")):
            dig, fur = as_dict(p.get("dig")), as_dict(p.get("furnish"))
            if p.get("phase") == "dig":
                state = f"digging, {dig.get('dug', 0)} of {dig.get('total', 0)} tiles dug"
                if dig.get("stuck"):
                    state += f" ({dig['stuck']} tiles no longer designated)"
            else:
                state = f"furnishing, {fur.get('done', 0)} of {fur.get('placed', 0)} built"
                waiting = as_dict(fur.get("waiting"))
                if waiting:
                    state += ", waiting for " + ", ".join(f"{v} {k.lower()}" for k, v in sorted(waiting.items()))
            lines.append(f"  #{p.get('id')} {p.get('kind')} on level {p.get('elevation', p.get('z'))}: {state}")
        for p in as_list(pr.get("decorating")):
            d = as_dict(p.get("decor"))
            state = (f"waiting for smoothing ({d.get('smooth_waiting', 0)} tiles left), then engraving"
                     if d.get("smooth_waiting") else "smoothed; engraving next")
            lines.append(f"  #{p.get('id')} {p.get('kind')} on level {p.get('elevation', p.get('z'))}: {state}")
        if not as_list(pr.get("open")) and not as_list(pr.get("decorating")):
            lines.append("  None in progress")
        lines.append(f"  Finished so far: {pr.get('finished', 0)}")

    st = as_dict(s.get("settings"))
    if st and "error" not in st:
        lines += ["", "AI SETTINGS (from the in-game panel, Ctrl-Shift-O)"]
        traits = as_dict(st.get("traits"))
        if traits:
            for k, v in sorted(traits.items(), key=lambda kv: -abs(kv[1])):
                lines.append(f"  {k.replace('_', ' ').title():22s} {v:+d}")
        else:
            lines.append("  All traits balanced (0)")
        cap = st.get("real_day_token_cap") or 0
        plan = ai_plan(st)
        lines.append(f"  AI reviews: {plan['frequency_word']} (every {plan['interval_days']} days), thinking "
                     f"{plan['effort_word'].lower()}; about {plan['tokens_per_year']:,} tokens per in-game year;"
                     f" real-day cap {'off' if not cap else cap}")

    lines += ["", "RECENT ANNOUNCEMENTS"]
    for a in as_list(s["recent_announcements"])[-8:]:
        lines.append(f"  - {a['text']}")

    if s.get("_errors"):
        lines += ["", "SECTIONS THAT FAILED IN-GAME (the rest of the report is fine):"]
        for k, err in s["_errors"].items():
            lines.append(f"  {k}: {err.splitlines()[0][:200]}")

    meta = s.get("_meta", {})
    lines += ["", f"(Report built in {meta.get('build_ms', '?')} ms inside the game.)"]
    return "\n".join(lines)


SNAPSHOTS_KEPT = 60


def main() -> int:
    try:
        bridge = Bridge()
        bridge.handshake()
        state = bridge.state()
    except (DFHackError, BridgeError) as e:
        print("FAILED:", e)
        print("\nIs DF running with a fort loaded? Does `ai-bridge state` work in the DFHack launcher?")
        return 1

    # Windows consoles may not handle every character in dwarf names.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    print(report(state))

    snap_dir = LOG_DIR / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap = snap_dir / f"state-{datetime.now():%Y%m%d-%H%M%S}.json"
    snap.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    import memstore
    memstore.keep_newest(snap_dir, "state-*.json", SNAPSHOTS_KEPT)
    print(f"Full report saved to {snap.relative_to(LOG_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
