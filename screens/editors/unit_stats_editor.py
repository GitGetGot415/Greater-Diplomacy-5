"""Edit scenario unit ranges in a draft, separate from the active game library."""
import json

import pygame

from data import queries
import data.constants as c
from ui.rendering import symbol_loader
from ui.rendering.font_manager import fonts
from ui import dialogs as confirm_dialog
from ui.bars import ui_bars
from ui.navigation.modal_screen import ModalScreen
from ui.widgets.ui_elements import Button, TextField, make_back_button

from ui.navigation import screen_runner


class UnitStatsEditorScreen(ModalScreen):
    PANEL_SIZE = (900, 640)
    PAD = 20
    ROW_HEIGHT = 54
    LIST_TOP_OFF = 160
    FIELD_WIDTH = 110
    START_RIGHT_OFF = 210
    STEP_RIGHT_OFF = 60
    ROW_ICON_SIZE = (52, 40)
    ROW_ICON_GAP = 10
    ROW_LABEL_INSET = 8
    DIVIDER_LABEL_GAP = 12

    def __init__(self, settings=None, persist=True):
        super().__init__(None, "Unit Stats Editor")
        self.target_settings = settings if settings is not None else queries.get_scenario_settings()
        self.persist = persist
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
        self.rows = []
        for key in ("bombard_range", "air_range_start"):
            group = [(family, key) for family, fields in families if key in fields]
            if self.rows and group:
                self.rows.append((None, None))
            self.rows.extend(group)
        self.list_top = self.panel_rect.y + self.LIST_TOP_OFF
        self.list_view_h = self.panel_rect.bottom - 66 - self.list_top
        self.refresh_ui()

    def save_all(self):
        self.sync_entries()
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
                    confirm_dialog.show_warning(
                        "Invalid Range", f"{family}: enter a whole number of at least {minimum}.")
                    return
                draft[family][key] = value
        overrides = queries.get_unit_range_overrides({"unit_range_overrides": draft}, self.defaults)
        if self.target_settings is not None:
            self.target_settings["unit_range_overrides"] = overrides
        if self.persist:
            queries.save_scenario_settings(
                self.target_settings if self.target_settings is not None else {"unit_range_overrides": overrides})
        confirm_dialog.show_success("Saved", "Successfully saved unit ranges to scenario settings.")
        self.exit_screen()

    def reset_to_defaults(self):
        def on_confirm(ok):
            if not ok:
                return
            self.values = {family: {key: f"{value:g}" for key, value in fields.items()}
                           for family, fields in self.defaults.items()}
            # Remove fields before saving so old text cannot replace reset values.
            self.elements = []
            self.save_all()

        confirm_dialog.ask_yes_no(
            "Confirm Reset", "Reset all unit ranges to defaults for this scenario?", on_confirm)

    def refresh_ui(self):
        self.sync_entries()
        p = self.panel_rect
        self.elements = []
        tab = Button(p.x + self.PAD, p.y + 56, "browser_tool", "green", "Range", lambda: None)
        tab.is_selected = True
        self.elements.append(tab)

        self.scroll_content_rect = pygame.Rect(
            p.x + self.PAD, self.list_top, p.width - 2 * self.PAD, self.list_view_h)
        self._row_layout = list(self.layout_list_rows(
            len(self.rows), self.ROW_HEIGHT, self.list_top,
            cull_top=self.list_top - 1,
            cull_bottom=self.list_top + self.list_view_h - self.ROW_HEIGHT + 2))
        for index, y in self._row_layout:
            family, key = self.rows[index]
            if family is None:
                continue
            self._add_field(family, key, p.right - self.START_RIGHT_OFF - self.FIELD_WIDTH, y + 10)
            if key == "air_range_start":
                self._add_field(family, "air_range_per_level",
                                p.right - self.STEP_RIGHT_OFF - self.FIELD_WIDTH, y + 10)

        button_y = p.bottom - 52
        self.elements.extend([
            make_back_button(self.exit_screen, pos=(p.x + self.PAD, button_y)),
            Button(p.centerx - 100, button_y - 5, "medium", "green", "Save All Changes", self.save_all),
            Button(p.right - self.PAD - 200, button_y - 5, "medium", "red",
                   "Reset to Defaults", self.reset_to_defaults),
        ])

    def _add_field(self, family, key, x, y):
        field = TextField(x, y, self.FIELD_WIDTH, 28, self.values[family][key], numeric=True)
        field.entry_ref = self.values[family]
        field.entry_key = key
        field.is_scrollable = True
        field.click_guard = self.scroll_click_guard
        self.elements.append(field)

    def additional_events(self, event):
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def draw_body(self, surface):
        p = self.panel_rect
        self.label(surface, "Bombardment uses tiles. Aircraft use map pixels. Range = start + (level - 1) x increase.",
                   (p.x + self.PAD, p.y + 102))
        for text, x in (("Unit Family", p.x + self.PAD),
                        ("Range / Start", p.right - self.START_RIGHT_OFF - self.FIELD_WIDTH),
                        ("+ per level", p.right - self.STEP_RIGHT_OFF - self.FIELD_WIDTH)):
            self.label(surface, text, (x, self.list_top - 24))

    def draw_elements(self, surface):
        p = self.panel_rect
        font, small = fonts.get("normal"), fonts.get("small")
        for element in self.elements:
            if not getattr(element, "is_scrollable", False):
                element.draw(surface)
        with ui_bars.clip_scroll_region(surface, self.scroll_content_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
            for index, y in self._row_layout:
                family, key = self.rows[index]
                if family is None:
                    label = font.render("Aircraft", True, c.UI_TEXT_DIM)
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
                    pygame.draw.rect(surface, (44, 44, 56),
                                     (p.x + self.PAD, y, p.width - 2 * self.PAD, self.ROW_HEIGHT))
                icon_x = p.x + self.PAD + self.ROW_LABEL_INSET
                icon = self.icons.get(family)
                if icon is not None:
                    center = (icon_x + self.ROW_ICON_SIZE[0] // 2, y + self.ROW_HEIGHT // 2)
                    surface.blit(icon, icon.get_rect(center=center))
                label_x = icon_x + self.ROW_ICON_SIZE[0] + self.ROW_ICON_GAP
                surface.blit(font.render(family, True, c.UI_TEXT_LIGHT), (label_x, y + 4))
                default = self.defaults[family]
                if key == "bombard_range":
                    hint = f"Bombardment (tiles); default: {default[key]:g}"
                else:
                    hint = (f"Flight (map px); default: {default[key]:g}"
                            f" + {default['air_range_per_level']:g} per level")
                surface.blit(small.render(hint, True, c.UI_TEXT_DIM), (label_x, y + 29))
            for element in self.elements:
                if getattr(element, "is_scrollable", False):
                    element.draw(surface)

    def draw_foreground(self, surface):
        self.draw_list_scrollbar(surface, self.panel_rect.right - 26, self.list_top, self.list_view_h)


def open_unit_stats_editor(on_done=None, settings=None, persist=True):
    """Open a nonblocking editor with the same settings owner as its caller."""
    screen_runner.run_screen(lambda: UnitStatsEditorScreen(settings=settings, persist=persist),
               on_done=on_done, caption="Unit Stats Editor")
