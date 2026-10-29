"""Faction and alliance membership, leadership, friendly-nation lookups, and pre-war snapshots."""

import contextlib
import data.constants as c
import threading
from data.state_access import world_for
from map_logic.diplomacy.faction_records import records_for, set_leadership, find, set_membership
from map_logic.diplomacy import faction_records
from data.queries.diplomacy import get_enemies


# Faction and alliance membership are pure derived data, but resolving either
# means scanning every nation -- and AI pathfinding asks for them hundreds of
# thousands of times per turn. diplomacy_snapshot() memoises those lookups for
# the length of a pass that only reads them. It is deliberately opt-in and
# thread-local: outside the block, and on every other thread, these queries
# recompute exactly as before, so no mutation can ever observe a stale answer.
_DIPLO_LOCAL = threading.local()


@contextlib.contextmanager
def diplomacy_snapshot(freeze_access=True):
    """Memoises faction/friendly lookups for the duration of a read-only pass.

    Only wrap code that leaves "faction", "master", and "puppets"
    alone -- a change to any of those inside the block would be invisible to the
    rest of it.

    freeze_access additionally memoises the "may I stand on this tile" rule,
    which also turns on military_access and on queued war declarations; pass
    False for a pass that edits either while it runs. Nesting is safe, and the
    inner block reuses the outer snapshot as-is.
    """
    if getattr(_DIPLO_LOCAL, "store", None) is not None:
        yield
        return

    _DIPLO_LOCAL.store = {
        "friendly": {},
        "faction_members": {},
        "entry": {} if freeze_access else None,
    }
    try:
        yield
    finally:
        _DIPLO_LOCAL.store = None


def get_imperial_family(nation, nation_data):
    """Returns a set containing the nation, its master (if any), and all related puppets."""
    family = set([nation])
    master = nation_data.get(nation, {}).get("master", "")
    top_dog = master if master else nation
    family.add(top_dog)
    family.update(nation_data.get(top_dog, {}).get("puppets", []))
    return family


def _compute_friendly_nations(nation, nation_data):
    friendly = get_imperial_family(nation, nation_data)
    faction = nation_data.get(nation, {}).get("faction", "")
    if faction:
        friendly.update(get_faction_members(faction, nation_data))
    return friendly


def friendly_nations_view(nation, nation_data):
    """Friendly-nation lookup for membership tests only -- never mutate the result.

    Hands back the snapshot's shared frozenset when one is active, which is what
    makes the movement rules cheap enough to call once per pathfinding edge.
    Callers that need their own mutable copy want get_all_friendly_nations.
    """
    store = getattr(_DIPLO_LOCAL, "store", None)
    if store is None:
        return _compute_friendly_nations(nation, nation_data)

    key = (id(nation_data), nation)
    cached = store["friendly"].get(key)
    if cached is None:
        cached = frozenset(_compute_friendly_nations(nation, nation_data))
        store["friendly"][key] = cached
    return cached


def get_all_friendly_nations(nation, nation_data):
    """Fetch a nation, its faction members, and its imperial family."""
    return set(friendly_nations_view(nation, nation_data))


def are_in_same_faction(nation_a, nation_b, nation_data):
    """Returns True if both nations share a faction string."""
    if records_for(nation_data) is not None:
        index = world_for(nation_data).faction_membership
        return nation_a in index and index[nation_a] == index.get(nation_b)
    fac_a = nation_data.get(nation_a, {}).get("faction", "")
    fac_b = nation_data.get(nation_b, {}).get("faction", "")
    return fac_a != "" and fac_a == fac_b


def get_faction_members(faction_name, nation_data):
    """Returns a list of all nations currently in the specified faction."""
    if not faction_name: return []
    if faction_records.records_for(nation_data) is not None:
        record = faction_records.find(nation_data, faction_name)
        return list(record["members"]) if record else []

    store = getattr(_DIPLO_LOCAL, "store", None)
    if store is None:
        return [n for n, d in list(nation_data.items()) if d.get("faction") == faction_name]

    # Under a snapshot, one pass over nation_data answers every faction instead
    # of one pass per question. Still hands back a fresh list each time, since
    # callers do stash and mutate what they get back.
    index = store["faction_members"].get(id(nation_data))
    if index is None:
        index = {}
        for n, d in list(nation_data.items()):
            fac = d.get("faction") if isinstance(d, dict) else None
            if fac:
                index.setdefault(fac, []).append(n)
        store["faction_members"][id(nation_data)] = index
    return list(index.get(faction_name, ()))


def get_faction_research_bonus(nation, tech_key, target_level, nation_data):
    """Return this faction's research-sharing bonus for one tech level.

    Only *other* members of the nation's current faction count, and a member
    must have completed at least the level the nation is pursuing.  That makes
    a faction member with Infantry III useful for an ally researching Infantry
    I or II, but not for an ally moving on to Infantry IV.
    """
    faction = nation_data.get(nation, {}).get("faction", "")
    if not faction:
        return 0.0

    try:
        target_level = int(target_level)
    except (TypeError, ValueError):
        return 0.0

    if target_level < 1:
        return 0.0

    completed_by_partners = sum(
        1 for member in get_faction_members(faction, nation_data)
        if member != nation
        and nation_data.get(member, {}).get("research", {}).get(tech_key, 0) >= target_level
    )
    return min(completed_by_partners * c.FACTION_RESEARCH_BONUS_PER_MEMBER,
               c.FACTION_RESEARCH_BONUS_CAP)


