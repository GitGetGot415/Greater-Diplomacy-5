import pygame
import data.constants as c
from data import queries
from map_logic.diplomacy import guarantees
from map_logic.diplomacy import military_attaches
from ui.bars import ui_bars
from ui.widgets.text_utils import fit_text
from ui.widgets.ui_elements import draw_pixel_panel

# ==========================================
# CONTENT LIMITS
# ==========================================

DIPLOMATIC_INFO_TITLE = "Diplomatic Info"

# How fast the mouse wheel scrolls the Diplomatic Info body
DIPLOMATIC_SCROLL_STEP = c.SCROLL_STEP

# --- Define the split boxes using the centralized constants ---
dip_rect = pygame.Rect(*c.PROVINCE_UI["diplomatic_box"])
mail_rect = pygame.Rect(*c.PROVINCE_UI["mail_box"])

RELATION_ROW_HEIGHT = 20
RELATION_GAP = 4
RELATION_ROW_RECTS = (
    pygame.Rect(dip_rect.x, dip_rect.y - RELATION_GAP - 2 * RELATION_ROW_HEIGHT, dip_rect.width, RELATION_ROW_HEIGHT),
    pygame.Rect(dip_rect.x, dip_rect.y - RELATION_GAP - RELATION_ROW_HEIGHT, dip_rect.width, RELATION_ROW_HEIGHT),
)
RELATION_DROPDOWN_WIDTH = 264
RELATION_PADDING = 7
RELATION_BG = (40, 30, 40)
RELATION_HOVER_BG = (63, 49, 74)
RELATION_BORDER = (150, 100, 250)
RELATION_NEGATIVE = (255, 145, 145)
RELATION_LABELS = ("Their opinion", "Your opinion")
RELATION_FACTORS = {
    "war": "At war",
    "faction": "Same faction",
    "shared_enemy": "Shared enemy",
    "political_affinity": "Political affinity",
    "political_reputation": "Political reputation",
    "overlord": "Overlord's view of subject",
    "subject": "Subject's view of overlord",
}
TEMPORARY_RELATION_FACTORS = {
    "recent_war": "Recent war",
    "recent_faction": "Recent faction departure",
    "deposed": "Deposed as faction leader",
    "removed_cores": "Removed cores",
    "general": "General opinion",
}


def _relation_factor_text(kind, detail):
    if kind == "claims":
        return f"Disputed provinces ({detail})"
    if kind == "temporary":
        name, entry = detail
        label = TEMPORARY_RELATION_FACTORS.get(name, "Other opinion modifier")
        decay, turns = queries.modifier_decay(entry), queries.modifier_turns(entry)
        timing = []
        if decay:
            timing.append(f"fades {decay}/turn")
        if turns is not None:
            timing.append(f"{turns} turns left")
        return f"{label} ({', '.join(timing)})" if timing else label
    return RELATION_FACTORS[kind]


def prepare_relation_indicators(map_screen):
    """Update directional opinions when the selection or map state changes."""
    province = map_screen.selected_province
    player = map_screen.session.player_country
    owner = province.get("owner") if province else None
    nation_data = map_screen.world.nation_data
    if (owner == player or owner not in nation_data or player not in nation_data
            or owner in c.UNPLAYABLE_NATIONS or player in c.UNPLAYABLE_NATIONS
            or map_screen.session.selection_mode):
        map_screen._relation_indicator_cache = None
        return

    key = (owner, player, map_screen._presentation_cache_revision)
    cached = map_screen._relation_indicator_cache
    if cached is not None and cached[0] == key:
        return

    their_factors, your_factors = queries.get_mutual_relation_breakdowns(
        owner, player, nation_data, map_screen.world.id_to_province)
    owner_name = queries.get_country_display_name(owner, nation_data)
    titles = (f"{owner_name}'s opinion of you", f"Your opinion of {owner_name}")
    opinions = []
    for title, factors in zip(titles, (their_factors, your_factors)):
        lines = tuple((_relation_factor_text(kind, detail), value) for kind, value, detail in factors if value)
        opinions.append((title, sum(value for _, value in lines), lines))
    map_screen._relation_indicator_cache = key, tuple(opinions)


def _relation_indicators(map_screen):
    # Some map input callers use lightweight screens without the province HUD.
    cached = getattr(map_screen, "_relation_indicator_cache", None)
    province = map_screen.selected_province
    if cached is None or not province or map_screen.session.selection_mode:
        return ()
    key = (province.get("owner"), map_screen.session.player_country, map_screen._presentation_cache_revision)
    return cached[1] if cached[0] == key else ()


def relation_indicator_at_position(map_screen, position):
    """Return the direction under the pointer, if its indicator is visible."""
    if _relation_indicators(map_screen):
        for index, rect in enumerate(RELATION_ROW_RECTS):
            if rect.collidepoint(position):
                return index
    return None


