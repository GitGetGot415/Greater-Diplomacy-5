import pygame
import data.constants as c
from data import queries

def draw_tooltip(self, surface):
    if not self.hovered_province:
        return

    mx, my = pygame.mouse.get_pos()
    prov = self.hovered_province
    
    # --- FOG OF WAR VISIBILITY CHECK ---
    is_visible = True
    if getattr(self, 'visible_provinces', None) is not None:
        if prov["id"] not in self.visible_provinces:
            is_visible = False
            
    owner_id = prov.get('owner', 'Unclaimed')
    owner_display = self.nation_data.get(owner_id, {}).get("name", owner_id)
    
    # Coastal Sea and Inland Sea display
    terrain = prov.get('terrain', 'Unknown')
    if terrain in c.WATER_TERRAINS:
        owner_display = terrain.replace('_', ' ').title()
    
    # 1. Start with the basic header info based on the primary map mode
    if getattr(self, 'base_layer', '') == "TERRAIN":
        terrain_display = terrain.replace('_', ' ').title()
        lines = [f"ID: {prov['id']} | {terrain_display}"]
    elif getattr(self, 'base_layer', '') == "RELATIONS":
        # Show exactly how much they like us
        rel_score = queries.get_relation_score(self.player_country, owner_id, self.nation_data, self.id_to_province)
        lines = [f"ID: {prov['id']} | {owner_display}", f"Opinion: {rel_score}"]
    else:
        lines = [f"ID: {prov['id']} | {owner_display}"]

    if getattr(self, 'base_layer', '') == "CORES":
        cores = prov.get("cores", [])
        if cores:
            lines.append(f"Cores: {', '.join(cores)}")

    # 2. Add contextual info based on secondary view mode
    if self.secondary_mode == "BLANK":
        # The header is already set correctly above, no need to overwrite it
        pass
        
    elif self.secondary_mode == "UNITS":
        if not is_visible:
            lines.append("(Units hidden by Fog of War)")
        else:
            units = prov.get("units", [])
            if not units:
                lines.append("No Units Present")
            else:
                lines.append("--- Units ---")
                # Show first 5 units to keep tooltip size reasonable
                for u in units[:5]:
                    u_name = u.get("type", "Unit")
                    level = u.get("level", 0)
                    
                    if level > 0:
                        # refactor: Use 'Type' for Infantry, 'Lvl' for others
                        base_name = queries.get_base_unit_name(u_name)
                        label = "Type" if base_name == "Infantry" else "Lvl"
                        lines.append(f"- {u_name} ({label} {level})")
                    else:
                        lines.append(f"- {u_name}")
                        
                if len(units) > 5:
                    lines.append(f"...and {len(units)-5} more")
    
    elif self.secondary_mode == "RESOURCES":
        if not is_visible:
            lines.append("(Resources hidden by Fog of War)")
        else:
            resources = prov.get("resources", {})
            if isinstance(resources, dict) and resources:
                lines.append("--- Resources ---")
                for r_type, amount in resources.items():
                    if amount > 0:
                        lines.append(f"- {r_type}: {amount}")
            else:
                lines.append("No Natural Resources")

    elif self.secondary_mode == "ECONOMY":
        # Base production from the tile itself dynamically calculated
        owner_data = self.nation_data.get(owner_id, {})
        research_data = owner_data.get("research", {})
        
        # Calculate dynamic bonuses based on tech
        gen_rec_lvl = research_data.get("general_recruitment", 0)
        manpower_bonus = gen_rec_lvl * getattr(c, 'GENERAL_RECRUITMENT_BONUS', 5)
        
        # Base yields including tech bonuses
        base_man = c.BASE_YIELDS['manpower'] + manpower_bonus
        base_mat = c.BASE_YIELDS['materials']
        base_fuel = c.BASE_YIELDS['fuel']

        # Apply core/non-core penalties to give the player the EXACT true yield
        is_core = owner_id in prov.get("cores", [])
        man_mult = 1.0 if is_core else c.NON_CORE_MULTIPLIERS["manpower"]
        mat_mult = 1.0 if is_core else c.NON_CORE_MULTIPLIERS["materials"]
        fuel_mult = 1.0 if is_core else c.NON_CORE_MULTIPLIERS["fuel"]

        actual_man = int(base_man * man_mult)
        actual_mat = int(base_mat * mat_mult)
        actual_fuel = int(base_fuel * fuel_mult)

        lines.append(f"Tile Yield: +{actual_man}Man, +{actual_mat}Mat, +{actual_fuel}Fuel")
        if not is_core and owner_id not in c.UNPLAYABLE_NATIONS:
            lines.append("  *(Non-Core Penalties Applied)*")

        lines.append("--- Buildings ---")
        if not is_visible:
            lines.append("(Hidden by Fog of War)")
        else:
            buildings = prov.get("buildings", [])
            if buildings:
                bldg_lib = queries.get_building_library()
                for b in buildings:
                    # Determine production text dynamically based on building stats
                    stats = bldg_lib.get(b, {})
                    p_mat = stats.get('prod_materials', 0)
                    p_man = stats.get('prod_manpower', 0)
                    p_fuel = stats.get('prod_fuel', 0)
                    
                    yields = []
                    if p_man > 0: yields.append(f"+{p_man}Man")
                    if p_mat > 0: yields.append(f"+{p_mat}Mat")
                    if p_fuel > 0: yields.append(f"+{p_fuel}Fuel")
                    
                    prod_hint = f"({', '.join(yields)})" if yields else ""
                    lines.append(f"- {b} {prod_hint}")

    # 3. Render the Tooltip
    # Calculate dimensions
    rendered_lines = [self.small_font.render(line, True, (255, 255, 255)) for line in lines]
    width = max(ts.get_width() for ts in rendered_lines) + 20
    height = sum(ts.get_height() for ts in rendered_lines) + 15
    
    # Position logic (prevent going off screen)
    tx, ty = mx + 15, my - height
    if tx + width > surface.get_width():
        tx = mx - width - 5
    if ty < 0:
        ty = my + 20

    bg_rect = pygame.Rect(tx, ty, width, height)
    
    # Draw Background
    pygame.draw.rect(surface, (30, 30, 30, 230), bg_rect)
    pygame.draw.rect(surface, (200, 200, 200), bg_rect, 1) # Border
    
    # Draw Text
    curr_y = ty + 8
    for ts in rendered_lines:
        surface.blit(ts, (tx + 10, curr_y))
        curr_y += ts.get_height() + 2