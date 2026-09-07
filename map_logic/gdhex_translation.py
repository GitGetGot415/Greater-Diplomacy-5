"""One-way conversion of Greater Diplomacy Hex Edition saves into GD5 saves.

Hex Edition's TurboWarp saves contain the complete hex grid, unlike GD4's
fixed world map.  This module therefore builds a self-contained GD5 map for
each import.  It deliberately contains no game-screen code; the menu is only
a file picker around :func:`translate_file`.
"""

import copy
import colorsys
import json
import math
import os
import re
import shutil
from datetime import datetime

import pygame

import data.constants as c
from data import queries
from data.map import history_io
from data.platform import sync_persisted_dir


RESOURCE_SCALE = 100
MAX_HEXES = 16_384
HEX_RADIUS = 17
HEX_PADDING = 18

LAND_COLOR = (144, 238, 144)
OCEAN_COLOR = (40, 100, 180)
PLAYER_COLOR = [65, 145, 255]
ENEMY_COLOR = [255, 70, 70]
RESOURCE_BY_CODE = {1: "Wheat", 2: "Oil", 3: "Iron"}
UNIT_TYPES = {
    "i": "Infantry Type {year}",
    "c": "Cavalry I",
    "mi": "Motorized Infantry Type {year}",
    "mei": "Mechanized Infantry Type {year}",
    "ac": "Armored Car I",
    "mbt": "Main Battle Tank I",
    "des": "Destroyer I",
    # GD5 has no cruiser class. Dreadnought is the closest available heavier
    # surface ship and keeps a Hex cruiser naval rather than silently losing it.
    "cru": "Dreadnought",
}


class GDHEXTranslationError(ValueError):
    """A selected file is not a supported Greater Diplomacy Hex save."""


def _number(value, label):
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise GDHEXTranslationError(f"Hex Edition {label} is not numeric") from error


def _positive_int(value):
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _nested_list(value, label):
    try:
        outer = json.loads(value)
        if not isinstance(outer, list):
            raise TypeError("not a list")
        return [json.loads(item) if isinstance(item, str) else item for item in outer]
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise GDHEXTranslationError(f"invalid Hex Edition {label} data") from error


def _resource_balances(value, label):
    try:
        values = json.loads(value)
        if not isinstance(values, list) or len(values) < 3:
            raise TypeError("expected three values")
        return [_positive_int(item) for item in values[:3]]
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise GDHEXTranslationError(f"invalid Hex Edition {label} resources") from error


def parse_save(source):
    """Parse the plain-text TurboWarp Hex Edition format into useful state."""
    parts = source.lstrip("\ufeff").strip().split("|")
    if len(parts) < 12:
        raise GDHEXTranslationError("save is missing required fields")

    width = _positive_int(parts[0])
    height = _positive_int(parts[1])
    expected_hexes = width * height
    if not width or not height or expected_hexes > MAX_HEXES:
        raise GDHEXTranslationError("map dimensions are invalid or too large")

    armies = _nested_list(parts[8], "army")
    hexes = _nested_list(parts[9], "hex grid")
    if len(armies) != expected_hexes or len(hexes) != expected_hexes:
        raise GDHEXTranslationError(
            f"save dimensions require {expected_hexes} hexes, but contain "
            f"{len(hexes)} grid records and {len(armies)} army records")
    for index, record in enumerate(hexes):
        if not isinstance(record, list) or len(record) < 8:
            raise GDHEXTranslationError(f"hex record {index + 1} is incomplete")
    for index, army in enumerate(armies):
        if not isinstance(army, list):
            raise GDHEXTranslationError(f"army record {index + 1} is invalid")

    time_value = _number(parts[5], "time")
    if time_value < 0:
        raise GDHEXTranslationError("dates before year 0 are not supported")
    return {
        "width": width,
        "height": height,
        "time": time_value,
        "hexes": hexes,
        "armies": armies,
        "player_resources": _resource_balances(parts[10], "Player"),
        "enemy_resources": _resource_balances(parts[11], "Enemy"),
    }


def _is_water(token):
    return str(token).upper().startswith("WATER")


def _token_text(token):
    number = _number(token, "country color")
    return format(number, "g")


