import pygame
import base64
from data.constants import UI_LEFT_OFFSET, UNPLAYABLE_NATIONS
from map_functions.rendering.font_manager import fonts

# Define the area for the sidebar info panel
sidebar_x = 580
sidebar_y = 70
info_rect = pygame.Rect(sidebar_x, sidebar_y, 300, 450)

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
        text_x = sidebar_x + 10
        surface.blit(tsurf, (text_x, 80 + i * 25))

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
        x_offset = sidebar_x + 10
        header = self.font.render("--- COMBAT ZONE ---", True, (255, 50, 50))
        surface.blit(header, (x_offset, y_offset))
        
        current_y = y_offset + 35
        
        for side_id in owners_present:
            side_data = self.nation_data.get(side_id, {})
            side_display = side_data.get("name", side_id).title()
            side_color = self.nation_colors.get(side_id, (200, 200, 200))
            
            title = self.small_font.render(f"{side_display}:", True, side_color)
            surface.blit(title, (x_offset, current_y))
            current_y += 22
            
            side_units = [u for u in units if u.get("owner") == side_id]
            for u in side_units[:5]:
                u_type = u.get("type", "Unit")
                atk = u.get("attack", 0)
                defense = u.get("defense", 0)
                hp = int(u.get("health", 0))
                
                u_stats = f" - {u_type} (ATK: {atk}) (DEF: {defense}) (HP: {hp})"

                txt = self.small_font.render(u_stats, True, (200, 200, 200))
                surface.blit(txt, (x_offset + 10, current_y))
                current_y += 20
            
            current_y += 10

# --- NEW FUNCTION FOR PORTRAIT ---
def draw_owner_portrait(self, surface):
    """
    Draws the portrait, name, and title of the selected province's owner in the top left.
    """
    province = self.selected_province
    if not province: return

    owner_id = province.get("owner", "Unclaimed")
    if owner_id in UNPLAYABLE_NATIONS: return

    owner_data = self.nation_data.get(owner_id, {})
    leader_name = owner_data.get("leader_name", "Unknown Leader")
    leader_title = owner_data.get("leader_title", "")
    portrait_str = owner_data.get("portrait_data", "")

    # Position safely beside the Left UI Bar and below the Top UI Bar
    start_x = UI_LEFT_OFFSET + 20
    start_y = 80

    # Draw Portrait
    if portrait_str:
        try:
            img_bytes = base64.b64decode(portrait_str)
            portrait_surf = pygame.image.fromstring(img_bytes, (60, 60), "RGB")
            portrait_surf = pygame.transform.scale(portrait_surf, (120, 120)) # Scale like the flag
            surface.blit(portrait_surf, (start_x, start_y))
            pygame.draw.rect(surface, (200, 200, 200), (start_x, start_y, 120, 120), 2)
        except Exception:
            pass

    # Render Text
    font = fonts.get("heading2")
    small_font = fonts.get("normal")

    name_surf = font.render(leader_name, True, (255, 255, 255))
    title_surf = small_font.render(leader_title, True, (200, 200, 200))

    # Text shadows for visibility over the map
    name_shadow = font.render(leader_name, True, (0, 0, 0))
    title_shadow = small_font.render(leader_title, True, (0, 0, 0))

    text_x = start_x + 135
    
    # Blit Name
    surface.blit(name_shadow, (text_x + 1, start_y + 11))
    surface.blit(name_surf, (text_x, start_y + 10))

    # Blit Title
    surface.blit(title_shadow, (text_x + 1, start_y + 41))
    surface.blit(title_surf, (text_x, start_y + 40))