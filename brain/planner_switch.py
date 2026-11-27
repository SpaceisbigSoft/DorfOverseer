"""(F2a) One Switch for every on/off decision in the planner.

The chattering's root cause: holds counted in game ticks, while a game day
now passes in about one planner cycle (planner_cistern_pull's note), so a
"half a day" hold held for nothing; and rules that toggle (pull a lever) on
a condition with no dwell flipped every cycle near their edge.

A Switch is an on/off decision keyed by a name (and an object id):

  * two thresholds (hysteresis): on at `on_at`, off at `off_at`; between
    them it stays as the game shows it. A bool input (or None: no opinion
    this cycle) passes through, for a rule whose own conditions make the band;
  * set-state, not toggle: decide() returns the state wanted, and the rule
    acts only when the game (observed) differs from it (act());
  * a minimum hold between two of the AI's own flips the other way, in REAL
    seconds (the cycle's wall clock: the state's "wall_time" when given, else
    time.time()) AND in planner cycles (note_switches: one a note_cycle):
    both must pass. Asking again for the state last asked (a pull still on
    its way) is no flip and is never held;
  * an emergency (an enemy within switch_emergency_tiles...) flips at once.

plan() never changes memory: decide() only reads Memory.switches. A rule
names the proposal that carries a flip (expect()); record() commits the flip
for a proposal that went (note_switch, ok not False): {on, at, c, by}.
note_cycle counts the cycles (note_switches). Without memory, or before the
first flip on record, nothing is held: the clear cases act as before; only
a flip back inside the hold waits.
"""

from __future__ import annotations

import time
import weakref

from planner_core import PLANNER_CONFIG

__all__ = ["SWITCH_CONFIG", "Switch", "wall_now", "SWITCH_KEEP", "enemy_within", "note_switches", "note_switch",
           "cycle_count", "CYCLE_KEY"]

SWITCH_CONFIG = {
    "switch_hold_seconds": 120,      # real seconds between two flips of one switch (at least)
    "switch_hold_cycles": 2,         # ...and planner cycles (both must pass; the seconds carry the weight)
    "switch_emergency_tiles": 12,    # an enemy that can reach the dwarves this close: a safety switch flips at once
}
PLANNER_CONFIG.update({k: v for k, v in SWITCH_CONFIG.items() if k not in PLANNER_CONFIG})

SWITCH_KEEP = 64                     # switches kept in memory (the oldest forgotten)
CYCLE_KEY = "_cycle"                 # Memory.switches[CYCLE_KEY]: {n}: the planner cycles counted (note_switches)

# flips wanted this cycle, by id(memory): (weakref to the memory, [(key, state, rule,
# match, by)]), committed by record() (note_switch) for a proposal that went; dropped
# at the next note_cycle (the weakref: an id reused by a new memory finds nothing)
_PENDING: dict[int, tuple] = {}


def _pending(memory) -> list:
    e = _PENDING.get(id(memory))
    if not e or e[0]() is not memory:
        return []
    return e[1]


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def wall_now(s=None) -> float:
    """The cycle's wall clock: the state's "wall_time" (tests, replays), else now."""
    v = s.get("wall_time") if isinstance(s, dict) else None
    return float(v) if _num(v) else time.time()


def _cfg(cfg, k):
    v = cfg.get(k) if isinstance(cfg, dict) else None
    return v if _num(v) else SWITCH_CONFIG[k]


def _book(memory, create: bool = False) -> dict | None:
    b = getattr(memory, "switches", None) if memory is not None else None
    if isinstance(b, dict):
        return b
    if not create or memory is None:
        return None
    try:
        memory.switches = {}
    except AttributeError:
        return None
    return memory.switches


def cycle_count(memory) -> int:
    """The planner cycles counted so far (note_switches), 0 without memory."""
    b = _book(memory)
    c = b.get(CYCLE_KEY) if b else None
    return int(c.get("n") or 0) if isinstance(c, dict) and _num(c.get("n")) else 0


def note_switches(state, memory) -> None:
    """note_cycle (before planning): one cycle more; last cycle's unsent flips dropped."""
    _PENDING.pop(id(memory), None)
    b = _book(memory, create=True)
    if b is None:
        return
    b[CYCLE_KEY] = {"n": cycle_count(memory) + 1}


def note_switch(p, r, state, memory) -> None:
    """record(): the flip a proposal carried, committed when it went (ok not False)."""
    if memory is None or not isinstance(r, dict) or r.get("ok") is False:
        return
    a = getattr(p, "action", None)
    if not isinstance(a, dict):
        return
    for key, on, rule, match, by in reversed(_pending(memory)):     # the latest first
        if (rule is None or rule == getattr(p, "rule", None)) and all(a.get(k) == v for k, v in match.items()):
            b = _book(memory, create=True)
            if b is None:
                return
            b[key] = {"on": on, "at": wall_now(state), "c": cycle_count(memory), "by": by}
            if len(b) > SWITCH_KEEP + 1:
                old = sorted((k for k in b if k not in (key, CYCLE_KEY)),
                             key=lambda k: b[k].get("at") if isinstance(b[k], dict) and _num(b[k].get("at")) else 0)
                for k in old[:len(b) - SWITCH_KEEP - 1]:
                    b.pop(k, None)
            return


