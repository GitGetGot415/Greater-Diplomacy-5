import pygame
import data.constants as c
from data import queries
from map_logic import politics
from ui.rendering import overlay_renderer

UNIT_PREVIEW_LIMIT = 5


def _fuel_conversion_key(map_screen):
    session = map_screen.session
    if not (session.is_editor or session.tactical_mode or session.selection_mode):
        return session.mode, session.player_country, queries.get_viewing_country(map_screen), map_screen._presentation_cache_revision


def prepare_building_yields(map_screen):
    """Cache visible building yields and fuel conversion at hover or state changes."""
    province = map_screen.hovered_province
    visible = bool(province and map_screen.secondary_mode == "ECONOMY"
                   and queries.is_province_visible(map_screen, province["id"]))
    conversion_key = _fuel_conversion_key(map_screen) if visible else None
    stamp = (id(province), map_screen._presentation_cache_revision, map_screen.secondary_mode, visible, conversion_key)
    if map_screen._tooltip_building_stamp == stamp:
        return
    map_screen._tooltip_building_stamp = stamp
    map_screen._tooltip_building_yields = []
    map_screen._tooltip_tile_in_combat = False
    if not visible:
        return
    owner = province.get("owner", "Unclaimed")
    world = map_screen.world
    if queries.is_province_in_active_combat(province, world.nation_data):
        map_screen._tooltip_tile_in_combat = True
        map_screen._tooltip_building_yields = [(name, dict.fromkeys(c.ECON_RESOURCE_KEYS, 0)) for name in province.get("buildings", [])]
        return
    country = world.nation_data.get(owner, {})
    if conversion_key:
        cached_key, countries = getattr(map_screen, "_tooltip_fuel_conversions", (None, {}))
        if conversion_key != cached_key:
            countries = {}
            map_screen._tooltip_fuel_conversions = conversion_key, countries
        if owner not in countries:
            conversions = {}
            session = map_screen.session
            # Network projections preserve full province economy inputs for the player.
            has_source_data = not session.is_networked or owner == session.player_country == queries.get_viewing_country(map_screen)
            if has_source_data and queries.can_view_country_economy(map_screen, owner) and queries.get_fuel_conversion_rate(country) > 0:
                production = queries.ProvinceProduction(world.nation_data, map_screen)
                provinces = (tile for tile in world.map_data.values() if tile.get("owner") == owner)
                conversions = production.fuel_conversion_by_province(owner, provinces)
            countries[owner] = conversions
    research = country.get("research", {})
    library = queries.get_building_library(map_screen)
    modifiers = queries.get_building_output_modifiers(research, library, context=map_screen)
    factory_multiplier = politics.factory_output_multiplier(map_screen.world.nation_data, owner)
    non_core_multiplier = politics.axis_effect(map_screen.world.nation_data, owner, "non_core_building_output")
    for name in province.get("buildings", []):
        building_province = dict(province, buildings=[name], building_queue=[])
        output = queries.get_province_building_output(building_province, research, library,
                                                      context=map_screen, modifiers=modifiers, factory_multiplier=factory_multiplier,
                                                      non_core_multiplier=non_core_multiplier)
        map_screen._tooltip_building_yields.append((name, output))


