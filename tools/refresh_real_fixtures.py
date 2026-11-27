"""Copy the six forts' live reports into tests/fixtures/real (F1b), for the
rule-set property tests (tests/test_f10_rule_properties.py). Run it on the PC
each release, then run that test and commit the new fixtures.

    python tools/refresh_real_fixtures.py                     # the six forts' default game folders
    python tools/refresh_real_fixtures.py A="D:\\DF-A" C="E:\\Games\\DF"   # or name them (letter=game folder)
    python tools/refresh_real_fixtures.py --configs C:\\Users\\me\\Documents\\DF-AI C:\\...\\DF-AI-B
                                  # or read each DF-AI folder's config.json (df_launch: the game's exe)
    python tools/refresh_real_fixtures.py --prune             # and remove the fixtures this run did not write

Each fort's last report is <game folder>\\dfhack-config\\ai-overseer\\state.json
(lua/ai-bridge.lua STATE_FILE). It is copied as
<letter>-<world>-<bridge version>-y<year>-<season>.json, after checking it is
a report (JSON with a date and the dwarves); a fort whose file is missing or
unreadable is said and skipped. --dry-run says what it would write.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "real"
REL = Path("dfhack-config") / "ai-overseer" / "state.json"

# fort A's game is the Steam one; B-F each run a copy of their own
DEFAULT_GAMES = {"A": r"D:\SteamLibrary\steamapps\common\Dwarf Fortress",
                 **{x: rf"D:\DF-{x}" for x in "BCDEF"}}


def slug(s) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "_", str(s or "fort")).strip("_").lower() or "fort"


def fixture_name(letter: str, state: dict) -> str:
    fort = state.get("fort") if isinstance(state.get("fort"), dict) else {}
    d = state["date"]
    return (f"{letter.lower()}-{slug(fort.get('world') or fort.get('save_dir'))}-{slug(state.get('bridge_version'))}"
            f"-y{int(d['year'])}-{slug(d.get('season') or 'x')}.json")


def from_config(folder: Path) -> Path | None:
    """The game folder of a DF-AI folder: its config.json's df_launch (the exe), else
    a df_path; None when neither is there."""
    try:
        cfg = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if cfg.get("df_path"):
        return Path(cfg["df_path"])
    if cfg.get("df_launch"):
        return Path(cfg["df_launch"]).parent
    return None


def games(args) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for i, folder in enumerate(args.configs or []):
        g = from_config(Path(folder))
        letter = "ABCDEF"[i] if i < 6 else str(i + 1)
        m = re.search(r"DF-AI-([A-Z])$", str(folder).rstrip("\\/"), re.I)
        letter = m.group(1).upper() if m else letter
        if g is None:
            print(f"{folder}: no df_launch or df_path in its config.json; skipped")
        else:
            out[letter] = g
    for pair in args.games:
        if "=" not in pair:
            sys.exit(f"{pair!r}: expected LETTER=game folder")
        k, v = pair.split("=", 1)
        out[k.strip().upper()] = Path(v.strip().strip('"'))
    if not out:
        out = {k: Path(v) for k, v in DEFAULT_GAMES.items()}
    return out


def read_report(p: Path) -> dict | None:
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"{p}: can't read it ({type(e).__name__}); skipped")
        return None
    d = s.get("date") if isinstance(s, dict) else None
    if not (isinstance(d, dict) and isinstance(d.get("year"), int) and isinstance(d.get("tick"), int)
            and "dwarves" in s):
        print(f"{p}: not a report (no date or dwarves); skipped")
        return None
    return s


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("games", nargs="*", help="LETTER=game folder (default: the six forts' folders)")
    ap.add_argument("--configs", nargs="+", help="DF-AI folders whose config.json names the game")
    ap.add_argument("--out", default=str(OUT), help="the fixtures folder (default tests/fixtures/real)")
    ap.add_argument("--prune", action="store_true", help="remove the fixtures this run did not write")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out)
    written: list[Path] = []
    for letter, game in sorted(games(args).items()):
        src = game / REL
        if not src.is_file():
            print(f"{letter}: no report at {src}; skipped")
            continue
        s = read_report(src)
        if s is None:
            continue
        dest = out / fixture_name(letter, s)
        print(f"{letter}: {src} -> {dest.name}" + (" (dry run)" if args.dry_run else ""))
        if not args.dry_run:
            out.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(dest)
    if args.prune and written:
        for old in sorted(out.glob("*.json")):
            if old not in written:
                print(f"remove {old.name}" + (" (dry run)" if args.dry_run else ""))
                if not args.dry_run:
                    old.unlink()
    print(f"{len(written)} report(s) {'would be ' if args.dry_run else ''}written to {out}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
