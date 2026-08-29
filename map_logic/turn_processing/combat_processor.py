import data.constants as c
from data import queries
from map_logic.turn_processing import combat_rules, edit_province_ownership
import random # Imported for the random tiebreaker
from collections import namedtuple

#: What one head-on clash left behind. `survivors1`/`survivors2` are everyone
#: still alive on each side, which is what tells a caller who died; `fought` is
#: the id()s of the units that were actually in the battle, which is what tells
#: it who has to stop here. The two differ whenever somebody crossed the same
#: edge without a war of their own.
MeetingResult = namedtuple("MeetingResult", "survivors1 survivors2 fought")

#: Saved directly on a unit rather than in a transient map-level table.  Units
#: stay in their departure province's ``units`` list for upkeep, save/history,
#: and national accounting, while all movement/combat/rendering code treats
#: this tag as their real location being the midpoint of the two provinces.
EDGE_BATTLE_KEY = "_edge_battle"

#: Which side of the suicide-charge probe in process_pinning is the charge. The
#: garrison is handed in first, so it is side 0 and the charge is side 1.
CHARGE_SIDE = 1


def apply_group_damage(total_atk, target_units, defense_bonus_fn=None):
    """Distributes attack after health-scaled unit defense and flat bonuses.

    Fortification defense is a property of the tile, not the individual unit,
    so it must not be reduced when a unit is wounded.  The callback remains
    generic because it is also useful for other tile-wide defensive effects.
    """
    if not target_units: return
    # Simple distribution: Divide total attack by number of units
    damage_per_unit = total_atk / len(target_units)
    
    for u in target_units:
        defense_bonus = defense_bonus_fn(u) if defense_bonus_fn else 0
        defense = (u.get("defense", 0) * combat_rules.health_defense_multiplier(u)
                   + defense_bonus)
        actual_dmg = max(0, damage_per_unit - defense)
        
        if actual_dmg > 0:
            max_hp = u.get("max_health", 1)
            percent_lost = (actual_dmg / max_hp) * 100.0
            u["morale"] = max(0.0, float(u.get("morale", c.DEFAULT_UNIT_MORALE)) - percent_lost)
            
        u["health"] -= actual_dmg


def is_edge_battle_unit(unit):
    """Compatibility wrapper for callers that already depend on this module."""
    return queries.is_unit_in_edge_battle(unit)


def _edge_pair_key(first_id, second_id):
    """A stable pair key even for maps that mix numeric and string ids."""
    return tuple(sorted((first_id, second_id), key=lambda value: (type(value).__name__, str(value))))


def edge_battles(map_screen):
    """Live virtual battles, grouped from their unit-level saved metadata.

    Each item contains the endpoint pair and the units marching in both
    directions.  Keeping this derived means a normal save already contains all
    required state and a load never has to reconstruct object references.
    """
    grouped = {}
    for province in map_screen.map_data.values():
        for unit in province.get("units", []):
            tag = unit.get(EDGE_BATTLE_KEY)
            if not isinstance(tag, dict):
                continue
            origin_id = tag.get("origin_id")
            destination_id = tag.get("destination_id")
            if (origin_id != province.get("id")
                    or destination_id not in map_screen.id_to_province
                    or destination_id == origin_id):
                continue
            pair = _edge_pair_key(origin_id, destination_id)
            record = grouped.setdefault(pair, {
                "pair": pair,
                "side1": [],
                "side2": [],
            })
            saved_side = tag.get("battle_side")
            if saved_side in (1, 2):
                record[f"side{saved_side}"].append(unit)
            elif origin_id == pair[0] and destination_id == pair[1]:
                record["side1"].append(unit)
            elif origin_id == pair[1] and destination_id == pair[0]:
                record["side2"].append(unit)
    return list(grouped.values())


def find_edge_battle(map_screen, pair):
    """Returns the live record for ``pair`` or ``None`` when it has settled."""
    wanted = _edge_pair_key(*pair)
    return next((record for record in edge_battles(map_screen)
                 if record["pair"] == wanted), None)


def edge_battle_opponents(record, origin_id, destination_id):
    """Return the fighters across the edge from this movement direction."""
    pair = record.get("pair", ())
    if len(pair) != 2:
        return ()
    if (origin_id, destination_id) == (pair[0], pair[1]):
        return record.get("side2", ())
    if (origin_id, destination_id) == (pair[1], pair[0]):
        return record.get("side1", ())
    return ()


def _nation_is_hostile_to_any(nation, units, nation_data):
    """Whether ``nation`` is at war with at least one listed fighter."""
    return any(
        queries.are_at_war(nation, enemy.get("owner"), nation_data)
        or queries.are_at_war(enemy.get("owner"), nation, nation_data)
        for enemy in units)


def _nation_belongs_with_side(nation, units, nation_data):
    """Whether ``nation`` is already part of a side's friendly coalition."""
    for member in units:
        owner = member.get("owner")
        if owner == nation:
            return True
        nation_friends = queries.friendly_nations_view(nation, nation_data)
        owner_friends = queries.friendly_nations_view(owner, nation_data)
        if owner in nation_friends and nation in owner_friends:
            return True
    return False


