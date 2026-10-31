import pygame
import data.constants as c
from ui.navigation.game_state import GameState
from ui.bars import ui_bars
from ui.background_styles import PRODUCTION_PANEL_STYLES
from ui.widgets import ui_elements
from ui.widgets.ui_elements import (
    Button,
    draw_resource_string,
    draw_combat_stats,
    draw_bombardment_stats,
    draw_time_stat,
    draw_stat_separator,
    make_back_button,
)
from screens.game import recruit_ui
from ui.rendering.font_manager import fonts
from data import queries
from ui.dialogs import pickers
from map_logic.actions import production_actions
from map_logic.diplomacy import restrictions
from ui.bars import resource_hud, view_mode_buttons
from screens.game import map_input
from ui.dialogs.checkbox_list_screen import CheckboxItem, SectionHeader


# ==========================================
# LAYOUT
# ==========================================


# Scrolling list of buttons + their stat bars
LIST_X = 50
ROW_STEP_Y = 40
SECTION_SPACING = 60

BAR_OFFSET_X = 140
BAR_WIDTH = 570
BAR_HEIGHT = 30
BAR_TEXT_PAD_X = 15
AIR_DAMAGE_LABEL_GAP = 8

# Infantry/Artillery rows: variant mode toggles ("Mot"/"Mec"/"IFV", or
# Artillery's single "Hvy") sit where the button normally starts, pushing the
# button (and its stat bar, which shrinks to keep its right edge fixed) right
# by this much. Only those rows are affected - every other row keeps its
# normal x position.
INFANTRY_MODE_BTN_GAP = 4
INFANTRY_MODE_TO_MAIN_GAP = 8
INFANTRY_MODE_COUNT = 3


def variant_block_width(count):
    """Width of `count` variant-toggle squares plus the gap to the main button."""
    return 30 * count + INFANTRY_MODE_BTN_GAP * (count - 1) + INFANTRY_MODE_TO_MAIN_GAP


INFANTRY_MODE_BLOCK_WIDTH = variant_block_width(INFANTRY_MODE_COUNT)

# Heavy Artillery rides Artillery's own research (see
# c.UNIT_TECH_KEY_OVERRIDES) rather than a separate gate tech, so unlike
# the Infantry variants it's always available once the row itself
# is being drawn at all - there's nothing separate to grey it out for.
ARTILLERY_VARIANTS = (
    ("heavy", "Heavy Artillery", "Hvy", True),
)


def _no_action():
    """The callback of a list button that is shown but cannot be used."""


def resolve_variant(mode, variants):
    """Validates a stored mode against current research, returning the
    (possibly corrected) mode and its unit-name prefix swap target."""
    for key, prefix, _label, available in variants:
        if mode == key:
            return (key, prefix) if available else ("normal", None)
    return "normal", None

# Colored section panels drawn behind each group of rows
PANEL_X = 30
PANEL_WIDTH = 750
PANEL_PAD_TOP = 15
PANEL_LABEL_X = 40
PANEL_LABEL_OFFSET_Y = -45

# Fixed chrome (drawn over the scrolling content)
HEADER_HEIGHT = 80
HEADER_TITLE_POS = (150, 25)
SCROLL_BOTTOM_PAD = 150
# Keep the first category's title fully below the fixed header at zero scroll.
LIST_START_Y = HEADER_HEIGHT - PANEL_LABEL_OFFSET_Y + PANEL_PAD_TOP

# Clicks only register between the header band and the resource bar, so a
# button that has scrolled behind either one stays visible but inert.
CLICK_GUARD_TOP = HEADER_HEIGHT
CLICK_GUARD_BOTTOM = c.SCREEN_HEIGHT - resource_hud.BAR_HEIGHT

# Scroll feel
SCROLL_WHEEL_STEP = 50
SCROLL_LERP = 0.15

# --- Section panels: (attr prefix, label, border, text color) ---
# Each entry paints one colored block behind its rows. Adding a section means
# adding a row here plus the matching self.<prefix>_start_y / _end_y markers.
SECTION_PANELS = [
    ("admin",    "ADMINISTRATION",     (150, 100, 200), (200, 150, 255)),
    ("other",    "GENERAL BUILDINGS",  (200, 100, 30),  (255, 150, 50)),
    ("infantry", "INFANTRY",           (50, 150, 50),   c.COLOR_SUCCESS_GREEN),
    ("tank",     "TANKS",              (40, 120, 40),   (80, 200, 80)),
    ("navy",     "NAVAL FORCES",       (50, 50, 150),   (100, 150, 255)),
    ("air",      "AIR",                (200, 50, 50),   (255, 100, 100)),
    ("custom",   "CUSTOM",             (200, 180, 50),  (255, 220, 100)),
]

BAR_BORDER_COLOR = (100, 100, 100)
BAR_YIELD_COLOR = (150, 255, 150)
BAR_STAT_COLOR = (200, 200, 200)

