from data.platform import IS_WEB
from data import research_display
from data.io.starting_defaults import get_starting_value
from map_logic.diplomacy.action_definitions import BILATERAL_ACTIONS, UNILATERAL_ACTIONS

# Used for logical ownership assignment
WATER_MAPPING = {
    "ocean": "Ocean", 
    "coastal_sea": "Ocean", 
    "inland_sea": "Ocean", 
    "lakes": "Lakes"
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

# Tactical weapon pacing is independent of campaign attack and defense. Damage
# multipliers apply after the shared target restrictions and tactical defense.
# interval is between shots; reload follows the last round in a magazine/burst.
TACTICAL_WEAPONS = {
    "rifle": dict(label="Rifle",                            interval=2.0, rounds=1, reload=2.0, speed=1000.0, spread=1.5, damage=1.0, penetration=0.0, shell=False, soft_only=False),
    "musket": dict(label="Musket",                          interval=6.0, rounds=1, reload=6.0, speed=850.0, spread=2.8, damage=2.0, penetration=0.0, shell=False, soft_only=False),
    "rifle_musket": dict(label="Rifle-musket",              interval=5.0, rounds=1, reload=5.0, speed=950.0, spread=1.8, damage=2.0, penetration=0.0, shell=False, soft_only=False),
    "breech_rifle": dict(label="Breech-loading rifle",      interval=3.0, rounds=1, reload=3.0, speed=1100.0, spread=1.5, damage=1.5, penetration=0.0, shell=False, soft_only=False),
    "magazine_rifle": dict(label="Magazine rifle",          interval=0.9, rounds=5, reload=3.0, speed=1250.0, spread=1.2, damage=1.0, penetration=0.0, shell=False, soft_only=False),
    "semi_auto_rifle": dict(label="Semi-automatic rifle",   interval=0.5, rounds=8, reload=2.5, speed=1300.0, spread=1.2, damage=1.0, penetration=0.0, shell=False, soft_only=False),
    "assault_rifle": dict(label="Assault rifle",            interval=0.12, rounds=3, reload=1.1, speed=1350.0, spread=1.8, damage=0.5, penetration=0.0, shell=False, soft_only=False),
    "support_mg": dict(label="Support machine gun",         interval=0.12, rounds=6, reload=1.8, speed=1350.0, spread=2.4, damage=0.5, penetration=0.0, shell=False, soft_only=True),
    "vehicle_mg": dict(label="Machine gun",                 interval=0.12, rounds=8, reload=2.0, speed=1350.0, spread=2.8, damage=0.2, penetration=0.0, shell=False, soft_only=True),
    "light_cannon": dict(label="Light cannon",              interval=4.5, rounds=1, reload=4.5, speed=1900.0, spread=1.0, damage=1.8, penetration=2.0, shell=True, soft_only=False),
    "cannon": dict(label="Cannon",                          interval=6.0, rounds=1, reload=6.0, speed=2300.0, spread=0.8, damage=2.5, penetration=3.0, shell=True, soft_only=False),
    "heavy_cannon": dict(label="Heavy cannon",              interval=8.0, rounds=1, reload=8.0, speed=2500.0, spread=0.8, damage=3.4, penetration=4.0, shell=True, soft_only=False),
    "autocannon": dict(label="Autocannon",                  interval=0.3, rounds=3, reload=2.8, speed=1800.0, spread=1.5, damage=1.0, penetration=1.0, shell=True, soft_only=False),
    "artillery_shell": dict(label="Artillery shells",       interval=8.0, rounds=1, reload=8.0, speed=700.0, spread=1.0, damage=1.0, penetration=0.0, shell=True, soft_only=False, projectile="artillery_shell", range=2800.0, gravity=300.0),
    "torpedo": dict(label="Torpedoes",                      interval=0.5, rounds=4, reload=8.0, speed=300.0, spread=0.5, damage=1.0, penetration=0.0, shell=False, soft_only=False, projectile="torpedo", range=3000.0),
    "convoy_gun": dict(label="Convoy guns",                 interval=2.0, rounds=1, reload=2.0, speed=1000.0, spread=1.5, damage=1.0, penetration=0.0, shell=False, soft_only=False, projectile="bullet", range=600.0),
}
TACTICAL_VEHICLE_WEAPONS = {
    "armored_car": ("light_cannon", "vehicle_mg"),
    "light_tank": ("light_cannon", "vehicle_mg"),
    "tank": ("cannon", "vehicle_mg"),
    "heavy_tank": ("heavy_cannon", "vehicle_mg"),
    "ifv": ("autocannon", "vehicle_mg"),
}
# Body width, height, collision radius, and resistance to a passing shell.
# The renderer and all simulation clearance checks read the same dimensions.
TACTICAL_BODIES = {
    "infantry": (15, 15, 8.0, 1.0), "cavalry": (22, 16, 11.0, 1.0),
    "motorized": (30, 20, 15.0, 1.5), "mechanized": (34, 24, 17.0, 2.0),
    "ifv": (38, 26, 19.0, 2.5), "armored_car": (30, 20, 15.0, 2.0),
    "light_tank": (34, 24, 17.0, 3.0), "tank": (40, 28, 20.0, 4.0),
    "heavy_tank": (48, 34, 24.0, 5.0),
    "carrack": (50, 26, 28.2, 3.0), "ironclad": (62, 26, 33.7, 4.0),
    "destroyer": (124, 26, 63.4, 4.0), "pre_dreadnought": (124, 26, 63.4, 5.0),
    "dreadnought": (182, 46, 93.9, 6.0), "battleship": (182, 46, 93.9, 6.0),
    "aircraft_carrier": (208, 48, 106.8, 5.0), "submarine": (180, 24, 90.8, 3.0),
    "convoy": (50, 26, 28.2, 2.0),
}
TACTICAL_PENETRATION_DAMAGE_RETAINED = 0.6
TACTICAL_NAVAL_HULL_HEIGHT = 24.0
TACTICAL_MOVING_SPREAD = 1.5  # Extra degrees at full movement speed.
TACTICAL_TURNING_SPREAD = 1.0  # Extra degrees at full hull turn speed.
TACTICAL_SHELL_SPREAD_MULTIPLIER = 0.35  # Shell spread, including movement and turning, relative to bullets.
TACTICAL_MUZZLE_SECONDS = 0.12
TACTICAL_IMPACT_SECONDS = 0.18


# --- Text Input Limits ---
COUNTRY_NAME_MAX_LENGTH = 50


# Economy Data
BASE_YIELDS = {
    "manpower": 100,
    "materials": 10,
    "fuel": 2
}

GENERAL_RECRUITMENT_BONUS = 5 # Add this

RESOURCE_REFINING_BONUS_PER_LVL = 0.1 # +10% natural resource income per level

# Shared resource ordering used across economy and UI calculations.
# ECON_RESOURCE_KEYS is the canonical order for anything that touches all three;
# TRADE_RESOURCE_KEYS is the subset nations can actually hand to each other.
ECON_RESOURCE_KEYS = ("manpower", "materials", "fuel")
TRADE_RESOURCE_KEYS = ("materials", "fuel")

# Natural resource deposit names (province "resources" keys) and the economy
# resource each one adds to. Coal and Oil both add fuel, and Wheat and Fish both
# add manpower: each pair differs only in name and icon. The order here is the
# order of the editor pickers and the random map generator's choices.
NATURAL_RESOURCE_OUTPUTS = {
    "Iron": "materials",
    "Coal": "fuel",
    "Oil": "fuel",
    "Wheat": "manpower",
    "Fish": "manpower",
}

COUNTRY_BASE_YIELDS = {
    "manpower": 200,
    "materials": 100,
    "fuel": 0
}

BERGIUS_FUEL_BONUS = 100

UPKEEP_MODIFIERS = {
    "manpower": 0.10,
    "materials": 0.05,
    "fuel": 0.40
}

# reminder that base days per turn is the scenario default
# days per turn is what the game actually does
# if the days per turn is set to default then it uses the scenario default
DEFAULT_DAYS_PER_TURN = get_starting_value("random_setup", "base_days_per_turn")
DAYS_PER_TURN_OPTIONS = ["Default", 5, 10, 15, 30]

# Non-core penalties
NON_CORE_MULTIPLIERS = {
    "manpower": 0.1,
    "materials": 0.5,
    "fuel": 0.5
}

NON_CORE_BUILDING_MULTIPLIER = 0.5
CORE_BASE_COST_MANPOWER = 1000
CORE_SCALING_COST_MANPOWER = 500

CORE_CONSTRUCTION_TURNS = 24

REMOVE_CORE_TURNS = 2

SHOW_FPS = get_starting_value("settings_config.json", "show_fps")

# Show the sky checkerboard's reflection on the ocean. The pattern follows
# the map camera's position, zoom, and tilt. Disabled by default.
CHECKERBOARD_WATER = get_starting_value("settings_config.json", "checkerboard_water")

# How clicking a tile and switching the bottom-left view mode (Resources/
# Blank/Units/Economy) behave on the map screen. "CLASSIC" is how the game
# played before clicking ever jumped screens on its own: a tile click always
# just opens the plain province menu, and the view-mode row (wherever it is
# drawn -- Map, Orders, Production, Battle) only swaps the map overlay, never
# the screen you're on -- Orders/Battle/Production are reached only through
# their own explicit buttons. "PREEMPTIVE" is the newer behaviour: a click (or
# a view-mode button) jumps straight into whatever screen the current view
# mode implies. See screens/game/map_input.py's navigate_view_mode. Defaults to
# CLASSIC -- it is the behaviour the game shipped with the longest. Split from
# its default so Settings' "Reset
# Defaults" has a fixed value to reset back to rather than whatever this is
# currently set to.
DEFAULT_MAP_NAVIGATION_MODE = get_starting_value("settings_config.json", "map_navigation_mode")
MAP_NAVIGATION_MODE = DEFAULT_MAP_NAVIGATION_MODE

CONTROL_MODES = ("AUTO", "MOBILE", "DESKTOP")
DEFAULT_CONTROL_MODE = get_starting_value("settings_config.json", "control_mode")
CONTROL_MODE = DEFAULT_CONTROL_MODE

# How active battles are presented in the map's Units view.  COMPACT preserves
# the original presentation, hiding units beneath an opaque combat bubble;
# FULL leaves the units visible beneath a translucent bubble.
DEFAULT_BATTLE_DISPLAY_MODE = get_starting_value("settings_config.json", "battle_display_mode")
BATTLE_DISPLAY_MODE = DEFAULT_BATTLE_DISPLAY_MODE

# Whether army markers animate while compacting or expanding on the strategic
# map.  This is a presentation preference only; it never changes unit state.
DEFAULT_ARMY_GROUP_ANIMATIONS = get_starting_value("settings_config.json", "army_group_animations")
ARMY_GROUP_ANIMATIONS = DEFAULT_ARMY_GROUP_ANIMATIONS

# Show the fixed army card for owned units outside saved army groups.
DEFAULT_SHOW_UNCLAIMED = get_starting_value("settings_config.json", "show_unclaimed")
SHOW_UNCLAIMED = DEFAULT_SHOW_UNCLAIMED

# Which unit art set ui.rendering.symbol_loader draws unit icons from.
# "classic" is the flat assets/classic unit art set the game has always shipped with;
# any other style (e.g. "hanskolmer") discovers unit art from filenames under
# its own assets/<style> folder. Both fall back to "classic" when they do not
# cover a request. See screens/menus/unit_art.py for the picker.
DEFAULT_UNIT_ART_STYLE = get_starting_value("settings_config.json", "unit_art_style")
UNIT_ART_STYLE = DEFAULT_UNIT_ART_STYLE
UNIT_ART_STYLES = ("classic", "hanskolmer")

GAME_VERSION = "v50"
VERSION_CHECK_URL = "https://raw.githubusercontent.com/GitGetGot415/Greater-Diplomacy-5/main/version.txt"

# ==========================================
# SCENARIO SETTINGS
# ==========================================

# --- FOG OF WAR ---
USE_FOG_OF_WAR = get_starting_value("scenario_settings.json", "fog_of_war") # Toggle Fog of War mechanics on or off
DEFAULT_FOG_OF_WAR = get_starting_value("scenario_settings.json", "fog_of_war")
DEFAULT_FOG_OF_WAR_STRENGTH = get_starting_value("scenario_settings.json", "fog_of_war_strength")

# Tournament spectators authenticate with this deliberately public key, but
# receive the same no-territory fog perspective as a nation with no vision.
# Keep this distinct from the ordinary all-seeing ``Spectator`` game mode.
TOURNAMENT_SPECTATOR = "Tournament Spectator"
TOURNAMENT_SPECTATOR_KEY = "Spectator"
TOURNAMENT_SPECTATOR_ROLE = "TOURNAMENT_SPECTATOR"

# --- CASUS BELLI ---
CASUS_BELLI_REQUIRED = get_starting_value("scenario_settings.json", "casus_belli_required")
DEFAULT_CASUS_BELLI = get_starting_value("scenario_settings.json", "casus_belli_required")

# --- SURPRISE ATTACK ---
DEFAULT_SURPRISE_ATTACK = get_starting_value("scenario_settings.json", "surprise_attack")

# --- SCRIPTED EVENTS & AI ---
DEFAULT_USE_SCRIPTED_EVENTS = get_starting_value("scenario_settings.json", "use_scripted_events")
DEFAULT_AI_DISABLED = get_starting_value("scenario_settings.json", "ai_disabled")

# --- RESEARCH ---
DEFAULT_FORCE_TIME_APPROPRIATE_RESEARCH = get_starting_value("scenario_settings.json", "force_time_appropriate_research")

# --- BATTLE ROYALE ---
BATTLE_ROYALE_MODE = get_starting_value("scenario_settings.json", "battle_royale")
DEFAULT_BATTLE_ROYALE = get_starting_value("scenario_settings.json", "battle_royale")
DEFAULT_BOUNCE_TIEBREAKER = get_starting_value("scenario_settings.json", "bounce_tiebreaker")

# --- FACTIONS ---
DISABLE_FACTIONS = get_starting_value("scenario_settings.json", "disable_factions")
DEFAULT_DISABLE_FACTIONS = get_starting_value("scenario_settings.json", "disable_factions")

# --- CORES ---
DISABLE_CORES = get_starting_value("scenario_settings.json", "disable_cores")
DEFAULT_DISABLE_CORES = get_starting_value("scenario_settings.json", "disable_cores")

# --- REPAIRS ---
# Whether repairing a damaged unit costs nothing at all. Off makes repair cost
# materials/manpower/fuel proportional to missing health -- see
# screens.game.orders.Orders_Screen.repair_unit.
DEFAULT_FREE_REPAIRS = get_starting_value("scenario_settings.json", "free_repairs")

# ==========================================
# DEFAULTS & ASSETS
# ==========================================

MENU_BOTTOM_TEXT_LINK_COLOR = (150, 200, 255)


# AI Default Models
DEFAULT_GEMINI_MODEL = get_starting_value("settings_config.json", "gemini_model")
DEFAULT_CHATGPT_MODEL = get_starting_value("settings_config.json", "chatgpt_model")
DEFAULT_CLAUDE_MODEL = get_starting_value("settings_config.json", "claude_model")
DEFAULT_OLLAMA_MODEL = get_starting_value("settings_config.json", "ollama_model")
DEFAULT_DEEPSEEK_MODEL = get_starting_value("settings_config.json", "deepseek_model")
DEFAULT_KIMI_MODEL = get_starting_value("settings_config.json", "kimi_model")
DEFAULT_OPENROUTER_MODEL = get_starting_value("settings_config.json", "openrouter_model")


# Models that safely support Ollama's strict JSON grammar engine
OLLAMA_JSON_SUPPORTED_MODELS = ["llama", "mistral", "phi", "gemma"]

# ==========================================
# STARTING BUILDINGS
# ==========================================

DEFAULT_STARTING_FACTORY = "Basic Factory"
BASIC_FACTORY_BASE_COST_X = 4000
BASIC_FACTORY_COST_MULTIPLIER = 1000
BASIC_FACTORY_TURNS = 20

# controls how much material income a Basic Factory produces while it is still being built
BASIC_FACTORY_CONSTRUCTION_OUTPUT_FRACTIONS = (0.16, 0.32, 0.48, 0.64, 0.8)

# Forts are available independently of the research tree.  Their level is
# also the amount of defense they provide to friendly units during combat on
# the tile.
FORT_MAX_LEVEL = 20
FORT_DEFENSE_PER_LEVEL = 10

# ==========================================
# ECONOMY SCREEN
# ==========================================

DEFAULT_CONSCRIPTION_RATE = get_starting_value("country_defaults", "conscription_slider")
DEFAULT_FUEL_CONVERSION_RATE = get_starting_value("country_defaults", "mat_to_fuel_slider")
DEFAULT_RESEARCH_FUNDING_RATE = get_starting_value("country_defaults", "research_funding_slider")

FUEL_REFINING_CONVERSION_PER_LVL = 0.01

MAX_CONVERSION_SLIDER_VAL = 0.50
CONSCRIPTION_RATIO = 0.2 # 5 manpower -> 1 material
CONSCRIPTION_MAX_DAMAGE_BONUS = 0.20
FUEL_CONVERSION_RATIO = 0.1 # 10 materials -> 1 fuel

# ==========================================
# AUDIO DEFAULTS
# ==========================================


USE_SOLOUD = not IS_WEB # SoLoud has no browser build; Pygame Mixer is forced on web

DEFAULT_SFX_VOLUME = get_starting_value("settings_config.json", "sfx_volume")
DEFAULT_MUSIC_VOLUME = get_starting_value("settings_config.json", "music_volume")
# Retain this public alias; music and SFX defaults are read separately by settings_schema.
DEFAULT_AUDIO_PITCH = get_starting_value("settings_config.json", "music_pitch")
MUSIC_PITCH_TIMELINE_STATIC = "STATIC"
MUSIC_PITCH_TIMELINE_DYNAMIC = "DYNAMIC"
DEFAULT_MUSIC_PITCH_TIMELINE = get_starting_value("settings_config.json", "music_pitch_timeline")

# ==========================================
# UI BARS
# ==========================================

UI_LEFT_OFFSET = 160

# --- UI Component Heights ---
TOP_UI_HEIGHT = 60
BOT_UI_HEIGHT = 60
TOTAL_UI_HEIGHT = 120

# This probably needs to be implemented in more places than just orders.py / buttons.py (does it? what is this for again?)
# I think this is implemented in everywhere it needs to be... right?
TOP_BAR_UI_CENTER_Y = 10
BOTTOM_BAR_UI_CENTER_Y = SCREEN_HEIGHT - 50

# ==========================================
# PROVINCE MENU
# ==========================================

# --- Province Menu UI Layout (X, Y, Width, Height) ---
PROVINCE_UI = {
    # Keep the diplomatic summary compact enough to leave a dedicated button
    # beneath it for inspecting the selected foreign country's politics.
    "diplomatic_box": (10, 150, 140, 390),
    "foreign_politics_button": (10, 550, 140, 40),
    "mail_box": (400, 300, 150, 300)
}

# ==========================================
# SETTINGS
# ==========================================

DEFAULT_AI_MODE = get_starting_value("settings_config.json", "ai_mode") # LLM AI is opt-in; off until the player picks a provider
AI_MODE_REENABLE_FALLBACK = get_starting_value("ai_defaults", "reenable_mode") # Provider selected when re-enabling AI from OFF with no prior mode
# How many LLM requests a turn's batch has in flight at once, when the player
# hasn't moved the slider. A hosted provider answers concurrent requests
# independently, so fanning out is close to free throughput; a local Ollama is
# one model on one GPU, and four concurrent generations there just thrash it.
DEFAULT_AI_THREADS = get_starting_value("settings_config.json", "ai_threads")
DEFAULT_AI_THREADS_LOCAL = get_starting_value("ai_defaults", "local_threads")

# Wall-clock ceiling for one turn's LLM work, in seconds. Whatever hasn't come
# back by then falls back. 0, the default, means no ceiling: every nation that
# was going to be asked gets asked, however long that takes.
#
# The ceiling existed so a slow or unreachable provider cost a wait rather than
# a hung turn -- but FORCE SKIP AI on the loading screen already does that, and
# does it better, because a player watching the bar knows whether the wait is
# worth it and a number chosen in advance does not. What the ceiling actually
# did was cut the world's diplomacy off partway through every single turn, at a
# point unrelated to anything happening in the game.
#
# What it costs, measured on the 1941 map at MAJOR with llama3 on one thread:
# ~8s for the first director call of a turn (the world moved since the last
# one, so the model re-reads it) and ~5s after while the prefix holds. Twelve
# major powers plus their proposals is a two to three minute turn. Set this to
# a number of seconds if you would rather have a short turn than a complete
# one; nothing else in the game reads it.
DEFAULT_AI_TURN_BUDGET_SECONDS = get_starting_value("settings_config.json", "ai_turn_budget_seconds")

# How that budget is divided between the three phases that spend it, in the
# order the turn runs them. Each takes this fraction of whatever is *left* when
# it starts, so a phase that finishes early hands the rest forward and none of
# them can leave the ones after it with nothing.
#
# Three phases used to ask for the budget separately, each measuring it from its
# own start, so a setting that says 45 seconds bought 135 and the first phase in
# the turn could spend a third of the model's time without the other two ever
# knowing. Letters get the smallest share because they are the most expendable:
# a letter that misses this turn waits unread for the next, while every nation
# deciding and every proposal on the map waiting for an answer cannot.
AI_BUDGET_SHARE_LETTERS = 0.2
AI_BUDGET_SHARE_DIRECTOR = 0.5
AI_BUDGET_SHARE_RESPONSES = 1.0     # whatever the first two left

TARGET_FPS = get_starting_value("settings_config.json", "target_fps")

# ==========================================
# STARTING GAME RULES & TIMING
# ==========================================

START_YEAR = 1800
END_YEAR = 2200

# --- TACTICAL MODE CONSTANTS ---
# The stockpile of a country that a tactical division founds with Declare Independence.
TACTICAL_INDEPENDENCE_STOCKPILE = {"manpower": 1000, "materials": 1000, "fuel": 1000}

TACTICAL_DEFAULT_YEAR = START_YEAR

BASE_RESEARCH_POINTS_PER_DAY = 10
RESEARCH_SLOTS = 3 # Number of techs a nation can research simultaneously

# Faction partners that have already completed the exact tech level being
# researched share their findings. Each partner makes research points 10% more
# effective; five or more partners reach the 50% cap.
FACTION_NAME_MAX_LENGTH = 60
FACTION_RESEARCH_BONUS_PER_MEMBER = 0.10
FACTION_RESEARCH_BONUS_CAP = 0.50

# Random Scenario Settings
RANDOM_SCENARIO_SPAWN_UNITS = True
RANDOM_SCENARIO_MIN_INFANTRY = 3 # Minimum ground army before buying ships/tanks
# Infantry bought per tank in a random scenario's starting army, multiplied by the
# country's manpower-to-materials income ratio, so manpower-rich countries field more infantry.
RANDOM_SCENARIO_INFANTRY_PER_TANK = 1
RANDOM_SCENARIO_MIN_FACTORIES = 2 # Minimum factories a country should spawn with
RANDOM_SCENARIO_DEFAULT_ISLAND_FILTER = get_starting_value("random_setup", "island_filter")
RANDOM_SCENARIO_MAX_ISLAND_FILTER = 50
RANDOM_SCENARIO_SINGLE_TILE_START = get_starting_value("random_setup", "single_tile_start")
RANDOM_SCENARIO_DEFAULT_RESOURCE_CHANCE = get_starting_value("random_setup", "resource_chance")

# Equipment year used by the starting package and older default unit choices.
DEFAULT_EQUIPMENT_YEAR = 1910

# Unlocked tech exception for starting exactly in 1910
# Infantry entries use equipment dates. Other entries specify starting levels.
DEFAULT_1910_TECH = {
    "infantry_type": 1,
    "cavalry": 1,
    "militia": 1,
    "artillery": 1,
    "destroyer": 1,
    "basic_factory": 1
}

# Save these year lists so inserted equipment stages preserve completed research.
DATED_UNIT_RESEARCH_TRACKS = ("infantry_type", "cavalry", "militia", "artillery")

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
DEFAULT_TRUCE_TURNS = get_starting_value("scenario_settings.json", "truce_turns")
MIN_TRUCE_TURNS = 0
MAX_TRUCE_TURNS = 12
TRUCE_TURNS = DEFAULT_TRUCE_TURNS

# ==========================================
# DEAL VALUATION
# ==========================================
# What each clause of an itemized deal is worth, in one shared currency, so a
# demand for six provinces and a demand for two thousand tons of fuel can be
# compared against the same leverage number. The scale is arbitrary -- only the
# ratios between these matter.

#: How long a covering note attached to an offer may be, and how many names a
#: roster prints before it gives up and says "+N more". Both exist because a
#: bloc-wide treaty has to fit on one screen: the panel title used to join both
#: sides' full membership and ran off both edges of the window at once.
DEAL_NOTE_MAX_LEN = 160
DEAL_NAMES_SHOWN = 3

DEAL_VALUE_TILE_BASE = 250.0        # a bare province with nothing on it
DEAL_VALUE_BUILDING = 120.0         # per building standing on it
DEAL_VALUE_RESOURCE_UNIT = 40.0     # per point of any NATURAL_RESOURCE_OUTPUTS deposit

# A nation's own core land is worth far more to it than land it merely holds,
# and land the receiver already has a claim on is cheaper to ask for -- which is
# the whole remaining job of the claims system now that it no longer gates the
# peace screen's buttons.
DEAL_VALUE_CORE_MULT = 2.0
DEAL_VALUE_CLAIM_MULT = 0.5
DEAL_VALUE_OCCUPIED_MULT = 0.6      # already under the receiver's guns

#: What a point of stockpile is worth beside a province, at the peace table only
#: -- the AI's *trade* pricing is the separate scarcity-based
#: ai_unit_eval.resource_prices and is not affected by this.
#:
#: Quartered from 0.08/0.2/0.12. A stockpile is a short-term gain and a province
#: is a permanent one, and the old table did not say so: a demand summed land and
#: goods into one figure, so on the save these were measured from, the German
#: treasury of 33,000 materials read as 34% of the Netherlands -- about five of
#: its core provinces -- and 14% of Hungary. A bare province now costs about
#: 12,500 materials, which is more than most nations hold.
DEAL_VALUE_RESOURCE_PRICES = {"materials": 0.02, "fuel": 0.05, "manpower": 0.03}
DEAL_VALUE_VASSAL_FRACTION = 0.75   # of everything the subject owns
DEAL_VALUE_DEMILITARIZE_PER_TURN = 60.0
DEAL_DEMILITARIZE_TURNS = 6         # how long a demilitarization clause runs
DEAL_VALUE_MILITARY_ACCESS = 200.0
DEAL_VALUE_FACTION_EXIT = 800.0
DEAL_VALUE_WAR_EXIT = 500.0

#: How many turns of raw output one deal may move, per resource and per payer.
#:
#: The number in the box used to mean nothing. Both halves of paying clamped to
#: the payer's stockpile -- escrow when the offer went out, delivery when it was
#: signed -- so a promise of 99,999,999 materials was priced at 99,999,999 and
#: collected at whatever was in the bank. Anything could be bought with money
#: that did not exist.
#:
#: A term is now capped at what a nation actually produces, and collected in
#: full: see deal.resource_cap and the payment loop in deal_effects.execute.
#: One turn also bounds the debt that collection can leave behind, because the
#: income arriving next turn is the same figure that set the ceiling.
DEAL_MAX_RESOURCE_TURNS = 1

# ==========================================
# WAR SCORE (LEVERAGE)
# ==========================================
# How strong a hand each side is holding at the peace table, 0..1 and summing to
# 1 across the two. Advisory: it is shown to the player and weighed heavily by
# the AI, but nothing is forbidden by it -- an outrageous demand is refused
# rather than disallowed.


#: Turns a human faction member has to answer before silence counts as consent.
RATIFICATION_TURNS = 1

# ==========================================
# PUPPET SETTINGS
# ==========================================

PUPPET_TYPE_AUTONOMOUS = "Autonomous"
PUPPET_TYPE_INTEGRATED = "Integrated"
# Independent is a release choice. Independent countries store no puppet type.
PUPPET_RELEASE_INDEPENDENT = "Independent"
PUPPET_RELEASE_TYPES = (PUPPET_TYPE_INTEGRATED, PUPPET_TYPE_AUTONOMOUS, PUPPET_RELEASE_INDEPENDENT)
MAX_PUPPET_SIPHON = 0.50

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
    "Carrack": ["ironclad"],
    "Dreadnought": ["battleship"],
    "Battleship": ["aircraft_carrier"],
    "V1 Flying Bomb": ["v2_rocket"],
    "Zeppelin": ["biplane_bomber"],
    "Biplane Fighter": ["piston_fighter"],
    "Biplane Bomber": ["piston_bomber"],
    "Monoplane Fighter": ["jet_fighter"],
    "Monoplane Bomber": ["jet_bomber"],
    "Monoplane Transport": ["jet_transport"],
}

