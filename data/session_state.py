"""Own participants, control permissions, and processing progress."""

import copy
from dataclasses import dataclass, field

# Play modes. Each session has exactly one. Tactical control, country selection,
# and viewing AI moves are phases within a mode, so they stay separate fields.
LOCAL_PLAY = "local"
MAP_EDITOR = "editor"
TOURNAMENT = "tournament"
REALTIME = "realtime"


@dataclass
class Progress:
    """Completed and total work for one loading bar. A total of -1 means an earlier phase is still counting."""
    completed: int = 0
    total: int = 0


# The loading bars, in drawing order after save and multi-turn progress.
PROGRESS_PHASES = ("save", "multi_turns", "letters", "proactive_tasks", "movement_tasks",
                   "proactive_llm_tasks", "responsive_tasks", "refresh_tasks")
SAVE_STAGES = 5


def new_progress():
    progress = {phase: Progress() for phase in PROGRESS_PHASES}
    progress["save"].total = SAVE_STAGES
    return progress


@dataclass
class SessionState:
    num_players: int = 1
    active_players: list = field(default_factory=list)
    current_player_index: int = 0
    player_country: str = "None"
    viewing_country: object = None
    tactical_mode: bool = False
    player_unit: object = None
    mode: str = LOCAL_PLAY
    editor_scenario_name: str = ""
    selection_mode: bool = False
    viewing_ai_moves: bool = False
    skip_ai_view: bool = False
    unit_event_read_turns: dict = field(default_factory=dict)
    # Local conversation appearance. Only disk saves include these preferences.
    conversation_colors: dict = field(default_factory=dict)
    ai_is_thinking: bool = False
    ai_processing_complete: bool = False
    is_refreshing: bool = False
    is_saving: bool = False
    progress: dict = field(default_factory=new_progress)
    thread_error: object = None
    force_skip_llm: bool = False
    multi_turn_processing_complete: bool = False
    multi_turn_abort_requested: bool = False
    loading_status_text: str = "Waiting..."
    proactive_llm_tasks: list = field(default_factory=list)
    proactive_choices: list = field(default_factory=list)
    # This turn's AI letters as (sender, receiver, text), held for the send phase.
    queued_letters: list = field(default_factory=list)
    # [sender, recipient] for each message a recipient's letter sitting answered this turn.
    letter_answers: list = field(default_factory=list)
    # Created country ID to (ordering country, release country).
    releases_this_turn: dict[str, tuple[str, str]] = field(default_factory=dict)
    turn_start_time: int = 0
    # Tournament host and player state.
    multiplayer_tournament_dir: object = None
    multiplayer_master_key: str = ""
    multiplayer_session_key: object = None
    multiplayer_keys_dict: dict = field(default_factory=dict)
    multiplayer_player_enc_cache: dict = field(default_factory=dict)
    multiplayer_protected_countries: set = field(default_factory=set)
    multiplayer_pending_key_regen: set = field(default_factory=set)
    submitted_moves: set = field(default_factory=set)
    # Shared edits made on a local planning map are sent as explicit commands.
    pending_faction_rename: str | None = None
    pending_subject_appearances: dict = field(default_factory=dict)
    # Real-time client drafts that travel as server-validated commands.
    realtime_volunteer_drafts: dict = field(default_factory=dict)
    # Map editor undo and redo stacks.
    editor_history: list = field(default_factory=list)
    editor_redo_history: list = field(default_factory=list)
    # Object IDs of units that moved during the current turn.
    _units_with_move_order_this_turn: set = field(default_factory=set)

    def __copy__(self):
        result = object.__new__(type(self))
        result.__dict__.update(self.__dict__)
        result.progress = {phase: copy.copy(counter) for phase, counter in self.progress.items()}
        result.releases_this_turn = self.releases_this_turn.copy()
        return result

    @property
    def is_editor(self):
        return self.mode == MAP_EDITOR

    @property
    def is_tournament(self):
        return self.mode == TOURNAMENT

    @property
    def is_realtime(self):
        return self.mode == REALTIME

    @property
    def is_networked(self):
        """Tournament and real-time play share hidden information and host-validated commands."""
        return self.mode in (TOURNAMENT, REALTIME)