def edge_battle_reinforcement_side(nation, origin_id, destination_id,
                                   record, nation_data):
    """Return the combat side a midpoint reinforcement should join.

    The endpoint a unit approaches from is not necessarily the side it fights
    for. A defender can send reserves through territory that is also being
    crossed by the attacker, as in a unit at the near endpoint reinforcing its
    country's fighters that started at the far endpoint. The old directional
    check mistook that reserve for a possible enemy of its own side.

    Side numbers are one-based to match the persisted ``battle_side`` value;
    old tags without that value still use their origin direction when grouped.
    """
    pair = record.get("pair", ())
    if (len(pair) != 2
            or (origin_id, destination_id) not in
            ((pair[0], pair[1]), (pair[1], pair[0]))):
        return None

    sides = (record.get("side1", ()), record.get("side2", ()))
    # A friendly nation standing beside one side is still a bystander unless
    # it is at war with the other side. This preserves military-access traffic
    # as a barrier casualty rather than quietly enlisting it in the battle.
    possible_sides = [
        side_index + 1
        for side_index, opposing_side in enumerate((sides[1], sides[0]))
        if _nation_is_hostile_to_any(nation, opposing_side, nation_data)
    ]
    if not possible_sides:
        return None

    coalition_matches = [
        side_index + 1
        for side_index, side in enumerate(sides)
        if _nation_belongs_with_side(nation, side, nation_data)
        and side_index + 1 in possible_sides
    ]
    if coalition_matches:
        return coalition_matches[0]

    # A unit joins the side whose fighters are on the same side of the war as
    # it, which means it must be hostile to the opposing side.
    if len(possible_sides) == 1:
        return possible_sides[0]
    if len(possible_sides) > 1:
        # A third party hostile to both sides has no unique coalition. Keep
        # the historical endpoint choice for that genuinely ambiguous case.
        return 1 if origin_id == pair[0] else 2
    return None


def can_nation_reinforce_edge_battle(nation, origin_id, destination_id,
                                     record, nation_data):
    """Whether a nation can reinforce a midpoint from either endpoint."""
    return edge_battle_reinforcement_side(
        nation, origin_id, destination_id, record, nation_data) is not None


def can_join_edge_battle(unit, origin_id, destination_id, record, nation_data):
    """Whether ``unit`` is allowed to reinforce from either endpoint."""
    return can_nation_reinforce_edge_battle(
        unit.get("owner"), origin_id, destination_id, record, nation_data)


def join_edge_battle(unit, origin_id, destination_id, record, nation_data):
    """Commit a mover to an active midpoint battle, if it can reinforce it.

    An edge battle is a hard barrier: a unit cannot pass through it.  A unit
    that is at war with the fighters on the far side may instead join the
    battle from its endpoint and will take part in the next exchange.
    """
    battle_side = edge_battle_reinforcement_side(
        unit.get("owner"), origin_id, destination_id, record, nation_data)
    if battle_side is None:
        return False

    tag = {
        "origin_id": origin_id,
        "destination_id": destination_id,
    }
    pair = record.get("pair", ())
    inferred_side = (1 if origin_id == pair[0] else 2
                     if origin_id == pair[1] else None)
    if battle_side != inferred_side:
        # Keep old, compact tags readable while recording the only case that
        # cannot be reconstructed from origin_id: reinforcing the friendly
        # side from the opposite endpoint.
        tag["battle_side"] = battle_side
    unit[EDGE_BATTLE_KEY] = tag
    unit.get("order", {}).pop("edge_battle_target", None)
    return True


def edge_battle_midpoint(map_screen, record):
    """World-space midpoint for a virtual battle, respecting wrapped maps."""
    first = map_screen.id_to_province[record["pair"][0]]["center"]
    second = map_screen.id_to_province[record["pair"][1]]["center"]
    first_x, first_y = first
    second_x, second_y = second
    if getattr(map_screen, "loop_map", False):
        half = map_screen.map_w / 2
        delta = ((second_x - first_x + half) % map_screen.map_w) - half
        return ((first_x + delta / 2) % map_screen.map_w, (first_y + second_y) / 2)
    return ((first_x + second_x) / 2, (first_y + second_y) / 2)


def edge_battle_at_screen_pos(map_screen, screen_pos):
    """The visible midpoint marker hit by a map click, if any.

    This lives beside the midpoint calculation so drawing and input cannot drift
    apart when camera tilt or wrapped-map coordinates are involved.
    """
    sx, sy = screen_pos
    # Keep the target comfortably clickable without turning the midpoint into
    # another province-sized map object.  Rendering uses the same base size.
    radius = max(10, int(10 * map_screen.camera.zoom))
    offsets = (0, -map_screen.map_w, map_screen.map_w) if map_screen.loop_map else (0,)
    for record in edge_battles(map_screen):
        world = edge_battle_midpoint(map_screen, record)
        for offset in offsets:
            marker_x = (world[0] + offset - map_screen.camera.pos.x) * map_screen.camera.zoom
            marker_y = ((world[1] - map_screen.camera.pos.y) * map_screen.camera.zoom
                        * map_screen.camera.tilt_factor + map_screen.top_ui_height)
            if (marker_x - sx) ** 2 + (marker_y - sy) ** 2 <= radius ** 2:
                return record
    return None


