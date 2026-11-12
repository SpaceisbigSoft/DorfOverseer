"""The Design track's language (D0): one small, checked JSON per fort and era
that the scripts follow at no token cost (review/design/design-track.md §3).

    lang, rejected = check_language(obj, ctx)   # every field checked alone
    store(memory, lang, by, now, era)           # memory.culture["design"]
    apply(profile, history, traits)             # culture._profile_from, last
    layout_style(profile, kind) ... style_fields(profile, kind)

Kept in the save as memory.culture["design"] (the chronicle kind):

    {"mode": "guided", "lang": {...} | None, "by": "rules" | "ai", "era": 3,
     "written": <tick>, "rules_key": "...", "old": [<= 3 compact eras],
     "ask": {"since", "tries", "rejected"}}

At Scripts (the default) nothing here changes anything: current() is None,
apply() leaves the profile alone and style_fields() gives {}. The window
keeps the player's taste: finish and statues stay within one step of what the
sliders give; a language makes a fort its own, it can't make a plain War-hold
gilded. Pure logic, no game access, no tokens.
"""

from __future__ import annotations

import copy
import json
import re

import culture

MODES = ("scripts", "guided", "architect")
HALLS = tuple(culture.HALLS)               # plain rounded pillared + octagonal round cruciform nave
NEW_HALLS = ("octagonal", "round", "cruciform", "nave")
MOTIFS = ("spiral", "ring", "cross", "star", "axe", "hammer", "shield", "tree", "wave", "flame",
          "mountain", "sun", "moon", "eye", "serpent", "key", "none")
FORMS = ("rows", "ring", "cross", "spiral", "star", "wave")
# A motif is drawn in a hall as one of the layout forms (lua/ai-layouts.lua motif_mask).
MOTIF_FORM = {"spiral": "spiral", "ring": "ring", "cross": "cross", "star": "star", "axe": "cross",
              "hammer": "cross", "shield": "ring", "tree": "star", "wave": "wave", "flame": "star",
              "mountain": "rows", "sun": "star", "moon": "ring", "eye": "ring", "serpent": "wave",
              "key": "cross", "none": "rows"}
ARMS = ("corridor", "cross", "ring")
SYMMETRY = ("none", "mirror", "radial")
ASPECTS = ("square", "long", "wide")
ENGRAVE = ("none", "halls", "all")
LANDMARK_KINDS = ("descent", "god_hall", "ziggurat", "chronicle_hall", "great_hall", "tower", "necropolis",
                  "gate_hall", "garden_court")
ADOPTABLE = ("cloister", "cells", "armoury", "ore_piles", "market_gate", "field_hall", "field_kitchens",
             "deep_hall", "wide_ways", "gate_barracks")
TONES = ("plain", "solemn", "martial", "merry", "austere", "mythic")
PATTERNS = ("adjective", "of", "compound", "possessive")   # see masterplan.district_name
STONE_TONES = ("any", "dark", "light", "warm", "cool", "precious")
FURNITURE = ("Bed", "Door", "Table", "Chair", "Cabinet", "Box", "Statue", "Armorstand", "Weaponrack",
             "Coffin", "Bookcase")
LEVEL_KINDS = ("bedrooms", "suites", "jail", "dining", "storage", "workshops", "temple", "memorial", "hospital",
               "barracks", "tombs", "tavern", "library", "archery", "garden", "farms")
# The Rules tab's level switch an adopted custom needs (planner_core.OPTIONAL_LEVELS).
CUSTOM_LEVEL = {"cloister": "temple", "cells": "temple", "armoury": "barracks", "gate_barracks": "barracks",
                "market_gate": "tavern"}
FIELDS = ("name", "story", "motif", "hall", "scale", "aspect", "arms", "symmetry", "finish", "materials",
          "customs", "emphasis", "naming", "landmarks", "era", "changes")

