import data.constants as c
from data.io import country_io
from map_logic.rendering import map_utils

def conquer_province(self, province, new_owner):
    """Annexes a specific province to a specific country and updates visuals."""
    if province:
        # --- NEW: Integrated Puppet Capture Reroute ---
        if new_owner in self.nation_data:
            nd = self.nation_data[new_owner]
            if nd.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED:
                if province["id"] not in nd.get("spawned_territories", []):
                    master = nd.get("master")
                    if master and master in self.nation_data:
                        new_owner = master

        # --- NEW: If you ever lose a territory, you immediately get a claim on it ---
        old_owner = province.get("owner", "Unclaimed")
        if old_owner not in c.UNPLAYABLE_NATIONS and old_owner != new_owner and not self.is_editor:
            add_claim(self, province, old_owner)

        # 1. Logic Update
        province["owner"] = new_owner
        
        # --- BUGFIX: Clear coring progress on capture ---
        if "building_queue" in province:
            province["building_queue"] = [q for q in province["building_queue"] if q.get("order_type") != "CORE"]
        
        # 2. Visual Update
        if not self.viewing_ai_moves and not self.ai_is_thinking:
            nations_dict = country_io.get_nation_colors()
            new_color = list(nations_dict.get(new_owner, (255, 255, 255))) # Fallback to white if unclaimed
            
            # --- THE MAGIC PINK BUG FIX ---
            # If the nation's color is completely identical to our colorkey mapping, shift it 1 bit
            if tuple(new_color) == (255, 0, 255):
                new_color = (254, 0, 255)
            
            map_utils.update_single_province_surface(
                self.political_map, 
                self.id_map, 
                province["map_color"], 
                new_color
            )
            
            # 3. Sync the active view
            if self.map_mode == "POLITICAL":
                self.active_map = self.political_map
                
        # 4. UPDATE COUNTRY CENTER FOR TEXT RENDERING
        # Flag this for an update later rather than doing the heavy math instantly
        self.centers_need_update = True

        if not self.is_editor:
            if not province.get("cores"):
                province["cores"] = [new_owner]

        # --- NEW: Check if old owner was a created integrated puppet and lost all territory ---
        if old_owner != new_owner and old_owner in self.nation_data:
            should_delete = False
            
            if self.nation_data[old_owner].get("is_created_integrated_puppet", False):
                should_delete = not any(p.get("owner") == old_owner for p in self.map_data.values())
            
            # Rebellion killed before peace deal: still at war means defeated in combat, not via treaty
            if self.nation_data[old_owner].get("is_rebellion", False):
                if not any(p.get("owner") == old_owner for p in self.map_data.values()):
                    if self.nation_data[old_owner].get("at_war_with", []):
                        should_delete = True
            
            if should_delete:
                # Remove all cores of this country from the map
                for p in self.map_data.values():
                    if old_owner in p.get("cores", []):
                        p["cores"].remove(old_owner)
                        # Visual Update (similar to remove_core)
                        if not self.viewing_ai_moves and not self.ai_is_thinking:
                            new_color = get_mixed_core_color(p["cores"])
                            map_utils.update_single_province_surface(self.cores_map, self.id_map, p["map_color"], new_color)
                            if self.map_mode == "CORES": self.active_map = self.cores_map
                            
                # --- Completely remove from the game ---
                # 1. Break puppet link from master
                master = self.nation_data[old_owner].get("master", "")
                if master and master in self.nation_data:
                    if old_owner in self.nation_data[master].get("puppets", []):
                        self.nation_data[master]["puppets"].remove(old_owner)
                        
                # 2. Cleanup references in other nations
                for n_id, n_data in list(self.nation_data.items()):
                    if old_owner in n_data.get("at_war_with", []):
                        n_data["at_war_with"].remove(old_owner)
                    if old_owner in n_data.get("allied_with", []):
                        n_data["allied_with"].remove(old_owner)
                    if old_owner in n_data.get("puppets", []):
                        n_data["puppets"].remove(old_owner)
                    if n_data.get("master") == old_owner:
                        n_data["master"] = ""
                        n_data["puppet_type"] = ""
                        
                    for dict_key in ["relations", "truces", "diplo_cooldowns", "wargoals", "pending_diplomacy", "draft_lists"]:
                        if old_owner in n_data.get(dict_key, {}):
                            del n_data[dict_key][old_owner]
                            
                    # Remove messages sent by the dead entity to avoid ghost notifications
                    if "inbox" in n_data:
                        n_data["inbox"] = [msg for msg in n_data["inbox"] if msg.get("sender") != old_owner]
                            
                # Cleanup faction maps
                fac = self.nation_data[old_owner].get("faction", "")
                if fac and "FACTION_WAR_MAPS" in self.nation_data:
                    if fac in self.nation_data["FACTION_WAR_MAPS"]:
                        if old_owner in self.nation_data["FACTION_WAR_MAPS"][fac]:
                            del self.nation_data["FACTION_WAR_MAPS"][fac][old_owner]
                            
                # 3. Finally delete from nation_data
                del self.nation_data[old_owner]

