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
EDITOR_BG = (23, 35, 61, 245)
EDITOR_BORDER = (125, 175, 240)
EDITOR_WIDTH = 540
EDITOR_HEIGHT = 390
SYMBOL_TILE_SIZE = 62


def _editor_rect():
    return pygame.Rect((c.SCREEN_WIDTH - EDITOR_WIDTH) // 2,
                       (c.SCREEN_HEIGHT - EDITOR_HEIGHT) // 2,
                       EDITOR_WIDTH, EDITOR_HEIGHT)


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
        "color_channel": None,
    }


def _symbol_rects(rect):
    choices = [""] + queries.army_symbol_choices()
    start_x, y = rect.x + 20, rect.y + 118
    return [(symbol, pygame.Rect(start_x + index * (SYMBOL_TILE_SIZE + 8), y,
                                 SYMBOL_TILE_SIZE, SYMBOL_TILE_SIZE))
            for index, symbol in enumerate(choices)]


def _color_bar_rect(rect, channel):
    return pygame.Rect(rect.x + 116, rect.y + 204 + channel * 33, 310, 18)


def _set_color_from_position(state, rect, channel, position):
    bar = _color_bar_rect(rect, channel)
    value = round(255 * max(0, min(1, (position[0] - bar.left) / bar.width)))
    state["symbol_color"][channel] = value


def _edit_rect(card):
    return pygame.Rect(card.right - 47, card.y + 10, 17, 17)


def _close_rect(card):
    return pygame.Rect(card.right - 25, card.y + 10, 17, 17)


def _draw_emblem(surface, symbol, color, center, size):
    if not symbol:
        return
    key = f"{c.ARMY_SYMBOL_KEY_PREFIX}{symbol}"
    native_size = symbol_loader.get_native_size(key, style="classic")
    if not native_size:
        return
    zoom = (size * 2) / max(native_size)
    emblem = symbol_loader.get_symbol(key, zoom, color=tuple(color), style="classic")
    if emblem:
        surface.blit(emblem, emblem.get_rect(center=center))


def _save_editor(map_screen):
    state = _editor_state(map_screen)
    if state is None:
        return False
    army = queries.update_army_presentation(
        map_screen.player_country, state["army_id"], state["name"],
        state["symbol"], state["symbol_color"], map_screen.nation_data,
        map_screen.map_data)
    if army is None:
        map_screen.show_feedback("Army names cannot be blank")
        return False
    map_screen.army_editor_state = None
    map_screen.show_feedback(f"Updated {army['name']}")
    return True


def _handle_editor_event(map_screen, event):
    state = _editor_state(map_screen)
    if state is None:
        return False
    rect = _editor_rect()
    if event.type == pygame.KEYDOWN:
        if event.key == pygame.K_ESCAPE:
            map_screen.army_editor_state = None
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
        return True
    for symbol, symbol_rect in _symbol_rects(rect):
        if symbol_rect.collidepoint(event.pos):
            state["symbol"] = symbol
            return True
    for channel in range(3):
        if _color_bar_rect(rect, channel).inflate(0, 10).collidepoint(event.pos):
            state["color_channel"] = channel
            _set_color_from_position(state, rect, channel, event.pos)
            return True
    save = pygame.Rect(rect.right - 122, rect.bottom - 42, 98, 26)
    cancel = pygame.Rect(rect.right - 230, rect.bottom - 42, 98, 26)
    if save.collidepoint(event.pos):
        _save_editor(map_screen)
    elif cancel.collidepoint(event.pos):
        map_screen.army_editor_state = None
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
        selected = state["symbol"] == symbol
        pygame.draw.rect(surface, (66, 112, 175) if selected else (39, 60, 95),
                         symbol_rect, border_radius=4)
        pygame.draw.rect(surface, (175, 215, 255) if selected else (95, 135, 190),
                         symbol_rect, 2 if selected else 1, border_radius=4)
        if symbol:
            _draw_emblem(surface, symbol, state["symbol_color"],
                         symbol_rect.center, 28)
            caption = text_font.render(symbol, True, (225, 235, 250))
            surface.blit(caption, caption.get_rect(center=(symbol_rect.centerx,
                                                           symbol_rect.bottom - 9)))
        else:
            caption = text_font.render("NONE", True, (225, 235, 250))
            surface.blit(caption, caption.get_rect(center=symbol_rect.center))
    component_names = ("Red", "Green", "Blue")
    component_colors = ((215, 75, 75), (75, 205, 105), (80, 140, 230))
    for channel, (name_text, component_color) in enumerate(zip(component_names, component_colors)):
        y = rect.y + 204 + channel * 33
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
    sample = pygame.Rect(rect.x + 20, rect.y + 314, 94, 44)
    pygame.draw.rect(surface, (12, 19, 34), sample, border_radius=4)
    pygame.draw.rect(surface, (110, 155, 215), sample, 1, border_radius=4)
    _draw_emblem(surface, state["symbol"], state["symbol_color"], sample.center, 32)
    cancel = pygame.Rect(rect.right - 230, rect.bottom - 42, 98, 26)
    save = pygame.Rect(rect.right - 122, rect.bottom - 42, 98, 26)
    for button, text, color in ((cancel, "Cancel", (84, 100, 130)),
                                (save, "Save", (55, 120, 78))):
        pygame.draw.rect(surface, color, button, border_radius=4)
        pygame.draw.rect(surface, (190, 215, 245), button, 1, border_radius=4)
        label = text_font.render(text, True, (245, 245, 250))
        surface.blit(label, label.get_rect(center=button.center))


