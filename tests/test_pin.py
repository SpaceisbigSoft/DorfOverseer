"""(0.105.0) Tests for the keeper's pin (brain/pin.py): revive, the daily
backup and the overseer stay on the world and site the keeper started with;
a save that fails to load is tried twice, then the next one, then a backup.

    python tests/test_pin.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import make_test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

TMP = Path(tempfile.mkdtemp())
os.environ["DFAI_LOG_DIR"] = str(TMP / "logs")

import backup  # noqa: E402
import pin  # noqa: E402
import revive  # noqa: E402
from dfhack import GameNotRunning  # noqa: E402

pin.PIN_FILE = TMP / "logs" / "keeper-pin.json"
pin.LAST_FORT = TMP / "logs" / "last-fort.json"
revive.LAST_FORT = pin.LAST_FORT
backup.BACKUP_DIR = TMP / "backups"
backup.STATE = TMP / "backups" / "last.json"


def _before():
    pin.clear()


test = make_test(before=_before)


def last_fort(world, save_dir, site, df_path=None):
    pin.LAST_FORT.parent.mkdir(parents=True, exist_ok=True)
    pin.LAST_FORT.write_text(json.dumps({"df_path": df_path or str(TMP / "df"), "save_dir": save_dir,
                                         "fort": f"{save_dir}#{site}", "world": world}), encoding="utf-8")


@test("first run in a fresh world: no last-fort.json, nothing pinned, nothing refused, no candidates")
def _():
    pin.LAST_FORT.unlink(missing_ok=True)
    assert pin.take(time.time() - 5) is None and pin.current() is None
    assert pin.matches("Any", 3) and pin.refusal("Any", 3) is None
    assert revive.load_candidates() == ([], None)


@test("the pin is the fort the overseer named since the keeper started; another world is refused, said plainly")
def _():
    started = time.time() - 10
    last_fort("Enxah", "region2", 7)
    os.utime(pin.LAST_FORT, (started - 100, started - 100))          # from before this keeper
    assert pin.take(started) is None                                  # (not yet: the game isn't at the title)
    os.utime(pin.LAST_FORT, None)
    said = []
    p = pin.take(started, log=said.append)
    assert p["world"] == "Enxah" and p["site"] == "7" and p["save_dir"] == "region2", p
    assert said and "pinned" in said[0], said
    last_fort("Other", "region5", 3)                                  # a manual run of another fort
    assert pin.current()["world"] == "Enxah"                          # the pin holds
    os.environ["DFAI_PIN"] = "1"
    try:
        assert pin.refusal("Enxah", 7) is None
        r = pin.refusal("Other", 3)
        assert r and "Enxah" in r and "Not acting" in r, r
        assert pin.refusal("Enxah", 8)                                # the same world, another site
    finally:
        del os.environ["DFAI_PIN"]
    assert pin.refusal("Other", 3) is None                            # the player's own run: never refused


@test("revive loads the pinned world's saves, not last-fort.json's (a daytime run of another fort)")
def _():
    started = time.time() - 10
    root = TMP / "df" / "save"
    for name in ("region2", "region5", "autosave 1"):
        (root / name).mkdir(parents=True, exist_ok=True)
    last_fort("Enxah", "region2", 7)
    pin.take(started)
    last_fort("Other", "region5", 3)
    import dfhack
    old = dfhack.save_root
    revive.save_root = lambda df_path, save_dir=None: root
    try:
        folders, world = revive.load_candidates()
    finally:
        revive.save_root = old
    assert world == "Enxah" and "region2" in folders and "region5" not in folders, (folders, world)


class FakeDF:
    def __init__(self):
        self.state, self.calls, self.site = "title", [], 7

    def run(self, *args):
        self.calls.append(args)
        if self.state == "down":
            raise GameNotRunning("no")
        if args[0] == "lua":
            return ("WORLD-LOADED SITE=%d" % self.site) if self.state == "world" else "NO-WORLD SITE="
        return '{"ok": true, "started": true, "folder": "%s"}' % args[-1].split("|")[0]


@test("a save that crashes DF on load: tried twice, then the next older one, then the newest backup copy")
def _():
    t = [0.0]
    df = FakeDF()
    logs, restored = [], []
    rv = revive.Reviver(logs.append, dfhack=df, launcher=lambda *_: None, clock=lambda: t[0])
    rv.candidates = lambda: (["autosave 2", "region2"], None)
    rv.restore = lambda log: restored.append(1) or "AI restore 2026-10-31 1200"

    def loads():
        return [c[2] for c in df.calls if c[0] == "ai-title"]

    def cycle_crash():
        for _ in range(4):                     # at the title: a load starts
            rv.tick(); t[0] += 60
        df.state = "down"                      # DF closes while loading
        rv.tick(); t[0] += 60
        df.state = "title"                     # (started again by the down branch)

    cycle_crash()
    cycle_crash()
    assert loads() == ["autosave 2", "autosave 2"], loads()
    assert rv.load_fails == {"autosave 2": 2} and any("isn't tried again" in x for x in logs), logs
    t[0] += 3600                               # (three loads an hour at most)
    cycle_crash()
    assert loads()[-1] == "region2", loads()
    cycle_crash()
    t[0] += 3600
    for _ in range(4):
        rv.tick(); t[0] += 60
    assert restored and loads()[-1] == "AI restore 2026-10-31 1200", (restored, loads())
    df.state = "world"
    rv.tick()
    assert rv.loading is None and "AI restore 2026-10-31 1200" not in rv.load_fails


@test("a load that never brings up a fort counts as failed after the timeout; a good load clears the count")
def _():
    t = [0.0]
    df = FakeDF()
    rv = revive.Reviver(lambda *_: None, dfhack=df, launcher=lambda *_: None, clock=lambda: t[0])
    rv.candidates = lambda: (["region2"], None)
    for _ in range(4):
        rv.tick(); t[0] += 60
    assert rv.loading and rv.loading[0] == "region2"
    t[0] += revive.LOAD_TIMEOUT_S
    rv.tick()
    assert rv.load_fails == {"region2": 1}, rv.load_fails
    assert rv.loading and rv.loading[0] == "region2"          # tried again at once (one failure so far)
    t[0] += 60
    df.state, df.site = "world", ""                       # (0.105.0 review) the world up, no fort's map yet
    df.run = (lambda orig: lambda *a: ("WORLD-LOADED SITE=" if a[0] == "lua" and df.site == "" else orig(*a)))(df.run)
    rv.tick()
    assert rv.loading and rv.loading[0] == "region2" and rv.load_fails == {"region2": 1}, (rv.loading, rv.load_fails)
    t[0] += 60
    df.site = 7
    rv.tick()
    assert rv.load_fails == {} and rv.loading is None


@test("restore from backups: the pinned fort's newest copy becomes 'AI restore <date>', once each")
def _():
    df_path = TMP / "df2"
    (df_path / "save" / "region2").mkdir(parents=True, exist_ok=True)
    last_fort("Enxah", "region2", 7, df_path=str(df_path))
    pin.take(time.time() - 10)
    for name in ("2026-10-30 0100", "2026-10-31 0100"):
        (backup.BACKUP_DIR / "region2" / name).mkdir(parents=True, exist_ok=True)
        (backup.BACKUP_DIR / "region2" / name / "world.sav").write_text(name)
    revive.save_root = lambda p, s=None: df_path / "save"
    try:
        a = revive.restore_from_backup()
        b = revive.restore_from_backup()
        c = revive.restore_from_backup()
    finally:
        import dfhack
        revive.save_root = dfhack.save_root
    assert a == "AI restore 2026-10-31 0100" and b == "AI restore 2026-10-30 0100" and c is None, (a, b, c)
    assert (df_path / "save" / a / "world.sav").read_text() == "2026-10-31 0100"


def make_save(root: Path, name: str, age: float, text: str | None = None):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "world.sav").write_text(text or name)
    t = time.time() - age
    os.utime(d / "world.sav", (t, t))
    os.utime(d, (t, t))


@test("backup: only the pinned world and site; another world's newer autosave never copied")
def _():
    import shutil
    shutil.rmtree(backup.BACKUP_DIR, ignore_errors=True)
    backup.SESSION.clear()
    root = TMP / "bk" / "save"
    make_save(root, "region2", 5000)
    make_save(root, "autosave 1", 3000, "other world")     # written before this fort was loaded
    last_fort("Enxah", "region2", 7)
    pin.take(time.time() - 10)
    now = time.time()
    fort = {"world": "Enxah", "site_id": 7, "save_dir": "region2"}
    line = backup.maybe(root, "region2", now=now, fort=fort, date={"tick": 1000})
    assert line and "region2" in line and "autosave" not in line, line
    copies = [c for c in (backup.BACKUP_DIR / "region2").iterdir() if c.is_dir()]   # (0.105.33) the .fort.json mark sits beside
    assert (copies[0] / "world.sav").read_text() == "region2"
    # another world loaded (a daytime run): no copy, whatever is due
    assert backup.maybe(root, "region5", now=now + 2 * 86400, fort={"world": "Other", "site_id": 3}) is None


@test("revive (0.105.0 review): an 'AI restore' folder restored earlier is a load candidate later")
def _():
    root = TMP / "cand" / "save"
    make_save(root, "region2", 5000)
    make_save(root, "AI restore 2026-10-31 0100", 100)
    last_fort("Enxah", "region2", 7, df_path=str(TMP / "cand"))
    pin.take(time.time() - 10)
    revive.save_root = lambda p, s=None: root
    try:
        folders, _ = revive.load_candidates()
    finally:
        import dfhack
        revive.save_root = dfhack.save_root
    assert folders[:2] == ["AI restore 2026-10-31 0100", "region2"], folders


@test("backup: never in a season's last 3 days, nor while any save folder is being written")
def _():
    import shutil
    shutil.rmtree(backup.BACKUP_DIR, ignore_errors=True)
    backup.SESSION.clear()
    root = TMP / "bk2" / "save"
    make_save(root, "region2", 5000)
    fort = {"world": "W", "site_id": 1}
    now = time.time()
    assert backup.maybe(root, "region2", now=now, fort=fort, date={"tick": 84 * 1200 - 1200}) is None
    make_save(root, "autosave 3", 10)                    # DF writing its autosave now
    assert backup.maybe(root, "region2", now=now, fort=fort, date={"tick": 1000}) is None
    make_save(root, "autosave 3", 5000)
    assert backup.maybe(root, "region2", now=now, fort=fort, date={"tick": 1000})


if __name__ == "__main__":
    finish()
