import pygame

info_rect = pygame.Rect(1380, 70, 210, 350) # Made slightly taller
recruit_btn_rect = pygame.Rect(1390, 370, 190, 40)

def draw_unit_info(self, surface):
    if not self.selected_province:
        return

    # Draw Panel
    pygame.draw.rect(surface, (30, 30, 50), info_rect)
    pygame.draw.rect(surface, (100, 100, 250), info_rect, 2)

    title = self.font.render("Active Garrison", True, (255, 255, 255))
    surface.blit(title, (info_rect.x + 10, info_rect.y + 10))

    # ONLY list active units here
    """units = self.selected_province.get("units", [])
    if not units:
        txt = self.small_font.render("(Empty)", True, (150, 150, 150))
        surface.blit(txt, (info_rect.x + 15, info_rect.y + 45))
    else:
        for i, unit_name in enumerate(units[:10]):
            txt = self.small_font.render(f"- {unit_name}", True, (200, 200, 200))
            surface.blit(txt, (info_rect.x + 15, info_rect.y + 45 + (i * 25)))"""
    
    units = self.selected_province.get("units", [])
    if not units:
        txt = self.small_font.render("(Empty)", True, (150, 150, 150))
        surface.blit(txt, (info_rect.x + 15, info_rect.y + 45))
    else:
        for i, unit_data in enumerate(units[:10]):
            u_name = unit_data["type"]
            u_owner_id = unit_data["owner"]
            
            # Resolve the owner's Display Name
            u_owner_display = self.nation_data.get(u_owner_id, {}).get("name", u_owner_id)
            
            display_text = f"- {u_name} ({u_owner_display})"
            txt = self.small_font.render(display_text, True, (200, 200, 200))
            surface.blit(txt, (info_rect.x + 15, info_rect.y + 45 + (i * 25)))