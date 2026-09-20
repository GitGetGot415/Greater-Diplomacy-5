"""Top-right persistent army cards for the playable strategic map."""

import pygame

import data.constants as c
from data import queries
from map_logic.rendering import symbol_loader
from map_logic.rendering.font_manager import fonts
from ui import map_top_right_layout


TRAY_BG = (15, 22, 42, 225)
CARD_BG = (38, 67, 112)
CARD_SELECTED = (62, 112, 175)
TRAY_CARD_SATURATION = 0.45
TRAY_CARD_DARKEN = 0.42
TRAY_SELECTED_LIGHTEN = 0.18
TRAY_BORDER_LIGHTEN = 0.35
EDITOR_BG = (23, 35, 61, 245)
EDITOR_BORDER = (125, 175, 240)
EDITOR_WIDTH = 540
EDITOR_MIN_HEIGHT = 390
SYMBOL_TILE_SIZE = 40
SYMBOL_TILE_GAP = 8
SYMBOLS_PER_ROW = 10
SYMBOL_GRID_X = 35
SYMBOL_GRID_Y = 118
SYMBOL_CONTROLS_GAP = 14
ROTATION_BUTTON_X = 180
ROTATION_BUTTON_WIDTH = 56
ROTATION_BUTTON_GAP = 6
FLIP_BUTTON_X = 435
FLIP_BUTTON_WIDTH = 80
CUSTOM_SYMBOL_CHOICE = object()
CUSTOM_DIALOG_WIDTH = 500
CUSTOM_DIALOG_HEIGHT = 440
CUSTOM_CANVAS_PIXEL_SIZE = 14
CUSTOM_CANVAS_SIZE = c.ARMY_CUSTOM_SYMBOL_SIZE * CUSTOM_CANVAS_PIXEL_SIZE
CUSTOM_CANVAS_EMPTY_COLOR = (190, 202, 222)
CUSTOM_CANVAS_GRID_COLOR = (130, 145, 170)
CUSTOM_BRUSHES = (
    ("red", c.ARMY_CUSTOM_SYMBOL_RED, (215, 75, 75)),
    ("black", c.ARMY_CUSTOM_SYMBOL_BLACK, (15, 15, 20)),
    ("erase", c.ARMY_CUSTOM_SYMBOL_EMPTY, (65, 75, 95)),
)


def _blend_color(first, second, second_weight):
    """Return a rounded blend of two RGB colors."""
    return tuple(round(start * (1 - second_weight) + end * second_weight)
                 for start, end in zip(first, second))


def _muted_army_color(color):
    """Keep an army RGB's hue while making it suitable for a dark tray card."""
    red, green, blue = queries.normalize_army_symbol_color(color)
    neutral = round((red + green + blue) / 3)
    muted = _blend_color((red, green, blue), (neutral, neutral, neutral),
                          1 - TRAY_CARD_SATURATION)
    return _blend_color(muted, (0, 0, 0), TRAY_CARD_DARKEN)


def _tray_card_colors(color, selected):
    """Return muted fill and readable border colors for an army tray card."""
    muted = _muted_army_color(color)
    fill = (_blend_color(muted, (255, 255, 255), TRAY_SELECTED_LIGHTEN)
            if selected else muted)
    return fill, _blend_color(muted, (255, 255, 255), TRAY_BORDER_LIGHTEN)


def _editor_rect():
    height = _editor_height()
    return pygame.Rect((c.SCREEN_WIDTH - EDITOR_WIDTH) // 2,
                       (c.SCREEN_HEIGHT - height) // 2,
                       EDITOR_WIDTH, height)


def _editor_state(map_screen):
    state = getattr(map_screen, "army_editor_state", None)
    if not isinstance(state, dict):
        return None
    army = next((item for item in _armies(map_screen)
                 if item.get("id") == state.get("army_id")), None)
    if army is None:
        map_screen.army_editor_state = None
        return None
    return state


def _open_editor(map_screen, army):
    map_screen.army_editor_state = {
        "army_id": army["id"],
        "name": army["name"],
        "symbol": army.get("symbol", ""),
        "symbol_color": queries.normalize_army_symbol_color(
            army.get("symbol_color")),
        "symbol_rotation": queries.normalize_army_symbol_rotation(
            army.get("symbol_rotation")),
        "symbol_flipped": queries.normalize_army_symbol_flipped(
            army.get("symbol_flipped")),
        "custom_symbol": queries.normalize_army_custom_symbol(
            army.get("custom_symbol")),
        "color_channel": None,
    }


