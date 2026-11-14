"""(0.105.42) The keeper loads only its own game's saves, and only its own game
counts as running (13 Nov 22:30: C and D loaded A's fort; B-F waited on A's game).

    python tests/test_r42_saves.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
import dfhack  # noqa: E402
import revive  # noqa: E402


@test("a portable copy's saves are only its own folder")
def _():
    with tempfile.TemporaryDirectory() as d:
        game, appdata = Path(d) / "DF-C", Path(d) / "appdata"
        (game / "prefs").mkdir(parents=True)
        (game / "save" / "autosave 2").mkdir(parents=True)
        (appdata / "Bay 12 Games" / "Dwarf Fortress" / "save" / "autosave 2").mkdir(parents=True)
        old = os.environ.get("APPDATA")
        os.environ["APPDATA"] = str(appdata)
        try:
            assert len(dfhack.save_roots(game)) == 2          # not portable: both, as before
            (game / "prefs" / "portable.txt").write_text("")
            assert dfhack.save_roots(game) == [game / "save"]
            assert dfhack.save_root(game, "autosave 2") == game / "save"
        finally:
            if old is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old


@test("the fort's own folder isn't listed twice")
def _():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for n in ("autosave 1", "autosave 2"):
            (root / n).mkdir()
            (root / n / "world.sav").write_text("x")
        lf = root / "last.json"
        lf.write_text('{"df_path": "%s", "save_dir": "autosave 1", "world": "W"}' % d.replace("\\", "/"))
        import pin
        real = revive.save_root, revive.LAST_FORT, pin.current
        pin.current = lambda: None
        revive.save_root = lambda p, s: root
        revive.LAST_FORT = lf
        try:
            names, _w = revive.load_candidates()
        finally:
            revive.save_root, revive.LAST_FORT, pin.current = real
        assert sorted(names) == ["autosave 1", "autosave 2"], names


@test("only this keeper's own game counts as running")
def _():
    paths = "D:\\SteamLibrary\\steamapps\\common\\Dwarf Fortress\\Dwarf Fortress.exe\n"
    run = lambda *a, **k: SimpleNamespace(stdout=paths, returncode=0)
    assert revive.df_running(run=run, exe="D:\\DF-C\\Dwarf Fortress.exe") is False
    assert revive.df_running(run=run, exe="D:\\SteamLibrary\\steamapps\\common\\Dwarf Fortress\\Dwarf Fortress.exe") is True
    none = lambda *a, **k: SimpleNamespace(stdout="", returncode=0)
    assert revive.df_running(run=none, exe="D:\\DF-C\\Dwarf Fortress.exe") is False


@test("a save name twice on the title screen is refused, and counted as a failed load")
def _():
    src = (ROOT / "lua" / "ai-title.lua").read_text(encoding="utf-8")
    assert "count_in(t.savegame_header, folder) > 1" in src
    assert "count_in(t.savegame_header, f) > 1" in src
    assert "two saves called" in revive._ONE_FOLDER


finish()