def _tag_edge_units(units, origin_id, destination_id, fought):
    for unit in units:
        if id(unit) in fought and unit.get("health", 0) > 0:
            unit[EDGE_BATTLE_KEY] = {
                "origin_id": origin_id,
                "destination_id": destination_id,
            }


def _clear_edge_tag(unit):
    unit.pop(EDGE_BATTLE_KEY, None)


def _prune_dead(provinces):
    for province in provinces:
        province["units"] = [u for u in province.get("units", [])
                              if u.get("health", 0) > 0]


def _resolve_meeting_exchange(prov1, prov2, units1, units2, nation_data):
    """One simultaneous, fort-less exchange between two directions of travel.

    The old direct-swap resolver and persistent midpoint battles both use this
    exact primitive.  Locking/freezing and where survivors stand are policy
    decisions made by their callers, not part of how a volley is calculated.
    """
    battle = combat_rules.build_battle([units1, units2], nation_data)
    fought = {id(u)
              for lane in battle.lanes
              for side in (lane.a, lane.b)
              for u in side.front + side.reserve}

    # A convoy's origin side decides whether it is on land.  This keeps the
    # established coast-swap rule: a sea convoy stays loaded even when the
    # opposing army marched from shore.
    for side_units, side_prov in ((units1, prov1), (units2, prov2)):
        if queries.is_water_province(side_prov):
            continue
        for unit in side_units:
            if id(unit) in fought and unit.get("type", "").startswith("Convoy"):
                queries.revert_transport(unit)

    for targets, total_atk in combat_rules.exchange(battle, nation_data):
        apply_group_damage(total_atk, targets)

    for lane in battle.lanes:
        for unit in lane.a.front + lane.b.front:
            unit["_in_combat_this_turn"] = True

    return MeetingResult(
        [u for u in units1 if u.get("health", 0) > 0],
        [u for u in units2 if u.get("health", 0) > 0],
        fought,
    )


def _release_edge_battle(record):
    """Return a non-hostile midpoint's survivors to their existing orders."""
    for unit in record["side1"] + record["side2"]:
        _clear_edge_tag(unit)
        unit.get("order", {}).pop("edge_battle_target", None)


def _advance_edge_winners(map_screen, record):
    """Move each decisive midpoint winner onto its own target and stop it.

    Crossing the midpoint has already consumed the movement that created the
    battle. A victory therefore captures exactly the tile that each unit was
    originally entering; it never silently continues any queued path beyond
    that tile. Reinforcements can approach from the opposite endpoint to the
    side they support, so the unit tag -- rather than the battle side -- is
    authoritative for this destination. The helper also works during a later
    movement sub-step, where units are temporarily outside their province
    lists but carry ``_current_province_id`` instead.
    """
    for side_index, winners in enumerate(
            (record["side1"], record["side2"]), start=1):
        for unit in winners:
            tag = unit.get(EDGE_BATTLE_KEY, {})
            origin_id = tag.get("origin_id", record["pair"][side_index - 1])
            destination_id = tag.get(
                "destination_id", record["pair"][1 if side_index == 1 else 0])
            current_id = unit.get("_current_province_id", origin_id)
            origin = map_screen.id_to_province.get(current_id)
            destination = map_screen.id_to_province.get(destination_id)
            if origin is None or destination is None:
                continue

            origin["units"] = [existing for existing in origin.get("units", [])
                                if existing is not unit]
            _clear_edge_tag(unit)
            order = unit.get("order")
            if not isinstance(order, dict):
                unit["order"] = {"type": "MOVE", "path": []}
            else:
                order["type"] = "MOVE"
                order["path"] = []
            order.pop("edge_battle_target", None)
            unit.pop("lane_target", None)
            unit.pop("combat_stance", None)

            # Mid-turn swaps keep their current position on the mover, rather
            # than in a province list.  Update that temporary position too so
            # the normal movement sync places the winner on this endpoint.
            if "_current_province_id" in unit:
                unit["_previous_province_id"] = current_id
                unit["_current_province_id"] = destination_id
            if not any(existing is unit for existing in destination["units"]):
                destination["units"].append(unit)


def _settle_edge_battle(map_screen, record):
    """Settle an edge with no hostile lane, advancing only a real winner."""
    current = find_edge_battle(map_screen, record["pair"])
    if current is None:
        # During a multi-speed swap movers are deliberately outside province
        # lists until the sub-step ends.  Their saved tags still make this
        # supplied record authoritative; a genuinely dissolved battle has no
        # tagged units left and needs no further work.
        current = {
            "pair": record["pair"],
            "side1": [unit for unit in record["side1"]
                      if is_edge_battle_unit(unit) and unit.get("health", 0) > 0],
            "side2": [unit for unit in record["side2"]
                      if is_edge_battle_unit(unit) and unit.get("health", 0) > 0],
        }
        if not current["side1"] and not current["side2"]:
            return True
    battle = combat_rules.build_battle(
        [current["side1"], current["side2"]], map_screen.nation_data)
    if battle.lanes:
        return False
    if current["side1"] and not current["side2"]:
        _advance_edge_winners(map_screen, current)
    elif current["side2"] and not current["side1"]:
        _advance_edge_winners(map_screen, current)
    else:
        # This was diplomacy, not a victory.  The original legal orders can
        # continue from their departure tiles as before.
        _release_edge_battle(current)
    return True


