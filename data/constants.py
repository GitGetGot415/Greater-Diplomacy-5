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
UNPLAYABLE_NATIONS = ["None", "Unclaimed", "Ocean", "Lakes"]

# Width and Height
SCREEN_WIDTH = 1600
SCREEN_HEIGHT = 900

UI_LEFT_OFFSET = 160

# This probably needs to be implemented in more places than just orders.py / buttons.py
TOP_BAR_UI_CENTER_Y = 10
BOTTOM_BAR_UI_CENTER_Y = SCREEN_HEIGHT - 50

# Economy Data
BASE_YIELDS = {
    "manpower": 50,
    "materials": 50,
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
ASSETS_DIR = "assets"
FLAGS_DIR = "assets/flags"
PORTRAITS_DIR = "assets/portraits"
SAVES_DIR = "saves"
SCENARIOS_DIR = "scenarios"
BASE_MAPS_DIR = "base_maps"

# Default Map Assets
DEFAULT_FLAG_PATH = "assets/flags/default_flag.png"
DEFAULT_PORTRAIT_PATH = "assets/portraits/default_portrait.png"
DEFAULT_TERRAIN_MAP_PATH = "map_tools/terrain_map.png"
DEFAULT_ID_MAP_PATH = "map_tools/provinces_id_map.png"
DEFAULT_MAP_DATA_PATH = "map_tools/map_data.json"

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