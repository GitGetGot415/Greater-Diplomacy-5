"""Compatibility projections for tournament intents and encrypted payload decoding."""

import copy
import gzip
import json

from map_logic import politics


def tournament_player_intents(payload, map_data=None):
    """Read intents and reject conflicting older choice projections."""
    commands = payload["player_intents"]
    if not isinstance(commands, list):
        raise ValueError("Player intents must be a list.")
    country = payload.get("nation_data", {})
    provinces = payload.get("provinces", {})
    if not isinstance(country, dict) or not isinstance(provinces, dict):
        raise ValueError("Invalid compatibility projection.")
    transport = [command for command in commands
                 if isinstance(command, dict) and command.get("type") == "air_transport"]
    if "air_transport" in payload and payload["air_transport"] != transport:
        raise ValueError("Conflicting aircraft cargo choices in the move file.")
    by_id = {province["id"]: province.get("json_key") for province in (map_data or {}).values()}
    # Current intents establish state. Older projections are retained for supported readers.
    # A field present in both representations must describe the same choice.
    unit_choices = {unit.get("unit_id"): unit for province in provinces.values()
                    if isinstance(province, dict) for unit in province.get("units", [])
                    if isinstance(unit, dict) and unit.get("unit_id")}
    unit_choices.update({unit.get("unit_id"): unit for unit in payload.get("aircraft_orders", [])
                         if isinstance(unit, dict) and unit.get("unit_id")})
    for province in provinces.values():
        if not isinstance(province, dict):
            raise ValueError("Invalid province compatibility projection.")
        for unit in province.get("units", []):
            if not isinstance(unit, dict) or not isinstance(unit.get("type"), str):
                raise ValueError("Invalid unit compatibility projection.")
    for command in commands:
        if not isinstance(command, dict):
            raise ValueError("Invalid player intent.")
        kind = command.get("type")
        if kind == "province_queue":
            older = provinces.get(by_id.get(command.get("province_id")), {})
            queue = command.get("queue")
            if queue in older and older[queue] != command.get("items"):
                raise ValueError("Conflicting production choices in the move file.")
        elif kind == "research_queue" and "research_queue" in country:
            if [entry.get("tech_name") for entry in country["research_queue"]] != command.get("tech_names"):
                raise ValueError("Conflicting research choices in the move file.")
        elif kind == "army_roster" and "armies" in country:
            if country["armies"] != command.get("armies"):
                raise ValueError("Conflicting army choices in the move file.")
        elif kind == "unit_order" and command.get("unit_id") in unit_choices:
            older = unit_choices[command["unit_id"]]
            for key in ("order", "custom_name", "combat_stance", "lane_target"):
                if key in older and older[key] != command.get(key):
                    raise ValueError("Conflicting unit choices in the move file.")
        elif kind == "country_preferences":
            for key in (*politics.DRIFT_KEYS, "automation", "conscription_slider",
                        "mat_to_fuel_slider", "research_funding_slider", "custom_production_units"):
                if key in country and country[key] != command.get(key):
                    raise ValueError("Conflicting country choices in the move file.")
        elif kind == "country_appearance":
            for key, value in command.get("appearance", {}).items():
                if key in country and country[key] != value:
                    raise ValueError("Conflicting country appearance in the move file.")
        elif kind == "faction_rename" and payload.get("faction_renames"):
            if command.get("name") != payload["faction_renames"][-1].get("new_name"):
                raise ValueError("Conflicting faction renames in the move file.")
    return copy.deepcopy(commands)


def decode_saved_json(payload):
    """Decode compressed JSON or the older plain JSON inside encrypted files."""
    if payload.startswith(b'\x1f\x8b'):
        payload = gzip.decompress(payload)
    return json.loads(payload.decode('utf-8'))