def _symbol_rects(rect):
    choices = [""] + queries.army_symbol_choices() + [CUSTOM_SYMBOL_CHOICE]
    rects = []
    for index, symbol in enumerate(choices):
        row, column = divmod(index, SYMBOLS_PER_ROW)
        rects.append((symbol, pygame.Rect(
            rect.x + SYMBOL_GRID_X + column * (SYMBOL_TILE_SIZE + SYMBOL_TILE_GAP),
            rect.y + SYMBOL_GRID_Y + row * (SYMBOL_TILE_SIZE + SYMBOL_TILE_GAP),
            SYMBOL_TILE_SIZE, SYMBOL_TILE_SIZE)))
    return rects


def _symbol_grid_rows():
    """Return the picker rows, including no-emblem and custom choices."""
    choice_count = len(queries.army_symbol_choices()) + 2
    return (choice_count + SYMBOLS_PER_ROW - 1) // SYMBOLS_PER_ROW


def _color_section_y(rect):
    rows = _symbol_grid_rows()
    grid_height = rows * SYMBOL_TILE_SIZE + (rows - 1) * SYMBOL_TILE_GAP
    return rect.y + SYMBOL_GRID_Y + grid_height + SYMBOL_CONTROLS_GAP


def _sample_rect(rect):
    color_bottom = _color_section_y(rect) + 2 * 33 + 18
    return pygame.Rect(rect.x + 20, color_bottom + 16, 94, 44)


def _rotation_button_rects(rect):
    sample = _sample_rect(rect)
    return [(rotation, pygame.Rect(
        rect.x + ROTATION_BUTTON_X + index * (ROTATION_BUTTON_WIDTH + ROTATION_BUTTON_GAP),
        sample.y + 8, ROTATION_BUTTON_WIDTH, 27))
            for index, rotation in enumerate(c.ARMY_SYMBOL_ROTATIONS)]


def _flip_button_rect(rect):
    sample = _sample_rect(rect)
    return pygame.Rect(rect.x + FLIP_BUTTON_X, sample.y + 8,
                       FLIP_BUTTON_WIDTH, 27)


def _editor_height():
    # Keep Save/Cancel beneath the preview when newly installed emblems add
    # rows to the picker, rather than letting controls overlap or leave view.
    rows = _symbol_grid_rows()
    content_bottom = (SYMBOL_GRID_Y + rows * SYMBOL_TILE_SIZE
                      + (rows - 1) * SYMBOL_TILE_GAP
                      + SYMBOL_CONTROLS_GAP + 2 * 33 + 18 + 16 + 44)
    return max(EDITOR_MIN_HEIGHT, content_bottom + 44)


def _color_bar_rect(rect, channel):
    return pygame.Rect(rect.x + 116, _color_section_y(rect) + channel * 33, 310, 18)


def _set_color_from_position(state, rect, channel, position):
    bar = _color_bar_rect(rect, channel)
    value = round(255 * max(0, min(1, (position[0] - bar.left) / bar.width)))
    state["symbol_color"][channel] = value


def _edit_rect(card):
    return pygame.Rect(card.right - 47, card.y + 10, 17, 17)


def _close_rect(card):
    return pygame.Rect(card.right - 25, card.y + 10, 17, 17)


def _move_up_rect(card):
    return pygame.Rect(card.right - 91, card.y + 4, 17, 17)


def _move_down_rect(card):
    return pygame.Rect(card.right - 91, card.y + 23, 17, 17)


def _defense_rect(card):
    """The defense-area control sits between vertical reorder arrows and Edit."""
    return pygame.Rect(card.right - 69, card.y + 10, 17, 17)


def _open_defense_area(map_screen, army):
    """Open an editable map picker without allowing submitted turns to mutate."""
    if not map_screen.can_select_map_units():
        map_screen.show_feedback("Turn submitted or unavailable; unsubmit to edit defense areas.")
        return
    from screens.map_related_screens.defense_area_screen import DefenseAreaScreen
    from ui.screen_runner import _run_pygame_sub_screen
    _run_pygame_sub_screen(map_screen, DefenseAreaScreen(map_screen, army["id"]))


def _blank_custom_symbol():
    return [[c.ARMY_CUSTOM_SYMBOL_EMPTY] * c.ARMY_CUSTOM_SYMBOL_SIZE
            for _row in range(c.ARMY_CUSTOM_SYMBOL_SIZE)]


def _custom_symbol_pixels(custom_symbol):
    normalized = queries.normalize_army_custom_symbol(custom_symbol)
    return ([list(row) for row in normalized]
            if normalized else _blank_custom_symbol())


def _custom_symbol_rows(pixels):
    return queries.normalize_army_custom_symbol(["".join(row) for row in pixels])


