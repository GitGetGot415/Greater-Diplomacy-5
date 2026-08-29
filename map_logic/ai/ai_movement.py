# --- START OF FILE CHANGES ---
import heapq
import data.constants as c
from data import queries
from map_logic.turn_processing import combat_rules

def build_neighbor_index(id_to_province):
    """Maps each tile to its neighbours that actually exist on the map.

    Dropping the dangling ids up front is what lets the pathfinder walk an edge
    without looking the destination province up just to confirm it is real.
    """
    return {
        p_id: [n_id for n_id in prov.get("neighbors", ()) if n_id in id_to_province]
        for p_id, prov in id_to_province.items()
    }

def _tile_depth(capacity, tile):
    """How many units `tile` can actually use: a front rank, and its relief.

    Under the lane model a tile's front slots depend on how many ways the fight
    there splits, so this is looked up per tile rather than read off a single
    constant -- `capacity` holds combat_rules.nation_front_capacity's answer for
    the nation doing the planning. A tile nobody measured (a quiet border, an
    empty target) falls back to a typical one-enemy lane, which is the fight
    that would open there if one started.

    The relief rank is counted because a body behind the front is not wasted the
    way it would be if it were surplus: it rotates in as the units ahead of it
    die. Bodies past that are the wasted ones, and under lanes they are wasted
    completely -- they absorb nothing at all while they wait.
    """
    slots = capacity.get(tile) if capacity else None
    if not slots:
        slots = c.LANE_SLOTS_TYPICAL
    return max(1.0, slots * c.AI_RESERVE_DEPTH)


def _tile_pressure(assignments, stacks, tile, capacity=None):
    """How reluctant we are to send one more unit to `tile`.

    A tile holding a full front rank and a full relief rank has nothing to gain
    from the next body, however much the weights want it there, so it sorts
    behind every tile with room and the existing weighted count decides among
    the rest exactly as before.

    This is the only thing in this file that reads combat width. Everything
    else the AI does already scaled with it -- what to buy, what a unit is
    worth, how strong a border is -- while movement spread units evenly across
    targets and never asked how many could fight once they arrived. Lower the
    width and it kept piling five onto a tile where three did nothing; raise it
    and it kept trickling one at a time and never massed anywhere.

    `stacks` is a true unit count, kept apart from `assignments` because that
    one carries preference weights (a battle pulls at -20, a quiet border pushes
    at +50) and so cannot answer "is this tile full?" on its own.
    """
    return (1 if stacks.get(tile, 0) >= _tile_depth(capacity, tile) else 0,
            assignments.get(tile, 0))


def _bfs_nearest_target(start_id, target_ids, allowed_prov_ids, id_to_province, target_assignments, is_convoy=False, is_ship=False, moving_nation=None, nation_data=None, unsafe_waters=None, unit_speed=1.0, water_ids=None, neighbor_ids=None, target_stacks=None, target_capacity=None):
    """Finds shortest path using Dijkstra. Returns the path to the target with the least units assigned."""
    if unsafe_waters is None:
        unsafe_waters = {}
    if target_stacks is None:
        target_stacks = {}
    if target_capacity is None:
        target_capacity = {}
    if water_ids is None:
        water_ids = {p_id for p_id, p in id_to_province.items() if queries.is_water_province(p)}
    if neighbor_ids is None:
        neighbor_ids = build_neighbor_index(id_to_province)

    # Partial paths are cons cells -- (tile_id, cell_it_came_from) -- rather than
    # lists. Extending one is a single tuple instead of copying the whole path,
    # and branches share their common prefix, which matters because this search
    # queues hundreds of thousands of candidates per turn.
    queue = [(0.0, 0, start_id, (start_id, None))]
    visited = {start_id: 0.0}
    valid_paths = []
    found_cost = -1.0
    counter = 1

    # Costs and the depth limit only depend on the unit, so resolve them once.
    speed = max(1.0, float(unit_speed))
    land_step = 1.0 if is_ship else 1.0 / speed
    sea_step = 1.0 * c.AI_SEA_PATH_PENALTY_MULTIPLIER
    # DEPTH OF 10 SO AI CAN SEE FAR (Scaled by speed)
    depth_slack = 10.0 / speed

    # If already on a target, staying is evaluated as a valid option
    if start_id in target_ids:
        valid_paths.append((0.0, (start_id, None)))
        found_cost = 0.0

    while queue:
        current_cost, _, curr, path = heapq.heappop(queue)

        # Allow search a few tiles deeper than the first found target
        # so it can accurately discover empty borders further down the line.
        if found_cost != -1.0 and current_cost > found_cost + depth_slack:
            break

        neighbors = neighbor_ids.get(curr)
        if not neighbors: continue

        curr_is_water = curr in water_ids

        for n_id in neighbors:
            # --- NEW CONVOY AND NAVAL BFS RULE ---
            dest_is_water = n_id in water_ids

            if is_convoy or is_ship:
                if not curr_is_water and not dest_is_water:
                    continue # Convoys and Ships on land cannot move to another land tile

                if not dest_is_water:
                    n_prov = id_to_province[n_id]

                    if is_ship:
                        # Ships can only enter friendly coastal tiles
                        if not queries.can_ships_enter(moving_nation, n_prov, nation_data):
                            continue

                    if is_convoy:
                        # Convoys landing must obey land border rules
                        if not queries.can_land_units_enter(moving_nation, n_prov, nation_data):
                            continue

            # --- NEW: Cost Calculation for Dijkstra ---
            # Land unit over water (Convoy) pays the sea penalty; everything else
            # pays its own per-tile rate.
            step_cost = sea_step if (dest_is_water and not is_ship) else land_step

            new_cost = current_cost + step_cost

            # --- BLOCK SUICIDE PATHS ---

            if n_id in target_ids:
                valid_paths.append((new_cost, (n_id, path)))
                if found_cost == -1.0:
                    found_cost = new_cost

            if n_id in allowed_prov_ids and (n_id not in visited or new_cost < visited[n_id]):
                visited[n_id] = new_cost
                heapq.heappush(queue, (new_cost, counter, n_id, (n_id, path)))
                counter += 1

    # Pick the path pointing to the target with the LEAST assignments, tie-breaking by cost.
    if valid_paths:
        # A cell's head is the tile the path ends on.
        best_cell = min(valid_paths,
                        key=lambda p: _tile_pressure(target_assignments, target_stacks, p[1][0],
                                                     target_capacity) + (p[0],))[1]

        # If the best path is just staying where we are, return an empty array so we don't move
        if best_cell[0] == start_id:
            return []

        # Unwind the cons chain, which runs destination-first.
        best_path = []
        while best_cell is not None:
            best_path.append(best_cell[0])
            best_cell = best_cell[1]
        best_path.reverse()

        return best_path[1:]

    return []

def process_ai_unit_orders(map_screen):
    """Generates movement orders for AI-controlled units to balance borders, attack, or escort."""
    # Order generation only reads the diplomatic picture -- it writes unit orders
    # and nothing else -- so faction and alliance membership can be resolved once
    # for the whole pass instead of once per pathfinding edge.
    with queries.diplomacy_snapshot():
        _generate_unit_orders(map_screen)


# ============================================================================ #
#                   _generate_unit_orders PHASE HELPERS                        #
# ============================================================================ #
# One nation's order pass runs a fixed pipeline: figure out who it's fighting
# and where its borders/targets/dangers are, tally how many units are already
# assigned to each one, then walk its units assigning orders against those
# tallies. Each phase reads/writes a shared `ctx` dict rather than a long
# parameter list, since the phases were originally one function's locals and
# the next phase often needs several of the previous one's results at once.