def _render_relation_value(font, value):
    color = c.COLOR_SUCCESS_GREEN if value > 0 else RELATION_NEGATIVE if value < 0 else c.UI_TEXT_LIGHT
    return font.render(f"{value:+d}" if value else "0", True, color)


def _draw_relation_breakdown(surface, font, opinion):
    title, _, lines = opinion
    line_height = font.get_linesize() + 2
    rect = pygame.Rect(dip_rect.x, RELATION_ROW_RECTS[-1].bottom, RELATION_DROPDOWN_WIDTH,
                       2 * RELATION_PADDING + (1 + max(1, len(lines))) * line_height)
    draw_pixel_panel(surface, rect, RELATION_BG, RELATION_BORDER, border_width=1)
    left, right = rect.left + RELATION_PADDING, rect.right - RELATION_PADDING
    y = rect.top + RELATION_PADDING
    surface.blit(font.render(fit_text(title, font, right - left), True, c.UI_TEXT_BRIGHT), (left, y))
    y += line_height
    if not lines:
        surface.blit(font.render("No active modifiers", True, c.UI_TEXT_LIGHT), (left, y))
    for label, value in lines:
        number = _render_relation_value(font, value)
        label = fit_text(label, font, right - left - number.get_width() - RELATION_PADDING)
        surface.blit(font.render(label, True, c.UI_TEXT_LIGHT), (left, y))
        surface.blit(number, (right - number.get_width(), y))
        y += line_height


def draw_relation_indicators(map_screen, surface):
    opinions = _relation_indicators(map_screen)
    if not opinions:
        return
    hovered = relation_indicator_at_position(map_screen, pygame.mouse.get_pos())
    font = map_screen.small_font
    for index, (rect, label, (_, score, _)) in enumerate(zip(RELATION_ROW_RECTS, RELATION_LABELS, opinions)):
        color = RELATION_HOVER_BG if index == hovered else RELATION_BG
        draw_pixel_panel(surface, rect, color, RELATION_BORDER, border_width=1)
        number = _render_relation_value(font, score)
        width = rect.width - 3 * RELATION_PADDING - number.get_width()
        caption = font.render(fit_text(label, font, width), True, c.UI_TEXT_BRIGHT)
        surface.blit(caption, caption.get_rect(midleft=(rect.left + RELATION_PADDING, rect.centery)))
        surface.blit(number, number.get_rect(midright=(rect.right - RELATION_PADDING, rect.centery)))
    if hovered is not None:
        _draw_relation_breakdown(surface, font, opinions[hovered])


