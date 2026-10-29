"""
Editable "recipes" for the linearly-scaled data files:
    data/json/unit_data.json
    data/json/building_data.json
    data/json/research_template.json

These three files are >90% mechanical: a stat at level N is almost always
`base + delta * N`, repeated for hundreds of entries. Instead of hand-editing
every line, tweak the numbers here and run generate_data.py to rewrite the
actual JSON files. The game itself only ever reads the JSON files in
data/json/ - nothing about how it loads/uses that data changes.

EQUIPMENT_STAGES stores base statistics and artwork references for each equipment stage.
Vehicle infantry statistics are generated from regular infantry through INFANTRY_VARIANT_RULES.
Heavy artillery statistics are generated through HEAVY_ARTILLERY_RULES.
Edit that table, then run the generator.
To add a new unit/building level, bump a `count`/range end and re-run.
"""
import sys
import os
import re
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import data.constants as c


# ===========================================================================
# VALUE GENERATORS
# Each of these returns a function: (zero-based level index) -> value.
# Use them as the value for any stat below. A plain number also works and
# means "constant at every level".
# ===========================================================================

def const(value):
    """Same value at every level."""
    return lambda i: value


def piecewise(segments):
    """General ramp-with-breakpoints generator.

    segments: list of (start_index, value_at_start_index, delta_per_level).
    Value ramps by `delta` per level within a segment, then jumps to the
    next segment's starting value at its start_index.

    Example: [(0, 6000, 1500), (9, 20000, 1000)]
      -> levels 0-8 climb by 1500/level starting at 6000,
         levels 9+ climb by 1000/level starting at 20000.
    """
    segs = sorted(segments, key=lambda s: s[0])

    def f(i):
        start, base, delta = segs[0]
        for s in segs:
            if i >= s[0]:
                start, base, delta = s
            else:
                break
        return base + delta * (i - start)

    return f


def lin(base, delta):
    """Value grows by `delta` every level, starting at `base`."""
    return piecewise([(0, base, delta)])


# ===========================================================================
# NAMING HELPERS
# ===========================================================================

def year_suffixes(start, count, step=1):
    return [str(start + i * step) for i in range(count)]


def rs(count):
    """Roman Suffixes"""
    return [c.ROMAN_NUMERALS[i] for i in range(1, count + 1)]


def single():
    """One entry, no numbering suffix (name == prefix)."""
    return [None]


def years_range(start, step, count):
    return [start + i * step for i in range(count)]


def table_values(columns, values):
    """Translate one editable row to full JSON field names and check its column count."""
    return dict(zip(columns.values(), values, strict=True))


# ===========================================================================
# UNIT_DATA.JSON
# ===========================================================================

UNIT_STAT_KEYS = ["health", "attack", "defense", "speed", "cost_materials",
                   "cost_manpower", "cost_fuel", "production_time"]

# Stats only some families define. A family that omits a key here simply
# doesn't get it written to its JSON entries, and combat code falls back to
# the equivalent required stat (e.g. "bombard_attack" falls back to "attack").
# This is how bombardment damage stays independently tunable per family
# without forcing every non-bombarding family to carry an unused stat.
OPTIONAL_UNIT_STAT_KEYS = ["bombard_attack", "production_group", "air_role",
                           "air_range_px", "air_attack_multiplier", "air_consumable",
                           "air_interception_immune", "air_damages_forts", "air_transport_capacity"]


class UnitFamily:
    def __init__(self, prefix, suffixes, stats, naval_unit=False, research_key=None, recruitment=None, division_suffix="", research_years=None, art_name=None):
        self.prefix = prefix
        self.division_suffix = division_suffix
        self.suffixes = suffixes
        self.stats = stats
        self.research_years = research_years
        self.art_name = art_name
        self.naval_unit = naval_unit
        key = re.sub(r'[^a-z0-9 ]', '', prefix.lower()).replace(' ', '_')
        self.research_key = research_key or c.UNIT_TECH_KEY_OVERRIDES.get(key, key)
        self.production_group = stats.get("production_group") or (
            "Navy" if naval_unit else "Tanks" if (
                "Tank" in prefix or "Armored Car" in prefix or prefix in c.TANK_GROUP_EXTRAS) else "Infantry")
        self.ai_tank = "Tank" in prefix or "Armored" in prefix or prefix == "Cavalry"
        self.ai_force_category = ("INFANTRY" if "Infantry" in prefix or prefix == "Militia" else
                                  "TANKS" if self.ai_tank else "NAVY" if naval_unit else None)
        self.recruitment = recruitment or {
            "industry": "industry" if prefix == "Militia" else "basic_factory",
            "coastal": naval_unit,
        }

    def entries(self):
        out = []
        for i, suffix in enumerate(self.suffixes):
            name = self.prefix if suffix is None else f"{self.prefix} {suffix}"
            entry = {}
            for key in UNIT_STAT_KEYS:
                gen = self.stats[key]
                entry[key] = gen(i) if callable(gen) else gen
            for key in OPTIONAL_UNIT_STAT_KEYS:
                if key in self.stats:
                    gen = self.stats[key]
                    entry[key] = gen(i) if callable(gen) else gen
            # Bombardment range doesn't vary by level, so it isn't hand-specified
            # per family like bombard_attack - it's pulled straight from
            # c.BOMBARDMENT_UNITS (keyed by family prefix) to keep that dict the
            # single source of truth instead of duplicating the number here.
            bombard_range = c.BOMBARDMENT_UNITS.get(self.prefix, 0)
            if bombard_range > 0:
                entry["bombard_range"] = bombard_range
            entry["naval_unit"] = self.naval_unit
            entry["order"] = {}
            is_year = suffix is not None and suffix.isdigit()
            tier = int(suffix) if is_year else (i + 1 if suffix is not None else 0)
            research = {"tech": self.research_key, "level": max(1, tier if not is_year else 1)}
            if self.research_key == "infantry_type" and is_year:
                research = {"tech": self.research_key, "year": tier}
            if self.research_years is not None:
                tier = self.research_years[i]
                research = {"tech": self.research_key, "year": tier}
            requirements = [research.copy()]
            if self.research_key in c.VEHICLE_INFANTRY_GATES:
                requirements = [{"tech": c.VEHICLE_INFANTRY_GATES[self.research_key], "level": 1},
                                {"tech": "infantry_type", "minimum_year": tier}]
            entry["metadata"] = {"family": self.prefix, "tier_order": tier,
                                 "research": research, "requirements": requirements,
                                 "tier_kind": "year" if is_year else "roman" if suffix else "single",
                                 "tier_label": suffix or "", "division_suffix": suffix or self.division_suffix,
                                 "recruitment": self.recruitment.copy(),
                                 "settings_family": self.prefix.removesuffix(" Type"),
                                 "production_group": self.production_group,
                                 # The old quota rule counted only unnumbered Cavalry.
                                 "ai_tank": self.ai_tank and (self.prefix != "Cavalry" or suffix is None),
                                 "ai_force_category": (None if self.prefix == "Cavalry" and suffix is not None
                                                       else self.ai_force_category)}
            if self.art_name:
                entry["metadata"]["art_name"] = self.art_name(i) if callable(self.art_name) else self.art_name
            out.append((name, entry))
        return out