def get_mixed_core_color(cores):
    """Helper function to average the colors of all cores on a tile."""
    nations_dict = country_io.get_nation_colors() 
    if not cores:
        return (255, 255, 255)
    if len(cores) == 1:
        color = nations_dict.get(cores[0], (255, 255, 255))
        if tuple(color) == (255, 0, 255):
            return (254, 0, 255)
        return color
        
    r = g = b = valid = 0
    for core in cores:
        col = nations_dict.get(core)
        if col:
            r += col[0]; g += col[1]; b += col[2]
            valid += 1
            
    color = (r // valid, g // valid, b // valid) if valid > 0 else (255, 255, 255)
    
    # Check Magic Pink for blended multi-core tiles as well!
    if tuple(color) == (255, 0, 255):
        return (254, 0, 255)
    return color

def add_core(self, province, nation):
    if province and nation:
        cores = province.setdefault("cores", [])
        if nation not in cores:
            cores.insert(0, nation) # Insert at front as primary
        
        # Visual Update
        if not self.viewing_ai_moves and not self.ai_is_thinking:
            new_color = get_mixed_core_color(cores)
            map_utils.update_single_province_surface(self.cores_map, self.id_map, province["map_color"], new_color)
            if self.map_mode == "CORES": self.active_map = self.cores_map

def remove_core(self, province, nation):
    if province and nation:
        cores = province.setdefault("cores", [])
        if nation in cores:
            cores.remove(nation)
        
        # Visual Update
        if not self.viewing_ai_moves and not self.ai_is_thinking:
            new_color = get_mixed_core_color(cores)
            map_utils.update_single_province_surface(self.cores_map, self.id_map, province["map_color"], new_color)
            if self.map_mode == "CORES": self.active_map = self.cores_map

def clear_cores(self, province):
    """Wipes all cores from the tile for the Unclaimed Eraser brush."""
    if province:
        province["cores"] = []
        
        # Visual Update
        if not self.viewing_ai_moves and not self.ai_is_thinking:
            map_utils.update_single_province_surface(self.cores_map, self.id_map, province["map_color"], (255, 255, 255))
            if self.map_mode == "CORES": self.active_map = self.cores_map

def add_claim(self, province, nation):
    if province and nation:
        prov_id = province["id"]
        claims = self.nation_data.setdefault(nation, {}).setdefault("claims", [])
        if prov_id not in claims:
            claims.append(prov_id)
        # Force a label text realignment
        self.centers_need_update = True

def remove_claim(self, province, nation):
    if province and nation:
        prov_id = province["id"]
        claims = self.nation_data.get(nation, {}).get("claims", [])
        if prov_id in claims:
            claims.remove(prov_id)
        self.centers_need_update = True

def clear_claims(self, province):
    if province:
        prov_id = province["id"]
        for n_data in self.nation_data.values():
            claims = n_data.get("claims", [])
            if prov_id in claims:
                claims.remove(prov_id)
        self.centers_need_update = True