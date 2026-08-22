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

#: Which side of the suicide-charge probe in process_pinning is the charge. The
#: garrison is handed in first, so it is side 0 and the charge is side 1.
CHARGE_SIDE = 1


def apply_group_damage(total_atk, target_units):
    """Distributes total attack among target units, reduced by their individual defense."""
    if not target_units: return
    # Simple distribution: Divide total attack by number of units
    damage_per_unit = total_atk / len(target_units)
    
    for u in target_units:
        defense = u.get("defense", 0)
        actual_dmg = max(0, damage_per_unit - defense)
        
        if actual_dmg > 0:
            max_hp = u.get("max_health", 1)
            percent_lost = (actual_dmg / max_hp) * 100.0
            u["morale"] = max(0.0, float(u.get("morale", c.DEFAULT_UNIT_MORALE)) - percent_lost)
            
        u["health"] -= actual_dmg

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
            order = unit.get("order")
            if not isinstance(order, dict) or order.get("type") != "BOMBARD":
                continue

            target_id = order.get("target_id")
            bomb_range = queries.get_bombardment_range(unit.get("type", ""))

            # Drop the order if the gun can no longer make the shot
            if (bomb_range <= 0
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
            targets = [u for u in target_prov.get("units", [])
                       if queries.are_at_war(owner, u.get("owner"), map_screen.nation_data)]
            if not targets:
                continue

            # Every gun that aimed here contributes; unlike a stack fight this
            # isn't capped by combat width, since each shot was ordered by hand.
            # "bombard_attack" is a separate stat from melee "attack" (falls
            # back to attack for any family that doesn't define it).
            total_atk = sum(u.get("bombard_attack", u.get("attack", c.DEFAULT_UNIT_ATK))
                            * combat_rules.health_damage_multiplier(u) for u in guns)
            apply_group_damage(total_atk, targets)

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
        
        defenders = dest_prov.get("units", [])
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
                    shot = combat_rules.volley(member.front, probe.shares)
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
            max(0, incoming_on_charge.get(id(a_unit), 0.0) - a_unit.get("defense", 0))
            < a_unit.get("health", 1)
            for a_unit in attacker_units_only)

        if not attackers_survive:
            # 1. Attackers are obliterated. Apply their pitiful damage to the defenders.
            for targets, total_atk in shots_at_defenders:
                apply_group_damage(total_atk, targets)

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
    """Fights one meeting engagement: units1 (crossing into prov2) against
    units2 (crossing into prov1). Removes the dead from their provinces and
    combat-locks survivors only when both sides have survivors -- a one-sided
    result leaves the winners free to keep advancing this turn.

    The two sides are gathered by direction of travel, not by flag, so either
    of them can hold several nations at once and not all of them are in the
    fight. Who duels whom is combat_rules.build_battle's answer, the same one
    the tile fight uses, with the clash's two directions of travel as its two
    sides -- so a lane always crosses the divide, and a nation crossing
    alongside a belligerent without a war of its own is neither shot at nor
    stopped.

    Shared by the turn-start pass (combat_processor.process_meeting_engagements,
    using combat_rules.find_meeting_pairs) and the mid-movement pass
    (movement_processor.process_movement), since a swap is the same fight
    whichever step of the turn it happens on.

    Returns a MeetingResult. `survivors1`/`survivors2` are every living unit on
    each side, bystanders included -- the movement pass subtracts them from what
    it handed in to find the dead. `fought` is the id()s of the units that were
    actually in a firing line, which is what the callers gate "stop here" on.
    """
    battle = combat_rules.build_battle([units1, units2], nation_data)

    # Front *and* reserve. `fought` is what stops a unit here, and a reserve that
    # walked on through the tile its own army is fighting over would be absurd --
    # it is in the battle, it just is not in the front rank of it.
    fought = {id(u)
              for lane in battle.lanes
              for side in (lane.a, lane.b)
              for u in side.front + side.reserve}

    # Unpack Convoys Caught in Land Engagements -- only those in the fight.
    is_land_engagement = (not queries.is_water_province(prov1)) or (not queries.is_water_province(prov2))
    if is_land_engagement:
        for u in units1 + units2:
            if id(u) in fought and u.get("type", "").startswith("Convoy"):
                queries.revert_transport(u)

    # Measured before any of it lands, so the exchange is simultaneous.
    for targets, total_atk in combat_rules.exchange(battle):
        apply_group_damage(total_atk, targets)

    # Only the front rank is in combat: a reserve rests and recovers morale
    # while the units ahead of it bleed, which is the pressure to rotate.
    for lane in battle.lanes:
        for u in lane.a.front + lane.b.front:
            u["_in_combat_this_turn"] = True

    surviving_units1 = [u for u in units1 if u.get("health", 0) > 0]
    surviving_units2 = [u for u in units2 if u.get("health", 0) > 0]

    # Only lock them in combat if the enemy survived -- and only the ones who
    # were fighting. A bystander crossing at the same moment walks on.
    fighters1 = [u for u in surviving_units1 if id(u) in fought]
    fighters2 = [u for u in surviving_units2 if id(u) in fought]

    if fighters2:
        for u in fighters1:
            u["_combat_locked"] = True
    if fighters1:
        for u in fighters2:
            u["_combat_locked"] = True

    prov1["units"] = [u for u in prov1["units"] if u.get("health", 0) > 0]
    prov2["units"] = [u for u in prov2["units"] if u.get("health", 0) > 0]

    return MeetingResult(surviving_units1, surviving_units2, fought)