# ==========================================
# GLOBAL COLORS & PALETTES
# ==========================================

# Screens draw their checkerboard from this color unless they set their own.
# It is also the default standalone menu background color.
DEFAULT_BG_COLOR = (30, 30, 30)

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
    # Preserve named presets for callers outside the research screen.
    **{name: tuple(size) for name, size in research_display.get_config()["button_sizes"].items()},
    "left_ui_button": (120, 30),
    "new_game": (300, 50),
    "production": (130, 30),
    "orders": (100, 50),
    "small": (100, 40),
    "tiny": (80, 30),
    "thin": (150, 30),
    "ai_opinion": (100, 30),
    "puppet_option": (100, 30),
    "edit_portrait": (120, 30),
    "character_portrait_tile": (190, 190),
    "automation_option": (200, 30),
    # Compact Orders roster: three header controls and six icon commands per row.
    "orders_header_button": (112, 30),
    "orders_clear_button": (150, 30),
    "orders_action_icon": (28, 28),
    "left_ui_bar": (120, 50),
    "song": (580, 30),
    "asset_folder": (200, 36),
    "asset_file": (270, 22),
    "save_file": (745, 30),
    "small_save_button": (100, 30),
    "diplomatic": (200, 30),
    "keys": (60, 30),
    "menu": (180, 50),
    "medium": (200, 50),
    "setting_option": (250, 40),
    "brick": (150, 50),
    # Scenario settings screen: same width as "medium" but thinner, so a whole
    # scenario's worth of toggles/sliders can fit on one screen without scrolling.
    "scenario_setting_button": (200, 36),
    "scenario_setting_info": (32, 32),
    "editor_ui": (300, 40),
    "FTAP": (400, 40),
    "large": (300, 80),
    "list_row": (520, 34),
    # File browser sidebar shortcut.
    "browser_place": (210, 30),
    # Tab button in the turn and unit stats editors.
    "browser_tool": (170, 40),
    # Checkbox list: one toggleable row, and the small buttons above it.
    "checkbox_row": (700, 30),
    "checkbox_tool": (150, 32),
    # Editor forms (unit/country editors, turn overrides).
    "form_row": (420, 30),
    "form_tool": (130, 32),
}

