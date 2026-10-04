"""Record the latest resolved turn without changing game rules."""
from contextlib import contextmanager
from contextvars import ContextVar
import math

from data import queries
import data.constants as c

_RECORDER = ContextVar("unit_event_recorder", default=None)
EVENT_LABELS = {
    "DAMAGE_RECEIVED": "Damage received", "DAMAGE_DEALT": "Damage dealt",
    "DESTROYED": "Destroyed", "DISBANDED": "Disbanded", "DEPLOYED": "Deployed",
    "MOVED": "Moved", "REPAIRED": "Repaired", "CONVERTED": "Converted",
    "UPGRADED": "Upgraded", "EXPENDED": "Weapon expended",
}


def unit_name(unit):
    return unit.get("custom_name") or unit.get("type", "Unit")


def normalize_log(value, turn):
    """Discard stale reports and malformed fields at save/network boundaries."""
    empty = {"turn": turn, "events": []}
    if not isinstance(value, dict) or type(value.get("turn")) is not int or value["turn"] != turn:
        return empty
    events = value.get("events")
    if not isinstance(events, list):
        return empty
    for row in events:
        if not isinstance(row, dict) or not isinstance(row.get("event"), str) or row["event"] not in EVENT_LABELS:
            continue
        if not all(isinstance(row.get(key), str) for key in ("owner", "unit_id", "unit_name", "details")):
            continue
        if type(row.get("tile_id")) is not int:
            continue
        amount = row.get("amount", 0)
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
            continue
        entry = {key: row[key] for key in ("owner", "unit_id", "unit_name", "tile_id", "event", "details")}
        entry["amount"] = amount
        # Old reports have plain text. Ignore invalid optional details without losing the event.
        parts = row.get("detail_parts")
        if (isinstance(parts, list) and parts
                and all(isinstance(part, dict) and isinstance(part.get("text"), str)
                        and ("owner" not in part or isinstance(part["owner"], str) and bool(part["owner"]))
                        for part in parts)
                and "".join(part["text"] for part in parts) == entry["details"]):
            entry["detail_parts"] = [{key: part[key] for key in ("text", "owner") if key in part} for part in parts]
        empty["events"].append(entry)
    return empty


def saved_log(map_screen):
    # Old saves and lightweight map fixtures predate this field.
    return normalize_log(getattr(map_screen, "unit_event_log", None), map_screen.time_manager.total_turns)


def saved_reads(map_screen):
    # Old saves and lightweight map fixtures predate local report preferences.
    reads = getattr(map_screen, "unit_event_read_turns", {})
    return {owner: turn for owner, turn in reads.items()
            if isinstance(owner, str) and type(turn) is int and turn == map_screen.time_manager.total_turns}


def restore(map_screen, metadata):
    map_screen.unit_event_log = normalize_log(metadata.get("unit_event_log"), map_screen.time_manager.total_turns)
    reads = metadata.get("unit_event_read_turns", {})
    map_screen.unit_event_read_turns = {
        owner: turn for owner, turn in reads.items()
        if isinstance(owner, str) and type(turn) is int and turn == map_screen.time_manager.total_turns
    } if isinstance(reads, dict) else {}
    event_filter_for(map_screen)


def set_event_filter(map_screen, event):
    """Keep the event filter local to this report. Do not save or send it."""
    if event is not None and event not in EVENT_LABELS:
        raise ValueError("Select a known unit event type or None.")
    map_screen.unit_event_filter = event
    map_screen.unit_event_filter_turn = map_screen.time_manager.total_turns


def event_filter_for(map_screen):
    """Clear the local filter when a new turn arrives."""
    # Lightweight map fixtures can omit local display preferences.
    if getattr(map_screen, "unit_event_filter_turn", None) != map_screen.time_manager.total_turns:
        set_event_filter(map_screen, None)
    return map_screen.unit_event_filter


def entries_for(map_screen):
    """Limit reports to the viewer's units, including casualties no longer on the map."""
    rows = saved_log(map_screen)["events"]
    if map_screen.is_editor or map_screen.player_country == c.TOURNAMENT_SPECTATOR:
        return []
    if map_screen.player_country == "Spectator":
        return rows
    rows = [row for row in rows if row["owner"] == map_screen.player_country]
    if map_screen.tactical_mode:
        unit = map_screen.player_unit
        rows = [row for row in rows if unit and row["unit_id"] == unit.get("unit_id")]
    return rows