def _build_shared_pathing_caches(map_screen):
    """Water-tile lookup and neighbour index: identical for every nation this
    pass, so built once rather than per-nation."""
    allowed_prov_ids_cache = set()
    for prov in map_screen.map_data.values():
        if queries.is_water_province(prov):
            allowed_prov_ids_cache.add(prov["id"])
    water_ids = allowed_prov_ids_cache
    neighbor_ids = build_neighbor_index(map_screen.id_to_province)
    return allowed_prov_ids_cache, water_ids, neighbor_ids


def _reset_orders_and_collect_units(map_screen, ai_nations):
    """Clears every AI unit's movement order (so it rethinks its strategy every
    turn) and buckets units/provinces by owning nation.

    Standing multi-turn commitments survive. This pass runs a few lines after
    ai_construction in prepare_turn, and clearing unconditionally destroyed the
    DISBAND orders construction had just issued -- DISBAND is only executed
    later, in movement_processor, by which point the order was gone. The effect
    was that no AI unit had ever been disbanded: peacetime militia accumulated
    indefinitely and the obsolete-unit cull never ran once.

    A unit already committed is also skipped for order assignment, since it is
    busy; see _assign_unit_orders.
    """
    nation_units = {}
    nation_provs = {}

    for ai_name in ai_nations:
        provs, units = queries.get_nation_provinces_and_units(ai_name, map_screen.map_data)
        nation_provs[ai_name] = provs
        nation_units[ai_name] = []

        for unit, prov in units:
            order = unit.get("order")
            if isinstance(order, dict) and order.get("type") in c.MULTI_TURN_ORDER_TYPES:
                continue  # Already committed; leave it be and do not re-task it.

            # Clear old path so the AI can rethink its strategy every turn
            unit["order"] = {"type": "MOVE", "path": []}
            nation_units[ai_name].append((unit, prov))

    return nation_units, nation_provs


def _gather_enemies(map_screen, ai_name):
    """This nation's current enemies, plus (if the scenario enables surprise
    attacks) anyone it has a war declaration queued or drafted against."""
    enemies = list(map_screen.nation_data[ai_name].get("at_war_with", []))

    if queries.get_scenario_flag("surprise_attack", c.DEFAULT_SURPRISE_ATTACK):
        queued = map_screen.nation_data[ai_name].get("queued_ai_actions", [])
        pending_wars = [q["target"] for q in queued if q.get("action") == "WAR_DECLARATION"]

        pending = map_screen.nation_data[ai_name].get("pending_diplomacy", {})
        for target, info in pending.items():
            if isinstance(info, dict) and info.get("action") == "WAR_DECLARATION":
                pending_wars.append(target)

        if pending_wars:
            enemies = list(set(enemies + pending_wars))

    return enemies


def _compute_unsafe_waters(map_screen, ai_name):
    """Pre-calculates areas heavily patrolled by enemies so Convoys and weak
    ships don't suicide into them."""
    unsafe_waters = {}
    for p in map_screen.map_data.values():
        if queries.is_water_province(p):
            # Hidden enemy submarines don't make a water tile read as patrolled --
            # an AI that routed convoys around them would be reacting to a fleet
            # it has no way of knowing is there.
            visible_units = queries.filter_visible_units(p.get("units", []), ai_name, p, map_screen.nation_data)
            enemy_str = sum(u.get("attack", c.DEFAULT_UNIT_ATK) + u.get("defense", 0) for u in visible_units
                            if queries.are_at_war(ai_name, u.get("owner"), map_screen.nation_data)
                            and queries.is_naval_unit(u.get("type", "")))
            if enemy_str > 0:
                unsafe_waters[p["id"]] = enemy_str
    return unsafe_waters


def _discover_borders_and_targets(map_screen, ai_name, my_provs, enemies, friendly_nations):
    """Locates coastal/enemy/unclaimed tiles globally (for naval targeting and
    island hopping and distant-ally expeditions) and classifies each of this
    nation's own border provinces as a war, peace, or coastal border."""
    war_borders = set()
    peace_borders = set()
    coastal_borders = set()
    enemy_targets = set()
    all_enemy_coasts = set()
    enemy_coastal_waters = set()
    unclaimed_targets = set()
    all_unclaimed_coasts = set()
    expedition_targets = set()

    # Locate coastal provinces globally for naval targeting and island hopping
    for prov in map_screen.map_data.values():
        owner = prov.get("owner", "Unclaimed")

        if prov.get("is_coastal", False):
            if enemies and owner in enemies:
                all_enemy_coasts.add(prov["id"])

                # Find adjacent water tiles for ships to blockade from
                for n_id in prov.get("neighbors", []):
                    n_prov = map_screen.id_to_province.get(n_id)
                    if n_prov and queries.is_water_province(n_prov):
                        enemy_coastal_waters.add(n_id)

            # Identify unclaimed islands globally
            elif owner in c.UNOWNED_LAND_OWNERS:
                all_unclaimed_coasts.add(prov["id"])

        # --- Distant Allied Wars / Expedition Targets ---
        if enemies:
            # 1. Reinforce allied battles
            if queries.is_province_in_active_combat(prov, map_screen.nation_data):
                units_here = prov.get("units", [])
                if any(u.get("owner") in friendly_nations for u in units_here):
                    expedition_targets.add(prov["id"])

            # 2. Reinforce allied borders touching mutual enemies
            if owner in enemies:
                for n_id in prov.get("neighbors", []):
                    n_prov = map_screen.id_to_province.get(n_id)
                    if n_prov and n_prov.get("owner") in friendly_nations and n_prov.get("owner") != ai_name:
                        expedition_targets.add(prov["id"])
                        break

    for prov in my_provs:
        is_war_border = False
        is_peace_border = False
        is_coastal = prov.get("is_coastal", False)

        for n_id in prov.get("neighbors", []):
            n_prov = map_screen.id_to_province.get(n_id)
            if not n_prov: continue
            if queries.is_water_province(n_prov): continue

            n_owner = n_prov.get("owner", "Unclaimed")
            if n_owner in enemies:
                is_war_border = True
                enemy_targets.add(n_id)
            elif n_owner in c.UNOWNED_LAND_OWNERS:
                unclaimed_targets.add(n_id)
            elif n_owner != ai_name and n_owner not in c.WATER_NATIONS and not queries.are_in_same_faction(ai_name, n_owner, map_screen.nation_data):
                is_peace_border = True

        if is_war_border:
            war_borders.add(prov["id"])
        elif is_peace_border:
            peace_borders.add(prov["id"])
        elif is_coastal:
            coastal_borders.add(prov["id"])

    return {
        "war_borders": war_borders,
        "peace_borders": peace_borders,
        "coastal_borders": coastal_borders,
        "enemy_targets": enemy_targets,
        "all_enemy_coasts": all_enemy_coasts,
        "enemy_coastal_waters": enemy_coastal_waters,
        "unclaimed_targets": unclaimed_targets,
        "all_unclaimed_coasts": all_unclaimed_coasts,
        "expedition_targets": expedition_targets,
    }