def process_meeting_engagements(map_screen):
    """Rule: If 2 units move into each other, let them engage in combat in between the tiles."""
    # Which tiles swapped garrisons is decided by combat_rules, the same rule
    # the prediction bubbles are drawn from. The sides are read per pair, as we
    # get to them: a unit killed in one engagement must not still be counted in
    # the next engagement its province takes part in.
    for pair in combat_rules.find_meeting_pairs(map_screen.map_data, map_screen.nation_data):
        prov1, prov2, units1, units2 = combat_rules.meeting_sides(map_screen.id_to_province, pair)
        resolve_meeting_engagement(prov1, prov2, units1, units2, map_screen.nation_data)

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
        units = province.get("units", [])
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
        for targets, total_atk in combat_rules.exchange(battle):
            apply_group_damage(total_atk, targets)

        # Only the front rank is in combat: a reserve rests and recovers morale
        # while the units ahead of it bleed, which is the pressure to rotate.
        for lane in battle.lanes:
            for u in lane.a.front + lane.b.front:
                u["_in_combat_this_turn"] = True

        # Remove dead units (HP <= 0) BEFORE checking if we should wipe paths
        surviving_units = [u for u in units if u.get("health", 0) > 0]
        province["units"] = surviving_units

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
            province["units"] = [u for u in surviving_units if u.get("health", 0) > 0]

def check_for_post_combat_captures(map_screen):
    """Assigns province ownership to units standing in an undefended enemy province."""
    for province in map_screen.map_data.values():
        if queries.is_water_province(province):
            continue

        units = province.get("units", [])
        if not units:
            continue
            
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
        valid_capturer_units = []
        for u in units:
            # You can't steal land from someone you are at peace with!
            # However, if the land was captured THIS TURN, we evaluate based on the original owner
            # to prevent order-of-execution advantages in movement processing.
            eval_owner = turn_start_owner if current_owner != turn_start_owner else current_owner
            
            if eval_owner in c.OWNERLESS_OWNERS or queries.are_at_war(u["owner"], eval_owner, map_screen.nation_data):
                valid_capturer_units.append(u)

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
                province["units"] = [u for u in units if u.get("health", 0) > 0]
        else:
            # If no capturer (e.g., bounce tiebreaker triggered), revert any order-of-execution captures
            if current_owner != turn_start_owner:
                edit_province_ownership.conquer_province(map_screen, province, turn_start_owner)