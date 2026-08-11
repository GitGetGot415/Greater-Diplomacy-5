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

# How many messages a nation's inbox keeps. Inboxes live in nation_data and
# are saved wholesale, so an uncapped one grows the save file for the whole
# length of a game. Newest first, so the oldest fall off the end.
INBOX_MAX_MESSAGES = 300

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
    "fuel": 0.50
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

# Each person may have "info" (free-text bio shown in the popup) and/or "links"
# (a list of {"text", "url"} shown as clickable lines below the info text).
# A person with neither is rendered as plain, non-clickable text.
CREDITS_DATA = [
    {
        "main_text": "Lead Developer: ",
        "people": [
            {
                "link_text": "GitGetGot415",
                "info": "Owns the repository",
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/GitGetGot415"}]
            }
        ]
    },
    {
        "main_text": "Music: ",
        "people": [
            {
                "link_text": "GitGetGot415",
                "info": "Made all the music",
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/GitGetGot415"}]
            }
        ]
    },
    {
        "main_text": "GitHub Contributors: ",
        "people": [
            {
                "link_text": "litbrb",
                "info": (
                    "Added:\n"
                    "- Submarines\n"
                    "- Terrain art\n"
                    "- Icons for: Credits, Load Game, Map Editor, New Game"
                ),
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/litbrb"}]
            }
        ]
    },
    {
        "main_text": "Map Makers: ",
        "people": [
            {
                "link_text": "neptune2019",
                "info": ("Maps Added:\n"
                "- Kaiserreich 1936\n"
                "- 1939 fixed schizo scenario"),
                "align": "left",
            },
        ]
    },
    {
        "main_text": "Tools: ",
        "people": [
            {
                "link_text": "github-advanced-security[bot]",
                "info": "Improved encryption for tournaments",
                "align": "left",
                "links": [{"text": "Docs", "url": "https://docs.github.com/en/get-started/learning-about-github/about-github-advanced-security"}]
            },
            {
                "link_text": "claude",
                "info": "Massive refactors to consolidate / organize code",
                "align": "left",
                "links": [{"text": "GitHub", "url": "https://github.com/claude"}]
            }
        ]
    }
]

SHOW_FPS = False

# Whether the Map screen's ocean uses the scrolling checkerboard pattern
# (see GameState.draw_checkerboard_background) instead of a flat fill. Off by
# default since it can visually read as unusual water for players who don't
# expect it.
CHECKERBOARD_WATER = False

GAME_VERSION = "v25"
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

# --- RESEARCH ---
DEFAULT_FORCE_TIME_APPROPRIATE_RESEARCH = False

# --- BATTLE ROYALE ---
BATTLE_ROYALE_MODE = False
DEFAULT_BATTLE_ROYALE = False
DEFAULT_BOUNCE_TIEBREAKER = False

# --- FACTIONS ---
DISABLE_FACTIONS = False
DEFAULT_DISABLE_FACTIONS = False

# --- CORES ---
DISABLE_CORES = False
DEFAULT_DISABLE_CORES = False

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
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_KIMI_MODEL = "kimi-k2-0711-preview"

# OpenAI-compatible chat completion endpoints for the hosted providers that
# don't need a user-editable URL (unlike Ollama, which stores its URL in the
# "api_key" field because it has no key of its own).
CHATGPT_API_URL = "https://api.openai.com/v1/chat/completions"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
# Moonshot AI is the company; Kimi is the model line they ship under that API host.
KIMI_API_URL = "https://api.moonshot.ai/v1/chat/completions"
# Anthropic's Messages API, used for Claude -- different auth/shape than the
# OpenAI-compatible providers above, so it gets its own caller.
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_API_VERSION = "2023-06-01"

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
ORDERS_PANEL_CAMERA_X_OFFSET = 0

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
# How many LLM requests a turn's batch has in flight at once, when the player
# hasn't moved the slider. A hosted provider answers concurrent requests
# independently, so fanning out is close to free throughput; a local Ollama is
# one model on one GPU, and four concurrent generations there just thrash it.
DEFAULT_AI_THREADS = 4
DEFAULT_AI_THREADS_LOCAL = 1

