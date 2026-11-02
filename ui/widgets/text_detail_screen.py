"""A scrollable full-screen view of one long piece of text.

The Global Messages Overview truncates its message column at 90 characters,
which is the only way a fixed-width table can show prose -- but it meant the end
of every message the AI wrote was simply unreadable. Rather than widening the
column (there is no width at which some message does not overflow), a row opens
here, where the text has the whole screen and scrolls.
"""

import pygame

import data.constants as c
from ui.navigation.game_state import GameState, host_map_screen
from ui.rendering.font_manager import fonts
from ui.widgets import text_utils
from ui.bars import ui_bars
from ui.widgets.ui_elements import make_back_button


class TextDetailScreen(GameState):
    LINE_HEIGHT = 24
    BODY_TOP = 150
    SIDE_MARGIN = 80

    def __init__(self, game_state, title, body, subtitle=""):
        super().__init__()
        self.map_screen = host_map_screen(game_state)
        self.bg_color = (25, 28, 35)
        self.title = title
        self.subtitle = subtitle
        self.body = str(body or "")
        self.scroll_y = 0
        self.max_scroll = 0
        self.elements = [make_back_button(self.exit_screen)]

    def additional_events(self, event):
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def draw(self, surface):
        self.draw_background(surface)
        ui_bars.draw_centered_title(surface, self.title, 25, "heading1")

        if self.subtitle:
            sub = fonts.get("small").render(self.subtitle, True, c.COLOR_GOLD_HIGHLIGHT)
            surface.blit(sub, sub.get_rect(center=(c.SCREEN_WIDTH // 2, 90)))

        body_font = fonts.get("normal")
        width = c.SCREEN_WIDTH - (self.SIDE_MARGIN * 2)
        lines = text_utils.wrap_text(self.body, body_font, width)

        view_h = c.SCREEN_HEIGHT - self.BODY_TOP - 40
        clip = pygame.Rect(self.SIDE_MARGIN, self.BODY_TOP - 10, width, view_h)

        # max_scroll is zero or negative here, as everywhere else in this
        # codebase: scroll_y counts down from 0 towards it.
        self.draw_scrolling_lines(surface, lines, body_font, self.SIDE_MARGIN, self.BODY_TOP, view_h,
                                  self.LINE_HEIGHT, clip, lambda _line: c.UI_TEXT_BRIGHT)

        self.draw_list_scrollbar(surface, self.SIDE_MARGIN + width + 15,
                                 self.BODY_TOP, view_h)

        for el in self.elements:
            el.draw(surface)