def _tile_is_lost(map_screen, ai_name, prov, friendly_nations):
    """Whether holding this tile means losing everything standing on it.

    Asked of the lane model rather than of the whole stack. The old sum divided
    *every* hostile unit's attack among our defenders, but under lanes only the
    seated front fires and only the seated front is shot at -- so an enemy who
    turned up with eight men and six slots was counted at eight, the tile was
    written off as lost, and it then dropped out of active_battles and out of
    the reinforcement pull entirely. The reserves that would have held it were
    told there was no battle to go to.

    A tile is lost when the rank we have in it is wiped and there is nobody
    behind them to step in. A relief rank is the difference between a bad turn
    and a rout, which is the distinction the retreat is supposed to be making.
    """
    units = list(prov.get("units", ()))
    battle = combat_rules.build_battle([units], map_screen.nation_data)

    ours, incoming = [], {}
    for lane in battle.lanes:
        for side in (lane.a, lane.b):
            for member in side.members:
                if member.nation in friendly_nations:
                    ours.extend(member.front)
                elif member.targets and queries.are_at_war(ai_name, member.nation,
                                                           map_screen.nation_data):
                    # apply_group_damage splits a volley among the units it may
                    # legally hit, so this is the figure each of them eats.
                    share = combat_rules.volley(member.front, battle.shares,
                                                map_screen.nation_data) / len(member.targets)
                    for target in member.targets:
                        incoming[id(target)] = incoming.get(id(target), 0.0) + share

    if not ours or not incoming:
        return False

    for unit in ours:
        taken = max(0.0, incoming.get(id(unit), 0.0) - unit.get("defense", c.DEFAULT_UNIT_DEF))
        if taken < unit.get("health", 1):
            return False

    # The front dies. Only a rout if there is no second rank to take its place.
    seated = {id(u) for u in ours}
    return not any(id(u) not in seated and u.get("owner") in friendly_nations
                   for u in units)


def _attackers_would_survive(map_screen, ai_name, target_prov, attackers):
    """Whether at least one attacker survives the first exchange at a target.

    A charge that kills every incoming unit is resolved immediately by
    ``combat_processor.process_pinning``. Ask the same battle builder and
    projected damage helper here, so the AI does not deliberately issue a move
    that the resolver will turn into an instant wipeout. A unit that is not in
    a lane is treated as surviving: it is not actually part of this fight.
    """
    attackers = list(attackers)
    if not attackers:
        return False

    target_units = list(target_prov.get("units", ()))
    battle = combat_rules.build_battle(
        [target_units, attackers], map_screen.nation_data)
    if not battle.lanes:
        return True

    incoming = combat_rules.projected_incoming_damage(
        battle, map_screen.nation_data)
    engaged_ids = {
        id(unit)
        for lane in battle.lanes
        for side in (lane.a, lane.b)
        for unit in side.front
    }

    return any(
        id(unit) not in engaged_ids
        or incoming.get(id(unit), 0.0) < unit.get("health", 1)
        for unit in attackers
    )


def _attack_target_is_immediate_loss(map_screen, ai_name, target_id, unit):
    """True when moving ``unit`` into ``target_id`` would be an instant wipe."""
    target_prov = map_screen.id_to_province.get(target_id)
    if not target_prov:
        return False

    if not any(queries.are_at_war(ai_name, defender.get("owner"),
                                  map_screen.nation_data)
               for defender in target_prov.get("units", ())):
        return False

    return not _attackers_would_survive(
        map_screen, ai_name, target_prov, [unit])


def _track_battles_and_convoys(map_screen, ai_name, units_info, friendly_nations, unsafe_waters, all_enemy_coasts, enemy_coastal_waters):
    """Finds active battles (and whether this nation is about to lose them, in
    which case it picks a retreat tile), plus which convoys are in combat or
    near danger so the escort-priority weighting can protect them."""
    friendly_convoys = set()
    convoy_in_combat = set()
    convoy_near_ship = set()
    convoy_near_coast = set()

    active_battles = set()
    lost_battles = {} # prov_id -> safe_retreat_id

    for unit, prov in units_info:
        p_id = prov["id"]
        if queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data):
            if p_id not in active_battles and p_id not in lost_battles:

                # Evaluate if the AI will lose this battle on the next turn
                if _tile_is_lost(map_screen, ai_name, prov, friendly_nations):
                    # Find a safe retreat target for the group
                    safe_retreats = []
                    for n_id in prov.get("neighbors", []):
                        if n_id in unsafe_waters: continue
                        n_prov = map_screen.id_to_province.get(n_id)
                        if not n_prov: continue
                        n_owner = n_prov.get("owner", "Unclaimed")
                        if not queries.is_hostile_territory(ai_name, n_owner, map_screen.nation_data):
                            safe_retreats.append(n_id)

                    if safe_retreats:
                        # Prioritize friendly territory
                        best_retreat = safe_retreats[0]
                        for r_id in safe_retreats:
                            if map_screen.id_to_province[r_id].get("owner") in friendly_nations:
                                best_retreat = r_id
                                break
                        lost_battles[p_id] = best_retreat
                    else:
                        active_battles.add(p_id) # Nowhere to run, fight to the death
                else:
                    active_battles.add(p_id)

        if unit.get("type", "").startswith("Convoy"):
            friendly_convoys.add(p_id)
            # Escort AI: Determine how much danger the convoy is in
            if queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data):
                convoy_in_combat.add(p_id)
            else:
                near_ship = False
                near_coast = False
                for n_id in prov.get("neighbors", []):
                    if n_id in unsafe_waters:
                        near_ship = True
                    elif n_id in all_enemy_coasts or n_id in enemy_coastal_waters:
                        near_coast = True

                if near_ship:
                    convoy_near_ship.add(p_id)
                elif near_coast:
                    convoy_near_coast.add(p_id)

    return {
        "active_battles": active_battles,
        "lost_battles": lost_battles,
        "friendly_convoys": friendly_convoys,
        "convoy_in_combat": convoy_in_combat,
        "convoy_near_ship": convoy_near_ship,
        "convoy_near_coast": convoy_near_coast,
    }