COLOR_GOLD_HIGHLIGHT = (255, 215, 0)
COLOR_SUCCESS_GREEN = (100, 255, 100)
COLOR_DIM_BORDER = (100, 100, 100)

COLOR_RESOURCE_MANPOWER = (100, 200, 255)
COLOR_RESOURCE_MATERIALS = (180, 180, 180)
COLOR_RESOURCE_FUEL = (200, 100, 255)

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

# Tool-window panel themes: (background, border, border width). Unpack one
# straight into a MapOverlayScreen subclass and it gets the whole look:
#
#     class Declare_War_Screen(MapOverlayScreen):
#         PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_DANGER
#
# Seventeen panels used to pass their own hand-picked RGB straight to
# ui_bars.draw_modal_box -- no two calls alike, several a couple of RGB points
# apart from each other, and two files repeating the same tuple twice. The
# border is what carries a panel's identity, so the backgrounds are all
# MODAL_BG apart from the deliberately red-tinted danger one.
PANEL_THEME_DANGER  = ((40, 30, 30), (255, 50, 50), 3)   # declaring war, leaving, wiping the map
PANEL_THEME_CONFIRM = (MODAL_BG, (76, 175, 80), 3)       # agreeing to something: peace, trade
PANEL_THEME_INFO    = (MODAL_BG, UI_ACCENT_BLUE, 2)      # showing state: puppets, diplomacy
PANEL_THEME_EDIT    = (MODAL_BG, (255, 152, 0), 2)       # editing scenario data: research, date
PANEL_THEME_SPECIAL = (MODAL_BG, (150, 100, 250), 2)     # brushes and personality tuning

