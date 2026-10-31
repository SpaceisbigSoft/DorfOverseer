"""In-game self-test: checks the bridge inside the running game, without
changing the fort. Safe on any save, and safe while the overseer is running.

    python brain/selftest.py

Run it after updating DFHack or Dwarf Fortress, or when something seems off.
Every line says PASS, WARN (works, but worth knowing) or FAIL.
"""

from __future__ import annotations

import os
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bridge import EXPECTED_PROTOCOL, Bridge, BridgeError  # noqa: E402
from dfhack import PROJECT_ROOT, DFHackError, GameNotRunning  # noqa: E402
from digest import REQUIRED, _d, digest, normalize  # noqa: E402
from memstore import same_site  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []


def check(name: str, level: str, detail: str = "") -> None:
    RESULTS.append((level, name, detail))
    print(f"[{level}] {name}" + (f"\n        {detail}" if detail else ""), flush=True)


def expected_bridge_version() -> str | None:
    """The version of ai-bridge.lua in this project folder (the one to install)."""
    src = PROJECT_ROOT / "lua" / "ai-bridge.lua"
    if not src.exists():
        return None
    m = re.search(r"^BRIDGE_VERSION = '([^']+)'", src.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def must_refuse(bridge: Bridge, name: str, action: dict, halted: bool) -> None:
    """A bad action must be refused before anything happens."""
    try:
        r = bridge.act(action)
    except (BridgeError, DFHackError) as e:
        check(name, "FAIL", f"errored instead of refusing cleanly: {e}")
        return
    if r.get("ok") or not r.get("rejected"):
        check(name, "FAIL", f"not refused: {json.dumps(r)[:200]}")
    elif halted and r.get("halted"):
        check(name, "PASS", "refused (the AI is halted, which also blocks it)")
    else:
        check(name, "PASS", f"refused: {str(r.get('error'))[:90]}")


def memory_detail(bridge, fort: dict, reply: dict) -> str:
    """Which kinds of memory the save holds, and how big each is."""
    if not reply.get("present"):
        return "none yet (normal before the overseer has run here)"
    try:
        data = bridge.load_memory() or {}
    except (BridgeError, DFHackError, OSError, ValueError) as e:
        return f"present, but couldn't be read: {e}"
    kinds = data.get("kinds") if isinstance(data.get("kinds"), dict) else {}
    key = f"{fort.get('save_dir')}#{fort.get('site_id')}"
    parts = [f"{k} {len(v.get('text') or '') // 1000} KB" + ("" if same_site(v.get("fort"), key) else " (another fort's)")
             for k, v in sorted(kinds.items()) if isinstance(v, dict)]
    if data.get("legacy"):
        parts.append("the old one-piece memory (moved over at the overseer's next check)")
    return "; ".join(parts) or "present"


def remembered_openings(bridge, fort: dict) -> list[tuple[int, int, int]]:
    """Open entrances from the atlas in the save, for when the game hasn't
    mapped them yet this session (it forgets its scan on a reload)."""
    try:
        data = bridge.load_memory() or {}
    except (BridgeError, DFHackError, OSError, ValueError):
        return []
    kinds = data.get("kinds") if isinstance(data.get("kinds"), dict) else {}
    atlas = kinds.get("atlas") if isinstance(kinds.get("atlas"), dict) else {}
    key = f"{fort.get('save_dir')}#{fort.get('site_id')}"
    if atlas.get("fort") is not None and not same_site(atlas.get("fort"), key):
        return []
    try:
        doc = json.loads(atlas.get("text") or "{}")
    except ValueError:
        return []
    doc = doc.get("data", doc) if isinstance(doc, dict) else {}
    ents = (doc.get("atlas") or {}).get("entrances") if isinstance(doc.get("atlas"), dict) else None
    out = []
    for k, rec in (ents or {}).items():
        if isinstance(rec, dict) and not rec.get("sealed") and not rec.get("gone"):
            try:
                x, y, z = (int(v) for v in str(k).split(","))
            except ValueError:
                continue
            out.append((x, y, z))
    return sorted(out)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        bridge = Bridge()
        t0 = time.perf_counter()
        info = bridge.handshake()
        ms = (time.perf_counter() - t0) * 1000
    except GameNotRunning:
        print("Dwarf Fortress isn't running (or DFHack isn't loaded).")
        return 1
    except BridgeError as e:
        check("bridge protocol", "FAIL", str(e))
        return 1
    except DFHackError as e:
        check("talking to DFHack", "FAIL", str(e))
        return 1

    # 1. versions and install
    check("bridge answers", "PASS", f"protocol {info.get('protocol')} (expected {EXPECTED_PROTOCOL}), {ms:.0f} ms")
    want, have = expected_bridge_version(), info.get("bridge_version")
    if want and have != want:
        check("installed bridge is current", "FAIL",
              f"the game has ai-bridge {have}, this folder has {want}: copy lua\\*.lua into DFHack's scripts "
              "folder (see docs/setup-guide.md) and restart DF")
    else:
        check("installed bridge is current", "PASS", f"ai-bridge {have}")
    for key in ("dfhack_version", "df_version"):
        if info.get(key):
            check(f"{key.replace('_', ' ')}", "PASS", str(info[key]))
    check("work order recipes known", "PASS" if info.get("recipes") else "FAIL",
          f"{len(info.get('recipes') or [])} recipes")
    # every game name and DFHack call the AI relies on, checked in this DF
    try:
        r = bridge._call("assumptions")
        if r.get("failed"):
            check("game names the AI relies on", "FAIL",
                  f"{len(r['failed'])} missing (the AI will misbehave where they're used): "
                  + "; ".join(r["failed"][:8]) + (" ..." if len(r["failed"]) > 8 else ""))
        elif r.get("ok") and r.get("optional_missing"):
            check("game names the AI relies on", "WARN",
                  f"all needed found; {len(r['optional_missing'])} optional missing (left to you): "
                  + "; ".join(r["optional_missing"][:4]))
        elif r.get("ok"):
            check("game names the AI relies on", "PASS", f"all {r.get('passed')} found")
        elif r.get("failed"):
            check("game names the AI relies on", "FAIL",
                  f"{len(r['failed'])} missing (the AI will misbehave where they're used): "
                  + "; ".join(r["failed"][:8]) + (" ..." if len(r["failed"]) > 8 else ""))
        else:
            check("game names the AI relies on", "WARN", str(r.get("error") or r)[:160])
    except (BridgeError, DFHackError) as e:
        check("game names the AI relies on", "WARN", f"not available (bridge older than 0.41?): {e}"[:160])

    # 2. status
    try:
        st = bridge.status()
    except (BridgeError, DFHackError) as e:
        check("status", "FAIL", str(e))
        return report()
    if not st.get("in_fort"):
        check("a fort is loaded", "WARN", "load a fort to run the rest of the checks")
        return report()
    halted = st.get("halted") is True
    check("status", "PASS", f"date {st.get('date')}, paused={st.get('paused')}, "
          f"fps={st.get('fps')}, halted={halted}")
    if st.get("fps") is None:
        check("FPS reading", "WARN", "the game didn't report FPS (older bridge?)")

    # 3. the fort report
    try:
        t0 = time.perf_counter()
        state = bridge.state(include_units=False)
        total_ms = (time.perf_counter() - t0) * 1000
    except (BridgeError, DFHackError, OSError, ValueError) as e:
        check("fort report", "FAIL", str(e))
        return report()
    build_ms = (state.get("_meta") or {}).get("build_ms")
    level = "PASS" if (build_ms or 0) < 500 else "WARN"
    check("fort report", level, f"built in {build_ms} ms in game, {total_ms:.0f} ms round trip"
          + ("" if level == "PASS" else " (slow: the game pauses while it's built)"))
    absent = [k for k in REQUIRED if k not in state]
    check("report has every section", "FAIL" if absent else "PASS",
          f"missing: {', '.join(absent)}" if absent else f"{len(REQUIRED)} required sections")
    errs = state.get("_errors")
    if errs:
        check("report sections built without errors", "WARN", json.dumps(errs)[:300])
    else:
        check("report sections built without errors", "PASS")
    try:
        text = digest(normalize(state))
        check("summary for the AI", "PASS", f"{len(text)} characters (about {len(text) // 4} tokens)")
    except Exception as e:  # noqa: BLE001
        check("summary for the AI", "FAIL", f"{type(e).__name__}: {e}")
    tools = state.get("tools") if isinstance(state.get("tools"), dict) else {}
    missing = sorted(t for t, on in tools.items() if on is None)
    check("DFHack tools the AI may use are installed", "WARN" if missing else "PASS",
          f"not installed: {', '.join(missing)} (the AI won't use them)" if missing
          else f"{len(tools)} tools, {sum(1 for v in tools.values() if v)} on")
    sup = state.get("supplies") if isinstance(state.get("supplies"), dict) else {}
    if sup.get("errors"):
        check("supplies counted", "WARN", f"some item lists couldn't be read: {json.dumps(sup['errors'])[:200]}")
    elif sup:
        check("supplies counted", "PASS", " ".join(f"{k} {v}" for k, v in sup.items() if isinstance(v, int)))
    dead = state.get("dead") if isinstance(state.get("dead"), dict) else {}
    if dead and "error" not in dead:
        check("the dead", "PASS", f"{dead.get('free_tombs')} free tombs of {dead.get('tomb_coffins')}, "
              f"{dead.get('unburied')} bodies unburied, {dead.get('ghosts')} ghosts")
    moods = state.get("moods") if isinstance(state.get("moods"), dict) else {}
    if moods and "error" not in moods:
        lst = moods.get("list") or []
        check("moods", "PASS", "; ".join(f"{m.get('name')}: {m.get('mood')}" for m in lst[:3]) or "nobody in a mood")
    mil = state.get("military") if isinstance(state.get("military"), dict) else {}
    if mil and "error" not in mil:
        sq = mil.get("squads") or []
        check("military", "PASS", f"{mil.get('soldiers', 0)} soldiers in {len(sq)} squads"
              + (": " + "; ".join(f"{q.get('name')} {q.get('members')}/{q.get('size')} {q.get('routine')}"
                                  for q in sq[:3]) if sq else "")
              + f" | {len(mil.get('gates') or [])} 'AI gate' lever(s)"
              + (f" | schedules: {', '.join(mil.get('routines') or [])}" if mil.get("routines") else ""))
        for gate in mil.get("gates") or []:
            if gate.get("linked"):
                check("AI gate lever", "PASS", f"lever id {gate.get('id')}, linked to {gate.get('linked')} "
                      f"thing(s), state {gate.get('state')}" + (", a pull is on its way" if gate.get("pending") else ""))
            else:
                check("AI gate lever", "WARN", f"lever id {gate.get('id')} isn't linked to a bridge or door yet, "
                      "so pulling it does nothing")
        g = mil.get("gear") if isinstance(mil.get("gear"), dict) else {}
        if g.get("error"):
            check("soldiers' gear", "WARN", f"couldn't be read: {g['error'][:150]}")
        elif g:
            check("soldiers' gear", "PASS",
                  f"{g.get('on_duty', '?')} of {g.get('soldiers')} soldiers on duty: {g.get('armed')} armed, "
                  f"{g.get('armored')} in body armour, {g.get('helmed')} with helms"
                  + (f", {g.get('shielded')} shields, {g.get('legged')} greaves, {g.get('booted')} metal boots, "
                     f"{g.get('gloved')} gauntlets" if "legged" in g else "")
                  + (f", {g.get('ranged_armed')} with crossbows ({g.get('spare_crossbows')} spare, "
                     f"{g.get('bolts')} bolts)" if "ranged_armed" in g else "")
                  + f"; {g.get('squads_with_uniform')}/{g.get('squads')} squads have a "
                  f"uniform; {g.get('forges')} forges; spare {json.dumps(g.get('spare'))}; bars {json.dumps(g.get('bars'))}")
            bk = mil.get("barracks") if isinstance(mil, dict) else None
            if isinstance(bk, list):
                check("barracks", "PASS" if bk or not g.get("squads") else "WARN",
                      "; ".join(f"zone {b.get('id')}: squads {b.get('squads')}" for b in bk if isinstance(b, dict))
                      or "no barracks zone yet")
            rg = mil.get("ranges") if isinstance(mil, dict) else None
            if isinstance(rg, list):
                check("archery ranges", "PASS",
                      "; ".join(f"zone {b.get('id')}: squads {b.get('squads')}" for b in rg if isinstance(b, dict))
                      or "none yet (dug once there's a crossbow squad)")
            if g.get("soldiers") and not g.get("squads_with_uniform"):
                # no uniform found: show where this DF keeps it, in case the search missed it
                try:
                    pr = bridge._call("probe").get("probe")
                    check("squad layout (for the developer)", "WARN",
                          "no squad uniform was found; if your squads do have one, please send this:\n        "
                          + json.dumps(pr)[:1500])
                except (BridgeError, DFHackError) as e:
                    check("squad layout (for the developer)", "WARN", str(e))
    elif mil.get("error"):
        check("military", "FAIL", str(mil["error"])[:200])
    ent = state.get("entrances") if isinstance(state.get("entrances"), dict) else {}
    if ent.get("error"):
        check("entrances", "FAIL", str(ent["error"])[:200])
    elif ent.get("scanned"):
        es = ent.get("entrances") or []
        check("entrances", "PASS", f"{len(es)} found ({sum(1 for e in es if e.get('sealed'))} can be closed), "
              f"{ent.get('inside_tiles')} tiles inside; watcher {'armed' if ent.get('armed') else 'off'}; "
              f"{ent.get('citizens_outside')} citizens outside")
    elif ent:
        check("entrances", "PASS", "not mapped yet (the overseer does it on its first check)")
    soc = state.get("society") if isinstance(state.get("society"), dict) else {}
    if soc and "error" not in soc:
        check("society", "PASS", f"vacant offices: {', '.join(soc.get('vacant') or []) or 'none'}; "
              f"{soc.get('starving')} starving, {soc.get('parched')} parched; "
              f"{soc.get('grazers_unpastured')} grazers without a pasture"
              + (f" (needing {soc.get('grazer_tiles')} tiles of grass; most room in a pasture "
                 f"{soc.get('pasture_spare')})" if soc.get("grazer_tiles") is not None else "")
              + (f"; {soc.get('ai_pastures')} AI pasture(s), {soc.get('ai_pasture_spare')} of "
                 f"{soc.get('ai_pasture_tiles')} tiles free" if soc.get("ai_pastures") is not None else "")
              + "; population cap "
              + (f"{soc.get('pop_cap')} (strict {soc.get('strict_pop_cap')})" if soc.get("pop_cap") is not None
                 else "not readable in this DF version"))
    elif soc.get("error"):
        check("society", "FAIL", str(soc["error"])[:200])
    farms = state.get("farms") if isinstance(state.get("farms"), dict) else {}
    if farms.get("error"):
        check("farm plots", "FAIL", str(farms["error"])[:200])
    elif farms:
        check("farm plots", "PASS", f"{farms.get('plots')} plots, {farms.get('tiles')} tiles "
              f"({farms.get('built')} built)")
    reg = state.get("registry")
    if isinstance(reg, dict) and reg.get("error"):
        check("registry of AI projects", "FAIL", str(reg["error"])[:200])
    elif isinstance(reg, list):
        bounded = sum(1 for p in reg if isinstance(p, dict) and isinstance(p.get("bounds"), dict))
        check("registry of AI projects", "PASS", f"{len(reg)} projects, {bounded} with their bounds")
    else:
        check("registry of AI projects", "WARN", "not in the report (bridge older than 0.31?)")
    try:
        t0 = time.perf_counter()
        pulse = bridge.state(include_units=False, tier="pulse")
        ms = (time.perf_counter() - t0) * 1000
        check("pulse report (between days)", "PASS" if pulse.get("tier") == "pulse" else "WARN",
              f"{len(json.dumps(pulse)) // 1000} KB, built in {pulse.get('_meta', {}).get('build_ms')} ms in game, "
              f"{ms:.0f} ms round trip" + ("" if pulse.get("tier") == "pulse" else " (the bridge sent a full report)"))
    except (BridgeError, DFHackError) as e:
        check("pulse report (between days)", "FAIL", str(e))
    if hasattr(bridge, "survey"):
        try:
            sv = bridge.survey()
            st = [x for x in (sv.get("stairs") or []) if isinstance(x, dict)]
            if st:
                m = st[0]
                soil = sv.get("soil") or []
                check("site survey (for the master plan)", "PASS",
                      f"{len(st)} main stair(s), the first at x{m.get('x')} y{m.get('y')} from elevation "
                      f"{m.get('elev_bottom')} to {m.get('elev_top')}; the dwarves mostly at "
                      f"{sv.get('citizen_elevation')}; soil at " + (", ".join(str(e) for e in soil[:6]) or "no level"))
            else:
                check("site survey (for the master plan)", "WARN",
                      "no staircase found where the dwarves live: " + str(sv.get("stairs_error") or "")[:120])
        except (BridgeError, DFHackError) as e:
            check("site survey (for the master plan)", "WARN", f"not available (bridge older than 0.32?): {e}")
    # what milestone 5 (defence) needs from this DF version: read-only
    try:
        ents = [e for e in (_d(state.get("entrances")).get("entrances") or [])
                if isinstance(e, dict) and not e.get("sealed") and isinstance(e.get("x"), int)][:10]
        spots = [(e["x"], e["y"], e["z"]) for e in ents]
        source = "open entrances"
        if not spots:
            fort0 = state.get("fort") if isinstance(state.get("fort"), dict) else {}
            spots = remembered_openings(bridge, fort0)[:16]
            source = "open entrances (as remembered)"
        coords = [str(v) for spot in spots for v in spot]
        pr = bridge._call("probe_defence", *coords).get("probe") or {}
        (Path(os.environ.get("DFAI_LOG_DIR") or PROJECT_ROOT / "logs")).mkdir(exist_ok=True)
        (Path(os.environ.get("DFAI_LOG_DIR") or PROJECT_ROOT / "logs") / "probe-defence.json").write_text(json.dumps(pr, indent=1), encoding="utf-8")
        need = {**(pr.get("job_types") or {}), **(pr.get("ref_types") or {})}
        missing = [k for k, v in need.items() if not v]
        roles = pr.get("job_roles")
        if isinstance(roles, dict) and not any(roles.values()):
            missing.append("the job item roles LinkToTarget/LinkToTrigger")
        levers = [l for l in pr.get("levers") or [] if isinstance(l, dict)]
        total = pr.get("levers_total", len(levers))
        gate = [l for l in levers if str(l.get("name") or "").lower() == "ai gate"]
        tiles = [t for t in pr.get("tiles") or [] if isinstance(t, dict)]

        def what(t):
            w = t.get("building") or t.get("shape") or "?"
            if t.get("trap"):
                w += f" ({t['trap']})"
            if t.get("liquid"):
                w += f", {t['liquid']} {t.get('depth')}/7"
            if t.get("linked"):
                w += " (linked to lever " + ", ".join(str(i) for i in t.get("levers") or []) + ")"
            return f"x{t['x']} y{t['y']}: {w}"
        things = [what(t) for t in tiles]
        check("defence probe (for milestone 5)", "WARN" if missing else "PASS",
              (f"missing in this DF: {', '.join(missing)}; " if missing else "lever links possible; ")
              + f"{total} lever(s), {sum(1 for l in levers if l.get('targets') or l.get('mechanisms'))} of the "
              + f"{len(levers)} listed linked"
              + (f" ('AI gate' id {gate[0].get('id')}: {len(gate[0].get('targets') or [])} target(s))" if gate else "")
              + f"; {source}: " + ("; ".join(things) or "none known yet") + " (saved to logs/probe-defence.json)")
        # milestone 5a: could the AI gate lever be linked to a drawbridge in an
        # opening? (a dry run: checks the lever, the bridge and 2 free mechanisms)
        bridges = [t for t in tiles if t.get("building") == "Bridge" and isinstance(t.get("id"), int)]
        if gate and bridges and not gate[0].get("mechanisms"):
            r = bridge.act({"type": "link_lever", "lever_id": gate[0]["id"], "target_id": bridges[0]["id"],
                            "dry_run": True})
            if r.get("ok"):
                check("lever link dry run", "PASS",
                      f"'AI gate' lever {gate[0]['id']} could be linked to the bridge at x{bridges[0]['x']} "
                      f"y{bridges[0]['y']} ({r.get('mechanisms')} free mechanisms found)")
            else:
                check("lever link dry run", "WARN", str(r.get("error") or r)[:160])
    except (BridgeError, DFHackError) as e:
        check("defence probe (for milestone 5)", "WARN", f"not available (bridge older than 0.33.3?): {e}")
    # keeper --revive: lua/ai-title.lua (loads the fort at the title screen) and a launch command
    try:
        out = bridge.df.run("lua", "print(dfhack.findScript('ai-title') and 'LOADSAVE-YES' or 'LOADSAVE-NO')")
        import revive
        has = "LOADSAVE-YES" in out
        launch = revive.launch_command()
        check("bringing the game back (keeper --revive)", "PASS" if has and launch else "WARN",
              ("ai-title is there (loads the save at the title screen)" if has else "DFHack can't find ai-title.lua: "
               "a game left at the title screen can't be loaded by the keeper")
              + ("; df_launch: " + launch if launch else "; no \"df_launch\" in config.json (the path to Dwarf "
                 "Fortress.exe or a steam:// link), so a closed game can't be started again"))
    except Exception as e:  # noqa: BLE001
        check("bringing the game back (keeper --revive)", "WARN", f"couldn't check: {e}"[:160])
    # the long unattended run (brain/keeper.py): can the game be saved each season?
    try:
        r = bridge.act({"type": "save_game", "dry_run": True})
        check("unattended run (keeper)", "PASS" if r.get("ok") else "WARN",
              "DF's own seasonal autosave saves the run (the AI saves only with --save-seasons; "
              "DFHack's quicksave is there for that)" if r.get("ok")
              else f"keep DF's own seasonal autosave on: the AI can't save ({r.get('error')})")
        q = bridge.act({"type": "quiet_announcements", "dry_run": True})
        check("announcements that stop the game", "PASS" if q.get("ok") else "WARN",
              f"{q.get('pausing')} kinds pause the game, {q.get('boxes')} open a box; an unattended run turns "
              "both off until DF restarts" if q.get("ok")
              else f"can't reach DF's announcement settings ({q.get('error')}): popups are taken off when they stall")
    except (BridgeError, DFHackError) as e:
        check("unattended run (keeper)", "WARN", f"not available (bridge older than 0.36?): {e}")
    # a fresh embark: where would the first staircase go?
    try:
        f = bridge.act({"type": "found_fort", "dry_run": True})
        if f.get("rejected") and "already has a staircase" in str(f.get("error")):
            check("founding (a fresh embark)", "PASS", "not needed here: the fort has its staircases")
        elif f.get("ok"):
            check("founding (a fresh embark)", "PASS",
                  f"the first stair would go beside {f.get('near')} at x{f.get('x')} y{f.get('y')}, "
                  f"{f.get('levels')} level(s) down" + (" to rock" if f.get("rock") else ""))
        else:
            check("founding (a fresh embark)", "WARN", str(f.get("error"))[:160])
    except (BridgeError, DFHackError) as e:
        check("founding (a fresh embark)", "WARN", f"not available (bridge older than 0.37?): {e}")
    # who does what: each job's work detail, its mode and its workers
    lb = state.get("labor")
    if isinstance(lb, dict) and "error" not in lb and isinstance(lb.get("jobs"), dict):
        parts = []
        for job in ("mining", "woodcutting", "gathering", "fishing", "farming"):
            j = lb["jobs"].get(job) or {}
            mode = {"OnlySelectedDoesThis": "selected", "EverybodyDoesThis": "everybody",
                    "NobodyDoesThis": "nobody", "Default": "default"}.get(j.get("mode"), j.get("mode") or "?")
            parts.append(f"{job} {j.get('doing')} ({j.get('detail') or 'no detail'}: {mode}"
                         + (", OUT OF ORDER" if j.get("unsorted") else "")
                         + (f", {j.get('tools')} tool(s) free" if "tools" in j else "") + ")")
        check("who does what (work details)", "PASS" if all((lb["jobs"].get(k) or {}).get("detail") for k in lb["jobs"])
              else "WARN", "; ".join(parts))
        wt, sk = lb.get("waiting"), lb.get("skilled_off")
        if isinstance(wt, list):
            text = "; ".join(f"{w.get('labor')} {w.get('jobs')} job(s), {w.get('holders')} doing it "
                             f"({w.get('idle')} free; {w.get('detail') or 'no detail'})" for w in wt[:6]
                             if isinstance(w, dict)) or "no job waits for a worker"
            if isinstance(sk, list) and sk:
                text += " | skilled but not on it: " + ", ".join(f"{k.get('labor')} {k.get('skilled')}"
                                                              for k in sk[:6] if isinstance(k, dict))
            check("work waiting for a worker", "PASS", text)
        else:
            check("work waiting for a worker", "WARN", f"not available: {wt}"[:160])
        from planner import food_per_dwarf
        st = state.get("stocks") if isinstance(state.get("stocks"), dict) else {}
        check("food before farms", "PASS",
              f"{food_per_dwarf(state):g} food a dwarf (meals {st.get('prepared_meals', 0)}, meat {st.get('meat', 0)}, "
              f"fish {st.get('fish', 0)}+{st.get('raw_fish', 0)} raw, plants {st.get('plants', 0)}, "
              f"fruit and leaves {st.get('plant_growths', 0)}, cheese {st.get('cheese', 0)}, eggs {st.get('eggs', 0)}); "
              f"{lb.get('shrubs')} shrub(s) to gather near the fort ({lb.get('gather_marked')} marked), "
              f"{lb.get('fish_water')} tile(s) of water to fish in, {lb.get('dig')} tile(s) to dig")
        try:
            r = bridge.act({"type": "assign_labor", "job": "mining", "count": 10, "dry_run": True})
            if r.get("ok"):
                check("miners dry run", "PASS", f"would let {', '.join(r.get('assigned') or [])} mine")
            else:
                check("miners dry run", "PASS", str(r.get("error"))[:160])
        except (BridgeError, DFHackError) as e:
            check("miners dry run", "WARN", str(e)[:160])
    else:
        check("who does what (work details)", "WARN", f"not available (bridge older than 0.39?): {lb}"[:160])
    # metal: ore uncovered near the fort, and the vein the AI would mine
    ind = state.get("industry")
    if isinstance(ind, dict) and "error" not in ind and isinstance(ind.get("ores"), dict):
        ores = ind["ores"]
        text = ", ".join(f"{m.lower()} {o.get('tiles')} tiles ({str(o.get('ore')).lower()})"
                         for m, o in ores.items() if isinstance(o, dict)) or "none uncovered yet"
        best = next((m for m in ("IRON", "COPPER", "TIN", "BISMUTH", "SILVER") if m in ores), None)
        if best:
            try:
                r = bridge.act({"type": "mine_ore", "metal": best, "count": 40, "dry_run": True})
                text += (f"; would mine {r.get('tiles')} tiles of {str(r.get('ore')).lower()} from x{r.get('x')} "
                         f"y{r.get('y')}" if r.get("ok") else f"; {r.get('error')}")
            except (BridgeError, DFHackError) as e:
                text += f"; {e}"
        by = ind.get("ore_stock_by") if isinstance(ind.get("ore_stock_by"), dict) else {}
        if by:
            text += "; dug and waiting for the smelter: " + ", ".join(
                f"{k.lower()} {v.get('n')}" for k, v in sorted(by.items(), key=lambda kv: -(kv[1].get("n") or 0)))
        if "flux_stock" in ind:
            text += f"; flux stone for steel: {ind.get('flux_stock')}"
        check("ore near the fort", "PASS", text[:300])
    else:
        check("ore near the fort", "WARN", f"not available (bridge older than 0.42?): {ind}"[:160])
    # trade: the depot, caravans, and crafts to take there
    tr = state.get("trade")
    if isinstance(tr, dict) and "error" not in tr and "depot" in tr:
        cs = ", ".join(f"{c.get('civ')} ({c.get('state')})" for c in (tr.get("caravans") or []) if isinstance(c, dict))
        check("trade", "PASS", ("a depot" if tr.get("depot") else "no depot yet")
              + (f"; {tr.get('goods')} crafts to sell (worth {tr.get('goods_value')})" if tr.get("depot") else "")
              + (f"; caravans: {cs}" if cs else "; no caravan here"))
    else:
        check("trade", "WARN", f"not available (bridge older than 0.43?): {tr}"[:160])
    ut = (state.get("military") or {}).get("uniform_templates") if isinstance(state.get("military"), dict) else None
    if isinstance(ut, list):
        check("uniform templates (for squads)", "PASS", ", ".join(map(str, ut)) or "none")
    # each soldier: what the uniform asks for, what's assigned, what they carry
    try:
        r = bridge._call("probe_squads")
        rows = [x for x in (r.get("soldiers") or []) if isinstance(x, dict)]
        text = " | ".join(f"{x.get('name')}: asks {', '.join(x.get('uniform') or []) or 'nothing'}; "
                          f"{x.get('assigned')} assigned; carries {', '.join(x.get('carries') or []) or 'nothing'}"
                          for x in rows[:3])
        check("soldiers' equipment (probe)", "PASS", text[:600] or "no soldiers")
        # the whole probe, with the items the game assigned and where they lie
        try:
            (Path(os.environ.get("DFAI_LOG_DIR") or PROJECT_ROOT / "logs")).mkdir(exist_ok=True)
            (Path(os.environ.get("DFAI_LOG_DIR") or PROJECT_ROOT / "logs") / "probe-squads.json").write_text(json.dumps(r, indent=1, ensure_ascii=False),
                                                             encoding="utf-8")
            first = next((x for x in rows if x.get("assigned_items")), None)
            if first:
                check("soldiers' assigned gear (probe)", "PASS",
                      f"{first.get('name')}: " + "; ".join(first["assigned_items"][:4])[:500]
                      + " (all soldiers in logs/probe-squads.json)")
        except OSError:
            pass
    except (BridgeError, DFHackError) as e:
        check("soldiers' equipment (probe)", "WARN", f"not available: {e}"[:160])
    # each squad's uniform, and what the AI would give one without
    sqs = [q for q in ((state.get("military") or {}).get("squads") or []) if isinstance(q, dict)]
    if sqs and "uniform" in sqs[0]:
        parts = []
        for q in sqs:
            q = dict(q, name=q.get("name") or f"squad {q.get('id')}")
            if q.get("uniform"):
                parts.append(f"{q.get('name')}: " + (f"{q['ai_uniform']} (the AI's)" if q.get("ai_uniform") else "set by you"))
            else:
                try:
                    r = bridge.act({"type": "set_uniform", "squad_id": q.get("id"), "kind": "leather", "dry_run": True})
                    parts.append(f"{q.get('name')}: none, the AI would give it {r.get('template')}" if r.get("ok")
                                 else f"{q.get('name')}: none ({r.get('error')})")
                except (BridgeError, DFHackError) as e:
                    parts.append(f"{q.get('name')}: none ({e})")
        check("squads' uniforms", "PASS", "; ".join(parts))
    # a new squad: which post would lead it, and who
    try:
        r = bridge.act({"type": "make_squad", "dry_run": True})
        check("a new squad (the AI makes)", "PASS",
              (f"would make one led by the {r.get('office')}, "
               + (f"appointing {r.get('leader')}" if r.get("appoint") else f"{r.get('leader')} (holds it already)"))
              if r.get("ok") else str(r.get("error"))[:160])
    except (BridgeError, DFHackError) as e:
        check("a new squad (the AI makes)", "WARN", f"not available (bridge older than 0.41?): {e}"[:160])
    # the fort's offices, and whom the AI would appoint
    of = state.get("offices")
    if isinstance(of, dict) and "error" not in of and isinstance(of.get("offices"), dict):
        parts = []
        for code in ("MANAGER", "BOOKKEEPER", "BROKER", "CHIEF_MEDICAL_DWARF", "SHERIFF"):
            o = of["offices"].get(code)
            if not isinstance(o, dict):
                parts.append(f"{code.lower()}: no such office yet")
            elif o.get("held"):
                parts.append(f"{code.lower()}: {', '.join(o['held'])}")
            else:
                try:
                    r = bridge.act({"type": "appoint", "office": code, "dry_run": True})
                    parts.append(f"{code.lower()}: vacant, the AI would appoint {r.get('name')}" if r.get("ok")
                                 else f"{code.lower()}: vacant ({r.get('error')})")
                except (BridgeError, DFHackError) as e:
                    parts.append(f"{code.lower()}: vacant ({e})")
        check("offices (the AI appoints)", "PASS", "; ".join(parts))
    else:
        check("offices (the AI appoints)", "WARN", f"not available (bridge older than 0.41?): {of}"[:160])
    # plant-gathering jobs: what they're aimed at (a fort had ~1000 of them)
    jb = state.get("jobs") if isinstance(state.get("jobs"), dict) else {}
    gt = jb.get("gather_targets")
    if isinstance(gt, dict):
        n = (jb.get("by_type") or {}).get("GatherPlants", 0)
        check("plant-gathering jobs", "PASS" if n < 200 else "WARN",
              f"{n} job(s)" + (": " + ", ".join(f"{k} {v}" for k, v in sorted(gt.items(), key=lambda kv: -kv[1]))
                               if gt else ""))
    # rooms the nobles' offices ask for
    nr = state.get("noble_rooms")
    if isinstance(nr, dict) and "error" not in nr and isinstance(nr.get("free"), dict):
        wants = [f"{n.get('name')} wants {'/'.join(n.get('needs') or [])}" for n in nr.get("nobles") or []
                 if isinstance(n, dict)]
        free = ", ".join(f"{k} {v}" for k, v in sorted(nr["free"].items()))
        check("nobles' rooms", "PASS", ("; ".join(wants[:4]) or "every noble has their rooms") + f" (free: {free})")
    else:
        check("nobles' rooms", "WARN", f"not available (bridge older than 0.43?): {nr}"[:160])
    # stone the masons may use (economic stone is kept from ordinary jobs)
    su = state.get("stone_use")
    if isinstance(su, dict) and isinstance(su.get("usable"), int):
        econ = su.get("economic") if isinstance(su.get("economic"), dict) else {}
        kinds = ", ".join(f"{k.lower()} {v.get('n')}" + (" (ore)" if v.get("ore") else " (flux)" if v.get("flux") else "")
                          for k, v in sorted(econ.items(), key=lambda kv: -(kv[1].get("n") or 0))[:6])
        text = f"{su['usable']} boulder(s); kept as economic: {kinds or 'none'}"
        try:
            q = bridge.act({"type": "quarry", "count": 30, "dry_run": True})
            text += (f"; a quarry would dig {q.get('tiles')} tile(s) of {str(q.get('stone')).lower()} at "
                     f"x{q.get('x')} y{q.get('y')}" if q.get("ok") else f"; quarry: {q.get('error')}")
        except (BridgeError, DFHackError) as e:
            text += f"; quarry: {e}"
        check("stone the masons may use", "PASS" if su["usable"] >= 10 else "WARN", text[:300])
    # ready for a siege? (the season report's line)
    try:
        import report as _report
        line = _report.readiness_line(state)
        check("ready for a siege", "PASS" if line.startswith("ready") else "WARN", line[:300])
    except Exception as e:  # noqa: BLE001
        check("ready for a siege", "WARN", f"couldn't judge: {e}"[:160])
    # hauling: feeder stockpiles beside the workshops and the depot
    lg = state.get("logistics")
    if isinstance(lg, dict) and isinstance(lg.get("feeders"), list):
        fd = [f for f in lg["feeders"] if isinstance(f, dict)]
        missing = [f"{f.get('kind')} ({f.get('what')})" for f in fd if not f.get("has")]
        check("feeder stockpiles", "PASS", f"{len(fd) - len(missing)} of {len(fd)} workshops have a pile beside them"
              + (f"; without: {', '.join(missing[:8])}" if missing else ""))
        try:
            first = next((f for f in fd if not f.get("has")), None)
            if first:
                r = bridge.act({"type": "feeder_pile", "building_id": first["id"], "dry_run": True})
                check("feeder dry run", "PASS" if r.get("ok") else "WARN",
                      (f"a {r.get('size')}x{r.get('size')} {r.get('what')} pile would go at x{r.get('x')} "
                       f"y{r.get('y')} elevation {r.get('elevation')} beside the {r.get('kind')}") if r.get("ok")
                      else str(r.get("error"))[:160])
        except (BridgeError, DFHackError) as e:
            check("feeder dry run", "WARN", str(e)[:160])
        stg = lg.get("storage") if isinstance(lg.get("storage"), dict) else {}
        if stg and "error" not in stg:
            from planner import PLANNER_CONFIG, full_stores
            full = full_stores(state, PLANNER_CONFIG)
            check("storage", "WARN" if full else "PASS",
                  "; ".join(f"{k.replace('_', ' ')} {v.get('used')}/{v.get('tiles')} used, {v.get('loose')} loose"
                            for k, v in sorted(stg.items()) if isinstance(v, dict))[:300]
                  + (f" | full, more storage wanted: {', '.join(full)}" if full else ""))
        c = lg.get("counts") if isinstance(lg.get("counts"), dict) else {}
        if c:
            check("fort size (what slows the game)", "PASS",
                  f"{c.get('items')} items, {c.get('units')} creatures active, {c.get('jobs')} jobs")
    else:
        check("feeder stockpiles", "WARN", f"not available: {lg}"[:160])
    # needs: what the dwarves miss
    nd = state.get("needs")
    if isinstance(nd, dict) and "error" not in nd:
        rows = sorted(((int((v or {}).get("distracted") or 0), k) for k, v in (nd.get("needs") or {}).items()),
                      reverse=True)
        top = ", ".join(f"{k} {n}" for n, k in rows[:6] if n) or "nobody is distracted by an unmet need"
        st = nd.get("stressed") or []
        check("needs (what the dwarves miss)", "WARN" if any(x.get("stress") == "miserable" for x in st) else "PASS",
              f"{top} | most stressed: " + (", ".join(f"{x.get('name')} {x.get('stress')}" for x in st[:3]) or "none"))
    else:
        check("needs (what the dwarves miss)", "WARN", f"not available: {nd}"[:160])
    # the deep: caverns, great dangers, cursed citizens
    dp = state.get("deep")
    if isinstance(dp, dict) and "error" not in dp:
        cav = "; ".join(f"{c.get('name')} " + ("not found yet" if not c.get("discovered") else
                        f"found, {'OPEN to the fort' if c.get('open') else 'not joined to the fort'} "
                        f"({c.get('seen')} tiles seen)") for c in dp.get("caverns") or [] if isinstance(c, dict))
        dz = ", ".join(f"{x.get('name')} ({x.get('kind')}, {x.get('layer')})" for x in dp.get("dangers") or []
                       if isinstance(x, dict)) or "none"
        cu = ", ".join(f"{c.get('name')} ({c.get('kind')})" for c in dp.get("cursed") or [] if isinstance(c, dict)) or "none"
        bad = any(isinstance(c, dict) and c.get("open") for c in dp.get("caverns") or []) or cu != "none"
        check("the deep", "WARN" if bad else "PASS", f"{cav or 'no caverns on this map'} | great dangers: {dz} | "
              f"cursed citizens: {cu}"[:300])
    else:
        check("the deep", "WARN", f"not available: {dp}"[:160])
    fort = state.get("fort") if isinstance(state.get("fort"), dict) else {}
    check("fort identity (for the AI's memory)", "PASS" if fort.get("save_dir") and fort.get("site_id") is not None
          else "FAIL", f"{fort.get('save_dir')} site {fort.get('site_id')}")

    # 4. other read-only commands
    for name, call in (("map layers", bridge.map_info), ("memory in the save", lambda: bridge._call("memory", "raw", timeout=60)),
                       ("event watcher", lambda: bridge._call("watch"))):
        try:
            r = call()
            extra = ""
            if name == "memory in the save":
                extra = memory_detail(bridge, fort, r)
            elif name == "event watcher":
                extra = "watching" if r.get("watching") else "not watching"
            elif name == "map layers":
                size = r.get("size") or []
                extra = f"map {'x'.join(str(v) for v in size)}, {len(r.get('layers') or [])} layers found"
            check(name, "PASS" if name != "event watcher" or r.get("watching") else "FAIL", extra)
        except (BridgeError, DFHackError) as e:
            check(name, "FAIL", str(e))

    # 4b. announcements: how the latest ones are sorted (nothing is consumed)
    try:
        r = bridge._call("reports")
        reps = r.get("reports") or []
        sorted_ = [x for x in reps if x.get("topic")]
        topics = sorted({x["topic"] for x in sorted_})
        check("announcements read", "PASS",
              f"{len(reps)} recent, {len(sorted_)} recognised" + (f" ({', '.join(topics)})" if topics else ""))
    except (BridgeError, DFHackError) as e:
        check("announcements read", "FAIL", str(e))

    # 5. bad actions are refused before they do anything
    must_refuse(bridge, "unknown action refused", {"type": "self_destruct"}, halted)
    must_refuse(bridge, "tool outside the allowlist refused", {"type": "tool", "name": "exterminate",
                                                               "enabled": True}, halted)
    must_refuse(bridge, "silly work order refused", {"type": "work_order", "recipe": "brew_drink",
                                                     "amount": -5}, halted)
    must_refuse(bridge, "unknown level kind refused", {"type": "start_project", "kind": "moat",
                                                       "dry_run": True}, halted)
    must_refuse(bridge, "silly farm request refused", {"type": "farm_plots", "tiles": 0,
                                                       "dry_run": True}, halted)

    # 6. a building dry run: finds a site and checks it, digs nothing
    # (allowed while halted from bridge 0.13.2: a dry run changes nothing)
    try:
        r = bridge.act({"type": "start_project", "kind": "bedrooms", "rooms": 4, "dry_run": True})
        if r.get("ok") and r.get("dry_run"):
            check("building dry run", "PASS", f"a 4-room bedroom level would fit at elevation {r.get('elevation')}")
        elif r.get("ok"):
            check("building dry run", "FAIL", "the game didn't treat it as a dry run!")
        elif r.get("halted"):
            check("building dry run", "WARN", "skipped: the AI is halted and the game's bridge is older "
                  "than 0.13.2 (restart DF)")
        else:
            check("building dry run", "WARN", f"refused: {r.get('error')}")
    except BridgeError as e:
        check("building dry run", "WARN", f"no site: {e} (normal if the fort has no room left)")
    except DFHackError as e:
        check("building dry run", "FAIL", str(e))

    # 6b. a farm dry run: where plots would go (existing soil or muddy floor
    # first, else a farm level in soil); places and digs nothing
    try:
        r = bridge.act({"type": "farm_plots", "tiles": 20, "dig": True, "dry_run": True})
        lvl = r.get("level") if isinstance(r.get("level"), dict) else {}
        if r.get("ok") and r.get("dry_run"):
            spots = r.get("placed") or []
            where = ", ".join(f"{p.get('w')}x{p.get('h')} at x{p.get('x')} y{p.get('y')} elevation "
                              f"{p.get('elevation')}" for p in spots[:3])
            check("farm dry run", "PASS", f"{r.get('tiles')} tiles on existing floor"
                  + (f" ({where})" if where else "")
                  + (f"; a farm level would fit at elevation {lvl.get('elevation')}" if lvl.get("ok")
                     else f"; no farm level: {lvl.get('error')}" if lvl else ""))
        elif r.get("ok"):
            check("farm dry run", "FAIL", "the game didn't treat it as a dry run!")
        else:
            check("farm dry run", "WARN", f"nowhere for farm plots: {str(r.get('error'))[:200]}")
    except BridgeError as e:
        check("farm dry run", "WARN", str(e))
    except DFHackError as e:
        check("farm dry run", "FAIL", str(e))

    # 6c. a well dry run: where a well would go; digs nothing
    try:
        r = bridge.act({"type": "place_well", "dry_run": True})
        if r.get("ok") and r.get("dry_run"):
            check("well dry run", "PASS", f"a well would go at x{r.get('x')} y{r.get('y')} elevation "
                  f"{r.get('elevation')}, {r.get('drop')} level(s) above the water"
                  + (", in a dining or meeting hall" if r.get("in_hall") else ""))
        elif r.get("ok"):
            check("well dry run", "FAIL", "the game didn't treat it as a dry run!")
        else:
            check("well dry run", "WARN", f"no spot for a well: {str(r.get('error'))[:200]}")
    except BridgeError as e:
        check("well dry run", "WARN", str(e))
    except DFHackError as e:
        check("well dry run", "FAIL", str(e))

    # 6d. a pasture dry run: where grass for the herd is; zones nothing
    try:
        r = bridge.act({"type": "make_pasture", "tiles": 40, "dry_run": True})
        if r.get("ok") and r.get("dry_run"):
            zs = r.get("zones") or []
            check("pasture dry run", "PASS", f"{r.get('tiles')} tiles of grass in {len(zs)} pasture(s)"
                  + (f", the first {zs[0].get('w')}x{zs[0].get('h')} at x{zs[0].get('x')} y{zs[0].get('y')} "
                     f"elevation {zs[0].get('elevation')}" if zs else ""))
        elif r.get("ok"):
            check("pasture dry run", "FAIL", "the game didn't treat it as a dry run!")
        else:
            check("pasture dry run", "WARN", f"no grass for a pasture: {str(r.get('error'))[:200]}")
    except BridgeError as e:
        check("pasture dry run", "WARN", str(e))
    except DFHackError as e:
        check("pasture dry run", "FAIL", str(e))

    # 7. how long a quick check takes (the overseer makes one every 2 s)
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        bridge.status()
        times.append((time.perf_counter() - t0) * 1000)
    avg = sum(times) / len(times)
    check("quick check speed", "PASS" if avg < 1000 else "WARN", f"{avg:.0f} ms on average")
    return report()


def report() -> int:
    fails = sum(1 for lv, _, _ in RESULTS if lv == "FAIL")
    warns = sum(1 for lv, _, _ in RESULTS if lv == "WARN")
    print(f"\n{len(RESULTS) - fails - warns} passed, {warns} warnings, {fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
