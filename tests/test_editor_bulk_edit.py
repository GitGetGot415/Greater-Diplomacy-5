"""Check bulk setup changes, cancellation, permissions, and persistence."""

import copy
import json
import unittest
from unittest import mock

from data import queries
from map_logic.diplomacy import faction_records, volunteers
from screens.editors import menus
from screens.editors.brush_screens import Bulk_Edit_Screen, Clear_Map_Screen, Unit_Transfer_Screen
from tests.stub_map_screen import map_double


def equipment(family, tier, requirement, health, extra=()):
    return {
        "health": health, "attack": tier * 3, "defense": tier * 2,
        "speed": tier, "naval_unit": False,
        "metadata": {"family": family, "tier_order": tier,
                     "research": requirement, "requirements": [requirement, *extra],
                     "recruitment": {"industry": "none", "coastal": False}},
    }


def editor():
    provinces = {
        "a": {"id": 1, "json_key": "a", "owner": "A", "cores": ["A"],
              "buildings": ["Basic Factory", "Other"], "units": [], "neighbors": [2]},
        "b": {"id": 2, "json_key": "b", "owner": "B", "cores": ["B"],
              "buildings": ["Factory Lvl 4"], "units": [], "neighbors": [1]},
        "empty": {"id": 3, "json_key": "empty", "owner": "A", "cores": [], "units": []},
    }
    return map_double(
        is_editor=True, map_data=provinces, id_to_province={p["id"]: p for p in provinces.values()},
        nation_data={"A": {"research": {"fixture": 1}, "materials": 17}, "B": {}},
        queue_editor_visual_refresh=mock.Mock(), refresh_all_maps=mock.Mock(),
        refresh_diplomacy_maps=mock.Mock(), show_feedback=mock.Mock(), refresh_nation_data=mock.Mock())


