import pygame
import data.constants as c
from data import queries
from map_logic.rendering.font_manager import fonts

def draw_bottom_text(map_screen, surface):
    """Draws the bottom resource bar with net income overlays."""
    hide_hud = map_screen.hide_resource_hud or map_screen.is_editor
    
    if hide_hud:
        return

    hud_y = c.SCREEN_HEIGHT - c.RESOURCE_HUD_HEIGHT_OFFSET
    
    # --- TACTICAL ECONOMY OVERRIDE ---
    if getattr(map_screen, 'tactical_mode', False) and getattr(map_screen, 'player_unit', None):
        u_type = map_screen.player_unit.get("original_type", map_screen.player_unit.get("type"))
        stats = queries.get_unit_library().get(u_type, {})
        
        total_inc = {
            "manpower": stats.get("cost_manpower", 0) * c.UPKEEP_MODIFIERS["manpower"],
            "materials": stats.get("cost_materials", 0) * c.UPKEEP_MODIFIERS["materials"],
            "fuel": stats.get("cost_fuel", 0) * c.UPKEEP_MODIFIERS["fuel"]
        }
        total_upkeep = {"manpower": 0, "materials": 0, "fuel": 0}
    else:
        # Cache logic to prevent calculating economy 60 times a second
        if not hasattr(map_screen, 'econ_cache_time') or pygame.time.get_ticks() - map_screen.econ_cache_time > 1000:
            map_screen.econ_cache = queries.get_economy_projections(map_screen.player_country, map_screen.map_data, map_screen.nation_data)
            map_screen.econ_cache_time = pygame.time.get_ticks()
            
        cached_data = map_screen.econ_cache
        if cached_data and len(cached_data) == 3:
            total_inc, total_upkeep, _ = cached_data
        else:
            total_inc = {"manpower": 0, "materials": 0, "fuel": 0}
            total_upkeep = {"manpower": 0, "materials": 0, "fuel": 0}

    def fmt_net(inc, exp):
        net = int(inc - exp)
        return f"+{net}" if net >= 0 else str(net)

    resources = [
        (f"Manpower: {int(map_screen.player_manpower)} ({fmt_net(total_inc['manpower'], total_upkeep['manpower'])})", (100, 200, 255)),
        (f"Materials: {int(map_screen.player_materials)} ({fmt_net(total_inc['materials'], total_upkeep['materials'])})", (180, 180, 180)),
        (f"Fuel: {int(map_screen.player_fuel)} ({fmt_net(total_inc['fuel'], total_upkeep['fuel'])})", (200, 100, 255))
    ]
    
    # Draw Background Box
    bg_width = (len(resources) * c.RESOURCE_HUD_SPACING) - 40
    bg_surf = pygame.Surface((bg_width, 30), pygame.SRCALPHA)
    bg_surf.fill((0, 0, 0, c.RESOURCE_HUD_BG_ALPHA))
    
    bg_rect = pygame.Rect(c.RESOURCE_HUD_START_X - 15, hud_y - 5, bg_width, 30)
    surface.blit(bg_surf, bg_rect.topleft)
    pygame.draw.rect(surface, (100, 100, 100), bg_rect, 1) 

    # Draw Text using the dedicated preset
    hud_font = fonts.get("resource_hud")
    for i, (text, color) in enumerate(resources):
        surface.blit(hud_font.render(text, True, color), (c.RESOURCE_HUD_START_X + (i * c.RESOURCE_HUD_SPACING), hud_y))