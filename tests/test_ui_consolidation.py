"""Behavior of the shared menu lists, lobby, editor windows, and text fields."""

import unittest
from types import SimpleNamespace
from unittest import mock

import pygame

from tests import app_harness


def key(code, text=""):
    return pygame.event.Event(pygame.KEYDOWN, key=code, unicode=text, mod=0)


def click(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)


def button_named(screen, text):
    return next(el for el in screen.elements if getattr(el, "text", None) == text)


class SharedUiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()


class TextFieldTests(SharedUiTestCase):
    def test_on_change_receives_each_edit_and_not_unchanged_keys(self):
        from ui.widgets.ui_elements import TextField

        changes = []
        field = TextField(0, 0, 100, 30, "a", on_change=changes.append)
        field.active = True
        field.handle_event(key(pygame.K_b, "b"))
        field.handle_event(key(pygame.K_LSHIFT))
        field.handle_event(key(pygame.K_BACKSPACE))
        self.assertEqual(changes, ["ab", "a"])


class MenuListTests(SharedUiTestCase):
    def test_category_page_has_no_list_input(self):
        from screens.setup.new_game import New_Game

        screen = New_Game()
        with mock.patch.object(screen, "handle_list_scroll") as scroll:
            screen.additional_events(click((0, 0)))
            scroll.assert_not_called()
            screen.set_sub_state("HISTORICAL")
            screen.additional_events(click((0, 0)))
            scroll.assert_called_once()

    def test_refresh_hides_buttons_and_ignores_input(self):
        from screens.setup.new_game import New_Game
        from screens.setup.select_base_map import Select_Base_Map

        for screen_type in (New_Game, Select_Base_Map):
            with self.subTest(screen=screen_type.__name__):
                screen = screen_type()
                screen.is_refreshing = True
                screen.update()
                self.assertTrue(screen.elements)
                self.assertFalse(any(el.visible for el in screen.elements))
                with mock.patch.object(screen, "additional_events") as events:
                    screen.handle_events([click((0, 0))])
                    events.assert_not_called()
                screen.draw(self.surface)
                screen.is_refreshing = False
                screen.update()
                self.assertTrue(all(el.visible for el in screen.elements))

    def test_every_picker_builds_rows_that_report_their_value(self):
        from screens.multiplayer.realtime_multiplayer import Realtime_Scenario_Select

        screen = Realtime_Scenario_Select()
        picked = []
        screen.elements = []
        screen.add_menu_list([("Label", "value")], picked.append)
        screen.elements[0].callback()
        self.assertEqual(picked, ["value"])
        screen.draw(self.surface)


class LobbyTests(SharedUiTestCase):
    @staticmethod
    def player(name, player_id, country_id, ready=False):
        return SimpleNamespace(name=name, player_id=player_id, country_id=country_id, ready=ready,
                               connected=True, ping_ms=5)

    def guest_lobby(self):
        from screens.multiplayer.realtime_multiplayer import Realtime_Remote_Lobby

        screen = Realtime_Remote_Lobby()
        screen.client = mock.Mock(map_bundle={})
        screen.view = SimpleNamespace(
            player_id="guest", host_id="host", config=SimpleNamespace(),
            available_countries=["Alpha", "Beta"],
            players={"guest": self.player("Guest", "guest", "Alpha"),
                     "host": self.player("Host", "host", "Beta", ready=True)})
        screen.refresh_ui()
        return screen

    def test_guest_lobby_draws_when_a_player_has_a_country(self):
        # The guest lobby called a helper that only the join screen defined.
        self.guest_lobby().draw(self.surface)

    def test_guest_rows_and_ready_only_send_requests(self):
        screen = self.guest_lobby()
        button_named(screen, "Beta: Host").callback()
        screen.client.send.assert_called_once_with("select_country", {"country_id": "Beta"})
        screen.client.send.reset_mock()
        button_named(screen, "Mark Ready").callback()
        screen.client.send.assert_called_once_with("ready", {"ready": True})

    def test_host_rows_change_the_session_directly(self):
        from screens.multiplayer.realtime_multiplayer import Realtime_Lobby

        screen = Realtime_Lobby()
        screen.server_map = SimpleNamespace(nation_data={})
        screen.session = mock.Mock(
            host_id="host", countries=["Alpha"], config=SimpleNamespace(scenario_id="Scenario", max_players=2,
                                                                        max_turns=9, turn_minutes=3),
            players={"host": self.player("Host", "host", None)})
        screen.internet_button_color = lambda: "blue"
        screen.internet_button_label = lambda: "Internet"
        screen.refresh_ui()
        button_named(screen, "Alpha: Available").callback()
        screen.session.select_country.assert_called_once_with("host", "Alpha")
        self.assertTrue(any(getattr(el, "text", "") == "Mark Host Ready" for el in screen.elements))
        screen.draw(self.surface)


class EditCountryFieldTests(SharedUiTestCase):
    def test_typing_reaches_the_clicked_field_and_captures_the_keyboard(self):
        from screens.editors.edit_country import Edit_Country_Screen
        from ui.navigation.game_state import keyboard_input_is_captured

        screen = Edit_Country_Screen()
        screen.elements = list(screen.fields.values())
        screen.adjective = "Old"
        self.assertFalse(keyboard_input_is_captured(screen))
        screen.handle_events([click(screen.fields["ADJECTIVE"].rect.center)])
        self.assertTrue(keyboard_input_is_captured(screen))
        screen.handle_events([key(pygame.K_x, "x")])
        self.assertEqual(screen.adjective, "Oldx")
        self.assertEqual(screen.country_name, "")

    def test_undo_shortcut_does_not_type_into_the_focused_field(self):
        from screens.editors.edit_country import Edit_Country_Screen

        screen = Edit_Country_Screen()
        screen.elements = list(screen.fields.values())
        screen.fields["NAME"].active = True
        with mock.patch.object(screen, "undo") as undo, \
                mock.patch("pygame.key.get_mods", return_value=pygame.KMOD_CTRL):
            screen.handle_events([key(pygame.K_z, "z")])
        undo.assert_called_once()
        self.assertEqual(screen.leader_name, "")