def _build_target_assignments(units_info, borders, battles, at_war, capacity=None):
    """Picks the destination sets (land and naval) this nation's units can be
    routed to, and tallies + weights how many units are already assigned to
    each one so orders spread out rather than piling onto one tile."""
    peace_borders = borders["peace_borders"]
    coastal_borders = borders["coastal_borders"]
    war_borders = borders["war_borders"]
    unclaimed_targets = borders["unclaimed_targets"]
    all_unclaimed_coasts = borders["all_unclaimed_coasts"]
    enemy_targets = borders["enemy_targets"]
    all_enemy_coasts = borders["all_enemy_coasts"]
    enemy_coastal_waters = borders["enemy_coastal_waters"]
    expedition_targets = borders["expedition_targets"]

    active_battles = battles["active_battles"]
    friendly_convoys = battles["friendly_convoys"]
    convoy_in_combat = battles["convoy_in_combat"]
    convoy_near_ship = battles["convoy_near_ship"]
    convoy_near_coast = battles["convoy_near_coast"]

    # --- FIX: UNIVERSAL TARGETS ---
    # ALWAYS include peace and coastal borders to prevent abandonment
    target_destinations = list(set(list(unclaimed_targets) + list(all_unclaimed_coasts) + list(peace_borders) + list(coastal_borders) + list(active_battles)))

    if at_war:
        # Inject expedition_targets so distant armies mobilize!
        target_destinations = list(set(target_destinations + list(enemy_targets) + list(all_enemy_coasts) + list(expedition_targets)))

    # If no targets (e.g. island with no neighbors), fall back to coastal borders.
    if not target_destinations:
        target_destinations = list(coastal_borders)

    # Keep track of how many units are assigned to each target so we can spread them evenly
    target_assignments = {t_id: 0 for t_id in target_destinations}

    naval_destinations = list(set(list(enemy_coastal_waters) + list(friendly_convoys)))
    naval_assignments = {t_id: 0 for t_id in naval_destinations}

    # Convoy Escort Priority
    # Apply massive negative weights so warships heavily prioritize covering active convoys
    for c_id in friendly_convoys:
        if c_id in naval_assignments:
            naval_assignments[c_id] -= c.AI_CONVOY_ESCORT_WEIGHT
            if c_id in convoy_in_combat:
                naval_assignments[c_id] -= c.AI_CONVOY_COMBAT_WEIGHT
            elif c_id in convoy_near_ship:
                naval_assignments[c_id] -= c.AI_CONVOY_DANGER_SHIP_WEIGHT
            elif c_id in convoy_near_coast:
                naval_assignments[c_id] -= c.AI_CONVOY_DANGER_COAST_WEIGHT

    # How many units are really on each target, kept clear of the weights
    # below so _tile_pressure can ask whether a tile is full of fighters rather
    # than merely unpopular. Counted before the battle pull, which now needs to
    # know how full a tile already is.
    target_stacks = {t_id: 0 for t_id in target_destinations}
    naval_stacks = {t_id: 0 for t_id in naval_destinations}

    # Pre-count units already AT the targets
    for unit, prov in units_info:
        if prov["id"] in target_assignments:
            target_assignments[prov["id"]] += 1
            target_stacks[prov["id"]] += 1
        if prov["id"] in naval_assignments:
            naval_assignments[prov["id"]] += 1
            naval_stacks[prov["id"]] += 1

    # Active Battle Reinforcement Priority, fading as the front and its relief
    # fill up.
    #
    # A flat pull said "this battle is worth 20 units" whatever the combat width
    # was, so a wider front drew no more men than a narrow one -- capping the
    # stack stopped the AI wasting bodies but never made it mass any. Scaling by
    # the share still empty means the pull runs out exactly where the tile stops
    # being able to use another body: at a front rank plus one relief rank. Same
    # strength as before on an empty tile, so a battle still outranks a quiet
    # border by the same margin it always did.
    for b_id in active_battles:
        if b_id in target_assignments:
            depth = _tile_depth(capacity, b_id)
            room = max(0, depth - target_stacks.get(b_id, 0)) / depth
            target_assignments[b_id] -= c.AI_REINFORCE_COMBAT_WEIGHT * room

    # --- STRATEGIC WEIGHTING FIX ---
    # 1. Coasts are low priority. Inflate their count so units prefer land borders.
    for c_id in coastal_borders:
        if c_id in target_assignments and c_id not in peace_borders and c_id not in war_borders:
            target_assignments[c_id] += 1

    # 2. Push the main army to the frontlines! Only keep 1 guard per peace/coastal
    # border during war or expansion. The guard stays at one whatever the combat
    # width is: a quiet border is a garrison, not a firing line.
    if at_war or unclaimed_targets:
        for p_id in peace_borders:
            if target_assignments.get(p_id, 0) >= 1:
                target_assignments[p_id] += c.AI_REAR_GUARD_PENALTY
        for c_id in coastal_borders:
            if target_assignments.get(c_id, 0) >= 1:
                target_assignments[c_id] += c.AI_REAR_GUARD_PENALTY

    # 3. Penalize expedition targets so the AI defends its homeland fronts FIRST.
    for e_id in expedition_targets:
        if e_id in target_assignments and e_id not in enemy_targets and e_id not in war_borders:
            target_assignments[e_id] += c.AI_EXPEDITION_WEIGHT

    return {
        "target_destinations": target_destinations,
        "naval_destinations": naval_destinations,
        "target_assignments": target_assignments,
        "naval_assignments": naval_assignments,
        "target_stacks": target_stacks,
        "naval_stacks": naval_stacks,
        "target_capacity": capacity or {},
    }


def _bombardment_target(map_screen, ai_name, prov, bomb_range):
    """The in-range tile whose enemy stack is worth shelling most, or None."""
    best_id, best_value = None, 0.0
    in_range = queries.get_bombardment_targets(prov, map_screen.id_to_province, bomb_range)

    for target_id in sorted(in_range):
        target = map_screen.id_to_province.get(target_id)
        if not target:
            continue
        visible_units = queries.filter_visible_units(target.get("units", ()), ai_name, target, map_screen.nation_data)
        value = sum(queries.calculate_unit_strength(u) for u in visible_units
                    if queries.are_at_war(ai_name, u.get("owner"), map_screen.nation_data))
        if value > best_value:
            best_id, best_value = target_id, value

    return best_id


def _try_bombard(map_screen, ai_name, unit, prov):
    """Orders a barrage if this unit has a gun and anything to point it at.

    Bombardment costs nothing, draws no return fire, and sits outside the lane
    system entirely -- it is the only thing in the game that reaches a unit
    waiting in reserve, which under the lane model is most of a deep stack. A
    bombarding unit still fights on its own tile, so the shot is pure profit. The AI had no
    bombardment code at all: it bought artillery, valued it for a barrage, and
    then walked it into melee to swing a melee attack a fraction the size.

    The order is reissued every turn, because process_bombardments clears it
    after firing and the best target moves.
    """
    bomb_range = queries.get_bombardment_range(unit.get("type", ""))
    if bomb_range <= 0:
        return False

    target_id = _bombardment_target(map_screen, ai_name, prov, bomb_range)
    if target_id is None:
        return False

    unit["order"] = {"type": "BOMBARD", "target_id": target_id}
    return True


