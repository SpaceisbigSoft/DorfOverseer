"""(0.105.42) The reviver orders saves by world.sav's time, not the newest file in the folder."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"))
from harness import finish, test  # noqa: E402

import backup  # noqa: E402


@test("the newest save by world.sav's time, not by a stray newer file in an older save")
def _():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        old, new = root / "autosave 1", root / "autosave 3"
        for f in (old, new):
            f.mkdir()
            (f / "world.sav").write_text("x")
        t = time.time()
        os.utime(old / "world.sav", (t - 3000, t - 3000))
        os.utime(new / "world.sav", (t - 100, t - 100))
        stray = old / "events-dfhack.log"          # a newer stray file in the older save
        stray.write_text("x")
        os.utime(stray, (t, t))
        assert backup.save_mtime(new) > backup.save_mtime(old)
        assert backup.newest_folder(root, "region4").name == "autosave 3"
        assert backup.folder_mtime(old) > backup.folder_mtime(new)   # the old way picked autosave 1


@test("no world.sav: the folder's own time")
def _():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x"
        p.mkdir()
        (p / "a").write_text("x")
        assert backup.save_mtime(p) == backup.folder_mtime(p)


if __name__ == "__main__":
    finish()
