import functools
import json
import os
import re

import pygame
from data import queries
from ui.background_styles import TUTORIAL_PANEL_STYLES
from ui.dialogs.base import _BaseModal, _back_key, _lighten, open_modal
from ui.bars import ui_bars
import data.constants as c
from ui.rendering.font_manager import fonts
from ui.widgets import ui_elements
from ui.widgets.text_utils import fit_text, render_inline_text, wrap_text

_KIND_ACCENTS = {
    "info": (80, 150, 220),
    "success": (60, 170, 90),
    "warning": (210, 160, 40),
    "error": (200, 70, 70),
}


class _MessageModal(_BaseModal):
    """A titled message with one OK button. The "info" kind is the blue popup:
    it plays Info.mp3 when it opens and Back.wav when it closes.

    Every message popup shares this scrolling body, including help text and
    Credits entries (person_info._PersonInfoModal). A box taller than the
    window stops at the window edge. Its content then scrolls with a draggable
    scrollbar, the mouse wheel, Up and Down, and Page Up and Page Down, while OK
    stays visible.

    A subclass adds content below the message: it reports where that content
    ends with set_content_bottom, draws it in draw_extra_content, and answers
    clicks in handle_content_click.
    """
    BOX_MAX_W = 520
    BOX_CHROME_H = 170   # 110 of chrome plus the 60 the OK row occupies
    BORDER_WIDTH = 3
    PASSES_RESULT = False
    #: The scrollbar sits in the right margin, so text never runs under it.
    TEXT_MARGIN = 40
    CONTENT_BUTTON_GAP = 10
    VIEWPORT_MARGIN = 20
    SCROLLBAR_WIDTH = 15
    SCROLLBAR_GAP = 12

    def __init__(self, surface, title, message, on_result, kind, inline_parts=None, extra_h=0, *, align=None):
        if align is not None:
            self.BODY_ALIGN = align
        self.accent = _KIND_ACCENTS.get(kind, _KIND_ACCENTS["info"])
        self.is_info = self.accent == _KIND_ACCENTS["info"]
        if self.is_info:
            ui_elements.play_ui_sound("info")
        self.inline_lines = (render_inline_text(inline_parts, fonts.get("normal"),
                             max(1, min(self.BOX_MAX_W, surface.get_width() - 40) - 2 * self.TEXT_MARGIN),
                             (210, 210, 210), wrap=True) if inline_parts is not None else None)
        self.inline_height = sum(line.get_height() + 2 for line in self.inline_lines or [])
        super().__init__(surface, title, message, on_result, extra_h=extra_h)
        self.box_rect.height = min(self.box_rect.height, surface.get_height() - 2 * self.VIEWPORT_MARGIN)
        self.box_rect.centery = surface.get_height() // 2
        self.BORDER_COLOR = self.accent
        self.ok_rect = pygame.Rect(self.box_rect.centerx - 60, self.box_rect.bottom - 55, 120, 40)
        self.ok_button = ui_elements.Button(*self.ok_rect.topleft, self.ok_rect.size, "blue", "OK",
                                            self._finish, sound_kind="back" if self.is_info else "click")
        self.ok_button.set_colors(self.accent, _lighten(self.accent))

        # Plain lines are drawn centred on BODY_DY, so the content starts half
        # a line above it.
        self.content_rect = pygame.Rect(
            self.box_rect.x + self.TEXT_MARGIN,
            self.box_rect.y + self.BODY_DY - self.msg_font.get_height() // 2,
            self.box_rect.width - 2 * self.TEXT_MARGIN, 0)
        self.content_rect.height = max(
            0, self.ok_rect.top - self.CONTENT_BUTTON_GAP - self.content_rect.top)
        self.scroll_y = 0
        self.max_scroll = 0
        self._scroll_drag_offset = None
        self.set_content_bottom(self.content_rect.top + self.body_height())

    # -- scrolling ------------------------------------------------------ #

    def set_content_bottom(self, bottom):
        """Records where the unscrolled content ends, which sets how far it scrolls."""
        self.max_scroll = max(0, bottom - self.content_rect.bottom)
        self._set_scroll(self.scroll_y)

    def _scrollbar_rects(self):
        return (self.content_rect.right + self.SCROLLBAR_GAP, self.content_rect.top,
                self.content_rect.height)

    def _set_scroll(self, value):
        self.scroll_y = max(0, min(self.max_scroll, value))
        # Kept current between frames, so a click before the first draw hits the bar.
        self.scroll_track_rect, self.scroll_handle_rect = ui_bars.get_standard_scrollbar_rects(
            -self.scroll_y, -self.max_scroll, *self._scrollbar_rects(), width=self.SCROLLBAR_WIDTH)

    def _drag_scrollbar(self, mouse_y):
        track = self.scroll_track_rect
        self._set_scroll(-ui_bars.calculate_scroll_snap(
            mouse_y - self._scroll_drag_offset, -self.max_scroll, track.top, track.height))

    def _scroll_key_step(self, key):
        return {pygame.K_DOWN: c.SCROLL_STEP, pygame.K_UP: -c.SCROLL_STEP,
                pygame.K_PAGEDOWN: self.content_rect.height,
                pygame.K_PAGEUP: -self.content_rect.height}.get(key, 0)

    def close_on_key(self, key):
        """Closes the popup if `key` dismisses it, and says whether it did."""
        if key not in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_SPACE, _back_key()):
            return False
        if self.is_info:
            ui_elements.play_ui_sound("back")
        self._finish()
        return True

    def body_height(self):
        if self.inline_lines is None:
            return super().body_height()
        return self.inline_height

    def draw_body_lines(self, surface, offset_y=0):
        clip = surface.get_clip()
        surface.set_clip(clip.clip(self.content_rect))
        try:
            if self.inline_lines is None:
                return super().draw_body_lines(surface, offset_y - self.scroll_y)
            y = self.content_rect.top + offset_y - self.scroll_y
            for line in self.inline_lines:
                surface.blit(line, (self.content_rect.left, y))
                y += line.get_height() + 2
            return y
        finally:
            surface.set_clip(clip)

    def handle_events(self, events):
        for event in events:
            if self._resolved:
                return
            self.ok_button.handle_event(event)
            if event.type == pygame.MOUSEWHEEL:
                self._set_scroll(self.scroll_y - event.y * c.SCROLL_STEP)
            elif event.type == pygame.MOUSEMOTION and self._scroll_drag_offset is not None:
                self._drag_scrollbar(event.pos[1])
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._scroll_drag_offset = None
            elif event.type == pygame.WINDOWFOCUSLOST:
                self._scroll_drag_offset = None
            elif event.type == pygame.KEYDOWN:
                if not self.close_on_key(event.key):
                    self._set_scroll(self.scroll_y + self._scroll_key_step(event.key))
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.scroll_track_rect is not None and self.scroll_track_rect.collidepoint(event.pos):
                    # Keep where the handle was grabbed so the first motion does
                    # not jump. A track click centres the handle on the pointer.
                    if self.scroll_handle_rect.collidepoint(event.pos):
                        self._scroll_drag_offset = event.pos[1] - self.scroll_handle_rect.centery
                    else:
                        self._scroll_drag_offset = 0
                        self._drag_scrollbar(event.pos[1])
                elif self.content_rect.collidepoint(event.pos) and self.handle_content_click(event.pos):
                    return

    def handle_content_click(self, pos):
        """A click on the visible content. Return True when it was used."""
        return False

    def draw_extra_content(self, surface):
        """Content below the message, drawn clipped to the scrolled content area."""
        pass

    def draw_content(self, surface):
        clip = surface.get_clip()
        surface.set_clip(clip.clip(self.content_rect))
        try:
            self.draw_extra_content(surface)
        finally:
            surface.set_clip(clip)
        self.scroll_track_rect, self.scroll_handle_rect = ui_bars.draw_standard_scrollbar(
            surface, -self.scroll_y, -self.max_scroll, *self._scrollbar_rects(),
            width=self.SCROLLBAR_WIDTH)
        self.ok_button.draw(surface)