# Wall-clock ceiling for one turn's LLM batch, in seconds. Whatever hasn't come
# back by then falls back, so a slow or unreachable provider costs a wait rather
# than a hung turn. 0 disables the limit.
DEFAULT_AI_TURN_BUDGET_SECONDS = 45

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
    "ai_opinion": (100, 30),
    "puppet_option": (100, 30),
    "swap_hildehrand": (120, 30),
    "automation_option": (200, 30),
    "top_orders_panel_button": (90, 40),
    "orders_panel_button": (60, 40),
    "orders_panel_button_2": (60, 40),
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
    "brick": (150, 50),
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

# ==========================================
# UI PALETTE / GEOMETRY
# ==========================================
# The shared vocabulary for chrome that every screen draws. Before these existed
# the same values were retyped as literals -- (200,200,200) alone appeared 79
# times -- so a palette tweak meant a repo-wide find-and-replace that always
# missed a few sites and left screens visibly out of step with each other.

# Body text, brightest to dimmest.
UI_TEXT_BRIGHT = (220, 220, 220)
UI_TEXT_LIGHT = (200, 200, 200)
UI_TEXT_DIM = (170, 170, 210)   # small column headers above list panes
UI_TEXT_MUTED = (150, 150, 150)

UI_ACCENT_BLUE = (100, 150, 255)

# Modal panels: the dim layer behind them, the box itself, and where the title
# sits relative to the box's top edge.
MODAL_OVERLAY_ALPHA = 200
MODAL_BG = (35, 35, 45)
MODAL_BORDER = UI_ACCENT_BLUE
MODAL_TITLE_Y_OFFSET = 14

# Panels layered over the live map (sidebar, order queue, diplomacy popup).
HUD_PANEL_BG = (30, 30, 50)
HUD_PANEL_BORDER = (100, 100, 250)

# Pixels per wheel notch. GameState.scroll_speed mirrors this; panels that roll
# their own wheel handling should read it from here rather than redeclaring it.
SCROLL_STEP = 30

# Yes/No confirmation buttons: size, and horizontal offset from the box centre.
CONFIRM_BTN_SIZE = (100, 40)
CONFIRM_BTN_DX = 130

ELLIPSIS = "..."

# Single-line text entry boxes. Nine screens each had their own fill/border
# pair; these are the values they all draw with now (see
# ui_elements.draw_text_box). The focused box lights up and gains a white edge.
INPUT_BG = (30, 30, 40)
INPUT_BG_ACTIVE = (60, 60, 80)
INPUT_BORDER = (150, 150, 150)
INPUT_BORDER_ACTIVE = (255, 255, 255)

# Back button placement. Full-screen menus anchor to the top-left corner;
# screens layered over the map sit beside the top UI bar instead.
BACK_BTN_TOPLEFT = (20, 20)
BACK_BTN_MAP_CENTER = (50, TOP_BAR_UI_CENTER_Y)

# Owner names that mean "nobody owns this". Deliberately NOT UNPLAYABLE_NATIONS:
# that list also carries "The Rot"/"Spectator"/"GLOBAL_EVENTS"/"FACTION_WAR_MAPS"
# and omits "", so substituting it would change which provinces count as empty.
OWNERLESS_OWNERS = ("Unclaimed", "None", "Ocean", "Lakes")
UNOWNED_LAND_OWNERS = ("Unclaimed", "None", "")

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
CONVOY_DEF = 0
TRUCK_DEF = 0
TRUCK_CONVERT_TURNS = 3

