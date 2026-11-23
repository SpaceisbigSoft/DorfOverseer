"""(r14 k1) A save folder torn when the PC went down: never loaded or copied.

On 22 Nov the PC lost power at 05:47 while fort E's game wrote its
autosave: "autosave 3"'s world.sav kept its size (54 MB) but its last 50.8 MB
were zeros (Windows' zero-filled tail of a file never flushed). It was the
newest save by world.sav's time, so the keeper loaded it twice, and DF hung
on the load. Every intact world.sav on the six forts ends in no zero byte
at all (it is compressed data).

A save folder is DAMAGED when its world.sav is empty, or ends in
a long run of zero bytes: at least ZERO_TAIL_MIN (1 MiB), or more than
ZERO_TAIL_SHARE of the file once the run is at least ZERO_TAIL_FLOOR (4 KiB,
one NTFS cluster: an unflushed tail is whole clusters, so a few zero bytes
a real save might end with never count). (r14 k1 fixes) A folder that holds
DF's save files (world.dat, unit-*.dat) but no world.sav is not damaged but
not loadable either ("has no world.sav"): skipped, never "move it".

Only the file's tail is read: the last TAIL_READ bytes, and further back in
chunks only while they are all zeros (to say how much was lost). Results are
kept per file size and time, so a folder is read once until DF writes it
again. Nothing is ever moved, deleted or written: the saves are the player's.

    why = save_check.damage(folder)     # None, or "its world.sav ends in 48.5 MB of zeros"
"""

from __future__ import annotations

from pathlib import Path

TAIL_READ = 1 << 20          # the tail read first (1 MiB)
WALK_CHUNK = 4 << 20         # then back in chunks this big while all zeros
ZERO_TAIL_MIN = 1 << 20      # a zero tail this long is damage, whatever the size
ZERO_TAIL_FLOOR = 4096       # ... and one this long is, when over ZERO_TAIL_SHARE of the file
ZERO_TAIL_SHARE = 0.10

_CACHE: dict = {}            # str(path) -> ((size, mtime_ns), why)


def zero_tail(path: Path, opener=open) -> tuple[int, int]:
    """(zero bytes at the end of the file, its size). Reads the last
    TAIL_READ bytes, then back in WALK_CHUNK chunks only while all zero.
    Raises OSError."""
    with opener(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        pos, zeros, chunk = size, 0, TAIL_READ
        while pos > 0:
            n = min(chunk, pos)
            f.seek(pos - n)
            data = f.read(n)
            if len(data) != n:
                raise OSError(f"short read of {path}")
            stripped = data.rstrip(b"\0")
            zeros += n - len(stripped)
            if stripped:
                break
            pos -= n
            chunk = WALK_CHUNK
        return zeros, size


def mb(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 100_000 else f"{n / 1e3:.0f} KB"


def judge(zeros: int, size: int) -> str | None:
    """Why a world.sav of `size` bytes ending in `zeros` zero bytes is damaged, or None."""
    if size <= 0:
        return "its world.sav is empty"
    if zeros >= ZERO_TAIL_MIN or (zeros >= ZERO_TAIL_FLOOR and zeros > ZERO_TAIL_SHARE * size):
        whole = " (all of it)" if zeros >= size else f" of its {mb(size)}"
        return f"its world.sav ends in {mb(zeros)} of zeros{whole}"
    return None


def damage(folder: Path, opener=open) -> str | None:
    """Why the save folder `folder` can't be loaded (a torn world.sav), or
    None when it looks whole, isn't a folder, or can't be read (unknown:
    never skipped for that). Never raises."""
    try:
        folder = Path(folder)
        if not folder.is_dir():
            return None
        sav = folder / "world.sav"
        try:
            st = sav.stat()
        except FileNotFoundError:
            # (r14 k1 fixes) not torn: a folder that looks like a save (DF's
            # world.dat or unit files) but has no world.sav can't be loaded;
            # any other folder isn't judged
            return NO_SAV if looks_like_save(folder) else None
        key = (st.st_size, st.st_mtime_ns)
        hit = _CACHE.get(str(sav))
        if hit and hit[0] == key:
            return hit[1]
        if st.st_size == 0:
            why = "its world.sav is empty"
        else:
            why = judge(*zero_tail(sav, opener))
        _CACHE[str(sav)] = (key, why)
        return why
    except (OSError, ValueError):
        return None


NO_SAV = "has no world.sav"


def looks_like_save(folder: Path) -> bool:
    """A folder holding DF's save files (world.dat, unit-*.dat)."""
    try:
        return (folder / "world.dat").is_file() or any(True for _ in folder.glob("unit-*.dat"))
    except OSError:
        return False


def no_sav(why: str | None) -> bool:
    """(r14 k1 fixes) The reason is a missing world.sav (not damage: nothing to move)."""
    return why == NO_SAV


def torn(why: str | None) -> bool:
    """A damage reason that a sudden shutdown leaves (the zero tail)."""
    return bool(why) and "zeros" in why
