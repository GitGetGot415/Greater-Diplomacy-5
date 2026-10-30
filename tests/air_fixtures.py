"""Shared air fixtures: a controlled aircraft library, a small world, tiles, and wings."""

import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

from data import queries
import data.constants as c
from tests.stub_map_screen import map_double


def controlled_air_library():
    """Supply artificial families with explicit stats for mechanics tests."""
    roles = {"Biplane Fighter": "fighter", "Monoplane Fighter": "fighter", "Jet Fighter": "fighter",
             "Biplane Bomber": "bomber", "Monoplane Bomber": "bomber", "Jet Bomber": "bomber",
             "Zeppelin": "bomber", "V1 Flying Bomb": "missile", "V2 Rocket": "missile"}
    names = [f"{base} {c.ROMAN_NUMERALS[level]}"
             for base in roles if base not in ("Zeppelin", "V1 Flying Bomb", "V2 Rocket")
             for level in (1, 2)]
    names.extend(("Zeppelin I", "V1 Flying Bomb I", "V2 Rocket I", "Infantry", "Infantry Type 1910",
                  "WW1 Tank I", "WW1 Railroad Gun I", "Artillery VII", "Battleship I", "Convoy", "Truck"))
    library = {}
    for name in names:
        base = queries.get_base_unit_name(name)
        stats = {"attack": 80, "defense": 0, "health": 1000, "speed": 1,
                 "cost_materials": 1000, "cost_manpower": 100, "cost_fuel": 0,
                 "production_time": 2, "naval_unit": name in ("Battleship I", "Convoy")}
        role = roles.get(base)
        if role:
            consumable = base in ("V1 Flying Bomb", "V2 Rocket")
            stats.update(air_role=role, air_range_px=240, air_consumable=consumable,
                         air_attack_multiplier=2 if role == "fighter" else 1,
                         air_interception_immune=base == "V2 Rocket",
                         air_damages_forts=role != "fighter",
                         speed=2 if consumable else 0)
        if base in ("WW1 Railroad Gun", "Artillery"):
            stats.update(bombard_attack=80, bombard_range=1)
        library[name] = stats
    return library


def install_air_fixture(case):
    """Patch tunable fields and restore them after each test."""
    library = controlled_air_library()
    tree = {}
    for name in library:
        family = queries.get_base_unit_name(name, library)
        levels = sum(queries.get_base_unit_name(other, library) == family for other in library)
        tree[queries.get_unit_tech_key(family)] = {
            "display_name": family, "max_lvl": levels,
            "years": list(range(1910, 1910 + levels)), "cost": 100, "req": {}}
    tree["infantry_type"]["years"] = [1910]
    tree["infantry_type"]["max_lvl"] = 1
    for name, stats in library.items():
        tree[queries.get_unit_tech_key(queries.get_base_unit_name(name))]["category"] = (
            "AIR" if stats.get("air_role") else "INFANTRY")
    # Loading refreshes these libraries from disk in place. Use fixture files
    # so save/load tests retain the same controlled data after that refresh.
    directory = case.enterContext(tempfile.TemporaryDirectory())
    for field, filename, data in (("UNIT_DATA_PATH", "units.json", library),
                                  ("RESEARCH_TEMPLATE_PATH", "research.json", tree)):
        path = os.path.join(directory, filename)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        case.enterContext(patch.object(c, field, path))
        key = "unit_library" if field == "UNIT_DATA_PATH" else "tech_tree"
        case.enterContext(patch.dict(queries._JSON_CACHE[key], {"path": path, "data": data}))
    case.enterContext(patch.object(queries, "get_unit_library", return_value=library))
    case.enterContext(patch.object(queries, "get_tech_tree", return_value=tree))


def world():
    nations = {name: {"name": name, "is_playable": True,
        "at_war_with": [other for other in ("A", "B", "C") if other != name],
        "research": {}, "materials": 100000, "fuel": 100000, "manpower": 100000}
        for name in ("A", "B", "C")}
    return map_double(map_data={}, id_to_province={}, nation_data=nations,
        id_map=pygame.Surface((2400, 32)), scenario_settings={}, tactical_mode=False,
        player_unit=None, player_country="A", loop_map=False, active_players=["A"],
        current_player_index=0, script_variables={}, default_research={},
        time_manager=SimpleNamespace(day=1, month_index=0, year=1939, total_turns=4),
        multiplayer_session_key="air-test-session", submitted_moves=set())


def tile(game, pid, x, owner="A", water=False, width=4, center=None):
    color = (pid, 1, 1)
    province = {"id": pid, "center": center or (x + width / 2, 5), "map_color": color,
        "json_key": str(color), "terrain": c.WATER_TERRAINS[0] if water else "Plains",
        "owner": "Ocean" if water else owner, "units": [], "neighbors": [],
        "buildings": [], "cores": [], "resources": {}, "unit_queue": [], "building_queue": []}
    game.map_data[color] = province
    game.id_to_province[pid] = province
    pygame.draw.rect(game.id_map, color, pygame.Rect(x, 4, width, 2))
    return province


def wing(base, name="Monoplane Bomber I", owner="A", order=None):
    unit = queries.create_unit_dict(name, owner, queries.get_unit_library())
    if order:
        unit["order"] = dict(order, base_id=base["id"])
    base["units"].append(unit)
    return unit
