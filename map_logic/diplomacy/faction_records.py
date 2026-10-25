"""Adapt supported faction interfaces to world-owned records."""

import uuid

from data.state_access import world_for


def records_for(context):
    world = world_for(context)
    # Plain country dictionaries remain supported by public diplomacy helpers.
    if isinstance(world, dict):
        return None
    if not getattr(world, "factions_initialized", False):
        from data.migrations import faction_records
        if not world.factions:
            world.factions.update(faction_records(dict(world.nation_data)))
        project(world)
    return world.factions


def find(context, identity_or_name):
    records = records_for(context)
    if records is None:
        return None
    if identity_or_name in records:
        return records[identity_or_name]
    return next((record for record in records.values() if record["name"] == identity_or_name), None)


def project(context):
    """Refresh compatibility fields from canonical records at mutation boundaries."""
    world = world_for(context)
    records = world.factions
    world.factions_initialized = True
    world.diplomacy_revision = getattr(world, "diplomacy_revision", 0) + 1
    for country in world.nation_data.values():
        if isinstance(country, dict) and ("faction" in country or "is_faction_leader" in country):
            country["faction"] = ""
            country["is_faction_leader"] = False
    borders = {}
    world.faction_membership = {}
    for identity, record in records.items():
        for member in record["members"]:
            world.faction_membership[member] = identity
            if member in world.nation_data:
                world.nation_data[member]["faction"] = record["name"]
                world.nation_data[member]["is_faction_leader"] = member == record["leader"]
        if record.get("pre_war_borders"):
            borders[record["name"]] = record["pre_war_borders"]
    if borders or "FACTION_WAR_MAPS" in world.nation_data:
        world.nation_data["FACTION_WAR_MAPS"] = borders


def set_membership(nation_data, country, name):
    records = records_for(nation_data)
    if records is None:
        nation_data[country]["faction"] = name
        return
    current = next((record for record in records.values() if country in record["members"]), None)
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
    record = next((record for record in records.values() if country in record["members"]), None)
    if record is not None:
        if is_leader:
            record["leader"] = country
        elif record["leader"] == country:
            record["leader"] = None
    project(nation_data)


def restore(context, records=None):
    from data.migrations import faction_records
    world = world_for(context)
    world.factions = faction_records(dict(world.nation_data), records)
    project(context)
