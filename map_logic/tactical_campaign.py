"""Campaign glue for tactical battles: forces, results, forecasts, random armies, and columns."""

import random

import data.constants as c
from data import queries
from data.state_access import session_for, world_for
from map_logic import tactical_rules as rules
from map_logic.system32 import combat_forecast


def campaign_sides(player_unit, province, nation_data):
    """Every living unit on the tile on the player's side (player's unit first) and on the enemy side."""
    country = queries.get_unit_combat_owner(player_unit)
    enemies = queries.get_enemies(country, nation_data)
    friends = {country, *queries.get_all_friendly_nations(country, nation_data)}
    units = [unit for unit in province.get("units", []) if unit.get("health", 0) > 0]
    friendly = ([unit for unit in units if unit is player_unit]
                + [unit for unit in units if unit is not player_unit
                   and queries.get_unit_combat_owner(unit) in friends])
    return friendly, [unit for unit in units if queries.get_unit_combat_owner(unit) in enemies]


def _artillery(units, library):
    return [unit for unit in units if unit.get("type") in library
            and rules.is_land_stats(library[unit["type"]]) and rules.is_artillery(unit["type"], library)]


def campaign_forces(player_unit, province, nation_data, library):
    """The campaign units (friendly, enemy) fighting a tactical player's unit on its tile.

    On land, land fighters and packed ships fight; at sea, warships and convoys fight a
    naval battle. The player's unit leads the friendly list. Returns None when that unit
    cannot fight on this tile or no hostile fighter shares it. Artillery sits a land battle
    out, so the enemy list is empty when hostile artillery alone shares the tile: the player
    wins without a battle (win_against_artillery). Each list holds at most one army's units.
    """
    sides = campaign_sides(player_unit, province, nation_data)
    water = queries.is_water_province(province)
    # Convoys caught on land unload before fighting. Recognize their divisions
    # without first building or simulating an automatic campaign battle.
    def battle_type(unit):
        if unit.get("type", "").startswith("Convoy (") and not water:
            return unit.get("original_type")
        return unit.get("type")

    eligible = rules.naval_campaign_unit_eligible if water else rules.campaign_unit_eligible
    friendly, enemy = ([unit for unit in side if eligible(battle_type(unit), library)][:c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE]
                       for side in sides)
    if not friendly or friendly[0] is not player_unit or not (enemy or _artillery(sides[1], library)):
        return None
    return friendly, enemy


def campaign_artillery(player_unit, province, nation_data, library):
    """The land artillery-type units (friendly, enemy) on a tactical player's tile, which sit the battle out."""
    return tuple(_artillery(side, library) for side in campaign_sides(player_unit, province, nation_data))


def _remove_defeated_units(province, units):
    """Clear defeated units, including reserves that never deployed, before refreshing campaign combat."""
    for unit in units:
        unit["health"] = 0
    province["units"] = [unit for unit in province["units"] if unit.get("health", 0) > 0]


def win_against_artillery(player_unit, province, nation_data, library):
    """Hostile artillery alone cannot fight a tactical battle: the player wins at once and that artillery is destroyed."""
    _remove_defeated_units(province, campaign_sides(player_unit, province, nation_data)[1])


def tactical_encounter(context, province):
    """The (friendly, enemy) campaign units of the tactical encounter on ``province``, or None.

    Only the tile holding the tactical player's unit has one, and only while hostile units
    that can fight there (land fighters on land, ships and convoys at sea) share it. The encounter deals that tile's damage, so campaign combat must skip the tile.
    """
    session = session_for(context)
    if session.is_networked:
        return None
    unit = session.tactical_mode and session.player_unit
    if not unit or not any(other is unit for other in province.get("units", [])):
        return None
    return campaign_forces(unit, province, world_for(context).nation_data, queries.get_unit_library(context))


def tactical_meeting_side(context, prov1, prov2, units1, units2, *, pinned_units=None):
    """The tactical player's movement side, when a hostile crossing can become a tile encounter."""
    session = session_for(context)
    # Multiplayer has no tactical encounters.
    if not session.tactical_mode or session.is_networked:
        return None
    unit = session.player_unit
    if unit is None:
        return None
    for index, (side, opponents) in enumerate(((units1, units2), (units2, units1))):
        if any(other is unit for other in side):
            destination = (prov1, prov2)[1 - index]
            owner, nation_data = queries.get_unit_combat_owner(unit), world_for(context).nation_data
            # Warships meet at sea; land divisions, including packed ships, meet on land.
            if queries.get_unit_library(context).get(unit.get("type"), {}).get("naval_unit"):
                can_meet = queries.is_water_province(destination) and queries.can_ships_enter(owner, destination, nation_data)
            else:
                can_meet = queries.can_land_units_enter(owner, destination, nation_data)
            if unit.get("speed", 1) <= 0 or not can_meet:
                return None
            # A separate incoming attack takes precedence over the player's
            # head-on crossing. Movement applies this same rule at every step.
            if pinned_units is None:
                pinned_units = queries.find_movement_pins(context)
            if id(unit) in pinned_units:
                return None
            # Only hostile forces that can fight on the destination, including artillery
            # sitting a land battle out, can start the existing tactical encounter flow.
            forces = campaign_forces(unit, {"units": [unit, *opponents], "terrain": destination.get("terrain")},
                                     nation_data, queries.get_unit_library(context))
            return index if forces is not None else None
    return None


