"""Military and economic strength, attacker ranking, and combat predictions."""

import data.constants as c
from data.state_access import world_for, session_for
from data.queries.diplomacy import are_at_war, get_enemies
from data.queries.unit_info import is_air_unit, units_with_air_cargo
from data.queries.combat_state import get_unit_combat_owner
from data.queries.air import air_unit_can_move_on_ground
from data import queries


def rank_combat_nations_by_health(units):
    """Rank combat nations by the same cascade used for land capture.

    Health is the primary result, followed by combined attack and then the
    highest speed. Callers must first select eligible units. Combat forecasts
    exclude bystanders. Land capture excludes units without capture permission.
    The returned list can still contain ties after all three rules.
    The live resolver handles these ties with its bounce/random setting.
    """
    health_totals = {}
    for unit in units:
        owner = get_unit_combat_owner(unit)
        health_totals[owner] = health_totals.get(owner, 0) + unit.get("health", 0)

    top_nations = _top_total_owners(health_totals)
    if len(top_nations) > 1:
        attack_totals = {
            owner: sum(unit.get("attack", 0) for unit in units
                       if get_unit_combat_owner(unit) == owner)
            for owner in top_nations
        }
        top_nations = _top_total_owners(attack_totals)

    if len(top_nations) > 1:
        speed_totals = {
            owner: max(
                (unit.get("speed", 0) for unit in units
                 if get_unit_combat_owner(unit) == owner),
                default=0)
            for owner in top_nations
        }
        top_nations = _top_total_owners(speed_totals)

    return top_nations


def _top_total_owners(totals):
    if not totals:
        return []
    highest = max(totals.values())
    return [owner for owner, total in totals.items() if total == highest]


def get_combined_enemy_strength(target_nation, map_data, nation_data):
    """Calculates the total military strength of everyone actively fighting the target."""
    total_str = 0
    enemies = get_enemies(target_nation, nation_data)
    for enemy in enemies:
        if enemy in nation_data and enemy not in c.UNPLAYABLE_NATIONS:
            total_str += get_military_strength(enemy, map_data)
    return total_str


def get_economic_power(nation, nation_data):
    """Estimates a nation's economic power based on its resource stockpiles."""
    data = nation_data.get(nation, {})
    manpower_val = data.get("manpower", 0) * c.ECONOMY_WEIGHT_MANPOWER
    materials_val = data.get("materials", 0) * c.ECONOMY_WEIGHT_MATERIALS
    fuel_val = data.get("fuel", 0) * c.ECONOMY_WEIGHT_FUEL
    return manpower_val + materials_val + fuel_val


def get_alliance_military_strength(nation, map_data, nation_data):
    """Calculate combined military strength for a nation, its faction, and its imperial family."""
    return sum(get_military_strength(member, map_data) for member in queries.get_all_friendly_nations(nation, nation_data))


def get_military_strength(nation, map_data):
    """Calculates rough military strength of a nation based on unit stats."""
    strength = 0
    for prov in map_data.values():
        for u in units_with_air_cargo(prov.get("units", [])):
            if u.get("owner") == nation:
                strength += calculate_unit_strength(u)
    return strength


def get_nations_holding_our_cores_or_claims(nation, map_data, nation_data):
    """Returns a set of foreign nations that own territory where the given nation has a core or a claim."""
    targets = set()
    claims = nation_data.get(nation, {}).get("claims", [])
    for prov in map_data.values():
        owner = prov.get("owner")
        if owner and owner != nation and owner not in c.UNPLAYABLE_NATIONS:
            if nation in prov.get("cores", []) or prov["id"] in claims:
                targets.add(owner)
    return targets


def get_border_strength(nation_a, nation_b, map_data, id_to_province, nation_data):
    """Calculates the military strength of both nations localized to their shared border zone."""
    combined_border_provs = set()
    
    # Build a single "Front Line" zone that includes BOTH sides of the border
    for prov in map_data.values():
        owner = prov.get("owner")
        if owner == nation_a:
            for n_id in prov.get("neighbors", []):
                n_prov = id_to_province.get(n_id)
                if n_prov and n_prov.get("owner") == nation_b:
                    combined_border_provs.add(prov["id"])
                    combined_border_provs.add(n_id)
                    
    def calc_strength(prov_ids, evaluating_nation, opposing_nation):
        strength = 0
        
        # Include the imperial family and faction members defending the border.
        friendly_nations = queries.get_all_friendly_nations(evaluating_nation, nation_data)
        
        for prov_id in prov_ids:
            prov = id_to_province.get(prov_id)
            if prov:
                # Gather all friendly units on this tile
                friendly_units = [u for u in prov.get("units", []) if u.get("owner") in friendly_nations]
                
                # What this tile can actually bring to bear: a lane's front rank
                # and the relief wave behind it, best units first.
                top_units = get_front_and_relief(
                    friendly_units, terrain=prov.get("terrain"))
                
                tile_strength = 0
                for u in top_units:
                    base_str = calculate_unit_strength(u)
                    
                    # Reduce strength if this unit is actively fighting someone else on this tile
                    in_combat_with_third_party = False
                    for other_u in prov.get("units", []):
                        other_owner = other_u.get("owner")
                        if other_owner != opposing_nation and are_at_war(u.get("owner"), other_owner, nation_data):
                            in_combat_with_third_party = True
                            break
                            
                    if in_combat_with_third_party:
                        base_str *= c.AI_BORDER_DISTRACTION_MULTIPLIER
                        
                    tile_strength += base_str
                strength += tile_strength
        return strength

    # Both nations now look at the exact same cluster of frontline tiles
    return calc_strength(combined_border_provs, nation_a, nation_b), calc_strength(combined_border_provs, nation_b, nation_a)


