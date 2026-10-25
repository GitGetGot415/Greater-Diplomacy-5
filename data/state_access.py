"""Provide explicit state access and legacy map attributes without shadow copies."""

from data.game_state import WorldState
from data.session_state import SessionState
import copy
from dataclasses import fields


def world_for(context):
    # Legacy adapters and lightweight tests may still supply a flat context.
    return getattr(context, "world", context)


def session_for(context):
    # This compatibility boundary does not infer permissions or game modes.
    return getattr(context, "session", context)


def replace_mapping(owner, name, value):
    # Older flat contexts can receive their first dictionary during loading.
    current = getattr(owner, name, None)
    if current is None:
        setattr(owner, name, value)
        return
    if value is not current:
        current.clear()
        current.update(value)


def _state_field(owner, name):
    try:
        return owner.__dict__[name]
    except KeyError:
        raise AttributeError(name) from None


class StateAccess:
    """Keep public map attributes as explicit references to canonical owners."""

    def __copy__(self):
        result = object.__new__(type(self))
        result.__dict__.update(self.__dict__)
        for name in ("world", "session"):
            original = getattr(self, name)
            owner = copy.copy(original)
            if name == "world":
                result.world = owner
                continue
            for item in fields(owner):
                value = getattr(owner, item.name)
                if isinstance(value, (dict, list)):
                    setattr(owner, item.name, value.copy())
            setattr(result, name, owner)
        return result

    @property
    def world(self):
        # Map.__new__ is used by older callers and tests before construction.
        if "_world" not in self.__dict__:
            self._world = WorldState()
        return self._world

    @world.setter
    def world(self, value):
        self._world = value

    @property
    def session(self):
        if "_session" not in self.__dict__:
            self._session = SessionState()
        return self._session

    @session.setter
    def session(self, value):
        self._session = value

    @property
    def map_data(self):
        return _state_field(self.world, "map_data")

    @map_data.setter
    def map_data(self, value):
        self.world.map_data = value

    @map_data.deleter
    def map_data(self):
        del self.world.__dict__["map_data"]

    @property
    def id_to_province(self):
        return _state_field(self.world, "id_to_province")

    @id_to_province.setter
    def id_to_province(self, value):
        self.world.id_to_province = value

    @id_to_province.deleter
    def id_to_province(self):
        del self.world.__dict__["id_to_province"]

    @property
    def nation_data(self):
        return _state_field(self.world, "nation_data")

    @nation_data.setter
    def nation_data(self, value):
        self.world.nation_data = value

    @nation_data.deleter
    def nation_data(self):
        del self.world.__dict__["nation_data"]

    @property
    def raw_json_data(self):
        return _state_field(self.world, "raw_json_data")

    @raw_json_data.setter
    def raw_json_data(self, value):
        self.world.raw_json_data = value

    @raw_json_data.deleter
    def raw_json_data(self):
        del self.world.__dict__["raw_json_data"]

    @property
    def history(self):
        return _state_field(self.world, "history")

    @history.setter
    def history(self, value):
        self.world.history = value

    @history.deleter
    def history(self):
        del self.world.__dict__["history"]

    @property
    def scenario_settings(self):
        return _state_field(self.world, "scenario_settings")

    @scenario_settings.setter
    def scenario_settings(self, value):
        self.world.scenario_settings = value

    @scenario_settings.deleter
    def scenario_settings(self):
        del self.world.__dict__["scenario_settings"]

    @property
    def script_variables(self):
        return _state_field(self.world, "script_variables")

    @script_variables.setter
    def script_variables(self, value):
        self.world.script_variables = value

    @script_variables.deleter
    def script_variables(self):
        del self.world.__dict__["script_variables"]

    @property
    def default_research(self):
        return _state_field(self.world, "default_research")

    @default_research.setter
    def default_research(self, value):
        self.world.default_research = value

    @default_research.deleter
    def default_research(self):
        del self.world.__dict__["default_research"]

    @property
    def time_manager(self):
        return _state_field(self.world, "time_manager")

    @time_manager.setter
    def time_manager(self, value):
        self.world.time_manager = value

    @time_manager.deleter
    def time_manager(self):
        del self.world.__dict__["time_manager"]

    @property
    def loop_map(self):
        return _state_field(self.world, "loop_map")

    @loop_map.setter
    def loop_map(self, value):
        self.world.loop_map = value

    @loop_map.deleter
    def loop_map(self):
        del self.world.__dict__["loop_map"]

    @property
    def map_w(self):
        return _state_field(self.world, "map_w")

    @map_w.setter
    def map_w(self, value):
        self.world.map_w = value

    @map_w.deleter
    def map_w(self):
        del self.world.__dict__["map_w"]

    @property
    def map_h(self):
        return _state_field(self.world, "map_h")

    @map_h.setter
    def map_h(self, value):
        self.world.map_h = value

    @map_h.deleter
    def map_h(self):
        del self.world.__dict__["map_h"]

    @property
    def unit_event_log(self):
        return _state_field(self.world, "unit_event_log")

    @unit_event_log.setter
    def unit_event_log(self, value):
        self.world.unit_event_log = value

    @unit_event_log.deleter
    def unit_event_log(self):
        del self.world.__dict__["unit_event_log"]

    @property
    def num_players(self):
        return _state_field(self.session, "num_players")

    @num_players.setter
    def num_players(self, value):
        self.session.num_players = value

    @num_players.deleter
    def num_players(self):
        del self.session.__dict__["num_players"]

    @property
    def active_players(self):
        return _state_field(self.session, "active_players")

    @active_players.setter
    def active_players(self, value):
        self.session.active_players = value

    @active_players.deleter
    def active_players(self):
        del self.session.__dict__["active_players"]

    @property
    def current_player_index(self):
        return _state_field(self.session, "current_player_index")

    @current_player_index.setter
    def current_player_index(self, value):
        self.session.current_player_index = value

    @current_player_index.deleter
    def current_player_index(self):
        del self.session.__dict__["current_player_index"]

    @property
    def player_country(self):
        return _state_field(self.session, "player_country")

    @player_country.setter
    def player_country(self, value):
        self.session.player_country = value

    @player_country.deleter
    def player_country(self):
        del self.session.__dict__["player_country"]

    @property
    def viewing_country(self):
        return _state_field(self.session, "viewing_country")

    @viewing_country.setter
    def viewing_country(self, value):
        self.session.viewing_country = value

    @viewing_country.deleter
    def viewing_country(self):
        del self.session.__dict__["viewing_country"]

    @property
    def tactical_mode(self):
        return _state_field(self.session, "tactical_mode")

    @tactical_mode.setter
    def tactical_mode(self, value):
        self.session.tactical_mode = value

    @tactical_mode.deleter
    def tactical_mode(self):
        del self.session.__dict__["tactical_mode"]

    @property
    def player_unit(self):
        return _state_field(self.session, "player_unit")

    @player_unit.setter
    def player_unit(self, value):
        self.session.player_unit = value

    @player_unit.deleter
    def player_unit(self):
        del self.session.__dict__["player_unit"]

    @property
    def unit_economy(self):
        return _state_field(self.session, "unit_economy")

    @unit_economy.setter
    def unit_economy(self, value):
        self.session.unit_economy = value

    @unit_economy.deleter
    def unit_economy(self):
        del self.session.__dict__["unit_economy"]

    @property
    def is_editor(self):
        return _state_field(self.session, "is_editor")

    @is_editor.setter
    def is_editor(self, value):
        self.session.is_editor = value

    @is_editor.deleter
    def is_editor(self):
        del self.session.__dict__["is_editor"]

    @property
    def selection_mode(self):
        return _state_field(self.session, "selection_mode")

    @selection_mode.setter
    def selection_mode(self, value):
        self.session.selection_mode = value

    @selection_mode.deleter
    def selection_mode(self):
        del self.session.__dict__["selection_mode"]

    @property
    def viewing_ai_moves(self):
        return _state_field(self.session, "viewing_ai_moves")

    @viewing_ai_moves.setter
    def viewing_ai_moves(self, value):
        self.session.viewing_ai_moves = value

    @viewing_ai_moves.deleter
    def viewing_ai_moves(self):
        del self.session.__dict__["viewing_ai_moves"]

    @property
    def skip_ai_view(self):
        return _state_field(self.session, "skip_ai_view")

    @skip_ai_view.setter
    def skip_ai_view(self, value):
        self.session.skip_ai_view = value

    @skip_ai_view.deleter
    def skip_ai_view(self):
        del self.session.__dict__["skip_ai_view"]

    @property
    def multiplayer_mode(self):
        return _state_field(self.session, "multiplayer_mode")

    @multiplayer_mode.setter
    def multiplayer_mode(self, value):
        self.session.multiplayer_mode = value

    @multiplayer_mode.deleter
    def multiplayer_mode(self):
        del self.session.__dict__["multiplayer_mode"]

    @property
    def realtime_multiplayer(self):
        return _state_field(self.session, "realtime_multiplayer")

    @realtime_multiplayer.setter
    def realtime_multiplayer(self, value):
        self.session.realtime_multiplayer = value

    @realtime_multiplayer.deleter
    def realtime_multiplayer(self):
        del self.session.__dict__["realtime_multiplayer"]

    @property
    def unit_event_read_turns(self):
        return _state_field(self.session, "unit_event_read_turns")

    @unit_event_read_turns.setter
    def unit_event_read_turns(self, value):
        self.session.unit_event_read_turns = value

    @unit_event_read_turns.deleter
    def unit_event_read_turns(self):
        del self.session.__dict__["unit_event_read_turns"]

    @property
    def ai_is_thinking(self):
        return _state_field(self.session, "ai_is_thinking")

    @ai_is_thinking.setter
    def ai_is_thinking(self, value):
        self.session.ai_is_thinking = value

    @ai_is_thinking.deleter
    def ai_is_thinking(self):
        del self.session.__dict__["ai_is_thinking"]

    @property
    def ai_processing_complete(self):
        return _state_field(self.session, "ai_processing_complete")

    @ai_processing_complete.setter
    def ai_processing_complete(self, value):
        self.session.ai_processing_complete = value

    @ai_processing_complete.deleter
    def ai_processing_complete(self):
        del self.session.__dict__["ai_processing_complete"]

    @property
    def is_refreshing(self):
        return _state_field(self.session, "is_refreshing")

    @is_refreshing.setter
    def is_refreshing(self, value):
        self.session.is_refreshing = value

    @is_refreshing.deleter
    def is_refreshing(self):
        del self.session.__dict__["is_refreshing"]

    @property
    def is_saving(self):
        return _state_field(self.session, "is_saving")

    @is_saving.setter
    def is_saving(self, value):
        self.session.is_saving = value

    @is_saving.deleter
    def is_saving(self):
        del self.session.__dict__["is_saving"]

    @property
    def save_progress_completed(self):
        return _state_field(self.session, "save_progress_completed")

    @save_progress_completed.setter
    def save_progress_completed(self, value):
        self.session.save_progress_completed = value

    @save_progress_completed.deleter
    def save_progress_completed(self):
        del self.session.__dict__["save_progress_completed"]

    @property
    def save_progress_total(self):
        return _state_field(self.session, "save_progress_total")

    @save_progress_total.setter
    def save_progress_total(self, value):
        self.session.save_progress_total = value

    @save_progress_total.deleter
    def save_progress_total(self):
        del self.session.__dict__["save_progress_total"]

    @property
    def thread_error(self):
        return _state_field(self.session, "thread_error")

    @thread_error.setter
    def thread_error(self, value):
        self.session.thread_error = value

    @thread_error.deleter
    def thread_error(self):
        del self.session.__dict__["thread_error"]

    @property
    def force_skip_llm(self):
        return _state_field(self.session, "force_skip_llm")

    @force_skip_llm.setter
    def force_skip_llm(self, value):
        self.session.force_skip_llm = value

    @force_skip_llm.deleter
    def force_skip_llm(self):
        del self.session.__dict__["force_skip_llm"]

    @property
    def multi_turn_processing_complete(self):
        return _state_field(self.session, "multi_turn_processing_complete")

    @multi_turn_processing_complete.setter
    def multi_turn_processing_complete(self, value):
        self.session.multi_turn_processing_complete = value

    @multi_turn_processing_complete.deleter
    def multi_turn_processing_complete(self):
        del self.session.__dict__["multi_turn_processing_complete"]

    @property
    def multi_turns_total(self):
        return _state_field(self.session, "multi_turns_total")

    @multi_turns_total.setter
    def multi_turns_total(self, value):
        self.session.multi_turns_total = value

    @multi_turns_total.deleter
    def multi_turns_total(self):
        del self.session.__dict__["multi_turns_total"]

    @property
    def multi_turns_completed(self):
        return _state_field(self.session, "multi_turns_completed")

    @multi_turns_completed.setter
    def multi_turns_completed(self, value):
        self.session.multi_turns_completed = value

    @multi_turns_completed.deleter
    def multi_turns_completed(self):
        del self.session.__dict__["multi_turns_completed"]

    @property
    def multi_turn_abort_requested(self):
        return _state_field(self.session, "multi_turn_abort_requested")

    @multi_turn_abort_requested.setter
    def multi_turn_abort_requested(self, value):
        self.session.multi_turn_abort_requested = value

    @multi_turn_abort_requested.deleter
    def multi_turn_abort_requested(self):
        del self.session.__dict__["multi_turn_abort_requested"]

    @property
    def loading_status_text(self):
        return _state_field(self.session, "loading_status_text")

    @loading_status_text.setter
    def loading_status_text(self, value):
        self.session.loading_status_text = value

    @loading_status_text.deleter
    def loading_status_text(self):
        del self.session.__dict__["loading_status_text"]

    @property
    def proactive_tasks_total(self):
        return _state_field(self.session, "proactive_tasks_total")

    @proactive_tasks_total.setter
    def proactive_tasks_total(self, value):
        self.session.proactive_tasks_total = value

    @proactive_tasks_total.deleter
    def proactive_tasks_total(self):
        del self.session.__dict__["proactive_tasks_total"]

    @property
    def proactive_tasks_completed(self):
        return _state_field(self.session, "proactive_tasks_completed")

    @proactive_tasks_completed.setter
    def proactive_tasks_completed(self, value):
        self.session.proactive_tasks_completed = value

    @proactive_tasks_completed.deleter
    def proactive_tasks_completed(self):
        del self.session.__dict__["proactive_tasks_completed"]

    @property
    def proactive_llm_tasks_total(self):
        return _state_field(self.session, "proactive_llm_tasks_total")

    @proactive_llm_tasks_total.setter
    def proactive_llm_tasks_total(self, value):
        self.session.proactive_llm_tasks_total = value

    @proactive_llm_tasks_total.deleter
    def proactive_llm_tasks_total(self):
        del self.session.__dict__["proactive_llm_tasks_total"]

    @property
    def proactive_llm_tasks_completed(self):
        return _state_field(self.session, "proactive_llm_tasks_completed")

    @proactive_llm_tasks_completed.setter
    def proactive_llm_tasks_completed(self, value):
        self.session.proactive_llm_tasks_completed = value

    @proactive_llm_tasks_completed.deleter
    def proactive_llm_tasks_completed(self):
        del self.session.__dict__["proactive_llm_tasks_completed"]

    @property
    def proactive_llm_tasks(self):
        return _state_field(self.session, "proactive_llm_tasks")

    @proactive_llm_tasks.setter
    def proactive_llm_tasks(self, value):
        self.session.proactive_llm_tasks = value

    @proactive_llm_tasks.deleter
    def proactive_llm_tasks(self):
        del self.session.__dict__["proactive_llm_tasks"]

    @property
    def proactive_choices(self):
        return _state_field(self.session, "proactive_choices")

    @proactive_choices.setter
    def proactive_choices(self, value):
        self.session.proactive_choices = value

    @proactive_choices.deleter
    def proactive_choices(self):
        del self.session.__dict__["proactive_choices"]

    @property
    def responsive_tasks_total(self):
        return _state_field(self.session, "responsive_tasks_total")

    @responsive_tasks_total.setter
    def responsive_tasks_total(self, value):
        self.session.responsive_tasks_total = value

    @responsive_tasks_total.deleter
    def responsive_tasks_total(self):
        del self.session.__dict__["responsive_tasks_total"]

    @property
    def responsive_tasks_completed(self):
        return _state_field(self.session, "responsive_tasks_completed")

    @responsive_tasks_completed.setter
    def responsive_tasks_completed(self, value):
        self.session.responsive_tasks_completed = value

    @responsive_tasks_completed.deleter
    def responsive_tasks_completed(self):
        del self.session.__dict__["responsive_tasks_completed"]

    @property
    def summits_total(self):
        return _state_field(self.session, "summits_total")

    @summits_total.setter
    def summits_total(self, value):
        self.session.summits_total = value

    @summits_total.deleter
    def summits_total(self):
        del self.session.__dict__["summits_total"]

    @property
    def summits_completed(self):
        return _state_field(self.session, "summits_completed")

    @summits_completed.setter
    def summits_completed(self, value):
        self.session.summits_completed = value

    @summits_completed.deleter
    def summits_completed(self):
        del self.session.__dict__["summits_completed"]

    @property
    def refresh_tasks_total(self):
        return _state_field(self.session, "refresh_tasks_total")

    @refresh_tasks_total.setter
    def refresh_tasks_total(self, value):
        self.session.refresh_tasks_total = value

    @refresh_tasks_total.deleter
    def refresh_tasks_total(self):
        del self.session.__dict__["refresh_tasks_total"]

    @property
    def refresh_tasks_completed(self):
        return _state_field(self.session, "refresh_tasks_completed")

    @refresh_tasks_completed.setter
    def refresh_tasks_completed(self, value):
        self.session.refresh_tasks_completed = value

    @refresh_tasks_completed.deleter
    def refresh_tasks_completed(self):
        del self.session.__dict__["refresh_tasks_completed"]

    @property
    def turn_start_time(self):
        return _state_field(self.session, "turn_start_time")

    @turn_start_time.setter
    def turn_start_time(self, value):
        self.session.turn_start_time = value

    @turn_start_time.deleter
    def turn_start_time(self):
        del self.session.__dict__["turn_start_time"]


class BackendState(StateAccess):
    """Execute game rules with world and session data and explicit callbacks."""

    def __init__(self, world=None, session=None, *, feedback=None):
        self.world = world if world is not None else WorldState()
        self.session = session if session is not None else SessionState()
        self.feedback = feedback
        self.presentation_enabled = False
        self.history_turn = None
        self.nation_colors = {}
        self.ai_world = None
        self.load_path = None
        self.random_settings = None
        self.visible_provinces = None
        self.country_economy_summaries = {}

    def show_feedback(self, message):
        if self.feedback is not None:
            self.feedback(message)