def _visible(map_screen):
    return (not getattr(map_screen, "selection_mode", False)
            and not getattr(map_screen, "is_editor", False)
            and not getattr(map_screen, "selected_province", None)
            and getattr(map_screen, "player_country", "None") not in ("None", "Spectator")
            and not getattr(map_screen, "tactical_mode", False))


def _armies(map_screen):
    if not _visible(map_screen):
        return []
    return queries.get_armies(map_screen.player_country, map_screen.nation_data,
                              map_screen.map_data)


def _layout(map_screen):
    armies = _armies(map_screen)
    tray = map_top_right_layout.army_tray_rect(map_screen, len(armies))
    content_height = len(armies) * (map_top_right_layout.CARD_HEIGHT + 5)
    min_scroll = min(0, tray.height - map_top_right_layout.TRAY_HEADER_HEIGHT - content_height)
    scroll_y = getattr(map_screen, "army_panel_scroll_y", 0)
    map_screen.army_panel_scroll_y = max(min_scroll, min(0, scroll_y))
    map_screen.army_panel_rect = tray
    map_screen.army_panel_min_scroll = min_scroll
    return tray, armies


def handle_event(map_screen, event):
    """Consume army-card input before it can select a province underneath."""
    if _handle_editor_event(map_screen, event):
        return True
    tray, armies = _layout(map_screen)
    if not armies:
        return False
    if event.type == pygame.MOUSEWHEEL and tray.collidepoint(pygame.mouse.get_pos()):
        map_screen.army_panel_scroll_y = max(
            map_screen.army_panel_min_scroll,
            min(0, map_screen.army_panel_scroll_y + event.y * 28))
        return True
    if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
        return False
    if not tray.collidepoint(event.pos):
        return False
    for index, army in enumerate(armies):
        rect = map_top_right_layout.card_rect(tray, index, map_screen.army_panel_scroll_y)
        if not rect.colliderect(tray) or not rect.collidepoint(event.pos):
            continue
        close_rect = _close_rect(rect)
        if close_rect.collidepoint(event.pos):
            queries.disband_army(map_screen.player_country, army["id"],
                                  map_screen.nation_data, map_screen.map_data)
            map_screen.show_feedback(f"Disbanded {army['name']}")
        elif _edit_rect(rect).collidepoint(event.pos):
            _open_editor(map_screen, army)
        else:
            map_screen.select_army(army["id"], open_orders=True)
        return True
    return True


def draw(map_screen, surface):
    tray, armies = _layout(map_screen)
    if not armies:
        return
    panel = pygame.Surface(tray.size, pygame.SRCALPHA)
    panel.fill(TRAY_BG)
    surface.blit(panel, tray.topleft)
    pygame.draw.rect(surface, (100, 145, 215), tray, 1, border_radius=4)
    title_font, text_font = fonts.get("tiny"), fonts.get("tiny")
    title = title_font.render("ARMIES", True, (185, 215, 255))
    surface.blit(title, (tray.x + 8, tray.y + 5))
    clip = surface.get_clip()
    surface.set_clip(tray)
    selected_ids = set(map_screen.selected_map_unit_ids())
    for index, army in enumerate(armies):
        rect = map_top_right_layout.card_rect(tray, index, map_screen.army_panel_scroll_y)
        if not rect.colliderect(tray):
            continue
        selected = bool(selected_ids) and selected_ids == set(army.get("unit_ids", []))
        pygame.draw.rect(surface, CARD_SELECTED if selected else CARD_BG, rect, border_radius=4)
        pygame.draw.rect(surface, (135, 185, 245), rect, 1, border_radius=4)
        _draw_emblem(surface, army.get("symbol", ""), army.get("symbol_color", c.DEFAULT_ARMY_SYMBOL_COLOR),
                     (rect.x + 21, rect.centery), 25)
        name = text_font.render(army["name"], True, (245, 245, 250))
        count = text_font.render(f"{len(army.get('unit_ids', []))} units", True, (205, 220, 235))
        text_x = rect.x + (39 if army.get("symbol") else 9)
        surface.blit(name, (text_x, rect.y + 6))
        surface.blit(count, (text_x, rect.y + 23))
        edit_rect = _edit_rect(rect)
        pygame.draw.rect(surface, (62, 88, 135), edit_rect, border_radius=3)
        edit = text_font.render("E", True, (230, 240, 255))
        surface.blit(edit, edit.get_rect(center=edit_rect.center))
        close_rect = _close_rect(rect)
        pygame.draw.rect(surface, (130, 45, 45), close_rect, border_radius=3)
        x = text_font.render("X", True, (255, 235, 235))
        surface.blit(x, x.get_rect(center=close_rect.center))
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
    _draw_editor(map_screen, surface)