def _assign_unit_orders(map_screen, ai_name, units_info, ctx, allowed_prov_ids, water_ids, neighbor_ids):
    """Walks every one of this nation's units and assigns it a MOVE/CONVERT
    order: retreat from a lost battle, hold a defensive line, push into
    unclaimed or enemy territory next door, or path to the nearest tile that
    still needs reinforcing."""
    unsafe_waters = ctx["unsafe_waters"]
    friendly_nations = ctx["friendly_nations"]
    war_borders = ctx["war_borders"]
    peace_borders = ctx["peace_borders"]
    coastal_borders = ctx["coastal_borders"]
    unclaimed_targets = ctx["unclaimed_targets"]
    active_battles = ctx["active_battles"]
    lost_battles = ctx["lost_battles"]
    at_war = ctx["at_war"]
    target_destinations = ctx["target_destinations"]
    naval_destinations = ctx["naval_destinations"]
    target_assignments = ctx["target_assignments"]
    naval_assignments = ctx["naval_assignments"]
    target_stacks = ctx["target_stacks"]
    naval_stacks = ctx["naval_stacks"]
    target_capacity = ctx["target_capacity"]

    def claim(tile, from_tile=None):
        """Books one unit onto `tile`, freeing the tile it left.

        The counts have to move as orders are issued, not only reflect where
        everyone started, or the second unit this turn would see the same empty
        battle tile the first one did.
        """
        target_assignments[tile] = target_assignments.get(tile, 0) + 1
        target_stacks[tile] = target_stacks.get(tile, 0) + 1
        if from_tile is not None and from_tile in target_assignments:
            target_assignments[from_tile] -= 1
            target_stacks[from_tile] = max(0, target_stacks.get(from_tile, 0) - 1)

    def pressure(tile):
        return _tile_pressure(target_assignments, target_stacks, tile, target_capacity)

    for unit, prov in units_info:
        u_type = unit.get("type", "")
        is_convoy = u_type.startswith("Convoy")
        is_naval_combatant = queries.is_naval_unit(u_type) and not is_convoy

        curr_id = prov["id"]

        # --- NEW: GROUP RETREAT FROM LOST BATTLES ---
        if curr_id in lost_battles:
            retreat_target = lost_battles[curr_id]
            n_prov = map_screen.id_to_province.get(retreat_target)
            if n_prov:
                can_retreat = False
                if is_convoy and queries.can_convoy_enter(prov, n_prov): can_retreat = True
                elif is_naval_combatant and (queries.is_water_province(n_prov) or queries.can_ships_enter(ai_name, n_prov, map_screen.nation_data)): can_retreat = True
                elif not is_naval_combatant and not is_convoy and queries.can_land_units_enter(unit["owner"], n_prov, map_screen.nation_data): can_retreat = True

                if can_retreat:
                    unit["order"]["path"] = [retreat_target]
                    continue
        # --------------------------------------------

        # --- ANTI-SHUFFLE & COMBAT INTERCEPTS ---
        in_combat = queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data)

        # If the AI is currently engaged in active combat on its tile...
        if in_combat:
            # Check if we are hopelessly outmatched and should pull our ships/convoys out
            my_str = sum(u.get("attack", c.DEFAULT_UNIT_ATK) + u.get("defense", 0) for u in prov.get("units", []) if u.get("owner") in friendly_nations)
            enemy_str = sum(u.get("attack", c.DEFAULT_UNIT_ATK) + u.get("defense", 0) for u in prov.get("units", []) if queries.are_at_war(ai_name, u.get("owner"), map_screen.nation_data))

            # If Navy is outnumbered 1.5-to-1, or if a Convoy is literally fighting ANY warship
            if (is_naval_combatant and enemy_str > my_str * 1.5) or (is_convoy and enemy_str > 0):
                safe_retreats = []
                for n_id in prov.get("neighbors", []):
                    if n_id in unsafe_waters: continue # Don't retreat into ANOTHER enemy fleet
                    n_prov = map_screen.id_to_province.get(n_id)
                    if not n_prov: continue

                    if is_convoy and queries.can_convoy_enter(prov, n_prov):
                        safe_retreats.append(n_id)
                    elif is_naval_combatant and (queries.is_water_province(n_prov) or queries.can_ships_enter(ai_name, n_prov, map_screen.nation_data)):
                        safe_retreats.append(n_id)

                if safe_retreats:
                    unit["order"]["path"] = [safe_retreats[0]]
                    continue # Successfully ordered retreat, skip normal BFS
            # -----------------------------------

            # Holding the line does not preclude firing: a bombarding unit still
            # fights on its own tile, so the barrage is pure profit. Tried only
            # after the retreat decisions above, so a fleet that should be
            # withdrawing does not stand and shell instead.
            _try_bombard(map_screen, ai_name, unit, prov)
            continue # Otherwise, hold the line and fight!

        # --- BOMBARDMENT ---
        # Free, draws no return fire, and the one thing not capped by combat
        # width, so a gun with anything in range has nothing better to do. An
        # adjacent enemy is inside range 1, which is what stops artillery
        # walking into a melee to swing a melee attack a fraction the size.
        if _try_bombard(map_screen, ai_name, unit, prov):
            continue
        # -------------------

        # If we are holding a defensive border (peace or coastal) and we are the ONLY unit here, HOLD THE LINE.
        # Do not apply this to war_borders because we WANT to push forward into enemy_targets.
        is_defensive_hold = (curr_id in peace_borders or curr_id in coastal_borders) and curr_id not in war_borders

        # Break the hold if there's an active battle literally 1 tile away!
        is_near_battle = any(n in active_battles for n in prov.get("neighbors", []))
        if is_near_battle:
            is_defensive_hold = False

        if not is_naval_combatant and is_defensive_hold:
            if target_assignments.get(curr_id, 0) <= 1:
                continue # Stay put!

        adjacent_unclaimed = [n for n in prov.get("neighbors", []) if n in unclaimed_targets]

        # PREVENT ILLEGAL CONVOY MOVES
        if is_convoy:
            adjacent_unclaimed = [n for n in adjacent_unclaimed if queries.can_convoy_enter(prov, map_screen.id_to_province.get(n)) and n not in unsafe_waters]

        if adjacent_unclaimed and not is_naval_combatant:
            best_adj = min(adjacent_unclaimed, key=pressure)

            speed = unit.get("speed", 1)
            unit["order"]["path"] = [best_adj]

            # Let fast units pathfind deeper into unclaimed territory!
            if speed > 1:
                curr_node = best_adj
                for _ in range(speed - 1):
                    curr_prov_data = map_screen.id_to_province.get(curr_node)
                    if not curr_prov_data: break

                    next_options = []
                    for n_id in curr_prov_data.get("neighbors", []):
                        n_prov = map_screen.id_to_province.get(n_id)
                        if not n_prov: continue

                        # Prevent backtracking
                        if n_id in unit["order"]["path"] or n_id == curr_id:
                            continue

                        # Obey movement rules using constants
                        if is_convoy:
                            if not queries.can_convoy_enter(curr_prov_data, n_prov) or n_id in unsafe_waters:
                                continue
                        else:
                            if queries.is_water_province(n_prov):
                                continue

                        # Check if it's a valid tile to push into
                        n_owner = n_prov.get("owner", "Unclaimed")
                        if n_owner in c.UNOWNED_LAND_OWNERS:
                            next_options.append(n_id)

                    if next_options:
                        # Pick the adjacent unclaimed tile with the least attackers to spread the expansion
                        next_step = min(next_options, key=pressure)
                        unit["order"]["path"].append(next_step)
                        claim(next_step)
                        curr_node = next_step
                    else:
                        # Reached a dead end (e.g. hit an ocean or claimed border)
                        break
            # -----------------------------------------------------------------------

            claim(best_adj, from_tile=curr_id)
            continue

        if at_war and not is_naval_combatant:
            # Include expedition targets in the adjacent strike check so they can push off allied territory
            adjacent_targets = [n for n in prov.get("neighbors", []) if n in target_destinations and (n in ctx["enemy_targets"] or n in ctx["expedition_targets"])]

            # PREVENT ILLEGAL CONVOY ATTACKS
            if is_convoy:
                adjacent_targets = [n for n in adjacent_targets if queries.can_convoy_enter(prov, map_screen.id_to_province.get(n)) and n not in unsafe_waters]

            if adjacent_targets:
                adjacent_targets = [
                    target_id for target_id in adjacent_targets
                    if not _attack_target_is_immediate_loss(
                        map_screen, ai_name, target_id, unit)
                ]
            if adjacent_targets:
                # Pick the adjacent enemy with the least attackers currently assigned
                best_adj = min(adjacent_targets, key=pressure)

                speed = unit.get("speed", 1)
                unit["order"]["path"] = [best_adj]

                # Let fast units pathfind deeper from the border!
                if speed > 1:
                    curr_node = best_adj
                    for _ in range(speed - 1):
                        curr_prov_data = map_screen.id_to_province.get(curr_node)
                        if not curr_prov_data: break

                        next_options = []
                        for n_id in curr_prov_data.get("neighbors", []):
                            n_prov = map_screen.id_to_province.get(n_id)
                            if not n_prov: continue

                            # Prevent backtracking
                            if n_id in unit["order"]["path"] or n_id == curr_id:
                                continue

                            # Obey movement rules using your constants/queries
                            if is_convoy:
                                if not queries.can_convoy_enter(curr_prov_data, n_prov) or n_id in unsafe_waters:
                                    continue
                            else:
                                if queries.is_water_province(n_prov):
                                    continue

                            # Check if it's a valid tile to push into
                            n_owner = n_prov.get("owner", "Unclaimed")
                            if queries.is_hostile_territory(ai_name, n_owner, map_screen.nation_data) or n_owner in c.UNOWNED_LAND_OWNERS:
                                next_options.append(n_id)

                        if next_options:
                            # Pick the adjacent hostile tile with the least attackers to spread the invasion
                            next_step = min(next_options, key=pressure)
                            unit["order"]["path"].append(next_step)
                            claim(next_step)
                            curr_node = next_step
                        else:
                            # Reached a dead end (e.g. hit an ocean or friendly border)
                            break

                claim(best_adj, from_tile=curr_id)
                continue

        # Branch routing logic between ground forces and naval forces
        if is_naval_combatant:
            targets = naval_destinations
            assignments = naval_assignments
            stacks = naval_stacks
        else:
            targets = target_destinations
            assignments = target_assignments
            stacks = target_stacks

        # Do not route a unit toward an occupied hostile tile if the first
        # exchange is guaranteed to kill that unit. Empty targets and fights
        # where the unit is not at war with anyone remain valid destinations.
        targets = [
            target_id for target_id in targets
            if not _attack_target_is_immediate_loss(
                map_screen, ai_name, target_id, unit)
        ]

        if not targets:
            continue

        # Bypass the depth limiter for fully garrisoned borders: drop anything
        # carrying the rear-guard penalty, and anything already holding a full
        # front and relief, since neither has anything to gain from one more body.
        priority_targets = [t for t in targets
                            if assignments.get(t, 0) < c.AI_REAR_GUARD_PENALTY
                            and stacks.get(t, 0) < _tile_depth(target_capacity, t)]
        search_targets = priority_targets if priority_targets else targets

        # Route to the nearest border/enemy/coast/convoy that needs reinforcements
        path = _bfs_nearest_target(
            curr_id,
            set(search_targets),
            allowed_prov_ids,
            map_screen.id_to_province,
            assignments,
            is_convoy=is_convoy,
            is_ship=is_naval_combatant,
            moving_nation=ai_name,
            nation_data=map_screen.nation_data,
            unsafe_waters=unsafe_waters,
            unit_speed=unit.get("speed", 1),
            water_ids=water_ids,
            neighbor_ids=neighbor_ids,
            target_stacks=stacks,
            target_capacity=target_capacity
        )

        if path:
            # Convoy Conversion Check
            next_prov = map_screen.id_to_province.get(path[0])
            next_is_water = queries.is_water_province(next_prov)

            if next_is_water and not is_convoy and not is_naval_combatant:
                # Cannot step onto water, must explicitly convert first
                unit["order"] = {"type": "CONVERT", "turns_left": 1, "to": "Convoy"}
            else:
                # Truncate the AI's path to match its actual movement speed
                speed = unit.get("speed", 1)

                # PREVENT LAND UNITS QUEUEING INTO OCEAN MID-MOVE
                final_path = []
                for step_id in path[:speed]:
                    step_prov = map_screen.id_to_province.get(step_id)
                    if not is_convoy and not is_naval_combatant and step_prov and queries.is_water_province(step_prov):
                        break
                    final_path.append(step_id)

                unit["order"]["path"] = final_path

            # Tell the system this unit is taking this target, reducing its
            # priority -- and filling a slot on it, so the next unit to look
            # sees a tile one body closer to full rather than the same one this
            # unit just claimed.
            if curr_id in assignments:
                assignments[curr_id] -= 1
                stacks[curr_id] = max(0, stacks.get(curr_id, 0) - 1)
            if path[-1] in assignments:
                assignments[path[-1]] += 1
                stacks[path[-1]] = stacks.get(path[-1], 0) + 1


