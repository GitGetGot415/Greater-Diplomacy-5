"""Provide explicit world and session access without shadow copies."""

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


# World and session fields have one owner. A map attribute with the same name would be a stale copy.
_OWNERS = {**{item.name: "world" for item in fields(WorldState)},
           **{item.name: "session" for item in fields(SessionState)}}


class StateAccess:
    """Own a context's world and session state. Their fields are reached only through those owners."""

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

    def __setattr__(self, name, value):
        owner = _OWNERS.get(name)
        if owner is not None:
            raise AttributeError(f"{name} belongs to {owner}. Set {owner}.{name} instead.")
        super().__setattr__(name, value)

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


def viewer_context(viewer, map_data, nation_data, id_to_province, tactical_unit=None):
    """A backend context that sees the given world as `viewer`, for fog queries.

    With a tactical unit, the viewer sees what that controlled division sees.
    """
    return BackendState(WorldState(map_data=map_data, nation_data=nation_data, id_to_province=id_to_province),
                        SessionState(player_country=viewer, tactical_mode=tactical_unit is not None,
                                     player_unit=tactical_unit))
