import pygame
import os
from contextlib import contextmanager
import data.constants as c

# Cache the images using a tuple (filename, scale, directory) as the key
_ui_images_cache = {}

# Recolored checkerboard tiles, cached by target bg_color so each screen only
# pays the generation cost once
_checkerboard_cache = {}

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

def calculate_scroll_snap_horizontal(mouse_x, min_value, max_value, track_x, track_w):
    """Horizontal counterpart to calculate_scroll_snap. Unlike the vertical
    version's fixed 0..max_scroll convention, min_value/max_value are passed
    explicitly so callers with their own signed scroll ranges (e.g. a
    timeline that can scroll both earlier and later than its start) can
    reuse the same drag-to-position math."""
    if max_value <= min_value: return min_value
    span = max_value - min_value
    handle_w = max(30, int(track_w * (track_w / (track_w + span))))
    rel_x = mouse_x - track_x - (handle_w / 2)
    max_x = track_w - handle_w
    ratio = max(0.0, min(1.0, rel_x / max(1, max_x)))
    return min_value + ratio * span

def draw_standard_scrollbar_horizontal(surface, value, min_value, max_value, track_x, track_y, track_w, height=15):
    """Horizontal counterpart to draw_standard_scrollbar -- see
    calculate_scroll_snap_horizontal for why the range is passed explicitly
    instead of assuming 0..max_scroll."""
    if max_value <= min_value:
        return None, None
    track_rect = pygame.Rect(track_x, track_y, track_w, height)
    pygame.draw.rect(surface, (50, 50, 60), track_rect)

    span = max_value - min_value
    handle_w = max(30, int(track_w * (track_w / (track_w + span))))
    ratio = (value - min_value) / span
    handle_x = track_x + ratio * (track_w - handle_w)

    handle_rect = pygame.Rect(handle_x, track_y, handle_w, height)
    pygame.draw.rect(surface, (150, 150, 150), handle_rect, border_radius=5)

    return track_rect, handle_rect

@contextmanager
def clip_scroll_region(surface, rect, line_color=(90, 90, 100), draw_top=True, draw_bottom=True):
    """Standard boundary for every scrollable region: real set_clip cropping.

    Replaces the old mix of "just don't draw rows past a pixel threshold"
    (which pops a whole row in/out at once) and each screen hand-rolling its
    own set_clip + border. `line_color`/`draw_top`/`draw_bottom` are accepted
    for backward compatibility with existing call sites but are otherwise
    unused -- the boundary is communicated by the scrollbar handle alone.

    Usage: `with ui_bars.clip_scroll_region(surface, rect, draw_top=..., draw_bottom=...): ...draw rows...`
    """
    old_clip = surface.get_clip()
    surface.set_clip(rect)
    try:
        yield
    finally:
        surface.set_clip(old_clip)

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

def draw_translucent_panel(surface, rect, rgba, border_color=None, border_width=2, radius=0):
    """A panel with an alpha fill -- the map-layered HUD boxes.

    draw_modal_box takes the same 4-tuple path, but six panels were building the
    SRCALPHA surface by hand because they also wanted a corner radius or no
    border at all. This is that variant, kept separate so neither call site has
    to pass arguments it doesn't use.
    """
    panel_surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    if radius:
        pygame.draw.rect(panel_surf, rgba, panel_surf.get_rect(), border_radius=radius)
    else:
        panel_surf.fill(rgba)
    surface.blit(panel_surf, rect.topleft)
    if border_color:
        pygame.draw.rect(surface, border_color, rect, border_width, border_radius=radius)


def draw_confirm_prompt(surface, box_rect, question, subtitle=None,
                        yes_label="CONFIRM", no_label="CANCEL",
                        yes_color=(0, 150, 0), no_color=(150, 0, 0),
                        overlay_alpha=180, hover=False,
                        bg=(40, 40, 40), border=(200, 200, 200), border_width=2):
    """Draws a yes/no prompt in `box_rect` and returns its two button rects.

    For the confirmations the map draws as a render layer rather than as a
    screen -- picking a country, quitting to the menu -- so that they can keep
    gating map input through their own flags instead of going on the modal
    stack. Both carried their own copy of the dim / box / question / two
    buttons sequence, in different geometry.

    The returned rects are what the click handler must hit-test. Publishing
    them is the point: re-deriving the same buttons somewhere else is how the
    quit dialog ended up drawn and clicked in two different coordinate frames.

    `overlay_alpha` stays a parameter because the country picker deliberately
    dims less -- you are meant to keep seeing the map you are choosing from.
    """
    from map_logic.rendering.font_manager import fonts

    draw_fullscreen_overlay(surface, overlay_alpha)
    draw_modal_box(surface, box_rect, bg_color=bg, border_color=border, border_width=border_width)

    font = fonts.get("heading2")
    head = font.render(question, True, (255, 255, 255))
    surface.blit(head, head.get_rect(center=(box_rect.centerx, box_rect.y + 50)))
    if subtitle:
        sub = fonts.get("normal").render(subtitle, True, c.UI_TEXT_LIGHT)
        surface.blit(sub, sub.get_rect(center=(box_rect.centerx, box_rect.y + 85)))

    btn_w, btn_h = c.CONFIRM_BTN_SIZE
    btn_y = box_rect.bottom - 70
    yes_rect = pygame.Rect(box_rect.centerx - c.CONFIRM_BTN_DX, btn_y, btn_w, btn_h)
    no_rect = pygame.Rect(box_rect.centerx + 30, btn_y, btn_w, btn_h)

    mouse_pos = pygame.mouse.get_pos()
    btn_font = fonts.get("button")
    for rect, label, color in ((yes_rect, yes_label, yes_color), (no_rect, no_label, no_color)):
        # `hover` dims the button until the cursor is on it, which is the
        # quit dialog's existing feedback; the picker had none.
        shade = tuple(max(0, ch - 50) for ch in color) if hover and not rect.collidepoint(mouse_pos) else color
        pygame.draw.rect(surface, shade, rect)
        text = btn_font.render(label, True, (255, 255, 255))
        surface.blit(text, text.get_rect(center=rect.center))

    return yes_rect, no_rect


