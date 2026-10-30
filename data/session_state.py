"""Own participants, control permissions, and processing progress."""

from dataclasses import dataclass, field
import data.constants as c


@dataclass
class SessionState:
    num_players: int = 1
    active_players: list = field(default_factory=list)
    current_player_index: int = 0
    player_country: str = "None"
    viewing_country: object = None
    tactical_mode: bool = False
    player_unit: object = None
    unit_economy: dict = field(default_factory=lambda: {**{res: 0 for res in c.ECON_RESOURCE_KEYS}, "fuel_inc": 0})
    is_editor: bool = False
    selection_mode: bool = False
    viewing_ai_moves: bool = False
    skip_ai_view: bool = False
    multiplayer_mode: bool = False
    realtime_multiplayer: bool = False
    unit_event_read_turns: dict = field(default_factory=dict)
    ai_is_thinking: bool = False
    ai_processing_complete: bool = False
    is_refreshing: bool = False
    is_saving: bool = False
    save_progress_completed: int = 0
    save_progress_total: int = 5
    thread_error: object = None
    force_skip_llm: bool = False
    multi_turn_processing_complete: bool = False
    multi_turns_total: int = 0
    multi_turns_completed: int = 0
    multi_turn_abort_requested: bool = False
    loading_status_text: str = "Waiting..."
    proactive_tasks_total: int = 0
    proactive_tasks_completed: int = 0
    proactive_llm_tasks_total: int = 0
    proactive_llm_tasks_completed: int = 0
    proactive_llm_tasks: list = field(default_factory=list)
    proactive_choices: list = field(default_factory=list)
    responsive_tasks_total: int = 0
    responsive_tasks_completed: int = 0
    summits_total: int = 0
    summits_completed: int = 0
    refresh_tasks_total: int = 0
    refresh_tasks_completed: int = 0
    turn_start_time: int = 0
    # Tournament host and player state.
    multiplayer_tournament_dir: object = None
    multiplayer_master_key: str = ""
    multiplayer_session_key: object = None
    multiplayer_keys_dict: dict = field(default_factory=dict)
    multiplayer_player_enc_cache: dict = field(default_factory=dict)
    multiplayer_protected_countries: set = field(default_factory=set)
    multiplayer_pending_key_regen: set = field(default_factory=set)
    multiplayer_pending_faction_renames: list = field(default_factory=list)
    multiplayer_pending_appearance_updates: dict = field(default_factory=dict)
    submitted_moves: set = field(default_factory=set)
    # Real-time client drafts that travel as server-validated commands.
    realtime_pending_appearance_updates: dict = field(default_factory=dict)
    realtime_volunteer_drafts: dict = field(default_factory=dict)
    # Map editor undo and redo stacks.
    editor_history: list = field(default_factory=list)
    editor_redo_history: list = field(default_factory=list)
    # Object IDs of units that moved during the current turn.
    _units_with_move_order_this_turn: set = field(default_factory=set)
