"""Native pygame replacement for the tkinter Construction Turns Editor.

Every base item type gets a row with its turn count inline, replacing the old
listbox + "Apply locally" round trip -- everything on screen is editable and
Save All writes both tabs at once. A row left at its library default stores no
override, so defaults keep tracking the unit/building libraries.
"""
import sys
import os
import json

# Add the parent directory (project root) to the Python path so this stays runnable standalone
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pygame
from gameState import GameState
import data.constants as c
from data import queries
from ui import confirm_dialog
from ui.bars import ui_bars
from ui_elements import Button, TextField
from map_logic.rendering.font_manager import fonts


class TurnEditorScreen(GameState):
    PANEL_SIZE = (900, 640)
    ROW_HEIGHT = 34
    PAD = 20
    LIST_TOP_OFF = 120
    CHECK_SIZE = 30

    def __init__(self):
        super().__init__()
        self.title = "Construction Turns Editor"

        self.settings = queries.get_scenario_settings() or {}

        # Read straight off disk rather than queries._load_cached_json(): that
        # cache is the SAME dict object load_map.py prunes in place for a
        # loaded game's disabled units/buildings, so after playing a game with
        # something disabled, the cached library would be missing it entirely
        # -- its row would vanish from this editor with no way to click it
        # back on. This editor always needs the full, unpruned list.
        with open(c.UNIT_DATA_PATH, "r") as f:
            full_unit_library = json.load(f)
        with open(c.BUILDING_DATA_PATH, "r") as f:
            full_building_library = json.load(f)

        self.tabs = {
            "unit": self._build_tab(full_unit_library,
                                    self.settings.setdefault("unit_turn_overrides", {}),
                                    self.settings.setdefault("unit_disabled", []),
                                    "production_time", "Unit Type"),
            "building": self._build_tab(full_building_library,
                                        self.settings.setdefault("building_turn_overrides", {}),
                                        self.settings.setdefault("building_disabled", []),
                                        "time", "Building Type"),
        }
        self.active_tab = "unit"

        surface = pygame.display.get_surface()
        self.background = surface.copy() if surface else None

        panel_w, panel_h = self.PANEL_SIZE
        self.panel_rect = pygame.Rect(0, 0, panel_w, panel_h)
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)

        self.list_top = self.panel_rect.y + self.LIST_TOP_OFF
        self.list_view_h = (self.panel_rect.bottom - 66) - self.list_top

        self.refresh_ui()

    def _build_tab(self, library, overrides, disabled_list, turn_key, label):
        """Collapses a library to its base types, each with a default and a current value.

        Variants of one base type ("Infantry Type 1936/1939/...") always shared a
        turn count, which is why the editor works on base types rather than items.
        """
        base_types = {}
        for name in library:
            base_types.setdefault(queries.get_base_item_name(name), []).append(name)

        defaults, values = {}, {}
        for btype, names in base_types.items():
            defaults[btype] = library[names[0]].get(turn_key, 0)
            values[btype] = str(overrides.get(btype, defaults[btype]))

        return {"label": label, "names": sorted(base_types, key=str.lower),
                "defaults": defaults, "values": values, "overrides": overrides,
                "disabled_set": set(disabled_list)}

    # ------------------------------------------------------------------ #
    #                               EDITING                              #
    # ------------------------------------------------------------------ #

    @property
    def tab(self):
        return self.tabs[self.active_tab]

    @property
    def listening_for(self):
        """Keeps the global BACK keybind from closing the editor mid-edit."""
        return any(getattr(el, "turn_key", None) and el.active for el in self.elements)

    def _sync_entries(self):
        """Pulls live text out of the on-screen fields before they are rebuilt or saved."""
        for el in self.elements:
            key = getattr(el, "turn_key", None)
            if key is not None:
                self.tab["values"][key] = el.text

    def select_tab(self, key):
        self._sync_entries()
        self.active_tab = key
        self.scroll_y = 0
        self.refresh_ui()

    def toggle_disabled(self, btype):
        disabled_set = self.tab["disabled_set"]
        if btype in disabled_set:
            disabled_set.discard(btype)
        else:
            disabled_set.add(btype)
        self.refresh_ui()

    def save_all(self):
        self._sync_entries()
        for tab in self.tabs.values():
            overrides = tab["overrides"]
            overrides.clear()
            for btype in tab["names"]:
                try:
                    value = max(1, int(tab["values"][btype]))
                except ValueError:
                    continue
                tab["values"][btype] = str(value)
                if value != tab["defaults"][btype]:
                    overrides[btype] = value

        self.settings["unit_turn_overrides"] = self.tabs["unit"]["overrides"]
        self.settings["building_turn_overrides"] = self.tabs["building"]["overrides"]
        self.settings["unit_disabled"] = sorted(self.tabs["unit"]["disabled_set"])
        self.settings["building_disabled"] = sorted(self.tabs["building"]["disabled_set"])
        queries.save_scenario_settings(self.settings)
        confirm_dialog.show_success("Saved", "Successfully saved overrides to scenario settings.")
        self.exit_screen()

    def reset_to_defaults(self):
        def on_confirm(ok):
            if not ok:
                return
            for tab in self.tabs.values():
                tab["overrides"].clear()
                tab["disabled_set"].clear()
                tab["values"] = {btype: str(default) for btype, default in tab["defaults"].items()}
            # Drop the on-screen fields so save_all's _sync_entries() can't pull
            # their stale (pre-reset) text back over the defaults we just set.
            self.elements = []
            self.save_all()

        confirm_dialog.ask_yes_no(
            "Confirm Reset",
            "Are you sure you want to clear overrides and reset to defaults? "
            "This applies to the current scenario.",
            on_confirm)

    # ------------------------------------------------------------------ #
    #                             RENDERING                              #
    # ------------------------------------------------------------------ #

    def refresh_ui(self):
        self._sync_entries()
        p = self.panel_rect
        self.elements = []

        tab_w, _tab_h = c.SIZES["browser_tool"]
        for i, (key, label) in enumerate((("unit", "Units"), ("building", "Buildings"))):
            btn = Button(p.x + self.PAD + i * (tab_w + 10), p.y + 56, "browser_tool",
                         "green" if key == self.active_tab else "light_blue", label,
                         lambda k=key: self.select_tab(k))
            btn.is_selected = key == self.active_tab
            self.elements.append(btn)

        names = self.tab["names"]
        cull_top, cull_bottom = self.list_top - 1, self.list_top + self.list_view_h - self.ROW_HEIGHT + 2
        self.scroll_content_rect = pygame.Rect(p.x + self.PAD, self.list_top, p.width - 2 * self.PAD, self.list_view_h)
        # Don't pass view_h explicitly here -- it would let layout_list_rows compute
        # max_scroll against the full (taller) list_view_h while cull_bottom (used
        # to decide what's actually visible/clickable) is shorter by ROW_HEIGHT-2,
        # leaving the last row permanently a sliver short of being scrollable into
        # view. Omitting it makes the function derive view_h from cull_bottom
        # itself, so the scroll limit and the visible boundary agree.
        self._row_layout = list(self.layout_list_rows(
            len(names), self.ROW_HEIGHT, self.list_top,
            cull_top=cull_top, cull_bottom=cull_bottom))

        disabled_set = self.tab["disabled_set"]
        check_x = p.right - self.PAD - 34
        for i, y in self._row_layout:
            btype = names[i]
            field = TextField(check_x - 10 - 100, y, 100, 28, self.tab["values"][btype], numeric=True)
            field.turn_key = btype
            field.is_scrollable = True
            field.click_guard = self.scroll_click_guard
            self.elements.append(field)

            is_enabled = btype not in disabled_set
            check_btn = Button(check_x, y + (self.ROW_HEIGHT - self.CHECK_SIZE) // 2, "tiny_square",
                               "green" if is_enabled else "red", "ON" if is_enabled else "OFF",
                               lambda bt=btype: self.toggle_disabled(bt), font_preset="button_small")
            check_btn.is_scrollable = True
            check_btn.click_guard = self.scroll_click_guard
            self.elements.append(check_btn)

        btn_y = p.bottom - 52
        self.elements.append(Button(p.x + self.PAD, btn_y, "small", "red", "Back", self.exit_screen))
        self.elements.append(Button(p.centerx - 100, btn_y - 5, "medium", "green", "Save All Changes", self.save_all))
        self.elements.append(Button(p.right - self.PAD - 200, btn_y - 5, "medium", "red",
                                    "Reset to Defaults", self.reset_to_defaults))

    def additional_events(self, event):
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def draw(self, surface):
        if self.background:
            surface.blit(self.background, (0, 0))
        else:
            surface.fill((20, 20, 28))
        ui_bars.draw_fullscreen_overlay(surface, 190)

        p = self.panel_rect
        ui_bars.draw_modal_box(surface, p, bg_color=(35, 35, 45),
                               border_color=(100, 150, 255), border_width=3)
        ui_bars.draw_centered_title(surface, self.title, p.y + 14, "heading2")

        font = fonts.get("normal")
        small = fonts.get("small")
        surface.blit(small.render(self.tab["label"], True, c.UI_TEXT_DIM), (p.x + self.PAD, self.list_top - 20))
        check_x = p.right - self.PAD - 34
        turns_hdr = small.render("Turns to Construct", True, c.UI_TEXT_DIM)
        surface.blit(turns_hdr, turns_hdr.get_rect(midright=(check_x - 10, self.list_top - 12)))
        enabled_hdr = small.render("Enabled", True, c.UI_TEXT_DIM)
        surface.blit(enabled_hdr, enabled_hdr.get_rect(center=(check_x + self.CHECK_SIZE // 2, self.list_top - 12)))

        names = self.tab["names"]
        if not names:
            msg = font.render("Nothing to edit.", True, c.UI_TEXT_LIGHT)
            surface.blit(msg, msg.get_rect(center=(p.centerx, self.list_top + self.list_view_h // 2)))

        for el in self.elements:
            if not getattr(el, "is_scrollable", False):
                el.draw(surface)

        with ui_bars.clip_scroll_region(surface, self.scroll_content_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
            for i, y in self._row_layout:
                btype = names[i]
                if i % 2 == 0:
                    pygame.draw.rect(surface, (44, 44, 56),
                                     pygame.Rect(p.x + self.PAD, y, p.width - 2 * self.PAD, self.ROW_HEIGHT))

                label = font.render(btype, True, (225, 225, 225))
                surface.blit(label, label.get_rect(midleft=(p.x + self.PAD + 8, y + self.ROW_HEIGHT // 2)))

                default = self.tab["defaults"][btype]
                hint = small.render(f"default: {default}", True, (150, 150, 165))
                surface.blit(hint, hint.get_rect(midright=(p.right - self.PAD - 159, y + self.ROW_HEIGHT // 2)))

            for el in self.elements:
                if getattr(el, "is_scrollable", False):
                    el.draw(surface)

        self.draw_list_scrollbar(surface, p.right - 26, self.list_top, self.list_view_h)


def open_turn_editor(on_done=None):
    """Construction-turns editor, usable in-game or standalone (see ui/screen_runner.py).

    `on_done` lets a caller (e.g. Scenario Settings) refresh itself once the
    editor closes, since it runs as a non-blocking modal (see ui/modal_stack.py).
    """
    from ui.screen_runner import run_screen
    run_screen(TurnEditorScreen, on_done=on_done, caption="Construction Turns Editor")


if __name__ == "__main__":
    open_turn_editor()
