"""Shared selection, search, sorting, and details for saved-content screens."""

from dataclasses import dataclass
from datetime import datetime
import os

import pygame

import data.constants as c
from data import queries
from ui.navigation.screen import FolderListState, RefreshingMenuListScreen
from ui.rendering import symbol_loader
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
        super().__init__(rect.x, rect.y, rect.size, "grey", entry.name, callback, sound_kind="select_sub_category")
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
    CLEAR_BUTTON_WIDTH = 60
    SORT_BUTTON_WIDTH = 120
    CONTROL_HEIGHT = 38
    CONTROL_GAP = 6
    SEARCH_FONT = "small"
    CATEGORY_Y = 94
    CONTROL_Y = 166
    PANEL_Y = 212
    BOTTOM_MARGIN = 24
    ROW_HEIGHT = 66
    ACTION_HEIGHT = 36
    ACTION_GAP = 8
    ACTION_COUNT = 4
    PRIMARY_ACTION_HEIGHT = 90
    PREVIEW_HEIGHT = 180
    show_map_preview = True
    content_label = "items"
    category_caption = ""
    SORTS = (("recent", "Modified"), ("name", "A-Z"), ("reverse_name", "Z-A"))
    # A screen sets this to (label, callback) to start its list with an action row.
    leading_row = None

    @property
    def leading_row_count(self):
        return 0 if self.leading_row is None else 1

    def __init__(self):
        super().__init__()
        self.browser_directory = None
        self.entries = []
        self.filtered_entries = []
        self.selected_entry = None
        self.summary_cache = {}
        self.preview_cache = {}
        self.sort_index = 0
        self.directory_error = ""
        self.detail_note = ""
        self.empty_message = "No items available."
        self._search_was_active = False
        self._was_refreshing = False
        self.search_field = TextField(self.MARGIN, self.CONTROL_Y,
                                      self.LIST_AND_SEARCH_WIDTH, self.CONTROL_HEIGHT,
                                      on_change=self.filter_entries, on_submit=self.finish_search,
                                      font_preset=self.SEARCH_FONT)

    @property
    def text_input_active(self):
        return self.search_field.active

    def finish_search(self):
        self.search_field.active = False

    def reload_entries(self):
        """Refresh after screen entry, a file operation, or an explicit request."""
        self.browser_directory = None
        self.summary_cache.clear()
        self.preview_cache.clear()
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
            self.entries, self.directory_error = self.read_directory(directory)
            self.summary_cache.clear()
            self.preview_cache.clear()
            self.prepare_entries()

        self._apply_filter()
        self.layout_browser()
        self.elements = [self.search_field]
        self.build_browser_controls()
        rect = self.regions["items"]
        offset = self.leading_row_count
        row_count = len(self.filtered_entries) + offset
        limit = min(0, rect.height - row_count * self.ROW_HEIGHT)
        self._scroll_items = max(limit, min(0, self.pane_scroll("items")))
        for index, y in self.layout_list_rows(row_count, self.ROW_HEIGHT, rect.y,
                                              cull_top=rect.top, cull_bottom=rect.bottom,
                                              attr="_scroll_items", limit_attr="_max_items"):
            row_rect = pygame.Rect(rect.x, y, rect.width, self.ROW_HEIGHT - 6)
            if index < offset:
                label, callback = self.leading_row
                row = Button(*row_rect.topleft, row_rect.size, "green", label, callback, font_preset="normal")
            else:
                row = self.make_content_row(row_rect, self.filtered_entries[index - offset])
            self.add_pane_row("items", row)
            row.click_guard = lambda r=rect: r.collidepoint(pygame.mouse.get_pos())
        self._prepare_details()

    def read_directory(self, directory):
        """Read visible folders. Call only at entry, refresh, or category changes."""
        entries = []
        try:
            os.makedirs(directory, exist_ok=True)
            with os.scandir(directory) as files:
                for entry in files:
                    if not entry.name.startswith(".") and entry.is_dir():
                        modified = entry.stat().st_mtime
                        label = datetime.fromtimestamp(modified).strftime("Modified %d %b %Y, %H:%M")
                        entries.append(ContentEntry(entry.name, entry.path, modified, label))
        except OSError as error:
            return entries, f"Cannot read this directory: {error}"
        return entries, ""

    def prepare_entries(self):
        """Prepare extra presentation data when the directory changes."""

    def layout_browser(self):
        """Place the list, details, and input regions."""
        margin, gap = self.MARGIN, self.GAP
        width = c.SCREEN_WIDTH - margin * 2
        list_width = self.LIST_AND_SEARCH_WIDTH
        panel_height = c.SCREEN_HEIGHT - self.PANEL_Y - self.BOTTOM_MARGIN
        self.list_panel = pygame.Rect(margin, self.PANEL_Y, list_width, panel_height)
        self.detail_panel = pygame.Rect(self.list_panel.right + gap, self.PANEL_Y,
                                        width - list_width - gap, panel_height)
        self.action_top = (self.detail_panel.bottom - margin - self.PRIMARY_ACTION_HEIGHT
                           - self.ACTION_GAP - self.ACTION_HEIGHT)
        self.regions = {
            "items": pygame.Rect(self.list_panel.x + 12, self.list_panel.y + 42,
                                 self.list_panel.width - 42, self.list_panel.height - 54),
            "details": pygame.Rect(self.detail_panel.x + margin, self.detail_panel.y + 68,
                                   self.detail_panel.width - margin * 2 - 16,
                                   self.action_top - self.detail_panel.y - 84),
        }
        for name, rect in self.regions.items():
            setattr(self, f"_content_{name}", rect)
        self.layout_search_controls(self.CONTROL_Y)

    def layout_search_controls(self, y):
        """Keep Search, Clear, and Sort together above the item list."""
        width = self.list_panel.width - self.CLEAR_BUTTON_WIDTH - self.SORT_BUTTON_WIDTH - 2 * self.CONTROL_GAP
        self.search_field.rect = pygame.Rect(self.list_panel.x, y, width, self.CONTROL_HEIGHT)
        self.search_field.font_preset = self.SEARCH_FONT

    def build_browser_controls(self):
        """Build the search and sort controls for this layout."""
        y = self.search_field.rect.y
        clear_x = self.search_field.rect.right + self.CONTROL_GAP
        sort_x = clear_x + self.CLEAR_BUTTON_WIDTH + self.CONTROL_GAP
        sort_button = Button(sort_x, y, (self.SORT_BUTTON_WIDTH, self.CONTROL_HEIGHT), "grey",
                             f"Sort: {self.SORTS[self.sort_index][1]}", self.cycle_sort, font_preset="small")
        sort_button.fit_text = True
        sort_button.fit_single_line = True
        self.elements.extend([
            Button(clear_x, y, (self.CLEAR_BUTTON_WIDTH, self.CONTROL_HEIGHT), "red", "Clear",
                   self.clear_search, font_preset="small"),
            sort_button,
        ])

    def make_content_row(self, rect, entry):
        return ContentRow(rect, entry, self.selected_entry == entry, lambda: self.toggle_entry(entry))

    def summary_for(self, entry):
        if entry.path not in self.summary_cache:
            self.summary_cache[entry.path] = queries.read_saved_content_summary(entry.path)
        return self.summary_cache[entry.path]

    def detail_texts(self, entry, summary):
        return [entry.modified_label, *summary["details"]]

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
        selected = next((entry for entry in entries if entry.path == selected_path), None)
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

    def toggle_entry(self, entry):
        self.select_entry(None if self.selected_entry == entry else entry)

    def selected_detail_texts(self):
        """Use the same selected details for layout and rendering."""
        self.selection_error = ""
        texts = []
        if self.selected_entry:
            entry = self.selected_entry
            summary = self.summary_for(entry)
            self.selection_error = summary["error"]
            texts = self.detail_texts(entry, summary)
            if self.selection_error:
                texts = [self.selection_error, "", *texts]
            if self.detail_note:
                texts.extend(("", self.detail_note))
        return texts

    def _prepare_details(self):
        rect = self.regions["details"]
        texts = self.selected_detail_texts()
        self.detail_preview = self.selected_map_preview(rect)
        self.detail_text_offset = self.detail_preview.get_height() + self.GAP if self.detail_preview is not None else 0
        font = fonts.get("normal")
        self.detail_lines = [font.render(line, True, c.UI_TEXT_LIGHT)
                             for text in texts for line in wrap_text(text, font, rect.width)]
        self.detail_line_height = font.get_linesize() + 5
        content_height = self.detail_text_offset + len(self.detail_lines) * self.detail_line_height
        self._max_details = min(0, rect.height - content_height)
        self._scroll_details = max(self._max_details, min(0, self.pane_scroll("details")))
        heading = self.selected_entry.name if self.selected_entry else ""
        self.detail_heading = fonts.get("heading2").render(
            fit_text(heading, fonts.get("heading2"), self.detail_panel.width - self.MARGIN * 2), True, c.UI_TEXT_BRIGHT)

    def selected_map_preview(self, rect):
        """Cache the selected terrain image. Missing or unreadable images do not block loading."""
        if not self.show_map_preview or self.selected_entry is None:
            return None
        bounds = (rect.width, min(self.PREVIEW_HEIGHT, rect.height // 2))
        if min(bounds) <= 0:
            return None
        path = os.path.join(self.selected_entry.path, "terrain.png")
        key = (path, bounds)
        if key not in self.preview_cache:
            preview = None
            try:
                with open(path, "rb") as source:
                    if source.read(8) == b"\x89PNG\r\n\x1a\n":
                        source.seek(0)
                        image = pygame.image.load(source, "terrain.png")
                        scale = min(bounds[0] / image.get_width(), bounds[1] / image.get_height(), 1)
                        size = (max(1, int(image.get_width() * scale)), max(1, int(image.get_height() * scale)))
                        preview = pygame.transform.scale(image, size)
            except (OSError, pygame.error):
                pass
            self.preview_cache[key] = preview
        return self.preview_cache[key]

    @property
    def selection_can_open(self):
        return self.selected_entry is not None and not self.selection_error

    def call_selected(self, handler):
        if self.selected_entry:
            handler(self.selected_entry.name)

    def add_browser_action(self, label, callback, slot, color="grey", *, enabled=True, sound_kind="click"):
        """Place a screen's action in the shared details panel."""
        width = (self.detail_panel.width - self.MARGIN * 2
                 - self.ACTION_GAP * (self.ACTION_COUNT - 1)) // self.ACTION_COUNT
        x = self.detail_panel.x + self.MARGIN + slot * (width + self.ACTION_GAP)
        button = Button(x, self.action_top, (width, self.ACTION_HEIGHT), color, label, callback,
                        font_preset="button_small", sound_kind=sound_kind)
        button.apply_state(enabled=enabled and self.selected_entry is not None, color=color)
        self.elements.append(button)
        return button

    def add_primary_action(self, label, callback=None):
        """Place the selected item's primary action below the other actions."""
        width = self.detail_panel.width - self.MARGIN * 2
        button = Button(self.detail_panel.x + self.MARGIN,
                        self.detail_panel.bottom - self.MARGIN - self.PRIMARY_ACTION_HEIGHT,
                        (width, self.PRIMARY_ACTION_HEIGHT), "orange", label, callback or self.activate_selected,
                        font_preset="heading1", sound_kind="click" if callback is not None else None)
        button.apply_state(enabled=callback is not None or self.selection_can_open, color="orange")
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
            if self.selected_entry is None:
                index = 0 if event.key == pygame.K_DOWN else len(self.filtered_entries) - 1
            else:
                index = self.filtered_entries.index(self.selected_entry)
                index = max(0, min(len(self.filtered_entries) - 1, index + (1 if event.key == pygame.K_DOWN else -1)))
            rect = self.regions["items"]
            scroll = self.pane_scroll("items")
            row = index + self.leading_row_count
            top = row * self.ROW_HEIGHT + scroll
            if top < 0:
                self._scroll_items = -row * self.ROW_HEIGHT
            elif top + self.ROW_HEIGHT > rect.height:
                self._scroll_items = rect.height - (row + 1) * self.ROW_HEIGHT
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
        top = rect.y + self.pane_scroll("details")
        if self.detail_preview is not None:
            surface.blit(self.detail_preview, self.detail_preview.get_rect(midtop=(rect.centerx, top)))
        for index, line in enumerate(self.detail_lines):
            y = top + self.detail_text_offset + index * self.detail_line_height
            if y + self.detail_line_height > rect.top and y < rect.bottom:
                surface.blit(line, (rect.x, y))

    def additional_draw(self, surface):
        for rect in (self.list_panel, self.detail_panel):
            draw_pixel_panel(surface, rect, (35, 40, 52), recessed=True)
        font = fonts.get("normal")
        if self.category_caption:
            surface.blit(font.render(self.category_caption, True, c.UI_TEXT_LIGHT), (self.MARGIN, self.CATEGORY_Y))
        surface.blit(fonts.get(self.SEARCH_FONT).render("Search by name", True, c.UI_TEXT_DIM),
                     (self.MARGIN, self.CONTROL_Y - 23))
        surface.blit(font.render("Name / Last modified", True, c.UI_TEXT_DIM),
                     (self.list_panel.x + 14, self.list_panel.y + 12))
        surface.blit(self.detail_heading, (self.detail_panel.x + self.MARGIN, self.detail_panel.y + 20))
        count = f"{len(self.filtered_entries)} of {len(self.entries)} {self.content_label}"
        count_surface = font.render(count, True, c.UI_TEXT_LIGHT)
        surface.blit(count_surface, (self.list_panel.right - 14 - count_surface.get_width(),
                                     self.list_panel.y + 12))
        if not self.filtered_entries:
            message = self.directory_error or ("No matching items. Clear the search to show all items."
                                               if self.search_field.text.strip() else self.empty_message)
            # The leading row is the only row here, so the message goes below it.
            message_top = self.leading_row_count * self.ROW_HEIGHT
            for index, line in enumerate(wrap_text(message, font, self.regions["items"].width - 24)):
                surface.blit(font.render(line, True, c.UI_TEXT_LIGHT),
                             (self.regions["items"].x + 12, self.regions["items"].y + message_top + 20 + index * 26))
        for name, rect in self.regions.items():
            self.draw_pane_scrollbar(surface, name, rect.right + 7, rect.top, rect.height)


class ScenarioLibraryScreen(ContentBrowserScreen):
    """Use compact category buttons, scenario rows, and text details."""

    LIBRARY_CATEGORY_WIDTH = 224
    LIBRARY_DETAIL_WIDTH = 432
    LIBRARY_PANEL_Y = 154
    LIBRARY_CONTROL_Y = 104
    LIBRARY_ROW_HEIGHT = 36
    LIBRARY_CATEGORY_HEIGHT = 36
    LIBRARY_CATEGORY_GAP = 8
    LIBRARY_CATEGORY_INSET = 16
    LIBRARY_CATEGORY_TOP = 44
    LIBRARY_ACTION_HEIGHT = 108
    LIBRARY_ACTION_ICON_SIZE = (48, 48)
    CATEGORY_COLORS = {
        "SCENARIOS_HISTORICAL_DIR": "blue",
        "SCENARIOS_ALTERNATE_DIR": "purple",
        "SCENARIOS_CUSTOM_DIR": "green",
        "BASE_MAPS_DIR": "orange",
    }

    @property
    def library_mode(self):
        return True

    @property
    def ROW_HEIGHT(self):
        return self.LIBRARY_ROW_HEIGHT if self.library_mode else ContentBrowserScreen.ROW_HEIGHT

    @property
    def library_categories(self):
        return self.CATEGORIES

    @property
    def category_color(self):
        return self.CATEGORY_COLORS[self.library_categories[self.sub_state][1]]

    def prepare_entries(self):
        if not self.library_mode:
            return
        # Cache metadata when a category opens. Frames and scrolling reuse it.
        for entry in self.entries:
            self.summary_for(entry)

    def layout_browser(self):
        if not self.library_mode:
            return super().layout_browser()
        margin, gap = self.MARGIN, self.GAP
        available_height = c.SCREEN_HEIGHT - self.LIBRARY_PANEL_Y - self.BOTTOM_MARGIN
        self.category_panel = pygame.Rect(margin, self.LIBRARY_PANEL_Y, self.LIBRARY_CATEGORY_WIDTH, available_height)
        self.detail_panel = pygame.Rect(c.SCREEN_WIDTH - margin - self.LIBRARY_DETAIL_WIDTH, self.LIBRARY_PANEL_Y,
                                        self.LIBRARY_DETAIL_WIDTH, available_height)
        list_x = self.category_panel.right + gap
        self.list_panel = pygame.Rect(list_x, self.LIBRARY_PANEL_Y,
                                      self.detail_panel.left - gap - list_x, available_height)
        detail_width = self.detail_panel.width - margin * 2 - 16
        self.action_top = self.detail_panel.bottom - margin - self.LIBRARY_ACTION_HEIGHT
        self.regions = {
            "items": pygame.Rect(self.list_panel.x + 12, self.list_panel.y + 44,
                                 self.list_panel.width - 42, self.list_panel.height - 56),
            "details": pygame.Rect(self.detail_panel.x + margin, self.detail_panel.y + 64,
                                   detail_width, self.action_top - self.detail_panel.y - 64 - gap),
        }
        for name, rect in self.regions.items():
            setattr(self, f"_content_{name}", rect)
        self.layout_search_controls(self.LIBRARY_CONTROL_Y)

    def build_browser_controls(self):
        super().build_browser_controls()
        if not self.library_mode:
            return
        y = self.LIBRARY_CONTROL_Y
        self.elements.append(Button(self.detail_panel.right - 128, y, (128, 38), "grey", "Refresh", self.reload_entries,
                                    font_preset="button_small"))
        for index, (state, (label, directory_attr)) in enumerate(self.library_categories.items()):
            rect = self.category_button_rect(index)
            tile = Button(rect.x, rect.y, rect.size, self.CATEGORY_COLORS[directory_attr], label,
                          lambda category=state: self.set_sub_state(category), font_preset="button_small",
                          sound_kind="select_category")
            tile.fit_text = True
            tile.fit_single_line = True
            tile.is_selected = self.sub_state == state
            self.elements.append(tile)

    def category_button_rect(self, index):
        """Align category buttons and category shortcuts in the same column."""
        panel = self.category_panel
        return pygame.Rect(panel.x + self.LIBRARY_CATEGORY_INSET,
                           panel.y + self.LIBRARY_CATEGORY_TOP + index * (self.LIBRARY_CATEGORY_HEIGHT + self.LIBRARY_CATEGORY_GAP),
                           panel.width - 2 * self.LIBRARY_CATEGORY_INSET, self.LIBRARY_CATEGORY_HEIGHT)

    def make_content_row(self, rect, entry):
        if not self.library_mode:
            return super().make_content_row(rect, entry)
        row = Button(rect.x, rect.y, rect.size, self.category_color, entry.name,
                     lambda: self.toggle_entry(entry), font_preset="button_small", sound_kind="select_sub_category")
        row.fit_text = True
        row.fit_single_line = True
        row.text_align = "left"
        row.is_selected = self.selected_entry == entry
        return row

    def detail_texts(self, entry, summary):
        if not self.library_mode:
            return super().detail_texts(entry, summary)
        texts = []
        if summary["date_label"]:
            texts.append(f"Start date: {summary['date_label']} (day/month/year)")
        if summary["author"]:
            texts.append(f"Author: {summary['author']}")
        if summary["description"]:
            texts.extend(("", summary["description"]))
        return texts

    def _prepare_details(self):
        super()._prepare_details()
        if not self.library_mode:
            return
        label = self.library_categories[self.sub_state][0]
        if self.selected_entry is None:
            font = fonts.get("heading2")
            self.detail_heading = font.render(
                fit_text(label, font, self.detail_panel.width - self.MARGIN * 2), True, c.UI_TEXT_BRIGHT)
        font = fonts.get("normal")
        self.library_labels = [
            (font.render(text, True, c.UI_TEXT_LIGHT), position) for text, position in (
                ("Categories", (self.category_panel.x + 16, self.category_panel.y + 12)),
                (label, (self.list_panel.x + 14, self.list_panel.y + 12)))
        ]
        self.library_labels.append((fonts.get(self.SEARCH_FONT).render("Search", True, c.UI_TEXT_LIGHT),
                                    (self.list_panel.x, self.LIBRARY_CONTROL_Y - 24)))
        count = font.render(f"{len(self.filtered_entries)} / {len(self.entries)}", True, c.UI_TEXT_DIM)
        self.library_labels.append((count, (self.list_panel.right - count.get_width() - 14, self.list_panel.y + 12)))
        if not self.filtered_entries:
            message = self.directory_error or ("No matching items." if self.search_field.text.strip() else self.empty_message)
            for index, line in enumerate(wrap_text(message, font, self.regions["items"].width - 24)):
                self.library_labels.append((font.render(line, True, c.UI_TEXT_LIGHT),
                                            (self.regions["items"].x + 12, self.regions["items"].y + 20 + index * 26)))

    def add_primary_action(self, label, callback=None):
        if not self.library_mode:
            return super().add_primary_action(label, callback)
        if callback is None and self.selected_entry is None:
            return None
        rect = self.detail_panel
        button = Button(rect.x + self.MARGIN, self.action_top,
                        (rect.width - self.MARGIN * 2, self.LIBRARY_ACTION_HEIGHT), "orange", label,
                        callback or self.activate_selected, font_preset="title",
                        image=symbol_loader.get_symbol("Star", 1, fit_size=self.LIBRARY_ACTION_ICON_SIZE),
                        sound_kind="click" if callback is not None else None)
        button.apply_state(enabled=callback is not None or self.selection_can_open, color="orange")
        self.elements.append(button)
        return button

    def add_category_footer_action(self, label, callback, color="grey", *, enabled=True, slot=0):
        """Anchor an action at the bottom of the category panel."""
        rect = self.category_button_rect(0)
        rect.bottom = (self.category_panel.bottom - self.LIBRARY_CATEGORY_INSET
                       - slot * (self.LIBRARY_CATEGORY_HEIGHT + self.LIBRARY_CATEGORY_GAP))
        button = Button(rect.x, rect.y, rect.size,
                        color, label, callback, font_preset="button_small")
        button.fit_text = True
        button.apply_state(enabled=enabled, color=color)
        self.elements.append(button)
        return button

    def additional_draw(self, surface):
        if not self.library_mode:
            return super().additional_draw(surface)
        for panel in (self.category_panel, self.list_panel, self.detail_panel):
            draw_pixel_panel(surface, panel, (35, 40, 52), recessed=True)
        for text, position in self.library_labels:
            surface.blit(text, position)
        surface.blit(self.detail_heading, (self.detail_panel.x + self.MARGIN, self.detail_panel.y + 20))
        for name, rect in self.regions.items():
            if rect.height:
                self.draw_pane_scrollbar(surface, name, rect.right + 7, rect.top, rect.height)
