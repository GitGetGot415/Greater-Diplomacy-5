"""Layout, timing, audio, and drawing constants for the tactical battle screen."""

import math
import os

import pygame

import data.constants as c


PANEL_X = 60

ROSTER_TOP = 56

PANEL_WIDTH = 1160

PANEL_TOPS = (365, 120)  # Friendly and enemy rosters retain their separate areas.

# Edit Battle and preview share one card size and one grid: each column of the grid is a
# battlefield rank, holding one card or two cards stacked.
CARD_SIZE = (160, 68)

CARD_GAP = 12  # Between columns, and between a column's two rows.

ROSTER_ROWS = c.CUSTOM_BATTLE_UNITS_PER_COLUMN

ROSTER_HEIGHT = ROSTER_ROWS * CARD_SIZE[1] + (ROSTER_ROWS - 1) * CARD_GAP

CONTROLLED_CARD_BRIGHTNESS = 100

TITLE_HELP_GAP = 12

# Card contents: the icon, health bar, and flag on the left; health, attack, and defense on the right.
CARD_INSET = 5

CARD_STATS_WIDTH = 64  # Fits a six-character value such as 999.9K after its icon.

CARD_LEFT_WIDTH = CARD_SIZE[0] - CARD_STATS_WIDTH - 2 * CARD_INSET

CARD_NAME_TOP = 2  # Edit Battle only: the unit name shares the top row with the gear button.

EDIT_ICON_TOP = 20

EDIT_ICON_MAX_SCALE = 1.4

PREVIEW_ICON_TOP = 4

CARD_BAR_TOP = 53

CARD_BAR_HEIGHT = 10

CARD_BAR_GRAB_PAD = 6  # Extra pixels above and below the bar that still grab it in editing.

CARD_BAR_FLAG_GAP = 4

CARD_BAR_FLAG_SIZE = (18, 12)

CARD_ICON_BAR_GAP = 4

EDIT_STATS_TOP = 20

PREVIEW_STATS_TOP = 11

CARD_STAT_ROW_HEIGHT = 15

CONTROLLED_ARROW_Y = 30  # Below the edit card's name row.

# Pixels at each card's left and right edge where a drop, like a drop in the gap between
# columns, gives the dragged card a new column instead of dropping it on that card.
DROP_NEW_COLUMN_EDGE = 14

HEALTH_BAR_FULL_COLOR = (105, 215, 85)

HEALTH_BAR_HALF_COLOR = (235, 205, 60)  # Reached at half health.

HEALTH_BAR_EMPTY_COLOR = (215, 60, 50)  # Reached at zero health; the fill blends between the three colors.

HEALTH_BAR_SHADE = 30  # Brightness step between the light, middle, and dark bands of the fill.

HEALTH_BAR_BANDS = 3

PANEL_BOTTOM_SPACE = 32  # Below the cards: scrollbar row and margin.

PANEL_HEIGHT = ROSTER_TOP + ROSTER_HEIGHT + PANEL_BOTTOM_SPACE

CARD_STAT_ICON_SIZE = 12

BATTLE_FLAG_SIZE = (14, 9)

BATTLE_FLAG_GAP = 3

MIXED_LABEL = "Mixed"

CARD_EDIT_SIZE = 18

CARD_EDIT_ICON_PAD = 3  # Between the gear button's edge and its icon.

CARD_EDIT_INSET = 2

ROSTER_INSET = 20

ROSTER_WIDTH = 900

SCROLLBAR_HEIGHT = 14

BUTTON_WIDTH = 170

CLEAR_ALL_OFFSET_Y = 20

CLEAR_ALL_HEIGHT = 32

TEAM_COLORS = ((85, 170, 245), (235, 100, 90))

DEATH_EXPLOSION_SECONDS = 0.7

DEATH_EXPLOSION_RADIUS = 36

DEATH_EXPLOSION_PARTICLE_SIZE = 12

DEATH_EXPLOSION_PARTICLE_COUNT = 8

DEATH_EXPLOSION_PARTICLE_SHAPE = "square"  # "circle" or "square"

DEATH_EXPLOSION_SPREAD = "circle"  # "circle" or "square"

DEATH_EXPLOSION_CIRCLE_COLOR = (255, 180, 60)