# The same two themes for panels that sit over the live map and want it to
# stay half-visible behind them -- the alpha is the point, not decoration.
PANEL_THEME_CONFIRM_OVER_MAP = ((30, 40, 30, 230), PANEL_THEME_CONFIRM[1], 3)
PANEL_THEME_INFO_OVER_MAP    = ((*HUD_PANEL_BG, 230), UI_ACCENT_BLUE, 2)

# Pixels per wheel notch. Screen.scroll_speed mirrors this; panels that roll
# their own wheel handling should read it from here rather than redeclaring it.
SCROLL_STEP = 30

ELLIPSIS = "..."

# Single-line text entry boxes. Nine screens each had their own fill/border
# pair; these are the values they all draw with now (see
# ui_elements.draw_text_box). The focused box lights up and gains a white edge.
INPUT_BORDER = (150, 150, 150)
INPUT_BORDER_ACTIVE = (255, 255, 255)

# Back button placement. Full-screen menus anchor to the top-left corner;
# screens layered over the map sit beside the top UI bar instead.
BACK_BTN_TOPLEFT = (20, 20)

# Owner names that mean "nobody owns this". Deliberately NOT UNPLAYABLE_NATIONS:
# that list also carries "The Rot"/"Spectator"/"GLOBAL_EVENTS"/"FACTION_WAR_MAPS"
# and omits "", so substituting it would change which provinces count as empty.
OWNERLESS_OWNERS = ("Unclaimed", "None", "Ocean", "Lakes")
UNOWNED_LAND_OWNERS = ("Unclaimed", "None", "")

