"""Edit Battle, read-only Preview Battle, and optional player-controlled combat."""

import math
import os
import random
from collections import deque
from functools import lru_cache
from itertools import islice

import pygame

import data.constants as c
from data import queries
from data.io import starting_defaults
from map_logic import custom_battle as combat
from map_logic import battle_terrain
from ui import dialogs
from ui.dialogs import pickers
from ui.navigation import screen_runner
from ui.navigation.modal_screen import ModalScreen
from ui.navigation.screen import Screen
from ui.rendering import symbol_loader
from ui.rendering.font_manager import fonts
from ui.widgets import ui_elements
from ui import sound_effects
from ui.widgets import flag_icons
from ui.widgets.text_utils import fit_text, wrap_text
from ui.widgets.ui_elements import Button, Slider
from screens.setup import player_setup


PANEL_X = 60
ROSTER_TOP = 56
PANEL_WIDTH = 1160
PANEL_TOPS = (365, 120)  # Friendly and enemy rosters retain their separate areas.
CARD_SIZE = (158, 148)
CARD_GAP = 12
CONTROLLED_CARD_BRIGHTNESS = 100
TITLE_HELP_GAP = 12
PREVIEW_CARD_ICON_SIZE = (96, 60)
PREVIEW_ICON_CENTER_Y = 40
# Health bar rows: preview puts the bar under the icon; editing puts it at the card bottom.
PREVIEW_BAR_TOP = 80
EDIT_BAR_TOP = 124
CARD_BAR_HEIGHT = 14
CARD_BAR_GRAB_PAD = 6  # Extra pixels above and below the bar that still grab it in editing.
CARD_ROW_INSET = 8
CARD_BAR_FLAG_GAP = 6
CARD_BAR_FLAG_SIZE = (24, 16)
PREVIEW_STATS_TOP = 108
HEALTH_BAR_FULL_COLOR = (105, 215, 85)
HEALTH_BAR_HALF_COLOR = (235, 205, 60)  # Reached at half health.
HEALTH_BAR_EMPTY_COLOR = (215, 60, 50)  # Reached at zero health; the fill blends between the three colors.
HEALTH_BAR_SHADE = 30  # Brightness step between the light, middle, and dark bands of the fill.
HEALTH_BAR_BANDS = 3
PANEL_BOTTOM_SPACE = 32  # Below the cards: scrollbar row and margin.
PANEL_HEIGHT = ROSTER_TOP + CARD_SIZE[1] + PANEL_BOTTOM_SPACE
CARD_STATS_TOP = 96
CARD_STAT_ICON_SIZE = 14
BATTLE_FLAG_SIZE = (14, 9)
BATTLE_FLAG_GAP = 3
MIXED_LABEL = "Mixed"
CARD_EDIT_SIZE = 24
CARD_EDIT_INSET = 6
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
DEATH_EXPLOSION_CIRCLE_COLOR = (255, 180, 60)
DEATH_EXPLOSION_CIRCLE_ALPHA = 180
DEATH_EXPLOSION_COLORS = ((255, 240, 150), (255, 160, 45), (205, 65, 30), (75, 70, 65))
DEATH_EXPLOSION_OFFSETS = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))

