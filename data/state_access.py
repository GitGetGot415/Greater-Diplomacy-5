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

    # Rules read these on both map types. An instance value replaces each default.
    realtime_server_map = None
    realtime_match_metadata = None
    presentation_enabled = True
    visible_provinces = None
    ai_world = None
    random_settings = None
    unit_event_filter_turn = None
    _presentation_cache_revision = None
    _bilateral_response_indicator_cache = None
    _scripted_response_indicator_cache = None

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


class _Forward:
    """Forward one public map attribute to the field of the same name on its owner."""

    def __init__(self, owner, name):
        self.owner = owner
        self.name = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return _state_field(getattr(obj, self.owner), self.name)

    def __set__(self, obj, value):
        setattr(getattr(obj, self.owner), self.name, value)

    def __delete__(self, obj):
        del getattr(obj, self.owner).__dict__[self.name]


# Every session field is public on the map. World fields not listed here,
# such as factions and runtime_rules, are reached only through `world`.
WORLD_ATTRIBUTES = ("map_data", "id_to_province", "nation_data", "raw_json_data", "history",
                    "scenario_settings", "script_variables", "default_research", "time_manager",
                    "loop_map", "map_w", "map_h", "unit_event_log")
for _name in WORLD_ATTRIBUTES:
    setattr(StateAccess, _name, _Forward("world", _name))
for _field in fields(SessionState):
    setattr(StateAccess, _field.name, _Forward("session", _field.name))


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
