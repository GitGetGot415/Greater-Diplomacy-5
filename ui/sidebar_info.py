import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts
from data import queries
from ui.bars import ui_bars
from ui_elements import draw_combat_stats, draw_bombardment_stats
from ui import flag_icons
from map_logic.turn_processing import combat_rules

# Small inline flag icon used in the garrison list, matching the FLAG_SIZE aspect ratio
GARRISON_FLAG_SIZE = flag_icons.ROW_FLAG_SIZE

# How fast the mouse wheel scrolls the Buildings/Garrison area
SIDEBAR_SCROLL_STEP = c.SCROLL_STEP

# ==========================================
# LAYOUT
# ==========================================

SIDEBAR_INFO_X = 900
SIDEBAR_INFO_Y = 70
SIDEBAR_INFO_WIDTH = 370
SIDEBAR_INFO_HEIGHT = 640 # Sized to fit the terrain image and buildings list

# Define the area for the sidebar info panel utilizing constants
info_rect = pygame.Rect(SIDEBAR_INFO_X, SIDEBAR_INFO_Y, SIDEBAR_INFO_WIDTH, SIDEBAR_INFO_HEIGHT)


def draw_unit_roster(map_screen, surface, province, units, is_visible, x, y, width):
    """Draws the ACTIVE GARRISON / COMBAT ZONE unit list for `province`, top-left
    anchored at (x, y) and wrapped to `width`. `units` should already be fog-of-war
    filtered (see queries.filter_visible_units); `is_visible` is the province's own
    fog-of-war state.

    Shared by the province sidebar and the read-only Orders panel (viewing a tile
    the player holds nothing on) so the two look identical apart from where they
    sit on screen. Returns the y-coordinate immediately below the last row drawn.
    """
    text_x = x + 10
    right_edge = x + width
    current_y = y

    # 5. Combat Detection
    is_combat = queries.is_province_in_active_combat(province, map_screen.nation_data)

    # Who is actually fighting whom, read off the same rule the turn
    # resolves by. A nation can stand in the middle of a battle on military
    # access without being in it, and listing it as a side -- with its top
    # units highlighted as the ones dealing damage -- was simply untrue.
    battle = combat_rules.build_battle([units], map_screen.nation_data)

    # --- Active Garrison / Combat Zone ---
    # While a fight is active, the Combat Zone display (grouped by side) fully
    # replaces the Active Garrison list rather than both showing side by side.
    if is_combat:
        header = map_screen.font.render("--- COMBAT ZONE ---", True, (255, 50, 50))
    else:
        header = map_screen.font.render("--- ACTIVE GARRISON ---", True, (255, 255, 255))
    surface.blit(header, (text_x, current_y))
    current_y += 25

    if not is_visible:
        if getattr(map_screen, 'partial_visible_provinces', None) is not None and province["id"] in map_screen.partial_visible_provinces and units:
            txt = map_screen.small_font.render("- ? (Unknown Units)", True, c.UI_TEXT_MUTED)
            surface.blit(txt, (text_x + 5, current_y))
            current_y += 25
        else:
            txt = map_screen.small_font.render("(Hidden by Fog of War)", True, c.UI_TEXT_MUTED)
            surface.blit(txt, (text_x + 5, current_y))
            current_y += 25
    elif not units:
        txt = map_screen.small_font.render("(Empty)", True, c.UI_TEXT_MUTED)
        surface.blit(txt, (text_x + 5, current_y))
        current_y += 25
    elif is_combat:
        def draw_side(side_id, side_units, front_ids=None, reserve_count=0):
            """One nation's rows in one lane. `front_ids` are the fighters.

            The rows are handed in rather than filtered out of the tile,
            because a nation holding a slot in two lanes appears twice and
            must not list its whole army under each of them.
            """
            nonlocal current_y

            side_data = map_screen.nation_data.get(side_id, {})
            side_display = side_data.get("name", side_id)
            side_color = map_screen.nation_colors.get(side_id, (200, 200, 200))

            # Flag next to the side/category name -- individual unit rows below stay as-is
            name_x = flag_icons.draw_flag_centered(
                surface, side_id, map_screen.nation_data, text_x, current_y,
                map_screen.small_font.get_height())

            title = map_screen.small_font.render(f"{side_display}:", True, side_color)
            surface.blit(title, (name_x, current_y))

            # The split is the thing worth reading at a glance: a nation with
            # forty units and six in the front rank is not fielding forty.
            if front_ids or reserve_count:
                tally = map_screen.small_font.render(
                    f"{len(front_ids)} front / {reserve_count} reserve", True, c.UI_TEXT_MUTED)
                surface.blit(tally, (right_edge - 10 - tally.get_width(), current_y))
            current_y += 22

            # Highlighted rows are the front rank -- the units that will
            # actually trade fire -- read straight off the resolver's answer
            # rather than restated here. A side not in this fight fires
            # nothing, so nothing of theirs is highlighted however good it is.
            engaged_ids = front_ids or set()
            for u in side_units:
                u_name = queries.get_condensed_unit_name(u.get("type", "Unit"))
                unit_stats = queries.get_unit_library().get(u.get("type", ""), {})
                has_bombard = 'bombard_attack' in unit_stats
                row_height = 20 + (18 if has_bombard else 0)

                in_front = id(u) in engaged_ids
                if in_front:
                    highlight_w = right_edge - (text_x + 5) - 10
                    highlight_surf = pygame.Surface((highlight_w, row_height), pygame.SRCALPHA)
                    highlight_surf.fill((*c.COLOR_SUCCESS_GREEN, 55))
                    surface.blit(highlight_surf, (text_x + 5, current_y - 1))

                row_x = text_x + 10

                # Unit name, dimmed for anything not in the front rank
                name_color = c.UI_TEXT_LIGHT if in_front else c.UI_TEXT_MUTED
                name_surf = map_screen.small_font.render(f"- {u_name}", True, name_color)
                surface.blit(name_surf, (row_x, current_y))
                row_x += name_surf.get_width() + 4

                hp_surf = map_screen.small_font.render(
                    queries.format_health_percent(u), True, c.UI_TEXT_MUTED)
                surface.blit(hp_surf, (row_x, current_y))
                row_x += hp_surf.get_width() + 6

                # Condensed, icon-based combat stats, matching the garrison list
                dmg_mult = combat_rules.effective_damage_multiplier(u, map_screen.nation_data)
                def_mult = combat_rules.health_defense_multiplier(u)
                fort_defense = queries.get_fort_defense_bonus(
                    province, u, map_screen.nation_data, combat_active=is_combat)
                draw_combat_stats(
                    surface, map_screen.small_font, "",
                    u.get("attack", 0) * dmg_mult,
                    u.get("defense", 0) * def_mult,
                    int(u.get("health", 0)), u.get("speed", 0),
                    row_x, current_y, (200, 200, 200), labeled=False,
                    defense_bonus=fort_defense
                )

                current_y += 20

                # Bombardment stats on their own indented line, only for units that can bombard
                if has_bombard:
                    draw_bombardment_stats(
                        surface, map_screen.small_font,
                        u.get("bombard_attack", unit_stats.get('bombard_attack', 0)) * dmg_mult,
                        u.get("bombard_range", unit_stats.get('bombard_range', 0)),
                        text_x + 20, current_y, (200, 200, 200), base_text="", labeled=False
                    )
                    current_y += 18

            current_y += 10

        # Grouped by lane, because that is the unit of the fight: damage
        # never crosses between them, so listing every nation in one column
        # would show a battle that is not happening. Inside a lane the rows
        # are per nation, since a side is a coalition and each member has
        # its own share of the width.
        for lane in battle.lanes:
            heading = map_screen.small_font.render(
                f"LANE {lane.index + 1}  -  {len(lane.a.front)} v {len(lane.b.front)}"
                f"  of {lane.slots}", True, c.UI_TEXT_MUTED)
            surface.blit(heading, (text_x, current_y))
            current_y += 20

            for lane_side in (lane.a, lane.b):
                for member in lane_side.members:
                    draw_side(member.nation,
                              list(member.front) + list(member.reserve),
                              front_ids={id(u) for u in member.front},
                              reserve_count=len(member.reserve))

        # Everyone else is here by military access, by a war that is not
        # being fought on this tile, or because the enemy they came for
        # could not spare a unit for them. They are worth showing -- they
        # are in the way, and they may join -- but they are not in a lane.
        if battle.bystanders:
            header = map_screen.small_font.render("--- PRESENT, NOT ENGAGED ---", True, c.UI_TEXT_MUTED)
            surface.blit(header, (text_x, current_y))
            current_y += 22
            for side_id in battle.bystanders:
                draw_side(side_id, [u for u in units if u.get("owner") == side_id])
    else:
        for u in units:
            u_name = queries.get_condensed_unit_name(u.get("type", "Unit"))
            u_owner_id = u.get("owner", "Unknown")

            row_x = text_x + 5

            # Unit name
            name_surf = map_screen.small_font.render(f"- {u_name}", True, c.UI_TEXT_LIGHT)
            surface.blit(name_surf, (row_x, current_y))
            row_x += name_surf.get_width() + 4

            hp_surf = map_screen.small_font.render(
                queries.format_health_percent(u), True, c.UI_TEXT_MUTED)
            surface.blit(hp_surf, (row_x, current_y))
            row_x += hp_surf.get_width() + 4

            # Owner flag instead of a country name string
            row_x = flag_icons.draw_flag_centered(
                surface, u_owner_id, map_screen.nation_data, row_x, current_y,
                name_surf.get_height())

            # Condensed, icon-based combat stats, matching the production tab's style
            dmg_mult = combat_rules.effective_damage_multiplier(u, map_screen.nation_data)
            draw_combat_stats(
                surface, map_screen.small_font, "",
                u.get("attack", 0) * dmg_mult, u.get("defense", 0), int(u.get("health", 0)), u.get("speed", 0),
                row_x, current_y, (200, 200, 200), labeled=False
            )

            current_y += 20

            # Bombardment stats on their own indented line, only for units that can bombard
            unit_stats = queries.get_unit_library().get(u.get("type", ""), {})
            if 'bombard_attack' in unit_stats:
                draw_bombardment_stats(
                    surface, map_screen.small_font,
                    u.get("bombard_attack", unit_stats.get('bombard_attack', 0)) * dmg_mult,
                    u.get("bombard_range", unit_stats.get('bombard_range', 0)),
                    text_x + 15, current_y, (200, 200, 200), base_text="", labeled=False
                )
                current_y += 18

    return current_y


