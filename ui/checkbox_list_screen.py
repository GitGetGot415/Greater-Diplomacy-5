"""Native pygame replacement for the tkinter "scrollable frame full of
tk.Checkbutton" panels.

Four tool windows were the same widget wearing different labels -- pick players
to skip, pick keys to regenerate, pick researched units to expose, pick which
country fields a data refresh may overwrite -- so they now share this screen.
Confirm hands back the checked keys; cancelling never calls on_confirm.
"""
import pygame
from gameState import GameState
import data.constants as c
from ui.bars import ui_bars
from ui_elements import Button
from ui.confirm_dialog import _wrap_text
from map_logic.rendering.font_manager import fonts


class CheckboxItem:
    """One toggleable row. `note` is right-aligned status text (e.g. [SUBMITTED])."""
    def __init__(self, key, label, checked=False, note="", note_color=(200, 200, 200)):
        self.key = key
        self.label = label
        self.checked = checked
        self.note = note
        self.note_color = note_color


class SectionHeader:
    """A non-clickable divider labelling the rows beneath it."""
    def __init__(self, label):
        self.label = label


class CheckboxListScreen(GameState):
    PANEL_SIZE = (760, 620)
    ROW_HEIGHT = 30
    PAD = 20

    def __init__(self, game_state, title, prompt, items, on_confirm,
                 confirm_label="Confirm", show_select_all=True, extra_buttons=None,
                 footnote=None):
        super().__init__()
        # Only used to resolve custom keybinds (BACK/ORDERS); may not carry feedback_text.
        self.map_screen = getattr(game_state, "map_screen", None) or game_state
        self.title = title
        self.on_confirm = on_confirm
        self.confirm_label = confirm_label
        self.show_select_all = show_select_all
        # Each entry is (label, color_preset, callback(screen)).
        self.extra_buttons = list(extra_buttons or [])
        self.footnote = footnote

        surface = pygame.display.get_surface()
        self.background = surface.copy() if surface else None

        panel_w, panel_h = self.PANEL_SIZE
        self.panel_rect = pygame.Rect(0, 0, panel_w, panel_h)
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)

        self.prompt_lines = _wrap_text(prompt, fonts.get("normal"), panel_w - 2 * self.PAD) if prompt else []
        self._layout()

        self.items = []
        self._row_layout = []
        self.set_items(items)

    # ------------------------------------------------------------------ #
    #                              LAYOUT                                #
    # ------------------------------------------------------------------ #

    def _layout(self):
        p = self.panel_rect
        line_h = fonts.get("normal").get_height()
        self.prompt_top = p.y + 52
        y = self.prompt_top + len(self.prompt_lines) * (line_h + 2)

        self.tool_y = y + 6 if (self.show_select_all or self.extra_buttons) else y
        if self.show_select_all or self.extra_buttons:
            y = self.tool_y + c.SIZES["checkbox_tool"][1] + 10

        self.list_top = y
        footnote_h = 24 if self.footnote else 0
        self.list_view_h = (p.bottom - 66 - footnote_h) - self.list_top
        self.row_x = p.x + self.PAD

    # ------------------------------------------------------------------ #
    #                               ITEMS                                #
    # ------------------------------------------------------------------ #

    def set_items(self, items):
        """Swaps the rows in, carrying every still-present key's tick over.

        Lets an extra button (Load Moves) refresh the list without the user
        losing the boxes they already ticked.
        """
        checked = {i.key for i in self.items if isinstance(i, CheckboxItem) and i.checked}
        self.items = list(items)
        if checked:
            for item in self.items:
                if isinstance(item, CheckboxItem) and item.key in checked:
                    item.checked = True
        self.scroll_y = 0
        self.refresh_ui()

    def checked_keys(self):
        return [i.key for i in self.items if isinstance(i, CheckboxItem) and i.checked]

    def toggle(self, item):
        item.checked = not item.checked
        self.refresh_ui()

    def _set_all(self, value):
        for item in self.items:
            if isinstance(item, CheckboxItem):
                item.checked = value
        self.refresh_ui()

    def reload(self, items):
        """Convenience for extra-button callbacks that rebuild the row list."""
        self.set_items(items)

    # ------------------------------------------------------------------ #
    #                              CONFIRM                               #
    # ------------------------------------------------------------------ #

    def _confirm(self):
        self.on_confirm(self.checked_keys())
        self.exit_screen()

    # ------------------------------------------------------------------ #
    #                             RENDERING                              #
    # ------------------------------------------------------------------ #

    def refresh_ui(self):
        p = self.panel_rect
        self.elements = []

        tool_w, _tool_h = c.SIZES["checkbox_tool"]
        x = p.x + self.PAD
        if self.show_select_all:
            self.elements.append(Button(x, self.tool_y, "checkbox_tool", "light_blue", "Select All",
                                        lambda: self._set_all(True), font_preset="normal"))
            x += tool_w + 8
            self.elements.append(Button(x, self.tool_y, "checkbox_tool", "light_blue", "Deselect All",
                                        lambda: self._set_all(False), font_preset="normal"))
            x += tool_w + 8
        for label, color, callback in self.extra_buttons:
            self.elements.append(Button(x, self.tool_y, "checkbox_tool", color, label,
                                        lambda cb=callback: cb(self), font_preset="normal"))
            x += tool_w + 8

        row_w, _row_h = c.SIZES["checkbox_row"]
        cull_top, cull_bottom = self.list_top - 1, self.list_top + self.list_view_h - self.ROW_HEIGHT + 2
        self.scroll_content_rect = pygame.Rect(p.x + self.PAD, self.list_top, p.width - 2 * self.PAD, self.list_view_h)
        self._row_layout = list(self.layout_list_rows(
            len(self.items), self.ROW_HEIGHT, self.list_top, view_h=self.list_view_h,
            # Cull a row as soon as it would hang past the bottom of the view,
            # since the list height is derived from the panel and rarely divides evenly.
            cull_top=cull_top, cull_bottom=cull_bottom))

        for i, y in self._row_layout:
            item = self.items[i]
            if isinstance(item, SectionHeader):
                continue  # Drawn as a label in draw(), not as a clickable row.
            mark = "[X]" if item.checked else "[  ]"
            btn = Button(self.row_x, y, "checkbox_row", "green" if item.checked else "blue",
                         f"{mark} {item.label}", lambda it=item: self.toggle(it),
                         font_preset="button_small")
            btn.is_selected = item.checked
            btn.is_scrollable = True
            btn.click_guard = self.scroll_click_guard
            self.elements.append(btn)

        btn_y = p.bottom - 52
        self.elements.append(Button(p.x + self.PAD, btn_y, "small", "red", "Cancel", self.exit_screen))
        confirm_w, _h = c.SIZES["medium"]
        self.elements.append(Button(p.right - self.PAD - confirm_w, btn_y - 5, "medium", "green",
                                    self.confirm_label, self._confirm))

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
        y = self.prompt_top
        for line in self.prompt_lines:
            surf = font.render(line, True, (215, 215, 215))
            surface.blit(surf, (p.x + self.PAD, y))
            y += font.get_height() + 2

        if not self.items:
            msg = font.render("Nothing to show.", True, (200, 200, 200))
            surface.blit(msg, msg.get_rect(center=(p.centerx, self.list_top + self.list_view_h // 2)))

        for el in self.elements:
            if not getattr(el, "is_scrollable", False):
                el.draw(surface)

        # Section labels and per-row status text sit over the rows, so they are
        # drawn after the buttons (both clipped/cropped together at the list boundary).
        header_font = fonts.get("normal")
        note_font = fonts.get("small")
        row_w, _row_h = c.SIZES["checkbox_row"]
        with ui_bars.clip_scroll_region(surface, self.scroll_content_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
            for el in self.elements:
                if getattr(el, "is_scrollable", False):
                    el.draw(surface)

            for i, row_y in self._row_layout:
                item = self.items[i]
                if isinstance(item, SectionHeader):
                    surf = header_font.render(item.label, True, c.COLOR_GOLD_HIGHLIGHT)
                    surface.blit(surf, (self.row_x + 4, row_y + 5))
                elif item.note:
                    surf = note_font.render(item.note, True, item.note_color)
                    surface.blit(surf, surf.get_rect(midright=(self.row_x + row_w - 10,
                                                               row_y + self.ROW_HEIGHT // 2)))

        if self.footnote:
            surf = note_font.render(self.footnote, True, (230, 180, 120))
            surface.blit(surf, surf.get_rect(center=(p.centerx, p.bottom - 74)))

        self.draw_list_scrollbar(surface, p.right - 26, self.list_top, self.list_view_h)
