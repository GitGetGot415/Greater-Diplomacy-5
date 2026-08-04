# Used for logical ownership assignment
WATER_MAPPING = {
    "ocean": "Ocean", 
    "coastal_sea": "Ocean", 
    "inland_sea": "Ocean", 
    "lakes": "Lakes"
}

# Used in refresh_map.py so lakes render the same color as oceans on political maps
VISUAL_WATER_MAPPING = {
    "ocean": "Ocean", 
    "coastal_sea": "Ocean", 
    "inland_sea": "Ocean", 
    "lakes": "Ocean"
}

# Used to check if terrain is water in several movement/combat files
WATER_TERRAINS = ["ocean", "coastal_sea", "inland_sea", "lakes"]
OCEAN_TERRAINS = ["ocean", "coastal_sea", "inland_sea"]

# Owner groupings for logic and UI checks
WATER_NATIONS = ["Ocean", "Lakes"]
UNPLAYABLE_NATIONS = ["None", "Unclaimed", "The Rot", "Ocean", "Lakes", "Spectator", "GLOBAL_EVENTS", "FACTION_WAR_MAPS"]

# Width and Height
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720

# --- Text Input Limits ---
MAX_API_KEY_LENGTH = 200
MAX_MODEL_NAME_LENGTH = 150
MAX_MESSAGE_LENGTH = 150
MAX_MAIL_DRAFT_LENGTH = 120
UNIT_NAME_MAX_LENGTH = 50
COUNTRY_NAME_MAX_LENGTH = 50

# Economy Data
BASE_YIELDS = {
    "manpower": 100,
    "materials": 10,
    "fuel": 1
}

GENERAL_RECRUITMENT_BONUS = 5 # Add this

RESOURCE_REFINING_BONUS_PER_LVL = 0.1 # +10% natural resource income per level

# Shared resource ordering used across economy and UI calculations.
# ECON_RESOURCE_KEYS is the canonical order for anything that touches all three;
# TRADE_RESOURCE_KEYS is the subset nations can actually hand to each other.
ECON_RESOURCE_KEYS = ("manpower", "materials", "fuel")
TRADE_RESOURCE_KEYS = ("materials", "fuel")

COUNTRY_BASE_YIELDS = {
    "manpower": 200,
    "materials": 100,
    "fuel": 0
}

BERGIUS_FUEL_BONUS = 100

UPKEEP_MODIFIERS = {
    "manpower": 0.10,
    "materials": 0.05,
    "fuel": 0.20
}

# reminder that base days per turn is the scenario default
# days per turn is what the game actually does
# if the days per turn is set to default then it uses the scenario default
DEFAULT_DAYS_PER_TURN = 15
DAYS_PER_TURN_OPTIONS = ["Default", 5, 10, 15, 30, 90]

# Non-core penalties
NON_CORE_MULTIPLIERS = {
    "manpower": 0.1,
    "materials": 0.5,
    "fuel": 1.0
}

NON_CORE_BUILDING_MULTIPLIER = 0.5
CORE_BASE_COST_MANPOWER = 1000
CORE_SCALING_COST_MANPOWER = 500

CORE_CONSTRUCTION_TURNS = 24

REMOVE_CORE_TURNS = 2

CREDITS_DATA = [
    {
        "main_text": "Lead Developer: ", 
        "people": [
            {"link_text": "GitGetGot415", "url": "https://github.com/GitGetGot415"}
        ]
    },
    {
        "main_text": "GitHub Contributors: ", 
        "people": [
            {"link_text": "litbrb", "url": "https://github.com/litbrb"},
            {"link_text": "github-advanced-security[bot]", "url": "https://docs.github.com/en/get-started/learning-about-github/about-github-advanced-security"}
        ]
    },
    {
            "main_text": "Map Makers: ", 
            "people": [
                {"link_text": "neptune2019"},
            ]
    },
]

SHOW_FPS = False

# Whether the Map screen's ocean uses the scrolling checkerboard pattern
# (see GameState.draw_checkerboard_background) instead of a flat fill. Off by
# default since it can visually read as unusual water for players who don't
# expect it.
CHECKERBOARD_WATER = False

GAME_VERSION = "v22"
VERSION_CHECK_URL = "https://raw.githubusercontent.com/GitGetGot415/Greater-Diplomacy-5/main/version.txt"

# --- TACTICAL MODE CONSTANTS ---
TACTICAL_MAX_MANPOWER = 2000
TACTICAL_MAX_MATERIALS = 20000
TACTICAL_MAX_FUEL = 500

TACTICAL_DEFAULT_YEAR = 1910

# ==========================================
# SCENARIO SETTINGS
# ==========================================

# --- FOG OF WAR ---
USE_FOG_OF_WAR = True # Toggle Fog of War mechanics on or off
DEFAULT_FOG_OF_WAR = True
DEFAULT_FOG_OF_WAR_STRENGTH = "normal"
FOG_OF_WAR_ALPHA = 160 # How dark unseen provinces get (0-255)