def calculate_unit_strength(unit):
    """Unified heuristic for a unit's military power."""
    return unit.get("attack", 0) + unit.get("defense", 0) + (unit.get("health", 0) / c.MILITARY_STRENGTH_HEALTH_DIVISOR)


def format_health_percent(unit):
    """Current health as a rounded percent of max, e.g. '(50%)' -- shown beside
    a unit's name so its reduced damage output (see combat_rules.
    health_damage_multiplier) has a visible cause."""
    max_hp = unit.get("max_health") or c.DEFAULT_UNIT_HP
    pct = max(0, round(unit.get("health", 0) / max_hp * 100))
    return f"({pct}%)"


def get_top_attackers(units, count=None):
    """The highest-attack units in a list, capped at a typical lane's front rank.

    An ESTIMATE, for the AI and the UI. It is not what the resolver does and
    must never be used to decide a fight: how many of these units actually fire
    depends on how many ways the tile splits into lanes, which only
    combat_rules.build_battle can answer. This used to be the one place combat
    width was applied, which is why the drift is worth naming here.
    """
    if count is None: count = c.LANE_SLOTS_TYPICAL
    return sorted(units, key=lambda x: x.get("attack", c.DEFAULT_UNIT_ATK), reverse=True)[:count]


def get_group_attack_sum(units, count=None):
    """Combined attack of a typical front rank. An estimate -- see get_top_attackers."""
    return sum(u.get("attack", c.DEFAULT_UNIT_ATK) for u in get_top_attackers(units, count))


def get_front_and_relief(units, count=None, terrain=None):
    """The front rank plus one relief wave: what a tile is worth reinforcing to.

    Measuring a tile by its front rank alone undercounts it, since
    the units behind the front are what replace it as it dies. Measuring by the
    whole stack overcounts it, since everything past the relief wave will not
    reach a slot before the tile resolves.
    """
    if count is None:
        from map_logic.system32 import combat_rules

        slots = combat_rules.lane_slots(
            1, combat_rules.combat_width_for_terrain(terrain))
        count = int(slots * c.AI_RESERVE_DEPTH)
    return sorted(units, key=calculate_unit_strength, reverse=True)[:count]


def get_combat_predictions(map_screen):
    """Generates predictions for meeting engagements and province clashes."""
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    map_data = world_state.map_data
    nation_data = world_state.nation_data

    player_country = session_state.player_country
    is_spectator = player_country == "Spectator" or session_state.is_editor
    
    predictions = []

    # 1. Meeting engagements: use the same rule as the turn resolver, but only
    #    with movement orders the player is allowed to know. Faction and
    #    alliance membership does not disclose another nation's plans.
    from map_logic.system32 import combat_rules
    visible_to = None if is_spectator else {player_country}

    # Layers hidden submarines out of the bubble the same way the map/sidebar
    # do. Spectators and the editor keep the full, unfiltered truth.
    def sub_visible(units, prov):
        if is_spectator:
            return units
        return queries.filter_visible_units(units, player_country, prov, nation_data)

    meeting_unit_ids = set()
    for pair in combat_rules.find_meeting_pairs(map_data, nation_data, visible_to):
        prov_a, prov_b, side1, side2 = combat_rules.meeting_sides(
            world_state.id_to_province, pair, visible_to)
        # A head-on swap is resolved between its two origin tiles, so it has no
        # province bubble of its own. Keep those movers out of the ordinary
        # incoming/static pass below to avoid duplicate endpoint bubbles.
        meeting_unit_ids.update(id(unit) for unit in side1 + side2)
        predictions.append({
            "type": "meeting",
            "loc": pair,
            "side1": sub_visible(side1, prov_a),
            "side2": sub_visible(side2, prov_b)
        })

    # 2. Incoming movements, for the province clashes below.
    incoming = {}
    for prov in map_data.values():
        for u in prov.get("units", []):
            if (is_air_unit(u, context=map_screen) and not air_unit_can_move_on_ground(u, context=map_screen)) or id(u) in meeting_unit_ids:
                continue
            order = u.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                if visible_to is not None and u.get("owner") not in visible_to:
                    continue
                if not is_spectator and not queries.is_unit_visible_to(u, player_country, prov, nation_data):
                    continue
                incoming.setdefault(order["path"][0], []).append((u, prov["id"]))

    # 3. Find Province Clashes (Static Defenders vs Incoming Attackers)
    for prov in map_data.values():
        prov_id = prov["id"]
        defenders = sub_visible([unit for unit in prov.get("units", [])
                                 if id(unit) not in meeting_unit_ids], prov)
        attackers = [u for u, o in incoming.get(prov_id, [])]
        
        forces_by_owner = {}
        for u in defenders + attackers:
            forces_by_owner.setdefault(u["owner"], []).append(u)
            
        # A donor may volunteer to more than one host.  Do not reduce the
        # conflict test to the actual owner here: two divisions with the same
        # donor can have different effective military allegiances.
        all_forces = defenders + attackers
        clash = any(
            are_at_war(get_unit_combat_owner(first),
                       get_unit_combat_owner(second), nation_data)
            for index, first in enumerate(all_forces)
            for second in all_forces[index + 1:])
        if clash:
            predictions.append({
                "type": "province",
                "loc": prov_id,
                "forces": forces_by_owner
            })
            
    return predictions
