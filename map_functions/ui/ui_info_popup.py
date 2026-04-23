import pygame
from map_functions.rendering.font_manager import fonts

# --- Define the 4 split boxes ---
units_rect = pygame.Rect(860, 70, 210, 350)
bldgs_rect = pygame.Rect(860, 440, 210, 350)
rel_rect = pygame.Rect(1180, 200, 210, 200)
mail_rect = pygame.Rect(1180, 420, 210, 300)

def draw_unit_info(self, surface):
    if not self.selected_province:
        return

    owner = self.selected_province.get("owner", "Unclaimed")
    is_foreign = owner != self.player_country and owner in self.nation_data and self.nation_data[owner].get("is_playable")

    # --- 1. Units Box ---
    pygame.draw.rect(surface, (30, 30, 50), units_rect)
    pygame.draw.rect(surface, (100, 100, 250), units_rect, 2)

    title = self.font.render("Active Garrison", True, (255, 255, 255))
    surface.blit(title, (units_rect.x + 10, units_rect.y + 10))

    units = self.selected_province.get("units", [])
    y_offset = units_rect.y + 40
    
    if not units:
        txt = self.small_font.render("(Empty)", True, (150, 150, 150))
        surface.blit(txt, (units_rect.x + 15, y_offset))
    else:
        for i, unit_data in enumerate(units[:12]):
            u_name = unit_data["type"]
            u_owner_id = unit_data["owner"]
            u_owner_display = self.nation_data.get(u_owner_id, {}).get("name", u_owner_id)
            display_text = f"- {u_name} ({u_owner_display})"
            txt = self.small_font.render(display_text, True, (200, 200, 200))
            surface.blit(txt, (units_rect.x + 15, y_offset))
            y_offset += 25

    # --- 2. Buildings Box ---
    pygame.draw.rect(surface, (30, 30, 50), bldgs_rect)
    pygame.draw.rect(surface, (100, 100, 250), bldgs_rect, 2)
    
    b_title = self.font.render("Buildings", True, (255, 255, 255))
    surface.blit(b_title, (bldgs_rect.x + 10, bldgs_rect.y + 10))
    y_offset = bldgs_rect.y + 40
    
    buildings = self.selected_province.get("buildings", [])
    if not buildings:
        txt = self.small_font.render("(None)", True, (150, 150, 150))
        surface.blit(txt, (bldgs_rect.x + 15, y_offset))
    else:
        for b in buildings[:12]:
            txt = self.small_font.render(f"- {b}", True, (200, 200, 200))
            surface.blit(txt, (bldgs_rect.x + 15, y_offset))
            y_offset += 25

    # --- 3. Foreign Info (Relations & Mail) ---
    if is_foreign:
        # Relations Box
        pygame.draw.rect(surface, (40, 30, 30), rel_rect)
        pygame.draw.rect(surface, (250, 100, 100), rel_rect, 2)

        rel_title = self.font.render("Relations", True, (255, 255, 255))
        surface.blit(rel_title, (rel_rect.x + 10, rel_rect.y + 10))
        
        target_data = self.nation_data.get(owner, {})
        wars = target_data.get("at_war_with", [])
        allies = target_data.get("allied_with", [])
        
        y_offset = rel_rect.y + 40
        surface.blit(self.small_font.render("At War With:", True, (255, 100, 100)), (rel_rect.x + 10, y_offset))
        y_offset += 20
        if not wars:
            surface.blit(self.small_font.render(" None", True, (150, 150, 150)), (rel_rect.x + 10, y_offset))
            y_offset += 20
        else:
            for w in wars[:3]:
                display_name = self.nation_data.get(w, {}).get("name", w)
                surface.blit(self.small_font.render(f" - {display_name}", True, (200, 200, 200)), (rel_rect.x + 10, y_offset))
                y_offset += 20

        y_offset += 10
        surface.blit(self.small_font.render("Allied With:", True, (100, 255, 100)), (rel_rect.x + 10, y_offset))
        y_offset += 20
        if not allies:
            surface.blit(self.small_font.render(" None", True, (150, 150, 150)), (rel_rect.x + 10, y_offset))
        else:
            for a in allies[:3]:
                display_name = self.nation_data.get(a, {}).get("name", a)
                surface.blit(self.small_font.render(f" - {display_name}", True, (200, 200, 200)), (rel_rect.x + 10, y_offset))

        # Mail Box
        pygame.draw.rect(surface, (30, 40, 50), mail_rect)
        pygame.draw.rect(surface, (100, 200, 250), mail_rect, 2)

        mail_title = self.font.render("Direct Message", True, (255, 255, 255))
        surface.blit(mail_title, (mail_rect.x + 10, mail_rect.y + 10))
        
        # Check status
        pending = self.nation_data.get(self.player_country, {}).get("pending_diplomacy", {}).get(owner, {})
        action = pending.get("action", "") if isinstance(pending, dict) else pending
        turns = pending.get("turns", 0) if isinstance(pending, dict) else 0

        status_text = "Drafting..."
        locked = False
        if turns > 0:
            status_text = "In Transit / Awaiting"
            locked = True
        elif isinstance(action, str) and action and not action.startswith("MSG:"):
            status_text = "Diplomat Busy"
            locked = True

        status_surf = self.small_font.render(status_text, True, (200, 255, 200) if not locked else (255, 200, 100))
        surface.blit(status_surf, (mail_rect.x + 10, mail_rect.y + 40))

        # Text input area
        input_bg = pygame.Rect(mail_rect.x + 10, mail_rect.y + 70, mail_rect.width - 20, 150)
        input_color = (60, 60, 80) if getattr(self, "mail_input_active", False) else (20, 20, 30)
        pygame.draw.rect(surface, input_color, input_bg)
        pygame.draw.rect(surface, (150, 150, 150), input_bg, 1)

        # Word wrap text
        draft_text = getattr(self, "mail_draft_text", "")
        if getattr(self, "mail_input_active", False): draft_text += "|"
        
        words = draft_text.split(" ")
        lines = []
        current_line = ""
        for word in words:
            test_line = current_line + word + " "
            if self.small_font.size(test_line)[0] < input_bg.width - 10:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word + " "
        lines.append(current_line)

        ly = input_bg.y + 5
        for l in lines:
            surface.blit(self.small_font.render(l, True, (255, 255, 255)), (input_bg.x + 5, ly))
            ly += 20

        # Instructions
        if not locked:
            instr = self.small_font.render("Click to edit. Enter to save.", True, (150, 150, 150))
            surface.blit(instr, (mail_rect.x + 10, mail_rect.y + 230))