# Orders that span more than one turn and are therefore a standing commitment,
# not a plan to be re-derived. The AI wipes its units' orders every turn so it
# can rethink its movement; these are the ones it must NOT wipe, or the order
# is destroyed before the turn processor ever sees it.
MULTI_TURN_ORDER_TYPES = ("CONVERT", "DISBAND", "REPAIR")
# The above plus bombardment, which occupies the unit's turn even though it
# resolves within it. A unit doing any of these cannot also move.
ORDERS_BLOCKING_MOVEMENT = MULTI_TURN_ORDER_TYPES + ("BOMBARD",)

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

# ==========================================
# AI PERSONALITY (map_logic/ai/ai_personality.py)
# ==========================================

# Seed every nation's procedural temperament is derived from. A scenario stores
# its own on first use, so changing this only affects scenarios that never had
# one; changing it will not reroll personalities in a save already underway.
DEFAULT_AI_PERSONALITY_SEED = "greater-diplomacy-5"

# What counts as a trait worth mentioning when describing a nation.
AI_TRAIT_NOTABLE_HIGH = 0.68
AI_TRAIT_NOTABLE_LOW = 0.32

AI_RELATION_FACTION_THRESHOLD = 50
AI_WAR_STRENGTH_THRESHOLD = 1.2 # AI must be 20% stronger on the shared border to declare war
AI_GLOBAL_STRENGTH_THRESHOLD = 0.8 # AI must have at least 80% of the target's total alliance + economic power to consider war
AI_DIPLO_COOLDOWN = 12 # How many turns before AI can retry a rejected/ignored proactive diplomatic action. -1 means infinite.
AI_WAR_COOLDOWN = 12
AI_CLAIM_COOLDOWN = 12 # How many turns the AI waits before trying to fabricate another claim
AI_WEAK_NEIGHBOR_STRENGTH_RATIO = 0.60 # Target must be this much weaker (e.g. 60% of AI's power) to be bullied with claims

# ==========================================
# AI DESIRE WEIGHTS (map_logic/ai/ai_opinion.py)
# ==========================================
# War used to be two thresholds and nothing else. These turn the same
# quantities into degrees, and add the things the old logic had no way to say:
# that we like them, that we are already fighting two wars, that we promised not
# to. The odds terms and the appetite terms each sum to 1.0, so a nation with
# perfect odds and maximum appetite sits at 2.0 before restraint pulls it back.

# How the two halves of the decision trade off. They are averaged rather than
# added -- see the note in war_desire -- so these sum to 1.0.
AI_W_ODDS = 0.55            # can we win
AI_W_APPETITE = 0.45        # do we want to

AI_W_BORDER = 0.6           # local superiority on the shared front
AI_W_GLOBAL = 0.4           # overall alliance and economic weight
AI_ODDS_STEEPNESS = 6.0     # how sharply confidence turns over around the crossover

AI_W_CLAIM = 0.45           # how much of their land we already claim
AI_W_AGGRO = 0.35           # temperament, independent of the odds
AI_W_AMBITION = 0.20        # appetite for land we have no claim on yet

AI_W_RELATION = 0.55        # good relations suppress war. Previously: nothing did.
AI_W_OVEREXTENSION = 0.45   # every war already being fought makes the next one less appealing

# Measured over 20 turns of the 1939 scenario against the old boolean, which
# declared 33 wars and ended 8. This gives 23 declared and 7 ended: a
# noticeably less trigger-happy world where a larger share of wars actually
# resolve, without making it inert. 0.62 gives 16/6 and 0.70 gives 11/7, both
# too quiet for a scenario that should catch fire.
AI_WAR_DESIRE_THRESHOLD = 0.55
# Lower than the war bar: fabricating a claim is a step toward a war, taken
# before the odds are settled, and it is how a war becomes legal at all.
AI_CLAIM_DESIRE_THRESHOLD = 0.45
AI_WAR_LOAD_SATURATION = 3.0    # wars at which a nation counts as fully committed