def draw_sidebar_info(map_screen, surface):
    """
    Draws the left-hand sidebar containing province information
    and active combat data.
    """
    # 1. Draw the Panel Background and Border
    ui_bars.draw_translucent_panel(surface, info_rect, (30, 30, 30, 200),
                                   border_color=c.UI_TEXT_LIGHT, border_width=1)

    # 2. Extract Province Data
    province = map_screen.selected_province
    if not province:
        map_screen.sidebar_scroll_rect = None
        return

    # --- FOG OF WAR VISIBILITY CHECK ---
    is_visible = queries.is_province_visible(map_screen, province["id"])

    owner_id = province.get("owner", "Unclaimed")
    terrain = province.get("terrain", "Unknown")
    # Submarines we're not allied with and aren't currently fighting stay off
    # this list entirely -- same rule the map icons and tooltip follow.
    units = queries.filter_visible_units(
        province.get("units", []), map_screen.player_country, province, map_screen.nation_data)

    # 3. Resolve Display Name for the Owner
    owner_data = map_screen.nation_data.get(owner_id, {})
    owner_display = owner_data.get("name", owner_id).upper()

    # --- Terrain Image Loading ---
    terrain_filename = f"{terrain.title()}.png"

    try:
        terrain_img = ui_bars.get_ui_image(terrain_filename, directory=c.TERRAINS_DIR)
    except FileNotFoundError:
        terrain_img = ui_bars.get_ui_image("Unknown.png", directory=c.TERRAINS_DIR)

    # Scale to fit the sidebar width with a small padding
    img_width = SIDEBAR_INFO_WIDTH - 20
    img_height = img_width / 3
    terrain_img = pygame.transform.scale(terrain_img, (img_width, img_height))

    img_x = info_rect.x + 10
    img_y = info_rect.y + 10

    surface.blit(terrain_img, (img_x, img_y))
    pygame.draw.rect(surface, (100, 100, 100), (img_x, img_y, img_width,  img_height), 2)

    # 4. Render Basic Information Lines
    info_lines = [
        f"Province ID: {province['id']}",
        f"Owner: {owner_display}",
        f"Terrain: {terrain.replace('_', ' ').upper()}"
    ]

    current_y = img_y + img_height + 10
    text_x = SIDEBAR_INFO_X + 10

    for i, line in enumerate(info_lines):
        tsurf = map_screen.small_font.render(line, True, (255, 255, 255))
        surface.blit(tsurf, (text_x, current_y))
        current_y += 25

    current_y += 10 # Padding

    # --- SCROLLABLE REGION (Buildings + Garrison/Combat Zone) ---
    # Everything below this point can run arbitrarily long (building lists,
    # garrisons, combat rosters), so it's clipped to the remaining panel space
    # and scrolled with the mouse wheel instead of being truncated with a
    # "+N more" line.
    scroll_rect = pygame.Rect(info_rect.x, current_y, info_rect.width, info_rect.bottom - current_y)
    map_screen.sidebar_scroll_rect = scroll_rect

    scroll_max = getattr(map_screen, 'sidebar_scroll_max', 0)
    scroll_offset = max(0, min(getattr(map_screen, 'sidebar_scroll_y', 0), scroll_max))

    scroll_top = current_y
    current_y -= scroll_offset

    with ui_bars.clip_scroll_region(surface, scroll_rect,
                                    draw_top=scroll_offset != 0, draw_bottom=scroll_offset < scroll_max):

        # Buildings Section
        header = map_screen.font.render("--- BUILDINGS ---", True, (255, 255, 255))
        surface.blit(header, (text_x, current_y))
        current_y += 25

        if not is_visible:
            txt = map_screen.small_font.render("(Hidden by Fog of War)", True, c.UI_TEXT_MUTED)
            surface.blit(txt, (text_x + 5, current_y))
            current_y += 25
        else:
            buildings = province.get("buildings", [])
            if not buildings:
                txt = map_screen.small_font.render("(None)", True, c.UI_TEXT_MUTED)
                surface.blit(txt, (text_x + 5, current_y))
                current_y += 25
            else:
                for b in buildings:
                    txt = map_screen.small_font.render(f"- {b}", True, c.UI_TEXT_LIGHT)
                    surface.blit(txt, (text_x + 5, current_y))
                    current_y += 20

        current_y += 10 # Padding before next section

        current_y = draw_unit_roster(map_screen, surface, province, units, is_visible,
                                     info_rect.x, current_y, info_rect.width)


    # Re-derive the scroll limit from what was actually drawn this frame, and
    # settle on the offset so a shrinking list (units dying, etc.) doesn't
    # leave the view stuck scrolled past the new bottom.
    content_height = (current_y + scroll_offset) - scroll_top
    map_screen.sidebar_scroll_max = max(0, content_height - scroll_rect.height)
    map_screen.sidebar_scroll_y = min(scroll_offset, map_screen.sidebar_scroll_max)

