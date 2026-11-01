"""Tournament move projections and encrypted-file payloads from older versions.

data/migrations/v46_moves.py reads whole v46 moves. These helpers serve it and the current loader.
"""

import copy
import gzip
import json

from data.state_access import world_for
from map_logic import politics
from map_logic.diplomacy import diplomacy_lifecycle as lifecycle
from map_logic.diplomacy.action_definitions import availability


def tournament_player_intents(payload, map_data=None):
    """Read optional intents and reject conflicting older choice projections."""
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
            for key in ("political_drift", "automation", "conscription_slider",
                        "mat_to_fuel_slider", "custom_production_units"):
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


def legacy_player_country(map_ref, country_id, nation_update):
    """Prepare a player's record without changing host state.

    Faction membership is shared state.  The player can queue a leave/invite
    in their normal diplomacy data, but the authoritative outcome is resolved
    by the host at turn processing.  A member's old move must therefore not
    restore the previous faction string after its leader has renamed the bloc.
    """
    from data import queries
    world_state = world_for(map_ref)
    if not isinstance(nation_update, dict) or country_id not in world_state.nation_data:
        raise ValueError("The move does not contain a valid country record.")

    existing = world_state.nation_data[country_id]
    faction_state = {
        key: existing[key]
        for key in ("faction", "is_faction_leader", "faction_pressure", "faction_tenure")
        if key in existing
    }
    merged = dict(nation_update)
    for key in ("faction", "is_faction_leader", "faction_pressure", "faction_tenure"):
        if key in faction_state:
            merged[key] = faction_state[key]
        else:
            merged.pop(key, None)

    # Tournament moves carry a full country record, but policy countdowns are
    # host-owned turn state.  Read only the player's requested lifecycle
    # statuses and rebuild the timers from the host's existing country record.
    requested_policies = politics.policy_draft_projection({country_id: merged}, country_id)
    canonical_policies = politics.canonicalize_policy_draft(
        world_state.nation_data, country_id, requested_policies)
    if canonical_policies:
        merged[politics.POLICY_KEY] = canonical_policies
    else:
        merged.pop(politics.POLICY_KEY, None)

    probe = copy.deepcopy(world_state.nation_data)
    lifecycle.normalize_diplomacy_channels(probe)
    pending = merged.get("pending_diplomacy", {})
    responses = merged.get("diplo_responses", {})
    draft_lists = merged.get("draft_lists", {})
    if not all(isinstance(channel, dict) for channel in (pending, responses, draft_lists)):
        raise ValueError("Invalid diplomatic channels.")
    if any(not isinstance(record, (dict, str)) for record in pending.values()):
        raise ValueError("Invalid diplomatic request.")
    if any(not isinstance(response, dict) for response in responses.values()):
        raise ValueError("Invalid diplomatic response.")
    submitted = {country_id: copy.deepcopy(merged)}
    lifecycle.normalize_diplomacy_channels(submitted)
    drafts = {}
    for target, record in submitted[country_id]["pending_diplomacy"].items():
        if record.get("turns", 0) > 0:
            host_record = probe[country_id].get("pending_diplomacy", {}).get(target)
            supplied = pending[target]
            reference = supplied.get("request_id") if isinstance(supplied, dict) else None
            if (not isinstance(host_record, dict) or record.get("action") != host_record.get("action")
                    or (reference is not None and reference != host_record.get("request_id"))):
                raise ValueError("A travelling request does not belong to this move.")
        else:
            available = availability(map_ref, country_id, target, record.get("action", ""))
            if not available.allowed:
                # Older snapshots discard invalid drafts while retaining unrelated choices.
                continue
            drafts[target] = record
    canonical_responses = {}
    for target, response in submitted[country_id]["diplo_responses"].items():
        canonical = dict(response)
        canonical.pop("legacy_unmatched", None)
        canonical.update(lifecycle.canonical_response_reference(probe, country_id, target, response))
        canonical_responses[target] = canonical
    lifecycle.apply_draft(probe, country_id, drafts, canonical_responses, draft_lists)
    for channel in ("pending_diplomacy", "diplo_responses", "draft_lists"):
        merged[channel] = probe[country_id].get(channel, {})
    ratification = merged.get("pending_ratification")
    host_ratification = probe[country_id].get("pending_ratification")
    if isinstance(ratification, dict):
        reference = ratification.get("treaty_id")
        if (not isinstance(host_ratification, dict)
                or (reference is not None and reference != host_ratification.get("treaty_id"))):
            raise ValueError("That ratification refers to an expired treaty.")
        merged["pending_ratification"] = copy.deepcopy(host_ratification)
        if "verdict" in ratification:
            merged["pending_ratification"]["verdict"] = ratification["verdict"]
        else:
            merged["pending_ratification"].pop("verdict", None)
    elif ratification is not None:
        raise ValueError("Invalid treaty ratification.")
    elif isinstance(host_ratification, dict):
        merged["pending_ratification"] = copy.deepcopy(host_ratification)
    return merged