DEATH_EXPLOSION_CIRCLE_ALPHA = 180

DEATH_EXPLOSION_COLORS = ((255, 240, 150), (255, 160, 45), (205, 65, 30), (75, 70, 65))

DEATH_EXPLOSION_CIRCLE_OFFSETS = tuple((math.cos(i * math.tau / DEATH_EXPLOSION_PARTICLE_COUNT), math.sin(i * math.tau / DEATH_EXPLOSION_PARTICLE_COUNT)) for i in range(DEATH_EXPLOSION_PARTICLE_COUNT))

DEATH_EXPLOSION_OFFSETS = {"circle": DEATH_EXPLOSION_CIRCLE_OFFSETS, "square": tuple((dx / max(abs(dx), abs(dy)), dy / max(abs(dx), abs(dy))) for dx, dy in DEATH_EXPLOSION_CIRCLE_OFFSETS)}[DEATH_EXPLOSION_SPREAD]

DEATH_EXPLOSION_DRAW_PARTICLE = {"circle": pygame.draw.ellipse, "square": pygame.draw.rect}[DEATH_EXPLOSION_PARTICLE_SHAPE]

# A torpedo hit on a ship reuses the explosion animation in white and blue, as a splash of water.
TORPEDO_SPLASH_CIRCLE_COLOR = (190, 225, 255)

TORPEDO_SPLASH_COLORS = ((255, 255, 255), (220, 240, 255), (120, 185, 240), (45, 110, 200))

# (expanding circle color, particle colors from start to finish) for each explosion animation.
DEATH_EXPLOSION_PALETTE = (DEATH_EXPLOSION_CIRCLE_COLOR, DEATH_EXPLOSION_COLORS)

TORPEDO_SPLASH_PALETTE = (TORPEDO_SPLASH_CIRCLE_COLOR, TORPEDO_SPLASH_COLORS)

EDIT_BATTLE_HELP_TEXT = (
    "Build both armies, choose their deployment order, and optionally choose a unit to control. Custom battles do not change your campaign.\n\n"
    "Add Friendly and Add Enemy open the unit picker. Choose units to add them; Cancel closes the picker and keeps your additions. Select a card and choose Duplicate to copy that unit, including nationality and starting HP, or Remove to remove that unit. Clear All empties that army.\n\n"
    "Each column of cards is one rank of the battlefield; the leftmost column deploys in the front rank, closest to the enemy. A column holds one division, centered, or two divisions, one above the other. New units join the last column when it has room. Drop a card on another card to swap them, on a column's empty lower space to stack it there, or between columns to give it a column of its own. Drag cards into the other army to move units between sides. Duplicating and moving units cannot exceed the destination army's unit limit. Scroll long rosters with the mouse wheel, scrollbar, or by dragging the roster background.\n\n"
    "A card's gear button opens Unit Settings for nationality and starting HP. You can also drag along the card's health bar to change starting HP.\n\n"
    "To select several units, start in empty roster panel space outside the card area and drag a square across the cards. Every selected card gets a gold outline. The gear button on any selected card opens Group Settings for all selected units; dragging a selected card's health bar changes the group's starting HP. Mixed means the selected units have different values. Click empty space or enter preview to clear the selection.\n\n"
    "Select a friendly card and choose Control to command that division's middle sub-unit during the battle. The controlled division's button is lighter blue and has a yellow arrow. Release Control lets both armies fight automatically.\n\n"
    "Random replaces both armies. Year limits the units Random can choose; manual unit selection is unrestricted by Year. The terrain button chooses the custom battlefield's terrain.\n\n"
    "The normal-game forecast estimates how these armies would fight under the strategic combat rules. The tactical battle can have a different result.\n\n"
    "Both armies need units before Simulate becomes available. Simulate opens Preview Battle; combat starts only after Start in preview. Exit returns to the menu."
)

PREVIEW_BATTLE_HELP_TEXT = (
    "Here you can review the armies before combat. The battle is paused here, so units do not move or fire.\n\n"
    "Each column of cards is one rank of the battlefield; the leftmost column deploys in the front rank, closest to the enemy. Drag friendly cards to change deployment: drop a card on another card to swap them, on a column's empty lower space to stack it there, or between columns to give it a column of its own.\n\n"
    "Start begins the tactical battle with the prepared forces.\n\n"
)

