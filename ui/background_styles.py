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

# Game panels retain their borders and layout in their screen modules.
PUPPET_PANEL_STYLES = {
    "subjects": {"color": c.PANEL_THEME_INFO[0], "gradient_strength": 0.5},
    "release_nations": {"color": c.PANEL_THEME_INFO_OVER_MAP[0], "gradient_strength": 0.5},
}

COUNTRY_SUMMARY_STYLES = {
    "card": {"color": (35, 41, 53), "gradient_strength": 1.0},
}

PRODUCTION_QUEUE_STYLES = {
    "production": {"color": c.HUD_PANEL_BG, "gradient_strength": 1.0},
    "map": {"color": (*c.HUD_PANEL_BG, 200), "gradient_strength": 1.0},
}

# These entries match the category prefixes in production.SECTION_PANELS.
PRODUCTION_PANEL_STYLES = {
    "admin": {"color": (40, 20, 60), "gradient_strength": 0.0},
    "other": {"color": (60, 40, 20), "gradient_strength": 0.0},
    "infantry": {"color": (30, 60, 30), "gradient_strength": 0.0},
    "tank": {"color": (20, 45, 20), "gradient_strength": 0.0},
    "navy": {"color": (30, 30, 60), "gradient_strength": 0.0},
    "air": {"color": (60, 30, 30), "gradient_strength": 0.0},
    "custom": {"color": (60, 55, 20), "gradient_strength": 0.0},
    "stats": {"color": (40, 40, 40), "gradient_strength": 0.0},
}

RESOURCE_BAR_STYLES = {
    "full_width": {"color": (30, 30, 30), "gradient_strength": 0.5},
}

COMBAT_PANEL_STYLES = {
    "main": {"color": c.PANEL_THEME_DANGER[0], "gradient_strength": 0.5},
}

POLITICS_PANEL_STYLES = {
    "main": {"color": (34, 38, 58), "gradient_strength": 0.5},
    "policy_card": {"color": (27, 31, 49), "gradient_strength": 0.5},
}

AUTOMATION_PANEL_STYLES = {
    "main": {"color": (40, 45, 50), "gradient_strength": 0.5},
}

ECONOMY_PANEL_STYLES = {
    "resource": {"color": (40, 40, 50), "gradient_strength": 1.0},
    "expenses": {"color": (25, 28, 35), "gradient_strength": 1.0},
}

ORDERS_PANEL_STYLES = {
    "main": {"color": c.HUD_PANEL_BG, "gradient_strength": 1.0},
}

DEFAULT_GRADIENT_EDITOR_PANELS = 0.5

EDITOR_PANEL_STYLES = {
    "research": {"color": c.PANEL_THEME_EDIT[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "research_list": {"color": c.PANEL_THEME_EDIT[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "date": {"color": c.PANEL_THEME_EDIT[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "starting_economy": {"color": c.PANEL_THEME_INFO[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "starting_economy_list": {"color": c.PANEL_THEME_CONFIRM[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "politics": {"color": c.PANEL_THEME_SPECIAL[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "politics_list": {"color": c.PANEL_THEME_SPECIAL[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "personality": {"color": c.PANEL_THEME_SPECIAL[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "personality_list": {"color": c.PANEL_THEME_SPECIAL[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "diplomacy": {"color": c.PANEL_THEME_INFO[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "convoy_converter": {"color": c.PANEL_THEME_CONFIRM[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "resource_brush": {"color": c.PANEL_THEME_SPECIAL[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "clear_map": {"color": c.PANEL_THEME_DANGER[0], "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "scripted_events": {"color": c.MODAL_BG, "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "scripted_event_lists": {"color": (26, 26, 34), "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "unit_stats": {"color": c.MODAL_BG, "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "unit_stats_row": {"color": (44, 44, 56), "gradient_strength": 0.0},
    "construction_turns": {"color": c.MODAL_BG, "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
    "construction_turns_row": {"color": (44, 44, 56), "gradient_strength": 0.0},
    "historical_leader_card": {"color": (35, 45, 35), "gradient_strength": DEFAULT_GRADIENT_EDITOR_PANELS},
}

# The research timeline is shared by play, spectators, and the country editor.
RESEARCH_PANEL_STYLES = {
    "slots": {"color": (40, 40, 60), "gradient_strength": 1.0},
    "details": {"color": (30, 30, 40), "gradient_strength": 1.0},
    "header": {"color": (40, 40, 50), "gradient_strength": 1.0},
}

MUSIC_PANEL_STYLES = {
    "albums": {"color": (35, 35, 45), "gradient_strength": 1.0},
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