def _country_name(token):
    token = str(token).strip()
    if token == "P":
        return "Player"
    if token == "E":
        return "Enemy"
    return f"Hex Country {_token_text(token)}"


def _hex_color(token):
    token = str(token).strip()
    if token == "P":
        return PLAYER_COLOR.copy()
    if token == "E":
        return ENEMY_COLOR.copy()
    hue = max(0.0, min(200.0, _number(token, "country color"))) / 200.0
    return [round(channel * 255) for channel in colorsys.hsv_to_rgb(hue, 1.0, 1.0)]


def _country_template(name, color, research):
    template = copy.deepcopy(queries.get_country_data().get("Unclaimed", {}))
    template.update({
        "name": name,
        "adjective": name,
        "color": color,
        "research": research.copy(),
        "manpower": 0,
        "materials": 0,
        "fuel": 0,
        "is_playable": True,
        "at_war_with": [],
        "allied_with": [],
        "faction": "",
        "is_faction_leader": False,
        "master": "",
        "puppets": [],
        "leader_name": "",
        "leader_title": "",
        "flag_data": "",
        "portrait_data": "",
    })
    return template


def _factory_buildings(level):
    level = min(_positive_int(level), 50)
    if level == 0:
        return []
    return ["Basic Factory" if level == 1 else f"Factory Lvl {level - 1}"]


def _unit_type(code, year, unit_library):
    template = UNIT_TYPES.get(str(code).strip().lower())
    if not template:
        return None
    name = template.format(year=year)
    if name in unit_library:
        return name
    if "{year}" not in template:
        return None
    prefix = template.split(" {year}", 1)[0] + " "
    choices = [item for item in unit_library if item.startswith(prefix)]
    if not choices:
        return None
    return min(choices, key=lambda item: abs(int(item.rsplit(" ", 1)[1]) - year))


def _build_units(source_units, year, unit_library, known_countries, skipped):
    converted = []
    for unit in source_units:
        if not isinstance(unit, list) or len(unit) < 7:
            skipped.add("malformed unit")
            continue
        target_type = _unit_type(unit[0], year, unit_library)
        if not target_type:
            skipped.add(str(unit[0]).strip() or "unnamed unit")
            continue
        owner_token = str(unit[6]).strip()
        if _is_water(owner_token):
            skipped.add(f"unit with water owner {owner_token}")
            continue
        try:
            owner = _country_name(owner_token)
        except GDHEXTranslationError:
            skipped.add(f"unit with invalid owner {owner_token}")
            continue
        if owner not in known_countries:
            skipped.add(f"unit for unknown country {owner_token}")
            continue
        converted_unit = queries.create_unit_dict(target_type, owner, unit_library)
        source_max = _number(unit[1], "unit maximum health")
        source_current = _number(unit[2], "unit current health")
        if source_max > 0:
            health_fraction = max(0.0, min(1.0, source_current / source_max))
            converted_unit["health"] = converted_unit["max_health"] * health_fraction
        converted_unit["naval_unit"] = bool(unit_library[target_type].get("naval_unit", False))
        converted.append(converted_unit)
    return converted


def _neighbors(index, width, height):
    row, column = divmod(index, width)
    offsets = ((-1, 0), (1, 0), (0, -1), (0, 1))
    # Columns are offset downward by half a hex, matching Hex Edition's saved
    # x/y layout. The two diagonal neighbors depend on the column parity.
    diagonals = ((-1, -1), (-1, 1)) if column % 2 == 0 else ((1, -1), (1, 1))
    result = []
    for row_delta, column_delta in offsets + diagonals:
        next_row, next_column = row + row_delta, column + column_delta
        if 0 <= next_row < height and 0 <= next_column < width:
            result.append(next_row * width + next_column + 1)
    return result


def _hex_center(row, column):
    vertical = math.sqrt(3) * HEX_RADIUS
    return (
        round(HEX_PADDING + HEX_RADIUS + column * HEX_RADIUS * 1.5),
        round(HEX_PADDING + vertical / 2 + row * vertical + (column % 2) * vertical / 2),
    )


