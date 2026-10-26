"""The player's report on a fort left to the AI: a few lines each in-game
season, in logs/forts/<fort>/report.md, so a long unattended run can be
caught up on from one file. No tokens.

    line = report.maybe_write(state, memory, key, todo, fps)   # once a cycle
"""

from __future__ import annotations

from datetime import datetime

import chronicle
import defence
import memstore
import phases
import timeline
from digest import _d, _l, normalize

MAX_BYTES = 400_000          # the oldest half goes when it grows past this


SEASONS = ("spring", "summer", "autumn", "winter")


def season_key(state: dict) -> str:
    d = _d(state.get("date"))
    return f"{d.get('year')} {d.get('season')}"


def _order(sk: str) -> tuple:
    y, _, s = str(sk).partition(" ")
    try:
        return int(y), SEASONS.index(s) if s in SEASONS else 0
    except ValueError:
        return (0, 0)


def _numbers(state: dict, memory) -> list[str]:
    s = normalize(state)
    rows = timeline.days(memory)
    r = rows[-1] if rows else {}
    out = []
    pop = r.get("pop")
    if pop is None:
        pop = _d(s.get("dwarves")).get("total")
    if pop is not None:
        out.append(f"{pop} dwarves")
    for k, label in (("drink_pd", "drinks"), ("meals_pd", "meals")):
        if isinstance(r.get(k), (int, float)):
            out.append(f"{r[k]:g} {label} per dwarf")
    for k, label in (("unhappy_pct", "unhappy"), ("idle_pct", "idle")):
        if isinstance(r.get(k), (int, float)):
            out.append(f"{r[k]:g}% {label}")
    w = s.get("wealth")
    if isinstance(w, (int, float)):
        out.append(f"wealth {int(w):,}")
    return out


