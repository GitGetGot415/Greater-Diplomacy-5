import pygame
from data.economy_data import BASE_YIELDS

def draw_tooltip(self, surface):
    if not self.hovered_province:
        return

    mx, my = pygame.mouse.get_pos()
    prov = self.hovered_province
    owner_id = prov.get('owner', 'Unclaimed')
    owner_display = self.nation_data.get(owner_id, {}).get("name", owner_id)
    
    # 1. Start with the basic header info based on the primary map mode
    if getattr(self, 'base_layer', '') == "TERRAIN":
        terrain_display = prov.get('terrain', 'Unknown').replace('_', ' ').title()
        lines = [f"ID: {prov['id']} | {terrain_display}"]
    else:
        lines = [f"ID: {prov['id']} | {owner_display}"]

    cores = prov.get("cores", [])
    if cores:
        lines.append(f"Cores: {', '.join(cores)}")

    # 2. Add contextual info based on secondary view mode
    if self.secondary_mode == "BLANK":
        # The header is already set correctly above, no need to overwrite it
        pass
        
    elif self.secondary_mode == "UNITS":
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
                    label = "Type" if u_name.lower() == "infantry" else "Lvl"
                    lines.append(f"- {u_name} ({label} {level})")
                else:
                    lines.append(f"- {u_name}")
                    
            if len(units) > 5:
                lines.append(f"...and {len(units)-5} more")
    
    elif self.secondary_mode == "RESOURCES":
            resources = prov.get("resources", {})
            if isinstance(resources, dict) and resources:
                lines.append("--- Resources ---")
                for r_type, amount in resources.items():
                    if amount > 0:
                        lines.append(f"- {r_type}: {amount}")
            else:
                lines.append("No Natural Resources")

    elif self.secondary_mode == "ECONOMY":
        buildings = prov.get("buildings", [])
        if not buildings:
            # Base production from the tile itself dynamically pulled from config
            lines.append(f"Base Yield: +{BASE_YIELDS['manpower']}Man, +{BASE_YIELDS['materials']}Mat, +{BASE_YIELDS['fuel']}Fuel")
        else:
            lines.append("--- Buildings ---")
            for b in buildings:
                # Determine production text based on building name
                prod_hint = ""
                if "Workshop" in b or "Factory" in b:
                    prod_hint = "(+Materials)"
                elif "Refinery" in b:
                    prod_hint = "(+Fuel)"
                
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