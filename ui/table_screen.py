import pygame
from gameState import GameState
import data.constants as c
from ui.bars import ui_bars
from ui import text_utils
from ui_elements import Button, make_back_button
from map_logic.rendering.font_manager import fonts

def truncate(text, max_chars):
    """Kept as the name three editors already import; the implementation now
    lives in ui/text_utils.py alongside the pixel-width fitters."""
    return text_utils.truncate_chars(text, max_chars)

class TableColumn:
    """One sortable column of a TableScreen.

    `fmt` renders the cell from `row[key]`; `sort_key` (defaults to `row[key]`
    itself) is what gets compared when the header is clicked, so a column can
    display one thing (a date string) but sort on another (its epoch day).
    Columns sharing the same `group` get one merged label drawn above them.
    """
    def __init__(self, key, label, width, align="center", fmt=str, group=None, sort_key=None):
        self.key = key
        self.label = label
        self.width = width
        self.align = align
        self.fmt = fmt
        self.group = group
        self.sort_key = sort_key or (lambda row, k=key: row.get(k))

class TableScreen(GameState):
    """Full-screen sortable data table -- the pygame stand-in for the old
    read-only ttk.Treeview overviews (global economy, messages, expenses).
    """
    ROW_HEIGHT = 30
    GROUP_LABEL_Y = 65
    HEADER_Y = 88
    ROW_TOP = 130

    def __init__(self, game_state, title, columns, rows, empty_message="Nothing to show.",
                 on_row_click=None):
        super().__init__()
        self.map_screen = getattr(game_state, "map_screen", None) or game_state
        self.bg_color = (25, 28, 35)
        self.title = title
        self.columns = columns
        self.rows = rows
        self.empty_message = empty_message
        self.sort_reverse = {}
        #: Optional callback taking the row dict. Rows are only clickable where
        #: one is given, so the economy and expenses tables are unaffected.
        self.on_row_click = on_row_click
        #: (rect, row) for every row actually drawn last frame. Culled rows are
        #: absent, so a row scrolled out of view cannot be clicked.
        self.row_hitboxes = []

        self.total_w = sum(col.width for col in columns)
        self.table_x = max(20, (c.SCREEN_WIDTH - self.total_w) // 2)

        # Pre-compute contiguous same-group spans once; columns don't change after creation.
        self.group_spans = []
        x, i = self.table_x, 0
        while i < len(columns):
            group = columns[i].group
            start_x, span_w = x, 0
            while i < len(columns) and columns[i].group == group:
                span_w += columns[i].width
                x += columns[i].width
                i += 1
            if group:
                self.group_spans.append((group, start_x, span_w))

        self.refresh_ui()

    def sort_by(self, col):
        reverse = self.sort_reverse.get(col.key, False)
        self.rows.sort(key=col.sort_key, reverse=reverse)
        self.sort_reverse[col.key] = not reverse

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]

        x = self.table_x
        for col in self.columns:
            btn = Button(x, self.HEADER_Y, "small", "blue", col.label,
                        lambda c=col: self.sort_by(c), font_preset="button_small")
            btn.rect.width, btn.rect.height = col.width, 28
            self.elements.append(btn)
            x += col.width

    def additional_events(self, event):
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

        if not self.on_row_click:
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        # A row half-scrolled under the header is drawn clipped, so the click
        # has to land inside the scroll region as well as on the row.
        clip = getattr(self, "scroll_content_rect", None)
        if clip is not None and not clip.collidepoint(event.pos):
            return
        for rect, row in self.row_hitboxes:
            if rect.collidepoint(event.pos):
                self.on_row_click(row)
                return

    def draw(self, surface):
        surface.fill(self.bg_color)
        ui_bars.draw_centered_title(surface, self.title, 25, "heading1")

        if not self.rows:
            msg_surf = fonts.get("normal").render(self.empty_message, True, c.UI_TEXT_LIGHT)
            surface.blit(msg_surf, msg_surf.get_rect(center=(c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)))
            for el in self.elements:
                el.draw(surface)
            return

        group_font = fonts.get("small")
        for label, gx, gw in self.group_spans:
            txt = group_font.render(label, True, c.COLOR_GOLD_HIGHLIGHT)
            surface.blit(txt, txt.get_rect(center=(gx + gw // 2, self.GROUP_LABEL_Y)))
            pygame.draw.line(surface, (80, 80, 90), (gx, self.GROUP_LABEL_Y + 15), (gx + gw, self.GROUP_LABEL_Y + 15), 1)

        for el in self.elements:
            el.draw(surface)

        view_h = c.SCREEN_HEIGHT - self.ROW_TOP - 20
        row_font = fonts.get("small")
        self.row_hitboxes = []
        hovered = pygame.mouse.get_pos() if self.on_row_click else None
        clip_rect = pygame.Rect(self.table_x, self.ROW_TOP - 10, self.total_w, c.SCREEN_HEIGHT - (self.ROW_TOP - 10) - 10)
        self.scroll_content_rect = clip_rect
        with ui_bars.clip_scroll_region(surface, clip_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
            for i, y in self.layout_list_rows(len(self.rows), self.ROW_HEIGHT, self.ROW_TOP, view_h=view_h,
                                              cull_top=self.ROW_TOP - 10, cull_bottom=c.SCREEN_HEIGHT - 10):
                row = self.rows[i]
                row_rect = pygame.Rect(self.table_x, y, self.total_w, self.ROW_HEIGHT)
                if i % 2 == 0:
                    pygame.draw.rect(surface, (35, 38, 45), row_rect)

                if hovered is not None:
                    self.row_hitboxes.append((row_rect, row))
                    if row_rect.collidepoint(hovered) and clip_rect.collidepoint(hovered):
                        pygame.draw.rect(surface, (55, 60, 75), row_rect)
                        pygame.draw.rect(surface, c.COLOR_GOLD_HIGHLIGHT, row_rect, 1)

                x = self.table_x
                for col in self.columns:
                    text = col.fmt(row.get(col.key, ""))
                    cell_surf = row_font.render(text, True, c.UI_TEXT_BRIGHT)
                    mid_y = y + self.ROW_HEIGHT // 2
                    if col.align == "left":
                        rect = cell_surf.get_rect(midleft=(x + 6, mid_y))
                    elif col.align == "right":
                        rect = cell_surf.get_rect(midright=(x + col.width - 6, mid_y))
                    else:
                        rect = cell_surf.get_rect(center=(x + col.width // 2, mid_y))
                    surface.blit(cell_surf, rect)
                    x += col.width

        self.draw_list_scrollbar(surface, min(c.SCREEN_WIDTH - 25, self.table_x + self.total_w + 10),
                                 self.ROW_TOP, view_h)