# ==========================================
# MESSAGING APP UI
# ==========================================

# Unread-mail badge on the map screen; the rest of the messaging layout lives
# in screens/game/messages.py.
MSG_NOTIFICATION_COLOR = (255, 50, 50)

# ==========================================
# CAMERA & MAP RENDERING
# ==========================================

MAX_CAMERA_ZOOM = 10.0
AIR_MISSION_CHOICES = (
    ("NONE", "No mission", "No Mission"),
    ("MOVE", "Move (select a destination)", "Air Move"),
    ("STRIKE", "Strike (select a target)", "Strike Selected"),
    ("TRANSPORT", "Transport (load or release ground units)", "Air Transport"),
    ("AIR_DROP", "Air Drop (select enemy land)", "Air Drop"),
    ("WEAKEST", "Defend area (weakest enemy missions targeted first)", "Weakest First"),
    ("STRONGEST", "Defend area (strongest enemy missions targeted first)", "Strongest First"),
    ("RANDOM", "Defend area (random enemy mission targeted first)", "Random First"),
)
AIR_MISSION_ICONS = {mission: icon for mission, _label, icon in AIR_MISSION_CHOICES}
APPLY_TILT_TO_OVERLAYS = False # Whether the tilt compresses icons and text overlays

# Water brightness stuff
OCEAN_DARK_BLUE = tuple(get_starting_value("settings_config.json", "ocean_dark_color"))
# OCEAN_DARK_BLUE = (5, 10, 20)
OCEAN_LIGHT_BLUE = tuple(get_starting_value("settings_config.json", "ocean_light_color"))
# OCEAN_LIGHT_BLUE = (20, 40, 80)

DEFAULT_OCEAN_DARK_BLUE = tuple(get_starting_value("settings_config.json", "ocean_dark_color"))
DEFAULT_OCEAN_LIGHT_BLUE = tuple(get_starting_value("settings_config.json", "ocean_light_color"))

# ==========================================
# DEFAULT UNIT STATS (Fallbacks)
# ==========================================

DEFAULT_UNIT_HP = 100
DEFAULT_UNIT_ATK = 5
DEFAULT_UNIT_DEF = 0
DEFAULT_UNIT_SPD = 1

# Each army deploys in at most this many columns (ranks), each holding one or two divisions.
# The battlefield size (ARENA_SIZE in map_logic/custom_battle.py and map_logic/naval_battle.py)
# is derived from the column count so two full armies fit.
CUSTOM_BATTLE_MAX_COLUMNS_PER_SIDE = 16
CUSTOM_BATTLE_UNITS_PER_COLUMN = 2
# Most divisions per army in a tactical battle.
CUSTOM_BATTLE_MAX_UNITS_PER_SIDE = CUSTOM_BATTLE_MAX_COLUMNS_PER_SIDE * CUSTOM_BATTLE_UNITS_PER_COLUMN

#: The roman numeral alphabet, largest first. Both directions of the conversion
#: read it, so they cannot disagree about which symbols exist: data/queries/unit_info.py's
#: roman_to_int used to know only I/V/X while _gen_roman could emit L and C, so
#: a tier numeral past XLIX parsed as a smaller number (or as zero) and the tier
#: suffix silently failed to strip off a unit's name.
ROMAN_SYMBOL_VALUES = (
    ("M", 1000), ("CM", 900), ("D", 500), ("CD", 400),
    ("C", 100), ("XC", 90), ("L", 50), ("XL", 40),
    ("X", 10), ("IX", 9), ("V", 5), ("IV", 4), ("I", 1),
)

#: Single-letter values, for parsing in the subtractive-notation direction.
ROMAN_LETTER_VALUES = {sym: val for sym, val in ROMAN_SYMBOL_VALUES if len(sym) == 1}


def _gen_roman(n):
    res = ""
    for sym, val in ROMAN_SYMBOL_VALUES:
        while n >= val:
            res += sym
            n -= val
    return res

ROMAN_NUMERALS = {i: _gen_roman(i) for i in range(1, 101)}


# ==========================================
# COMBAT WIDTH
# ==========================================
# A tile does not fight as one pot. It splits into lanes -- one duel per pair of
# hostile powers standing on it -- and these three numbers decide how many units
# get to be in those duels. See map_logic/system32/combat_rules.py.

# Width covers ground and sea combat across every lane, rather than each nation.
# Flying missions have no width limit. Terrain can override width in
# combat_rules.combat_width_for_terrain.
COMBAT_WIDTH = 16
COMBAT_WIDTH_BY_TERRAIN = {
    "mountain": 12,
    "plains": 20,
}

# Flying stacks have no width limit. These constants control attack efficiency.
AIR_STACK_EFFICIENCY_PENALTY = 0.15
AIR_STACK_EFFICIENCY_BREAKPOINT = 17
AIR_STACK_LARGE_EFFICIENCY_BASE = 0.60
AIR_STACK_LARGE_EFFICIENCY_PENALTY = 0.05
AIR_STACK_MIN_ATTACK_EFFICIENCY = 0.25

# What a unit at 0% health still deals, as a fraction of its full attack. Damage
# scales linearly between this floor (at 0% health) and 1.0 (at 100% health) --
# see combat_rules.health_damage_multiplier. 0 means a dying unit deals no
# damage at all; 1 means health has no effect on damage, as if this mechanic
# did not exist.
#
# Player-editable in scenario settings (see screens/setup/
# scenario_settings.py) as "damage_at_zero_health"; this is only the value a
# reset scenario uses. Active overrides belong to each world's runtime rules.
DAMAGE_AT_ZERO_HEALTH = get_starting_value("scenario_settings.json", "damage_at_zero_health")
DEFAULT_DAMAGE_AT_ZERO_HEALTH = DAMAGE_AT_ZERO_HEALTH