def _province_tooltip_lines(map_screen, prov):
    # --- FOG OF WAR VISIBILITY CHECK ---
    show_details = (map_screen.secondary_mode == "ECONOMY"
                    or map_screen.base_layer != "RELATIONS" or not map_screen.selected_province)
    is_visible = show_details and queries.is_province_visible(map_screen, prov["id"])

    owner_id = prov.get('owner', 'Unclaimed')
    owner_display = map_screen.world.nation_data.get(owner_id, {}).get("name", owner_id)

    # Coastal Sea and Inland Sea display
    terrain = prov.get('terrain', 'Unknown')
    is_water = queries.is_water_province(prov)
    if is_water:
        owner_display = terrain.replace('_', ' ').title()

    # 1. Start with the basic header info based on the primary map mode
    if map_screen.base_layer == "TERRAIN":
        terrain_display = terrain.replace('_', ' ').title()
        lines = [f"ID: {prov['id']} | {terrain_display}"]
    elif map_screen.base_layer == "RELATIONS":
        lines = [f"ID: {prov['id']} | {owner_display}"]
        viewpoint = map_screen._relations_viewpoint
        score = map_screen._relations_scores.get(owner_id)
        if (score is not None and not is_water and viewpoint != owner_id
                and viewpoint in map_screen.world.nation_data and viewpoint not in c.UNPLAYABLE_NATIONS):
            name = queries.get_country_display_name(viewpoint, map_screen.world.nation_data)
            signed_score = f"{score:+d}" if score else "0"
            lines.append(f"{name}'s opinion: {signed_score}")
    else:
        lines = [f"ID: {prov['id']} | {owner_display}"]

    if map_screen.base_layer == "CORES":
        cores = prov.get("cores", [])
        if cores:
            core_names = [map_screen.world.nation_data.get(core, {}).get("name", core) for core in cores]
            lines.append(f"Cores: {', '.join(core_names)}")

    # 2. Add contextual info based on secondary view mode
    if not show_details or map_screen.secondary_mode == "BLANK":
        # With a province selected, show only the Relations score and header.
        pass

    elif map_screen.secondary_mode == "UNITS":
        # Older standalone UI fixtures may not have a unit view filter.
        view_filter = map_screen.unit_view_filter
        units = prov.get("units", [])
        if view_filter != "ALL":
            # Reuse map membership cached at state/input changes. Do not
            # classify units again in the planning-frame draw path.
            units = overlay_renderer._unit_render_index(map_screen).view_units_by_province.get(
                id(prov), ())
        # Filtered up front: a lone hidden submarine must not even trip the
        # "something is here" partial-fog hint, or its position leaks through
        # the "?" blip despite being otherwise invisible.
        visible_units = queries.filter_visible_units(
            units, map_screen.session.player_country, prov, map_screen.world.nation_data)
        if not is_visible:
            # Unknown stacks have no visible category, as on the map.
            if (view_filter == "ALL"
                    and map_screen.partial_visible_provinces is not None
                    and prov["id"] in map_screen.partial_visible_provinces and visible_units):
                lines.append("- ? (Unknown Units)")
            else:
                lines.append("(Units hidden by Fog of War)")
        else:
            units = visible_units
            if not units:
                lines.append("No Units Present" if view_filter == "ALL" else "No Units in Selected Category")
            else:
                lines.append("--- Units ---")
                # Limit the preview after applying visibility and category.
                for u in units[:UNIT_PREVIEW_LIMIT]:
                    u_name = u.get("type", "Unit")
                    level = u.get("level", 0)
                    # Single-level families omit their numeral in visible labels.
                    display_name = queries.get_unit_display_name(u_name, context=map_screen)

                    if level > 0:
                        # refactor: Use 'Type' for Infantry, 'Lvl' for others
                        base_name = queries.get_base_unit_name(u_name, context=map_screen)
                        label = "Type" if base_name == "Infantry" else "Lvl"
                        lines.append(f"- {display_name} ({label} {level})")
                    else:
                        lines.append(f"- {display_name}")

                if len(units) > UNIT_PREVIEW_LIMIT:
                    lines.append(f"...and {len(units)-UNIT_PREVIEW_LIMIT} more")

    elif map_screen.secondary_mode == "RESOURCES":
        if not is_visible:
            lines.append("(Resources hidden by Fog of War)")
        else:
            resources = prov.get("resources", {})
            if isinstance(resources, dict) and resources:
                lines.append("--- Resources ---")
                for r_type, amount in resources.items():
                    if amount > 0:
                        lines.append(f"- {r_type}: {queries.format_number(amount)}")
            else:
                lines.append("No Natural Resources")

    elif map_screen.secondary_mode == "ECONOMY":
        # Base production from the tile itself dynamically calculated
        owner_data = map_screen.world.nation_data.get(owner_id, {})
        research_data = owner_data.get("research", {})

        # Calculate dynamic bonuses based on tech
        gen_rec_lvl = research_data.get("general_recruitment", 0)
        manpower_bonus = gen_rec_lvl * c.GENERAL_RECRUITMENT_BONUS

        # Base yields including tech bonuses
        base_man = c.BASE_YIELDS['manpower'] + manpower_bonus
        base_mat = c.BASE_YIELDS['materials']
        base_fuel = c.BASE_YIELDS['fuel']

        # Apply core/non-core penalties to give the player the EXACT true yield
        is_core = queries.has_core(owner_id, prov)
        man_mult = 1.0 if is_core else c.NON_CORE_MULTIPLIERS["manpower"]
        mat_mult = 1.0 if is_core else c.NON_CORE_MULTIPLIERS["materials"]
        fuel_mult = 1.0 if is_core else c.NON_CORE_MULTIPLIERS["fuel"]

        in_combat = is_visible and map_screen._tooltip_tile_in_combat
        if in_combat:
            lines.append("No income during battle")
        else:
            actual_man = int(base_man * man_mult)
            actual_mat = int(base_mat * mat_mult)
            actual_fuel = int(base_fuel * fuel_mult)
            lines.append(f"Tile Yield: +{queries.format_number(actual_man)}Man, +{queries.format_number(actual_mat)}Mat, +{queries.format_number(actual_fuel)}Fuel")
            if not is_core and owner_id not in c.UNPLAYABLE_NATIONS:
                lines.append("  *(Non-Core Penalties Applied)*")

        if is_visible and not in_combat:
            cached_key, countries = getattr(map_screen, "_tooltip_fuel_conversions", (None, {}))
            if cached_key and cached_key == _fuel_conversion_key(map_screen):
                conversion = countries.get(owner_id, {}).get(prov["id"])
                if conversion and any(conversion.values()):
                    amounts = []
                    for resource, label in (("materials", "Materials"), ("fuel", "Fuel")):
                        if amount := conversion[resource]:
                            formatted = f"{amount:+,.2f}".rstrip("0").rstrip(".")
                            if round(amount, 2) == 0:
                                formatted = f"{amount:+.2g}"
                            amounts.append(f"{formatted} {label}")
                    lines.append(f"Fuel conversion: {', '.join(amounts)}")

        lines.append("--- Buildings ---")
        if not is_visible:
            lines.append("(Hidden by Fog of War)")
        else:
            for b, output in map_screen._tooltip_building_yields:
                p_mat = output['materials']
                p_man = output['manpower']
                p_fuel = output['fuel']

                yields = []
                if p_man > 0: yields.append(f"+{queries.format_number(p_man)}Man")
                if p_mat > 0: yields.append(f"+{queries.format_number(p_mat)}Mat")
                if p_fuel > 0: yields.append(f"+{queries.format_number(p_fuel)}Fuel")

                prod_hint = f"({', '.join(yields)})" if yields else ""
                lines.append(f"- {b} {prod_hint}")

    return lines


