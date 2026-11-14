"""Save folders on disk, in real temporary folders (nothing stubbed but the
clock where a test says so): the backups' partial copies (brain/backup.py) and
the reviver's save lookup (brain/revive.py, through dfhack.save_root).

    python tests/test_save_folders.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import make_test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import backup  # noqa: E402
import dfhack  # noqa: E402
import pin  # noqa: E402
import revive  # noqa: E402

TMP = Path(tempfile.mkdtemp())
backup.BACKUP_DIR = TMP / "backups"
backup.STATE = TMP / "backups" / "last.json"
revive.LAST_FORT = pin.LAST_FORT = TMP / "logs" / "last-fort.json"
pin.PIN_FILE = TMP / "logs" / "keeper-pin.json"
dfhack.CONFIG_PATH = TMP / "no-config.json"          # no df_save_dir from a real config.json
APPDATA = TMP / "AppData"
USER = APPDATA / "Bay 12 Games" / "Dwarf Fortress" / "save"
GAME = TMP / "Dwarf Fortress"                         # the game's own folder (portable saves)


def _before():
    shutil.rmtree(backup.BACKUP_DIR, ignore_errors=True)
    shutil.rmtree(APPDATA, ignore_errors=True)
    shutil.rmtree(GAME, ignore_errors=True)
    for f in (revive.LAST_FORT, pin.PIN_FILE):
        f.unlink(missing_ok=True)
    os.environ["APPDATA"] = str(APPDATA)
    backup.SESSION.clear()


test = make_test(before=_before)


def save(root: Path, name: str, age: float, files=("world.sav",)) -> Path:
    """A save folder written `age` seconds ago (the folder and its files)."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    t = time.time() - age
    for f in files:
        (d / f).write_text(f"{name}/{f}")
        os.utime(d / f, (t, t))
    os.utime(d, (t, t))
    return d


def age(p: Path, seconds: float) -> None:
    t = time.time() - seconds
    os.utime(p, (t, t))


def last_fort(save_dir="region2", world="Enxah", site=7):
    revive.LAST_FORT.parent.mkdir(parents=True, exist_ok=True)
    revive.LAST_FORT.write_text(json.dumps({"df_path": str(GAME), "save_dir": save_dir,
                                            "fort": f"{save_dir}#{site}", "world": world}), encoding="utf-8")


def copies(save_dir="region2") -> list[str]:
    d = backup.BACKUP_DIR / save_dir
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


# --- backups: partial copies -----------------------------------------------------------

@test("backup: a copy cut short leaves no partial and no dated copy, and is tried again in an hour")
def _():
    src = save(GAME / "save", "region2", 600, files=("a.dat", "b.dat", "c.dat"))
    real, n = backup._copy_beating, [0]

    def failing(s, d, **kw):
        n[0] += 1
        if n[0] == 2:
            raise OSError("disk full")
        return real(s, d, **kw)
    backup._copy_beating = failing
    now = time.time()
    try:
        line = backup.maybe(GAME / "save", "region2", now=now, force=True)
    finally:
        backup._copy_beating = real
    assert line and "couldn't copy" in line and "again in an hour" in line, line
    assert copies() == [], copies()                                     # nothing half-copied left behind
    assert not backup.due(now + 60) and backup.due(now + backup.RETRY_S + 1)
    line = backup.maybe(GAME / "save", "region2", now=now + backup.RETRY_S + 1)
    assert line and "a copy of the save (region2)" in line, line
    (got,) = copies()
    assert backup.COPY_NAME.match(got) and sorted(p.name for p in (backup.BACKUP_DIR / "region2" / got).iterdir()) \
        == ["a.dat", "b.dat", "c.dat"], got
    assert src.is_dir()


@test("backup: the game saving during the copy (the source newer after it) throws the torn copy away")
def _():
    src = save(GAME / "save", "region2", 600, files=("a.dat", "b.dat"))
    real = backup._copy_beating

    def saving(s, d, **kw):
        out = real(s, d, **kw)
        (src / "a.dat").write_text("written while copied")                # DF writes mid-copy
        return out
    backup._copy_beating = saving
    try:
        line = backup.maybe(GAME / "save", "region2", now=time.time(), force=True)
    finally:
        backup._copy_beating = real
    assert line and "changed while it was copied" in line, line
    assert copies() == [], copies()


