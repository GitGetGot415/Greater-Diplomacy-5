import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts

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

        # Progress Fill
        progress_ratio = (completed / float(total)) if total > 0 else 1.0
        fill_w = int(bar_w * progress_ratio)
        if fill_w > 0:
            pygame.draw.rect(surface, (100, 200, 100), (bar_x, y_pos, fill_w, bar_h), border_radius=5)

        # Counter text
        pct_txt = fonts.get("tiny").render(f"{completed}/{total}", True, (255, 255, 255))
        surface.blit(pct_txt, pct_txt.get_rect(center=(center_x, y_pos + bar_h // 2)))

        # Outline
        pygame.draw.rect(surface, (200, 200, 200), (bar_x, y_pos, bar_w, bar_h), 2, border_radius=5)

    # Render the 4 distinct phases
    draw_bar(center_y - 100, "1. Analyzing Global Strategy", map_screen.proactive_tasks_completed, map_screen.proactive_tasks_total)
    draw_bar(center_y - 100 + spacing, "2. Drafting Proactive Diplomatics", getattr(map_screen, 'proactive_llm_tasks_completed', 0), getattr(map_screen, 'proactive_llm_tasks_total', 0))
    draw_bar(center_y - 100 + spacing*2, "3. Processing Global Responses", map_screen.responsive_tasks_completed, map_screen.responsive_tasks_total)
    draw_bar(center_y - 100 + spacing*3, "4. Re-Rendering World Maps", getattr(map_screen, 'refresh_tasks_completed', 0), getattr(map_screen, 'refresh_tasks_total', 0))

    # --- Draw the Force Skip Button ---
    # Only show it if there are LLM tasks that might get stuck
    if getattr(map_screen, 'proactive_llm_tasks_total', 0) > 0 or map_screen.responsive_tasks_total > 0:
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