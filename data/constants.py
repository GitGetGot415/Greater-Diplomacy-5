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
    "materials": 10,
    "fuel": 1
}

UPKEEP_MODIFIERS = {
    "manpower": 0.10,
    "materials": 0.05,
    "fuel": 0.20
}

DAYS_PER_TURN = 10

# Non-core penalties
NON_CORE_MULTIPLIERS = {
    "manpower": 0.0,
    "materials": 0.5,
    "fuel": 0.5
}

# ==========================================
# STARTING BUILDINGS
# ==========================================

DEFAULT_STARTING_FACTORY = "Basic Factory"
DEFAULT_STARTING_REFINERY = "Experimental Refinery"

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
TOP_BAR_COUNTRY_X = 180
TOP_BAR_COUNTRY_Y = 15
TOP_BAR_TEXT_BG_PADDING = 10
TOP_BAR_TEXT_BG_ALPHA = 180

# --- View Toggle UI Layout ---
VIEW_BTN_START_X = 10
VIEW_BTN_STEP_X = 50
VIEW_BTN_ROW1_Y = SCREEN_HEIGHT - 50
VIEW_BTN_ROW2_Y = SCREEN_HEIGHT - 100

# --- Left UI Bar Placement ---
LEFT_UI_BAR_X = 20
LEFT_UI_BAR_STEP_Y = 80
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
    "diplomatic_box": (10, 150, 140, 450),
    "mail_box": (400, 300, 150, 300)
}

DIPLOMATIC_INFO_TITLE = "Diplomatic Info"

# --- Sidebar Info Panel ---
SIDEBAR_INFO_X = 900
SIDEBAR_INFO_Y = 70
SIDEBAR_INFO_WIDTH = 300
SIDEBAR_INFO_HEIGHT = 640 # Increased to accommodate the new terrain image and buildings list

# --- Action Buttons UI Layout ---
ACTION_BTN_X = 200
ACTION_BTN_START_Y = 300
ACTION_BTN_STEP_Y = 33

ORDER_BTN_X = SCREEN_WIDTH - 250

# ==========================================
# SETTINGS
# ==========================================

DEFAULT_AI_MODE = "OLLAMA"

# --- Settings UI Layout ---
SETTINGS_GEMINI_BOX_X = 130
SETTINGS_GEMINI_BOX_Y = SCREEN_HEIGHT - 50
SETTINGS_GEMINI_BOX_W = 170
SETTINGS_GEMINI_BOX_H = 40

# Add the Ollama box coordinates (we can reuse the same spot since they toggle)
SETTINGS_OLLAMA_BOX_X = 130
SETTINGS_OLLAMA_BOX_Y = SCREEN_HEIGHT - 50
SETTINGS_OLLAMA_BOX_W = 170
SETTINGS_OLLAMA_BOX_H = 40

SETTINGS_CHATGPT_BOX_X = 130
SETTINGS_CHATGPT_BOX_Y = SCREEN_HEIGHT - 50
SETTINGS_CHATGPT_BOX_W = 170
SETTINGS_CHATGPT_BOX_H = 40

SETTINGS_CLAUDE_BOX_X = 130
SETTINGS_CLAUDE_BOX_Y = SCREEN_HEIGHT - 50
SETTINGS_CLAUDE_BOX_W = 170
SETTINGS_CLAUDE_BOX_H = 40

# ==========================================
# GAME RULES & TIMING
# ==========================================

START_YEAR = 1910
END_YEAR = 1950
AI_THINKING_COOLDOWN = 0 # how long does an ai have to wait before thinking again
RESEARCH_TIMELINE_SPACING = 80 # Width between years on the research timeline

BASE_RESEARCH_POINTS_PER_DAY = 10 

# ==========================================
# INPUT SETTINGS
# ==========================================

KEY_REPEAT_DELAY = 400
KEY_REPEAT_INTERVAL = 40

# ==========================================
# UNIT OBSOLESCENCE
# ==========================================
OBSOLESCENCE_RULES = {
    "WW1 Armored Car": ["armored_car"],
    "WW1 Tank": ["medium_tank", "heavy_tank"],
}

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
    "medium_square": (50, 50),
    "tech_square": (80, 80),
    "orders": (100, 50),
    "small": (100, 40),
    "left_ui_bar": (120, 50),
    "diplomatic": (200, 30),
    "medium": (200, 50),
    "large": (300, 80)
}

# ==========================================
# MESSAGING APP UI
# ==========================================

MSG_LEFT_PANE_W = 280
MSG_INPUT_H = 80
MSG_BG_DARK = (25, 25, 30)
MSG_BG_LIGHT = (35, 35, 45)
MSG_BUBBLE_PLAYER = (40, 100, 200)
MSG_BUBBLE_PLAYER_DIPLO = (180, 60, 60) # Added: Player diplomatic red
MSG_BUBBLE_AI = (60, 60, 80)
MSG_BUBBLE_AI_DIPLO = (200, 100, 0) # Added: AI diplomatic orange
MSG_NOTIFICATION_COLOR = (255, 50, 50)
MSG_BUBBLE_MAX_WIDTH_RATIO = 0.6

