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


def linear(base, delta):
    """Value grows by `delta` every level, starting at `base`."""
    return piecewise([(0, base, delta)])


# ===========================================================================
# NAMING HELPERS
# ===========================================================================

def year_suffixes(start, count, step=1):
    return [str(start + i * step) for i in range(count)]


def roman_suffixes(count):
    return [c.ROMAN_NUMERALS[i] for i in range(1, count + 1)]


def single():
    """One entry, no numbering suffix (name == prefix)."""
    return [None]


def years_range(start, step, count):
    return [start + i * step for i in range(count)]


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
        #  YR, NAME,                                 HP,  ATK, DEF, SPD,  MAT,  MAN, FUEL, TIME, BOMB, ART
        (1800, "Flintlock Infantry",                600,   50,   0,   1,  200, 1000,   10,    2, None, "Infantry Type 1910"),
        (1830, "Percussion Infantry",               640,   60,   0,   1,  240, 1000,   10,    2, None, "Infantry Type 1910"),
        (1850, "Rifle-Musket Infantry",             700,   70,   0,   1,  300, 1000,   10,    2, None, "Infantry Type 1910"),
        (1865, "Breech-Loading Infantry",           760,   75,   0,   1,  350, 1000,   10,    2, None, "Infantry Type 1910"),
        (1875, "Metallic-Cartridge Infantry",       820,   80,   0,   1,  390, 1000,   10,    2, None, "Infantry Type 1910"),
        (1885, "Magazine-Rifle Infantry",           870,   85,   0,   1,  430, 1000,   10,    2, None, "Infantry Type 1910"),
        (1895, "Smokeless-Rifle Infantry",          920,   90,   0,   1,  470, 1000,   10,    2, None, "Infantry Type 1910"),
        (1905, "Supported Rifle Infantry",          970,   95,   0,   1,  490, 1000,   10,    2, None, "Infantry Type 1910"),
        (1915, "Trench Infantry",                  1250,  150,   0,   1,  525, 1000,   15,    2, None, "Infantry Type 1915"),
        (1925, "Squad-Automatic Infantry",         1750,  250,   0,   1,  575, 1000,   25,    2, None, "Infantry Type 1925"),
        (1940, "Semi-Automatic Infantry",          2500,  400,   0,   1,  650, 1000,   40,    2, None, "Infantry Type 1940"),
        (1955, "Battle-Rifle Infantry",            3250,  550,   0,   1,  725, 1000,   55,    2, None, "Infantry Type 1955"),
        (1970, "Assault-Rifle Infantry",           4000,  700,   0,   1,  800, 1000,   70,    2, None, "Infantry Type 1970"),
        (1985, "Night-Equipped Infantry",          4750,  850,   0,   1,  875, 1000,   85,    2, None, "Infantry Type 1985"),
        (2000, "Optics-Equipped Infantry",         5500, 1000,   0,   1,  950, 1000,  100,    2, None, "Infantry Type 2000"),
        (2015, "Networked Infantry",               6250, 1150,   0,   1, 1025, 1000,  115,    2, None, "Infantry Type 2015"),
        (2030, "Drone-Integrated Infantry",        7000, 1300,   0,   1, 1100, 1000,  130,    2, None, "Infantry Type 2030"),
        (2040, "Sensor-Integrated Infantry",       7500, 1400,   0,   1, 1150, 1000,  140,    2, None, "Infantry Type 2040"),
    ],
    "cavalry": [
        #  YR, NAME,                                 HP,  ATK, DEF, SPD,  MAT,  MAN, FUEL, TIME, BOMB, ART
        (1800, "Early Cavalry",                     350,  120,   0,   2,  450, 2000,    0,    3, None, "Cavalry I"),
        (1850, "Improved Cavalry",                  400,  180,   0,   2,  600, 2000,    0,    3, None, "Cavalry I"),
        (1870, "Breech-Loading Carbines",           470,  220,   0,   2,  750, 2000,    0,    3, None, "Cavalry I"),
        (1890, "Magazine Carbines",                 550,  260,   0,   2,  900, 2000,    0,    3, None, "Cavalry I"),
        (1910, "Supported Cavalry",                 600,  300,   0,   2, 1000, 2000,    0,    3, None, "Cavalry I"),
        (1918, "Mounted Rifle Cavalry",             800,  300,   0,   2, 1000, 2000,    0,    3, None, "Cavalry III"),
        (1930, "Modern Cavalry",                   1000,  300,   0,   2, 1000, 2000,    0,    3, None, "Cavalry V"),
    ],
    "militia": [
        #  YR, NAME,                                 HP,  ATK, DEF, SPD,  MAT,  MAN, FUEL, TIME, BOMB, ART
        (1800, "Local Militia",                     200,   12,   0,   1,  100, 1000,    0,    1, None, "Militia I"),
        (1840, "Organized Militia",                 280,   20,   0,   1,  150, 1000,    0,    1, None, "Militia I"),
        (1870, "Reserve Infantry",                  360,   32,   0,   1,  210, 1000,    0,    1, None, "Militia I"),
        (1900, "Modern Militia",                    440,   44,   0,   1,  270, 1000,    0,    1, None, "Militia I"),
        (1915, "Rifle Militia",                     600,   60,   0,   1,  300, 1000,    0,    1, None, "Militia II"),
        (1935, "Support-Weapon Militia",           1000,  100,   0,   1,  300, 1000,    0,    1, None, "Militia VI"),
        (1955, "Self-Loading Rifle Militia",       1400,  140,   0,   1,  300, 1000,    0,    1, None, "Militia X"),
        (1975, "Assault-Rifle Militia",            1800,  180,   0,   1,  300, 1000,    0,    1, None, "Militia XIV"),
        (1995, "Radio-Equipped Militia",           2200,  220,   0,   1,  300, 1000,    0,    1, None, "Militia XVIII"),
        (2015, "Optics-Equipped Militia",          2600,  260,   0,   1,  300, 1000,    0,    1, None, "Militia XXII"),
        (2035, "Drone-Supported Militia",          3000,  300,   0,   1,  300, 1000,    0,    1, None, "Militia XXVI"),
    ],
    "artillery": [
        #  YR, NAME,                                 HP,  ATK, DEF, SPD,  MAT,  MAN, FUEL, TIME, BOMB, ART
        (1800, "Smoothbore Artillery",               60,   50,   0,   1,  450,  500,    0,    2,   50, "Artillery I"),
        (1830, "Improved Field Artillery",           65,   60,   0,   1,  650,  500,    0,    2,   60, "Artillery I"),
        (1850, "Rifled Artillery",                   75,   70,   0,   1,  850,  500,    0,    2,   70, "Artillery I"),
        (1870, "Breech-Loading Artillery",           80,   80,   0,   1, 1050,  500,    0,    2,   80, "Artillery I"),
        (1890, "Quick-Firing Artillery",             90,   90,   0,   1, 1250,  500,    0,    2,   90, "Artillery I"),
        (1900, "Recoil-System Artillery",            95,  110,   0,   1, 1400,  500,    0,    2,  110, "Artillery I"),
        (1915, "Indirect-Fire Artillery",           150,  180,   0,   1, 1600,  500,    0,    2,  180, "Artillery II"),
        (1930, "Modern Field Artillery",            300,  360,   0,   1, 1900,  500,    0,    2,  360, "Artillery V"),
        (1940, "Radio-Coordinated Artillery",       400,  480,   0,   1, 2100,  500,    0,    2,  480, "Artillery VII"),
        (1955, "Advanced-Ammunition Artillery",     550,  660,   0,   1, 2400,  500,    0,    2,  660, "Artillery X"),
        (1975, "Computer-Assisted Artillery",       750,  900,   0,   1, 2800,  500,    0,    2,  900, "Artillery XIV"),
        (1995, "Digital Fire-Control Artillery",    950, 1140,   0,   1, 3200,  500,    0,    2, 1140, "Artillery XVIII"),
        (2010, "Precision-Guided Artillery",       1100, 1320,   0,   1, 3500,  500,    0,    2, 1320, "Artillery XXI"),
        (2025, "Sensor-Linked Artillery",          1250, 1500,   0,   1, 3800,  500,    0,    2, 1500, "Artillery XXIV"),
        (2040, "Automated Fire-Control Artillery", 1400, 1680,   0,   1, 4100,  500,    0,    2, 1680, "Artillery XXVII"),
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
    base = dict(zip(EQUIPMENT_COLUMNS.values(), stage[2:], strict=True))
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
UNIT_SECTIONS = [
    [
        equipment_family("Infantry Type", "infantry_type"),
        # Vehicle variants share infantry research and retain their separate unlocks.
        equipment_family("Motorized Infantry Type", "infantry_type"),
        equipment_family("Mechanized Infantry Type", "infantry_type"),
        equipment_family("Infantry Fighting Vehicle Type", "infantry_type"),
        equipment_family("Cavalry", "cavalry"),
        equipment_family("Militia", "militia"),
        # Fragile in a straight fight - its damage is meant to come from bombarding
        # an adjacent tile (see c.BOMBARDMENT_UNITS) rather than from stacking up.
        # Field and heavy artillery share the same equipment stages.
        # Direct attack and bombardment use separate fields for independent tuning.
        equipment_family("Artillery", "artillery"),
        equipment_family("Heavy Artillery", "artillery"),
    ],
    [
        UnitFamily("WW1 Tank", single(), {"health": 3000, "attack": 1500, "defense": 100, "speed": 1, "cost_materials": 6000, "cost_manpower": 1000, "cost_fuel": 300, "production_time": 6}),
        UnitFamily("WW1 Armored Car", single(), {"health": 1000, "attack": 300, "defense": 50, "speed": 2, "cost_materials": 3000, "cost_manpower": 1000, "cost_fuel": 100, "production_time": 4}),
        # speed steps: I=2, II-IV=3, V+=4
        UnitFamily("Armored Car", roman_suffixes(34), {"health": linear(1000, 100), "attack": linear(400, 100), "defense": linear(60, 10), "speed": piecewise([(0, 2, 0), (1, 3, 0), (4, 4, 0)]), "cost_materials": linear(3000, 200), "cost_manpower": const(1000), "cost_fuel": linear(100, 5), "production_time": const(4)}),
        # speed steps: I-III=2, IV+=3
        UnitFamily("Light Tank", roman_suffixes(34), {"health": linear(1800, 200), "attack": linear(1200, 150), "defense": linear(80, 10), "speed": piecewise([(0, 2, 0), (3, 3, 0)]), "cost_materials": linear(5000, 500), "cost_manpower": const(1000), "cost_fuel": linear(150, 5), "production_time": const(5)}),
        UnitFamily("Medium Tank", roman_suffixes(4), {"health": linear(2500, 500), "attack": linear(2400, 600), "defense": linear(150, 25), "speed": const(2), "cost_materials": linear(9000, 1000), "cost_manpower": const(1000), "cost_fuel": linear(200, 10), "production_time": const(6)}),
        UnitFamily("Heavy Tank", roman_suffixes(4), {"health": linear(3000, 500), "attack": linear(3000, 500), "defense": linear(350, 50), "speed": const(1), "cost_materials": linear(12000, 1000), "cost_manpower": const(1000), "cost_fuel": linear(200, 10), "production_time": const(6)}),
        UnitFamily("Super Heavy Tank", roman_suffixes(5), {"health":  const(5000), "attack":  const(5000), "defense": linear(550, 50), "speed": const(1), "cost_materials": linear(16000, 2000), "cost_manpower": const(1000), "cost_fuel": linear(240, 20), "production_time": const(6)}),
        # Can bombard an adjacent tile (see c.BOMBARDMENT_UNITS); bombard_attack
        # is tracked separately from melee "attack" so the two stay tunable independently.
        UnitFamily("Landkreuzer P.1000 Ratte", single(), {"health": 10000, "attack": 6000, "defense": 400, "bombard_attack": 1000, "speed": 1, "cost_materials": 50000, "cost_manpower": 2000, "cost_fuel": 1000, "production_time": 10}, division_suffix="1000"),
        UnitFamily("Landkreuzer P.1500 Monster", single(), {"health": 15000, "attack": 8000, "defense": 500, "bombard_attack": 1200, "speed": 1, "cost_materials": 60000, "cost_manpower": 2000, "cost_fuel": 1200, "production_time": 12}, division_suffix="1500"),
        # Simmilar stats to the Landkreuzer P.1500 Monster but reaches 3 tiles instead
        # of 2 (see c.BOMBARDMENT_UNITS) - the endgame answer to its siege role.
        UnitFamily("Railgun", single(), {"health": 10000, "attack": 10000, "defense": 500, "bombard_attack": 10000, "speed": 1, "cost_materials": 80000, "cost_manpower": 2000, "cost_fuel": 3000, "production_time": 10}),
        UnitFamily("Main Battle Tank", roman_suffixes(22), {"health": linear(5000, 500), "attack": linear(5000, 500), "defense": linear(250, 25), "speed": const(2), "cost_materials": linear(16000, 1000), "cost_manpower": const(1000), "cost_fuel": linear(240, 10), "production_time": const(6)}),
        # Siege pieces: reach 2 tiles instead of Artillery's 1 (see c.BOMBARDMENT_UNITS).
        # Two standalone guns (not a leveled family) - stats equal the old 5-level
        # Railroad Gun's level 1 and level 5 respectively.
        # Bombardment damage, tracked separately from melee "attack" so the
        # two can be tuned independently. Currently mirrors attack 1:1.
        UnitFamily("WW1 Railroad Gun", single(), {"health": 1200, "attack": 500, "bombard_attack": 500, "defense": 0, "speed": 1, "cost_materials": 5000, "cost_manpower": 1000, "cost_fuel": 0, "production_time": 6}),
        UnitFamily("WW2 Railroad Gun", single(), {"health": 2000, "attack": 800, "bombard_attack": 800, "defense": 0, "speed": 1, "cost_materials": 8000, "cost_manpower": 1000, "cost_fuel": 0, "production_time": 6}),
    ],
    [
        UnitFamily("Carrack", single(), {"health": 1000, "attack": 400, "defense": 0, "speed": 1, "cost_materials": 2000, "cost_manpower": 500, "cost_fuel": 0, "production_time": 4}, naval_unit=True),
        UnitFamily("Ironclad", single(), {"health": 2000, "attack": 800, "defense": 200, "speed": 1, "cost_materials": 8000, "cost_manpower": 1000, "cost_fuel": 100, "production_time": 6}, naval_unit=True),
        UnitFamily("Pre-Dreadnought", single(), {"health": 3000, "attack": 1200, "defense": 300, "speed": 1, "cost_materials": 12000, "cost_manpower": 2000, "cost_fuel": 250, "production_time": 8}, naval_unit=True),
        # Can bombard an adjacent tile (see c.BOMBARDMENT_UNITS); bombard_attack
        # is tracked separately from melee "attack" so the two stay tunable independently.
        UnitFamily("Dreadnought", single(), {"health": 4000, "attack": 2400, "defense": 400, "speed": 1, "bombard_attack": 300, "cost_materials": 20000, "cost_manpower": 2000, "cost_fuel": 300, "production_time": 10}, naval_unit=True),
        UnitFamily("Battleship", single(), {"health": 6000, "attack": 4000, "defense": 600, "speed": 1, "bombard_attack": 500, "cost_materials": 20000, "cost_manpower": 2000, "cost_fuel": 400, "production_time": 10}, naval_unit=True),
        UnitFamily("Destroyer", roman_suffixes(36), {"health": linear(2400, 400), "attack": linear(1200, 300), "defense": linear(200, 20), "speed": const(1), "cost_materials": linear(10000, 500), "cost_manpower": const(1000), "cost_fuel": linear(250, 5), "production_time": const(8)}, naval_unit=True),
        # attack climbs 300/level through IX, jumps to 4000 at X, then 200/level
        # "attack": piecewise([(0, 1200, 300), (9, 4000, 200)]),
        UnitFamily("Submarine", roman_suffixes(36), {"health": linear(1200, 200), "attack": linear(600, 100), "defense": const(0), "speed": const(1), "cost_materials": linear(8000, 400), "cost_manpower": const(1000), "cost_fuel": linear(150, 5), "production_time": const(6)}, naval_unit=True),
        # Can bombard an adjacent tile (see c.BOMBARDMENT_UNITS); bombard_attack
        # is tracked separately from melee "attack" so the two stay tunable independently.
        UnitFamily("Aircraft Carrier", roman_suffixes(25), {"health": linear(800, 200), "attack": linear(600, 120), "defense": linear(200, 20), "bombard_attack": linear(600, 120), "speed": const(1), "cost_materials": linear(20000, 1000), "cost_manpower": const(2000), "cost_fuel": linear(500, 25), "production_time": const(10)}, naval_unit=True),
    ],
    [
        UnitFamily('Biplane Fighter', roman_suffixes(5), {'health': linear(2000, 100), 'attack': linear(120, 20), 'defense': 0, 'speed': 1, 'cost_materials': 1000, 'cost_manpower': 500, 'cost_fuel': 60, 'production_time': 2, 'production_group': 'Air', 'air_role': 'fighter', 'air_range_px': linear(60, 5), 'air_attack_multiplier': 10}),
        UnitFamily('Biplane Bomber', roman_suffixes(5), {'health': linear(3000, 500), 'attack': linear(600, 100), 'defense': 0, 'speed': 1, 'cost_materials': 2000, 'cost_manpower': 500, 'cost_fuel': 80, 'production_time': 3, 'production_group': 'Air', 'air_role': 'bomber', 'air_range_px': linear(80, 10), 'air_damages_forts': True}),
        UnitFamily('Zeppelin', single(), {'health': 3000, 'attack': 300, 'defense': 0, 'speed': 1, 'cost_materials': 2000, 'cost_manpower': 500, 'cost_fuel': 60, 'production_time': 4, 'production_group': 'Air', 'air_role': 'bomber', 'air_range_px': 120, 'air_damages_forts': True}),
        UnitFamily('Monoplane Fighter', roman_suffixes(5), {'health': linear(3000, 200), 'attack': linear(250, 50), 'defense': linear(50, 10), 'speed': 1, 'cost_materials': 3000, 'cost_manpower': 500, 'cost_fuel': 100, 'production_time': 3, 'production_group': 'Air', 'air_role': 'fighter', 'air_range_px': linear(100, 5), 'air_attack_multiplier': 8}),
        UnitFamily('Monoplane Bomber', roman_suffixes(5), {'health': linear(5000, 200), 'attack': linear(1000, 100), 'defense': linear(120, 20), 'speed': 1, 'cost_materials': linear(4000, 400), 'cost_manpower': 500, 'cost_fuel': 120, 'production_time': 4, 'production_group': 'Air', 'air_role': 'bomber', 'air_range_px': linear(120, 20), 'air_damages_forts': True}),
        UnitFamily('Monoplane Transport', roman_suffixes(3), {'health': 1000, 'attack': 0, 'defense': 0, 'speed': 1, 'cost_materials': linear(9000, 500), 'cost_manpower': 1000, 'cost_fuel': 200, 'production_time': 4, 'production_group': 'Air', 'air_role': 'transport', 'air_range_px': linear(60, 10), 'air_transport_capacity': 1}),
        UnitFamily('V1 Flying Bomb', single(), {'health': 1000, 'attack': 800, 'defense': 0, 'speed': 1, 'cost_materials': 2000, 'cost_manpower': 0, 'cost_fuel': 60, 'production_time': 2, 'production_group': 'Air', 'air_role': 'strike', 'air_range_px': 200, 'air_consumable': True, 'air_damages_forts': True}),
        UnitFamily('V2 Rocket', single(), {'health': 2000, 'attack': 1200, 'defense': 0, 'speed': 1, 'cost_materials': 4000, 'cost_manpower': 0, 'cost_fuel': 80, 'production_time': 4, 'production_group': 'Air', 'air_role': 'strike', 'air_range_px': 300, 'air_consumable': True, 'air_interception_immune': True, 'air_damages_forts': True}),
        UnitFamily('Jet Fighter', roman_suffixes(26), {'health': linear(4000, 200), 'attack':  linear(1000, 100), 'defense':  linear(100, 20), 'speed': 1, 'cost_materials':  linear(5000, 200), 'cost_manpower': 500, 'cost_fuel': linear(160, 10), 'production_time': 4, 'production_group': 'Air', 'air_role': 'fighter', 'air_range_px': linear(200, 5), 'air_attack_multiplier': 4}),
        UnitFamily('Jet Bomber', roman_suffixes(20), {'health': linear(6000, 200), 'attack':  linear(1600, 200), 'defense':  linear(200, 20), 'speed': 1, 'cost_materials':  linear(6000, 500), 'cost_manpower': 500, 'cost_fuel': linear(160, 20), 'production_time': 6, 'production_group': 'Air', 'air_role': 'bomber', 'air_range_px': linear(300, 10), 'air_damages_forts': True}),
        UnitFamily('Jet Transport', roman_suffixes(20), {'health': linear(2000, 200), 'attack': 0, 'defense': 0, 'speed': 1, 'cost_materials': linear(25000, 1000), 'cost_manpower': 1000, 'cost_fuel': 500, 'production_time': 6, 'production_group': 'Air', 'air_role': 'transport', 'air_range_px': linear(100, 20), 'air_transport_capacity': 2}),
    ],
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


BUILDING_CHAINS = [
    BuildingChain(
        base_name="Basic Factory",
        # NOTE: req is the literal string "null" here (not JSON null) - a
        # pre-existing quirk in the data file, preserved intentionally.
        base_req="null",
        base_stats={
            # cost_* stay 0 -- Basic Factory cost is computed dynamically from
            # factory count in queries.get_building_cost(), not read from here.
            "time": 20, "group": "industry", "cost_materials": 0, "cost_manpower": 0,
            "cost_fuel": 0, "prod_materials": 200, "prod_manpower": 0, "prod_fuel": 0,
        },
        level_prefix="Factory Lvl",
        count=25,
        stats={
            "time": const(12), "group": const("industry"), "cost_materials": const(30000),
            "cost_manpower": const(0), "cost_fuel": const(1000),
            "prod_materials": lambda n: 100 * n + 500, "prod_manpower": const(0),
            "prod_fuel": lambda n: 10 * n,
        },
    ),
    BuildingChain(
        base_name="Basic Recruitment Center",
        base_req=None,
        base_stats={
            "time": 6, "group": "recruitment", "cost_materials": 2500, "cost_manpower": 0,
            "cost_fuel": 0, "prod_materials": 0, "prod_manpower": 50, "prod_fuel": 0,
        },
        level_prefix="Recruitment Building Lvl",
        count=50,
        stats={
            "time": const(6), "group": const("recruitment"), "cost_materials": const(5000),
            "cost_manpower": const(0), "cost_fuel": const(0), "prod_materials": const(0),
            "prod_manpower": lambda n: 100 * n, "prod_fuel": const(0),
        },
    ),
    BuildingChain(
        base_name="Fort Lvl 1",
        base_req=None,
        base_stats={
            "time": 1, "group": "fortification", "cost_materials": 5000,
            "cost_manpower": 0, "cost_fuel": 0, "prod_materials": 0,
            "prod_manpower": 0, "prod_fuel": 0,
        },
        level_prefix="Fort Lvl",
        count=c.FORT_MAX_LEVEL,
        skip_generated_base=True,
        stats={
            "time": const(1), "group": const("fortification"),
            "cost_materials": lambda n: 4000 + (1000 * n),
            "cost_manpower": const(0), "cost_fuel": const(0),
            "prod_materials": const(0), "prod_manpower": const(0),
            "prod_fuel": const(0),
        },
    ),
]


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
RESEARCH_SECTIONS = [
    [
        ("infantry_type", extend_infantry_research("infantry_type", { "category": "INFANTRY", "cost": 900, "req": {}})),
        ("cavalry", extend_infantry_research("cavalry", { "category": "INFANTRY", "cost": 1200, "req": {}})),
        ("militia", extend_infantry_research("militia", { "category": "INFANTRY", "cost": 600, "req": {}})),
        ("artillery", extend_infantry_research("artillery", { "category": "INFANTRY", "cost": 900, "req": {}})),
        # One-time unlocks rather than leveled techs: owning them lets a nation build
        # Motorized/Mechanized Infantry up to whatever year its own infantry_type
        # research has reached (see queries.get_infantry_family_year), instead of
        # requiring a separate research track for each vehicle family.
        ("trucks", {"category": "INFANTRY", "max_lvl": 1, "cost": 1800, "req": {"cavalry": len(EQUIPMENT_STAGES["cavalry"])}, "years": years_range(1930, 1, 1)}),
        ("armored_personnel_carriers", {"category": "INFANTRY", "max_lvl": 1, "cost": 1800, "req": {"trucks": 1}, "years": years_range(1940, 1, 1)}),
        ("infantry_fighting_vehicle", {"category": "INFANTRY", "max_lvl": 1, "cost": 1800, "req": {"armored_personnel_carriers": 1}, "years": years_range(1950, 1, 1)}),
    ],
    [
        ("civilian_car", {"category": "TANKS", "max_lvl": 1, "cost": 2400, "req": {}, "years": years_range(1910, 1, 1)}),
        ("ww1_armored_car", {"category": "TANKS", "max_lvl": 1, "cost": 2400, "req": {"civilian_car": 1}, "years": years_range(1912, 1, 1)}),
        ("armored_car", {"category": "TANKS", "max_lvl": 34, "cost": 2400, "req": {"ww1_armored_car": 1}, "years": years_range(1916, 4, 34)}),
    ],
    [
        ("ww1_tank", {"category": "TANKS", "max_lvl": 1, "cost": 2400, "req": {"ww1_armored_car": 1}, "years": years_range(1914, 1, 1)}),
        ("light_tank", {"category": "TANKS", "max_lvl": 34, "cost": 2400, "req": {"ww1_tank": 1}, "years": years_range(1918, 4, 34)}),
        ("medium_tank", {"category": "TANKS", "max_lvl": 4, "cost": 2400, "req": {"light_tank": 1}, "years": years_range(1925, 5, 4)}),
        ("heavy_tank", {"category": "TANKS", "max_lvl": 4, "cost": 2400, "req": {"medium_tank": 1}, "years": years_range(1929, 4, 4)}),
        ("super_heavy_tank", {"category": "TANKS", "max_lvl": 5, "cost": 2400, "req": {"heavy_tank": 4}, "years": years_range(1945, 4, 5)}),
        ("landkreuzer_p1000_ratte", {"category": "TANKS", "max_lvl": 1, "cost": 3000, "req": {"ww2_railroad_gun": 1}, "years": years_range(1944, 6, 1)}),
        ("landkreuzer_p1500_monster", {"category": "TANKS", "max_lvl": 1, "cost": 3600, "req": {"landkreuzer_p1000_ratte": 1}, "years": years_range(1956, 8, 1)}),
        ("electromagnetic_launcher", {"category": "TANKS", "max_lvl": 1, "cost": 3000, "req": {}, "years": years_range(1980, 1, 1)}),
        ("railgun", {"category": "TANKS", "max_lvl": 1, "cost": 3600, "req": {"electromagnetic_launcher": 1}, "years": years_range(2030, 1, 1)}),
        ("main_battle_tank", {"category": "TANKS", "max_lvl": 22, "cost": 2400, "req": {"OR": [{"medium_tank": 4}, {"heavy_tank": 4}]}, "years": years_range(1945, 5, 22)}),
        ("ww1_railroad_gun", {"category": "TANKS", "max_lvl": 1, "cost": 2400, "req": {"ww1_tank": 1}, "years": years_range(1918, 1, 1)}),
        ("ww2_railroad_gun", {"category": "TANKS", "max_lvl": 1, "cost": 2400, "req": {"AND": [{"heavy_tank": 1}, {"ww1_railroad_gun": 1}]}, "years": years_range(1932, 1, 1)}),
    ],
    [
        ("carrack", {"category": "NAVY", "max_lvl": 1, "cost": 600, "req": {}, "years": [1800]}),
        ("ironclad", {"category": "NAVY", "max_lvl": 1, "cost": 2400, "req": {"carrack": 1}, "years": [1860]}),
        ("pre-dreadnought", {"category": "NAVY", "max_lvl": 1, "cost": 2400, "req": {"ironclad": 1}, "years": [1880]}),
        ("dreadnought", {"category": "NAVY", "max_lvl": 1, "cost": 2400, "req": {"pre-dreadnought": 1}, "years": years_range(1900, 1, 1)}),
        ("battleship", {"category": "NAVY", "max_lvl": 1, "cost": 2400, "req": {"dreadnought": 1}, "years": years_range(1920, 1, 1)}),
        ("destroyer", {"category": "NAVY", "max_lvl": 36, "cost": 2400, "req": {"dreadnought": 1}, "years": years_range(1910, 4, 36)}),
        ("aircraft_carrier", {"category": "NAVY", "max_lvl": 25, "cost": 2400, "req": {"battleship": 1}, "years": years_range(1930, 5, 25)}),
        ("submarine", {"category": "NAVY", "max_lvl": 36, "cost": 2400, "req": {"dreadnought": 1}, "years": years_range(1910, 4, 36)}),
    ],
    [
        ("basic_factory", {"category": "INDUSTRY", "max_lvl": 1, "cost": 1200, "req": {}, "years": years_range(1800, 1, 1)}),
        ("waltham_system", {"category": "INDUSTRY", "display_name": "Waltham System", "max_lvl": 1, "cost": 1200, "req": {"basic_factory": 1}, "years": [1815], "building_output_bonuses": [{"building_families": ["Basic Factory"], "flat_outputs": {"materials": 100}}]}),
        ("metal_shaper", {"category": "INDUSTRY", "display_name": "Metal Shaper", "max_lvl": 1, "cost": 1200, "req": {"waltham_system": 1}, "years": [1835]}),
        ("steam_hammer", {"category": "INDUSTRY", "display_name": "Steam Hammer", "max_lvl": 1, "cost": 1200, "req": {"metal_shaper": 1}, "years": [1840]}),
        ("bessemer_process", {"category": "INDUSTRY", "display_name": "Bessemer Process", "max_lvl": 1, "cost": 1200, "req": {"steam_hammer": 1}, "years": [1855], "building_output_bonuses": [{"building_families": ["Basic Factory"], "flat_outputs": {"materials": 200}}]}),
        ("electricity", {"category": "INDUSTRY", "display_name": "Electricity", "max_lvl": 1, "cost": 1200, "req": {"bessemer_process": 1}, "years": [1870]}),
        ("lightbulb", {"category": "INDUSTRY", "display_name": "Lightbulb", "max_lvl": 1, "cost": 1200, "req": {"electricity": 1}, "years": [1880]}),
        ("assembly_line", {"category": "INDUSTRY", "display_name": "Assembly Line", "max_lvl": 1, "cost": 1200, "req": {"factory": 1}, "years": [1905], "building_output_bonuses": [{"building_families": ["Basic Factory", "Factory"], "outputs": {"materials": 0.5}}]}),
        ("conveyor_belt", {"category": "INDUSTRY", "display_name": "Conveyor Belt", "max_lvl": 1, "cost": 1200, "req": {"factory": 2}, "years": [1915], "building_output_bonuses": [{"building_families": ["Basic Factory", "Factory"], "outputs": {"materials": 0.5}}]}),
        ("machine_tools", {"category": "INDUSTRY", "display_name": "Machine Tools", "max_lvl": 1, "cost": 1200, "req": {"factory": 4}, "years": [1935]}),
        ("just_in_time_manufacturing", {"category": "INDUSTRY", "display_name": "Just In Time Manufacturing", "max_lvl": 1, "cost": 1200, "req": {"factory": 5}, "years": [1945], "building_output_bonuses": [{"building_families": ["Basic Factory", "Factory"], "outputs": {"materials": 0.2}}]}),
        ("industrial_robot", {"category": "INDUSTRY", "display_name": "Industrial Robot", "max_lvl": 1, "cost": 1200, "req": {"factory": 6}, "years": [1955]}),
        ("stanford_arm", {"category": "INDUSTRY", "display_name": "Stanford Arm", "max_lvl": 1, "cost": 1200, "req": {"factory": 7}, "years": [1965]}),
        ("asea_irb_6", {"category": "INDUSTRY", "display_name": "ASEA IRB 6", "max_lvl": 1, "cost": 1200, "req": {"factory": 8}, "years": [1975]}),
        ("computer_numerical_control", {"category": "INDUSTRY", "display_name": "Computer Numerical Control", "max_lvl": 1, "cost": 1200, "req": {"factory": 9}, "years": [1985]}),
        ("3d_printing", {"category": "INDUSTRY", "display_name": "3D Printing", "max_lvl": 1, "cost": 1200, "req": {"factory": 10}, "years": [1995]}),
        ("internet_of_things", {"category": "INDUSTRY", "display_name": "Internet of Things", "max_lvl": 1, "cost": 1200, "req": {"factory": 11}, "years": [2005]}),
        ("industry_4_0", {"category": "INDUSTRY", "display_name": "Industry 4.0", "max_lvl": 1, "cost": 1200, "req": {"factory": 12}, "years": [2015]}),
        ("industry_5_0", {"category": "INDUSTRY", "display_name": "Industry 5.0", "max_lvl": 1, "cost": 1200, "req": {"factory": 13}, "years": [2025]}),
        ("factory", {"category": "INDUSTRY", "max_lvl": 25, "cost": 1200, "req": {"lightbulb": 1}, "level_reqs": {"2": {"assembly_line": 1}, "3": {"conveyor_belt": 1}, "5": {"machine_tools": 1}, "6": {"just_in_time_manufacturing": 1}, "7": {"industrial_robot": 1}, "8": {"stanford_arm": 1}, "9": {"asea_irb_6": 1}, "10": {"computer_numerical_control": 1}, "11": {"3d_printing": 1}, "12": {"internet_of_things": 1}, "13": {"industry_4_0": 1}, "14": {"industry_5_0": 1}}, "years": years_range(1900, 10, 25)}),
        ("bergius_process", {"category": "INDUSTRY", "max_lvl": 1, "cost": 1200, "req": {}, "years": years_range(1910, 1, 1)}),
        ("fuel_refining", {"category": "INDUSTRY", "max_lvl": 50, "cost": 1200, "req": {"bergius_process": 1}, "years": years_range(1912, 2, 50)}),
        ("basic_recruitment", {"category": "INDUSTRY", "max_lvl": 1, "cost": 1200, "req": {}, "years": years_range(1910, 1, 1)}),
        ("recruitment_buildings", {"category": "INDUSTRY", "max_lvl": 50, "cost": 1200, "req": {"basic_recruitment": 1}, "years": years_range(1912, 2, 50)}),
        ("general_recruitment", {"category": "INDUSTRY", "max_lvl": 50, "cost": 900, "req": {"recruitment_buildings": "MATCH_LEVEL"}, "years": years_range(1913, 2, 50)}),
        ("resource_refining", {"category": "INDUSTRY", "max_lvl": 100, "cost": 900, "req": {}, "years": years_range(1911, 1, 100)}),
    ],
    [
        ('biplane', {'category': 'AIR', 'display_name': 'Biplane Fighter', 'max_lvl': 5, 'cost': 1200, 'req': {}, 'years': [1910, 1914, 1918, 1922, 1926]}),
        ('biplane_bomber', {'category': 'AIR', 'display_name': 'Biplane Bomber', 'max_lvl': 3, 'cost': 1800, 'req': {'biplane': 1}, 'years': [1915, 1920, 1925]}),
        ('zeppelin', {'category': 'AIR', 'display_name': 'Zeppelin', 'max_lvl': 1, 'cost': 1800, 'req': {}, 'years': [1910]}),
        ('piston_fighter', {'category': 'AIR', 'display_name': 'Monoplane Fighter', 'max_lvl': 5, 'cost': 1200, 'req': {'biplane': 5}, 'years': [1930, 1934, 1938, 1942, 1946]}),
        ('piston_bomber', {'category': 'AIR', 'display_name': 'Monoplane Bomber', 'max_lvl': 5, 'cost': 1800, 'req': {'biplane_bomber': 3}, 'years': [1930, 1935, 1940, 1945, 1950]}),
        ('monoplane_transport', {'category': 'AIR', 'display_name': 'Monoplane Transport', 'max_lvl': 3, 'cost': 1800, 'req': {'biplane_bomber': 3}, 'years': [1930, 1935, 1940]}),
        ('v1_flying_bomb', {'category': 'AIR', 'display_name': 'V1 Flying Bomb', 'max_lvl': 1, 'cost': 900, 'req': {}, 'years': [1940]}),
        ('v2_rocket', {'category': 'AIR', 'display_name': 'V2 Rocket', 'max_lvl': 1, 'cost': 1200, 'req': {'v1_flying_bomb': 1}, 'years': [1945]}),
        ('jet_engine', {'category': 'AIR', 'display_name': 'Jet Engine', 'max_lvl': 1, 'cost': 2400, 'req': {}, 'years': [1945]}),
        ('jet_fighter', {'category': 'AIR', 'display_name': 'Jet Fighter', 'max_lvl': 26, 'cost': 1800, 'req': {'piston_fighter': 5, 'jet_engine': 1}, 'years': years_range(1950, 4, 26)}),
        ('jet_bomber', {'category': 'AIR', 'display_name': 'Jet Bomber', 'max_lvl': 20, 'cost': 2400, 'req': {'piston_bomber': 5, 'jet_fighter': 1}, 'years': years_range(1955, 5, 20)}),
        ('jet_transport', {'category': 'AIR', 'display_name': 'Jet Transport', 'max_lvl': 20, 'cost': 2400, 'req': {'piston_bomber': 5}, 'years': years_range(1955, 5, 20)}),
    ],
]
