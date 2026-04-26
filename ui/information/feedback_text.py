import pygame
from data.constants import FEEDBACK_TEXT_OFFSET_X, FEEDBACK_TEXT_Y

def draw_feedback(map_screen, surface):
    # --- LAYER 6: FEEDBACK & TOOLTIPS ---
    # this is the green text stuff
    if map_screen.feedback_text and pygame.time.get_ticks() - map_screen.feedback_timer < 2000:
        tsurf = map_screen.font.render(map_screen.feedback_text, True, (0, 255, 0))
        surface.blit(tsurf, (surface.get_width() - tsurf.get_width() - FEEDBACK_TEXT_OFFSET_X, FEEDBACK_TEXT_Y))