class Production_Screen(GameState):
    back_state = "MAP"

    def __init__(self):
        super().__init__()
        self.bg_color = (25, 25, 25)
        self.target_province = None
        self.map_screen = None
        self.btn_back = None
        self.cancel_hitboxes = []
        
        self.unit_library = queries.get_unit_library(self.map_screen)
        self.building_library = queries.get_building_library(self.map_screen)
        self.tech_tree = queries.get_tech_tree(self.map_screen)
        
        # Use the centralized query
        (self.infantry_groups, self.tank_groups, self.navy_groups,
         self.air_groups) = queries.get_ordered_unit_groups(self.unit_library, context=self.map_screen)
        self.active_bars = []
        self.air_damage_labels = {}

        # Scroll variables
        self.scroll_y = 0
        self.target_scroll_y = 0
        self.max_scroll = 0

        # Which variant the single combined Infantry row currently builds -
        # "normal", "motorized", or "mechanized". Purely a UI selection, not
        # game state, so it isn't persisted - see start_with_province.
        self.infantry_mode = "normal"

        # Each custom infantry stage has its own vehicle toggle.
        # custom_production_units stores the regular infantry stage name.
        self.custom_infantry_modes = {}

        # Mirrors infantry_mode/custom_infantry_modes above, but for the single
        # Artillery/Heavy Artillery toggle - "normal" or "heavy".
        self.artillery_mode = "normal"
        self.custom_artillery_modes = {}

    def can_edit_realtime(self):
        return queries.require_realtime_turn_open(self.map_screen, "production")

    def _mark_draft_changed(self):
        """Invalidate presentation and queue one real-time draft sync per edit."""
        self.map_screen.invalidate_map_presentation_cache()

    def exit_screen(self):
        if c.MAP_NAVIGATION_MODE == "CLASSIC":
            # Classic: Back lands on the plain province menu, tile still
            # selected. (The view-mode row only ever switches the map overlay
            # in Classic -- see navigate_view_mode -- so this is the only path
            # that leaves Production at all.)
            super().exit_screen()
            return

        # Preemptive: Back means leaving this province's screens entirely --
        # land on the bare map, not back on its province menu. (Resources/Blank
        # in the view-mode row go through navigate_view_mode instead, which
        # keeps the tile selected -- that's the "regular province menu" path.)
        if self.map_screen:
            self.map_screen.deselect_province()
        super().exit_screen()

    def handle_events(self, events):
        # Override to block all interaction
        if self.map_screen.tactical_mode:
            for event in events:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.btn_back and self.btn_back.rect.collidepoint(event.pos):
                        self.exit_screen() # Allow back button explicitly
                    else:
                        self.map_screen.show_feedback("Tactical Mode: Cannot interact with national production.")
            return

        super().handle_events(events)

    def handle_orders_key(self):
        """Q. Same as clicking the Units button in the view-mode row; also
        jumps screens when the Keybinds screen's per-key toggle is on -- see
        screens.game.map_input.handle_view_mode_keybind."""
        if self.map_screen.tactical_mode:
            return
        map_input.handle_view_mode_keybind(self.map_screen, "UNITS", "ORDERS", origin=self)

    def handle_economy_key(self):
        """W. Same as clicking the Economy button in the view-mode row; also
        jumps screens when the Keybinds screen's per-key toggle is on -- see
        screens.game.map_input.handle_view_mode_keybind."""
        if self.map_screen.tactical_mode:
            return
        map_input.handle_view_mode_keybind(self.map_screen, "ECONOMY", "ECONOMY", origin=self)

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        self.scroll_y = 0
        self.target_scroll_y = 0
        self.infantry_mode = "normal"
        self.custom_infantry_modes = {}
        self.artillery_mode = "normal"
        self.custom_artillery_modes = {}
        self.refresh_ui()

    def enforce_scroll_bounds(self):
        self.target_scroll_y = max(self.max_scroll, min(self.target_scroll_y, 0))
        self.scroll_y = max(self.max_scroll, min(self.scroll_y, 0))

    def update(self):
        super().update()
        self.enforce_scroll_bounds()
        if abs(self.scroll_y - self.target_scroll_y) > 0.5:
            self.scroll_y += (self.target_scroll_y - self.scroll_y) * SCROLL_LERP

        # Keep scrollable buttons pinned to the list. They stay visible (the
        # ProductionChromeOverlay draws over them once they slide behind the
        # header/resource-HUD bars) but a click only registers while the click
        # itself lands clear of those bars, so a still-visible sliver of a
        # button stays clickable and no sfx sneaks through on the hidden part.
        for el in self.elements:
            if getattr(el, 'is_scrollable', False):
                el.rect.y = el.base_y + int(self.scroll_y)
                el.click_guard = lambda: CLICK_GUARD_TOP <= pygame.mouse.get_pos()[1] <= CLICK_GUARD_BOTTOM

    def _add_scroll_button(self, x_pos, y_offset, color, text, callback, size="production", font_preset="button_small"):
        """Creates one of the production screen's scrollable list buttons
        (building/unit/manage rows) and registers it in self.elements."""
        btn = Button(x_pos, y_offset + int(self.scroll_y), size, color, text, callback, font_preset=font_preset)
        btn.base_y = y_offset
        btn.is_scrollable = True
        self.elements.append(btn)
        return btn

    def refresh_ui(self):
        self.btn_back = make_back_button(self.exit_screen)
        self.view_mode_buttons = view_mode_buttons.build(
            lambda mode: map_input.navigate_view_mode(self.map_screen, mode, origin=self))
        view_mode_buttons.sync_highlight(self.view_mode_buttons, self.map_screen.secondary_mode)
        self.elements = [self.btn_back, *self.view_mode_buttons]

        self.active_bars = []
        self.air_damage_labels = {}
        self._list_y = LIST_START_Y

        self.admin_start_y = self._list_y
        self._add_administrative_rows()
        self.admin_end_y = self._list_y
        self._list_y += SECTION_SPACING

        self.other_start_y = self._list_y
        self._add_building_rows()
        self.other_end_y = self._list_y
        self._list_y += SECTION_SPACING

        self._add_unit_sections()
        self._add_custom_unit_section()

        # Calculate maximum scroll distance
        # Negative floor, matching GameState.max_scroll -- see enforce_scroll_bounds.
        self.max_scroll = min(0, c.SCREEN_HEIGHT - SCROLL_BOTTOM_PAD - self._list_y)

        self.scroll_content_rect = pygame.Rect(0, CLICK_GUARD_TOP, c.SCREEN_WIDTH, CLICK_GUARD_BOTTOM - CLICK_GUARD_TOP)

    def _spectator_locked(self):
        return self.map_screen.player_country == "Spectator" and not c.SPECTATOR_CAN_EDIT_PRODUCTION

    def _owner_research(self):
        owner = self.target_province.get("owner")
        return self.map_screen.nation_data.get(owner, {}).get("research", {})

    def _add_administrative_row(self, color, text, callback, cost):
        self._add_scroll_button(LIST_X, self._list_y, color, text, callback)
        bar_rect = pygame.Rect(LIST_X + BAR_OFFSET_X, self._list_y, BAR_WIDTH, BAR_HEIGHT)
        stats = {
            "time": cost["time"],
            "cost_manpower": cost["cost_manpower"],
            "cost_materials": cost["cost_materials"],
            "cost_fuel": cost["cost_fuel"],
            "prod_manpower": 0, "prod_materials": 0, "prod_fuel": 0
        }
        self.active_bars.append((bar_rect, stats, self._list_y, "BUILDING"))
        self._list_y += ROW_STEP_Y

    def _add_administrative_rows(self):
        province = self.target_province
        owner = province.get("owner")
        map_data = self.map_screen.map_data
        settings = self.map_screen.scenario_settings
        building_queue = province.get("building_queue", [])
        locked = self._spectator_locked()

        # --- BUGFIX: Coring Restrictions ---
        can_core = queries.province_can_be_cored(owner, province, self.map_screen.id_to_province,
                                                 queries.nation_has_any_core(owner, map_data))

        if not queries.has_core(owner, province) and queries.is_administrative_action_enabled("CORE", settings):
            if any(q.get("order_type") == "CORE" for q in building_queue):
                color, text, callback = "grey", "Coring...", _no_action
            elif locked:
                color, text, callback = "grey", "Core Territory", _no_action
            elif not can_core:
                color, text, callback = "grey", "Cannot Core", _no_action
            else:
                color, text, callback = "purple", "Core Territory", lambda: self.start_coring()
            self._add_administrative_row(color, text, callback, queries.get_core_cost(owner, map_data, settings))

        # --- REMOVE CORES BUTTON ---
        # Cores are ignored entirely under the "Disable Cores" scenario rule, so
        # there's nothing left to add or strip -- skip this row completely.
        if queries.is_administrative_action_enabled("REMOVE_CORE", settings):
            foreign_cores = [core for core in province.get("cores", []) if core != owner]

            if any(q.get("order_type") == "REMOVE_CORE" for q in building_queue):
                color, text, callback = "grey", "Removing Cores...", _no_action
            elif not foreign_cores:
                color, text, callback = "grey", "No Foreign Cores", _no_action
            elif not queries.province_has_garrison(owner, province):
                color, text, callback = "grey", "Needs Garrison", _no_action
            elif not can_core:
                color, text, callback = "grey", "Cannot Remove", _no_action
            elif locked:
                color, text, callback = "grey", "Remove Cores", _no_action
            else:
                color, text, callback = "red", "Remove Cores", lambda: self.start_remove_cores()
            self._add_administrative_row(color, text, callback, queries.get_remove_core_cost(owner, map_data, settings))

    def _next_building_in_group(self, group_id, current_buildings):
        b_list = [b for b, d in self.building_library.items() if d.get("group") == group_id]
        owned_in_group = [b for b in current_buildings if self.building_library.get(b, {}).get("group") == group_id]
        if not owned_in_group:
            return b_list[0] if b_list else None
        target = None
        for i, b_name in enumerate(b_list):
            if b_name in owned_in_group:
                if i + 1 < len(b_list):
                    target = b_list[i+1]
        return target

    def _add_building_rows(self):
        province = self.target_province
        owner = province.get("owner")
        research = self._owner_research()
        building_queue = province.get("building_queue", [])

        for group_id in ("industry", "fortification", "recruitment"):
            target = self._next_building_in_group(group_id, province.get("buildings", []))
            if not target:
                continue

            # Dynamically calculate the visual cost for the player
            data = queries.get_building_cost(target, owner, self.map_screen.map_data, self.building_library)
            output = queries.get_province_building_output(
                {"owner": owner, "cores": province.get("cores", []), "buildings": [target]},
                research, self.building_library, context=self.map_screen)
            data.update({f"prod_{res}": amount for res, amount in output.items()})
            is_building = any(q.get("group") == data["group"] for q in building_queue)
            req_tech, req_lvl = queries.get_building_required_tech(target)

            if req_tech and research.get(req_tech, 0) < req_lvl:
                continue

            # --- ENFORCE FACTORY DEPENDENCY ---
            if data["group"] in ["recruitment"]:
                if not queries.has_basic_factory(province):
                    continue

            if is_building:
                btn_txt = "Building..."
                cb = _no_action
                btn_color = "grey"
            elif self._spectator_locked():
                btn_txt = queries.get_condensed_building_name(target)
                cb = _no_action
                btn_color = "grey"
            else:
                btn_txt = queries.get_condensed_building_name(target)
                cb = lambda t=target: self.start_construction(t)
                btn_color = "orange"

            self._add_scroll_button(LIST_X, self._list_y, btn_color, btn_txt, cb)

            bar_rect = pygame.Rect(LIST_X + BAR_OFFSET_X, self._list_y, BAR_WIDTH, BAR_HEIGHT)
            self.active_bars.append((bar_rect, data, self._list_y, "BUILDING"))
            self._list_y += ROW_STEP_Y

    def _add_unit_row(self, unit_name, btn_color, x_offset=0):
        factory = queries.get_unit_metadata(unit_name, self.unit_library, context=self.map_screen)["recruitment"]["industry"]
        can_build = (factory == "none" or (queries.has_industry(self.target_province)
                     if factory == "industry" else queries.has_basic_factory(self.target_province)))

        if self._spectator_locked():
            final_btn_color = "grey"
            cb = _no_action
        else:
            final_btn_color = btn_color if can_build else "grey"
            cb = lambda n=unit_name: self.buy_unit(n)

        self._add_scroll_button(LIST_X + x_offset, self._list_y, final_btn_color,
                                queries.get_condensed_unit_name(unit_name, self.unit_library), cb)

        stats = self.unit_library[unit_name]
        if stats.get("air_role") == "fighter" and id(stats) not in self.air_damage_labels:
            text = f"(Air Dmg x{stats.get('air_attack_multiplier', 1.0):g})"
            self.air_damage_labels[id(stats)] = fonts.get("small").render(text, True, c.COLOR_SUCCESS_GREEN)
        # Shrinks to keep its right edge fixed when x_offset > 0 (the Infantry
        # row's Mot/Mec toggles push its button right) so every bar's right
        # edge still lines up regardless of which row it belongs to.
        bar_rect = pygame.Rect(LIST_X + BAR_OFFSET_X + x_offset, self._list_y, BAR_WIDTH - x_offset, BAR_HEIGHT)
        self.active_bars.append((bar_rect, stats, self._list_y, "UNIT"))
        self._list_y += ROW_STEP_Y

    def _add_variant_toggles(self, mode, set_mode, variants):
        """Draws the variant toggle squares at the row's left edge (see
        variant_block_width). Always drawn, disabled/greyed when the
        corresponding tech isn't researched. `set_mode(key)` should flip to
        that mode, or back to 'normal' if it's already active."""
        toggle_x = LIST_X
        spectator_locked = self._spectator_locked()
        for key, _prefix, label, available in variants:
            toggle_color = "orange" if (available and mode == key) else "blue"
            toggle_cb = (lambda k=key: set_mode(k)) if (available and not spectator_locked) else _no_action
            toggle_btn = self._add_scroll_button(toggle_x, self._list_y, toggle_color, label, toggle_cb,
                                                  size="tiny_square", font_preset="tiny")
            toggle_btn.disabled = not available or spectator_locked
            toggle_x += 30 + INFANTRY_MODE_BTN_GAP

    def _add_variant_row(self, variants, get_mode, store_mode, unit_for_prefix, btn_color):
        """One production button with variant toggles to its left, so a family's
        variants share a row. `unit_for_prefix` names the unit the chosen variant
        builds, or None when there is nothing to build."""
        mode, prefix = resolve_variant(get_mode(), variants)
        store_mode(mode)
        unit_name = unit_for_prefix(prefix)
        if unit_name is None:
            return

        def set_mode(new_mode):
            # Clicking the already-active mode toggles it back off.
            store_mode(new_mode if get_mode() != new_mode else "normal")
            self.refresh_ui()

        self._add_variant_toggles(mode, set_mode, variants)
        self._add_unit_row(unit_name, btn_color, x_offset=variant_block_width(len(variants)))

    def _unit_in_variant_family(self, prefix, unit_name):
        """The same tier as `unit_name` in the family named by `prefix`."""
        if not prefix:
            return unit_name
        tier = queries.get_unit_tier(unit_name, context=self.map_screen)
        return queries.get_unit_for_family_tier(self.unit_library, prefix, tier, context=self.map_screen)

    def _add_infantry_row(self, variants):
        """Single combined Infantry row: a Mot/Mec/IFV toggle to the left of
        the production button picks which variant it builds (they all share
        Infantry's own current year - see queries.get_infantry_family_year),
        instead of separate rows per variant."""
        base_year = queries.get_infantry_family_year("infantry_type", self._owner_research(), self.tech_tree)
        if base_year is None:
            return
        self._add_variant_row(
            variants, lambda: self.infantry_mode, lambda mode: setattr(self, "infantry_mode", mode),
            lambda prefix: queries.get_unit_for_family_tier(self.unit_library, prefix or "Infantry Type", base_year,
                                                            context=self.map_screen),
            "green")

    def _add_artillery_row(self):
        """Single combined Artillery row: a Hvy toggle to the left of the
        production button switches to Heavy Artillery, which shares
        Artillery's own research level exactly (see
        c.UNIT_TECH_KEY_OVERRIDES) instead of getting a row of its own."""
        highest_unlocked = self._highest_unlocked_tier("Artillery")
        if highest_unlocked is None:
            return
        self._add_variant_row(
            ARTILLERY_VARIANTS, lambda: self.artillery_mode, lambda mode: setattr(self, "artillery_mode", mode),
            lambda prefix: self._unit_in_variant_family(prefix, highest_unlocked), "green")

    def _add_custom_variant_row(self, base_name, variants, modes, btn_color):
        """Give each custom entry its own independent variant toggle."""
        self._add_variant_row(
            variants, lambda: modes.get(base_name, "normal"), lambda mode: modes.__setitem__(base_name, mode),
            lambda prefix: self._unit_in_variant_family(prefix, base_name), btn_color)

    def _highest_unlocked_tier(self, group_name):
        """Return the latest unlocked equipment stage or numbered tier in a family."""
        research = self._owner_research()
        highest_lvl, highest_unlocked = -1, None
        for name in self.unit_library:
            if queries.get_base_unit_name(name, context=self.map_screen) == group_name:
                lvl = queries.get_unit_tier(name, self.unit_library, context=self.map_screen)
                if queries.is_unit_unlocked(name, research, self.unit_library, context=self.map_screen) and lvl > highest_lvl:
                    highest_lvl, highest_unlocked = lvl, name
        return highest_unlocked

    def _unit_speed_sort_key(self, unit_name):
        # Fastest-to-build units float to the top of their category;
        # materials cost is the tiebreaker when build time is equal.
        stats = self.unit_library.get(unit_name, {})
        return (stats.get('production_time', 0), stats.get('cost_materials', 0))

    def _add_unit_group_rows(self, groups, btn_color):
        research = self._owner_research()
        unlocked_units = []
        for group_name in groups:
            if queries.is_unit_obsolete(group_name, research):
                continue

            highest_unlocked = None
            tech_key = queries.get_unit_tech_key(group_name, context=self.map_screen)

            if tech_key in ("infantry_type", "motorized_infantry", "mechanized_infantry", "infantry_fighting_vehicle"):
                year = queries.get_infantry_family_year(tech_key, research, self.tech_tree)
                if year is not None:
                    highest_unlocked = queries.get_unit_for_family_tier(self.unit_library, group_name, year, context=self.map_screen)
            else:
                highest_unlocked = self._highest_unlocked_tier(group_name)

            if highest_unlocked:
                unlocked_units.append(highest_unlocked)

        for unit_name in sorted(unlocked_units, key=self._unit_speed_sort_key):
            self._add_unit_row(unit_name, btn_color)

    def _infantry_variants(self):
        """(mode key, name-swap target, toggle label, available) for every
        non-regular variant, left to right. Whether Motorized/Mechanized/IFV
        Infantry are unlocked at all (Trucks/APCs/IFV researched) is shared by the
        main Infantry row and every custom Infantry row, since the toggle's
        availability isn't per-year, just global."""
        research = self._owner_research()
        return tuple(
            (key, family, label, queries.get_infantry_family_year(tech, research, self.tech_tree) is not None)
            for key, family, label, tech in (
                ("motorized", "Motorized Infantry Type", "Mot", "motorized_infantry"),
                ("mechanized", "Mechanized Infantry Type", "Mec", "mechanized_infantry"),
                ("ifv", "Infantry Fighting Vehicle Type", "IFV", "infantry_fighting_vehicle"),
            ))

    def _add_unit_sections(self):
        self.infantry_start_y = self._list_y
        self._add_infantry_row(self._infantry_variants())
        self._add_artillery_row()
        # Motorized/Mechanized/IFV are folded into the combined Infantry row above,
        # and Heavy Artillery into the combined Artillery row above - none of the
        # four are listed as their own group here.
        other_infantry_groups = [g for g in self.infantry_groups
                                  if g not in ("Infantry Type", "Motorized Infantry Type",
                                               "Mechanized Infantry Type", "Infantry Fighting Vehicle Type",
                                               "Artillery", "Heavy Artillery")]
        self._add_unit_group_rows(other_infantry_groups, "green")
        self.infantry_end_y = self._list_y

        self._list_y += SECTION_SPACING
        self.tank_start_y = self._list_y
        self._add_unit_group_rows(self.tank_groups, "green")
        self.tank_end_y = self._list_y

        self._list_y += SECTION_SPACING
        if self.target_province.get("is_coastal", False):
            self.navy_start_y = self._list_y
            self._add_unit_group_rows(self.navy_groups, "blue")
            self.navy_end_y = self._list_y
        else:
            self.navy_start_y = self.navy_end_y = self._list_y

        # A hidden/empty naval section must not add a second gap on land tiles.
        if self.navy_end_y > self.navy_start_y:
            self._list_y += SECTION_SPACING
        self.air_start_y = self._list_y
        self._add_unit_group_rows(self.air_groups, "red")
        self.air_end_y = self._list_y

    def _add_custom_unit_section(self):
        # --- CUSTOM UNIT LOGIC ---
        # Lets a player build a specific researched tier (e.g. Medium Tank II) even
        # when a higher tier is researched and would otherwise be the only option shown.
        self._list_y += SECTION_SPACING
        self.custom_start_y = self._list_y

        owner_nation = self.target_province.get("owner")
        research = self._owner_research()
        p_data = self.map_screen.nation_data.get(owner_nation)
        owner_valid = p_data is not None

        custom_units = p_data.get("custom_production_units", []) if owner_valid else []
        valid_custom_units = [u for u in custom_units if u in self.unit_library and queries.is_unit_unlocked(u, research, context=self.map_screen)]
        if owner_valid and valid_custom_units != custom_units:
            p_data["custom_production_units"] = valid_custom_units
        custom_units = valid_custom_units

        if not owner_valid or self._spectator_locked():
            manage_color, manage_cb = "grey", _no_action
        else:
            manage_color, manage_cb = "pink", self.open_custom_unit_manager

        self._add_scroll_button(LIST_X, self._list_y, manage_color, "Edit Custom Units", manage_cb)
        self._list_y += ROW_STEP_Y

        # Stale entries (removed from the custom list since the last toggle) don't
        # need to stick around in the per-row Mot/Mec/Hvy state.
        self.custom_infantry_modes = {k: v for k, v in self.custom_infantry_modes.items() if k in custom_units}
        self.custom_artillery_modes = {k: v for k, v in self.custom_artillery_modes.items() if k in custom_units}

        infantry_variants = self._infantry_variants()
        for unit_name in sorted(custom_units, key=self._unit_speed_sort_key):
            base_name = queries.get_base_unit_name(unit_name, context=self.map_screen)
            if base_name == "Infantry Type":
                self._add_custom_variant_row(unit_name, infantry_variants, self.custom_infantry_modes, "yellow")
            elif base_name == "Artillery":
                self._add_custom_variant_row(unit_name, ARTILLERY_VARIANTS, self.custom_artillery_modes, "yellow")
            else:
                self._add_unit_row(unit_name, "yellow")

        self.custom_end_y = self._list_y

    def _can_start_administrative_action(self, order_type):
        owner = self.target_province.get("owner")
        viewer = self.map_screen.player_country
        if (self.map_screen.tactical_mode or
                (viewer == "Spectator" and not c.SPECTATOR_CAN_EDIT_PRODUCTION) or
                (viewer != "Spectator" and viewer != owner)):
            return False
        return (queries.is_administrative_action_enabled(order_type, self.map_screen.scenario_settings)
                and self.can_edit_realtime())

    def start_coring(self):
        if self._can_start_administrative_action("CORE"):
            self._submit_production("building_queue", {"order_type": "CORE"}, "Started Coring Territory")

    def start_remove_cores(self):
        if self._can_start_administrative_action("REMOVE_CORE"):
            self._submit_production("building_queue", {"order_type": "REMOVE_CORE"}, "Started Core Removal")

    def start_construction(self, b_name):
        self._submit_production("building_queue", {"order_type": "BUILDING", "item_name": b_name}, f"Started {b_name}")

    def buy_unit(self, unit_name):
        label = queries.get_unit_display_name(unit_name, self.unit_library)
        self._submit_production("unit_queue", {"unit_type": unit_name}, f"Production started: {label}")

    def _submit_production(self, queue, intent, feedback):
        if not self.map_screen or not self.can_edit_realtime():
            return
        owner = self.target_province.get("owner")
        try:
            production_actions.submit_production(
                self.map_screen, owner, self.target_province, queue, intent,
                unit_library=self.unit_library, building_library=self.building_library)
        except ValueError as error:
            self.map_screen.show_feedback(str(error))
            return
        self._mark_draft_changed()
        self.map_screen.show_feedback(feedback)
        self.refresh_ui()

    def open_custom_unit_manager(self):
        if not self.can_edit_realtime():
            return
        if not self.map_screen: return

        owner_nation = self.target_province.get("owner")
        p_data = self.map_screen.nation_data.get(owner_nation)
        if p_data is None: return

        player_research = p_data.get("research", {})
        current_custom = set(p_data.get("custom_production_units", []))

        # Group every unit the player currently has the research level for, regardless
        # of whether it's the group's highest tier (that restriction is what this menu exists to bypass).
        # Same category rule the production columns use. Motorized/Mechanized/
        # IFV Infantry and Heavy Artillery aren't listed separately - add the plain
        # "Infantry Type <year>"/"Artillery <numeral>" entry here and use the
        # Mot/Mec/IFV/Hvy toggle next to it on the production screen's Custom row
        # to build that variant instead.
        categorized = queries.get_grouped_units(
            self.unit_library, by_family=False,
            unit_filter=lambda name, stats: queries.is_unit_unlocked(name, player_research, context=self.map_screen), context=self.map_screen)

        for names in categorized.values():
            names[:] = [n for n in names
                        if queries.get_base_unit_name(n, context=self.map_screen) not in (
                            "Motorized Infantry Type", "Mechanized Infantry Type",
                            "Infantry Fighting Vehicle Type", "Heavy Artillery")]
            names.sort()


        items = []
        for category, names in categorized.items():
            if not names:
                continue
            items.append(SectionHeader(category))
            items.extend(CheckboxItem(name, queries.get_unit_display_name(name, self.unit_library),
                                      checked=name in current_custom) for name in names)

        def on_picked(picked):
            if picked is None:
                return
            p_data["custom_production_units"] = picked
            self._mark_draft_changed()
            self.refresh_ui()

        pickers.open_checkbox_list(
            self, "Manage Custom Production Units",
            "Select researched units to add to the Custom build category:",
            items, on_picked, confirm_label="Apply")

    def cancel_order(self, index, q_type):
        if not self.can_edit_realtime():
            return
        queue = "building_queue" if q_type == "building" else "unit_queue"
        owner = self.target_province.get("owner", "Unclaimed")
        try:
            production_actions.cancel_production(self.map_screen, owner, self.target_province, queue, index)
        except ValueError:
            return
        self._mark_draft_changed()
        self.map_screen.show_feedback("Cancelled & Refunded")
        self.refresh_ui()

    def additional_events(self, event):
        if event.type == pygame.MOUSEWHEEL:
            self.target_scroll_y += event.y * SCROLL_WHEEL_STEP
            self.enforce_scroll_bounds()

        # Content-drag targets target_scroll_y (not scroll_y) so a drag eases in
        # exactly like the wheel does, via the same lerp in update(). refresh=False
        # since update() already repositions every is_scrollable button off
        # base_y + scroll_y each frame -- no need to rebuild the whole list per pixel.
        if self.handle_content_drag(event, attr="target_scroll_y", rect_attr="scroll_content_rect",
                                    lo=self.max_scroll, hi=0, refresh=False):
            self.enforce_scroll_bounds()
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.map_screen.player_country == "Spectator" and not c.SPECTATOR_CAN_EDIT_PRODUCTION:
                return
                
            for rect, index, q_type in self.cancel_hitboxes:
                if rect.collidepoint(event.pos):
                    self.cancel_order(index, q_type)
                    return

    def additional_draw(self, surface):
        if not self.target_province: return

        # Fixed header + resource HUD, drawn first now that the scrolling content
        # below is genuinely clipped to scroll_content_rect instead of needing a
        # chrome layer painted over it afterwards to hide whatever slid behind it.
        self.draw_chrome(surface)

        # --- DRAW SCROLLING CONTENT ---
        # Every section is the same panel + label, so they are painted from the
        # SECTION_PANELS table rather than seven near-identical blocks.
        scroll = int(self.scroll_y)
        heading_font = fonts.get("heading2")

        with ui_bars.clip_scroll_region(surface, self.scroll_content_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
            for prefix, label, border, text_color in SECTION_PANELS:
                start_y = getattr(self, f"{prefix}_start_y", 0)
                end_y = getattr(self, f"{prefix}_end_y", 0)
                if end_y <= start_y:
                    continue

                panel = pygame.Rect(PANEL_X, start_y + scroll - PANEL_PAD_TOP,
                                    PANEL_WIDTH, end_y - start_y + PANEL_PAD_TOP)
                ui_elements.draw_pixel_background(surface, panel, PRODUCTION_PANEL_STYLES[prefix])
                pygame.draw.rect(surface, border, panel, 2)
                surface.blit(heading_font.render(label, True, text_color),
                             (PANEL_LABEL_X, start_y + scroll + PANEL_LABEL_OFFSET_Y))

            # Stats Bars -- everything packed onto a single line, per-section
            # colors preserved but labels dropped, so it fits within the bar
            # instead of running off-screen.
            bar_font = fonts.get("small")
            for base_rect, stats, base_y, bar_type in self.active_bars:
                bar_rect = pygame.Rect(base_rect.x, base_y + scroll, base_rect.width, base_rect.height)
                ui_elements.draw_pixel_background(surface, bar_rect, PRODUCTION_PANEL_STYLES["stats"])
                pygame.draw.rect(surface, BAR_BORDER_COLOR, bar_rect, 1)

                text_y = bar_rect.y + (bar_rect.height - bar_font.get_height()) // 2
                x = bar_rect.x + BAR_TEXT_PAD_X

                if bar_type == "BUILDING":
                    t = max(1, stats.get('time', 1))
                    x = draw_time_stat(surface, bar_font, t, x, text_y, c.COLOR_GOLD_HIGHLIGHT)
                    x = draw_stat_separator(surface, bar_font, x, text_y)
                    x = draw_resource_string(surface, bar_font, "", stats.get('cost_materials', 0), stats.get('cost_manpower', 0), stats.get('cost_fuel', 0), x, text_y, c.COLOR_GOLD_HIGHLIGHT)
                    x = draw_stat_separator(surface, bar_font, x, text_y)
                    draw_resource_string(surface, bar_font, "", stats.get('prod_materials', 0), stats.get('prod_manpower', 0), stats.get('prod_fuel', 0), x, text_y, BAR_YIELD_COLOR, is_yield=True)
                else:
                    t = max(1, stats.get('production_time', 1))
                    x = draw_time_stat(surface, bar_font, t, x, text_y, c.COLOR_GOLD_HIGHLIGHT)
                    x = draw_stat_separator(surface, bar_font, x, text_y)
                    x = draw_resource_string(surface, bar_font, "", stats.get('cost_materials', 0), stats.get('cost_manpower', 0), stats.get('cost_fuel', 0), x, text_y, c.COLOR_GOLD_HIGHLIGHT)
                    x = draw_stat_separator(surface, bar_font, x, text_y)
                    x = draw_combat_stats(
                        surface, bar_font, "",
                        stats.get('attack', 0), stats.get('defense', 0), stats.get('health', 0), stats.get('speed', 0),
                        x, text_y, BAR_STAT_COLOR, labeled=False
                    )

                    if 'bombard_attack' in stats:
                        x = draw_stat_separator(surface, bar_font, x, text_y)
                        x = draw_bombardment_stats(
                            surface, bar_font,
                            stats.get('bombard_attack', 0), stats.get('bombard_range', 0),
                            x, text_y, BAR_STAT_COLOR, base_text="", labeled=False
                        )

                    air_damage_label = self.air_damage_labels.get(id(stats))
                    if air_damage_label is not None:
                        surface.blit(air_damage_label, (x + AIR_DAMAGE_LABEL_GAP, text_y))

    def draw_chrome(self, surface):
        """Fixed header + resource HUD."""
        if not self.target_province: return

        pygame.draw.rect(surface, self.bg_color, (0, 0, c.SCREEN_WIDTH, HEADER_HEIGHT))
        title_font = fonts.get("heading1")

        # Determine the name to display at the top of the production queue!
        owner_nation = self.target_province.get("owner", "Unclaimed")
        owner_name = self.map_screen.nation_data.get(owner_nation, {}).get("name", owner_nation).upper()
        surface.blit(title_font.render(f"{owner_name} PRODUCTION", True, (255, 255, 255)), HEADER_TITLE_POS)

        resource_hud.draw_resource_bar(surface, self.map_screen, target_nation=owner_nation,
                                       start_x=view_mode_buttons.RESOURCE_BAR_OFFSET_X)

        # Draw Queue (Returns hitbox rectangles for the event handler)
        self.cancel_hitboxes = recruit_ui.draw_recruitment_overlay(surface, self.target_province)

