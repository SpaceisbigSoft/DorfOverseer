"""(0.105.40, Phase 13e) Fewer dfhack-run calls a cycle: the bridge's `batch`
command (several actions in one call, each run as `act` runs it) and the
brain sending its per-cycle bookkeeping (report_status, ledger_set,
set_learned, set_culture) with the cycle's next call, falling back to one call
each on an older bridge or when the batch fails as a whole. Lua on a stub
DFHack in a real Lua 5.3 engine (pip install lupa); the brain over a fake game.

    python tests/test_r40_batch.py
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from harness import ROOT, finish, make_test

sys.path.insert(0, str(ROOT / "brain"))

import overseer  # noqa: E402
import bridge as bridge_mod  # noqa: E402
from bridge import Bridge, BridgeError  # noqa: E402
from dfhack import DFHackError, NotStarted  # noqa: E402

LUA_DIR = ROOT / "lua"
HUB = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

# --- the brain's fake game ----------------------------------------------------

overseer.THROTTLE_MEMORY_SAVE = False
overseer.leanings.OWN_MAX = 0
overseer.leanings.site_leanings = lambda state: []
import weights  # noqa: E402
weights.data()["settings"]["near"] = 0.0

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
TMP = Path(tempfile.mkdtemp())
overseer.memstore.FORTS_DIR = TMP / "forts"
overseer.memstore.LEGACY_FILE = TMP / "memory.json"
overseer.JOURNAL = TMP / "decisions.jsonl"
overseer.STOP_FILE = TMP / "STOP"
overseer.learning.PLAYER_FILE = TMP / "player-memory.json"
SAID: list[str] = []
overseer.say = lambda msg: SAID.append(msg)


def _before():
    for f in (overseer.memstore.LEGACY_FILE, overseer.JOURNAL, overseer.STOP_FILE, overseer.learning.PLAYER_FILE):
        f.unlink(missing_ok=True)
    shutil.rmtree(overseer.memstore.FORTS_DIR, ignore_errors=True)
    overseer.PRINTED.clear()
    overseer.LAST_FULL.clear()
    overseer.STATUS_SENT.clear()
    overseer.MEMORY_CACHE.clear()
    SAID.clear()


test = make_test(before=_before)


class FakeGame:
    """dfhack-run with ai-bridge behind it: `state`, `events`, `status`,
    `version`, `act` and (when `batch`) `batch`. Every call and every action
    the game ran, in order, is kept."""

    def __init__(self, batch=True, out=None, fail_batch=None, refuse=()):
        self.timeout_s = 10.0
        self.batch = batch
        self.out = Path(out or tempfile.mkdtemp())
        self.calls: list[str] = []
        self.ran: list[dict] = []          # each action the game ran, in order
        self.fail_batch = fail_batch       # None, "error" (ok false), "timeout"
        self.refuse = set(refuse)
        self.state = copy.deepcopy(BASE)
        self.state.setdefault("ledger", {})
        self.timeouts: list = []

    def run_json(self, script, cmd, *rest, timeout=None):
        assert script == "ai-bridge"
        self.calls.append(cmd)
        if cmd == "version":
            v = {"ok": True, "protocol": 1, "bridge_version": "0.105.40",
                 "recipes": ["brew_drink", "stone_blocks", "prepare_fine_meal"],
                 "tools": ["autochop", "seedwatch", "suspendmanager"]}
            v["commands"] = ["act", "events", "state", "status", "version"] + (["batch"] if self.batch else [])
            return v
        if cmd == "status":
            return {"ok": True, "in_fort": True, "halted": False, "decisions": {}}
        if cmd == "state":
            p = self.out / "state.json"
            p.write_text(json.dumps(self.state), encoding="utf-8")
            return {"ok": True, "file": str(p), "build_ms": 1}
        if cmd == "events":
            p = self.out / "events.json"
            p.write_text(json.dumps({"events": []}), encoding="utf-8")
            return {"ok": True, "file": str(p), "count": 0}
        if cmd == "act":
            return self._act(json.loads(rest[0]))
        if cmd == "batch":
            if not self.batch:
                return {"ok": False, "error": "unknown command: batch"}
            self.timeouts.append(timeout)
            if self.fail_batch == "error":
                return {"ok": False, "rejected": True, "error": "batch: too big"}
            acts = json.loads(rest[0])
            if self.fail_batch == "timeout":
                raise DFHackError("DFHack did not answer within 10s")
            if self.fail_batch == "nostart":
                raise NotStarted("couldn't run dfhack-run: [WinError 206] The filename or extension is too long")
            res = [self._act(a) for a in acts]
            return {"ok": True, "results": res, "times": [1] * len(res), "ms": len(res)}
        return {"ok": True}

    def _act(self, a):
        self.ran.append(a)
        t = a.get("type")
        if t in self.refuse:
            return {"ok": False, "rejected": True, "error": f"{t} refused", "action": t}
        if t == "boom":
            return {"ok": False, "error": "it broke", "action": t}
        if t == "save_memory":
            return {"ok": True, "saved": ["working"], "action": t}
        if t == "tool":
            return {"ok": True, "name": a.get("name"), "enabled": True, "action": t}
        return {"ok": True, "order_id": 900 + len(self.ran), "action": t}


def game(**kw):
    g = FakeGame(**kw)
    b = Bridge(g)
    b.handshake()
    g.calls.clear()
    return b, g


def entries(kind=None):
    if not overseer.JOURNAL.exists():
        return []
    rows = [json.loads(x) for x in overseer.JOURNAL.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if kind is None or r.get("kind") == kind]


def cycle_run(batch, days=3, **kw):
    """A few autopilot cycles on the fake game: (calls, actions run, decisions)."""
    _before()
    b, g = game(batch=batch, **kw)
    for _ in range(days):
        overseer.one_cycle(b, autopilot=True)
        g.state["date"]["tick"] += 1200
        overseer.LAST_FULL.clear()
    dec = [(d["rule"], json.dumps(d["action"], sort_keys=True), (d.get("result") or {}).get("ok"))
           for d in entries("decision")]
    return g.calls, g.ran, dec, b


# --- 1. the bridge: `batch` in Lua -------------------------------------------------

if LuaRuntime is not None:
    _hyg = (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8")
    HARNESS = re.search(r'HARNESS = r"""(.*?)"""', _hyg, re.S).group(1)
    HARNESS = HARNESS.replace("return H\n", r"""
