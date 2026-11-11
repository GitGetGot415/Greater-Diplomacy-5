"""Edit scenario unit ranges and building stats in a draft, separate from the active game library.

The map editor reuses the building rows to edit a map's default factory stats.
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
from ui.widgets.ui_elements import Button, TextField, make_back_button, make_toggle_button

from ui.navigation import screen_runner


#: Marks the Use Defaults row at the top of the Buildings category.
USE_DEFAULTS_ROW = "use_defaults"


class UnitStatsEditorScreen(ModalScreen):
    TITLE = "Unit / Building Stats Editor"
    PANEL_STYLE = EDITOR_PANEL_STYLES["unit_stats"]
    PANEL_SIZE = (900, 640)
    PAD = 20
    ROW_HEIGHT = 54
    TAB_Y_OFF = 56
    NOTE_Y_OFF = 102
    LIST_TOP_OFF = 160
    FIELD_WIDTH = 110
    START_RIGHT_OFF = 210
    STEP_RIGHT_OFF = 60
    # Building rows: three cost fields, then three income fields.
    BUILDING_FIELD_WIDTH = 74
    BUILDING_FIELD_GAP = 6
    BUILDING_GROUP_GAP = 18
    BUILDING_RIGHT_OFF = 40
    BUILDING_GROUP_HEADER_OFF = 46
    ROW_ICON_SIZE = (52, 40)
    ROW_ICON_GAP = 10
    ROW_LABEL_INSET = 8
    DIVIDER_LABEL_GAP = 12

    #: (key, tab label) for each category, in tab order.
    CATEGORIES = (("range", "Range"), ("buildings", "Buildings"))
    #: Building groups in the Buildings category, or None for every building.
    BUILDING_GROUPS = None
    #: The scenario settings key that holds the edited building stats.
    BUILDING_SETTING = "building_stat_overrides"
    #: Show Use Defaults as the first Buildings row.
    HAS_USE_DEFAULTS = True
    RESET_MESSAGE = "Reset all unit ranges and building stats to defaults for this scenario?"

    def __init__(self, settings=None, persist=True, game_state=None):
        super().__init__(game_state, self.TITLE)
        self.target_settings = settings if settings is not None else queries.get_scenario_settings()
        self.persist = persist
        self.use_defaults = self.HAS_USE_DEFAULTS and queries.uses_default_building_stats(self.target_settings)
        self.rows = {}
        if any(key == "range" for key, _label in self.CATEGORIES):
            self._load_ranges()
        self._load_buildings()
        self.active_category = self.CATEGORIES[0][0]
        self.list_top = self.panel_rect.y + self.LIST_TOP_OFF
        self.list_view_h = self.panel_rect.bottom - 66 - self.list_top
        self.refresh_ui()

    def _load_ranges(self):
        # The live library can omit families disabled in the previous game.
        with open(c.UNIT_DATA_PATH, encoding="utf-8") as handle:
            unit_library = json.load(handle)
        self.defaults = queries.get_unit_range_defaults(unit_library)
        self.icons = symbol_loader.get_family_symbols(unit_library, self.ROW_ICON_SIZE)
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

    def _load_buildings(self):
        with open(c.BUILDING_DATA_PATH, encoding="utf-8") as handle:
            building_library = json.load(handle)
        self.building_defaults = queries.get_building_stat_defaults(building_library, self.BUILDING_GROUPS)
        self.building_icons = symbol_loader.get_family_symbols(building_library, self.ROW_ICON_SIZE)
        overrides = queries.get_building_stat_overrides(
            (self.target_settings or {}).get(self.BUILDING_SETTING), self.building_defaults)
        self.building_values = {
            name: {key: str(overrides.get(name, {}).get(key, default)) for key, default in fields.items()}
            for name, fields in self.building_defaults.items()
        }
        rows = [(USE_DEFAULTS_ROW, None)] if self.HAS_USE_DEFAULTS else []
        group = None
        for name in self.building_defaults:
            if group is not None and building_library[name].get("group") != group:
                rows.append((None, str(building_library[name].get("group", "")).title()))
            group = building_library[name].get("group")
            rows.append((name, None))
        self.rows["buildings"] = rows

    def toggle_use_defaults(self):
        self.sync_entries()
        self.use_defaults = not self.use_defaults
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
        for name, fields in self.building_values.items():
            draft[name] = {}
            for key, text in fields.items():
                try:
                    value = int(text)
                except ValueError:
                    value = None
                if value is None or value < 0:
                    dialogs.show_warning("Invalid Building Stat", f"{name}: enter a whole number of at least 0.")
                    return None
                draft[name][key] = value
        return queries.get_building_stat_overrides(draft, self.building_defaults)

    def save_all(self):
        self.sync_entries()
        changes = {}
        if "range" in self.rows:
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
            if "range" in self.rows:
                self.values = {family: {key: f"{value:g}" for key, value in fields.items()}
                               for family, fields in self.defaults.items()}
            self.building_values = {name: {key: str(value) for key, value in fields.items()}
                                    for name, fields in self.building_defaults.items()}
            # Remove fields before saving so old text cannot replace reset values.
            self.elements = []
            if self.use_defaults and self.target_settings is not None:
                # save_all skips locked building fields, so clear the saved values here.
                self.target_settings[self.BUILDING_SETTING] = {}
            self.save_all()

        dialogs.ask_yes_no("Confirm Reset", self.RESET_MESSAGE, on_confirm)

    def building_field_x(self, index):
        """Left edge of one building field. Income fields follow cost fields after a wider gap."""
        count = len(queries.BUILDING_STAT_FIELDS)
        width = (count * self.BUILDING_FIELD_WIDTH + (count - 1) * self.BUILDING_FIELD_GAP
                 + self.BUILDING_GROUP_GAP - self.BUILDING_FIELD_GAP)
        x = self.panel_rect.right - self.BUILDING_RIGHT_OFF - width
        x += index * (self.BUILDING_FIELD_WIDTH + self.BUILDING_FIELD_GAP)
        if index >= len(c.ECON_RESOURCE_KEYS):
            x += self.BUILDING_GROUP_GAP - self.BUILDING_FIELD_GAP
        return x

    def refresh_ui(self):
        self.sync_entries()
        p = self.panel_rect
        self.elements = []
        tab_w = c.SIZES["browser_tool"][0]
        for index, (key, label) in enumerate(self.CATEGORIES):
            tab = Button(p.x + self.PAD + index * (tab_w + 10), p.y + self.TAB_Y_OFF, "browser_tool",
                         "green" if key == self.active_category else "light_blue", label,
                         lambda k=key: self.select_category(k), sound_kind="select_category")
            tab.is_selected = key == self.active_category
            self.elements.append(tab)

        rows = self.rows[self.active_category]
        self.scroll_content_rect = pygame.Rect(
            p.x + self.PAD, self.list_top, p.width - 2 * self.PAD, self.list_view_h)
        self._row_layout = list(self.layout_list_rows(
            len(rows), self.ROW_HEIGHT, self.list_top,
            cull_top=self.list_top - 1,
            cull_bottom=self.list_top + self.list_view_h - self.ROW_HEIGHT + 2))
        for index, y in self._row_layout:
            name, key = rows[index]
            if name is None:
                continue
            if name == USE_DEFAULTS_ROW:
                toggle_h = c.SIZES["scenario_setting_button"][1]
                self.add_list_row(make_toggle_button(
                    p.x + self.PAD + self.ROW_LABEL_INSET, y + (self.ROW_HEIGHT - toggle_h) // 2,
                    "scenario_setting_button", "Use Defaults", self.use_defaults,
                    self.toggle_use_defaults, font_preset="button_small"))
                continue
            if self.active_category == "range":
                self._add_field(self.values[name], self.defaults[name], key,
                                p.right - self.START_RIGHT_OFF - self.FIELD_WIDTH, y + 10, self.FIELD_WIDTH)
                if key == "air_range_start":
                    self._add_field(self.values[name], self.defaults[name], "air_range_per_level",
                                    p.right - self.STEP_RIGHT_OFF - self.FIELD_WIDTH, y + 10, self.FIELD_WIDTH)
                continue
            for field_index, field_key in enumerate(queries.BUILDING_STAT_FIELDS):
                self._add_field(self.building_values[name], self.building_defaults[name], field_key,
                                self.building_field_x(field_index), y + (self.ROW_HEIGHT - 28) // 2,
                                self.BUILDING_FIELD_WIDTH, locked=self.use_defaults)

        button_y = p.bottom - 52
        self.elements.extend([
            make_back_button(self.exit_screen, pos=(p.x + self.PAD, button_y)),
            Button(p.centerx - 100, button_y - 5, "medium", "green", "Save All Changes", self.save_all),
            Button(p.right - self.PAD - 200, button_y - 5, "medium", "red",
                   "Reset to Defaults", self.reset_to_defaults),
        ])

    def _add_field(self, values, defaults, key, x, y, width, locked=False):
        """A locked field shows the default value and leaves the draft unchanged."""
        if locked:
            field = TextField(x, y, width, 28, f"{defaults[key]:g}", numeric=True)
            field.disabled = True
        else:
            field = TextField(x, y, width, 28, values[key], numeric=True)
            field.entry_ref = values
            field.entry_key = key
        self.add_list_row(field)

    def additional_events(self, event):
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def draw_body(self, surface):
        p = self.panel_rect
        header_y = self.list_top - 24
        if self.active_category == "range":
            self.label(surface, "Bombardment uses tiles. Aircraft use map pixels. Range = start + (level - 1) x increase.",
                       (p.x + self.PAD, p.y + self.NOTE_Y_OFF))
            for text, x in (("Unit Family", p.x + self.PAD),
                            ("Range / Start", p.right - self.START_RIGHT_OFF - self.FIELD_WIDTH),
                            ("+ per level", p.right - self.STEP_RIGHT_OFF - self.FIELD_WIDTH)):
                self.label(surface, text, (x, header_y))
            return
        small = fonts.get("small")
        self.label(surface, "Building", (p.x + self.PAD, header_y))
        resources = len(c.ECON_RESOURCE_KEYS)
        for group_index, group in enumerate(("Cost", "Income")):
            left = self.building_field_x(group_index * resources)
            right = self.building_field_x((group_index + 1) * resources - 1) + self.BUILDING_FIELD_WIDTH
            text = small.render(group, True, c.UI_TEXT_DIM)
            surface.blit(text, text.get_rect(midtop=((left + right) // 2,
                                                     self.list_top - self.BUILDING_GROUP_HEADER_OFF)))
        for index, field_key in enumerate(queries.BUILDING_STAT_FIELDS):
            x = self.building_field_x(index)
            text = small.render(field_key.split("_", 1)[1].title(), True, c.UI_TEXT_DIM)
            surface.blit(text, text.get_rect(midtop=(x + self.BUILDING_FIELD_WIDTH // 2, header_y)))

    def draw_scroll_backdrop(self, surface):
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
            if index % 2 == 0:
                ui_elements.draw_pixel_background(
                    surface, pygame.Rect(p.x + self.PAD, y, p.width - 2 * self.PAD, self.ROW_HEIGHT),
                    EDITOR_PANEL_STYLES["unit_stats_row"])
            icon_x = p.x + self.PAD + self.ROW_LABEL_INSET
            icons = self.icons if self.active_category == "range" else self.building_icons
            icon = icons.get(queries.get_base_item_name(name))
            if icon is not None:
                center = (icon_x + self.ROW_ICON_SIZE[0] // 2, y + self.ROW_HEIGHT // 2)
                surface.blit(icon, icon.get_rect(center=center))
            label_x = icon_x + self.ROW_ICON_SIZE[0] + self.ROW_ICON_GAP
            if self.active_category == "buildings":
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

    def draw_foreground(self, surface):
        self.draw_list_scrollbar(surface, self.panel_rect.right - 26, self.list_top, self.list_view_h)


class MapFactoryStatsScreen(UnitStatsEditorScreen):
    """Edit one map's default factory costs and income in the map editor.

    New games on the map use these values while Use Defaults is on.
    Factories the map does not change use data/json/building_data.json.
    """
    TITLE = "Factory Stats"
    CATEGORIES = (("buildings", "Factories"),)
    BUILDING_GROUPS = ("industry",)
    BUILDING_SETTING = "map_building_stat_overrides"
    HAS_USE_DEFAULTS = False
    RESET_MESSAGE = "Reset this map's factory stats to the building library defaults?"

    def __init__(self, map_screen):
        super().__init__(settings=map_screen.scenario_settings, persist=False, game_state=map_screen)

    def after_save(self):
        rebuild(self.map_screen)
        self.map_screen.show_feedback("Factory stats updated. Save the map to write them to disk.")


def open_unit_stats_editor(on_done=None, settings=None, persist=True):
    """Open a nonblocking editor with the same settings owner as its caller."""
    screen_runner.run_screen(lambda: UnitStatsEditorScreen(settings=settings, persist=persist),
               on_done=on_done, caption=UnitStatsEditorScreen.TITLE)