def _repair_havens(map_screen, ai_name, my_provs, ctx):
    """Tiles where this nation could repair a unit: industry, and no enemy on it.

    Exactly the two conditions the player's own orders panel applies -- "Needs
    Factory" (queries.has_industry) and "In Combat" -- and deliberately nothing
    else. Whether a tile is somewhere you would *march* a wounded unit to is a
    different question, asked separately in _march_havens; conflating the two is
    what stopped a Soviet Heavy Tank III sitting at 4% health on top of its own
    factory in province 295 from repairing (saves/NOT REPAIRING). That tile
    borders four German provinces, so it is a war border, so it was not a haven,
    so the tank marched off to take empty ground instead.

    A unit already standing on a factory is not choosing where to be. It is not
    in combat, it is holding the tile either way -- REPAIR blocks movement, not
    fighting -- and at 4% health it is contributing almost nothing to holding
    it. Repairing is simply the best thing it can do with the turn, and where
    the tile sits on the map has no bearing on that.
    """
    havens = set()
    for prov in my_provs:
        if not queries.has_industry(prov):
            continue
        if queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data):
            continue
        havens.add(prov["id"])
    return havens


def _march_havens(havens, ctx):
    """The subset of `havens` worth walking a wounded unit to.

    Marching is a choice about where to be, so here the war border does matter:
    arriving somewhere that is about to be attacked is the situation the unit
    was sent away from. Deciding this at the destination rather than in
    _repair_havens is what keeps a unit already standing on a front-line factory
    free to repair where it is.
    """
    return havens - ctx["war_borders"]


def _may_leave_the_line(map_screen, ai_name, unit, prov, ctx):
    """Whether this unit can be spared for the march home.

    The repair trip is the one order that deliberately walks a unit away from
    the war, so what it must never do is open a hole. A tile on the war border,
    in a battle, or next to one, or held by this unit alone, is a tile this unit
    is the defence of; everywhere else it is one of several and can be missed.
    """
    curr_id = prov["id"]
    if curr_id in ctx["war_borders"] or curr_id in ctx["active_battles"]:
        return False
    if any(n in ctx["active_battles"] for n in prov.get("neighbors", ())):
        return False

    friendly_nations = ctx["friendly_nations"]
    return any(u.get("owner") in friendly_nations and u is not unit
               for u in prov.get("units", ()))


