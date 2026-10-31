"""Shared background colors and gradient strengths.

Edit these tables, then restart the game.
Colors use red, green, blue (RGB) values from 0 to 255.
A fourth color value sets opacity from 0 to 255.
Gradient strength must be zero or greater: 0 gives a flat fill; 1 gives standard shading.
Values above 1 increase contrast. Borders and bevels keep their existing appearance.
"""

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
