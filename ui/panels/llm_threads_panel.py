"""Model worker threads on the turn loading screen.

SHOW THREADS opens a fixed-size panel beside the progress bars. It has one row
per worker thread of the current model batch (map_logic/ai/ai_activity.py):
the job, its state, and how long it has run. Below the rows is the selected
thread's model output, which follows the end of the text as it arrives.
"""

import time

import pygame

import data.constants as c
from map_logic.ai import ai_activity
from ui.rendering.font_manager import fonts
from ui.widgets import ui_elements
from ui.widgets.text_utils import fit_text, wrap_text

TOGGLE_RECT = pygame.Rect(c.SCREEN_WIDTH // 2 - 100, c.SCREEN_HEIGHT // 2 + 240, 200, 40)
# Right of the progress bars and below the status title, which can run wide.
PANEL_RECT = pygame.Rect(866, 186, 400, 466)
PADDING = 8
HEADER_HEIGHT = 44
ROW_HEIGHT = 40
ROW_GAP = 4
VISIBLE_ROWS = 4
SCROLLBAR_WIDTH = 8
OUTPUT_TITLE_HEIGHT = 20
TEXT_INSET = 4
# Only the end of a long reply can be visible, so only the end is wrapped.
OUTPUT_TAIL_CHARS = 2000
OUTPUT_REFRESH_SECONDS = 0.1

PANEL_COLOR = (15, 22, 42, 225)
PANEL_BORDER = (100, 145, 215)
ROW_COLOR = (25, 35, 60)
OUTPUT_COLOR = (10, 14, 28)
ROW_BORDER = (20, 20, 20)
TOGGLE_COLOR = (40, 70, 130)
TOGGLE_HOVER = (60, 95, 165)
TITLE_COLOR = (185, 215, 255)
TEXT_COLOR = (230, 230, 230)
STATE_COLORS = {
    ai_activity.WAITING: (242, 195, 105),
    ai_activity.WRITING: (120, 220, 120),
    ai_activity.DONE: c.UI_TEXT_LIGHT,
    ai_activity.FAILED: (235, 90, 90),
    ai_activity.STOPPED: c.UI_TEXT_MUTED,
}

_ROWS_TOP = PANEL_RECT.y + HEADER_HEIGHT
_ROWS_BOTTOM = _ROWS_TOP + VISIBLE_ROWS * (ROW_HEIGHT + ROW_GAP)
_INNER_X = PANEL_RECT.x + PADDING
_INNER_WIDTH = PANEL_RECT.width - 2 * PADDING
_OUTPUT_RECT = pygame.Rect(_INNER_X, _ROWS_BOTTOM + OUTPUT_TITLE_HEIGHT, _INNER_WIDTH,
                           PANEL_RECT.bottom - PADDING - _ROWS_BOTTOM - OUTPUT_TITLE_HEIGHT)

# The selected request's wrapped output, rebuilt when its text changes.
_output_cache = {"key": None, "built": 0.0, "lines": []}


def _row_rect(index):
    return pygame.Rect(_INNER_X, _ROWS_TOP + index * (ROW_HEIGHT + ROW_GAP),
                       _INNER_WIDTH - SCROLLBAR_WIDTH - ROW_GAP, ROW_HEIGHT)


def _rows():
    batch = ai_activity.current_batch()
    return batch, (batch.rows() if batch is not None else [])


def _max_scroll(rows):
    return max(0, len(rows) - VISIBLE_ROWS)


def _selected_slot(map_screen, rows):
    """The chosen thread, or else the first running one, or else the first used one."""
    slots = {slot for slot, request in rows if request is not None}
    if map_screen.llm_threads_selected in slots:
        return map_screen.llm_threads_selected
    running = [slot for slot, request in rows if request is not None and request.finished is None]
    return min(running or slots, default=None)


def handle_event(map_screen, event):
    """Toggle, select, and scroll. True when the event belonged to the panel."""
    if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
            and TOGGLE_RECT.collidepoint(event.pos)):
        map_screen.llm_threads_open = not map_screen.llm_threads_open
        return True
    if not map_screen.llm_threads_open:
        return False
    if event.type == pygame.MOUSEWHEEL and PANEL_RECT.collidepoint(pygame.mouse.get_pos()):
        _batch, rows = _rows()
        map_screen.llm_threads_scroll = max(0, min(_max_scroll(rows),
                                                   map_screen.llm_threads_scroll - event.y))
        return True
    if event.type == pygame.MOUSEBUTTONDOWN and PANEL_RECT.collidepoint(event.pos):
        _batch, rows = _rows()
        for index in range(VISIBLE_ROWS):
            position = map_screen.llm_threads_scroll + index
            if position < len(rows) and _row_rect(index).collidepoint(event.pos):
                map_screen.llm_threads_selected = rows[position][0]
        return True
    return False


def draw(map_screen, surface):
    is_open = map_screen.llm_threads_open
    ui_elements.draw_pixel_button(surface, TOGGLE_RECT, TOGGLE_COLOR,
                                  hover_color=TOGGLE_HOVER, selected=is_open)
    label = fonts.get("button").render("HIDE THREADS" if is_open else "SHOW THREADS",
                                       True, (255, 255, 255))
    surface.blit(label, label.get_rect(center=TOGGLE_RECT.center))
    if is_open:
        _draw_panel(map_screen, surface)


