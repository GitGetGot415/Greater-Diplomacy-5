import pygame
from gameState import GameState
import data.constants as c
from ui.bars import ui_bars
from ui_elements import Button
from map_logic.rendering.font_manager import fonts

class ListSelectScreen(GameState):
    """In-engine stand-in for a tkinter listbox picker.

    Freezes whatever was on screen behind a dimmed modal panel and shows a
    scrollable, clickable list of rows -- the pygame equivalent of the old
    "pick one item from a list" native dialogs.
    """
    PANEL_SIZE = (620, 560)
    ROW_HEIGHT = 40
    ROW_TOP = 110
    ROW_LABEL_MAX_CHARS = 42
    # Rows whose label equals this are drawn greyed-out and unclickable (list separators).
    SEPARATOR = "----------"

    def __init__(self, game_state, title, prompt, items, on_confirm):
        super().__init__()
        # Only used to resolve custom keybinds (BACK/ORDERS); may not carry feedback_text.
        self.map_screen = getattr(game_state, "map_screen", None) or game_state
        self.title = title
        self.prompt = prompt
        self.items = list(items)
        self.on_confirm = on_confirm

        surface = pygame.display.get_surface()
        self.background = surface.copy() if surface else None

        panel_w, panel_h = self.PANEL_SIZE
        self.panel_rect = pygame.Rect(0, 0, panel_w, panel_h)
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)

        self.refresh_ui()

    def select(self, item):
        self.on_confirm(item)
        self.exit_screen()

    def refresh_ui(self):
        self.elements = [Button(self.panel_rect.x + 20, self.panel_rect.y + 20, "small", "red",
                                "Cancel", self.exit_screen)]

        row_top = self.panel_rect.y + self.ROW_TOP
        view_h = self.panel_rect.height - self.ROW_TOP - 30
        row_x = self.panel_rect.centerx - (c.SIZES["list_row"][0] // 2)

        for i, y in self.layout_list_rows(len(self.items), self.ROW_HEIGHT, row_top, view_h=view_h,
                                          cull_top=self.panel_rect.y + 60, cull_bottom=self.panel_rect.bottom - 20):
            item = self.items[i]
            label = item if len(item) <= self.ROW_LABEL_MAX_CHARS else item[:self.ROW_LABEL_MAX_CHARS - 3] + "..."
            btn = Button(row_x, y, "list_row", "blue", label, lambda it=item: self.select(it))
            if item == self.SEPARATOR:
                btn.apply_state(enabled=False)
            self.elements.append(btn)

    def additional_events(self, event):
        self.handle_list_scroll(event)

    def draw(self, surface):
        if self.background:
            surface.blit(self.background, (0, 0))
        ui_bars.draw_fullscreen_overlay(surface, 190)

        ui_bars.draw_modal_box(surface, self.panel_rect, bg_color=(35, 35, 45),
                               border_color=(100, 150, 255), border_width=3)
        ui_bars.draw_centered_title(surface, self.title, self.panel_rect.y + 20, "heading2")

        prompt_surf = fonts.get("normal").render(self.prompt, True, (220, 220, 220))
        surface.blit(prompt_surf, prompt_surf.get_rect(center=(self.panel_rect.centerx, self.panel_rect.y + 75)))

        for el in self.elements:
            el.draw(surface)

        self.draw_list_scrollbar(surface, self.panel_rect.right - 30, self.panel_rect.y + self.ROW_TOP,
                                 self.panel_rect.height - self.ROW_TOP - 30)