#: Help content. See documentation/general_info.txt, HELP CONTENT, for the format.
TUTORIAL_PATH = "data/json/tutorial.json"
_ICON_MARKER = re.compile(r"\[icon:([a-z_]+)(?::([1-9][0-9]*))?\]")
_TEXT_BLOCK_ALIGNMENTS = ("left", "center")
_STEP_COLUMN_COUNTS = (1, 2)


def _require(value, kind, where):
    """Return value when it has the required type and is not empty."""
    if not isinstance(value, kind) or (isinstance(value, (str, list)) and not value):
        raise ValueError(f"{where} must be a non-empty {kind.__name__}.")
    return value


def _validate_tutorial_block(block, where):
    _require(block, dict, where)
    kind = block.get("type")
    if kind == "text":
        _require(block.get("text"), str, f"{where}.text")
        if block.get("align", "left") not in _TEXT_BLOCK_ALIGNMENTS:
            raise ValueError(f"{where}.align must be one of {', '.join(_TEXT_BLOCK_ALIGNMENTS)}.")
    elif kind == "steps":
        if block.get("columns", 1) not in _STEP_COLUMN_COUNTS:
            raise ValueError(f"{where}.columns must be 1 or 2.")
        for index, item in enumerate(_require(block.get("items"), list, f"{where}.items")):
            item_where = f"{where}.items[{index}]"
            _require(item, dict, item_where)
            for field in ("heading", "text"):
                _require(item.get(field), str, f"{item_where}.{field}")
            if "icon" in item:
                _require(item["icon"], str, f"{item_where}.icon")
    elif kind == "mouse_buttons":
        for index, item in enumerate(_require(block.get("items"), list, f"{where}.items")):
            item_where = f"{where}.items[{index}]"
            _require(item, dict, item_where)
            for field in ("image", "heading"):
                _require(item.get(field), str, f"{item_where}.{field}")
            for line_index, line in enumerate(_require(item.get("lines"), list, f"{item_where}.lines")):
                _require(line, str, f"{item_where}.lines[{line_index}]")
    elif kind == "key_box":
        for field in ("heading", "text"):
            _require(block.get(field), str, f"{where}.{field}")
    else:
        raise ValueError(f"{where}.type must be text, steps, mouse_buttons, or key_box.")