# Defense multipliers use regular infantry's base attack, including for IFVs.
# Material multipliers leave manpower, fuel, and production time unchanged.
INFANTRY_VARIANT_RULES = {
    "Motorized Infantry Type": {"speed": 2, "material_multiplier": 1.5, "attack_multiplier": 1, "defense_multiplier": None},
    "Mechanized Infantry Type": {"speed": 2, "material_multiplier": 2, "attack_multiplier": 1, "defense_multiplier": 0.2},
    "Infantry Fighting Vehicle Type": {"speed": 2, "material_multiplier": 3, "attack_multiplier": 1.5, "defense_multiplier": 0.3},
}

# Preserve the first existing vehicle stage independently of artwork selection.
INFANTRY_VARIANT_FIRST_YEAR = 1905
HEAVY_ARTILLERY_RULES = {"material_multiplier": 2, "attack_multiplier": 2, "bombard_multiplier": 2, "extra_production_time": 3}
EQUIPMENT_VARIANT_BASES = {family: "Infantry Type" for family in INFANTRY_VARIANT_RULES}
EQUIPMENT_VARIANT_BASES["Heavy Artillery"] = "Artillery"

# Each row defines its year, name, base statistics, and existing artwork reference.
# Variant statistics and artwork are generated. Infantry's cost_fuel applies only to vehicles.
EQUIPMENT_COLUMNS = {
    "HP": "health",
    "ATK": "attack",
    "DEF": "defense",
    "SPD": "speed",
    "MAT": "cost_materials",
    "MAN": "cost_manpower",
    "FUEL": "cost_fuel",
    "TIME": "production_time",
    "BOMB": "bombard_attack",
    "ART": "art_name",
}