def repair_edge_battles(map_screen):
    """Settle serialized midpoint records that no longer have two sides.

    A midpoint battle is only a live engagement while both endpoints have a
    surviving fighter. Older saves, and saves made during the narrow window
    after a decisive exchange, can contain just one tagged side. Leaving that
    tag in place creates a visible battle with no opponent and makes every
    attempted reinforcement fail the combatant check. Treat it like the
    normal end-of-battle path so the remaining side advances onto the endpoint
    it was entering.

    Returns the number of records repaired. The pass is deliberately separate
    from :func:`edge_battles` because that function is a read-only view used by
    rendering and AI planning.
    """
    repaired = 0
    for record in list(edge_battles(map_screen)):
        if record["side1"] and record["side2"]:
            continue
        if _settle_edge_battle(map_screen, record):
            repaired += 1
    return repaired


def start_edge_battle(prov1, prov2, units1, units2, nation_data, map_screen=None):
    """Create and immediately fight a virtual battle between two provinces.

    Only units in an actual lane are tagged.  Fellow travellers who are neutral
    to the enemy do not become fighters.  If the opening volley clears a
    direction, its opponent advances once onto the enemy endpoint and stops.
    """
    result = _resolve_meeting_exchange(prov1, prov2, units1, units2, nation_data)
    _prune_dead((prov1, prov2))
    _tag_edge_units(result.survivors1, prov1["id"], prov2["id"], result.fought)
    _tag_edge_units(result.survivors2, prov2["id"], prov1["id"], result.fought)
    if map_screen is not None:
        record = find_edge_battle(map_screen, (prov1["id"], prov2["id"]))
        if record is not None:
            _settle_edge_battle(map_screen, record)
        else:
            # Mid-turn swaps happen while movers are temporarily outside their
            # province lists.  The derived record is therefore unavailable
            # until movement syncs them back at the end of this sub-step.  A
            # decisive exchange must still place its winner on the opposing
            # endpoint immediately, before movement syncs its temporary
            # position back into province lists.
            pair = _edge_pair_key(prov1["id"], prov2["id"])
            temporary = {"pair": pair, "side1": [], "side2": []}
            for unit in result.survivors1 + result.survivors2:
                tag = unit.get(EDGE_BATTLE_KEY, {})
                if not is_edge_battle_unit(unit):
                    continue
                if tag.get("origin_id") == pair[0]:
                    temporary["side1"].append(unit)
                elif tag.get("origin_id") == pair[1]:
                    temporary["side2"].append(unit)
            _settle_edge_battle(map_screen, temporary)
    return result


def request_edge_retreat(unit, path=None):
    """Queue a midpoint withdrawal, whose first movement step is its origin."""
    tag = unit.get(EDGE_BATTLE_KEY)
    if not isinstance(tag, dict):
        return False
    origin_id = tag.get("origin_id")
    if path is None:
        path = [origin_id]
    if (not isinstance(path, list) or not path
            or path[0] != origin_id):
        return False
    tag["retreat"] = True
    tag["retreat_path"] = list(path)
    return True


def process_edge_battles(map_screen):
    """Apply withdrawals, then fight every pre-existing midpoint battle once.

    Retreats happen before that turn's exchange, matching ordinary province
    combat where a valid withdrawal moves away before the end-of-turn melee.
    A withdrawal replaces the unit's old advance queue with the player-chosen
    retreat path.  Its origin is deliberately the first path step, so leaving
    the midpoint costs movement before a fast unit can continue farther away.
    """
    for record in edge_battles(map_screen):
        for unit in record["side1"] + record["side2"]:
            tag = unit.get(EDGE_BATTLE_KEY, {})
            if not tag.get("retreat"):
                continue
            retreat_path = tag.get("retreat_path")
            if (not isinstance(retreat_path, list) or not retreat_path
                    or retreat_path[0] != tag.get("origin_id")):
                retreat_path = [tag.get("origin_id")]
            _clear_edge_tag(unit)
            order = unit.get("order")
            if not isinstance(order, dict):
                unit["order"] = {"type": "MOVE", "path": list(retreat_path)}
            else:
                order["type"] = "MOVE"
                order["path"] = list(retreat_path)
            unit.pop("lane_target", None)
            unit.pop("combat_stance", None)

        # A withdrawal or a diplomacy change can end the engagement before a
        # volley is due.  Re-read it from unit tags rather than trusting the
        # record captured before we changed those tags.
        current = find_edge_battle(map_screen, record["pair"])
        if current is None or _settle_edge_battle(map_screen, current):
            continue

        first = map_screen.id_to_province[current["pair"][0]]
        second = map_screen.id_to_province[current["pair"][1]]
        _resolve_meeting_exchange(first, second, current["side1"], current["side2"],
                                  map_screen.nation_data)
        _prune_dead((first, second))
        _settle_edge_battle(map_screen, current)

