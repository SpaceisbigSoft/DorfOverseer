"""The overseer's main loop (_run: main() in overseer.py parses the command
line and takes the lock). Split from overseer.py (r7 d1); overseer
re-exports it. What it uses from overseer is looked up there at call time
(_ov, _late), so the tests' patches of overseer.Bridge, .one_cycle, .say,
... hold.
"""

from __future__ import annotations

import os
import time
import traceback
from datetime import datetime
from bridge import BridgeError
from dfhack import DFHackError, GameNotRunning
from planner import TICKS_PER_YEAR
from planner_meetings import meeting_open_due, meeting_open_said, meeting_reopen_wait
import fallen
import memstore
from digest import _d
from review import SHADOW_WORDS, shadow_on

__all__ = ["POLL_SECONDS", "UNPAUSE_AFTER_S", "FPS_WINDOW_S", "TRADE_CYCLES_MAX", "TRADE_CYCLE_S", "TRADE_STUCK_S",
           "TRADE_FORCE_S", "ERRORS_MAX_BYTES", "SOAK_EVERY_S", "MEETING_CLOSE_S", "MEETING_ANSWER_S",
           "MEETING_GIVEUP_S", "STALL_AFTER_S", "PLAN_EVERY_TICKS", "EVENT_CYCLE_MIN_TICKS"]

_ov = None     # the overseer module: set by overseer.py as it imports this part (its own
               # module object, also when it runs as the main script)


def _late(name: str):
    """A call-time forwarder to overseer.<name> (the one there now: a test's patch, too)."""
    def call(*a, **kw):
        return getattr(_ov, name)(*a, **kw)
    call.__name__ = call.__qualname__ = name
    return call


Bridge = _late("Bridge")
check_pin = _late("check_pin")
fallen_probe = _late("fallen_probe")
fps_state = _late("fps_state")
heartbeat = _late("heartbeat")
journal = _late("journal")
journal_meeting = _late("journal_meeting")
_leave_open = _late("_leave_open")
make_backend = _late("make_backend")
meeting_leave_after = _late("meeting_leave_after")
meeting_unattended = _late("meeting_unattended")
note_failed_cycles = _late("note_failed_cycles")
one_cycle = _late("one_cycle")
pin_hold = _late("pin_hold")
say = _late("say")
slow_factor = _late("slow_factor")
world_leave_due = _late("world_leave_due")
write_soak = _late("write_soak")


POLL_SECONDS = 2.0
UNPAUSE_AFTER_S = 30.0           # (unattended) the game paused itself this long ago: unpause it
FPS_WINDOW_S = 600               # (unattended) the game's speed over the last 10 minutes


TRADE_CYCLES_MAX = 4             # cycles while DF's trade screen is open (time stands still there)...
TRADE_CYCLE_S = 5.0              # ...this many seconds apart
TRADE_STUCK_S = 180.0            # (0.100.1, unattended) still open after its cycles: the AI's own screen closed
TRADE_FORCE_S = 900.0            # ...and any screen, after this long (nobody is at the game)


ERRORS_MAX_BYTES = 2_000_000


SOAK_EVERY_S = 600


MEETING_CLOSE_S = 600.0          # (0.104.0, unattended) a meeting screen holding the game this long is left
MEETING_ANSWER_S = 20.0          # (0.105.0) a meeting screen holding the game this long is answered (every 30 s)
MEETING_GIVEUP_S = 120.0         # (0.105.24) left this soon when the AI knows it can't answer it (no button shown
                                 # yet, or a press changed nothing): nobody else will, so no 10-minute stall


STALL_AFTER_S = 60.0             # (unattended) running, but the date hasn't moved this long: a popup


PLAN_EVERY_TICKS = 1200          # one in-game day


EVENT_CYCLE_MIN_TICKS = 100      # after an event, plan again this soon at the earliest


