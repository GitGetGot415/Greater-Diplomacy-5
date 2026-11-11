"""Edit a scenario's unit and building rules in one draft, separate from the active game library.

Construction turns, enabled families, unit ranges, and building stats share one Save All Changes.
Default turn rows store no override. Conversions use whole-turn sliders and remain enabled.
The map editor reuses the building rows to edit a map's default building stats.
"""
import json

import pygame

from data import queries
from data.runtime_rules import rebuild
import data.constants as c
from ui.background_styles import EDITOR_PANEL_STYLES
from ui.rendering import symbol_loader
from ui.rendering.font_manager import fonts
from ui import dialogs
from ui.widgets import ui_elements
from ui.navigation.modal_screen import ModalScreen
from ui.widgets.ui_elements import (Button, Slider, TextField, make_back_button, make_on_off_button,
                                    make_toggle_button)

from ui.navigation import screen_runner


#: Marks the Use Defaults row at the top of the Buildings category.
USE_DEFAULTS_ROW = "use_defaults"

#: Building row kinds: level 1 values, then the increase for each later level.
LEVEL_ONE_ROW, PER_LEVEL_ROW = "level_one", "per_level"

#: The settings prefix of each category's construction turns and disabled list.
TURN_CATEGORIES = {"units": "unit", "buildings": "building",
                   "administrative": "administrative", "conversions": "conversion"}

#: Categories whose rows are only a turn count, an ON/OFF button, or a conversion slider.
TURN_ONLY_CATEGORIES = ("units", "administrative", "conversions")


def _number_text(value):
    """Show whole numbers without a decimal point or exponent."""
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}".rstrip("0")


def _read_library(path):
    """Read the complete library file.

    The cached library is the same dict that load_map.py prunes for a loaded game's disabled families.
    Rows read from it would vanish, and a disabled family could not be enabled again.
    """
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class _ConversionTurnSlider(Slider):
    """Snap the shared slider to whole turns within the conversion limits."""

    def __init__(self, x, y, width, turns, callback):
        self.on_change = callback
        span = c.MAX_CONVERSION_TURNS - c.MIN_CONVERSION_TURNS
        super().__init__(x, y, width, "", turns - c.MIN_CONVERSION_TURNS,
                         self._set_turns, visual_max=span, allowed_max=span)

    def get_display_string(self):
        turns = round(self.value) + c.MIN_CONVERSION_TURNS
        return f"{turns} {'turn' if turns == 1 else 'turns'}"

    def _set_turns(self, value):
        self.value = round(value)
        self.handle_rect.centerx = self.rect.x + round(self.rect.width * self.value / self.visual_max)
        self.on_change(self.value + c.MIN_CONVERSION_TURNS)


