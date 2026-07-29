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

To change a family (e.g. make Infantry Type gain more health per year),
edit its `linear(base, delta)` call below and re-run the generator.
To add a new unit/building level, bump a `count`/range end and re-run.
"""
import sys
import os
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


class UnitFamily:
    def __init__(self, prefix, suffixes, stats, naval_unit=False):
        self.prefix = prefix
        self.suffixes = suffixes
        self.stats = stats
        self.naval_unit = naval_unit

    def entries(self):
        out = []
        for i, suffix in enumerate(self.suffixes):
            name = self.prefix if suffix is None else f"{self.prefix} {suffix}"
            entry = {}
            for key in UNIT_STAT_KEYS:
                gen = self.stats[key]
                entry[key] = gen(i) if callable(gen) else gen
            entry["naval_unit"] = self.naval_unit
            entry["order"] = {}
            out.append((name, entry))
        return out


# Each inner list is a contiguous block of families; a blank spacer line is
# written between blocks, matching the hand-maintained file's formatting.
UNIT_SECTIONS = [
    [
        UnitFamily("Infantry Type", year_suffixes(1910, 101), {
            "health": linear(1000, 50), "attack": linear(100, 10), "defense": const(0),
            "speed": const(1), "cost_materials": const(500), "cost_manpower": const(1000),
            "cost_fuel": const(0), "production_time": const(2),
        }),
        UnitFamily("Motorized Infantry Type", year_suffixes(1930, 81), {
            "health": linear(2000, 50), "attack": linear(300, 10), "defense": const(0),
            "speed": const(2), "cost_materials": const(1000), "cost_manpower": const(1000),
            "cost_fuel": const(50), "production_time": const(2),
        }),
        UnitFamily("Mechanized Infantry Type", year_suffixes(1940, 71), {
            "health": linear(2500, 50), "attack": linear(400, 10), "defense": linear(100, 5),
            "speed": const(2),
            # material cost drops from 2000 to 1000 starting the 2001 model (index 61)
            "cost_materials": piecewise([(0, 2000, 0), (61, 1000, 0)]),
            "cost_manpower": const(1000), "cost_fuel": const(50), "production_time": const(3),
        }),
        UnitFamily("Cavalry", roman_suffixes(5), {
            "health": linear(600, 100), "attack": const(300), "defense": const(0),
            "speed": const(2), "cost_materials": const(1000), "cost_manpower": const(2000),
            "cost_fuel": const(0), "production_time": const(3),
        }),
        UnitFamily("Militia", roman_suffixes(20), {
            "health": linear(500, 100), "attack": linear(50, 10), "defense": const(0),
            "speed": const(1), "cost_materials": const(300), "cost_manpower": const(1000),
            "cost_fuel": const(0), "production_time": const(1),
        }),
        # Fragile in a straight fight - its damage is meant to come from bombarding
        # an adjacent tile (see c.BOMBARDMENT_UNITS) rather than from stacking up.
        UnitFamily("Artillery", roman_suffixes(51), {
            "health": linear(100, 20), "attack": linear(50, 10), "defense": const(0),
            "speed": const(1), "cost_materials": const(2000), "cost_manpower": const(500),
            "cost_fuel": const(0), "production_time": const(3),
        }),
    ],
    [
        UnitFamily("WW1 Tank", single(), {
            "health": 3000, "attack": 1500, "defense": 100, "speed": 1,
            "cost_materials": 6000, "cost_manpower": 1000, "cost_fuel": 300, "production_time": 6,
        }),
        UnitFamily("WW1 Armored Car", single(), {
            "health": 1000, "attack": 300, "defense": 50, "speed": 2,
            "cost_materials": 3000, "cost_manpower": 1000, "cost_fuel": 100, "production_time": 4,
        }),
        UnitFamily("Armored Car", roman_suffixes(24), {
            "health": linear(1000, 100), "attack": linear(400, 100), "defense": linear(60, 10),
            # speed steps: I=2, II-IV=3, V+=4
            "speed": piecewise([(0, 2, 0), (1, 3, 0), (4, 4, 0)]),
            "cost_materials": const(3000), "cost_manpower": const(1000),
            "cost_fuel": const(100), "production_time": const(4),
        }),
        UnitFamily("Light Tank", roman_suffixes(24), {
            "health": linear(1800, 200), "attack": linear(1200, 150), "defense": linear(80, 10),
            # speed steps: I-III=2, IV+=3
            "speed": piecewise([(0, 2, 0), (3, 3, 0)]),
            "cost_materials": const(8000), "cost_manpower": const(1000),
            "cost_fuel": const(150), "production_time": const(5),
        }),
        UnitFamily("Medium Tank", roman_suffixes(4), {
            "health": linear(2500, 500), "attack": linear(2400, 600), "defense": linear(150, 25),
            "speed": const(2), "cost_materials": const(12000), "cost_manpower": const(1000),
            "cost_fuel": const(200), "production_time": const(6),
        }),
        UnitFamily("Heavy Tank", roman_suffixes(4), {
            "health": linear(3000, 500), "attack": linear(3000, 500), "defense": linear(350, 50),
            "speed": const(1), "cost_materials": const(16000), "cost_manpower": const(1000),
            "cost_fuel": const(200), "production_time": const(6),
        }),
        UnitFamily("Super Heavy Tank", roman_suffixes(3), {
                    "health": linear(5000, 500), "attack": linear(5000, 500), "defense": linear(550, 50),
                    "speed": const(1), "cost_materials": const(16000), "cost_manpower": const(1000),
                    "cost_fuel": const(200), "production_time": const(6),
        }),
        UnitFamily("Landkreuzer P.1000 Ratte", single(), {
            "health": 10000, "attack": 6000, "defense": 800,
            "speed": 1, "cost_materials": 100000, "cost_manpower": 2000,
            "cost_fuel": 3000, "production_time": 8,
        }),
        UnitFamily("Landkreuzer P.1500 Monster", single(), {
            "health": 15000, "attack": 8000, "defense": 800,
            "speed": 1, "cost_materials": 150000, "cost_manpower": 2000,
            "cost_fuel": 3000, "production_time": 10,
        }),
        UnitFamily("Main Battle Tank", roman_suffixes(14), {
            "health": linear(5000, 500), "attack": linear(5000, 500), "defense": linear(250, 25),
            "speed": const(2), "cost_materials": const(15000), "cost_manpower": const(1000),
            "cost_fuel": const(200), "production_time": const(6),
        }),
        # Siege piece: reaches 2 tiles instead of Artillery's 1 (see c.BOMBARDMENT_UNITS).
        UnitFamily("Railroad Gun", roman_suffixes(5), {
            "health": linear(1200, 200), "attack": linear(500, 100), "defense": const(0),
            "speed": const(1), "cost_materials": const(12000), "cost_manpower": const(1000),
            "cost_fuel": const(0), "production_time": const(6),
        }),
    ],
    [
        UnitFamily("Dreadnought", single(), {
            "health": 10000, "attack": 6000, "defense": 1000, "speed": 1,
            "cost_materials": 20000, "cost_manpower": 2000, "cost_fuel": 300, "production_time": 10,
        }, naval_unit=True),
        UnitFamily("Battleship", single(), {
            "health": 15000, "attack": 10000, "defense": 1500, "speed": 1,
            "cost_materials": 20000, "cost_manpower": 2000, "cost_fuel": 400, "production_time": 10,
        }, naval_unit=True),
        UnitFamily("Destroyer", roman_suffixes(26), {
            "health": linear(6000, 1000), "attack": linear(3000, 1000), "defense": linear(600, 100),
            "speed": const(1), "cost_materials": const(10000), "cost_manpower": const(1000),
            "cost_fuel": const(300), "production_time": const(8),
        }, naval_unit=True),
        UnitFamily("Submarine", roman_suffixes(26), {
            "health": linear(3000, 500),
            # attack climbs 1500/level through IX, jumps to 20000 at X, then 1000/level
            "attack": piecewise([(0, 6000, 1500), (9, 20000, 1000)]),
            "defense": linear(300, 50),
            "speed": const(1), "cost_materials": const(8000), "cost_manpower": const(1000),
            "cost_fuel": const(200), "production_time": const(6),
        }, naval_unit=True),
        UnitFamily("Aircraft Carrier", roman_suffixes(17), {
            "health": linear(2000, 1000), "attack": linear(20000, 5000), "defense": linear(1000, 100),
            "speed": const(1), "cost_materials": const(20000), "cost_manpower": const(2000),
            "cost_fuel": const(500), "production_time": const(10),
        }, naval_unit=True),
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
    def __init__(self, base_name, base_stats, base_req, level_prefix, count, stats):
        self.base_name = base_name
        self.base_stats = base_stats
        self.base_req = base_req
        self.level_prefix = level_prefix
        self.count = count
        self.stats = stats

    def entries(self):
        base_entry = {"time": self.base_stats["time"], "group": self.base_stats["group"],
                       "req": self.base_req}
        for key in BUILDING_STAT_KEYS[2:]:
            base_entry[key] = self.base_stats[key]
        out = [(self.base_name, base_entry)]

        prev_name = self.base_name
        for n in range(1, self.count + 1):
            name = f"{self.level_prefix} {n}"

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
            "time": 6, "group": "industry", "cost_materials": 0, "cost_manpower": 0,
            "cost_fuel": 0, "prod_materials": 500, "prod_manpower": 0, "prod_fuel": 0,
        },
        level_prefix="Factory Lvl",
        count=25,
        stats={
            "time": const(12), "group": const("industry"), "cost_materials": const(30000),
            "cost_manpower": const(0), "cost_fuel": const(1000),
            "prod_materials": lambda n: 1000 * n, "prod_manpower": const(0),
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
]


# ===========================================================================
# RESEARCH_TEMPLATE.JSON
# ===========================================================================
# `years` is always a pure arithmetic sequence in the current data, so it's
# expressed as years_range(start, step, count) rather than per-family stat
# generators. req/category/cost are just literal values (there are only 26
# techs total, so no abstraction is needed there).

# Sections separated by a blank spacer line, matching the current file.
RESEARCH_SECTIONS = [
    [
        ("infantry_type", {"category": "INFANTRY", "max_lvl": 101, "cost": 900, "req": {},
                            "years": years_range(1910, 1, 101)}),
        ("cavalry", {"category": "INFANTRY", "max_lvl": 5, "cost": 1200, "req": {},
                      "years": years_range(1910, 4, 5)}),
        ("militia", {"category": "INFANTRY", "max_lvl": 20, "cost": 600, "req": {},
                      "years": years_range(1910, 5, 20)}),
        ("artillery", {"category": "INFANTRY", "max_lvl": 51, "cost": 900, "req": {},
                        "years": years_range(1910, 2, 51)}),
        ("motorized_infantry", {"category": "INFANTRY", "max_lvl": 81, "cost": 900,
                                 "req": {"infantry_type": "MATCH_LEVEL_+20", "cavalry": 5},
                                 "years": years_range(1930, 1, 81)}),
        ("mechanized_infantry", {"category": "INFANTRY", "max_lvl": 71, "cost": 900,
                                  "req": {"motorized_infantry": "MATCH_LEVEL_+10"},
                                  "years": years_range(1940, 1, 71)}),
    ],
    [
        ("civilian_car", {"category": "TANKS", "max_lvl": 1, "cost": 2400, "req": {},
                           "years": years_range(1910, 1, 1)}),
        ("ww1_armored_car", {"category": "TANKS", "max_lvl": 1, "cost": 2400,
                              "req": {"civilian_car": 1}, "years": years_range(1912, 1, 1)}),
        ("armored_car", {"category": "TANKS", "max_lvl": 24, "cost": 2400,
                          "req": {"ww1_armored_car": 1}, "years": years_range(1916, 4, 24)}),
    ],
    [
        ("ww1_tank", {"category": "TANKS", "max_lvl": 1, "cost": 2400,
                       "req": {"ww1_armored_car": 1}, "years": years_range(1914, 1, 1)}),
        ("light_tank", {"category": "TANKS", "max_lvl": 24, "cost": 2400,
                         "req": {"ww1_tank": 1}, "years": years_range(1918, 4, 24)}),
        ("medium_tank", {"category": "TANKS", "max_lvl": 4, "cost": 2400,
                          "req": {"light_tank": 1}, "years": years_range(1925, 5, 4)}),
        ("heavy_tank", {"category": "TANKS", "max_lvl": 4, "cost": 2400,
                         "req": {"medium_tank": 1}, "years": years_range(1929, 4, 4)}),
        ("super_heavy_tank", {"category": "TANKS", "max_lvl": 3, "cost": 2400,
                                "req": {"heavy_tank": 4}, "years": years_range(1945, 4, 3)}),
        ("landkreuzer_p1000_ratte", {"category": "TANKS", "max_lvl": 1, "cost": 3000,
                                        "req": {"heavy_tank": 4}, "years": years_range(1944, 6, 1)}),
        ("landkreuzer_p1500_monster", {"category": "TANKS", "max_lvl": 1, "cost": 3600,
                                                "req": {"landkreuzer_p1000_ratte": 1}, "years": years_range(1952, 8, 1)}),
        ("main_battle_tank", {"category": "TANKS", "max_lvl": 14, "cost": 2400,
                               "req": {"OR": [{"medium_tank": 4}, {"heavy_tank": 4}]},
                               "years": years_range(1945, 5, 14)}),
        ("railroad_gun", {"category": "TANKS", "max_lvl": 5, "cost": 2400,
                           "req": {"ww1_tank": 1}, "years": years_range(1918, 5, 5)}),
    ],
    [
        ("dreadnought", {"category": "NAVY", "max_lvl": 1, "cost": 2400, "req": {},
                          "years": years_range(1910, 1, 1)}),
        ("battleship", {"category": "NAVY", "max_lvl": 1, "cost": 2400,
                         "req": {"dreadnought": 1}, "years": years_range(1920, 1, 1)}),
        ("destroyer", {"category": "NAVY", "max_lvl": 26, "cost": 2400, "req": {},
                        "years": years_range(1910, 4, 26)}),
        ("aircraft_carrier", {"category": "NAVY", "max_lvl": 17, "cost": 2400,
                               "req": {"battleship": 1}, "years": years_range(1930, 5, 17)}),
        ("submarine", {"category": "NAVY", "max_lvl": 26, "cost": 2400, "req": {},
                        "years": years_range(1910, 4, 26)}),
    ],
    [
        ("basic_factory", {"category": "INDUSTRY", "max_lvl": 1, "cost": 1200, "req": {},
                            "years": years_range(1910, 1, 1)}),
        ("factory", {"category": "INDUSTRY", "max_lvl": 25, "cost": 1200,
                      "req": {"basic_factory": 1}, "years": years_range(1914, 4, 25)}),
        ("bergius_process", {"category": "INDUSTRY", "max_lvl": 1, "cost": 1200, "req": {},
                              "years": years_range(1910, 1, 1)}),
        ("fuel_refining", {"category": "INDUSTRY", "max_lvl": 50, "cost": 1200,
                            "req": {"bergius_process": 1}, "years": years_range(1912, 2, 50)}),
        ("basic_recruitment", {"category": "INDUSTRY", "max_lvl": 1, "cost": 1200, "req": {},
                                "years": years_range(1910, 1, 1)}),
        ("recruitment_buildings", {"category": "INDUSTRY", "max_lvl": 50, "cost": 1200,
                                    "req": {"basic_recruitment": 1},
                                    "years": years_range(1912, 2, 50)}),
        ("general_recruitment", {"category": "INDUSTRY", "max_lvl": 50, "cost": 900,
                                  "req": {"recruitment_buildings": "MATCH_LEVEL"},
                                  "years": years_range(1913, 2, 50)}),
        ("resource_refining", {"category": "INDUSTRY", "max_lvl": 100, "cost": 900, "req": {},
                                "years": years_range(1911, 1, 100)}),
    ],
]
