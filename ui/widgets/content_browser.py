"""Shared selection, search, sorting, and details for saved-content screens."""

from dataclasses import dataclass
from datetime import datetime
import os

import pygame

import data.constants as c
from data import queries
from ui.navigation.screen import FolderListState, RefreshingMenuListScreen
from ui.rendering.font_manager import fonts
from ui.widgets.scroll_panes import ScrollPanes
from ui.widgets.text_utils import fit_text, wrap_text
from ui.widgets.ui_elements import Button, TextField, draw_pixel_button, draw_pixel_panel


@dataclass(frozen=True)
class ContentEntry:
    name: str
    path: str
    modified: float
    modified_label: str


class ContentRow(Button):
    """Use standard button input and shading with two cached text lines."""

    def __init__(self, rect, entry, selected, callback):
        super().__init__(rect.x, rect.y, rect.size, "grey", entry.name, callback)
        self.is_selected = selected
        self.lines = [
            fonts.get(preset).render(fit_text(text, fonts.get(preset), rect.width - 28), True, color)
            for text, preset, color in ((entry.name, "normal", c.UI_TEXT_BRIGHT),
                                        (entry.modified_label, "small", c.UI_TEXT_DIM))
        ]

    def draw(self, surface):
        if not self.visible:
            return
        draw_pixel_button(surface, self.rect, self.color, hover_color=self.hover_color,
                          pressed_color=self.pressed_color, selected=self.is_selected, pressed=self.is_pressed)
        y = self.rect.y + 9
        for line in self.lines:
            surface.blit(line, (self.rect.x + 14, y))
            y += line.get_height() + 3