# --- CASUS BELLI ---
CASUS_BELLI_REQUIRED = True
DEFAULT_CASUS_BELLI = True

# --- SURPRISE ATTACK ---
DEFAULT_SURPRISE_ATTACK = False

# --- SCRIPTED EVENTS & AI ---
DEFAULT_USE_SCRIPTED_EVENTS = True
DEFAULT_AI_DISABLED = False

# --- BATTLE ROYALE ---
BATTLE_ROYALE_MODE = False
DEFAULT_BATTLE_ROYALE = False
DEFAULT_BOUNCE_TIEBREAKER = False

# --- FACTIONS ---
DISABLE_FACTIONS = False
DEFAULT_DISABLE_FACTIONS = False

# ==========================================
# DEFAULTS & ASSETS
# ==========================================

# --- Dynamic Menu Text & Links ---
# The first item will be placed at the bottom, and subsequent items will stack upwards.
MENU_BOTTOM_TEXTS = [
    {"main_text": "Discord - ", "link_text": "https://discord.gg/f5Jugz9SKa", "url": "https://discord.gg/f5Jugz9SKa/"},
    {"main_text": "Github - ", "link_text": "https://github.com/GitGetGot415/Greater-Diplomacy-5", "url": "https://github.com/GitGetGot415/Greater-Diplomacy-5/"}
]
MENU_BOTTOM_TEXT_START_X = 20
MENU_BOTTOM_TEXT_START_Y = SCREEN_HEIGHT - 40
MENU_BOTTOM_TEXT_STEP_Y = -30

MENU_BOTTOM_TEXT_COLOR = (255, 255, 255)
MENU_BOTTOM_TEXT_LINK_COLOR = (150, 200, 255)
MENU_BOTTOM_TEXT_HOVER_COLOR = (100, 255, 100)


DEFAULT_BG_COLOR = (30, 30, 30)

# AI Default Models
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_CHATGPT_MODEL = "gpt-4o-mini"
DEFAULT_CLAUDE_MODEL = "claude-3-haiku-20240307"
DEFAULT_OLLAMA_MODEL = "llama3"

# Models that safely support Ollama's strict JSON grammar engine
OLLAMA_JSON_SUPPORTED_MODELS = ["llama", "mistral", "phi", "gemma"]

# ==========================================
# STARTING BUILDINGS
# ==========================================

DEFAULT_STARTING_FACTORY = "Basic Factory"
BASIC_FACTORY_BASE_COST_X = 10000
BASIC_FACTORY_COST_MULTIPLIER = 1000
BASIC_FACTORY_TURNS = 20

# ==========================================
# ECONOMY SCREEN
# ==========================================

FUEL_REFINING_CONVERSION_PER_LVL = 0.01

MAX_CONVERSION_SLIDER_VAL = 0.50
CONSCRIPTION_RATIO = 0.2 # 5 manpower -> 1 material
FUEL_CONVERSION_RATIO = 0.1 # 10 materials -> 1 fuel

# ==========================================
# AUDIO DEFAULTS
# ==========================================

from data.platform import IS_WEB

USE_SOLOUD = not IS_WEB # SoLoud has no browser build; Pygame Mixer is forced on web

DEFAULT_SFX_VOLUME = 1.0
DEFAULT_MUSIC_VOLUME = 1.0
DEFAULT_AUDIO_PITCH = 0.5 # Updated from 0.3 to make 50% the new true default playback speed

# ==========================================
# UI BARS
# ==========================================

UI_LEFT_OFFSET = 160

# How far (in screen pixels) to shift the camera left when a province is selected,
# so the orders panel doesn't cover the unit the camera just centered on.
ORDERS_PANEL_CAMERA_X_OFFSET = 150

# --- UI Component Heights ---
TOP_UI_HEIGHT = 60
BOT_UI_HEIGHT = 60
TOTAL_UI_HEIGHT = 120

# This probably needs to be implemented in more places than just orders.py / buttons.py (does it? what is this for again?)
# I think this is implemented in everywhere it needs to be... right?
TOP_BAR_UI_CENTER_Y = 10
BOTTOM_BAR_UI_CENTER_Y = SCREEN_HEIGHT - 50

# ==========================================
# EDIT COUNTRY
# ==========================================

MAX_EDITOR_HISTORY = 30

# --- Editor UI Placement ---
EDIT_COUNTRY_UI_X1 = 50
EDIT_COUNTRY_UI_X2 = 450
EDIT_COUNTRY_UI_X3 = 850

# ==========================================
# PROVINCE MENU
# ==========================================

# --- Province Menu UI Layout (X, Y, Width, Height) ---
PROVINCE_UI = {
    "diplomatic_box": (10, 150, 140, 450),
    "mail_box": (400, 300, 150, 300)
}