class BulkEditTests(unittest.TestCase):
    def setUp(self):
        self.game = editor()
        self.library = {
            "Early": equipment("Ground", 10, {"tech": "ground", "year": 1810}, 120),
            "Late": equipment("Ground", 30, {"tech": "ground", "year": 1850}, 300),
            "Engine I": equipment("Engine", 1, {"tech": "engine", "level": 1}, 90),
            "Engine II": equipment("Engine", 2, {"tech": "engine", "level": 2}, 150),
            "Vehicle": equipment("Vehicle", 10, {"tech": "gate", "level": 1}, 80,
                                 [{"tech": "ground", "minimum_year": 1840}]),
        }
        self.tree = {"ground": {"years": [1810, 1850]}, "engine": {"years": [1820, 1860]},
                     "gate": {"years": [1830]}}
        self.enterContext(mock.patch.object(queries, "get_unit_library", return_value=self.library))
        self.enterContext(mock.patch.object(queries, "get_tech_tree", return_value=self.tree))
        self.buildings = {
            "Basic Factory": {"group": "industry"},
            "Factory Lvl 2": {"group": "industry"},
            "Factory Lvl 4": {"group": "industry"},
            "Recruitment Start": {"group": "recruitment"},
            "Recruitment Target": {"group": "recruitment"},
            "Fort Start": {"group": "fortification"},
            "Fort Target": {"group": "fortification"},
            "Other": {"group": "other"},
        }
        self.enterContext(mock.patch.object(queries, "get_building_library", return_value=self.buildings))

    def test_each_building_group_changes_only_existing_matching_buildings(self):
        for group in queries.EDITOR_BUILDING_GROUPS:
            with self.subTest(group=group):
                game = editor()
                source, *_, target = [name for name, data in self.buildings.items() if data["group"] == group]
                other_buildings = [name for name, data in self.buildings.items() if data["group"] != group]
                game.map_data["a"]["buildings"] = [source, *other_buildings]
                game.map_data["a"]["building_queue"] = [{"type": source, "turns_left": 3}]
                game.map_data["b"]["buildings"] = [target]
                game.map_data["other"] = {"id": 4, "owner": "B", "buildings": other_buildings.copy()}
                before = copy.deepcopy(game.map_data)
                self.assertEqual(queries.set_editor_buildings(game, group, target), 1)
                self.assertEqual(game.map_data["a"]["buildings"], [target, *other_buildings])
                self.assertEqual(game.map_data["b"], before["b"])
                self.assertEqual(game.map_data["other"], before["other"])
                self.assertEqual(game.map_data["empty"], before["empty"])
                self.assertEqual(game.map_data["a"]["building_queue"], before["a"]["building_queue"])
                self.assertEqual(len(game.editor_history), 1)
                queries.restore_editor_state(game)
                self.assertEqual(game.map_data["a"]["buildings"], before["a"]["buildings"])
                queries.redo_editor_state(game)
                self.assertEqual(game.map_data["a"]["buildings"], [target, *other_buildings])

    def test_building_group_validation_and_no_matching_tiles_have_no_side_effects(self):
        for group in queries.EDITOR_BUILDING_GROUPS:
            expected = [name for name, data in self.buildings.items() if data["group"] == group]
            self.assertEqual(queries.editor_building_targets(self.game, group), expected)
            with self.subTest(group=group), self.assertRaises(ValueError):
                queries.set_editor_buildings(self.game, group, "Other")
        with self.assertRaises(ValueError):
            queries.set_editor_buildings(self.game, "unknown", "Other")
        with self.assertRaises(ValueError):
            queries.set_editor_buildings(self.game, "fortification", "Basic Factory")
        before = copy.deepcopy(self.game.map_data)
        self.assertEqual(queries.set_editor_buildings(self.game, "fortification", "Fort Target"), 0)
        self.assertEqual(self.game.map_data, before)
        self.assertEqual(self.game.editor_history, [])

    def test_factories_change_across_owners_and_support_undo_redo(self):
        self.assertEqual(queries.editor_building_targets(self.game, "industry"),
                         ["Basic Factory", "Factory Lvl 2", "Factory Lvl 4"])
        self.assertEqual(queries.set_editor_buildings(self.game, "industry", "Factory Lvl 2"), 2)
        self.assertEqual(self.game.map_data["a"]["buildings"], ["Factory Lvl 2", "Other"])
        self.assertNotIn("buildings", self.game.map_data["empty"])
        self.assertEqual(len(self.game.editor_history), 1)
        queries.restore_editor_state(self.game)
        self.assertEqual(self.game.map_data["a"]["buildings"], ["Basic Factory", "Other"])
        queries.redo_editor_state(self.game)
        self.assertEqual(self.game.map_data["b"]["buildings"], ["Factory Lvl 2"])

    def test_invalid_and_unchanged_factories_do_not_create_history(self):
        with self.assertRaises(ValueError):
            queries.set_editor_buildings(self.game, "industry", "Other")
        self.game.map_data["b"]["buildings"] = []
        self.assertEqual(queries.set_editor_buildings(self.game, "industry", "Basic Factory"), 0)
        self.assertEqual(self.game.editor_history, [])

    def test_year_uses_equipment_and_numbered_research_dates_inclusively(self):
        for year, expected in ((1800, {}), (1820, {"Ground": "Early", "Engine": "Engine I"}),
                               (1840, {"Ground": "Early", "Engine": "Engine I", "Vehicle": "Vehicle"}),
                               (1850, {"Ground": "Late", "Engine": "Engine I", "Vehicle": "Vehicle"}),
                               (1860, {"Ground": "Late", "Engine": "Engine II", "Vehicle": "Vehicle"})):
            with self.subTest(year=year):
                self.assertEqual(queries.editor_unit_targets(self.game, "year", year), expected)

    def test_family_level_orders_metadata_tiers_and_clamps_each_family(self):
        self.assertEqual(queries.editor_unit_targets(self.game, "level", 1),
                         {"Ground": "Early", "Engine": "Engine I", "Vehicle": "Vehicle"})
        self.assertEqual(queries.editor_unit_targets(self.game, "level", 8),
                         {"Ground": "Late", "Engine": "Engine II", "Vehicle": "Vehicle"})
        for mode, value in (("other", 1), ("year", True), ("level", 0), ("year", "1850")):
            with self.subTest(mode=mode, value=value), self.assertRaises(ValueError):
                queries.set_editor_units(self.game, mode, value)
        self.assertEqual(self.game.editor_history, [])

    def test_units_keep_identity_damage_cargo_and_transport_with_undo(self):
        unit = {"type": "Early", "owner": "A", "id": "division", "custom_name": "Keep",
                "army_id": "army", "health": 30, "max_health": 120, "order": {"old": True}}
        cargo = copy.deepcopy(unit)
        cargo["id"] = "cargo"
        transport = {"type": "Convoy (Early)", "original_type": "Early", "health": 50,
                     "max_health": 100, "owner": "B", "id": "transport"}
        carrier = {"type": "Unknown carrier", "air_cargo": [cargo]}
        self.game.map_data["a"]["units"] = [unit, carrier]
        self.game.map_data["b"]["units"] = [transport]
        before = copy.deepcopy(self.game.map_data)
        research = copy.deepcopy(self.game.nation_data)
        self.assertEqual(queries.set_editor_units(self.game, "year", 1850), (3, 1))
        for changed in (unit, cargo):
            self.assertEqual(changed["type"], "Late")
            self.assertEqual(changed["health"], 75)
            self.assertEqual(changed["custom_name"], "Keep")
            self.assertEqual(changed["army_id"], "army")
            self.assertEqual(changed["order"], {})
        self.assertEqual(unit["id"], "division")
        self.assertEqual(transport["type"], "Convoy (Late)")
        self.assertEqual(transport["original_max_health"], 300)
        self.assertEqual(transport["health"] / transport["max_health"], .5)
        self.assertEqual(self.game.nation_data, research)
        queries.restore_editor_state(self.game)
        for key in before:
            self.assertEqual(self.game.map_data[key]["units"], before[key]["units"])

    def test_unavailable_year_keeps_units_and_does_not_create_history(self):
        self.game.map_data["a"]["units"] = [{"type": "Late"}]
        self.assertEqual(queries.set_editor_units(self.game, "year", 1800), (0, 1))
        self.assertEqual(self.game.map_data["a"]["units"][0]["type"], "Late")
        self.assertEqual(self.game.editor_history, [])

    def test_all_mutations_recheck_modes_and_processing_state(self):
        for field, value in (("is_editor", False), ("tactical_mode", True),
                             ("multiplayer_mode", True), ("realtime_multiplayer", True),
                             ("ai_is_thinking", True), ("viewing_ai_moves", True),
                             ("is_saving", True), ("is_refreshing", True)):
            with self.subTest(field=field), mock.patch.object(self.game, field, value):
                actions = [(queries.set_editor_buildings, (group, queries.editor_building_targets(self.game, group)[0]))
                           for group in queries.EDITOR_BUILDING_GROUPS]
                actions.extend(((queries.set_editor_units, ("year", 1850)),
                                (queries.reset_editor_diplomacy, ())))
                for action, args in actions:
                    with self.assertRaises(ValueError):
                        action(self.game, *args)
        self.assertEqual(self.game.editor_history, [])

    def test_diplomacy_reset_clears_both_directions_and_pending_treaties(self):
        game = self.game
        for country, other in (("A", "B"), ("B", "A")):
            game.nation_data[country].update({
                "at_war_with": [other], "master": other if country == "B" else "",
                "puppets": [other] if country == "A" else [], "puppet_type": "Integrated",
                "military_access": [other], "military_access_reasons": {other: "war"},
                "guarantees": [other], "military_attaches": [other],
                "pending_diplomacy": {other: {"action": "WAR_DECLARATION"}},
                "diplo_responses": {other: {}}, "draft_lists": {other: ["message"]},
                "pending_treaty": {"awaiting": [other]}, "pending_ratification": {"from": other},
                "temp_modifiers": {other: {"fixture": -9}}, "truces": {other: 4},
                "war_durations": {other: 8}, "inbox": [{"content": "Keep history"}],
                "return_queue": [{"prov_id": 1, "recipient": other}],
                "faction_pressure": 7, "is_created_integrated_puppet": True,
            })
        faction_records.restore(game, {"fixture": {"name": "Fixture", "leader": "A",
                                                   "members": ["A", "B"], "pre_war_borders": {"1": "A"}}})
        held = {"id": "held", "owner": "A", "type": "Early", "volunteer_host": "B"}
        deployed = {"id": "deployed", "owner": "A", "type": "Early",
                    "volunteer_host": "B", "volunteer_origin_id": 1}
        game.map_data["b"]["units"] = [deployed]
        game.nation_data["A"]["volunteer_missions"] = {"B": {
            "state": volunteers.DEPLOYED, "held_units": []}}
        game.nation_data["B"]["volunteer_missions"] = {"A": {
            "state": volunteers.OUTBOUND, "held_units": [{"unit": held, "origin_id": 2}]}}
        # The outbound fixture belongs to its donor and returns to that donor's origin.
        held["owner"] = "B"
        game.nation_data["GLOBAL_EVENTS"] = {"log": ["Keep event"]}
        game.nation_data["WAR_PRE_MAPS"] = {"A": {"1": "B"}}
        game.editor_history = ["old"]
        game.editor_redo_history = ["old"]
        queries.reset_editor_diplomacy(game)
        self.assertEqual(game.factions, {})
        self.assertEqual(game.faction_membership, {})
        self.assertEqual(game.nation_data["FACTION_WAR_MAPS"], {})
        self.assertNotIn("WAR_PRE_MAPS", game.nation_data)
        for country in ("A", "B"):
            data = game.nation_data[country]
            for key in ("at_war_with", "puppets", "guarantees", "military_access", "military_attaches"):
                self.assertEqual(data[key], [])
            for key in ("pending_diplomacy", "diplo_responses", "draft_lists", "temp_modifiers",
                        "military_access_reasons", "truces", "volunteer_missions"):
                self.assertEqual(data[key], {})
            for key in ("pending_treaty", "pending_ratification", "is_created_integrated_puppet"):
                self.assertNotIn(key, data)
            self.assertEqual(data["master"], "")
            self.assertEqual(data["faction"], "")
            self.assertEqual(data["inbox"], [{"content": "Keep history"}])
        self.assertEqual(game.map_data["a"]["units"], [deployed])
        self.assertEqual(game.map_data["b"]["units"], [held])
        self.assertNotIn("volunteer_host", deployed)
        self.assertNotIn("volunteer_host", held)
        self.assertEqual(game.nation_data["A"]["materials"], 17)
        self.assertEqual(game.nation_data["GLOBAL_EVENTS"]["log"], ["Keep event"])
        self.assertEqual(game.editor_history, [])
        self.assertEqual(game.editor_redo_history, [])

    def test_edited_equipment_and_buildings_survive_existing_save_overlay(self):
        self.game.map_data["a"]["units"] = [{"type": "Early", "owner": "A", "health": 60, "max_health": 120}]
        self.game.map_data["a"]["buildings"].extend(["Recruitment Start", "Fort Start"])
        for group in queries.EDITOR_BUILDING_GROUPS:
            targets = queries.editor_building_targets(self.game, group)
            queries.set_editor_buildings(self.game, group, targets[-1])
        queries.set_editor_units(self.game, "year", 1850)
        saved = json.loads(json.dumps({key: queries.build_saved_province_data(p)
                                      for key, p in self.game.map_data.items()}))
        loaded = editor()
        queries.overlay_saved_province_data(loaded.map_data, saved)
        for key in saved:
            self.assertEqual(loaded.map_data[key]["units"], self.game.map_data[key]["units"])
            self.assertEqual(loaded.map_data[key]["buildings"], self.game.map_data[key].get("buildings", []))

    def test_diplomacy_reset_refunds_actual_escrow_once(self):
        self.game.nation_data["A"].update({
            "pending_diplomacy": {"B": {"escrow": {"materials": 12},
                                         "parameters": {"promised_materials": 999}}},
            "pending_treaty": {"escrow": {"materials": 4}},
        })
        queries.reset_editor_diplomacy(self.game)
        self.assertEqual(self.game.nation_data["A"]["materials"], 17 + 12 + 4)
        queries.reset_editor_diplomacy(self.game)
        self.assertEqual(self.game.nation_data["A"]["materials"], 17 + 12 + 4)