def _assign_maintenance_orders(map_screen, ai_name, units_info, ctx,
                               allowed_prov_ids, water_ids, neighbor_ids):
    """Sends wounded or idle units to repair or upgrade instead of a move order.

    Mirrors what a human player would click in the orders panel. Three triggers:

    - Wounded, and already standing somewhere it can be fixed: below
      c.AI_REPAIR_ON_SITE_FRACTION health, on a haven (see _repair_havens). A
      unit this hurt deals reduced damage now (see
      combat_rules.health_damage_multiplier), so it is worth less in the next
      fight than the same unit at full health -- fixing it is worth the turn.
    - Wounded, and not: below the harder c.AI_REPAIR_HEALTH_FRACTION line it is
      worth the march as well, so it is sent home. See below.
    - Idle: on a quiet tile with no battle nearby and nothing else routed
      through it, with research holding a better version of its type. A unit
      that was going to do nothing this turn anyway loses nothing by upgrading.

    Chosen units are dropped from `units_info` in place, so _assign_unit_orders
    never reassigns them a move order this turn. Repairing and upgrading only
    block movement (c.ORDERS_BLOCKING_MOVEMENT) -- the unit is still standing on
    its tile and still fights if it is attacked -- so this never actually leaves
    a front unmanned, only unmoving for a turn.

    **The trip.** Repair has always required industry on the tile a unit was
    *already* standing on, and nothing in the AI ever sent one there, while
    _assign_unit_orders actively pushes units toward the enemy. So the mechanic
    was unreachable in practice: it could only fire on a unit that happened to
    be shot up on top of its own factory. A unit that commits to the march
    carries `unit["repair_trip"]`, which is a plain key rather than an order
    because _reset_orders_and_collect_units wipes orders every turn and the walk
    home takes several -- the unit would be re-tasked back to the front at the
    first junction. It is handled before anything else here, and dropped the
    moment it stops making sense.
    """
    unit_library = queries.get_unit_library()
    tech_tree = queries.get_tech_tree()
    nation = map_screen.nation_data.get(ai_name, {})
    research = nation.get("research", {})
    free_repairs = queries.get_scenario_flag(
        "free_repairs", c.DEFAULT_FREE_REPAIRS, map_screen.scenario_settings)

    war_borders = ctx["war_borders"]
    active_battles = ctx["active_battles"]
    target_assignments = ctx["target_assignments"]
    havens = ctx["repair_havens"]
    march_targets = _march_havens(havens, ctx)

    def health_fraction(unit):
        return unit.get("health", 0) / max(1.0, unit.get("max_health", 1))

    def repair_costs(unit):
        """What the orders panel would charge for this repair, or all zeroes."""
        if free_repairs:
            return {"cost_materials": 0, "cost_manpower": 0, "cost_fuel": 0}
        m_hp = unit.get("max_health", 1)
        missing_pct = (m_hp - unit.get("health", 0)) / max(1, m_hp)
        stats = unit_library.get(unit.get("original_type", unit.get("type", "")), {})
        return {res: int(stats.get(res, 0) * missing_pct)
                for res in ("cost_materials", "cost_manpower", "cost_fuel")}

    def start_repair(unit):
        """Issues REPAIR if the nation can pay for it. True if it did."""
        costs = repair_costs(unit)
        if not queries.can_afford(nation, costs):
            return False
        queries.deduct_resources(nation, costs)
        unit.pop("repair_trip", None)
        unit["order"] = {"type": "REPAIR", "turns_left": 1, "refund": costs}
        return True

    def route(unit, curr_id, targets):
        """An all-land march to the nearest of `targets`, or None.

        Land units only, and overland only. The trip is a unit walking home
        through its own country, and neither half of that is negotiable: a ship
        cannot reach a factory, a convoy is a land unit mid-crossing that should
        finish the crossing first, and a land unit routed over water needs the
        CONVERT-to-Convoy dance _assign_unit_orders does for an invasion. None
        of that is worth it to fix one division, so a repair that would need an
        amphibious operation simply does not happen.
        """
        path = _bfs_nearest_target(
            curr_id, set(targets), allowed_prov_ids, map_screen.id_to_province,
            target_assignments,
            moving_nation=ai_name, nation_data=map_screen.nation_data,
            unit_speed=unit.get("speed", 1),
            water_ids=water_ids, neighbor_ids=neighbor_ids)
        if not path or any(step in water_ids for step in path):
            return None
        return path

    # Units already walking home count against the cap, so a nation cannot send
    # its whole army back one turn at a time.
    trips = sum(1 for unit, _prov in units_info if unit.get("repair_trip") is not None)

    remaining = []
    for unit, prov in units_info:
        curr_id = prov["id"]
        in_combat = queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data)
        speed = unit.get("speed", 1)
        u_type = unit.get("type", "")
        is_convoy = u_type.startswith("Convoy")
        is_naval_combatant = queries.is_naval_unit(u_type) and not is_convoy
        marches = not is_convoy and not is_naval_combatant

        # --- a trip already under way ---------------------------------------
        trip = unit.get("repair_trip")
        if trip is not None:
            if health_fraction(unit) >= c.AI_REPAIR_ON_SITE_FRACTION or trip not in havens:
                # Healed on the way, or the destination was taken, overrun, or
                # lost its industry while the unit was still walking to it.
                unit.pop("repair_trip", None)
                trips -= 1
            elif curr_id == trip:
                if not in_combat and start_repair(unit):
                    trips -= 1
                    continue
            else:
                path = route(unit, curr_id, {trip})
                if path:
                    unit["order"]["path"] = path[:speed]
                    continue
                # The way home is cut. Fight where it stands.
                unit.pop("repair_trip", None)
                trips -= 1

        if in_combat:
            remaining.append((unit, prov))
            continue

        # --- repair, here or at home -----------------------------------------
        wants_repair = False
        if curr_id in havens:
            if health_fraction(unit) < c.AI_REPAIR_ON_SITE_FRACTION:
                wants_repair = True
                if start_repair(unit):
                    continue
        elif (marches
                and march_targets
                and trips < c.AI_MAX_REPAIR_TRIPS
                and health_fraction(unit) < c.AI_REPAIR_HEALTH_FRACTION
                and _may_leave_the_line(map_screen, ai_name, unit, prov, ctx)):
            path = route(unit, curr_id, march_targets)
            if path:
                unit["repair_trip"] = path[-1]
                unit["order"]["path"] = path[:speed]
                trips += 1
                continue

        # --- upgrade, if it has nothing better to do -------------------------
        # Quiet rear tiles as well as quiet borders. Reading this as "on a peace
        # or coastal border" excluded every interior province -- which is
        # exactly where a nation's factories and their garrisons are, so the one
        # unit in the country with nothing to do all game could never upgrade.
        is_quiet = curr_id not in war_borders and curr_id not in active_battles
        is_near_battle = any(n in active_battles for n in prov.get("neighbors", ()))
        # A unit that wanted repairing and could not afford it must not be sent
        # to upgrade instead: process_upgrades carries health across as a
        # *percentage*, so it would spend the turn and still be wounded, only
        # now wounded as a more expensive type.
        #
        # A haven is a factory tile of ours with no enemy on it, which is
        # exactly the pair of conditions the player's orders panel spells out as
        # "Needs Factory" and "In Combat". The AI used to skip that half of the
        # rule entirely and upgrade wherever a unit happened to be idle -- which
        # is how two American divisions re-equipped themselves to Infantry Type
        # 1943 while adrift in the sea off Spain in saves/HOW DO YOU LAUNCH
        # ARTILLERY FROM THE OCEAN.
        is_idle = (not is_naval_combatant and curr_id in havens
                  and is_quiet and not is_near_battle
                  and not wants_repair
                  and target_assignments.get(curr_id, 0) <= 1)

        if is_idle:
            target = queries.get_upgrade_target(u_type, research, unit_library, tech_tree)
            if target:
                unit["order"] = {"type": "UPGRADE", "turns_left": 1,
                                 "target_type": target, "refund": {}}
                continue

        remaining.append((unit, prov))

    units_info[:] = remaining


