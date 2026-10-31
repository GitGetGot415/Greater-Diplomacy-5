"""Generate unit, building, and research libraries from dated stage rows.

Each unit or building row owns its base statistics, first year, and upgrades.
UPGRADES stores (levels, years between levels, per-level statistic increases).
Research reads the same dates and level counts. Research-only dates stay in RESEARCH_RECIPES.
Vehicle infantry and heavy artillery retain their shared variant rules.

Edit the rows, then run data/generators/generate_data.py.
The game reads only the generated JSON files in data/json/.
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

def rs(count):
    """Roman Suffixes"""
    return [c.ROMAN_NUMERALS[i] for i in range(1, count + 1)]


def yr(start, step, count):
    return [start + i * step for i in range(count)]


def table_values(columns, values):
    """Translate one editable row to full JSON field names and check its column count."""
    return dict(zip(columns.values(), values, strict=True))


def stage_stats(columns, values, increases, *, name):
    """Apply the shared per-level increases to a row's base statistics."""
    base = table_values(columns, values)
    if not isinstance(increases, dict) or any(key not in columns.values() for key in increases):
        raise ValueError(f"{name}: invalid upgrade statistics.")
    for field, delta in increases.items():
        if (isinstance(base[field], bool) or not isinstance(base[field], (int, float))
                or isinstance(delta, bool) or not isinstance(delta, (int, float))):
            raise ValueError(f"{name}: invalid increase for {field}.")
    return {field: lin(value, increases[field]) if field in increases else value
            for field, value in base.items() if value is not None}


def recipe_years(row):
    """Read dates from a unit or building stage without repeating its level count."""
    year, name = row[:2]
    levels, interval, _ = row[-2]
    if type(levels) is not int or levels <= 0:
        raise ValueError(f"{name}: invalid upgrade level count.")
    if type(interval) is not int or interval <= 0:
        raise ValueError(f"{name}: upgrade interval must be a positive integer.")
    if type(year) is not int:
        raise ValueError(f"{name}: research requires a first year.")
    return yr(year, interval, levels)


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
    def __init__(self, prefix, suffixes, stats, naval_unit=False, research_key=None, recruitment=None, division_suffix="", research_years=None):
        self.prefix = prefix
        self.division_suffix = division_suffix
        self.suffixes = suffixes
        self.stats = stats
        self.research_years = research_years
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
            name = f"{self.prefix} {suffix}"
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
            is_year = suffix.isdigit()
            tier = int(suffix) if is_year else i + 1
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
                                 "display_name": self.prefix if len(self.suffixes) == 1 else name,
                                 "research": research, "requirements": requirements,
                                 "tier_kind": "year" if is_year else "roman",
                                 "tier_label": suffix,
                                 "division_suffix": self.division_suffix or (suffix if len(self.suffixes) > 1 else ""),
                                 "recruitment": self.recruitment.copy(),
                                 "settings_family": self.prefix.removesuffix(" Type"),
                                 "production_group": self.production_group,
                                 # Cavalry stages do not count toward the older tank quota.
                                 "ai_tank": self.ai_tank and self.prefix != "Cavalry",
                                 "ai_force_category": (None if self.prefix == "Cavalry"
                                                       else self.ai_force_category)}
            out.append((name, entry))
        return out


# Defense multipliers use regular infantry's base attack, including for IFVs.
# Material multipliers leave manpower, fuel, and production time unchanged.
# Round generated variant statistics to remove floating-point artifacts.
INFANTRY_VARIANT_DECIMAL_PLACES = 10
INFANTRY_VARIANT_RULES = {
    "Motorized Infantry Type": {"speed": 2, "material_multiplier": 1.5, "attack_multiplier": 1, "defense_multiplier": None},
    "Mechanized Infantry Type": {"speed": 2, "material_multiplier": 2, "attack_multiplier": 1, "defense_multiplier": 0.2},
    "Infantry Fighting Vehicle Type": {"speed": 2, "material_multiplier": 3, "attack_multiplier": 1.5, "defense_multiplier": 0.3},
}

# Preserve the first existing vehicle stage independently of artwork selection.
INFANTRY_VARIANT_FIRST_YEAR = 1905
HEAVY_ARTILLERY_RULES = {"material_multiplier": 2, "attack_multiplier": 2, "bombard_multiplier": 2, "extra_production_time": 3}

# Each row defines its year, name, and base statistics.
# Variant statistics are generated. Infantry's cost_fuel applies only to vehicles.
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
}

