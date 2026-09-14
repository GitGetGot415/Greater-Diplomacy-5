"""Top-right persistent army cards for the playable strategic map."""

import pygame

import data.constants as c
from data import queries
from map_logic.rendering.font_manager import fonts
from ui import map_top_right_layout


TRAY_BG = (15, 22, 42, 225)
CARD_BG = (38, 67, 112)
CARD_SELECTED = (62, 112, 175)


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
        close_rect = pygame.Rect(rect.right - 25, rect.y + 10, 17, 17)
        if close_rect.collidepoint(event.pos):
            queries.disband_army(map_screen.player_country, army["id"],
                                  map_screen.nation_data, map_screen.map_data)
            map_screen.show_feedback(f"Disbanded {army['name']}")
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
        name = text_font.render(army["name"], True, (245, 245, 250))
        count = text_font.render(f"{len(army.get('unit_ids', []))} units", True, (205, 220, 235))
        surface.blit(name, (rect.x + 9, rect.y + 6))
        surface.blit(count, (rect.x + 9, rect.y + 23))
        close_rect = pygame.Rect(rect.right - 25, rect.y + 10, 17, 17)
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