# Peace. Losing, tired and cautious all push toward the table.
AI_W_PEACE_LOSING = 0.5
AI_W_PEACE_WEARINESS = 0.35
AI_W_PEACE_CAUTION = 0.15
AI_WAR_WEARINESS_TURNS = 25.0
AI_PEACE_CEASEFIRE_THRESHOLD = 0.5
# Giving up land takes more than agreeing to stop. Above zero and reachable,
# where the old rule refused a claims demand unconditionally -- which is the
# reason AI wars never once ended with territory changing hands.
AI_PEACE_CEDE_LAND_THRESHOLD = 0.72

# Trade. How much a good relationship discounts what we hand over.
AI_TRADE_GOODWILL_DISCOUNT = 0.5

# Alliances and faction invitations.
AI_W_ALLY_RELATION = 0.5
AI_W_ALLY_SHARED_ENEMY = 0.35
AI_W_ALLY_WEAKNESS = 0.15   # the weak seek protection
AI_ALLIANCE_DESIRE_THRESHOLD = 0.55

# How many proposals one nation may have in flight at once. The pass used to
# allow exactly one per target with no comparison between them, so whichever
# section ran first won the slot.
AI_MAX_ACTIONS_PER_TURN = 3

# Proposing a trade. Stock counts toward what a nation can spare, spread over
# this many turns, so a full warehouse is tradeable but not all at once.
AI_TRADE_STOCK_TURNS = 20.0
AI_TRADE_OFFER_FRACTION = 0.5
AI_TRADE_MIN_AMOUNT = 250

# How each action reads in a prompt or an event log.
# ==========================================
# LLM DIRECTOR (map_logic/ai/ai_director.py)
# ==========================================

# Per-country override of whether a nation is model-driven, stored on
# nation_data so it saves with everything else. AUTO defers to the global
# immersion level.
AI_TIER_AUTO = "AUTO"
AI_TIER_ALWAYS = "ALWAYS"
AI_TIER_NEVER = "NEVER"

# The immersion levels, in order. MAJOR sits between FULL and ABSOLUTE: the
# model drives the countries a player actually notices, which is great-power
# diplomacy at a fraction of what ABSOLUTE costs.
AI_IMMERSION_LEVELS = ("LITE", "FULL", "MAJOR", "ABSOLUTE")

# Who counts as a major power: the strongest handful, plus everyone whose doings
# a player would see anyway.
AI_MAJOR_POWER_FRACTION = 0.15
AI_MAJOR_POWER_MIN = 6
AI_MAJOR_POWER_MAX = 12
AI_MAJOR_POWER_PROVINCE_WEIGHT = 5.0   # size counts, but an army counts more

# The index the model answers with to decline to act. Must not collide with a
# candidate index, so it is not a number.
AI_DIRECTOR_NONE_CID = "none"

# A verdict at or above this confidence is stated to the model as settled and
# cannot be overruled -- those are structural rules, not judgement calls. Below
# it the recommendation is offered with its reasoning and the leader may differ.
AI_VERDICT_OVERRIDE_MAX_CONFIDENCE = 0.85

# An action the model pushed for while answering a proposal is filed rather than
# executed, and reconsidered next turn against the ordinary rules. True restores
# the old behaviour, where such an action skipped every war prerequisite.
AI_LLM_DIRECT_RETALIATION = False
AI_REQUEST_LIFETIME = 3          # turns a filed request stays worth acting on
AI_REQUEST_REASON_LENGTH = 120
# How much the leader having asked for it counts. Enough to break a tie, not
# enough to carry a war the nation has no appetite for.
AI_LLM_REQUEST_BONUS = 0.25

# ==========================================
# COMMITMENTS AND SUMMITS
# (map_logic/ai/ai_commitments.py, ai_negotiation.py)
# ==========================================