def draw_unit_info(map_screen, surface):
    map_screen.diplomatic_scroll_rect = None
    if not map_screen.selected_province:
        return

    owner = map_screen.selected_province.get("owner", "Unclaimed")
    is_foreign = queries.is_foreign_playable(owner, map_screen.session.player_country, map_screen.world.nation_data)

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

        scroll_max = map_screen.diplomatic_scroll_max
        scroll_offset = max(0, min(map_screen.diplomatic_scroll_y, scroll_max))

        body_top = body_rect.y
        y_offset = body_top - scroll_offset

        with ui_bars.clip_scroll_region(surface, body_rect,
                                        draw_top=scroll_offset != 0, draw_bottom=scroll_offset < scroll_max):
            # Guarantees are the first diplomatic fact: they decide who joins
            # a new war before factions or access do.
            protected = guarantees.guaranteed_targets(owner, map_screen.world.nation_data)
            guarantors = guarantees.guarantors_of(owner, map_screen.world.nation_data)
            for label, color, nations in (
                    ("Guaranteeing:", c.COLOR_GOLD_HIGHLIGHT, protected),
                    ("Guaranteed By:", (150, 200, 255), guarantors)):
                if not nations:
                    continue
                surface.blit(map_screen.small_font.render(label, True, color),
                             (dip_rect.x + 10, y_offset))
                y_offset += 20
                for nation in nations:
                    display = map_screen.world.nation_data.get(nation, {}).get("name", nation)
                    surface.blit(map_screen.small_font.render(f" - {display}", True,
                                                              c.UI_TEXT_LIGHT),
                                 (dip_rect.x + 10, y_offset))
                    y_offset += 20

            hosts = military_attaches.hosts_for(owner, map_screen.world.nation_data)
            observers = military_attaches.attaches_from(owner, map_screen.world.nation_data)
            for label, color, nations in (
                    ("Military Attachés With:", (255, 180, 100), hosts),
                    ("Hosts Attachés From:", (255, 210, 150), observers)):
                if not nations:
                    continue
                surface.blit(map_screen.small_font.render(label, True, color),
                             (dip_rect.x + 10, y_offset))
                y_offset += 20
                for nation in nations:
                    display = map_screen.world.nation_data.get(nation, {}).get("name", nation)
                    surface.blit(map_screen.small_font.render(f" - {display}", True,
                                                              c.UI_TEXT_LIGHT),
                                 (dip_rect.x + 10, y_offset))
                    y_offset += 20

            faction_name = queries.get_country_faction(owner, map_screen.world.nation_data)

            if not faction_name:
                surface.blit(map_screen.small_font.render("No Faction", True, c.UI_TEXT_MUTED), (dip_rect.x + 10, y_offset))
                y_offset += 30
            else:
                surface.blit(map_screen.small_font.render(faction_name, True, c.COLOR_SUCCESS_GREEN), (dip_rect.x + 10, y_offset))
                y_offset += 20

                members = queries.get_faction_members(faction_name, map_screen.world.nation_data)
                for m in members:
                    m_display = map_screen.world.nation_data.get(m, {}).get("name", m)
                    surface.blit(map_screen.small_font.render(f" - {m_display}", True, c.UI_TEXT_LIGHT), (dip_rect.x + 10, y_offset))
                    y_offset += 20

            # --- MAP PUPPET HIERARCHY ---
            master = map_screen.world.nation_data.get(owner, {}).get("master", "")
            if master:
                m_disp = map_screen.world.nation_data.get(master, {}).get("name", master)
                surface.blit(map_screen.small_font.render(f"Master: {m_disp}", True, (255, 150, 150)), (dip_rect.x + 10, y_offset))
                y_offset += 20

            puppets = map_screen.world.nation_data.get(owner, {}).get("puppets", [])
            if puppets:
                surface.blit(map_screen.small_font.render("Puppets:", True, c.COLOR_GOLD_HIGHLIGHT), (dip_rect.x + 10, y_offset))
                y_offset += 20
                for p in puppets:
                    p_disp = map_screen.world.nation_data.get(p, {}).get("name", p)
                    surface.blit(map_screen.small_font.render(f" - {p_disp}", True, c.UI_TEXT_LIGHT), (dip_rect.x + 10, y_offset))
                    y_offset += 20

            # Keep war info so players know who this nation is fighting
            wars = queries.get_enemies(owner, map_screen.world.nation_data)
            if wars:
                surface.blit(map_screen.small_font.render("At War With:", True, (255, 100, 100)), (dip_rect.x + 10, y_offset))
                y_offset += 20
                for w in wars:
                    w_disp = map_screen.world.nation_data.get(w, {}).get("name", w)
                    surface.blit(map_screen.small_font.render(f" - {w_disp}", True, c.UI_TEXT_LIGHT), (dip_rect.x + 10, y_offset))
                    y_offset += 20

            # Truces don't show up anywhere else, but they're the reason a
            # recent enemy can't be attacked again yet.
            truces = queries.get_active_truces(owner, map_screen.world.nation_data)
            if truces:
                surface.blit(map_screen.small_font.render("Truce With:", True, (200, 200, 100)), (dip_rect.x + 10, y_offset))
                y_offset += 20
                for t, turns_left in truces.items():
                    t_disp = map_screen.world.nation_data.get(t, {}).get("name", t)
                    surface.blit(map_screen.small_font.render(f" - {t_disp} ({turns_left} turns)", True, c.UI_TEXT_LIGHT), (dip_rect.x + 10, y_offset))
                    y_offset += 20

            # --- MILITARY ACCESS, BOTH WAYS ---
            # Access is one-way and stored only on the granting side, so the two
            # directions are genuinely different facts and both are worth having:
            # who may walk through this nation, and whose land it may walk
            # through. Nothing listed either of them anywhere before.
            for label, color, names in (
                    ("Grants Passage To:", c.COLOR_GOLD_HIGHLIGHT,
                     queries.get_military_access_granted_by(owner, map_screen.world.nation_data)),
                    ("Has Passage Through:", (150, 200, 255),
                     queries.get_military_access_granted_to(owner, map_screen.world.nation_data))):
                if not names:
                    continue
                surface.blit(map_screen.small_font.render(label, True, color), (dip_rect.x + 10, y_offset))
                y_offset += 20
                for n in names:
                    n_disp = map_screen.world.nation_data.get(n, {}).get("name", n)
                    surface.blit(map_screen.small_font.render(f" - {n_disp}", True, c.UI_TEXT_LIGHT), (dip_rect.x + 10, y_offset))
                    y_offset += 20

        # Re-derive the scroll limit from what was actually drawn this frame.
        content_height = (y_offset + scroll_offset) - body_top
        map_screen.diplomatic_scroll_max = max(0, content_height - body_rect.height)
        map_screen.diplomatic_scroll_y = min(scroll_offset, map_screen.diplomatic_scroll_max)
