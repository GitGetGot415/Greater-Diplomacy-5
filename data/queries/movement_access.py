"""Whether a unit class may enter a tile, before path-finding."""

import data.constants as c
from data.queries.geometry import is_water_province
from data.queries.diplomacy import are_at_war, has_military_access
from data.queries.factions import _DIPLO_LOCAL, friendly_nations_view
from data import queries


def needs_military_access_request(moving_nation, target_owner, nation_data):
    """False if moving_nation can already enter target_owner's territory.

    Covers explicit grants as well as implicit access via puppet/master,
    faction, or alliance ties, so the AI doesn't ask for something it
    (or its allies) already has.
    """
    if has_military_access(moving_nation, target_owner, nation_data):
        return False
    if target_owner in friendly_nations_view(moving_nation, nation_data):
        return False
    return True


def can_convoy_enter(current_province, target_province):
    """Convoys on a land tile can only move into water tiles."""
    curr_is_water = is_water_province(current_province)
    dest_is_water = is_water_province(target_province)

    # If they're on a land tile they can only move onto an ocean one
    if not curr_is_water and not dest_is_water:
        return False
    return True


def has_surprise_attack_entry(moving_nation, target_owner, nation_data):
    """True when a queued war declaration lets units pre-position inside the target.

    Only applies while the surprise_attack scenario flag is on. Covers both the
    player's pending_diplomacy entry and the AI's queued_ai_actions list, since
    the two paths queue a declaration differently.
    """
    if not queries.get_scenario_flag("surprise_attack", c.DEFAULT_SURPRISE_ATTACK, queries.get_scenario_settings()):
        return False

    from map_logic.diplomacy import diplomacy_messages
    if diplomacy_messages.get_pending_action(nation_data, moving_nation, target_owner) == "WAR_DECLARATION":
        return True

    queued = nation_data.get(moving_nation, {}).get("queued_ai_actions", [])
    return any(q.get("target") == target_owner and q.get("action") == "WAR_DECLARATION" for q in queued)


def _resolve_owned_tile_entry(moving_nation, target_owner, nation_data):
    if has_surprise_attack_entry(moving_nation, target_owner, nation_data):
        return True
    if has_military_access(moving_nation, target_owner, nation_data):
        return True
    return target_owner in friendly_nations_view(moving_nation, nation_data)


def _can_enter_owned_tile(moving_nation, target_owner, nation_data):
    """The shared tail of the naval and land movement rules."""
    store = getattr(_DIPLO_LOCAL, "store", None)
    entry = store["entry"] if store is not None else None
    if entry is None:
        return _resolve_owned_tile_entry(moving_nation, target_owner, nation_data)

    # The answer turns on who owns the tile, not which tile it is, so a snapshot
    # only has to settle it once per nation pairing instead of once per tile.
    key = (id(nation_data), moving_nation, target_owner)
    if key not in entry:
        entry[key] = _resolve_owned_tile_entry(moving_nation, target_owner, nation_data)
    return entry[key]


def can_ships_enter(moving_nation, target_province, nation_data):
    """Centralized rules for naval movement."""
    if is_water_province(target_province): return True
    if not target_province.get("is_coastal", False): return False

    # Ships can dock in a friendly port, but cannot land on unclaimed shores
    # to claim them -- taking territory is a job for land units.
    target_owner = target_province.get("owner", "Unclaimed")
    return _can_enter_owned_tile(moving_nation, target_owner, nation_data)


def can_land_units_enter(moving_nation, target_province, nation_data):
    """Centralized rules for land movement."""
    if is_water_province(target_province): return False

    target_owner = target_province.get("owner", "Unclaimed")
    turn_start_owner = target_province.get("_turn_start_owner", target_owner)

    # If the tile was captured THIS TURN, we evaluate entry based on the original owner
    # to prevent movement execution order from blocking units moving on the exact same turn.
    if current_owner := target_owner:
        if turn_start_owner != current_owner:
            target_owner = turn_start_owner

    if target_owner in c.OWNERLESS_OWNERS: return True
    if are_at_war(moving_nation, target_owner, nation_data): return True

    return _can_enter_owned_tile(moving_nation, target_owner, nation_data)
