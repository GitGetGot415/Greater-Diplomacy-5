"""Own world data without presentation or transports."""

from dataclasses import dataclass, field
from map_logic.turn_processing.time_handler import TimeHandler


@dataclass
class WorldState:
    map_data: dict = field(default_factory=dict)
    id_to_province: dict = field(default_factory=dict)
    nation_data: dict = field(default_factory=dict)
    raw_json_data: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)
    scenario_settings: dict = field(default_factory=dict)
    script_variables: list = field(default_factory=list)
    default_research: object = None
    time_manager: TimeHandler = field(default_factory=TimeHandler)
    loop_map: bool = False
    map_w: int = 0
    map_h: int = 0
    unit_event_log: dict = field(default_factory=lambda: {"turn": 0, "events": []})