def _run(args) -> int:
    """The main loop (main() above parses the command line and takes the lock)."""
    mode = "AUTOPILOT" if args.autopilot else "DRY RUN (nothing will be changed)"
    say(f"Overseer starting in {mode}. Ctrl-C to quit; create a file named STOP to halt actions.")
    backend = make_backend() if args.ai else None
    try:      # (D0) the design language's AI turn needs --ai (and config design_ai)
        import planner_design
        planner_design.set_ai(backend is not None)
    except Exception:  # noqa: BLE001
        pass
    if backend and not args.autopilot:
        say("Note: in a dry run the AI still reviews (and uses tokens); its actions are only shown.")
    if backend and shadow_on():
        say(SHADOW_WORDS)          # (r4 k5) advice only until the player switches it off

    bridge = None
    last_plan_tick = None
    trade_cycles, trade_cycle_at = 0, float("-inf")   # cycles run while the trade screen is open
    trade_open_since, trade_close_tried = None, float("-inf")   # (0.100.1) a screen left open
    last_full_tick = 0
    waiting_msg = None
    was_halted = False
    seen_decisions: dict = {}
    problems_in_a_row = 0
    failed_cycles = 0            # (0.105.48, K6) cycles in a row that raised: reset only by a good cycle
    in_cycle = False
    paused_since = None          # (unattended) when the game was first seen paused
    unpauses = 0
    fps_samples: list = []       # (time, fps) while the game runs, the last 10 minutes
    fps_low = None
    last_date = None             # (unattended) the game's date, and since when it hasn't moved
    date_since = 0.0
    held_date, held_since, meeting_tried = None, 0.0, float("-inf")   # (0.104.0) paused or not: for meetings
    answer_tried = float("-inf")  # (0.105.0) the last try at answering the meeting screen
    answer_dead = None           # (0.105.0 review) held_since of a meeting where a press changed nothing: no more presses
    answer_cant = None           # (0.105.24) held_since of a meeting the AI can't answer (no button, a dead press)
    open_meeting_tried = float("-inf")   # (0.105.47) the last click on DF's diplomacy light
    open_meeting_said = None     # (0.105.47) the last line said about it (not said again)
    world_since, world_tried = None, float("-inf")   # (0.105.48, K9) the World screen open since, last left
    stall_said = float("-inf")
    stall_wait = STALL_AFTER_S   # the wait before the next try at the same stall (doubles, up to 10 min)
    quieted = False              # (unattended) announcements told not to pause or pop up, this fort
    soak_at = float("-inf")      # (unattended) when the last soak row was written
    saving_at = float("-inf")    # (0.104.138) when the game last said it was saving
    season_end = False           # (0.104.138) the last date seen was a season's last days (DF autosaves then)
    save_said = False            # (0.104.138) "DF is saving" said for this silence
    quiet_wait = 10              # (0.104.138) the wait after an unanswered call while DF saves (10 -> 60 s)
    stop_left = False            # (0.105.47, J16) the fort left open for this STOP file
    leave_ok = False             # (0.105.47, J16) the last poll's fort may be left open as the AI stops
    while True:
        heartbeat()
        try:
            if bridge is None:
                bridge = Bridge()
                info = bridge.handshake()
                say(f"Connected: bridge {info['bridge_version']}, DFHack {info['dfhack_version']}")
            if args.once:
                one_cycle(bridge, args.autopilot, backend)
                return 0
            st = bridge.status()
            if st.get("saving"):
                saving_at = time.time()
            _d0 = _d(st.get("date"))
            season_end = isinstance(_d0.get("tick"), int) and (_d0["tick"] // 33600) % 3 == 2 and int(_d0.get("day") or 0) >= 26
            save_said, quiet_wait = False, 10
            controls = {"halted": st.get("halted") is True, "decisions": st.get("decisions") or {}}
            if st.get("in_fort") and controls["halted"] != was_halted:
                say("Halted in the game (Ctrl-Shift-H): watching only, changing nothing."
                    if controls["halted"] else "Resumed in the game.")
                was_halted = controls["halted"]
            # An answer starts a cycle right away, once (the cycle acknowledges it;
            # if that cycle can't, don't spin on the same answers).
            answered = bool(controls["decisions"]) and controls["decisions"] != seen_decisions
            seen_decisions = dict(controls["decisions"])
            # (unattended) the game's speed, measured while it runs
            nowt = time.monotonic()
            date_now = (st.get("date") or {}).get("tick"), (st.get("date") or {}).get("year")
            if date_now != last_date or st.get("paused") or not st.get("in_fort") or st.get("trade_open"):
                last_date, date_since = date_now, nowt
                stall_said, stall_wait = float("-inf"), STALL_AFTER_S     # time moves: a new stall starts afresh
            if not st.get("in_fort"):
                quieted = False
                _ov.PIN_SEEN["checked"], _ov.PIN_SEEN["refused"] = False, None    # (0.105.33) the next fort is checked afresh
                _ov.PIN_SEEN.pop("failed_at", None)
            if st.get("in_fort") and os.environ.get("DFAI_PIN") and not _ov.PIN_SEEN.get("checked"):
                check_pin(bridge)
            held_pin = pin_hold()
            # (r1g9) a fallen fort is left alone: not unpaused, no popups taken off.
            # (x3, V7) only the fort and date the mark names: another fort, an
            # earlier save or citizens back (DF loads every save paused, and no
            # cycle runs while paused) end it here, and the loop runs as usual
            fallen_idle = bool(args.autopilot and fallen.idle(st, fallen_probe(bridge), say, journal))
            # (0.105.47, J16) the fort this overseer may leave open as it stops:
            # its own (the pin), in the fort. (0.105.48, K3) halted too: the
            # leave passes the halt (it only opens, lowers and lets out)
            leave_ok = bool(st.get("in_fort")) and not held_pin
            # the STOP file: the AI stops acting, so the fort is left open (no
            # enemy in reach), once for each STOP file
            if _ov.STOP_FILE.exists():
                if not stop_left and args.autopilot and leave_ok:
                    stop_left = True
                    _leave_open(bridge)
            else:
                stop_left = False
            if (args.unattended and args.autopilot and st.get("in_fort") and not quieted
                    and not controls["halted"] and not held_pin):
                quieted = True
                r = bridge.act({"type": "quiet_announcements"})
                say(f"Unattended: announcements no longer pause the game or open a box ({r.get('pausing', 0)} "
                    f"paused, {r.get('boxes', 0)} opened one; until DF is restarted)." if r.get("ok")
                    else f"Unattended: couldn't quiet the announcements ({r.get('error')}); popups are "
                         "taken off when they stall the game.")
            # (0.104.0) DF's meeting screen holds the game until someone answers
            # (paused or not): unattended, it is left after MEETING_CLOSE_S
            if date_now != held_date or not st.get("in_fort"):
                held_date, held_since = date_now, nowt
            # (0.105.47) a meeting waiting behind DF's diplomacy light is opened
            # (the light clicked) under the same rules as the answers below: it
            # never opened by itself, and the diplomats left unhappy
            if meeting_open_due(st, args.autopilot, meeting_unattended(args), controls["halted"], held_pin,
                                _ov.STOP_FILE.exists(), nowt - open_meeting_tried):
                open_meeting_tried = nowt
                try:
                    r = bridge.act({"type": "open_meeting"})
                    journal_meeting("open_meeting", r)
                    line = meeting_open_said(r)
                    if line and line != open_meeting_said:
                        say(line)
                    open_meeting_said = line
                except (BridgeError, DFHackError):
                    pass
            # (0.105.0, 12b) before that, answered with the AI's defaults (the
            # tribute by the Rules tab), when the AI knows the screen's buttons
            # (0.105.0 review) only when the run is unattended (--unattended, or the
            # keeper's DFAI_PIN): a player at the screen answers it; and after a press
            # that changed nothing, no more presses for that meeting
            if (args.autopilot and meeting_unattended(args) and st.get("in_fort") and st.get("meeting")
                    and not controls["halted"] and not held_pin and answer_dead != held_since
                    and not _ov.STOP_FILE.exists() and MEETING_ANSWER_S <= nowt - held_since < MEETING_CLOSE_S and nowt - answer_tried >= 30):
                answer_tried = nowt
                try:
                    r = bridge.act({"type": "answer_meeting"})
                    journal_meeting("answer_meeting", r, nowt - held_since)
                    if r.get("pressed") and not r.get("ok"):
                        answer_dead = held_since
                    # (0.105.35) or a topic the AI can't answer (a barony's holder): left soon,
                    # nobody being there to answer it
                    if r.get("needs_button") or (r.get("pressed") and not r.get("ok")) or r.get("left_to_player"):
                        answer_cant = held_since
                    if r.get("pressed") or r.get("needs_button") or r.get("left_to_player"):
                        say("DF's meeting screen: " + (f"answered {r.get('answer')} ({r.get('why') or r.get('topic')})"
                                                       if r.get("ok") else str(r.get("error"))))
                except BridgeError as e:
                    # (0.105.49) bridge.act raises on an answer that came back ok false
                    # (a press that changed nothing): no more presses for this meeting,
                    # and it is left after MEETING_GIVEUP_S (R3, 14 Nov: a dead key
                    # was pressed every 30 s for 5 minutes in all six games)
                    answer_dead = answer_cant = held_since
                    journal_meeting("answer_meeting", {"ok": False, "pressed": True, "error": str(e)[:200]},
                                    nowt - held_since)
                    say(f"DF's meeting screen: {str(e)[:160]}; left in about {int(MEETING_GIVEUP_S)} s "
                        "if nobody answers it")
                except DFHackError:
                    pass
            if (args.unattended and args.autopilot and st.get("in_fort") and not controls["halted"] and not held_pin
                    and not _ov.STOP_FILE.exists() and nowt - held_since >= meeting_leave_after(answer_cant == held_since)
                    and nowt - meeting_tried >= MEETING_CLOSE_S):
                meeting_tried = nowt
                try:
                    r = bridge.act({"type": "close_meeting"})
                    journal_meeting("close_meeting", r, nowt - held_since)
                    # (0.105.47) a meeting it couldn't answer: the light not clicked again for a while
                    # (each opening holds the game until the leave)
                    if r.get("screen") and answer_cant == held_since:
                        open_meeting_tried = nowt + meeting_reopen_wait()
                    if r.get("screen"):
                        say(f"Unattended: DF's meeting screen held the game for {int(nowt - held_since)} s with "
                            "nobody to answer: " + ("left it (the meeting ends without an agreement)."
                                                    if r.get("ok") else f"couldn't leave it ({r.get('error')})."))
                except (BridgeError, DFHackError):
                    pass
            # (0.105.48, K9) DF's World screen holds the game too: unattended, left
            # after WORLD_CLOSE_S (lua/ai-mission-send.lua leave_world)
            if st.get("in_fort") and st.get("world_open"):
                world_since = nowt if world_since is None else world_since
            else:
                world_since, world_tried = None, float("-inf")
            if world_leave_due(st, world_since, world_tried, nowt, args.unattended, args.autopilot,
                               controls["halted"], held_pin, _ov.STOP_FILE.exists()):
                world_tried = nowt
                try:
                    r = bridge.act({"type": "close_world"})
                    say(f"Unattended: DF's World screen held the game for {int(nowt - world_since)} s with nobody "
                        "to close it: " + ("leaving it." if r.get("ok") else f"not left ({r.get('error')})."))
                except (BridgeError, DFHackError):
                    pass
            stalled = nowt - date_since >= STALL_AFTER_S
            if st.get("in_fort") and not st.get("paused") and not stalled and isinstance(st.get("fps"), (int, float)):
                fps_samples.append((nowt, st["fps"]))
            if stalled and st.get("saving"):
                # (0.104.138) DF is saving itself: time stands still for minutes
                # (2-10 on Teacheroar), nothing to take off or say
                pass
            elif stalled and fallen_idle:
                pass          # (r1g9) F: "time stood still" 65 times over 9 hours on a dead fort
            elif (stalled and args.unattended and args.autopilot and not controls["halted"] and not held_pin
                    and not _ov.STOP_FILE.exists() and nowt - stall_said >= stall_wait):
                # running, but time stands still: DF waits on a popup. Take it off
                # (again a minute later if that didn't help, then 2, 4, 8, 10 minutes)
                if stall_said != float("-inf"):
                    stall_wait = min(600.0, stall_wait * 2)
                stall_said = nowt
                r = bridge.act({"type": "unpause", "unstick": True})
                n = r.get("popups_cleared", 0)
                if n:
                    say(f"Unattended: time stood still for {int(nowt - date_since)} s with the game running: "
                        f"{n} popup(s) waiting for a click taken off.")
                else:
                    say(f"Unattended: time stood still for {int(nowt - date_since)} s with the game running and no "
                        "popup to take off (a save, or a window only a click closes); if this repeats every "
                        "10 minutes, the game needs a click from you."
                        + ("" if r.get("ok") else f" ({r.get('error')})"))
            fps_samples = [x for x in fps_samples if nowt - x[0] <= FPS_WINDOW_S]
            fps_low = fps_state(fps_samples, fps_low)
            if args.unattended and nowt - soak_at >= SOAK_EVERY_S:
                soak_at = nowt
                write_soak(st, fps_samples, fps_low, unpauses, int(nowt - date_since), controls["halted"])
            controls["fps"] = fps_samples[-1][1] if fps_samples else None
            controls["fps_low"] = fps_low if args.unattended else None
            # (r9, B8) what the back-off judged by, for the saved state: the
            # median over the window (fps_state's measure), the samples in it
            # and fps_low. The saved states read fps_low None while their
            # perf.fps said 4-24: perf.fps is read while the report itself
            # holds the game; this is the loop's own 10 minutes
            vals = sorted(v for _, v in fps_samples)
            controls["fps_seen"] = ({"median": int(vals[len(vals) // 2]), "samples": len(vals), "low": fps_low}
                                    if vals else None)
            controls["unattended"] = args.unattended
            controls["save_seasons"] = args.save_seasons
            if (args.unattended and args.autopilot and st.get("in_fort") and st.get("paused")
                    and not controls["halted"] and not held_pin and not _ov.STOP_FILE.exists() and not fallen_idle):
                paused_since = paused_since or nowt
                if nowt - paused_since >= UNPAUSE_AFTER_S:
                    r = bridge.act({"type": "unpause"})
                    paused_since = None
                    if r.get("ok"):
                        unpauses += 1
                        say(f"Unattended: the game had paused itself; unpaused it ({unpauses} so far).")
                    else:
                        say(f"Unattended: couldn't unpause: {r.get('error')}")
            else:
                paused_since = None
            if not st.get("in_fort"):
                msg = "Waiting for a fortress to be loaded..."
            elif st.get("paused") and not answered:
                msg = ("The fort has fallen: the game is left paused until you act." if fallen_idle else
                       "Game is paused; unpausing it in 30 s (unattended)." if args.unattended and args.autopilot
                       and not controls["halted"] and not held_pin else "Game is paused; planning resumes when it runs.")
            else:
                msg = None
                now = st["date"]["year"] * TICKS_PER_YEAR + st["date"]["tick"]
                # (0.104.0) while the game runs slowly the full report (the bridge's
                # heaviest work, the game paused while it's built) comes every 2 days
                # (0.105.40) perf_slow_cycle_factor; never stretched while a threat is on
                every = PLAN_EVERY_TICKS * slow_factor(fps_low, args.unattended)
                daily = (last_plan_tick is None or now < last_plan_tick
                         or now - last_full_tick >= every)
                # DF's trade screen holds time still: a few cycles while it's open
                # (the deal, the press), each a few seconds apart; none once it shuts
                trade_now = False
                if st.get("trade_open") and args.autopilot:
                    if trade_open_since is None:
                        trade_open_since = nowt
                    if trade_cycles < TRADE_CYCLES_MAX and nowt - trade_cycle_at >= TRADE_CYCLE_S:
                        trade_now, trade_cycles, trade_cycle_at = True, trade_cycles + 1, nowt
                    elif (args.unattended and trade_cycles >= TRADE_CYCLES_MAX and not controls["halted"] and not held_pin
                          and nowt - trade_open_since >= TRADE_STUCK_S and nowt - trade_close_tried >= TRADE_STUCK_S):
                        # (0.100.1) time stands still while the screen is open, so it
                        # can't change by itself: the AI's own screen is closed after
                        # 3 minutes; any screen after 15 (nobody is at the game)
                        trade_close_tried = nowt
                        force = nowt - trade_open_since >= TRADE_FORCE_S
                        try:
                            r = bridge.act({"type": "close_trade", "force": force})
                            say("Unattended: the trade screen stood open for "
                                f"{int(nowt - trade_open_since)} s with nothing left to do: "
                                + ("closed it." if r.get("ok") else f"couldn't close it ({r.get('error')})."))
                        except (BridgeError, DFHackError) as e:
                            say(f"Unattended: the trade screen stood open and couldn't be closed: {e}")
                else:
                    trade_cycles, trade_open_since, trade_close_tried = 0, None, float("-inf")
                due = (daily or trade_now
                       or answered     # you answered a question in the game: act on it now
                       or (st.get("events_waiting", 0) > 0 and now - last_plan_tick >= EVENT_CYCLE_MIN_TICKS))
                if due:
                    last_plan_tick = now      # set first: a failed cycle isn't retried at once
                    if daily:
                        last_full_tick = now
                    # between days, the small pulse report (the rest from today's full one)
                    in_cycle = True
                    one_cycle(bridge, args.autopilot, backend, controls,
                              tier="daily" if daily or trade_now else "pulse")
                    in_cycle = False
                    if failed_cycles:
                        say(f"The cycle runs again after {failed_cycles} failed cycle(s) in a row.")
                        failed_cycles = 0
                        note_failed_cycles(0, None)
            if msg and msg != waiting_msg:
                say(msg)
            waiting_msg = msg
            problems_in_a_row = 0
        except GameNotRunning:
            if args.once:
                say("Dwarf Fortress isn't running (or DFHack isn't loaded).")
                return 1
            if waiting_msg != "not running":
                say("Dwarf Fortress isn't running. Waiting for it...")
            waiting_msg = "not running"
            bridge = None
            time.sleep(10)
            continue
        except (DFHackError, BridgeError) as e:
            if args.once:
                say(f"Problem talking to the game: {e}. Retrying in 10 s.")
                return 1
            # (0.104.138) an unanswered call while DF autosaves (it said it was
            # saving lately, or the season is ending) is the save, not a fault:
            # said once, and asked again less often (10 -> 20 -> 40 -> 60 s)
            if "did not answer" in str(e) and (time.time() - saving_at < 900 or season_end):
                if not save_said:
                    say("DF is saving itself (the season's autosave): the game doesn't answer until it's done.")
                    save_said = True
                bridge = None
                time.sleep(quiet_wait)
                quiet_wait = min(60, quiet_wait * 2)
                continue
            say(f"Problem talking to the game: {e}. Retrying in 10 s.")
            bridge = None
            time.sleep(10)
            continue
        except KeyboardInterrupt:
            if args.autopilot and leave_ok:
                _leave_open(bridge)      # (0.105.47, J16) a fort left alone is never sealed
            say("Overseer stopped.")
            return 0
        except Exception as e:  # noqa: BLE001 - a bug or odd report: log it, keep the overseer alive
            problems_in_a_row += 1
            if in_cycle:
                # (0.105.48, K6) counted apart (an idle poll doesn't reset it) and
                # shown to the health check as a standing "rule cycle failed" line
                in_cycle = False
                failed_cycles += 1
                note_failed_cycles(failed_cycles, e)
                say(f"The cycle failed {failed_cycles} time(s) in a row: nothing was planned.")
            say(f"Unexpected problem: {type(e).__name__}: {e} (details in logs/overseer-errors.log)")
            _ov.LOG_DIR.mkdir(exist_ok=True)
            memstore.cap_file(_ov.LOG_DIR / "overseer-errors.log", ERRORS_MAX_BYTES)
            with (_ov.LOG_DIR / "overseer-errors.log").open("a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{traceback.format_exc()}\n")
            if args.once or problems_in_a_row >= 5:
                say("Stopping after repeated problems." if not args.once else "Stopping.")
                if args.autopilot and not args.once and leave_ok:
                    _leave_open(bridge)      # (0.105.47, J16) the run ends: the fort left open
                return 1
            time.sleep(10)
            continue
        try:
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            if args.autopilot and leave_ok:
                _leave_open(bridge)      # (0.105.47, J16) a fort left alone is never sealed
            say("Overseer stopped.")
            return 0