def refresh_presentation(map_screen):
    """Prepare the badge at a state or viewer boundary, never in a frame loop."""
    event_filter_for(map_screen)
    map_screen._unit_event_view = entries_for(map_screen)
    turn = map_screen.time_manager.total_turns
    reads = getattr(map_screen, "unit_event_read_turns", {})
    map_screen._unit_event_unread = (0 if reads.get(map_screen.player_country) == turn
                                    else len(map_screen._unit_event_view))


def mark_read(map_screen):
    # Read status is a local presentation preference, including on network clients.
    reads = getattr(map_screen, "unit_event_read_turns", {})
    turn = map_screen.time_manager.total_turns
    map_screen.unit_event_read_turns = {owner: value for owner, value in reads.items() if value == turn}
    map_screen.unit_event_read_turns[map_screen.player_country] = turn
    refresh_presentation(map_screen)


def mark_unread(map_screen):
    """Mark only the current viewer's last-turn report as unread."""
    map_screen.unit_event_read_turns = saved_reads(map_screen)
    map_screen.unit_event_read_turns.pop(map_screen.player_country, None)
    refresh_presentation(map_screen)


def _state(map_screen):
    return {id(unit): (unit, province["id"], unit.get("type", ""),
                      unit.get("health", 0))
            for province in map_screen.map_data.values() for unit in province.get("units", [])}


class _TurnRecorder:
    def __init__(self, map_screen):
        self.map_screen = map_screen
        queries.ensure_unit_ids(map_screen.map_data)
        self.state = _state(map_screen)
        self.locations = {identity: state[1] for identity, state in self.state.items()}
        self.rows = []
        self.visibility = {}
        self.phase = "Turn resolution"
        self.damage_seen = set()
        self.loss_tiles = {}
        self.expended = {}

    def tile(self, unit):
        return self.locations.get(id(unit), -1)

    def add(self, unit, event, tile=None, amount=0, details="", detail_parts=None):
        # Queue deployments also receive stable IDs before their first report.
        if not unit.get("unit_id"):
            queries.ensure_unit_ids(self.map_screen.map_data)
        row = {"owner": unit.get("owner", ""), "unit_id": unit.get("unit_id", ""),
                          "unit_name": unit_name(unit), "event": event,
                          "tile_id": self.tile(unit) if tile is None else tile,
                          "amount": amount, "details": details or self.phase}
        if detail_parts:
            row["detail_parts"] = detail_parts
        self.rows.append(row)

    def counterpart(self, viewer, unit):
        tile = self.tile(unit)
        if unit.get("owner") != viewer:
            if viewer not in self.visibility:
                from types import SimpleNamespace
                tactical = self.map_screen.tactical_mode and viewer == self.map_screen.player_country
                view = SimpleNamespace(player_country=viewer, map_data=self.map_screen.map_data,
                    nation_data=self.map_screen.nation_data, id_to_province=self.map_screen.id_to_province,
                    tactical_mode=tactical, player_unit=self.map_screen.player_unit if tactical else None)
                self.visibility[viewer] = queries.get_visible_provinces(view)[0]
            visible = self.visibility[viewer]
            province = self.map_screen.id_to_province.get(tile)
            fog = queries.get_scenario_flag("fog_of_war", c.DEFAULT_FOG_OF_WAR,
                                           self.map_screen.scenario_settings)
            if (province is None or fog and visible is not None and tile not in visible
                    or not queries.is_unit_visible_to(unit, viewer, province, self.map_screen.nation_data)):
                tile = "???"
        return {"text": f"{unit_name(unit)} (tile {tile})", "owner": unit["owner"]}

    def damage_details(self, viewer, units):
        parts = [{"text": f"{self.phase}: "}]
        for index, unit in enumerate(units):
            if index:
                parts.append({"text": "; "})
            parts.append(self.counterpart(viewer, unit))
        return parts

    def damage(self, unit, amount, sources, tile):
        if amount <= 0:
            return
        sources = [(source, weight) for source, weight in sources or () if weight > 0]
        # Combat details reveal unit identities, but hidden positions stay private.
        parts = self.damage_details(unit.get("owner"), [source for source, _weight in sources]) if sources else None
        self.add(unit, "DAMAGE_RECEIVED", tile, amount,
                 "".join(part["text"] for part in parts) if parts else self.phase, detail_parts=parts)
        self.damage_seen.add(id(unit))
        self.loss_tiles[id(unit)] = tile
        total = sum(weight for _source, weight in sources)
        for source, weight in sources:
            parts = self.damage_details(source.get("owner"), [unit])
            self.add(source, "DAMAGE_DEALT", tile, amount * weight / total,
                     "".join(part["text"] for part in parts), detail_parts=parts)

    def finish_step(self):
        current = _state(self.map_screen)
        for identity, (unit, tile, old_type, health) in self.state.items():
            after = current.get(identity)
            if after is None:
                event = "DISBANDED" if self.phase == "Disbanding" else "DESTROYED"
                if identity in self.expended:
                    event = "EXPENDED"
                if event == "DESTROYED" and health > 0 and identity not in self.damage_seen:
                    self.damage(unit, health, (), self.tile(unit))
                self.add(unit, event, self.expended.get(identity, self.loss_tiles.get(identity, self.tile(unit))))
                continue
            if after[1] != tile:
                self.add(unit, "MOVED", after[1], details=f"{self.phase}: from tile {tile}")
            if after[2] != old_type:
                event = "UPGRADED" if self.phase == "Upgrades" else "CONVERTED"
                self.add(unit, event, after[1], details=f"{old_type} -> {after[2]}")
            if after[3] > health and after[2] == old_type:
                self.add(unit, "REPAIRED", after[1], after[3] - health)
            if after[3] < health and identity not in self.damage_seen and after[2] == old_type:
                self.damage(unit, min(health, health - after[3]), (), after[1])
        for identity, (unit, tile, _type, _health) in current.items():
            if identity not in self.state:
                self.add(unit, "DEPLOYED", tile)
        self.state = current
        self.locations = {identity: state[1] for identity, state in current.items()}
        self.visibility.clear()
        self.damage_seen.clear()
        self.loss_tiles.clear()
        self.expended.clear()