def _draw_emblem(surface, symbol, custom_symbol, color, rotation, center, size, flipped=False):
    if custom_symbol:
        emblem = symbol_loader.get_custom_army_symbol(
            custom_symbol, size, tuple(queries.normalize_army_symbol_color(color)))
    elif not symbol:
        return
    else:
        key = f"{c.ARMY_SYMBOL_KEY_PREFIX}{symbol}"
        native_size = symbol_loader.get_native_size(key, style="classic")
        if not native_size:
            return
        zoom = (size * 2) / max(native_size)
        emblem = symbol_loader.get_symbol(key, zoom, color=tuple(color), style="classic")
    if emblem:
        rotation = queries.normalize_army_symbol_rotation(rotation)
        flipped = queries.normalize_army_symbol_flipped(flipped)
        emblem = symbol_loader.orient_army_symbol(emblem, rotation, flipped)
        surface.blit(emblem, emblem.get_rect(center=center))


def _save_editor(map_screen):
    state = _editor_state(map_screen)
    if state is None:
        return False
    army = queries.update_army_presentation(
        map_screen.player_country, state["army_id"], state["name"],
        state["symbol"], state["symbol_color"], state["symbol_rotation"],
        state["symbol_flipped"], state["custom_symbol"],
        map_screen.nation_data,
        map_screen.map_data)
    if army is None:
        map_screen.show_feedback("Army names cannot be blank")
        return False
    map_screen.army_editor_state = None
    map_screen.army_custom_symbol_state = None
    map_screen.show_feedback(f"Updated {army['name']}")
    return True


def _open_custom_symbol_editor(map_screen, editor_state):
    map_screen.army_custom_symbol_state = {
        "army_id": editor_state["army_id"],
        "pixels": _custom_symbol_pixels(editor_state["custom_symbol"]),
        "brush": c.ARMY_CUSTOM_SYMBOL_RED,
    }


def _custom_symbol_editor_state(map_screen):
    state = getattr(map_screen, "army_custom_symbol_state", None)
    editor_state = _editor_state(map_screen)
    if (not isinstance(state, dict) or editor_state is None
            or state.get("army_id") != editor_state["army_id"]):
        map_screen.army_custom_symbol_state = None
        return None
    return state


def _custom_symbol_editor_rect():
    return pygame.Rect((c.SCREEN_WIDTH - CUSTOM_DIALOG_WIDTH) // 2,
                       (c.SCREEN_HEIGHT - CUSTOM_DIALOG_HEIGHT) // 2,
                       CUSTOM_DIALOG_WIDTH, CUSTOM_DIALOG_HEIGHT)


def _custom_canvas_rect(rect):
    return pygame.Rect(rect.x + 20, rect.y + 82, CUSTOM_CANVAS_SIZE, CUSTOM_CANVAS_SIZE)


def _custom_brush_rects(rect):
    return [(name, value, color, pygame.Rect(rect.x + 330, rect.y + 114 + index * 43,
                                               135, 32))
            for index, (name, value, color) in enumerate(CUSTOM_BRUSHES)]


def _set_custom_pixel(custom_state, canvas, position):
    if not canvas.collidepoint(position):
        return False
    column = (position[0] - canvas.x) // CUSTOM_CANVAS_PIXEL_SIZE
    row = (position[1] - canvas.y) // CUSTOM_CANVAS_PIXEL_SIZE
    custom_state["pixels"][row][column] = custom_state["brush"]
    return True


def _handle_custom_symbol_event(map_screen, event):
    custom_state = _custom_symbol_editor_state(map_screen)
    if custom_state is None:
        return False
    rect = _custom_symbol_editor_rect()
    canvas = _custom_canvas_rect(rect)
    if event.type == pygame.KEYDOWN:
        if event.key == pygame.K_ESCAPE:
            map_screen.army_custom_symbol_state = None
        elif event.key == pygame.K_RETURN:
            custom_symbol = _custom_symbol_rows(custom_state["pixels"])
            if custom_symbol is None:
                map_screen.show_feedback("Draw at least one red or black pixel")
            else:
                editor_state = _editor_state(map_screen)
                editor_state["symbol"] = ""
                editor_state["custom_symbol"] = custom_symbol
                map_screen.army_custom_symbol_state = None
        return True
    if event.type == pygame.MOUSEMOTION and event.buttons[0]:
        _set_custom_pixel(custom_state, canvas, event.pos)
        return True
    if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
        return True
    if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
        return False
    if not rect.collidepoint(event.pos):
        return True
    if _set_custom_pixel(custom_state, canvas, event.pos):
        return True
    for _name, value, _color, button in _custom_brush_rects(rect):
        if button.collidepoint(event.pos):
            custom_state["brush"] = value
            return True
    clear = pygame.Rect(rect.x + 330, rect.y + 268, 135, 30)
    if clear.collidepoint(event.pos):
        custom_state["pixels"] = _blank_custom_symbol()
        return True
    cancel = pygame.Rect(rect.right - 224, rect.bottom - 42, 94, 26)
    done = pygame.Rect(rect.right - 120, rect.bottom - 42, 94, 26)
    if cancel.collidepoint(event.pos):
        map_screen.army_custom_symbol_state = None
    elif done.collidepoint(event.pos):
        custom_symbol = _custom_symbol_rows(custom_state["pixels"])
        if custom_symbol is None:
            map_screen.show_feedback("Draw at least one red or black pixel")
        else:
            editor_state = _editor_state(map_screen)
            editor_state["symbol"] = ""
            editor_state["custom_symbol"] = custom_symbol
            map_screen.army_custom_symbol_state = None
    return True