# How much a non-aggression pact restrains a nation, before temperament. Scaled
# by loyalty, so a faithless country breaks one when the prize is big enough and
# a loyal one very nearly will not -- a pact that bound everyone identically
# would be a rule rather than a promise.
AI_COMMITMENT_WEIGHT = 0.55
AI_COMMITMENT_MIN_HOLD = 0.25    # even the faithless honour a pact a little
AI_COMMITMENT_HISTORY_MAX = 40   # settled promises kept per nation; this is saved
AI_DEFAULT_REPUTATION = 0.7      # benefit of the doubt before any record exists

# Summits. Each pair is one job, and the exchanges inside it are sequential, so
# wall clock is rounds x latency rather than pairs x rounds x latency.
AI_NEGOTIATION_MAX_PAIRS = 4
AI_NEGOTIATION_ROUNDS = 2
AI_NEGOTIATION_COOLDOWN = 6      # turns before the same pair meets again
AI_NEGOTIATION_MIN_PRESSURE = 0.35
AI_NEGOTIATION_DEFAULT_TURNS = 20
AI_NEGOTIATION_MAX_TERM_TURNS = 60
AI_TRANSCRIPT_LINE_LENGTH = 400
AI_NEGOTIATION_MAX_TERMS = 4

# What makes a pair worth convening, roughly in the order a historian would
# expect. These are added, then scaled by how well the other side keeps its word.
AI_PRESSURE_COMMON_ENEMY = 0.55      # co-belligerents who have formalised nothing
AI_PRESSURE_WEARY_WAR = 0.60         # two exhausted enemies; this is how wars end
AI_PRESSURE_FRIENDLY = 0.40          # friends without a bloc
AI_PRESSURE_CONTESTED = 0.25         # a grievance not yet worth a war
AI_PRESSURE_NEIGHBOUR = 0.15
AI_PRESSURE_SALVAGEABLE_RELATION = -60   # below this there is nothing to discuss

AI_ACTION_PHRASES = {
    "WAR_DECLARATION": "declare war on",
    "CEASEFIRE": "offer a ceasefire to",
    "PEACE_TREATY": "offer peace terms to",
    "JOIN_FACTION_REQ": "ask to join the faction of",
    "CREATE_FACTION": "propose founding a faction with",
    "FACTION_INVITE": "invite into our faction",
    "CALL_TO_ARMS": "call to arms",
    "JOIN_WARS": "offer to join the wars of",
    "REQ_MILITARY_ACCESS": "request military access through",
    "TRADE": "propose a trade with",
    "BREAK_ALLIANCE": "break our alliance with",
}

# Baseline desirability for actions with no appetite function of their own.
# Access is cheap to ask for and often the difference between being able to
# fight a shared war at all -- but it is a tactical convenience, and loses to
# anything that changes who a nation's friends are.
AI_SCORE_MILITARY_ACCESS = 0.55

# A nation at war with no allies at all wants that fixed more than it wants
# anything else, whatever it happens to think of the only bloc on offer.
AI_SCORE_DEFENSIVE_FACTION = 0.78
AI_SCORE_CALL_TO_ARMS = 0.50
AI_SCORE_JOIN_WARS = 0.45
AI_SCORE_CEASEFIRE_UNREACHABLE = 0.80   # a war we physically cannot fight is pure cost
AI_SCORE_TRADE = 0.40                   # useful, rarely urgent

# How badly a war must be going before the AI sues for peace. Below the bar at
# which it would accept a ceasefire offered to it: asking costs standing, so it
# waits a little longer than it would to say yes.
AI_PEACE_OFFER_THRESHOLD = 0.62
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

