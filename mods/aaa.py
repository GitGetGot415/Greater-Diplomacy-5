#ui/information/feedback_text.py
import pygame

# ==========================================
# LAYOUT
# ==========================================

# Green status text, measured in from the right edge of the screen.
FEEDBACK_TEXT_OFFSET_X = 620
FEEDBACK_TEXT_Y = 220
FEEDBACK_TEXT_DURATION_MS = 2000
FEEDBACK_TEXT_COLOR = (0, 255, 0)

# Trying to make feedback text linger longer -- but this typos the constant
# name (DURATON instead of DURATION). Since it's a bare module-level
# statement, not something tucked inside a function body, it runs the
# instant this file is imported, not later when draw_feedback() is called --
# so it's a NameError at *load* time, not at use time. This is exactly the
# failure mode mod_loader.py's exec_module() fallback exists for: without
# it, this typo would crash the game before it ever reached a menu; with it,
# the game just falls back to the real feedback_text.py and the Mods screen
# shows this mod as [ERROR].
FEEDBACK_TEXT_DURATION_MS = FEEDBACK_TEXT_DURATON_MS + 1000

def draw_feedback(map_screen, surface):
    # --- LAYER 6: FEEDBACK & TOOLTIPS ---
    # this is the green text stuff
    if map_screen.feedback_text and pygame.time.get_ticks() - map_screen.feedback_timer < FEEDBACK_TEXT_DURATION_MS:
        tsurf = map_screen.font.render(map_screen.feedback_text, True, FEEDBACK_TEXT_COLOR)
        surface.blit(tsurf, (surface.get_width() - tsurf.get_width() - FEEDBACK_TEXT_OFFSET_X, FEEDBACK_TEXT_Y))