def handle_back_key(map_screen):
    """Close the foremost army editor layer, returning whether one was open."""
    if _custom_symbol_editor_state(map_screen) is not None:
        map_screen.army_custom_symbol_state = None
        return True
    if _editor_state(map_screen) is not None:
        map_screen.army_editor_state = None
        map_screen.army_custom_symbol_state = None
        return True
    return False


def _handle_editor_event(map_screen, event):
    state = _editor_state(map_screen)
    if state is None:
        return False
    rect = _editor_rect()
    if event.type == pygame.KEYDOWN:
        if event.key == pygame.K_ESCAPE:
            handle_back_key(map_screen)
        elif event.key == pygame.K_RETURN:
            _save_editor(map_screen)
        elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
            state["name"] = ""
        elif event.key == pygame.K_BACKSPACE:
            state["name"] = state["name"][:-1]
        elif event.unicode and event.unicode.isprintable() and len(state["name"]) < 80:
            state["name"] += event.unicode
        return True
    if event.type == pygame.MOUSEMOTION and state.get("color_channel") is not None:
        if event.buttons[0]:
            _set_color_from_position(state, rect, state["color_channel"], event.pos)
            return True
        state["color_channel"] = None
        return False
    if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
        state["color_channel"] = None
        # A modal editor owns left-click interaction even when the release is
        # outside its border; otherwise a drag ending over the map can issue
        # an unrelated map action. Middle/right map gestures still pass on.
        return True
    if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
        return False
    if not rect.collidepoint(event.pos):
        return True
    close = pygame.Rect(rect.right - 30, rect.y + 10, 18, 18)
    if close.collidepoint(event.pos):
        map_screen.army_editor_state = None
        map_screen.army_custom_symbol_state = None
        return True
    for symbol, symbol_rect in _symbol_rects(rect):
        if symbol_rect.collidepoint(event.pos):
            if symbol is CUSTOM_SYMBOL_CHOICE:
                _open_custom_symbol_editor(map_screen, state)
                return True
            state["symbol"] = symbol
            state["custom_symbol"] = None
            return True
    for channel in range(3):
        if _color_bar_rect(rect, channel).inflate(0, 10).collidepoint(event.pos):
            state["color_channel"] = channel
            _set_color_from_position(state, rect, channel, event.pos)
            return True
    for rotation, button in _rotation_button_rects(rect):
        if button.collidepoint(event.pos):
            state["symbol_rotation"] = rotation
            return True
    flip = _flip_button_rect(rect)
    if flip.collidepoint(event.pos):
        state["symbol_flipped"] = not state["symbol_flipped"]
        return True
    save = pygame.Rect(rect.right - 122, rect.bottom - 42, 98, 26)
    cancel = pygame.Rect(rect.right - 230, rect.bottom - 42, 98, 26)
    if save.collidepoint(event.pos):
        _save_editor(map_screen)
    elif cancel.collidepoint(event.pos):
        map_screen.army_editor_state = None
        map_screen.army_custom_symbol_state = None
    return True


