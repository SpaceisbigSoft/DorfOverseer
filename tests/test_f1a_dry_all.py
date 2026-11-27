"""(F1a) Every DRY_OK action dry-run at delivery: brain/selftest_dry.py and
`python brain/selftest.py --dry-all`.

The bridge's DRY_OK list is read from lua/ai-bridge-catalog.lua; every name
on it needs an argument builder (a new action without one fails here), every
builder gives planner-shaped dry-run actions on a real fort's report and on
an empty one, and the run fails on Lua error text and passes a clean refusal.

    python tests/test_f1a_dry_all.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, test  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import selftest  # noqa: E402
import selftest_dry as sd  # noqa: E402
from dfhack import DFHackError, NoAnswer  # noqa: E402

FORTS = {
    "test fort": json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8")),
    "enxah": json.loads((ROOT / "tests" / "fixtures" / "real" / "enxah-0.104.52-y73-winter.json")
                        .read_text(encoding="utf-8")),
    "empty": {},
}
LUA = "".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "lua").glob("*.lua")))


@test("DRY_OK is read from the catalog: every quoted name in its list, no comment text, no repeats")
def _():
    names = sd.dry_ok_actions()
    assert len(names) > 200, len(names)
    assert len(names) == len(set(names))
    for n in ("start_project", "farm_plots", "were_cells", "social_places", "fight_watch", "unforbid_dead"):
        assert n in names, n
    # an independent count: the quoted names between the list's two ends
    text = (ROOT / "lua" / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    block = text[text.index("DRY_OK = {}"):text.index("do DRY_OK[name] = true end")]
    block = re.sub(r"--[^\n]*", "", block)
    assert set(names) >= set(re.findall(r"'([a-z_0-9]+)'", block))
    # never unpause, pull_gate or narrow_detail (their dry runs act for real)
    assert not {"unpause", "pull_gate", "narrow_detail"} & set(names)


@test("every DRY_OK action is in the bridge's ACTIONS table")
def _():
    acts = sd.catalog_actions()
    assert len(acts) > 250, len(acts)
    assert {"unpause", "work_order", "reset_cage_traps", "assign_quivers", "cut_entrance"} <= acts
    missing = [n for n in sd.dry_ok_actions() if n not in acts]
    assert not missing, missing


@test("every DRY_OK action has an argument builder (add one to selftest_dry.ARGS for a new action)")
def _():
    missing = [n for n in sd.dry_ok_actions() if n not in sd.ARGS]
    assert not missing, f"no builder in brain/selftest_dry.py ARGS for: {missing}"
    stale = [n for n in sd.ARGS if n not in sd.dry_ok_actions()]
    assert not stale, f"builders for actions no longer in DRY_OK: {stale}"


@test("a DRY_OK list with a new name and no builder is caught")
def _():
    import tempfile
    text = (ROOT / "lua" / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    text = text.replace("    'were_cells',", "    'were_cells', 'brand_new_thing',   -- (test)")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cat.lua"
        p.write_text(text, encoding="utf-8")
        names = sd.dry_ok_actions(p)
    assert "brand_new_thing" in names
    assert [n for n in names if n not in sd.ARGS] == ["brand_new_thing"]


@test("every builder gives dry-run actions of its own type, as JSON, on a real fort and an empty report")
def _():
    for label, st in FORTS.items():
        fort = sd.Fort(st)
        for n in sd.dry_ok_actions():
            acts = sd.build_actions(n, fort)
            assert acts, (label, n)
            for a in acts:
                assert a["type"] == n and a["dry_run"] is True, (label, a)
                assert json.loads(json.dumps(a)) == a, (label, n)
                assert None not in a.values(), (label, a)


@test("each argument a builder sends is a field the bridge reads (a misspelt key never reaches a handler)")
def _():
    # fields the planner sends for its own bookkeeping (the outcome reads them), the bridge not
    brain_only = {("farm_thresholds", "steer")}
    bad = []
    for n in sd.dry_ok_actions():
        for a in sd.build_actions(n, sd.Fort(FORTS["enxah"])):
            for k in a:
                if k in ("type", "dry_run") or (n, k) in brain_only:
                    continue
                if not re.search(r"[.]%s\b|\[['\"]%s['\"]\]|['\"]%s['\"]|\b%s\s*=" % (k, k, k, k), LUA):
                    bad.append(f"{n}.{k}")
    assert not bad, bad


@test("the builders take the fort's own ids: a squad, the entrance, a project, a location, a workshop")
def _():
    f = sd.Fort(FORTS["enxah"])
    st = FORTS["enxah"]
    assert f.squad == st["military"]["squads"][0]["id"]
    assert f.entrance == st["entrances"]["entrances"][0]["id"]
    assert f.project == st["projects"]["open"][0]["id"]
    assert f.location == 0                      # an id of 0 is an id, not "none"
    assert f.building == st["order_desk"]["workshops"][0]["id"]
    assert f.hospital == st["health"]["hospital"][0]["id"]
    assert sd.build_actions("set_uniform", f)[0]["squad_id"] == f.squad
    assert sd.build_actions("open_entrance", f)[0]["id"] == f.entrance
    e = sd.Fort({})
    assert e.squad == sd.MISSING_ID and e.entrance == sd.MISSING_ID


@test("Lua error text is found; a clean refusal is not")
def _():
    for t in ("...ai-builder.lua:812: attempt to index a nil value (field 'mat_type')",
              "attempt to call a nil value (global 'forbidden')",
              "stack traceback:\n\t[C]: in ?",
              "Cannot read field item.mat_type: not found",
              "bad argument #1 to 'ipairs' (table expected, got nil)",
              "attempt to compare number with nil",
              "attempt to perform arithmetic on a nil value"):
        assert sd.lua_error(t), t
        assert sd.lua_error({"ok": False, "error": t}), t
    for t in ("no site", "nothing to do", "ledger_set: x is not a ledger field", "no such squad",
              "the AI is halted in the game (Ctrl-Shift-H to resume)", "build_killzone needs entrance_id",
              "cross_cavern: layer is Cavern1, Cavern2 or Cavern3", "no free mechanisms"):
        assert sd.lua_error({"ok": False, "rejected": True, "error": t}) is None, t
    assert sd.lua_error({"ok": True, "dry_run": True, "would": [{"why": "fine"}]}) is None


@test("classify: ok and refusals pass; Lua text, no dry run, unknown type and no JSON fail; a timeout warns")
def _():
    assert sd.classify({"ok": True, "dry_run": True}, None)[0] == "ok"
    assert sd.classify({"ok": False, "error": "no site"}, None)[0] == "refused"
    assert sd.classify({"ok": False, "rejected": True, "error": "nothing to do"}, None)[0] == "refused"
    assert sd.classify({"ok": False, "error": "x.lua:3: attempt to index a nil value"}, None)[0] == "lua"
    assert sd.classify({"ok": False, "rejected": True, "error": "pull_gate has no dry run (it would act for real)"},
                       None)[0] == "bad"
    assert sd.classify({"ok": False, "rejected": True, "error": "unknown action type: zzz (known: a)"}, None)[0] == "bad"
    assert sd.classify(None, DFHackError("No JSON in output of ai-bridge act:\nboom"))[0] == "bad"
    assert sd.classify(None, DFHackError("dfhack-run exited with code 1:\nstack traceback:"))[0] == "lua"
    assert sd.classify(None, NoAnswer("DFHack did not answer within 10s"))[0] == "timeout"


class FakeDF:
    def __init__(self, answer):
        self.answer, self.sent = answer, []

    def run_json(self, *args, timeout=None):
        assert args[:2] == ("ai-bridge", "act")
        a = json.loads(args[2])
        self.sent.append(a)
        r = self.answer(a)
        if isinstance(r, Exception):
            raise r
        return r


class FakeBridge:
    def __init__(self, answer):
        self.df = FakeDF(answer)


@test("run_dry_all: every action sent with dry_run true, one line each, a summary, exit 0 on clean refusals")
def _():
    b = FakeBridge(lambda a: {"ok": False, "rejected": True, "error": "nothing to do", "action": a["type"]})
    lines = []
    rc = sd.run_dry_all(b, FORTS["enxah"], out=lines.append)
    assert rc == 0, lines[-3:]
    assert all(a["dry_run"] is True for a in b.df.sent)
    names = sd.dry_ok_actions()
    assert {a["type"] for a in b.df.sent} == set(names)
    assert sum(1 for l in lines if l.startswith("[PASS]")) == len(b.df.sent)
    assert any(f"{len(names)} actions, {len(b.df.sent)} dry runs" in l and "0 Lua errors" in l for l in lines)


@test("run_dry_all: a Lua error in one action's answer fails the run and names the action")
def _():
    def answer(a):
        if a["type"] == "mark_melt":
            return {"ok": False, "error": "...ai-disposal.lua:120: attempt to index a nil value (field 'mat_type')"}
        if a["type"] == "unforbid_dead":
            return DFHackError("dfhack-run exited with code 1:\n...stack traceback:\n\t[C]: in ?")
        if a["type"] == "save_game":
            return NoAnswer("DFHack did not answer within 10s")
        return {"ok": True, "dry_run": True}
    lines = []
    rc = sd.run_dry_all(FakeBridge(answer), {}, out=lines.append)
    assert rc == 1
    fails = [l for l in lines if l.startswith("[FAIL]")]
    assert len(fails) == 2 and any("mark_melt" in l and "Lua error" in l for l in fails), fails
    assert any(l.startswith("[WARN] save_game") for l in lines)
    assert lines[-1] == "FAILED: mark_melt, unforbid_dead"
    assert any("2 Lua errors" in l and "1 no answer in time" in l for l in lines)


@test("run_dry_all --only: just the named actions")
def _():
    b = FakeBridge(lambda a: {"ok": True})
    lines = []
    assert sd.run_dry_all(b, {}, out=lines.append, only=["save_game", "were_cells"]) == 0
    assert {a["type"] for a in b.df.sent} == {"save_game", "were_cells"}


@test("run_dry_all: a builder that throws is a failure of its own, the rest still run")
def _():
    keep = sd.ARGS["were_cells"]
    sd.ARGS["were_cells"] = lambda f: 1 / 0
    try:
        b = FakeBridge(lambda a: {"ok": True})
        lines = []
        assert sd.run_dry_all(b, {}, out=lines.append, only=["were_cells", "save_game"]) == 1
        assert any(l.startswith("[FAIL] were_cells: no arguments built") for l in lines)
        assert [a["type"] for a in b.df.sent] == ["save_game"]
    finally:
        sd.ARGS["were_cells"] = keep


@test("selftest's command line: nothing for the daily run; --dry-all, --only and --port")
def _():
    a = selftest.parse_args([])
    assert not a.dry_all and a.port is None and a.only == ""
    a = selftest.parse_args(["--dry-all", "--port", "5001", "--only", "save_game,were_cells"])
    assert a.dry_all and a.port == 5001 and a.only == "save_game,were_cells"


@test("selftest --dry-all: runs the dry runs (not the daily checks) and gives their exit code")
def _():
    calls = []

    class B:
        def __init__(self, df=None):
            self.df = FakeDF(lambda a: calls.append(a["type"]) or {"ok": False, "error": "no site"})

        def handshake(self):
            return {"protocol": 1}

        def status(self):
            return {"in_fort": True}

        def state(self, include_units=True, tier=None):
            return FORTS["enxah"]

    import contextlib
    import io
    keep = selftest.Bridge
    selftest.Bridge = B
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert selftest.main(["--dry-all", "--only", "save_game"]) == 0
        assert calls == ["save_game"]
        assert "[PASS] save_game: refused: no site" in buf.getvalue()
        assert "bridge answers" not in buf.getvalue()          # the daily checks are not run
        B.status = lambda self: {"in_fort": False}
        with contextlib.redirect_stdout(io.StringIO()):
            assert selftest.main(["--dry-all"]) == 1
    finally:
        selftest.Bridge = keep


if __name__ == "__main__":
    finish()