def get_faction_leader(faction_name, nation_data):
    """Returns the leader of the specified faction."""
    if not faction_name: return None
    if faction_records.records_for(nation_data) is not None:
        record = faction_records.find(nation_data, faction_name)
        return record["leader"] if record else None
    for n, d in list(nation_data.items()):
        if d.get("faction") == faction_name and d.get("is_faction_leader", False):
            return n
    return None


def set_country_faction(nation_data, country, faction):
    set_membership(nation_data, country, faction)


def get_country_faction_id(context, country):
    records_for(context)
    return world_for(context).faction_membership.get(country)


def set_faction_leadership(nation_data, country, is_leader):
    set_leadership(nation_data, country, is_leader)


def is_faction_leader(nation, nation_data):
    """Returns True if the nation is currently a faction leader."""
    records = records_for(nation_data)
    if records is not None:
        return any(record["leader"] == nation for record in records.values())
    return nation_data.get(nation, {}).get("is_faction_leader", False)


def can_invite_to_faction(nation, nation_data):
    """Only the leader of an existing faction can invite new members."""
    return bool(nation_data.get(nation, {}).get("faction")
                and is_faction_leader(nation, nation_data))


def faction_request_leadership_error(sender, target, action, nation_data):
    """Return feedback when a membership request lacks the leader's authority."""
    if action == "FACTION_INVITE" and not can_invite_to_faction(sender, nation_data):
        return "Only a faction leader may invite members."
    if action == "JOIN_FACTION_REQ" and not can_invite_to_faction(target, nation_data):
        return "You must ask the faction leader to let you join."
    return None


def get_historical_owner(province, faction_name, nation_data):
    """Returns the pre-war owner of a tile if a faction war is active, otherwise the primary core."""
    if faction_name and "FACTION_WAR_MAPS" in nation_data and faction_name in nation_data["FACTION_WAR_MAPS"]:
        pre_war = nation_data["FACTION_WAR_MAPS"][faction_name]
        return pre_war.get(str(province["id"])) or pre_war.get(province["id"])
    return province.get("cores", [None])[0] if province.get("cores") else None


def get_faction_core_transfer_target(capturer, province, nation_data):
    """
    Determines if a captured territory should be transferred to a faction member
    who has a core on it, OR who originally owned it before the war began.
    Returns the true owner to assign the province to.
    """
    if capturer in c.UNPLAYABLE_NATIONS:
        return capturer

    faction_name = nation_data.get(capturer, {}).get("faction", "")
    if not faction_name:
        return capturer

    original_owner = get_historical_owner(province, faction_name, nation_data)
    faction_members = get_faction_members(faction_name, nation_data)

    # 1. Check Pre-War Faction Map First
    if original_owner and original_owner != capturer and original_owner in faction_members:
        return original_owner

    # 2. Fallback to standard core logic
    tile_cores = province.get("cores", [])
    faction_cores_on_tile = [m for m in faction_members if m in tile_cores]

    if len(faction_cores_on_tile) == 1:
        return faction_cores_on_tile[0]
    
    return capturer


# --- NEW FACTION WAR BORDER TRACKING QUERIES ---
def is_faction_at_war(faction_name, nation_data):
    """Returns True if any member of the given faction is actively at war."""
    members = get_faction_members(faction_name, nation_data)
    return any(len(get_enemies(m, nation_data)) > 0 for m in members)


def save_faction_pre_war_map(faction_name, map_data, nation_data):
    """Snapshots the faction's borders right before entering a war."""
    if "FACTION_WAR_MAPS" not in nation_data:
        nation_data["FACTION_WAR_MAPS"] = {}

    members = get_faction_members(faction_name, nation_data)
    pre_war_map = {}
    for prov in map_data.values():
        owner = prov.get("owner")
        if owner in members:
            pre_war_map[str(prov["id"])] = owner

    nation_data["FACTION_WAR_MAPS"][faction_name] = pre_war_map
    record = find(nation_data, faction_name)
    if record is not None:
        record["pre_war_borders"] = pre_war_map


def _modify_pre_war_map(faction_name, nation_data, modify_func):
    """Helper to safely access and modify the pre-war map."""
    if "FACTION_WAR_MAPS" in nation_data and faction_name in nation_data["FACTION_WAR_MAPS"]:
        modify_func(nation_data["FACTION_WAR_MAPS"][faction_name])


def add_member_to_pre_war_map(member_name, faction_name, map_data, nation_data):
    """Adds a newly joined member's territory to the active pre-war map."""
    def _add(pre_war_map):
        for prov in map_data.values():
            if prov.get("owner") == member_name:
                pre_war_map[str(prov["id"])] = member_name
    _modify_pre_war_map(faction_name, nation_data, _add)


def remove_member_from_pre_war_map(member_name, faction_name, nation_data):
    """Removes a leaving member's territory from the active pre-war map."""
    def _remove(pre_war_map):
        keys_to_remove = [prov_id for prov_id, owner in pre_war_map.items() if owner == member_name]
        for k in keys_to_remove:
            del pre_war_map[k]
    _modify_pre_war_map(faction_name, nation_data, _remove)


def clear_faction_pre_war_map_if_peace(faction_name, nation_data):
    """Clears the pre-war map if the faction is no longer at war."""
    if not is_faction_at_war(faction_name, nation_data):
        record = find(nation_data, faction_name)
        if record is not None:
            record["pre_war_borders"].clear()
        if "FACTION_WAR_MAPS" in nation_data and faction_name in nation_data["FACTION_WAR_MAPS"]:
            del nation_data["FACTION_WAR_MAPS"][faction_name]
