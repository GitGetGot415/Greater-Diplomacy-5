import pygame
import os
from contextlib import contextmanager
import data.constants as c

# Cache the images using a tuple (filename, scale, directory) as the key
_ui_images_cache = {}

# ==========================================
# UNIFIED UI HELPERS
# ==========================================

def calculate_scroll_snap(mouse_y, max_scroll, track_y, view_h):
    """Standardized math for dragging scrollbars."""
    if max_scroll >= 0: return 0
    handle_h = max(30, int(view_h * (view_h / max(1, view_h - max_scroll))))
    rel_y = mouse_y - track_y - (handle_h / 2)
    max_y = view_h - handle_h
    ratio = max(0.0, min(1.0, rel_y / max(1, max_y)))
    return ratio * max_scroll

def draw_standard_scrollbar(surface, scroll_y, max_scroll, track_x, track_y, view_h, width=15):
    """Standardized scrollbar rendering to eliminate visual duplication across screens."""
    if max_scroll >= 0:
        return None, None
    track_rect = pygame.Rect(track_x, track_y, width, view_h)
    pygame.draw.rect(surface, (50, 50, 60), track_rect)
    
    ratio = scroll_y / max_scroll
    handle_h = max(30, int(view_h * (view_h / (view_h - max_scroll))))
    handle_y = track_y + ratio * (view_h - handle_h)
    
    handle_rect = pygame.Rect(track_x, handle_y, width, handle_h)
    pygame.draw.rect(surface, (150, 150, 150), handle_rect, border_radius=5)
    
    return track_rect, handle_rect

@contextmanager
def clip_scroll_region(surface, rect, line_color=(90, 90, 100), draw_top=True, draw_bottom=True):
    """Standard boundary for every scrollable region: real set_clip cropping,
    with a thin line marking the edge(s) that still have content beyond them.

    Replaces the old mix of "just don't draw rows past a pixel threshold"
    (which pops a whole row in/out at once) and each screen hand-rolling its
    own set_clip + border. `draw_top`/`draw_bottom` should reflect whether
    that side actually has hidden content (e.g. `scroll_y != 0` for the top,
    `scroll_y > max_scroll` for the bottom), matching how the scrollbar handle
    itself already only appears when there's something to scroll.

    Usage: `with ui_bars.clip_scroll_region(surface, rect, draw_top=..., draw_bottom=...): ...draw rows...`
    """
    old_clip = surface.get_clip()
    surface.set_clip(rect)
    try:
        yield
    finally:
        surface.set_clip(old_clip)
        if draw_top:
            pygame.draw.line(surface, line_color, (rect.left, rect.top), (rect.right, rect.top), 1)
        if draw_bottom:
            pygame.draw.line(surface, line_color, (rect.left, rect.bottom - 1), (rect.right, rect.bottom - 1), 1)

def draw_fullscreen_overlay(surface, alpha=180):
    """Draws a semi-transparent black overlay across the entire screen."""
    overlay = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, alpha))
    surface.blit(overlay, (0, 0))

def draw_modal_box(surface, rect, bg_color=(40, 40, 50), border_color=(100, 150, 255), border_width=2):
    """Draws a standardized modal background box with a border."""
    if len(bg_color) == 4:
        panel_surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        panel_surf.fill(bg_color)
        surface.blit(panel_surf, rect.topleft)
    else:
        pygame.draw.rect(surface, bg_color, rect)
    pygame.draw.rect(surface, border_color, rect, border_width)

def draw_centered_title(surface, text, y_pos, font_preset="heading1", color=(255, 255, 255), shadow=False):
    """Draws centered title text to standardize headers."""
    from map_logic.rendering.font_manager import fonts
    title_font = fonts.get(font_preset)
    title_surf = title_font.render(text, True, color)
    x_pos = c.SCREEN_WIDTH // 2 - title_surf.get_width() // 2
    if shadow:
        surface.blit(title_font.render(text, True, (0, 0, 0)), (x_pos + 1, y_pos + 1))
    rect = title_surf.get_rect(topleft=(x_pos, y_pos))
    surface.blit(title_surf, rect)
    return rect

# ==========================================
# CACHE & DRAWING
# ==========================================

def get_ui_image(filename, scale=1.0, directory=c.ASSETS_DIR):
    cache_key = (filename, scale, directory)
    
    if cache_key not in _ui_images_cache:
        try:
            # Load the original image (Change .convert() to .convert_alpha())
            img = pygame.image.load(os.path.join(directory, filename)).convert_alpha()
            
            # Apply scaling if the scale multiplier is not exactly 1.0
            if scale != 1.0:
                new_w = max(1, int(img.get_width() * scale))
                new_h = max(1, int(img.get_height() * scale))
                img = pygame.transform.scale(img, (new_w, new_h))
                
            _ui_images_cache[cache_key] = img
            
        except FileNotFoundError:
            print(f"Warning: {directory}/{filename} not found. Using fallback.")
            fallback = pygame.Surface((64, 64))
            fallback.fill((40, 40, 40))
            _ui_images_cache[cache_key] = fallback
            
    return _ui_images_cache[cache_key]

def draw_textured_rect(surface, rect, image, mode="tile"):
    """Fills the target rect with an image by either tiling or stretching it."""
    
    if mode == "stretch":
        # Scale the image exactly to the dimensions of the rect
        stretched_img = pygame.transform.scale(image, (rect.width, rect.height))
        surface.blit(stretched_img, rect.topleft)
        
    else: # Default to "tile" mode
        original_clip = surface.get_clip()
        surface.set_clip(rect)
        
        img_w, img_h = image.get_size()
        
        for x in range(rect.left, rect.right, img_w):
            for y in range(rect.top, rect.bottom, img_h):
                surface.blit(image, (x, y))
                
        surface.set_clip(original_clip)
    
    pygame.draw.rect(surface, (20, 20, 20), rect, 2)

def draw_ui_bars(map_screen, surface):
    # Pass the scale multiplier as the second argument (e.g., 2.0 is double size, 0.5 is half size)
    # Tiled bars benefit greatly from scaling, stretched bars will ignore it anyway
    top_bg = get_ui_image("UI Square Top.png", 3.8)
    bot_bg = get_ui_image("UI Square Bottom.png", 3.8)
    side_bg = get_ui_image("UI Square 2.png", 10.0)
    corner_bg = get_ui_image("UI Square 3.png", 1.0) # Doubled in size before tiling

    # --- LAYER 4: UI BARS & HUD ---
    draw_textured_rect(surface, map_screen.top_bar_rect, top_bg, mode="tile")
    draw_textured_rect(surface, map_screen.bot_bar_rect, bot_bg, mode="tile")
    
    if not map_screen.selection_mode and not map_screen.hide_raised_rect:
        draw_textured_rect(surface, map_screen.raised_rect, side_bg, mode="tile")
        draw_textured_rect(surface, map_screen.ui_background_rect, corner_bg, mode="stretch")