# ==========================================
# SETTINGS
# ==========================================

DEFAULT_AI_MODE = "OFF" # LLM AI is opt-in; off until the player picks a provider
AI_MODE_REENABLE_FALLBACK = "OLLAMA" # Provider selected when re-enabling AI from OFF with no prior mode
DEFAULT_AI_THREADS = 1 # Added default thread count

# --- Unified Settings UI Layout ---
SETTINGS_BOX_X = 140
SETTINGS_KEY_BOX_Y = SCREEN_HEIGHT - 130
SETTINGS_MOD_BOX_Y = SCREEN_HEIGHT - 60
SETTINGS_BOX_W = 320
SETTINGS_BOX_H = 40

TARGET_FPS = 60
CPU_LIMITER = 10

# ==========================================
# STARTING GAME RULES & TIMING
# ==========================================

START_YEAR = 1910
END_YEAR = 2010
RESEARCH_TIMELINE_SPACING = 70 # Width between years on the research timeline

BASE_RESEARCH_POINTS_PER_DAY = 10
RESEARCH_SLOTS = 3 # Number of techs a nation can research simultaneously

# Random Scenario Settings
RANDOM_SCENARIO_SPAWN_UNITS = True
RANDOM_SCENARIO_MIN_INFANTRY = 3 # Minimum ground army before buying ships/tanks
RANDOM_SCENARIO_MIN_FACTORIES = 2 # Minimum factories a country should spawn with
RANDOM_SCENARIO_DEFAULT_ISLAND_FILTER = 5
RANDOM_SCENARIO_MAX_ISLAND_FILTER = 50
RANDOM_SCENARIO_SINGLE_TILE_START = False
RANDOM_SCENARIO_DEFAULT_RESOURCE_CHANCE = 0.15

# Unlocked tech exception for starting exactly in 1910
DEFAULT_1910_TECH = {
    "infantry_type": 1,
    "cavalry": 1,
    "militia": 1,
    "destroyer": 1,
    "basic_factory": 1
}

# ==========================================
# WARGOALS & PEACE TREATIES
# ==========================================

CLAIM_TURN_CORE = 1
CLAIM_TURN_NON_CORE = 2

WARGOAL_TAKE_CLAIMS = "Take Claims"
WARGOAL_NO_CB = "No Casus Belli"
WARGOAL_INDEPENDENCE = "Independence"
WARGOAL_PREEMPTIVE = "Preemptive"

PEACE_SURRENDER = "Surrender"
PEACE_WHITE_PEACE = "Ceasefire"
PEACE_DEMAND_CLAIMS = "Demand Claims"
TRUCE_TURNS = 12

# ==========================================
# PUPPET SETTINGS
# ==========================================

PUPPET_TYPE_AUTONOMOUS = "Autonomous"
PUPPET_TYPE_INTEGRATED = "Integrated"
MAX_PUPPET_SIPHON = 0.50

# ==========================================
# INPUT SETTINGS
# ==========================================

KEY_REPEAT_DELAY = 400
KEY_REPEAT_INTERVAL = 40

# ==========================================
# UNIT OBSOLESCENCE
# ==========================================

OBSOLESCENCE_RULES = {
    "Cavalry": ["trucks"],
    "WW1 Armored Car": ["armored_car"],
    "WW1 Tank": ["medium_tank", "heavy_tank"],
    "Medium Tank": ["main_battle_tank"],
    "Heavy Tank": ["super_heavy_tank"],
    "WW1 Railroad Gun": ["ww2_railroad_gun"],
    "Landkreuzer P.1000 Ratte": ["landkreuzer_p1500_monster"],
    "Dreadnought": ["battleship"],
    "Battleship": ["aircraft_carrier"],
}

# ==========================================
# GLOBAL COLORS & PALETTES
# ==========================================

UI_COLORS = {
    "red": ((200, 0, 0), (255, 50, 50)),
    "orange": ((200, 90, 0), (255, 140, 50)),
    "yellow": ((200, 150, 0), (255, 200, 50)),
    "purple": ((200, 0, 200), (255, 50, 255)),
    "pink": ((200, 100, 100), (255, 150, 150)),
    "green": ((0, 150, 0), (0, 200, 0)),
    "light_blue": ((100, 100, 200), (150, 150, 255)),
    "blue": ((0, 0, 200), (50, 50, 255)),
    "white": ((200, 200, 200), (255, 255, 255)),
    "light_grey": ((150, 150, 150), (200, 200, 200)),
    "grey": ((100, 100, 100), (150, 150, 150))
}

