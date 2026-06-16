import pygame
import data.constants as c
from data.io import country_io
from map_logic.rendering import map_utils

def conquer_province(self, province, new_owner):
    """Annexes a specific province to a specific country and updates visuals."""
    if province:
        # --- NEW: If you ever lose a territory, you immediately get a claim on it ---
        old_owner = province.get("owner", "Unclaimed")
        if old_owner not in c.UNPLAYABLE_NATIONS and old_owner != new_owner:
            add_claim(self, province, old_owner)

        # 1. Logic Update
        province["owner"] = new_owner
        
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

        if not province.get("cores"):
            province["cores"] = [new_owner]

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
    for c in cores:
        col = nations_dict.get(c)
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
        if not self.viewing_ai_moves and not getattr(self, 'ai_is_thinking', False):
            new_color = get_mixed_core_color(cores)
            map_utils.update_single_province_surface(self.cores_map, self.id_map, province["map_color"], new_color)
            if self.map_mode == "CORES": self.active_map = self.cores_map

def remove_core(self, province, nation):
    if province and nation:
        cores = province.setdefault("cores", [])
        if nation in cores:
            cores.remove(nation)
        
        # Visual Update
        if not self.viewing_ai_moves and not getattr(self, 'ai_is_thinking', False):
            new_color = get_mixed_core_color(cores)
            map_utils.update_single_province_surface(self.cores_map, self.id_map, province["map_color"], new_color)
            if self.map_mode == "CORES": self.active_map = self.cores_map

def clear_cores(self, province):
    """Wipes all cores from the tile for the Unclaimed Eraser brush."""
    if province:
        province["cores"] = []
        
        # Visual Update
        if not self.viewing_ai_moves and not getattr(self, 'ai_is_thinking', False):
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