# Row columns match EQUIPMENT_COLUMNS after the year and name.
# BOMB=None omits bombardment. ART refers to existing artwork.
EQUIPMENT_STAGES = {
    "infantry_type": [
        #YR    NAME                                HP    ATK   DEF  SPD  MAT   MAN   FUEL  TIME  BOMB  ART
        (1800, "Flintlock Infantry",               600,  50,   0,   1,   200,  1000, 10,   2,    None, "Infantry Type 1910"),
        (1830, "Percussion Infantry",              640,  60,   0,   1,   240,  1000, 10,   2,    None, "Infantry Type 1910"),
        (1850, "Rifle-Musket Infantry",            700,  70,   0,   1,   300,  1000, 10,   2,    None, "Infantry Type 1910"),
        (1865, "Breech-Loading Infantry",          760,  75,   0,   1,   350,  1000, 10,   2,    None, "Infantry Type 1910"),
        (1875, "Metallic-Cartridge Infantry",      820,  80,   0,   1,   390,  1000, 10,   2,    None, "Infantry Type 1910"),
        (1885, "Magazine-Rifle Infantry",          870,  85,   0,   1,   430,  1000, 10,   2,    None, "Infantry Type 1910"),
        (1895, "Smokeless-Rifle Infantry",         920,  90,   0,   1,   470,  1000, 10,   2,    None, "Infantry Type 1910"),
        (1905, "Supported Rifle Infantry",         970,  95,   0,   1,   490,  1000, 10,   2,    None, "Infantry Type 1910"),
        (1915, "Trench Infantry",                  1250, 150,  0,   1,   525,  1000, 15,   2,    None, "Infantry Type 1915"),
        (1925, "Squad-Automatic Infantry",         1750, 250,  0,   1,   575,  1000, 25,   2,    None, "Infantry Type 1925"),
        (1940, "Semi-Automatic Infantry",          2500, 400,  0,   1,   650,  1000, 40,   2,    None, "Infantry Type 1940"),
        (1955, "Battle-Rifle Infantry",            3250, 550,  0,   1,   725,  1000, 55,   2,    None, "Infantry Type 1955"),
        (1970, "Assault-Rifle Infantry",           4000, 700,  0,   1,   800,  1000, 70,   2,    None, "Infantry Type 1970"),
        (1985, "Night-Equipped Infantry",          4750, 850,  0,   1,   875,  1000, 85,   2,    None, "Infantry Type 1985"),
        (2000, "Optics-Equipped Infantry",         5500, 1000, 0,   1,   950,  1000, 100,  2,    None, "Infantry Type 2000"),
        (2015, "Networked Infantry",               6250, 1150, 0,   1,   1025, 1000, 115,  2,    None, "Infantry Type 2015"),
        (2030, "Drone-Integrated Infantry",        7000, 1300, 0,   1,   1100, 1000, 130,  2,    None, "Infantry Type 2030"),
        (2040, "Sensor-Integrated Infantry",       7500, 1400, 0,   1,   1150, 1000, 140,  2,    None, "Infantry Type 2040"),
    ],
    "cavalry": [
        #YR    NAME                                HP    ATK   DEF  SPD  MAT   MAN   FUEL  TIME  BOMB  ART
        (1800, "Early Cavalry",                    350,  120,  0,   2,   450,  2000, 0,    3,    None, "Cavalry I"),
        (1850, "Improved Cavalry",                 400,  180,  0,   2,   600,  2000, 0,    3,    None, "Cavalry I"),
        (1870, "Breech-Loading Carbines",          470,  220,  0,   2,   750,  2000, 0,    3,    None, "Cavalry I"),
        (1890, "Magazine Carbines",                550,  260,  0,   2,   900,  2000, 0,    3,    None, "Cavalry I"),
        (1910, "Supported Cavalry",                600,  300,  0,   2,   1000, 2000, 0,    3,    None, "Cavalry I"),
        (1918, "Mounted Rifle Cavalry",            800,  300,  0,   2,   1000, 2000, 0,    3,    None, "Cavalry III"),
        (1930, "Modern Cavalry",                   1000, 300,  0,   2,   1000, 2000, 0,    3,    None, "Cavalry V"),
    ],
    "militia": [
        #YR    NAME                                HP    ATK   DEF  SPD  MAT   MAN   FUEL  TIME  BOMB  ART
        (1800, "Local Militia",                    200,  12,   0,   1,   100,  1000, 0,    1,    None, "Militia I"),
        (1840, "Organized Militia",                280,  20,   0,   1,   150,  1000, 0,    1,    None, "Militia I"),
        (1870, "Reserve Infantry",                 360,  32,   0,   1,   210,  1000, 0,    1,    None, "Militia I"),
        (1900, "Modern Militia",                   440,  44,   0,   1,   270,  1000, 0,    1,    None, "Militia I"),
        (1915, "Rifle Militia",                    600,  60,   0,   1,   300,  1000, 0,    1,    None, "Militia II"),
        (1935, "Support-Weapon Militia",           1000, 100,  0,   1,   300,  1000, 0,    1,    None, "Militia VI"),
        (1955, "Self-Loading Rifle Militia",       1400, 140,  0,   1,   300,  1000, 0,    1,    None, "Militia X"),
        (1975, "Assault-Rifle Militia",            1800, 180,  0,   1,   300,  1000, 0,    1,    None, "Militia XIV"),
        (1995, "Radio-Equipped Militia",           2200, 220,  0,   1,   300,  1000, 0,    1,    None, "Militia XVIII"),
        (2015, "Optics-Equipped Militia",          2600, 260,  0,   1,   300,  1000, 0,    1,    None, "Militia XXII"),
        (2035, "Drone-Supported Militia",          3000, 300,  0,   1,   300,  1000, 0,    1,    None, "Militia XXVI"),
    ],
    "artillery": [
        #YR    NAME                                HP    ATK   DEF  SPD  MAT   MAN   FUEL  TIME  BOMB  ART
        (1800, "Smoothbore Artillery",             60,   50,   0,   1,   450,  500,  0,    2,    50,   "Artillery I"),
        (1830, "Improved Field Artillery",         65,   60,   0,   1,   650,  500,  0,    2,    60,   "Artillery I"),
        (1850, "Rifled Artillery",                 75,   70,   0,   1,   850,  500,  0,    2,    70,   "Artillery I"),
        (1870, "Breech-Loading Artillery",         80,   80,   0,   1,   1050, 500,  0,    2,    80,   "Artillery I"),
        (1890, "Quick-Firing Artillery",           90,   90,   0,   1,   1250, 500,  0,    2,    90,   "Artillery I"),
        (1900, "Recoil-System Artillery",          95,   110,  0,   1,   1400, 500,  0,    2,    110,  "Artillery I"),
        (1915, "Indirect-Fire Artillery",          150,  180,  0,   1,   1600, 500,  0,    2,    180,  "Artillery II"),
        (1930, "Modern Field Artillery",           300,  360,  0,   1,   1900, 500,  0,    2,    360,  "Artillery V"),
        (1940, "Radio-Coordinated Artillery",      400,  480,  0,   1,   2100, 500,  0,    2,    480,  "Artillery VII"),
        (1955, "Advanced-Ammunition Artillery",    550,  660,  0,   1,   2400, 500,  0,    2,    660,  "Artillery X"),
        (1975, "Computer-Assisted Artillery",      750,  900,  0,   1,   2800, 500,  0,    2,    900,  "Artillery XIV"),
        (1995, "Digital Fire-Control Artillery",   950,  1140, 0,   1,   3200, 500,  0,    2,    1140, "Artillery XVIII"),
        (2010, "Precision-Guided Artillery",       1100, 1320, 0,   1,   3500, 500,  0,    2,    1320, "Artillery XXI"),
        (2025, "Sensor-Linked Artillery",          1250, 1500, 0,   1,   3800, 500,  0,    2,    1500, "Artillery XXIV"),
        (2040, "Automated Fire-Control Artillery", 1400, 1680, 0,   1,   4100, 500,  0,    2,    1680, "Artillery XXVII"),
    ],
}


