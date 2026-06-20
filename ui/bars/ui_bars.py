import pygame
import os
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

# ==========================================
# CACHE & DRAWING
# ==========================================

def get_ui_image(filename, scale=1.0, directory=c.ASSETS_DIR):
    global _ui_images_cache
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