# Same idea as DAMAGE_AT_ZERO_HEALTH, but for the defense a wounded unit still
# offers -- see combat_rules.health_defense_multiplier. 0 means a unit at 0%
# health blocks nothing; 1 means health has no effect on defense.
#
# Player-editable in scenario settings as "defense_at_zero_health"; this is
# the default for a reset scenario. Active overrides belong to each world.
DEFENSE_AT_ZERO_HEALTH = get_starting_value("scenario_settings.json", "defense_at_zero_health")
DEFAULT_DEFENSE_AT_ZERO_HEALTH = DEFENSE_AT_ZERO_HEALTH

# Floor on a lane's per-side allowance, so a two-unit ally is never squeezed out
# of the fight by a fifty-unit one. When lanes * 2 * this exceeds COMBAT_WIDTH
# the floor wins and the tile fields more than COMBAT_WIDTH -- at 12/2 that
# needs four separate duels on one tile.
MIN_LANE_SLOTS_PER_SIDE = 2

# Slots per side in a typical lane: one lane, one enemy, which is what most
# fights are. This is the number the AI reasons with, since it cannot know in
# advance how many ways a tile will split.
LANE_SLOTS_TYPICAL = COMBAT_WIDTH // 2

# ==========================================
# BOMBARDMENT
# ==========================================

