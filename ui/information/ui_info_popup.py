import pygame
import data.constants as c
from data import queries
from ui.bars import ui_bars

# ==========================================
# CONTENT LIMITS
# ==========================================

DIPLOMATIC_INFO_TITLE = "Diplomatic Info"

# How fast the mouse wheel scrolls the Diplomatic Info body
DIPLOMATIC_SCROLL_STEP = c.SCROLL_STEP

# --- Define the split boxes using the centralized constants ---
dip_rect = pygame.Rect(*c.PROVINCE_UI["diplomatic_box"])
mail_rect = pygame.Rect(*c.PROVINCE_UI["mail_box"])

def draw_unit_info(map_screen, surface):
    map_screen.diplomatic_scroll_rect = None
    if not map_screen.selected_province:
        return

    owner = map_screen.selected_province.get("owner", "Unclaimed")
    is_foreign = queries.is_foreign_playable(owner, map_screen.player_country, map_screen.nation_data)

    # --- Diplomatic Info (Faction & Wars) ---
    if owner not in c.UNPLAYABLE_NATIONS:
        # Diplomatic Box (Replaced Faction Box)
        pygame.draw.rect(surface, (40, 30, 40), dip_rect)
        pygame.draw.rect(surface, (150, 100, 250), dip_rect, 2)

        dip_title = map_screen.font.render(DIPLOMATIC_INFO_TITLE, True, (255, 255, 255))
        surface.blit(dip_title, (dip_rect.x + 10, dip_rect.y + 10))

        # --- SCROLLABLE BODY ---
        # Faction rosters, puppet lists and war lists can all run long, so the
        # body below the title is clipped and scrolled with the mouse wheel
        # instead of being truncated with an "(...and more)" line.
        body_rect = pygame.Rect(dip_rect.x, dip_rect.y + 40, dip_rect.width, dip_rect.bottom - (dip_rect.y + 40))
        map_screen.diplomatic_scroll_rect = body_rect

        scroll_max = getattr(map_screen, 'diplomatic_scroll_max', 0)
        scroll_offset = max(0, min(getattr(map_screen, 'diplomatic_scroll_y', 0), scroll_max))

        body_top = body_rect.y
        y_offset = body_top - scroll_offset

        with ui_bars.clip_scroll_region(surface, body_rect,
                                        draw_top=scroll_offset != 0, draw_bottom=scroll_offset < scroll_max):
            faction_name = map_screen.nation_data.get(owner, {}).get("faction", "")

            if not faction_name:
                surface.blit(map_screen.small_font.render("No Faction", True, c.UI_TEXT_MUTED), (dip_rect.x + 10, y_offset))
                y_offset += 30
            else:
                surface.blit(map_screen.small_font.render(faction_name, True, c.COLOR_SUCCESS_GREEN), (dip_rect.x + 10, y_offset))
                y_offset += 20

                members = queries.get_faction_members(faction_name, map_screen.nation_data)
                for m in members:
                    m_display = map_screen.nation_data.get(m, {}).get("name", m)
                    surface.blit(map_screen.small_font.render(f" - {m_display}", True, c.UI_TEXT_LIGHT), (dip_rect.x + 10, y_offset))
                    y_offset += 20

            # --- MAP PUPPET HIERARCHY ---
            master = map_screen.nation_data.get(owner, {}).get("master", "")
            if master:
                m_disp = map_screen.nation_data.get(master, {}).get("name", master)
                surface.blit(map_screen.small_font.render(f"Master: {m_disp}", True, (255, 150, 150)), (dip_rect.x + 10, y_offset))
                y_offset += 20

            puppets = map_screen.nation_data.get(owner, {}).get("puppets", [])
            if puppets:
                surface.blit(map_screen.small_font.render("Puppets:", True, c.COLOR_GOLD_HIGHLIGHT), (dip_rect.x + 10, y_offset))
                y_offset += 20
                for p in puppets:
                    p_disp = map_screen.nation_data.get(p, {}).get("name", p)
                    surface.blit(map_screen.small_font.render(f" - {p_disp}", True, c.UI_TEXT_LIGHT), (dip_rect.x + 10, y_offset))
                    y_offset += 20

            # Keep war info so players know who this nation is fighting
            wars = queries.get_enemies(owner, map_screen.nation_data)
            if wars:
                surface.blit(map_screen.small_font.render("At War With:", True, (255, 100, 100)), (dip_rect.x + 10, y_offset))
                y_offset += 20
                for w in wars:
                    w_disp = map_screen.nation_data.get(w, {}).get("name", w)
                    surface.blit(map_screen.small_font.render(f" - {w_disp}", True, c.UI_TEXT_LIGHT), (dip_rect.x + 10, y_offset))
                    y_offset += 20

            # Truces don't show up anywhere else, but they're the reason a
            # recent enemy can't be attacked again yet.
            truces = queries.get_active_truces(owner, map_screen.nation_data)
            if truces:
                surface.blit(map_screen.small_font.render("Truce With:", True, (200, 200, 100)), (dip_rect.x + 10, y_offset))
                y_offset += 20
                for t, turns_left in truces.items():
                    t_disp = map_screen.nation_data.get(t, {}).get("name", t)
                    surface.blit(map_screen.small_font.render(f" - {t_disp} ({turns_left} turns)", True, c.UI_TEXT_LIGHT), (dip_rect.x + 10, y_offset))
                    y_offset += 20

            # --- MILITARY ACCESS, BOTH WAYS ---
            # Access is one-way and stored only on the granting side, so the two
            # directions are genuinely different facts and both are worth having:
            # who may walk through this nation, and whose land it may walk
            # through. Nothing listed either of them anywhere before.
            for label, colour, names in (
                    ("Grants Passage To:", c.COLOR_GOLD_HIGHLIGHT,
                     queries.get_military_access_granted_by(owner, map_screen.nation_data)),
                    ("Has Passage Through:", (150, 200, 255),
                     queries.get_military_access_granted_to(owner, map_screen.nation_data))):
                if not names:
                    continue
                surface.blit(map_screen.small_font.render(label, True, colour), (dip_rect.x + 10, y_offset))
                y_offset += 20
                for n in names:
                    n_disp = map_screen.nation_data.get(n, {}).get("name", n)
                    surface.blit(map_screen.small_font.render(f" - {n_disp}", True, c.UI_TEXT_LIGHT), (dip_rect.x + 10, y_offset))
                    y_offset += 20

        # Re-derive the scroll limit from what was actually drawn this frame.
        content_height = (y_offset + scroll_offset) - body_top
        map_screen.diplomatic_scroll_max = max(0, content_height - body_rect.height)
        map_screen.diplomatic_scroll_y = min(scroll_offset, map_screen.diplomatic_scroll_max)