PREVIEW_CUSTOM_HELP_TEXT = "Retreat returns to Edit Battle and keeps your army setup."

PREVIEW_CAMPAIGN_HELP_TEXT = "Retreat opens the map to choose a retreat destination. Back from the retreat chooser returns to this preview."

# Actual battle fills the whole screen. The mouse wheel steps through these scales, starting at 1.0.
ZOOM_LEVELS = (0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.75, 1.0, 1.25, 1.5, 2.0)

DEFAULT_ZOOM_INDEX = ZOOM_LEVELS.index(1.0)

# Battle audio multipliers: 0.0 mutes, 0.5 halves, and 1.0 keeps normal volume.
# Edit these values and restart the game. Zooming out reduces both further.
BATTLE_MUSIC_VOLUME = 1.0

BATTLE_SFX_VOLUME = 1.0

# Unit sounds fade with distance from the controlled unit, or from the screen's center while spectating.
# Distances are shares of the battlefield's width, so land and naval arenas fade alike.
SFX_FULL_VOLUME_DISTANCE = 0.1  # Closer than this plays at full volume.

SFX_FLOOR_DISTANCE = 0.5  # Farther than this plays at SFX_DISTANCE_FLOOR.

SFX_DISTANCE_FLOOR = 0.1  # Share of full volume for the most distant sounds; they never go silent.

AIM_CAMERA_OFFSET = 1.0  # Share of the pointer's distance from the view center, in screen pixels.

CONTROLLED_MIN_ZOOM = 0.15 # Minimum zoom while controlling a living unit; choose a value from ZOOM_LEVELS.

MIN_PLAYER_INDICATOR_SCALE = 0.85

EDGE_INDICATOR_INSET = 48

EDGE_INDICATOR_TOP = 100

EDGE_INDICATOR_SIZE = 10

EDGE_INDICATOR_SPACING = 80

EDGE_INDICATOR_LABEL_STEP = 25  # Battlefield distance, rounded to keep moving labels readable.

GRASS_TILE = 64  # Battlefield pixels per square of the battlefield's faint checkerboard.

TERRAIN_BUTTON_POSITION = (180, 20)

TERRAIN_BUTTON_SIZE = (220, 40)

TERRAIN_COLORS = {
    "plains": (126, 163, 88), "hills": (177, 155, 64), "desert": (194, 124, 58),
    "forest": (80, 140, 80), "jungle": (35, 76, 47), "mountain": (119, 88, 64),
    "swamp": (160, 104, 132),
    "ocean": (25, 65, 115), "coastal_sea": (40, 100, 140), "inland_sea": (45, 90, 130), "lakes": (45, 115, 135),
    # not used due to color conflicting with canopy leaves: (65, 115, 57)
}

# Out of 255. All foliage is partly transparent, so units and trunks show faintly beneath it.
FOLIAGE_ALPHA = 200

FOLIAGE_SHADOW_ALPHA = 96  # Translucent darkness behind foliage, separate from opaque sight shadows.

FOLIAGE_COLOR = (25, 128, 0)  # Each tree's foliage is a circle of this green, lightened or darkened slightly.

FOLIAGE_GREEN_VARIATION = 14  # Most a tree's shade can lighten or darken the foliage's green channel.

FEATURE_COLORS = {
    "rock": ((39, 32, 30), (70, 58, 49), (107, 88, 68), (146, 121, 91)),
    "chasm": ((72, 47, 36), (40, 30, 30), (20, 22, 27)),
    "marsh": ((106, 81, 100), (76, 91, 83), (56, 73, 78)),
}

FEATURE_PIXEL_STEP = 4

FEATURE_OUTLINE_POINTS = 24

HILL_CONTOUR_HEIGHT = 25.0

HILL_CONTOUR_SHADE = 25

HILL_BASE_SHADE = -30

OFF_FIELD_COLOR = (24, 30, 22)  # Outside the battlefield when zoomed out past its edges.

OUTLINE_COLOR = (22, 30, 22)

MAX_FRAME_SECONDS = 0.25

DRAG_THRESHOLD = 6

GENERATION_SLIDER_POSITION = (c.SCREEN_WIDTH - 270, 48)