# Base unit classes allowed to fire on a nearby tile instead of moving, mapped
# to how many tiles their shells reach (1 = directly adjacent only).
# Matched against queries.get_base_unit_name, so every level of the family counts.
BOMBARDMENT_UNITS = {
    "Artillery": 1,
    "Heavy Artillery": 1,
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


# ==========================================
# CONVOY & TRUCK LOGIC
# ==========================================

CONVOY_MAX_HP = 1000
TRUCK_MAX_HP = 1000
CONVOY_ATK = 100
TRUCK_ATK = 100
CONVOY_DEF = 0
TRUCK_DEF = 0
TRUCK_CONVERT_TURNS = 2

# The editor and shared rules use the same inclusive timing limits.
MIN_CONVERSION_TURNS = 1
MAX_CONVERSION_TURNS = 9

# Recovery includes landing and this many subsequent complete turns.
AIR_DROP_RECOVERY_TURNS = 2

# Orders that span more than one turn and are therefore a standing commitment,
# not a plan to be re-derived. The AI wipes its units' orders every turn so it
# can rethink its movement; these are the ones it must NOT wipe, or the order
# is destroyed before the turn processor ever sees it.
MULTI_TURN_ORDER_TYPES = ("CONVERT", "DISBAND", "REPAIR", "UPGRADE", "AIR_DROP_RECOVERY")
# The above plus bombardment, which occupies the unit's turn even though it
# resolves within it. A unit doing any of these cannot also move.
ORDERS_BLOCKING_MOVEMENT = MULTI_TURN_ORDER_TYPES + ("BOMBARD",)

# ==========================================
# OVERLAY ICONS & SCALES
# ==========================================


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
# "heavy_artillery" rides the plain "artillery" tech instead of a track of its
# own, so researching Artillery unlocks both variants at the same levels.
UNIT_TECH_KEY_OVERRIDES = {
    "predreadnought": "pre-dreadnought",
    # Keep saved research IDs stable when aircraft display names change.
    "biplane_fighter": "biplane",
    "monoplane_fighter": "piston_fighter",
    "monoplane_bomber": "piston_bomber",
    "motorized_infantry_type": "motorized_infantry",
    "mechanized_infantry_type": "mechanized_infantry",
    "infantry_fighting_vehicle_type": "infantry_fighting_vehicle",
    "heavy_artillery": "artillery",
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


# ==========================================
# STAT ICONS
# ==========================================

ICON_ATTACK = "Attack"
ICON_DEFENSE = "Shield"
ICON_HEALTH = "Heart"

# ==========================================
# AI & SPECTATOR CONFIGURATION
# ==========================================

# What a spectator is allowed to change, as opposed to merely watch. All three
# default to True, which is what a spectator could already do before the
# switches existed; turn one off to make that screen read-only for them.
SPECTATOR_CAN_EDIT_PRODUCTION = True
SPECTATOR_CAN_EDIT_RESEARCH = True
SPECTATOR_CAN_EDIT_APPEARANCE = True


# ==========================================
# AI PERSONALITY (map_logic/ai/ai_personality.py)
# ==========================================

# Seed every nation's procedural temperament is derived from. A scenario stores
# its own on first use, so changing this only affects scenarios that never had
# one; changing it will not reroll personalities in a save already underway.
DEFAULT_AI_PERSONALITY_SEED = "greater-diplomacy-5"


AI_WAR_STRENGTH_THRESHOLD = 1.2 # AI must be 20% stronger on the shared border to declare war
AI_GLOBAL_STRENGTH_THRESHOLD = 0.8 # AI must have at least 80% of the target's total alliance + economic power to consider war
AI_DIPLO_COOLDOWN = 12

# How long an AI must have been in a faction before it will consider walking
# out. Nothing in the game measured membership at all: the LLM could answer a
# message with {"action": "LEAVE_FACTION"} and that was the entire process, no
# war state, no relations, no delay. In saves/"what happened to the allies" the
# United Kingdom and then the United States each left the Allies that way, ~14
# turns apart, and each dragged its puppets with it -- which is the whole of how
# a faction of thirteen became a faction of six with the rest sitting in a rival
# bloc. Applies to the AI only; a player may still leave whenever they like.
AI_FACTION_MIN_TENURE = 15 # How many turns before AI can retry a rejected/ignored proactive diplomatic action. -1 means infinite.
AI_WAR_COOLDOWN = 12
AI_WEAK_NEIGHBOR_STRENGTH_RATIO = 0.60 # Target must be this much weaker (e.g. 60% of AI's power) to be bullied with claims
AI_NEARBY_SEA_TILES = 3 # Longest water crossing considered nearby for AI claims and wars

# ==========================================
# POLITICS (map_logic/politics.py, map_logic/ai/ai_politics.py)
# ==========================================
# Four axes in two groups, each moving independently once per processed turn:
#   Civilian: Political (libertarian / authoritarian), Economic (planned / market)
#   Military: Quality (professional / numerous), Strategy (offensive / defensive)

POLITICS_MIN = -10              # libertarian / planned / professional / offensive
POLITICS_MAX = 10               # authoritarian / market / numerous / defensive
POLITICS_START = 0              # the centre of every axis
POLITICS_STEP = 1               # distance per processed turn on each axis

# Every axis effect, as (value at POLITICS_MIN, value at POLITICS_MAX). A
# position between the ends interpolates linearly. Effect names are unique
# across axes, so a name alone identifies its axis.
POLITICS_AXIS_EFFECTS = {
    "political": {
        "coring_turns": (10, -10),          # added to the scenario's coring turns
        "coring_cost": (1.2, 0.8),
        "remove_core_cost": (1.2, 0.8),     # removing cores keeps its scenario turns
        "research": (2.0, 0.0),             # normal research; funded research bypasses it
        "reputation": (10, -10),            # added to every other country's opinion of this one
    },
    "economic": {
        "factory_output": (0.9, 1.1),       # factories (group "industry") only, on any territory
        "deposit_output": (0.9, 1.1),       # natural resource deposits only
        "building_cost": (0.8, 1.2),        # every building except forts
        "non_core_tile_output": (2.0, 0.0), # multiplies NON_CORE_MULTIPLIERS; not buildings
        "non_core_building_output": (0.6, 0.4),  # every building's output on non-core territory
    },
    "quality": {
        "damage": (1.3, 0.7),
        "tile_manpower": (0.5, 1.5),        # core and non-core province tiles only
        "unit_upkeep": (1.5, 0.5),          # the whole upkeep bill: manpower, materials and fuel
        "max_health": (1.2, 0.8),
        "research_year_months": (10, -10),  # the ahead-of-time penalty treats the date as this many months later
    },
    "strategy": {
        "aircraft_range": (1.2, 0.8),
        # Core and non-core damage are separate so two countries with different
        # strategies each keep their own modifier in either one's territory.
        "core_territory_damage": (1.0, 1.2),
        "non_core_territory_damage": (1.0, 0.8),
        "defense": (0.8, 1.2),              # unit defense and fort defense
        "fort_cost": (1.2, 0.8),
    },
}
# Idea for later: removing cores could become a policy.


# ==========================================
# LLM DIRECTOR (map_logic/ai/ai_director.py)
# ==========================================
# The immersion levels, in order. MAJOR sits between FULL and ABSOLUTE: the
# model drives the countries a player actually notices, which is great-power
# diplomacy at a fraction of what ABSOLUTE costs.
AI_IMMERSION_LEVELS = ("LITE", "FULL", "MAJOR", "ABSOLUTE")


# An action the model pushed for while answering a proposal is filed rather than
# executed, and reconsidered next turn against the ordinary rules. True restores
# the old behaviour, where such an action skipped every war prerequisite.
AI_LLM_DIRECT_RETALIATION = False
AI_REQUEST_REASON_LENGTH = 120

# ==========================================
# LETTERS AND NOTEBOOKS
# (map_logic/ai/ai_letters.py)
# ==========================================
# The largest opinion change one letter or one reply can cause, in either
# direction, on the -200 to 200 relation scale.
AI_OPINION_CHANGE_MAX = 20


TURNS_TO_WAIT_BEFORE_WAR = get_starting_value("scenario_settings.json", "turns_to_wait_before_war") # Turns the AI waits before declaring wars
AI_WAR_DECLARATION_CHANCE = get_starting_value("scenario_settings.json", "ai_war_declaration_chance") # Chance to declare war when conditions are met

# ==========================================
# FACTION LEADERSHIP
# ==========================================
# Who runs a faction was decided once, by whoever founded it, and could never
# change: a member that grew into the strongest power in its own bloc still had
# to ask its founder's permission to negotiate, and the founder still spoke for
# everyone at the peace table. Leadership is now something a member can take.
#
# The two numbers are what stop it being a revolving door. A challenger has to
# outweigh the leader by half again -- not merely edge ahead, which two
# comparable powers do to each other constantly as units are built and lost --
# and it has to hold that lead for six consecutive turns, with the count reset
# by the first turn it does not. See map_logic/diplomacy/faction_leadership.py.
FACTION_CHALLENGE_MARGIN = 1.5
FACTION_CHALLENGE_TURNS = 6


# Distraction Weight
# How much the AI values the strength of their target's current enemies. 
# 0.8 means if the target is fighting someone with 1000 strength, the AI feels 800 points braver.
AI_ENEMY_DISTRACTION_WEIGHT = 0.8
AI_BORDER_DISTRACTION_MULTIPLIER = 0.5 # Multiplier for border units actively engaged in combat with a third party

# ==========================================
# AI RECRUITMENT PREFERENCES
# ==========================================

# Fallbacks only. map_logic/ai/ai_unit_eval.py scores every unit the nation can
# actually build from its stats, so a change to unit_data.json changes what the AI
# builds without anyone editing a list here. queries.get_best_offensive_unit and
# get_best_naval_unit read these lists only for a nation with no research to score.
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

# Waves deep a tile is worth reinforcing to: one front rank, and one relief rank
# to replace it as it dies. Bodies past this cannot reach a front slot before the
# tile resolves, and under the lane model they absorb nothing while they wait --
# which is the single biggest difference from the model this replaced, where
# every extra body thinned the volley for the whole stack.
AI_RESERVE_DEPTH = 2.0

# Below this share of its health, a unit is worth more in reserve than in the
# front rank -- a reserve takes no damage. Only ever applied
# when a healthier unit is free to take the slot, since an empty slot dissolves
# the lane and is worse than a hurt one holding it.
AI_ROTATE_HEALTH_FRACTION = 0.4


AI_UPKEEP_TARGETS = {
    "manpower": 0.80,
    "materials": 0.60,
    "fuel": 0.70
}


# ==========================================
# DIPLOMATIC ACTION CLASSIFICATIONS
# ==========================================

# Actions that happen instantly and do not require the target's consent


# Proposals that require the target to explicitly Accept or Reject
# Moves a nation makes about itself rather than at somebody. The distinction
# matters for rate limiting: a diplomatic cooldown is keyed (sender, target,
# action), and these have no real target, so keying them on whoever the AI
# happened to be talking to made their cooldown per-interlocutor -- i.e. no
# cooldown at all. See _process_ai_retaliation.
SELF_TARGETED_ACTIONS = ("LEAVE_FACTION", "DISBAND_FACTION")

# A country may have only one of these pending at a time, whoever it is aimed at.
FACTION_REQUEST_ACTIONS = ("CREATE_FACTION", "JOIN_FACTION_REQ")


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

#: How a deposed faction leader regards the member that took the chair. One-way
#: on purpose, unlike walking out of a faction: the rest of the bloc did not
#: lose anything, and did not have a say either.
REL_MOD_DEPOSED = -40

REL_MOD_PER_CLAIM = -5
REL_MOD_MAX_CLAIM_PENALTY = -50

REL_MOD_REMOVE_CORE = -30
REL_MOD_MAX_REMOVE_CORE_PENALTY = -150


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
# Small player-facing emblems used by persistent armies.  They are loaded
# under an army-specific key, so a generic filename such as ``Star.png``
# cannot replace normal unit or UI art.
ARMY_SYMBOLS_DIR = "assets/symbols"
ARMY_SYMBOL_KEY_PREFIX = "Army Symbol "
DEFAULT_ARMY_SYMBOL_COLOR = (210, 70, 70)
UNASSIGNED_ARMY_ID = "__unassigned__"
UNASSIGNED_ARMY_COLOR = (55, 55, 55)
# New armies choose one of these high-contrast colors.  Keeping the palette
# bounded makes both their emblems and the matching Orders roster bands easy
# to distinguish against the map and panel backgrounds.
ARMY_SYMBOL_COLOR_CHOICES = (
    DEFAULT_ARMY_SYMBOL_COLOR, (55, 145, 225), (70, 180, 105),
    (225, 160, 45), (155, 100, 220), (45, 185, 180),
    (225, 95, 155), (200, 120, 65),
)
ARMY_SYMBOL_ROTATIONS = (0, 90, 180, 270)
DEFAULT_ARMY_SYMBOL_ROTATION = ARMY_SYMBOL_ROTATIONS[0]
DEFAULT_ARMY_SYMBOL_FLIPPED = False
ARMY_CUSTOM_SYMBOL_SIZE = 20
ARMY_CUSTOM_SYMBOL_RED = "R"
ARMY_CUSTOM_SYMBOL_BLACK = "B"
ARMY_CUSTOM_SYMBOL_EMPTY = "."
BACKGROUNDS_DIR = "assets/backgrounds"
FLAGS_DIR = "assets/flags"
PORTRAITS_DIR = "assets/portraits"
MUSIC_DIR = "assets/music"
# Audio files the game plays from an album folder. BeepBox and UltraBox .json songs are also played.
MUSIC_AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg")
# Album folder names the music screen never deletes. Every other album folder
# gets a delete button. Add the name of each album that ships with the game.
UNDELETABLE_ALBUMS = (
    "Experimental", "Greater Diplomacy 1", "Greater Diplomacy 2", "Greater Diplomacy 3",
    "Greater Diplomacy 4", "Greater Diplomacy 5",
)
# These three are rebindable in Settings, so main.py overwrites them at startup
# with whatever was persisted. The DEFAULT_ forms are the shipped values, and
# are what settings loading falls back to -- reading the mutable name there
# would hand back the last value loaded instead of the actual default.
DEFAULT_SAVES_DIR = get_starting_value("settings_config.json", "saves_dir")
DEFAULT_TOURNAMENT_SAVES_DIR = get_starting_value("settings_config.json", "tournament_saves_dir")
DEFAULT_SCENARIOS_CUSTOM_DIR = get_starting_value("settings_config.json", "custom_scenarios_dir")

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

DEFAULT_CHECKERBOARD_SCROLL_SPEED = get_starting_value("settings_config.json", "checkerboard_scroll_speed")  # pixels/sec
CHECKERBOARD_SCROLL_SPEED = DEFAULT_CHECKERBOARD_SCROLL_SPEED
MAX_CHECKERBOARD_SCROLL_SPEED = 100
DEFAULT_CHECKERBOARD_GRADIENT_STRENGTH = get_starting_value("settings_config.json", "checkerboard_gradient_strength")
CHECKERBOARD_GRADIENT_STRENGTH = DEFAULT_CHECKERBOARD_GRADIENT_STRENGTH
MAX_CHECKERBOARD_GRADIENT_STRENGTH = 2.0

FLAG_SIZE = (60, 40)
PORTRAIT_SIZE = (60, 60)

# Fonts & Sounds
FONT_PATH_DEFAULT = "assets/fonts/W95F.otf"
FONT_PATH_MAP = "assets/fonts/PixelOperatorMonoHB.ttf"

# UI Specific Font Paths
FONT_PATH_DATE = "assets/fonts/PixelOperatorMonoHB.ttf"
FONT_PATH_TOP_COUNTRY = "assets/fonts/PixelOperatorMonoHB.ttf"
FONT_PATH_RESOURCES = "assets/fonts/W95F.otf"
# Draws words that the fonts above have no glyphs for.
FONT_PATH_FALLBACK = "assets/fonts/unifont.otf"

SOUND_CLICK_PATH = "assets/sounds/Slider.wav"
SOUND_SLIDER_PATH = "assets/sounds/Info.mp3"

# JSON Data
UNIT_DATA_PATH = "data/json/unit_data.json"
COUNTRIES_DATA_PATH = "data/json/countries_data.json"
RESEARCH_TEMPLATE_PATH = "data/json/research_template.json"
BUILDING_DATA_PATH = "data/json/building_data.json"
# Everything the AI says when the language model is not consulted.
AI_RESPONSES_PATH = "data/json/ai_responses.json"
SETTINGS_CONFIG_PATH = "data/json/settings_config.json"
ACTIVE_ALBUMS_PATH = "data/json/active_albums.json"
SHUFFLE_DISABLED_TRACKS_PATH = "data/json/shuffle_disabled_tracks.json"
STARTING_SONG_PATH = "data/json/starting_song.json"
HILDEHRAND_CHOICE_PATH = "data/json/hildehrand_choice.json"
# Menu portrait gradient: strength 1 matches a standard button; the slider runs 0 to the maximum.
HILDEHRAND_GRADIENT_DEFAULT_ENABLED = get_starting_value("hildehrand_choice.json", "gradient")
HILDEHRAND_GRADIENT_DEFAULT_STRENGTH = get_starting_value("hildehrand_choice.json", "gradient_strength")
HILDEHRAND_GRADIENT_MAX_STRENGTH = 3.0
# Stepped bands instead of fine smooth bands.
HILDEHRAND_GRADIENT_DEFAULT_STEPPED = get_starting_value("hildehrand_choice.json", "gradient_stepped")
# Stepped style: how many color bands the portrait gradient has.
HILDEHRAND_GRADIENT_DEFAULT_BANDS = get_starting_value("hildehrand_choice.json", "gradient_bands")
HILDEHRAND_GRADIENT_MIN_BANDS = 2
HILDEHRAND_GRADIENT_MAX_BANDS = 64
HISTORICAL_LEADERS_PATH = "data/json/historical_leaders.json"
HISTORICAL_LEADERS_DEFAULT_PATH = "data/json/historical_leaders_DEFAULT.json"

# ==========================================
# HISTORY & SAVING SETTINGS
# ==========================================

RECORD_HISTORY = True
# Plain history exports use indentation. Compressed history uses compact JSON.
HISTORY_INDENT = 4
# Library files in data/json/ keep four-space indentation.
LIBRARY_JSON_INDENT = 4
# Save and map JSON (meta.json, map_data.json) indents nested values by
# SAVE_INDENT spaces. A list or object stays on one line when that whole line
# fits within SAVE_LINE_WIDTH characters. See history_io.dump_save_text.
SAVE_INDENT = 2
SAVE_LINE_WIDTH = 100
# Level 6 makes history files about a quarter smaller than level 1. The extra
# compression time is small next to serializing the snapshots.
HISTORY_GZIP_LEVEL = 6
# Marks a history snapshot whose images have already been scrubbed, so a save
# does not redo identical work for every turn it has ever recorded.
HISTORY_SCRUBBED_KEY = "_scrubbed"

# Mouse controls are a per-button action map. The defaults come from
# starting_defaults.json; names and labels here describe the available actions.
MOUSE_BUTTONS = ((1, "left", "Left"), (2, "middle", "Middle"),
                 (3, "right", "Right"))
MOUSE_CONTROL_ACTIONS = (
    ("select_units", "Select unit stacks", "Click a visible stack to select it."),
    ("box_select_units", "Box-select unit stacks", "Hold and drag to select multiple stacks."),
    ("pan_map", "Pan the map", "Hold and drag to pan in every map workspace."),
    ("issue_orders", "Give move orders", "Click a destination for selected units."),
)


def default_mouse_button_actions():
    """Return an independent copy suitable for a controller or save default."""
    return get_starting_value("settings_config.json", "mouse_button_actions")


def normalize_mouse_button_actions(value):
    """Validate mouse controls after the shared older-format conversion."""
    # Migrations import constants. Load this adapter after constants initialize.
    from data.migrations import migrate_mouse_button_actions
    value = migrate_mouse_button_actions(value)
    normalized = default_mouse_button_actions()
    if not isinstance(value, dict):
        return normalized
    valid_actions = ({action for action, _label, _help in MOUSE_CONTROL_ACTIONS}
                     | {"exclude_orders"})
    for _number, button, _label in MOUSE_BUTTONS:
        saved_actions = value.get(button)
        if not isinstance(saved_actions, dict):
            continue
        for action in valid_actions:
            if action in saved_actions and isinstance(saved_actions[action], bool):
                normalized[button][action] = saved_actions[action]
        if not normalized[button]["pan_map"]:
            normalized[button]["exclude_orders"] = False
    return normalized


# Mirrored at startup and whenever Mouse Settings changes; direct map-input
# paths deliberately use this cached mapping rather than reading a file/event.
MOUSE_BUTTON_ACTIONS = default_mouse_button_actions()

# ==========================================
# RUNTIME SETTINGS
# ==========================================
# A handful of settings are mirrored onto this module because the code that
# reads them -- the renderer, the camera, the save paths -- is too low-level to
# reach the Controller. Every one of them used to be copied across by hand at
# six different call sites, and the lists had already fallen out of step.

#: setting name (as used by data/io/settings_schema.py) -> constant name here.
RUNTIME_SETTINGS = {
    "saves_dir": "SAVES_DIR",
    "custom_scenarios_dir": "SCENARIOS_CUSTOM_DIR",
    "ocean_light_color": "OCEAN_LIGHT_BLUE",
    "ocean_dark_color": "OCEAN_DARK_BLUE",
    "tournament_saves_dir": "TOURNAMENT_SAVES_DIR",
    "checkerboard_water": "CHECKERBOARD_WATER",
    "checkerboard_gradient_strength": "CHECKERBOARD_GRADIENT_STRENGTH",
    "checkerboard_scroll_speed": "CHECKERBOARD_SCROLL_SPEED",
    "unit_art_style": "UNIT_ART_STYLE",
    "map_navigation_mode": "MAP_NAVIGATION_MODE",
    "control_mode": "CONTROL_MODE",
    "battle_display_mode": "BATTLE_DISPLAY_MODE",
    "army_group_animations": "ARMY_GROUP_ANIMATIONS",
    "show_unclaimed": "SHOW_UNCLAIMED",
    "mouse_button_actions": "MOUSE_BUTTON_ACTIONS",
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
            globals()[constant] = (
                normalize_mouse_button_actions(values[name])
                if name == "mouse_button_actions" else values[name])


# Country identity fields shared by local editors and multiplayer projections.
COUNTRY_APPEARANCE_FIELDS = ("name", "adjective", "leader_name", "leader_title",
                             "flag_data", "portrait_data", "color")
