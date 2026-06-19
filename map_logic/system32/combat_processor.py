import data.constants as c
from data import queries
from map_logic.system32 import edit_province_ownership
import random # Imported for the random tiebreaker

def apply_group_damage(total_atk, target_units):
    """Distributes total attack among target units, reduced by their individual defense."""
    if not target_units: return
    # Simple distribution: Divide total attack by number of units
    damage_per_unit = total_atk / len(target_units)
    
    for u in target_units:
        defense = u.get("defense", 0)
        actual_dmg = max(0, damage_per_unit - defense)
        u["health"] -= actual_dmg

def process_pinning(self):
    """Rule: Units being attacked from a tile must defend the tile they're on, unless moving to friendly territory."""
    incoming_attacks = {}
    for province in self.map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                dest_id = order["path"][0]
                dest_prov = self.id_to_province.get(dest_id)
                if dest_prov and queries.is_hostile_territory(unit["owner"], dest_prov.get("owner", "Unclaimed"), self.nation_data):
                    # Track the origin province ID (province["id"]) along with the unit
                    incoming_attacks.setdefault(dest_id, []).append((unit, province["id"]))

    # --- NEW: RESOLVE SUICIDE CHARGES ---
    # If incoming attackers are so weak they'd die instantly, resolve the combat NOW
    # so they die, deal their damage, and don't pin the defenders.
    for dest_id, attackers_info in list(incoming_attacks.items()):
        dest_prov = self.id_to_province.get(dest_id)
        if not dest_prov: continue
        
        defenders = dest_prov.get("units", [])
        if not defenders: continue
        
        tile_owner = dest_prov.get("owner", "Unclaimed")
        if tile_owner in c.UNPLAYABLE_NATIONS: continue
        
        friendly_defenders = [u for u in defenders if not queries.are_at_war(tile_owner, u.get("owner"), self.nation_data)]
        if not friendly_defenders: continue
        
        # Only top attackers deal damage
        top_friendly_defenders = sorted(friendly_defenders, key=lambda x: x.get("attack", c.DEFAULT_UNIT_ATK), reverse=True)[:c.MAX_COMBAT_ATTACKERS]
        total_defender_atk = sum(u.get("attack", c.DEFAULT_UNIT_ATK) for u in top_friendly_defenders)
        
        hostile_attackers = [
            info for info in attackers_info
            if queries.are_at_war(tile_owner, info[0].get("owner"), self.nation_data)
        ]
        
        if not hostile_attackers: continue
        
        damage_per_attacker = total_defender_atk / len(hostile_attackers)
        attackers_survive = False
        
        for a_unit, _ in hostile_attackers:
            actual_dmg = max(0, damage_per_attacker - a_unit.get("defense", 0))
            if actual_dmg < a_unit.get("health", 1):
                attackers_survive = True
                break
                
        if not attackers_survive:
            # 1. Attackers are obliterated. Apply their pitiful damage to the defenders.
            attacker_units_only = [a_unit for a_unit, _ in hostile_attackers]
            top_suicide_attackers = sorted(attacker_units_only, key=lambda x: x.get("attack", c.DEFAULT_UNIT_ATK), reverse=True)[:c.MAX_COMBAT_ATTACKERS]
            total_attacker_atk = sum(a_unit.get("attack", c.DEFAULT_UNIT_ATK) for a_unit in top_suicide_attackers)
            apply_group_damage(total_attacker_atk, friendly_defenders)
            
            # 2. Kill the attackers and remove them from incoming_attacks
            for a_unit, a_origin_id in hostile_attackers:
                a_unit["health"] = 0
                incoming_attacks[dest_id] = [info for info in incoming_attacks[dest_id] if info[0] != a_unit]
                
                # Cleanup dead units from their origin province immediately
                a_prov = self.id_to_province.get(a_origin_id)
                if a_prov:
                    a_prov["units"] = [u for u in a_prov["units"] if u.get("health", 0) > 0]
            
            # 3. Cleanup dead defenders in the destination province (just in case they died to scratch damage)
            dest_prov["units"] = [u for u in dest_prov["units"] if u.get("health", 0) > 0]

    # --- STANDARD PINNING LOGIC ---
    for province in self.map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                dest_id = order["path"][0]
                dest_prov = self.id_to_province.get(dest_id)
                
                # If moving to hostile territory, check if we are pinned by an incoming attack
                if dest_prov and queries.is_hostile_territory(unit["owner"], dest_prov.get("owner", "Unclaimed"), self.nation_data):
                    attackers = incoming_attacks.get(province["id"], [])
                    
                    # ONLY pin if the attacker is hostile AND NOT coming from the tile we are moving to.
                    hostile_attackers = [
                        a for a, origin_id in attackers 
                        if queries.are_at_war(unit["owner"], a["owner"], self.nation_data) and origin_id != dest_id
                    ]
                    
                    if hostile_attackers:
                        # Pinned! Cannot attack outwards. Must defend.
                        order["path"] = []

