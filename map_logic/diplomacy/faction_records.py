"""Adapt supported faction interfaces to world-owned records."""

import copy
import hashlib
import uuid

from data.state_access import world_for
from data.world_nations import WorldNations


def canonical_records(nation_data, records=None):
    """Read canonical factions or convert repaired country projections once."""
    if records is not None:
        if not isinstance(records, dict):
            raise ValueError("Faction records must be a mapping.")
        result = copy.deepcopy(records)
        assigned = set()
        for identity, record in result.items():
            if (not isinstance(identity, str) or not identity or not isinstance(record, dict)
                    or not isinstance(record.get("name"), str) or not record["name"]
                    or not isinstance(record.get("members"), list)
                    or not record["members"] or (record.get("leader") is not None
                                                and record["leader"] not in record["members"])
                    or not isinstance(record.get("pre_war_borders", {}), dict)):
                raise ValueError("Invalid faction record.")
            for member in record["members"]:
                if not isinstance(member, str) or member not in nation_data or member in assigned:
                    raise ValueError("Faction members must be distinct existing countries.")
                assigned.add(member)
            record.setdefault("pre_war_borders", {})
        return result
    groups = {}
    for country, data in nation_data.items():
        if isinstance(data, dict) and data.get("faction"):
            groups.setdefault(data["faction"], []).append(country)
    result = {}
    for name, members in groups.items():
        leader = next((member for member in members
                       if nation_data[member].get("is_faction_leader")), None)
        # Existing leadership repair selects a successor after loading land and units.
        identity = "faction-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]
        result[identity] = {"name": name, "leader": leader, "members": members,
                            "pre_war_borders": copy.deepcopy(
                                nation_data.get("FACTION_WAR_MAPS", {}).get(name, {}))}
    return result


def records_for(context):
    # Plain country dictionaries remain supported by public diplomacy helpers.
    if isinstance(context, dict) and not isinstance(context, WorldNations):
        return None
    world = world_for(context)
    if not world.factions_initialized:
        if not world.factions:
            world.factions.update(canonical_records(dict(world.nation_data)))
        project(world)
    return world.factions


def find(context, identity_or_name):
    records = records_for(context)
    if records is None:
        return None
    if identity_or_name in records:
        return records[identity_or_name]
    return next((record for record in records.values() if record["name"] == identity_or_name), None)


def country_record(context, country):
    records = records_for(context)
    if records is None:
        return None
    return records.get(world_for(context).faction_membership.get(country))


def pre_war_map(nation_data, faction):
    if not faction:
        return None
    if records_for(nation_data) is None:
        return nation_data.get("FACTION_WAR_MAPS", {}).get(faction)
    record = find(nation_data, faction)
    return (record.get("pre_war_borders") or None) if record else None


def set_pre_war_map(nation_data, faction, borders):
    if records_for(nation_data) is None:
        if borders is None:
            nation_data.get("FACTION_WAR_MAPS", {}).pop(faction, None)
        else:
            nation_data.setdefault("FACTION_WAR_MAPS", {})[faction] = borders
    else:
        record = find(nation_data, faction)
        if record is not None:
            record["pre_war_borders"] = {} if borders is None else borders


def pre_war_maps(nation_data):
    records = records_for(nation_data)
    if records is None:
        return nation_data.get("FACTION_WAR_MAPS", {})
    return {record["name"]: record["pre_war_borders"] for record in records.values()
            if record.get("pre_war_borders")}


def saved_country_projection(nation_data):
    """Supply the old name-keyed border view to existing save consumers."""
    result = dict(nation_data)
    if records_for(nation_data) is not None:
        borders = pre_war_maps(nation_data)
        if borders:
            result["FACTION_WAR_MAPS"] = copy.deepcopy(borders)
        else:
            result.pop("FACTION_WAR_MAPS", None)
    return result


def project(context):
    """Refresh compatibility fields from canonical records at mutation boundaries."""
    world = world_for(context)
    records = world.factions
    world.factions_initialized = True
    world.diplomacy_revision += 1
    for country in world.nation_data.values():
        if isinstance(country, dict) and ("faction" in country or "is_faction_leader" in country):
            country["faction"] = ""
            country["is_faction_leader"] = False
    world.faction_membership = {}
    for identity, record in records.items():
        for member in record["members"]:
            world.faction_membership[member] = identity
            if member in world.nation_data:
                world.nation_data[member]["faction"] = record["name"]
                world.nation_data[member]["is_faction_leader"] = member == record["leader"]


def set_membership(nation_data, country, name):
    records = records_for(nation_data)
    if records is None:
        nation_data[country]["faction"] = name
        return
    current = country_record(nation_data, country)
    if current is not None and current["name"] == name:
        return
    if current is not None:
        current["members"].remove(country)
        if current["leader"] == country:
            current["leader"] = None
        if not current["members"]:
            identity = next(key for key, value in records.items() if value is current)
            del records[identity]
    if name:
        record = find(nation_data, name)
        if record is None:
            record = {"name": name, "leader": None, "members": [], "pre_war_borders": {}}
            records["faction-" + uuid.uuid4().hex] = record
        record["members"].append(country)
        # Preserve the previous country-order processing policy when members join.
        order = {member: index for index, member in enumerate(nation_data)}
        record["members"].sort(key=order.__getitem__)
    nation_data[country]["faction"] = name
    project(nation_data)


def set_leadership(nation_data, country, is_leader):
    records = records_for(nation_data)
    if records is None:
        nation_data[country]["is_faction_leader"] = is_leader
        return
    record = country_record(nation_data, country)
    if record is not None:
        if is_leader:
            record["leader"] = country
        elif record["leader"] == country:
            record["leader"] = None
    project(nation_data)


def restore(context, records=None):
    world = world_for(context)
    world.factions = canonical_records(dict(world.nation_data), records)
    # Remove the legacy field at the input boundary. A query can initialize
    # records while its caller is iterating the country mapping.
    world.nation_data.pop("FACTION_WAR_MAPS", None)
    project(context)
