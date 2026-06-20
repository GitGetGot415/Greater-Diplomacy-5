import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts

def draw_simple_refresh_bar(surface, status_text, completed, total):
    """Unified data refresh overlay to prevent duplication on base menu screens."""
    overlay = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 200))
    surface.blit(overlay, (0, 0))

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
    overlay = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 200))
    surface.blit(overlay, (0, 0))

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
        lbl_txt = fonts.get("normal").render(label, True, (200, 200, 200))
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
        return

    # Render the 4 distinct phases
    draw_bar(center_y - 100, "1. Analyzing Global Strategy", map_screen.proactive_tasks_completed, map_screen.proactive_tasks_total)
    draw_bar(center_y - 100 + spacing, "2. Drafting Proactive Diplomatics", map_screen.proactive_llm_tasks_completed, map_screen.proactive_llm_tasks_total)
    draw_bar(center_y - 100 + spacing*2, "3. Processing Global Responses", map_screen.responsive_tasks_completed, map_screen.responsive_tasks_total)
    draw_bar(center_y - 100 + spacing*3, "4. Re-Rendering World Maps", map_screen.refresh_tasks_completed, map_screen.refresh_tasks_total)

    # --- Draw the Force Skip Button ---
    # Only show it if there are LLM tasks that might get stuck
    if map_screen.proactive_llm_tasks_total > 0 or map_screen.responsive_tasks_total > 0:
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