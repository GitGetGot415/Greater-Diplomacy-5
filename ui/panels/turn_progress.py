from data.state_access import session_for
import pygame
import data.constants as c
from ui.rendering.font_manager import fonts
from ui.bars import ui_bars
from ui.widgets import ui_elements

TURN_PROGRESS_BAR_SIZE = (400, 25)
TURN_PROGRESS_ROW_GAP = 55
TURN_PROGRESS_FIRST_ROW_OFFSET = -140
TURN_PROGRESS_TITLE_OFFSET = -205
TURN_PROGRESS_SKIP_OFFSET = 190


def turn_progress_values(completed, total):
    """Distinguish pending work, no work, and a measured turn-phase workload."""
    if total == -1:
        return 0.0, "Calculating..."
    if total == 0:
        return 1.0, "N/A"
    return completed / float(total), f"{completed}/{total}"


def draw_simple_refresh_bar(surface, status_text, completed, total):
    """Unified data refresh overlay to prevent duplication on base menu screens."""
    ui_bars.draw_fullscreen_overlay(surface, 200)

    center_x, center_y = c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2
    
    font_title = fonts.get("title")
    txt = font_title.render(status_text, True, (255, 255, 255))
    surface.blit(txt, txt.get_rect(center=(center_x, center_y - 40)))

    bar_w, bar_h = 400, 30
    bar_x = center_x - (bar_w // 2)
    
    progress_ratio = (completed / float(total)) if total > 0 else 0.0
    ui_elements.draw_progress_bar(surface, pygame.Rect(bar_x, center_y, bar_w, bar_h), progress_ratio)

    pct_txt = fonts.get("tiny").render(f"{completed} / {total}", True, (255, 255, 255))
    surface.blit(pct_txt, pct_txt.get_rect(center=(center_x, center_y + bar_h // 2)))

def draw_turn_loading_screen(map_screen, surface):
    """Draw processing progress and its available stop controls."""
    session_state = session_for(map_screen)
    ui_bars.draw_fullscreen_overlay(surface, 200)

    center_x = c.SCREEN_WIDTH // 2
    center_y = c.SCREEN_HEIGHT // 2

    font_title = fonts.get("title")
    txt = font_title.render(session_state.loading_status_text, True, (255, 255, 255))
    surface.blit(txt, txt.get_rect(center=(center_x, center_y + TURN_PROGRESS_TITLE_OFFSET)))

    # Configuration for bars
    bar_w, bar_h = TURN_PROGRESS_BAR_SIZE
    bar_x = center_x - (bar_w // 2)
    spacing = TURN_PROGRESS_ROW_GAP

    def draw_bar(y_pos, label, completed, total):
        label_color = c.UI_TEXT_MUTED if total == 0 else c.UI_TEXT_LIGHT
        lbl_txt = fonts.get("normal").render(label, True, label_color)
        surface.blit(lbl_txt, (bar_x, y_pos - 22))

        progress_ratio, display_text = turn_progress_values(completed, total)
        ui_elements.draw_progress_bar(surface, pygame.Rect(bar_x, y_pos, bar_w, bar_h), progress_ratio)

        pct_txt = fonts.get("tiny").render(display_text, True, (255, 255, 255))
        surface.blit(pct_txt, pct_txt.get_rect(center=(center_x, y_pos + bar_h // 2)))

    # --- NEW MULTI TURN LOGIC ---
    multi_total = session_state.multi_turns_total
    if multi_total > 0:
        draw_bar(center_y - 50, "Multi-Turn Skip Progress", session_state.multi_turns_completed, multi_total)

        # --- Draw the Abort Multi-Turn Button ---
        abort_btn_rect = pygame.Rect(center_x - 110, c.SCREEN_HEIGHT - 90, 220, 45)
        already_aborting = session_state.multi_turn_abort_requested
        if already_aborting:
            abort_label = "STOPPING..."
        else:
            abort_label = "ABORT MULTI-TURN"

        ui_elements.draw_pixel_button(surface, abort_btn_rect, (150, 40, 40),
                                      hover_color=(200, 60, 60), disabled=already_aborting)

        abort_txt = fonts.get("button").render(abort_label, True, (255, 255, 255))
        surface.blit(abort_txt, abort_txt.get_rect(center=abort_btn_rect.center))

        # Store for the event handler
        map_screen.multi_turn_abort_btn_rect = abort_btn_rect
        return

    # Keep every phase visible and in a fixed position, including phases with no work.
    phases = (
        ("Holding Summits", session_state.summits_completed, session_state.summits_total),
        ("Analyzing Global Strategy", session_state.proactive_tasks_completed, session_state.proactive_tasks_total),
        ("Generating AI Movement Orders", session_state.movement_tasks_completed, session_state.movement_tasks_total),
        ("Drafting Proactive Diplomatics", session_state.proactive_llm_tasks_completed, session_state.proactive_llm_tasks_total),
        ("Processing Global Responses", session_state.responsive_tasks_completed, session_state.responsive_tasks_total),
        ("Re-Rendering World Maps", session_state.refresh_tasks_completed, session_state.refresh_tasks_total),
    )
    top = center_y + TURN_PROGRESS_FIRST_ROW_OFFSET
    for index, (label, completed, total) in enumerate(phases):
        draw_bar(top + spacing * index, f"{index + 1}. {label}", completed, total)

    # --- Draw the Force Skip Button ---
    # Only show it if there are LLM tasks that might get stuck.
    #
    # Summits belong in that list. They are the first model work of a turn and
    # run before either of the other two counters has been set, so the one
    # phase where nothing else has started yet was the one phase with no way
    # out of it -- which matters a great deal now that ai_turn_budget_seconds
    # can be 0 and this button is the only thing that ends a turn early.
    if (session_state.proactive_llm_tasks_total > 0
            or session_state.responsive_tasks_total > 0
            or session_state.summits_total > 0):
        skip_btn_rect = pygame.Rect(center_x - 100, center_y + TURN_PROGRESS_SKIP_OFFSET, 200, 40)
        ui_elements.draw_pixel_button(surface, skip_btn_rect, (150, 40, 40), hover_color=(200, 60, 60))
        
        skip_txt = fonts.get("button").render("FORCE SKIP AI", True, (255, 255, 255))
        surface.blit(skip_txt, skip_txt.get_rect(center=skip_btn_rect.center))
        
        # Store for the event handler
        map_screen.force_skip_btn_rect = skip_btn_rect