def _map_size(width, height):
    vertical = math.sqrt(3) * HEX_RADIUS
    return (
        math.ceil(HEX_PADDING * 2 + width * HEX_RADIUS * 1.5 + HEX_RADIUS / 2),
        math.ceil(HEX_PADDING * 2 + (height + 0.5) * vertical),
    )


def _hex_points(center):
    center_x, center_y = center
    half_height = math.sqrt(3) * HEX_RADIUS / 2
    return [
        (round(center_x - HEX_RADIUS), center_y),
        (round(center_x - HEX_RADIUS / 2), round(center_y - half_height)),
        (round(center_x + HEX_RADIUS / 2), round(center_y - half_height)),
        (round(center_x + HEX_RADIUS), center_y),
        (round(center_x + HEX_RADIUS / 2), round(center_y + half_height)),
        (round(center_x - HEX_RADIUS / 2), round(center_y + half_height)),
    ]


def _color_for_id(province_id):
    return (province_id & 0xFF, (province_id >> 8) & 0xFF, (province_id >> 16) & 0xFF)


def _build_map_assets(raw_map, nation_data, width, height):
    size = _map_size(width, height)
    terrain = pygame.Surface(size, depth=24)
    id_map = pygame.Surface(size, depth=24)
    political = pygame.Surface(size, depth=24)
    cores = pygame.Surface(size, depth=24)
    for surface in (terrain, id_map, political, cores):
        surface.fill((0, 0, 0))
    for province in raw_map.values():
        points = _hex_points(province["center"])
        is_water = province["terrain"] in c.WATER_TERRAINS
        pygame.draw.polygon(terrain, OCEAN_COLOR if is_water else LAND_COLOR, points)
        pygame.draw.polygon(id_map, province["map_color"], points)
        owner_color = nation_data[province["owner"]]["color"]
        pygame.draw.polygon(political, owner_color, points)
        core_color = owner_color if province["cores"] else nation_data["Unclaimed"]["color"]
        pygame.draw.polygon(cores, core_color, points)
    return terrain, id_map, political, cores


