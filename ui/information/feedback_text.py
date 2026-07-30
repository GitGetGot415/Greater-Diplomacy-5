import pygame

# ==========================================
# LAYOUT
# ==========================================

# Green status text, measured in from the right edge of the screen.
FEEDBACK_TEXT_OFFSET_X = 620
FEEDBACK_TEXT_Y = 220
FEEDBACK_TEXT_DURATION_MS = 2000
FEEDBACK_TEXT_COLOR = (0, 255, 0)

def draw_feedback(map_screen, surface):
    # --- LAYER 6: FEEDBACK & TOOLTIPS ---
    # this is the green text stuff
    if map_screen.feedback_text and pygame.time.get_ticks() - map_screen.feedback_timer < FEEDBACK_TEXT_DURATION_MS:
        tsurf = map_screen.font.render(map_screen.feedback_text, True, FEEDBACK_TEXT_COLOR)
        surface.blit(tsurf, (surface.get_width() - tsurf.get_width() - FEEDBACK_TEXT_OFFSET_X, FEEDBACK_TEXT_Y))