def process_meeting_engagements(self):
    """Rule: If 2 units move into each other, let them engage in combat in between the tiles."""
    incoming = {}
    for prov in self.map_data.values():
        for u in prov.get("units", []):
            order = u.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                dest_id = order["path"][0]
                incoming.setdefault(dest_id, []).append((u, prov["id"], prov))

    processed_pairs = set()
    for dest_id, attackers in incoming.items():
        for u_a, origin_a_id, prov_a in attackers:
            crossers = []
            for u_b, orig_b_id, prov_b in incoming.get(origin_a_id, []):
                if orig_b_id == dest_id and queries.are_at_war(u_a["owner"], u_b["owner"], self.nation_data):
                    crossers.append((u_b, prov_b))
            
            if crossers:
                pair = tuple(sorted([origin_a_id, dest_id]))
                if pair not in processed_pairs:
                    processed_pairs.add(pair)
                    
                    prov1 = self.id_to_province[pair[0]]
                    prov2 = self.id_to_province[pair[1]]
                    
                    # Safely check if the path has elements before grabbing index 0
                    units1 = [u for u in prov1.get("units", []) if u.get("order", {}).get("path") and u["order"]["path"][0] == pair[1]]
                    units2 = [u for u in prov2.get("units", []) if u.get("order", {}).get("path") and u["order"]["path"][0] == pair[0]]
                    
                    # Unpack Convoys Caught in Land Engagements
                    is_land_engagement = (prov1.get("terrain") not in c.WATER_TERRAINS) or (prov2.get("terrain") not in c.WATER_TERRAINS)
                    if is_land_engagement:
                        for u in units1 + units2:
                            if u.get("type", "").startswith("Convoy"):
                                queries.revert_transport(u)
                    
                    # Sort and cap attackers
                    top_units1 = sorted(units1, key=lambda x: x.get("attack", c.DEFAULT_UNIT_ATK), reverse=True)[:c.MAX_COMBAT_ATTACKERS]
                    top_units2 = sorted(units2, key=lambda x: x.get("attack", c.DEFAULT_UNIT_ATK), reverse=True)[:c.MAX_COMBAT_ATTACKERS]
                    
                    atk1 = sum(u.get("attack", c.DEFAULT_UNIT_ATK) for u in top_units1)
                    atk2 = sum(u.get("attack", c.DEFAULT_UNIT_ATK) for u in top_units2)
                    
                    apply_group_damage(atk2, units1)
                    apply_group_damage(atk1, units2)
                    
                    # Only lock them in combat if the enemy survived!
                    surviving_units1 = [u for u in units1 if u.get("health", 0) > 0]
                    surviving_units2 = [u for u in units2 if u.get("health", 0) > 0]
                    
                    if surviving_units2:
                        for u in surviving_units1:
                            u["_combat_locked"] = True
                    if surviving_units1:
                        for u in surviving_units2:
                            u["_combat_locked"] = True
                    
                    prov1["units"] = [u for u in prov1["units"] if u.get("health", 0) > 0]
                    prov2["units"] = [u for u in prov2["units"] if u.get("health", 0) > 0]