def process_bombardments(map_screen):
    """Resolves artillery fire on nearby tiles.

    Runs before movement, so a unit that walks away this turn still eats the
    shells first. Bombarding units hold position (they carry a BOMBARD order
    instead of a MOVE one) and take no return fire.
    """
    # Collect every barrage before resolving any of them so the damage is
    # simultaneous - two guns shelling each other's tiles both get to fire.
    barrages = {}
    firing_units = []

    for province in map_screen.map_data.values():
        for unit in province.get("units", []):
            if is_edge_battle_unit(unit):
                continue
            order = unit.get("order")
            if not isinstance(order, dict) or order.get("type") != "BOMBARD":
                continue

            target_id = order.get("target_id")
            u_type = unit.get("type", "")
            bomb_range = queries.get_bombardment_range(u_type)

            # A field gun has nothing to stand on out at sea. Asked of the unit
            # rather than the tile because shore bombardment is a real order --
            # Battleships, Dreadnoughts and Carriers are all in
            # c.BOMBARDMENT_UNITS and fire from the water by design.
            afloat = (queries.is_water_province(province)
                      and not (unit.get("naval_unit") or queries.is_naval_unit(u_type)))

            # Drop the order if the gun can no longer make the shot
            if (bomb_range <= 0 or afloat
                    or target_id not in queries.get_bombardment_targets(province, map_screen.id_to_province, bomb_range)):
                unit["order"] = {"type": "MOVE", "path": []}
                continue

            barrages.setdefault(target_id, {}).setdefault(unit["owner"], []).append(unit)
            firing_units.append(unit)

    if not firing_units:
        return

    for target_id, guns_by_owner in barrages.items():
        target_prov = map_screen.id_to_province.get(target_id)
        if not target_prov: continue

        for owner, guns in guns_by_owner.items():
            # A land artillery order against an enemy fort damages the fort
            # itself, even when the tile currently has no units to hit.  Each
            # artillery unit has its own BOMBARD order, so each one can remove
            # one level; damage stops naturally at level 0.
            target_owner = target_prov.get("owner")
            fort_hits = 0
            if (target_owner and queries.are_at_war(owner, target_owner,
                                                     map_screen.nation_data)):
                fort_hits = sum(
                    not (gun.get("naval_unit")
                         or queries.is_naval_unit(gun.get("type", "")))
                    for gun in guns
                )

            targets = [u for u in queries.units_on_province(target_prov)
                       if queries.are_at_war(owner, u.get("owner"), map_screen.nation_data)]
            if not targets:
                # A valid bombardment can hit an empty fort tile, so apply its
                # fort damage even when there are no enemy units to receive
                # the volley.
                for _ in range(fort_hits):
                    queries.damage_fort(
                        target_prov, map_screen.nation_data, map_screen.map_data)
                continue

            # Every gun that aimed here contributes; unlike a stack fight this
            # isn't capped by combat width, since each shot was ordered by hand.
            # "bombard_attack" is a separate stat from melee "attack" (falls
            # back to attack for any family that doesn't define it).
            total_atk = sum(u.get("bombard_attack", u.get("attack", c.DEFAULT_UNIT_ATK))
                            * combat_rules.effective_damage_multiplier(u, map_screen.nation_data)
                            for u in guns)
            apply_group_damage(
                total_atk,
                targets,
                lambda unit, province=target_prov: queries.get_fort_defense_bonus(
                    province, unit, map_screen.nation_data, combat_active=True),
            )

            # Resolve the fort damage after this volley has been calculated so
            # the fort's current level protects against the shells that hit it.
            for _ in range(fort_hits):
                queries.damage_fort(
                    target_prov, map_screen.nation_data, map_screen.map_data)

            for u in targets:
                u["_in_combat_this_turn"] = True

    # Clear the casualties out before movement and combat run
    for province in map_screen.map_data.values():
        if province.get("units"):
            province["units"] = [u for u in province["units"] if u.get("health", 0) > 0]

    # Guns stay put; the order has to be reissued next turn
    for unit in firing_units:
        unit["order"] = {"type": "MOVE", "path": []}