@contextmanager
def record_turn(map_screen):
    recorder = _TurnRecorder(map_screen)
    token = _RECORDER.set(recorder)
    try:
        yield
        map_screen.unit_event_log = {"turn": map_screen.time_manager.total_turns, "events": recorder.rows}
        map_screen.unit_event_read_turns = {}
        set_event_filter(map_screen, None)
    finally:
        _RECORDER.reset(token)


def run_step(map_screen, label, function):
    recorder = _RECORDER.get()
    if recorder is not None:
        recorder.phase = label
    function(map_screen)
    if recorder is not None:
        recorder.finish_step()


def record_damage(unit, amount, sources=None, tile=None):
    recorder = _RECORDER.get()
    # Forecasts use copied units. They must never enter the authoritative report.
    if recorder is not None and id(unit) in recorder.state:
        recorder.damage(unit, amount, sources, recorder.tile(unit) if tile is None else tile)


def set_locations(province, units):
    """Update combat locations during movement without losing the initial position."""
    recorder = _RECORDER.get()
    if recorder is not None:
        for unit in units:
            recorder.locations[id(unit)] = province["id"]
        recorder.visibility.clear()


def record_grounded_air_loss(unit, enemies, nation_data):
    recorder = _RECORDER.get()
    if recorder is not None and id(unit) in recorder.state:
        sources = [(enemy, 1) for enemy in enemies if enemy is not unit and queries.are_at_war(
            queries.get_unit_combat_owner(unit), queries.get_unit_combat_owner(enemy), nation_data)]
        recorder.damage(unit, max(0, unit.get("health", 0)), sources, recorder.tile(unit))


def record_expended(unit, tile):
    recorder = _RECORDER.get()
    if recorder is not None and id(unit) in recorder.state:
        recorder.expended[id(unit)] = tile