def _draw_editor(map_screen, surface):
    state = _editor_state(map_screen)
    if state is None:
        return
    rect = _editor_rect()
    shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 105))
    surface.blit(shade, (0, 0))
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    panel.fill(EDITOR_BG)
    surface.blit(panel, rect.topleft)
    pygame.draw.rect(surface, EDITOR_BORDER, rect, 2, border_radius=7)
    title_font, text_font = fonts.get("button"), fonts.get("tiny")
    title = title_font.render("EDIT ARMY", True, (235, 245, 255))
    surface.blit(title, (rect.x + 18, rect.y + 11))
    close = pygame.Rect(rect.right - 30, rect.y + 10, 18, 18)
    pygame.draw.rect(surface, (130, 45, 45), close, border_radius=3)
    x = text_font.render("X", True, (255, 235, 235))
    surface.blit(x, x.get_rect(center=close.center))
    label = text_font.render("Name", True, (205, 220, 240))
    surface.blit(label, (rect.x + 20, rect.y + 66))
    name_box = pygame.Rect(rect.x + 70, rect.y + 57, rect.width - 92, 28)
    pygame.draw.rect(surface, (11, 18, 34), name_box, border_radius=3)
    pygame.draw.rect(surface, (110, 155, 215), name_box, 1, border_radius=3)
    name = text_font.render(state["name"] or " ", True, (245, 245, 250))
    surface.blit(name, (name_box.x + 7, name_box.y + 7))
    symbol_label = text_font.render("Map emblem", True, (205, 220, 240))
    surface.blit(symbol_label, (rect.x + 20, rect.y + 98))
    for symbol, symbol_rect in _symbol_rects(rect):
        is_custom = symbol is CUSTOM_SYMBOL_CHOICE
        selected = bool(state["custom_symbol"]) if is_custom else state["symbol"] == symbol
        pygame.draw.rect(surface, (66, 112, 175) if selected else (39, 60, 95),
                         symbol_rect, border_radius=4)
        pygame.draw.rect(surface, (175, 215, 255) if selected else (95, 135, 190),
                         symbol_rect, 2 if selected else 1, border_radius=4)
        if is_custom:
            caption = text_font.render("Custom", True, (225, 235, 250))
            surface.blit(caption, caption.get_rect(center=symbol_rect.center))
        elif symbol:
            _draw_emblem(surface, symbol, None, state["symbol_color"], state["symbol_rotation"],
                         symbol_rect.center, 26, flipped=state["symbol_flipped"])
    component_names = ("Red", "Green", "Blue")
    component_colors = ((215, 75, 75), (75, 205, 105), (80, 140, 230))
    for channel, (name_text, component_color) in enumerate(zip(component_names, component_colors)):
        y = _color_section_y(rect) + channel * 33
        label = text_font.render(name_text, True, component_color)
        surface.blit(label, (rect.x + 20, y + 2))
        bar = _color_bar_rect(rect, channel)
        pygame.draw.rect(surface, (16, 22, 37), bar, border_radius=3)
        filled = bar.copy()
        filled.width = round(bar.width * state["symbol_color"][channel] / 255)
        if filled.width:
            pygame.draw.rect(surface, component_color, filled, border_radius=3)
        pygame.draw.rect(surface, (140, 175, 220), bar, 1, border_radius=3)
        value = text_font.render(str(state["symbol_color"][channel]), True, (240, 240, 245))
        surface.blit(value, (bar.right + 10, y + 2))
    sample = _sample_rect(rect)
    pygame.draw.rect(surface, (12, 19, 34), sample, border_radius=4)
    pygame.draw.rect(surface, (110, 155, 215), sample, 1, border_radius=4)
    _draw_emblem(surface, state["symbol"], state["custom_symbol"], state["symbol_color"],
                 state["symbol_rotation"], sample.center, 32,
                 flipped=state["symbol_flipped"])
    rotation_label = text_font.render("Rotation", True, (205, 220, 240))
    surface.blit(rotation_label, (sample.right + 12, sample.y + 15))
    for rotation, button in _rotation_button_rects(rect):
        selected = state["symbol_rotation"] == rotation
        pygame.draw.rect(surface, (66, 112, 175) if selected else (39, 60, 95),
                         button, border_radius=4)
        pygame.draw.rect(surface, (175, 215, 255) if selected else (95, 135, 190),
                         button, 2 if selected else 1, border_radius=4)
        label = text_font.render(f"{rotation}", True, (235, 245, 255))
        surface.blit(label, label.get_rect(center=button.center))
    flip = _flip_button_rect(rect)
    pygame.draw.rect(surface, (66, 112, 175) if state["symbol_flipped"] else (39, 60, 95),
                     flip, border_radius=4)
    pygame.draw.rect(surface, (175, 215, 255) if state["symbol_flipped"] else (95, 135, 190),
                     flip, 2 if state["symbol_flipped"] else 1, border_radius=4)
    label = text_font.render("Flip", True, (235, 245, 255))
    surface.blit(label, label.get_rect(center=flip.center))
    cancel = pygame.Rect(rect.right - 230, rect.bottom - 42, 98, 26)
    save = pygame.Rect(rect.right - 122, rect.bottom - 42, 98, 26)
    for button, text, color in ((cancel, "Cancel", (84, 100, 130)),
                                (save, "Save", (55, 120, 78))):
        pygame.draw.rect(surface, color, button, border_radius=4)
        pygame.draw.rect(surface, (190, 215, 245), button, 1, border_radius=4)
        label = text_font.render(text, True, (245, 245, 250))
        surface.blit(label, label.get_rect(center=button.center))