class DeclareIndependenceFieldTests(SharedUiTestCase):
    def screen(self):
        from screens.game.declare_independence import Declare_Independence_Screen

        map_screen = mock.Mock(player_country="Alpha", player_unit=None, map_data={},
                               nation_data={"Core": {"name": "Coreland"}}, top_bar_rect=None)
        return Declare_Independence_Screen(map_screen)

    def test_back_key_leaves_the_name_box_before_the_screen(self):
        screen = self.screen()
        screen.name_field.active = True
        screen.handle_back_key()
        self.assertFalse(screen.name_field.active)
        self.assertFalse(screen.done)
        screen.handle_back_key()
        self.assertTrue(screen.done)

    def test_choosing_a_core_renames_and_enter_confirms(self):
        screen = self.screen()
        screen.select_core("Core")
        self.assertEqual(screen.name_field.text, "Free Coreland")
        screen.name_field.active = True
        with mock.patch.object(screen.name_field, "on_submit") as submit:
            screen.name_field.handle_event(key(pygame.K_RETURN))
        submit.assert_called_once()


class EditorWindowTests(SharedUiTestCase):
    def test_date_form_writes_its_fields(self):
        from screens.editors.date_economy_screens import Editor_Date_Screen

        time_manager = SimpleNamespace(day=1, month_index=0, year=1900)
        map_screen = mock.Mock(player_country="Editor", time_manager=time_manager, scenario_settings={})
        screen = Editor_Date_Screen(map_screen)
        self.assertEqual(len(screen.fields), 4)
        for name, text in (("day", "9"), ("month", "3"), ("year", "1941"), ("days_per_turn", "7")):
            screen.fields[name].text = text
        with mock.patch("screens.editors.date_economy_screens.queries.save_scenario_settings"), \
                mock.patch("screens.editors.date_economy_screens.queries.get_scenario_flag", return_value=False):
            button_named(screen, "Apply Date").callback()
        self.assertEqual((time_manager.day, time_manager.month_index, time_manager.year), (9, 2, 1941))
        self.assertEqual(map_screen.scenario_settings["base_days_per_turn"], 7)
        self.assertTrue(screen.done)

    def test_form_field_focus_captures_the_keyboard(self):
        from screens.editors.date_economy_screens import Starting_Economy_Edit_Screen
        from ui.navigation.game_state import keyboard_input_is_captured

        map_screen = mock.Mock(player_country="Editor", nation_data={"Alpha": {}}, army_editor_state=None)
        screen = Starting_Economy_Edit_Screen(map_screen, "Alpha")
        self.assertFalse(keyboard_input_is_captured(screen))
        next(iter(screen.fields.values())).active = True
        self.assertTrue(keyboard_input_is_captured(screen))

    def test_nation_list_edit_opens_its_edit_screen(self):
        from screens.editors.date_economy_screens import Starting_Economy_Edit_Screen, Starting_Economy_List_Screen

        map_screen = mock.Mock(player_country="Editor", map_data={}, nation_data={"Alpha": {}})
        with mock.patch("ui.navigation.game_state.queries.get_living_nations", return_value=["Alpha"]):
            screen = Starting_Economy_List_Screen(map_screen)
        with mock.patch("ui.navigation.screen_runner._run_pygame_sub_screen") as run:
            screen.edit("Alpha")
        opened = run.call_args.args[1]
        self.assertIsInstance(opened, Starting_Economy_Edit_Screen)
        self.assertEqual(opened.country_id, "Alpha")
        self.assertEqual(run.call_args.kwargs["on_done"], screen.refresh_ui)

    def test_attribute_picker_stores_the_value_and_rebuilds(self):
        from ui.dialogs import pickers

        screen = mock.Mock()
        with mock.patch.object(pickers, "open_listbox_selector") as selector:
            pickers.open_attribute_picker(screen, "selected_country", "Title", "Prompt", ["Alpha"])
        selector.call_args.args[4]("Alpha")
        self.assertEqual(screen.selected_country, "Alpha")
        screen.refresh_ui.assert_called_once()


class ToggleAndFooterTests(SharedUiTestCase):
    def test_toggle_button_reports_its_state_and_callback(self):
        from ui.widgets.ui_elements import make_toggle_button

        callback = mock.Mock()
        button = make_toggle_button(0, 0, "medium", "Fog", True, callback)
        self.assertEqual(button.text, "Fog: ON")
        self.assertEqual(make_toggle_button(0, 0, "medium", "Fog", False, callback).text, "Fog: OFF")
        button.callback()
        callback.assert_called_once()

    def test_checkbox_list_confirm_and_cancel_keep_their_results(self):
        from ui.dialogs.checkbox_list_screen import CheckboxItem, CheckboxListScreen

        results = []
        screen = CheckboxListScreen(self.controller, "Pick", "Prompt", [CheckboxItem("a", "A", checked=True)],
                                    results.append)
        button_named(screen, "Cancel").callback()
        self.assertEqual(results, [])
        button_named(screen, "Confirm").callback()
        self.assertEqual(results, [["a"]])


if __name__ == "__main__":
    unittest.main()
