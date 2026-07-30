import pygame
import data.constants as c
from data import queries

# ==========================================
# CONTENT LIMITS
# ==========================================

DIPLOMATIC_INFO_TITLE = "Diplomatic Info"

# How fast the mouse wheel scrolls the Diplomatic Info body
DIPLOMATIC_SCROLL_STEP = 30

# --- Define the split boxes using the centralized constants ---
dip_rect = pygame.Rect(*c.PROVINCE_UI["diplomatic_box"])
mail_rect = pygame.Rect(*c.PROVINCE_UI["mail_box"])

def draw_unit_info(self, surface):
    self.diplomatic_scroll_rect = None
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

        # --- SCROLLABLE BODY ---
        # Faction rosters, puppet lists and war lists can all run long, so the
        # body below the title is clipped and scrolled with the mouse wheel
        # instead of being truncated with an "(...and more)" line.
        body_rect = pygame.Rect(dip_rect.x, dip_rect.y + 40, dip_rect.width, dip_rect.bottom - (dip_rect.y + 40))
        self.diplomatic_scroll_rect = body_rect

        scroll_max = getattr(self, 'diplomatic_scroll_max', 0)
        scroll_offset = max(0, min(getattr(self, 'diplomatic_scroll_y', 0), scroll_max))

        body_top = body_rect.y
        y_offset = body_top - scroll_offset

        surface.set_clip(body_rect)

        faction_name = self.nation_data.get(owner, {}).get("faction", "")

        if not faction_name:
            surface.blit(self.small_font.render("No Faction", True, (150, 150, 150)), (dip_rect.x + 10, y_offset))
            y_offset += 30
        else:
            surface.blit(self.small_font.render(faction_name, True, c.COLOR_SUCCESS_GREEN), (dip_rect.x + 10, y_offset))
            y_offset += 20

            members = queries.get_faction_members(faction_name, self.nation_data)
            for m in members:
                m_display = self.nation_data.get(m, {}).get("name", m)
                surface.blit(self.small_font.render(f" - {m_display}", True, (200, 200, 200)), (dip_rect.x + 10, y_offset))
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
            for p in puppets:
                p_disp = self.nation_data.get(p, {}).get("name", p)
                surface.blit(self.small_font.render(f" - {p_disp}", True, (200, 200, 200)), (dip_rect.x + 10, y_offset))
                y_offset += 20

        # Keep war info so players know who this nation is fighting
        wars = queries.get_enemies(owner, self.nation_data)
        if wars:
            surface.blit(self.small_font.render("At War With:", True, (255, 100, 100)), (dip_rect.x + 10, y_offset))
            y_offset += 20
            for w in wars:
                w_disp = self.nation_data.get(w, {}).get("name", w)
                surface.blit(self.small_font.render(f" - {w_disp}", True, (200, 200, 200)), (dip_rect.x + 10, y_offset))
                y_offset += 20

        surface.set_clip(None)

        # Re-derive the scroll limit from what was actually drawn this frame.
        content_height = (y_offset + scroll_offset) - body_top
        self.diplomatic_scroll_max = max(0, content_height - body_rect.height)
        self.diplomatic_scroll_y = min(scroll_offset, self.diplomatic_scroll_max)