def _draw_custom_symbol_editor(map_screen, surface):
    custom_state = _custom_symbol_editor_state(map_screen)
    if custom_state is None:
        return
    rect = _custom_symbol_editor_rect()
    shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 130))
    surface.blit(shade, (0, 0))
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    panel.fill(EDITOR_BG)
    surface.blit(panel, rect.topleft)
    pygame.draw.rect(surface, EDITOR_BORDER, rect, 2, border_radius=7)
    title_font, text_font = fonts.get("button"), fonts.get("tiny")
    title = title_font.render("DRAW CUSTOM EMBLEM", True, (235, 245, 255))
    surface.blit(title, (rect.x + 18, rect.y + 15))
    instructions = text_font.render("20 x 20 pixels; red, black, or erase", True,
                                    (205, 220, 240))
    surface.blit(instructions, (rect.x + 20, rect.y + 49))
    canvas = _custom_canvas_rect(rect)
    pygame.draw.rect(surface, CUSTOM_CANVAS_EMPTY_COLOR, canvas)
    pixel_colors = {c.ARMY_CUSTOM_SYMBOL_RED: c.DEFAULT_ARMY_SYMBOL_COLOR,
                    c.ARMY_CUSTOM_SYMBOL_BLACK: (0, 0, 0),
                    c.ARMY_CUSTOM_SYMBOL_EMPTY: CUSTOM_CANVAS_EMPTY_COLOR}
    for row, pixels in enumerate(custom_state["pixels"]):
        for column, pixel in enumerate(pixels):
            pixel_rect = pygame.Rect(canvas.x + column * CUSTOM_CANVAS_PIXEL_SIZE,
                                     canvas.y + row * CUSTOM_CANVAS_PIXEL_SIZE,
                                     CUSTOM_CANVAS_PIXEL_SIZE, CUSTOM_CANVAS_PIXEL_SIZE)
            pygame.draw.rect(surface, pixel_colors[pixel], pixel_rect)
            pygame.draw.rect(surface, CUSTOM_CANVAS_GRID_COLOR, pixel_rect, 1)
    pygame.draw.rect(surface, (150, 190, 245), canvas, 2)
    brush_label = text_font.render("Brush", True, (205, 220, 240))
    surface.blit(brush_label, (rect.x + 330, rect.y + 82))
    for name, value, color, button in _custom_brush_rects(rect):
        selected = custom_state["brush"] == value
        pygame.draw.rect(surface, color, button, border_radius=4)
        pygame.draw.rect(surface, (215, 235, 255) if selected else (100, 135, 180),
                         button, 2 if selected else 1, border_radius=4)
        label = text_font.render(name.title(), True,
                                 (245, 245, 250) if value != c.ARMY_CUSTOM_SYMBOL_BLACK
                                 else (230, 230, 235))
        surface.blit(label, label.get_rect(center=button.center))
    clear = pygame.Rect(rect.x + 330, rect.y + 268, 135, 30)
    pygame.draw.rect(surface, (72, 84, 110), clear, border_radius=4)
    pygame.draw.rect(surface, (160, 190, 230), clear, 1, border_radius=4)
    clear_label = text_font.render("Clear", True, (245, 245, 250))
    surface.blit(clear_label, clear_label.get_rect(center=clear.center))
    cancel = pygame.Rect(rect.right - 224, rect.bottom - 42, 94, 26)
    done = pygame.Rect(rect.right - 120, rect.bottom - 42, 94, 26)
    for button, text, color in ((cancel, "Cancel", (84, 100, 130)),
                                (done, "Done", (55, 120, 78))):
        pygame.draw.rect(surface, color, button, border_radius=4)
        pygame.draw.rect(surface, (190, 215, 245), button, 1, border_radius=4)
        label = text_font.render(text, True, (245, 245, 250))
        surface.blit(label, label.get_rect(center=button.center))


def _visible(map_screen, orders_screen=None):
    """Return whether the army tray may occupy the current map workspace."""
    if orders_screen is not None and getattr(orders_screen, "battle_screen", None) is not None:
        return False
    return (not getattr(map_screen, "selection_mode", False)
            and not getattr(map_screen, "is_editor", False)
            and (getattr(map_screen, "army_panel_visible_in_orders", False)
                 or not getattr(map_screen, "selected_province", None))
            and getattr(map_screen, "player_country", "None") not in ("None", "Spectator")
            and not getattr(map_screen, "tactical_mode", False))


def _armies(map_screen, orders_screen=None):
    if not _visible(map_screen, orders_screen):
        return []
    return queries.get_armies(map_screen.player_country, map_screen.nation_data,
                              map_screen.map_data)


def _layout(map_screen, show_create=False, orders_screen=None):
    armies = _armies(map_screen, orders_screen)
    row_count = len(armies) + int(show_create)
    tray = map_top_right_layout.army_tray_rect(map_screen, row_count)
    content_height = row_count * (map_top_right_layout.CARD_HEIGHT + 5)
    min_scroll = min(0, tray.height - map_top_right_layout.TRAY_HEADER_HEIGHT - content_height)
    scroll_y = getattr(map_screen, "army_panel_scroll_y", 0)
    map_screen.army_panel_scroll_y = max(min_scroll, min(0, scroll_y))
    map_screen.army_panel_rect = tray
    map_screen.army_panel_min_scroll = min_scroll
    return tray, armies


