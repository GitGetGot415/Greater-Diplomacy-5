import pygame
import data.constants as c
from data import queries

# ==========================================
# CONTENT LIMITS
# ==========================================

DIPLOMATIC_INFO_TITLE = "Diplomatic Info"
MAX_DIPLOMACY_DISPLAY = 10 # Caps how many relations the panel lists

# --- Define the split boxes using the centralized constants ---
dip_rect = pygame.Rect(*c.PROVINCE_UI["diplomatic_box"])
mail_rect = pygame.Rect(*c.PROVINCE_UI["mail_box"])

def draw_unit_info(self, surface):
    if not self.selected_province:
        return

    owner = self.selected_province.get("owner", "Unclaimed")
    is_foreign = queries.is_foreign_playable(owner, self.player_country, self.nation_data)

    # --- Diplomatic Info (Faction & Wars) ---
    if owner not in c.UNPLAYABLE_NATIONS:
        # Diplomatic Box (Replaced Faction Box)
        pygame.draw.rect(surface, (40, 30, 40), dip_rect)
        pygame.draw.rect(surface, (150, 100, 250), dip_rect, 2)

        dip_title = self.font.render(DIPLOMATIC_INFO_TITLE, True, (255, 255, 255))
        surface.blit(dip_title, (dip_rect.x + 10, dip_rect.y + 10))
        
        faction_name = self.nation_data.get(owner, {}).get("faction", "")
        y_offset = dip_rect.y + 40
        
        if not faction_name:
            surface.blit(self.small_font.render("No Faction", True, (150, 150, 150)), (dip_rect.x + 10, y_offset))
            y_offset += 30
        else:
            surface.blit(self.small_font.render(faction_name, True, c.COLOR_SUCCESS_GREEN), (dip_rect.x + 10, y_offset))
            y_offset += 20
            
            members = queries.get_faction_members(faction_name, self.nation_data)
            for m in members[:MAX_DIPLOMACY_DISPLAY]:
                m_display = self.nation_data.get(m, {}).get("name", m)
                surface.blit(self.small_font.render(f" - {m_display}", True, (200, 200, 200)), (dip_rect.x + 10, y_offset))
                y_offset += 20
                
            if len(members) > MAX_DIPLOMACY_DISPLAY:
                surface.blit(self.small_font.render("(...and more)", True, (150, 150, 150)), (dip_rect.x + 10, y_offset))
                y_offset += 20

        # --- MAP PUPPET HIERARCHY ---
        master = self.nation_data.get(owner, {}).get("master", "")
        if master:
            m_disp = self.nation_data.get(master, {}).get("name", master)
            surface.blit(self.small_font.render(f"Master: {m_disp}", True, (255, 150, 150)), (dip_rect.x + 10, y_offset))
            y_offset += 20
            
        puppets = self.nation_data.get(owner, {}).get("puppets", [])
        if puppets:
            surface.blit(self.small_font.render("Puppets:", True, c.COLOR_GOLD_HIGHLIGHT), (dip_rect.x + 10, y_offset))
            y_offset += 20
            for p in puppets[:MAX_DIPLOMACY_DISPLAY]:
                p_disp = self.nation_data.get(p, {}).get("name", p)
                surface.blit(self.small_font.render(f" - {p_disp}", True, (200, 200, 200)), (dip_rect.x + 10, y_offset))
                y_offset += 20
            if len(puppets) > MAX_DIPLOMACY_DISPLAY:
                surface.blit(self.small_font.render("(...and more)", True, (150, 150, 150)), (dip_rect.x + 10, y_offset))
                y_offset += 20

        # Keep war info so players know who this nation is fighting
        wars = queries.get_enemies(owner, self.nation_data)
        if wars:
            surface.blit(self.small_font.render("At War With:", True, (255, 100, 100)), (dip_rect.x + 10, y_offset))
            y_offset += 20
            # Use the new constant here
            for w in wars[:MAX_DIPLOMACY_DISPLAY]:
                w_disp = self.nation_data.get(w, {}).get("name", w)
                surface.blit(self.small_font.render(f" - {w_disp}", True, (200, 200, 200)), (dip_rect.x + 10, y_offset))
                y_offset += 20

            if len(wars) > MAX_DIPLOMACY_DISPLAY:
                # Updated the fallback text
                surface.blit(self.small_font.render("(...and more)", True, (150, 150, 150)), (dip_rect.x + 10, y_offset))
                y_offset += 20