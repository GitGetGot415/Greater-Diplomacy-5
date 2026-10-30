"""Per-country summaries and shared-economy views."""

import copy
import data.constants as c
from data.state_access import session_for, world_for
from map_logic import politics
from data.queries.diplomacy import get_enemies
from data.queries.factions import are_in_same_faction, get_faction_members
from data.queries.countries import get_country_display_name, get_viewing_country
from data.queries.unit_info import units_with_air_cargo
from data.queries.economy import get_country_damage_multiplier
from data import queries


def get_nation_provinces_and_units(nation, map_data):
    """Returns a tuple of (list_of_provinces, list_of_units) owned by the nation."""
    owned_provs = []
    owned_units = []
    for prov in map_data.values():
        if prov.get("owner") == nation:
            owned_provs.append(prov)
        for unit in units_with_air_cargo(prov.get("units", [])):
            if unit.get("owner") == nation:
                owned_units.append((unit, prov))
    return owned_provs, owned_units


def shares_country_economy(viewer, country_id, nation_data):
    """Share economics with the same country, faction members, and direct subjects or masters."""
    if (viewer not in nation_data or country_id not in nation_data
            or viewer in c.UNPLAYABLE_NATIONS or country_id in c.UNPLAYABLE_NATIONS):
        return False
    return (viewer == country_id or are_in_same_faction(viewer, country_id, nation_data)
            or nation_data[country_id].get("master") == viewer
            or nation_data[viewer].get("master") == country_id)


def _country_economy_summary(country, income, expenses):
    return {
        "available": True,
        "conscription": country.get("conscription_slider", 1.0),
        "conversion": country.get("mat_to_fuel_slider", 0.0),
        "resources": [{"resource": resource, "stockpile": country.get(resource, 0),
                       "income": income[resource], "expenses": expenses[resource],
                       "net": income[resource] - expenses[resource]}
                      for resource in c.ECON_RESOURCE_KEYS],
    }


def get_shared_country_economy_summaries(viewer, map_data, nation_data, *, context=None):
    """Prepare permitted foreign totals before a network view removes private source data."""
    if context is None:
        context = nation_data
    shared = [country_id for country_id in nation_data
              if country_id != viewer and shares_country_economy(viewer, country_id, nation_data)]
    if not shared:
        return {}
    # Projection can initialize siphon rates. Do not change the authoritative state.
    economies = queries.calculate_all_economies(map_data, copy.deepcopy(nation_data), context=context)
    empty = {resource: 0 for resource in c.ECON_RESOURCE_KEYS}
    return {country_id: _country_economy_summary(
        nation_data[country_id], economies.get(country_id, {}).get("total_inc", empty),
        economies.get(country_id, {}).get("upkeep", empty)) for country_id in shared}


def can_view_country_economy(map_screen, country_id):
    """Permit shared economics and unrestricted local inspection."""
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    viewer = get_viewing_country(map_screen)
    if viewer == c.TOURNAMENT_SPECTATOR:
        return False
    if shares_country_economy(viewer, country_id, world_state.nation_data):
        return True
    if (session_state.realtime_multiplayer
            or session_state.multiplayer_mode):
        return False
    if session_state.is_editor or viewer in ("Spectator", "Editor"):
        return True
    return not queries.get_scenario_flag(
        "fog_of_war", c.DEFAULT_FOG_OF_WAR, world_state.scenario_settings)


def get_country_summary(map_screen, country_id):
    """Build a read-only country summary from information available to its viewer.

    Foreign military totals count visible units, without revealing transported cargo.
    Economy figures use the existing projections only when private information is available.
    Call this when opening the summary, never during frame rendering.
    """
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    from map_logic.system32 import combat_rules

    nation_data = world_state.nation_data
    if country_id not in nation_data or country_id in c.UNPLAYABLE_NATIONS:
        raise ValueError("Choose a country to view its summary.")
    country = nation_data[country_id]
    viewer = get_viewing_country(map_screen)
    networked = (session_state.realtime_multiplayer
                 or session_state.multiplayer_mode)
    unrestricted = (not networked and viewer != c.TOURNAMENT_SPECTATOR
                    and (session_state.is_editor or viewer in ("Spectator", "Editor")))
    complete_army = unrestricted or (country_id == viewer and not session_state.tactical_mode)
    fog = queries.get_scenario_flag("fog_of_war", c.DEFAULT_FOG_OF_WAR, world_state.scenario_settings)
    units = []
    for province in world_state.map_data.values():
        if (not complete_army and fog
                and not queries.is_province_visible(map_screen, province["id"])):
            continue
        visible_units = province.get("units", [])
        if not complete_army:
            visible_units = queries.filter_visible_units(visible_units, viewer, province, nation_data)
        candidates = units_with_air_cargo(visible_units) if complete_army else visible_units
        units.extend(unit for unit in candidates if unit.get("owner") == country_id)

    economy_available = can_view_country_economy(map_screen, country_id)
    economy = {"available": False, "resources": []}
    if economy_available:
        # Older local maps and test doubles have no network presentation cache.
        shared_economies = getattr(map_screen, "country_economy_summaries", {})
        if networked and country_id != viewer and country_id in shared_economies:
            economy = copy.deepcopy(shared_economies[country_id])
        elif not (session_state.realtime_multiplayer and country_id != viewer
                  and not getattr(map_screen, "realtime_server_map", None)):
            # Remote clients without server totals keep the economy private.
            # Economy queries can initialize missing siphon rates. Inspection must
            # not initialize or change any saved country state.
            income, expenses, _breakdown = queries.get_economy_projections(
                country_id, world_state.map_data, copy.deepcopy(nation_data), context=map_screen)
            economy = _country_economy_summary(country, income, expenses)

    faction = country.get("faction", "")
    policies = [{"name": politics.policy(policy_id)["name"], "status": state["status"],
                 "turns_remaining": state.get("turns_remaining", 0)}
                for policy_id, state in politics.policy_states(nation_data, country_id).items()]
    return {
        "country_id": country_id, "name": get_country_display_name(country_id, nation_data),
        "military": {
            "complete": complete_army, "unit_count": len(units),
            "raw_damage_output": combat_rules.volley(units),
            "damage_output": combat_rules.volley(units, nation_data=nation_data),
            "damage_multiplier": get_country_damage_multiplier(country_id, nation_data),
            "political_damage_multiplier": politics.damage_multiplier(nation_data, country_id),
            "conscription_damage_bonus": queries.get_conscription_damage_bonus(country),
        },
        "politics": {"label": politics.label(politics.value(nation_data, country_id)),
                     "value": politics.value(nation_data, country_id),
                     "drift": politics.drift(nation_data, country_id),
                     "research_multiplier": politics.research_multiplier(nation_data, country_id),
                     "policies": policies},
        "diplomacy": {"faction": faction,
                      "faction_leader": queries.get_faction_leader(faction, nation_data) if faction else None,
                      "faction_members": get_faction_members(faction, nation_data) if faction else [],
                      "master": country.get("master", ""),
                      "puppets": list(country.get("puppets", [])),
                      "enemies": get_enemies(country_id, nation_data)},
        "economy": economy,
    }
