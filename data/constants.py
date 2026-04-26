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

# Handy list to check if terrain is water in several movement/combat files
WATER_TERRAINS = ["ocean", "coastal_sea", "inland_sea", "lakes"]

# Owner groupings for logic and UI checks
WATER_NATIONS = ["Ocean", "Lakes"]
UNPLAYABLE_NATIONS = ["None", "Unclaimed", "Ocean", "Lakes", "Spectator", "GLOBAL_EVENTS"]

# Width and Height
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720

# --- Feedback Text Placement ---
# ie the green text stuff
FEEDBACK_TEXT_OFFSET_X = 620
FEEDBACK_TEXT_Y = 220

# Economy Data
BASE_YIELDS = {
    "manpower": 50,
    "materials": 20,
    "fuel": 0
}

UPKEEP_MODIFIER = 0.05

DAYS_PER_TURN = 10

# Non-core penalties
NON_CORE_MULTIPLIERS = {
    "manpower": 0.0,
    "materials": 0.5,
    "fuel": 0.5
}

# ==========================================
# ECONOMY SCREEN
# ==========================================

# --- Economy Screen Placement ---
ECON_CONVERT_BTN_Y = 600
ECON_CONVERT_BTN_X1 = SCREEN_WIDTH // 2 - 250
ECON_CONVERT_BTN_X2 = SCREEN_WIDTH // 2 + 50

# ==========================================
# UI BARS
# ==========================================

UI_LEFT_OFFSET = 160

# --- Resource HUD UI Layout ---
RESOURCE_HUD_START_X = 300
RESOURCE_HUD_SPACING = 200
RESOURCE_HUD_HEIGHT_OFFSET = 40
RESOURCE_HUD_BG_ALPHA = 200

# This probably needs to be implemented in more places than just orders.py / buttons.py (does it? what is this for again?)
# I think this is implemented in everywhere it needs to be... right?
TOP_BAR_UI_CENTER_Y = 10
BOTTOM_BAR_UI_CENTER_Y = SCREEN_HEIGHT - 50

# --- Top Bar Text Placement ---
TOP_BAR_DATE_Y = 20
TOP_BAR_COUNTRY_X = 200
TOP_BAR_COUNTRY_Y = 20
TOP_BAR_TEXT_BG_PADDING = 10
TOP_BAR_TEXT_BG_ALPHA = 180

# --- View Toggle UI Layout ---
VIEW_BTN_START_X = 10
VIEW_BTN_STEP_X = 50
VIEW_BTN_ROW1_Y = SCREEN_HEIGHT - 50
VIEW_BTN_ROW2_Y = SCREEN_HEIGHT - 100

# --- Left UI Bar Placement ---
LEFT_UI_BAR_X = 20
BTN_EDIT_NATION_Y = 120
BTN_RESEARCH_Y = 220
BTN_SAVE_Y = 320
BTN_ECONOMY_Y = 420
BTN_MESSAGES_Y = 520
BTN_SPECTATOR_Y = SCREEN_HEIGHT - 50

# ==========================================
# EDIT COUNTRY
# ==========================================

# --- Editor UI Placement ---
EDIT_COUNTRY_UI_X1 = 50
EDIT_COUNTRY_UI_X2 = 450
EDIT_COUNTRY_UI_X3 = 850

EDITOR_BOT_BTN_START_X = SCREEN_WIDTH - 120
EDITOR_BOT_BTN_STEP_X = 110

# ==========================================
# PROVINCE MENU
# ==========================================

# --- Province Menu UI Layout (X, Y, Width, Height) ---
PROVINCE_UI = {
    "units_box": (860, 70, 210, 250),
    "buildings_box": (860, 340, 210, 250),
    "faction_box": (SCREEN_WIDTH - 200, 200, 210, 200),
    "mail_box": (SCREEN_WIDTH - 200, 420, 210, 300)
}

# --- Sidebar Info Panel ---
SIDEBAR_INFO_X = 580
SIDEBAR_INFO_Y = 70
SIDEBAR_INFO_WIDTH = 300
SIDEBAR_INFO_HEIGHT = 450

# --- Action Buttons UI Layout ---
ACTION_BTN_X = 200
ACTION_BTN_START_Y = 250
ACTION_BTN_STEP_Y = 60

# ==========================================
# GAME RULES & TIMING
# ==========================================

START_YEAR = 1850
AI_THINKING_COOLDOWN = 0 # how long does an ai have to wait before thinking again

# ==========================================
# GLOBAL COLORS & PALETTES
# ==========================================

UI_COLORS = {
    "red": ((200, 0, 0), (255, 50, 50)),
    "orange": ((200, 100, 0), (255, 150, 50)),
    "yellow": ((200, 200, 0), (255, 255, 50)),
    "purple": ((200, 0, 200), (255, 50, 255)),
    "pink": ((200, 100, 100), (255, 150, 150)),
    "green": ((0, 150, 0), (0, 200, 0)),
    "light_blue": ((100, 100, 200), (150, 150, 255)),
    "blue": ((0, 0, 200), (50, 50, 255)),
    "grey": ((100, 100, 100), (150, 150, 150))
}

SIZES = {
    "small_square": (40, 40),
    "tech_square": (80, 80),
    "small": (100, 40),
    "left_ui_bar": (120, 50),
    "medium": (200, 50),
    "large": (300, 80)
}

# ==========================================
# FILE PATHS
# ==========================================

# Directories
ASSETS_DIR = "assets/images"
FLAGS_DIR = "assets/flags"
PORTRAITS_DIR = "assets/portraits"
SAVES_DIR = "saves"
SCENARIOS_DIR = "scenarios"
BASE_MAPS_DIR = "base_maps"

# Default Map Assets
DEFAULT_FLAG_PATH = "assets/flags/default_flag.png"
DEFAULT_PORTRAIT_PATH = "assets/portraits/default_portrait.png"

# Fonts & Sounds
FONT_PATH_DEFAULT = "assets/fonts/idk.ttf"
SOUND_CLICK_PATH = "assets/sounds/click.mp3"
SOUND_SLIDER_PATH = "assets/sounds/slider.wav"

# JSON Data
UNIT_DATA_PATH = "data/json/unit_data.json"
COUNTRIES_DATA_PATH = "data/json/countries_data.json"
RESEARCH_TEMPLATE_PATH = "data/json/research_template.json"
BUILDING_DATA_PATH = "data/json/building_data.json"
SETTINGS_CONFIG_PATH = "data/json/settings_config.json"