def draw_tooltip(map_screen, surface):
    if map_screen.hovered_province:
        lines = _province_tooltip_lines(map_screen, map_screen.hovered_province)
    elif (map_screen.base_layer == "RELATIONS" and not map_screen.session.selection_mode
          and not (map_screen.hovered_combat_bubble or map_screen.hovered_unit_stack)
          and (province := map_screen._relations_hovered_province)
          and (owner := province.get("owner")) == map_screen._relations_viewpoint):
        lines = [queries.get_country_display_name(owner, map_screen.world.nation_data)]
    else:
        return

    rendered_lines = [map_screen.small_font.render(line, True, (255, 255, 255)) for line in lines]
    draw_text_tooltip(surface, rendered_lines, pygame.mouse.get_pos())


def draw_text_tooltip(surface, rendered_lines, position):
    """Place an existing set of text surfaces beside the pointer."""
    if not rendered_lines:
        return
    mx, my = position
    width = max(ts.get_width() for ts in rendered_lines) + 20
    height = sum(ts.get_height() + 2 for ts in rendered_lines) + 14

    # Position logic (prevent going off screen)
    tx, ty = mx + 15, my - height
    if tx + width > surface.get_width():
        tx = mx - width - 5
    if ty < 0:
        ty = my + 20

    bg_rect = pygame.Rect(tx, ty, width, height).clamp(surface.get_rect())

    # Draw Background
    pygame.draw.rect(surface, (30, 30, 30, 230), bg_rect)
    pygame.draw.rect(surface, (200, 200, 200), bg_rect, 1) # Border

    # Draw Text
    curr_y = bg_rect.top + 8
    for ts in rendered_lines:
        surface.blit(ts, (bg_rect.left + 10, curr_y))
        curr_y += ts.get_height() + 2
