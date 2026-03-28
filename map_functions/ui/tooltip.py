import pygame

def draw_tooltip(self, surface):
    if not self.hovered_province:
        return

    mx, my = pygame.mouse.get_pos()
    prov = self.hovered_province
    owner_id = prov['owner']
    owner_display = self.nation_data.get(owner_id, {}).get("name", owner_id)
    
    # 1. Start with the basic header info
    lines = [f"ID: {prov['id']} | {owner_display}"]

    # 2. Add contextual info based on view mode
    if self.secondary_mode == "BLANK":
        lines = [f"ID: {prov['id']} | {owner_display}"]
    elif self.secondary_mode == "UNITS":
        units = prov.get("units", [])
        if not units:
            lines.append("No Units Present")
        else:
            lines.append("--- Units ---")
            # Show first 5 units to keep tooltip size reasonable
            for u in units[:5]:
                u_name = u.get("type", "Unit")
                # If it's a scaled infantry, show level
                if "level" in u and u["level"] > 0:
                    lines.append(f"- {u_name} (Lvl {u['level']})")
                else:
                    lines.append(f"- {u_name}")
            if len(units) > 5:
                lines.append(f"...and {len(units)-5} more")

    elif self.secondary_mode == "ECONOMY":
        buildings = prov.get("buildings", [])
        if not buildings:
            # Base production from the tile itself
            lines.append("Base Yield: +500M, +50Man, +100Mat, +1Fuel")
        else:
            lines.append("--- Buildings ---")
            for b in buildings:
                # Determine production text based on building name
                prod_hint = ""
                if "Workshop" in b or "Factory" in b:
                    prod_hint = "(+Materials/Money)"
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