def validate_tutorial(content):
    """Check the Help content shape. Errors name the field to correct."""
    _require(content, dict, "The file")
    for category_index, category in enumerate(_require(content.get("categories"), list, "categories")):
        where = f"categories[{category_index}]"
        _require(category, dict, where)
        _require(category.get("title"), str, f"{where}.title")
        if "icon" in category:
            _require(category["icon"], str, f"{where}.icon")
        for topic_index, topic in enumerate(_require(category.get("topics"), list, f"{where}.topics")):
            topic_where = f"{where}.topics[{topic_index}]"
            _require(topic, dict, topic_where)
            _require(topic.get("title"), str, f"{topic_where}.title")
            if not isinstance(topic.get("subtitle", ""), str):
                raise ValueError(f"{topic_where}.subtitle must be a str.")
            for block_index, block in enumerate(_require(topic.get("blocks"), list, f"{topic_where}.blocks")):
                _validate_tutorial_block(block, f"{topic_where}.blocks[{block_index}]")
    return content


@functools.lru_cache(maxsize=None)
def load_tutorial(path=TUTORIAL_PATH):
    """Read the Help content once per path. Restart the game after file edits."""
    try:
        with open(path, encoding="utf-8") as source:
            content = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot load {path}. Correct the Help content file: {error}") from error
    try:
        return validate_tutorial(content)
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from None


def _fit_surface(image, max_width, max_height, *, smooth=True):
    """Scale an image into a slot with one scale factor, so it keeps its proportions."""
    scale = min(max_width / image.get_width(), max_height / image.get_height())
    size = (max(1, round(image.get_width() * scale)), max(1, round(image.get_height() * scale)))
    return (pygame.transform.smoothscale if smooth else pygame.transform.scale)(image, size)