GENERATION_SLIDER_WIDTH = 240

GENERATION_BUTTON_SIZE = (100, 40)

GENERATION_BUTTON_POSITION = (GENERATION_SLIDER_POSITION[0] - GENERATION_BUTTON_SIZE[0] - 20, 25)

SIMULATE_BUTTON_SIZE = (100, 40)

SIMULATE_BUTTON_POSITION = (GENERATION_BUTTON_POSITION[0] - SIMULATE_BUTTON_SIZE[0] - 10, 25)

FORECAST_CENTER_Y = 650  # Edit Battle's normal-game forecast line, below the friendly roster.

PREVIEW_START_POSITION = ("centered", 625)

PREVIEW_START_SIZE = (220, 50)

PREVIEW_RETREAT_SIZE = (160, 50)

PREVIEW_RETREAT_GAP = 20  # Between Start and Retreat.

# Settings and Music open over a preview or a running battle, along the top right edge.
OVERLAY_BUTTON_SIZE = (40, 40)

OVERLAY_ICON_SIZE = (28, 28)

OVERLAY_BUTTON_GAP = 10

OVERLAY_BUTTON_TOP = 20

SCREEN_EDGE_MARGIN = 20

PAUSE_BUTTON_SIZE = (130, 40)

BATTLE_STATUS_SIDE_OFFSET = 170

BATTLE_STATUS_Y = 103

KILL_FEED_TOP = OVERLAY_BUTTON_TOP + OVERLAY_BUTTON_SIZE[1] + 10

KILL_FEED_VISIBLE_ROWS = 6

KILL_FEED_ROW_HEIGHT = 26

KILL_FEED_INSET = 8

KILL_FEED_ICON_SIZE = (40, 22)

KILL_FEED_DIVISION_COLOR = (255, 155, 65)

KILL_FEED_FLAG_SIZE = (18, 12)

KILL_FEED_CAUSE_WIDTH = 36

KILL_FEED_SCROLLBAR_WIDTH = 10

KILL_FEED_SCROLLBAR_GAP = 4

KILL_FEED_ACTOR_WIDTH = KILL_FEED_FLAG_SIZE[0] + 6 + KILL_FEED_ICON_SIZE[0]

KILL_FEED_WIDTH = (2 * KILL_FEED_ACTOR_WIDTH + KILL_FEED_CAUSE_WIDTH + 2 * KILL_FEED_INSET
                   + KILL_FEED_SCROLLBAR_WIDTH + KILL_FEED_SCROLLBAR_GAP)

KILL_FEED_HEIGHT = KILL_FEED_VISIBLE_ROWS * KILL_FEED_ROW_HEIGHT + 2 * KILL_FEED_INSET

# Preview entry animation: edit these durations in seconds, then restart the game.
# Slide durations must be positive; the hold can be zero.
PREVIEW_SLIDE_IN_SECONDS = 0.2

PREVIEW_HOLD_SECONDS = 0.5

PREVIEW_SLIDE_OUT_SECONDS = 0.2

# Independent of Messages so the battle bars can be restyled separately.
PREVIEW_BAR_COLOR = (46, 56, 72)

PREVIEW_BAR_BORDER = (13, 17, 24)

PREVIEW_BAR_GRADIENT_STRENGTH = 0.5

PLAYER_COLOR = (255, 225, 95)

# Body (width, height) in pixels at scale 1.0, before the barrel line.
UNIT_SHAPE_SIZES = {shape: body[:2] for shape, body in c.TACTICAL_BODIES.items()}

TOUCH_PAD_SIZE = 120

TOUCH_PAD_MARGIN = 24

TOUCH_PAD_BOTTOM = 176

TOUCH_DEAD_ZONE = 0.18

TOUCH_AIM_DISTANCE = 600.0

TOUCH_WEAPON_SIZE = (94, 38)

TOUCH_WEAPON_GAP = 6

TOUCH_WEAPON_MODES = ("Primary", "Secondary", "Both")

ROUNDED_SHAPES = frozenset(("armored_car", "motorized"))

UNARMED_SHAPES = frozenset(("motorized", "mechanized", "ifv"))  # Drawn without the gun line.

ROUNDED_CORNER_RADIUS = 6

