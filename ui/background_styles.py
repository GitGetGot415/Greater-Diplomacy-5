"""Shared background colors and gradient strengths.

Edit these tables, then restart the game.
Colors use red, green, blue (RGB) values from 0 to 255.
A fourth color value sets opacity from 0 to 255.
Gradient strength must be zero or greater: 0 gives a flat fill; 1 gives standard shading.
Values above 1 increase contrast. Borders and bevels keep their existing appearance.
"""

import data.constants as c

MAP_FRAME_COLOR = (50, 80, 50)
LEFT_FRAME_COLOR = (40, 80, 80)
EDITOR_BG = (23, 35, 61, 245)

# Each bar can override the common color and the gradient strength.
MAP_BAR_STYLES = {
    "top": {"color": MAP_FRAME_COLOR, "gradient_strength": 0.0},
    "bottom": {"color": MAP_FRAME_COLOR, "gradient_strength": 0.0},
    "left": {"color": LEFT_FRAME_COLOR, "gradient_strength": 0.0},
    "unit_filter": {"color": (120, 120, 120), "gradient_strength": 0.5},
    "bottom_left": {"color": LEFT_FRAME_COLOR, "gradient_strength": 0.0},
}

MAP_CONFIRM_STYLES = {
    "country": {"color": (40, 40, 40), "gradient_strength": 0.0},
    "exit": {"color": (60, 40, 40), "gradient_strength": 0.0},
}

TEXT_INPUT_STYLES = {
    "inactive": {"color": (0, 0, 0), "gradient_strength": 0.0},
    "active": {"color": (0, 0, 0), "gradient_strength": 0.0},
    "dialog": {"color": (0, 0, 0), "gradient_strength": 0.0},
    "message": {"color": (0, 0, 0), "gradient_strength": 0.0},
}

# Credits, help, confirmations, and other dialogs share this background.
DIALOG_STYLES = {
    "main": {"color": (40, 40, 40), "gradient_strength": 0.5},
    "file_browser": {"color": c.MODAL_BG, "gradient_strength": 1.0},
}

MESSAGE_PANEL_STYLES = {
    "contacts": {"color": (35, 35, 45), "gradient_strength": 1.0},
}

ASSET_VIEWER_STYLES = {
    "folders": {"color": (35, 35, 45), "gradient_strength": 0.0},
    "files": {"color": (30, 30, 38), "gradient_strength": 0.0},
    "preview": {"color": (60, 60, 75), "gradient_strength": 0.0},
}

# Shared sliders, scrollbars, and music progress use these RGB colors.
# Replace a color reference with an RGB tuple to override its default.
SLIDER_STYLES = {
    "track": {"color": c.COLOR_SLIDER_TRACK, "gradient_strength": 0.5},
    "handle": {"color": c.COLOR_SLIDER_HANDLE, "gradient_strength": 0.5},
    "locked": {"color": (60, 40, 40), "gradient_strength": 0.5},
    "progress": {"color": (255, 150, 50), "gradient_strength": 0.5},
}

TUTORIAL_PANEL_STYLES = {
    "main": {"color": (34, 38, 49), "gradient_strength": 0.3},
    "keyboard_navigation": {"color": (25, 31, 43), "gradient_strength": 0.0},
}

# The main style applies to both the army editor and the custom emblem editor.
ARMY_EDITOR_STYLES = {
    "main": {"color": EDITOR_BG, "gradient_strength": 0.0},
    "name_field": {"color": (0, 0, 0), "gradient_strength": 0.0},
    "emblem_preview": {"color": (10, 20, 40), "gradient_strength": 1.0},
}

ARMY_BUTTON_STYLES = {
    "create": {"color": (42, 98, 73), "gradient_strength": 0.5},
    "E": {"color": (62, 88, 135), "gradient_strength": 0.0},
    "T": {"color": (62, 88, 135), "active_color": (50, 108, 83), "gradient_strength": 0.0},
    # Army cards use each army's symbol color. Unassigned uses constants.UNASSIGNED_ARMY_COLOR.
    "army_group": {"gradient_strength": 0.5},
    "unassigned": {"gradient_strength": 0.0},
}