SIZES = {
    "tiny_square": (30, 30),
    "small_square": (40, 40),
    "medium_square": (50, 50),
    "tech_square": (60, 60),
    "tech_square_medium": (100, 60),
    "tech_square_wide": (150, 60),
    "tech_square_ultra_wide": (270, 60),
    "tech_square_railroad_gun": (270, 110),
    "tech_square_ww2_railroad_gun": (340, 120),
    "tech_square_landkreuzer_p1000_ratte": (400, 130),
    "tech_square_landkreuzer_p1500_monster": (600, 180),
    "tech_square_railgun": (500, 220),
    "album_square": (200, 200),
    "left_ui_button": (120, 30),
    "new_game": (300, 50),
    "production": (130, 30),
    "orders": (100, 50),
    "small": (100, 40),
    "puppet_option": (160, 30),
    "top_orders_panel_button": (90, 40),
    "orders_panel_button": (80, 40),
    "orders_panel_button_2": (70, 40),
    "left_ui_bar": (120, 50),
    "song": (700, 30),
    "asset_folder": (200, 36),
    "asset_file": (270, 22),
    "save_file": (745, 30),
    "small_save_button": (100, 30),
    "diplomatic": (200, 30),
    "keys": (60, 30),
    "menu": (200, 45),
    "medium": (200, 50),
    # Scenario settings screen: same width as "medium" but thinner, so a whole
    # scenario's worth of toggles/sliders can fit on one screen without scrolling.
    "scenario_setting_button": (200, 36),
    "scenario_setting_info": (32, 32),
    "editor_ui": (300, 40),
    "FTAP": (400, 40),
    "large": (300, 80),
    "list_row": (520, 34),
    # File browser: sidebar shortcut, entry row, toolbar nav and bottom toggle.
    "browser_place": (210, 30),
    "browser_row": (890, 30),
    "browser_nav": (70, 32),
    "browser_tool": (170, 40),
    # Checkbox list: one toggleable row, and the small buttons above it.
    "checkbox_row": (700, 30),
    "checkbox_tool": (150, 32),
    # Editor forms (unit/country editors, turn overrides).
    "form_row": (420, 30),
    "form_tool": (130, 32)
}

COLOR_GOLD_HIGHLIGHT = (255, 215, 0)
COLOR_SUCCESS_GREEN = (100, 255, 100)
COLOR_DIM_BORDER = (100, 100, 100)

COLOR_RESOURCE_MANPOWER = (100, 200, 255)
COLOR_RESOURCE_MATERIALS = (180, 180, 180)
COLOR_RESOURCE_FUEL = (200, 100, 255)
COLOR_SLIDER_TRACK = (100, 100, 100)
COLOR_SLIDER_HANDLE = (200, 200, 200)

COLOR_CHROMA_PINK = (255, 0, 255)

# https://smilebasic.com/en/e-manual/manual28/
EDITOR_COLOR_PALETTE = [
    (0,0,0),            # Black
    (32,32,32),         # Very Dark Grey
    (64,64,64),         # Dark Grey
    (96,96,96),         # Darkish Grey
    (128,128,128),      # Grey
    (196,196,196),      # Light Grey
    (220,220,220),      # Very Light Grey
    (255,255,255),      # White
    
    (255,96,96),        # Light Red
    (255,200,20),       # Light Orange
    (255,255,128),      # Light Yellow
    (96,255,128),       # Lime
    (128,255,255),      # Light Indigo
    (64,64,255),        # Light Blue
    (200,64,255),       # Light Purple
    (255,128,255),      # Light Pink

    (255,0,0),          # Red
    (255,160,16),       # Orange
    (255,255,32),       # Yellow
    (0,192,0),          # Green
    (80,200,255),       # Indigo
    (0,0,255),          # Blue
    (160,32,255),       # Purple
    (255,96,208),       # Pink
    
    (196,0,0),          # Dark Red
    (200,120,12),       # Dark Orange
    (200,200,0),        # Dark Yellow
    (0,128,0),          # Dark Green
    (60,160,200),       # Dark Indigo
    (0,0,196),          # Dark Blue
    (120,16,200),       # Dark Purple
    (200,80,160),       # Dark Pink

    # (160,128,96),       # Oak Tree
    # (255,208,160),      # White Skin

    (128,0,0),          # Very Dark Red
    (160,80,10),        # Brown
    (128,128,0),        # Very Dark Yellow
    (0,64,0),           # Very Dark Green
    (32,128,160),       # Very Dark Indigo
    (0,0,128),          # Very Dark Blue
    (80,12,160),        # Very Dark Purple
    (160,60,120),       # Very Dark Pink

    # (128,0,128),        # Austria-Hungary
]

# ==========================================
# MESSAGING APP UI
# ==========================================

# Unread-mail badge on the map screen; the rest of the messaging layout lives
# in screens/map_related_screens/messages.py.
MSG_NOTIFICATION_COLOR = (255, 50, 50)

# ==========================================
# CAMERA & MAP RENDERING
# ==========================================