LANG_MAX_BYTES = 1500
SCALE = (80, 150)
EMPHASIS_SCALE = 20
MAX_OLD = 3
MAX_CUSTOMS = 3
MAX_EMPHASIS = 3
MAX_LANDMARKS = 4
MAX_BY_KIND = 6
MAX_WORDS = 12
WORD_MAX = 16
NAME_MAX = 40
STORY_MAX = 200
CHANGES_MAX = 160
WISH_WORDS_MAX = 60
MAX_LINES = 6


# --- small helpers -------------------------------------------------------------------

def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _text(v, n: int) -> str:
    """Plain words only, as culture.check_style cleans a guide: it's shown in the game."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w .,;:'()!?-]", "", v)).strip()[:n].strip()


def _name(v, n: int = NAME_MAX) -> str:
    """Letters, spaces, apostrophes and hyphens (it may end up in a zone name)."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z' -]", "", v)).strip()[:n].strip()


def _word(v) -> str:
    return re.sub(r"[^A-Za-z']", "", v)[:WORD_MAX]


def _bytes(lang: dict) -> int:
    return len(json.dumps(lang, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _ctx_set(ctx, key) -> set:
    v = (ctx or {}).get(key) if isinstance(ctx, dict) else None
    return {x for x in v if isinstance(x, str)} if isinstance(v, (set, list, tuple, frozenset, dict)) else set()


# --- checking a language ---------------------------------------------------------------

def check_language(obj, ctx: dict | None = None) -> tuple[dict, list[str]]:
    """A language (the AI's, or the rules') -> (the fields that passed, reasons).
    ctx: {"stones": tokens with 20+ boulders on hand, "names": names the brief
    showed (a god, a beast, a dead hero), "kinds": level kinds (default
    LEVEL_KINDS)}. A bad field is dropped with its reason; the rest are kept.
    Over LANG_MAX_BYTES, the landmark wishes go first, then the naming words."""
    out: dict = {}
    rej: list[str] = []
    if not isinstance(obj, dict):
        return out, ["design: not an object"]
    stones = _ctx_set(ctx, "stones")
    names = {n.lower(): n for n in _ctx_set(ctx, "names")}
    kinds = _ctx_set(ctx, "kinds") or set(LEVEL_KINDS)

    def bad(k, why):
        rej.append(f"design: {k} {why}")

    for k, v in obj.items():
        if k not in FIELDS:
            bad(k, "is not a field of the language")
        elif k == "name":
            t = _name(v) if isinstance(v, str) else ""
            if t:
                out[k] = t
            else:
                bad(k, "must be a name of letters")
        elif k in ("story", "changes"):
            t = _text(v, STORY_MAX if k == "story" else CHANGES_MAX) if isinstance(v, str) else ""
            if t:
                out[k] = t
            else:
                bad(k, "must be plain text")
        elif k in ("motif", "hall", "aspect", "arms", "symmetry"):
            allowed = {"motif": MOTIFS, "hall": HALLS, "aspect": ASPECTS, "arms": ARMS, "symmetry": SYMMETRY}[k]
            if v in allowed:
                out[k] = v
            else:
                bad(k, f"{v!r} is not one of {', '.join(allowed)}")
        elif k == "scale":
            if _int(v) and SCALE[0] <= v <= SCALE[1]:
                out[k] = v
            else:
                bad(k, f"{v!r} must be a whole number {SCALE[0]}-{SCALE[1]}")
        elif k == "era":
            if _int(v) and 0 <= v <= 999:
                out[k] = v
            else:
                bad(k, f"{v!r} must be a whole number")
        elif k == "finish":
            f = _finish(v, rej)
            if f:
                out[k] = f
        elif k == "materials":
            m = _materials(v, stones, rej)
            if m:
                out[k] = m
        elif k in ("customs", "emphasis"):
            allowed, cap = (ADOPTABLE, MAX_CUSTOMS) if k == "customs" else (kinds, MAX_EMPHASIS)
            if not isinstance(v, list):
                bad(k, "must be a list")
                continue
            got = []
            for x in v:
                if x not in allowed:
                    bad(k, f"{x!r} is not allowed")
                elif x in got:
                    continue
                elif len(got) >= cap:
                    bad(k, f"{x!r}: {cap} at most")
                else:
                    got.append(x)
            if got:
                out[k] = got
        elif k == "naming":
            n = _naming(v, rej)
            if n:
                out[k] = n
        elif k == "landmarks":
            w = _landmarks(v, names, rej)
            if w:
                out[k] = w
    # the size cap: the wishes first, then the naming words, then the story
    while _bytes(out) > LANG_MAX_BYTES and out.get("landmarks"):
        out["landmarks"].pop()
        if not out["landmarks"]:
            del out["landmarks"]
        rej.append("design: landmarks cut (the language is over its size)")
    while _bytes(out) > LANG_MAX_BYTES and (out.get("naming") or {}).get("words"):
        out["naming"]["words"].pop()
        if not out["naming"]["words"]:
            del out["naming"]["words"]
        rej.append("design: naming words cut (the language is over its size)")
    for k in ("story", "changes"):
        if _bytes(out) > LANG_MAX_BYTES and k in out:
            del out[k]
            rej.append(f"design: {k} cut (the language is over its size)")
    return out, rej


def _finish(v, rej) -> dict:
    out = {}
    if not isinstance(v, dict):
        rej.append("design: finish must be an object")
        return out
    for k, x in v.items():
        if k == "smooth" and _int(x) and 0 <= x <= 3 or k == "statues" and _int(x) and 0 <= x <= 4:
            out[k] = x
        elif k == "engrave" and x in ENGRAVE:
            out[k] = x
        else:
            rej.append(f"design: finish.{k}={x!r} is not allowed")
    return out


def _materials(v, stones, rej) -> dict:
    out: dict = {}
    if not isinstance(v, dict):
        rej.append("design: materials must be an object")
        return out
    for k, x in v.items():
        if k == "palette" and x in culture.PALETTES:
            out[k] = x
        elif k == "blocks" and isinstance(x, bool):
            out[k] = x
        elif k == "signature" and (x is None or x == "none"):
            out[k] = None
        elif k == "signature" and isinstance(x, str) and x in stones:
            out[k] = x
        elif k == "signature":
            rej.append(f"design: materials.signature {x!r} is not a stone with 20 or more boulders on hand")
        elif k == "by_kind" and isinstance(x, dict):
            bk = {}
            for fk, tone in x.items():
                if fk not in FURNITURE or tone not in STONE_TONES:
                    rej.append(f"design: materials.by_kind {fk!r}={tone!r} is not allowed")
                elif len(bk) >= MAX_BY_KIND:
                    rej.append(f"design: materials.by_kind {fk!r}: {MAX_BY_KIND} at most")
                else:
                    bk[fk] = tone
            if bk:
                out[k] = bk
        else:
            rej.append(f"design: materials.{k}={x!r} is not allowed")
    return out


def _naming(v, rej) -> dict:
    out: dict = {}
    if not isinstance(v, dict):
        rej.append("design: naming must be an object")
        return out
    for k, x in v.items():
        if k == "tone" and x in TONES or k == "pattern" and x in PATTERNS:
            out[k] = x
        elif k == "words" and isinstance(x, list):
            ws = []
            for w in x:
                c = _word(w) if isinstance(w, str) else ""
                if not c:
                    rej.append(f"design: naming word {w!r} must be letters")
                elif len(ws) >= MAX_WORDS:
                    rej.append(f"design: naming words: {MAX_WORDS} at most")
                    break
                elif c not in ws:
                    ws.append(c[:1].upper() + c[1:])
            if ws:
                out[k] = ws
        else:
            rej.append(f"design: naming.{k}={x!r} is not allowed")
    return out


def _landmarks(v, names, rej) -> list:
    out = []
    if not isinstance(v, list):
        rej.append("design: landmarks must be a list")
        return out
    for w in v:
        if not isinstance(w, dict) or w.get("kind") not in LANDMARK_KINDS:
            rej.append(f"design: landmark {w!r}: kind must be one of {', '.join(LANDMARK_KINDS)}")
            continue
        extra = set(w) - {"kind", "for", "words"}
        if extra:
            rej.append(f"design: landmark {w['kind']}: {', '.join(sorted(extra))} not allowed")
            continue
        wish = {"kind": w["kind"]}
        f = w.get("for")
        if f not in (None, ""):
            if not isinstance(f, str) or f.strip().lower() not in names:
                rej.append(f"design: landmark {w['kind']}: {f!r} is not a name from the brief")
                continue
            wish["for"] = names[f.strip().lower()]
        if isinstance(w.get("words"), str) and _text(w["words"], WISH_WORDS_MAX):
            wish["words"] = _text(w["words"], WISH_WORDS_MAX)
        if len(out) >= MAX_LANDMARKS:
            rej.append(f"design: landmarks: {MAX_LANDMARKS} at most")
            break
        out.append(wish)
    return out


# --- the mode, the stored language ------------------------------------------------------

def mode(state) -> str:
    st = state.get("settings") if isinstance(state, dict) else None
    m = st.get("design") if isinstance(st, dict) else None
    return m if m in MODES else "scripts"


def _rec(history) -> dict:
    d = history.get("design") if isinstance(history, dict) else None
    return d if isinstance(d, dict) else {}


def current(history) -> dict | None:
    """The language the scripts follow, or None (Scripts, or none written yet)."""
    d = _rec(history)
    if d.get("mode") not in ("guided", "architect"):
        return None
    lang = d.get("lang")
    return lang if isinstance(lang, dict) and lang else None


def store(memory, lang: dict, by: str, now, era) -> None:
    """Keep a checked language in memory.culture["design"]. The one it
    replaces, from another era, goes to `old` in short (3 kept)."""
    if not isinstance(memory.culture, dict):
        memory.culture = culture.new_history()
    d = memory.culture.get("design")
    if not isinstance(d, dict):
        d = memory.culture["design"] = {"mode": "scripts", "lang": None}
    prev = d.get("lang")
    if isinstance(prev, dict) and prev and d.get("era") != era:
        old = [o for o in d.get("old") or [] if isinstance(o, dict)]
        old.append({"era": d.get("era"), "name": prev.get("name"), "hall": prev.get("hall"),
                    "motif": prev.get("motif"), "arms": prev.get("arms")})
        d["old"] = old[-MAX_OLD:]
    d["lang"] = copy.deepcopy(lang)
    d["by"] = "ai" if by == "ai" else "rules"
    d["era"] = era
    d["written"] = now


def _change_names(changes) -> set:
    if isinstance(changes, str):
        return {w for w in re.findall(r"[a-z_]+(?:\.[a-z_]+)?", changes.lower())
                if w.split(".")[0] in FIELDS}
    if isinstance(changes, (list, tuple, set, frozenset)):
        return {c for c in changes if isinstance(c, str) and c.split(".")[0] in FIELDS}
    return set()


def revise(old: dict | None, new: dict | None, changes) -> dict:
    """An era's revision: the old language with only the fields named in
    `changes` (a list of field names, or words naming them; "finish.smooth"
    for one part) taken from the new one (or dropped when the new one has
    none). era and changes always come from the new one."""
    out = copy.deepcopy(old) if isinstance(old, dict) else {}
    new = new if isinstance(new, dict) else {}
    for c in sorted(_change_names(changes)):
        top, _, sub = c.partition(".")
        if top in ("era", "changes"):
            continue
        if sub:
            src = new.get(top) if isinstance(new.get(top), dict) else {}
            dst = out.get(top) if isinstance(out.get(top), dict) else {}
            if sub in src:
                dst[sub] = copy.deepcopy(src[sub])
            else:
                dst.pop(sub, None)
            if dst:
                out[top] = dst
            else:
                out.pop(top, None)
        elif top in new:
            out[top] = copy.deepcopy(new[top])
        else:
            out.pop(top, None)
    for k in ("era", "changes"):
        if k in new:
            out[k] = new[k]
    return out


# --- the slider window and the profile ----------------------------------------------------

def window(lang: dict, profile: dict, traits: dict | None = None) -> dict:
    """The language within the player's taste: finish and statues within one
    step of what the sliders give, scale 80-150, and precious stone only for
    a fort whose sliders already lean that way (Grandeur or Craftsmanship 50+,
    or the profile's own palette). Room size is the sliders' alone."""
    out = copy.deepcopy(lang) if isinstance(lang, dict) else {}
    t = traits or {}
    f = out.get("finish") if isinstance(out.get("finish"), dict) else {}
    base_s = int(profile.get("smooth", 0) or 0)
    base_st = int(profile.get("statues", 0) or 0)
    if f:
        smooth = f.get("smooth")
        if smooth is None and f.get("engrave") in ("halls", "all"):
            smooth = 3
        elif smooth is None and f.get("engrave") == "none":
            smooth = min(base_s, 2)
        if smooth is not None:
            f["smooth"] = _clamp(int(smooth), max(0, base_s - 1), min(3, base_s + 1))
        if f.get("statues") is not None:
            f["statues"] = _clamp(int(f["statues"]), max(0, base_st - 1), min(4, base_st + 1))
        out["finish"] = f
    if "scale" in out:
        out["scale"] = _clamp(int(out["scale"]), *SCALE)
    m = out.get("materials") if isinstance(out.get("materials"), dict) else None
    if m and m.get("palette") == "precious" and profile.get("palette") != "precious" \
            and max(float(t.get("grandeur", 0) or 0), float(t.get("craftsmanship", 0) or 0)) < 50:
        m.pop("palette")
    return out


def apply(profile: dict, history, traits: dict | None = None) -> None:
    """The language over a profile, in place (culture._profile_from, last).
    No language (Scripts, or none yet): nothing changes."""
    lang = current(history)
    if lang is None:
        return
    w = window(lang, profile, traits)
    f = w.get("finish") or {}
    m = w.get("materials") or {}
    arms = w.get("arms", "corridor")
    if w.get("symmetry") == "radial" and arms == "corridor":
        arms = "cross"                       # radial: four equal arms
    profile["design"] = {"name": w.get("name"), "hall": w.get("hall", profile.get("hall")),
                         "scale": w.get("scale", 100), "aspect": w.get("aspect"), "arms": arms,
                         "motif": MOTIF_FORM.get(w.get("motif"), "rows"), "symbol": w.get("motif"),
                         "symmetry": w.get("symmetry", "none"), "emphasis": list(w.get("emphasis") or []),
                         "by_kind": dict(m.get("by_kind") or {}), "signature": m.get("signature"),
                         "blocks": bool(m.get("blocks", False))}
    if w.get("hall") in HALLS:
        profile["hall"] = w["hall"]
    if "smooth" in f:
        profile["smooth"] = f["smooth"]
    if "statues" in f:
        profile["statues"] = f["statues"]
    if m.get("palette") in culture.PALETTES:
        profile["palette"] = m["palette"]


def style_fields(profile: dict, kind: str | None = None) -> dict:
    """The new style keys for one level (d0-spec §1.4), each only when it isn't
    its default, so a level at Scripts carries none. A kind in the language's
    emphasis is grand: +20 scale (150 at most) and grand: true."""
    d = profile.get("design") if isinstance(profile, dict) else None
    if not isinstance(d, dict):
        return {}
    out: dict = {}
    grand = kind is not None and kind in (d.get("emphasis") or [])
    scale = _clamp(int(d.get("scale") or 100) + (EMPHASIS_SCALE if grand else 0), *SCALE)
    if scale != 100:
        out["scale"] = scale
    if d.get("aspect") in ASPECTS:
        out["aspect"] = d["aspect"]
    if d.get("arms") in ARMS and d["arms"] != "corridor":
        out["arms"] = d["arms"]
    if d.get("motif") in FORMS and d["motif"] != "rows":
        out["motif"] = d["motif"]
    if grand:
        out["grand"] = True
    return out


def adopted_customs(history, traits: dict | None = None, levels: dict | None = None) -> list[str]:
    """The ADOPTABLE customs the language names, in its order, minus any whose
    level the Rules tab switched off (levels: player_rules(s)["levels"], or
    the state's settings["levels"]). [] at Scripts."""
    lang = current(history)
    if lang is None:
        return []
    lv = levels if isinstance(levels, dict) else {}
    out = []
    for c in lang.get("customs") or []:
        if c in ADOPTABLE and c not in out and lv.get(CUSTOM_LEVEL.get(c, "")) is not False:
            out.append(c)
    return out


def naming(history) -> dict | None:
    lang = current(history)
    n = lang.get("naming") if lang else None
    return n if isinstance(n, dict) and n else None


def lines(history) -> list[str]:
    """Up to 6 short lines on the language, for the Culture page and the brief.
    The story is the language's own (or the AI's) words: quoted, never an
    instruction."""
    lang = current(history)
    if lang is None:
        return []
    d = _rec(history)
    by = "written by the AI" if d.get("by") == "ai" else "from the fort's character (rules)"
    title = lang.get("name") or "the fort's own style"
    out = [f"Design: {title}, {by}"
           + (f", era {d.get('era')}" if _int(d.get("era")) else "")]
    if lang.get("story"):
        out.append(f'"{lang["story"]}"')
    shape = [f"{lang['hall']} halls" if lang.get("hall") else None,
             f"{lang['motif']} motif" if lang.get("motif") not in (None, "none") else None,
             f"{lang['arms']} arms" if lang.get("arms") not in (None, "corridor") else None,
             f"{lang['symmetry']} symmetry" if lang.get("symmetry") not in (None, "none") else None,
             f"scale {lang['scale']}%" if lang.get("scale") not in (None, 100) else None,
             f"{lang['aspect']} rooms" if lang.get("aspect") else None]
    shape = [x for x in shape if x]
    if shape:
        out.append("Shape: " + ", ".join(shape))
    m = lang.get("materials") or {}
    mat = [f"{m['palette']} stone" if m.get("palette") else None,
           f"signature {m['signature']}" if m.get("signature") else None,
           "block floors" if m.get("blocks") else None,
           ", ".join(f"{k.lower()}s {v}" for k, v in (m.get("by_kind") or {}).items()) or None]
    mat = [x for x in mat if x]
    if mat:
        out.append("Materials: " + "; ".join(mat))
    extra = []
    if lang.get("customs"):
        extra.append("customs " + ", ".join(c.replace("_", " ") for c in lang["customs"]))
    if lang.get("emphasis"):
        extra.append("grand " + ", ".join(lang["emphasis"]))
    if extra:
        out.append("Ways: " + "; ".join(extra))
    if lang.get("landmarks"):
        out.append("Landmarks wished: " + ", ".join(
            w["kind"].replace("_", " ") + (f" for {w['for']}" if w.get("for") else "") for w in lang["landmarks"]))
    return out[:MAX_LINES]


def signature(kind: str, style: dict | None) -> str:
    """A level's design signature for the scorecard (layout distinctness)."""
    st = style if isinstance(style, dict) else {}
    scale = st.get("scale") if _int(st.get("scale")) else 100
    return (f"{kind}:{st.get('hall') or 'plain'}:{st.get('arms') or 'corridor'}:{scale // 10}:"
            f"{st.get('motif') or 'rows'}:{st.get('orient') if _int(st.get('orient')) else 0}")