def _rotate_damaged_units(map_screen, ai_name, active_battles):
    """Pulls shot-up units out of the front rank when a fresh one can take the slot.

    The only thing the lane model asks of a commander that movement cannot
    express. A reserve takes no damage and recovers morale, so a unit down to a
    fraction of its health is worth more waiting than standing -- but only if
    somebody healthier is behind it, since an empty slot is worse than a hurt one
    and an uncovered lane dissolves entirely.

    Without this the AI would field its casualties until they died while a human
    rotated theirs, which is a real edge and an invisible one.
    """
    for prov_id in active_battles:
        province = map_screen.id_to_province.get(prov_id)
        if not province:
            continue

        mine = [u for u in province.get("units", ()) if u.get("owner") == ai_name]
        if len(mine) < 2:
            continue

        # Last turn's stances go before the measurement, not after it. Read the
        # other way round this ratcheted: build_battle saw the units already
        # held back, slots_held answered with the allowance that left, spare was
        # recomputed from that smaller number, and the reserve could only ever
        # grow. A nation pushed down once never climbed back -- three of the
        # four short fronts in saves/province 907 are stuck there.
        for unit in mine:
            unit.pop("combat_stance", None)

        battle = combat_rules.build_battle([province.get("units", ())], map_screen.nation_data)
        slots = combat_rules.slots_held(battle, ai_name)
        if not slots:
            continue

        def health_fraction(unit):
            return unit.get("health", 0) / max(1.0, unit.get("max_health", 1))

        # Anything past the slots is standing in reserve regardless, so that is
        # exactly how many units can be held back without leaving one empty.
        # The worst-hurt go first.
        spare = max(0, len(mine) - slots)
        wounded = sorted((u for u in mine if health_fraction(u) < c.AI_ROTATE_HEALTH_FRACTION),
                         key=health_fraction)

        for unit in wounded[:spare]:
            unit["combat_stance"] = "RESERVE"


def _cancel_opposing_transitions(ai_nations, nation_units, contested=None):
    """Anti-swap cleanup: if a unit is ordered A->B and another (identical
    type and health) is ordered B->A, cancel both -- otherwise they'd cross
    paths and swap tiles instead of actually contesting either one.

    A tile with a fight on it is exempt in both directions. Two units passing
    each other between quiet tiles have achieved nothing and may as well stay
    put; a garrison pulling out of a battle while a reserve marches in is the
    relief working exactly as intended, and cancelling it left the wounded unit
    standing in the fight AND the fresh one standing behind it -- the same pair,
    every turn, forever.
    """
    contested = contested or set()
    for ai_name in ai_nations:
        units_info = nation_units[ai_name]

        # Track where every unit is trying to go for this specific nation
        transitions = {}
        for unit, prov in units_info:
            path = unit.get("order", {}).get("path", [])
            if path:
                src_id = prov["id"]
                dest_id = path[0]
                if src_id in contested or dest_id in contested:
                    continue
                transitions.setdefault((src_id, dest_id), []).append(unit)

        # Check for opposing traffic
        processed = set()
        for (src, dest), fwd_units in transitions.items():
            if (src, dest) in processed: continue

            bwd_units = transitions.get((dest, src), [])
            if bwd_units:
                # Match up identical unit types AND health
                fwd_types = {}
                for u in fwd_units:
                    # Using int() on health prevents floating point mismatch errors
                    key = (u.get("type", ""), int(u.get("health", 0)))
                    fwd_types.setdefault(key, []).append(u)

                bwd_types = {}
                for u in bwd_units:
                    key = (u.get("type", ""), int(u.get("health", 0)))
                    bwd_types.setdefault(key, []).append(u)

                # Cancel pairs of identical units
                for u_key, f_list in fwd_types.items():
                    b_list = bwd_types.get(u_key, [])
                    cancel_count = min(len(f_list), len(b_list))

                    for i in range(cancel_count):
                        f_list[i]["order"]["path"] = []
                        b_list[i]["order"]["path"] = []

            processed.add((src, dest))
            processed.add((dest, src))


def _generate_unit_orders(map_screen):
    ai_nations = queries.get_active_ai_nations(map_screen)

    # --- NEW: Pre-calculate allowed pathing IDs to include water for convoys ---
    # Doubles as the water lookup the pathfinder uses per tile.
    allowed_prov_ids_cache, water_ids, neighbor_ids = _build_shared_pathing_caches(map_screen)

    nation_units, nation_provs = _reset_orders_and_collect_units(map_screen, ai_nations)

    # Every tile somebody is fighting over this turn, pooled across nations so
    # the anti-swap pass at the end can leave relief traffic alone.
    contested = set()

    for ai_name in ai_nations:
        units_info = nation_units[ai_name]
        if not units_info:
            continue

        my_provs = nation_provs[ai_name]

        # Combine land and water IDs so BFS can route overseas
        # Include ALL legally passable tiles so the AI isn't blind!
        allowed_prov_ids = set(allowed_prov_ids_cache)
        for p in map_screen.map_data.values():
            if queries.can_land_units_enter(ai_name, p, map_screen.nation_data):
                allowed_prov_ids.add(p["id"])

        enemies = _gather_enemies(map_screen, ai_name)

        # --- NEW: IDENTIFY UNSAFE WATERS FOR NAVAL SURVIVAL ---
        unsafe_waters = _compute_unsafe_waters(map_screen, ai_name)

        # --- Identify Friendly Nations for Expedition Logic ---
        friendly_nations = queries.get_all_friendly_nations(ai_name, map_screen.nation_data)

        borders = _discover_borders_and_targets(map_screen, ai_name, my_provs, enemies, friendly_nations)

        at_war = len(enemies) > 0 and (len(borders["enemy_targets"]) > 0 or len(borders["all_enemy_coasts"]) > 0 or len(borders["expedition_targets"]) > 0)

        # --- FIND ACTIVE BATTLES, RETREATS & CONVOY STATUS ---
        battles = _track_battles_and_convoys(map_screen, ai_name, units_info, friendly_nations,
                                             unsafe_waters, borders["all_enemy_coasts"], borders["enemy_coastal_waters"])

        # What each destination's fight can actually seat for us, asked of the
        # combat rules rather than restated here. A tile splitting three ways
        # gives us fewer slots than one where we face a single enemy.
        capacity = {
            t_id: combat_rules.nation_front_capacity(
                ai_name, map_screen.id_to_province[t_id], map_screen.nation_data)
            for t_id in battles["active_battles"]
            if t_id in map_screen.id_to_province
        }

        assignments = _build_target_assignments(units_info, borders, battles, at_war, capacity)

        ctx = {
            "unsafe_waters": unsafe_waters,
            "friendly_nations": friendly_nations,
            "at_war": at_war,
            **borders,
            **battles,
            **assignments,
        }
        ctx["repair_havens"] = _repair_havens(map_screen, ai_name, my_provs, ctx)

        _assign_maintenance_orders(map_screen, ai_name, units_info, ctx,
                                   allowed_prov_ids, water_ids, neighbor_ids)

        # If no targets at all (e.g. an island with no neighbours), there is
        # nothing to march toward. Maintenance runs before this rather than
        # after it: a garrison sitting on its own factory with no front to walk
        # to is the unit with the most to gain from a repair or an upgrade, and
        # skipping the nation here is what stopped it ever getting one.
        if not assignments["target_destinations"]:
            continue

        _assign_unit_orders(map_screen, ai_name, units_info, ctx, allowed_prov_ids, water_ids, neighbor_ids)
        _rotate_damaged_units(map_screen, ai_name, battles["active_battles"])

        contested |= set(battles["active_battles"])
        contested |= set(battles["lost_battles"])

    # --- Anti-Swap Cleanup ---
    _cancel_opposing_transitions(ai_nations, nation_units, contested)
