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

# --- Province Menu UI Layout (X, Y, Width, Height) ---
PROVINCE_UI = {
    "units_box": (860, 70, 210, 350),
    "buildings_box": (860, 440, 210, 350),
    "faction_box": (SCREEN_WIDTH - 200, 200, 210, 200),
    "mail_box": (SCREEN_WIDTH - 200, 420, 210, 300)
}

# --- Editor UI Placement ---
EDIT_COUNTRY_UI_X1 = 50
EDIT_COUNTRY_UI_X2 = 450
EDIT_COUNTRY_UI_X3 = 850

EDITOR_BOT_BTN_START_X = SCREEN_WIDTH - 120
EDITOR_BOT_BTN_STEP_X = 110

# --- View Toggle UI Layout ---
VIEW_BTN_START_X = 10
VIEW_BTN_STEP_X = 50
VIEW_BTN_ROW1_Y = SCREEN_HEIGHT - 50
VIEW_BTN_ROW2_Y = SCREEN_HEIGHT - 100

# --- Action Buttons UI Layout ---
ACTION_BTN_X = SCREEN_WIDTH - 200
ACTION_BTN_START_Y = 70
ACTION_BTN_STEP_Y = 60

# --- Left UI Bar Placement ---
LEFT_UI_BAR_X = 20
BTN_EDIT_NATION_Y = 120
BTN_RESEARCH_Y = 220
BTN_SAVE_Y = 320
BTN_ECONOMY_Y = 420
BTN_MESSAGES_Y = 520
BTN_SPECTATOR_Y = SCREEN_HEIGHT - 50

# --- Economy Screen Placement ---
ECON_CONVERT_BTN_Y = 600
ECON_CONVERT_BTN_X1 = SCREEN_WIDTH // 2 - 250
ECON_CONVERT_BTN_X2 = SCREEN_WIDTH // 2 + 50

# --- Sidebar Info Panel ---
SIDEBAR_INFO_X = 580
SIDEBAR_INFO_Y = 70
SIDEBAR_INFO_WIDTH = 300
SIDEBAR_INFO_HEIGHT = 450

# --- Feedback Text Placement ---
# ie the green text stuff
FEEDBACK_TEXT_OFFSET_X = 620
FEEDBACK_TEXT_Y = 220

UI_LEFT_OFFSET = 160

# This probably needs to be implemented in more places than just orders.py / buttons.py
TOP_BAR_UI_CENTER_Y = 10
BOTTOM_BAR_UI_CENTER_Y = SCREEN_HEIGHT - 50

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

# --- File Paths ---
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

# How to make a god import:
#   import data.constants as c
#   c.UI_LEFT_OFFSET