"""The overseer's cycle: one_cycle (observe, note, plan, act, record) and its
guarded steps. Split from overseer.py (r7 d1); overseer re-exports every
name. What it uses from overseer is looked up there at call time (_ov,
_late), so the tests' patches of overseer.say, .plan, .record, ... hold.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from bridge import Bridge, BridgeError  # noqa: F401  (Bridge: the annotations)
from dfhack import DFHackError
from planner import NEEDS_YOU, PLANNER_CONFIG, abs_tick, effective_config, note_tantrums, select
from planner_guards import guard_fail, guard_lines, guard_ok
from planner_core import limit_exempt
from planner_tantrums import fight_journal, note_tantrum_book
from planner_society import note_heists
from planner_shaft_guard import remember_shaft_beasts   # (item16) the shaft guard's great beasts remembered
from planner_moods import mood_journal
from planner_missions import mission_journal
from planner_cleanup import CLEANUP_ACTIONS, cleanup_journal, cleanup_words
from planner_thirst import thirst_journal
from planner_recovery import recovery_journal
from planner_shopslots import shop_level_action
from planner_floors import floor_action, floor_outcome, not_on_floor_words
from planner_floors import journal_hint as floor_journal_hint
from planner_floors import forget_sent as floor_forget_sent
from planner_meetings import meeting_report_lines
from planner_threats import note_intrusions
from planner_hostile_arrivals import note_hostile_arrivals   # (r34b)
from planner_holdfast import note_thief_targets
from planner_attempts import refusal_target   # (F2b) a refusal's site, for the attempt ledger
import seen as seen_ledger
import atlas
import backup
import fort_run as runid
import fallen
import health_check
import season as season_mod
import calibrate
import chronicle
import crisis
import rests
import learning
import masterplan
import memstore
import outcomes
import report
from digest import _d, normalize, project_text
from review import hold_review_proposals, maybe_review, note_events, shadow_on
from storyteller import maybe_tell
from overseer_words import camera_feed, death_words, DECLINE_DAYS, is_big, journal_event, MODES, proposal_id, short
from overseer_world import culture_update, _note_adjust, push_culture, push_learned, _style_choices

__all__ = ["cycle_step", "one_cycle"]

_ov = None     # the overseer module: set by overseer.py as it imports this part (its own
               # module object, also when it runs as the main script)


def _late(name: str):
    """A call-time forwarder to overseer.<name> (the one there now: a test's patch, too)."""
    def call(*a, **kw):
        return getattr(_ov, name)(*a, **kw)
    call.__name__ = call.__qualname__ = name
    return call


acknowledged = _late("acknowledged")
apply_preset = _late("apply_preset")
date_str = _late("date_str")
expire_adjustments = _late("expire_adjustments")
flush_held = _late("flush_held")
fort_key = _late("fort_key")
get_state = _late("get_state")
journal = _late("journal")
keep_state = _late("keep_state")
load = _late("load")
_log_error = _late("_log_error")
note_cycle = _late("note_cycle")
note_perf = _late("note_perf")
plan = _late("plan")
probe_gear = _late("probe_gear")
probe_posts = _late("probe_posts")
record = _late("record")
remember_world = _late("remember_world")
report_status = _late("report_status")
rules_request = _late("rules_request")
save = _late("save")
say = _late("say")
show_changed = _late("show_changed")
write_ledger = _late("write_ledger")


def cycle_step(memory, state: dict, name: str, fn, *args, default=None, **kw):
    """(0.105.48, K6) One step of the cycle on its own (A9: observe, the event
    notes, calibrate, outcomes, culture, the strategist's review, select, the
    record after acting raised out of one_cycle, nothing was planned, and a
    cycle that failed every time ran for ever planning nothing). A failure is
    said, its traceback logged, counted in memory.guard_fails (a "rule
    cycle_<step> failed" note each cycle, the health check's standing lines)
    and the cycle goes on with `default`."""
    try:
        out = fn(*args, **kw)
    except Exception as e:  # noqa: BLE001
        try:
            now = abs_tick(state)
        except Exception:  # noqa: BLE001
            now = None
        guard_fail(memory, "cycle_" + name, e, now)
        say(f"Step {name} failed ({type(e).__name__}: {str(e)[:160]}); the cycle goes on without it "
            "(details in logs/overseer-errors.log)")
        _log_error()
        return default
    guard_ok(memory, "cycle_" + name)
    return out


def _calibrate_step(state: dict, memory, key: str, cfg: dict) -> None:
    """The self-tuning's changes, said and journalled (one_cycle's step)."""
    for ch in calibrate.update(state, memory, cfg, memory.adjust):
        say(f"Self-tuned: {ch['name']} {ch['old']} -> {ch['new']} ({ch['why']})")
        journal({"kind": "calibration", "fort": key, "date": state["date"], **ch})
        if ch["up"]:
            kind = {"drink_per_dwarf": "drink_target", "meals_per_dwarf": "meal_target",
                    "farm_tiles_per_dwarf": "farm_target", "pasture_margin": "pasture_margin"}[ch["key"]]
            ent = outcomes.open_entry(state, memory, kind, f"{ch['name']} {ch['old']} -> {ch['new']}",
                                      "self-tuning", expect="down" if kind == "pasture_margin" else "up")
            if ent is not None:     # (0.102.7, B6) so a bad verdict can take it back
                ent.update(tune_key=ch["key"], tune_old=ch["old"], tune_new=ch["new"])


def _outcomes_step(state: dict, memory, key: str) -> None:
    """The verdicts on earlier changes, said and journalled (one_cycle's step)."""
    for e in outcomes.judge(state, memory):
        say(f"Outcome: {outcomes.KINDS[e['kind']][3]} ({e['by']}): "
            f"{outcomes.VERDICT_TEXT[e['verdict']]}, {e['why']}")
        journal({"kind": "outcome", "fort": key, "date": state["date"], "of": e.get("kind"),
                 **{k: e.get(k) for k in ("what", "by", "metric", "expect", "before", "verdict", "why")}})
        back = calibrate.heed(e, memory, state)
        if back:
            say(f"Self-tuned: {back['name']} {back['old']} -> {back['new']} ({back['why']})")
            journal({"kind": "calibration", "fort": key, "date": state["date"], **back})


def one_cycle(bridge: Bridge, autopilot: bool, backend=None, controls: dict | None = None,
              mode_override: str | None = None, tier: str = "daily") -> None:
    if controls is None:
        try:
            st = bridge.status()
        except (BridgeError, DFHackError):
            st = {}
        controls = {"halted": st.get("halted") is True, "decisions": st.get("decisions") or {}}
    state = get_state(bridge, tier)
    if controls.get("fps_low"):
        state["fps_low"] = controls["fps_low"]     # measured by the main loop (unattended)
    if isinstance(controls.get("fps_seen"), dict):
        state["fps_seen"] = controls["fps_seen"]   # (r9, B8) and what it judged by (kept in the saved states)
    # (0.105.48, K9) nobody at the game (--unattended, or the keeper's DFAI_PIN):
    # the planner answers DF's meeting screen only then (planner_world)
    state["unattended"] = bool(controls.get("unattended") or os.environ.get("DFAI_PIN"))
    key = fort_key(state)
    if key is None:
        say("Couldn't tell which fort is loaded (report section 'fort' failed); skipping this cycle.")
        return
    # (0.105.0) under the keeper: only the fort it pinned (brain/pin.py)
    try:
        import pin
        _f = _d(state.get("fort"))
        refused = pin.refusal(_f.get("world"), _f.get("site_id"),
                              df_path=_d(getattr(bridge, "version", None)).get("df_path"))   # (K17)
    except Exception:  # noqa: BLE001
        refused = None
    _ov.PIN_SEEN["checked"], _ov.PIN_SEEN["refused"] = True, refused
    if refused:
        if refused not in _ov.WARNED:
            _ov.WARNED.add(refused)
            say(refused)
        return
    try:
        import scenario_mark                       # (0.105.0) a scenario copy waiting for its run id
        if scenario_mark.mark(bridge, state, say):
            key = fort_key(state)
    except Exception:  # noqa: BLE001
        pass
    try:
        memstore.note_world(key, (state.get("fort") or {}).get("world"),
                            save_dir=(state.get("fort") or {}).get("save_dir"))   # (r1g9) the folder by the save
    except Exception:  # noqa: BLE001  (the logs folder's name never stops the fort)
        pass
    try:      # (R29 W9) logs/ai-window.json: the strategist on for this fort for a span of game time
        import ai_window
        # only the folder's autopilot (the keeper's): a dry run watching beside it spends nothing
        if autopilot:
            backend = ai_window.WINDOW.backend(backend, state, key, _ov.make_backend, say, journal)
    except Exception:  # noqa: BLE001  (the window never stops a cycle)
        pass
    if _ov.PRESET:
        apply_preset(bridge, state, key, autopilot)    # (0.105.4) keeper.py --preset, before the first plan
    rules_request(bridge, autopilot)                   # (0.105.20) logs/rules-request.json
    memory, bank = load(key, bridge, prefer_logs=not autopilot, state=state)
    for k in sorted(memory._texts.get("frozen") or ()):
        if (key, k) not in _ov.WARNED:
            _ov.WARNED.add((key, k))
            say(f"Memory: the {k} part of this fort's memory couldn't be read (or comes from a newer "
                "version); it is left exactly as it is, and that part starts afresh for now.")
    if memory._texts.get("save_unread"):
        say("Memory: the save's memory couldn't be read this time; nothing is written into the save this cycle"
            + (f" ({memory._texts.get('save_unread_why')})" if memory._texts.get("save_unread_why") else "") + ".")
        if memory._texts.get("source") == "new":
            # (0.105.48, K8) and no copy in logs/ read either: a blank memory (no
            # master plan, cooldowns or saved-before marks) would be acted on and
            # then written over the only copy outside the save. Next cycle.
            say("Memory: no copy of this fort's memory could be read (the save's didn't answer, logs/ holds "
                "none for it): not acting this cycle, nothing written.")
            _ov.MEMORY_CACHE.pop(key, None)
            return
    if isinstance(state.get("fort"), dict) and runid.of(memory):
        state["fort"]["fort_run"] = runid.of(memory)   # (0.105.48, K8) for the backup's mark and last-fort.json
    to_save = False
    try:
        # (0.105.46, I1) each section of a full report, ok or {"error"}, tallied for
        # the seen ledger (brain/seen.py): before normalize swaps errors for defaults
        seen_ledger.note_report(state, memstore.fort_dir(key))
        # (r1g9) a fallen fort (no citizens left, no migrant wave coming), read
        # from the report as it came (normalize makes a failed section 0): said,
        # marked and its last report kept once; nothing is planned while it stands
        fallen_now = bool(autopilot) and fallen.note(state, key, memstore.fort_dir(key), say, journal)
        normalize(state)      # (13c) once, in place: the steps below read the sections as they are
        # (0.105.33 fix, runs) the report's date failed (normalize made it year
        # 0, tick 0): no learning, no note_cycle (it would wipe every cooldown,
        # loop count and "No" as from the future), no plan, no act and no record
        # at tick 0 this cycle; memory is left as the last good cycle saved it
        # (0.105.36, D7) checked before bridge.events() drains the game's
        # events: DF keeps them (deaths, heists, tantrums) for the next good cycle
        if chronicle.date_failed(state):
            say("The report's date couldn't be read this cycle: nothing planned, done or written into "
                "the fort's memory until it can be")
            try:
                when = date_str(state)
            except Exception:  # noqa: BLE001
                when = "?"
            report_status(bridge, {
                "mode": MODES.get(_d(state.get("settings")).get("mode"), MODES["autopilot"]),
                "acting": "waiting: the report's date couldn't be read", "date": when,
                "last": [f"{short(a['action'])}: {a.get('reason', '')}".rstrip(": ")
                         for a in memory.recent_actions[-5:]][::-1],
                "notes": [], "todo": [], "pending": [], "ack": [],
                "unattended": _ov.UNATTENDED,
            })
            return
        note_perf(state, key)
        _ov.LAST_FORT.update(key=key, date=state.get("date"))     # (r5 p2) for the main loop's meeting lines
        events = bridge.events()
        # (r5 p2) a ghost laid to rest is no death, whatever shape DF told it in:
        # a death told again (also after DF restarted: the memory keeps who was
        # told dead), of a ghost, or beside "put to rest"; the announcement is
        # topic `rest`, not a ghost risen. Every reader below gets them so.
        events = cycle_step(memory, state, "mark_rests",
                            lambda: rests.mark_rests(events, memory.dead_told, abs_tick(state)), default=events)
        seen: dict[str, int] = {}
        for ev in events:
            # (r1g8) a ghost laid to rest is no second death: journaled as
            # what it is (R-AD: 11 such counted again in B, A's Zulban twice)
            journal({"kind": "event", "fort": key, "event": journal_event(ev)})
            if ev.get("kind") == "death" and ev.get("again"):
                if ev.get("own_civ") and not ev.get("animal"):
                    line = "Laid to rest: " + death_words(ev)
                    seen[line] = seen.get(line, 0) + 1
                continue
            if ev.get("kind") == "report" and ev.get("topic") not in _ov.QUIET_TOPICS:
                # one line however the text runs (a name can hold a line break)
                line = f"Seen: {ev.get('topic')}: {' '.join(str(ev.get('text', '')).split())[:120]}"
                seen[line] = seen.get(line, 0) + 1
            elif (ev.get("kind") == "death" and ev.get("own_civ") and not ev.get("animal")) \
                    or (ev.get("kind") == "death" and ev.get("great")):
                line = "Died: " + death_words(ev)    # (0.104.100) how each one died, in the log
                seen[line] = seen.get(line, 0) + 1
        for line, n in seen.items():          # the same announcement 9 times is one line
            say(line + (f" (x{n})" if n > 1 else ""))

        # (0.97.1) your memory on the PC knows the fort by its line (world and
        # site: its autosaves and copies are one fort); a dry run doesn't write it
        line = learning.line_key(key, (state.get("fort") or {}).get("world"))
        # (0.105.48, K6) each step before the plan on its own (cycle_step): one
        # raising no longer stops the cycle before anything is planned
        learned_now = cycle_step(memory, state, "observe", lambda: learning.observe(state, memory, line, write_pc=autopilot),
                                 default=[])   # before note_cycle: it reads the tools
        cycle_step(memory, state, "expire_adjustments", lambda: expire_adjustments(memory, state))
        notes = list(cycle_step(memory, state, "note_cycle", lambda: note_cycle(state, memory)) or [])
        # (0.105.36, D7) a date-failed report returned above, so the date is good from here

        def _journals():
            for e in mood_journal(state, memory):     # (0.105.30) each mood's requests, once a day
                journal({"kind": "mood", "fort": key, "date": state["date"], **e})
            for e in mission_journal(memory):         # (0.105.39) missions out and back (planner_missions)
                journal({"kind": "mission", "fort": key, "date": state["date"], **e})
            for e in cleanup_journal(memory):         # (0.105.40) what the world cleanup found and removed
                journal({"kind": "cleanup", "fort": key, "date": state["date"], **e})
            for e in thirst_journal(state, memory):   # (0.105.46, I2) each death of thirst, with its last reason
                journal({"kind": "thirst_death", "fort": key, "date": state["date"], **e})
            for e in recovery_journal(memory):        # (0.105.46, I4) recovery entered, left, migrants called
                journal({"kind": "recovery", "fort": key, "date": state["date"], **e})
            for e in crisis.crisis_journal(memory):   # (r5 p2) crisis mode entered and left
                journal({"kind": "crisis", "fort": key, "date": state["date"], **e})
            for e in meeting_report_lines(events):    # (r5 p2) DF's word that the diplomats left
                journal({"kind": "meeting", "fort": key, "date": state["date"], **e})
            for e in fight_journal(state, memory):    # (item1) the fight watcher capped or broke up a fight
                journal({"kind": "fight_watch", "fort": key, "date": state["date"], **e})
            from planner_combat_log import combat_journal
            for e in combat_journal(state, memory, events):   # (R29 W6) how a hunt, lure or sortie ended
                say(f"Result: {e.get('text')}")
                journal({"kind": "combat_result", "fort": key, "date": state["date"], **e})
            from planner_siege_watch import siege_journal      # (R29 W2) a siege invited, its summary at the end
            for e in siege_journal(memory):
                say(f"Siege: {str(e.get('text') or e.get('what'))[:400]}")
                journal({"kind": "siege", "fort": key, "date": state["date"], **e})
        cycle_step(memory, state, "journals", _journals)
        cycle_step(memory, state, "note_tantrums", lambda: note_tantrums(state, memory, events))   # (0.104.31) tantrums counted for the jail
        cycle_step(memory, state, "note_tantrum_book", lambda: note_tantrum_book(state, memory, events))   # (0.105.47) tantrum/berserk/possession reports
        cycle_step(memory, state, "note_heists", lambda: note_heists(state, memory, events))       # (0.105.24) heists and visitors' killings
        cycle_step(memory, state, "note_intrusions", lambda: note_intrusions(state, memory, events))   # (0.105.30) DF's invasion records
        cycle_step(memory, state, "note_hostile_arrivals",
                   lambda: note_hostile_arrivals(state, memory, events))    # (r34b) a hostile arrival a threat at once
        cycle_step(memory, state, "note_thief_targets", lambda: note_thief_targets(state, memory, events))   # (0.105.47) a thief's artifact
        cycle_step(memory, state, "note_deaths", lambda: crisis.note_deaths(state, memory, events))   # (0.104.137) deaths for crisis mode
        cycle_step(memory, state, "shaft_beasts", lambda: remember_shaft_beasts(state, memory, events))   # (item16) the shaft guard's great beasts remembered
        cycle_step(memory, state, "note_events", lambda: note_events(state, memory, bank if backend else None, events))
        for line in learned_now or []:
            say(f"Learned: {line}")
            journal({"kind": "learned", "fort": key, "date": state["date"], "text": line})

        def _cfg():
            return effective_config(memory.adjust, calibration=calibrate.values(memory))
        cfg = cycle_step(memory, state, "config", _cfg, default=None) or PLANNER_CONFIG
        cycle_step(memory, state, "remember_world", lambda: remember_world(state, memory, events, key, cfg, learned_now, bridge))
        cycle_step(memory, state, "calibrate", _calibrate_step, state, memory, key, cfg)
        cfg = cycle_step(memory, state, "config", _cfg, default=None) or cfg
        cycle_step(memory, state, "outcomes", _outcomes_step, state, memory, key)
        style_before = _style_choices(memory)
        cycle_step(memory, state, "culture", lambda: culture_update(state, memory, events, key))
        style_after = _style_choices(memory)
        if style_before and style_after != style_before:
            changed = [a for a in style_after if style_after.get(a) != style_before.get(a)]
            cycle_step(memory, state, "style", outcomes.open_entry, state, memory, "style", "new style: " + ", ".join(
                f"{a} {style_after[a]}" for a in changed), "weights engine")
        if fallen_now:
            # (r1g9) B ran thousands of useless actions over 2.5 game years with 0 citizens
            proposals, plan_notes = [], ["the fort has fallen: nothing is planned or done until you act (load a "
                                         "save, or delete logs/fallen.json)"]
        else:
            proposals, plan_notes = cycle_step(memory, state, "plan", lambda: plan(state, memory, cfg)) or ([], [])
        try:
            from planner import agenda as _agenda
            if proposals or plan_notes:
                memory.agenda = _agenda(proposals, plan_notes)
        except Exception:  # noqa: BLE001  (the agenda is only words)
            pass
        notes += plan_notes

        # (0.104.3) the season's character decision by script: forts without
        # tokens, or whose AI review made no choice in the season's first two weeks
        # ((r4 k5) or whose AI only advises: its choice is journaled, never applied)
        if autopilot and not fallen_now and season_mod.due(state, memory) and (
                backend is None or season_mod.ai_gave_up(state, memory) or shadow_on()):
            try:
                choice = season_mod.pick(state, memory, cfg)
                said = season_mod.apply(choice, state, memory, memory.adjust)
                chronicle.add(memory, state, "season", choice.get("line") or "; ".join(said))
                for line in said:
                    say(f"  Season (script): {line} ({choice.get('why')})")
                journal({"fort": key, "date": state["date"], "kind": "season", "by": "script", "choice": choice,
                         "scores": {k: v[0] for k, v in season_mod.score_options(state, memory, cfg).items()}})
            except Exception as e:  # noqa: BLE001  (a season's choice never stops the fort)
                say(f"Season: no scripted choice ({type(e).__name__}: {e})")
        if backend is not None and not fallen_now:
            def _review():
                outcome = maybe_review(state, memory, bank, backend, bridge.version or {}, notes, proposals=proposals)
                for line in outcome.say:
                    say(line)
                if outcome.journal:
                    journal({"fort": key, "date": state["date"], **outcome.journal})
                ai_props = outcome.proposals
                try:     # (0.105.23) the strategist's levels keep under the surface in the Deep mine too
                    from planner import _deep_surface_filter, _traits as _plan_traits
                    ai_props = _deep_surface_filter(state, _plan_traits(state), memory, list(ai_props), notes)
                except Exception:  # noqa: BLE001  (never stops the cycle; the bridge's own checks still hold)
                    pass
                # (r4 k4, audit A7 B7) the crisis and recovery holds, as for the planner's own
                held_notes = []
                ai_props = hold_review_proposals(state, memory, list(ai_props), held_notes, cfg)
                for line in held_notes:
                    say(f"  AI review: {line}")
                notes.extend(n for n in held_notes if n not in notes)
                if not (outcome.journal or {}).get("shadow"):
                    _note_adjust(state, memory, outcome.journal, cfg)   # (r4 W1) advice only: nothing to judge
                return list(ai_props)
            # (0.105.48, K6) the strategist's review on its own: failing, the plan goes on without it
            proposals = (cycle_step(memory, state, "strategist", _review, default=None) or []) + proposals
            try:
                story = maybe_tell(state, memory, bank, backend)
                for line in story.say:
                    say(line)
                if story.text:
                    journal({"fort": key, "date": state["date"], "kind": "story", "text": story.text,
                             "tokens": story.used})
            except Exception as e:  # noqa: BLE001 - a story is never worth stopping the overseer for
                say(f"AI chronicle failed: {type(e).__name__}: {e}")

        # what you've turned down waits (or is left to you)
        proposals, learned_notes = cycle_step(memory, state, "learning_apply",
                                              lambda: learning.apply(proposals, memory, abs_tick(state))) or (proposals, [])
        notes += [n for n in learned_notes if n not in notes]
        # (0.105.48, K6) select() guards each proposal itself; failing whole, the
        # responses to danger still go (the limits' exempt rules), the rest wait
        allowed, held = cycle_step(memory, state, "select", lambda: select(proposals, state, memory, cfg)) or (
            [p for p in proposals if limit_exempt(p.rule)],
            [f"{p.rule}: the limits' check failed this cycle; it waits" for p in proposals if not limit_exempt(p.rule)])
        stopped = _ov.STOP_FILE.exists()
        halted = controls.get("halted") is True
        decisions = _d(controls.get("decisions"))
        settings = _d(state["settings"])
        mode = settings.get("mode") if settings.get("mode") in MODES else "autopilot"
        if mode_override in MODES:
            mode = mode_override      # scenario runs play unattended: nobody to ask
        acting = autopilot and not stopped and not halted and mode != "advisor"
        to_save = autopilot           # a dry run never writes into the save
        why_not = ("halted in the game" if halted else "STOP file present" if stopped
                   else "advisor mode: suggesting only" if mode == "advisor" else "")
        say(f"{date_str(state)}: {len(proposals)} proposal(s), {len(allowed)} allowed"
            + (f" [{why_not}: not acting]" if autopilot and why_not else ""))
        todo = [n[len(NEEDS_YOU):] for n in notes if n.startswith(NEEDS_YOU)]
        notes = [n for n in notes if not n.startswith(NEEDS_YOU)]
        try:
            import old_saves                     # (0.105.46, I6) old test saves, told once (the AI never deletes them)
            todo += old_saves.needs_you()
        except Exception:  # noqa: BLE001
            pass
        # (0.105.48, K6) the cycle's own failing steps (select, record's hooks, the
        # steps before the plan): a "rule <step> failed" note each cycle until it runs
        notes += [n for n in guard_lines(memory) if n not in notes]
        # (0.104.0) how long each Needs you and failing-rule line has stood (the run check)
        health_check.track_standing(key, todo, notes, abs_tick(state))
        show_changed(key, [f"  NEEDS YOU: {n}" for n in todo] + [f"  note: {n}" for n in notes]
                     + [f"  held: {h}" for h in held])

        if acting:
            push_culture(bridge, state, memory)
            push_learned(bridge, state, memory)
        now = abs_tick(state)
        pending, would = [], []
        memory.declined = {k: t for k, t in memory.declined.items() if 0 <= now - t < DECLINE_DAYS * 1200}
        results = []
        looked: set = set()          # (0.105.33) the answers read this cycle (only these are acknowledged)
        no_answer = False            # (0.104.138) an action the game didn't answer: the rest wait
        try:
            for p in allowed:
                floor_forget_sent()           # (r3 V4) no hint left over from an earlier send that never reached its line
                r = None
                if no_answer and acting:
                    say(f"  held: {short(p.action)} (the game didn't answer the last action; next cycle)")
                    continue
                if acting and mode == "copilot" and is_big(p.action):
                    pid = proposal_id(p)
                    answer = decisions.get(pid)
                    looked.add(pid)
                    if memory.saved_before == pid:
                        answer = "yes"        # you said Yes; the game was saved first
                    if answer == "no":
                        memory.declined[pid] = now
                        say(f"  you declined: {short(p.action)}")
                        lesson = learning.note_decline(memory, p.action, state)
                        if lesson:
                            say(f"  learned: {lesson}")
                            if "lesson" in lesson:
                                chronicle.add(memory, state, "learned", lesson)
                        journal({"kind": "declined", "fort": key, "date": state["date"], "rule": p.rule,
                                 "reason": p.reason, "action": p.action})
                        continue
                    if answer != "yes":
                        if pid not in memory.declined:
                            pending.append({"id": pid, "text": f"{short(p.action)} ({p.reason})"})
                            say(f"  asking you in the game: {short(p.action)} ({p.reason})")
                        continue
                    say(f"  you approved: {short(p.action)}")
                    if answer == "yes":
                        learning.note_approve(memory, p.action, state)
                if acting and p.action["type"] == "start_project" and settings.get("save_before_projects"):
                    pid = proposal_id(p)
                    if memory.saved_before != pid:
                        # Save first; the new level starts next cycle, after the save.
                        try:
                            write_ledger(bridge, state, memory)    # (0.104.0) the save carries the ledger as of now
                            flush_held(bridge)        # (0.105.40) what's held reaches the game before the save
                            bridge.df.run("quicksave")
                            memory.saved_before = pid
                            say("  saving the game before digging a new level; it starts next cycle")
                        except DFHackError as e:
                            say(f"  could not save the game first ({e}); not starting the new level")
                        continue
                if acting and p.action["type"] in CLEANUP_ACTIONS and not p.action.get("dry_run"):
                    # (0.105.40) a journal line before anything is deleted from the world
                    journal({"kind": "cleanup", "fort": key, "date": state["date"], "rule": p.rule,
                             "reason": p.reason, "action": p.action, "text": cleanup_words(p.action)})
                if acting:
                    try:
                        # was: r = bridge.act(shop_level_action(p.action, state))   (two tests look for that text)
                        # (0.105.54) a workshops level: a standing level first, a new one planned for several
                        # (layout B) every level with its floor hint; p.action itself stays the proposal's
                        r = bridge.act(floor_action(shop_level_action(p.action, state), state, memory))
                    except BridgeError as e:
                        r = {"ok": False, "error": str(e)}
                        r.update(refusal_target(getattr(e, "reply", None)))   # (F2b) its site: the attempt ledger
                    except DFHackError as e:
                        # The command may or may not have happened in the game.
                        r = {"ok": None, "error": f"no reply from the game ({e})"}
                        no_answer = True     # (0.104.138) the next would only queue behind it
                    results.append((p, r))
                    if p.action["type"] == "start_project" and r.get("ok") is True:
                        memory.saved_before = ""
                    outcome_txt = {True: "done", None: f"UNKNOWN: {r.get('error')}"}.get(
                        r.get("ok"), f"refused: {r.get('error')}")
                    if r.get("ok") is True and r.get("clearing"):
                        outcome_txt = (f"started: {r.get('trees')} tree(s) at x{r.get('x')} y{r.get('y')} "
                                       "marked for felling first; placed once they're down")
                    elif r.get("ok") is True and p.action["type"] == "start_project" and r.get("joined") is not None:
                        # (0.105.54) the shops went into a standing workshops level
                        outcome_txt = (f"done: into workshops level #{r.get('joined')} "
                                       + ("(a free room)" if r.get("how") == "free_room" else "(the level extended)"))
                    elif (r.get("ok") is True and p.action["type"] == "start_project"
                          and isinstance(r.get("floor"), dict)):
                        # (layout B) the level went into slots along a floor's main hall
                        outcome_txt = floor_outcome(r) or outcome_txt
                    elif r.get("ok") is True and p.action["type"] == "open_trade" and r.get("clicking"):
                        outcome_txt = (f"clicked the depot's Trade button at {r.get('at')} (the screen is checked next cycle)"
                                       if r.get("at") else    # (r2 h5) no place known: looked for by its word
                                       "opened the depot's sheet to find its Trade button by its word and click it "
                                       "(the screen is checked next cycle)")
                    elif r.get("ok") is True and p.action["type"] == "send_mission" and r.get("sending"):   # (0.105.24)
                        outcome_txt = ("the World screen driven to send "
                                       + ("the messenger" if p.action.get("goal") in (None, "make_contact")
                                          else "the squads") + f" to {r.get('site') or r.get('site_id')} "
                                       "(each step checked over the next frames; the outcome in the missions report)")
                    elif r.get("ok") is True and p.action["type"] == "call_trader" and not r.get("waiting"):
                        outcome_txt = ("the trader is at the depot" if r.get("at_depot") else
                                       "anyone may trade now (the broker didn't come)" if r.get("anyone") else
                                       "broker asked for" if r.get("requested") else
                                       f"waiting for {r.get('coming') or 'the broker'} ({r.get('waiting_ticks')} ticks)")
                    elif r.get("ok") is True and p.action["type"] == "trade_deal" and not r.get("dry_run") and not r.get("waiting"):
                        outcome_txt = (f"ticked {len(r.get('bought') or [])} of their goods (value {r.get('buy_value')}) "
                                       f"for {r.get('given')} of ours (value {r.get('give_value')})")
                        if r.get("answer"):
                            # (item9) how the deal was seen: their goods gone, changing owner, or the merchants' yes
                            by = {"goods": "the goods left the lists", "owners": "the goods changed owner",
                                  "answer": "the merchants said yes"}.get(
                                str((r.get("press") if isinstance(r.get("press"), dict) else {}).get("traded_by")))
                            outcome_txt += (f"; pressed Trade: {r.get('answer')}, "
                                            + (("traded" + (f" ({by})" if by else "")) if r.get("traded") else "NOT traded"))
                            c = r.get("counter") or {}
                            if c:
                                outcome_txt += (f" (they asked for {c.get('items')} more worth {c.get('value')}: "
                                                + ("given" if c.get("accepted") else "refused") + ")")
                            if r.get("traded") and not r.get("closed"):
                                outcome_txt += "; the trade screen is still open"
                        elif isinstance(r.get("press"), dict) and r["press"].get("error"):
                            # (r2 h5) the press looked for the Trade button by its word: why it didn't press
                            outcome_txt += f"; not pressed: {r['press']['error']}" + ("; the screen closed" if r.get("closed") else "")
                        elif not r.get("calibrated"):
                            # (0.105.35) kept: the AI presses only a button it has been shown
                            outcome_txt += ("; not pressed: the AI hasn't been shown the Trade button (python "
                                            "brain\\probe_trade.py --here), so the goods stay ticked on the screen")
                    elif r.get("ok") is True and p.action["type"] == "explore_dig" and r.get("tiles") == 0:
                        # (r36c) every slot held by a tunnel still being dug
                        outcome_txt = f"waiting: {r.get('waiting') or 'the last tunnels are still being dug'}"
                    elif r.get("waiting"):
                        outcome_txt = f"waiting: {r.get('error')}"
                    if p.action["type"] == "start_project":
                        # (layout B) hallway mode was on and the level went the classic way: why
                        outcome_txt += not_on_floor_words(r)
                    say(f"  {p.rule}: {p.reason} -> {json.dumps(p.action)} [{outcome_txt}]")
                else:
                    would.append(f"would {short(p.action)}: {p.reason}")
                    say(f"  would do ({p.rule}): {p.reason} -> {json.dumps(p.action)}")
                # (r3 g3) the level's line carries the floor hint it was sent with
                journal({"kind": "decision", "fort": key, "date": state["date"], "rule": p.rule,
                         "reason": p.reason, "action": p.action, **floor_journal_hint(p.action),
                         "mode": "autopilot" if acting else "dry-run", "result": r})
        finally:
            if results:
                _ov.LAST_FULL.clear()                 # the fort changed: the next cycle reads the full report
                # (0.105.48, K6) each on its own: record() first (the cooldowns, the
                # alarm's and gate's ownership), then the rest whatever it did
                cycle_step(memory, state, "record", lambda: record(results, state, memory, cfg))
                cycle_step(memory, state, "learning_actions", lambda: learning.note_actions(results, state, memory))
                cycle_step(memory, state, "outcomes_actions", lambda: outcomes.record_actions(results, state, memory))

                def _atlas():
                    for line in atlas.note_actions(results, state, memory):
                        say(f"Atlas: {line}")              # what was built, or what the AI found and chose
                        chronicle.add(memory, state, "gate", line)
                cycle_step(memory, state, "atlas", _atlas)

                def _masterplan():
                    for p, r in results:
                        line = masterplan.note_result(memory, p.action, r, state)
                        if line:
                            say(f"Plan: {line}")
                            chronicle.add(memory, state, "plan", line)
                cycle_step(memory, state, "masterplan", _masterplan)
        memory.notes = notes + [NEEDS_YOU + t for t in todo]
        if acting:
            write_ledger(bridge, state, memory, defer=True)    # (0.105.40) with the cycle's last call
        if autopilot:
            try:
                bad = "; ".join(report.trouble(state, memory))
            except Exception:  # noqa: BLE001  (a report problem never stops the fort)
                bad = memory.trouble_seen
            if bad != memory.trouble_seen:
                say(f"THE FORT IS IN TROUBLE: {bad}" if bad else "The fort is out of trouble.")
                chronicle.add(memory, state, "trouble", bad or "out of trouble")
                memory.trouble_seen = bad
            if controls.get("unattended"):
                # (0.105.100) the keeper's fresh start: is the fort calm now (logs/calm.json)
                try:
                    import fresh_start
                    fresh_start.note_cycle(state, memory, fort=key)
                except Exception:  # noqa: BLE001  (never stops the fort)
                    pass
            line = report.maybe_write(state, memory, key, todo, controls.get("fps"))
            if line:
                say(f"Report: {line}")
                if controls.get("save_seasons") and acting and not line.startswith("couldn't"):
                    # only with --save-seasons: DF's own seasonal autosave does this (Oct 21: it
                    # saved every season by itself, and a second save only made the game stall)
                    try:
                        r = bridge.act({"type": "save_game"})
                        say(f"No extra save for the new season: {r.get('by')}." if r.get("already")
                            else "Asked DFHack to save the game for the new season." if r.get("ok")
                            else f"Couldn't save the game: {r.get('error')}")
                    except (BridgeError, DFHackError) as e:
                        say(f"Couldn't save the game: {e}")
        if state.get("tier") in (None, "daily", "survey"):
            keep_state(state, key)
            probe_gear(bridge, state, key)
            probe_posts(bridge, state, key)
        try:
            # where the save lives, for the keeper's --revive (load-save after a crash)
            import revive
            f0 = _d(state.get("fort"))
            revive.write_last_fort((bridge.version or {}).get("df_path"), f0.get("save_dir"), key,
                                   world=f0.get("world"), run=f0.get("fort_run"))
        except Exception:  # noqa: BLE001
            pass
        if controls.get("unattended") and not controls.get("no_backup"):
            # a long run alone: a copy of the save once a real day (backups/)
            try:
                f = _d(state.get("fort"))
                root = (bridge.version or {}).get("df_path")
                # (0.99.13) the folder the save is really in (DF's user folder, not the game's)
                # only when a copy is due: the lookup can walk both save trees
                from dfhack import save_root
                line = backup.maybe((lambda: save_root(root, f.get("save_dir")) or Path(root) / "save")
                                    if root else None, f.get("save_dir"),
                                    fort=f, date=state.get("date"))   # (0.105.0) the pinned fort, never mid-save
                if line:
                    say(f"Backup: {line}")
            except Exception as e:  # noqa: BLE001  (a failed copy never stops the fort)
                say(f"Backup: couldn't copy the save ({e})")
        acting_text = ("acting" if acting else "dry run (watching only)" if not autopilot
                       else why_not or "not acting")
        recent = [f"{short(a['action'])}: {a.get('reason', '')}".rstrip(": ")
                  for a in memory.recent_actions[-5:]][::-1]
        report_status(bridge, {
            "mode": MODES[mode], "acting": acting_text, "date": date_str(state),
            "last": (recent if acting else would[:5] or recent),
            "notes": notes[:2],
            "todo": list(dict.fromkeys(todo))[:10],   # things only the player can do
            "building": [t for t in project_text(state["projects"]).split("; ") if t][:2],
            "ai": (f"AI strategist: {int(bank.balance):,} tokens saved" if backend else None),
            "tokens": ({"saved": int(bank.balance), "total": int(bank.total_used),
                        "today": int(bank.real_day_used) if bank.real_day == date.today().isoformat() else 0}
                       if backend else None),
            "pending": pending,
            # (0.105.33) the answers read this cycle, and every "no" (kept as
            # declined): a "yes" to a proposal this cycle held or didn't make
            # waits in the panel for the cycle that makes it
            "ack": acknowledged(decisions, looked, memory, now),   # the panel forgets these
            "unattended": _ov.UNATTENDED,             # (0.104.88) the camera director runs only then
            # (0.104.90) what only the brain knows, for the camera's captions
            "camera": camera_feed(memory) if _ov.UNATTENDED else None,
        })
    finally:
        # (0.105.40) held set_learned / set_culture answered before the memory
        # is written (their answers are part of it); the rest go with save_memory
        flush_held(bridge, _ov.HELD_BEFORE_SAVE)
        save(key, memory, bank, bridge if to_save else None, state)
        flush_held(bridge)
