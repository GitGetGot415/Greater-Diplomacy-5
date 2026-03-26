import pygame

def draw_tooltip(self, surface):
    mx, my = pygame.mouse.get_pos()
    owner_id = self.hovered_province['owner']
    
    # Get Display Name from nation_data, fallback to ID
    owner_display = self.nation_data.get(owner_id, {}).get("name", owner_id)
    
    txt = f"ID: {self.hovered_province['id']} | {owner_display}"
    tsurf = self.small_font.render(txt, True, (255, 255, 255))
    bg_rect = tsurf.get_rect(bottomleft=(mx + 15, my - 5)).inflate(10, 6)
    
    pygame.draw.rect(surface, (30, 30, 30), bg_rect)
    pygame.draw.rect(surface, (200, 200, 200), bg_rect, 1)
    surface.blit(tsurf, (bg_rect.x + 5, bg_rect.y + 3))