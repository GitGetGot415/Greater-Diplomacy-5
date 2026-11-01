"""Convert older Greater Diplomacy 5 (GD5) data to the current formats.

Every conversion of older GD5 data lives in this package. See documentation/data_migrations.txt.

versions.py       Version stamps, SAVE_STEPS and MOVE_STEPS, and the conversion entry points.
v47.py            The version 47 step. Each new version gets its own file.
settings.py       Older settings names and mouse-button controls.
units.py          Older unit identifiers, categories, and unit metadata.
research.py       Saved research levels and the active technology tree.
repairs.py        Load repairs against the active libraries, and faction roster repair.
tournament.py     Tournament move projections and encrypted-file payloads.
v46_moves.py      The input adapter for released v46 move files. Import it by module name.

Keep imports from other games in their separate translation modules.
Loaders own saved-file access. Shared gameplay modules own current rules and validation.
Queries import this package. Keep query imports local to avoid that cycle.
Preserve unknown valid fields.

Callers import names from this package. Tests that replace SAVE_STEPS, MOVE_STEPS, or
CURRENT_VERSION must replace them in data.migrations.versions, which reads them.
"""

from data.migrations.versions import (
    NewerVersionError,
    version_number,
    CURRENT_VERSION,
    check_version,
    upgrade_save,
    LAST_UNSTAMPED_VERSION,
    move_version,
    upgrade_move,
    SAVE_STEPS,
    MOVE_STEPS,
)
from data.migrations.settings import (
    SETTING_ALIASES,
    LEGACY_SETTINGS_KEYWORD_NAMES,
    setting_keys,
    read_setting_value,
    controller_setting_values,
    normalize_ai_mode,
    migrate_setting_names,
    migrate_mouse_button_actions,
)
from data.migrations.research import (
    LEGACY_INFANTRY_RESEARCH_YEARS,
    migrate_infantry_research,
    clamp_research_levels,
)
from data.migrations.units import (
    normalize_air_category,
    legacy_unit_tech_key,
    legacy_unit_metadata,
    legacy_unit_group,
    legacy_ai_force_category,
    normalize_cached_json_names,
    LEGACY_AIRCRAFT_NAMES,
    LEGACY_UNIT_NAMES,
    equipment_stage_aliases,
)
from data.migrations.repairs import (
    clamp_building_level,
    clamp_building_queue,
    normalize_production_order,
    repair_faction_rosters,
)
from data.migrations.tournament import (
    tournament_player_intents,
    decode_saved_json,
    legacy_player_country,
)
from data.migrations.v47 import (
    LEGACY_RESEARCH_DEFAULT_DAYS,
    LEGACY_RESEARCH_POINTS_PER_DAY,
)
