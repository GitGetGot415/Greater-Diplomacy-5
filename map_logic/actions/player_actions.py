"""Validate and apply player choices independently of network transports."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Callable

import data.constants as c
from data.state_access import world_for, session_for
from map_logic import politics

from data.game_state import WorldState
from data.state_access import BackendState
from data import queries
from map_logic.diplomacy import volunteers, faction_actions, diplomacy_messages, peace_scope, diplomacy_lifecycle as lifecycle
from map_logic.diplomacy.puppet_actions import canonical_puppet_release_queue
from map_logic.diplomacy.action_definitions import BILATERAL_ACTIONS, UNILATERAL_ACTIONS, availability
from map_logic.actions import unit_actions, production_actions
from map_logic.actions.production_actions import (
    validate_queue_budget,
    settle_draft_budget,
    apply_queue_change,
)
from map_logic.actions.unit_actions import apply_action
from map_logic.system32.research_processor import apply_research_selection


class PlayerActionError(ValueError):
    """A player choice cannot be applied to the current world."""


class PlayerActions:
    """Own domain validation and application for complete player drafts."""
    _AUTOMATION_KEYS = {"construction", "movement", "research"}
    _APPEARANCE_KEYS = set(c.COUNTRY_APPEARANCE_FIELDS)
    _MAX_CLAIM_DRAFTS = 100
    _MAX_QUEUE_ITEMS = 100

    def __init__(self, context, session=None):
        self.context = BackendState(context, session) if isinstance(context, WorldState) else context
        self.world = world_for(self.context)
        self.session = session_for(self.context)

    def validate_draft(self, country_id: str, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(commands, list):
            raise PlayerActionError("Player intents must be a list.")
        self._country(country_id)
        planning_view = self._planning_view(country_id, commands)
        transport_commands = [command for command in commands
                              if isinstance(command, dict) and command.get("type") == "air_transport"]
        try:
            transport_view, canonical = (queries.air_transport_draft(planning_view, country_id, transport_commands)
                                         if transport_commands else (planning_view, []))
        except ValueError as exc:
            raise PlayerActionError(str(exc)) from exc
        seen = set()
        seen_units = set()
        seen_queues = set()
        for command in commands:
            if not isinstance(command, dict):
                raise PlayerActionError("Invalid order command.")
            kind = command.get("type")
            if not isinstance(kind, str):
                raise PlayerActionError("Invalid command type.")
            definition = _COUNTRY_COMMANDS.get(kind)
            # A country draft specifies at most one complete choice per domain.
            if definition and kind in seen:
                raise PlayerActionError("Only one command is allowed for that game action.")
            if kind == "unit_order":
                validated = self._validate_unit_order(country_id, command, context=transport_view)
                identity = (validated["province_id"], validated["unit_index"])
                if identity in seen_units:
                    raise PlayerActionError("Only one order is allowed per unit.")
                seen_units.add(identity)
                canonical.append(validated)
            elif kind == "air_transport":
                continue  # The complete cargo projection was validated above.
            elif kind == "province_queue":
                entry = self._validate_queue(country_id, command)
                key = (entry["province_id"], entry["queue"])
                if key in seen_queues:
                    raise PlayerActionError("Only one projection is allowed per province queue.")
                seen_queues.add(key)
                canonical.append(entry)
            elif definition:
                validated = (definition.validate(self, country_id, command, context=transport_view)
                             if definition.uses_transport_view else definition.validate(self, country_id, command))
                canonical.append({"type": kind, **validated})
            elif kind == "volunteer_draft":
                canonical.append(self._validate_volunteer_draft(country_id, command, context=transport_view))
            else:
                raise PlayerActionError("That order type is not supported by the server.")
            seen.add(kind)
        self._validate_queue_budget(country_id, canonical)
        self._validate_volunteer_commands(country_id, canonical, context=planning_view)
        return canonical

    def _collect_army_roster(self, country_id):
        country_data = self.world.nation_data.get(country_id, {})
        return {"armies": copy.deepcopy(country_data.get("armies", []))}

    def _apply_army_roster(self, country_id, command):
        country_data = self.world.nation_data[country_id]
        country_data["armies"] = copy.deepcopy(command["armies"])

    def _validate_army_roster(self, country_id: str, command: dict[str, Any], *, context=None) -> dict[str, Any]:
        """Validate organization metadata without trusting client unit ownership."""
        supplied = command.get("armies", [])
        if not isinstance(supplied, list) or len(supplied) > 200:
            raise PlayerActionError("Invalid army roster.")
        world = self.world if context is None else world_for(context)
        owned = {unit.get("unit_id") for province in world.map_data.values()
                 for unit in queries.units_with_air_cargo(province.get("units", []))
                 if unit.get("owner") == country_id}
        armies, army_ids, assigned = [], set(), set()
        for raw in supplied:
            if not isinstance(raw, dict):
                raise PlayerActionError("Invalid army roster.")
            army_id, name, unit_ids = raw.get("id"), raw.get("name"), raw.get("unit_ids")
            symbol = raw.get("symbol", "")
            symbol_color = raw.get("symbol_color", list(c.DEFAULT_ARMY_SYMBOL_COLOR))
            symbol_rotation = raw.get("symbol_rotation", c.DEFAULT_ARMY_SYMBOL_ROTATION)
            symbol_flipped = raw.get("symbol_flipped", c.DEFAULT_ARMY_SYMBOL_FLIPPED)
            custom_symbol = raw.get("custom_symbol")
            defense_area = raw.get("defense_area", [])
            valid_symbol = (isinstance(symbol, str)
                            and (not symbol or queries.normalize_army_symbol(symbol) == symbol))
            valid_color = (isinstance(symbol_color, list)
                           and queries.normalize_army_symbol_color(symbol_color) == symbol_color)
            valid_rotation = (isinstance(symbol_rotation, int)
                              and not isinstance(symbol_rotation, bool)
                              and queries.normalize_army_symbol_rotation(symbol_rotation)
                              == symbol_rotation)
            valid_flipped = (isinstance(symbol_flipped, bool)
                             and queries.normalize_army_symbol_flipped(symbol_flipped)
                             == symbol_flipped)
            valid_custom_symbol = (custom_symbol is None
                                   or queries.normalize_army_custom_symbol(custom_symbol)
                                   == custom_symbol)
            valid_defense_area = (
                isinstance(defense_area, list)
                and queries.normalize_army_defense_area(
                    defense_area, self.world.map_data) == defense_area)
            if (not isinstance(army_id, str) or not army_id or len(army_id) > 80
                    or army_id == c.UNASSIGNED_ARMY_ID
                    or army_id in army_ids or not isinstance(name, str)
                    or not name.strip() or len(name.strip()) > 80
                    or not isinstance(unit_ids, list) or len(unit_ids) > len(owned)
                    or not valid_symbol or not valid_color or not valid_rotation or not valid_flipped
                    or not valid_custom_symbol or not valid_defense_area
                    or (symbol and custom_symbol)):
                raise PlayerActionError("Invalid army roster.")
            if any(not isinstance(unit_id, str) or unit_id not in owned
                   or unit_id in assigned for unit_id in unit_ids):
                raise PlayerActionError("Army members must be distinct owned units.")
            army_ids.add(army_id)
            assigned.update(unit_ids)
            if unit_ids:
                armies.append({"id": army_id, "name": name.strip(),
                               "unit_ids": list(unit_ids), "symbol": symbol,
                               "symbol_color": list(symbol_color),
                               "symbol_rotation": symbol_rotation,
                               "symbol_flipped": symbol_flipped,
                               "custom_symbol": copy.deepcopy(custom_symbol),
                               "defense_area": list(defense_area)})
        try:
            queries.validate_air_drop_recovery_armies(country_id, armies, self.world.nation_data,
                                                      self.world.map_data)
        except ValueError as exc:
            raise PlayerActionError(str(exc)) from exc
        return {"armies": armies}

    def _validate_volunteer_commands(self, country_id: str, commands: list[dict[str, Any]], *, context=None) -> None:
        """Keep a volunteer request and its reserved divisions inseparable."""
        pending_targets = set()
        offered_targets, offered_count = set(), 0
        reserved_units = set()
        for command in commands:
            if command.get("type") == "country_diplomacy":
                pending_targets = {target for target, info in command.get("pending", {}).items()
                                   if isinstance(info, dict) and info.get("action") == volunteers.ACTION}
            elif command.get("type") == "volunteer_draft":
                target = command["target"]
                if target in offered_targets:
                    raise PlayerActionError("Only one volunteer offer may be made to each country.")
                offered_targets.add(target)
                offered_count += len(command["units"])
                for unit in command["units"]:
                    identity = unit.get("unit_id") or (unit["province_id"], unit["unit_index"])
                    if identity in reserved_units:
                        raise PlayerActionError("A division may only join one volunteer offer.")
                    reserved_units.add(identity)
        if pending_targets != offered_targets:
            raise PlayerActionError("Volunteer offers must include their selected divisions.")
        if offered_count:
            view = volunteers.draft_context(self.context if context is None else context, country_id,
                                            always_copy=True)
            if offered_count > volunteers.remaining_capacity(view, country_id):
                raise PlayerActionError("The selected volunteer divisions exceed your available capacity.")

    def _country(self, country_id: str) -> dict[str, Any]:
        country = self.world.nation_data.get(country_id)
        if not isinstance(country, dict):
            raise PlayerActionError("Unknown player country.")
        return country

    def _planning_view(self, country_id, commands):
        if any(isinstance(command, dict) and command.get("type") == "country_diplomacy" for command in commands):
            return volunteers.draft_context(self.context, country_id)
        return self.context

    def _is_local_tournament_player(self, country_id):
        return (self.session.is_tournament and not self.session.is_realtime
                and self.session.player_country == country_id)

    def _collect_country_preferences(self, country_id):
        country_data = self.world.nation_data.get(country_id, {})
        return {**{axis["drift_key"]: politics.axis_drift(self.world.nation_data, country_id, axis["id"])
                   for axis in politics.AXES},
                "automation": copy.deepcopy(country_data.get("automation", {})),
                "conscription_slider": queries.get_conscription_rate(country_data),
                "mat_to_fuel_slider": queries.get_fuel_conversion_rate(country_data),
                "research_funding_slider": queries.get_research_funding_rate(country_data),
                "custom_production_units": copy.deepcopy(country_data.get("custom_production_units", [])),
                politics.POLICY_KEY: politics.policy_draft_projection(
                    self.world.nation_data, country_id)}

    def _apply_country_preferences(self, country_id, command):
        country_data = self.world.nation_data[country_id]
        # Older moves can omit an axis; its drift on the host stays as it is.
        for axis in politics.AXES:
            if axis["drift_key"] in command:
                politics.set_axis_drift(self.world.nation_data, country_id, axis["id"], command[axis["drift_key"]])
        country_data["automation"] = copy.deepcopy(command["automation"])
        country_data["conscription_slider"] = command["conscription_slider"]
        country_data["mat_to_fuel_slider"] = command["mat_to_fuel_slider"]
        if "research_funding_slider" in command:
            country_data["research_funding_slider"] = command["research_funding_slider"]
        country_data["custom_production_units"] = copy.deepcopy(command["custom_production_units"])
        stat_policies = politics.unit_stat_policies(self.world.nation_data, country_id)
        if command[politics.POLICY_KEY]:
            country_data[politics.POLICY_KEY] = copy.deepcopy(command[politics.POLICY_KEY])
        else:
            country_data.pop(politics.POLICY_KEY, None)
        queries.refresh_policy_unit_stats(self.context, country_id, stat_policies)

    def _validate_country_preferences(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Validate politics, automation, economy, and custom unit choices."""

        country = self._country(country_id)
        automation = command.get("automation", {})
        if set(politics.VALUE_KEYS) & set(command):
            raise PlayerActionError("The host controls political positions.")
        # Every move carries the political direction; older moves may omit the others.
        drifts = {}
        for axis in politics.AXES:
            key = axis["drift_key"]
            if key not in command and axis["id"] != politics.POLITICAL:
                continue
            direction = command.get(key, 0)
            if type(direction) is not int or direction not in (-1, 0, 1):
                raise PlayerActionError(f"Invalid {axis['name'].lower()} direction.")
            if not politics.can_shift(politics.axis_value(self.world.nation_data, country_id, axis["id"]), direction):
                raise PlayerActionError(f"The {axis['name'].lower()} position is already at the end of that direction.")
            drifts[key] = direction
        if not isinstance(automation, dict) or set(automation) - self._AUTOMATION_KEYS:
            raise PlayerActionError("Invalid automation settings.")
        if any(not isinstance(value, bool) for value in automation.values()):
            raise PlayerActionError("Invalid automation settings.")
        conscription = queries.get_conscription_rate(command)
        if not queries.valid_slider_rate(conscription):
            raise PlayerActionError("Invalid manpower conversion setting.")
        max_conversion = max(0.0, float(queries.get_max_fuel_conversion(country)))
        # Validate the submitted value itself; the shared getter would clamp an over-limit rate.
        fuel_conversion = command.get("mat_to_fuel_slider", queries.get_fuel_conversion_rate(command, max_conversion=max_conversion))
        if not queries.valid_slider_rate(fuel_conversion, max_conversion):
            raise PlayerActionError("Invalid material-to-fuel conversion setting.")
        research_funding = {}
        if "research_funding_slider" in command:
            rate = command["research_funding_slider"]
            if not queries.valid_slider_rate(rate):
                raise PlayerActionError("Invalid research funding setting.")
            research_funding["research_funding_slider"] = float(rate)
        custom_units = command.get("custom_production_units", [])
        if (not isinstance(custom_units, list) or len(custom_units) > 100
                or any(not isinstance(name, str) for name in custom_units)
                or len(set(custom_units)) != len(custom_units)):
            raise PlayerActionError("Invalid custom production selection.")
        unit_library = queries.get_unit_library(self.context)
        research = country.get("research", {})
        if any(name not in unit_library or not queries.is_unit_unlocked(name, research, context=self.context)
               for name in custom_units):
            raise PlayerActionError("A selected custom unit is not researched.")
        try:
            policies = politics.canonicalize_policy_draft(
                self.world.nation_data, country_id, command.get(politics.POLICY_KEY, {}))
        except ValueError as exc:
            raise PlayerActionError(str(exc)) from exc
        return {**drifts,
                "automation": {key: bool(automation.get(key, False))
                               for key in self._AUTOMATION_KEYS},
                "conscription_slider": float(conscription),
                "mat_to_fuel_slider": float(fuel_conversion),
                **research_funding,
                "custom_production_units": list(custom_units),
                politics.POLICY_KEY: policies}

    def _collect_claim_draft(self, country_id):
        # Send the selected provinces. The host keeps or starts the timers.
        country_data = self.world.nation_data.get(country_id, {})
        claim_queue = country_data.get("claim_queue", []) if isinstance(country_data, dict) else []
        return {"province_ids": [entry.get("prov_id")
                for entry in claim_queue if isinstance(entry, dict)
                and isinstance(entry.get("prov_id"), int)
                and not isinstance(entry.get("prov_id"), bool)],
                "revoke_ids": [entry.get("prov_id") for entry in country_data.get("revoke_queue", [])
                               if isinstance(entry, dict) and isinstance(entry.get("prov_id"), int)
                               and not isinstance(entry.get("prov_id"), bool)],
                "returns": [{"prov_id": entry.get("prov_id"), "recipient": entry.get("recipient")}
                            for entry in country_data.get("return_queue", [])
                            if isinstance(entry, dict)]}

    def _apply_claim_draft(self, country_id, command):
        country_data = self.world.nation_data[country_id]
        country_data["claim_queue"] = copy.deepcopy(command["queue"])
        country_data["revoke_queue"] = copy.deepcopy(command["revokes"])
        country_data["return_queue"] = copy.deepcopy(command["returns"])

    def _validate_claim_draft(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Validate a player's desired claim queue without trusting timers.

        Clients name the provinces they want to keep in their queue. The
        authoritative map retains timers for existing entries and assigns the
        normal fabrication duration to new ones. This lets a player add or
        cancel claims while preventing forged instant claims or countdowns.
        """
        country = self._country(country_id)
        requested = command.get("province_ids", [])
        requested_revokes = command.get("revoke_ids", [])
        requested_returns = command.get("returns", [])
        if (not isinstance(requested, list) or len(requested) > self._MAX_CLAIM_DRAFTS
                or any(isinstance(province_id, bool) or not isinstance(province_id, int)
                       for province_id in requested)
                or len(set(requested)) != len(requested)):
            raise PlayerActionError("Invalid claim draft.")
        if (not isinstance(requested_revokes, list) or len(requested_revokes) > self._MAX_CLAIM_DRAFTS
                or any(isinstance(province_id, bool) or not isinstance(province_id, int)
                       for province_id in requested_revokes)
                or len(set(requested_revokes)) != len(requested_revokes)):
            raise PlayerActionError("Invalid claim revocation draft.")
        if (not isinstance(requested_returns, list) or len(requested_returns) > self._MAX_CLAIM_DRAFTS
                or any(not isinstance(entry, dict) for entry in requested_returns)):
            raise PlayerActionError("Invalid territory return draft.")

        existing = {}
        for entry in country.get("claim_queue", []):
            if not isinstance(entry, dict):
                continue
            province_id, turns_left = entry.get("prov_id"), entry.get("turns_left")
            if (isinstance(province_id, int) and not isinstance(province_id, bool)
                    and isinstance(turns_left, int) and not isinstance(turns_left, bool)):
                existing[province_id] = {"prov_id": province_id, "turns_left": max(0, turns_left)}

        claims = set(country.get("claims", []))
        queue = []
        for province_id in requested:
            if province_id in existing:
                # This entry was accepted by the server on an earlier turn;
                # preserve its authoritative remaining time exactly.
                queue.append(existing[province_id])
                continue
            province = self._province(province_id)
            owner = province.get("owner")
            if owner == country_id or owner in c.UNPLAYABLE_NATIONS:
                raise PlayerActionError("Claims must target a foreign playable province.")
            if province_id in claims:
                raise PlayerActionError("That province is already claimed.")
            queue.append({"prov_id": province_id, "turns_left": c.CLAIM_TURN_NON_CORE})
        existing_revokes = {entry.get("prov_id"): entry for entry in country.get("revoke_queue", [])
                            if isinstance(entry, dict) and isinstance(entry.get("prov_id"), int)}
        revokes = []
        claims = set(country.get("claims", []))
        for province_id in requested_revokes:
            province = self._province(province_id)
            if province.get("owner") != country_id:
                raise PlayerActionError("Only owned territory can have its claim revoked.")
            if province_id not in claims and country_id not in province.get("cores", []):
                raise PlayerActionError("That territory has no claim or core to revoke.")
            old = existing_revokes.get(province_id)
            revokes.append({"prov_id": province_id,
                            "turns_left": max(0, int(old.get("turns_left", 1))) if old else 1})

        existing_returns = {entry.get("prov_id"): entry for entry in country.get("return_queue", [])
                            if isinstance(entry, dict) and isinstance(entry.get("prov_id"), int)}
        returns, returned_ids = [], set()
        for entry in requested_returns:
            province_id, recipient = entry.get("prov_id"), entry.get("recipient")
            if (isinstance(province_id, bool) or not isinstance(province_id, int)
                    or not isinstance(recipient, str) or province_id in returned_ids):
                raise PlayerActionError("Invalid territory return.")
            province = self._province(province_id)
            recipient_data = self.world.nation_data.get(recipient)
            if province.get("owner") != country_id or not isinstance(recipient_data, dict):
                raise PlayerActionError("Invalid territory return.")
            if recipient not in province.get("cores", []) and province_id not in recipient_data.get("claims", []):
                raise PlayerActionError("The recipient has no claim on that territory.")
            old = existing_returns.get(province_id)
            # Recipient is an authoritative choice too.  A pending return may
            # be kept or cancelled, but cannot be redirected from a stale map.
            if old and old.get("recipient") != recipient:
                raise PlayerActionError("Cancel a territory return before changing its recipient.")
            returns.append({"prov_id": province_id, "recipient": recipient,
                            "turns_left": max(0, int(old.get("turns_left", 1))) if old else 1})
            returned_ids.add(province_id)
        return {"queue": queue, "revokes": revokes,
                "returns": returns}

    def _collect_country_appearance(self, country_id):
        country_data = self.world.nation_data.get(country_id, {})
        # Older partial country records can omit appearance entirely.
        if "color" in country_data:
            return {"appearance": queries.country_appearance_draft(country_data)}

    def _apply_country_appearance(self, country_id, command):
        self._apply_appearance(country_id, command["appearance"])

    def _apply_appearance(self, country_id, appearance):
        queries.apply_country_appearance(self.world.nation_data, country_id, appearance)
        self.context.nation_colors[country_id] = tuple(self.world.nation_data[country_id]["color"])

    def _validate_country_appearance(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Allow identity changes without allowing a client to alter gameplay data."""
        self._country(country_id)
        return {"appearance": self._canonical_appearance(command.get("appearance"))}

    def _canonical_appearance(self, appearance: Any) -> dict[str, Any]:
        """Use the same narrow identity schema for a player and their subject."""
        if not isinstance(appearance, dict) or set(appearance) - self._APPEARANCE_KEYS:
            raise PlayerActionError("Invalid country appearance.")
        canonical = {}
        for key in ("name", "adjective", "leader_name", "leader_title"):
            value = appearance.get(key, "")
            if not isinstance(value, str) or len(value) > 120 or any(ord(ch) < 32 for ch in value):
                raise PlayerActionError("Invalid country appearance text.")
            canonical[key] = value
        for key in ("flag_data", "portrait_data"):
            value = appearance.get(key, "DEFAULT")
            if not isinstance(value, str) or len(value) > 4_000_000:
                raise PlayerActionError("Invalid country appearance image.")
            canonical[key] = value
        color = appearance.get("color")
        if (not isinstance(color, list) or len(color) not in (3, 4)
                or any(not isinstance(channel, int) or not 0 <= channel <= 255 for channel in color)):
            raise PlayerActionError("Invalid country color.")
        canonical["color"] = list(color)
        return canonical

    def _collect_puppet_draft(self, country_id):
        country_data = self.world.nation_data.get(country_id, {})
        controlled = country_data.get("puppets", []) if isinstance(country_data, dict) else []
        siphons = {}
        for puppet in controlled:
            subject = self.world.nation_data.get(puppet, {})
            if isinstance(subject, dict) and subject.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED:
                siphons[puppet] = copy.deepcopy(subject.get("siphon_rates", {}))
        return {"puppet_order": list(controlled), "siphons": siphons,
                "release_subjects": [{"core_nation": entry.get("core_nation"),
                                      "keep_cores": bool(entry.get("keep_cores", False)),
                                      "release_type": entry["release_type"]}
                                     for entry in country_data.get("release_puppet_queue", [])
                                     if isinstance(entry, dict)],
                "appearances": copy.deepcopy(self.session.pending_subject_appearances)}

    def _apply_puppet_draft(self, country_id, command):
        country_data = self.world.nation_data[country_id]
        country_data["puppets"] = list(command["puppet_order"])
        country_data["release_puppet_queue"] = copy.deepcopy(command["release_subjects"])
        for puppet, rates in command["siphons"].items():
            self.world.nation_data[puppet]["siphon_rates"] = copy.deepcopy(rates)
        for puppet, appearance in command["appearances"].items():
            self._apply_appearance(puppet, appearance)
            if self._is_local_tournament_player(country_id):
                self.session.pending_subject_appearances[puppet] = copy.deepcopy(appearance)

    def _validate_puppet_draft(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Validate the controller-only subject controls from the Puppets UI."""
        country = self._country(country_id)
        puppet_order = command.get("puppet_order", [])
        siphons = command.get("siphons", {})
        releases = command.get("release_subjects", [])
        appearances = command.get("appearances", {})
        controlled = list(country.get("puppets", []))
        if not isinstance(puppet_order, list) or sorted(puppet_order) != sorted(controlled):
            raise PlayerActionError("Invalid puppet order.")
        if not all(isinstance(value, dict) for value in (siphons, appearances)):
            raise PlayerActionError("Invalid puppet settings.")
        if not isinstance(releases, list) or len(releases) > self._MAX_CLAIM_DRAFTS:
            raise PlayerActionError("Invalid nation creation queue.")
        canonical_siphons = {}
        for puppet, values in siphons.items():
            puppet_data = self.world.nation_data.get(puppet)
            if (puppet not in controlled or not isinstance(puppet_data, dict)
                    or puppet_data.get("puppet_type") != c.PUPPET_TYPE_INTEGRATED
                    or not isinstance(values, dict)):
                raise PlayerActionError("You may only change your integrated subjects.")
            rates = {}
            for resource in ("manpower", "materials", "fuel"):
                value = values.get(resource, 0)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= c.MAX_PUPPET_SIPHON:
                    raise PlayerActionError("Invalid puppet siphon rate.")
                rates[resource] = value
            canonical_siphons[puppet] = rates
        canonical_appearances = {}
        for puppet, appearance in appearances.items():
            puppet_data = self.world.nation_data.get(puppet)
            if (puppet not in controlled or not isinstance(puppet_data, dict)
                    or puppet_data.get("puppet_type") != c.PUPPET_TYPE_INTEGRATED):
                raise PlayerActionError("You may only edit an integrated subject.")
            canonical_appearances[puppet] = self._canonical_appearance(appearance)
        try:
            canonical_releases = canonical_puppet_release_queue(
                self.world.map_data, self.world.nation_data, country_id, releases,
                country.get("release_puppet_queue", []))
        except ValueError as error:
            raise PlayerActionError(str(error)) from error
        return {"puppet_order": list(puppet_order),
                "siphons": canonical_siphons, "release_subjects": canonical_releases,
                "appearances": canonical_appearances}

    def _collect_faction_rename(self, _country_id):
        # Only a player edit may request a rename. A copy of the old faction
        # name would reject a member's draft if the leader imported first.
        return {"name": self.session.pending_faction_rename}

    def _apply_faction_rename(self, country_id, command):
        name = command.get("name")
        if name:
            if self._is_local_tournament_player(country_id):
                rename_player_faction(self.context, name)
            else:
                current = queries.get_country_faction(country_id, self.world.nation_data)
                faction_actions.rename_faction(self.world.nation_data, country_id, current, name)

    def _validate_faction_rename(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        self._country(country_id)
        name = command.get("name")
        if name is None:
            return {"name": None}
        if not isinstance(name, str) or len(name.strip()) > 40:
            raise PlayerActionError("Invalid faction name.")
        old_name = queries.get_country_faction(country_id, self.world.nation_data)
        if name.strip() == old_name:
            return {"name": None}
        if not queries.is_faction_leader(country_id, self.world.nation_data) or not old_name:
            raise PlayerActionError("Only a faction leader may rename their faction.")
        # Validate against a copy: the helper owns the collision and membership
        # rules, while the real mutation waits for atomic turn processing.
        probe = copy.deepcopy(self.world.nation_data)
        if not faction_actions.rename_faction(probe, country_id, old_name, name.strip()):
            raise PlayerActionError("That faction name is unavailable.")
        return {"name": name.strip()}

    def _collect_ratification_response(self, country_id):
        country_data = self.world.nation_data.get(country_id, {})
        pending_ratification = country_data.get("pending_ratification", {})
        return {"verdict": pending_ratification.get("verdict") if isinstance(pending_ratification, dict) else None,
                "treaty_id": pending_ratification.get("treaty_id") if isinstance(pending_ratification, dict) else None}

    def _apply_ratification_response(self, country_id, command):
        country_data = self.world.nation_data[country_id]
        pending = country_data.get("pending_ratification")
        if isinstance(pending, dict):
            lifecycle.answer_ratification(self.world.nation_data, country_id, command["verdict"],
                                          treaty_id=command.get("treaty_id"))

    def _validate_ratification_response(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        verdict = command.get("verdict")
        pending = self._country(country_id).get("pending_ratification")
        if verdict is not None and verdict not in ("RATIFY", "REFUSE"):
            raise PlayerActionError("Invalid treaty ratification response.")
        if verdict is not None and not isinstance(pending, dict):
            raise PlayerActionError("There is no treaty awaiting ratification.")
        reference = command.get("treaty_id")
        if reference is not None and (not isinstance(pending, dict) or reference != pending.get("treaty_id")):
            raise PlayerActionError("That ratification refers to an expired treaty.")
        return {"verdict": verdict, "treaty_id": reference}

    def _collect_peace_choices(self, country_id):
        rounds = self._country(country_id).get("peace_choices", {})
        selections = {opponent: {"round_id": round_["round_id"], "proposer": round_["selected"]}
                      for opponent, round_ in rounds.items() if round_.get("selected")}
        return {"selections": selections} if selections else None

    def _validate_peace_choices(self, country_id, command):
        selections = command.get("selections")
        if not isinstance(selections, dict) or len(selections) > len(self._country(country_id).get("peace_choices", {})):
            raise PlayerActionError("Invalid peace treaty choices.")
        result = {}
        for opponent, selection in selections.items():
            if not isinstance(opponent, str) or not isinstance(selection, dict):
                raise PlayerActionError("Invalid peace treaty choice.")
            round_ = peace_scope.pending_choice(self.world.nation_data, country_id, opponent)
            round_id, proposer = selection.get("round_id"), selection.get("proposer")
            if not round_ or round_id != round_["round_id"]:
                raise PlayerActionError("That peace treaty choice has expired.")
            if not isinstance(proposer, str) or proposer not in round_["offers"]:
                raise PlayerActionError("That peace treaty is unavailable.")
            result[opponent] = {"round_id": round_id, "proposer": proposer}
        return {"selections": result}

    def _apply_peace_choices(self, country_id, command):
        for opponent, selection in command["selections"].items():
            peace_scope.choose_offer(self.world.nation_data, country_id, opponent, selection["round_id"], selection["proposer"])

    def _apply_volunteer_draft(self, country_id, command):
        country_data = self.world.nation_data[country_id]
        pending = country_data.get("pending_diplomacy", {}).get(command["target"], {})
        if not isinstance(pending, dict) or pending.get("action") != "SEND_VOLUNTEERS":
            return
        chosen = [self._unit_for_reference(ref) for ref in command["units"]]
        _details, error = volunteers.create_offer(self.context, country_id, command["target"], chosen)
        if error:
            raise PlayerActionError(error)

    def _validate_volunteer_draft(self, country_id: str, command: dict[str, Any], *, context=None) -> dict[str, Any]:
        """Identify divisions by their authoritative province/index, never data."""
        target, units = command.get("target"), command.get("units", [])
        if (not isinstance(target, str) or target == country_id or target not in self.world.nation_data
                or not isinstance(units, list) or not units or len(units) > 100):
            raise PlayerActionError("Invalid volunteer offer.")
        legal, reason = volunteers.is_eligible(country_id, target, self.world.nation_data)
        if not legal:
            raise PlayerActionError(reason)
        canonical, seen = [], set()
        for ref in units:
            if not isinstance(ref, dict):
                raise PlayerActionError("Invalid volunteer division.")
            view = self.context if context is None else context
            province = queries.province_for_order(view, ref.get("province_id"))
            index = ref.get("unit_index")
            if "unit_id" in ref:
                if not isinstance(ref["unit_id"], str):
                    raise PlayerActionError("Invalid volunteer identity.")
                index = next((index for index, unit in enumerate(province.get("units", []))
                              if unit.get("unit_id") == ref["unit_id"]), None)
            if type(index) is not int or not 0 <= index < len(province.get("units", [])):
                raise PlayerActionError("Unknown volunteer division.")
            unit = province["units"][index]
            key = (province["id"], index)
            if (key in seen or unit.get("owner") != country_id or unit.get("volunteer_host")
                    or not volunteers._is_land(unit, view) or queries.unit_is_air_drop_recovering(unit)):
                raise PlayerActionError("That division cannot volunteer.")
            entry = {"province_id": province["id"], "unit_index": index}
            if unit.get("unit_id"):
                entry["unit_id"] = unit["unit_id"]
            canonical.append(entry)
            seen.add(key)
        return {"type": "volunteer_draft", "target": target, "units": canonical}

    def _collect_country_diplomacy(self, country_id):
        # A proposal in transit belongs to the host. Only a queued forward can
        # add an intent to a travelling proposal.
        country_data = self.world.nation_data.get(country_id, {})
        pending = country_data.get("pending_diplomacy", {})
        if not isinstance(pending, dict):
            pending = {}
        responses = country_data.get("diplo_responses", {})
        if not isinstance(responses, dict):
            responses = {}
        draft_lists = country_data.get("draft_lists", {})
        if not isinstance(draft_lists, dict):
            draft_lists = {}
        return {"pending": {target: (copy.deepcopy(info) if info.get("turns", 0) <= 0
                                      else diplomacy_messages.forward_intent(info)) for target, info in pending.items()
                            if isinstance(target, str) and isinstance(info, dict)
                            and (info.get("turns", 0) <= 0 or diplomacy_messages.has_queued_forward(info))},
                "responses": copy.deepcopy(responses),
                "draft_lists": copy.deepcopy(draft_lists)}

    def _apply_country_diplomacy(self, country_id, command):
        lifecycle.apply_draft(self.world.nation_data, country_id,
                              command["pending"], command["responses"], command["draft_lists"])

    def _validate_country_diplomacy(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Validate only this country's unprocessed diplomatic draft.

        Diplomacy is deliberately a command rather than copied client map data.
        In-flight proposals remain on the authoritative map; clients can only
        replace their own unsent proposals and responses for the current turn.
        """

        self._country(country_id)
        pending = command.get("pending", {})
        responses = command.get("responses", {})
        draft_lists = command.get("draft_lists", {})
        if not all(isinstance(value, dict) for value in (pending, responses, draft_lists)):
            raise PlayerActionError("Invalid diplomacy draft.")
        if any(len(value) > 100 for value in (pending, responses, draft_lists)):
            raise PlayerActionError("Too many diplomatic actions in one turn.")
        allowed_actions = set(UNILATERAL_ACTIONS) | set(BILATERAL_ACTIONS)

        def target_ok(target: Any, action=None) -> str:
            if (not isinstance(target, str) or (target == country_id and action not in c.SELF_TARGETED_ACTIONS) or
                    target not in self.world.nation_data):
                raise PlayerActionError("Invalid diplomacy target.")
            return target

        def text(value: Any, label: str, limit: int = 4000) -> str:
            if (not isinstance(value, str) or len(value) > limit or
                    any(ord(character) < 32 and character not in "\n\t" for character in value)):
                raise PlayerActionError(f"Invalid diplomacy {label}.")
            return value

        canonical_pending = {}
        for target, info in pending.items():
            if not isinstance(info, dict):
                raise PlayerActionError("Invalid diplomatic action.")
            action = info.get("action")
            target_ok(target, action)
            if not isinstance(action, str) or len(action) > 4500:
                raise PlayerActionError("Invalid diplomatic action.")
            if action.startswith("MSG:"):
                text(action[4:], "message")
            elif action not in allowed_actions:
                raise PlayerActionError("Unknown diplomatic action.")
            leadership_error = queries.faction_request_leadership_error(
                country_id, target, action, self.world.nation_data)
            if leadership_error:
                raise PlayerActionError(leadership_error)
            timer = info.get("timer", 0)
            if not isinstance(timer, int) or isinstance(timer, bool) or not -1 <= timer <= 1000:
                raise PlayerActionError("Invalid diplomacy timer.")
            entry = {"action": action, "turns": 0,
                     "timer": timer,
                     "message": text(info.get("message", ""), "message")}
            if "parameters" in info:
                try:
                    encoded = json.dumps(info["parameters"], separators=(",", ":"))
                except (TypeError, ValueError) as exc:
                    raise PlayerActionError("Invalid diplomacy terms.") from exc
                if len(encoded) > 50_000:
                    raise PlayerActionError("Diplomacy terms are too large.")
                entry["parameters"] = copy.deepcopy(info["parameters"])
            if action == diplomacy_messages.FORWARD_ACTION:
                try:
                    entry.update(diplomacy_messages.canonical_forward_fields(self.world.nation_data, country_id, info))
                except ValueError as error:
                    raise PlayerActionError(str(error)) from error
                original = diplomacy_messages.get_pending(self.world.nation_data, country_id, target)
                if original.get("turns", 0) > 0 and original.get("action", "").startswith("MSG:"):
                    if info.get("request_id") != original["request_id"]:
                        raise PlayerActionError("That forward refers to an expired message. Reload the current turn.")
                    entry["request_id"] = original["request_id"]
            canonical_pending[target] = entry

        canonical_responses = {}
        for target, info in responses.items():
            target_ok(target)
            if not isinstance(info, dict):
                raise PlayerActionError("Invalid diplomatic response.")
            verdict, action = info.get("verdict"), info.get("action")
            if verdict not in ("ACCEPT", "REJECT") or action not in BILATERAL_ACTIONS:
                raise PlayerActionError("Invalid diplomatic response.")
            entry = {"verdict": verdict, "action": action,
                     "message": text(info.get("message", ""), "response message")}
            if "parameters" in info:
                try:
                    encoded = json.dumps(info["parameters"], separators=(",", ":"))
                except (TypeError, ValueError) as exc:
                    raise PlayerActionError("Invalid diplomacy terms.") from exc
                if len(encoded) > 50_000:
                    raise PlayerActionError("Diplomacy terms are too large.")
                entry["parameters"] = copy.deepcopy(info["parameters"])
            try:
                entry.update(lifecycle.canonical_response_reference(
                    self.world.nation_data, country_id, target, info))
            except ValueError as error:
                raise PlayerActionError(str(error)) from error
            canonical_responses[target] = entry

        # A counteroffer relies on the decline in this same draft, even when a
        # previous synchronization had a different answer or no answer yet.
        for target, entry in canonical_pending.items():
            available = availability(self.context, country_id, target, entry["action"], responses=canonical_responses)
            if not available.allowed:
                raise PlayerActionError(available.reason)

        canonical_lists = {}
        for target, messages in draft_lists.items():
            target_ok(target)
            if (not isinstance(messages, list) or len(messages) > 20 or
                    any(not isinstance(message, str) or len(message) > 4000 or
                        any(ord(character) < 32 and character not in "\n\t" for character in message)
                        for message in messages)):
                raise PlayerActionError("Invalid diplomatic message draft.")
            canonical_lists[target] = list(messages)
        return {"pending": canonical_pending,
                "responses": canonical_responses, "draft_lists": canonical_lists}

    def _province(self, province_id: Any):
        try:
            return self.world.id_to_province[int(province_id)]
        except (KeyError, TypeError, ValueError) as exc:
            raise PlayerActionError("Unknown province in order.") from exc

    def _unit_for_reference(self, ref):
        province = self._province(ref["province_id"])
        unit = (next(unit for unit in province["units"] if unit.get("unit_id") == ref["unit_id"])
                if ref.get("unit_id") else province["units"][ref["unit_index"]])
        return province, unit

    def _apply_unit_order(self, country_id, command):
        province, unit = self._unit_for_reference(command)
        apply_action(self.context, country_id, province, unit,
                     command["order"], authority="server", payment_settled=True)
        for key in ("custom_name", "combat_stance", "lane_target"):
            value = command.get(key)
            if value is None:
                unit.pop(key, None)
            else:
                unit[key] = value

    def _validate_unit_order(self, country_id: str, command: dict[str, Any], *, context=None) -> dict[str, Any]:
        context = self.context if context is None else context
        try:
            province = queries.province_for_order(context, command.get("province_id"))
        except ValueError as exc:
            raise PlayerActionError(str(exc)) from exc
        index = command.get("unit_index")
        unit_id = command.get("unit_id")
        if unit_id is not None:
            if not isinstance(unit_id, str):
                raise PlayerActionError("Invalid unit identity.")
            index = next((i for i, unit in enumerate(province.get("units", []))
                          if unit.get("unit_id") == unit_id), None)
        if type(index) is not int or not 0 <= index < len(province.get("units", [])):
            raise PlayerActionError("Unknown unit in order.")
        unit = province["units"][index]
        if unit.get("owner") != country_id:
            raise PlayerActionError("Players may only order their own units.")
        try:
            queries.validate_air_drop_recovery_draft(unit, {
                key: command.get(key) for key in ("order", "custom_name", "combat_stance", "lane_target")})
        except ValueError as exc:
            raise PlayerActionError(str(exc)) from exc
        order = command.get("order")
        if order is not None and not isinstance(order, dict):
            raise PlayerActionError("Invalid unit order.")
        try:
            prepared = unit_actions.prepare_action(context, country_id, province, unit, order)
        except ValueError as error:
            raise PlayerActionError(str(error)) from error
        canonical_order = copy.deepcopy(prepared.order)
        if isinstance(canonical_order, dict) and canonical_order.get("type") == "REPAIR":
            canonical_order["realtime_cost"] = prepared.cost
        custom_name = command.get("custom_name")
        if custom_name is not None and (not isinstance(custom_name, str) or len(custom_name.strip()) > 120
                                        or any(ord(character) < 32 for character in custom_name)):
            raise PlayerActionError("Invalid unit name.")
        stance = command.get("combat_stance")
        lane_target = command.get("lane_target")
        try:
            unit_actions.validate_battle_choices(context, unit, stance, lane_target)
        except ValueError as error:
            raise PlayerActionError(str(error)) from error
        return {"type": "unit_order", "province_id": province["id"],
                "unit_index": index, "unit_id": unit.get("unit_id"), "order": canonical_order,
                "unit_refund": prepared.refund,
                "custom_name": custom_name.strip() if isinstance(custom_name, str) and custom_name.strip() else None,
                "combat_stance": stance, "lane_target": lane_target}

    def _apply_province_queue(self, country_id, command):
        apply_queue_change(self.context, country_id, command, payment_settled=True)

    def _validate_queue(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        province = self._province(command.get("province_id"))
        if province.get("owner") != country_id:
            raise PlayerActionError("Players may only change queues in their own provinces.")
        queue_type = command.get("queue")
        items = command.get("items")
        if queue_type not in ("building_queue", "unit_queue") or not isinstance(items, list):
            raise PlayerActionError("Invalid province queue.")
        if len(items) > self._MAX_QUEUE_ITEMS or any(not isinstance(item, dict) for item in items):
            raise PlayerActionError("Invalid province queue contents.")
        try:
            return production_actions.reconstruct_queue(self.context, country_id, province, queue_type, items)
        except ValueError as error:
            raise PlayerActionError(str(error)) from error

    def _build_queue_item(self, country_id: str, province: dict[str, Any], queue_type: str,
                          intent: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Reconstruct untrusted client intent through shared production rules."""
        try:
            result = production_actions.prepare_production(self.context, country_id, province, queue_type, intent)
        except ValueError as error:
            raise PlayerActionError(str(error)) from error
        return result.order, result.cost

    def _validate_queue_budget(self, country_id: str, commands: list[dict[str, Any]]) -> None:
        """Ensure queue changes can be paid for before accepting a draft."""
        try:
            validate_queue_budget(self._country(country_id), commands)
        except ValueError as error:
            raise PlayerActionError(str(error)) from error

    def _collect_research_queue(self, country_id):
        # An empty selection means the player paused all ongoing projects.
        country_data = self.world.nation_data.get(country_id, {})
        research_queue = country_data.get("research_queue", []) if isinstance(country_data, dict) else []
        tech_names = [project.get("tech_name") for project in research_queue
                      if isinstance(project, dict) and isinstance(project.get("tech_name"), str)]
        return {"tech_names": tech_names}

    def _apply_research_queue(self, country_id, command):
        country_data = self.world.nation_data[country_id]
        apply_research_selection(country_data, command)

    def _validate_research_queue(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Replay a player's start/pause choices without trusting client points.

        Clients submit only the desired ordered tech names. Progress always
        comes from the authoritative map: pausing stores that server progress,
        and resuming restores it. A forged client therefore cannot finish a
        technology by claiming a smaller point cost.
        """

        try:
            result = queries.canonical_research_selection(self.world.nation_data.get(country_id),
                                                          command.get("tech_names"),
                                                          queries.get_tech_tree(self.context), context=self.context)
        except ValueError as error:
            raise PlayerActionError(str(error)) from error
        return result

    def apply_drafts(self, drafts: dict[str, list[dict[str, Any]]]) -> None:
        # Validate every complete submission before any country's state changes.
        drafts = {country: self.validate_draft(country, commands) for country, commands in drafts.items()}
        self.apply_validated_drafts(drafts)

    def apply_validated_drafts(self, drafts):
        """Apply host-validated domain data in its established processing order."""
        # Recompute payment from live state before any country's stockpiles change.
        drafts = {country: self._refresh_payments(country, commands)
                  for country, commands in drafts.items()}
        for country_id, commands in drafts.items():
            if any(command["type"] == "country_diplomacy" for command in commands):
                volunteers.release_draft_reservations(self.context, country_id)
            country_data = self.world.nation_data[country_id]
            settle_draft_budget(country_data, commands)
            queries.apply_air_transport_commands(self.context, country_id,
                [command for command in commands if command["type"] == "air_transport"])
            for command in commands:
                kind = command["type"]
                if kind == "unit_order":
                    self._apply_unit_order(country_id, command)
                elif kind == "province_queue":
                    self._apply_province_queue(country_id, command)
                elif kind in _COUNTRY_COMMANDS:
                    _COUNTRY_COMMANDS[kind].apply(self, country_id, command)
            # Volunteer reservations must be created after their diplomatic
            # request has been placed on the server map, just like the normal
            # player UI does in an offline game.
            for command in commands:
                if command["type"] != "volunteer_draft":
                    continue
                self._apply_volunteer_draft(country_id, command)

    def _refresh_payments(self, country_id, commands):
        planning_view = self._planning_view(country_id, commands)
        transport = [command for command in commands if command["type"] == "air_transport"]
        view = queries.air_transport_draft(planning_view, country_id, transport)[0] if transport else planning_view
        refreshed = []
        for command in commands:
            if command["type"] == "unit_order":
                command = self._validate_unit_order(country_id, command, context=view)
            elif command["type"] == "province_queue":
                command = self._validate_queue(country_id, command)
            refreshed.append(command)
        self._validate_queue_budget(country_id, refreshed)
        # Apply orders against the same policy state used to check range and prices.
        # The turn then resolves any policy cancellations before executing orders.
        refreshed.sort(key=lambda command: command["type"] == "country_preferences")
        return refreshed


@dataclass(frozen=True)
class _CountryCommand:
    collect: Callable
    validate: Callable
    apply: Callable
    uses_transport_view: bool = False


# One complete draft per country domain. Keep collection order stable for exports
# and fingerprints. Unit, production, transport, and volunteer orders have their
# own per-target or per-province ordering and validation.
_COUNTRY_COMMANDS = {
    "army_roster": _CountryCommand(PlayerActions._collect_army_roster, PlayerActions._validate_army_roster, PlayerActions._apply_army_roster, uses_transport_view=True),
    "research_queue": _CountryCommand(PlayerActions._collect_research_queue, PlayerActions._validate_research_queue, PlayerActions._apply_research_queue),
    "country_preferences": _CountryCommand(PlayerActions._collect_country_preferences, PlayerActions._validate_country_preferences, PlayerActions._apply_country_preferences),
    "claim_draft": _CountryCommand(PlayerActions._collect_claim_draft, PlayerActions._validate_claim_draft, PlayerActions._apply_claim_draft),
    "country_appearance": _CountryCommand(PlayerActions._collect_country_appearance, PlayerActions._validate_country_appearance, PlayerActions._apply_country_appearance),
    "country_diplomacy": _CountryCommand(PlayerActions._collect_country_diplomacy, PlayerActions._validate_country_diplomacy, PlayerActions._apply_country_diplomacy),
    "puppet_draft": _CountryCommand(PlayerActions._collect_puppet_draft, PlayerActions._validate_puppet_draft, PlayerActions._apply_puppet_draft),
    "faction_rename": _CountryCommand(PlayerActions._collect_faction_rename, PlayerActions._validate_faction_rename, PlayerActions._apply_faction_rename),
    "ratification_response": _CountryCommand(PlayerActions._collect_ratification_response, PlayerActions._validate_ratification_response, PlayerActions._apply_ratification_response),
    "peace_choices": _CountryCommand(PlayerActions._collect_peace_choices, PlayerActions._validate_peace_choices, PlayerActions._apply_peace_choices),
}


def rename_player_faction(context, new_name):
    """Rename on the planning map and record the player's requested name."""
    world = world_for(context)
    session = session_for(context)
    country = session.player_country
    current = queries.get_country_faction(country, world.nation_data)
    renamed = faction_actions.rename_faction(world.nation_data, country, current, new_name)
    if renamed and session.is_networked:
        session.pending_faction_rename = queries.get_country_faction(country, world.nation_data)
    return renamed


def collect_map_commands(context, country_id: str) -> list[dict[str, Any]]:
    """Serialize supported local order controls into server commands.

    This deliberately reads only player choices, never mutable combat,
    resource, research-progress, or claim-timer fields from the client map.
    """
    held_offers = volunteers.unsent_offers(context, country_id)
    volunteer_choices = {target: [{"province_id": entry["origin_id"],
                                  "unit_id": entry["unit"].get("unit_id")}
                                 for entry in mission.get("held_units", [])]
                         for target, mission in held_offers.items()}
    context = volunteers.draft_context(context, country_id)
    world_state = world_for(context)
    queries.ensure_unit_ids(world_state.map_data)
    commands: list[dict[str, Any]] = queries.air_transport_commands(context, country_id)
    for province in world_state.map_data.values():
        for index, unit in enumerate(province.get("units", [])):
            if unit.get("owner") == country_id:
                commands.append({"type": "unit_order", "province_id": province["id"],
                                 "unit_index": index, "unit_id": unit.get("unit_id"),
                                 "order": copy.deepcopy(unit.get("order")),
                                 "custom_name": unit.get("custom_name"),
                                 "combat_stance": unit.get("combat_stance"),
                                 "lane_target": unit.get("lane_target")})
        if province.get("owner") == country_id:
            for queue_name in ("building_queue", "unit_queue"):
                # Empty queues are meaningful: they are how a player cancels
                # already-paid work on the authoritative server.
                commands.append({"type": "province_queue", "province_id": province["id"],
                                 "queue": queue_name,
                                 "items": copy.deepcopy(province.get(queue_name, []))})
    queries.normalize_armies(world_state.nation_data, world_state.map_data)
    service = PlayerActions(context)
    for kind, definition in _COUNTRY_COMMANDS.items():
        command = definition.collect(service, country_id)
        if command is not None:
            commands.append({"type": kind, **command})
    volunteer_drafts = context.session.realtime_volunteer_drafts
    if isinstance(volunteer_drafts, dict):
        volunteer_choices.update(volunteer_drafts)
    for target, units in volunteer_choices.items():
        commands.append({"type": "volunteer_draft", "target": target, "units": copy.deepcopy(units)})
    return commands
