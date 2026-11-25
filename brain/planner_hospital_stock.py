"""planner_hospital_stock (0.105.112): the hospitals' standing thread and cloth.

B (24 Nov): four hospital locations, each wanting DF's 5 thread and 5 cloth
(desired_thread 75000, desired_cloth 50000 in DF's units): 17 of the fort's 19
plant threads lay in their chests, no thread was free outside them, and the
strange moods failed for want of it while the loom wove nothing. item2's
`hospital_release` (planner_moods.mood_hospital_rule) lowered the quotas only
while a mood waited and put the old values back after.

Now a standing cap: the hospitals together keep `hospital_stock_base` whole
thread and cloth, one more (`hospital_stock_per_patient`) for each patient
waiting for sutures or dressings, never more than `hospital_stock_max`. All of
it on the hospital with the most chests (its doctors fetch from any of them;
the rest of the fort's thread stays free), 0 on the others. The bridge
(lua/ai-mood-help.lua act_hospital_cap) sets the quotas (never raising one the
player set below the AI's last cap; while hospital_release holds a quota at 0
it lowers the value kept for the restore instead, and the restore never puts
back more than the cap), and sets the surplus whole items in the hospitals'
chests out beside them, unforbidden, for the haulers. A stock that could not
be set out (used pieces, in a job) is not asked for again until it changes.

(0.105.115 item20) B, 25 Nov (2.5 h): 54 hospital_cap steps, 15 refused "the
quotas are at the cap already, and no whole thread or cloth in their chests
could be set out". The chests' counts move by one or two between cycles (a
piece set out is hauled back, a doctor fetches one), so "the same stock" was
never the same: the 10 cloth that never move (no tile in reach) were asked for
with each thread count. And the cap went 2 -> 3 -> 2 as one patient came and
went every few cycles. Now:
  * a kind is set out only when its count moved by more than SAME_SLACK (a
    fifth, at least 1) since the last try, or HOLD_DAYS / REAL_HOLD_MINUTES
    after it (the longer, at the fort's fps);
  * a quota is raised at once (patients wait) but lowered back only
    LOWER_DAYS / REAL_LOWER_MINUTES after the AI last changed it.
So the rule proposes nothing when the quotas are at the cap and nothing can
move: no refusal to back off.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import COOLDOWN_KEYS, LIMIT_EXEMPT, LOCATION_UNITS, TICKS_PER_DAY, Proposal, abs_tick
from planner_backoff import real_ticks

__all__ = ["hospital_targets", "hospital_stock_rule"]

LIMIT_EXEMPT.add("hospital_stock")        # one cheap step; the moods wait on it
QUOTAS = ("thread", "cloth")
SET_OUT_MAX = 10                          # whole items a call (the bridge's RELEASE_MAX)
# (item20) a kind's count within this of the last try's is the same stock (a fifth, at least 1)
SAME_SLACK = 0.2
HOLD_DAYS, REAL_HOLD_MINUTES = 7, 30      # then the same stock is tried again
LOWER_DAYS, REAL_LOWER_MINUTES = 3, 5     # a quota lowered back no sooner after the AI's last change


def _wait_ticks(s: dict, days: float, minutes: float) -> int:
    return max(int(days * TICKS_PER_DAY), real_ticks(s, minutes))


def same_stock(have: int, tried) -> bool:
    """(item20) The count is the last try's, give or take a piece or two."""
    t = _num(tried)
    return t is not None and abs(have - t) <= max(1, int(t * SAME_SLACK))


# kept local: an int (not a bool) or the default
def _int(v, default: int = 0) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else default