class BulkEditorCallbackTests(unittest.TestCase):
    def test_building_picker_selects_group_and_level_then_requires_confirmation(self):
        screen = object.__new__(Bulk_Edit_Screen)
        screen.map_screen = editor()
        for group in queries.EDITOR_BUILDING_GROUPS:
            with self.subTest(group=group), \
                    mock.patch.object(queries, "editor_building_targets", return_value=["chosen"]) as targets, \
                    mock.patch("screens.editors.brush_screens.pickers.open_listbox_selector") as picker, \
                    mock.patch("ui.dialogs.ask_yes_no") as ask, \
                    mock.patch.object(queries, "set_editor_buildings", return_value=2) as apply:
                screen.pick_buildings()
                self.assertEqual({value for label, value in picker.call_args.args[3]},
                                 {"industry", "recruitment", "fortification"})
                apply.assert_not_called()
                picker.call_args.args[4](group)
                targets.assert_called_once_with(screen.map_screen, group)
                self.assertEqual(picker.call_args.args[3], ["chosen"])
                picker.call_args.args[4]("chosen")
                apply.assert_not_called()
                ask.call_args.args[2](False)
                apply.assert_not_called()
                ask.call_args.args[2](True)
                apply.assert_called_once_with(screen.map_screen, group, "chosen")

    def test_army_year_input_cancellation_and_confirmation(self):
        screen = object.__new__(Bulk_Edit_Screen)
        screen.map_screen = editor()
        with mock.patch("ui.dialogs.ask_integer") as number, \
                mock.patch("ui.dialogs.ask_yes_no") as ask, \
                mock.patch.object(queries, "set_editor_units", return_value=(2, 1)) as apply:
            screen.pick_units()
            number.call_args.args[2](None)
            ask.assert_not_called()
            apply.assert_not_called()
            number.call_args.args[2](1837)
            apply.assert_not_called()
            ask.call_args.args[2](True)
            apply.assert_called_once_with(screen.map_screen, "year", 1837)

    def test_refresh_waits_for_confirmation_and_rechecks_permission(self):
        game = editor()
        with mock.patch("ui.dialogs.ask_yes_no") as ask:
            menus.confirm_editor_data_refresh(game)
        game.refresh_nation_data.assert_not_called()
        confirmed = ask.call_args.args[2]
        confirmed(False)
        game.refresh_nation_data.assert_not_called()
        game.multiplayer_mode = True
        confirmed(True)
        game.refresh_nation_data.assert_not_called()
        game.multiplayer_mode = False
        confirmed(True)
        game.refresh_nation_data.assert_called_once_with()

    def test_bulk_confirmation_cancel_has_no_side_effects(self):
        screen = object.__new__(Bulk_Edit_Screen)
        screen.map_screen = editor()
        action = mock.Mock(return_value="Changed")
        with mock.patch("ui.dialogs.ask_yes_no") as ask:
            screen.confirm_change("Confirm", action)
        action.assert_not_called()
        ask.call_args.args[2](False)
        action.assert_not_called()
        ask.call_args.args[2](True)
        action.assert_called_once_with()