dfhack.filesystem.mtime = function() return 1 end
dfhack.findScript = function() return nil end
dfhack.getDFHackVersion = function() return 'x' end
dfhack.getDFVersion = function() return 'y' end
function H.cmd(env, name, decoded)
  H.action = decoded
  env.dfhack_flags = {module = false}
  H.printed = nil
  assert(load(src, '@' .. lua_dir .. '/ai-bridge.lua', 't', env))(name, '{}')
  return H.printed
end
return H
""")
    LUA = LuaRuntime(unpack_returned_tuples=True)
    H = LUA.execute(HARNESS, HUB, str(LUA_DIR))

    def t(d):
        if isinstance(d, dict):
            return LUA.table_from({k: t(v) for k, v in d.items()})
        if isinstance(d, list):
            return LUA.table_from([t(v) for v in d])
        return d

    def lua_list(v) -> list:
        return [] if v is None else [v[i] for i in range(1, len(v) + 1)]

    def module():
        H.scripts = LUA.table()
        H.halted = False
        M = H.module()
        # test actions, beside the real ones (the module stays loaded: cmd_batch reads ACTIONS at the call)
        LUA.execute("""local M = ...
          M.RAN = {}
          M.ACTIONS.t_ok = function(a) table.insert(M.RAN, a.n or 0); return {ok = true, n = a.n, dry = a.dry_run} end
          M.ACTIONS.t_boom = function(a) table.insert(M.RAN, -1); error('kaboom') end
          M.ACTIONS.t_refuse = function(a) table.insert(M.RAN, -2); return M.reject('no thanks') end
          M.ACTIONS.t_change = function(a) table.insert(M.RAN, 99); return {ok = true} end
          M.DRY_OK.t_ok = true
          M.CACHE_INVALIDATES.t_change = {'justice'}
        """, M)
        return M

    def batch(M, actions):
        H.action = t(actions)
        return M.cmd_batch(t(["[...]"]))

    @test("batch: each action runs in order; one result each, as act gives it; times and ms")
    def _():
        M = module()
        r = batch(M, [{"type": "t_ok", "n": 1}, {"type": "t_ok", "n": 2}, {"type": "t_ok", "n": 3}])
        assert r.ok is True and isinstance(r.ms, int), dict(r)
        res = lua_list(r.results)
        assert [x.n for x in res] == [1, 2, 3] and all(x.ok and x.action == "t_ok" for x in res)
        assert lua_list(M.RAN) == [1, 2, 3]
        assert len(lua_list(r.times)) == 3
        # the same action alone by run_action (act's own path) answers the same
        one = M.run_action(t({"type": "t_ok", "n": 7}))
        assert one.ok is True and one.n == 7 and one.action == "t_ok"

    @test("batch: a failing or refused action doesn't stop the rest; unknown types refused like act")
    def _():
        M = module()
        r = batch(M, [{"type": "t_ok", "n": 1}, {"type": "t_boom"}, {"type": "t_refuse"},
                      {"type": "nope"}, {"type": "t_ok", "n": 5}])
        res = lua_list(r.results)
        assert r.ok is True and len(res) == 5
        assert res[0].ok is True and res[4].ok is True and res[4].n == 5
        assert res[1].ok is False and "kaboom" in res[1].error and res[1].action == "t_boom" and not res[1].rejected
        assert res[2].ok is False and res[2].rejected is True and res[2].action == "t_refuse"
        assert res[3].rejected is True and "unknown action type" in res[3].error
        assert lua_list(M.RAN) == [1, -1, -2, 5]

    @test("batch: DRY_OK per action; a dry run of another action refused; the halt as act has it")
    def _():
        M = module()
        r = batch(M, [{"type": "t_ok", "n": 1, "dry_run": True}, {"type": "t_change", "dry_run": True},
                      {"type": "t_ok", "dry_run": "yes"}])
        res = lua_list(r.results)
        assert res[0].ok is True and res[0].dry is True
        assert res[1].rejected and "has no dry run" in res[1].error
        assert res[2].rejected and "true or false" in res[2].error
        H.halted = True
        r = batch(M, [{"type": "t_change"}, {"type": "t_ok", "n": 2, "dry_run": True},
                      {"type": "ledger_set", "values": {}}])
        res = lua_list(r.results)
        assert res[0].halted is True and res[0].ok is False
        assert res[1].ok is True, "a DRY_OK dry run passes the halt"
        assert res[2].ok is True, "the AI's own bookkeeping (DISPLAY_ONLY) passes the halt"
        assert lua_list(M.RAN) == [1, 2]

    @test("batch: CACHE_INVALIDATES per action that succeeded (not for a dry run or a refusal)")
    def _():
        M = module()
        M.SECTION_CACHE.justice = t({"x": 1})
        batch(M, [{"type": "t_ok"}])
        assert M.SECTION_CACHE.justice is not None
        batch(M, [{"type": "t_ok"}, {"type": "t_change"}])
        assert M.SECTION_CACHE.justice is None
        LUA.execute("local M = ... M.ACTIONS.t_stale = function() return {ok = false, rejected = true, stale = {'needs'}} end", M)
        M.SECTION_CACHE.needs = t({"x": 1})
        batch(M, [{"type": "t_stale"}])
        assert M.SECTION_CACHE.needs is None, "a refusal naming stale sections clears them, as in act"

    @test("batch: caps (20 actions, payload size), an empty or non-list body, the never-batched actions")
    def _():
        M = module()
        r = batch(M, [{"type": "t_ok", "n": i} for i in range(21)])
        assert r.ok is False and r.rejected and "at most 20" in r.error and lua_list(M.RAN) == []
        r = batch(M, [{"type": "t_ok", "n": i} for i in range(20)])
        assert r.ok is True and len(lua_list(r.results)) == 20
        H.action = t([{"type": "t_ok"}])
        r = M.cmd_batch(t(["x" * (M.BATCH_MAX_BYTES + 1)]))
        assert r.ok is False and "bytes" in r.error
        assert batch(M, []).ok is False
        assert batch(M, {"type": "t_ok"}).ok is False, "one object is act's, not batch's"
        r = batch(M, [{"type": "send_mission"}, {"type": "t_ok", "n": 3}])
        res = lua_list(r.results)
        assert res[0].rejected and "alone" in res[0].error and res[1].ok
        # the same never-list in the brain and the bridge
        never = set(lua_list(LUA.eval("function(M) local o = {} for k in pairs(M.BATCH_NEVER) do o[#o+1] = k end return o end")(M)))
        assert never == set(bridge_mod.BATCH_NEVER), never ^ set(bridge_mod.BATCH_NEVER)
        assert M.BATCH_MAX_ACTIONS == bridge_mod.BATCH_MAX_ACTIONS
        assert bridge_mod.BATCH_MAX_CHARS < M.BATCH_MAX_BYTES

    @test("batch: through the command line (main), and listed in version's commands; not in a fort refused")
    def _():
        M = module()
        r = H.cmd(M, "batch", t([{"type": "ledger_set", "values": {}}, {"type": "ledger_set", "values": 5}]))
        res = lua_list(r.results)
        assert r.ok is True and res[0].ok is True and res[1].rejected, [dict(x) for x in res]
        H.scripts["ai-layouts"] = t({"KINDS": [], "STOCKPILES": {}, "WORKSHOPS": {}})
        v = H.cmd(M, "version", None)
        assert v.ok, dict(v)
        cmds = lua_list(v.commands)
        assert "batch" in cmds and "act" in cmds and "events" in cmds, cmds
        LUA.execute("local H = ... H.dfhack.world.isFortressMode = function() return false end", H)
        try:
            r = H.cmd(M, "batch", t([{"type": "ledger_set", "values": {}}]))
            assert r.ok is False and "no fortress" in r.error
        finally:
            LUA.execute("local H = ... H.dfhack.world.isFortressMode = function() return true end", H)
else:
    print("SKIPPED (Lua part): needs the lupa package with Lua 5.3 (pip install lupa)")


# --- 2. the brain: Bridge.defer / batch / fallback ---------------------------------

@test("Bridge: held actions go with the next act in one batch call; each answer to its own callback, in order")
def _():
    b, g = game()
    got = []
    b.defer({"type": "report_status", "status": {}}, lambda r, e: got.append(("rs", r and r["ok"], e)))
    b.defer({"type": "ledger_set", "values": {}}, lambda r, e: got.append(("ls", r and r["ok"], e)))
    assert g.calls == [] and len(b.pending) == 2
    r = b.act({"type": "work_order", "recipe": "brew_drink"})
    assert g.calls == ["batch"] and r["ok"] and r["action"] == "work_order", (g.calls, r)
    assert [a["type"] for a in g.ran] == ["report_status", "ledger_set", "work_order"]
    assert got == [("rs", True, None), ("ls", True, None)] and b.pending == []


@test("Bridge: a held action refused or failing: its callback as act would (rejected reply / BridgeError)")
def _():
    b, g = game(refuse={"set_learned"})
    got = []
    b.defer({"type": "set_learned", "learned": {}}, lambda r, e: got.append((r, e)))
    b.defer({"type": "boom"}, lambda r, e: got.append((r, e)))
    b.flush()
    assert g.calls == ["batch"]
    assert got[0][0]["rejected"] and got[0][1] is None
    assert got[1][0] is None and isinstance(got[1][1], BridgeError) and "it broke" in str(got[1][1])
    # the host failing raises BridgeError as act does; the held ones still answered
    got.clear()
    b.defer({"type": "report_status", "status": {}}, lambda r, e: got.append(r["ok"]))
    try:
        b.act({"type": "boom"})
        raise AssertionError("no error")
    except BridgeError as e:
        assert "it broke" in str(e)
    assert got == [True]


@test("Bridge: an older bridge (no batch in version): held actions go at once, one call each")
def _():
    b, g = game(batch=False)
    got = []
    b.defer({"type": "report_status", "status": {}}, lambda r, e: got.append(r["ok"]))
    assert g.calls == ["act"] and got == [True] and b.pending == []
    b.act({"type": "save_memory"})
    assert g.calls == ["act", "act"] and "batch" not in g.calls


@test("Bridge: the batch refused as a whole: each sent again alone (nothing ran), the host's answer kept")
def _():
    b, g = game(fail_batch="error")
    got = []
    b.defer({"type": "report_status", "status": {}}, lambda r, e: got.append(r["ok"]))
    r = b.act({"type": "save_memory"})
    assert g.calls == ["batch", "act", "act"] and r["ok"] and got == [True], g.calls
    assert [a["type"] for a in g.ran] == ["report_status", "save_memory"]


@test("Bridge: no answer to a batch of bookkeeping: sent again one by one; with a real action in it: nothing resent")
def _():
    b, g = game(fail_batch="timeout")
    got = []
    b.defer({"type": "report_status", "status": {}}, lambda r, e: got.append(r and r["ok"]))
    b.defer({"type": "ledger_set", "values": {}}, lambda r, e: got.append(r and r["ok"]))
    b.flush()
    assert g.calls == ["batch", "act", "act"] and got == [True, True], g.calls
    g.calls.clear()
    got.clear()
    b.defer({"type": "report_status", "status": {}}, lambda r, e: got.append(type(e).__name__))
    try:
        b.act({"type": "work_order", "recipe": "brew_drink"})
        raise AssertionError("no error")
    except DFHackError:
        pass
    assert g.calls == ["batch"] and got == ["DFHackError"], (g.calls, got)
    assert not any(a.get("type") == "work_order" for a in g.ran), "the order may have run: never sent twice"


@test("Bridge: never-batched actions (screens, long runs) go alone, after the held ones; a command flushes first")
def _():
    b, g = game()
    got = []
    b.defer({"type": "report_status", "status": {}}, lambda r, e: got.append(1))
    b.act({"type": "send_mission", "site_id": 3})
    assert g.calls == ["act", "act"] and [a["type"] for a in g.ran] == ["report_status", "send_mission"], g.calls
    g.calls.clear()
    b.defer({"type": "report_status", "status": {}}, lambda r, e: got.append(2))
    b.events()
    assert g.calls == ["act", "events"] and got == [1, 2], g.calls
    g.calls.clear()
    b.defer({"type": "save_game"}, lambda r, e: got.append(3))      # never held
    assert g.calls == ["act"] and got[-1] == 3


@test("Bridge: the caps: more than 20 or too long a payload cut into several calls; a huge one goes by act")
def _():
    b, g = game()
    for i in range(45):
        b.defer({"type": "ledger_set", "values": {"i": i}}, None)
    b.flush()
    assert g.calls == ["batch", "batch", "batch"], g.calls
    assert [a["values"]["i"] for a in g.ran] == list(range(45))
    g.calls.clear()
    g.ran.clear()
    big = "x" * 15000
    b.defer({"type": "set_learned", "learned": {"t": big}}, None)
    b.defer({"type": "set_culture", "culture": {"t": big}}, None)
    b.defer({"type": "set_culture", "culture": {"t": "y" * 30000}}, None)
    b.defer({"type": "report_status", "status": {}}, None)
    b.flush()
    assert g.calls == ["act", "act", "act", "act"], g.calls      # 15k + 15k is over the cap: each alone
    assert [a["type"] for a in g.ran] == ["set_learned", "set_culture", "set_culture", "report_status"]
    assert g.timeouts and all(t >= 10 for t in g.timeouts)


@test("Bridge: each action of a batch gets its own act line in bridge.log, as act writes it")
def _():
    b, g = game()
    lines = []
    import logging

    class Keep(logging.Handler):
        def emit(self, rec):
            lines.append(rec.getMessage())
    h = Keep()
    b.log.addHandler(h)
    try:
        b.defer({"type": "report_status", "status": {}}, None)
        b.act({"type": "save_memory"})
    finally:
        b.log.removeHandler(h)
    acts = [ln for ln in lines if ln.startswith("act ")]
    assert len(acts) == 2 and '"type":"report_status"' in acts[0] and '"type":"save_memory"' in acts[1], lines
    assert all(re.search(r"-> \{.*\} \(\d+ ms\)$", ln) for ln in acts), acts



@test("review 4: dfhack-run never started (a command line too long): nothing ran, so each goes again alone, "
      "a real action too; the host's answer kept")
def _():
    b, g = game(fail_batch="nostart")
    got = []
    b.defer({"type": "report_status", "status": {}}, lambda r, e: got.append(r and r["ok"]))
    r = b.act({"type": "work_order", "recipe": "brew_drink"})
    assert g.calls == ["batch", "act", "act"] and r["ok"] and got == [True], g.calls
    assert [a["type"] for a in g.ran] == ["report_status", "work_order"]


@test("review 4: the batch's size is measured as Windows quotes it (list2cmdline, quotes escaped) against "
      "BATCH_MAX_CMDLINE, beside the raw cap")
def _():
    import subprocess
    q = '"' * 4000              # JSON: 8,000 characters each; quoted for the command line: 16,000 each
    acts = [{"type": "set_learned", "learned": {"t": q}}, {"type": "set_culture", "culture": {"t": q}}]
    text = bridge_mod.batch_text([json.dumps(a, separators=(",", ":")) for a in acts])
    assert len(text) <= bridge_mod.BATCH_MAX_CHARS < len(subprocess.list2cmdline([text])), len(text)
    assert bridge_mod.cmdline_len(text) > bridge_mod.BATCH_MAX_CMDLINE == 30000
    b, g = game()
    for a in acts:
        b.defer(a, None)
    b.flush()
    assert g.calls == ["act", "act"], g.calls                  # too long together: each alone
    g.calls.clear()
    small = '"' * 2000
    for a in acts:
        b.defer({**a, list(a)[1]: {"t": small}}, None)
    b.flush()
    assert g.calls == ["batch"], g.calls


@test("review 4: dfhack-run that can't start (missing, command line too long) raises NotStarted; other OSErrors "
      "a DFHackError; one that starts and gives no answer NoAnswer")
def _():
    import subprocess
    import dfhack as dh
    d = dh.DFHack(dfhack_run=Path("/nonexistent/dfhack-run"), timeout_s=1.0)
    try:
        d.run("ai-bridge", "status")
        raise AssertionError("no error")
    except dh.NotStarted:
        pass
    keep = dh.subprocess.run

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 1.0)
    dh.subprocess.run = slow
    try:
        d.run("ai-bridge", "status")
        raise AssertionError("no error")
    except dh.NoAnswer:
        pass
    finally:
        dh.subprocess.run = keep
    assert issubclass(dh.NotStarted, DFHackError) and issubclass(dh.NoAnswer, DFHackError)
    # (last review) NotStarted only for the process not being made: E2BIG, Windows' 206, a missing program;
    # any other OSError (later, talking to it) is a plain DFHackError
    import errno as _errno
    win = OSError(22, "The filename or extension is too long")
    win.winerror = 206
    for e, started in ((OSError(_errno.E2BIG, "Argument list too long"), False), (win, False),
                       (FileNotFoundError(2, "no such file"), False), (OSError(_errno.EPIPE, "Broken pipe"), True),
                       (PermissionError(13, "denied"), True)):
        def boom(*a, _e=e, **k):
            raise _e
        dh.subprocess.run = boom
        try:
            d.run("ai-bridge", "status")
            raise AssertionError("no error")
        except dh.NotStarted:
            assert not started, e
        except DFHackError:
            assert started, e
        finally:
            dh.subprocess.run = keep

# --- 3. the cycle --------------------------------------------------------------------

@test("cycle: the bookkeeping goes in fewer calls with batch; the same actions in the same order, the same decisions")
def _():
    calls_b, ran_b, dec_b, _b = cycle_run(batch=True)
    calls_o, ran_o, dec_o, _o = cycle_run(batch=False)
    strip = lambda ran: [json.dumps(a, sort_keys=True) for a in ran
                         if a.get("type") not in ("report_status", "set_learned", "set_culture")]
    assert dec_b == dec_o and dec_b, (dec_b, dec_o)
    assert strip(ran_b) == strip(ran_o)
    order = lambda ran: [a["type"] for a in ran]
    assert order(ran_b) == order(ran_o), "every action, bookkeeping too, reaches the game in the same order"
    n_b = sum(1 for c in calls_b if c in ("act", "batch"))
    n_o = sum(1 for c in calls_o if c in ("act", "batch"))
    assert "batch" in calls_b and "batch" not in calls_o
    assert n_b < n_o, (n_b, n_o, calls_b, calls_o)


@test("cycle: a quiet cycle's tail (ledger_set, report_status, save_memory) is one call")
def _():
    _before()
    b, g = game()
    for _ in range(3):
        overseer.one_cycle(b, autopilot=True)
        g.state["date"]["tick"] += 1200
        overseer.LAST_FULL.clear()
    g.calls.clear()
    g.ran.clear()
    g.state["ledger"] = {"stale": True}           # the game's ledger differs: written again
    overseer.STATUS_SENT.clear()                  # and the panel's report sent again
    overseer.one_cycle(b, autopilot=True)
    types = [a["type"] for a in g.ran]
    tail = g.calls[g.calls.index("events") + 1:]
    assert {"ledger_set", "report_status", "save_memory"} <= set(types), types
    if "set_learned" in types or "set_culture" in types:
        # held set_learned answered before the memory is written: two calls
        assert tail == ["batch", "act"] and types[-1] == "save_memory", (tail, types)
    else:
        assert tail == ["batch"], (tail, types)
    assert types[-3:] == ["ledger_set", "report_status", "save_memory"] or types[-1] == "save_memory", types


@test("cycle: report_status remembered only when the game took it; a failed one is sent again next cycle")
def _():
    _before()
    b, g = game(refuse=set())
    overseer.report_status(b, {"mode": "x"})
    assert overseer.STATUS_SENT == {} and len(b.pending) == 1, "held: nothing known yet"
    b.flush()
    assert overseer.STATUS_SENT.get("payload") == {"mode": "x"}
    overseer.report_status(b, {"mode": "x"})
    assert b.pending == [], "the same report not sent again"
    overseer.STATUS_SENT.clear()
    g.fail_batch = "timeout"
    g.calls.clear()

    g._act_saved, g._act = g._act, lambda a: (_ for _ in ()).throw(DFHackError("gone"))
    overseer.report_status(b, {"mode": "y"})
    b.flush()
    assert overseer.STATUS_SENT == {}, overseer.STATUS_SENT
    g._act = g._act_saved


@test("cycle: set_learned's answer is in the memory before it is written (flushed before the save)")
def _():
    _before()
    b, g = game()
    seen = {}
    real = overseer.memstore.save

    def spy(key, memory, bank, bridge=None, limit=None):
        seen["pushed"] = (memory.learning or {}).get("pushed")
        seen["held"] = [a["type"] for a, _ in b.pending]
        return real(key, memory, bank, bridge, limit=limit)
    overseer.memstore.save = spy
    try:
        overseer.one_cycle(b, autopilot=True)
    finally:
        overseer.memstore.save = real
    assert "set_learned" in [a["type"] for a in g.ran]
    assert seen["pushed"], "the fingerprint was set before the memory was written"
    assert "set_learned" not in seen["held"] and "set_culture" not in seen["held"], seen


@test("cycle: with a fake bridge that has no defer (the older tests' fakes), everything goes at once as before")
def _():
    _before()
    sent = []

    class Plain:
        version = {}

        def act(self, a):
            sent.append(a["type"])
            return {"ok": True}
    overseer.report_status(Plain(), {"mode": "z"})
    overseer.write_ledger(Plain(), {"ledger": {}}, overseer.Memory(), defer=True)
    assert sent[0] == "report_status" and overseer.STATUS_SENT.get("payload") == {"mode": "z"}


if __name__ == "__main__":
    finish()