def trouble(state: dict, memory) -> list[str]:
    """Plain signs the fort is in trouble, worst first (empty when it's fine)."""
    from planner import food_per_dwarf, has_farms           # (planner imports nothing from here)
    s = normalize(state)
    out = []
    so, st, dw = _d(s.get("society")), _d(s.get("stocks")), _d(s.get("dwarves"))
    pop = dw.get("total") or 0
    if pop == 0:
        return ["no citizens left: the fort has fallen"]
    if so.get("starving") or so.get("parched"):
        out.append(f"{so.get('starving', 0)} starving and {so.get('parched', 0)} parched")
    rows = timeline.days(memory)[-28:]
    deaths = sum(r.get("deaths") or 0 for r in rows)
    if deaths >= max(3, pop // 10):
        out.append(f"{deaths} deaths in the last {len(rows)} days")
    food = food_per_dwarf(s)
    if food < 3 and not has_farms(s):
        out.append(f"only {food:g} food a dwarf and no farm")
    if pop and (st.get("drink") or 0) < pop:
        out.append(f"less than one drink a dwarf ({st.get('drink') or 0} for {pop})")
    if rows and len(rows) >= 14 and isinstance(rows[0].get("pop"), (int, float)) and rows[0]["pop"] - pop >= max(3, pop // 4):
        out.append(f"the fort shrank from {rows[0]['pop']} to {pop} dwarves in {len(rows)} days")
    return out


def readiness(state: dict) -> list[tuple[str, bool]]:
    """Is the fort ready for a siege? (what, ready) for each thing that
    matters when one comes: the ways in can be closed, enough soldiers, and
    armed and armoured, a hospital and a well for the wounded, food and drink
    to sit it out."""
    from planner import PLANNER_CONFIG, food_per_dwarf, soldiers_wanted
    s = normalize(state)
    out: list[tuple[str, bool]] = []
    pop = _d(s.get("dwarves")).get("total") or 0
    en = _d(s.get("entrances"))
    if en.get("scanned"):
        es = [e for e in (en.get("entrances") or []) if isinstance(e, dict)]
        closable = [e for e in es if e.get("sealed") or e.get("closing") or e.get("equipment")]
        out.append((f"ways in that can be closed {len(closable)} of {len(es)}", len(closable) == len(es)))
    mil = _d(s.get("military"))
    gear = _d(mil.get("gear"))
    have = mil.get("soldiers") or 0
    want = soldiers_wanted(s, pop, PLANNER_CONFIG) if pop else 0
    out.append((f"soldiers {have} of {want}", have >= want and have > 0))
    if have:
        armed, armoured, helmed = gear.get("armed") or 0, gear.get("armored") or 0, gear.get("helmed") or 0
        on = gear.get("on_duty") if "on_duty" in gear else have
        out.append((f"soldiers armed {armed}, in armour {armoured}, with helms {helmed} (of {on} on duty)",
                    bool(on) and min(armed, armoured, helmed) >= on))
    hospital = _d(_d(s.get("locations")).get("count")).get("HOSPITAL", 0)
    out.append(("a hospital" if hospital else "no hospital", bool(hospital)))
    wells = _d(_d(s.get("buildings")).get("other")).get("Well", 0)
    out.append(("a well" if wells else "no well", bool(wells)))
    if pop:
        food = food_per_dwarf(s)
        drink = (_d(s.get("stocks")).get("drink") or 0) / pop
        out.append((f"food {food:g} and drink {drink:.0f} a dwarf", food >= 20 and drink >= 10))
    return out


def readiness_line(state: dict) -> str:
    items = readiness(state)
    gaps = [w for w, ok in items if not ok]
    good = [w for w, ok in items if ok]
    if not gaps:
        return "ready: " + "; ".join(good)
    return "NOT YET: " + "; ".join(gaps) + (" (ready: " + "; ".join(good) + ")" if good else "")


def text_for(state: dict, memory, todo: list[str], fps) -> str:
    d = _d(state.get("date"))
    lines = [f"## {d.get('day')} {d.get('month')} y{d.get('year')} ({d.get('season')}), "
             f"written {datetime.now().strftime('%a %d %b %H:%M')}", ""]
    bad = trouble(state, memory)
    if bad:
        lines.append("- **THE FORT IS IN TROUBLE:** " + "; ".join(bad))
    nums = _numbers(state, memory)
    if isinstance(fps, (int, float)):
        nums.append(f"{int(fps)} FPS")
    if nums:
        lines.append("- **The fort:** " + ", ".join(nums))
    lines.append("- **Phase:** " + (phases.line(memory) or phases.current(memory)))
    try:
        lines.append("- **Ready for a siege?** " + readiness_line(state))
    except Exception:  # noqa: BLE001 (the report is written anyway)
        pass
    goals = getattr(memory, "agenda", None) or []
    if goals:
        lines.append("- **This season the AI works to:** " + "; ".join(goals))
    story = chronicle.lines(memory, 8)
    if story:
        lines.append("- **Lately:**")
        lines += [f"  - {x}" for x in reversed(story)]
    sieges = defence.lesson_lines(memory, 4)
    if sieges:
        lines.append("- **Gates in sieges:** " + "; ".join(sieges))
    stuck = sorted(((v.get("n") or 0, k.split(":")[0], v.get("why") or "")
                    for k, v in (memory.refusals or {}).items() if isinstance(v, dict) and (v.get("n") or 0) >= 3),
                   reverse=True)
    if stuck:
        lines.append("- **The game keeps refusing:** " + "; ".join(
            f"{rule} ({n} times in a row{': ' + why if why else ''})" for n, rule, why in stuck[:4]))
    if todo:
        lines.append("- **Needs you:**")
        lines += [f"  - {t}" for t in list(dict.fromkeys(todo))[:6]]
    return "\n".join(lines) + "\n\n"


def maybe_write(state: dict, memory, key: str, todo: list[str], fps=None) -> str | None:
    """Write a season's lines when the season has changed since the last
    report (never on the first look at a fort). Returns a line to print."""
    sk = season_key(state)
    if memory.report_season == sk:
        return None
    first = not memory.report_season
    back = not first and _order(sk) < _order(memory.report_season)
    memory.report_season = sk
    if first or back:
        return None                     # (an older save loaded: no report, no save, just noted)
    path = memstore.fort_dir(key) / "report.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        if len(old) > MAX_BYTES:
            old = old[len(old) // 2:]
            old = old[old.find("\n## ") + 1:] if "\n## " in old else old
        head = "" if old else f"# Report: {key.split('#')[0]}\n\nA few lines each in-game season, newest last.\n\n"
        from dfhack import write_atomic
        write_atomic(path, head + old + text_for(state, memory, _l(todo), fps))   # (0.100) whole or not at all
    except OSError as e:
        return f"couldn't write the season's report ({e})"
    return f"the season's report is in {path}"
