import pygame
import data.constants as c
import ui_elements
from ui import text_utils
from ui.modal_screen import ModalScreen
from ui_elements import Button
from map_logic.rendering.font_manager import fonts

class ListSelectScreen(ModalScreen):
    """In-engine stand-in for a tkinter listbox picker.

    Freezes whatever was on screen behind a dimmed modal panel and shows a
    scrollable, clickable list of rows -- the pygame equivalent of the old
    "pick one item from a list" native dialogs.
    """
    PANEL_SIZE = (620, 560)
    ROW_HEIGHT = 40
    ROW_TOP = 154
    ROW_LABEL_MAX_CHARS = 42
    # Rows whose label equals this are drawn greyed-out and unclickable (list separators).
    SEPARATOR = "----------"

    SEARCH_BOX_Y = 92
    SEARCH_BOX_HEIGHT = 34
    SEARCH_MAX_CHARS = 40

    def __init__(self, game_state, title, prompt, items, on_confirm):
        super().__init__(game_state, title)
        self.prompt = prompt
        self.items = list(items)
        self.on_confirm = on_confirm
        self.search_text = ""
        self.visible_items = self.items
        self.refresh_ui()

    def select(self, item):
        self.on_confirm(item)
        self.exit_screen()

    def _filtered_items(self):
        if not self.search_text:
            return self.items
        query = self.search_text.lower()
        return [item for item in self.items if item != self.SEPARATOR and query in item.lower()]

    def refresh_ui(self):
        self.elements = [Button(self.panel_rect.x + 20, self.panel_rect.y + 20, "small", "red",
                                "Cancel", self.exit_screen)]

        self.visible_items = self._filtered_items()

        row_top = self.panel_rect.y + self.ROW_TOP
        view_h = self.panel_rect.height - self.ROW_TOP - 30
        row_x = self.panel_rect.centerx - (c.SIZES["list_row"][0] // 2)

        # Cull below the search box's own bottom edge (plus a small gap) so the
        # clip region never starts mid-box -- otherwise a scrolled row can show
        # through the box's lower half instead of being hidden behind it.
        search_bottom = self.panel_rect.y + self.SEARCH_BOX_Y + self.SEARCH_BOX_HEIGHT
        cull_top, cull_bottom = search_bottom + 8, self.panel_rect.bottom - 20
        self.scroll_content_rect = pygame.Rect(self.panel_rect.x, cull_top, self.panel_rect.width, cull_bottom - cull_top)

        for i, y in self.layout_list_rows(len(self.visible_items), self.ROW_HEIGHT, row_top, view_h=view_h,
                                          cull_top=cull_top, cull_bottom=cull_bottom):
            item = self.visible_items[i]
            label = text_utils.truncate_chars(item, self.ROW_LABEL_MAX_CHARS)
            btn = Button(row_x, y, "list_row", "blue", label, lambda it=item: self.select(it))
            if item == self.SEPARATOR:
                btn.apply_state(enabled=False)
            btn.is_scrollable = True
            btn.click_guard = self.scroll_click_guard
            self.elements.append(btn)

    def handle_back_key(self):
        # Escape clears an active filter first; only closes the screen once
        # the search box is already empty, so "give up on this search" and
        # "cancel the picker" are two separate presses instead of one.
        if self.search_text:
            self.search_text = ""
            self.scroll_y = 0
            self.refresh_ui()
        else:
            self.exit_screen()

    def _handle_search_key(self, event):
        from ui_elements import process_text_input
        if event.key == pygame.K_RETURN:
            for item in self.visible_items:
                if item != self.SEPARATOR:
                    self.select(item)
                    break
            return
        if event.key == pygame.K_ESCAPE:
            return  # handled by handle_back_key via dispatch_global_keys
        new_text, _status = process_text_input(event, self.search_text, max_length=self.SEARCH_MAX_CHARS)
        if new_text != self.search_text:
            self.search_text = new_text
            self.scroll_y = 0
            self.refresh_ui()

    def additional_events(self, event):
        if self.handle_list_scroll(event, content_rect_attr="scroll_content_rect"):
            return
        if event.type == pygame.KEYDOWN:
            self._handle_search_key(event)

    def draw_body(self, surface):
        prompt_surf = fonts.get("normal").render(self.prompt, True, c.UI_TEXT_BRIGHT)
        surface.blit(prompt_surf, prompt_surf.get_rect(center=(self.panel_rect.centerx, self.panel_rect.y + 75)))

        self.draw_search_box(surface)

        if not self.visible_items:
            font = fonts.get("normal")
            msg = font.render("No matches found." if self.search_text else "Nothing to show.",
                              True, c.UI_TEXT_LIGHT)
            list_top = self.panel_rect.y + self.ROW_TOP
            view_h = self.panel_rect.height - self.ROW_TOP - 30
            surface.blit(msg, msg.get_rect(center=(self.panel_rect.centerx, list_top + view_h // 2)))

    def draw_foreground(self, surface):
        self.draw_list_scrollbar(surface, self.panel_rect.right - 30, self.panel_rect.y + self.ROW_TOP,
                                 self.panel_rect.height - self.ROW_TOP - 30)

    def draw_search_box(self, surface):
        box = pygame.Rect(self.panel_rect.x + 20, self.panel_rect.y + self.SEARCH_BOX_Y,
                          self.panel_rect.width - 40, self.SEARCH_BOX_HEIGHT)
        # Always drawn focused: this box is the screen's only text target.
        ui_elements.draw_text_box(surface, box, self.search_text, active=True,
                                  placeholder="Search...")
