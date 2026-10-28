"""Validate and apply player choices independently of network transports."""

from __future__ import annotations

import copy
import json
from typing import Any

import data.constants as c
from data.state_access import world_for, session_for
from map_logic import politics


class PlayerActionError(ValueError):
    """A player choice cannot be applied to the current world."""


class PlayerActions:
    """Own domain validation and application for complete player drafts."""
    _UNIT_MUTABLE_KEYS = {"order", "custom_name", "combat_stance", "lane_target"}
    _AUTOMATION_KEYS = {"construction", "movement", "research"}
    _APPEARANCE_KEYS = set(c.COUNTRY_APPEARANCE_FIELDS)
    _MAX_CLAIM_DRAFTS = 100
    _MAX_QUEUE_ITEMS = 100

    def __init__(self, map_ref, session=None):
        from data.game_state import WorldState
        from data.state_access import BackendState
        self.map_ref = BackendState(map_ref, session) if isinstance(map_ref, WorldState) else map_ref
        self.world = world_for(self.map_ref)
        self.session = session_for(self.map_ref)

    def validate_draft(self, country_id: str, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from data import queries
        if not isinstance(commands, list):
            raise PlayerActionError("Player intents must be a list.")
        self._country(country_id)
        from map_logic.diplomacy import volunteers
        planning_view = self._planning_view(country_id, commands)
        transport_commands = [command for command in commands
                              if isinstance(command, dict) and command.get("type") == "air_transport"]
        try:
            transport_view, canonical = (queries.air_transport_draft(planning_view, country_id, transport_commands)
                                         if transport_commands else (planning_view, []))
        except ValueError as exc:
            raise PlayerActionError(str(exc)) from exc
        has_research_command = False
        seen = set()
        seen_units = set()
        seen_queues = set()
        for command in commands:
            if not isinstance(command, dict):
                raise PlayerActionError("Invalid order command.")
            kind = command.get("type")
            if not isinstance(kind, str):
                raise PlayerActionError("Invalid command type.")
            # A draft is a complete projection of each mutable domain.  One
            # command per domain prevents a client from smuggling a later
            # conflicting value through the same update.
            if kind in seen and kind in {"research_queue", "country_preferences", "claim_draft",
                                        "country_appearance", "country_diplomacy", "puppet_draft",
                                        "faction_rename", "ratification_response", "army_roster"}:
                raise PlayerActionError("Only one command is allowed for that game action.")
            if kind == "unit_order":
                validated = self._validate_unit_order(country_id, command, map_ref=transport_view)
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
            elif kind == "research_queue":
                if has_research_command:
                    raise PlayerActionError("Only one research selection may be submitted per turn.")
                canonical.append(self._validate_research_queue(country_id, command))
                has_research_command = True
            elif kind == "country_preferences":
                canonical.append(self._validate_country_preferences(country_id, command))
            elif kind == "claim_draft":
                canonical.append(self._validate_claim_draft(country_id, command))
            elif kind == "country_appearance":
                canonical.append(self._validate_country_appearance(country_id, command))
            elif kind == "country_diplomacy":
                canonical.append(self._validate_country_diplomacy(country_id, command))
            elif kind == "puppet_draft":
                canonical.append(self._validate_puppet_draft(country_id, command))
            elif kind == "faction_rename":
                canonical.append(self._validate_faction_rename(country_id, command))
            elif kind == "ratification_response":
                canonical.append(self._validate_ratification_response(country_id, command))
            elif kind == "army_roster":
                canonical.append(self._validate_army_roster(country_id, command, map_ref=transport_view))
            elif kind == "volunteer_draft":
                canonical.append(self._validate_volunteer_draft(country_id, command, map_ref=transport_view))
            else:
                raise PlayerActionError("That order type is not supported by the server.")
            seen.add(kind)
        self._validate_queue_budget(country_id, canonical)
        self._validate_volunteer_commands(country_id, canonical, map_ref=planning_view)
        return canonical

    def _validate_army_roster(self, country_id: str, command: dict[str, Any], *, map_ref=None) -> dict[str, Any]:
        """Validate organization metadata without trusting client unit ownership."""
        from data import queries
        supplied = command.get("armies", [])
        if not isinstance(supplied, list) or len(supplied) > 200:
            raise PlayerActionError("Invalid army roster.")
        world = self.world if map_ref is None else world_for(map_ref)
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
        return {"type": "army_roster", "armies": armies}

    def _validate_volunteer_commands(self, country_id: str, commands: list[dict[str, Any]], *, map_ref=None) -> None:
        """Keep a volunteer request and its reserved divisions inseparable."""
        from map_logic.diplomacy import volunteers
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
            view = volunteers.draft_context(self.map_ref if map_ref is None else map_ref, country_id,
                                            always_copy=True)
            if offered_count > volunteers.remaining_capacity(view, country_id):
                raise PlayerActionError("The selected volunteer divisions exceed your available capacity.")

    def _country(self, country_id: str) -> dict[str, Any]:
        country = self.world.nation_data.get(country_id)
        if not isinstance(country, dict):
            raise PlayerActionError("Unknown player country.")
        return country

    def _planning_view(self, country_id, commands):
        from map_logic.diplomacy import volunteers
        if any(isinstance(command, dict) and command.get("type") == "country_diplomacy" for command in commands):
            return volunteers.draft_context(self.map_ref, country_id)
        return self.map_ref

    def _validate_country_preferences(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Validate politics, automation, economy, and custom unit choices."""
        from data import queries

        country = self._country(country_id)
        drift = command.get("political_drift", 0)
        automation = command.get("automation", {})
        if not isinstance(drift, int) or drift not in (-1, 0, 1):
            raise PlayerActionError("Invalid political direction.")
        if not isinstance(automation, dict) or set(automation) - self._AUTOMATION_KEYS:
            raise PlayerActionError("Invalid automation settings.")
        if any(not isinstance(value, bool) for value in automation.values()):
            raise PlayerActionError("Invalid automation settings.")
        conscription = command.get("conscription_slider", 1.0)
        fuel_conversion = command.get("mat_to_fuel_slider", 0.0)
        if (isinstance(conscription, bool) or not isinstance(conscription, (int, float))
                or not 0.0 <= float(conscription) <= 1.0):
            raise PlayerActionError("Invalid manpower conversion setting.")
        max_conversion = max(0.0, float(queries.get_max_fuel_conversion(country)))
        if (isinstance(fuel_conversion, bool) or not isinstance(fuel_conversion, (int, float))
                or not 0.0 <= float(fuel_conversion) <= max_conversion):
            raise PlayerActionError("Invalid material-to-fuel conversion setting.")
        custom_units = command.get("custom_production_units", [])
        if (not isinstance(custom_units, list) or len(custom_units) > 100
                or any(not isinstance(name, str) for name in custom_units)
                or len(set(custom_units)) != len(custom_units)):
            raise PlayerActionError("Invalid custom production selection.")
        unit_library = queries.get_unit_library(self.map_ref)
        research = country.get("research", {})
        if any(name not in unit_library or not queries.is_unit_unlocked(name, research, context=self.map_ref)
               for name in custom_units):
            raise PlayerActionError("A selected custom unit is not researched.")
        try:
            policies = politics.canonicalize_policy_draft(
                self.world.nation_data, country_id, command.get(politics.POLICY_KEY, {}))
        except ValueError as exc:
            raise PlayerActionError(str(exc)) from exc
        return {"type": "country_preferences", "political_drift": drift,
                "automation": {key: bool(automation.get(key, False))
                               for key in self._AUTOMATION_KEYS},
                "conscription_slider": float(conscription),
                "mat_to_fuel_slider": float(fuel_conversion),
                "custom_production_units": list(custom_units),
                politics.POLICY_KEY: policies}

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
        return {"type": "claim_draft", "queue": queue, "revokes": revokes,
                "returns": returns}

    def _validate_country_appearance(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Allow identity changes without allowing a client to alter gameplay data."""
        self._country(country_id)
        return {"type": "country_appearance", "appearance": self._canonical_appearance(command.get("appearance"))}

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
            raise PlayerActionError("Invalid puppet release queue.")
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
        from map_logic.diplomacy.puppet_actions import canonical_puppet_release_queue
        try:
            canonical_releases = canonical_puppet_release_queue(
                self.world.map_data, self.world.nation_data, country_id, releases,
                country.get("release_puppet_queue", []))
        except ValueError as error:
            raise PlayerActionError(str(error)) from error
        return {"type": "puppet_draft", "puppet_order": list(puppet_order),
                "siphons": canonical_siphons, "release_subjects": canonical_releases,
                "appearances": canonical_appearances}

    def _validate_faction_rename(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        country = self._country(country_id)
        name = command.get("name")
        if name is None:
            return {"type": "faction_rename", "name": None}
        if not isinstance(name, str) or len(name.strip()) > 40:
            raise PlayerActionError("Invalid faction name.")
        old_name = country.get("faction", "")
        if name.strip() == old_name:
            return {"type": "faction_rename", "name": None}
        if not country.get("is_faction_leader") or not old_name:
            raise PlayerActionError("Only a faction leader may rename their faction.")
        from map_logic.diplomacy import faction_actions
        # Validate against a copy: the helper owns the collision and membership
        # rules, while the real mutation waits for atomic turn processing.
        probe = copy.deepcopy(self.world.nation_data)
        if not faction_actions.rename_faction(probe, country_id, old_name, name.strip()):
            raise PlayerActionError("That faction name is unavailable.")
        return {"type": "faction_rename", "name": name.strip()}

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
        return {"type": "ratification_response", "verdict": verdict, "treaty_id": reference}

    def _validate_volunteer_draft(self, country_id: str, command: dict[str, Any], *, map_ref=None) -> dict[str, Any]:
        """Identify divisions by their authoritative province/index, never data."""
        from data import queries
        target, units = command.get("target"), command.get("units", [])
        if (not isinstance(target, str) or target == country_id or target not in self.world.nation_data
                or not isinstance(units, list) or not units or len(units) > 100):
            raise PlayerActionError("Invalid volunteer offer.")
        from map_logic.diplomacy import volunteers
        legal, reason = volunteers.is_eligible(country_id, target, self.world.nation_data)
        if not legal:
            raise PlayerActionError(reason)
        canonical, seen = [], set()
        for ref in units:
            if not isinstance(ref, dict):
                raise PlayerActionError("Invalid volunteer division.")
            view = self.map_ref if map_ref is None else map_ref
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

    def _validate_country_diplomacy(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Validate only this country's unprocessed diplomatic draft.

        Diplomacy is deliberately a command rather than copied client map data.
        In-flight proposals remain on the authoritative map; clients can only
        replace their own unsent proposals and responses for the current turn.
        """
        from data import queries

        self._country(country_id)
        pending = command.get("pending", {})
        responses = command.get("responses", {})
        draft_lists = command.get("draft_lists", {})
        if not all(isinstance(value, dict) for value in (pending, responses, draft_lists)):
            raise PlayerActionError("Invalid diplomacy draft.")
        if any(len(value) > 100 for value in (pending, responses, draft_lists)):
            raise PlayerActionError("Too many diplomatic actions in one turn.")
        allowed_actions = set(c.UNILATERAL_ACTIONS) | set(c.BILATERAL_ACTIONS)

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
            from map_logic.diplomacy.action_definitions import availability
            available = availability(self.map_ref, country_id, target, action)
            if not available.allowed:
                raise PlayerActionError(available.reason)
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
            canonical_pending[target] = entry

        canonical_responses = {}
        for target, info in responses.items():
            target_ok(target)
            if not isinstance(info, dict):
                raise PlayerActionError("Invalid diplomatic response.")
            verdict, action = info.get("verdict"), info.get("action")
            if verdict not in ("ACCEPT", "REJECT") or action not in c.BILATERAL_ACTIONS:
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
            from map_logic.diplomacy import diplomacy_lifecycle as lifecycle
            try:
                entry.update(lifecycle.canonical_response_reference(
                    self.world.nation_data, country_id, target, info))
            except ValueError as error:
                raise PlayerActionError(str(error)) from error
            canonical_responses[target] = entry

        canonical_lists = {}
        for target, messages in draft_lists.items():
            target_ok(target)
            if (not isinstance(messages, list) or len(messages) > 20 or
                    any(not isinstance(message, str) or len(message) > 4000 or
                        any(ord(character) < 32 and character not in "\n\t" for character in message)
                        for message in messages)):
                raise PlayerActionError("Invalid diplomatic message draft.")
            canonical_lists[target] = list(messages)
        return {"type": "country_diplomacy", "pending": canonical_pending,
                "responses": canonical_responses, "draft_lists": canonical_lists}

    def _province(self, province_id: Any):
        try:
            return self.world.id_to_province[int(province_id)]
        except (KeyError, TypeError, ValueError) as exc:
            raise PlayerActionError("Unknown province in order.") from exc

    def _validate_unit_order(self, country_id: str, command: dict[str, Any], *, map_ref=None) -> dict[str, Any]:
        from data import queries
        map_ref = self.map_ref if map_ref is None else map_ref
        try:
            province = queries.province_for_order(map_ref, command.get("province_id"))
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
        from map_logic.actions import unit_actions
        try:
            prepared = unit_actions.prepare_action(map_ref, country_id, province, unit, order)
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
        if stance not in (None, "RESERVE"):
            raise PlayerActionError("Invalid combat stance.")
        lane_target = command.get("lane_target")
        if lane_target is not None and (not isinstance(lane_target, str)
                                        or lane_target not in self.world.nation_data
                                        or not queries.are_at_war(country_id, lane_target, self.world.nation_data)):
            raise PlayerActionError("Invalid battle lane target.")
        return {"type": "unit_order", "province_id": province["id"],
                "unit_index": index, "unit_id": unit.get("unit_id"), "order": canonical_order,
                "unit_refund": prepared.refund,
                "custom_name": custom_name.strip() if isinstance(custom_name, str) and custom_name.strip() else None,
                "combat_stance": stance, "lane_target": lane_target}

    def _canonical_unit_order(self, country_id: str, province: dict[str, Any], unit: dict[str, Any],
                              order: dict[str, Any] | None, *, map_ref=None) -> dict[str, Any] | None:
        """Use the same rule as tournament's host-validated aircraft orders."""
        from data import queries
        try:
            return queries.canonical_unit_order(self.map_ref if map_ref is None else map_ref,
                                                country_id, province, unit, order)
        except ValueError as exc:
            raise PlayerActionError(str(exc)) from exc

    def _validate_queue(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        from data import queries
        province = self._province(command.get("province_id"))
        if province.get("owner") != country_id:
            raise PlayerActionError("Players may only change queues in their own provinces.")
        queue_type = command.get("queue")
        items = command.get("items")
        if queue_type not in ("building_queue", "unit_queue") or not isinstance(items, list):
            raise PlayerActionError("Invalid province queue.")
        if len(items) > self._MAX_QUEUE_ITEMS or any(not isinstance(item, dict) for item in items):
            raise PlayerActionError("Invalid province queue contents.")
        from map_logic.actions import production_actions
        try:
            return production_actions.reconstruct_queue(
                self.map_ref, country_id, province, queue_type, items,
                policy=production_actions.REALTIME_POLICY)
        except ValueError as error:
            raise PlayerActionError(str(error)) from error

    def _build_queue_item(self, country_id: str, province: dict[str, Any], queue_type: str,
                          intent: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Reconstruct untrusted client intent through shared production rules."""
        from map_logic.actions import production_actions
        try:
            result = production_actions.prepare_production(
                self.map_ref, country_id, province, queue_type, intent,
                policy=production_actions.REALTIME_POLICY)
        except ValueError as error:
            raise PlayerActionError(str(error)) from error
        return result.order, result.cost

    def _validate_queue_budget(self, country_id: str, commands: list[dict[str, Any]]) -> None:
        """Ensure queue changes can be paid for before accepting a draft."""
        from map_logic.actions.production_actions import validate_queue_budget
        try:
            validate_queue_budget(self._country(country_id), commands)
        except ValueError as error:
            raise PlayerActionError(str(error)) from error

    def _validate_research_queue(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Replay a player's start/pause choices without trusting client points.

        Clients submit only the desired ordered tech names. Progress always
        comes from the authoritative map: pausing stores that server progress,
        and resuming restores it. A forged client therefore cannot finish a
        technology by claiming a smaller point cost.
        """
        from data import queries

        try:
            result = queries.canonical_research_selection(self.world.nation_data.get(country_id),
                                                          command.get("tech_names"),
                                                          queries.get_tech_tree(self.map_ref), context=self.map_ref)
        except ValueError as error:
            raise PlayerActionError(str(error)) from error
        return {"type": "research_queue", **result}

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
            from map_logic.diplomacy import volunteers
            if any(command["type"] == "country_diplomacy" for command in commands):
                volunteers.release_draft_reservations(self.map_ref, country_id)
            country_data = self.world.nation_data[country_id]
            from data import queries
            from map_logic.actions.production_actions import settle_draft_budget
            settle_draft_budget(country_data, commands)
            queries.apply_air_transport_commands(self.map_ref, country_id,
                [command for command in commands if command["type"] == "air_transport"])
            for command in commands:
                if command["type"] == "air_transport":
                    continue
                if command["type"] == "unit_order":
                    province = self._province(command["province_id"])
                    unit = (next(u for u in province["units"] if u.get("unit_id") == command["unit_id"])
                            if command.get("unit_id") else province["units"][command["unit_index"]])
                    from map_logic.actions.unit_actions import apply_action
                    apply_action(self.map_ref, country_id, province, unit,
                                 command["order"], authority="server", payment_settled=True)
                    for key in ("custom_name", "combat_stance", "lane_target"):
                        value = command.get(key)
                        if value is None:
                            unit.pop(key, None)
                        else:
                            unit[key] = value
                elif command["type"] == "province_queue":
                    from map_logic.actions.production_actions import apply_queue_change
                    apply_queue_change(self.map_ref, country_id, command, payment_settled=True)
                elif command["type"] == "research_queue":
                    from map_logic.system32.research_processor import apply_research_selection
                    apply_research_selection(country_data, command)
                elif command["type"] == "country_preferences":
                    country_data["political_drift"] = command["political_drift"]
                    country_data["automation"] = copy.deepcopy(command["automation"])
                    country_data["conscription_slider"] = command["conscription_slider"]
                    country_data["mat_to_fuel_slider"] = command["mat_to_fuel_slider"]
                    country_data["custom_production_units"] = copy.deepcopy(command["custom_production_units"])
                    if command[politics.POLICY_KEY]:
                        country_data[politics.POLICY_KEY] = copy.deepcopy(command[politics.POLICY_KEY])
                    else:
                        country_data.pop(politics.POLICY_KEY, None)
                elif command["type"] == "army_roster":
                    country_data["armies"] = copy.deepcopy(command["armies"])
                elif command["type"] == "claim_draft":
                    country_data["claim_queue"] = copy.deepcopy(command["queue"])
                    country_data["revoke_queue"] = copy.deepcopy(command["revokes"])
                    country_data["return_queue"] = copy.deepcopy(command["returns"])
                elif command["type"] == "country_appearance":
                    queries.apply_country_appearance(self.world.nation_data, country_id, command["appearance"])
                    self.map_ref.nation_colors[country_id] = tuple(country_data["color"])
                elif command["type"] == "country_diplomacy":
                    # A proposal already travelling belongs to the server and
                    # cannot be cancelled or rewritten by a stale client view.
                    from map_logic.diplomacy import diplomacy_lifecycle as lifecycle
                    lifecycle.apply_draft(self.world.nation_data, country_id,
                                          command["pending"], command["responses"], command["draft_lists"])
                elif command["type"] == "puppet_draft":
                    country_data["puppets"] = list(command["puppet_order"])
                    country_data["release_puppet_queue"] = copy.deepcopy(command["release_subjects"])
                    for puppet, rates in command["siphons"].items():
                        self.world.nation_data[puppet]["siphon_rates"] = copy.deepcopy(rates)
                    for puppet, appearance in command["appearances"].items():
                        subject = self.world.nation_data[puppet]
                        queries.apply_country_appearance(self.world.nation_data, puppet, appearance)
                        self.map_ref.nation_colors[puppet] = tuple(subject["color"])
                elif command["type"] == "faction_rename" and command.get("name"):
                    from map_logic.diplomacy import faction_actions
                    faction_actions.rename_faction(self.world.nation_data, country_id,
                                                   country_data.get("faction", ""), command["name"])
                elif command["type"] == "ratification_response":
                    pending = country_data.get("pending_ratification")
                    if isinstance(pending, dict):
                        from map_logic.diplomacy import diplomacy_lifecycle as lifecycle
                        lifecycle.answer_ratification(self.world.nation_data, country_id, command["verdict"],
                                                      treaty_id=command.get("treaty_id"))
            # Volunteer reservations must be created after their diplomatic
            # request has been placed on the server map, just like the normal
            # player UI does in an offline game.
            for command in commands:
                if command["type"] != "volunteer_draft":
                    continue
                pending = country_data.get("pending_diplomacy", {}).get(command["target"], {})
                if not isinstance(pending, dict) or pending.get("action") != "SEND_VOLUNTEERS":
                    continue
                from map_logic.diplomacy import volunteers
                chosen = []
                for ref in command["units"]:
                    province = self._province(ref["province_id"])
                    unit = (next(unit for unit in province["units"] if unit.get("unit_id") == ref["unit_id"])
                            if ref.get("unit_id") else province["units"][ref["unit_index"]])
                    chosen.append((province, unit))
                _details, error = volunteers.create_offer(self.map_ref, country_id, command["target"], chosen)
                if error:
                    raise PlayerActionError(error)

    def _refresh_payments(self, country_id, commands):
        from data import queries
        from map_logic.diplomacy import volunteers
        planning_view = self._planning_view(country_id, commands)
        transport = [command for command in commands if command["type"] == "air_transport"]
        view = queries.air_transport_draft(planning_view, country_id, transport)[0] if transport else planning_view
        refreshed = []
        for command in commands:
            if command["type"] == "unit_order":
                command = self._validate_unit_order(country_id, command, map_ref=view)
            elif command["type"] == "province_queue":
                command = self._validate_queue(country_id, command)
            refreshed.append(command)
        self._validate_queue_budget(country_id, refreshed)
        return refreshed

    def apply_legacy_unit_projection(self, country_id, provs, live_aircraft, aircraft_orders, *, replace_units):
        """Apply validated older snapshots after the tournament host completes review.

        This input adapter preserves approved stats and queue overrides.
        Current player intents cannot reach this method.
        """
        from data import queries
        world_state = self.world
        # ``unit_snapshot`` was added after the original .gd5move format.
        # Preserve old files' behavior, but make every newly-created move
        # replace even an empty army so disbands and volunteer offers survive.
        apply_unit_snapshot = replace_units
        if apply_unit_snapshot:
            for target_prov in world_state.map_data.values():
                target_prov["units"] = [u for u in target_prov.get("units", [])
                                        if u.get("owner") != country_id or u.get("unit_id") in live_aircraft]
            
            # Create a lookup for json_key -> tuple key
            json_key_map = {v.get("json_key"): k for k, v in world_state.map_data.items()}
                
            for prov_key, updates in provs.items():
                real_key = json_key_map.get(prov_key)
                if real_key not in world_state.map_data:
                    continue
                target_prov = world_state.map_data[real_key]
                
                if "building_queue" in updates:
                    target_prov["building_queue"] = updates["building_queue"]
                if "unit_queue" in updates:
                    target_prov["unit_queue"] = updates["unit_queue"]
                    
                if "units" in updates:
                    if "units" not in target_prov:
                        target_prov["units"] = []
                    target_prov["units"].extend(u for u in updates["units"] if isinstance(u, dict)
                        and u.get("owner") == country_id and u.get("unit_id") not in live_aircraft
                        and not queries.is_air_unit(u, context=self.map_ref) and not queries.is_air_transport(u, context=self.map_ref)
                        and not (isinstance(u.get("order"), dict)
                                 and isinstance(u["order"].get("type"), str)
                                 and u["order"].get("type") in queries.AIR_ORDER_TYPES))

        for unit, order, name in aircraft_orders:
            uid = unit["unit_id"]
            current = next(u for p in world_state.map_data.values()
                           for u in queries.units_with_air_cargo(p.get("units", []))
                           if u.get("unit_id") == uid)
            current["order"] = order or {"type": "MOVE", "path": []}
            if name:
                current["custom_name"] = name
            


def collect_map_commands(map_ref, country_id: str) -> list[dict[str, Any]]:
    """Serialize supported local order controls into server commands.

    This deliberately reads only player choices, never mutable combat,
    resource, research-progress, or claim-timer fields from the client map.
    """
    from map_logic.diplomacy import volunteers
    held_offers = volunteers.unsent_offers(map_ref, country_id)
    volunteer_choices = {target: [{"province_id": entry["origin_id"],
                                  "unit_id": entry["unit"].get("unit_id")}
                                 for entry in mission.get("held_units", [])]
                         for target, mission in held_offers.items()}
    map_ref = volunteers.draft_context(map_ref, country_id)
    world_state = world_for(map_ref)
    from data import queries
    queries.ensure_unit_ids(world_state.map_data)
    commands: list[dict[str, Any]] = queries.air_transport_commands(map_ref, country_id)
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
    from data import queries
    queries.normalize_armies(world_state.nation_data, world_state.map_data)
    country_data = world_state.nation_data.get(country_id, {})
    commands.append({"type": "army_roster",
                     "armies": copy.deepcopy(country_data.get("armies", []))})
    research_queue = country_data.get("research_queue", []) if isinstance(country_data, dict) else []
    tech_names = [project.get("tech_name") for project in research_queue
                  if isinstance(project, dict) and isinstance(project.get("tech_name"), str)]
    # Include an empty selection too: pausing every project must be a real
    # draft change rather than silently preserving the server's old queue.
    commands.append({"type": "research_queue", "tech_names": tech_names})
    commands.append({"type": "country_preferences",
                     "political_drift": country_data.get("political_drift", 0),
                     "automation": copy.deepcopy(country_data.get("automation", {})),
                     "conscription_slider": country_data.get("conscription_slider", 1.0),
                     "mat_to_fuel_slider": country_data.get("mat_to_fuel_slider", 0.0),
                     "custom_production_units": copy.deepcopy(country_data.get("custom_production_units", [])),
                     politics.POLICY_KEY: politics.policy_draft_projection(
                         world_state.nation_data, country_id)})
    # Claim timers are server state. A client only says which existing/new
    # claims should remain queued; validation restores server timers and gives
    # new claims the standard fabrication time.
    claim_queue = country_data.get("claim_queue", []) if isinstance(country_data, dict) else []
    commands.append({"type": "claim_draft", "province_ids": [entry.get("prov_id")
                     for entry in claim_queue if isinstance(entry, dict)
                     and isinstance(entry.get("prov_id"), int)
                     and not isinstance(entry.get("prov_id"), bool)],
                     "revoke_ids": [entry.get("prov_id") for entry in country_data.get("revoke_queue", [])
                                    if isinstance(entry, dict) and isinstance(entry.get("prov_id"), int)
                                    and not isinstance(entry.get("prov_id"), bool)],
                     "returns": [{"prov_id": entry.get("prov_id"), "recipient": entry.get("recipient")}
                                 for entry in country_data.get("return_queue", [])
                                 if isinstance(entry, dict)]})
    # Older partial country records can omit appearance entirely.
    if "color" in country_data:
        commands.append({"type": "country_appearance", "appearance": {
            key: copy.deepcopy(country_data.get(key, "DEFAULT" if key.endswith("_data") else [] if key == "color" else ""))
            for key in PlayerActions._APPEARANCE_KEYS}})
    # Only unsent proposals are a local draft.  Messages already in transit
    # are server-owned and are deliberately omitted so a stale client cannot
    # cancel or alter them on its next ordinary sync.
    pending = country_data.get("pending_diplomacy", {})
    if not isinstance(pending, dict):
        pending = {}
    responses = country_data.get("diplo_responses", {})
    if not isinstance(responses, dict):
        responses = {}
    draft_lists = country_data.get("draft_lists", {})
    if not isinstance(draft_lists, dict):
        draft_lists = {}
    commands.append({"type": "country_diplomacy",
                     "pending": {target: copy.deepcopy(info) for target, info in pending.items()
                                 if isinstance(target, str) and isinstance(info, dict)
                                 and info.get("turns", 0) <= 0},
                     "responses": copy.deepcopy(responses),
                     "draft_lists": copy.deepcopy(draft_lists)})
    controlled = country_data.get("puppets", []) if isinstance(country_data, dict) else []
    siphons = {}
    for puppet in controlled:
        subject = world_state.nation_data.get(puppet, {})
        if isinstance(subject, dict) and subject.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED:
            siphons[puppet] = copy.deepcopy(subject.get("siphon_rates", {}))
    commands.append({"type": "puppet_draft", "puppet_order": list(controlled), "siphons": siphons,
                     "release_subjects": [{"core_nation": entry.get("core_nation"),
                                           "keep_cores": bool(entry.get("keep_cores", False)),
                                           "release_type": entry["release_type"]}
                                          for entry in country_data.get("release_puppet_queue", [])
                                          if isinstance(entry, dict)],
                     "appearances": copy.deepcopy(getattr(map_ref, "realtime_pending_appearance_updates", {}))})
    commands.append({"type": "faction_rename", "name": country_data.get("faction", "")})
    pending_ratification = country_data.get("pending_ratification", {})
    commands.append({"type": "ratification_response",
                     "verdict": pending_ratification.get("verdict") if isinstance(pending_ratification, dict) else None,
                     "treaty_id": pending_ratification.get("treaty_id") if isinstance(pending_ratification, dict) else None})
    volunteer_drafts = getattr(map_ref, "realtime_volunteer_drafts", {})
    if isinstance(volunteer_drafts, dict):
        volunteer_choices.update(volunteer_drafts)
    for target, units in volunteer_choices.items():
        commands.append({"type": "volunteer_draft", "target": target, "units": copy.deepcopy(units)})
    return commands