# LEGACY. These lists no longer decide anything -- map_logic/ai/ai_unit_eval.py
# scores every unit the nation can actually build from its stats, so a change to
# unit_data.json changes what the AI builds without anyone editing a list here.
# Kept defined because mods read them, and because get_best_offensive_unit /
# get_best_naval_unit still exist as (now stat-derived) wrappers.
#
# For the record, what they used to do: get_best_preferred_unit walks them in
# REVERSE, so the last entry won. That meant the AI always reached for Main
# Battle Tanks and Destroyers the moment it had a single level of either,
# whatever they cost, and never built Heavy Tanks, Super Heavy Tanks, Artillery,
# Submarines or Carriers at all -- three of those aren't even on the lists.
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

# ==========================================
# AI UNIT VALUATION (map_logic/ai/ai_unit_eval.py)
# ==========================================
# Weights for the stat-derived replacement for the lists above. They are applied
# to values normalised against the mean of whatever the nation can currently
# build, so they stay meaningful after any rebalance of unit_data.json.

# What a unit contributes, given how combat actually resolves:
#  - only the top MAX_COMBAT_ATTACKERS by attack deal damage, so offence is raw attack
#  - incoming damage is split across ALL defenders, then each subtracts its own
#    defense flat, so a cheap high-defense body is worth far more than its stats
#    suggest and every extra body thins the share for the whole stack
AI_W_OFFENSE = 1.0
AI_W_DURABILITY = 1.0
# Flat, not scaled by health: damage is divided by the NUMBER of defenders, so
# every body thins the volley for the stack by the same amount whatever it is
# made of. Its real effect is to make cheap units better value per point of pain.
AI_W_SOAK = 0.35
AI_W_BOMBARD = 0.6      # bombardment ignores the combat-width cap and takes no return fire

# Floor on the damage a unit takes, as a fraction of its share of the volley.
# Without it, defense >= share divides by zero and an unkillable unit scores
# infinitely; with it, stacking defense has strong but finite returns.
AI_MIN_DAMAGE_FRACTION = 0.10

# A unit that takes ten turns to build is worth less than the same value
# arriving now. 0.5 = value scales with the square root of build time.
AI_TIME_EXPONENT = 0.5

# Turns of upkeep counted against a unit's purchase price.
AI_UPKEEP_HORIZON = 20

# Floor on how scarce a resource can get, so pricing saturates instead of
# dividing by zero when a nation has no income and no stockpile of something.
AI_MIN_RESOURCE_SLACK = 0.05

# Army composition. Targets are per frontline tile; a role at its target is
# multiplied by AI_ROLE_DIMINISH, so roles trade off against each other instead
# of being bought to a hardcoded ratio.
AI_ROLE_DIMINISH = 0.35

# How much to spend on depth versus firepower, as a ratio of resources -- NOT of
# unit counts. Only MAX_COMBAT_ATTACKERS units per tile can fire, so the assault
# target is a count the combat rules hand us directly; bodies then get a
# comparable share of the budget, which at 1.0 means "about as much again".
#
# It has to be expressed as spend rather than as a number of units, because a
# heavy tank costs seventeen infantry. A count-based depth target quietly
# committed 90% of the budget to armour and produced an army that lost to every
# mixed composition in a round-robin under the real combat rules.
#
# 2.0 was picked by measurement, not taste: armies built at each ratio were
# fought against eleven fixed compositions under the real combat rules, and
# 1.5-3.0 all win comfortably while 4.0 collapses into pure infantry and loses
# to everything. Sitting in the middle of that plateau rather than at its edge.
AI_LINE_SPEND_RATIO = 2.0
AI_BOMBARD_SPEND_RATIO = 0.15   # guns are support, not the main line
AI_MIN_ROLE_TARGET = 2.0    # even a landlocked one-province nation wants a couple of each

# A unit is ASSAULT when this much of its combat value comes from attack rather
# than from staying alive and taking up space; everything else on land is a LINE
# body. Below 0.5 on purpose: a unit that does most of its work shooting still
# has to survive to do it, so the best attackers are never pure offence.
AI_ASSAULT_OFFENSE_SHARE = 0.45

