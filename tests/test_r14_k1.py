"""(r14 k1) A save torn when the PC went down (E, 22 Nov 05:47: 'autosave 3's
world.sav ended in 50.8 MB of zeros) is never loaded, copied or restored;
a load DF hangs on counts in full against that save as written.

    python tests/test_r14_k1.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

TMP = Path(tempfile.mkdtemp())
os.environ["DFAI_LOG_DIR"] = str(TMP / "logs")

import backup  # noqa: E402
import pin  # noqa: E402
import revive  # noqa: E402
from dfhack import GameNotRunning, NoAnswer  # noqa: E402

LOGS = TMP / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
pin.PIN_FILE, pin.LAST_FORT = LOGS / "keeper-pin.json", LOGS / "last-fort.json"
revive.LAST_FORT = LOGS / "last-fort.json"
backup.BACKUP_DIR = TMP / "backups"
backup.STATE = backup.BACKUP_DIR / "last.json"

MB = 1 << 20


def intact(root: Path, name: str, age: float, size: int = 200_000) -> Path:
    """A save folder whose world.sav ends in data (no zero byte at its end)."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "world.sav").write_bytes(bytes((i % 251) + 1 for i in range(size)))
    (d / "unit-1.dat").write_bytes(b"u" * 100)
    t = time.time() - age
    os.utime(d / "world.sav", (t, t))
    return d