def _create_rect(tray, armies, scroll_y):
    return map_top_right_layout.card_rect(tray, len(armies), scroll_y)


def _orders_can_manage_armies(map_screen, orders_screen):
    return (orders_screen is not None and not getattr(orders_screen, "read_only", False)
            and map_screen.can_select_map_units())


def _orders_can_use_selection(map_screen, orders_screen):
    return (_orders_can_manage_armies(map_screen, orders_screen)
            and bool(map_screen.selected_map_unit_ids()))


def handle_event(map_screen, event, orders_screen=None):
    """Consume army-card input before it can select a province underneath."""
    if _handle_custom_symbol_event(map_screen, event):
        return True
    if _handle_editor_event(map_screen, event):
        return True
    # Orders uses right-button release to issue movement.  A press on an army
    # card is instead an assignment action, so retain it through its matching
    # release even when the pointer is now over the map behind the tray.
    if (event.type == pygame.MOUSEBUTTONUP and event.button == 3
            and getattr(map_screen, "_army_tray_right_click_active", False)):
        map_screen._army_tray_right_click_active = False
        return True
    if orders_screen is not None and getattr(orders_screen, "battle_screen", None) is not None:
        return False
    show_create = orders_screen is not None
    tray, armies = _layout(map_screen, show_create=show_create, orders_screen=orders_screen)
    if not armies and not show_create:
        return False
    if event.type == pygame.MOUSEWHEEL and tray.collidepoint(pygame.mouse.get_pos()):
        map_screen.army_panel_scroll_y = max(
            map_screen.army_panel_min_scroll,
            min(0, map_screen.army_panel_scroll_y + event.y * 28))
        return True
    if event.type != pygame.MOUSEBUTTONDOWN:
        return False
    if event.button == 3:
        if orders_screen is None or not tray.collidepoint(event.pos):
            return False
        map_screen._army_tray_right_click_active = True
        for index, army in enumerate(armies):
            rect = map_top_right_layout.card_rect(tray, index, map_screen.army_panel_scroll_y)
            if rect.colliderect(tray) and rect.collidepoint(event.pos):
                if _orders_can_use_selection(map_screen, orders_screen):
                    map_screen.assign_selection_to_army(army["id"])
                    orders_screen.refresh_ui()
                return True
        return True
    if event.button != 1:
        return False
    if not tray.collidepoint(event.pos):
        return False
    if show_create:
        create_rect = _create_rect(tray, armies, map_screen.army_panel_scroll_y)
        if create_rect.colliderect(tray) and create_rect.collidepoint(event.pos):
            if _orders_can_use_selection(map_screen, orders_screen):
                map_screen.create_army_from_selection()
                orders_screen.refresh_ui()
            return True
    for index, army in enumerate(armies):
        rect = map_top_right_layout.card_rect(tray, index, map_screen.army_panel_scroll_y)
        if not rect.colliderect(tray) or not rect.collidepoint(event.pos):
            continue
        close_rect = _close_rect(rect)
        if close_rect.collidepoint(event.pos):
            queries.disband_army(map_screen.player_country, army["id"],
                                  map_screen.nation_data, map_screen.map_data)
            map_screen.show_feedback(f"Disbanded {army['name']}")
        elif _move_up_rect(rect).collidepoint(event.pos):
            if queries.move_army(map_screen.player_country, army["id"], -1,
                                  map_screen.nation_data, map_screen.map_data):
                map_screen.show_feedback(f"Moved {army['name']} up")
        elif _move_down_rect(rect).collidepoint(event.pos):
            if queries.move_army(map_screen.player_country, army["id"], 1,
                                  map_screen.nation_data, map_screen.map_data):
                map_screen.show_feedback(f"Moved {army['name']} down")
        elif _defense_rect(rect).collidepoint(event.pos):
            _open_defense_area(map_screen, army)
        elif _edit_rect(rect).collidepoint(event.pos):
            _open_editor(map_screen, army)
        else:
            map_screen.select_army(army["id"], open_orders=orders_screen is None)
            if orders_screen is not None:
                orders_screen.refresh_ui()
        return True
    return True


