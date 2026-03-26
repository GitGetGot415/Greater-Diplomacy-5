import pygame

info_rect = pygame.Rect(10, 70, 300, 450) # Increased height for combat info

def draw_sidebar_info(self, surface):
    pygame.draw.rect(surface, (30, 30, 30, 200), info_rect)
    pygame.draw.rect(surface, (200, 200, 200), info_rect, 1)

    province = self.selected_province
    units = province.get("units", [])
    
    # Sort units by owner to see who is present
    owners = set(u["owner"] for u in units)
    
    # Basic Info
    info_lines = [
        f"Province ID: {province['id']}",
        f"Owner: {province['owner'].upper()}",
        f"Terrain: {province['terrain'].upper()}"
    ]
    
    for i, line in enumerate(info_lines):
        tsurf = self.small_font.render(line, True, (255, 255, 255))
        surface.blit(tsurf, (20, 80 + i * 25))

    # COMBAT WINDOW SECTION
    # Detect if units from countries at war are in this tile
    is_combat = False
    if len(owners) > 1:
        # Check if any two owners are at war
        owner_list = list(owners)
        for i in range(len(owner_list)):
            for j in range(i + 1, len(owner_list)):
                nation_a = self.nation_data.get(owner_list[i], {})
                if owner_list[j] in nation_a.get("at_war_with", []):
                    is_combat = True
                    break

    if is_combat:
        y_offset = 180
        header = self.font.render("--- COMBAT ZONE ---", True, (255, 50, 50))
        surface.blit(header, (20, y_offset))
        
        # List units by side
        current_y = y_offset + 30
        for owner in owners:
            owner_units = [u for u in units if u["owner"] == owner]
            color = self.nation_colors.get(owner, (200, 200, 200))
            
            title = self.small_font.render(f"{owner.title()}:", True, color)
            surface.blit(title, (20, current_y))
            current_y += 20
            
            for u in owner_units[:5]:
                u_name = u["type"]
                # If it's infantry, maybe show the level next to the name
                display_name = f"{u_name} (Lvl {u['level']})" if u.get('level') else u_name
                txt = self.small_font.render(f" - {display_name} (ATK: {u['attack']}) (HP: {u['health']}) (DEF: {u['defense']})", True, (200, 200, 200))
                surface.blit(txt, (30, current_y))
                current_y += 20
            current_y += 10