def draw_panel_frame(surface, rect, title=None, bg=None, border=None, border_width=3,
                     title_dy=None, font_preset="heading2"):
    """The standard modal panel: filled box, border, and a centred title.

    Every modal screen repeated this same three-step sequence with its own
    slightly different colours and title offset. Defaults come from the shared
    palette so they all land on one look; the arguments stay for the screens
    that genuinely need something else.
    """
    draw_modal_box(surface, rect,
                   bg_color=c.MODAL_BG if bg is None else bg,
                   border_color=c.MODAL_BORDER if border is None else border,
                   border_width=border_width)
    if title:
        dy = c.MODAL_TITLE_Y_OFFSET if title_dy is None else title_dy
        return draw_centered_title(surface, title, rect.y + dy, font_preset)
    return None


def acquire_surface(size=None, caption=None):
    """Returns (surface, owns_display), creating a window only when none exists.

    Used by the standalone paths -- the dev tools in data/editors and the
    map_tools scripts run outside the game's main loop, with no display up yet.
    """
    surface = pygame.display.get_surface()
    if surface is not None:
        return surface, False

    if not pygame.get_init():
        pygame.init()
    surface = pygame.display.set_mode(size or (c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
    if caption:
        pygame.display.set_caption(caption)
    return surface, True


def release_surface(owns_display):
    """Tears down a display acquire_surface created, and only that one."""
    if owns_display:
        pygame.display.quit()


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

def get_checkerboard_tile(base_color):
    """Builds (and caches) a checkerboard tile tinted to base_color.

    The on-disk template (CHECKERBOARD_TEMPLATE_FILE) is plain red -- it's
    only sampled to learn the brightness ratio between its two squares and
    its seam line versus its base square. Those ratios are then applied to
    base_color via uniform per-channel scaling, which changes value without
    touching hue, so every screen gets a checkerboard in its own bg_color
    rather than the template's literal red.

    base_color is quantized before use so callers with a continuously
    changing color (the Map screen's zoom-driven ocean tint) can't grow the
    cache without bound -- a couple of shades of visual precision buys an
    always-small cache.
    """
    quantized = tuple(min(255, max(0, round(ch / 4) * 4)) for ch in base_color)
    cache_key = quantized
    if cache_key in _checkerboard_cache:
        return _checkerboard_cache[cache_key]
    base_color = quantized

    template = get_ui_image(c.CHECKERBOARD_TEMPLATE_FILE, directory=c.BACKGROUNDS_DIR)
    square = template.get_width() // 2

    color_a = template.get_at((square // 2, square // 2))[:3]
    color_b = template.get_at((square + square // 2, square // 2))[:3]
    seam = template.get_at((square, square // 2))[:3]

    def brightness(color):
        return sum(color) / 3.0

    base_brightness = brightness(color_a) or 1.0
    ratio_b = brightness(color_b) / base_brightness
    ratio_seam = brightness(seam) / base_brightness

    def scale(color, ratio):
        return tuple(min(255, max(0, int(ch * ratio))) for ch in color)

    shade_a = tuple(base_color)
    shade_b = scale(base_color, ratio_b)
    shade_seam = scale(base_color, ratio_seam)

    tile_size = square * 2
    tile = pygame.Surface((tile_size, tile_size))
    for row in range(2):
        for col in range(2):
            color = shade_a if (row + col) % 2 == 0 else shade_b
            tile.fill(color, (col * square, row * square, square, square))
    pygame.draw.line(tile, shade_seam, (0, square), (tile_size, square))
    pygame.draw.line(tile, shade_seam, (square, 0), (square, tile_size))

    _checkerboard_cache[cache_key] = tile
    return tile

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