"""Own world data without presentation or transports."""

import copy


from dataclasses import dataclass, field
from data.runtime_rules import RuntimeRules
from map_logic.system32.time_handler import TimeHandler

from data.world_nations import WorldNations


@dataclass
class WorldState:
    map_data: dict = field(default_factory=dict)
    id_to_province: dict = field(default_factory=dict)
    nation_data: dict = field(default_factory=dict)
    raw_json_data: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)
    scenario_settings: dict = field(default_factory=dict)
    runtime_rules: RuntimeRules = field(default_factory=RuntimeRules)
    factions: dict = field(default_factory=dict)
    faction_membership: dict = field(default_factory=dict)
    factions_initialized: bool = False
    diplomacy_revision: int = 0
    script_variables: list = field(default_factory=list)
    default_research: object = None
    time_manager: TimeHandler = field(default_factory=TimeHandler)
    loop_map: bool = False
    map_w: int = 0
    map_h: int = 0
    unit_event_log: dict = field(default_factory=lambda: {"turn": 0, "events": []})

    def __setattr__(self, name, value):
        if name == "nation_data":
            value = WorldNations(self, value)
            if "nation_data" in self.__dict__:
                object.__setattr__(self, "factions", {})
                object.__setattr__(self, "faction_membership", {})
                object.__setattr__(self, "factions_initialized", False)
        object.__setattr__(self, name, value)

    def __copy__(self):
        result = object.__new__(type(self))
        for name, value in self.__dict__.items():
            if name in ("scenario_settings", "runtime_rules", "factions", "faction_membership"):
                value = copy.deepcopy(value)
            elif isinstance(value, (dict, list)):
                value = value.copy()
            object.__setattr__(result, name, value)
        object.__setattr__(result, "nation_data", WorldNations(result, copy.deepcopy(self.nation_data)))
        return result

    def __deepcopy__(self, memo):
        result = object.__new__(type(self))
        memo[id(self)] = result
        for name, value in self.__dict__.items():
            object.__setattr__(result, name, copy.deepcopy(value, memo))
        object.__setattr__(result, "nation_data", WorldNations(result, result.nation_data))
        return result