def process_combat(self):
    """Calculates turn-based damage for units sharing a province."""
    for province in self.map_data.values():
        units = province.get("units", [])
        if len(units) < 2:
            continue
            
        is_land = province.get("terrain") not in c.WATER_TERRAINS
        
        # Unpack Convoys Caught on Land
        if is_land and queries.is_province_in_active_combat(province, self.nation_data):
            for u in units:
                if u.get("type", "").startswith("Convoy"):
                    queries.revert_transport(u)
            
        # Group units by owner to calculate total attack per side
        sides = {}
        for u in units:
            owner = u["owner"]
            if owner not in sides:
                sides[owner] = {"units": [], "total_atk": 0}
            sides[owner]["units"].append(u)

        owners = list(sides.keys())
        
        # Sort and cap attackers for each side
        for owner in owners:
            owner_units = sorted(sides[owner]["units"], key=lambda x: x.get("attack", c.DEFAULT_UNIT_ATK), reverse=True)
            top_attackers = owner_units[:c.MAX_COMBAT_ATTACKERS]
            sides[owner]["total_atk"] = sum(u.get("attack", c.DEFAULT_UNIT_ATK) for u in top_attackers)

        combat_occurred = False
        
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                nation_a = owners[i]
                nation_b = owners[j]
                
                # Check if they are actually at war
                at_war = queries.are_at_war(nation_a, nation_b, self.nation_data)
                
                if at_war:
                    combat_occurred = True
                    # Side A attacks Side B
                    apply_group_damage(sides[nation_a]["total_atk"], sides[nation_b]["units"])
                    # Side B attacks Side A
                    apply_group_damage(sides[nation_b]["total_atk"], sides[nation_a]["units"])

        # Remove dead units (HP <= 0) BEFORE checking if we should wipe paths
        surviving_units = [u for u in units if u.get("health", 0) > 0]
        province["units"] = surviving_units

        # Wipe queues and destroy misplaced naval units ONLY if combat is still ongoing
        if combat_occurred:
            is_land = not queries.is_water_province(province)
            
            # Check if there are STILL enemies present after the combat phase
            still_in_combat = queries.is_province_in_active_combat(province, self.nation_data)
            
            for u in surviving_units:
                if still_in_combat:
                    if "order" in u and "path" in u["order"]:
                        u["order"]["path"] = []
                
                # Immediately destroy warships caught in land combat
                if is_land and queries.is_naval_unit(u.get("type", "")) and not u.get("type", "").startswith("Convoy"):
                    u["health"] = 0
            
            # Filter dead ships out
            province["units"] = [u for u in surviving_units if u.get("health", 0) > 0]

def check_for_post_combat_captures(self):
    """Assigns province ownership to units standing in an undefended enemy province."""
    for province in self.map_data.values():
        if province.get("terrain") in c.WATER_TERRAINS:
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
                edit_province_ownership.conquer_province(self, province, turn_start_owner)
            continue
            
        # Ensure capturer is legally allowed to take the tile
        valid_capturer_units = []
        for u in units:
            # You can't steal land from someone you are at peace with!
            if current_owner in ["Unclaimed", "None", "Ocean", "Lakes"] or queries.are_at_war(u["owner"], current_owner, self.nation_data):
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
                    # Tiebreaker 3: Let fate decide
                    capturer = random.choice(tied_by_spd)
            
        # Finalize Capture Logic
        if capturer:
            if capturer != current_owner:
                # faction core transfer stuff
                true_owner = queries.get_faction_core_transfer_target(capturer, province, self.nation_data)
                edit_province_ownership.conquer_province(self, province, true_owner)
            
            # Scuttle ships if an enemy takes the tile they are on
            is_land = province.get("terrain") not in c.WATER_TERRAINS
            if is_land:
                for u in units:
                    if queries.is_naval_unit(u.get("type", "")) and not u.get("type", "").startswith("Convoy"):
                        # Use capturer instead of true_owner here so ships are correctly scuttled even if core transferred
                        if queries.is_hostile_territory(capturer, u["owner"], self.nation_data):
                            u["health"] = 0
                province["units"] = [u for u in units if u.get("health", 0) > 0]