# Stop buying when the best remaining option is worth less than this fraction of
# the best option overall -- the AI has better uses for the resources.
AI_MARGINAL_FLOOR = 0.15

# Saving up. If the best unit the nation cannot yet afford is worth more than
# this much more than the best it can, it banks the turn's budget instead --
# but only when income actually closes the gap inside AI_SAVE_UP_TURNS, so a
# nation with no industry never sits waiting for a tank it will never afford.
AI_SAVE_UP_THRESHOLD = 0.6
AI_SAVE_UP_TURNS = 4

# Fallback for how hard the enemy hits when a nation is at peace and has no
# frontline to measure, expressed as a multiple of the mean buildable attack.
AI_PEACETIME_THREAT_MULTIPLIER = 3.0

AI_UPKEEP_TARGETS = {
    "manpower": 0.80,
    "materials": 0.60,
    "fuel": 0.70
}

AI_INFANTRY_TO_TANK_RATIO = 1 # Tanks honestly have no downsides aside from long deployment time so spamming them is pretty good tbh

AI_WAR_UPKEEP_MULTIPLIER = 1.5

AI_MAX_NAVY_RATIO = 0.5 # LEGACY: superseded by AI_NAVY_PER_COAST_TILE
AI_NAVY_PER_COAST_TILE = 0.5 # Warships wanted per coastal tile, as a role target
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

# How much an economic tech's per-turn yield counts against a military tech's
# one-off improvement to the units on offer. The two are in different units --
# income per turn versus a better division -- so this is the exchange rate
# between them, and raising it makes the AI build its economy before its army.
AI_TECH_ECONOMY_WEIGHT = 1.0

# How many of the RESEARCH_SLOTS are held for a tech that unlocks a unit.
# Economic techs are repeatable and compound, so on value alone they take every
# slot forever -- true enough about this economy, and a terrible way to fight a
# war. Which military tech fills the slot still comes from the valuation.
AI_RESEARCH_MILITARY_SLOTS = 1

# How many turns of extra income an economic tech is credited with. Longer means
# more willingness to invest in industry before army.
AI_TECH_ECONOMY_HORIZON = 30.0

# How long a BUILDING gets to earn back what it cost to put up. A separate
# number from the one above, which they used to share: that one scales an
# income stream against an army, while this one is a payback period, and a
# building keeps producing long after the thirty turns a division is costed
# against. At thirty every building in the game -- including the first Basic
# Factory -- read as a loss, which is the opposite of the error it was meant
# to correct. Sixty turns is roughly when a factory upgrade breaks even.
AI_BUILDING_PAYBACK_TURNS = 60.0

# How many building levels the AI will research ahead of what it has actually
# constructed. A province can only ever queue the next item in its chain, so
# research further ahead than this buys nothing it can act on for many turns.
# One spare level keeps the pipeline full without letting it run away.
AI_MAX_BUILDING_RESEARCH_LEAD = 1

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

# How a puppet and its master regard each other. Asymmetric on purpose: a
# master is fonder of the puppet it installed than the puppet is of the master.
REL_MOD_MASTER_OF = 50   # our view of a nation we puppeted
REL_MOD_PUPPET_OF = 20   # our view of the nation that puppeted us

REL_MOD_PER_CLAIM = -5
REL_MOD_MAX_CLAIM_PENALTY = -50

REL_MOD_REMOVE_CORE = -30
REL_MOD_MAX_REMOVE_CORE_PENALTY = -150

