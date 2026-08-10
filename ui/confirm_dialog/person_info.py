import webbrowser
import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts
from ui import modal_stack
from ui.confirm_dialog.base import _BaseModal, _back_key, _lighten, _run_blocking
from ui.confirm_dialog.message_box import _KIND_ACCENTS

_LINK_COLOR = (100, 100, 255)
_LINK_HOVER_COLOR = (255, 255, 0)


class _PersonInfoModal(_BaseModal):
    """Popup for a Credits entry: a title, an optional free-text info section,
    and an optional list of clickable links below it."""

    BOX_MAX_W = 560
    BOX_MIN_H = 220
    BOX_CHROME_H = 180   # 110 of chrome plus the 70 the Close row occupies
    BORDER_COLOR = _KIND_ACCENTS["info"]
    BORDER_WIDTH = 3
    PASSES_RESULT = False

    def __init__(self, surface, name, info_text, links, on_result, align="center"):
        self.align = align if align in ("left", "center", "right") else "center"
        self.BODY_ALIGN = self.align
        self.links = links or []
        self.link_font = fonts.get("normal")

        links_h = len(self.links) * (self.link_font.get_height() + 8)
        super().__init__(surface, name, info_text, on_result,
                         extra_h=links_h + (20 if self.links else 0))

        self.name = name
        self.ok_rect = pygame.Rect(self.box_rect.centerx - 60, self.box_rect.bottom - 55, 120, 40)
        self.text_y_start = self.box_rect.y + self.BODY_DY

        left_x, right_x = self.box_rect.x + 40, self.box_rect.right - 40
        self.link_rects = []
        y = self.text_y_start + self.body_height() + (20 if self.links else 0)
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

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE,
                                 pygame.K_SPACE, _back_key()):
                    self._finish()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.ok_rect.collidepoint(event.pos):
                    self._finish()
                    return
                for rect, link in zip(self.link_rects, self.links):
                    if link.get("url") and rect.collidepoint(event.pos):
                        webbrowser.open(link["url"])
                        return

    def draw_content(self, surface):
        mx, my = pygame.mouse.get_pos()
        for rect, link in zip(self.link_rects, self.links):
            has_url = bool(link.get("url"))
            is_hovered = has_url and rect.collidepoint(mx, my)
            color = _LINK_HOVER_COLOR if is_hovered else (_LINK_COLOR if has_url else c.UI_TEXT_LIGHT)
            surface.blit(self.link_font.render(link.get("text", ""), True, color), rect.topleft)
            if is_hovered:
                pygame.draw.line(surface, color, (rect.left, rect.bottom), (rect.right, rect.bottom), 2)

        accent = _KIND_ACCENTS["info"]
        self.draw_button(surface, self.ok_rect, "Close", accent, _lighten(accent))


def _show_person_info_standalone(name, info_text, links, align, tk_parent, on_result):
    _run_blocking(lambda surf: _PersonInfoModal(surf, name, info_text, links, None, align),
                  tk_parent)
    if on_result:
        on_result()


def show_person_info(name, info_text="", links=None, align="center", tk_parent=None, on_result=None):
    """Popup with free-text info about `name`, plus a list of clickable links below it.

    links is a list of {"text": str, "url": str} dicts; each renders as its own
    clickable line and opens its url in a browser when clicked. align controls
    the info text's horizontal alignment: "left", "center" (default), or "right".
    """
    surface = pygame.display.get_surface()
    if surface is None:
        _show_person_info_standalone(name, info_text, links, align, tk_parent, on_result)
        return

    modal_stack.push(_PersonInfoModal(surface, name, info_text, links, on_result, align))