def torn(root: Path, name: str, age: float, head: int = 300_000, zeros: int = 3 * MB) -> Path:
    """A save folder as the shutdown left it: the start written, the rest zeros."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    with (d / "world.sav").open("wb") as f:
        f.write(bytes((i % 251) + 1 for i in range(head)))
        f.write(b"\0" * zeros)
    (d / "unit-1.dat").write_bytes(b"u" * 100)
    t = time.time() - age
    os.utime(d / "world.sav", (t, t))
    return d


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*"))}


def pin_to(df_path: Path, save_dir: str, world="W", site="1430") -> None:
    pin.PIN_FILE.write_text(json.dumps({"world": world, "site": site, "save_dir": save_dir,
                                        "df_path": str(df_path), "started": 1.0}))


class Patched:
    """revive.save_root pointed at a temp save folder for the test."""
    def __init__(self, root: Path):
        self.root = root

    def __enter__(self):
        self.saved = revive.save_root
        revive.save_root = lambda p, s=None: self.root
        return self

    def __exit__(self, *a):
        revive.save_root = self.saved
        pin.clear()


class CountingOpen:
    """An opener that counts the bytes read."""
    def __init__(self):
        self.read = 0

    def __call__(self, path, mode="rb"):
        f = open(path, mode)
        outer = self

        class W:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                f.close()

            def seek(self, *a):
                return f.seek(*a)

            def tell(self):
                return f.tell()

            def read(self, n=-1):
                data = f.read(n)
                outer.read += len(data)
                return data
        return W()


# ------------------------------------------------------------------ the check

@test("damaged: a world.sav ending in MBs of zeros; intact, a few zero bytes, unreadable-free cases are not")
def _():
    import save_check
    root = TMP / "chk"
    bad = torn(root, "autosave 3", 10)
    good = intact(root, "autosave 2", 20)
    why = save_check.damage(bad)
    assert why and "3.1 MB of zeros" in why, why
    assert save_check.damage(good) is None
    # a few trailing zero bytes (under one 4 KiB cluster) are never damage
    few = root / "few"
    few.mkdir()
    (few / "world.sav").write_bytes(b"x" * 5000 + b"\0" * 100)
    assert save_check.damage(few) is None
    # a small torn file: a 40 KB zero tail is over 10% of a 100 KB file
    small = torn(root, "small", 5, head=60_000, zeros=40_000)
    assert save_check.damage(small), "a small torn save"
    assert save_check.damage(root / "not there") is None          # no folder: not judged


@test("damaged: world.sav missing or empty")
def _():
    import save_check
    root = TMP / "chk2"
    (root / "none").mkdir(parents=True)
    (root / "none" / "unit-1.dat").write_bytes(b"u")
    (root / "empty").mkdir()
    (root / "empty" / "world.sav").write_bytes(b"")
    assert "no world.sav" in save_check.damage(root / "none")
    assert "empty" in save_check.damage(root / "empty")


@test("cheap: a 60 MB (sparse) world.sav ending in data reads only its last 1 MiB")
def _():
    import save_check
    d = TMP / "sparse" / "autosave 1"
    d.mkdir(parents=True)
    with (d / "world.sav").open("wb") as f:
        f.seek(60 * MB - 1)
        f.write(b"\x01")
    op = CountingOpen()
    assert save_check.damage(d, opener=op) is None
    assert 0 < op.read <= save_check.TAIL_READ, op.read
    op2 = CountingOpen()
    assert save_check.damage(d, opener=op2) is None              # judged once per file as written
    assert op2.read == 0, op2.read
    # torn (the first byte only): measured back in chunks, said in MB
    d2 = TMP / "sparse" / "autosave 3"
    d2.mkdir(parents=True)
    with (d2 / "world.sav").open("wb") as f:
        f.write(b"\x01")
        f.seek(60 * MB - 1)
        f.write(b"\0")
    why = save_check.damage(d2)
    assert why and "62.9 MB of zeros" in why, why


# ------------------------------------------------------------------ candidates

@test("load_candidates: the damaged newest is skipped, also when the pin names it; nothing is touched")
def _():
    root = TMP / "dfA" / "save"
    torn(root, "autosave 3", 100)
    intact(root, "autosave 2", 5000)
    intact(root, "autosave 1", 9000)
    before = snapshot(root)
    with Patched(root):
        pin_to(TMP / "dfA", "autosave 3")
        names, world = revive.load_candidates()
        assert names == ["autosave 2", "autosave 1"], names
        assert world == "W"
        assert [n for n, _ in revive.LAST_DAMAGED] == ["autosave 3"], revive.LAST_DAMAGED
        assert revive.damaged_folder("autosave 3") and revive.damaged_folder("autosave 2") is None
    assert snapshot(root) == before


@test("backup: the newest folder (and the daily copy's source) is never a damaged save")
def _():
    root = TMP / "dfB" / "save"
    torn(root, "autosave 3", 100)
    intact(root, "autosave 2", 5000)
    intact(root, "region4", 9000)
    assert backup.newest_folder(root, "region4").name == "autosave 2"
    assert backup._ours(root, "region4", 0.0).name == "autosave 2"


@test("restore: a damaged backup copy is passed over for the next older one (said once)")
def _():
    root = TMP / "dfR" / "save"
    intact(root, "region1", 9000)
    bdir = backup.BACKUP_DIR / "region1"
    new = torn(bdir, "2026-11-22 0500", 10)
    old = intact(bdir, "2026-11-21 0500", 3000)
    saved = backup.copies_of
    backup.copies_of = lambda *a, **k: [new, old]
    logs = []
    try:
        with Patched(root):
            pin_to(TMP / "dfR", "region1")
            name = revive.restore_from_backup(logs.append)
            assert name == "AI restore 2026-11-21 0500", name
            assert not (root / "AI restore 2026-11-22 0500").exists()
            revive.restore_from_backup(logs.append)
    finally:
        backup.copies_of = saved
    said = [x for x in logs if "is damaged" in x]
    assert len(said) == 1 and "2026-11-22 0500" in said[0], logs


# ------------------------------------------------------------------ the reviver

class TitleDF:
    def __init__(self):
        self.state, self.calls = "title", []

    def run(self, *args):
        self.calls.append(args)
        if self.state == "down":
            raise GameNotRunning("no")
        if self.state == "hung":
            raise NoAnswer("timed out")
        if args[0] == "lua":
            return "WORLD-LOADED SITE=1430" if self.state == "world" else "NO-WORLD SITE="
        if args[1] == "status":
            return ""
        return '{"ok": true, "started": true, "folder": "%s"}' % args[-1].split("|")[0]


def loads(df):
    return [c[-1] for c in df.calls if c[0] == "ai-title" and c[1] != "status"]


@test("reviver: pinned to the torn 'autosave 3', it loads 'autosave 2' and says so once; nothing moved")
def _():
    root = TMP / "dfE" / "save"
    torn(root, "autosave 3", 100)
    intact(root, "autosave 2", 5000)
    before = snapshot(root)
    t = [0.0]
    df = TitleDF()
    logs = []
    with Patched(root):
        pin_to(TMP / "dfE", "autosave 3")
        rv = revive.Reviver(logs.append, dfhack=df, launcher=lambda *_: None, clock=lambda: t[0])
        rv.restore = None
        for _ in range(4):
            rv.tick(); t[0] += 60
        assert loads(df) and all("autosave 3" not in x for x in loads(df)), loads(df)
        assert loads(df)[-1] == "autosave 2", loads(df)
        df.state = "down"                                   # it crashed later: loaded again
        rv.tick(); t[0] += 60
        df.state = "title"
        for _ in range(4):
            rv.tick(); t[0] += 60
        assert len(loads(df)) >= 2 and all(x == "autosave 2" for x in loads(df)), loads(df)
    said = [x for x in logs if "is damaged" in x and "skipped" in x]
    assert len(said) == 1, logs
    assert said[0].startswith("Revive: 'autosave 3' is damaged (its world.sav ends in"), said
    assert "written as the PC went down?): skipped, loading 'autosave 2'." in said[0], said
    assert sum("Needs you" in x and "old-saves" in x for x in logs) == 1, logs
    assert snapshot(root) == before


@test("reviver: a candidates list from elsewhere with a damaged folder: still never loaded")
def _():
    root = TMP / "dfF" / "save"
    torn(root, "autosave 1", 100)
    intact(root, "region9", 5000)
    t = [0.0]
    df = TitleDF()
    logs = []
    with Patched(root):
        pin_to(TMP / "dfF", "region9")
        rv = revive.Reviver(logs.append, dfhack=df, launcher=lambda *_: None, clock=lambda: t[0])
        rv.candidates = lambda: (["autosave 1", "region9"], None)
        rv.restore = None
        for _ in range(4):
            rv.tick(); t[0] += 60
    assert loads(df) == ["region9"], loads(df)
    assert any("'autosave 1' is damaged" in x for x in logs), logs


@test("hang guard: DF stops answering while loading: counted in full, the next try takes the next save")
def _():
    t = [0.0]
    df = TitleDF()
    logs = []
    rv = revive.Reviver(logs.append, dfhack=df, launcher=lambda *_: None, clock=lambda: t[0])
    rv.candidates = lambda: (["autosave 3", "autosave 2"], None)
    rv.restore = None
    rv.damaged = lambda f: None
    stamps = {"autosave 3": 100.0, "autosave 2": 50.0}
    rv.save_stamp = lambda f: stamps.get(f)
    for _ in range(4):
        rv.tick(); t[0] += 60
    assert loads(df) == ["autosave 3"], loads(df)
    df.state = "hung"
    for _ in range(int(revive.LOAD_TIMEOUT_S // 60) + 2):
        rv.tick(); t[0] += 60
    assert rv.load_fails.get("autosave 3") == revive.LOAD_FAILS_MAX, rv.load_fails
    assert rv.fail_stamp.get("autosave 3") == 100.0
    assert any("hung" in x and "isn't tried again" in x for x in logs), logs
    df.state = "down"                                       # the hung game closed
    rv.tick(); t[0] += 60
    df.state = "title"
    for _ in range(4):
        rv.tick(); t[0] += 60
    assert loads(df)[-1] == "autosave 2", loads(df)


if __name__ == "__main__":
    finish()
