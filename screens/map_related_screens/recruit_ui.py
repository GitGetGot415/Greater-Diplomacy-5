import pygame
import data.constants as c
from data import queries
from map_logic.rendering.font_manager import fonts

# ==========================================
# LAYOUT
# ==========================================

# --- Read-only queue box drawn on the map, under the Production button ---
MAP_QUEUE_OVERLAY_WIDTH = 400
MAP_QUEUE_OVERLAY_X = 400
MAP_QUEUE_OVERLAY_Y = 80
MAP_QUEUE_MIN_HEIGHT = 80
MAP_QUEUE_MAX_HEIGHT = 400

# --- Interactive queue panel on the Production screen ---
PANEL_WIDTH = 460
PANEL_MARGIN_X = 20
PANEL_TOP = 100
PANEL_BOTTOM_MARGIN = 200
PANEL_COLUMN_SPLIT = 230

# --- Shared row metrics for both panels ---
ROW_STEP_Y = 35
ROW_NAME_MAX_CHARS = 13
CANCEL_BOX_SIZE = 25

PANEL_BG_COLOR = (30, 30, 50)
PANEL_BORDER_COLOR = (100, 100, 250)
QUEUE_TEXT_COLOR = (255, 200, 50)
MUTED_TEXT_COLOR = (150, 150, 150)
CANCEL_BOX_COLOR = (150, 0, 0)

# Long-winded item names shortened so they fit a queue column.
NAME_ABBREVIATIONS = {"Chadian ": "", "Synthetic ": "Syn. "}


def get_queue_entry_text(item):
    """Renders one queue row as "<short name> (Nt)".

    Both queue panels (the interactive one on the Production screen and the
    read-only one on the map) show the exact same string, so the abbreviating,
    truncating and turn lookup all happen here once.
    """
    raw_name = item.get("unit_type", item.get("item_name", "Unknown Order"))
    for old, new in NAME_ABBREVIATIONS.items():
        raw_name = raw_name.replace(old, new)

    if len(raw_name) > ROW_NAME_MAX_CHARS:
        raw_name = raw_name[:ROW_NAME_MAX_CHARS - 2] + ".."

    turns = item.get("turns_remaining",
                     max(1, item.get("days_remaining", c.DEFAULT_DAYS_PER_TURN) // c.DEFAULT_DAYS_PER_TURN))
    return f"{raw_name} ({turns}t)"


def draw_cancel_box(surface, font, x, y):
    """Draws the red "X" cancel square and returns its rect for hit-testing."""
    rect = pygame.Rect(x, y, CANCEL_BOX_SIZE, CANCEL_BOX_SIZE)
    pygame.draw.rect(surface, CANCEL_BOX_COLOR, rect)
    label = font.render("X", True, (255, 255, 255))
    surface.blit(label, label.get_rect(center=rect.center))
    return rect


def draw_recruitment_overlay(surface, target_province):
    """Draws the separated building and unit queues."""
    cancel_buttons = []

    panel_rect = pygame.Rect(c.SCREEN_WIDTH - PANEL_WIDTH - PANEL_MARGIN_X, PANEL_TOP,
                             PANEL_WIDTH, c.SCREEN_HEIGHT - PANEL_BOTTOM_MARGIN)
    pygame.draw.rect(surface, PANEL_BG_COLOR, panel_rect)
    pygame.draw.rect(surface, PANEL_BORDER_COLOR, panel_rect, 2)
    split_x = panel_rect.x + PANEL_COLUMN_SPLIT
    pygame.draw.line(surface, PANEL_BORDER_COLOR, (split_x, panel_rect.y), (split_x, panel_rect.bottom), 2)

    font = fonts.get("heading1")
    small_font = fonts.get("button")

    surface.blit(font.render("Buildings", True, (255, 255, 255)), (panel_rect.x + 20, panel_rect.y + 20))
    surface.blit(font.render("Units", True, (255, 255, 255)), (panel_rect.x + 250, panel_rect.y + 20))

    def render_half(queue_list, q_type, start_x):
        for i, item in enumerate(queue_list):
            y_pos = panel_rect.y + 70 + (i * ROW_STEP_Y)
            surface.blit(small_font.render(get_queue_entry_text(item), True, QUEUE_TEXT_COLOR), (start_x, y_pos))
            cancel_buttons.append((draw_cancel_box(surface, small_font, start_x + 185, y_pos), i, q_type))

    render_half(target_province.get("building_queue", []), "building", panel_rect.x + 10)
    render_half(target_province.get("unit_queue", []), "unit", panel_rect.x + 240)

    return cancel_buttons


def draw_map_queue_overlay(surface, target_province, map_screen=None):
    """Draws a read-only split queue under the construction button on the map screen."""
    b_queue = target_province.get("building_queue", [])
    u_queue = target_province.get("unit_queue", [])

    # --- FOG OF WAR VISIBILITY CHECK ---
    is_visible = queries.is_province_visible(map_screen, target_province["id"])

    # Fixed height while fogged (just the hidden text); otherwise sized to the
    # longer of the two queues, clamped so it never collapses or runs off-screen.
    if is_visible:
        rows = max(len(b_queue), len(u_queue))
        panel_height = max(MAP_QUEUE_MIN_HEIGHT, min(MAP_QUEUE_MAX_HEIGHT, rows * ROW_STEP_Y + 40))
    else:
        panel_height = MAP_QUEUE_MIN_HEIGHT

    panel_rect = pygame.Rect(MAP_QUEUE_OVERLAY_X, MAP_QUEUE_OVERLAY_Y, MAP_QUEUE_OVERLAY_WIDTH, panel_height)

    panel_surf = pygame.Surface((panel_rect.width, panel_rect.height), pygame.SRCALPHA)
    panel_surf.fill((*PANEL_BG_COLOR, 200))
    surface.blit(panel_surf, panel_rect.topleft)
    pygame.draw.rect(surface, PANEL_BORDER_COLOR, panel_rect, 2)
    pygame.draw.line(surface, PANEL_BORDER_COLOR, (panel_rect.centerx, panel_rect.y), (panel_rect.centerx, panel_rect.bottom), 2)

    font = fonts.get("normal")
    small_font = fonts.get("tiny")

    columns = ((b_queue, panel_rect.x + 10), (u_queue, panel_rect.centerx + 10))

    surface.blit(font.render("Buildings", True, (255, 255, 255)), (columns[0][1], panel_rect.y + 10))
    surface.blit(font.render("Units", True, (255, 255, 255)), (columns[1][1], panel_rect.y + 10))

    # If the province is hidden by fog, draw the hidden text under both columns and stop
    if not is_visible:
        hidden_txt = font.render("(Hidden by Fog of War)", True, MUTED_TEXT_COLOR)
        for _queue, start_x in columns:
            surface.blit(hidden_txt, (start_x, panel_rect.y + 40))
        return

    for queue_list, start_x in columns:
        if not queue_list:
            surface.blit(font.render("(Queue Empty)", True, MUTED_TEXT_COLOR), (start_x, panel_rect.y + 40))
            continue

        for i, item in enumerate(queue_list):
            y_pos = panel_rect.y + 35 + (i * ROW_STEP_Y)
            if y_pos + 30 > panel_rect.bottom:
                more_txt = small_font.render(f"+{len(queue_list) - i} more...", True, MUTED_TEXT_COLOR)
                surface.blit(more_txt, (start_x, y_pos))
                break

            surface.blit(small_font.render(get_queue_entry_text(item), True, QUEUE_TEXT_COLOR), (start_x, y_pos))