def process_pinning(map_screen):
    """Rule: Units being attacked from a tile must defend the tile they're on, unless moving to friendly territory."""
    incoming_attacks = {}
    for province in map_screen.map_data.values():
        for unit in province.get("units", []):
            if is_edge_battle_unit(unit):
                continue
            order = unit.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                dest_id = order["path"][0]
                dest_prov = map_screen.id_to_province.get(dest_id)
                if dest_prov and queries.is_hostile_territory(unit["owner"], dest_prov.get("owner", "Unclaimed"), map_screen.nation_data):
                    # Track the origin province ID (province["id"]) along with the unit
                    incoming_attacks.setdefault(dest_id, []).append((unit, province["id"]))

    # --- NEW: RESOLVE SUICIDE CHARGES ---
    # If incoming attackers are so weak they'd die instantly, resolve the combat NOW
    # so they die, deal their damage, and don't pin the defenders.
    for dest_id, attackers_info in list(incoming_attacks.items()):
        dest_prov = map_screen.id_to_province.get(dest_id)
        if not dest_prov: continue
        
        defenders = queries.units_on_province(dest_prov)
        if not defenders: continue
        
        tile_owner = dest_prov.get("owner", "Unclaimed")
        if tile_owner in c.UNPLAYABLE_NATIONS: continue
        
        friendly_defenders = [u for u in defenders if not queries.are_at_war(tile_owner, u.get("owner"), map_screen.nation_data)]
        if not friendly_defenders: continue

        hostile_attackers = [
            info for info in attackers_info
            if queries.are_at_war(tile_owner, info[0].get("owner"), map_screen.nation_data)
        ]

        if not hostile_attackers: continue

        # "Not at war with the tile's owner" is not the same as "in this fight".
        # A third country sitting here on military access is at war with neither
        # side, and used to both add its attack to the defence and eat the
        # charge's damage. Keep only the defenders these attackers are actually
        # fighting.
        friendly_defenders = [
            u for u in friendly_defenders
            if any(queries.are_at_war(u.get("owner"), a.get("owner"), map_screen.nation_data)
                   for a, _ in hostile_attackers)
        ]
        if not friendly_defenders: continue

        # A charge into a held tile is a head-on clash, so it is resolved by the
        # same rule as one: the garrison and the charge are the two sides, and
        # every lane crosses between them. Routing it through build_battle is
        # what stops the probe and the fight it is predicting from drifting
        # apart the moment either is tuned.
        attacker_units_only = [a_unit for a_unit, _ in hostile_attackers]
        probe = combat_rules.build_battle(
            [friendly_defenders, attacker_units_only], map_screen.nation_data)

        incoming_on_charge = {}
        shots_at_defenders = []
        for lane in probe.lanes:
            for firing, receiving in ((lane.a, lane.b), (lane.b, lane.a)):
                # Per firing nation, not per side: exactly what exchange() does,
                # so the probe and the fight it predicts cannot disagree about
                # who a coalition member is actually shooting at.
                for member in firing.members:
                    if not member.targets:
                        continue
                    shot = combat_rules.volley(member.front, probe.shares,
                                               map_screen.nation_data)
                    if receiving.side_index == CHARGE_SIDE:
                        share = shot / len(member.targets)
                        for target in member.targets:
                            incoming_on_charge[id(target)] = incoming_on_charge.get(id(target), 0.0) + share
                    else:
                        shots_at_defenders.append((member.targets, shot))

        # A charge deeper than the lane can seat always has survivors, because
        # the surplus sits in reserve where nothing can reach it. Fifty militia
        # genuinely cannot all be shot down in one exchange, so the early
        # resolution below simply stops applying to charges that big.
        attackers_survive = any(
            max(0, incoming_on_charge.get(id(a_unit), 0.0)
                - a_unit.get("defense", 0) * combat_rules.health_defense_multiplier(a_unit))
            < a_unit.get("health", 1)
            for a_unit in attacker_units_only)

        if not attackers_survive:
            # 1. Attackers are obliterated. Apply their pitiful damage to the defenders.
            for targets, total_atk in shots_at_defenders:
                apply_group_damage(
                    total_atk,
                    targets,
                    lambda unit, province=dest_prov: queries.get_fort_defense_bonus(
                        province, unit, map_screen.nation_data, combat_active=True),
                )

            for lane in probe.lanes:
                for u in lane.a.front + lane.b.front:
                    u["_in_combat_this_turn"] = True

            # 2. Kill the attackers and remove them from incoming_attacks
            for a_unit, a_origin_id in hostile_attackers:
                a_unit["health"] = 0
                incoming_attacks[dest_id] = [info for info in incoming_attacks[dest_id] if info[0] != a_unit]
                
                # Cleanup dead units from their origin province immediately
                a_prov = map_screen.id_to_province.get(a_origin_id)
                if a_prov:
                    a_prov["units"] = [u for u in a_prov["units"] if u.get("health", 0) > 0]
            
            # 3. Cleanup dead defenders in the destination province (just in case they died to scratch damage)
            dest_prov["units"] = [u for u in dest_prov["units"] if u.get("health", 0) > 0]

    # --- STANDARD PINNING LOGIC ---
    for province in map_screen.map_data.values():
        for unit in province.get("units", []):
            if is_edge_battle_unit(unit):
                continue
            order = unit.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                dest_id = order["path"][0]
                dest_prov = map_screen.id_to_province.get(dest_id)
                
                # If moving to hostile territory, check if we are pinned by an incoming attack
                if dest_prov and queries.is_hostile_territory(unit["owner"], dest_prov.get("owner", "Unclaimed"), map_screen.nation_data):
                    attackers = incoming_attacks.get(province["id"], [])
                    
                    # ONLY pin if the attacker is hostile AND NOT coming from the tile we are moving to.
                    hostile_attackers = [
                        a for a, origin_id in attackers 
                        if queries.are_at_war(unit["owner"], a["owner"], map_screen.nation_data) and origin_id != dest_id
                    ]
                    
                    if hostile_attackers:
                        # Pinned! Cannot attack outwards. Must defend.
                        order["path"] = []

