import pygame
from data.io import country_io
from map_logic.rendering import map_utils

def conquer_province(self, province, new_owner):
    """Annexes a specific province to a specific country and updates visuals."""
    if province:
        # 1. Logic Update
        province["owner"] = new_owner
        
        # 2. Visual Update
        # SKIP individual surface updates during Turn Resolution to prevent massive lag.
        # The turn_manager will bulk-refresh the map using NumPy at the end of the phase.
        if not getattr(self, 'viewing_ai_moves', False):
            nations_dict = country_io.get_nation_colors() 
            new_color = nations_dict.get(new_owner, (255, 255, 255)) # Fallback to white if unclaimed
            
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

def get_mixed_core_color(cores):
    """Helper function to average the colors of all cores on a tile."""
    nations_dict = country_io.get_nation_colors() 
    if not cores:
        return (255, 255, 255)
    if len(cores) == 1:
        return nations_dict.get(cores[0], (255, 255, 255))
        
    r = g = b = valid = 0
    for c in cores:
        col = nations_dict.get(c)
        if col:
            r += col[0]; g += col[1]; b += col[2]
            valid += 1
            
    return (r // valid, g // valid, b // valid) if valid > 0 else (255, 255, 255)

def add_core(self, province, nation):
    if province and nation:
        cores = province.setdefault("cores", [])
        if nation not in cores:
            cores.insert(0, nation) # Insert at front as primary
        
        # Visual Update
        if not getattr(self, 'viewing_ai_moves', False):
            new_color = get_mixed_core_color(cores)
            map_utils.update_single_province_surface(self.cores_map, self.id_map, province["map_color"], new_color)
            if self.map_mode == "CORES": self.active_map = self.cores_map

def remove_core(self, province, nation):
    if province and nation:
        cores = province.setdefault("cores", [])
        if nation in cores:
            cores.remove(nation)
        
        # Visual Update
        if not getattr(self, 'viewing_ai_moves', False):
            new_color = get_mixed_core_color(cores)
            map_utils.update_single_province_surface(self.cores_map, self.id_map, province["map_color"], new_color)
            if self.map_mode == "CORES": self.active_map = self.cores_map

def clear_cores(self, province):
    """Wipes all cores from the tile for the Unclaimed Eraser brush."""
    if province:
        province["cores"] = []
        
        # Visual Update
        if not getattr(self, 'viewing_ai_moves', False):
            map_utils.update_single_province_surface(self.cores_map, self.id_map, province["map_color"], (255, 255, 255))
            if self.map_mode == "CORES": self.active_map = self.cores_map