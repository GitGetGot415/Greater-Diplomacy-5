import pygame

info_rect = pygame.Rect(10, 70, 300, 220)
# x, y, width, height = 10, 70, 300, 220

def draw_sidebar_info(self, surface):

    pygame.draw.rect(surface, (30, 30, 30, 200), info_rect)
    pygame.draw.rect(surface, (200, 200, 200), info_rect, 1)

    # Check if it's water
    water_types = ["ocean", "coastal_sea", "inland_sea", "lakes"]
    terrain = self.selected_province['terrain']
    terrain_color = (100, 200, 255) if terrain in water_types else (255, 255, 255)

    info_lines = [
        f"Province ID: {self.selected_province['id']}",
        f"Owner: {self.selected_province['owner']}",
        f"Units: {len(self.selected_province['units'])}",
        f"Terrain: {terrain.upper()}"
    ]
    
    for i, line in enumerate(info_lines):
        # Use blue text for terrain if it's water
        color = terrain_color if "Terrain" in line else (255, 255, 255)
        tsurf = self.small_font.render(line, True, color)
        surface.blit(tsurf, (20, 80 + i * 30))