def resolve_meeting_engagement(prov1, prov2, units1, units2, nation_data):
    """Legacy one-volley swap API, kept for callers and older saves/tests.

    Persistent midpoint battles call :func:`start_edge_battle`; this wrapper
    deliberately preserves the former one-turn lock behaviour while sharing
    the same lane, convoy, damage, and morale exchange primitive.
    """
    result = _resolve_meeting_exchange(prov1, prov2, units1, units2, nation_data)
    fighters1 = [u for u in result.survivors1 if id(u) in result.fought]
    fighters2 = [u for u in result.survivors2 if id(u) in result.fought]

    if fighters2:
        for u in fighters1:
            u["_combat_locked"] = True
    if fighters1:
        for u in fighters2:
            u["_combat_locked"] = True

    _prune_dead((prov1, prov2))
    return result

def process_meeting_engagements(map_screen):
    """Resolve existing midpoint battles, then start any new head-on clashes."""
    process_edge_battles(map_screen)

    # Which tiles swap garrisons is decided by combat_rules, the same rule the
    # prediction bubbles are drawn from.  Newly created edge fights are read
    # fresh per pair so a casualty in one cannot join another edge this turn.
    for pair in combat_rules.find_meeting_pairs(map_screen.map_data, map_screen.nation_data):
        # New movers at an already active edge are reinforcements, not a second
        # independent clash.  Movement will attach them to the existing record
        # after this turn's volley has resolved.
        if find_edge_battle(map_screen, pair) is not None:
            continue
        prov1, prov2, units1, units2 = combat_rules.meeting_sides(map_screen.id_to_province, pair)
        start_edge_battle(prov1, prov2, units1, units2, map_screen.nation_data,
                          map_screen=map_screen)

def process_combat(map_screen):
    """Fights everyone sharing a province, lane by lane.

    The tile splits into duels -- one per pair of hostile powers standing on it
    -- and c.COMBAT_WIDTH front slots are divided among them. Each side of a
    lane fires the attack of its front rank, split across the *opposing front
    rank in that lane* and nothing else. Damage never crosses a lane boundary,
    so an ally fighting its own enemy beside you takes none of your fire and
    none of your enemy's.

    Units past a lane's allowance are in reserve: they deal no damage and take
    none. Depth stopped being a way to thin somebody else's volley -- the
    divisor is the front, not the stack -- and became a queue of replacements
    for the units in front of them. Bombardment is what reaches them.

    A nation on the tile with nobody to fight -- passing through on military
    access, or at war with somebody who is not standing here -- takes no part.
    Not just no damage: its convoys stay loaded, its orders survive, and its
    ships are not scuttled by other people's war.
    """
    for province in map_screen.map_data.values():
        units = queries.units_on_province(province)
        if len(units) < 2:
            continue

        is_land = not queries.is_water_province(province)

        battle = combat_rules.build_battle([units], map_screen.nation_data)
        fighters = set(battle.engaged)

        # Unpack Convoys Caught on Land -- only the ones in the battle.
        if is_land:
            for u in units:
                if u.get("owner") in fighters and u.get("type", "").startswith("Convoy"):
                    queries.revert_transport(u)

        # Every volley is measured before any of it lands, so the fight is
        # simultaneous: a nation wiped out this turn still fires this turn, and
        # nobody's share depends on who happened to be resolved first.
        for targets, total_atk in combat_rules.exchange(battle, map_screen.nation_data):
            apply_group_damage(
                total_atk,
                targets,
                lambda unit, province=province: queries.get_fort_defense_bonus(
                    province, unit, map_screen.nation_data, combat_active=True),
            )

        # Only the front rank is in combat: a reserve rests and recovers morale
        # while the units ahead of it bleed, which is the pressure to rotate.
        for lane in battle.lanes:
            for u in lane.a.front + lane.b.front:
                u["_in_combat_this_turn"] = True

        # Remove dead units (HP <= 0) BEFORE checking if we should wipe paths
        surviving_units = [u for u in units if u.get("health", 0) > 0]
        edge_units = [u for u in province.get("units", []) if is_edge_battle_unit(u)]
        province["units"] = edge_units + surviving_units

        # Wipe queues and destroy misplaced naval units ONLY if combat is still ongoing
        if battle.lanes:
            # Pinned by its OWN enemies, not by anyone else's. The tile-wide test
            # that used to sit here froze a bystander in place because two other
            # countries were shooting at each other around it. Read after the
            # dead are cleared, so a side that wiped its enemy out is free again.
            still_fighting = {
                owner for owner in fighters
                if queries.is_nation_in_combat_here(owner, province, map_screen.nation_data)
            }

            for u in surviving_units:
                if u.get("owner") not in fighters:
                    continue

                if u.get("owner") in still_fighting:
                    if "order" in u and "path" in u["order"]:
                        u["order"]["path"] = []

                # Immediately destroy warships caught in land combat
                if is_land and queries.is_warship(u.get("type", "")):
                    u["health"] = 0

            # Filter dead ships out
            province["units"] = edge_units + [u for u in surviving_units if u.get("health", 0) > 0]