MAX_CAMERA_ZOOM = 10.0
MAX_Y_TILT_FACTOR = 0.0 # The maximum compression of the Y axis (0.6 = 60% of original height)
APPLY_TILT_TO_OVERLAYS = False # Whether the tilt compresses icons and text overlays
APPLY_TILT_TO_ARROWS = True # Whether the tilt compresses movement arrows
APPLY_TILT_TO_STATUS_ICONS = True # Whether the tilt compresses training, disbanding, and construction icons
APPLY_TILT_TO_TEXT = True

COLOR_SKYBOX = (135, 206, 235) # Light Sky Blue

# Water brightness stuff
OCEAN_DARK_BLUE = (10, 20, 40)
# OCEAN_DARK_BLUE = (5, 10, 20)
OCEAN_LIGHT_BLUE = (40, 100, 180)
# OCEAN_LIGHT_BLUE = (20, 40, 80)

DEFAULT_OCEAN_DARK_BLUE = (10, 20, 40)
DEFAULT_OCEAN_LIGHT_BLUE = (40, 100, 180)

# Toggle this to False if you want to strictly hide names on areas <= 3 provinces
SHOW_SMALL_TERRITORY_NAMES = False
NAME_FADE_START = 4.0
NAME_FADE_WINDOW = 1.5

NAME_MIN_TILES_TO_SHOW = 3      # when to ignore showing islands
NAME_ABS_MIN_TILES_TO_SHOW = 1  # if a country only has this many tiles

# ==========================================
# DEFAULT UNIT STATS (Fallbacks)
# ==========================================

DEFAULT_UNIT_HP = 100
DEFAULT_UNIT_ATK = 5
DEFAULT_UNIT_DEF = 0
DEFAULT_UNIT_SPD = 1
DEFAULT_UNIT_MORALE = 100.0