# ==========================================
# CAMERA & MAP RENDERING
# ==========================================

MAX_CAMERA_ZOOM = 10.0
OCEAN_DARK_BLUE = (10, 20, 40)
OCEAN_LIGHT_BLUE = (40, 100, 180)

# Toggle this to False if you want to strictly hide names on areas <= 3 provinces
SHOW_SMALL_TERRITORY_NAMES = False
NAME_FADE_START = 2.0
NAME_FADE_WINDOW = 1.5

# ==========================================
# DEFAULT UNIT STATS (Fallbacks)
# ==========================================

DEFAULT_UNIT_HP = 100
DEFAULT_UNIT_ATK = 5
DEFAULT_UNIT_DEF = 0
DEFAULT_UNIT_SPD = 1

# ==========================================
# CONVOY & TRUCK LOGIC
# ==========================================

CONVOY_MAX_HP = 1000
TRUCK_MAX_HP = 1000
CONVOY_ATK = 0
TRUCK_ATK = 0
TRUCK_CONVERT_TURNS = 3

# ==========================================
# OVERLAY ICONS & SCALES
# ==========================================

ICON_TRAINING = "Training"
ICON_CONSTRUCTION = "Hammer"
ICON_DISBANDING = "Disbanding"
OVERLAY_STATUS_ICON_SCALE = 0.6
OVERLAY_STATUS_ICON_ALPHA = 180  # 0 to 255 transparency scale

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
    "Destroyer",
    # "Aircraft Carrier"
]

AI_UPKEEP_TARGETS = {
    "manpower": 0.60,
    "materials": 0.20,
    "fuel": 0.40
}

AI_WAR_UPKEEP_MULTIPLIER = 1.5

# ==========================================
# FILE PATHS
# ==========================================

# Directories
ASSETS_DIR = "assets/images"
TERRAINS_DIR = "assets/terrains" # Added terrains directory
BACKGROUNDS_DIR = "assets/backgrounds"
FLAGS_DIR = "assets/flags"
PORTRAITS_DIR = "assets/portraits"
SAVES_DIR = "saves"
SCENARIOS_DIR = "scenarios"
BASE_MAPS_DIR = "base_maps"

# Default Map Assets
DEFAULT_FLAG_PATH = "assets/flags/default_flag.png"
DEFAULT_PORTRAIT_PATH = "assets/portraits/default_portrait.png"
PROVINCE_BG_FILE = "Province.png"
SETTINGS_BG_FILE = "Settings.png"
MENU_BG_FILE = "Menu.png"

FLAG_SIZE = (60, 40)
PORTRAIT_SIZE = (60, 60)

# Fonts & Sounds
FONT_PATH_DEFAULT = "assets/fonts/W95F.otf"
# FONT_PATH_DEFAULT = "assets/fonts/idk.ttf"
FONT_PATH_MAP = "assets/fonts/OpenSans-Regular.ttf"
SOUND_CLICK_PATH = "assets/sounds/click.mp3"
SOUND_SLIDER_PATH = "assets/sounds/slider.wav"

# JSON Data
UNIT_DATA_PATH = "data/json/unit_data.json"
COUNTRIES_DATA_PATH = "data/json/countries_data.json"
RESEARCH_TEMPLATE_PATH = "data/json/research_template.json"
BUILDING_DATA_PATH = "data/json/building_data.json"
SETTINGS_CONFIG_PATH = "data/json/settings_config.json"

# ==========================================
# FALLBACK / MANUAL AI RESPONSES
# ==========================================

AI_FALLBACK_RESPONSES = {
    "AI_OFF_ACCEPT": "We accept your proposal.",
    "AI_OFF_REJECT": "We reject your proposal.",
    "AI_OFF_MESSAGE": "Message received (AI is OFF).",
    "GENERIC_ACCEPT": "We have made our decision.",
    "GENERIC_MESSAGE": "Message received.",
    "OLLAMA_ERROR": "Ollama server error or timeout.",
    "API_ERROR": "API Error.",
    "TIMEOUT": "Timeout.",
    "BETRAYAL": "You will regret this betrayal.",
    "ALLIANCE_BROKEN": "We won't forget this.",
    "FACTION_ABANDONED": "We will not forget your abandonment.",
    "FACTION_DISBANDED": "It is a shame to see our alliance broken.",
    "ACCEPTED_HELP": "We gratefully accept your assistance in our conflicts.",
    "INVITE_IGNORED": "Your faction invitation was ignored and has expired.",
    "JOIN_REQ_IGNORED": "Your request to join the faction was ignored and has expired.",
    "CEASEFIRE_IGNORED": "Your ceasefire offer was ignored and has expired.",
    "CALL_TO_ARMS_IGNORED": "Your call to arms was ignored and has expired.",
    "CANT_JOIN_FACTION": "We cannot join a new faction while we are already bound to our own treaties.",
    "NOT_AT_WAR": "We would offer military aid to {target}, but they are not currently at war.",
    "KICKED_FROM_FACTION": "We will not forget being expelled from the alliance."
}