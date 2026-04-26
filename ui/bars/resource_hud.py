import pygame
import data.constants as c
from data import queries

def draw_bottom_text(map_screen, surface):
    """Draws the bottom resource bar with net income overlays."""
    hide_hud = getattr(map_screen, 'hide_resource_hud', False) or map_screen.is_editor
    
    if hide_hud:
        return

    hud_y = c.SCREEN_HEIGHT - c.RESOURCE_HUD_HEIGHT_OFFSET
    
    # Cache logic to prevent calculating economy 60 times a second
    if not hasattr(map_screen, 'econ_cache_time') or pygame.time.get_ticks() - getattr(map_screen, 'econ_cache_time', 0) > 1000:
        map_screen.econ_cache = queries.get_economy_projections(map_screen.player_country, map_screen.map_data, map_screen.nation_data)
        map_screen.econ_cache_time = pygame.time.get_ticks()
        
    cached_data = getattr(map_screen, 'econ_cache', None)
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

    # Draw Text
    for i, (text, color) in enumerate(resources):
        surface.blit(map_screen.font.render(text, True, color), (c.RESOURCE_HUD_START_X + (i * c.RESOURCE_HUD_SPACING), hud_y))