class ContentBrowserScreen(ScrollPanes, RefreshingMenuListScreen, FolderListState):
    """Screens supply their actions. This class owns the common browser controls."""

    MARGIN = 24
    GAP = 16
    LIST_AND_SEARCH_WIDTH = 470
    CATEGORY_Y = 94
    CONTROL_Y = 166
    PANEL_Y = 212
    BOTTOM_MARGIN = 24
    ROW_HEIGHT = 66
    ACTION_HEIGHT = 36
    ACTION_GAP = 8
    PRIMARY_ACTION_SIZE = (220, 44)
    content_label = "items"
    category_caption = ""
    SORTS = (("recent", "Recently modified"), ("name", "Name A-Z"), ("reverse_name", "Name Z-A"))

    def __init__(self):
        super().__init__()
        self.browser_directory = None
        self.entries = []
        self.filtered_entries = []
        self.selected_entry = None
        self.summary_cache = {}
        self.sort_index = 0
        self.directory_error = ""
        self.detail_note = ""
        self.empty_message = "No items available."
        self._search_was_active = False
        self._was_refreshing = False
        self.search_field = TextField(self.MARGIN, self.CONTROL_Y, self.LIST_AND_SEARCH_WIDTH, 38,
                                      on_change=self.filter_entries, on_submit=self.finish_search)

    @property
    def text_input_active(self):
        return self.search_field.active

    def finish_search(self):
        self.search_field.active = False

    def reload_entries(self):
        """Refresh after screen entry, a file operation, or an explicit request."""
        self.browser_directory = None
        self.summary_cache.clear()
        self.refresh_ui()

    def update(self):
        super().update()
        if self._was_refreshing and not self.is_refreshing:
            self.reload_entries()
        self._was_refreshing = self.is_refreshing

    def set_sub_state(self, state):
        self.search_field.text = ""
        self.search_field.active = False
        self.selected_entry = None
        self._scroll_items = 0
        self._scroll_details = 0
        self.cancel_active_drags()
        super().set_sub_state(state)

    def build_browser(self, directory, empty_message, note=""):
        """Build controls from cached entries. Scrolling does not read files."""
        self.empty_message, self.detail_note = empty_message, note
        if self.browser_directory != directory:
            self.browser_directory = directory
            self.directory_error = ""
            self.entries = []
            try:
                os.makedirs(directory, exist_ok=True)
                with os.scandir(directory) as files:
                    for entry in files:
                        if not entry.name.startswith(".") and entry.is_dir():
                            modified = entry.stat().st_mtime
                            label = datetime.fromtimestamp(modified).strftime("Modified %d %b %Y, %H:%M")
                            self.entries.append(ContentEntry(entry.name, entry.path, modified, label))
            except OSError as error:
                self.directory_error = f"Cannot read this directory: {error}"
            self.summary_cache.clear()

        margin, gap = self.MARGIN, self.GAP
        width = c.SCREEN_WIDTH - margin * 2
        list_width = self.LIST_AND_SEARCH_WIDTH
        panel_height = c.SCREEN_HEIGHT - self.PANEL_Y - self.BOTTOM_MARGIN
        self.list_panel = pygame.Rect(margin, self.PANEL_Y, list_width, panel_height)
        self.detail_panel = pygame.Rect(self.list_panel.right + gap, self.PANEL_Y,
                                        width - list_width - gap, panel_height)
        self.action_top = (self.detail_panel.bottom - margin - self.PRIMARY_ACTION_SIZE[1]
                           - self.ACTION_GAP - 2 * (self.ACTION_HEIGHT + self.ACTION_GAP))
        self.regions = {
            "items": pygame.Rect(self.list_panel.x + 12, self.list_panel.y + 42,
                                 self.list_panel.width - 42, self.list_panel.height - 54),
            "details": pygame.Rect(self.detail_panel.x + margin, self.detail_panel.y + 68,
                                   self.detail_panel.width - margin * 2 - 16,
                                   self.action_top - self.detail_panel.y - 84),
        }
        for name, rect in self.regions.items():
            setattr(self, f"_content_{name}", rect)
        self._apply_filter()
        self.elements = [self.search_field]
        self.elements.append(Button(self.list_panel.right + gap, self.CONTROL_Y, (130, 38), "grey", "Clear Search", self.clear_search,
                                    font_preset="button_small"))
        sort_label = self.SORTS[self.sort_index][1]
        self.elements.append(Button(c.SCREEN_WIDTH - margin - 310, self.CONTROL_Y, (310, 38), "grey",
                                    f"Sort: {sort_label}", self.cycle_sort, font_preset="button_small"))
        rect = self.regions["items"]
        limit = min(0, rect.height - len(self.filtered_entries) * self.ROW_HEIGHT)
        self._scroll_items = max(limit, min(0, self.pane_scroll("items")))
        for index, y in self.layout_list_rows(len(self.filtered_entries), self.ROW_HEIGHT, rect.y,
                                              cull_top=rect.top, cull_bottom=rect.bottom,
                                              attr="_scroll_items", limit_attr="_max_items"):
            entry = self.filtered_entries[index]
            row = ContentRow(pygame.Rect(rect.x, y, rect.width, self.ROW_HEIGHT - 6), entry,
                             self.selected_entry == entry, lambda item=entry: self.select_entry(item))
            self.add_pane_row("items", row)
            row.click_guard = lambda r=rect: r.collidepoint(pygame.mouse.get_pos())
        self._prepare_details()

    def _apply_filter(self):
        search = self.search_field.text.strip().casefold()
        entries = [entry for entry in self.entries if search in entry.name.casefold()]
        sort = self.SORTS[self.sort_index][0]
        if sort == "recent":
            entries.sort(key=lambda entry: (-entry.modified, entry.name.casefold(), entry.name))
        else:
            entries.sort(key=lambda entry: (entry.name.casefold(), entry.name), reverse=sort == "reverse_name")
        selected_path = self.selected_entry.path if self.selected_entry else None
        self.filtered_entries = entries
        selected = next((entry for entry in entries if entry.path == selected_path), entries[0] if entries else None)
        if selected != self.selected_entry:
            self._scroll_details = 0
        self.selected_entry = selected

    def filter_entries(self, _text):
        self._scroll_items = 0
        self.refresh_ui()

    def clear_search(self):
        self.search_field.text = ""
        self.filter_entries("")

    def cycle_sort(self):
        self.sort_index = (self.sort_index + 1) % len(self.SORTS)
        self._scroll_items = 0
        self.refresh_ui()

    def select_entry(self, entry):
        self.selected_entry = entry
        self._scroll_details = 0
        self.refresh_ui()

    def _prepare_details(self):
        rect = self.regions["details"]
        self.selection_error = ""
        texts = ["Select an item to see its details."]
        if self.selected_entry:
            entry = self.selected_entry
            if entry.path not in self.summary_cache:
                self.summary_cache[entry.path] = queries.read_saved_content_summary(entry.path)
            summary = self.summary_cache[entry.path]
            self.selection_error = summary["error"]
            texts = [entry.modified_label, *summary["details"]]
            if self.selection_error:
                texts = [self.selection_error, "", *texts]
            if self.detail_note:
                texts.extend(("", self.detail_note))
        font = fonts.get("normal")
        self.detail_lines = [font.render(line, True, c.UI_TEXT_LIGHT)
                             for text in texts for line in wrap_text(text, font, rect.width)]
        self.detail_line_height = font.get_linesize() + 5
        self._max_details = min(0, rect.height - len(self.detail_lines) * self.detail_line_height)
        self._scroll_details = max(self._max_details, min(0, self.pane_scroll("details")))
        heading = self.selected_entry.name if self.selected_entry else "Details"
        self.detail_heading = fonts.get("heading2").render(
            fit_text(heading, fonts.get("heading2"), self.detail_panel.width - self.MARGIN * 2), True, c.UI_TEXT_BRIGHT)

    @property
    def selection_can_open(self):
        return self.selected_entry is not None and not self.selection_error

    def call_selected(self, handler):
        if self.selected_entry:
            handler(self.selected_entry.name)

    def add_browser_action(self, label, callback, slot, color="grey", *, enabled=True, sound_kind="click"):
        """Place a screen's action in the shared details panel."""
        width = (self.detail_panel.width - self.MARGIN * 2 - self.ACTION_GAP) // 2
        x = self.detail_panel.x + self.MARGIN + slot % 2 * (width + self.ACTION_GAP)
        y = self.action_top + slot // 2 * (self.ACTION_HEIGHT + self.ACTION_GAP)
        button = Button(x, y, (width, self.ACTION_HEIGHT), color, label, callback,
                        font_preset="button_small", sound_kind=sound_kind)
        button.apply_state(enabled=enabled and self.selected_entry is not None, color=color)
        self.elements.append(button)
        return button

    def add_primary_action(self, label):
        """Place the selected item's primary action below the other actions."""
        width, height = self.PRIMARY_ACTION_SIZE
        button = Button(self.detail_panel.right - self.MARGIN - width,
                        self.detail_panel.bottom - self.MARGIN - height,
                        (width, height), "green", label, self.activate_selected, sound_kind=None)
        button.apply_state(enabled=self.selection_can_open, color="green")
        self.elements.append(button)
        return button

    def finish_rename(self, old_name, new_name):
        super().finish_rename(old_name, new_name)
        name = (new_name or "").strip()
        path = os.path.join(self.managed_dir, name)
        if name and not os.path.exists(os.path.join(self.managed_dir, old_name)) and os.path.isdir(path):
            self.selected_entry = ContentEntry(name, path, 0, "")
        self.reload_entries()

    def delete_item(self, name):
        super().delete_item(name)
        self.reload_entries()

    def handle_back_key(self):
        if self.search_field.active:
            self.finish_search()
        else:
            super().handle_back_key()

    def additional_events(self, event):
        self.route_pane_scroll(event)
        # Enter submits a focused search field without opening a game.
        if event.type != pygame.KEYDOWN or self.search_field.active:
            return
        if event.key == pygame.K_RETURN:
            if not self._search_was_active:
                self.activate_selected()
        elif event.key in (pygame.K_UP, pygame.K_DOWN) and self.filtered_entries:
            index = self.filtered_entries.index(self.selected_entry)
            index = max(0, min(len(self.filtered_entries) - 1, index + (1 if event.key == pygame.K_DOWN else -1)))
            rect = self.regions["items"]
            scroll = self.pane_scroll("items")
            top = index * self.ROW_HEIGHT + scroll
            if top < 0:
                self._scroll_items = -index * self.ROW_HEIGHT
            elif top + self.ROW_HEIGHT > rect.height:
                self._scroll_items = rect.height - (index + 1) * self.ROW_HEIGHT
            self.select_entry(self.filtered_entries[index])

    def handle_events(self, events):
        if self.is_refreshing:
            return
        for event in events:
            self._search_was_active = self.search_field.active
            super().handle_events([event])

    def draw_elements(self, surface):
        self.draw_panes(surface, foregrounds={"details": self._draw_details})

    def _draw_details(self, surface):
        rect = self.regions["details"]
        for index, line in enumerate(self.detail_lines):
            y = rect.y + self.pane_scroll("details") + index * self.detail_line_height
            if y + self.detail_line_height > rect.top and y < rect.bottom:
                surface.blit(line, (rect.x, y))

    def additional_draw(self, surface):
        for rect in (self.list_panel, self.detail_panel):
            draw_pixel_panel(surface, rect, (35, 40, 52), recessed=True)
        font = fonts.get("normal")
        if self.category_caption:
            surface.blit(font.render(self.category_caption, True, c.UI_TEXT_LIGHT), (self.MARGIN, self.CATEGORY_Y))
        surface.blit(font.render("Search by name", True, c.UI_TEXT_DIM), (self.MARGIN, self.CONTROL_Y - 23))
        surface.blit(font.render("Name / Last modified", True, c.UI_TEXT_DIM),
                     (self.list_panel.x + 14, self.list_panel.y + 12))
        surface.blit(self.detail_heading, (self.detail_panel.x + self.MARGIN, self.detail_panel.y + 20))
        count = f"{len(self.filtered_entries)} of {len(self.entries)} {self.content_label}"
        count_surface = font.render(count, True, c.UI_TEXT_LIGHT)
        surface.blit(count_surface, (self.list_panel.right - 14 - count_surface.get_width(),
                                     self.list_panel.y + 12))
        if not self.filtered_entries:
            message = self.directory_error or ("No matching items. Clear Search to show all items."
                                               if self.search_field.text.strip() else self.empty_message)
            for index, line in enumerate(wrap_text(message, font, self.regions["items"].width - 24)):
                surface.blit(font.render(line, True, c.UI_TEXT_LIGHT),
                             (self.regions["items"].x + 12, self.regions["items"].y + 20 + index * 26))
        for name, rect in self.regions.items():
            self.draw_pane_scrollbar(surface, name, rect.right + 7, rect.top, rect.height)