class EquipmentFamily(UnitFamily):
    """Give equipment stages names while retaining their shared family metadata."""

    def __init__(self, *args, stage_names, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage_names = stage_names

    def entries(self):
        entries = super().entries()
        prefix = {"Motorized Infantry Type": "Motorized ", "Mechanized Infantry Type": "Mechanized ",
                  "Infantry Fighting Vehicle Type": "IFV ", "Heavy Artillery": "Heavy "}.get(self.prefix, "")
        result = []
        for (_, entry), label in zip(entries, self.stage_names):
            name = prefix + label
            entry["metadata"]["tier_label"] = label
            entry["metadata"]["tier_kind"] = "stage"
            result.append((name, entry))
        return result


def equipment_profile(prefix, stage):
    """Derive variant statistics and artwork from their base family profiles."""
    base_family = EQUIPMENT_VARIANT_BASES.get(prefix, prefix)
    base = table_values(EQUIPMENT_COLUMNS, stage[2:])
    if base["bombard_attack"] is None:
        del base["bombard_attack"]
    profile = dict(base, art_name=base["art_name"].replace(base_family, prefix, 1))
    if prefix in INFANTRY_VARIANT_RULES:
        rule = INFANTRY_VARIANT_RULES[prefix]
        profile.update(speed=rule["speed"],
                       cost_materials=base["cost_materials"] * rule["material_multiplier"],
                       attack=base["attack"] * rule["attack_multiplier"])
        if rule["defense_multiplier"] is not None:
            profile["defense"] = base["attack"] * rule["defense_multiplier"]
    elif prefix == "Heavy Artillery":
        rule = HEAVY_ARTILLERY_RULES
        profile.update(cost_materials=base["cost_materials"] * rule["material_multiplier"],
                       attack=base["attack"] * rule["attack_multiplier"],
                       bombard_attack=base["bombard_attack"] * rule["bombard_multiplier"],
                       production_time=base["production_time"] + rule["extra_production_time"])
    elif prefix == "Infantry Type":
        profile["cost_fuel"] = 0
    return profile


def equipment_family(prefix, tech):
    """Generate one family from base stages and shared variant rules."""
    stages = [(stage[0], stage[1], equipment_profile(prefix, stage))
              for stage in EQUIPMENT_STAGES[tech]
              if prefix not in INFANTRY_VARIANT_RULES or stage[0] >= INFANTRY_VARIANT_FIRST_YEAR]
    key = prefix.lower().replace(" ", "_")
    research_key = c.UNIT_TECH_KEY_OVERRIDES.get(key, tech)
    fields = UNIT_STAT_KEYS + [field for field in OPTIONAL_UNIT_STAT_KEYS if field in stages[0][2]]
    stats = {field: (lambda i, field=field: stages[i][2][field]) for field in fields}
    return EquipmentFamily(prefix, [str(year) for year, _, _ in stages], stats,
                           research_key=research_key,
                           research_years=[year for year, _, _ in stages],
                           art_name=lambda i: stages[i][2]["art_name"],
                           stage_names=[label for _, label, _ in stages])


# Each inner list is a contiguous block of families; a blank spacer line is
# written between blocks, matching the hand-maintained file's formatting.
# Family rows retain live const, lin, piecewise, and suffix generators.
# None omits an optional statistic. OPTIONS contains constructor settings.
UNIT_RECIPE_COLUMNS = {
    "HP": "health",
    "ATK": "attack",
    "DEF": "defense",
    "SPD": "speed",
    "MAT": "cost_materials",
    "MAN": "cost_manpower",
    "FUEL": "cost_fuel",
    "TIME": "production_time",
    "BOMB": "bombard_attack",
}
AIR_RECIPE_COLUMNS = {
    "HP": "health",
    "ATK": "attack",
    "DEF": "defense",
    "SPD": "speed",
    "MAT": "cost_materials",
    "MAN": "cost_manpower",
    "FUEL": "cost_fuel",
    "TIME": "production_time",
    "ROLE": "air_role",
    "RNG": "air_range_px",
    "AAMULT": "air_attack_multiplier",
    "CONSUME": "air_consumable",
    "IMMUNE": "air_interception_immune",
    "FORT": "air_damages_forts",
    "CARGO": "air_transport_capacity",
}

CAR_SPEED = piecewise([(0, 2, 0), (1, 3, 0), (4, 4, 0)])
LIGHT_TANK_SPEED = piecewise([(0, 2, 0), (3, 3, 0)])

LAND_UNIT_RECIPES = [
    #NAME                          TIERS     HP              ATK             DEF           SPD               MAT               MAN          FUEL          TIME      BOMB   OPTIONS
    ("WW1 Tank",                   single(), 3000,           1500,           100,          1,                6000,             1000,        300,          6,        None,  {}),
    ("WW1 Armored Car",            single(), 1000,           300,            50,           2,                3000,             1000,        100,          4,        None,  {}),
    ("Armored Car",                rs(34),   lin(1000, 100), lin(400, 100),  lin(60, 10),  CAR_SPEED,        lin(3000, 200),   const(1000), lin(100, 5),  const(4), None,  {}),
    ("Light Tank",                 rs(34),   lin(1800, 200), lin(1200, 150), lin(80, 10),  LIGHT_TANK_SPEED, lin(5000, 500),   const(1000), lin(150, 5),  const(5), None,  {}),
    ("Medium Tank",                rs(4),    lin(2500, 500), lin(2400, 600), lin(150, 25), const(2),         lin(9000, 1000),  const(1000), lin(200, 10), const(6), None,  {}),
    ("Heavy Tank",                 rs(4),    lin(3000, 500), lin(3000, 500), lin(350, 50), const(1),         lin(12000, 1000), const(1000), lin(200, 10), const(6), None,  {}),
    ("Super Heavy Tank",           rs(5),    const(5000),    const(5000),    lin(550, 50), const(1),         lin(16000, 2000), const(1000), lin(240, 20), const(6), None,  {}),
    ("Landkreuzer P.1000 Ratte",   single(), 10000,          6000,           400,          1,                50000,            2000,        1000,         10,       1000,  {"division_suffix": "1000"}),
    ("Landkreuzer P.1500 Monster", single(), 15000,          8000,           500,          1,                60000,            2000,        1200,         12,       1200,  {"division_suffix": "1500"}),
    ("Railgun",                    single(), 10000,          10000,          500,          1,                80000,            2000,        3000,         10,       10000, {}),
    ("Main Battle Tank",           rs(22),   lin(5000, 500), lin(5000, 500), lin(250, 25), const(2),         lin(16000, 1000), const(1000), lin(240, 10), const(6), None,  {}),
    ("WW1 Railroad Gun",           single(), 1200,           500,            0,            1,                5000,             1000,        0,            6,        500,   {}),
    ("WW2 Railroad Gun",           single(), 2000,           800,            0,            1,                8000,             1000,        0,            6,        800,   {}),
]

NAVAL_UNIT_RECIPES = [
    #NAME                          TIERS     HP              ATK             DEF           SPD                                           MAT               MAN          FUEL          TIME       BOMB           OPTIONS
    ("Carrack",                    single(), 1000,           400,            0,            1,                                            2000,             500,         0,            4,         None,          {}),
    ("Ironclad",                   single(), 2000,           800,            200,          1,                                            8000,             1000,        100,          6,         None,          {}),
    ("Pre-Dreadnought",            single(), 3000,           1200,           300,          1,                                            12000,            2000,        250,          8,         None,          {}),
    ("Dreadnought",                single(), 4000,           2400,           400,          1,                                            20000,            2000,        300,          10,        300,           {}),
    ("Battleship",                 single(), 6000,           4000,           600,          1,                                            20000,            2000,        400,          10,        500,           {}),
    ("Destroyer",                  rs(36),   lin(2400, 400), lin(1200, 300), lin(200, 20), const(1),                                     lin(10000, 500),  const(1000), lin(250, 5),  const(8),  None,          {}),
    ("Submarine",                  rs(36),   lin(1200, 200), lin(600, 100),  const(0),     const(1),                                     lin(8000, 400),   const(1000), lin(150, 5),  const(6),  None,          {}),
    ("Aircraft Carrier",           rs(25),   lin(800, 200),  lin(600, 120),  lin(200, 20), const(1),                                     lin(20000, 1000), const(2000), lin(500, 25), const(10), lin(600, 120), {}),
]

AIR_UNIT_RECIPES = [
    #NAME                   TIERS     HP              ATK             DEF           SPD  MAT               MAN   FUEL          TIME  ROLE         RNG           AAMULT  CONSUME  IMMUNE  FORT  CARGO  OPTIONS
    ('Biplane Fighter',     rs(5),    lin(2000, 100), lin(120, 20),   0,            1,   1000,             500,  60,           2,    'fighter',   lin(60, 5),   10,     None,    None,   None, None,  {}),
    ('Biplane Bomber',      rs(5),    lin(3000, 500), lin(600, 100),  0,            1,   2000,             500,  80,           3,    'bomber',    lin(80, 10),  None,   None,    None,   True, None,  {}),
    ('Zeppelin',            single(), 3000,           300,            0,            1,   2000,             500,  60,           4,    'bomber',    120,          None,   None,    None,   True, None,  {}),
    ('Monoplane Fighter',   rs(5),    lin(3000, 200), lin(250, 50),   lin(50, 10),  1,   3000,             500,  100,          3,    'fighter',   lin(100, 5),  8,      None,    None,   None, None,  {}),
    ('Monoplane Bomber',    rs(5),    lin(5000, 200), lin(1000, 100), lin(120, 20), 1,   lin(4000, 400),   500,  120,          4,    'bomber',    lin(120, 20), None,   None,    None,   True, None,  {}),
    ('Monoplane Transport', rs(3),    1000,           0,              0,            1,   lin(9000, 500),   1000, 200,          4,    'transport', lin(60, 10),  None,   None,    None,   None, 1,     {}),
    ('V1 Flying Bomb',      single(), 1000,           800,            0,            1,   2000,             0,    60,           2,    'strike',    200,          None,   True,    None,   True, None,  {}),
    ('V2 Rocket',           single(), 2000,           1200,           0,            1,   4000,             0,    80,           4,    'strike',    300,          None,   True,    True,   True, None,  {}),
    ('Jet Fighter',         rs(26),   lin(4000, 200), lin(1000, 100), lin(100, 20), 1,   lin(5000, 200),   500,  lin(160, 10), 4,    'fighter',   lin(200, 5),  4,      None,    None,   None, None,  {}),
    ('Jet Bomber',          rs(20),   lin(6000, 200), lin(1600, 200), lin(200, 20), 1,   lin(6000, 500),   500,  lin(160, 20), 6,    'bomber',    lin(300, 10), None,   None,    None,   True, None,  {}),
    ('Jet Transport',       rs(20),   lin(2000, 200), 0,              0,            1,   lin(25000, 1000), 1000, 500,          6,    'transport', lin(100, 20), None,   None,    None,   None, 2,     {}),
]


def unit_family(row, *, naval_unit=False, air=False):
    """Translate an aligned family recipe while retaining its growth functions."""
    prefix, suffixes, *values, options = row
    columns = AIR_RECIPE_COLUMNS if air else UNIT_RECIPE_COLUMNS
    stats = {field: value for field, value in table_values(columns, values).items() if value is not None}
    if air:
        stats["production_group"] = "Air"
    return UnitFamily(prefix, suffixes, stats, naval_unit=naval_unit, **options)


UNIT_SECTIONS = [
    [
        equipment_family("Infantry Type", "infantry_type"),
        equipment_family("Motorized Infantry Type", "infantry_type"),
        equipment_family("Mechanized Infantry Type", "infantry_type"),
        equipment_family("Infantry Fighting Vehicle Type", "infantry_type"),
        equipment_family("Cavalry", "cavalry"),
        equipment_family("Militia", "militia"),
        equipment_family("Artillery", "artillery"),
        equipment_family("Heavy Artillery", "artillery"),
    ],
    [unit_family(row) for row in LAND_UNIT_RECIPES],
    [unit_family(row, naval_unit=True) for row in NAVAL_UNIT_RECIPES],
    [unit_family(row, air=True) for row in AIR_UNIT_RECIPES],
]


# ===========================================================================
# BUILDING_DATA.JSON
# ===========================================================================
# Two upgrade chains: a base/root building, then N numbered levels each
# requiring the previous one. `stats` generators are keyed by the same
# names used in the JSON (minus `req`, which is derived automatically from
# the chain unless overridden on the base entry).

# "req" sits between "group" and "cost_materials" in every entry.
BUILDING_STAT_KEYS = ["time", "group", "cost_materials", "cost_manpower",
                       "cost_fuel", "prod_materials", "prod_manpower", "prod_fuel"]


class BuildingChain:
    def __init__(self, base_name, base_stats, base_req, level_prefix, count, stats,
                 skip_generated_base=False):
        self.base_name = base_name
        self.base_stats = base_stats
        self.base_req = base_req
        self.level_prefix = level_prefix
        self.count = count
        self.stats = stats
        # Some chains use a numbered first level as their base entry.  Avoid
        # emitting that same name a second time from the generated sequence.
        self.skip_generated_base = skip_generated_base

    def entries(self):
        base_entry = {"time": self.base_stats["time"], "group": self.base_stats["group"],
                       "req": self.base_req}
        for key in BUILDING_STAT_KEYS[2:]:
            base_entry[key] = self.base_stats[key]
        out = [(self.base_name, base_entry)]

        prev_name = self.base_name
        for n in range(1, self.count + 1):
            name = f"{self.level_prefix} {n}"
            if self.skip_generated_base and name == self.base_name:
                continue

            def val(key):
                gen = self.stats[key]
                return gen(n) if callable(gen) else gen

            entry = {"time": val("time"), "group": val("group"), "req": prev_name}
            for key in BUILDING_STAT_KEYS[2:]:
                entry[key] = val(key)
            out.append((name, entry))
            prev_name = name
        return out


BUILDING_RECIPE_COLUMNS = {
    "TIME": "time",
    "GROUP": "group",
    "MAT": "cost_materials",
    "MAN": "cost_manpower",
    "FUEL": "cost_fuel",
    "OUTMAT": "prod_materials",
    "OUTMAN": "prod_manpower",
    "OUTFUEL": "prod_fuel",
}

# Base requirements preserve the literal "null" string separately from None.
# Basic Factory costs remain dynamic in queries.get_building_cost; its stored costs stay zero.
BUILDING_BASE_RECIPES = [
    #NAME                        REQ     TIME  GROUP            MAT   MAN  FUEL  OUTMAT  OUTMAN  OUTFUEL
    ("Basic Factory",            "null", 20,   "industry",      0,    0,   0,    200,    0,      0),
    ("Basic Recruitment Center", None,   6,    "recruitment",   2500, 0,   0,    0,      50,     0),
    ("Fort Lvl 1",               None,   1,    "fortification", 5000, 0,   0,    0,      0,      0),
]

# Growth functions receive the numbered building level, starting at 1.
BUILDING_GROWTH_RECIPES = [
    #NAME                        PREFIX                      COUNT             TIME       GROUP                   MAT                          MAN       FUEL         OUTMAT                   OUTMAN             OUTFUEL           OPTIONS
    ("Basic Factory",            "Factory Lvl",              25,               const(12), const("industry"),      const(30000),                const(0), const(1000), lambda n: 100 * n + 500, const(0),          lambda n: 10 * n, {}),
    ("Basic Recruitment Center", "Recruitment Building Lvl", 50,               const(6),  const("recruitment"),   const(5000),                 const(0), const(0),    const(0),                lambda n: 100 * n, const(0),         {}),
    ("Fort Lvl 1",               "Fort Lvl",                 c.FORT_MAX_LEVEL, const(1),  const("fortification"), lambda n: 4000 + (1000 * n), const(0), const(0),    const(0),                const(0),          const(0),         {"skip_generated_base": True}),
]


def building_chain(row):
    """Translate base and growth recipes without expanding their formulas."""
    name, prefix, count, *values, options = row
    base = next(base for base in BUILDING_BASE_RECIPES if base[0] == name)
    return BuildingChain(name, table_values(BUILDING_RECIPE_COLUMNS, base[2:]), base[1],
                         prefix, count, table_values(BUILDING_RECIPE_COLUMNS, values), **options)


BUILDING_CHAINS = [building_chain(row) for row in BUILDING_GROWTH_RECIPES]


# ===========================================================================
# RESEARCH_TEMPLATE.JSON
# ===========================================================================
# Equipment research uses the named stages. Other tracks can use years_range for regular intervals.
# Prerequisites, categories, and costs are literal tuning values.

def extend_infantry_research(tech, entry):
    """Use the same equipment stages for research and generated units."""
    stages = EQUIPMENT_STAGES[tech]
    names = {str(i + 1): stage[1] for i, stage in enumerate(stages)}
    entry["years"] = [stage[0] for stage in stages]
    entry["max_lvl"] = len(entry["years"])
    entry["level_names"] = names
    entry["level_icons"] = names.copy()
    return entry


# Sections separated by a blank spacer line, matching the current file.
RESEARCH_RECIPE_COLUMNS = {"CAT": "category", "LVLS": "max_lvl", "COST": "cost", "REQ": "req", "YRS": "years"}
RESEARCH_OPTION_COLUMNS = {"NAME": "display_name", "GATES": "level_reqs", "BONUS": "building_output_bonuses"}

# None for both LVLS and YRS derives equipment research from EQUIPMENT_STAGES.
# Other rows retain their years_range expressions and prerequisite dictionaries.
RESEARCH_RECIPES = [
    [
        #ID                            CAT         LVLS  COST  REQ                                                    YRS                             OPTIONS
        ("infantry_type",              "INFANTRY", None, 900,  {},                                                    None,                           {}),
        ("cavalry",                    "INFANTRY", None, 1200, {},                                                    None,                           {}),
        ("militia",                    "INFANTRY", None, 600,  {},                                                    None,                           {}),
        ("artillery",                  "INFANTRY", None, 900,  {},                                                    None,                           {}),
        ("trucks",                     "INFANTRY", 1,    1800, {"cavalry": len(EQUIPMENT_STAGES["cavalry"])},         years_range(1930, 1, 1),        {}),
        ("armored_personnel_carriers", "INFANTRY", 1,    1800, {"trucks": 1},                                         years_range(1940, 1, 1),        {}),
        ("infantry_fighting_vehicle",  "INFANTRY", 1,    1800, {"armored_personnel_carriers": 1},                     years_range(1950, 1, 1),        {}),
    ],
    [
        #ID                            CAT         LVLS  COST  REQ                                                    YRS                             OPTIONS
        ("civilian_car",               "TANKS",    1,    2400, {},                                                    years_range(1910, 1, 1),        {}),
        ("ww1_armored_car",            "TANKS",    1,    2400, {"civilian_car": 1},                                   years_range(1912, 1, 1),        {}),
        ("armored_car",                "TANKS",    34,   2400, {"ww1_armored_car": 1},                                years_range(1916, 4, 34),       {}),
    ],
    [
        #ID                            CAT         LVLS  COST  REQ                                                    YRS                             OPTIONS
        ("ww1_tank",                   "TANKS",    1,    2400, {"ww1_armored_car": 1},                                years_range(1914, 1, 1),        {}),
        ("light_tank",                 "TANKS",    34,   2400, {"ww1_tank": 1},                                       years_range(1918, 4, 34),       {}),
        ("medium_tank",                "TANKS",    4,    2400, {"light_tank": 1},                                     years_range(1925, 5, 4),        {}),
        ("heavy_tank",                 "TANKS",    4,    2400, {"medium_tank": 1},                                    years_range(1929, 4, 4),        {}),
        ("super_heavy_tank",           "TANKS",    5,    2400, {"heavy_tank": 4},                                     years_range(1945, 4, 5),        {}),
        ("landkreuzer_p1000_ratte",    "TANKS",    1,    3000, {"ww2_railroad_gun": 1},                               years_range(1944, 6, 1),        {}),
        ("landkreuzer_p1500_monster",  "TANKS",    1,    3600, {"landkreuzer_p1000_ratte": 1},                        years_range(1956, 8, 1),        {}),
        ("electromagnetic_launcher",   "TANKS",    1,    3000, {},                                                    years_range(1980, 1, 1),        {}),
        ("railgun",                    "TANKS",    1,    3600, {"electromagnetic_launcher": 1},                       years_range(2030, 1, 1),        {}),
        ("main_battle_tank",           "TANKS",    22,   2400, {"OR": [{"medium_tank": 4}, {"heavy_tank": 4}]},       years_range(1945, 5, 22),       {}),
        ("ww1_railroad_gun",           "TANKS",    1,    2400, {"ww1_tank": 1},                                       years_range(1918, 1, 1),        {}),
        ("ww2_railroad_gun",           "TANKS",    1,    2400, {"AND": [{"heavy_tank": 1}, {"ww1_railroad_gun": 1}]}, years_range(1932, 1, 1),        {}),
    ],
    [
        #ID                            CAT         LVLS  COST  REQ                                                    YRS                             OPTIONS
        ("carrack",                    "NAVY",     1,    600,  {},                                                    [1800],                         {}),
        ("ironclad",                   "NAVY",     1,    2400, {"carrack": 1},                                        [1860],                         {}),
        ("pre-dreadnought",            "NAVY",     1,    2400, {"ironclad": 1},                                       [1880],                         {}),
        ("dreadnought",                "NAVY",     1,    2400, {"pre-dreadnought": 1},                                years_range(1900, 1, 1),        {}),
        ("battleship",                 "NAVY",     1,    2400, {"dreadnought": 1},                                    years_range(1920, 1, 1),        {}),
        ("destroyer",                  "NAVY",     36,   2400, {"dreadnought": 1},                                    years_range(1910, 4, 36),       {}),
        ("aircraft_carrier",           "NAVY",     25,   2400, {"battleship": 1},                                     years_range(1930, 5, 25),       {}),
        ("submarine",                  "NAVY",     36,   2400, {"dreadnought": 1},                                    years_range(1910, 4, 36),       {}),
    ],
    [
        #ID                            CAT         LVLS  COST  REQ                                                    YRS                             OPTIONS
        ("basic_factory",              "INDUSTRY", 1,    1200, {},                                                    years_range(1800, 1, 1),        {}),
        ("waltham_system",             "INDUSTRY", 1,    1200, {"basic_factory": 1},                                  [1815],                         {"NAME": "Waltham System", "BONUS": [{"building_families": ["Basic Factory"], "flat_outputs": {"materials": 100}}]}),
        ("metal_shaper",               "INDUSTRY", 1,    1200, {"waltham_system": 1},                                 [1835],                         {"NAME": "Metal Shaper"}),
        ("steam_hammer",               "INDUSTRY", 1,    1200, {"metal_shaper": 1},                                   [1840],                         {"NAME": "Steam Hammer"}),
        ("bessemer_process",           "INDUSTRY", 1,    1200, {"steam_hammer": 1},                                   [1855],                         {"NAME": "Bessemer Process", "BONUS": [{"building_families": ["Basic Factory"], "flat_outputs": {"materials": 200}}]}),
        ("electricity",                "INDUSTRY", 1,    1200, {"bessemer_process": 1},                               [1870],                         {"NAME": "Electricity"}),
        ("lightbulb",                  "INDUSTRY", 1,    1200, {"electricity": 1},                                    [1880],                         {"NAME": "Lightbulb"}),
        ("assembly_line",              "INDUSTRY", 1,    1200, {"factory": 1},                                        [1905],                         {"NAME": "Assembly Line", "BONUS": [{"building_families": ["Basic Factory", "Factory"], "outputs": {"materials": 0.5}}]}),
        ("conveyor_belt",              "INDUSTRY", 1,    1200, {"factory": 2},                                        [1915],                         {"NAME": "Conveyor Belt", "BONUS": [{"building_families": ["Basic Factory", "Factory"], "outputs": {"materials": 0.5}}]}),
        ("machine_tools",              "INDUSTRY", 1,    1200, {"factory": 4},                                        [1935],                         {"NAME": "Machine Tools"}),
        ("just_in_time_manufacturing", "INDUSTRY", 1,    1200, {"factory": 5},                                        [1945],                         {"NAME": "Just In Time Manufacturing", "BONUS": [{"building_families": ["Basic Factory", "Factory"], "outputs": {"materials": 0.2}}]}),
        ("industrial_robot",           "INDUSTRY", 1,    1200, {"factory": 6},                                        [1955],                         {"NAME": "Industrial Robot"}),
        ("stanford_arm",               "INDUSTRY", 1,    1200, {"factory": 7},                                        [1965],                         {"NAME": "Stanford Arm"}),
        ("asea_irb_6",                 "INDUSTRY", 1,    1200, {"factory": 8},                                        [1975],                         {"NAME": "ASEA IRB 6"}),
        ("computer_numerical_control", "INDUSTRY", 1,    1200, {"factory": 9},                                        [1985],                         {"NAME": "Computer Numerical Control"}),
        ("3d_printing",                "INDUSTRY", 1,    1200, {"factory": 10},                                       [1995],                         {"NAME": "3D Printing"}),
        ("internet_of_things",         "INDUSTRY", 1,    1200, {"factory": 11},                                       [2005],                         {"NAME": "Internet of Things"}),
        ("industry_4_0",               "INDUSTRY", 1,    1200, {"factory": 12},                                       [2015],                         {"NAME": "Industry 4.0"}),
        ("industry_5_0",               "INDUSTRY", 1,    1200, {"factory": 13},                                       [2025],                         {"NAME": "Industry 5.0"}),
        ("factory",                    "INDUSTRY", 25,   1200, {"lightbulb": 1},                                      years_range(1900, 10, 25),      {"GATES": {"2": {"assembly_line": 1}, "3": {"conveyor_belt": 1}, "5": {"machine_tools": 1}, "6": {"just_in_time_manufacturing": 1}, "7": {"industrial_robot": 1}, "8": {"stanford_arm": 1}, "9": {"asea_irb_6": 1}, "10": {"computer_numerical_control": 1}, "11": {"3d_printing": 1}, "12": {"internet_of_things": 1}, "13": {"industry_4_0": 1}, "14": {"industry_5_0": 1}}}),
        ("bergius_process",            "INDUSTRY", 1,    1200, {},                                                    years_range(1910, 1, 1),        {}),
        ("fuel_refining",              "INDUSTRY", 50,   1200, {"bergius_process": 1},                                years_range(1912, 2, 50),       {}),
        ("basic_recruitment",          "INDUSTRY", 1,    1200, {},                                                    years_range(1910, 1, 1),        {}),
        ("recruitment_buildings",      "INDUSTRY", 50,   1200, {"basic_recruitment": 1},                              years_range(1912, 2, 50),       {}),
        ("general_recruitment",        "INDUSTRY", 50,   900,  {"recruitment_buildings": "MATCH_LEVEL"},              years_range(1913, 2, 50),       {}),
        ("resource_refining",          "INDUSTRY", 100,  900,  {},                                                    years_range(1911, 1, 100),      {}),
    ],
    [
        #ID                            CAT         LVLS  COST  REQ                                                    YRS                             OPTIONS
        ('biplane',                    'AIR',      5,    1200, {},                                                    [1910, 1914, 1918, 1922, 1926], {"NAME": 'Biplane Fighter'}),
        ('biplane_bomber',             'AIR',      3,    1800, {'biplane': 1},                                        [1915, 1920, 1925],             {"NAME": 'Biplane Bomber'}),
        ('zeppelin',                   'AIR',      1,    1800, {},                                                    [1910],                         {"NAME": 'Zeppelin'}),
        ('piston_fighter',             'AIR',      5,    1200, {'biplane': 5},                                        [1930, 1934, 1938, 1942, 1946], {"NAME": 'Monoplane Fighter'}),
        ('piston_bomber',              'AIR',      5,    1800, {'biplane_bomber': 3},                                 [1930, 1935, 1940, 1945, 1950], {"NAME": 'Monoplane Bomber'}),
        ('monoplane_transport',        'AIR',      3,    1800, {'biplane_bomber': 3},                                 [1930, 1935, 1940],             {"NAME": 'Monoplane Transport'}),
        ('v1_flying_bomb',             'AIR',      1,    900,  {},                                                    [1940],                         {"NAME": 'V1 Flying Bomb'}),
        ('v2_rocket',                  'AIR',      1,    1200, {'v1_flying_bomb': 1},                                 [1945],                         {"NAME": 'V2 Rocket'}),
        ('jet_engine',                 'AIR',      1,    2400, {},                                                    [1945],                         {"NAME": 'Jet Engine'}),
        ('jet_fighter',                'AIR',      26,   1800, {'piston_fighter': 5, 'jet_engine': 1},                years_range(1950, 4, 26),       {"NAME": 'Jet Fighter'}),
        ('jet_bomber',                 'AIR',      20,   2400, {'piston_bomber': 5, 'jet_fighter': 1},                years_range(1955, 5, 20),       {"NAME": 'Jet Bomber'}),
        ('jet_transport',              'AIR',      20,   2400, {'piston_bomber': 5},                                  years_range(1955, 5, 20),       {"NAME": 'Jet Transport'}),
    ],
]


def research_recipe(row):
    """Translate one compact research row without changing saved field names or order."""
    key, *values, options = row
    entry = table_values(RESEARCH_RECIPE_COLUMNS, values)
    entry.update({RESEARCH_OPTION_COLUMNS.get(field, field): value for field, value in options.items()})
    if entry["max_lvl"] is None and entry["years"] is None:
        del entry["max_lvl"], entry["years"]
        return key, extend_infantry_research(key, entry)
    fields = ("category", "display_name", "max_lvl", "cost", "req", "level_reqs", "years")
    ordered = {field: entry[field] for field in fields if field in entry}
    ordered.update({field: value for field, value in entry.items() if field not in ordered})
    return key, ordered


RESEARCH_SECTIONS = [[research_recipe(row) for row in block] for block in RESEARCH_RECIPES]