# kept local: a whole number or None (other modules' _num give a default or a float)
def _num(v) -> int | None:
    """A whole number from the bridge (JSON may carry 75000.0), else None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v)


def _stitch_waiting(s: dict) -> int:
    """Patients waiting for sutures or dressings (planner_moods.stitch_waiting)."""
    from planner_moods import stitch_waiting
    return stitch_waiting(s)


def _hospitals(s: dict) -> list:
    """The hospital locations of the bridge's `locations.list`, the one with
    the most chests first (then the lowest id)."""
    rows = [e for e in _l(_d(s.get("locations")).get("list"))
            if isinstance(e, dict) and e.get("type") == "HOSPITAL" and isinstance(e.get("id"), int)]
    return sorted(rows, key=lambda e: (-_int(e.get("chests")), e["id"]))


def hospital_targets(s: dict, cfg: dict) -> tuple[list, int, int]:
    """([{id, thread, cloth}] in whole items, total thread, total cloth)."""
    base = max(0, _int(cfg.get("hospital_stock_base"), 2))
    per = max(0, _int(cfg.get("hospital_stock_per_patient"), 1))
    top = max(0, _int(cfg.get("hospital_stock_max"), 5))
    n = min(top, base + per * _stitch_waiting(s))
    caps = []
    for i, e in enumerate(_hospitals(s)):
        caps.append({"id": e["id"], "thread": n if i == 0 else 0, "cloth": n if i == 0 else 0})
    return caps, (n if caps else 0), (n if caps else 0)


def _by_id(rows) -> dict:
    return {e["id"]: e for e in _l(rows) if isinstance(e, dict) and isinstance(e.get("id"), int)}


def hospital_stock_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """The hospitals' thread and cloth quotas set to what their patients
    need; the surplus in their chests set out for the fort."""
    caps, thread_n, cloth_n = hospital_targets(s, cfg)
    if not caps:
        return
    mh = _d(s.get("mood_help"))
    held = _by_id(_d(mh.get("hospital_hold")).get("list"))
    rec = _d(mh.get("hospital_cap"))
    last = _by_id(rec.get("list"))
    locs = {e["id"]: e for e in _hospitals(s)}
    try:
        now = abs_tick(s)
    except Exception:  # noqa: BLE001
        now = None
    lower_wait = _wait_ticks(s, LOWER_DAYS, REAL_LOWER_MINUTES)
    changes = []
    for c in caps:
        loc = locs[c["id"]]
        for k in QUOTAS:
            units = c[k] * LOCATION_UNITS[k]
            kept = _num(held.get(c["id"], {}).get(k))
            if kept is not None:
                if kept > units:                 # held at 0 for a mood: the value to restore lowered
                    changes.append(f"hospital {c['id']}'s {k} {kept // LOCATION_UNITS[k]} -> {c[k]} (after the mood)")
                continue
            want = _num(_d(loc.get("want")).get(k))
            if want is None:
                continue
            prev = _num(last.get(c["id"], {}).get(k))
            if (want > units and prev is not None and want == prev and isinstance(now, int)
                    and isinstance(_num(rec.get("at")), int) and 0 <= now - _num(rec.get("at")) < lower_wait):
                continue    # (item20) the AI's own cap, raised lately for a patient: lowered back later
            if want > units or (want < units and prev is not None and want == prev):
                changes.append(f"hospital {c['id']}'s {k} {want // LOCATION_UNITS[k]} -> {c[k]}")
    hosp = _d(_d(s.get("supplies")).get("hospital"))
    have = {k: _int(hosp.get(k)) for k in QUOTAS}
    surplus = {"thread": max(0, have["thread"] - thread_n), "cloth": max(0, have["cloth"] - cloth_n)}
    tried = _d(rec.get("tried"))
    # (item20) each kind on its own, the same stock give or take a piece, tried again after a while
    t_at = _num(tried.get("at"))
    fresh = not (isinstance(now, int) and isinstance(t_at, int)
                 and 0 <= now - t_at < _wait_ticks(s, HOLD_DAYS, REAL_HOLD_MINUTES))
    set_out = {k: min(SET_OUT_MAX, v) for k, v in surplus.items()
               if v > 0 and (fresh or not same_stock(have[k], tried.get(k)))}
    if not changes and not set_out:
        return
    a = {"type": "hospital_cap", "caps": caps}
    if set_out:
        a["set_out"] = set_out
        a["seen"] = dict(have)
    stitch = _stitch_waiting(s)
    why = (f"the hospitals keep {thread_n} thread and {cloth_n} cloth "
           + (f"({stitch} patient(s) wait for sutures or dressings)" if stitch else "(no patient waits for sutures)")
           + ", so the fort's other thread and cloth stay free for the loom and the strange moods")
    parts = []
    if changes:
        parts.append("quotas " + ", ".join(changes[:6]))
    if set_out:
        parts.append("the surplus set out beside the hospital ("
                     + ", ".join(f"{v} {k}" for k, v in set_out.items()) + f" of {have['thread']} thread and "
                     + f"{have['cloth']} cloth in its chests)")
    proposals.append(Proposal("hospital_stock", a, f"{why}: " + "; ".join(parts), 2))


COOLDOWN_KEYS.setdefault("hospital_stock", "hospital_stock_cooldown_ticks")