class _NavigationIntroPopup:
    """Draggable Help window over the live map, shown once for fresh games.

    Unlike a modal-stack dialog, this belongs to the map screen itself.  The
    player can still see the map and HUD behind it, and clicks outside the
    panel continue to use the normal map controls.

    The category list on the left opens one category at a time. Previous and
    Next step through every topic in order, across categories. Content comes
    from TUTORIAL_PATH. Each topic is drawn onto one cached surface when it is
    selected, so frames only blit it.
    """
    WIDTH = 960
    HEIGHT = 500
    HEADER_H = 46
    FOOTER_H = 60
    RAIL_W = 210
    RAIL_INSET = 6
    RAIL_TOP_GAP = 6
    RAIL_LABEL_X = 8
    RAIL_ICON_SIZE = 20
    RAIL_ICON_GAP = 8
    CATEGORY_ROW_H = 28
    TOPIC_ROW_H = 22
    TOPIC_INDENT = 36
    CONTENT_SIDE_PAD = 24
    SUBTITLE_TOP_GAP = 8
    SUBTITLE_LINE_GAP = 2
    SUBTITLE_CONTENT_GAP = 12
    LINE_GAP = 2
    BLOCK_GAP = 16
    INLINE_ICON_GAP = 4
    STEP_GAP = 8
    STEP_COLUMN_GAP = 24
    STEP_MARKER_SIZE = 28
    STEP_TEXT_X = 39
    STEP_HEADING_GAP = 2
    MOUSE_IMAGE_SLOT = (72, 84)
    MOUSE_CAPTION_SIDE_PAD = 18
    MOUSE_HEADING_GAP = 12
    MOUSE_CAPTION_GAP = 6
    KEY_BOX_MIN_H = 36
    KEY_BOX_SIDE_PAD = 15
    KEY_BOX_TEXT_X = 125
    KEY_BOX_TEXT_PAD_Y = 6
    SCROLLBAR_W = 15
    SCROLLBAR_GAP = 8
    # This is what edits how offset the tutorial popup is when it spawns!
    INITIAL_CENTER_Y_OFFSET = -32
    BORDER_COLOR = _KIND_ACCENTS["info"]
    MOUSE_DIR = os.path.join(c.ASSETS_ROOT_DIR, "mouse")
    TITLE_COLOR = (255, 255, 255)
    HEADING_COLOR = (130, 205, 255)
    TEXT_COLOR = (225, 225, 225)
    SUBTITLE_COLOR = (205, 215, 225)
    MUTED_COLOR = (190, 205, 220)
    STEP_NUMBER_COLOR = (70, 115, 160)
    KEY_BOX_BORDER_COLOR = (70, 115, 160)
    MISSING_ICON_COLOR = (75, 85, 100)
    DISABLED_TEXT_COLOR = (145, 145, 145)
    CHECKBOX_LABEL = "Don't show this popup when starting a game"
    BLOCK_RENDERERS = {
        "text": "_text_block",
        "steps": "_steps_block",
        "mouse_buttons": "_mouse_buttons_block",
        "key_box": "_key_box_block",
    }
    #: The Help button reopens the topic viewed last in this session.
    last_topic_index = 0

    def __init__(self, map_screen, topic_index=0):
        self.map_screen = map_screen
        self.categories = load_tutorial()["categories"]
        self.topics = tuple((category_index, topic_index)
                            for category_index, category in enumerate(self.categories)
                            for topic_index in range(len(category["topics"])))
        self.first_topic = {}
        for index, (category_index, _topic_index) in enumerate(self.topics):
            self.first_topic.setdefault(category_index, index)
        self.rect = pygame.Rect(0, 0, self.WIDTH, self.HEIGHT)
        self.rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2 + self.INITIAL_CENTER_Y_OFFSET)
        self.dont_show_again = False
        self.is_dragging = False
        self.drag_offset = (0, 0)
        self.scroll_y = 0
        self.max_scroll = 0
        self._scroll_drag_offset = None
        self.title_font = fonts.get("heading2")
        self.label_font = fonts.get("small")
        self.body_font = fonts.get("tiny")
        self._prepared_topics = {}
        self._prepare_chrome()
        self.topic_index = None
        self.select_topic(topic_index)

    # -- prepared surfaces ---------------------------------------------- #

    def _column_width(self):
        """Width of the topic column, between the category list and the right edge."""
        return self.WIDTH - self.RAIL_W - 2 * self.CONTENT_SIDE_PAD

    def _content_width(self):
        """Topic content keeps room for its scrollbar, so text never runs under it."""
        return self._column_width() - self.SCROLLBAR_W - self.SCROLLBAR_GAP

    def _prepare_chrome(self):
        """Render the category list and footer labels once when the window opens."""
        label_width = self.RAIL_W - 2 * self.RAIL_INSET - self.RAIL_LABEL_X
        category_width = label_width - self.RAIL_ICON_SIZE - self.RAIL_ICON_GAP
        topic_width = self.RAIL_W - 2 * self.RAIL_INSET - self.TOPIC_INDENT
        self.category_labels = []
        for category in self.categories:
            icon = ui_elements.UI_ICONS.get(category.get("icon"))
            if icon is not None:
                icon = _fit_surface(icon, self.RAIL_ICON_SIZE, self.RAIL_ICON_SIZE)
            title = fit_text(category["title"], self.label_font, category_width)
            self.category_labels.append((
                icon,
                self.label_font.render(title, True, self.TEXT_COLOR),
                self.label_font.render(title, True, self.HEADING_COLOR)))
        self.topic_labels = []
        for category_index, topic_index in self.topics:
            title = self.categories[category_index]["topics"][topic_index]["title"]
            self.topic_labels.append(self.body_font.render(
                fit_text(title, self.body_font, topic_width), True, self.TEXT_COLOR))
        self.help_label = self.label_font.render("HELP", True, self.MUTED_COLOR)
        self.close_label = self.body_font.render("X", True, self.TITLE_COLOR)
        self.checkbox_label = self.body_font.render(self.CHECKBOX_LABEL, True, self.TEXT_COLOR)
        self.arrow_labels = {
            (label, enabled): self.label_font.render(
                label, True, self.TITLE_COLOR if enabled else self.DISABLED_TEXT_COLOR)
            for label in ("<", ">") for enabled in (True, False)}

    def _inline_parts(self, text, color):
        """Split text at [icon:name:size] markers into parts for render_inline_text."""
        parts = []
        position = 0
        for marker in _ICON_MARKER.finditer(text):
            before = text[position:marker.start()]
            icon = ui_elements.UI_ICONS.get(marker.group(1))
            if icon is None:
                parts.append((before, None))
            else:
                # Keep the preceding word with its image when a line wraps.
                word = re.search(r"(\S+)([ \t]*)$", before)
                label = word.group(1) if word else ""
                parts.append((before[:word.start()] if word else before, None))
                size = int(marker.group(2)) if marker.group(2) else self.body_font.get_height()
                icon = _fit_surface(icon, size, size, smooth=False)
                text_surf = self.body_font.render(label, True, color)
                gap = self.INLINE_ICON_GAP if label else 0
                height = max(self.body_font.get_height(), icon.get_height())
                group = pygame.Surface((text_surf.get_width() + gap + icon.get_width(), height), pygame.SRCALPHA)
                group.blit(text_surf, text_surf.get_rect(midleft=(0, height // 2)))
                group.blit(icon, icon.get_rect(midleft=(text_surf.get_width() + gap, height // 2)))
                parts.append(("", group))
            position = marker.end()
        parts.append((text[position:], None))
        return parts

    def _inline_lines(self, text, width, color):
        return render_inline_text(self._inline_parts(text, color), self.body_font, max(1, width),
                                  color, wrap=True, icon_gap=0)

    def _lines_height(self, lines):
        return max(0, sum(line.get_height() + self.LINE_GAP for line in lines) - self.LINE_GAP)

    def _blit_lines(self, surface, lines, x, y, *, centered=False):
        for line in lines:
            surface.blit(line, line.get_rect(midtop=(x, y)) if centered else (x, y))
            y += line.get_height() + self.LINE_GAP

    def _text_block(self, block, width):
        lines = self._inline_lines(block["text"], width, self.TEXT_COLOR)
        surface = pygame.Surface((width, max(1, self._lines_height(lines))), pygame.SRCALPHA)
        if block.get("align") == "center":
            self._blit_lines(surface, lines, width // 2, 0, centered=True)
        else:
            self._blit_lines(surface, lines, 0, 0)
        return surface

    def _draw_step_marker(self, surface, number, icon_name, center):
        """Draw an item's icon, or its number when the item names no icon."""
        size = self.STEP_MARKER_SIZE
        if icon_name is None:
            pygame.draw.circle(surface, self.STEP_NUMBER_COLOR, center, size // 2)
            label = self.label_font.render(str(number), True, self.TITLE_COLOR)
            surface.blit(label, label.get_rect(center=center))
            return
        icon = ui_elements.UI_ICONS.get(icon_name)
        if icon is None:
            # The registry is populated during game bootstrap. Keep a stable
            # reserved icon slot for lightweight test/tool views.
            slot = pygame.Rect(0, 0, size, size)
            slot.center = center
            pygame.draw.rect(surface, self.MISSING_ICON_COLOR, slot, 1)
            return
        icon = _fit_surface(icon, size, size)
        surface.blit(icon, icon.get_rect(center=center))

    def _steps_block(self, block, width):
        """Items fill each column top to bottom, so two columns read like two lists."""
        items = block["items"]
        columns = block.get("columns", 1)
        rows = -(-len(items) // columns)
        column_w = (width - (columns - 1) * self.STEP_COLUMN_GAP) // columns
        text_w = column_w - self.STEP_TEXT_X
        cells = []
        for item in items:
            heading = self.label_font.render(item["heading"], True, self.HEADING_COLOR)
            lines = self._inline_lines(item["text"], text_w, self.TEXT_COLOR)
            height = max(self.STEP_MARKER_SIZE,
                         heading.get_height() + self.STEP_HEADING_GAP + self._lines_height(lines))
            cells.append((item.get("icon"), heading, lines, height))
        row_heights = [max(cells[index][3] for index in range(row, len(cells), rows))
                       for row in range(rows)]
        surface = pygame.Surface(
            (width, sum(row_heights) + self.STEP_GAP * (rows - 1)), pygame.SRCALPHA)
        for index, (icon_name, heading, lines, _height) in enumerate(cells):
            column, row = divmod(index, rows)
            x = column * (column_w + self.STEP_COLUMN_GAP)
            y = sum(row_heights[:row]) + self.STEP_GAP * row
            self._draw_step_marker(surface, index + 1, icon_name,
                                   (x + self.STEP_MARKER_SIZE // 2, y + self.STEP_MARKER_SIZE // 2 - 1))
            surface.blit(heading, (x + self.STEP_TEXT_X, y))
            self._blit_lines(surface, lines, x + self.STEP_TEXT_X,
                             y + heading.get_height() + self.STEP_HEADING_GAP)
        return surface

    def _mouse_buttons_block(self, block, width):
        items = block["items"]
        column_w = width // len(items)
        caption_w = column_w - 2 * self.MOUSE_CAPTION_SIDE_PAD
        slot_w, slot_h = self.MOUSE_IMAGE_SLOT
        columns = []
        for item in items:
            # The supplied button images are deliberately tall and narrow;
            # fit them into this slot with one scale factor, never stretch
            # them to fill both dimensions.
            image = _fit_surface(ui_bars.get_ui_image(item["image"], directory=self.MOUSE_DIR), slot_w, slot_h)
            heading = self.label_font.render(item["heading"], True, self.HEADING_COLOR)
            lines = [line for text in item["lines"]
                     for line in self._inline_lines(text, caption_w, self.TEXT_COLOR)]
            columns.append((image, heading, lines))
        caption_h = max(heading.get_height() + self.MOUSE_CAPTION_GAP + self._lines_height(lines)
                        for _image, heading, lines in columns)
        surface = pygame.Surface((width, slot_h + self.MOUSE_HEADING_GAP + caption_h), pygame.SRCALPHA)
        for index, (image, heading, lines) in enumerate(columns):
            center_x = column_w * index + column_w // 2
            surface.blit(image, image.get_rect(center=(center_x, slot_h // 2)))
            heading_y = slot_h + self.MOUSE_HEADING_GAP
            surface.blit(heading, heading.get_rect(midtop=(center_x, heading_y)))
            self._blit_lines(surface, lines, center_x,
                             heading_y + heading.get_height() + self.MOUSE_CAPTION_GAP, centered=True)
        return surface

    def _key_box_block(self, block, width):
        """A recessed strip, so keyboard controls are not mistaken for a mouse gesture."""
        heading = self.label_font.render(block["heading"], True, self.HEADING_COLOR)
        lines = self._inline_lines(block["text"], width - self.KEY_BOX_TEXT_X - self.KEY_BOX_SIDE_PAD,
                                   self.TEXT_COLOR)
        lines_h = self._lines_height(lines)
        height = max(self.KEY_BOX_MIN_H, lines_h + 2 * self.KEY_BOX_TEXT_PAD_Y)
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        style = TUTORIAL_PANEL_STYLES["keyboard_navigation"]
        ui_elements.draw_pixel_panel(surface, surface.get_rect(), style["color"], self.KEY_BOX_BORDER_COLOR,
                                     recessed=True, gradient_strength=style["gradient_strength"])
        surface.blit(heading, (self.KEY_BOX_SIDE_PAD, (height - heading.get_height()) // 2))
        self._blit_lines(surface, lines, self.KEY_BOX_TEXT_X, (height - lines_h) // 2)
        return surface

    def _prepare_topic(self, index):
        """Draw one topic's title, subtitle, and content the first time it is selected."""
        prepared = self._prepared_topics.get(index)
        if prepared is not None:
            return prepared
        category_index, topic_index = self.topics[index]
        category = self.categories[category_index]
        topic = category["topics"][topic_index]
        width = self._content_width()
        blocks = [getattr(self, self.BLOCK_RENDERERS[block["type"]])(block, width)
                  for block in topic["blocks"]]
        content = pygame.Surface(
            (width, sum(block.get_height() + self.BLOCK_GAP for block in blocks) - self.BLOCK_GAP),
            pygame.SRCALPHA)
        y = 0
        for block in blocks:
            content.blit(block, (0, y))
            y += block.get_height() + self.BLOCK_GAP
        subtitle = topic.get("subtitle", "")
        prepared = self._prepared_topics[index] = {
            "title": self.title_font.render(topic["title"], True, self.TITLE_COLOR),
            "subtitle": [self.body_font.render(line, True, self.SUBTITLE_COLOR)
                         for line in (wrap_text(subtitle, self.body_font, self._column_width())
                                      if subtitle else ())],
            "counter": self.body_font.render(
                f"{topic_index + 1}/{len(category['topics'])}", True, self.MUTED_COLOR),
            "content": content,
        }
        return prepared

    # -- selection, layout, and scrolling ------------------------------- #

    def select_topic(self, index):
        """Show one topic. Returns whether the selection changed."""
        index = max(0, min(index, len(self.topics) - 1))
        if index == self.topic_index:
            return False
        self.topic_index = type(self).last_topic_index = index
        self.prepared = self._prepare_topic(index)
        self.scroll_y = 0
        self._scroll_drag_offset = None
        self._layout()
        return True

    def change_page(self, direction):
        if self.select_topic(self.topic_index + direction):
            ui_elements.play_ui_sound("click")

    def _layout(self):
        x, y = self.rect.topleft
        self.header_rect = pygame.Rect(x, y, self.rect.width, self.HEADER_H)
        self.close_rect = pygame.Rect(self.rect.right - 34, y + 11, 22, 22)
        self.checkbox_rect = pygame.Rect(x + 30, self.rect.bottom - 43, 20, 20)
        self.prev_rect = pygame.Rect(self.rect.right - 118, self.rect.bottom - 51, 36, 32)
        self.next_rect = pygame.Rect(self.rect.right - 72, self.rect.bottom - 51, 36, 32)
        self.rail_rect = pygame.Rect(x + self.RAIL_INSET, y + self.HEADER_H, self.RAIL_W - 2 * self.RAIL_INSET,
                                     self.HEIGHT - self.HEADER_H - self.FOOTER_H)
        self.column_center_x = x + self.RAIL_W + (self.WIDTH - self.RAIL_W) // 2

        # Only the open category lists its topics.
        open_category = self.topics[self.topic_index][0]
        self.rail_rows = []
        row_y = self.rail_rect.y + self.RAIL_TOP_GAP
        for category_index, category in enumerate(self.categories):
            self.rail_rows.append((pygame.Rect(self.rail_rect.x, row_y, self.rail_rect.width, self.CATEGORY_ROW_H),
                                   "category", category_index))
            row_y += self.CATEGORY_ROW_H
            if category_index == open_category:
                for topic_index in range(len(category["topics"])):
                    self.rail_rows.append((pygame.Rect(self.rail_rect.x, row_y, self.rail_rect.width,
                                                       self.TOPIC_ROW_H),
                                           "topic", self.first_topic[category_index] + topic_index))
                    row_y += self.TOPIC_ROW_H

        subtitle_lines = self.prepared["subtitle"]
        subtitle_h = max(0, sum(line.get_height() + self.SUBTITLE_LINE_GAP for line in subtitle_lines)
                         - self.SUBTITLE_LINE_GAP)
        self.subtitle_top = y + self.HEADER_H + self.SUBTITLE_TOP_GAP
        content_top = self.subtitle_top + subtitle_h + self.SUBTITLE_CONTENT_GAP
        self.content_rect = pygame.Rect(x + self.RAIL_W + self.CONTENT_SIDE_PAD, content_top,
                                        self._content_width(),
                                        max(0, self.rect.bottom - self.FOOTER_H - content_top))
        self.max_scroll = max(0, self.prepared["content"].get_height() - self.content_rect.height)
        self._set_scroll(self.scroll_y)

    def _set_scroll(self, value):
        self.scroll_y = max(0, min(self.max_scroll, value))
        # Kept current between frames, so a click before the first draw hits the bar.
        self.scroll_track_rect, self.scroll_handle_rect = ui_bars.get_standard_scrollbar_rects(
            -self.scroll_y, -self.max_scroll, *self._scrollbar_track(), width=self.SCROLLBAR_W)

    def _scrollbar_track(self):
        return (self.content_rect.right + self.SCROLLBAR_GAP, self.content_rect.top, self.content_rect.height)

    def _drag_scrollbar(self, mouse_y):
        track = self.scroll_track_rect
        self._set_scroll(-ui_bars.calculate_scroll_snap(
            mouse_y - self._scroll_drag_offset, -self.max_scroll, track.top, track.height))

    def _persist_checkbox(self):
        settings = dict(queries.get_settings() or {})
        settings["show_intro_popup"] = not self.dont_show_again
        queries.save_cached_json("settings", settings)

    def dismiss(self):
        if getattr(self.map_screen, "navigation_intro_popup", None) is self:
            self.map_screen.navigation_intro_popup = None

    def _move_to(self, x, y):
        self.rect.topleft = (x, y)
        display = pygame.display.get_surface()
        bounds = display.get_rect() if display is not None else pygame.Rect(
            0, 0, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        self.rect.clamp_ip(bounds)
        self._layout()

    def _click_rail(self, pos):
        """Open a category at its first topic, or show a topic. Returns whether a row was hit."""
        for rect, kind, index in self.rail_rows:
            if rect.collidepoint(pos):
                if kind == "category" and index == self.topics[self.topic_index][0]:
                    return True  # The open category keeps its current topic.
                target = self.first_topic[index] if kind == "category" else index
                if self.select_topic(target):
                    ui_elements.play_ui_sound("click")
                return True
        return False

    # -- input ---------------------------------------------------------- #

    def handle_event(self, event):
        """Handle popup-local input; True prevents that event reaching the map."""
        if event.type == pygame.KEYDOWN:
            # Escape is handled globally by the map.  In particular, it closes
            # the province menu before this popup receives the same event; do
            # not mistake that close for a request to dismiss the tutorial.
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.dismiss()
                return True
            return False

        if event.type == pygame.MOUSEWHEEL:
            # Wheel events carry no position. Over the popup, the wheel scrolls
            # the topic instead of zooming the map behind it.
            if not self.rect.collidepoint(pygame.mouse.get_pos()):
                return False
            self._set_scroll(self.scroll_y - event.y * c.SCROLL_STEP)
            return True

        # Middle/right mouse belong to map pan and unit selection even when
        # their drag crosses this popup.  Only left mouse operates its chrome.
        if (event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP)
                and getattr(event, "button", None) in (2, 3)):
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.close_rect.collidepoint(event.pos):
                ui_elements.play_ui_sound("back")
                self.dismiss()
                return True
            if self.prev_rect.collidepoint(event.pos):
                self.change_page(-1)
                return True
            if self.next_rect.collidepoint(event.pos):
                self.change_page(1)
                return True
            if self.checkbox_rect.collidepoint(event.pos):
                self.dont_show_again = not self.dont_show_again
                self._persist_checkbox()
                return True
            if self.scroll_track_rect is not None and self.scroll_track_rect.collidepoint(event.pos):
                # Keep where the handle was grabbed so the first motion does
                # not jump. A track click centres the handle on the pointer.
                if self.scroll_handle_rect.collidepoint(event.pos):
                    self._scroll_drag_offset = event.pos[1] - self.scroll_handle_rect.centery
                else:
                    self._scroll_drag_offset = 0
                    self._drag_scrollbar(event.pos[1])
                return True
            if self._click_rail(event.pos):
                return True
            if self.rect.collidepoint(event.pos):
                self.is_dragging = True
                self.drag_offset = (event.pos[0] - self.rect.x,
                                    event.pos[1] - self.rect.y)
                return True
            return False

        if event.type == pygame.MOUSEMOTION:
            if self._scroll_drag_offset is not None:
                self._drag_scrollbar(event.pos[1])
                return True
            if self.is_dragging:
                self._move_to(event.pos[0] - self.drag_offset[0],
                              event.pos[1] - self.drag_offset[1])
                return True
            buttons = getattr(event, "buttons", ())
            middle_or_right_held = ((len(buttons) > 1 and buttons[1])
                                    or (len(buttons) > 2 and buttons[2])
                                    or getattr(self.map_screen, "unit_selection_drag", None)
                                    or getattr(getattr(self.map_screen, "camera", None),
                                               "_middle_drag_last_pos", None) is not None)
            if middle_or_right_held:
                return False
            return self.rect.collidepoint(event.pos)

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was_dragging = self.is_dragging or self._scroll_drag_offset is not None
            self.is_dragging = False
            self._scroll_drag_offset = None
            return was_dragging or self.rect.collidepoint(event.pos)

        if hasattr(event, "pos"):
            return self.rect.collidepoint(event.pos)
        return False

    # -- drawing -------------------------------------------------------- #

    def _draw_rail(self, surface):
        style = TUTORIAL_PANEL_STYLES["rail"]
        ui_elements.draw_pixel_panel(surface, self.rail_rect, style["color"], self.KEY_BOX_BORDER_COLOR,
                                     recessed=True, gradient_strength=style["gradient_strength"])
        open_category = self.topics[self.topic_index][0]
        selected_style = TUTORIAL_PANEL_STYLES["rail_selected"]
        clip = surface.get_clip()
        surface.set_clip(clip.clip(self.rail_rect))
        try:
            for rect, kind, index in self.rail_rows:
                if kind == "category":
                    icon, label, open_label = self.category_labels[index]
                    x = rect.x + self.RAIL_LABEL_X
                    if icon is not None:
                        surface.blit(icon, icon.get_rect(center=(x + self.RAIL_ICON_SIZE // 2, rect.centery)))
                    label = open_label if index == open_category else label
                    surface.blit(label, label.get_rect(
                        midleft=(x + self.RAIL_ICON_SIZE + self.RAIL_ICON_GAP, rect.centery)))
                else:
                    if index == self.topic_index:
                        ui_elements.draw_pixel_panel(surface, rect.inflate(-4, 0), selected_style["color"],
                                                     self.BORDER_COLOR, border_width=1,
                                                     gradient_strength=selected_style["gradient_strength"])
                    label = self.topic_labels[index]
                    surface.blit(label, label.get_rect(midleft=(rect.x + self.TOPIC_INDENT, rect.centery)))
        finally:
            surface.set_clip(clip)

    def draw(self, surface):
        style = TUTORIAL_PANEL_STYLES["main"]
        ui_elements.draw_pixel_panel(surface, self.rect, style["color"], self.BORDER_COLOR,
                                     gradient_strength=style["gradient_strength"])

        surface.blit(self.help_label, self.help_label.get_rect(
            midleft=(self.rect.x + 14, self.header_rect.centery)))
        title = self.prepared["title"]
        surface.blit(title, title.get_rect(center=(self.column_center_x, self.header_rect.centery)))
        subtitle_y = self.subtitle_top
        for line in self.prepared["subtitle"]:
            surface.blit(line, line.get_rect(midtop=(self.column_center_x, subtitle_y)))
            subtitle_y += line.get_height() + self.SUBTITLE_LINE_GAP

        ui_elements.draw_pixel_button(surface, self.close_rect, (150, 0, 0))
        surface.blit(self.close_label, self.close_label.get_rect(center=self.close_rect.center))

        self._draw_rail(surface)

        content = self.prepared["content"]
        surface.blit(content, self.content_rect.topleft,
                     area=pygame.Rect(0, self.scroll_y, self.content_rect.width, self.content_rect.height))
        self.scroll_track_rect, self.scroll_handle_rect = ui_bars.draw_standard_scrollbar(
            surface, -self.scroll_y, -self.max_scroll, *self._scrollbar_track(), width=self.SCROLLBAR_W)

        pygame.draw.rect(surface, (230, 230, 230), self.checkbox_rect, 2)
        if self.dont_show_again:
            pygame.draw.line(surface, (80, 190, 100), self.checkbox_rect.topleft,
                             self.checkbox_rect.bottomright, 3)
            pygame.draw.line(surface, (80, 190, 100), self.checkbox_rect.topright,
                             self.checkbox_rect.bottomleft, 3)
        surface.blit(self.checkbox_label, (self.checkbox_rect.right + 9, self.checkbox_rect.y + 2))

        counter = self.prepared["counter"]
        surface.blit(counter, counter.get_rect(midright=(self.prev_rect.x - 12, self.prev_rect.centery)))
        for rect, label, enabled in (
                (self.prev_rect, "<", self.topic_index > 0),
                (self.next_rect, ">", self.topic_index < len(self.topics) - 1)):
            ui_elements.draw_pixel_button(surface, rect, self.BORDER_COLOR, disabled=not enabled)
            button = self.arrow_labels[(label, enabled)]
            surface.blit(button, button.get_rect(center=rect.center))


def show_message(title, message, tk_parent=None, kind="info", on_result=None, *, inline_parts=None, align=None):
    """Drop-in replacement for messagebox.showinfo / showwarning / showerror.

    `kind` picks the accent color: "info", "success", "warning", or "error".
    `align` sets plain message lines to "left", "center", or "right". The default is centered.
    on_result, if given, is called (with no arguments) once the user dismisses it.
    """
    open_modal(lambda surface, callback: _MessageModal(surface, title, message, callback, kind, inline_parts,
                                                       align=align),
               on_result, tk_parent)


def show_info(title, message, tk_parent=None, on_result=None, *, inline_parts=None, align=None):
    show_message(title, message, tk_parent=tk_parent, kind="info", on_result=on_result, inline_parts=inline_parts,
                 align=align)


def show_success(title, message, tk_parent=None, on_result=None):
    show_message(title, message, tk_parent=tk_parent, kind="success", on_result=on_result)


def show_warning(title, message, tk_parent=None, on_result=None):
    show_message(title, message, tk_parent=tk_parent, kind="warning", on_result=on_result)


def show_error(title, message, tk_parent=None, on_result=None):
    show_message(title, message, tk_parent=tk_parent, kind="error", on_result=on_result)


def show_navigation_intro(map_screen, *, resume=False):
    """Show the Help window over the active map and HUD.

    A fresh game starts at the first topic. With resume, the window opens at
    the topic viewed last in this session.
    """
    topic_index = _NavigationIntroPopup.last_topic_index if resume else 0
    map_screen.navigation_intro_popup = _NavigationIntroPopup(map_screen, topic_index)
