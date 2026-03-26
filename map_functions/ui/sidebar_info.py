import pygame

# Define the area for the sidebar info panel
info_rect = pygame.Rect(10, 70, 300, 450)

def draw_sidebar_info(self, surface):
    """
    Draws the left-hand sidebar containing province information 
    and active combat data.
    """
    # 1. Draw the Panel Background and Border
    panel_surf = pygame.Surface((info_rect.width, info_rect.height), pygame.SRCALPHA)
    panel_surf.fill((30, 30, 30, 200))
    surface.blit(panel_surf, (info_rect.x, info_rect.y))
    pygame.draw.rect(surface, (200, 200, 200), info_rect, 1)

    # 2. Extract Province Data
    province = self.selected_province
    if not province:
        return

    owner_id = province.get("owner", "Unclaimed")
    terrain = province.get("terrain", "Unknown")
    units = province.get("units", [])
    
    # 3. Resolve Display Name for the Owner
    owner_data = self.nation_data.get(owner_id, {})
    owner_display = owner_data.get("name", owner_id).upper()

    # 4. Render Basic Information Lines
    info_lines = [
        f"Province ID: {province['id']}",
        f"Owner: {owner_display}",
        f"Terrain: {terrain.upper()}"
    ]
    
    for i, line in enumerate(info_lines):
        tsurf = self.small_font.render(line, True, (255, 255, 255))
        surface.blit(tsurf, (20, 80 + i * 25))

    # 5. Combat Detection
    owners_present = list(set(u.get("owner", "Unknown") for u in units))
    
    is_combat = False
    if len(owners_present) > 1:
        for i in range(len(owners_present)):
            for j in range(i + 1, len(owners_present)):
                nation_a = self.nation_data.get(owners_present[i], {})
                if owners_present[j] in nation_a.get("at_war_with", []):
                    is_combat = True
                    break
            if is_combat: break

    # 6. Draw the Combat Zone Section
    if is_combat:
        y_offset = 180
        header = self.font.render("--- COMBAT ZONE ---", True, (255, 50, 50))
        surface.blit(header, (20, y_offset))
        
        current_y = y_offset + 35
        
        for side_id in owners_present:
            side_data = self.nation_data.get(side_id, {})
            side_display = side_data.get("name", side_id).title()
            side_color = self.nation_colors.get(side_id, (200, 200, 200))
            
            title = self.small_font.render(f"{side_display}:", True, side_color)
            surface.blit(title, (20, current_y))
            current_y += 22
            
            side_units = [u for u in units if u.get("owner") == side_id]
            for u in side_units[:5]:
                u_type = u.get("type", "Unit")
                
                # --- FIX: Use .get() to prevent KeyError if stats are missing ---
                atk = u.get("attack", 0)
                hp = int(u.get("health", 0))
                
                # Formatting string based on whether it's scaled Infantry or standard
                if u.get('level'):
                    u_stats = f" - {u_type} Lvl {u['level']} (HP: {hp})"
                else:
                    u_stats = f" - {u_type} (ATK: {atk}) (HP: {hp})"

                txt = self.small_font.render(u_stats, True, (200, 200, 200))
                surface.blit(txt, (30, current_y))
                current_y += 20
            
            current_y += 10