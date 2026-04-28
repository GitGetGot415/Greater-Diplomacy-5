import pygame
from map_logic.rendering.font_manager import fonts
import data.constants as c
from data import queries

# --- Define the 4 split boxes using the centralized constants ---
units_rect = pygame.Rect(*c.PROVINCE_UI["units_box"])
bldgs_rect = pygame.Rect(*c.PROVINCE_UI["buildings_box"])
fac_rect = pygame.Rect(*c.PROVINCE_UI["faction_box"])
mail_rect = pygame.Rect(*c.PROVINCE_UI["mail_box"])

def draw_unit_info(self, surface):
    if not self.selected_province:
        return

    owner = self.selected_province.get("owner", "Unclaimed")
    is_foreign = queries.is_foreign_playable(owner, self.player_country, self.nation_data)

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

    # --- 3. Foreign Info (Faction & Mail) ---
    if is_foreign:
        # Faction Box (Replaced Relations Box)
        pygame.draw.rect(surface, (40, 30, 40), fac_rect)
        pygame.draw.rect(surface, (150, 100, 250), fac_rect, 2)

        fac_title = self.font.render("Faction Info", True, (255, 255, 255))
        surface.blit(fac_title, (fac_rect.x + 10, fac_rect.y + 10))
        
        faction_name = self.nation_data.get(owner, {}).get("faction", "")
        y_offset = fac_rect.y + 40
        
        if not faction_name:
            surface.blit(self.small_font.render("No Faction", True, (150, 150, 150)), (fac_rect.x + 10, y_offset))
            y_offset += 30
        else:
            surface.blit(self.small_font.render(faction_name, True, (100, 255, 100)), (fac_rect.x + 10, y_offset))
            y_offset += 20
            
            members = queries.get_faction_members(faction_name, self.nation_data)
            for m in members[:4]:
                m_display = self.nation_data.get(m, {}).get("name", m)
                surface.blit(self.small_font.render(f" - {m_display}", True, (200, 200, 200)), (fac_rect.x + 10, y_offset))
                y_offset += 20
                
            if len(members) > 4:
                surface.blit(self.small_font.render(f" + {len(members)-4} more", True, (150, 150, 150)), (fac_rect.x + 10, y_offset))
                y_offset += 20

        # Keep war info so players know who this nation is fighting
        wars = queries.get_enemies(owner, self.nation_data)
        if wars:
            surface.blit(self.small_font.render("At War With:", True, (255, 100, 100)), (fac_rect.x + 10, y_offset))
            y_offset += 20
            for w in wars[:2]:
                w_disp = self.nation_data.get(w, {}).get("name", w)
                surface.blit(self.small_font.render(f" - {w_disp}", True, (200, 200, 200)), (fac_rect.x + 10, y_offset))
                y_offset += 20

        # Mail Box
        pygame.draw.rect(surface, (30, 40, 50), mail_rect)
        pygame.draw.rect(surface, (100, 200, 250), mail_rect, 2)

        mail_title = self.font.render("Direct Message", True, (255, 255, 255))
        surface.blit(mail_title, (mail_rect.x + 10, mail_rect.y + 10))
        
        # --- NEW: Check status cleanly ---
        action, turns = queries.get_diplomatic_status(self.player_country, owner, self.nation_data)
        locked = queries.is_diplomat_busy(self.player_country, owner, self.nation_data)

        is_unilateral = action in ["WAR_DECLARATION", "JOIN_WARS", "BREAK_ALLIANCE", "KICK_FACTION_MEMBER", "LEAVE_FACTION", "DISBAND_FACTION"]
        if is_unilateral and turns > 0:
            action = ""
            turns = 0

        status_text = "Drafting..."
        if turns > 0:
            status_text = "In Transit / Awaiting"
        elif locked:
            status_text = "Diplomat Busy"
        # ---------------------------------

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