# --- MODIFIED FUNCTION FOR PORTRAIT ---
def draw_owner_portrait(map_screen, surface):
    """
    Draws the portrait, name, and title of the selected province's owner in the top left.
    Dynamically scales the image slightly larger if the leader title is empty.
    """
    province = map_screen.selected_province
    if not province: return

    owner_id = province.get("owner", "Unclaimed")
    if owner_id in c.UNPLAYABLE_NATIONS: return

    owner_data = map_screen.nation_data.get(owner_id, {})
    leader_name = owner_data.get("leader_name", "Unknown Leader")
    leader_title = owner_data.get("leader_title", "Unknown Title").strip()
    portrait_str = owner_data.get("portrait_data", "DEFAULT")

    # Position safely beside the Left UI Bar and below the Top UI Bar
    start_x = c.UI_LEFT_OFFSET + 20
    start_y = 80

    # Determine the size
    has_title = bool(leader_title)
    has_name = bool(leader_name)
    portrait_dim = 160 if has_title or has_name else 200

    # Draw Portrait
    portrait_surf = queries.decode_b64_to_surf(portrait_str, c.PORTRAIT_SIZE, is_portrait=True, country_name=owner_id)
    portrait_surf = pygame.transform.scale(portrait_surf, (portrait_dim, portrait_dim)) # Scale dynamically
    surface.blit(portrait_surf, (start_x, start_y))
    pygame.draw.rect(surface, (200, 200, 200), (start_x, start_y, portrait_dim, portrait_dim), 2)

    # Shift the text downwards cleanly based on whichever dimension we just used
    text_x = start_x
    text_y = start_y + portrait_dim - 5

    # Blit Name and Title using the unified shadow helper
    fonts.draw_text_with_shadow(surface, leader_name, text_x, text_y + 10, "heading2")
    if has_title:
        fonts.draw_text_with_shadow(surface, leader_title, text_x, text_y + 40, "normal", text_color=(200, 200, 200))