class UnitStatsEditorScreen(ModalScreen):
    TITLE = "Unit / Building Stats Editor"
    PANEL_STYLE = EDITOR_PANEL_STYLES["unit_stats"]
    PANEL_SIZE = (900, 640)
    PAD = 20
    ROW_HEIGHT = 54
    #: Administrative rows have no images. Conversion rows hold a labeled slider.
    CATEGORY_ROW_HEIGHTS = {"administrative": 34, "conversions": 64}
    TAB_SIZE = (160, 40)
    TAB_GAP = 10
    TAB_Y_OFF = 56
    NOTE_Y_OFF = 102
    LIST_TOP_OFF = 160
    HEADER_ABOVE_LIST = 24
    FIELD_HEIGHT = 28
    # Range rows.
    FIELD_WIDTH = 110
    RANGE_FIELD_Y_OFF = 10
    START_RIGHT_OFF = 210
    STEP_RIGHT_OFF = 60
    # Turn rows: the default hint, the turns field, then the ON/OFF button.
    # Leaves a gap between the ON/OFF buttons and the scrollbar.
    CHECK_RIGHT_OFF = 60
    CHECK_SIZE = c.SIZES["tiny_square"][0]
    TURN_FIELD_WIDTH = 100
    TURN_FIELD_GAP = 10
    TURN_HINT_GAP = 15
    CONVERSION_SLIDER_WIDTH = 240
    CONVERSION_SLIDER_RIGHT_OFF = 40
    CONVERSION_SLIDER_Y_OFF = 32
    CONVERSION_HINT_GAP = 30
    # Building rows: turns, three cost fields, three income fields, then the ON/OFF button.
    BUILDING_FIELD_WIDTH = 64
    BUILDING_FIELD_GAP = 6
    BUILDING_GROUP_GAP = 18
    BUILDING_GROUP_HEADER_OFF = 46
    ROW_ICON_SIZE = (52, 40)
    ROW_ICON_GAP = 10
    ROW_LABEL_INSET = 8
    DIVIDER_LABEL_GAP = 12

    #: (key, tab label) for each category, in tab order.
    CATEGORIES = (("units", "Units"), ("buildings", "Buildings"), ("range", "Range"),
                  ("administrative", "Administrative"), ("conversions", "Conversions"))
    #: The scenario settings key that holds the edited building stats.
    BUILDING_SETTING = "building_stat_overrides"
    #: Show Use Defaults as the first Buildings row.
    HAS_USE_DEFAULTS = True
    #: Edit construction turns, enabled families, and unit ranges.
    HAS_SCENARIO_RULES = True
    RESET_MESSAGE = "Reset everything in this editor to defaults for this scenario?"

    def __init__(self, settings=None, persist=True, game_state=None):
        super().__init__(game_state, self.TITLE)
        self.target_settings = settings if settings is not None else queries.get_scenario_settings()
        self.persist = persist
        self.use_defaults = self.HAS_USE_DEFAULTS and queries.uses_default_building_stats(self.target_settings)
        self.rows = {}
        building_library = _read_library(c.BUILDING_DATA_PATH)
        if self.HAS_SCENARIO_RULES:
            unit_library = _read_library(c.UNIT_DATA_PATH)
            self.icons = symbol_loader.get_family_symbols(unit_library, self.ROW_ICON_SIZE)
            self._load_ranges(unit_library)
            self._load_turns(unit_library, building_library)
        self._load_buildings(building_library)
        self.active_category = self.CATEGORIES[0][0]
        self.list_top = self.panel_rect.y + self.LIST_TOP_OFF
        self.list_view_h = self.panel_rect.bottom - 66 - self.list_top
        self.refresh_ui()

    def _load_ranges(self, unit_library):
        self.defaults = queries.get_unit_range_defaults(unit_library)
        overrides = queries.get_unit_range_overrides(self.target_settings, self.defaults)
        self.values = {
            family: {key: f"{overrides.get(family, {}).get(key, default):g}"
                     for key, default in fields.items()}
            for family, fields in self.defaults.items()
        }
        families = sorted(self.defaults.items(), key=lambda item: item[0].lower())
        rows = []
        for key in ("bombard_range", "air_range_start"):
            group = [(family, key) for family, fields in families if key in fields]
            if rows and group:
                rows.append((None, "Aircraft"))
            rows.extend(group)
        self.rows["range"] = rows

    def _load_turns(self, unit_library, building_library):
        settings = self.target_settings or {}
        self.turn_tabs = {}
        for key, library, time_key, label in (
                ("unit", unit_library, "production_time", "Unit Type"),
                ("building", building_library, "time", "Building Type"),
                ("administrative", queries.get_administrative_library(), "time", "Administrative Action")):
            self.turn_tabs[key] = self._build_turn_tab(
                library, settings.get(f"{key}_turn_overrides", {}), settings.get(f"{key}_disabled", []),
                time_key, label)
        # Manually edited scenario files can contain a malformed override block.
        conversions = settings.get("conversion_turn_overrides")
        self.turn_tabs["conversion"] = self._build_turn_tab(
            queries.get_conversion_library(), conversions if isinstance(conversions, dict) else {},
            [], "time", "Conversion")
        for action, (name, _constant) in queries.CONVERSION_ACTIONS.items():
            self.turn_tabs["conversion"]["values"][name] = str(queries.get_conversion_turns(action, settings))
        for category in TURN_ONLY_CATEGORIES:
            self.rows[category] = [(name, None) for name in self.turn_tabs[TURN_CATEGORIES[category]]["names"]]

    @staticmethod
    def _build_turn_tab(library, overrides, disabled_list, turn_key, label):
        """Collapse a library to its base types, each with a default and a current turn count.

        Variants of one base type ("Infantry Type 1936/1939/...") always shared a
        turn count, which is why the editor works on base types rather than items.
        """
        base_types = {}
        for name in library:
            base_types.setdefault(queries.get_base_item_name(name), []).append(name)
        defaults = {btype: library[names[0]].get(turn_key, 0) for btype, names in base_types.items()}
        return {"label": label, "names": sorted(base_types, key=str.lower), "defaults": defaults,
                "values": {btype: str(overrides.get(btype, default)) for btype, default in defaults.items()},
                "disabled_set": set(disabled_list)}

    def _load_buildings(self, building_library):
        self.building_defaults = queries.get_building_stat_defaults(building_library)
        self.building_icons = symbol_loader.get_family_symbols(building_library, self.ROW_ICON_SIZE)
        overrides = queries.get_building_stat_overrides(
            (self.target_settings or {}).get(self.BUILDING_SETTING), self.building_defaults)
        self.building_values = {
            family: {key: _number_text(overrides.get(family, {}).get(key, default))
                     for key, default in fields.items()}
            for family, fields in self.building_defaults.items()
        }
        groups = {queries.base_item_name_from_text(name): stats.get("group")
                  for name, stats in building_library.items()}
        rows = [(USE_DEFAULTS_ROW, None)] if self.HAS_USE_DEFAULTS else []
        group = None
        for family, fields in self.building_defaults.items():
            if group is not None and groups[family] != group:
                rows.append((None, str(groups[family] or "").title()))
            group = groups[family]
            rows.append((family, LEVEL_ONE_ROW))
            if any(key.endswith("_per_level") for key in fields):
                rows.append((family, PER_LEVEL_ROW))
        self.rows["buildings"] = rows
        self.leveled_families = {family for family, kind in rows if kind == PER_LEVEL_ROW}
        # Both rows of one family share a stripe.
        self.building_stripes = {family: index % 2 == 0 for index, family in enumerate(self.building_defaults)}

    # ------------------------------------------------------------------ #
    #                               EDITING                              #
    # ------------------------------------------------------------------ #

    @property
    def turn_tab(self):
        """The construction turns and disabled families shown in the active category."""
        return self.turn_tabs[TURN_CATEGORIES[self.active_category]]

    @property
    def row_height(self):
        return self.CATEGORY_ROW_HEIGHTS.get(self.active_category, self.ROW_HEIGHT)

    def toggle_use_defaults(self):
        self.sync_entries()
        self.use_defaults = not self.use_defaults
        self.refresh_ui()

    def toggle_disabled(self, name):
        disabled = self.turn_tab["disabled_set"]
        if name in disabled:
            disabled.discard(name)
        else:
            disabled.add(name)
        self.refresh_ui()

    def select_category(self, key):
        self.sync_entries()
        self.active_category = key
        self.scroll_y = 0
        self.refresh_ui()

    def _read_ranges(self):
        draft = {}
        for family, fields in self.values.items():
            draft[family] = {}
            for key, text in fields.items():
                minimum = 0 if key == "air_range_per_level" else 1
                try:
                    value = int(text)
                except ValueError:
                    value = None
                if value is None or value < minimum:
                    dialogs.show_warning(
                        "Invalid Range", f"{family}: enter a whole number of at least {minimum}.")
                    return None
                draft[family][key] = value
        return queries.get_unit_range_overrides({"unit_range_overrides": draft}, self.defaults)

    def _read_building_stats(self):
        draft = {}
        for family, fields in self.building_values.items():
            draft[family] = {}
            for key, text in fields.items():
                default = self.building_defaults[family][key]
                if text == _number_text(default):
                    # Library data that is not linear can give a fractional default increase.
                    continue
                try:
                    value = int(text)
                except ValueError:
                    value = None
                if value is None or value < 0:
                    dialogs.show_warning("Invalid Building Stat", f"{family}: enter a whole number of at least 0.")
                    return None
                draft[family][key] = value
        return queries.get_building_stat_overrides(draft, self.building_defaults)

    def _read_turns(self):
        """Return the construction settings. Turn text that is not a whole number keeps the default."""
        changes = {}
        for key, tab in self.turn_tabs.items():
            overrides = {}
            for name in tab["names"]:
                try:
                    value = max(1, int(tab["values"][name]))
                except ValueError:
                    continue
                if key == "conversion":
                    value = min(c.MAX_CONVERSION_TURNS, max(c.MIN_CONVERSION_TURNS, value))
                tab["values"][name] = str(value)
                if value != tab["defaults"][name]:
                    overrides[name] = value
            changes[f"{key}_turn_overrides"] = overrides
            if key != "conversion":
                changes[f"{key}_disabled"] = sorted(tab["disabled_set"])
        return changes

    def save_all(self):
        self.sync_entries()
        changes = {}
        if self.HAS_SCENARIO_RULES:
            ranges = self._read_ranges()
            if ranges is None:
                return
            changes["unit_range_overrides"] = ranges
        if self.HAS_USE_DEFAULTS:
            changes["use_default_building_stats"] = self.use_defaults
        # Use Defaults keeps the player's saved building stats unchanged and unused.
        if not self.use_defaults:
            buildings = self._read_building_stats()
            if buildings is None:
                return
            changes[self.BUILDING_SETTING] = buildings
        # Turn text cannot block a save, so a rejected range or stat leaves the turns unsaved too.
        if self.HAS_SCENARIO_RULES:
            changes.update(self._read_turns())
        if self.target_settings is not None:
            self.target_settings.update(changes)
        if self.persist:
            queries.save_scenario_settings(self.target_settings if self.target_settings is not None else changes)
        self.after_save()
        self.exit_screen()

    def after_save(self):
        dialogs.show_success("Saved", "Successfully saved unit and building stats to scenario settings.")

    def reset_to_defaults(self):
        def on_confirm(ok):
            if not ok:
                return
            if self.HAS_SCENARIO_RULES:
                self.values = {family: {key: f"{value:g}" for key, value in fields.items()}
                               for family, fields in self.defaults.items()}
                for tab in self.turn_tabs.values():
                    tab["disabled_set"].clear()
                    tab["values"] = {name: str(default) for name, default in tab["defaults"].items()}
            self.building_values = {family: {key: _number_text(value) for key, value in fields.items()}
                                    for family, fields in self.building_defaults.items()}
            # Remove fields before saving so old text cannot replace reset values.
            self.elements = []
            if self.use_defaults and self.target_settings is not None:
                # save_all skips locked building fields, so clear the saved values here.
                self.target_settings[self.BUILDING_SETTING] = {}
            self.save_all()

        dialogs.ask_yes_no("Confirm Reset", self.RESET_MESSAGE, on_confirm)

    # ------------------------------------------------------------------ #
    #                              LAYOUT                                #
    # ------------------------------------------------------------------ #

    @property
    def check_x(self):
        """Left edge of the ON/OFF buttons."""
        return self.panel_rect.right - self.CHECK_RIGHT_OFF

    @property
    def turn_field_x(self):
        return self.check_x - self.TURN_FIELD_GAP - self.TURN_FIELD_WIDTH

    @property
    def conversion_slider_x(self):
        return self.panel_rect.right - self.CONVERSION_SLIDER_RIGHT_OFF - self.CONVERSION_SLIDER_WIDTH

    def building_field_x(self, index):
        """Left edge of one building stat field. Income fields follow cost fields after a wider gap."""
        count = len(queries.BUILDING_STAT_FIELDS)
        width = (count * self.BUILDING_FIELD_WIDTH + (count - 1) * self.BUILDING_FIELD_GAP
                 + self.BUILDING_GROUP_GAP - self.BUILDING_FIELD_GAP)
        x = self.check_x - self.BUILDING_GROUP_GAP - width
        x += index * (self.BUILDING_FIELD_WIDTH + self.BUILDING_FIELD_GAP)
        if index >= len(c.ECON_RESOURCE_KEYS):
            x += self.BUILDING_GROUP_GAP - self.BUILDING_FIELD_GAP
        return x

    @property
    def building_turns_x(self):
        return self.building_field_x(0) - self.BUILDING_GROUP_GAP - self.BUILDING_FIELD_WIDTH

    def refresh_ui(self):
        self.sync_entries()
        p = self.panel_rect
        self.elements = []
        for index, (key, label) in enumerate(self.CATEGORIES):
            tab = Button(p.x + self.PAD + index * (self.TAB_SIZE[0] + self.TAB_GAP), p.y + self.TAB_Y_OFF,
                         self.TAB_SIZE, "green" if key == self.active_category else "light_blue", label,
                         lambda k=key: self.select_category(k), sound_kind="select_category")
            tab.is_selected = key == self.active_category
            self.elements.append(tab)

        category = self.active_category
        rows = self.rows[category]
        row_height = self.row_height
        self.scroll_content_rect = pygame.Rect(
            p.x + self.PAD, self.list_top, p.width - 2 * self.PAD, self.list_view_h)
        self._row_layout = list(self.layout_list_rows(
            len(rows), row_height, self.list_top,
            cull_top=self.list_top - 1,
            cull_bottom=self.list_top + self.list_view_h - row_height + 2))
        for index, y in self._row_layout:
            name, key = rows[index]
            if name is None:
                continue
            if name == USE_DEFAULTS_ROW:
                toggle_h = c.SIZES["scenario_setting_button"][1]
                self.add_list_row(make_toggle_button(
                    p.x + self.PAD + self.ROW_LABEL_INSET, y + (row_height - toggle_h) // 2,
                    "scenario_setting_button", "Use Defaults", self.use_defaults,
                    self.toggle_use_defaults, font_preset="button_small"))
                continue
            if category == "range":
                field_y = y + self.RANGE_FIELD_Y_OFF
                self._add_field(self.values[name], self.defaults[name], key,
                                p.right - self.START_RIGHT_OFF - self.FIELD_WIDTH, field_y, self.FIELD_WIDTH)
                if key == "air_range_start":
                    self._add_field(self.values[name], self.defaults[name], "air_range_per_level",
                                    p.right - self.STEP_RIGHT_OFF - self.FIELD_WIDTH, field_y, self.FIELD_WIDTH)
                continue
            if category == "conversions":
                values = self.turn_tab["values"]
                self.add_list_row(_ConversionTurnSlider(
                    self.conversion_slider_x, y + self.CONVERSION_SLIDER_Y_OFF,
                    self.CONVERSION_SLIDER_WIDTH, int(values[name]),
                    lambda value, row=name, target=values: target.__setitem__(row, str(value))))
                continue
            if category == "buildings":
                self._add_building_fields(name, key, y)
                continue
            self._add_turn_controls(name, self.turn_field_x, self.TURN_FIELD_WIDTH, y)

        button_y = p.bottom - 52
        self.elements.extend([
            make_back_button(self.exit_screen, pos=(p.x + self.PAD, button_y)),
            Button(p.centerx - 100, button_y - 5, "medium", "green", "Save All Changes", self.save_all),
            Button(p.right - self.PAD - 200, button_y - 5, "medium", "red",
                   "Reset to Defaults", self.reset_to_defaults),
        ])

    def _add_building_fields(self, name, key, row_y):
        field_y = row_y + (self.row_height - self.FIELD_HEIGHT) // 2
        for field_index, field_key in enumerate(queries.BUILDING_STAT_FIELDS):
            if key == PER_LEVEL_ROW:
                field_key = f"{field_key}_per_level"
            # Families with calculated costs have no cost fields.
            if field_key not in self.building_defaults[name]:
                continue
            self._add_field(self.building_values[name], self.building_defaults[name], field_key,
                            self.building_field_x(field_index), field_y,
                            self.BUILDING_FIELD_WIDTH, locked=self.use_defaults)
        # Use Defaults locks only building stats. Turns and enabled families stay editable.
        if self.HAS_SCENARIO_RULES and key == LEVEL_ONE_ROW:
            self._add_turn_controls(name, self.building_turns_x, self.BUILDING_FIELD_WIDTH, row_y)

    def _add_turn_controls(self, name, x, width, row_y):
        """Add one family's turns field and ON/OFF button from the active category."""
        tab = self.turn_tab
        field = TextField(x, row_y + (self.row_height - self.FIELD_HEIGHT) // 2, width, self.FIELD_HEIGHT,
                          tab["values"][name], numeric=True)
        field.entry_ref = tab["values"]
        field.entry_key = name
        self.add_list_row(field)
        self.add_list_row(make_on_off_button(
            self.check_x, row_y + (self.row_height - self.CHECK_SIZE) // 2,
            name not in tab["disabled_set"], lambda row=name: self.toggle_disabled(row)))

    def _add_field(self, values, defaults, key, x, y, width, locked=False):
        """A locked field shows the default value and leaves the draft unchanged."""
        if locked:
            field = TextField(x, y, width, self.FIELD_HEIGHT, _number_text(defaults[key]), numeric=True)
            field.disabled = True
        else:
            field = TextField(x, y, width, self.FIELD_HEIGHT, values[key], numeric=True)
            field.entry_ref = values
            field.entry_key = key
        self.add_list_row(field)

    def additional_events(self, event):
        if any(isinstance(element, Slider) and element.dragging for element in self.elements):
            return
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    # ------------------------------------------------------------------ #
    #                             RENDERING                              #
    # ------------------------------------------------------------------ #

    def _header(self, surface, text, center_x, y):
        small = fonts.get("small")
        label = small.render(text, True, c.UI_TEXT_DIM)
        surface.blit(label, label.get_rect(midtop=(center_x, y)))

    def draw_body(self, surface):
        p = self.panel_rect
        header_y = self.list_top - self.HEADER_ABOVE_LIST
        category = self.active_category
        if category == "range":
            self.label(surface, "Bombardment uses tiles. Aircraft use map pixels. Range = start + (level - 1) x increase.",
                       (p.x + self.PAD, p.y + self.NOTE_Y_OFF))
            for text, x in (("Unit Family", p.x + self.PAD),
                            ("Range / Start", p.right - self.START_RIGHT_OFF - self.FIELD_WIDTH),
                            ("+ per level", p.right - self.STEP_RIGHT_OFF - self.FIELD_WIDTH)):
                self.label(surface, text, (x, header_y))
            return
        if category == "buildings":
            self._draw_building_headers(surface, header_y)
            return
        tab = self.turn_tab
        self.label(surface, tab["label"], (p.x + self.PAD, header_y))
        if category == "conversions":
            self._header(surface, "Turns", self.conversion_slider_x + self.CONVERSION_SLIDER_WIDTH // 2, header_y)
        else:
            self._header(surface, "Turns", self.turn_field_x + self.TURN_FIELD_WIDTH // 2, header_y)
            self._header(surface, "Enabled", self.check_x + self.CHECK_SIZE // 2, header_y)
        if not tab["names"]:
            message = fonts.get("normal").render("Nothing to edit.", True, c.UI_TEXT_LIGHT)
            surface.blit(message, message.get_rect(center=(p.centerx, self.list_top + self.list_view_h // 2)))

    def _draw_building_headers(self, surface, header_y):
        p = self.panel_rect
        self.label(surface, "Building Family", (p.x + self.PAD, header_y))
        resources = len(c.ECON_RESOURCE_KEYS)
        for group_index, group in enumerate(("Cost", "Income")):
            left = self.building_field_x(group_index * resources)
            right = self.building_field_x((group_index + 1) * resources - 1) + self.BUILDING_FIELD_WIDTH
            self._header(surface, group, (left + right) // 2, self.list_top - self.BUILDING_GROUP_HEADER_OFF)
        for index, field_key in enumerate(queries.BUILDING_STAT_FIELDS):
            self._header(surface, field_key.split("_", 1)[1].title(),
                         self.building_field_x(index) + self.BUILDING_FIELD_WIDTH // 2, header_y)
        if self.HAS_SCENARIO_RULES:
            self._header(surface, "Turns", self.building_turns_x + self.BUILDING_FIELD_WIDTH // 2, header_y)
            self._header(surface, "Enabled", self.check_x + self.CHECK_SIZE // 2, header_y)

    def draw_scroll_backdrop(self, surface):
        if self.active_category in TURN_ONLY_CATEGORIES:
            self._draw_turn_rows(surface)
            return
        p = self.panel_rect
        font, small = fonts.get("normal"), fonts.get("small")
        rows = self.rows[self.active_category]
        for index, y in self._row_layout:
            name, key = rows[index]
            if name == USE_DEFAULTS_ROW:
                continue
            if name is None:
                label = font.render(key, True, c.UI_TEXT_DIM)
                rect = label.get_rect(center=(p.centerx, y + self.ROW_HEIGHT // 2))
                pygame.draw.line(surface, c.UI_TEXT_DIM,
                                 (p.x + self.PAD + self.ROW_LABEL_INSET, rect.centery),
                                 (rect.left - self.DIVIDER_LABEL_GAP, rect.centery))
                pygame.draw.line(surface, c.UI_TEXT_DIM,
                                 (rect.right + self.DIVIDER_LABEL_GAP, rect.centery),
                                 (p.right - self.PAD - self.ROW_LABEL_INSET, rect.centery))
                surface.blit(label, rect)
                continue
            striped = (self.building_stripes[name] if self.active_category == "buildings"
                       else index % 2 == 0)
            if striped:
                self._draw_stripe(surface, y, self.ROW_HEIGHT)
            icon_x = p.x + self.PAD + self.ROW_LABEL_INSET
            label_x = icon_x + self.ROW_ICON_SIZE[0] + self.ROW_ICON_GAP
            if key == PER_LEVEL_ROW:
                label = small.render("+ per level", True, c.UI_TEXT_DIM)
                surface.blit(label, label.get_rect(midleft=(label_x, y + self.ROW_HEIGHT // 2)))
                continue
            icons = self.icons if self.active_category == "range" else self.building_icons
            self._draw_icon(surface, icons.get(queries.get_base_item_name(name)), icon_x, y, self.ROW_HEIGHT)
            if key == LEVEL_ONE_ROW:
                if name in self.leveled_families:
                    surface.blit(font.render(name, True, c.UI_TEXT_LIGHT), (label_x, y + 4))
                    surface.blit(small.render("Level 1", True, c.UI_TEXT_DIM), (label_x, y + 29))
                else:
                    label = font.render(name, True, c.UI_TEXT_LIGHT)
                    surface.blit(label, label.get_rect(midleft=(label_x, y + self.ROW_HEIGHT // 2)))
                continue
            surface.blit(font.render(name, True, c.UI_TEXT_LIGHT), (label_x, y + 4))
            default = self.defaults[name]
            if key == "bombard_range":
                hint = f"Bombardment (tiles); default: {default[key]:g}"
            else:
                hint = (f"Flight (map px); default: {default[key]:g}"
                        f" + {default['air_range_per_level']:g} per level")
            surface.blit(small.render(hint, True, c.UI_TEXT_DIM), (label_x, y + 29))

    def _draw_turn_rows(self, surface):
        """Draw the stripe, image, name, and default hint behind each turn row."""
        p = self.panel_rect
        font, small = fonts.get("normal"), fonts.get("small")
        tab = self.turn_tab
        row_height = self.row_height
        if self.active_category == "conversions":
            hint_right = self.conversion_slider_x - self.CONVERSION_HINT_GAP
        else:
            hint_right = self.turn_field_x - self.TURN_HINT_GAP
        for index, y in self._row_layout:
            name = tab["names"][index]
            if index % 2 == 0:
                self._draw_stripe(surface, y, row_height)
            label_x = p.x + self.PAD + self.ROW_LABEL_INSET
            if self.active_category == "units":
                self._draw_icon(surface, self.icons.get(name), label_x, y, row_height)
                label_x += self.ROW_ICON_SIZE[0] + self.ROW_ICON_GAP
            label = font.render(name, True, c.UI_TEXT_LIGHT)
            surface.blit(label, label.get_rect(midleft=(label_x, y + row_height // 2)))
            hint = small.render(f"default: {tab['defaults'][name]}", True, c.UI_TEXT_DIM)
            surface.blit(hint, hint.get_rect(midright=(hint_right, y + row_height // 2)))

    def _draw_stripe(self, surface, y, row_height):
        p = self.panel_rect
        ui_elements.draw_pixel_background(
            surface, pygame.Rect(p.x + self.PAD, y, p.width - 2 * self.PAD, row_height),
            EDITOR_PANEL_STYLES["unit_stats_row"])

    def _draw_icon(self, surface, icon, icon_x, y, row_height):
        if icon is not None:
            center = (icon_x + self.ROW_ICON_SIZE[0] // 2, y + row_height // 2)
            surface.blit(icon, icon.get_rect(center=center))

    def draw_foreground(self, surface):
        self.draw_list_scrollbar(surface, self.panel_rect.right - 26, self.list_top, self.list_view_h)


class MapBuildingStatsScreen(UnitStatsEditorScreen):
    """Edit one map's default building costs and income, by level 1 value and increase, in the map editor.

    New games on the map use these values while Use Defaults is on.
    Buildings the map does not change use data/json/building_data.json.
    """
    TITLE = "Building Stats"
    CATEGORIES = (("buildings", "Buildings"),)
    BUILDING_SETTING = "map_building_stat_overrides"
    HAS_USE_DEFAULTS = False
    HAS_SCENARIO_RULES = False
    RESET_MESSAGE = "Reset this map's building stats to the building library defaults?"

    def __init__(self, map_screen):
        super().__init__(settings=map_screen.scenario_settings, persist=False, game_state=map_screen)

    def after_save(self):
        rebuild(self.map_screen)
        self.map_screen.show_feedback("Building stats updated. Save the map to write them to disk.")


def open_unit_stats_editor(on_done=None, settings=None, persist=True):
    """Open a nonblocking editor with the same settings owner as its caller.

    `on_done` lets a caller such as Scenario Settings refresh itself once the editor closes.
    """
    screen_runner.run_screen(lambda: UnitStatsEditorScreen(settings=settings, persist=persist),
               on_done=on_done, caption=UnitStatsEditorScreen.TITLE)