# Row columns match EQUIPMENT_COLUMNS after the year and name.
# Equipment rows add (levels, years between levels, per-level stat increases).
# BOMB=None omits bombardment.
EQUIPMENT_STAGES = {
    "infantry_type": [
        #YR    NAME                           HP    ATK   DEF SPD MAT   MAN   FUEL TIME BOMB  UPGRADES
        (1800, "Flintlock Infantry",          600,  50,   0,  1,  200,  1000, 10,  2,   None, (5, 5, {'health': 10, 'attack': 2, 'cost_materials': 10})),
        (1825, "Percussion Infantry",         650,  60,   0,  1,  250,  1000, 10,  2,   None, (5, 5, {'health': 10, 'attack': 2, 'cost_materials': 10})),
        (1850, "Rifle-Musket Infantry",       700,  70,   0,  1,  300,  1000, 10,  2,   None, (3, 5, {'health': 20, 'attack': 2, 'cost_materials': 10})),
        (1865, "Breech-Loading Infantry",     760,  76,   0,  1,  330,  1000, 10,  2,   None, (2, 5, {'health': 20, 'attack': 2, 'cost_materials': 10})),
        (1875, "Metallic-Cartridge Infantry", 800,  80,   0,  1,  350,  1000, 10,  2,   None, (2, 5, {'health': 20, 'attack': 2, 'cost_materials': 15})),
        (1885, "Magazine-Rifle Infantry",     840,  84,   0,  1,  380,  1000, 10,  2,   None, (2, 5, {'health': 30, 'attack': 3, 'cost_materials': 20})),
        (1894, "Smokeless-Rifle Infantry",    900,  90,   0,  1,  420,  1000, 10,  2,   None, (2, 4, {'health': 40, 'attack': 5, 'cost_materials': 20})),
        (1902, "Supported Rifle Infantry",    980,  100,  0,  1,  460,  1000, 10,  2,   None, (3, 4, {'health': 40, 'attack': 10, 'cost_materials': 20})),
        (1914, "Trench Infantry",             1100, 140,  0,  1,  520,  1000, 15,  2,   None, (3, 4, {'health': 50, 'attack': 20, 'cost_materials': 30})),
        (1925, "Squad-Automatic Infantry",    1300, 200,  0,  1,  600,  1000, 25,  2,   None, (5, 3, {'health': 60, 'attack': 30, 'cost_materials': 30})),
        (1940, "Semi-Automatic Infantry",     1600, 350,  0,  1,  750,  1000, 40,  2,   None, (5, 3, {'health': 80, 'attack': 30, 'cost_materials': 30})),
        (1955, "Battle-Rifle Infantry",       2000, 500,  0,  1,  900,  1000, 55,  2,   None, (5, 3, {'health': 100, 'attack': 40, 'cost_materials': 30})),
        (1970, "Assault-Rifle Infantry",      2500, 700,  0,  1,  1050, 1000, 70,  2,   None, (5, 3, {'health': 100, 'attack': 40, 'cost_materials': 30})),
        (1985, "Night-Equipped Infantry",     3000, 900,  0,  1,  1200, 1000, 85,  2,   None, (5, 3, {'health': 100, 'attack': 40, 'cost_materials': 30})),
        (2000, "Optics-Equipped Infantry",    3500, 1100, 0,  1,  1350, 1000, 100, 2,   None, (5, 3, {'health': 100, 'attack': 50, 'cost_materials': 30})),
        (2015, "Networked Infantry",          4000, 1350, 0,  1,  1500, 1000, 115, 2,   None, (5, 3, {'health': 100, 'attack': 50, 'cost_materials': 40})),
        (2030, "Drone-Integrated Infantry",   4500, 1600, 0,  1,  1700, 1000, 130, 2,   None, (5, 2, {'health': 100, 'attack': 50, 'cost_materials': 40})),
        (2040, "Sensor-Integrated Infantry",  5000, 1850, 0,  1,  1900, 1000, 140, 2,   None, (56, 2, {'health': 100, 'attack': 50, 'cost_materials': 50})),
    ],
    "cavalry": [
        #YR    NAME                       HP    ATK  DEF SPD MAT   MAN   FUEL TIME BOMB  UPGRADES
        (1800, "Early Cavalry",           200,  300, 0,  2,  600,  2000, 0,   3,   None, (10, 5,{'health': 10, 'cost_materials': 10})),
        (1850, "Improved Cavalry",        300,  300, 0,  2,  700,  2000, 0,   3,   None, (5, 4, {'health': 20, 'cost_materials': 10})),
        (1870, "Breech-Loading Carbines", 500,  300, 0,  2,  750,  2000, 0,   3,   None, (5, 4, {'health': 20, 'cost_materials': 10})),
        (1890, "Magazine Carbines",       600,  300, 0,  2,  800,  2000, 0,   3,   None, (5, 4, {'health': 20, 'cost_materials': 20})),
        (1910, "Supported Cavalry",       700,  300, 0,  2,  900,  2000, 0,   3,   None, (2, 4, {'health': 50, 'cost_materials': 50})),
        (1918, "Mounted Rifle Cavalry",   800,  300, 0,  2,  1000, 2000, 0,   3,   None, (3, 4, {'health': 50, 'cost_materials': 50})),
        (1930, "Modern Cavalry",          1000, 300, 0,  2,  1200, 2000, 0,   3,   None, (6, 4, {'health': 100, 'cost_materials': 60})),
    ],
    "militia": [
        #YR    NAME                          HP    ATK  DEF SPD MAT  MAN   FUEL TIME BOMB  UPGRADES
        (1800, "Local Militia",              200,  20,  0,  1,  100, 1000, 0,   1,   None, (10, 5, {'health': 10, 'attack': 1, 'cost_materials': 5})),
        (1850, "Organized Militia",          300,  30,  0,  1,  150, 1000, 0,   1,   None, (10, 5, {'health': 20, 'attack': 2, 'cost_materials': 5})),
        (1900, "Modern Militia",             500,  50,  0,  1,  200, 1000, 0,   1,   None, (5, 4,  {'health': 30, 'attack': 4, 'cost_materials': 10})),
        (1920, "Rifle Militia",              750,  70,  0,  1,  250, 1000, 0,   1,   None, (5, 4,  {'health': 30, 'attack': 6, 'cost_materials': 10})),
        (1940, "Support-Weapon Militia",     900,  100, 0,  1,  300, 1000, 0,   1,   None, (5, 4,  {'health': 40, 'attack': 8, 'cost_materials': 10})),
        (1960, "Self-Loading Rifle Militia", 1100, 140, 0,  1,  350, 1000, 0,   1,   None, (5, 4,  {'health': 50, 'attack': 8, 'cost_materials': 10})),
        (1980, "Assault-Rifle Militia",      1350, 180, 0,  1,  400, 1000, 0,   1,   None, (5, 4,  {'health': 50, 'attack': 8, 'cost_materials': 10})),
        (2000, "Radio-Equipped Militia",     1600, 220, 0,  1,  450, 1000, 0,   1,   None, (5, 4,  {'health': 50, 'attack': 8, 'cost_materials': 10})),
        (2020, "Optics-Equipped Militia",    1850, 260, 0,  1,  500, 1000, 0,   1,   None, (5, 4,  {'health': 50, 'attack': 8, 'cost_materials': 20})),
        (2040, "Drone-Supported Militia",    2100, 300, 0,  1,  600, 1000, 0,   1,   None, (28, 4, {'health': 100, 'attack': 20, 'cost_materials': 50})),
    ],
    "artillery": [
        #YR    NAME                                HP    ATK   DEF SPD MAT   MAN  FUEL TIME BOMB  UPGRADES
        (1800, "Smoothbore Artillery",             60,   50,   0,  1,  400,  500, 0,   2,   50,   (5, 5, {'health': 1, 'attack': 2, 'bombard_attack': 2, 'cost_materials': 20})),
        (1825, "Improved Field Artillery",         65,   60,   0,  1,  500,  500, 0,   2,   60,   (5, 5, {'health': 1, 'attack': 2, 'bombard_attack': 2, 'cost_materials': 20})),
        (1850, "Rifled Artillery",                 70,   70,   0,  1,  600,  500, 0,   2,   70,   (5, 5, {'health': 2, 'attack': 2, 'bombard_attack': 2, 'cost_materials': 20})),
        (1875, "Breech-Loading Artillery",         80,   80,   0,  1,  700,  500, 0,   2,   80,   (3, 5, {'health': 5, 'attack': 5, 'bombard_attack': 5, 'cost_materials': 50})),
        (1890, "Quick-Firing Artillery",           100,  100,  0,  1,  850,  500, 0,   2,   90,   (2, 5, {'health': 10, 'attack': 10, 'bombard_attack': 10, 'cost_materials': 50})),
        (1900, "Recoil-System Artillery",          120,  120,  0,  1,  950,  500, 0,   2,   110,  (3, 5, {'health': 20, 'attack': 20, 'bombard_attack': 20, 'cost_materials': 50})),
        (1915, "Indirect-Fire Artillery",          180,  180,  0,  1,  1100, 500, 0,   2,   180,  (3, 5, {'health': 40, 'attack': 40, 'bombard_attack': 40, 'cost_materials': 50})),
        (1930, "Modern Field Artillery",           300,  300,  0,  1,  1250, 500, 0,   2,   300,  (2, 5, {'health': 50, 'attack': 50, 'bombard_attack': 50, 'cost_materials': 50})),
        (1940, "Radio-Coordinated Artillery",      400,  400,  0,  1,  1400, 500, 0,   2,   400,  (3, 5, {'health': 50, 'attack': 50, 'bombard_attack': 50, 'cost_materials': 50})),
        (1955, "Advanced-Ammunition Artillery",    550,  550,  0,  1,  1550, 500, 0,   2,   550,  (4, 5, {'health': 50, 'attack': 50, 'bombard_attack': 50, 'cost_materials': 50})),
        (1975, "Computer-Assisted Artillery",      750,  750,  0,  1,  1700, 500, 0,   2,   750,  (4, 5, {'health': 50, 'attack': 50, 'bombard_attack': 50, 'cost_materials': 50})),
        (1995, "Digital Fire-Control Artillery",   950,  950,  0,  1,  1850, 500, 0,   2,   950,  (3, 5, {'health': 50, 'attack': 50, 'bombard_attack': 50, 'cost_materials': 50})),
        (2010, "Precision-Guided Artillery",       1100, 1100, 0,  1,  2000, 500, 0,   2,   1100, (3, 5, {'health': 50, 'attack': 50, 'bombard_attack': 50, 'cost_materials': 50})),
        (2025, "Sensor-Linked Artillery",          1250, 1250, 0,  1,  2150, 500, 0,   2,   1250, (3, 5, {'health': 50, 'attack': 50, 'bombard_attack': 50, 'cost_materials': 50})),
        (2040, "Automated Fire-Control Artillery", 1400, 1400, 0,  1,  2300, 500, 0,   2,   1400, (28, 4, {'health': 100, 'attack': 100, 'bombard_attack': 100, 'cost_materials': 100})),
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
            entry["metadata"]["display_name"] = name
            entry["metadata"]["tier_label"] = label
            entry["metadata"]["tier_kind"] = "stage"
            result.append((name, entry))
        return result


def equipment_profile(prefix, stage):
    """Derive variant statistics from their base family profiles."""
    base = table_values(EQUIPMENT_COLUMNS, stage[2:])
    if base["bombard_attack"] is None:
        del base["bombard_attack"]
    profile = dict(base)
    if prefix in INFANTRY_VARIANT_RULES:
        rule = INFANTRY_VARIANT_RULES[prefix]
        profile.update(speed=rule["speed"],
                       cost_materials=round(base["cost_materials"] * rule["material_multiplier"], INFANTRY_VARIANT_DECIMAL_PLACES),
                       attack=round(base["attack"] * rule["attack_multiplier"], INFANTRY_VARIANT_DECIMAL_PLACES))
        if rule["defense_multiplier"] is not None:
            profile["defense"] = round(base["attack"] * rule["defense_multiplier"], INFANTRY_VARIANT_DECIMAL_PLACES)
    elif prefix == "Heavy Artillery":
        rule = HEAVY_ARTILLERY_RULES
        profile.update(cost_materials=base["cost_materials"] * rule["material_multiplier"],
                       attack=base["attack"] * rule["attack_multiplier"],
                       bombard_attack=base["bombard_attack"] * rule["bombard_multiplier"],
                       production_time=base["production_time"] + rule["extra_production_time"])
    elif prefix == "Infantry Type":
        profile["cost_fuel"] = 0
    return profile


def expanded_equipment_stages(tech):
    """Expand equipment upgrades into dated stages shared by research and units."""
    stages = EQUIPMENT_STAGES[tech]
    result = []
    for index, row in enumerate(stages):
        year, name, *values = row
        if len(values) == len(EQUIPMENT_COLUMNS):
            result.append(row)
            continue
        levels, interval, increases = values.pop()
        if type(levels) is not int or not 1 <= levels <= len(c.ROMAN_NUMERALS):
            raise ValueError(f"{name}: invalid upgrade level count.")
        if type(interval) is not int or interval <= 0:
            raise ValueError(f"{name}: upgrade interval must be a positive integer.")
        next_year = stages[index + 1][0] if index + 1 < len(stages) else c.END_YEAR + 1
        if year + (levels - 1) * interval >= next_year:
            raise ValueError(f"{name}: upgrades must end before the next stage and within the timeline.")
        generators = stage_stats(EQUIPMENT_COLUMNS, values, increases, name=name)
        for level in range(levels):
            stats = [generators[field](level) if callable(generators.get(field)) else generators.get(field)
                     for field in EQUIPMENT_COLUMNS.values()]
            result.append((year + interval * level, f"{name} {c.ROMAN_NUMERALS[level + 1]}", *stats))
    if any(first[0] >= second[0] for first, second in zip(result, result[1:])):
        raise ValueError(f"{tech}: equipment years must increase.")
    return result


def equipment_family(prefix, tech):
    """Generate one family from base stages and shared variant rules."""
    stages = [(stage[0], stage[1], equipment_profile(prefix, stage))
              for stage in expanded_equipment_stages(tech)
              if prefix not in INFANTRY_VARIANT_RULES or stage[0] >= INFANTRY_VARIANT_FIRST_YEAR]
    key = prefix.lower().replace(" ", "_")
    research_key = c.UNIT_TECH_KEY_OVERRIDES.get(key, tech)
    fields = UNIT_STAT_KEYS + [field for field in OPTIONAL_UNIT_STAT_KEYS if field in stages[0][2]]
    stats = {field: (lambda i, field=field: stages[i][2][field]) for field in fields}
    return EquipmentFamily(prefix, [str(year) for year, _, _ in stages], stats,
                           research_key=research_key,
                           research_years=[year for year, _, _ in stages],
                           stage_names=[label for _, label, _ in stages])


# Each row stores its year, name, base statistics, upgrades, and options.
# UPGRADES is (levels, years between levels, per-level statistic increases).
# A piecewise base value keeps a statistic's existing non-linear progression.
# None omits an optional statistic. OPTIONS contains naming and constructor settings.
UNIT_RECIPE_COLUMNS = EQUIPMENT_COLUMNS
AIR_RECIPE_COLUMNS = {
    **EQUIPMENT_COLUMNS,
    "ROLE": "air_role",
    "RNG": "air_range_px",
    "AAMULT": "air_attack_multiplier",
    "CONSUME": "air_consumable",
    "IMMUNE": "air_interception_immune",
    "FORT": "air_damages_forts",
    "CARGO": "air_transport_capacity",
}

CAR_SPD = piecewise([(0, 2, 0), (1, 3, 0), (4, 4, 0)])
LT_SPD = piecewise([(0, 2, 0), (3, 3, 0)])

# Every recruitable unit starts at level I. Older identifiers convert on load.
LAND_UNIT_RECIPES = [
    #YR    NAME                          HP     ATK    DEF  SPD      MAT    MAN   FUEL  TIME BOMB   UPGRADES                                                                                         OPTIONS
    (1914, 'WW1 Tank',                   3000,  1500,  100, 1,       6000,  1000, 300,  6,   None,  (1, 1, {}),                                                                                      {}),
    (1912, 'WW1 Armored Car',            1000,  300,   50,  2,       3000,  1000, 100,  4,   None,  (1, 1, {}),                                                                                      {}),
    (1916, 'Armored Car',                1000,  400,   60,  CAR_SPD, 3000,  1000, 100,  4,   None,  (59, 4, {'health': 100, 'attack': 100, 'defense': 10, 'cost_materials': 200, 'cost_fuel': 5}),   {}),
    (1918, 'Light Tank',                 1800,  1200,  80,  LT_SPD,  5000,  1000, 150,  5,   None,  (59, 4, {'health': 200, 'attack': 150, 'defense': 10, 'cost_materials': 500, 'cost_fuel': 5}),   {}),
    (1925, 'Medium Tank',                2500,  2400,  150, 2,       9000,  1000, 200,  6,   None,  (4, 5, {'health': 500, 'attack': 600, 'defense': 25, 'cost_materials': 1000, 'cost_fuel': 10}),  {}),
    (1929, 'Heavy Tank',                 3000,  3000,  350, 1,       12000, 1000, 200,  6,   None,  (4, 4, {'health': 500, 'attack': 500, 'defense': 50, 'cost_materials': 1000, 'cost_fuel': 10}),  {}),
    (1945, 'Super Heavy Tank',           5000,  5000,  550, 1,       16000, 1000, 240,  6,   None,  (5, 4, {'defense': 50, 'cost_materials': 2000, 'cost_fuel': 20}),                                {}),
    (1944, 'Landkreuzer P.1000 Ratte',   10000, 6000,  400, 1,       50000, 2000, 1000, 10,  1000,  (1, 1, {}),                                                                                      {'division_suffix': '1000'}),
    (1956, 'Landkreuzer P.1500 Monster', 15000, 8000,  500, 1,       60000, 2000, 1200, 12,  1200,  (1, 1, {}),                                                                                      {'division_suffix': '1500'}),
    (2030, 'Railgun',                    10000, 10000, 500, 1,       80000, 2000, 3000, 10,  10000, (1, 1, {}),                                                                                      {}),
    (1945, 'Main Battle Tank',           5000,  5000,  250, 2,       16000, 1000, 240,  6,   None,  (42, 5, {'health': 500, 'attack': 500, 'defense': 25, 'cost_materials': 1000, 'cost_fuel': 10}), {}),
    (1918, 'WW1 Railroad Gun',           1200,  500,   0,   1,       5000,  1000, 0,    6,   500,   (1, 1, {}),                                                                                      {}),
    (1932, 'WW2 Railroad Gun',           2000,  800,   0,   1,       8000,  1000, 0,    6,   800,   (1, 1, {}),                                                                                      {}),
]

NAVAL_UNIT_RECIPES = [
    #YR    NAME                HP    ATK   DEF  SPD MAT    MAN   FUEL TIME BOMB  UPGRADES                                                                                                                OPTIONS
    (1800, 'Carrack',          800,  400,  0,   1,  2000,  500,  0,   4,   None, (6, 10, {'health': 40, 'attack': 20, 'cost_materials': 100}),                                                           {}),
    (1860, 'Ironclad',         2000, 800,  200, 1,  6000,  1000, 100, 6,   None, (5, 4,  {'health': 200, 'attack': 50, 'defense': 20, 'cost_materials': 500, 'cost_fuel': 10}),                           {}),
    (1880, 'Pre-Dreadnought',  3000, 1200, 300, 1,  10000, 2000, 150, 8,   None, (5, 4,  {'health': 200, 'attack': 200, 'defense': 20, 'cost_materials': 1000, 'cost_fuel': 10}),                         {}),
    (1900, 'Dreadnought',      4000, 3000, 400, 1,  16000, 2000, 200, 10,  300,  (5, 4,  {'health': 400, 'attack': 100, 'defense': 40, 'cost_materials': 800, 'cost_fuel': 20, 'bombard_attack': 40}),    {}),
    (1920, 'Battleship',       6000, 3500, 600, 1,  20000, 2000, 300, 10,  500,  (6, 4,  {'attack': 100, 'cost_materials': 1000, 'cost_fuel': 20, 'bombard_attack': 40}),   {}),
    (1900, 'Destroyer',        2400, 1200, 200, 1,  8000,  1000, 250, 8,   None, (63, 4, {'health': 400, 'attack': 300, 'defense': 20, 'cost_materials': 500, 'cost_fuel': 5}),                          {}),
    (1900, 'Submarine',        1200, 600,  0,   1,  6000,  1000, 150, 6,   None, (63, 4, {'health': 200, 'attack': 100, 'cost_materials': 400, 'cost_fuel': 5}),                                         {}),
    (1920, 'Aircraft Carrier', 600,  300,  200, 1,  20000, 2000, 300, 10,  300,  (47, 5, {'health': 200, 'attack': 150, 'defense': 20, 'cost_materials': 1000, 'cost_fuel': 20, 'bombard_attack': 150}), {}),
]

AIR_UNIT_RECIPES = [
    #YR    NAME                   HP    ATK   DEF  SPD MAT    MAN   FUEL TIME BOMB  ROLE         RNG  AAMULT CONSUME IMMUNE FORT  CARGO UPGRADES                                                                                                            OPTIONS
    (1910, 'Biplane Fighter',     2000, 120,  0,   1,  1000,  500,  60,  2,   None, 'fighter',   60,  10,    None,   None,  None, None, (5, 4, {'health': 100, 'attack': 20, 'air_range_px': 5}),                                                           {}),
    (1915, 'Biplane Bomber',      3000, 600,  0,   1,  2000,  500,  80,  3,   None, 'bomber',    80,  None,  None,   None,  True, None, (5, 5, {'health': 500, 'attack': 100, 'air_range_px': 10}),                                                         {}),
    (1910, 'Zeppelin',            3000, 300,  0,   1,  2000,  500,  60,  4,   None, 'bomber',    120, None,  None,   None,  True, None, (1, 1, {}),                                                                                                         {}),
    (1930, 'Monoplane Fighter',   3000, 250,  50,  1,  3000,  500,  100, 3,   None, 'fighter',   100, 8,     None,   None,  None, None, (5, 4, {'health': 200, 'attack': 50, 'defense': 10, 'air_range_px': 5}),                                            {}),
    (1930, 'Monoplane Bomber',    5000, 1000, 120, 1,  4000,  500,  120, 4,   None, 'bomber',    120, None,  None,   None,  True, None, (5, 5, {'health': 200, 'attack': 100, 'defense': 20, 'cost_materials': 400, 'air_range_px': 20}),                   {}),
    (1930, 'Monoplane Transport', 1000, 0,    0,   1,  9000,  1000, 200, 4,   None, 'transport', 60,  None,  None,   None,  None, 1,    (3, 5, {'cost_materials': 500, 'air_range_px': 10}),                                                                {}),
    (1940, 'V1 Flying Bomb',      1000, 800,  0,   1,  2000,  0,    60,  2,   None, 'strike',    200, None,  True,   None,  True, None, (1, 1, {}),                                                                                                         {}),
    (1945, 'V2 Rocket',           2000, 1200, 0,   1,  4000,  0,    80,  4,   None, 'strike',    300, None,  True,   True,  True, None, (1, 1, {}),                                                                                                         {}),
    (1950, 'Jet Fighter',         4000, 1000, 100, 1,  5000,  500,  160, 4,   None, 'fighter',   200, 4,     None,   None,  None, None, (51, 4, {'health': 200, 'attack': 100, 'defense': 20, 'cost_materials': 200, 'cost_fuel': 10, 'air_range_px': 5}),  {}),
    (1955, 'Jet Bomber',          6000, 1600, 200, 1,  6000,  500,  160, 6,   None, 'bomber',    300, None,  None,   None,  True, None, (40, 5, {'health': 200, 'attack': 200, 'defense': 20, 'cost_materials': 500, 'cost_fuel': 20, 'air_range_px': 10}), {}),
    (1955, 'Jet Transport',       2000, 0,    0,   1,  25000, 1000, 500, 6,   None, 'transport', 100, None,  None,   None,  None, 2,    (40, 5, {'health': 200, 'cost_materials': 1000, 'air_range_px': 20}),                                               {}),
]


def unit_family(row, *, naval_unit=False, air=False):
    """Build units from one dated row without changing their existing identifiers."""
    _, prefix, *values, upgrades, options = row
    recipe_years(row)
    levels, _, increases = upgrades
    options = options.copy()
    suffixes = rs(levels)
    columns = AIR_RECIPE_COLUMNS if air else UNIT_RECIPE_COLUMNS
    stats = stage_stats(columns, values, increases, name=prefix)
    if air:
        stats["production_group"] = "Air"
    return UnitFamily(prefix, suffixes, stats, naval_unit=naval_unit, **options)


def unit_years(prefix):
    """Use the unit row's dates and level count for research."""
    for rows in (LAND_UNIT_RECIPES, NAVAL_UNIT_RECIPES, AIR_UNIT_RECIPES):
        for row in rows:
            if row[1] == prefix:
                return recipe_years(row)
    raise ValueError(f"Unknown unit recipe: {prefix}.")


def equipment_years(tech):
    """Read research dates from the named equipment stages."""
    return [row[0] for row in expanded_equipment_stages(tech)]


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
# Each group is one building chain. Each row owns its dates and statistics.
# Later entries require the previous building unless the row supplies an explicit req.
# None as the year marks a building without its own research track.
# The literal "null" requirement remains distinct from None.
# Basic Factory costs remain dynamic in queries.get_building_cost; its stored costs stay zero.
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

BUILDING_RECIPES = [
    [
        #YR    NAME             TIME GROUP       MAT    MAN FUEL  OUTMAT OUTMAN OUTFUEL UPGRADES                                            OPTIONS
        (1800, "Basic Factory", 20,  "industry", 0,     0,  0,    100,   0,     0,      (1, 1, {}),                                         {"numbered": False, "req": "null"}),
        (1900, "Factory Lvl",   12,  "industry", 30000, 0,  1000, 600,   0,     10,     (25, 10, {"prod_materials": 100, "prod_fuel": 10}), {}),
    ],
    [
        #YR    NAME                        TIME GROUP          MAT   MAN FUEL OUTMAT OUTMAN OUTFUEL UPGRADES                         OPTIONS
        (1800, "Basic Recruitment Center", 6,   "recruitment", 2500, 0,  0,   0,     50,    0,      (1, 1, {}),                      {"numbered": False}),
        (1805, "Recruitment Building Lvl", 6,   "recruitment", 5000, 0,  0,   0,     100,   0,      (35, 10, {"prod_manpower": 100}), {}),
    ],
    [
        #YR    NAME        TIME GROUP            MAT   MAN FUEL OUTMAT OUTMAN OUTFUEL UPGRADES                                         OPTIONS
        (None, "Fort Lvl", 1,   "fortification", 5000, 0,  0,   0,     0,     0,      (c.FORT_MAX_LEVEL, 1, {"cost_materials": 1000}), {}),
    ],
]


class BuildingChain:
    def __init__(self, stages):
        self.stages = stages

    def entries(self):
        out = []
        previous = None
        for _, prefix, *values, upgrades, options in self.stages:
            levels, _, increases = upgrades
            stats = stage_stats(BUILDING_RECIPE_COLUMNS, values, increases, name=prefix)
            for level in range(levels):
                name = f"{prefix} {level + 1}" if options.get("numbered", True) else prefix
                entry = {field: value(level) if callable(value) else value for field, value in stats.items()}
                # Keep req between group and costs in the generated file.
                ordered = {"time": entry.pop("time"), "group": entry.pop("group"),
                           "req": options.get("req", previous) if level == 0 else previous}
                ordered.update(entry)
                out.append((name, ordered))
                previous = name
        return out


def building_years(prefix):
    """Use the building stage's dates and level count for research."""
    for stages in BUILDING_RECIPES:
        for row in stages:
            if row[1] == prefix:
                return recipe_years(row)
    raise ValueError(f"Unknown building recipe: {prefix}.")


BUILDING_CHAINS = [BuildingChain(stages) for stages in BUILDING_RECIPES]


# ===========================================================================
# RESEARCH_TEMPLATE.JSON
# ===========================================================================
# Equipment research uses the named stages. Other tracks can use yr for regular intervals.
# Prerequisites, categories, and costs are literal tuning values.

def extend_infantry_research(tech, entry):
    """Use the same equipment stages for research and generated units."""
    stages = expanded_equipment_stages(tech)
    names = {str(i + 1): stage[1] for i, stage in enumerate(stages)}
    entry["years"] = [stage[0] for stage in stages]
    entry["max_lvl"] = len(entry["years"])
    entry["level_names"] = names
    entry["level_icons"] = names.copy()
    return entry


def flat_building_bonus(families, resource, amount):
    """Build a fixed output bonus for the specified building families."""
    return [{"building_families": families, "flat_outputs": {resource: amount}}]


def proportional_building_bonus(families, resource, amount):
    """Build a proportional output bonus for the specified building families."""
    return [{"building_families": families, "outputs": {resource: amount}}]


# Sections separated by a blank spacer line, matching the current file.
RESEARCH_RECIPE_COLUMNS = {"CAT": "category", "COST": "cost", "REQ": "req"}
RESEARCH_OPTION_COLUMNS = {"NAME": "display_name", "GATES": "level_reqs", "BONUS": "building_output_bonuses"}

FACTORY_LEVEL_GATES = {
    "2": {'assembly_line': 1},
    "3": {'conveyor_belt': 1},
    "4": {'continuous_assembly_line': 1},
    "5": {'machine_tools': 1},
    "6": {'just_in_time_manufacturing': 1},
    "7": {'industrial_robot': 1},
    "8": {'stanford_arm': 1},
    "9": {'asea_irb_6': 1},
    "10": {'computer_numerical_control': 1},
    "11": {'3d_printing': 1},
    "12": {'internet_of_things': 1},
    "13": {'industry_4_0': 1},
    "14": {'industry_5_0': 1},
}


MBT_REQ = {"OR": [{"medium_tank": 4}, {"heavy_tank": 4}]}
WW2_RAIL_REQ = {"AND": [{"heavy_tank": 1}, {"ww1_railroad_gun": 1}]}

IAC = {"industrial_air_compressor": 1}
GR = {"recruitment_buildings": "MATCH_LEVEL"}

# Unit and building dates come from their stage rows. Other dates stay in this table.
# Research level counts come from these dates.

RESEARCH_RECIPES = [
    [
        #YEARS                             ID                            CAT         COST  REQ                                OPTIONS
        (equipment_years("infantry_type"), "infantry_type",              "INFANTRY", 900,  {},                                {}),
        (equipment_years("cavalry"),       "cavalry",                    "INFANTRY", 1200, {},                                {}),
        (equipment_years("militia"),       "militia",                    "INFANTRY", 600,  {},                                {}),
        (equipment_years("artillery"),     "artillery",                  "INFANTRY", 900,  {},                                {}),
        ([1930],                           "trucks",                     "INFANTRY", 1800, {},                                {}),
        ([1940],                           "armored_personnel_carriers", "INFANTRY", 1800, {"trucks": 1},                     {}),
        ([1950],                           "infantry_fighting_vehicle",  "INFANTRY", 1800, {"armored_personnel_carriers": 1}, {}),
    ],
    [
        #YEARS                          ID                 CAT      COST  REQ                     OPTIONS
        ([1908],                        "civilian_car",    "TANKS", 2400, {},                     {}),
        (unit_years("WW1 Armored Car"), "ww1_armored_car", "TANKS", 2400, {"civilian_car": 1},    {}),
        (unit_years("Armored Car"),     "armored_car",     "TANKS", 2400, {"ww1_armored_car": 1}, {}),
    ],
    [
        #YEARS                                     ID                           CAT      COST  REQ                              OPTIONS
        (unit_years("WW1 Tank"),                   "ww1_tank",                  "TANKS", 2400, {"ww1_armored_car": 1},          {}),
        (unit_years("Light Tank"),                 "light_tank",                "TANKS", 2400, {"ww1_tank": 1},                 {}),
        (unit_years("Medium Tank"),                "medium_tank",               "TANKS", 2400, {"light_tank": 1},               {}),
        (unit_years("Heavy Tank"),                 "heavy_tank",                "TANKS", 2400, {"medium_tank": 1},              {}),
        (unit_years("Super Heavy Tank"),           "super_heavy_tank",          "TANKS", 2400, {"heavy_tank": 4},               {}),
        (unit_years("Landkreuzer P.1000 Ratte"),   "landkreuzer_p1000_ratte",   "TANKS", 3000, {"ww2_railroad_gun": 1},         {}),
        (unit_years("Landkreuzer P.1500 Monster"), "landkreuzer_p1500_monster", "TANKS", 3600, {"landkreuzer_p1000_ratte": 1},  {}),
        ([1980],                                   "electromagnetic_launcher",  "TANKS", 3000, {},                              {}),
        (unit_years("Railgun"),                    "railgun",                   "TANKS", 3600, {"electromagnetic_launcher": 1}, {}),
        (unit_years("Main Battle Tank"),           "main_battle_tank",          "TANKS", 2400, MBT_REQ,                         {}),
        (unit_years("WW1 Railroad Gun"),           "ww1_railroad_gun",          "TANKS", 2400, {"ww1_tank": 1},                 {}),
        (unit_years("WW2 Railroad Gun"),           "ww2_railroad_gun",          "TANKS", 2400, WW2_RAIL_REQ,                    {}),
    ],
    [
        #YEARS                           ID                  CAT     COST  REQ                                                      OPTIONS
        (unit_years("Carrack"),          "carrack",          "NAVY", 600,  {},                                                      {}),
        (unit_years("Ironclad"),         "ironclad",         "NAVY", 2400, {"carrack": len(unit_years("Carrack"))},                 {}),
        (unit_years("Pre-Dreadnought"),  "pre-dreadnought",  "NAVY", 2400, {"ironclad": len(unit_years("Ironclad"))},               {}),
        (unit_years("Dreadnought"),      "dreadnought",      "NAVY", 2400, {"pre-dreadnought": len(unit_years("Pre-Dreadnought"))}, {}),
        (unit_years("Battleship"),       "battleship",       "NAVY", 2400, {"dreadnought": len(unit_years("Dreadnought"))},         {}),
        (unit_years("Destroyer"),        "destroyer",        "NAVY", 2400, {"pre-dreadnought": len(unit_years("Pre-Dreadnought"))}, {}),
        (unit_years("Aircraft Carrier"), "aircraft_carrier", "NAVY", 2400, {"dreadnought": len(unit_years("Dreadnought"))},         {}),
        (unit_years("Submarine"),        "submarine",        "NAVY", 2400, {"pre-dreadnought": len(unit_years("Pre-Dreadnought"))}, {}),
    ],
    [
        #YEARS                                       ID                            CAT         COST  REQ                       OPTIONS
        (building_years("Basic Factory"),            "basic_factory",              "INDUSTRY", 1200, {},                       {}),
        ([1815],                                     "waltham_system",             "INDUSTRY", 1200, {"basic_factory": 1},     {"NAME": "Waltham System", "BONUS": flat_building_bonus(["Basic Factory"], "materials", 20)}),
        ([1830],                                     "mechanical_reaper",          "INDUSTRY", 1200, {"waltham_system": 1},    {"NAME": "Mechanical Reaper", "BONUS": flat_building_bonus(["Basic Factory"], "materials", 30)}),
        ([1835],                                     "metal_shaper",               "INDUSTRY", 1200, {"mechanical_reaper": 1}, {"NAME": "Metal Shaper", "BONUS": flat_building_bonus(["Basic Factory"], "materials", 40)}),
        ([1840],                                     "steam_hammer",               "INDUSTRY", 1200, {"metal_shaper": 1},      {"NAME": "Steam Hammer", "BONUS": flat_building_bonus(["Basic Factory"], "materials", 50)}),
        ([1855],                                     "bessemer_process",           "INDUSTRY", 1200, {"steam_hammer": 1},      {"NAME": "Bessemer Process", "BONUS": flat_building_bonus(["Basic Factory"], "materials", 60)}),
        ([1870],                                     "electricity",                "INDUSTRY", 1200, {"bessemer_process": 1},  {"NAME": "Electricity", "BONUS": flat_building_bonus(["Basic Factory"], "materials", 50)}),
        ([1880],                                     "lightbulb",                  "INDUSTRY", 1200, {"electricity": 1},       {"NAME": "Lightbulb", "BONUS": flat_building_bonus(["Basic Factory"], "materials", 40)}),
        ([1890],                                     "industrial_air_compressor",  "INDUSTRY", 1200, {"lightbulb": 1},         {"NAME": "Industrial Air Compressor", "BONUS": flat_building_bonus(["Basic Factory"], "materials", 50)}),
        ([1895],                                     "diesel_engine",              "INDUSTRY", 1200, IAC,                      {"NAME": "Diesel Engine", "BONUS": flat_building_bonus(["Basic Factory"], "materials", 60)}),
        ([1905],                                     "assembly_line",              "INDUSTRY", 1200, {"factory": 1},           {"NAME": "Assembly Line", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.1)}),
        ([1915],                                     "conveyor_belt",              "INDUSTRY", 1200, {"factory": 2},           {"NAME": "Conveyor Belt", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.1)}),
        ([1925],                                     "continuous_assembly_line",   "INDUSTRY", 1200, {"factory": 3},           {"NAME": "Continuous Assembly Line", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.1)}),
        ([1935],                                     "machine_tools",              "INDUSTRY", 1200, {"factory": 4},           {"NAME": "Machine Tools", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.1)}),
        ([1945],                                     "just_in_time_manufacturing", "INDUSTRY", 1200, {"factory": 5},           {"NAME": "Just In Time Manufacturing", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.1)}),
        ([1955],                                     "industrial_robot",           "INDUSTRY", 1200, {"factory": 6},           {"NAME": "Industrial Robot", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.1)}),
        ([1965],                                     "stanford_arm",               "INDUSTRY", 1200, {"factory": 7},           {"NAME": "Stanford Arm", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.1)}),
        ([1975],                                     "asea_irb_6",                 "INDUSTRY", 1200, {"factory": 8},           {"NAME": "ASEA IRB 6", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.1)}),
        ([1985],                                     "computer_numerical_control", "INDUSTRY", 1200, {"factory": 9},           {"NAME": "Computer Numerical Control", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.1)}),
        ([1995],                                     "3d_printing",                "INDUSTRY", 1200, {"factory": 10},          {"NAME": "3D Printing", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.1)}),
        ([2005],                                     "internet_of_things",         "INDUSTRY", 1200, {"factory": 11},          {"NAME": "Internet of Things", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.05)}),
        ([2015],                                     "industry_4_0",               "INDUSTRY", 1200, {"factory": 12},          {"NAME": "Industry 4.0", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.05)}),
        ([2025],                                     "industry_5_0",               "INDUSTRY", 1200, {"factory": 13},          {"NAME": "Industry 5.0", "BONUS": proportional_building_bonus(["Basic Factory", "Factory"], "materials", 0.05)}),
        (building_years("Factory Lvl"),              "factory",                    "INDUSTRY", 1200, {"diesel_engine": 1},     {"GATES": FACTORY_LEVEL_GATES}),
        ([1910],                                     "bergius_process",            "INDUSTRY", 1200, {},                       {}),
        (yr(1912, 2, 50),                            "fuel_refining",              "INDUSTRY", 1200, {"bergius_process": 1},   {}),
        (building_years("Basic Recruitment Center"), "basic_recruitment",          "INDUSTRY", 1200, {},                       {}),
        (building_years("Recruitment Building Lvl"), "recruitment_buildings",      "INDUSTRY", 1200, {"basic_recruitment": 1}, {}),
        (yr(1810, 10, 35),                            "general_recruitment",        "INDUSTRY", 900,  GR,                       {}),
        (yr(1850, 2, 100),                           "resource_refining",          "INDUSTRY", 900,  {},                       {}),
    ],
    [
        #YEARS                              ID                         CAT    COST  REQ                                     OPTIONS
        ([1906],                            'heavier_than_air_flight', 'AIR', 900,  {},                                     {"NAME": 'Heavier Than Air Flight'}),
        (unit_years("Biplane Fighter"),     'biplane',                 'AIR', 1200, {'heavier_than_air_flight': 1},         {"NAME": 'Biplane Fighter'}),
        (unit_years("Biplane Bomber"),      'biplane_bomber',          'AIR', 1800, {'biplane': 1},                         {"NAME": 'Biplane Bomber'}),
        (unit_years("Zeppelin"),            'zeppelin',                'AIR', 1800, {},                                     {"NAME": 'Zeppelin'}),
        (unit_years("Monoplane Fighter"),   'piston_fighter',          'AIR', 1200, {'biplane': 5},                         {"NAME": 'Monoplane Fighter'}),
        (unit_years("Monoplane Bomber"),    'piston_bomber',           'AIR', 1800, {'biplane_bomber': 3},                  {"NAME": 'Monoplane Bomber'}),
        (unit_years("Monoplane Transport"), 'monoplane_transport',     'AIR', 1800, {'biplane_bomber': 3},                  {"NAME": 'Monoplane Transport'}),
        (unit_years("V1 Flying Bomb"),      'v1_flying_bomb',          'AIR', 900,  {},                                     {"NAME": 'V1 Flying Bomb'}),
        (unit_years("V2 Rocket"),           'v2_rocket',               'AIR', 1200, {'v1_flying_bomb': 1},                  {"NAME": 'V2 Rocket'}),
        ([1945],                            'jet_engine',              'AIR', 2400, {},                                     {"NAME": 'Jet Engine'}),
        (unit_years("Jet Fighter"),         'jet_fighter',             'AIR', 1800, {'piston_fighter': 5, 'jet_engine': 1}, {"NAME": 'Jet Fighter'}),
        (unit_years("Jet Bomber"),          'jet_bomber',              'AIR', 2400, {'piston_bomber': 5, 'jet_fighter': 1}, {"NAME": 'Jet Bomber'}),
        (unit_years("Jet Transport"),       'jet_transport',           'AIR', 2400, {'piston_bomber': 5},                   {"NAME": 'Jet Transport'}),
    ],
]


def research_recipe(row):
    """Translate one compact research row without changing saved field names or order."""
    years, key, *values, options = row
    entry = table_values(RESEARCH_RECIPE_COLUMNS, values)
    entry.update({RESEARCH_OPTION_COLUMNS.get(field, field): value for field, value in options.items()})
    if key in EQUIPMENT_STAGES:
        return key, extend_infantry_research(key, entry)
    entry["max_lvl"] = len(years)
    entry["years"] = years
    for families in UNIT_SECTIONS[1:]:
        for family in families:
            if family.research_key == key:
                entry["level_names"] = {str(level): name for level, (name, _) in enumerate(family.entries(), 1)}
    fields = ("category", "display_name", "max_lvl", "cost", "req", "level_reqs", "years")
    ordered = {field: entry[field] for field in fields if field in entry}
    ordered.update({field: value for field, value in entry.items() if field not in ordered})
    return key, ordered


RESEARCH_SECTIONS = [[research_recipe(row) for row in block] for block in RESEARCH_RECIPES]