def campaign_roster(units, library, terrain=None):
    """Battle roster entries for campaign units in their form on ``terrain``, keeping each unit's fraction of health."""
    roster = []
    for unit in units:
        # Packed ships already carry their current transport stats, including damage.
        entry = dict(unit) if rules.packed_ship_type(unit["type"], library) else rules.create_battle_unit(unit["type"], unit["owner"], library, terrain)
        entry["health"] = unit["health"] / unit["max_health"] * entry["max_health"]
        entry["_supply_multiplier"] = queries.unit_supply_multiplier(unit)
        roster.append(entry)
    return roster


def apply_campaign_result(simulation, units, province, artillery, *, side_units=None, player_unit=None):
    """Write a finished battle back: each unit keeps its division's fraction of health and the dead are removed.

    ``units`` are the campaign units in roster order, friendly army then enemy army.
    ``artillery`` is (friendly, enemy) from campaign_artillery. The losing side's artillery is
    destroyed; the winning side's is untouched. Campaign callers supply ``side_units`` from
    campaign_sides so the defeat also clears units beyond the deployment limit and other
    nonparticipants on the defeated side. Neutral units and winning reserves are untouched.
    A victory preserves the player's division at 1 HP if all of its sub-units were destroyed.
    """
    for index, unit in enumerate(units):
        unit["health"] = simulation.division_health_fraction(index) * unit["max_health"]
        if unit is player_unit and simulation.winner == 0 and unit["health"] <= 0:
            unit["health"] = 1
    defeated = (artillery if side_units is None else side_units)[1 - simulation.winner]
    _remove_defeated_units(province, defeated)


def normal_game_forecast(friendly, enemy):
    """How this fight would end in the normal game: (winning army index or None, turns or None).

    The normal game's turn-by-turn forecast resolves it. Each army stands in for one of two
    countries at war with each other, so nationality, terrain width, forts, politics, and
    conscription do not apply. ``turns`` is None when the forecast finds no end.
    """
    nation_data = {nation: {"at_war_with": [other]}
                   for nation, other in zip(rules.FORECAST_NATIONS, reversed(rules.FORECAST_NATIONS))}
    sides = [[dict(unit, owner=nation) for unit in roster] for nation, roster in zip(rules.FORECAST_NATIONS, (friendly, enemy))]
    outcome = combat_forecast.estimated_combat_outcome(sides, nation_data)
    return outcome["winner_side"], outcome["turns"]


def _recent_unit_types_for_year(library, year, allowed):
    """Choose the latest unlocked tiers within the shared Random research-age limit."""
    candidates = []
    for name in queries.get_latest_units_for_year(library, year):
        if name not in allowed:
            continue
        researched = queries.get_unit_research_year(name, library)
        if researched is not None and 0 <= year - researched < rules.RANDOM_UNIT_AGE_LIMIT:
            candidates.append(name)
    return candidates


def land_unit_types_for_year(library, year):
    """Choose the latest unlocked land tiers less than five research years old."""
    return _recent_unit_types_for_year(library, year, set(rules.land_unit_types(library)))


def custom_unit_types_for_year(library, year, terrain):
    if terrain not in c.WATER_TERRAINS:
        return land_unit_types_for_year(library, year)
    return _recent_unit_types_for_year(library, year, {name for name, stats in library.items() if stats.get("naval_unit")})


def random_armies(candidates, *, rng=None):
    """Independently choose each army's size and types; repeated units are allowed."""
    if not candidates:
        raise ValueError("No units are available for the selected year and terrain.")
    rng = random if rng is None else rng
    return [[rng.choice(candidates)
             for _ in range(rng.randint(rules.RANDOM_ARMY_MIN_UNITS, rules.RANDOM_ARMY_MAX_UNITS))]
            for side in (0, 1)]


def paired_columns(count):
    """The starting formation: divisions two to a column, front to back."""
    return [index // c.CUSTOM_BATTLE_UNITS_PER_COLUMN for index in range(count)]


def valid_columns(columns, count):
    """Whether ``columns`` gives each of ``count`` roster entries a column number, in roster order.

    Columns are numbered from 0 without gaps, each holds one or two divisions, and an army
    uses at most CUSTOM_BATTLE_MAX_COLUMNS_PER_SIDE columns.
    """
    return (len(columns) == count
            and all(type(column) is int for column in columns)
            and (not columns or columns[0] == 0)
            and all(after - before in (0, 1) for before, after in zip(columns, columns[1:]))
            and all(columns.count(column) <= c.CUSTOM_BATTLE_UNITS_PER_COLUMN for column in set(columns))
            and len(set(columns)) <= c.CUSTOM_BATTLE_MAX_COLUMNS_PER_SIDE)


def column_groups(entries, columns):
    """Split a roster into its columns, front to back; each column lists its divisions top to bottom."""
    groups = []
    for entry, column in zip(entries, columns):
        if column == len(groups):
            groups.append([])
        groups[column].append(entry)
    return groups


def flatten_columns(groups):
    """The roster and its column numbers for a list of columns. Empty columns close up."""
    groups = [group for group in groups if group]
    return ([entry for group in groups for entry in group],
            [column for column, group in enumerate(groups) for _entry in group])


def open_column(groups):
    """The column a new division joins: beside the last column's only division, else a new column,
    else the first column with room. None when the army is full."""
    if groups and len(groups[-1]) < c.CUSTOM_BATTLE_UNITS_PER_COLUMN:
        return len(groups) - 1
    if len(groups) < c.CUSTOM_BATTLE_MAX_COLUMNS_PER_SIDE:
        return len(groups)
    return next((column for column, group in enumerate(groups)
                 if len(group) < c.CUSTOM_BATTLE_UNITS_PER_COLUMN), None)