def _clock(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def _draw_panel(map_screen, surface):
    batch, rows = _rows()
    small, tiny = fonts.get("small"), fonts.get("tiny")
    ui_elements.draw_pixel_panel(surface, PANEL_RECT, PANEL_COLOR, PANEL_BORDER)

    surface.blit(small.render("MODEL THREADS", True, TITLE_COLOR),
                 (_INNER_X, PANEL_RECT.y + PADDING))
    if batch is None:
        summary = "No model requests yet this turn."
    else:
        running, waiting, finished, skipped = batch.counts()
        summary = f"{batch.phase}: {running} running, {waiting} waiting, {finished} finished"
        if skipped:
            summary += f", {skipped} skipped"
    surface.blit(tiny.render(fit_text(summary, tiny, _INNER_WIDTH), True, c.UI_TEXT_LIGHT),
                 (_INNER_X, PANEL_RECT.y + PADDING + small.get_linesize()))

    max_scroll = _max_scroll(rows)
    map_screen.llm_threads_scroll = max(0, min(max_scroll, map_screen.llm_threads_scroll))
    scroll = map_screen.llm_threads_scroll
    selected = _selected_slot(map_screen, rows)
    now = time.monotonic()
    selected_request = None
    for slot, request in rows:
        if slot == selected:
            selected_request = request

    for index in range(VISIBLE_ROWS):
        position = scroll + index
        if position >= len(rows):
            break
        slot, request = rows[position]
        rect = _row_rect(index)
        border = c.COLOR_GOLD_HIGHLIGHT if slot == selected else ROW_BORDER
        ui_elements.draw_pixel_panel(surface, rect, ROW_COLOR, border, recessed=True)
        text_x = rect.x + TEXT_INSET + 2
        if request is None:
            surface.blit(tiny.render(f"Thread {slot}: Idle", True, c.UI_TEXT_MUTED),
                         (text_x, rect.y + TEXT_INSET))
            continue
        timer = tiny.render(_clock(request.elapsed(now)), True, TEXT_COLOR)
        timer_rect = timer.get_rect(topright=(rect.right - TEXT_INSET - 2, rect.y + TEXT_INSET))
        surface.blit(timer, timer_rect)
        name = fit_text(f"Thread {slot}: {request.label}", tiny,
                        timer_rect.left - text_x - TEXT_INSET)
        surface.blit(tiny.render(name, True, TEXT_COLOR), (text_x, rect.y + TEXT_INSET))
        surface.blit(tiny.render(request.state, True, STATE_COLORS[request.state]),
                     (text_x, rect.y + TEXT_INSET + tiny.get_linesize()))

    if max_scroll:
        track = pygame.Rect(PANEL_RECT.right - PADDING - SCROLLBAR_WIDTH, _ROWS_TOP,
                            SCROLLBAR_WIDTH, _ROWS_BOTTOM - _ROWS_TOP - ROW_GAP)
        handle_h = max(20, track.height * VISIBLE_ROWS // len(rows))
        handle_y = track.y + (track.height - handle_h) * scroll // max_scroll
        ui_elements.draw_slider(surface, track,
                                pygame.Rect(track.x, handle_y, SCROLLBAR_WIDTH, handle_h))

    title = "Output" if selected is None else f"Output: Thread {selected}"
    surface.blit(tiny.render(title, True, TITLE_COLOR), (_INNER_X, _ROWS_BOTTOM + 2))
    ui_elements.draw_pixel_panel(surface, _OUTPUT_RECT, OUTPUT_COLOR, ROW_BORDER, recessed=True)
    y = _OUTPUT_RECT.y + TEXT_INSET
    for line in _output_lines(selected_request, tiny, now):
        surface.blit(line, (_OUTPUT_RECT.x + TEXT_INSET, y))
        y += tiny.get_linesize()


def _output_lines(request, font, now):
    """Rendered lines from the end of the request's output that fit the box.

    Rebuilt when the text changes, at most every OUTPUT_REFRESH_SECONDS while a
    reply streams in, so a fast model does not re-wrap the text every frame.
    """
    if request is None:
        return []
    key = (id(request), request.revision)
    cache = _output_cache
    if cache["key"] == key:
        return cache["lines"]
    same_request = cache["key"] is not None and cache["key"][0] == key[0]
    if same_request and request.finished is None and now - cache["built"] < OUTPUT_REFRESH_SECONDS:
        return cache["lines"]
    width = _OUTPUT_RECT.width - 2 * TEXT_INSET
    fit = max(1, (_OUTPUT_RECT.height - 2 * TEXT_INSET) // font.get_linesize())
    text = request.output()[-OUTPUT_TAIL_CHARS:]
    lines = wrap_text(text, font, width)[-fit:] if text else []
    cache.update(key=key, built=now,
                 lines=[font.render(line, True, TEXT_COLOR) for line in lines])
    return cache["lines"]