EDIT_BATTLE_HELP_TEXT = (
    "Build both armies, choose their deployment order, and optionally choose a unit to control. Custom battles do not change your campaign.\n\n"
    "Add Friendly and Add Enemy open the unit picker. Choose units to add them; Cancel closes the picker and keeps your additions. Select a card and choose Remove to remove that unit. Clear All empties that army.\n\n"
    "Drag cards within either army to reorder deployment. The leftmost card deploys in the front rank, closest to the enemy. Scroll long rosters with the mouse wheel, scrollbar, or by dragging the roster background.\n\n"
    "A card's gear button opens Unit Settings for nationality and starting HP. You can also drag along the card's health bar to change starting HP.\n\n"
    "To select several units, start in empty roster panel space outside the card area and drag a square across the cards. Every selected card gets a gold outline. The gear button on any selected card opens Group Settings for all selected units; dragging a selected card's health bar changes the group's starting HP. Mixed means the selected units have different values. Click empty space or enter preview to clear the selection.\n\n"
    "Select a friendly card and choose Control to command that division's middle sub-unit during the battle. The controlled division's button is lighter blue and has a yellow arrow. Release Control lets both armies fight automatically.\n\n"
    "Random replaces both armies. Year limits the units Random can choose; manual unit selection is unrestricted by Year. The terrain button chooses the custom battlefield's terrain.\n\n"
    "The normal-game forecast estimates how these armies would fight under the strategic combat rules. The tactical battle can have a different result.\n\n"
    "Both armies need units before Simulate becomes available. Simulate opens Preview Battle; combat starts only after Start in preview. Exit returns to the menu."
)
PREVIEW_BATTLE_HELP_TEXT = (
    "Here you can review the armies before combat. The battle is paused here, so units do not move or fire.\n\n"
    "Drag friendly cards to change deployment order. The leftmost card deploys in the front rank, closest to the enemy.\n\n"
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

_BODY_SPRITES = {}
_ROTATED_SPRITES = {}
_BATTLE_ART = {}
_TRUNK_ART = {}


@lru_cache(maxsize=256)
def _health_fill_surface(size, color):
    """Cache dithered health shading by fill dimensions and displayed color."""
    surface = pygame.Surface(size)
    # Light, middle, and dark bands; a checkerboard of the neighboring shade softens each edge.
    shades = [tuple(max(0, min(255, channel + HEALTH_BAR_SHADE * (1 - band))) for channel in color) for band in range(HEALTH_BAR_BANDS)]
    width, height = size
    for row in range(height):
        band = row * HEALTH_BAR_BANDS // height
        first = band > 0 and (row - 1) * HEALTH_BAR_BANDS // height < band
        last = band < HEALTH_BAR_BANDS - 1 and (row + 1) * HEALTH_BAR_BANDS // height > band
        for column in range(width):
            shade = band
            if (column + row) % 2 == 0:
                shade += 1 if last else -1 if first else 0
            surface.set_at((column, row), shades[shade])
    return surface


def _draw_health_fill(surface, fill, ratio):
    if fill.width <= 0 or fill.height <= 0:
        return
    if ratio >= 0.5:
        low, high, blend = HEALTH_BAR_HALF_COLOR, HEALTH_BAR_FULL_COLOR, (ratio - 0.5) * 2
    else:
        low, high, blend = HEALTH_BAR_EMPTY_COLOR, HEALTH_BAR_HALF_COLOR, ratio * 2
    color = tuple(round(a + (b - a) * blend) for a, b in zip(low, high))
    surface.blit(_health_fill_surface(fill.size, color), fill)


def _trunk_art(size):
    """The unscaled "Trunk" image of one size, loaded once."""
    if size not in _TRUNK_ART:
        _TRUNK_ART[size] = pygame.image.load(os.path.join(TERRAIN_ART_DIR, f"Trunk {size}.png")).convert_alpha()
    return _TRUNK_ART[size]


def _load_battle_art(artwork):
    """Load the chassis and optional weapon once, before the battlefield starts drawing."""
    if artwork not in _BATTLE_ART:
        chassis = pygame.image.load(os.path.join(BATTLE_ART_DIR, "chassis", artwork[0] + ".png")).convert_alpha()
        centered = None
        if artwork[1] is not None:
            turret = pygame.image.load(os.path.join(BATTLE_ART_DIR, "turret", artwork[1] + ".png")).convert_alpha()
            # Weapons point right, with their base in the leftmost square of the image.
            # Pad the barrel side symmetrically so rotation keeps the base on the body center.
            pivot = turret.get_height() // 2
            centered = pygame.Surface((2 * (turret.get_width() - pivot), turret.get_height()), pygame.SRCALPHA)
            centered.blit(turret, (centered.get_width() // 2 - pivot, 0))
        _BATTLE_ART[artwork] = chassis, centered
    return _BATTLE_ART[artwork]


def _battle_sprite(artwork, shape, part, color, scale):
    key = (artwork, shape, part, tuple(color), scale)
    if key not in _BODY_SPRITES:
        chassis, turret = _BATTLE_ART[artwork]
        width, height = UNIT_SHAPE_SIZES[shape]
        source = turret if part == "turret" else chassis
        if part == "turret":
            factor = width * scale / chassis.get_width()
            size = tuple(max(1, round(side * factor)) for side in source.get_size())
        else:
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
        _BODY_SPRITES[key] = pygame.transform.scale(symbol_loader.colorize_red_image(source, color), size)
    return _BODY_SPRITES[key]


def _unit_sprite(shape, color, scale, barrel):
    """An unrotated silhouette pointing right; cached because battles draw hundreds per frame."""
    key = (shape, tuple(color), scale, barrel)
    if key not in _BODY_SPRITES:
        width, height = UNIT_SHAPE_SIZES[shape]
        width, height = round(width * scale), round(height * scale)
        sprite = pygame.Surface((width + 12, max(height, 24)), pygame.SRCALPHA)
        body = pygame.Rect(2, (sprite.get_height() - height) // 2, width, height)
        if shape in {"infantry", "cavalry"}:
            pygame.draw.ellipse(sprite, OUTLINE_COLOR, body)
            pygame.draw.ellipse(sprite, color, body.inflate(-4, -4))
        else:
            radius = round(ROUNDED_CORNER_RADIUS * scale) if shape in ROUNDED_SHAPES else 0
            pygame.draw.rect(sprite, OUTLINE_COLOR, body, border_radius=radius)
            pygame.draw.rect(sprite, color, body.inflate(-4, -4), border_radius=max(0, radius - 2))
            if barrel and shape not in UNARMED_SHAPES:
                pygame.draw.line(sprite, OUTLINE_COLOR, body.center,
                                 (sprite.get_width() - 1, body.centery), max(2, round(3 * scale)))
        _BODY_SPRITES[key] = sprite
    return _BODY_SPRITES[key]


def clear_rotated_sprites():
    """Drop the cached rotations, e.g. when the battlefield zoom changes, so old scales do not pile up."""
    _ROTATED_SPRITES.clear()


def _draw_rotated_sprite(surface, sprite, key, center, angle):
    step = round(math.degrees(angle) / SPRITE_ANGLE_STEP) % (360 // SPRITE_ANGLE_STEP)
    key = (*key, step)
    rotated = _ROTATED_SPRITES.get(key)
    if rotated is None:
        rotated = pygame.transform.rotate(sprite, -step * SPRITE_ANGLE_STEP)
        _ROTATED_SPRITES[key] = rotated
    surface.blit(rotated, rotated.get_rect(center=center))


def draw_unit_shape(surface, shape, center, angle, color, *, scale=1.0, aim=None, artwork=None, recoil=0.0):
    """Draw battle artwork or geometric silhouettes in setup cards and on the field.

    With ``aim``, the turret or gun line follows ``aim`` independently of the hull.
    """
    if artwork is not None:
        for part, heading in (("chassis", angle), ("turret", angle if aim is None else aim)):
            if part == "turret" and artwork[1] is None:
                continue
            sprite = _battle_sprite(artwork, shape, part, color, scale)
            key = (artwork, shape, part, tuple(color), scale)
            part_center = center
            if part == "turret" and artwork[1] == "Infantry Gun":
                # The shoulder follows the body while the weapon turns independently to aim.
                offset = UNIT_SHAPE_SIZES[shape][1] * INFANTRY_GUN_SIDE_OFFSET * scale
                part_center = (center[0] - math.sin(angle) * offset,
                               center[1] + math.cos(angle) * offset)
            if part == "turret" and recoil:
                part_center = (part_center[0] - math.cos(heading) * recoil * scale,
                               part_center[1] - math.sin(heading) * recoil * scale)
            _draw_rotated_sprite(surface, sprite, key, part_center, heading)
        return
    key = (shape, tuple(color), scale, aim is None)
    _draw_rotated_sprite(surface, _unit_sprite(shape, color, scale, aim is None), key, center, angle)
    if aim is not None and shape not in UNARMED_SHAPES:
        # Same reach as the sprite's own gun line at full scale: half the body plus the sprite's margin.
        length = (UNIT_SHAPE_SIZES[shape][0] / 2 + 9 - recoil) * scale
        pygame.draw.line(surface, OUTLINE_COLOR, center,
                         (center[0] + math.cos(aim) * length, center[1] + math.sin(aim) * length),
                         max(1, round(3 * scale)))


def draw_player_arrow(surface, center, angle, stretch=0.0, scale=1.0):
    """Mark the controlled unit and point along its hull heading.

    ``stretch`` is the signed share of top speed: the arrow lengthens with speed and points back while reversing.
    ``scale`` follows the battlefield zoom.
    """
    if stretch < 0:
        angle += math.pi
    extra = abs(stretch) * ARROW_STRETCH
    forward = pygame.Vector2(math.cos(angle), math.sin(angle)) * scale
    sideways = pygame.Vector2(-forward.y, forward.x)
    origin = pygame.Vector2(center)
    if extra * scale >= 1:
        pygame.draw.line(surface, OUTLINE_COLOR, origin + forward * 19, origin + forward * (19 + extra), 4)
        pygame.draw.line(surface, PLAYER_COLOR, origin + forward * 19, origin + forward * (19 + extra), 2)
    head = origin + forward * extra
    points = [head + forward * 33, head + forward * 19 + sideways * 6,
              head + forward * 23, head + forward * 19 - sideways * 6]
    pygame.draw.polygon(surface, OUTLINE_COLOR, points)
    pygame.draw.polygon(surface, PLAYER_COLOR, points, 2)


class CampaignBattle:
    """The tactical-mode encounter a battle belongs to. The player's unit starts as friendly entry 0.

    Reordering the friendly army in preview reorders ``units`` the same way.
    """

    def __init__(self, map_screen, province, units, custom_rosters):
        self.map_screen = map_screen
        self.province = province
        self.units = units  # The campaign units in roster order: friendly army, then enemy army.
        self.unit = units[0]
        self.result_applied = False
        self.custom_rosters = custom_rosters  # The custom-battle armies to restore afterward.


class CustomBattleScreen(Screen):
    back_state = "MENU"
    title = "Edit Battle"
    title_y = 42

    def __init__(self):
        super().__init__()
        self.mode = "setup"
        self.controller = None
        self.library = {}
        self.country_data = {}
        self.nationalities = []
        self.generation_year = starting_defaults.get_starting_value("random_setup", "start_year")
        self.terrain = starting_defaults.get_starting_value("random_setup", "custom_battle_terrain")
        self.terrain_art = []
        self.canopy_art = []  # (tree, transparent foliage surface), drawn above units.
        self.terrain_art_key = None
        self.visibility_key = None
        self.visibility_outline = ()
        self.visibility_blockers = ()
        self.visibility_mask_key = None
        self.visibility_mask = None
        self.foliage_shadow_outline = ()
        self.foliage_shadow_mask = None
        self.visible_fighters = set()
        self.terrain_sprites = {}
        self.battle_seed = None
        self.random_candidates = []
        self.rosters = [[], []]
        self.selected = [None, None]
        # Roster indices chosen by a selection square; two or more entries per side.
        self.group = [[], []]
        self.campaign = None  # A CampaignBattle while a tactical-mode encounter is shown.
        self.choosing_retreat = False
        self.viewing_overlay = False  # Settings or Music is open over preview, battle, or results.
        self.bar_drag = None  # (side, index) of the card whose health bar is being dragged
        self.marquee = None  # [side, start position, current position] while dragging a square
        self.controlled_index = None
        self.held_keys = set()
        self.firing = False  # Left mouse held on the battlefield while controlling a sub-unit.
        self.secondary_firing = False
        self.touch_mode = False
        self.touch_pointers = {}  # pointer -> (drive/aim, last position)
        self.touch_weapon_mode = "Primary"
        self.touch_weapon_buttons = []
        self.camera = [0.0, 0.0]  # Battlefield coordinates at the screen's top-left corner.
        self.zoom_index = DEFAULT_ZOOM_INDEX
        self.pan_drag = None  # Last pointer position while dragging the battlefield.
        self.card_surfaces = {}
        self.unit_buttons = {}
        self.gear_icon = None
        self.roster_labels = []
        self.panes = []
        self.drag = None
        self.simulation = None
        self.last_tick = 0
        self.preview_intro_started = None
        self.preview_intro_stage = None
        self.status_key = None
        self.status_surfaces = []
        self.kill_feed = deque()
        self.death_explosions = []  # Destroyed sub-unit and animation age, in seconds.
        self.death_explosion_circle = None
        self.kill_feed_surface = None
        self.kill_feed_scroll = self.kill_feed_limit = 0
        self.kill_feed_dragging = False
        self.kill_feed_track = self.kill_feed_handle = None
        self.kill_feed_rect = pygame.Rect(c.SCREEN_WIDTH - SCREEN_EDGE_MARGIN - KILL_FEED_WIDTH,
                                          KILL_FEED_TOP, KILL_FEED_WIDTH, KILL_FEED_HEIGHT)
        self.kill_feed_content = self.kill_feed_rect.inflate(-2 * KILL_FEED_INSET, -2 * KILL_FEED_INSET)
        self.kill_feed_content.width -= KILL_FEED_SCROLLBAR_WIDTH + KILL_FEED_SCROLLBAR_GAP
        self.controlled_stats_key = None
        self.controlled_stats_surface = None
        self.forecast_key = None  # The armies the forecast line was calculated for.
        self.forecast_surface = None
        for side, top in enumerate(PANEL_TOPS):
            self.panes.append(pygame.Rect(PANEL_X + ROSTER_INSET, top + ROSTER_TOP,
                                          ROSTER_WIDTH, CARD_SIZE[1]))
            setattr(self, f"roster_{side}_scroll", 0)
            setattr(self, f"roster_{side}_limit", 0)
            setattr(self, f"roster_{side}_content", self.panes[side])
        self.refresh_ui()

    def on_enter(self, app, previous):
        self.controller = app
        request = getattr(previous, "tactical_battle_request", None)
        if request is not None:
            previous.tactical_battle_request = None
            self._enter_campaign(previous, *request)
            return
        if self.choosing_retreat:
            # Back from the retreat map: show the same preview again.
            self.choosing_retreat = False
            self.done = False
            self.next_state = None
            self.start_tactical_music()
            return
        if self.viewing_overlay:
            # Back from Settings or Music: preserve the current music, view, and simulation.
            # Only the clock restarts, so no combat time passes while the screen was open.
            self.viewing_overlay = False
            self.done = False
            self.next_state = None
            self.last_tick = pygame.time.get_ticks()
            self.refresh_ui()  # The Pause button must read Resume if opening the screen paused the battle.
            return
        if self.campaign is not None:
            self._end_campaign()
        self.stop_tactical_music()
        self.done = False
        self.next_state = None
        self.mode = "setup"
        self.preview_intro_started = None
        self.preview_intro_stage = None
        # Main-menu battles use the default library, never a loaded world's overrides.
        self.library = queries.get_unit_library()
        self.country_data = queries.get_country_data()
        self.gear_icon = symbol_loader.get_symbol(
            "Gear", zoom=1, fit_size=(CARD_EDIT_SIZE - 8, CARD_EDIT_SIZE - 8))
        self.nationalities = sorted(
            (country for country in self.country_data if queries.is_playable(country, self.country_data)),
            key=lambda country: queries.get_country_display_name(country, self.country_data))
        if not self.nationalities:
            raise ValueError("Custom battles need at least one playable country in countries_data.json.")
        self.unit_names = sorted(combat.land_unit_types(self.library), key=lambda name: (
            queries.get_unit_metadata(name, self.library)["family"],
            queries.get_unit_tier(name, self.library)))
        allowed = set(self.unit_names)
        self.rosters = [[unit for unit in roster if unit["type"] in allowed] for roster in self.rosters]
        self.selected = [None, None]
        self.group = [[], []]
        self.controlled_index = None
        self.held_keys.clear()
        self.card_surfaces.clear()
        self.simulation = None
        self.cancel_active_drags()
        self.random_candidates = combat.land_unit_types_for_year(self.library, self.generation_year)
        self.refresh_ui()

    def _enter_campaign(self, map_screen, province, friendly, enemy):
        """Open preview at once for a tactical player's encounter, controlling their unit."""
        self.done = False
        self.next_state = None
        self.campaign = CampaignBattle(map_screen, province, friendly + enemy, self.rosters)
        self.library = queries.get_unit_library(map_screen)
        self.country_data = map_screen.nation_data
        self.rosters = [combat.campaign_roster(friendly, self.library),
                        combat.campaign_roster(enemy, self.library)]
        self.selected = [None, None]
        self.group = [[], []]
        self.controlled_index = 0
        self.held_keys.clear()
        self.card_surfaces.clear()
        self.simulation = None
        self.mode = "setup"
        self.cancel_active_drags()
        for side in (0, 1):
            setattr(self, f"roster_{side}_scroll", 0)
        self.preview_battle()

    def _end_campaign(self):
        self.rosters = self.campaign.custom_rosters
        self.campaign = None
        self.choosing_retreat = False

    def retreat(self):
        """Custom battles return to editing; a tactical encounter picks a tile on the map."""
        if self.mode != "preview" or self.preview_intro_stage is not None:
            return
        if self.campaign is None:
            self.return_to_setup()
            return
        self.clear_controls()
        self.choosing_retreat = True
        self.go_to("TACTICAL_RETREAT")

    def open_overlay(self, state):
        """Open Settings or Music over preview, battle, or results; Back returns to the same view."""
        if self.mode not in {"preview", "battle", "result"} or self.preview_intro_stage is not None:
            return
        self.cancel_active_drags()
        self.clear_controls()
        if self.mode == "battle":
            self.simulation.paused = True  # Stays paused after Back until the player chooses Resume.
        self.viewing_overlay = True
        self.go_to(state)

    def finish_retreat(self):
        """The retreat order is given: the encounter is over."""
        self._end_campaign()

    def _apply_campaign_result(self):
        """A finished tactical encounter changes the campaign: damage stays and the dead are gone."""
        campaign = self.campaign
        if campaign is None or campaign.result_applied:
            return
        campaign.result_applied = True
        artillery = combat.campaign_artillery(campaign.unit, campaign.province,
                                              campaign.map_screen.nation_data, self.library)
        sides = combat.campaign_sides(campaign.unit, campaign.province, campaign.map_screen.nation_data)
        combat.apply_campaign_result(self.simulation, campaign.units, campaign.province, artillery, side_units=sides, player_unit=campaign.unit)
        player_setup.settle_tactical_tile(campaign.map_screen, campaign.province)

    def continue_campaign(self):
        """Leave the finished encounter. A destroyed tactical division sends the player to spectating."""
        if self.mode != "result" or self.campaign is None:
            return
        campaign = self.campaign
        died = campaign.unit["health"] <= 0
        self._end_campaign()
        if died:
            player_setup.lose_tactical_unit(campaign.map_screen, campaign.province)
        self.go_to("MAP")

    def get_title(self):
        if self.mode == "result":
            return "You Win" if self.simulation.winner == 0 else "You Lose"
        if self.mode == "preview":
            return "Preview Battle"
        return "Edit Battle" if self.mode == "setup" else "Actual Battle"

    def show_help(self):
        if self.mode not in {"setup", "preview"} or self.preview_intro_stage is not None:
            return
        self.cancel_active_drags()
        text = EDIT_BATTLE_HELP_TEXT if self.mode == "setup" else PREVIEW_BATTLE_HELP_TEXT + (PREVIEW_CAMPAIGN_HELP_TEXT if self.campaign is not None else PREVIEW_CUSTOM_HELP_TEXT)
        dialogs.show_info(f"{self.get_title()} Help", text)

    @property
    def reserved_keys(self):
        if (self.preview_intro_stage is None and self.mode in {"preview", "battle"}
                and self.simulation.controlled is not None):
            return CONTROL_KEYS
        return ()

    @staticmethod
    def _scroll_options(side):
        return dict(attr=f"roster_{side}_scroll", limit_attr=f"roster_{side}_limit",
                    track_attr=f"roster_{side}_track", handle_attr=f"roster_{side}_handle",
                    drag_attr=f"roster_{side}_dragging", content_rect_attr=f"roster_{side}_content",
                    axis="x")

    def refresh_ui(self):
        self.unit_buttons = {}
        self.elements = []
        self.help_button = None
        if self.mode in {"setup", "preview"}:
            title_width, title_height = fonts.get(self.title_preset).size(self.get_title())
            self.help_button = ui_elements.make_info_button(0, 0, self.show_help)
            self.help_button.rect.midleft = (c.SCREEN_WIDTH // 2 + title_width - title_width // 2 + TITLE_HELP_GAP, self.title_y + title_height // 2)
            self.elements.append(self.help_button)
        self.battle_artwork = {}
        for name in dict.fromkeys(unit["type"] for roster in self.rosters for unit in roster):
            family = queries.get_unit_metadata(name, self.library)["family"]
            artwork = BATTLE_ART_FAMILIES.get(family)
            self.battle_artwork[name] = artwork
            if artwork is not None:
                _load_battle_art(artwork)
        if self.mode == "setup" or (self.mode in {"battle", "result"} and self.campaign is None):
            self.elements.append(Button(20, 20, "small", "red", "Exit", self.leave,
                                        sound_kind="back"))
        if self.mode in {"preview", "battle", "result"}:
            # Battle and results keep the same Pause, Settings, and Music positions.
            right = c.SCREEN_WIDTH - SCREEN_EDGE_MARGIN
            if self.mode in {"battle", "result"}:
                right -= PAUSE_BUTTON_SIZE[0] + OVERLAY_BUTTON_GAP
            for symbol, state, color, sound in (("Music", "MUSIC_PLAYER", "blue", "open_music"),
                                                ("Gear", "SETTINGS", "grey", "open_settings")):
                right -= OVERLAY_BUTTON_SIZE[0]
                icon = symbol_loader.get_symbol(symbol, zoom=1, fit_size=OVERLAY_ICON_SIZE)
                self.elements.append(Button(right, OVERLAY_BUTTON_TOP, OVERLAY_BUTTON_SIZE, color, "",
                                            lambda state=state: self.open_overlay(state),
                                            image=icon, show_text=False, sound_kind=sound))
                right -= OVERLAY_BUTTON_GAP
        if self.mode in {"battle", "result"}:
            self.pause_button = Button(c.SCREEN_WIDTH - SCREEN_EDGE_MARGIN - PAUSE_BUTTON_SIZE[0], OVERLAY_BUTTON_TOP,
                                       PAUSE_BUTTON_SIZE, "yellow",
                                       "Resume" if self.mode == "battle" and self.simulation.paused else "Pause",
                                       self.toggle_pause)
            self.pause_button.apply_state(enabled=self.mode == "battle", color="yellow")
            self.elements.append(self.pause_button)
        if self.mode in {"setup", "preview"}:
            self.roster_labels = []
            for side, top in enumerate(PANEL_TOPS):
                roster = self.rosters[side]
                name = "Friendly Units" if side == 0 else "Enemy Units"
                self.roster_labels.append(fonts.get("heading2").render(
                    f"{name} ({len(roster)})", True, TEAM_COLORS[side]))
                for index, unit in enumerate(roster):
                    self._cache_card(side, unit)
                    if self.mode == "setup":
                        self.unit_buttons[side, index] = Button(
                            0, 0, (CARD_EDIT_SIZE, CARD_EDIT_SIZE), "grey", "",
                            lambda side=side, unit=unit: self.edit_unit(side, unit),
                            image=self.gear_icon, show_text=False,
                            sound_kind="open_settings")
                limit = min(0, ROSTER_WIDTH - len(roster) * (CARD_SIZE[0] + CARD_GAP) + CARD_GAP)
                setattr(self, f"roster_{side}_limit", limit)
                offset = max(limit, min(0, getattr(self, f"roster_{side}_scroll")))
                setattr(self, f"roster_{side}_scroll", offset)
                if self.mode == "preview":
                    continue
                x = PANEL_X + PANEL_WIDTH - BUTTON_WIDTH - ROSTER_INSET
                clear = Button(x, top + CLEAR_ALL_OFFSET_Y, (BUTTON_WIDTH, CLEAR_ALL_HEIGHT), "red", "Clear All", lambda side=side: self.clear_army(side), font_size=18)
                clear.apply_state(enabled=bool(roster), color="red")
                add = Button(x, top + 70, (BUTTON_WIDTH, 42), "blue" if side == 0 else "red",
                             "Add Friendly" if side == 0 else "Add Enemy",
                             lambda side=side: self.open_picker(side), font_size=20)
                add.apply_state(enabled=len(roster) < c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE,
                                color="blue" if side == 0 else "red")
                remove = Button(x, top + 128, (BUTTON_WIDTH, 42), "grey", "Remove",
                                lambda side=side: self.remove_unit(side), font_size=20)
                remove.apply_state(enabled=self.selected[side] is not None, color="red")
                self.elements.extend((clear, add, remove))
                if side == 0:
                    controlling = self.controlled_index is not None and self.controlled_index == self.selected[0]
                    control = Button(x, top + 178, (BUTTON_WIDTH, 32), "yellow",
                                     "Release Control" if controlling else "Control",
                                     self.toggle_control, font_size=18)
                    control.apply_state(enabled=self.selected[0] is not None,
                                        color="yellow" if controlling else "green")
                    self.elements.append(control)
            if self.mode == "preview":
                start = Button(*PREVIEW_START_POSITION, PREVIEW_START_SIZE,
                               "green", "Start", self.start_battle)
                retreat = Button(start.rect.right + PREVIEW_RETREAT_GAP, start.rect.y,
                                 PREVIEW_RETREAT_SIZE, "red", "Retreat", self.retreat,
                                 sound_kind="back")
                self.elements.extend((start, retreat))
                return
            self._refresh_forecast()
            simulate = Button(*SIMULATE_BUTTON_POSITION, SIMULATE_BUTTON_SIZE, "green", "Simulate",
                              self.preview_battle, font_size=18, sound_kind=None)
            simulate.apply_state(enabled=all(self.rosters), color="green")
            self.elements.append(simulate)
            self.generate_button = Button(
                *GENERATION_BUTTON_POSITION, GENERATION_BUTTON_SIZE, "purple", "Random",
                self.generate_armies, font_size=20)
            self.generate_button.apply_state(enabled=bool(self.random_candidates), color="purple")
            self.year_slider = Slider(
                *GENERATION_SLIDER_POSITION, GENERATION_SLIDER_WIDTH,
                f"Year: {self.generation_year}", self.generation_year - c.START_YEAR,
                self.update_generation_year, visual_max=c.END_YEAR - c.START_YEAR,
                allowed_max=c.END_YEAR - c.START_YEAR)
            self.elements.extend((self.generate_button, self.year_slider))
            self.elements.append(Button(*TERRAIN_BUTTON_POSITION, TERRAIN_BUTTON_SIZE, "grey",
                                        battle_terrain.TERRAIN_NAMES[self.terrain], self.choose_terrain,
                                        font_size=20))
        elif self.mode == "battle":
            self.touch_weapon_buttons = []
            if self.touch_mode and self.simulation.controlled is not None and self.simulation.controlled.alive and self.simulation.controlled.weapon(1) is not None:
                width, height = TOUCH_WEAPON_SIZE
                left = c.SCREEN_WIDTH - TOUCH_PAD_MARGIN - (width * 3 + TOUCH_WEAPON_GAP * 2)
                top = self._touch_pad_rect("aim").top - height - TOUCH_WEAPON_GAP
                for index, mode in enumerate(TOUCH_WEAPON_MODES):
                    button = Button(left + index * (width + TOUCH_WEAPON_GAP), top, TOUCH_WEAPON_SIZE,
                                    "yellow" if mode == self.touch_weapon_mode else "grey", mode,
                                    lambda mode=mode: self._select_touch_weapon(mode), font_size=16)
                    button.apply_state(enabled=self._driving(),
                                       color="yellow" if mode == self.touch_weapon_mode else "grey")
                    self.touch_weapon_buttons.append(button)
                    self.elements.append(button)
        elif self.campaign is not None:
            self.elements.append(Button("centered", 370, (220, 50), "green", "Continue",
                                        self.continue_campaign))
        else:
            self.elements.extend((
                Button("centered", 370, (220, 50), "green", "Run Again", self.preview_battle,
                       sound_kind=None),
                Button("centered", 440, (220, 50), "blue", "Edit Armies", self.return_to_setup)))

    def _refresh_forecast(self):
        """Forecast how the armies would fare in the normal game, only when their types, order, or health change."""
        key = tuple(tuple((unit["type"], unit["health"]) for unit in roster) for roster in self.rosters)
        if key == self.forecast_key:
            return
        self.forecast_key = key
        if not all(self.rosters):
            self.forecast_surface = None
            return
        winner, turns = combat.normal_game_forecast(*self.rosters)
        if turns is None:
            text, color = "Normal game: no clear winner", c.UI_TEXT_MUTED
        else:
            span = f"{turns} turn" if turns == 1 else f"{turns} turns"
            if winner is None:
                text, color = f"Normal game: both armies destroyed in {span}", c.UI_TEXT_MUTED
            else:
                army = "Friendly" if winner == 0 else "Enemy"
                text, color = f"Normal game: {army} army wins in {span}", TEAM_COLORS[winner]
        self.forecast_surface = fonts.get("normal").render(text, True, color)

    def update_generation_year(self, value):
        if self.mode != "setup":
            return
        year = max(c.START_YEAR, min(c.END_YEAR, c.START_YEAR + round(value)))
        if year != self.generation_year:
            self.generation_year = year
            self.random_candidates = combat.land_unit_types_for_year(self.library, year)
            self.generate_button.apply_state(enabled=bool(self.random_candidates), color="purple")
        # Keep the current slider alive while dragging instead of rebuilding controls.
        self.year_slider.text = f"Year: {self.generation_year}"
        self.year_slider.value = self.generation_year - c.START_YEAR
        self.year_slider.handle_rect.centerx = self.year_slider.rect.left + round(
            self.year_slider.rect.width * self.year_slider.value / self.year_slider.visual_max)

    def generate_armies(self):
        if self.mode != "setup" or not self.random_candidates:
            return
        self.cancel_active_drags()
        self.rosters = [[self._new_unit(side, name, random.choice(self.nationalities)) for name in roster]
                        for side, roster in enumerate(combat.random_armies(self.random_candidates))]
        self.selected = [None, None]
        self.group = [[], []]
        self.controlled_index = None
        for side in (0, 1):
            setattr(self, f"roster_{side}_scroll", 0)
        self.refresh_ui()

    def open_picker(self, side):
        if self.mode != "setup":
            return
        self.cancel_active_drags()
        pickers.open_listbox_selector(
            self, "Add Friendly Units" if side == 0 else "Add Enemy Units", "",
            queries.unit_picker_items(self.unit_names, self.library),
            lambda name: self.add_unit(side, name), close_on_select=False, background_draw=self.draw,
            is_enabled=lambda item: len(self.rosters[side]) < c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE)

    def choose_terrain(self):
        if self.mode != "setup" or self.campaign is not None:
            return
        self.cancel_active_drags()
        pickers.open_listbox_selector(self, "Battle Terrain", "",
                                     [(label, key) for key, label in battle_terrain.TERRAIN_NAMES.items()],
                                     self.set_terrain)

    def set_terrain(self, terrain):
        if self.mode != "setup" or self.campaign is not None or terrain not in battle_terrain.TERRAIN_NAMES:
            return
        self.terrain = terrain
        self.refresh_ui()

    def add_unit(self, side, name):
        if self.mode != "setup" or name not in self.unit_names:
            return
        roster = self.rosters[side]
        if len(roster) >= c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE:
            return
        roster.append(self._new_unit(side, name))
        self.selected[side] = len(roster) - 1
        self.refresh_ui()
        setattr(self, f"roster_{side}_scroll", getattr(self, f"roster_{side}_limit"))

    def _new_unit(self, side, name, country=None):
        if country is None:
            country = self.nationalities[min(side, len(self.nationalities) - 1)]
        return queries.create_unit_dict(name, country, self.library)

    def edit_unit(self, side, unit):
        if self.mode != "setup" or not any(entry is unit for entry in self.rosters[side]):
            return
        self.cancel_active_drags()
        screen_runner._run_pygame_sub_screen(
            self, CustomBattleUnitEditor(self, side, self._units_to_edit(side, unit)))

    def _units_to_edit(self, side, unit):
        """A card in a selected group edits the whole group; any other card edits itself."""
        grouped = [self.rosters[side][index] for index in self.group[side]]
        return grouped if any(entry is unit for entry in grouped) else [unit]

    def set_unit_options(self, side, units, *, owner=None, health_percent=None):
        """Set nationality and starting HP (a percent of each unit's maximum HP) for roster entries."""
        if (self.mode != "setup" or not units
                or not all(any(entry is unit for entry in self.rosters[side]) for unit in units)):
            return False
        if owner is not None and owner not in self.nationalities:
            return False
        if health_percent is not None and not (
                isinstance(health_percent, (int, float)) and not isinstance(health_percent, bool)
                and 0 < health_percent <= 100):
            return False
        for unit in units:
            if owner is not None:
                unit["owner"] = owner
            if health_percent is not None:
                unit["health"] = unit["max_health"] * health_percent / 100
        self.card_surfaces.clear()
        self.refresh_ui()
        return True

    def remove_unit(self, side):
        index = self.selected[side]
        if self.mode != "setup" or index is None or not 0 <= index < len(self.rosters[side]):
            return
        self.rosters[side].pop(index)
        self.group[side] = []
        if side == 0 and self.controlled_index is not None:
            if self.controlled_index == index:
                self.controlled_index = None
            elif self.controlled_index > index:
                self.controlled_index -= 1
        self.selected[side] = None
        self.refresh_ui()

    def clear_army(self, side):
        if self.mode != "setup" or side not in (0, 1):
            return
        self.cancel_active_drags()
        self.rosters[side].clear()
        self.selected[side] = None
        self.group[side] = []
        if side == 0:
            self.controlled_index = None
        setattr(self, f"roster_{side}_scroll", 0)
        self.refresh_ui()

    def toggle_control(self):
        index = self.selected[0]
        if self.mode != "setup" or index is None or not 0 <= index < len(self.rosters[0]):
            return
        self.controlled_index = None if self.controlled_index == index else index
        self.refresh_ui()

    def preview_battle(self):
        if self.mode not in {"setup", "result"} or not all(self.rosters):
            return
        self.cancel_active_drags()
        self._clear_roster_selection()
        self.battle_seed = random.getrandbits(64)
        self._build_simulation()
        self.clear_controls()
        self.mode = "preview"
        # Start the clock on the first draw so entry always includes a black frame.
        self.preview_intro_started = None
        self.preview_intro_stage = 0
        sound_effects.play_ui_sound("open_music")
        self.start_tactical_music()
        self.status_key = None
        self._refresh_status()
        self.refresh_ui()

    def start_tactical_music(self):
        """Play the tactical songs for the prepared battle: tank songs when the enemy has a tank."""
        if self.controller is not None:
            self.controller.set_tactical_battle_music(True, tanks=self.simulation.enemy_has_tanks())

    def stop_tactical_music(self):
        """Return to normal playlist music at full volume."""
        if self.controller is not None:
            self.controller.set_tactical_battle_music(False)
            self.controller.set_music_volume_scale(1.0)

    def zoom_volume_share(self):
        """Full volume at the default zoom and closer; zooming out lowers it in proportion to the zoom."""
        return min(1.0, self.zoom / ZOOM_LEVELS[DEFAULT_ZOOM_INDEX])

    def battle_sfx_volume_share(self):
        """Apply the editable battle SFX multiplier before the shared zoom reduction."""
        return BATTLE_SFX_VOLUME * self.zoom_volume_share()

    def update_battle_music_volume(self):
        """Lower music in actual battle: BATTLE_MUSIC_VOLUME, then quieter the further the view zooms out."""
        if self.controller is not None and self.mode == "battle":
            self.controller.set_music_volume_scale(BATTLE_MUSIC_VOLUME * self.zoom_volume_share())

    def _build_simulation(self):
        """Deploy the armies, paused, as preview shows them."""
        self.kill_feed.clear()
        self.death_explosions.clear()
        self.kill_feed_scroll = 0
        self.kill_feed_dragging = False
        self._refresh_kill_feed()
        self.simulation = combat.BattleSimulation(self.library, *self.rosters,
                                                  controlled_index=self.controlled_index,
                                                  seed=self.battle_seed,
                                                  terrain=self.campaign.province["terrain"] if self.campaign else self.terrain,
                                                  on_shot=self._play_shot_sound,
                                                  on_hit=self._play_hit_sound,
                                                  on_kill=self._record_kill)
        self.simulation.paused = True
        self.terrain_sprites.clear()
        self._cache_terrain_art()

    def _record_kill(self, source, target, cause):
        """Update the recent kills when a battlefield sub-unit dies."""
        if target.shape not in combat.FOOT_SHAPES:
            self.death_explosions.append((target, 0.0))
            sound_effects.play_ui_sound("tank_explosion", volume_scale=self.battle_sfx_volume_share())
        if self.kill_feed_scroll < 0:
            self.kill_feed_scroll -= KILL_FEED_ROW_HEIGHT
        self.kill_feed.appendleft((source, target, cause))
        self._refresh_kill_feed()

    @staticmethod
    def _kill_feed_scroll_options():
        return dict(attr="kill_feed_scroll", limit_attr="kill_feed_limit", track_attr="kill_feed_track",
                    handle_attr="kill_feed_handle", drag_attr="kill_feed_dragging",
                    content_rect_attr="kill_feed_content")

    def _refresh_kill_feed(self):
        """Cache the fixed-size panel, including when no kills have occurred."""
        view_height = self.kill_feed_content.height
        self.kill_feed_limit = min(0, view_height - len(self.kill_feed) * KILL_FEED_ROW_HEIGHT)
        self.kill_feed_scroll = max(self.kill_feed_limit, min(0, self.kill_feed_scroll))
        panel = pygame.Surface((KILL_FEED_WIDTH, KILL_FEED_HEIGHT), pygame.SRCALPHA)
        ui_elements.draw_pixel_panel(panel, panel.get_rect(), CONTROL_STATS_COLOR, CONTROL_STATS_BORDER)
        content = self.kill_feed_content.move(-self.kill_feed_rect.x, -self.kill_feed_rect.y)
        panel.set_clip(content)
        actor_width = KILL_FEED_ACTOR_WIDTH
        font = fonts.get("tiny")
        # Scrollbar positions can be fractional; deque slicing needs an integer row index.
        first = math.floor(-self.kill_feed_scroll / KILL_FEED_ROW_HEIGHT)
        visible = islice(self.kill_feed, first, first + KILL_FEED_VISIBLE_ROWS + 1)
        controlled = self.simulation.controlled if self.simulation is not None else None
        for row, (killer, victim, kind) in enumerate(visible, first):
            top = KILL_FEED_INSET + row * KILL_FEED_ROW_HEIGHT + self.kill_feed_scroll
            for index, fighter in enumerate((killer, victim)):
                x = KILL_FEED_INSET + index * (actor_width + KILL_FEED_CAUSE_WIDTH)
                x = flag_icons.draw_flag_centered(panel, fighter.data["owner"], self.country_data,
                                                  x, top, KILL_FEED_ROW_HEIGHT, KILL_FEED_FLAG_SIZE)
                center = (x + KILL_FEED_ICON_SIZE[0] // 2, top + KILL_FEED_ROW_HEIGHT // 2)
                if controlled is not None and fighter.division == controlled.division:
                    color = PLAYER_COLOR if fighter is controlled else KILL_FEED_DIVISION_COLOR
                    highlight = pygame.Rect(0, 0, KILL_FEED_ICON_SIZE[1], KILL_FEED_ICON_SIZE[1])
                    highlight.center = center
                    pygame.draw.rect(panel, color, highlight)
                artwork = symbol_loader.get_symbol(fighter.data["type"], zoom=1,
                                                    color=TEAM_COLORS[fighter.side], country=fighter.data["owner"],
                                                    fit_size=KILL_FEED_ICON_SIZE)
                if artwork is not None:
                    panel.blit(artwork, artwork.get_rect(center=center))
            center = (KILL_FEED_INSET + actor_width + KILL_FEED_CAUSE_WIDTH // 2,
                      top + KILL_FEED_ROW_HEIGHT // 2)
            if kind == "ram":
                text = font.render("RAM", True, c.UI_TEXT_BRIGHT)
                panel.blit(text, text.get_rect(center=center))
            else:
                # A code-drawn arrow remains readable without relying on font glyphs.
                pygame.draw.line(panel, c.UI_TEXT_BRIGHT, (center[0] - 8, center[1]), (center[0] + 8, center[1]), 2)
                pygame.draw.polygon(panel, c.UI_TEXT_BRIGHT,
                                    [(center[0] + 8, center[1]), (center[0] + 2, center[1] - 4),
                                     (center[0] + 2, center[1] + 4)])
        panel.set_clip(None)
        self.draw_list_scrollbar(panel, KILL_FEED_WIDTH - KILL_FEED_INSET - KILL_FEED_SCROLLBAR_WIDTH,
                                 KILL_FEED_INSET, view_height, width=KILL_FEED_SCROLLBAR_WIDTH,
                                 **self._kill_feed_scroll_options())
        for name in ("kill_feed_track", "kill_feed_handle"):
            rect = getattr(self, name)
            if rect is not None:
                rect.move_ip(self.kill_feed_rect.topleft)
        self.kill_feed_surface = panel

    def _kill_feed_events(self, event):
        """Scroll the feed without steering, firing, panning, or zooming the battlefield."""
        if event.type not in {pygame.MOUSEWHEEL, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION}:
            return False
        position = getattr(event, "pos", pygame.mouse.get_pos())
        engaged = (self.kill_feed_rect.collidepoint(position) or self.kill_feed_dragging
                   or self.is_content_dragging("kill_feed_scroll"))
        if not engaged:
            return False
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.firing = False
                self.pan_drag = None
            elif event.button == 3:
                self.secondary_firing = False
        before = self.kill_feed_scroll
        self.handle_list_scroll(event, speed=KILL_FEED_ROW_HEIGHT, **self._kill_feed_scroll_options())
        if before != self.kill_feed_scroll:
            self._refresh_kill_feed()
        return True

    def _play_shot_sound(self, fighter):
        # Keep audio randomness separate from the seeded simulation's aiming and movement decisions.
        if fighter.weapon(fighter.fired_weapon)["shell"]:
            kind = random.choice(TANK_SHOT_SOUNDS)
        elif fighter is self.simulation.controlled:
            kind = "heavy_gunshot"
        else:
            kind = random.choice(RIFLE_SHOT_SOUNDS)
        sound_effects.play_ui_sound(kind, volume_scale=self.battle_sfx_volume_share())

    def _play_hit_sound(self, target, damage):
        # The simulation supplies HP actually lost, including the remaining-HP limit.
        if target.shape in combat.SOFT_TARGET_SHAPES:
            sounds = FLESH_HIT_SOUNDS
        elif damage <= target.data["max_health"] * RICOCHET_MAX_HEALTH_SHARE:
            sounds = RICOCHET_SOUNDS
        else:
            return
        sound_effects.play_ui_sound(random.choice(sounds), volume_scale=self.battle_sfx_volume_share())

    def start_battle(self):
        if self.mode != "preview" or self.preview_intro_stage is not None:
            return
        self.clear_controls()
        self.simulation.paused = False
        self.mode = "battle"
        self._refresh_controlled_stats()
        self.zoom_by(0, pygame.mouse.get_pos())
        self.update_battle_music_volume()
        self.last_tick = pygame.time.get_ticks()
        controlled = self.simulation.controlled
        if controlled is not None:
            self._follow_controlled_camera(controlled, pygame.mouse.get_pos())
        else:
            self._center_camera(combat.ARENA_SIZE[0] / 2, combat.ARENA_SIZE[1] / 2)
        self.refresh_ui()
        self._refresh_visibility()

    def clear_controls(self):
        self.held_keys.clear()
        self.firing = False
        self.secondary_firing = False
        self.touch_pointers.clear()
        self.kill_feed_dragging = False
        if self.simulation is not None:
            self.simulation.set_player_input()

    def cancel_pointer_input(self):
        super().cancel_pointer_input()
        self.clear_controls()

    def set_touch_mode(self, enabled):
        if self.touch_mode != enabled:
            self.touch_mode = enabled
            self.clear_controls()
            if self.mode == "battle":
                self.refresh_ui()

    @staticmethod
    def _touch_pad_rect(role):
        left = (TOUCH_PAD_MARGIN if role == "drive" else c.SCREEN_WIDTH - TOUCH_PAD_MARGIN - TOUCH_PAD_SIZE)
        return pygame.Rect(left, c.SCREEN_HEIGHT - TOUCH_PAD_BOTTOM - TOUCH_PAD_SIZE,
                           TOUCH_PAD_SIZE, TOUCH_PAD_SIZE)

    def _select_touch_weapon(self, mode):
        if self._driving() and self.simulation.controlled.weapon(1) is not None:
            self.touch_weapon_mode = mode
            for button in self.touch_weapon_buttons:
                button.apply_state(enabled=True, color="yellow" if button.text == mode else "grey")

    def handle_touch_pointer(self, kind, pointer, position):
        if pointer in self.touch_pointers:
            role, _ = self.touch_pointers[pointer]
            if kind == pygame.FINGERUP or not self._driving():
                del self.touch_pointers[pointer]
            else:
                self.touch_pointers[pointer] = role, position
            return True
        if kind != pygame.FINGERDOWN or not self.touch_mode or not self._driving():
            return False
        for role in ("drive", "aim"):
            if (self._touch_pad_rect(role).collidepoint(position)
                    and all(active != role for active, _ in self.touch_pointers.values())):
                self.touch_pointers[pointer] = role, position
                return True
        return False

    def _touch_axes(self, role):
        center = self._touch_pad_rect(role).center
        position = next((pos for active, pos in self.touch_pointers.values() if active == role), center)
        vector = pygame.Vector2(position) - center
        vector /= TOUCH_PAD_SIZE / 2
        if vector.length() <= TOUCH_DEAD_ZONE:
            return pygame.Vector2()
        if vector.length() > 1:
            vector.scale_to_length(1)
        return vector

    @staticmethod
    def view_rect():
        """Actual battle fills the whole screen."""
        return pygame.Rect(0, 0, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)

    @property
    def zoom(self):
        return ZOOM_LEVELS[self.zoom_index]

    def _view_span(self):
        """How much of the battlefield the screen shows at the current zoom."""
        return c.SCREEN_WIDTH / self.zoom, c.SCREEN_HEIGHT / self.zoom

    def _center_camera(self, x, y):
        width, height = self._view_span()
        self._move_camera(x - width / 2, y - height / 2)

    def _follow_controlled_camera(self, fighter, pointer):
        """Show more ground toward the pointer while keeping the controlled unit visible."""
        view = self.view_rect()
        # Use the view center, so moving the camera cannot amplify its own offset.
        dx = max(-view.width / 2, min(view.width / 2, pointer[0] - view.centerx))
        dy = max(-view.height / 2, min(view.height / 2, pointer[1] - view.centery))
        self._center_camera(fighter.x + dx * AIM_CAMERA_OFFSET / self.zoom,
                            fighter.y + dy * AIM_CAMERA_OFFSET / self.zoom)

    def _move_camera(self, left, top):
        """Keep the view inside the battlefield, or center the battlefield when it is smaller than the view."""
        self.camera = [(arena - span) / 2 if span >= arena else max(0.0, min(arena - span, start))
                       for start, span, arena in zip((left, top), self._view_span(), combat.ARENA_SIZE)]

    def zoom_by(self, steps, pos):
        """Step through ZOOM_LEVELS, keeping the battlefield point under ``pos`` in place."""
        controlling = (self.mode == "battle" and self.simulation is not None
                       and self.simulation.controlled is not None and self.simulation.controlled.alive)
        minimum = ZOOM_LEVELS.index(CONTROLLED_MIN_ZOOM) if controlling else 0
        index = max(minimum, min(len(ZOOM_LEVELS) - 1, self.zoom_index + steps))
        if index == self.zoom_index:
            return
        anchor = self.to_field(pos)
        self.zoom_index = index
        clear_rotated_sprites()
        if self.simulation is not None:
            self._cache_terrain_art()
        self._move_camera(anchor[0] - pos[0] / self.zoom, anchor[1] - pos[1] / self.zoom)
        self.update_battle_music_volume()
        self._refresh_visibility()

    def to_field(self, pos):
        """A screen position in battlefield coordinates."""
        return pos[0] / self.zoom + self.camera[0], pos[1] / self.zoom + self.camera[1]

    def to_screen(self, x, y):
        """A battlefield position on the screen."""
        return round((x - self.camera[0]) * self.zoom), round((y - self.camera[1]) * self.zoom)

    def _driving(self):
        """The player steers and fires only while the controlled sub-unit lives; afterward the player spectates."""
        return (self.mode == "battle" and not self.simulation.paused
                and self.simulation.controlled is not None and self.simulation.controlled.alive)

    def return_to_setup(self):
        self.cancel_active_drags()
        self.clear_controls()
        self.stop_tactical_music()
        self.mode = "setup"
        self.preview_intro_started = None
        self.preview_intro_stage = None
        self.simulation = None
        self.refresh_ui()

    def leave(self):
        if self.mode == "setup":
            self.cancel_active_drags()
            self.exit_screen()
        else:
            self.return_to_setup()

    def toggle_pause(self):
        if self.mode == "battle":
            self.clear_controls()
            self.simulation.paused = not self.simulation.paused
            self.last_tick = pygame.time.get_ticks()
            self.refresh_ui()

    def handle_back_key(self):
        if self.drag is not None:
            self.cancel_active_drags()
        elif self.mode == "battle":
            self.toggle_pause()
        elif self.campaign is None:
            self.leave()

    def cancel_active_drags(self):
        super().cancel_active_drags()
        self.drag = None
        self.marquee = None
        self.bar_drag = None
        self.pan_drag = None
        for element in self.elements:
            if isinstance(element, Slider):
                element.dragging = False
        for button in self.unit_buttons.values():
            button.is_pressed = False
        for side in (0, 1):
            setattr(self, f"roster_{side}_dragging", False)

    def card_rect(self, side, index):
        pane = self.panes[side]
        return pygame.Rect(pane.x + index * (CARD_SIZE[0] + CARD_GAP)
                           + getattr(self, f"roster_{side}_scroll"), pane.y, *CARD_SIZE)

    @staticmethod
    def _position_edit_button(button, card):
        button.rect.topright = (card.right - CARD_EDIT_INSET, card.top + CARD_EDIT_INSET)

    def _unit_button_events(self, event):
        if (self.mode != "setup" or self.drag is not None
                or event.type not in {pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP}):
            return False
        for (side, index), button in self.unit_buttons.items():
            self._position_edit_button(button, self.card_rect(side, index))
            if self.panes[side].collidepoint(event.pos):
                engaged = button.is_pressed or button.rect.collidepoint(event.pos)
                if engaged:
                    button.handle_event(event)
                    return True
            elif event.type == pygame.MOUSEBUTTONUP:
                button.is_pressed = False
        return False

    def _on_scrollbar(self, side, pos):
        track = getattr(self, f"roster_{side}_track", None)
        return bool(track and track.collidepoint(pos))

    def _clear_roster_selection(self):
        self.selected = [None, None]
        self.group = [[], []]

    def _deselect_background(self, event):
        if (event.type != pygame.MOUSEBUTTONDOWN or event.button != 1
                or self.drag is not None or self.marquee is not None or self.bar_drag is not None
                or not (any(index is not None for index in self.selected) or any(self.group))):
            return
        # Controls must keep their selected unit or group available to their callbacks.
        if any(element.visible and element.rect.collidepoint(event.pos) for element in self.elements):
            return
        for side, pane in enumerate(self.panes):
            if self._on_scrollbar(side, event.pos):
                return
            if pane.collidepoint(event.pos) and any(self.card_rect(side, index).collidepoint(event.pos) for index in range(len(self.rosters[side]))):
                return
        self._clear_roster_selection()
        self.refresh_ui()

    def _marquee_events(self, event):
        """Drag a selection square from empty panel space; roster background drags still scroll."""
        if self.marquee is not None:
            if event.type == pygame.MOUSEMOTION:
                self.marquee[2] = event.pos
                self._select_group(self.marquee[0], self.marquee[1], event.pos)
                return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                side, origin, _current = self.marquee
                self.marquee = None
                self._select_group(side, origin, event.pos)
                return True
            return False
        if (event.type != pygame.MOUSEBUTTONDOWN or event.button != 1 or self.drag is not None):
            return False
        if any(isinstance(element, Button) and element.rect.collidepoint(event.pos)
               for element in self.elements):
            return False
        for side, top in enumerate(PANEL_TOPS):
            if (pygame.Rect(PANEL_X, top, PANEL_WIDTH, PANEL_HEIGHT).collidepoint(event.pos)
                    and not self.panes[side].collidepoint(event.pos)
                    and not self._on_scrollbar(side, event.pos)):
                self.marquee = [side, event.pos, event.pos]
                return True
        return False

    @staticmethod
    def _marquee_rect(origin, current):
        return pygame.Rect(min(origin[0], current[0]), min(origin[1], current[1]),
                           abs(origin[0] - current[0]), abs(origin[1] - current[1]))

    def _select_group(self, side, origin, current):
        """Select the visible cards the square touches; a click without dragging clears the selection."""
        picked = []
        if math.dist(origin, current) >= DRAG_THRESHOLD:
            area = self._marquee_rect(origin, current).clip(self.panes[side])
            picked = [index for index in range(len(self.rosters[side]))
                      if self.card_rect(side, index).colliderect(area)]
        # One card is an ordinary selection, so Remove and Control keep working.
        selected = picked[0] if len(picked) == 1 else None
        group = picked if len(picked) > 1 else []
        if self.selected[side] == selected and self.group[side] == group:
            return
        self.selected[side] = selected
        self.group[side] = group
        self.refresh_ui()

    def _set_bar_health(self, side, index, x):
        """Set starting HP from the pointer's position along a card's health bar."""
        card = self.card_rect(side, index)
        bar, _flag_x = self._bar_geometry(EDIT_BAR_TOP)
        percent = round((x - card.x - bar.x) / bar.width * 100)
        unit = self.rosters[side][index]
        self.set_unit_options(side, self._units_to_edit(side, unit), health_percent=max(1, min(100, percent)))

    def _health_bar_events(self, event):
        """Press or drag along a card's health bar to set its starting HP."""
        if self.bar_drag is not None:
            side, index = self.bar_drag
            if event.type == pygame.MOUSEMOTION:
                self._set_bar_health(side, index, event.pos[0])
                return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._set_bar_health(side, index, event.pos[0])
                self.bar_drag = None
                return True
            return False
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1 or self.drag is not None:
            return False
        bar, _flag_x = self._bar_geometry(EDIT_BAR_TOP)
        for side, pane in enumerate(self.panes):
            if not pane.collidepoint(event.pos):
                continue
            for index in range(len(self.rosters[side])):
                card = self.card_rect(side, index)
                if bar.move(card.topleft).inflate(0, 2 * CARD_BAR_GRAB_PAD).collidepoint(event.pos):
                    self.bar_drag = (side, index)
                    self._set_bar_health(side, index, event.pos[0])
                    return True
        return False

    def _move_roster_entry(self, side, index, destination):
        """Move one roster entry. The leftmost card deploys in the front rank."""
        unit = self.rosters[side].pop(index)
        self.rosters[side].insert(destination, unit)
        self.group[side] = []
        if side == 0 and self.controlled_index is not None:
            if self.controlled_index == index:
                self.controlled_index = destination
            elif index < self.controlled_index <= destination:
                self.controlled_index -= 1
            elif destination <= self.controlled_index < index:
                self.controlled_index += 1
        if self.mode == "setup":
            self.selected[side] = destination
            return
        # Preview: campaign units follow their roster entries (friendly ones come first),
        # and the paused battle deploys again in the new order.
        if self.campaign is not None:
            self.campaign.units.insert(destination, self.campaign.units.pop(index))
        self._build_simulation()

    def _roster_reorderable(self, side):
        """Editing reorders both armies; preview reorders only the friendly army."""
        return self.mode == "setup" or (self.mode == "preview" and side == 0)

    def _roster_events(self, event):
        self._deselect_background(event)
        if self.mode == "setup" and (self._marquee_events(event) or self._health_bar_events(event)):
            return True
        if self.drag is not None:
            side, index, origin, active = self.drag
            if event.type == pygame.MOUSEMOTION:
                if math.dist(event.pos, origin) >= DRAG_THRESHOLD:
                    self.drag[3] = True
                return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if active and self.panes[side].collidepoint(event.pos):
                    offset = getattr(self, f"roster_{side}_scroll")
                    destination = int((event.pos[0] - self.panes[side].x - offset)
                                      // (CARD_SIZE[0] + CARD_GAP))
                    self._move_roster_entry(side, index, min(len(self.rosters[side]) - 1, max(0, destination)))
                self.drag = None
                self.refresh_ui()
                return True
            return False
        pointer = getattr(event, "pos", pygame.mouse.get_pos())
        for side, pane in enumerate(self.panes):
            options = self._scroll_options(side)
            track = getattr(self, options["track_attr"], None)
            engaged = (pane.collidepoint(pointer) or (track and track.collidepoint(pointer))
                       or getattr(self, options["drag_attr"], False)
                       or self.is_content_dragging(options["attr"]))
            if not engaged:
                continue
            if (self._roster_reorderable(side) and event.type == pygame.MOUSEBUTTONDOWN
                    and event.button == 1 and pane.collidepoint(event.pos)):
                for index in range(len(self.rosters[side])):
                    if self.card_rect(side, index).collidepoint(event.pos):
                        if self.mode == "setup":
                            self.selected[side] = index
                            self.group[side] = []
                        self.drag = [side, index, event.pos, False]
                        self.refresh_ui()
                        return True
            if self.handle_list_scroll(event, **options):
                return True
        return False

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.WINDOWFOCUSLOST:
                self.cancel_active_drags()
                self.clear_controls()
                if self.mode == "battle" and not self.simulation.paused:
                    self.toggle_pause()
            if self.done:
                return
            if event.type == pygame.KEYUP:
                self.held_keys.discard(event.key)
            if self.preview_intro_stage is not None:
                # Global Back handling remains available while the UI is covered.
                continue
            if self._unit_button_events(event):
                continue
            if event.type == pygame.KEYDOWN and event.key in CONTROL_KEYS and self._driving():
                self.held_keys.add(event.key)
                continue
            if self.mode in {"battle", "result"} and self._kill_feed_events(event):
                continue
            if self.mode in {"battle", "result"} and self._battlefield_mouse(event):
                continue
            if (self.mode == "setup" and event.type == pygame.MOUSEWHEEL
                    and self.year_slider.rect.inflate(20, 40).collidepoint(pygame.mouse.get_pos())):
                # A shorter track skips some years when dragged at pixel resolution.
                self.update_generation_year(self.generation_year - c.START_YEAR + event.y)
                continue
            if self.mode in {"setup", "preview"} and self._roster_events(event):
                continue
            for element in list(self.elements):
                element.handle_event(event)

    def _battlefield_mouse(self, event):
        """The wheel zooms; left/right mouse fire primary/secondary weapons while controlling a sub-unit.

        While spectating or viewing results, a left drag makes the battlefield follow the pointer.
        """
        if event.type == pygame.MOUSEWHEEL:
            self.zoom_by(1 if event.y > 0 else -1 if event.y < 0 else 0, pygame.mouse.get_pos())
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button in (1, 3):
            if event.button == 1:
                self.firing = False
                self.pan_drag = None
            else:
                self.secondary_firing = False
            return False  # Buttons still need the release.
        if event.type == pygame.MOUSEMOTION and self.pan_drag is not None:
            self._move_camera(self.camera[0] - (event.pos[0] - self.pan_drag[0]) / self.zoom,
                              self.camera[1] - (event.pos[1] - self.pan_drag[1]) / self.zoom)
            self.pan_drag = event.pos
            return True
        if (event.type != pygame.MOUSEBUTTONDOWN or event.button not in (1, 3)
                or any(element.rect.collidepoint(event.pos) for element in self.elements)):
            return False
        if self._driving():
            if event.button == 1:
                self.firing = True
            else:
                self.secondary_firing = True
        elif event.button == 1 and (self.mode == "result" or self.simulation.controlled is None
                                   or not self.simulation.controlled.alive):
            self.pan_drag = event.pos
        return True

    def _refresh_status(self):
        counts = tuple(sum(fighter.alive for fighter in self.simulation.fighters if fighter.side == side) for side in (0, 1))
        key = (*counts, int(self.simulation.elapsed))
        if key != self.status_key:
            self.status_key = key
            self.status_surfaces = [fonts.get("normal").render(text, True, c.UI_TEXT_BRIGHT)
                                    for text in (f"Friendly: {counts[0]}", f"Enemy: {counts[1]}",
                                                 f"{int(self.simulation.elapsed)}s")]

    def _refresh_controlled_stats(self):
        """Cache the controlled unit's readout only when its displayed values change."""
        controlled = self.simulation.controlled if self.simulation is not None else None
        if self.mode != "battle" or controlled is None or not controlled.alive:
            self.controlled_stats_key = None
            self.controlled_stats_surface = None
            return
        # Speed is signed along the hull. Round the countdown up so an unfinished reload never reads zero.
        key = (round(controlled.speed, 1) or 0.0, round(math.degrees(controlled.angle)) % 360,
               math.ceil(max(0.0, controlled.cooldown) * 10))
        if controlled.weapon(1) is not None:
            key += (math.ceil(max(0.0, controlled.secondary_cooldown) * 10),)
        if key == self.controlled_stats_key:
            return
        self.controlled_stats_key = key
        speed, angle, reload_tenths = key[:3]
        reload_status = f"{reload_tenths / 10:.1f}s" if reload_tenths else "Ready"
        lines = (f"Speed: {speed:.1f} px/s", f"Angle: {angle}\N{DEGREE SIGN}", f"Reload: {reload_status}")
        if controlled.weapon(1) is not None:
            secondary = f"{key[3] / 10:.1f}s" if key[3] else "Ready"
            lines = (*lines[:2], f"Primary: {reload_status}", f"Secondary: {secondary}")
        panel = pygame.Surface(CONTROL_STATS_SIZE)
        ui_elements.draw_pixel_panel(panel, panel.get_rect(), CONTROL_STATS_COLOR, CONTROL_STATS_BORDER)
        text_rect = panel.get_rect().inflate(-2 * CONTROL_STATS_INSET, -2 * CONTROL_STATS_INSET)
        ui_elements.draw_pixel_panel(panel, text_rect, CONTROL_STATS_TEXT_BACKGROUND,
                                     CONTROL_STATS_BORDER, gradient_strength=0.0, recessed=True)
        for row, text in enumerate(lines):
            image = fonts.get("normal").render(text, True, c.UI_TEXT_BRIGHT)
            panel.blit(image, (text_rect.x + CONTROL_STATS_TEXT_PADDING,
                               text_rect.y + CONTROL_STATS_TEXT_PADDING + row * CONTROL_STATS_ROW_HEIGHT))
        self.controlled_stats_surface = panel

    def update(self):
        if self.preview_intro_stage is not None:
            self._update_preview_intro()
            return
        if self.mode not in {"battle", "result"}:
            return
        now = pygame.time.get_ticks()
        dt = min(MAX_FRAME_SECONDS, max(0, now - self.last_tick) / 1000.0)
        self.last_tick = now
        if self.mode == "result" or not self.simulation.paused:
            self.death_explosions = [(fighter, age + dt) for fighter, age in self.death_explosions if age + dt < DEATH_EXPLOSION_SECONDS]
        if self.mode == "result":
            return
        driving = self._driving()
        pointer = pygame.mouse.get_pos()
        controlled = self.simulation.controlled
        aim_point = None
        move_direction = None
        throttle = int(pygame.K_w in self.held_keys) - int(pygame.K_s in self.held_keys)
        turn = int(pygame.K_d in self.held_keys) - int(pygame.K_a in self.held_keys)
        primary, secondary = self.firing, self.secondary_firing
        if self.touch_mode and controlled is not None and controlled.alive:
            drive, aim = self._touch_axes("drive"), self._touch_axes("aim")
            move_direction = drive
            pointer = (c.SCREEN_WIDTH / 2 + aim.x * TOUCH_PAD_SIZE,
                       c.SCREEN_HEIGHT / 2 + aim.y * TOUCH_PAD_SIZE)
            if aim.length_squared():
                aim_point = (controlled.x + aim.x * TOUCH_AIM_DISTANCE,
                             controlled.y + aim.y * TOUCH_AIM_DISTANCE)
            weapon_mode = self.touch_weapon_mode if controlled.weapon(1) is not None else "Primary"
            primary = bool(aim.length_squared()) and weapon_mode in {"Primary", "Both"}
            secondary = bool(aim.length_squared()) and weapon_mode in {"Secondary", "Both"}
        if controlled is not None and controlled.alive:
            # Convert the pointer to a firing target only after applying its camera offset.
            self._follow_controlled_camera(controlled, pointer)
        self.simulation.set_player_input(
            throttle=throttle if driving else 0.0, turn=turn if driving else 0.0,
            fire=primary if driving else False, secondary_fire=secondary if driving else False,
            aim_point=(aim_point if self.touch_mode else self.to_field(pointer)) if driving else None,
            move_direction=move_direction if driving else None)
        self.simulation.advance(dt)
        if self.terrain_art_key != (id(self.simulation.battlefield), self.simulation.battlefield.revision, self.zoom):
            self._cache_terrain_art()
        controlled = self.simulation.controlled
        if controlled is not None and controlled.alive:
            self._follow_controlled_camera(controlled, pointer)
        elif self.held_keys or self.firing or self.secondary_firing or self.touch_pointers:
            # The controlled sub-unit is gone: the player spectates, so drop held input and leave the camera free.
            self.clear_controls()
        if self.touch_weapon_buttons and (controlled is None or not controlled.alive):
            self.elements = [element for element in self.elements if element not in self.touch_weapon_buttons]
            self.touch_weapon_buttons.clear()
        self._refresh_status()
        if self.simulation.winner is not None:
            self.clear_controls()
            self.stop_tactical_music()
            self.mode = "result"
            self._apply_campaign_result()
            self.refresh_ui()
        self._refresh_controlled_stats()
        self._refresh_visibility()

    def _refresh_visibility(self):
        """Cache sight geometry on observer/terrain changes and project it on camera changes."""
        controlled = self.simulation.controlled if self.simulation is not None else None
        if self.mode != "battle" or controlled is None or not controlled.alive:
            self.visibility_key = self.visibility_mask_key = None
            self.visibility_mask = None
            self.foliage_shadow_mask = None
            self.visible_fighters.clear()
            return
        field = self.simulation.battlefield
        origin = controlled.x, controlled.y
        key = field, field.revision, origin, combat.WEAPON_RANGE
        if key != self.visibility_key:
            self.visibility_key = key
            self.visibility_blockers = field.sight_blockers(origin, combat.WEAPON_RANGE)
            self.visibility_outline = battle_terrain.sight_polygon(origin, combat.WEAPON_RANGE, self.visibility_blockers)
            foliage = field.foliage_silhouettes(origin, combat.WEAPON_RANGE)
            self.foliage_shadow_outline = battle_terrain.sight_polygon(origin, combat.WEAPON_RANGE, foliage) if foliage else ()
        self.visible_fighters = {id(fighter) for fighter in self.simulation.fighters if fighter is controlled or battle_terrain.point_in_sight(origin, (fighter.x, fighter.y), combat.WEAPON_RANGE, self.visibility_blockers)}
        size = self.view_rect().size
        mask_key = key, tuple(self.camera), self.zoom, size
        if mask_key != self.visibility_mask_key:
            self.visibility_mask_key = mask_key
            if self.visibility_mask is None or self.visibility_mask.get_size() != size:
                self.visibility_mask = pygame.Surface(size, pygame.SRCALPHA)
            self.visibility_mask.fill((0, 0, 0, 255))
            pygame.draw.polygon(self.visibility_mask, (0, 0, 0, 0), [self.to_screen(x, y) for x, y in self.visibility_outline])
            if self.foliage_shadow_outline:
                if self.foliage_shadow_mask is None or self.foliage_shadow_mask.get_size() != size:
                    self.foliage_shadow_mask = pygame.Surface(size, pygame.SRCALPHA)
                self.foliage_shadow_mask.fill((0, 0, 0, FOLIAGE_SHADOW_ALPHA))
                pygame.draw.polygon(self.foliage_shadow_mask, (0, 0, 0, 0), [self.to_screen(x, y) for x, y in self.foliage_shadow_outline])
                # Keep the stronger shadow: foliage must never reveal an opaque sight blocker.
                self.visibility_mask.blit(self.foliage_shadow_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MAX)

    def _update_preview_intro(self):
        if self.preview_intro_started is None:
            return
        elapsed = (pygame.time.get_ticks() - self.preview_intro_started) / 1000.0
        opening_at = PREVIEW_SLIDE_IN_SECONDS + PREVIEW_HOLD_SECONDS
        # Check both boundaries in order, even if a slow frame crosses both.
        if self.preview_intro_stage == 0 and elapsed >= PREVIEW_SLIDE_IN_SECONDS:
            sound_effects.play_ui_sound("select_unit_filter")
            self.preview_intro_stage = 1
        if self.preview_intro_stage == 1 and elapsed >= opening_at:
            sound_effects.play_ui_sound("open_music")
            self.preview_intro_stage = 2
        if elapsed >= opening_at + PREVIEW_SLIDE_OUT_SECONDS:
            self.preview_intro_stage = None
            self.preview_intro_started = None

    def draw(self, surface):
        if self.preview_intro_stage is None:
            super().draw(surface)
            return
        if self.preview_intro_started is None:
            self.preview_intro_started = pygame.time.get_ticks()
            surface.fill((0, 0, 0))
            return
        elapsed = (pygame.time.get_ticks() - self.preview_intro_started) / 1000.0
        if self.preview_intro_stage == 2:
            # Reveal the roster preview only as the bars move apart.
            super().draw(surface)
            elapsed -= PREVIEW_SLIDE_IN_SECONDS + PREVIEW_HOLD_SECONDS
            shown = 1.0 - min(1.0, max(0.0, elapsed / PREVIEW_SLIDE_OUT_SECONDS))
        else:
            surface.fill((0, 0, 0))
            shown = min(1.0, max(0.0, elapsed / PREVIEW_SLIDE_IN_SECONDS))
        top_height = c.SCREEN_HEIGHT // 2
        bottom_height = c.SCREEN_HEIGHT - top_height
        bars = (
            pygame.Rect(0, -top_height + round(top_height * shown), c.SCREEN_WIDTH, top_height),
            pygame.Rect(0, c.SCREEN_HEIGHT - round(bottom_height * shown), c.SCREEN_WIDTH, bottom_height),
        )
        for rect in bars:
            ui_elements.draw_pixel_panel(surface, rect, PREVIEW_BAR_COLOR, PREVIEW_BAR_BORDER,
                                         gradient_strength=PREVIEW_BAR_GRADIENT_STRENGTH)

    def _card_key(self, side, unit):
        return (self.mode, side, unit["type"], unit["owner"], unit["health"], unit["max_health"])

    @staticmethod
    def _bar_geometry(top):
        """The health bar rect and the flag's x, in card coordinates; the flag sits right of the bar."""
        flag_x = CARD_SIZE[0] - CARD_ROW_INSET - CARD_BAR_FLAG_SIZE[0]
        bar = pygame.Rect(CARD_ROW_INSET, top,
                          flag_x - CARD_BAR_FLAG_GAP - CARD_ROW_INSET, CARD_BAR_HEIGHT)
        return bar, flag_x

    def _draw_health_bar(self, card, unit, top):
        bar, flag_x = self._bar_geometry(top)
        pygame.draw.rect(card, OUTLINE_COLOR, bar)
        ratio = max(0.0, min(1.0, unit["health"] / unit["max_health"]))
        fill = pygame.Rect(bar.x + 1, bar.y + 1, round((bar.width - 2) * ratio), bar.height - 2)
        _draw_health_fill(card, fill, ratio)
        flag_icons.draw_flag(card, unit["owner"], self.country_data, flag_x,
                             bar.centery - CARD_BAR_FLAG_SIZE[1] // 2, size=CARD_BAR_FLAG_SIZE)

    def _cache_card(self, side, unit):
        key = self._card_key(side, unit)
        if key not in self.card_surfaces:
            width, height = CARD_SIZE
            card = pygame.Surface(CARD_SIZE, pygame.SRCALPHA)
            if not self._roster_reorderable(side):
                ui_elements.draw_pixel_panel(card, card.get_rect(), (46, 51, 65), (15, 19, 27))
            name = unit["type"]
            font = fonts.get("tiny")
            if self.mode == "preview":
                # Preview shows no unit name: a large icon, then a health bar with the flag to its right.
                icon = symbol_loader.get_symbol(name, zoom=1, color=TEAM_COLORS[side],
                                                country=unit["owner"], fit_size=PREVIEW_CARD_ICON_SIZE)
                if icon is not None:
                    card.blit(icon, icon.get_rect(center=(width // 2, PREVIEW_ICON_CENTER_Y)))
                self._draw_health_bar(card, unit, PREVIEW_BAR_TOP)
                stats_top = PREVIEW_STATS_TOP
            else:
                draw_unit_shape(card, combat.unit_shape(name, self.library), (width // 2, 28),
                                0 if side == 0 else math.pi, TEAM_COLORS[side], scale=1.4,
                                artwork=self.battle_artwork[name])
                label = queries.get_unit_display_name(name, self.library)
                line_height = font.get_height()
                for line_number, line in enumerate(wrap_text(label, font, width - 16)[:3]):
                    text = font.render(fit_text(line, font, width - 16), True, c.UI_TEXT_BRIGHT)
                    card.blit(text, text.get_rect(midtop=(width // 2, 52 + line_number * line_height)))
                self._draw_health_bar(card, unit, EDIT_BAR_TOP)
                stats_top = CARD_STATS_TOP
            attack = combat.division_attack(unit, self.library)
            entries = [(icon, queries.format_number(value)) for icon, value in (
                (c.ICON_HEALTH, unit["health"]), (c.ICON_ATTACK, attack), (c.ICON_DEFENSE, unit["defense"]))]
            ui_elements.draw_wrapped_icon_row(
                card, font, entries, 6, stats_top, c.UI_TEXT_LIGHT,
                width - 12, icon_size=CARD_STAT_ICON_SIZE)
            self.card_surfaces[key] = card
        return self.card_surfaces[key]

    def _draw_roster_card(self, surface, rect, side, unit, *, hovered=False, pressed=False, selected=False):
        if self._roster_reorderable(side):
            color = c.UI_COLORS["blue" if side == 0 else "red"][0]
            if side == 0 and self.controlled_index is not None and unit is self.rosters[0][self.controlled_index]:
                color = tuple(min(255, channel + CONTROLLED_CARD_BRIGHTNESS) for channel in color)
            ui_elements.draw_pixel_button(surface, rect, color, hovered=hovered, pressed=pressed, selected=selected)
        surface.blit(self.card_surfaces[self._card_key(side, unit)], rect)

    def _draw_rosters(self, surface):
        pointer = pygame.mouse.get_pos()
        for side, top in enumerate(PANEL_TOPS):
            panel = pygame.Rect(PANEL_X, top, PANEL_WIDTH, PANEL_HEIGHT)
            ui_elements.draw_pixel_panel(surface, panel, (39, 44, 58), (15, 19, 27))
            surface.blit(self.roster_labels[side], (panel.x + ROSTER_INSET, panel.y + 14))
            old_clip = surface.get_clip()
            surface.set_clip(old_clip.clip(self.panes[side]))
            for index, unit in enumerate(self.rosters[side]):
                rect = self.card_rect(side, index)
                if not rect.colliderect(self.panes[side]):
                    continue
                if self.drag is not None and self.drag[0] == side and self.drag[1] == index and self.drag[3]:
                    continue
                pressed = self.drag is not None and self.drag[:2] == [side, index]
                selected = self.selected[side] == index or index in self.group[side]
                hovered = self.panes[side].collidepoint(pointer) and rect.collidepoint(pointer) and (self.drag is None or pressed)
                self._draw_roster_card(surface, rect, side, unit, hovered=hovered or (self.mode == "setup" and selected), pressed=pressed, selected=selected)
                if self.mode == "setup":
                    button = self.unit_buttons[side, index]
                    self._position_edit_button(button, rect)
                    button.draw(surface)
                if side == 0 and self.controlled_index == index:
                    draw_player_arrow(surface, (rect.centerx, rect.y + 28), 0)
            surface.set_clip(old_clip)
            self.draw_list_scrollbar(surface, self.panes[side].x, self.panes[side].bottom + 10,
                                     ROSTER_WIDTH, width=SCROLLBAR_HEIGHT, **self._scroll_options(side))
        if self.drag is not None and self.drag[3]:
            side, index, origin, active = self.drag
            card = self.card_surfaces[self._card_key(side, self.rosters[side][index])]
            rect = card.get_rect(center=pygame.mouse.get_pos())
            self._draw_roster_card(surface, rect, side, self.rosters[side][index], hovered=True, pressed=True)
            if self.mode == "setup":
                button = self.unit_buttons[side, index]
                self._position_edit_button(button, rect)
                button.draw(surface)
            if side == 0 and self.controlled_index == index:
                draw_player_arrow(surface, (rect.centerx, rect.y + 28), 0)
        if self.marquee is not None:
            side, origin, current = self.marquee
            if math.dist(origin, current) >= DRAG_THRESHOLD:
                pygame.draw.rect(surface, TEAM_COLORS[side], self._marquee_rect(origin, current), 1)

    def _draw_controls(self, surface, fighter, center):
        """Range, firing cone, gun direction, heading arrow, and reload for the controlled sub-unit only."""
        zoom = self.zoom
        cone = combat.firing_cone(fighter.shape)
        reach = round(combat.WEAPON_RANGE * zoom)
        if cone is None:
            pygame.draw.circle(surface, RANGE_COLOR, center, reach, 1)
        else:
            steps = max(1, math.ceil(cone / CONE_ARC_STEP))
            start = fighter.angle - cone / 2
            edge = [(center[0] + math.cos(start + cone * step / steps) * reach,
                     center[1] + math.sin(start + cone * step / steps) * reach) for step in range(steps + 1)]
            pygame.draw.lines(surface, RANGE_COLOR, True, [center, *edge])
        end = (center[0] + math.cos(fighter.aim) * reach, center[1] + math.sin(fighter.aim) * reach)
        pygame.draw.line(surface, AIM_LINE_COLOR, center, end, 1)
        indicator_scale = max(MIN_PLAYER_INDICATOR_SCALE, zoom)
        pygame.draw.circle(surface, PLAYER_COLOR, center, max(PLAYER_RING_RADIUS, fighter.radius + 4) * indicator_scale, 2)
        draw_player_arrow(surface, center, fighter.angle,
                          fighter.speed / fighter.max_speed if fighter.max_speed else 0.0, scale=indicator_scale)
        for slot in (0, 1):
            if fighter.weapon(slot) is None or fighter.weapon_cooldown(slot) <= 0:
                continue
            # The ring fills clockwise from the top as the weapon reloads.
            loaded = max(0.0, min(1.0, 1.0 - fighter.weapon_cooldown(slot) / fighter.reload_duration(slot)))
            radius = (max(RELOAD_RING_RADIUS, fighter.radius + 8) + slot * 5) * indicator_scale
            steps = max(2, math.ceil(math.tau * loaded / CONE_ARC_STEP))
            ring = [(center[0] + math.cos(-math.pi / 2 + math.tau * loaded * step / steps) * radius,
                     center[1] + math.sin(-math.pi / 2 + math.tau * loaded * step / steps) * radius)
                    for step in range(steps + 1)]
            pygame.draw.lines(surface, RELOAD_COLOR if not slot else PLAYER_COLOR, False, ring, 2)

    def _draw_grass(self, surface):
        """The battlefield and its faint, fixed checkerboard; anything past its edges is dark."""
        surface.fill(OFF_FIELD_COLOR)
        zoom = self.zoom
        width, height = combat.ARENA_SIZE
        left, top = self.to_screen(0, 0)
        right, bottom = self.to_screen(width, height)
        field = pygame.Rect(left, top, right - left, bottom - top)
        color = TERRAIN_COLORS[self.simulation.battlefield.terrain]
        check_color = tuple(min(255, channel + 4) for channel in color)
        surface.fill(color, field)
        span_width, span_height = self._view_span()
        columns = range(max(0, int(self.camera[0] // GRASS_TILE)),
                        min(math.ceil(width / GRASS_TILE), math.ceil((self.camera[0] + span_width) / GRASS_TILE)))
        rows = range(max(0, int(self.camera[1] // GRASS_TILE)),
                     min(math.ceil(height / GRASS_TILE), math.ceil((self.camera[1] + span_height) / GRASS_TILE)))
        # Squares sit on the battlefield, so they pan and zoom with it but never animate.
        edges_x = {column: (round((column * GRASS_TILE - self.camera[0]) * zoom),
                            round((min(width, (column + 1) * GRASS_TILE) - self.camera[0]) * zoom))
                   for column in columns}
        for row in rows:
            y0 = round((row * GRASS_TILE - self.camera[1]) * zoom)
            y1 = round((min(height, (row + 1) * GRASS_TILE) - self.camera[1]) * zoom)
            for column in columns:
                if (row + column) % 2:
                    x0, x1 = edges_x[column]
                    surface.fill(check_color, (x0, y0, x1 - x0, y1 - y0))
        pygame.draw.rect(surface, OUTLINE_COLOR, field.inflate(6, 6), 3)

    def _trunk_sprite(self, size, width):
        """A trunk image scaled to its hitbox width at the current zoom."""
        source = _trunk_art(size)
        pixels = max(2, round(width * self.zoom))
        key = "trunk", size, pixels
        if key not in self.terrain_sprites:
            height = max(2, round(source.get_height() * pixels / source.get_width()))
            self.terrain_sprites[key] = pygame.transform.scale(source, (pixels, height))
        return self.terrain_sprites[key]

    def _see_through_foliage(self, radius, color):
        """A foliage circle at FOLIAGE_ALPHA, so the sub-units and trunk beneath it show faintly."""
        key = "foliage", radius, color
        if key not in self.terrain_sprites:
            sprite = pygame.Surface((radius * 2 + 1, radius * 2 + 1), pygame.SRCALPHA)
            pygame.draw.circle(sprite, color, (radius, radius), radius)
            sprite.set_alpha(FOLIAGE_ALPHA)
            self.terrain_sprites[key] = sprite
        return self.terrain_sprites[key]

    def _cache_terrain_art(self):
        """Cache terrain artwork at geometry/zoom changes; drawing only places surfaces.

        Ground features and tree trunks draw beneath units. Foliage draws above them as the canopy.
        """
        field = self.simulation.battlefield
        self.terrain_art_key = id(field), field.revision, self.zoom
        self.terrain_art = []
        self.canopy_art = []
        for feature in sorted(field.features, key=lambda feature: feature.kind == "tree"):
            if feature.destroyed:
                continue
            if feature.kind == "tree":
                self.terrain_art.append((feature, self._trunk_sprite(feature.trunk, feature.radius * 2)))
                # Only the green channel varies, so every tree stays a shade of FOLIAGE_COLOR.
                red, green, blue = FOLIAGE_COLOR
                color = red, max(0, min(255, green + round(feature.shade * FOLIAGE_GREEN_VARIATION))), blue
                radius = max(1, round(feature.foliage_radius * self.zoom))
                self.canopy_art.append((feature, self._see_through_foliage(radius, color)))
                continue
            radius = max(2, round(feature.radius * self.zoom))
            key = feature.kind, radius, feature.height if feature.kind == "hill" else 0
            if key not in self.terrain_sprites:
                art = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
                if feature.kind == "hill":
                    # Each contour represents the same height, so taller mounds
                    # have more bands. Mountain mounds keep their brown palette.
                    bands = [(1.0 - band * HILL_CONTOUR_HEIGHT / feature.height,
                              tuple(max(0, min(255, channel + HILL_BASE_SHADE + band * HILL_CONTOUR_SHADE))
                                    for channel in TERRAIN_COLORS[field.terrain]))
                             for band in range(math.ceil(feature.height / HILL_CONTOUR_HEIGHT))]
                else:
                    colors = FEATURE_COLORS[feature.kind]
                    bands = [(1.0 - band / (len(colors) + 1), color) for band, color in enumerate(colors)]
                for fraction, color in bands:
                    size = radius * fraction
                    points = []
                    step = max(1, round(FEATURE_PIXEL_STEP * self.zoom))
                    for index in range(FEATURE_OUTLINE_POINTS):
                        angle = math.tau * index / FEATURE_OUTLINE_POINTS
                        points.append((radius + round(math.cos(angle) * size / step) * step,
                                       radius + round(math.sin(angle) * size / step) * step))
                    pygame.draw.polygon(art, color, points)
                self.terrain_sprites[key] = art
            self.terrain_art.append((feature, self.terrain_sprites[key]))
    def _draw_terrain(self, surface):
        visible = surface.get_rect()
        for feature, art in self.terrain_art:
            rect = art.get_rect(center=self.to_screen(feature.x, feature.y))
            if rect.colliderect(visible):
                surface.blit(art, rect)

    def _draw_canopy(self, surface):
        """Draw every tree's cached, partly transparent foliage above units."""
        visible = surface.get_rect()
        for feature, art in self.canopy_art:
            rect = art.get_rect(center=self.to_screen(feature.x, feature.y))
            if rect.colliderect(visible):
                surface.blit(art, rect)

    def _draw_death_explosions(self, surface, limited_sight):
        if not self.death_explosions:
            return
        diameter = max(3, math.ceil(DEATH_EXPLOSION_RADIUS * self.zoom) * 2 + 1)
        if self.death_explosion_circle is None or self.death_explosion_circle.get_width() != diameter:
            self.death_explosion_circle = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        for fighter, age in self.death_explosions:
            if limited_sight and id(fighter) not in self.visible_fighters:
                continue
            progress = age / DEATH_EXPLOSION_SECONDS
            center = self.to_screen(fighter.x, fighter.y)
            radius = DEATH_EXPLOSION_RADIUS * progress * self.zoom
            circle = self.death_explosion_circle
            circle.fill((0, 0, 0, 0))
            pygame.draw.circle(circle, (*DEATH_EXPLOSION_CIRCLE_COLOR, round(DEATH_EXPLOSION_CIRCLE_ALPHA * (1 - progress))), (diameter // 2, diameter // 2), max(1, round(radius)))
            surface.blit(circle, circle.get_rect(center=center))
            size = max(1, round(DEATH_EXPLOSION_PARTICLE_SIZE * (1 - progress) * self.zoom))
            color = DEATH_EXPLOSION_COLORS[min(len(DEATH_EXPLOSION_COLORS) - 1, int(progress * len(DEATH_EXPLOSION_COLORS)))]
            for dx, dy in DEATH_EXPLOSION_OFFSETS:
                rect = pygame.Rect(0, 0, size, size)
                rect.center = (round(center[0] + dx * radius), round(center[1] + dy * radius))
                pygame.draw.rect(surface, color, rect)

    def _draw_battle(self, surface):
        self._draw_grass(surface)
        self._draw_terrain(surface)
        zoom = self.zoom
        # Shapes partly on screen still draw; the widest shape fits inside this margin.
        margin = math.ceil(140 * zoom)
        visible = self.view_rect().inflate(margin, margin)
        bar_size = (round(28 * zoom), round(4 * zoom))
        flag_size = tuple(max(2, round(side * zoom)) for side in BATTLE_FLAG_SIZE)
        controlled = self.simulation.controlled
        limited_sight = self.mode == "battle" and controlled is not None and controlled.alive and self.visibility_mask is not None
        labeled = []  # Living sub-units whose health bars and flags draw above the foliage.
        for fighter in self.simulation.fighters:
            if limited_sight and id(fighter) not in self.visible_fighters:
                continue
            center = self.to_screen(fighter.x, fighter.y)
            if not visible.collidepoint(center):
                continue
            if not fighter.alive:
                draw_unit_shape(surface, fighter.shape, center, fighter.angle, DEAD_COLOR,
                                scale=zoom, aim=fighter.aim, artwork=self.battle_artwork[fighter.data["type"]])
                continue
            scale = zoom
            draw_unit_shape(surface, fighter.shape, center, fighter.angle, TEAM_COLORS[fighter.side],
                            scale=scale, aim=fighter.aim,
                            artwork=self.battle_artwork[fighter.data["type"]],
                            recoil=4 * fighter.recoil / c.TACTICAL_MUZZLE_SECONDS)
            if fighter.muzzle > 0:
                shell = fighter.weapon(fighter.fired_weapon)["shell"]
                length = UNIT_SHAPE_SIZES[fighter.shape][0] / 2
                tip = (round(center[0] + math.cos(fighter.aim) * length * scale),
                       round(center[1] + math.sin(fighter.aim) * length * scale))
                flash = max(2, round((5 if shell else 2) * scale))
                pygame.draw.rect(surface, TANK_SHOT_COLOR if shell else SHOT_COLOR,
                                 (tip[0] - flash, tip[1] - flash, flash * 2, flash * 2))
            labeled.append((fighter, center, scale))
        line_width = max(1, round(SHOT_WIDTH * zoom))
        tank_line_width = max(2, round(TANK_SHOT_WIDTH * zoom))
        for shot in self.simulation.projectiles:
            head = self.to_screen(shot.x, shot.y)
            if not visible.collidepoint(head):
                continue
            tail_length = SHOT_TAIL * zoom / (math.hypot(shot.vx, shot.vy) or 1.0)
            tail = (round(head[0] - shot.vx * tail_length), round(head[1] - shot.vy * tail_length))
            tank_shell = shot.weapon_data["shell"]
            pygame.draw.line(surface, TANK_SHOT_COLOR if tank_shell else SHOT_COLOR, tail, head,
                             tank_line_width if tank_shell else line_width)
        for x, y, remaining, shell in self.simulation.impacts:
            point = self.to_screen(x, y)
            size = max(1, round((7 if shell else 3) * zoom * remaining / c.TACTICAL_IMPACT_SECONDS))
            pygame.draw.rect(surface, TANK_SHOT_COLOR if shell else SHOT_COLOR,
                             (point[0] - size, point[1] - size, size * 2, size * 2), max(1, round(zoom)))
        self._draw_death_explosions(surface, limited_sight)
        self._draw_canopy(surface)
        for fighter, center, scale in labeled:
            bar = pygame.Rect(center[0] - bar_size[0] // 2, center[1] - round(23 * scale), *bar_size)
            pygame.draw.rect(surface, OUTLINE_COLOR, bar)
            ratio = max(0.0, min(1.0, fighter.data["health"] / fighter.data["max_health"]))
            _draw_health_fill(surface, pygame.Rect(bar.x, bar.y, round(bar.width * ratio), bar.height), ratio)
            flag_icons.draw_flag(surface, fighter.data["owner"], self.country_data,
                                 bar.right + round(BATTLE_FLAG_GAP * zoom),
                                 bar.centery - flag_size[1] // 2, size=flag_size)
        if controlled is not None and controlled.alive:
            self._draw_controls(surface, controlled, self.to_screen(controlled.x, controlled.y))
            self._draw_edge_indicators(surface, controlled)
        if limited_sight:
            # Cover terrain, bodies, labels, effects, and aiming guides together.
            # Screen controls and battle readouts are drawn above this world mask.
            surface.blit(self.visibility_mask, (0, 0))

    def _draw_edge_indicators(self, surface, controlled):
        """Group off-screen divisions by direction; show the nearest distance in each group."""
        bounds = self.view_rect().inflate(-EDGE_INDICATOR_INSET * 2, -EDGE_INDICATOR_INSET * 2)
        bounds.top = max(bounds.top, EDGE_INDICATOR_TOP)
        origin = pygame.Vector2(self.to_screen(controlled.x, controlled.y))
        origin.x = max(bounds.left, min(bounds.right - 1, origin.x))
        origin.y = max(bounds.top, min(bounds.bottom - 1, origin.y))
        view = self.view_rect()
        indicators = {}
        for division in self.simulation.divisions:
            enemies = [unit for unit in division if unit.alive and unit.side != controlled.side and id(unit) in self.visible_fighters]
            if not enemies or any(view.collidepoint(self.to_screen(unit.x, unit.y)) for unit in enemies):
                continue
            enemy = min(enemies, key=lambda unit: math.hypot(unit.x - controlled.x, unit.y - controlled.y))
            direction = pygame.Vector2(self.to_screen(enemy.x, enemy.y)) - origin
            if direction.length_squared() == 0:
                continue
            direction.normalize_ip()
            horizontal = math.inf
            vertical = math.inf
            if direction.x:
                horizontal = ((bounds.right - 1 - origin.x) if direction.x > 0 else bounds.left - origin.x) / direction.x
            if direction.y:
                vertical = ((bounds.bottom - 1 - origin.y) if direction.y > 0 else bounds.top - origin.y) / direction.y
            point = origin + direction * min(horizontal, vertical)
            edge = ("right" if direction.x > 0 else "left") if horizontal <= vertical else ("bottom" if direction.y > 0 else "top")
            along = point.y if horizontal <= vertical else point.x
            key = edge, round(along / EDGE_INDICATOR_SPACING)
            distance = math.hypot(enemy.x - controlled.x, enemy.y - controlled.y)
            count = 1
            if key in indicators:
                previous = indicators[key]
                count += previous[3]
                if previous[2] < distance:
                    point, direction, distance = previous[:3]
            indicators[key] = point, direction, distance, count
        for point, direction, distance, count in indicators.values():
            sideways = pygame.Vector2(-direction.y, direction.x)
            size = EDGE_INDICATOR_SIZE
            points = [point, point - direction * size * 2 + sideways * size,
                      point - direction * size * 2 - sideways * size]
            pygame.draw.polygon(surface, OUTLINE_COLOR, points)
            color = TEAM_COLORS[1 - controlled.side]
            pygame.draw.polygon(surface, color, points, 2)
            distance_label = str(round(distance / EDGE_INDICATOR_LABEL_STEP) * EDGE_INDICATOR_LABEL_STEP)
            caption = f"{count}x {distance_label}" if count > 1 else distance_label
            label = fonts.get("small").render(caption, True, color)
            label_rect = label.get_rect(center=point - direction * size * 3)
            label_rect.clamp_ip(view)
            surface.blit(label, label_rect)

    def draw_background(self, surface):
        """Keep the battlefield behind combat and the finished battle's result controls."""
        if self.mode in {"battle", "result"}:
            self._draw_battle(surface)
        else:
            super().draw_background(surface)

    def additional_draw(self, surface):
        if self.mode in {"setup", "preview"}:
            self._draw_rosters(surface)
            if self.mode == "setup" and self.forecast_surface is not None:
                surface.blit(self.forecast_surface,
                             self.forecast_surface.get_rect(center=(c.SCREEN_WIDTH // 2, FORECAST_CENTER_Y)))
            return
        center_x = c.SCREEN_WIDTH // 2
        for image, center in zip(self.status_surfaces, (
                (center_x - BATTLE_STATUS_SIDE_OFFSET, BATTLE_STATUS_Y),
                (center_x + BATTLE_STATUS_SIDE_OFFSET, BATTLE_STATUS_Y), (center_x, BATTLE_STATUS_Y))):
            surface.blit(image, image.get_rect(center=center))
        if self.kill_feed_surface is not None:
            surface.blit(self.kill_feed_surface, self.kill_feed_rect)
        controlled = self.simulation.controlled
        if self.touch_mode and self.mode == "battle" and controlled is not None and controlled.alive:
            for role in ("drive", "aim"):
                rect = self._touch_pad_rect(role)
                ui_elements.draw_pixel_panel(surface, rect, CONTROL_STATS_COLOR, CONTROL_STATS_BORDER, recessed=True)
                axes = self._touch_axes(role)
                knob = pygame.Rect(0, 0, 28, 28)
                knob.center = (rect.centerx + axes.x * (rect.width / 2 - knob.width / 2),
                               rect.centery + axes.y * (rect.height / 2 - knob.height / 2))
                ui_elements.draw_pixel_panel(surface, knob, TEAM_COLORS[0] if role == "drive" else PLAYER_COLOR,
                                             CONTROL_STATS_BORDER)
        if (self.mode == "battle" and controlled is not None and controlled.alive
                and self.controlled_stats_surface is not None):
            panel = self.controlled_stats_surface
            surface.blit(panel, panel.get_rect(bottomleft=(SCREEN_EDGE_MARGIN,
                                                          surface.get_height() - SCREEN_EDGE_MARGIN)))
        if self.mode == "battle" and self.simulation.paused:
            rect = pygame.Rect(0, 0, 210, 70)
            rect.center = self.view_rect().center
            ui_elements.draw_pixel_panel(surface, rect, (39, 44, 58), (15, 19, 27))
            label = fonts.get("heading2").render("Paused", True, c.UI_TEXT_BRIGHT)
            surface.blit(label, label.get_rect(center=rect.center))


class CustomBattleUnitEditor(ModalScreen):
    """Edit one custom roster entry, or a selected group, with the country picker and an HP slider."""

    PANEL_SIZE = (460, 250)
    ROW_TOP = 70
    ROW_HEIGHT = 42
    ROW_GAP = 12
    DONE_SIZE = (100, 34)
    SLIDER_OFFSET = ROW_HEIGHT + ROW_GAP + 28
    DONE_GAP = 40

    def __init__(self, battle_screen, side, units):
        super().__init__(battle_screen, "Unit Settings" if len(units) == 1 else "Group Settings")
        self.battle_screen = battle_screen
        self.side = side
        self.units = units
        self.refresh_ui()

    def _health_percent(self, unit):
        return unit["health"] / unit["max_health"] * 100

    def refresh_ui(self):
        x = self.panel_rect.x + self.PAD
        y = self.panel_rect.y + self.ROW_TOP
        width = self.panel_rect.width - self.PAD * 2
        owners = {unit["owner"] for unit in self.units}
        percents = {round(self._health_percent(unit)) for unit in self.units}
        country = (queries.get_country_display_name(next(iter(owners)), self.battle_screen.country_data)
                   if len(owners) == 1 else MIXED_LABEL)
        health = f"{next(iter(percents))}%" if len(percents) == 1 else MIXED_LABEL
        buttons = [
            Button(x, y, (width, self.ROW_HEIGHT), "grey", f"Nationality: {country}",
                   self.choose_country, font_size=18),
            Button(self.panel_rect.centerx - self.DONE_SIZE[0] // 2,
                   y + self.SLIDER_OFFSET + self.DONE_GAP, self.DONE_SIZE, "blue", "Done",
                   self.exit_screen, font_size=18, sound_kind="back"),
        ]
        for button in buttons:
            button.fit_text = True
            button.fit_single_line = True
        # The label is drawn above the track, so the slider sits below that label's room.
        self.hp_slider = Slider(x, y + self.SLIDER_OFFSET, width, f"Starting HP: {health}",
                                self._health_percent(self.units[0]), self.set_percent,
                                visual_max=100, allowed_max=100)
        self.elements = [buttons[0], self.hp_slider, buttons[1]]

    def set_percent(self, value):
        percent = max(1, round(value))
        if self.battle_screen.set_unit_options(self.side, self.units, health_percent=percent):
            # Keep the dragged slider alive instead of rebuilding the controls.
            self.hp_slider.text = f"Starting HP: {percent}%"

    def _set_options(self, **options):
        if self.battle_screen.set_unit_options(self.side, self.units, **options):
            self.refresh_ui()

    def choose_country(self):
        pickers.open_listbox_selector(
            self, "Nationality", "",
            queries.country_picker_items(self.battle_screen.nationalities, self.battle_screen.country_data),
            lambda country: self._set_options(owner=country))