def draw(map_screen, surface, orders_screen=None, draw_editors=True):
    if orders_screen is not None and getattr(orders_screen, "battle_screen", None) is not None:
        return
    show_create = orders_screen is not None
    tray, armies = _layout(map_screen, show_create=show_create, orders_screen=orders_screen)
    if not armies and not show_create:
        return
    panel = pygame.Surface(tray.size, pygame.SRCALPHA)
    panel.fill(TRAY_BG)
    surface.blit(panel, tray.topleft)
    pygame.draw.rect(surface, (100, 145, 215), tray, 1, border_radius=4)
    title_font, text_font = fonts.get("tiny"), fonts.get("tiny")
    title = title_font.render("ARMIES", True, (185, 215, 255))
    surface.blit(title, (tray.x + 8, tray.y + 5))
    if show_create:
        hint = text_font.render("Right-click: assign", True, (165, 195, 235))
        surface.blit(hint, (tray.x + 69, tray.y + 6))
    clip = surface.get_clip()
    surface.set_clip(tray)
    selected_ids = set(map_screen.selected_map_unit_ids())
    for index, army in enumerate(armies):
        rect = map_top_right_layout.card_rect(tray, index, map_screen.army_panel_scroll_y)
        if not rect.colliderect(tray):
            continue
        selected = bool(selected_ids) and selected_ids == set(army.get("unit_ids", []))
        card_color, border_color = _tray_card_colors(
            army.get("symbol_color", c.DEFAULT_ARMY_SYMBOL_COLOR), selected)
        pygame.draw.rect(surface, card_color, rect, border_radius=4)
        pygame.draw.rect(surface, border_color, rect, 1, border_radius=4)
        _draw_emblem(surface, army.get("symbol", ""), army.get("custom_symbol"),
                     army.get("symbol_color", c.DEFAULT_ARMY_SYMBOL_COLOR),
                     army.get("symbol_rotation", c.DEFAULT_ARMY_SYMBOL_ROTATION),
                     (rect.x + 21, rect.centery), 25,
                     flipped=army.get("symbol_flipped"))
        name = text_font.render(army["name"], True, (245, 245, 250))
        count = text_font.render(f"{len(army.get('unit_ids', []))} units", True, (205, 220, 235))
        text_x = rect.x + (39 if army.get("symbol") or army.get("custom_symbol") else 9)
        surface.blit(name, (text_x, rect.y + 6))
        surface.blit(count, (text_x, rect.y + 23))
        for arrow_rect, label, enabled in (
                (_move_up_rect(rect), "^", index > 0),
                (_move_down_rect(rect), "v", index < len(armies) - 1)):
            pygame.draw.rect(surface, (62, 88, 135) if enabled else (45, 52, 67),
                             arrow_rect, border_radius=3)
            arrow = text_font.render(label, True, (230, 240, 255) if enabled else (120, 130, 145))
            surface.blit(arrow, arrow.get_rect(center=arrow_rect.center))
        defense_rect = _defense_rect(rect)
        has_defense_area = bool(army.get("defense_area"))
        pygame.draw.rect(surface, (50, 108, 83) if has_defense_area else (62, 88, 135),
                         defense_rect, border_radius=3)
        defense = text_font.render("D", True, (235, 255, 240))
        surface.blit(defense, defense.get_rect(center=defense_rect.center))
        edit_rect = _edit_rect(rect)
        pygame.draw.rect(surface, (62, 88, 135), edit_rect, border_radius=3)
        edit = text_font.render("E", True, (230, 240, 255))
        surface.blit(edit, edit.get_rect(center=edit_rect.center))
        close_rect = _close_rect(rect)
        pygame.draw.rect(surface, (130, 45, 45), close_rect, border_radius=3)
        x = text_font.render("X", True, (255, 235, 235))
        surface.blit(x, x.get_rect(center=close_rect.center))
    if show_create:
        create_rect = _create_rect(tray, armies, map_screen.army_panel_scroll_y)
        if create_rect.colliderect(tray):
            enabled = _orders_can_use_selection(map_screen, orders_screen)
            pygame.draw.rect(surface, (42, 98, 73) if enabled else (45, 52, 67),
                             create_rect, border_radius=4)
            pygame.draw.rect(surface, (140, 205, 165) if enabled else (95, 115, 130),
                             create_rect, 1, border_radius=4)
            label = text_font.render("+ Create Army", True,
                                     (235, 250, 240) if enabled else (135, 145, 155))
            surface.blit(label, label.get_rect(center=create_rect.center))
    surface.set_clip(clip)
    if map_screen.army_panel_min_scroll < 0:
        track = pygame.Rect(tray.right - 5, tray.y + 4, 3, tray.height - 8)
        handle_h = max(18, int(track.height * tray.height /
                               (tray.height - map_screen.army_panel_min_scroll)))
        travel = track.height - handle_h
        ratio = map_screen.army_panel_scroll_y / map_screen.army_panel_min_scroll
        pygame.draw.rect(surface, (145, 175, 215),
                         (track.x, track.y + int(travel * ratio), track.width, handle_h),
                         border_radius=2)
    if draw_editors:
        draw_editors_over_map(map_screen, surface)


def draw_editors_over_map(map_screen, surface):
    """Draw army editing modals above any owning screen's normal controls."""
    _draw_editor(map_screen, surface)
    _draw_custom_symbol_editor(map_screen, surface)
