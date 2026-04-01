import pygame
from data import country_io
from map_functions.logic import map_utils

def conquer_province(self, province, new_owner):
    """Annexes a specific province to a specific country and updates visuals."""
    if province:
        # 1. Logic Update
        province["owner"] = new_owner
        
        # 2. Visual Update
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
            
        # 4. UPDATE COUNTRY CENTER FOR TEXT RENDERING <-- NEW
        if hasattr(self, 'update_country_centers'):
            self.update_country_centers()

def add_core(self, province, nation):
    if province and nation:
        cores = province.setdefault("cores", [])
        if nation not in cores:
            cores.insert(0, nation) # Insert at front as primary
        
        nations_dict = country_io.get_nation_colors() 
        new_color = nations_dict.get(nation, (255, 255, 255))
        
        map_utils.update_single_province_surface(self.cores_map, self.id_map, province["map_color"], new_color)
        if self.map_mode == "CORES": self.active_map = self.cores_map

def remove_core(self, province, nation):
    if province and nation:
        cores = province.setdefault("cores", [])
        if nation in cores:
            cores.remove(nation)
        
        primary_core = cores[0] if cores else "Unclaimed"
        nations_dict = country_io.get_nation_colors() 
        new_color = nations_dict.get(primary_core, (255, 255, 255))
        
        map_utils.update_single_province_surface(self.cores_map, self.id_map, province["map_color"], new_color)
        if self.map_mode == "CORES": self.active_map = self.cores_map