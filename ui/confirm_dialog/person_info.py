import os
import webbrowser
import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts
from ui import modal_stack
from ui.confirm_dialog.base import _BaseModal, _back_key, _lighten, _run_blocking, _wrap_text
from ui.confirm_dialog.message_box import _KIND_ACCENTS
from ui.bars import ui_bars

_LINK_COLOR = (100, 100, 255)
_LINK_HOVER_COLOR = (255, 255, 0)
_IMAGE_SIZE = 40
_IMAGE_TEXT_GAP = 12
_IMAGE_ROW_GAP = 8
_IMAGE_COLUMNS = 2
_IMAGE_COLUMN_GAP = 20
_CONTENT_GAP = 20
_CONTENT_MARGIN = 40
_SCROLL_STEP = 40
_SCROLLBAR_WIDTH = 15
_SCROLLBAR_GAP = 12


class _PersonInfoModal(_BaseModal):
    """Popup for a Credits entry: a title, an optional free-text info section,
    optional labeled images, and clickable links below it."""

    BOX_MAX_W = 560
    BOX_MIN_H = 220
    BOX_CHROME_H = 180   # 110 of chrome plus the 70 the Close row occupies
    BORDER_COLOR = _KIND_ACCENTS["info"]
    BORDER_WIDTH = 3
    PASSES_RESULT = False

    def __init__(self, surface, name, info_text, links, on_result, align="center", images=None):
        self.align = align if align in ("left", "center", "right") else "center"
        self.BODY_ALIGN = self.align
        self.links = links or []
        self.link_font = fonts.get("normal")
        self.image_rows = []
        self.scroll_y = 0
        self._scroll_drag_offset = None
        self.image_columns = min(_IMAGE_COLUMNS, len(images or []))

        # Load and fit images/labels once when opening the popup, keeping draw
        # cache-only. Nearest-neighbor scaling preserves the pixel artwork.
        box_w = min(self.BOX_MAX_W, surface.get_width() - _CONTENT_MARGIN)
        columns = max(1, self.image_columns)
        cell_w = (box_w - 2 * _CONTENT_MARGIN - _IMAGE_COLUMN_GAP * (columns - 1)) // columns
        label_w = max(1, cell_w - _IMAGE_SIZE - _IMAGE_TEXT_GAP)
        loaded_images = {}
        for image in images or []:
            path = image["path"]
            if path not in loaded_images:
                source = pygame.image.load(path)
                scale = _IMAGE_SIZE / max(source.get_size())
                size = tuple(max(1, round(dimension * scale)) for dimension in source.get_size())
                loaded_images[path] = pygame.transform.scale(source, size)
            label = image.get("text", os.path.basename(path))
            lines = _wrap_text(label, self.link_font, label_w)
            labels = [self.link_font.render(line, True, c.UI_TEXT_LIGHT) for line in lines]
            text_h = len(labels) * (self.link_font.get_height() + 2)
            self.image_rows.append({
                "image": loaded_images[path], "labels": labels,
                "height": max(_IMAGE_SIZE, text_h),
                "width": _IMAGE_SIZE + _IMAGE_TEXT_GAP + max((s.get_width() for s in labels), default=0),
            })
        grid_rows = [self.image_rows[i:i + columns]
                     for i in range(0, len(self.image_rows), columns)]
        images_h = sum(max(cell["height"] for cell in row) + _IMAGE_ROW_GAP for row in grid_rows)

        links_h = len(self.links) * (self.link_font.get_height() + 8)
        super().__init__(surface, name, info_text, on_result,
                         extra_h=images_h + (_CONTENT_GAP if self.image_rows else 0)
                         + links_h + (_CONTENT_GAP if self.links else 0))
        if self.image_rows:
            self.box_rect.height = min(self.box_rect.height, surface.get_height() - _CONTENT_MARGIN)
            self.box_rect.centery = surface.get_height() // 2

        self.name = name
        self.ok_rect = pygame.Rect(self.box_rect.centerx - 60, self.box_rect.bottom - 55, 120, 40)
        self.text_y_start = self.box_rect.y + self.BODY_DY

        left_x, right_x = self.box_rect.x + _CONTENT_MARGIN, self.box_rect.right - _CONTENT_MARGIN
        self.content_rect = pygame.Rect(
            left_x, self.text_y_start - self.link_font.get_height() // 2,
            right_x - left_x, 0)
        self.content_rect.height = max(0, self.ok_rect.top - _CONTENT_GAP - self.content_rect.top)
        self.link_rects = []
        y = self.text_y_start + self.body_height()
        if self.image_rows:
            y += _CONTENT_GAP
            for grid_row in grid_rows:
                row_h = max(cell["height"] for cell in grid_row)
                for column, cell in enumerate(grid_row):
                    cell_left = left_x + column * (cell_w + _IMAGE_COLUMN_GAP)
                    if self.align == "left":
                        x = cell_left
                    elif self.align == "right":
                        x = cell_left + cell_w - cell["width"]
                    else:
                        x = cell_left + (cell_w - cell["width"]) // 2
                    cell["rect"] = pygame.Rect(x, y, cell["width"], row_h)
                    cell["image_rect"] = cell["image"].get_rect(
                        center=(x + _IMAGE_SIZE // 2, cell["rect"].centery))
                y += row_h + _IMAGE_ROW_GAP
        y += _CONTENT_GAP if self.links else 0
        for link in self.links:
            w = self.link_font.size(link.get("text", ""))[0]
            if self.align == "left":
                x = left_x
            elif self.align == "right":
                x = right_x - w
            else:
                x = self.box_rect.centerx - w // 2
            self.link_rects.append(pygame.Rect(x, y, w, self.link_font.get_height()))
            y += self.link_font.get_height() + 8
        self.max_scroll = max(0, y - self.content_rect.bottom) if self.image_rows else 0
        self._sync_scrollbar()

    def _sync_scrollbar(self):
        self.scroll_track_rect, self.scroll_handle_rect = ui_bars.get_standard_scrollbar_rects(
            -self.scroll_y, -self.max_scroll,
            self.content_rect.right + _SCROLLBAR_GAP, self.content_rect.top,
            self.content_rect.height, width=_SCROLLBAR_WIDTH)

    def _set_scroll(self, value):
        self.scroll_y = max(0, min(self.max_scroll, value))
        self._sync_scrollbar()

    def _drag_scrollbar(self, mouse_y):
        track = self.scroll_track_rect
        self._set_scroll(-ui_bars.calculate_scroll_snap(
            mouse_y - self._scroll_drag_offset, -self.max_scroll, track.top, track.height))

    def draw_body_lines(self, surface):
        if not self.image_rows:
            return super().draw_body_lines(surface)
        clip = surface.get_clip()
        surface.set_clip(clip.clip(self.content_rect))
        try:
            return super().draw_body_lines(surface, offset_y=-self.scroll_y)
        finally:
            surface.set_clip(clip)

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.MOUSEWHEEL and self.image_rows:
                self._set_scroll(self.scroll_y - event.y * _SCROLL_STEP)
            elif event.type == pygame.MOUSEMOTION and self._scroll_drag_offset is not None:
                self._drag_scrollbar(event.pos[1])
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._scroll_drag_offset = None
            elif event.type == pygame.WINDOWFOCUSLOST:
                self._scroll_drag_offset = None
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE,
                                 pygame.K_SPACE, _back_key()):
                    self._finish()
                elif event.key in (pygame.K_UP, pygame.K_DOWN):
                    step = _SCROLL_STEP if event.key == pygame.K_DOWN else -_SCROLL_STEP
                    self._set_scroll(self.scroll_y + step)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.ok_rect.collidepoint(event.pos):
                    self._finish()
                    return
                if self.scroll_track_rect is not None and self.scroll_track_rect.collidepoint(event.pos):
                    # Preserve where the thumb was grabbed so the first motion
                    # doesn't jump. Track clicks center the thumb at the pointer.
                    if self.scroll_handle_rect.collidepoint(event.pos):
                        self._scroll_drag_offset = event.pos[1] - self.scroll_handle_rect.centery
                    else:
                        self._scroll_drag_offset = 0
                        self._drag_scrollbar(event.pos[1])
                    continue
                for rect, link in zip(self.link_rects, self.links):
                    if self.image_rows and not self.content_rect.collidepoint(event.pos):
                        continue
                    if link.get("url") and rect.move(0, -self.scroll_y).collidepoint(event.pos):
                        webbrowser.open(link["url"])
                        return

    def draw_content(self, surface):
        clip = surface.get_clip()
        if self.image_rows:
            surface.set_clip(clip.clip(self.content_rect))
        try:
            self._draw_extra_content(surface)
        finally:
            surface.set_clip(clip)

        self.scroll_track_rect, self.scroll_handle_rect = ui_bars.draw_standard_scrollbar(
            surface, -self.scroll_y, -self.max_scroll,
            self.content_rect.right + _SCROLLBAR_GAP, self.content_rect.top,
            self.content_rect.height, width=_SCROLLBAR_WIDTH)
        accent = _KIND_ACCENTS["info"]
        self.draw_button(surface, self.ok_rect, "Close", accent, _lighten(accent))

    def _draw_extra_content(self, surface):
        mx, my = pygame.mouse.get_pos()
        for row in self.image_rows:
            surface.blit(row["image"], row["image_rect"].move(0, -self.scroll_y))
            text_h = len(row["labels"]) * (self.link_font.get_height() + 2)
            y = row["rect"].centery - text_h // 2 - self.scroll_y
            for label in row["labels"]:
                surface.blit(label, (row["rect"].left + _IMAGE_SIZE + _IMAGE_TEXT_GAP, y))
                y += self.link_font.get_height() + 2
        for rect, link in zip(self.link_rects, self.links):
            rect = rect.move(0, -self.scroll_y)
            has_url = bool(link.get("url"))
            is_hovered = has_url and rect.collidepoint(mx, my)
            color = _LINK_HOVER_COLOR if is_hovered else (_LINK_COLOR if has_url else c.UI_TEXT_LIGHT)
            surface.blit(self.link_font.render(link.get("text", ""), True, color), rect.topleft)
            if is_hovered:
                pygame.draw.line(surface, color, (rect.left, rect.bottom), (rect.right, rect.bottom), 2)

def _show_person_info_standalone(name, info_text, links, align, tk_parent, on_result, images=None):
    _run_blocking(lambda surf: _PersonInfoModal(surf, name, info_text, links, None, align, images),
                  tk_parent)
    if on_result:
        on_result()


def show_person_info(name, info_text="", links=None, align="center", tk_parent=None, on_result=None, *, images=None):
    """Popup with free-text info about `name`, plus a list of clickable links below it.

    links is a list of {"text": str, "url": str} dicts; each renders as its own
    clickable line and opens its url in a browser when clicked. align controls
    the info text's horizontal alignment: "left", "center" (default), or "right".
    images is a list of {"path": str, "text": str} entries displayed in two
    columns between the info and links. Labels default to filenames. Overflow
    content scrolls with a draggable scrollbar, mouse wheel or arrow keys while
    Close stays visible.
    """
    surface = pygame.display.get_surface()
    if surface is None:
        _show_person_info_standalone(name, info_text, links, align, tk_parent, on_result, images)
        return

    modal_stack.push(_PersonInfoModal(surface, name, info_text, links, on_result, align, images))