# Consequences of keeping or breaking your word. The broken-promise grudge is
# deliberately durable -- decay 0, and long -- because a betrayal nobody
# remembers next decade is not a betrayal, it is a free move.
REL_MOD_BROKEN_COMMITMENT = -40
REL_MOD_BROKEN_COMMITMENT_TURNS = 60
REL_MOD_HONORED_COMMITMENT = 15
REL_MOD_REFUSED_CALL_TO_ARMS = -25
REL_MOD_FOUGHT_TOGETHER = 10
REL_MOD_GIFT = 10

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
# These three are rebindable in Settings, so main.py overwrites them at startup
# with whatever was persisted. The DEFAULT_ forms are the shipped values, and
# are what settings loading falls back to -- reading the mutable name there
# would hand back the last value loaded instead of the actual default.
DEFAULT_SAVES_DIR = "saves"
DEFAULT_TOURNAMENT_SAVES_DIR = "tournament_saves"
DEFAULT_SCENARIOS_CUSTOM_DIR = "scenarios/map_editor"

SAVES_DIR = DEFAULT_SAVES_DIR
TOURNAMENT_SAVES_DIR = DEFAULT_TOURNAMENT_SAVES_DIR
SCENARIOS_HISTORICAL_DIR = "scenarios/historical"
SCENARIOS_ALTERNATE_DIR = "scenarios/alternate"
SCENARIOS_CUSTOM_DIR = DEFAULT_SCENARIOS_CUSTOM_DIR
BASE_MAPS_DIR = "base_maps"
MODS_DIR = "mods"

# Default Map Assets
DEFAULT_FLAG_PATH = "assets/flags/default_flag.png"
DEFAULT_PORTRAIT_PATH = "assets/portraits/default_portrait.png"
PROVINCE_BG_FILE = "Province.png"
SETTINGS_BG_FILE = "Settings.png"

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
HISTORICAL_LEADERS_PATH = "data/json/historical_leaders.json"
HISTORICAL_LEADERS_DEFAULT_PATH = "data/json/historical_leaders_DEFAULT.json"

# ==========================================
# HISTORY & SAVING SETTINGS
# ==========================================

RECORD_HISTORY = True
HISTORY_INDENT = None # this used to be 4
SAVE_INDENT = 4
# Level 1 gets ~13x on history's very repetitive JSON for a third of level 6's
# CPU, and the write it saves is bigger than the compression it costs.
HISTORY_GZIP_LEVEL = 1
# Marks a history snapshot whose images have already been scrubbed, so a save
# does not redo identical work for every turn it has ever recorded.
HISTORY_SCRUBBED_KEY = "_scrubbed"

# Camera Settings
DEFAULT_MOUSE_BUTTON_TOGGLE = "RIGHT"
DRAG_MOUSE_BUTTON_TOGGLE = DEFAULT_MOUSE_BUTTON_TOGGLE # Options: "RIGHT", "LEFT", "BOTH"

# ==========================================
# RUNTIME SETTINGS
# ==========================================
# A handful of settings are mirrored onto this module because the code that
# reads them -- the renderer, the camera, the save paths -- is too low-level to
# reach the Controller. Every one of them used to be copied across by hand at
# six different call sites, and the lists had already fallen out of step.

#: setting name (as used by data/io/settings_schema.py) -> constant name here.
RUNTIME_SETTINGS = {
    "drag_mouse_toggle": "DRAG_MOUSE_BUTTON_TOGGLE",
    "saves_dir": "SAVES_DIR",
    "custom_scenarios_dir": "SCENARIOS_CUSTOM_DIR",
    "ocean_light_color": "OCEAN_LIGHT_BLUE",
    "ocean_dark_color": "OCEAN_DARK_BLUE",
    "tournament_saves_dir": "TOURNAMENT_SAVES_DIR",
    "checkerboard_water": "CHECKERBOARD_WATER",
}


def apply_runtime_settings(values):
    """Mirrors the settings above onto this module.

    `values` is any mapping keyed by setting name; keys it does not carry are
    left alone, so a screen that changed one setting can pass just that one.
    Order is the declaration order above, which is the order the boot path used
    -- data/platform.py reads SAVES_DIR when asked, not at import, so nothing
    downstream depends on a different order, but keeping one is free.
    """
    for name, constant in RUNTIME_SETTINGS.items():
        if name in values:
            globals()[constant] = values[name]