class Switch:
    """sw = Switch(memory, "gate_lever", lever_id, cfg=cfg)
    sw.decide(signal, s, observed=closed, emergency=near)
    if sw.act(closed):
        proposals.append(...); sw.expect("gate", {"type": "pull_gate", "lever_id": lever_id})"""

    def __init__(self, memory, name: str, oid=None, *, on_at=None, off_at=None, hold_s=None, hold_cycles=None,
                 cfg=None):
        self.memory, self.name, self.oid = memory, name, oid
        self.key = name if oid is None else f"{name}:{oid}"
        self.on_at, self.off_at = on_at, off_at
        self.hold_s = float(hold_s if _num(hold_s) else _cfg(cfg, "switch_hold_seconds"))
        self.hold_cycles = int(hold_cycles if _num(hold_cycles) else _cfg(cfg, "switch_hold_cycles"))
        self.state = None        # the state wanted (after decide)
        self.emergency = False   # the emergency decided it
        self.held = False        # a flip was wanted and the hold kept it
        self.wait_s = 0.0        # real seconds left of the hold (when held)
        self.wait_cycles = 0     # cycles left of the hold (when held)

    def record(self) -> dict:
        """The last flip on record ({on, at, c, by}; {} if none): read only."""
        b = _book(self.memory)
        rec = b.get(self.key) if b else None
        return rec if isinstance(rec, dict) else {}

    def level(self, value):
        """The input against the thresholds: True (on), False (off) or None (in the band: as it is)."""
        if value is None or isinstance(value, bool):
            return value
        if not _num(value) or not _num(self.on_at) or not _num(self.off_at):
            return bool(value)
        if self.on_at >= self.off_at:            # on when high (the usual)
            return True if value >= self.on_at else False if value <= self.off_at else None
        return True if value <= self.on_at else False if value >= self.off_at else None

    def decide(self, value=None, s=None, *, observed=None, emergency=None, now=None) -> bool | None:
        """The state wanted this cycle (memory only read). value: a number
        (against on_at/off_at), a bool, or None (no opinion: as the game
        shows). observed: the state in the game (None: not known).
        emergency: True/False forces that state at once, past any hold."""
        self.held = self.emergency = False
        self.wait_s, self.wait_cycles = 0.0, 0
        sig = self.level(value)
        if isinstance(emergency, bool):
            sig = emergency
        rec = self.record()
        last = rec.get("on") if isinstance(rec.get("on"), bool) else None
        seen = observed if isinstance(observed, bool) else last
        if sig is None or seen is None or sig == seen:
            self.state = sig if sig is not None else seen
            return self.state
        # a change of the game wanted: held only when it undoes the AI's last flip
        if isinstance(emergency, bool):
            self.emergency = True
            self.state = sig
            return sig
        if last is None or sig == last:
            self.state = sig
            return sig
        now = wall_now(s) if now is None else float(now)
        age = now - rec["at"] if _num(rec.get("at")) else None
        n = cycle_count(self.memory) - int(rec["c"]) if _num(rec.get("c")) else self.hold_cycles
        if age is None or age < 0 or (age >= self.hold_s and n >= self.hold_cycles):
            self.state = sig
            return sig
        self.held = True
        self.wait_s = max(0.0, self.hold_s - age)
        self.wait_cycles = max(0, self.hold_cycles - n)
        self.state = seen
        return seen

    def act(self, observed) -> bool:
        """Set-state: the rule acts only when the game differs from the state wanted."""
        return isinstance(self.state, bool) and isinstance(observed, bool) and observed != self.state

    def expect(self, rule, match: dict) -> None:
        """The proposal (rule None: any rule; its action holding `match`) that
        carries this cycle's state: record() books the flip if it goes."""
        if self.memory is None or not isinstance(self.state, bool):
            return
        e = _PENDING.get(id(self.memory))
        if not e or e[0]() is not self.memory:
            try:
                e = _PENDING[id(self.memory)] = (weakref.ref(self.memory), [])
            except TypeError:                    # a memory that takes no weak reference: not booked
                return
        e[1].append((self.key, self.state, rule, dict(match), "emergency" if self.emergency else "rule"))
        if len(_PENDING) > 64:                   # memories gone (tests): the oldest dropped
            _PENDING.pop(next(iter(_PENDING)))

    def held_words(self) -> str:
        """For a note: how long the hold still keeps it."""
        if not self.held:
            return ""
        return (f"held {int(self.wait_s + 0.999)} s / {self.wait_cycles} cycle(s) more since its last change "
                f"(at least {int(self.hold_s)} s and {self.hold_cycles} cycles between two)")


def enemy_within(s, tiles) -> bool:
    """An enemy that can reach the dwarves within `tiles` of one (the report's
    threats rows): the emergency that flips a safety switch at once."""
    tiles = tiles if _num(tiles) else SWITCH_CONFIG["switch_emergency_tiles"]
    o = s.get("others_on_map") if isinstance(s, dict) and isinstance(s.get("others_on_map"), dict) else {}
    rows = o.get("threats") if isinstance(o.get("threats"), list) else []
    for t in rows:
        if not isinstance(t, dict) or t.get("can_reach_dwarves") is False:
            continue
        d = t.get("distance_to_nearest_dwarf")
        if _num(d) and _num(tiles) and d <= tiles:
            return True
    return False