def build_save_payload(parsed):
    """Create GD5 metadata, structural map data, images, and conversion notes."""
    months = int(math.floor(parsed["time"]))
    year, month = divmod(months, 12)
    research = queries.get_time_appropriate_research(year)
    width, height = parsed["width"], parsed["height"]

    country_tokens = {"P", "E"}
    for record in parsed["hexes"]:
        token = record[2]
        if not _is_water(token):
            country_tokens.add(str(token).strip())
    for army in parsed["armies"]:
        for unit in army:
            if isinstance(unit, list) and len(unit) >= 7 and not _is_water(unit[6]):
                country_tokens.add(str(unit[6]).strip())

    nation_data = copy.deepcopy(queries.get_country_data())
    for token in sorted(country_tokens, key=lambda value: (value not in {"P", "E"}, value)):
        try:
            name = _country_name(token)
            nation_data[name] = _country_template(name, _hex_color(token), research)
        except GDHEXTranslationError as error:
            raise GDHEXTranslationError(f"invalid Hex Edition country token {token!r}") from error
    nation_data["Player"]["manpower"], nation_data["Player"]["fuel"], nation_data["Player"]["materials"] = [
        amount * RESOURCE_SCALE for amount in parsed["player_resources"]]
    nation_data["Enemy"]["manpower"], nation_data["Enemy"]["fuel"], nation_data["Enemy"]["materials"] = [
        amount * RESOURCE_SCALE for amount in parsed["enemy_resources"]]
    nation_data["Player"]["at_war_with"] = ["Enemy"]
    nation_data["Enemy"]["at_war_with"] = ["Player"]

    raw_map = {}
    source_keys = []
    for index, record in enumerate(parsed["hexes"]):
        province_id = index + 1
        color = _color_for_id(province_id)
        key = f"({color[0]}, {color[1]}, {color[2]})"
        source_keys.append(key)
        water = _is_water(record[2])
        owner = "Ocean" if water else _country_name(record[2])
        resource = RESOURCE_BY_CODE.get(_positive_int(record[5]))
        buildings = _factory_buildings(record[3])
        fort_level = min(_positive_int(record[4]), 20)
        if fort_level:
            buildings.append(f"Fort Lvl {fort_level}")
        row, column = divmod(index, width)
        raw_map[key] = {
            "id": province_id,
            "terrain": "ocean" if water else "plains",
            "is_coastal": False,
            "center": list(_hex_center(row, column)),
            "neighbors": _neighbors(index, width, height),
            "owner": owner,
            "units": [],
            "building_queue": [],
            "unit_queue": [],
            "orders": [],
            "buildings": buildings,
            "resources": {resource: RESOURCE_SCALE} if resource and not water else {},
            "cores": [] if water else [owner],
            "json_key": key,
            "map_color": list(color),
        }

    by_id = {province["id"]: province for province in raw_map.values()}
    for province in raw_map.values():
        if province["terrain"] != "ocean":
            province["is_coastal"] = any(
                by_id[neighbor]["terrain"] == "ocean" for neighbor in province["neighbors"])

    unit_library = queries.get_unit_library()
    skipped = set()
    for index, source_units in enumerate(parsed["armies"]):
        raw_map[source_keys[index]]["units"] = _build_units(
            source_units, year, unit_library, nation_data, skipped)

    player_country = "Player" if any(
        province["owner"] == "Player" for province in raw_map.values()) else "Spectator"
    payload = {
        "version": c.GAME_VERSION,
        "generated_at": datetime.now().isoformat(),
        "date": {"day": 15, "month": month, "year": year, "total_turns": 0},
        "loop_map": False,
        "player_country": player_country,
        "active_players": ["Player"] if player_country == "Player" else [],
        "current_player_index": 0,
        "scenario_settings": {"fog_of_war": True, "casus_belli_required": True,
                              "days_per_turn": 30, "use_scripted_events": True,
                              "ai_disabled": False},
        "script_variables": [],
        "default_research": research,
        "nation_data": nation_data,
        "provinces": {
            key: {
                field: value[field] for field in ("owner", "cores", "is_coastal", "units",
                                                   "building_queue", "unit_queue", "orders",
                                                   "resources", "buildings")
            }
            for key, value in raw_map.items()
        },
    }
    notes = [
        f"Generated a {width} x {height} GD5 hex map ({width * height} provinces).",
        "Hex AI settings, capitals, dockyard markers, queues, and unknown unit codes were not imported.",
    ]
    if skipped:
        notes.append("Skipped unsupported Hex units: " + ", ".join(sorted(skipped)) + ".")
    return payload, raw_map, _build_map_assets(raw_map, nation_data, width, height), notes


def _destination_path(source_path, saves_dir):
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", os.path.splitext(os.path.basename(source_path))[0]).strip()
    stem = stem or "GD Hex Import"
    base = os.path.join(saves_dir, f"GD HEX - {stem}")
    destination, suffix = base, 2
    while os.path.exists(destination):
        destination = f"{base} ({suffix})"
        suffix += 1
    return destination


def translate_file(source_path, saves_dir=None):
    """Convert a Hex save into a new, collision-safe GD5 save folder."""
    try:
        with open(source_path, encoding="utf-8") as handle:
            parsed = parse_save(handle.read())
    except OSError as error:
        raise GDHEXTranslationError(f"could not read {os.path.basename(source_path)}") from error

    payload, raw_map, assets, notes = build_save_payload(parsed)
    saves_dir = saves_dir or c.SAVES_DIR
    os.makedirs(saves_dir, exist_ok=True)
    destination = _destination_path(source_path, saves_dir)
    os.makedirs(destination)
    try:
        with open(os.path.join(destination, "meta.json"), "w", encoding="utf-8") as handle:
            handle.write(history_io.dump_text(payload, indent=c.SAVE_INDENT))
        with open(os.path.join(destination, "map_data.json"), "w", encoding="utf-8") as handle:
            handle.write(history_io.dump_text(raw_map, indent=c.SAVE_INDENT))
        for name, surface in zip(("terrain.png", "id_map.png", "political.png", "cores.png"), assets):
            pygame.image.save(surface, os.path.join(destination, name))
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    sync_persisted_dir(saves_dir)
    return destination, notes