def _gen_roman(n):
    val = [100, 90, 50, 40, 10, 9, 5, 4, 1]
    syb = ["C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
    res, i = "", 0
    while n > 0:
        for _ in range(n // val[i]):
            res += syb[i]
            n -= val[i]
        i += 1
    return res

ROMAN_NUMERALS = {i: _gen_roman(i) for i in range(1, 101)}


# ==========================================
# CALCULATIONS & Weights
# ==========================================

# Used in queries.py to estimate a nation's total economic power
ECONOMY_WEIGHT_MANPOWER = 1
ECONOMY_WEIGHT_MATERIALS = 10
ECONOMY_WEIGHT_FUEL = 20

# Used in queries.py to calculate military strength (Attack + Defense + (Health / DIVISOR))
MILITARY_STRENGTH_HEALTH_DIVISOR = 10.0

MAX_COMBAT_ATTACKERS = 5 # Only the top 5 units will deal damage in combat

# ==========================================
# BOMBARDMENT
# ==========================================

# Base unit classes allowed to fire on a nearby tile instead of moving, mapped
# to how many tiles their shells reach (1 = directly adjacent only).
# Matched against queries.get_base_unit_name, so every level of the family counts.
BOMBARDMENT_UNITS = {
    "Artillery": 1,
    "WW1 Railroad Gun": 2,
    "WW2 Railroad Gun": 2,
    "Landkreuzer P.1000 Ratte": 2,
    "Landkreuzer P.1500 Monster": 2,
    "Railgun": 3,
    "Dreadnought": 1,
    "Battleship": 1,
    "Aircraft Carrier": 2
}

# Fallback range for anything that can bombard without a listed range.
DEFAULT_BOMBARDMENT_RANGE = 1

# Scale of the barrage sprite drawn between the gun and its target.
BOMBARDMENT_ARROW_SCALE = 1.0

# ==========================================
# CONVOY & TRUCK LOGIC
# ==========================================

CONVOY_MAX_HP = 1000
TRUCK_MAX_HP = 1000
CONVOY_ATK = 100
TRUCK_ATK = 100
TRUCK_CONVERT_TURNS = 3

# ==========================================
# OVERLAY ICONS & SCALES
# ==========================================

ICON_TRAINING = "Training"
ICON_CONSTRUCTION = "Hammer"
ICON_DISBANDING = "Disbanding"
ICON_CONVERTING_TO_CONVOY = "Convoying"
ICON_CONVERTING_TO_LAND = "Unconvoying"
ICON_CONVERTING_TO_TRUCK = "Trucking"
ICON_CONVERTING_TO_SHIP = "Untrucking"

# Maps a unit's CONVERT order "to" field to the icon shown over the unit while converting
CONVERSION_ICONS = {
    "Convoy": ICON_CONVERTING_TO_CONVOY,
    "Land Unit": ICON_CONVERTING_TO_LAND,
    "Truck": ICON_CONVERTING_TO_TRUCK,
    "Ship": ICON_CONVERTING_TO_SHIP,
}
ICON_BOMBARDMENT = "Bombardment Arrows"
ICON_BOMBARDMENT_LONG = "Long Range Bombardment Arrows"
ICON_BOMBARDMENT_VERY_LONG = "Very Long Range Bombardment Arrows"

# Barrage sprite keyed by the firing unit's range. The highest key at or below
# the unit's range wins, so longer-ranged guns added later reuse the long art.
BOMBARDMENT_ARROW_ICONS = {
    1: ICON_BOMBARDMENT,
    2: ICON_BOMBARDMENT_LONG,
    3: ICON_BOMBARDMENT_VERY_LONG
}

OVERLAY_STATUS_ICON_SCALE = 0.6
OVERLAY_STATUS_ICON_ALPHA = 180  # 0 to 255 transparency scale

# Handle disproportionate raw assets
SYMBOL_BASE_SCALES = {
    "Motorized Infantry": 0.4,
    "Mechanized Infantry": 0.4,
    "Truck": 0.4,
    "Cavalry": 0.8,
    "Militia": 0.8,
}

# Base unit classes that belong to the TANKS column despite not having
# "Tank" or "Armored Car" in their name (see queries.get_ordered_unit_groups).
TANK_GROUP_EXTRAS = [
    "WW1 Railroad Gun",
    "WW2 Railroad Gun",
    "Landkreuzer P.1000 Ratte",
    "Landkreuzer P.1500 Monster",
    "Railgun"
]

# Unit classes whose research key isn't just their lowercased name (see
# queries.get_unit_tech_key). The "Type" suffix is part of the unit name only.
UNIT_TECH_KEY_OVERRIDES = {
    "motorized_infantry_type": "motorized_infantry",
    "mechanized_infantry_type": "mechanized_infantry",
    "infantry_fighting_vehicle_type": "infantry_fighting_vehicle",
}

# motorized_infantry/mechanized_infantry/infantry_fighting_vehicle (see
# UNIT_TECH_KEY_OVERRIDES above) aren't leveled techs of their own - each is
# unlocked by a one-time "vehicle" tech and then tracks the nation's own
# infantry_type year exactly (see queries.get_infantry_family_year).
VEHICLE_INFANTRY_GATES = {
    "motorized_infantry": "trucks",
    "mechanized_infantry": "armored_personnel_carriers",
    "infantry_fighting_vehicle": "infantry_fighting_vehicle",
}

LARGE_ICON_BUILDING_GROUPS = ["industry", "recruitment"]
BUILDING_ICON_SCALE = 1.0

# ==========================================
# STAT ICONS
# ==========================================

ICON_ATTACK = "Attack"
ICON_DEFENSE = "Shield"
ICON_HEALTH = "Heart"
ICON_SPEED = "Lightning"
ICON_WARNING = "Warning"
ICON_BOMBARD_RANGE = "Target"

# ==========================================
# MAP UNIT DISPLAY (HOI4 STYLE)
# ==========================================

UNIT_BOX_WIDTH = 80
UNIT_BOX_HEIGHT = 40
UNIT_BOX_BG_COLOR = (80, 80, 80, 200)
UNIT_BOX_TEXT_COLOR = (255, 255, 255)

# ==========================================
# AI & SPECTATOR CONFIGURATION
# ==========================================

SPECTATOR_CAN_EDIT_PRODUCTION = True

# --- NEW: Expeditionary Force Weight ---
# A higher number means the AI prefers defending its own borders over helping allies.
# 5 means it will secure its own borders with at least 5 units before sending units away.
AI_EXPEDITION_WEIGHT = 5

# ==========================================
# AI PROACTIVE DIPLOMACY THRESHOLDS
# ==========================================

AI_RELATION_FACTION_THRESHOLD = 50
AI_WAR_STRENGTH_THRESHOLD = 1.2 # AI must be 20% stronger on the shared border to declare war
AI_GLOBAL_STRENGTH_THRESHOLD = 0.8 # AI must have at least 80% of the target's total alliance + economic power to consider war
AI_DIPLO_COOLDOWN = 12 # How many turns before AI can retry a rejected/ignored proactive diplomatic action. -1 means infinite.
AI_WAR_COOLDOWN = 12
AI_CLAIM_COOLDOWN = 12 # How many turns the AI waits before trying to fabricate another claim
AI_WEAK_NEIGHBOR_STRENGTH_RATIO = 0.60 # Target must be this much weaker (e.g. 60% of AI's power) to be bullied with claims
TURNS_TO_WAIT_BEFORE_WAR = 12 # How many turns from the start of the game the AI waits before declaring wars
AI_WAR_DECLARATION_CHANCE = 0.50 # 50% chance the AI actually declares war when conditions are met
MIN_TURNS_FOR_CEASEFIRE = 2 # Turns that must occur before the ai allows ceasefires

# Distraction Weight
# How much the AI values the strength of their target's current enemies. 
# 0.8 means if the target is fighting someone with 1000 strength, the AI feels 800 points braver.
AI_ENEMY_DISTRACTION_WEIGHT = 0.8
AI_BORDER_DISTRACTION_MULTIPLIER = 0.5 # Multiplier for border units actively engaged in combat with a third party

# ==========================================
# AI RECRUITMENT PREFERENCES
# ==========================================

AI_OFFENSIVE_UNIT_PREFERENCE = [
    "Cavalry",
    # the stuff below requires fuel, make sure the ai can handle it
    "WW1 Armored Car",
    "WW1 Tank",
    "Light Tank",
    "Medium Tank",
    "Main Battle Tank"
]

AI_NAVAL_UNIT_PREFERENCE = [
    "Dreadnought",
    "Battleship",
    "Destroyer",
    # "Aircraft Carrier"
]

AI_UPKEEP_TARGETS = {
    "manpower": 0.80,
    "materials": 0.60,
    "fuel": 0.70
}

AI_INFANTRY_TO_TANK_RATIO = 1 # Tanks honestly have no downsides aside from long deployment time so spamming them is pretty good tbh

AI_WAR_UPKEEP_MULTIPLIER = 1.5

AI_MAX_NAVY_RATIO = 0.5 # Maximum percentage of an AI's army that can be navy
AI_CONVOY_ESCORT_WEIGHT = 1 # Negative weight to pull pathing warships towards convoys
AI_CONVOY_COMBAT_WEIGHT = 50 # MASSIVE priority to escort convoys actively being attacked
AI_CONVOY_DANGER_SHIP_WEIGHT = 25 # Priority for convoys near enemy ships
AI_CONVOY_DANGER_COAST_WEIGHT = 10 # Priority for convoys near enemy borders/coasts

AI_SEA_PATH_PENALTY_MULTIPLIER = 2.0 # Land troops prefer land routes unless sea is this much faster (2.0 = 2x faster)

AI_REINFORCE_COMBAT_WEIGHT = 20 # Pulls pathing land units toward active battles

AI_MIN_COAST_FOR_NAVY = 8 # Tiles needed to justify building a navy

AI_TANK_MIN_BASE_THRESHOLD = 2000
AI_TANK_MIN_DIVISOR = 2000

AI_MIN_MATERIALS_FOR_CONSTRUCTION = 15000

AI_SURPLUS_MANPOWER_FOR_CORING = 2000 # Manpower above this triggers AI to prioritize coring uncored provinces

AI_CONSCRIPTION_MIN_MANPOWER = 5000
AI_CONSCRIPTION_PANIC_MANPOWER = 10000
AI_CONSCRIPTION_PANIC_MATERIALS = 1000
AI_CONSCRIPTION_EMERGENCY_MANPOWER = 50000

AI_CONVERSION_MIN_MATERIALS = 500
AI_CONVERSION_PANIC_MATERIALS = 5000
AI_CONVERSION_PANIC_FUEL = 500
AI_CONVERSION_EMERGENCY_MATERIALS = 50000

MAX_RESEARCH_TURN_SIMULATION = 5000

# ==========================================
# DIPLOMATIC ACTION CLASSIFICATIONS
# ==========================================

# Actions that happen instantly and do not require the target's consent
UNILATERAL_ACTIONS = [
    "WAR_DECLARATION",
    "BREAK_ALLIANCE",
    "KICK_FACTION_MEMBER",
    "LEAVE_FACTION",
    "DISBAND_FACTION",
    "JUSTIFY_WARGOAL",
    "ANNEX_PUPPET",
    "RELEASE_PUPPET",
    "TAKE_PUPPETS",
    "CANCEL_MILITARY_ACCESS",
    "REVOKE_MILITARY_ACCESS"
]

# Proposals that require the target to explicitly Accept or Reject
BILATERAL_ACTIONS = [
    "JOIN_WARS",
    "FACTION_INVITE",
    "JOIN_FACTION_REQ",
    "CEASEFIRE",
    "CALL_TO_ARMS",
    "CREATE_FACTION",
    "PEACE_TREATY",
    "TRADE",
    "REQ_MILITARY_ACCESS"
]

# ==========================================
# RELATION MODIFIERS & COLORS
# ==========================================

REL_MOD_AT_WAR = -100
REL_MOD_IN_FACTION = 80
REL_MOD_RECENT_WAR = -20
REL_MOD_RECENT_FACTION = -20
REL_MOD_COMMON_ENEMY = 20

REL_MOD_PER_CLAIM = -5
REL_MOD_MAX_CLAIM_PENALTY = -50

REL_MOD_REMOVE_CORE = -30
REL_MOD_MAX_REMOVE_CORE_PENALTY = -150

COLOR_REL_MAX_POS = (100, 100, 200) # Light blue at 200
COLOR_REL_POS = (0, 255, 0)         # Green at 100
COLOR_REL_NEU = (255, 255, 255)     # White at 0
COLOR_REL_NEG = (255, 0, 0)         # Red at -100
COLOR_REL_MAX_NEG = (150, 0, 0)     # Very dark red at -200

# ==========================================
# RANDOM PROCEDURAL MAP GENERATION DEFAULTS
# ==========================================

PROCEDURAL_MAP_WIDTH = 1200
PROCEDURAL_MAP_HEIGHT = 400
PROCEDURAL_PROVINCE_COUNT = 600

# ==========================================
# REBELLION SETTINGS
# ==========================================

REBELLION_MIN_MILITIA = 4
REBELLION_MAX_MILITIA = 8
REBELLION_SECONDARY_MILITIA = 2
REBELLION_TERTIARY_MILITIA = 1
REBELLION_MAX_SPREAD_DISTANCE = 3

REBELLION_TERMS = [
    "Rebellion", "Uprising", "Revolt", "Unrest", "Riot",
    "Radicals", "Dissenters", "Revolutionaries", "Insurrection",
    "Mutiny", "Insurgency", "Resistance", "Liberation Front",
    "Movement", "Defiance", "Sedition", "Agitation",
    "Partisans", "Guerrillas", "Separatists", "Outcry",
]

# ==========================================
# FILE PATHS
# ==========================================

# Directories
ASSETS_ROOT_DIR = "assets"
ASSETS_DIR = "assets/images"
TERRAINS_DIR = "assets/terrains"
BACKGROUNDS_DIR = "assets/backgrounds"
FLAGS_DIR = "assets/flags"
PORTRAITS_DIR = "assets/portraits"
MUSIC_DIR = "assets/music"
SAVES_DIR = "saves"
TOURNAMENT_SAVES_DIR = "tournament_saves"
SCENARIOS_HISTORICAL_DIR = "scenarios/historical"
SCENARIOS_ALTERNATE_DIR = "scenarios/alternate"
SCENARIOS_CUSTOM_DIR = "scenarios/map_editor"
BASE_MAPS_DIR = "base_maps"

# Default Map Assets
DEFAULT_FLAG_PATH = "assets/flags/default_flag.png"
DEFAULT_PORTRAIT_PATH = "assets/portraits/default_portrait.png"
PROVINCE_BG_FILE = "Province.png"
SETTINGS_BG_FILE = "Settings.png"
MENU_BG_FILE = "Menu.png"

# Scrolling checkerboard drawn behind any screen that has no bg_image_path
# (see GameState.draw_checkerboard_background). The on-disk file is a plain
# red template -- it exists only to define the light/dark contrast ratio
# between squares; at runtime it's recolored to match each screen's own
# bg_color instead of being drawn red.
CHECKERBOARD_TEMPLATE_FILE = "Checkerboard.png"
CHECKERBOARD_SCROLL_SPEED = 18  # pixels/sec, moves down-and-right

FLAG_SIZE = (60, 40)
PORTRAIT_SIZE = (60, 60)

# Fonts & Sounds
FONT_PATH_DEFAULT = "assets/fonts/W95F.otf"
FONT_PATH_MAP = "assets/fonts/PixelOperatorMonoHB.ttf"

# UI Specific Font Paths
FONT_PATH_DATE = "assets/fonts/PixelOperatorMonoHB.ttf"
FONT_PATH_TOP_COUNTRY = "assets/fonts/PixelOperatorMonoHB.ttf"
FONT_PATH_RESOURCES = "assets/fonts/W95F.otf"

SOUND_CLICK_PATH = "assets/sounds/Slider.wav"
SOUND_SLIDER_PATH = "assets/sounds/Slider.wav"

# JSON Data
UNIT_DATA_PATH = "data/json/unit_data.json"
COUNTRIES_DATA_PATH = "data/json/countries_data.json"
RESEARCH_TEMPLATE_PATH = "data/json/research_template.json"
BUILDING_DATA_PATH = "data/json/building_data.json"
SETTINGS_CONFIG_PATH = "data/json/settings_config.json"
ACTIVE_ALBUMS_PATH = "data/json/active_albums.json"
STARTING_SONG_PATH = "data/json/starting_song.json"
HILDEHRAND_CHOICE_PATH = "data/json/hildehrand_choice.json"

# ==========================================
# HISTORY & SAVING SETTINGS
# ==========================================

RECORD_HISTORY = True
HISTORY_INDENT = None # this used to be 4
SAVE_INDENT = 4

# Camera Settings
DEFAULT_MOUSE_BUTTON_TOGGLE = "RIGHT"
DRAG_MOUSE_BUTTON_TOGGLE = DEFAULT_MOUSE_BUTTON_TOGGLE # Options: "RIGHT", "LEFT", "BOTH"