@test("backup: a crash's old partial copy is cleared, one under way (written lately) is left; neither counts as a copy")
def _():
    save(GAME / "save", "region2", 600)
    dest = backup.BACKUP_DIR / "region2"
    old_part, new_part = dest / "2026-10-01 0100.partial", dest / "2026-10-02 0100.partial"
    for p in (old_part, new_part):
        p.mkdir(parents=True)
        (p / "world.sav").write_text("half")
    age(old_part, backup.QUIET_S + 60)
    for name in ("2026-09-01 0100", "2026-09-02 0100", "2026-09-03 0100"):     # KEEP finished copies already
        (dest / name).mkdir()
    line = backup.maybe(GAME / "save", "region2", now=time.time(), force=True)
    assert line and "1 kept" in line, line          # (0.105.46, I6) by age: September's are past 5 weeks
    names = copies()
    assert old_part.name not in names and new_part.name in names, names
    finished = [n for n in names if backup.COPY_NAME.match(n)]
    assert len(finished) == 1 and not any(n.startswith("2026-09") for n in finished), finished   # the old ones went


@test("backup: the copy is renamed whole from its .partial name (never seen under its dated name half-done)")
def _():
    save(GAME / "save", "region2", 600, files=("a.dat", "b.dat"))
    seen = []
    real = backup._copy_beating

    def watching(s, d, **kw):
        seen.append(sorted(p.name for p in (backup.BACKUP_DIR / "region2").iterdir()))
        return real(s, d, **kw)
    backup._copy_beating = watching
    try:
        assert backup.maybe(GAME / "save", "region2", now=time.time(), force=True)
    finally:
        backup._copy_beating = real
    assert seen and all(len(x) == 1 and x[0].endswith(".partial") for x in seen), seen
    (got,) = copies()
    assert backup.COPY_NAME.match(got), got


# --- revive: which save to load --------------------------------------------------------------

@test("revive: the newest of the fort's save, DF's autosaves and an AI restore, in DF's user folder; another save never")
def _():
    last_fort("region2")
    save(USER, "region2", 3000)
    save(USER, "autosave 1", 100)
    save(USER, "autosave 2", 5000)
    save(USER, f"{revive.RESTORE_PREFIX} 2026-10-31 0100", 4000)
    save(USER, "region5", 10)                                     # another fort's save, the newest of all
    (USER / "autosave 3").write_text("not a folder")
    save(GAME / "save", "region2", 1)                              # an old portable copy without the autosaves
    assert dfhack.save_root(str(GAME), "region2") == GAME / "save"  # (both hold it: the newer wins)
    shutil.rmtree(GAME / "save")
    assert revive.save_to_load() == "autosave 1"
    folders, world = revive.load_candidates()
    assert folders == ["autosave 1", "region2", f"{revive.RESTORE_PREFIX} 2026-10-31 0100", "autosave 2"], folders
    assert world == "Enxah"
    (USER / "region2" / "world.sav").write_text("saved again")    # a file written in the fort's folder
    assert revive.save_to_load() == "region2" and revive.load_candidates()[0][0] == "region2"


@test("revive: the pinned fort's folder, not last-fort.json's; no last fort and no pin: nothing to load")
def _():
    assert revive.save_to_load() is None and revive.load_candidates() == ([], None)
    save(USER, "region2", 3000)
    save(USER, "region5", 100)
    last_fort("region2", "Enxah", 7)
    assert pin.take(time.time() - 10)["save_dir"] == "region2"
    last_fort("region5", "Other", 3)                               # a daytime run of another fort
    folders, world = revive.load_candidates()
    assert folders == ["region2"] and world == "Enxah", (folders, world)
    assert revive.save_to_load() == "region5"                      # (last-fort.json's, for the plain load)


@test("revive: a save written in the last minutes (the folder or a file in it, autosaves too) is DF saving, not hung")
def _():
    assert revive.save_written_within(180) is False                # no last fort: not saving
    last_fort("region2")
    save(USER, "region2", 3000)
    save(USER, "autosave 1", 2000, files=("a.dat", "b.dat"))
    assert revive.save_written_within(180) is False
    t = time.time() - 30
    os.utime(USER / "autosave 1" / "b.dat", (t, t))
    assert revive.save_written_within(180) is True
    assert revive.save_written_within(10) is False


if __name__ == "__main__":
    finish()
