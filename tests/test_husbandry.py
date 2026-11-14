"""(0.105.47) The herd by Husbandry: lua/ai-herd.lua in a fake fort (the
herd by kind, wool grown and milk ready now, breeders kept and let go,
caged wild animals tamed, hunting training, autobutcher's targets), the
bridge's wiring, and the brain (brain/planner_husbandry.py, the war
animals by Militarism, the dairy rule) slider by slider.

Why: the 14 Nov scorecard: the Garden fort (Husbandry +80) won no
Husbandry line (tame animals A 58, B 19, C 45, D 12, E 14, F 30; pastures
A 9, B 5, C 8, D 2, E 3, F 7; the War-hold most).

    python tests/test_husbandry.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, Proposal, plan  # noqa: E402
import planner_husbandry as PH  # noqa: E402
from planner_military import _war_animal_rule  # noqa: E402
from planner_farms import _dairy_rule  # noqa: E402
from digest import normalize, SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"

FAKE = r"""
local src = ...
local W = {units = {}, races = {}, site = {}, training = {}, zones = {}, cmds = {}}
local env = setmetatable({}, {__index = _G})
setmetatable(W.training, {__index = {insert = function(self, _, a) rawset(self, #self + 1, a) end}})
function W.race(id, name, flags, extra)
    local c = {flags = flags or {}, misc = {milkable = 0, grazer = 0}, shearable_tissue_layer = {}}
    for k, v in pairs(extra or {}) do c[k] = v end
    W.races[id] = {creature_id = name, caste = {[0] = c}}
end
function W.unit(t)
    t.caste = 0
    t.flags1 = t.flags1 or {caged = false, merchant = false}
    t.flags2 = t.flags2 or {slaughter = false}
    t.name = t.name or {nickname = '', has_name = false}
    t.relationship_ids = t.relationship_ids or {PetOwner = -1}
    t.profession = t.profession or 0
    t.birth_year = t.birth_year or 250
    t.birth_time = t.birth_time or 0
    t.appearance = t.appearance or {bp_modifiers = {}}
    t.status = t.status or {misc_traits = {}, labors = {}}
    table.insert(W.units, t)
    return t
end
local function f(key) return function(u) return u[key] == true end end
env.df = {
    global = {plotinfo = {training = {training_assignments = W.training}, civ_id = 10},
              world = {units = {active = W.units}}},
    creature_raw = {find = function(id) return W.races[id] end},
    profession = {[0] = 'STANDARD', [98] = 'TRAINED_WAR', [99] = 'TRAINED_HUNTER'},
    misc_trait_type = {MilkCounter = 7},
    general_ref_type = {BUILDING_CIVZONE_ASSIGNED = 'zone'},
    building = {find = function(id) return W.zones[id] end},
    training_assignment = {new = function() return {flags = {}} end},
    unit_labor = {ANIMALTRAIN = 'ANIMALTRAIN'},
}
env.dfhack = {
    units = {
        isAlive = function(u) return not u.dead end,
        isAnimal = function(u) return not u.citizen end,
        isCitizen = f('citizen'),
        isFortControlled = function(u) return u.tame == true end,
        isTame = f('tame'), isOwnCiv = function(u) return u.tame == true end,
        isPet = f('pet'),
        isWar = function(u) return u.profession == 98 end,
        isHunter = function(u) return u.profession == 99 end,
        isAdult = function(u) return not u.kid end,
        isFemale = function(u) return u.sex == 'f' end,
        isMale = function(u) return u.sex == 'm' end,
        isGrazer = function(u) return W.races[u.race].caste[0].flags.GRAZER == true end,
        isGreatDanger = f('great'),
        getGeneralRef = function(u) if u.zone then return {building_id = u.zone} end end,
        setNickname = function(u, n) u.name.nickname = n end,
        getReadableName = function(u) return u.label or ('animal ' .. u.id) end,
        getCitizens = function() return W.citizens or {} end,
    },
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
    run_command_silent = function(...)
        table.insert(W.cmds, table.concat({...}, ' '))
        return '', 0
    end,
}
env.reqscript = function(name)
    if name == 'ai-society' then
        return {visiting_animal = function(u) return u.visitor == true end,
                grazer_tiles = function(u) return u.grass or 10 end}
    end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-herd', 't', env))()
return env, W
"""

COW, HEN, DOG, BEAR, GOBLIN = 1, 2, 3, 4, 5


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-herd.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        keys = list(v.keys())
    except AttributeError:
        return v
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


def farm(lua, w):
    """Cows (grazers, milk, wool layer), hens (eggs), dogs (hunting/war),
    a pet, a war dog, a caged bear to tame, a caged goblin (no animal to
    tame), a visitor's horse."""
    wool = T(lua, [{"length": 50, "bp_modifiers_idx": [0]}])
    w.race(COW, "COW", T(lua, {"GRAZER": True, "MILKABLE": True}), T(lua, {"shearable_tissue_layer": wool}))
    w.race(HEN, "HEN", T(lua, {"LAYS_EGGS": True}))
    w.race(DOG, "DOG", T(lua, {"TRAINABLE_HUNTING": True, "TRAINABLE_WAR": True, "PET": True}))
    w.race(BEAR, "BEAR_GRIZZLY", T(lua, {"TRAINABLE_WAR": True, "PET_EXOTIC": True}))
    w.race(GOBLIN, "GOBLIN", T(lua, {"CAN_LEARN": True, "CAN_SPEAK": True}))
    U = lambda **kw: w.unit(T(lua, kw))  # noqa: E731
    # cows: 3 females (one with wool grown, one milked lately), 1 male, a calf; one in the AI pasture
    U(id=1, race=COW, tame=True, sex="f", appearance={"bp_modifiers": {0: 60}}, zone=500, grass=40)
    U(id=2, race=COW, tame=True, sex="f", appearance={"bp_modifiers": {0: 10}}, grass=40,
      status={"misc_traits": [{"id": 7, "value": 300}], "labors": {}})
    U(id=3, race=COW, tame=True, sex="f", birth_year=260, grass=40)
    U(id=4, race=COW, tame=True, sex="m", grass=40)
    U(id=5, race=COW, tame=True, sex="f", kid=True, grass=40)
    # hens: 2 females, 1 male (marked for slaughter)
    U(id=10, race=HEN, tame=True, sex="f")
    U(id=11, race=HEN, tame=True, sex="f")
    U(id=12, race=HEN, tame=True, sex="m", flags2={"slaughter": True})
    # dogs: a pet, a war dog, two plain adults
    U(id=20, race=DOG, tame=True, sex="m", pet=True)
    U(id=21, race=DOG, tame=True, sex="m", profession=98)
    U(id=22, race=DOG, tame=True, sex="f")
    U(id=23, race=DOG, tame=True, sex="m")
    # caged: a bear to tame, a goblin (a prisoner), a great beast
    U(id=30, race=BEAR, sex="m", flags1={"caged": True, "merchant": False})
    U(id=31, race=GOBLIN, sex="m", flags1={"caged": True, "merchant": False})
    U(id=32, race=BEAR, sex="f", great=True, flags1={"caged": True, "merchant": False})
    # a merchant's cow: not the fort's
    U(id=40, race=COW, tame=True, sex="m", visitor=True)
    w.zones[500] = T(lua, {"name": "AI pasture"})


# --- 1. the module ----------------------------------------------------------------------------

@test("report: the herd by kind, wool grown and milk ready now, grass need, tameable, protected and marked")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    farm(lua, w)
    r = py(env.report())
    assert r["tame"] == 12, r["tame"]              # 5 cows (a calf), 3 hens, 4 dogs; not the merchant's cow
    kinds = {k["name"]: k for k in r["kinds"]}
    assert kinds["COW"]["f"] == 3 and kinds["COW"]["m"] == 1 and kinds["COW"]["kids"] == 1
    assert r["wool_now"] == 1 and r["shearable"] == 5          # one cow's wool at its shear length
    assert r["milk_now"] == 2 and r["milkable"] == 3           # one milked lately, the calf no adult
    assert r["egg_layers"] == 2 and r["marked"] == 1
    assert r["pets"] == 1 and r["war"] == 1
    assert r["pairs"] == 3 and r["breeding_pairs"] == 2        # cows and hens breed; dogs are no herd kind
    assert r["grazing_need"] == 200                            # 5 cows x 40: the AI pasture's and the loose
    assert r["tameable"] == 1 and r["tameable_kinds"][0]["name"] == "BEAR_GRIZZLY"
    assert r["hunt_candidates"] == 2                            # the plain adult dogs (no pet, no war dog)


@test("keep_breeders: a male and n females a kind, the youngest first, unmarked; f=0 lets them go; a dry run changes nothing")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    farm(lua, w)
    dry = py(env.keep_breeders(2, True))
    assert dry["ok"] and dry["kept"] == 6 and dry["kinds"] == 2
    assert all(py(u.name.nickname) == "" for u in w.units.values())
    r = py(env.keep_breeders(2, False))
    nick = {int(u.id): u.name.nickname for u in w.units.values()}
    assert r["kept"] == 6 and r["unmarked"] == 1, r
    assert nick[3] == "Breeder" and nick[4] == "Breeder" and nick[12] == "Breeder"   # the youngest cow first
    assert nick[5] == "" and nick[20] == "" and nick[22] == ""                        # calf, pet, dogs left
    assert w.units[12].flags2.slaughter is False
    again = py(env.keep_breeders(2, False))
    assert again["kept"] == 6 and not again.get("named")
    out = py(env.keep_breeders(0, False))
    assert out["released"] == 6 and all(u.name.nickname == "" for u in w.units.values())


@test("tame: a training assignment (any trainer, no war or hunting flag) for the caged bear only; counted in the save")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    farm(lua, w)
    assert py(env.tame(2, True))["assigned"] == 1 and len(w.training) == 0
    r = py(env.tame(2, False))
    assert r["assigned"] == 1 and len(w.training) == 1
    a = w.training[1]
    assert a.animal_id == 30 and a.flags.any_trainer is True and not a.flags.train_war and not a.flags.train_hunt
    assert py(env.tame(2, False))["rejected"] is True          # nothing else to tame (the goblin, the great beast)
    assert py(env.report())["tamed"] == 1


@test("train_hunt: plain adult dogs get hunting training; breeders, pets, the war dog left")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    farm(lua, w)
    r = py(env.train_hunt(4, False))
    assert r["assigned"] == 2 and sorted(int(a.animal_id) for a in w.training.values()) == [22, 23]
    assert all(a.flags.train_hunt is True for a in w.training.values())


@test("set_targets: autobutcher target for all kinds and new ones, kept in the save; bad numbers refused")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    assert py(env.set_targets(T(lua, {"fk": 1, "mk": 1, "fa": 3, "ma": 1}), True))["command"] == \
        "autobutcher target 1 1 3 1 all"
    assert len(w.cmds) == 0
    r = py(env.set_targets(T(lua, {"fk": 0, "mk": 0, "fa": 2, "ma": 1}), False))
    assert r["ok"] and list(w.cmds.values()) == ["autobutcher target 0 0 2 1 all", "autobutcher target 0 0 2 1 new"]
    assert py(env.report())["targets"] == {"fk": 0, "mk": 0, "fa": 2, "ma": 1}
    assert py(env.set_targets(T(lua, {"fk": -1, "mk": 0, "fa": 2, "ma": 1}), False))["rejected"] is True


# --- 2. the wiring ----------------------------------------------------------------------------

@test("bridge: the herd section (safe), the four actions with dry runs, the module listed; labels, defaults, config")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "herd = function() return safe(function() return reqscript('ai-herd').report() end) end," in src
    actions = src[src.index("ACTIONS = {"):src.index("DRY_OK = {}")]
    dry = src[src.index("DRY_OK = {}"):src.index("}) do DRY_OK[name] = true end")]
    for name in ("herd_breeders", "tame_wild", "train_hunt", "herd_targets"):
        assert f"    {name} = function(a)" in actions and f"'{name}'" in dry, name
    mods = src[src.index("BRIDGE_MODULES = {"):src.index("}", src.index("BRIDGE_MODULES = {"))]
    assert "'ai-herd'" in mods
    assert SECTION_DEFAULTS["herd"] == {}
    import overseer
    for name in ("herd_breeders", "tame_wild", "train_hunt", "herd_targets"):
        assert name in overseer.SHORT_WORDS
    # the butcher's one-at-a-time pick spares the breeders; the gate dogs' pen is no pasture
    acts = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    i = acts.index("function act_slaughter_one(a)")
    assert "'Breeder'" in acts[i:i + 1200]
    soc = (LUA_DIR / "ai-society.lua").read_text(encoding="utf-8")
    j = soc.index("function pasture_report()")
    assert "GATE_DOGS_NAME" in soc[j:j + 1400] and "count = #list - dogs" in soc[j:j + 1400]
    if LuaRuntime is None:
        return
    k = src.index("    herd_breeders = function(a)")
    m = src.index("    end,\n}\n", k)
    body = src[k:m + len("    end,\n")]
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        GOT = {}
        function reject(r) return {ok = false, rejected = true, error = r} end
        function int_in(v, lo, hi)
            local n = math.tointeger(v); if n and n >= lo and n <= hi then return n end
        end
        txt = tostring
        function reqscript() return setmetatable({}, {__index = function(_, k)
            return function(...) GOT[#GOT + 1] = {k, ...}; return {ok = true} end end}) end
    """)
    t = lua.execute("return {\n" + body + "}")
    assert t.herd_breeders(lua.table_from({"females": 20}))["rejected"] is True
    assert t.herd_breeders(lua.table_from({"females": 0}))["ok"] is True
    assert t.tame_wild(lua.table_from({}))["rejected"] is True
    assert t.herd_targets(lua.table_from({"fk": 1, "mk": 1, "fa": 3}))["rejected"] is True
    assert t.herd_targets(lua.table_from({"fk": 1, "mk": 1, "fa": 3, "ma": 1, "dry_run": True}))["ok"] is True


# --- 3. the brain, slider by slider ------------------------------------------------------------

CFG = dict(PLANNER_CONFIG)
GARDEN = {"agriculture": 120, "husbandry": 80, "surface": 80, "welfare": 40, "grandeur": 40, "militarism": -30}
WAR = {"militarism": 150, "fortification": 120}
LOW = {"husbandry": -60}
MID: dict = {}


def herd(**kw):
    h = {"tame": 30, "kinds": [{"name": "COW", "n": 10, "f": 5, "m": 2, "grazer": True, "breeders_f": 0, "breeders_m": 0},
                               {"name": "HEN", "n": 12, "f": 8, "m": 1, "layer": True, "breeders_f": 0, "breeders_m": 0},
                               {"name": "DOG", "n": 8, "f": 3, "m": 5}],
         "breeders": 0, "wool_now": 3, "milk_now": 2, "grazing_need": 200, "tameable": 2,
         "tameable_kinds": [{"name": "BEAR_GRIZZLY", "n": 2}], "trainers": 1, "hunters": 0, "hunt_candidates": 3,
         "war": 0, "pets": 2, "breeding_pairs": 2, "targets": None}
    h.update(kw)
    return h


def state(h=None, tools=None, **extra):
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    base["herd"] = h if h is not None else herd()
    base.setdefault("buildings", {}).setdefault("workshops", {})["Farmers"] = 1
    base["tools"] = dict(base.get("tools") or {}, **(tools or {"autobutcher": False}))
    base.setdefault("society", {}).update({"ai_pastures": 1, "ai_pasture_tiles": 60})
    base.setdefault("dwarves", {})["total"] = 60
    base.update(extra)
    return normalize(base)


def run(traits, s=None, memory=None, citizens=60):
    props, notes = [], []
    PH._husbandry_rules(s if s is not None else state(), memory or Memory(), traits, CFG, citizens, props, notes)
    return {p.rule: p for p in props}, notes


@test("Garden (Husbandry 80): breeders kept, the bear tamed, a pasture ahead of the herd, wool and milk; no cull")
def _():
    got, notes = run(GARDEN)
    assert got["herd_breeders"].action == {"type": "herd_breeders", "females": PH.breeders_wanted(GARDEN, CFG)}
    assert PH.breeders_wanted(GARDEN, CFG) == 3
    assert "cow" in got["herd_breeders"].reason and "hen" in got["herd_breeders"].reason
    assert "dog" not in got["herd_breeders"].reason
    assert got["tame_wild"].action == {"type": "tame_wild", "max": 2}
    p = got["new_pasture"].action
    import math
    want = math.ceil(200 * CFG["herd_pasture_margin"] * 2 ** 0.8)         # need x margin x the factor (1.74)
    assert p["type"] == "make_pasture" and p["tiles"] == want - 60, p
    assert got["shearing"].action["amount"] == 3 and got["milking"].action["amount"] == 2
    assert "herd_cull" not in got and "herd_targets" not in got
    assert "train_hunt" not in got                                     # Militarism -30
    assert any("the herd:" in n for n in notes)


@test("middle (Husbandry 0): no breeders, no taming, no pasture ahead; wool and milk still taken as grown")
def _():
    got, _ = run(MID)
    for r in ("herd_breeders", "tame_wild", "new_pasture", "herd_cull"):
        assert r not in got, r
    assert "shearing" in got and "milking" in got


@test("low (Husbandry -60): autobutcher on at the low targets, breeders let go, no wool or milk rules")
def _():
    got, _ = run(LOW, state(herd(breeders=4)))
    assert got["herd_cull"].action == {"type": "tool", "name": "autobutcher", "enabled": True}
    assert got["herd_targets"].action == {"type": "herd_targets", "fk": 0, "mk": 0, "fa": 2, "ma": 1}
    assert got["herd_breeders"].action["females"] == 0
    assert "shearing" not in got and "milking" not in got and "tame_wild" not in got
    # a small herd isn't culled; nor a Beast-friends fort; nor when the player switched autobutcher off
    got, _ = run(LOW, state(herd(tame=6)))
    assert "herd_cull" not in got
    m = Memory()
    m.tools_player_disabled = ["autobutcher"]
    assert "herd_cull" not in run(LOW, memory=m)[0]


@test("autobutcher's targets follow the slider while it is on, and are not set again once set")
def _():
    on = {"autobutcher": True}
    assert run(MID, state(tools=on))[0]["herd_targets"].action == {"type": "herd_targets", "fk": 1, "mk": 1, "fa": 3, "ma": 1}
    assert run(GARDEN, state(tools=on))[0]["herd_targets"].action["fa"] == 6
    done = state(herd(targets={"fk": 1, "mk": 1, "fa": 3, "ma": 1}), tools=on)
    assert "herd_targets" not in run(MID, done)[0]


@test("the caps: no taming and no pasture ahead at the herd's size or while the game runs slowly; a trainer first")
def _():
    cap = PH.herd_cap(GARDEN, CFG, 60)
    got, notes = run(GARDEN, state(herd(tame=int(cap) + 1)))
    assert "tame_wild" not in got and "new_pasture" not in got and any("left in their cages" in n for n in notes)
    got, _ = run(GARDEN, state(fps_low=12))
    assert "tame_wild" not in got and "new_pasture" not in got
    got, _ = run(GARDEN, state(herd(trainers=0)))
    assert got["animal_trainer"].action == {"type": "assign_labor", "job": "ANIMALTRAIN", "count": 1}
    assert "tame_wild" not in got
    # enough grass already: no pasture ahead
    s = state()
    s["society"]["ai_pasture_tiles"] = 500
    assert "new_pasture" not in run(GARDEN, s)[0]
    # a pasture the waiting-grazer rule asks for already: not a second
    props = [Proposal("new_pasture", {"type": "make_pasture", "tiles": 50}, "x", 3)]
    PH._husbandry_rules(state(), Memory(), GARDEN, CFG, 60, props, [])
    assert sum(1 for p in props if p.rule == "new_pasture") == 1


@test("War-hold (Militarism 150): hunting training; war animals by Militarism (none below 0, more above)")
def _():
    got, _ = run(WAR)
    assert got["train_hunt"].action == {"type": "train_hunt", "max": 2}
    assert PH.hunt_animals_wanted(WAR, CFG) == 11 and PH.hunt_animals_wanted(GARDEN, CFG) == 0
    s = state(society={"animals": {"war_trained": 0, "in_training": 0, "war_candidates": 30, "trainers": 1}})
    s["dwarves"]["total"] = 80

    def war(traits):
        props: list = []
        _war_animal_rule(s, CFG, props, traits)
        return props
    assert war(GARDEN) == []                                       # Militarism -30: no war animals
    p = war(MID)[0]
    assert p.action["max"] == 3 and "of 8 wanted" in p.reason
    assert "of 23 wanted" in war(WAR)[0].reason or "of 24 wanted" in war(WAR)[0].reason
    props: list = []
    _war_animal_rule(s, CFG, props)                               # no traits: as before
    assert "of 8 wanted" in props[0].reason


@test("dairy: with the herd section the old rule no longer milks animals with no milk ready")
def _():
    s = state(herd(milk_now=0))
    s.setdefault("supplies", {}).update({"milkable": 4, "milk": 0})
    s.setdefault("stocks", {})["cheese"] = 0
    props: list = []
    _dairy_rule(s, CFG, 60, props)
    assert not any(p.action.get("recipe") == "milk_creature" for p in props)
    got, _ = run(GARDEN, s)
    assert "milking" not in got
    del s["herd"]
    props = []
    _dairy_rule(s, CFG, 60, props)
    assert any(p.action.get("recipe") == "milk_creature" for p in props)


@test("plan() carries the rules; without the herd section nothing; the fixtures hold none")
def _():
    s = state()
    s["settings"]["traits"] = GARDEN
    props, _ = plan(s, Memory())
    rules = {p.rule for p in props}
    assert "herd_breeders" in rules or "tame_wild" in rules, sorted(rules)
    s2 = state()
    del s2["herd"]
    got, _ = run(GARDEN, s2)
    assert got == {}


@test("words and the scorecard: the slider's effects say the herd; two new Husbandry lines for the Garden")
def _():
    import temperament
    import scorecard
    def words(t):
        s = state()
        s["settings"]["traits"] = t
        return temperament.effects(s).get("husbandry", "")
    hi, lo = words({"husbandry": 80}), words({"husbandry": -60})
    assert "breeding pairs kept" in hi and "tamed" in hi, hi
    assert "surplus to the butcher" in lo and "wool" not in lo, lo
    lines = {(sl, k): own for sl, _w, k, own, _lo in scorecard.LINES}
    assert lines[("Husbandry", "breeding_pairs")] == {"Garden fort"}
    assert lines[("Husbandry", "tamed")] == {"Garden fort"}


if __name__ == "__main__":
    finish()