class EditorUnitTransferTests(unittest.TestCase):
    def transfer_fixture(self):
        game = editor()
        cargo = {"unit_id": "cargo", "type": "Early", "owner": "A", "order": {"type": "MOVE", "path": [2]}}
        moved = {"unit_id": "moved", "type": "Early", "owner": "A", "order": {"type": "MOVE", "path": [2]},
                 "air_cargo": [cargo]}
        kept = {"unit_id": "kept", "type": "Early", "owner": "A", "order": {"type": "MOVE", "path": [2]}}
        game.map_data["a"]["units"] = [moved, kept]
        game.nation_data["A"]["armies"] = [{"id": "army", "name": "First", "unit_ids": ["moved", "kept"]}]
        return game, moved, kept, cargo

    def test_transfer_changes_owner_with_cargo_clears_orders_and_rosters(self):
        game, moved, kept, cargo = self.transfer_fixture()
        queries.transfer_editor_units(game, [moved], "B")
        self.assertEqual((moved["owner"], cargo["owner"], kept["owner"]), ("B", "B", "A"))
        self.assertEqual(moved["order"], {})
        self.assertEqual(kept["order"], {"type": "MOVE", "path": [2]})
        self.assertEqual(game.nation_data["A"]["armies"][0]["unit_ids"], ["kept"])
        game.queue_editor_visual_refresh.assert_called_once_with()

    def test_transfer_rejects_missing_and_unplayable_countries(self):
        for country_id in ("Missing", "Unclaimed"):
            with self.subTest(country=country_id):
                game, moved, _kept, _cargo = self.transfer_fixture()
                game.nation_data.setdefault("Unclaimed", {})
                with self.assertRaises(ValueError):
                    queries.transfer_editor_units(game, [moved], country_id)
                self.assertEqual(moved["owner"], "A")

    def test_owner_choices_return_only_playable_country_ids(self):
        game = editor()
        game.nation_data["Unclaimed"] = {}
        self.assertEqual({value for _label, value in queries.editor_unit_owner_choices(game)}, {"A", "B"})

    def test_screen_transfers_only_selected_units_after_country_pick(self):
        game, moved, kept, _cargo = self.transfer_fixture()
        screen = object.__new__(Unit_Transfer_Screen)
        screen.map_screen, screen.province, screen.done = game, game.map_data["a"], False
        screen.selected = {0}
        with mock.patch("screens.editors.brush_screens.pickers.open_listbox_selector") as picker:
            screen.pick_country()
        self.assertEqual(moved["owner"], "A")
        picker.call_args.args[4]("B")
        self.assertEqual((moved["owner"], kept["owner"]), ("B", "A"))
        self.assertTrue(screen.done)

    def test_screen_without_selection_does_not_open_country_picker(self):
        game, *_ = self.transfer_fixture()
        screen = object.__new__(Unit_Transfer_Screen)
        screen.map_screen, screen.province, screen.selected = game, game.map_data["a"], set()
        with mock.patch("screens.editors.brush_screens.pickers.open_listbox_selector") as picker:
            screen.pick_country()
        picker.assert_not_called()


class ClearUnitsOutsideLandTests(unittest.TestCase):
    def test_clears_country_units_only_on_other_land(self):
        game = editor()
        game.map_data["sea"] = {"id": 4, "owner": "Ocean", "units": []}
        home, abroad, other, ship = ({"owner": "A", "type": "home"}, {"owner": "A", "type": "abroad"},
                                     {"owner": "B", "type": "other"}, {"owner": "A", "type": "ship"})
        game.map_data["a"]["units"] = [home]
        game.map_data["b"]["units"] = [abroad, other]
        game.map_data["sea"]["units"] = [ship]
        screen = object.__new__(Clear_Map_Screen)
        screen.map_screen, screen.done = game, False
        screen.selected_option = "all units from (x) country outside its land"
        screen.selected_country = "A"
        screen.selected_unit_type = screen.selected_resource_type = ""
        with mock.patch("ui.dialogs.ask_yes_no") as ask:
            screen.confirm_clear()
        ask.call_args.args[2](True)
        self.assertEqual(game.map_data["a"]["units"], [home])
        self.assertEqual(game.map_data["b"]["units"], [other])
        self.assertEqual(game.map_data["sea"]["units"], [ship])


if __name__ == "__main__":
    unittest.main()