def check_for_post_combat_captures(map_screen):
    """Assigns province ownership to units standing in an undefended enemy province."""
    for province in map_screen.map_data.values():
        if queries.is_water_province(province):
            continue

        units = queries.units_on_province(province)
        if not units:
            continue

        # Midpoint fighters remain serialized in their departure province, but
        # are deliberately omitted by units_on_province because they do not
        # occupy that tile.  Keep them when rebuilding the province's unit
        # list below; otherwise an ordinary capture on the endpoint silently
        # deletes the other half of an unrelated edge battle.
        edge_units = [u for u in province.get("units", [])
                      if is_edge_battle_unit(u)]
            
        current_owner = province.get("owner", "Unclaimed")
        turn_start_owner = province.get("_turn_start_owner", current_owner)
        
        # Get a list of unique owners of units currently in the tile
        unit_owners = list(set(u["owner"] for u in units))
        
        # If the original owner of the tile (from the start of the turn) is STILL HERE,
        # they automatically retain (or regain) ownership, regardless of HP.
        if turn_start_owner in unit_owners:
            if current_owner != turn_start_owner:
                edit_province_ownership.conquer_province(map_screen, province, turn_start_owner)
            continue
            
        # Ensure capturer is legally allowed to take the tile
        # You can't steal land from someone you are at peace with! A tile that
        # changed hands THIS TURN is judged against both the owner it started
        # the turn with and the owner it has now, so neither claim is lost to
        # order-of-execution in movement processing. Reading only the turn-start
        # owner -- which is what this used to do -- threw away the second half:
        # in saves/GERMAN TANK IN YUGOSLAVIA BUT NOT TAKEN, Yugoslavia retook
        # province 818 from Italy during movement, so the German tank that then
        # killed the garrison was judged against Italy, an ally, and could not
        # take a tile it had just cleared of every defender.
        claim_owners = {current_owner, turn_start_owner}
        valid_capturer_units = [
            u for u in units
            if any(o in c.OWNERLESS_OWNERS
                   or queries.are_at_war(u["owner"], o, map_screen.nation_data)
                   for o in claim_owners)
        ]

        if not valid_capturer_units:
            continue # No one here is legally allowed to capture the tile
            
        # Tally HP for all VALID units on the tile to see who claims it
        hp_totals = {}
        for u in valid_capturer_units:
            o = u["owner"]
            hp_totals[o] = hp_totals.get(o, 0) + u.get("health", 0)

        # Find the nation(s) with the highest combined HP
        max_hp = -1
        top_nations = []
        for o, hp in hp_totals.items():
            if hp > max_hp:
                max_hp = hp
                top_nations = [o]
            elif hp == max_hp:
                top_nations.append(o)
            
        capturer = None
        
        # If one clear winner, they take it
        if len(top_nations) == 1:
            capturer = top_nations[0]
        # If there's a tie, run through the tiebreaker cascade
        elif len(top_nations) > 1:
            # Tiebreaker 1: Highest combined attack
            atk_totals = {o: sum(u.get("attack", 0) for u in units if u["owner"] == o) for o in top_nations}
            max_atk = max(atk_totals.values())
            tied_by_atk = [o for o, atk in atk_totals.items() if atk == max_atk]

            if len(tied_by_atk) == 1:
                capturer = tied_by_atk[0]
            else:
                # Tiebreaker 2: Highest speed stat
                spd_max = {o: max((u.get("speed", 0) for u in units if u["owner"] == o), default=0) for o in tied_by_atk}
                max_spd = max(spd_max.values())
                tied_by_spd = [o for o, spd in spd_max.items() if spd == max_spd]

                if len(tied_by_spd) == 1:
                    capturer = tied_by_spd[0]
                else:
                    # Tiebreaker 3: Let fate decide, or bounce
                    if queries.get_scenario_flag("bounce_tiebreaker", c.DEFAULT_BOUNCE_TIEBREAKER, map_screen.scenario_settings):
                        capturer = None
                        
                        # Bounce all valid capturer units back to where they came from
                        for u in valid_capturer_units:
                            if "_previous_province_id" in u:
                                prev_prov_id = u.pop("_previous_province_id")
                                prev_prov = map_screen.id_to_province.get(prev_prov_id)
                                if prev_prov:
                                    if u in units:
                                        units.remove(u)
                                    u["_current_province_id"] = prev_prov_id
                                    if u not in prev_prov.get("units", []):
                                        prev_prov.setdefault("units", []).append(u)
                                    if "order" in u and "path" in u["order"]:
                                        u["order"]["path"] = []
                    else:
                        capturer = random.choice(tied_by_spd)
            
        # Finalize Capture Logic
        if capturer:
            if capturer != current_owner:
                # faction core transfer stuff
                true_owner = queries.get_faction_core_transfer_target(capturer, province, map_screen.nation_data)
                edit_province_ownership.conquer_province(map_screen, province, true_owner)
            
            # Scuttle ships if an enemy takes the tile they are on
            is_land = not queries.is_water_province(province)
            if is_land:
                for u in units:
                    if queries.is_warship(u.get("type", "")):
                        # Use capturer instead of true_owner here so ships are correctly scuttled even if core transferred
                        if queries.is_hostile_territory(capturer, u["owner"], map_screen.nation_data):
                            u["health"] = 0
                province["units"] = (edge_units +
                                      [u for u in units if u.get("health", 0) > 0])
        else:
            # If no capturer (e.g., bounce tiebreaker triggered), revert any order-of-execution captures
            if current_owner != turn_start_owner:
                edit_province_ownership.conquer_province(map_screen, province, turn_start_owner)
