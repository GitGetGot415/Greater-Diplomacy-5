"""Where combat is taking place and which units a nation can see."""

import data.constants as c
import itertools
from data.queries.diplomacy import are_at_war, get_enemies
from data import queries


def get_unit_combat_owner(unit):
    """The diplomatic side a unit temporarily fights for.

    Volunteer units retain their donor in ``owner`` for commands and vision,
    while their host supplies their movement, combat, and capture allegiance.
    """
    return unit.get("volunteer_host") or unit.get("owner", "")


def is_province_in_active_combat(province, nation_data):
    """Returns True if ANY units from mutually hostile nations occupy this province."""
    units = province.get("units", [])
    if len(units) < 2:
        return False
        
    owners_present = list(set(get_unit_combat_owner(u) for u in units
                              if get_unit_combat_owner(u)))
    
    # Optimized check using itertools
    return any(are_at_war(o1, o2, nation_data) for o1, o2 in itertools.combinations(owners_present, 2))


def is_nation_in_combat_here(nation, province, nation_data):
    """Returns True if the specified nation has units in the province that are actively engaged with enemy units."""
    units = province.get("units", [])
    enemies = get_enemies(nation, nation_data)
    return any(get_unit_combat_owner(u) in enemies for u in units)


def is_submarine_unit(unit_type):
    """Checks if a unit belongs to the Submarine family, at any research level."""
    return unit_type.startswith("Submarine")


def is_unit_visible_to(unit, viewer_nation, province, nation_data):
    """Whether `viewer_nation` is allowed to see this unit, on top of ordinary fog of war.

    Submarines stay hidden from everyone outside the owner's imperial family
    and faction -- unless mutually hostile nations are already trading
    fire in the province, at which point there is no more hiding among them.
    Every other unit type is unaffected.
    """
    if not is_submarine_unit(unit.get("type", "")):
        return True
    if viewer_nation == c.TOURNAMENT_SPECTATOR:
        return False
    if viewer_nation not in nation_data:
        # Spectator/Editor/no-country views ignore fog of war entirely, same as
        # get_visible_provinces -- there's no nation here to keep a secret from.
        return True
    owner = unit.get("owner")
    if owner == viewer_nation or owner in queries.get_all_friendly_nations(viewer_nation, nation_data):
        return True
    return queries.is_province_in_active_combat(province, nation_data)


def filter_visible_units(units, viewer_nation, province, nation_data):
    """Returns `units` with any submarines `viewer_nation` may not see stripped out."""
    return [u for u in units if queries.is_unit_visible_to(u, viewer_nation, province, nation_data)]


def is_hostile_territory(moving_nation, target_owner, nation_data):
    """Checks if a nation is actively at war with the target territory."""
    if target_owner in c.UNPLAYABLE_NATIONS:
        return False
    return are_at_war(moving_nation, target_owner, nation_data)


# Combat locations are always described from one nation's perspective.  These
# names deliberately match the map bubbles, but are rules-facing categories so
# future mechanics do not have to reimplement the fort-territory test.
COMBAT_LOCATION_DEFENSE = "defense"


COMBAT_LOCATION_OFFENSE = "offense"


COMBAT_LOCATION_GENERIC = "generic"


# Backwards-compatible name for callers that use "unknown" to mean that the
# viewer has no usable side-specific information. The rendered asset is now
# the generic bubble.
COMBAT_LOCATION_UNKNOWN = COMBAT_LOCATION_GENERIC
