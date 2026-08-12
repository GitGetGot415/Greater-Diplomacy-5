import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts
from ui.bars import ui_bars

def draw_simple_refresh_bar(surface, status_text, completed, total):
    """Unified data refresh overlay to prevent duplication on base menu screens."""
    ui_bars.draw_fullscreen_overlay(surface, 200)

    center_x, center_y = c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2
    
    font_title = fonts.get("title")
    txt = font_title.render(status_text, True, (255, 255, 255))
    surface.blit(txt, txt.get_rect(center=(center_x, center_y - 40)))

    bar_w, bar_h = 400, 30
    bar_x = center_x - (bar_w // 2)
    
    pygame.draw.rect(surface, (40, 40, 60), (bar_x, center_y, bar_w, bar_h), border_radius=5)
    
    progress_ratio = (completed / float(total)) if total > 0 else 0.0
    fill_w = int(bar_w * progress_ratio)
    if fill_w > 0:
        pygame.draw.rect(surface, (100, 200, 100), (bar_x, center_y, fill_w, bar_h), border_radius=5)
        
    pygame.draw.rect(surface, (200, 200, 200), (bar_x, center_y, bar_w, bar_h), 2, border_radius=5)
    
    pct_txt = fonts.get("tiny").render(f"{completed} / {total}", True, (255, 255, 255))
    surface.blit(pct_txt, pct_txt.get_rect(center=(center_x, center_y + bar_h // 2)))

def draw_turn_loading_screen(map_screen, surface):
    """Draws 4 dynamic progress bars for turn processing and a skip button."""
    ui_bars.draw_fullscreen_overlay(surface, 200)

    center_x = c.SCREEN_WIDTH // 2
    center_y = c.SCREEN_HEIGHT // 2

    font_title = fonts.get("title")
    txt = font_title.render(map_screen.loading_status_text, True, (255, 255, 255))
    surface.blit(txt, txt.get_rect(center=(center_x, center_y - 180)))

    # Configuration for bars
    bar_w, bar_h = 400, 25
    bar_x = center_x - (bar_w // 2)
    spacing = 65 # Tighter vertical spacing for 4 bars

    def draw_bar(y_pos, label, completed, total):
        lbl_txt = fonts.get("normal").render(label, True, c.UI_TEXT_LIGHT)
        surface.blit(lbl_txt, (bar_x, y_pos - 22))

        # Background
        pygame.draw.rect(surface, (40, 40, 60), (bar_x, y_pos, bar_w, bar_h), border_radius=5)

        # Progress Fill (Hold at 0% if total is currently unknown)
        progress_ratio = 0.0 if total == -1 else ((completed / float(total)) if total > 0 else 1.0)
        fill_w = int(bar_w * progress_ratio)
        if fill_w > 0:
            pygame.draw.rect(surface, (100, 200, 100), (bar_x, y_pos, fill_w, bar_h), border_radius=5)

        # Counter text
        if total == -1:
            display_text = "Calculating..."
        else:
            display_text = f"{completed}/{total}"
            
        pct_txt = fonts.get("tiny").render(display_text, True, (255, 255, 255))
        surface.blit(pct_txt, pct_txt.get_rect(center=(center_x, y_pos + bar_h // 2)))

        # Outline
        pygame.draw.rect(surface, (200, 200, 200), (bar_x, y_pos, bar_w, bar_h), 2, border_radius=5)

    # --- NEW MULTI TURN LOGIC ---
    multi_total = map_screen.multi_turns_total
    if multi_total > 0:
        draw_bar(center_y - 50, "Multi-Turn Skip Progress", map_screen.multi_turns_completed, multi_total)

        # --- Draw the Abort Multi-Turn Button ---
        abort_btn_rect = pygame.Rect(center_x - 110, c.SCREEN_HEIGHT - 90, 220, 45)
        mx, my = pygame.mouse.get_pos()

        already_aborting = map_screen.multi_turn_abort_requested
        if already_aborting:
            btn_color = (90, 90, 90)
            abort_label = "STOPPING..."
        else:
            btn_color = (200, 60, 60) if abort_btn_rect.collidepoint(mx, my) else (150, 40, 40)
            abort_label = "ABORT MULTI-TURN"

        pygame.draw.rect(surface, btn_color, abort_btn_rect, border_radius=5)
        pygame.draw.rect(surface, (255, 100, 100), abort_btn_rect, 2, border_radius=5)

        abort_txt = fonts.get("button").render(abort_label, True, (255, 255, 255))
        surface.blit(abort_txt, abort_txt.get_rect(center=abort_btn_rect.center))

        # Store for the event handler
        map_screen.multi_turn_abort_btn_rect = abort_btn_rect
        return

    # Render the distinct phases, in the order prepare_turn runs them. Summits
    # go first and are drawn only when there are any, since they need ABSOLUTE
    # or two model-driven majors and most turns have none -- an empty bar every
    # turn would be worse than no bar.
    top = center_y - 100
    summits = getattr(map_screen, "summits_total", 0)
    if summits:
        draw_bar(top, "1. Holding Summits", map_screen.summits_completed, summits)
        top += spacing

    draw_bar(top, "2. Analyzing Global Strategy", map_screen.proactive_tasks_completed, map_screen.proactive_tasks_total)
    draw_bar(top + spacing, "3. Drafting Proactive Diplomatics", map_screen.proactive_llm_tasks_completed, map_screen.proactive_llm_tasks_total)
    draw_bar(top + spacing*2, "4. Processing Global Responses", map_screen.responsive_tasks_completed, map_screen.responsive_tasks_total)
    draw_bar(top + spacing*3, "5. Re-Rendering World Maps", map_screen.refresh_tasks_completed, map_screen.refresh_tasks_total)

    # --- Draw the Force Skip Button ---
    # Only show it if there are LLM tasks that might get stuck.
    #
    # Summits belong in that list. They are the first model work of a turn and
    # run before either of the other two counters has been set, so the one
    # phase where nothing else has started yet was the one phase with no way
    # out of it -- which matters a great deal now that ai_turn_budget_seconds
    # can be 0 and this button is the only thing that ends a turn early.
    if (map_screen.proactive_llm_tasks_total > 0
            or map_screen.responsive_tasks_total > 0
            or getattr(map_screen, "summits_total", 0) > 0):
        skip_btn_rect = pygame.Rect(center_x - 100, center_y + 180, 200, 40)
        mx, my = pygame.mouse.get_pos()
        
        # Hover color feedback
        btn_color = (200, 60, 60) if skip_btn_rect.collidepoint(mx, my) else (150, 40, 40)
        
        pygame.draw.rect(surface, btn_color, skip_btn_rect, border_radius=5)
        pygame.draw.rect(surface, (255, 100, 100), skip_btn_rect, 2, border_radius=5)
        
        skip_txt = fonts.get("button").render("FORCE SKIP AI", True, (255, 255, 255))
        surface.blit(skip_txt, skip_txt.get_rect(center=skip_btn_rect.center))
        
        # Store for the event handler
        map_screen.force_skip_btn_rect = skip_btn_rect