SPRITE_ANGLE_STEP = 4  # Degrees between the cached rotations of each battlefield shape.

INFANTRY_GUN_SIDE_OFFSET = 0.0  # Share of body height toward the unit's right shoulder. 0.25 was the original value it was set to.

# Each family selects a chassis and a weapon image independently.
BATTLE_ART_FAMILIES = {
    "Armored Car": ("Armored Car", "Armored Car"),
    "WW1 Armored Car": ("Armored Car", "Armored Car"),
    "WW1 Tank": ("WW1", "WW1"),
    "Light Tank": ("Light", "Light"), "Medium Tank": ("Medium", "Medium"),
    "Heavy Tank": ("Heavy", "Heavy"), "Main Battle Tank": ("MBT", "MBT"),
    "Super Heavy Tank": ("Super Heavy", "Super Heavy"),
    "Infantry Type": ("Infantry", "Infantry Gun"),
    "Cavalry": ("Cavalry", "Infantry Gun"),
    "Militia": ("Militia", "Infantry Gun"),
    "Motorized Infantry Type": ("Motorized Infantry", None),
    "Mechanized Infantry Type": ("Mechanized Infantry", None),
    "Infantry Fighting Vehicle Type": ("IFV", None),
}

BATTLE_ART_DIR = os.path.join(c.ASSETS_ROOT_DIR, "battles")

TERRAIN_ART_DIR = os.path.join(BATTLE_ART_DIR, "terrain")  # "Trunk N.png" draws each trunk size.

DEAD_COLOR = (53, 65, 44)

SHOT_COLOR = (250, 232, 150)

SHOT_WIDTH = 2

TANK_SHOT_COLOR = (255, 110, 0)

TANK_SHOT_WIDTH = 5

ARTILLERY_SHOT_COLOR = (255, 205, 105)

ARTILLERY_SHADOW_COLOR = (18, 40, 65)

TORPEDO_COLOR = (185, 195, 190)

TORPEDO_WAKE_COLOR = (115, 180, 200)

SPLASH_COLOR = (170, 220, 240)

SHELL_HEIGHT_DRAW_SCALE = 0.3

SUBMARINE_ALPHA = 128  # Half opacity: submarines read as underwater.

EDIT_ICON_SIZE = (CARD_LEFT_WIDTH, CARD_BAR_TOP - CARD_ICON_BAR_GAP - EDIT_ICON_TOP)

PREVIEW_CARD_ICON_SIZE = (CARD_LEFT_WIDTH, CARD_BAR_TOP - CARD_ICON_BAR_GAP - PREVIEW_ICON_TOP)

RIFLE_SHOT_SOUNDS = ("rifle_shot_1", "rifle_shot_2", "rifle_shot_3")

TANK_SHOT_SOUNDS = ("tank_shot_1", "tank_shot_2", "tank_shot_3")

FLESH_HIT_SOUNDS = ("flesh_wound_1", "flesh_wound_2", "flesh_wound_3")

RICOCHET_SOUNDS = ("bullet_ricochet_1", "bullet_ricochet_2", "bullet_ricochet_3", "bullet_ricochet_4")

RICOCHET_MAX_HEALTH_SHARE = 0.01

SHOT_TAIL = 8  # Pixels behind a shot's head.

RANGE_COLOR = (255, 225, 95)

AIM_LINE_COLOR = (255, 245, 200)

CONE_ARC_STEP = math.radians(3)  # Spacing of the points that draw the cone's curved edge.

PLAYER_RING_RADIUS = 18

RELOAD_RING_RADIUS = 22

RELOAD_COLOR = (255, 245, 200)

CONTROL_STATS_SIZE = (244, 138)  # Fixed space for both weapon cooldowns.

CONTROL_STATS_INSET = 8

CONTROL_STATS_TEXT_PADDING = 8

CONTROL_STATS_ROW_HEIGHT = 26

CONTROL_STATS_COLOR = (46, 56, 72)

CONTROL_STATS_BORDER = (13, 17, 24)

CONTROL_STATS_TEXT_BACKGROUND = (0, 0, 0)

ARROW_STRETCH = 26  # Extra arrow length at top speed.

CONTROL_KEYS = frozenset((pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d))
