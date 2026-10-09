"""Check immediate spectator annexation, deletion, permissions, and save history."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import pygame

import data.constants as c
from data import queries
from map_logic.diplomacy import puppet_actions, volunteers, faction_leadership
from map_logic.turn_processing import turn_processor, edit_province_ownership
from tests import app_harness
from tests.test_map_save_format import sample_map_screen
from ui import spectator_menus, confirm_dialog, modal_stack


def country(name):
    return dict(name=name, is_playable=True, color=[100, 120, 140], research={},
                master="", puppet_type="", puppets=[], faction="", is_faction_leader=False,
                at_war_with=[], allied_with=[], pending_diplomacy={}, claims=[], armies=[])


def unit(owner, unit_id):
    return dict(owner=owner, unit_id=unit_id, type="Fixture", health=100, max_health=100,
                attack=1, defense=1, speed=1, naval_unit=False, order={"type": "MOVE", "path": []})


def game():
    screen = sample_map_screen()
    screen.nation_data = {key: country(key + " Display") for key in ("Source", "Target", "Child", "Ally")}
    screen.map_data = {}
    for pid, owner in ((1, "Source"), (2, "Target"), (3, "Target"), (4, "Ally")):
        screen.map_data[str(pid)] = dict(id=pid, json_key=str(pid), owner=owner, cores=[owner, "Target"],
                                        terrain="plains", neighbors=[n for n in range(1, 5) if n != pid],
                                        map_color=[pid, 0, 0], units=[], unit_queue=[], building_queue=[],
                                        orders=[], resources={}, buildings=[])
    screen.id_to_province = {p["id"]: p for p in screen.map_data.values()}
    screen.player_country = "Spectator"
    screen.active_players = ["Spectator"]
    screen.is_editor = screen.tactical_mode = screen.selection_mode = False
    screen.multiplayer_mode = screen.realtime_multiplayer = False
    screen.ai_is_thinking = screen.viewing_ai_moves = False
    screen.is_saving = screen.is_refreshing = False
    screen.selected_province = screen.map_data["1"]
    screen.nation_colors = {key: tuple(data["color"]) for key, data in screen.nation_data.items()}
    screen.time_manager.get_date_string = lambda: "Fixture Date"
    screen.show_feedback = mock.Mock()
    return screen


class SpectatorCountryRemovalTests(unittest.TestCase):
    def setUp(self):
        self.game = game()

    def remove(self, annexer=None):
        return puppet_actions.finalize_spectator_country_removal(self.game, "Target", annexer)

    def test_annex_transfers_all_land_units_cargo_and_puppets_immediately(self):
        target = self.game.nation_data["Target"]
        target.update(puppets=["Child"], faction="Pact", is_faction_leader=True, at_war_with=["Source"])
        self.game.nation_data["Child"].update(master="Target", puppet_type=c.PUPPET_TYPE_AUTONOMOUS)
        self.game.nation_data["Source"]["at_war_with"] = ["Target"]
        carrier = unit("Target", "carrier")
        carrier["air_cargo"] = [unit("Target", "cargo")]
        abroad = unit("Target", "abroad")
        self.game.map_data["4"]["units"] = [carrier, abroad]
        self.assertTrue(self.remove("Source"))
        self.assertEqual([self.game.map_data[str(pid)]["owner"] for pid in (1, 2, 3)], ["Source"] * 3)
        self.assertEqual(self.game.map_data["4"]["owner"], "Ally")
        self.assertTrue(all(u["owner"] == "Source" for u in queries.units_with_air_cargo([carrier, abroad])))
        self.assertEqual(self.game.nation_data["Child"]["master"], "Source")
        self.assertIn("Child", self.game.nation_data["Source"]["puppets"])
        self.assertEqual(target["faction"], "")
        self.assertEqual(target["at_war_with"], [])
        self.assertEqual(self.game.nation_data["Source"]["at_war_with"], [])
        self.assertNotIn("Target", queries.get_active_ai_nations(self.game))
        self.assertIn("Target", self.game.map_data["2"]["cores"])

    def test_integrated_annexer_receives_the_land_instead_of_its_master(self):
        self.game.nation_data["Source"].update(master="Ally", puppet_type=c.PUPPET_TYPE_INTEGRATED,
                                             spawned_territories=[1])
        self.assertTrue(self.remove("Source"))
        self.assertEqual(self.game.map_data["2"]["owner"], "Source")
        self.assertEqual(set(self.game.nation_data["Source"]["spawned_territories"]), {1, 2, 3})

    def test_subject_can_annex_its_ancestor_without_a_cycle(self):
        self.game.nation_data["Target"]["puppets"] = ["Child"]
        self.game.nation_data["Child"].update(master="Target", puppets=["Source"])
        self.game.nation_data["Source"].update(master="Child", puppet_type=c.PUPPET_TYPE_AUTONOMOUS)
        self.assertTrue(self.remove("Source"))
        self.assertEqual(self.game.nation_data["Source"]["master"], "")
        self.assertEqual(self.game.nation_data["Child"]["master"], "Source")

    def test_delete_removes_country_land_cores_units_cargo_and_production(self):
        foreign = unit("Ally", "foreign")
        foreign["air_cargo"] = [unit("Target", "hidden_cargo")]
        self.game.map_data["4"]["units"] = [unit("Target", "abroad"), foreign]
        self.game.map_data["2"].update(units=[unit("Target", "home")],
                                       unit_queue=[{"type": "Fixture"}], building_queue=[{"type": "Fixture"}])
        self.assertTrue(self.remove())
        self.assertNotIn("Target", self.game.nation_data)
        self.assertNotIn("Target", self.game.nation_colors)
        for province in self.game.map_data.values():
            self.assertNotEqual(province["owner"], "Target")
            self.assertNotIn("Target", province["cores"])
            self.assertTrue(all(u["owner"] != "Target" for u in queries.units_with_air_cargo(province["units"])))
        self.assertEqual(self.game.map_data["2"]["owner"], "Unclaimed")
        self.assertEqual(self.game.map_data["2"]["unit_queue"], [])
        self.assertEqual(self.game.map_data["2"]["building_queue"], [])
        self.assertEqual(self.game.map_data["4"]["units"], [foreign])

    def test_delete_clears_diplomacy_nested_deals_queues_and_war_borders(self):
        data = self.game.nation_data["Source"]
        data.update(at_war_with=["Target", "Ally"], guarantees=["Target"], military_access=["Target"],
                    military_attaches=["Target"], puppets=["Target"],
                    pending_diplomacy={"Ally": {"action": "TRADE", "deal": {"sides": {"a": ["Target"]}}}},
                    release_puppet_queue=[{"core_nation": "Target", "turns_left": 1}],
                    return_queue=[{"to_nation": "Target"}], temp_modifiers={"Target": {"fixture": 1}})
        self.game.nation_data["Child"].update(master="Target", puppet_type=c.PUPPET_TYPE_AUTONOMOUS)
        self.game.nation_data["FACTION_WAR_MAPS"] = {
            "Pact": {"2": "Target", "4": "Ally"}, "at_war_with": [], "manpower": 0}
        self.assertTrue(self.remove())
        self.assertEqual(data["at_war_with"], ["Ally"])
        for field in ("guarantees", "military_access", "military_attaches", "puppets", "return_queue", "release_puppet_queue"):
            self.assertEqual(data[field], [])
        self.assertEqual(data["pending_diplomacy"], {})
        self.assertEqual(data["temp_modifiers"], {})
        self.assertEqual(self.game.nation_data["Child"]["master"], "")
        self.assertEqual(self.game.nation_data["FACTION_WAR_MAPS"]["Pact"], {"4": "Ally"})

    def test_deleting_a_leader_promotes_a_surviving_member(self):
        self.game.nation_data["Target"].update(faction="Pact", is_faction_leader=True)
        self.game.nation_data["Ally"].update(faction="Pact")
        with mock.patch.object(faction_leadership, "power_of", return_value=1):
            self.assertTrue(self.remove())
        self.assertTrue(self.game.nation_data["Ally"]["is_faction_leader"])

    def test_held_volunteers_transfer_on_annex_and_foreign_volunteers_return_on_delete(self):
        held = unit("Target", "held")
        self.game.nation_data["Target"]["volunteer_missions"] = {
            "Ally": {"state": volunteers.OUTBOUND, "held_units": [{"unit": held, "origin_id": 2}]}}
        self.assertTrue(self.remove("Source"))
        self.assertEqual(held["owner"], "Source")
        self.assertTrue(any(held in p["units"] and p["owner"] == "Source"
                            for p in self.game.map_data.values()))
        self.game = game()
        deployed = unit("Ally", "deployed")
        deployed.update(volunteer_host="Target", volunteer_origin_id=4)
        self.game.map_data["2"]["units"] = [deployed]
        self.game.nation_data["Ally"]["volunteer_missions"] = {
            "Target": {"state": volunteers.DEPLOYED, "held_units": []}}
        self.assertTrue(self.remove())
        self.assertIn(deployed, self.game.map_data["4"]["units"])
        self.assertNotIn("volunteer_host", deployed)
        self.assertEqual(self.game.nation_data["Ally"]["volunteer_missions"], {})

    def test_save_reload_does_not_restore_deleted_catalog_country_and_preserves_history(self):
        catalog = copy.deepcopy(self.game.nation_data)
        turn_processor.snapshot_history(self.game)
        history = copy.deepcopy(self.game.history)
        self.assertTrue(self.remove())
        self.assertEqual(self.game.history, history)
        with mock.patch.object(queries, "get_country_data", return_value=catalog):
            saved = json.loads(json.dumps(queries.build_save_dict(self.game, compact_nations=True)))
            queries.merge_country_templates(saved["nation_data"])
            queries.merge_country_templates(saved["nation_data"])
            self.assertNotIn("Target", saved["nation_data"])
            self.assertEqual(saved["nation_data"]["GLOBAL_EVENTS"]["deleted_countries"], ["Target"])
            old_snapshot = copy.deepcopy(history[str(self.game.time_manager.total_turns)]["nation_data"])
            queries.merge_country_templates(old_snapshot)
            self.assertIn("Target", old_snapshot)

    def test_wrong_modes_busy_state_and_invalid_annexers_cannot_mutate(self):
        for field in ("is_editor", "tactical_mode", "selection_mode", "multiplayer_mode", "realtime_multiplayer",
                      "ai_is_thinking", "viewing_ai_moves", "is_saving", "is_refreshing"):
            self.game = game()
            setattr(self.game, field, True)
            before = copy.deepcopy((self.game.nation_data, self.game.map_data))
            self.assertFalse(self.remove())
            self.assertFalse(self.remove("Source"))
            self.assertEqual((self.game.nation_data, self.game.map_data), before)
        self.game = game()
        self.game.player_country = "Source"
        self.assertFalse(self.remove())
        self.game.player_country = "Spectator"
        for target in ("Target", "Missing", "Unclaimed"):
            self.assertFalse(self.remove(target))


class SpectatorRemovalControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()

    def setUp(self):
        self.game = game()
        self.enterContext(mock.patch.object(spectator_menus, "_refresh_country_removal"))

    def test_annex_picker_uses_selected_source_and_display_names(self):
        with mock.patch.object(queries, "open_listbox_selector") as picker:
            spectator_menus.spec_annex_country(self.game)
        items = picker.call_args.args[3]
        self.assertIn(("Target Display", "Target"), items)
        self.assertNotIn(("Source Display", "Source"), items)
        picker.call_args.args[4]("Target")
        self.assertEqual(self.game.map_data["2"]["owner"], "Source")

    def test_delete_waits_for_confirmation_and_cancel_preserves_state(self):
        self.game.selected_province = self.game.map_data["2"]
        with mock.patch.object(confirm_dialog, "ask_yes_no") as ask:
            spectator_menus.spec_delete_country(self.game)
        before = copy.deepcopy((self.game.nation_data, self.game.map_data))
        self.assertIn("Target Display", ask.call_args.args[1])
        callback = ask.call_args.kwargs["on_result"]
        callback(False)
        self.assertEqual((self.game.nation_data, self.game.map_data), before)
        callback(True)
        self.assertNotIn("Target", self.game.nation_data)

    def test_stale_selection_or_permission_cancels_annex_and_delete_callbacks(self):
        for menu, tool, target in ((spectator_menus.spec_annex_country, queries, "open_listbox_selector"),
                                   (spectator_menus.spec_delete_country, confirm_dialog, "ask_yes_no")):
            for change in ("selection", "permissions"):
                self.game = game()
                with mock.patch.object(tool, target) as launch:
                    menu(self.game)
                if change == "selection":
                    self.game.selected_province = None
                else:
                    self.game.realtime_multiplayer = True
                before = copy.deepcopy((self.game.nation_data, self.game.map_data))
                if target == "ask_yes_no":
                    launch.call_args.kwargs["on_result"](True)
                else:
                    launch.call_args.args[4]("Target")
                self.assertEqual((self.game.nation_data, self.game.map_data), before)

    def test_confirmation_escape_cancels_deletion(self):
        with mock.patch.object(modal_stack, "_stack", []):
            spectator_menus.spec_delete_country(self.game)
            modal_stack.active().handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)])
            modal_stack.active().update()
            self.assertTrue(modal_stack.is_empty())
            self.assertIn("Source", self.game.nation_data)

    def test_confirmation_delete_button_applies_removal(self):
        self.game.selected_province = self.game.map_data["2"]
        with mock.patch.object(modal_stack, "_stack", []):
            spectator_menus.spec_delete_country(self.game)
            modal = modal_stack.active()
            modal.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                                    pos=modal.yes_rect.center, button=1)])
            self.assertIn("Target", self.game.nation_data)
            modal.update()
            self.assertTrue(modal_stack.is_empty())
            self.assertNotIn("Target", self.game.nation_data)


class SpectatorRemovalButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.game = app_harness.boot_map()

    def setUp(self):
        from screens.menu_screens import map as map_module
        self.map_module = map_module
        self.addCleanup(map_module.update_button_states, self.game)
        selected = next(p for p in self.game.map_data.values()
                        if queries.is_playable(p.get("owner"), self.game.nation_data))
        fields = dict(player_country="Spectator", selected_province=selected,
                      selection_mode=False, is_editor=False, tactical_mode=False,
                      ai_is_thinking=False, viewing_ai_moves=False,
                      multiplayer_mode=False, realtime_multiplayer=False,
                      is_saving=False, is_refreshing=False,
                      realtime_session=SimpleNamespace(phase="TURN", players={}), realtime_player_id="spectator",
                      _realtime_submit=mock.Mock(), _realtime_unsubmit=mock.Mock())
        for field, value in fields.items():
            self.enterContext(mock.patch.object(self.game, field, value, create=True))

    def test_local_spectator_buttons_are_available_and_call_the_handlers(self):
        self.map_module.update_button_states(self.game)
        for button, handler in ((self.game.btn_spec_annex, "spec_annex_country"),
                                (self.game.btn_spec_delete, "spec_delete_country")):
            self.assertTrue(button.visible)
            self.assertFalse(button.disabled)
            with mock.patch.object(spectator_menus, handler) as action:
                button.callback()
            action.assert_called_once_with(self.game)

    def test_buttons_are_hidden_outside_local_spectator_planning(self):
        for flag in ("multiplayer_mode", "realtime_multiplayer", "tactical_mode", "ai_is_thinking"):
            with mock.patch.object(self.game, flag, True):
                self.map_module.update_button_states(self.game)
                self.assertFalse(self.game.btn_spec_annex.visible)
                self.assertFalse(self.game.btn_spec_delete.visible)


if __name__ == "__main__":
    unittest.main()
