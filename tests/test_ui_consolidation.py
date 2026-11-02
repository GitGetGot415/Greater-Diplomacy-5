"""Behavior of the shared menu lists, lobby, editor windows, and text fields."""

import os
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


def save_browser():
    from screens.menus.load_game import Load_Game
    from ui.widgets.content_browser import ContentEntry

    screen = Load_Game()
    entry = ContentEntry("Save", os.path.join(screen.managed_dir, "Save"), 0, "Fixture date")
    screen.entries = [entry]
    screen.summary_cache = {entry.path: {"details": [], "error": ""}}
    screen.refresh_ui()
    return screen


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
        from ui.navigation.screen import keyboard_input_is_captured

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
        from ui.navigation.screen import keyboard_input_is_captured

        map_screen = mock.Mock(player_country="Editor", nation_data={"Alpha": {}}, army_editor_state=None)
        screen = Starting_Economy_Edit_Screen(map_screen, "Alpha")
        self.assertFalse(keyboard_input_is_captured(screen))
        next(iter(screen.fields.values())).active = True
        self.assertTrue(keyboard_input_is_captured(screen))

    def test_nation_list_edit_opens_its_edit_screen(self):
        from screens.editors.date_economy_screens import Starting_Economy_Edit_Screen, Starting_Economy_List_Screen

        map_screen = mock.Mock(player_country="Editor", map_data={}, nation_data={"Alpha": {}})
        with mock.patch("ui.navigation.screen.queries.get_living_nations", return_value=["Alpha"]):
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


class FolderRowTests(SharedUiTestCase):
    def test_save_selection_and_actions_use_the_selected_folder(self):
        screen = save_browser()
        with mock.patch.object(screen, "load_specific_save") as load:
            button_named(screen, "Save").callback()
        load.assert_not_called()
        for label, handler in (("Load Game", "load_specific_save"), ("History", "open_history_menu"),
                               ("Rename", "start_rename"), ("Export", "export_save_zip"), ("Delete…", "start_delete")):
            with self.subTest(label=label), mock.patch.object(screen, handler) as called:
                button_named(screen, label).callback()
                called.assert_called_once_with("Save")

    def history_click_sounds(self, turn_dates):
        """Every sound one click on History makes, including the button's own."""
        from screens.menus import load_game
        from ui.widgets import ui_elements

        screen = save_browser()
        button = button_named(screen, "History")
        with mock.patch.object(load_game.history_io, "read_turn_dates", return_value=turn_dates), \
                mock.patch.object(load_game.pickers, "open_listbox_selector"), \
                mock.patch.object(ui_elements, "play_ui_sound") as sound, \
                mock.patch.object(load_game, "play_ui_sound", sound), \
                mock.patch("pygame.mouse.get_pos", return_value=button.rect.center):
            button.handle_event(click(button.rect.center))
            button.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=button.rect.center))
        from ui.navigation import modal_stack
        if turn_dates == {}:
            modal_stack.pop()
        return [call.args[0] for call in sound.call_args_list]

    def test_history_with_nothing_to_show_plays_only_the_info_sound(self):
        self.assertEqual(self.history_click_sounds({}), ["info"])

    def test_history_with_turns_plays_only_time_select(self):
        self.assertEqual(self.history_click_sounds({"1": "January 1900"}), ["time_select"])


class ButtonMenuPageTests(SharedUiTestCase):
    def test_new_game_category_page_routes_each_button(self):
        from screens.setup.new_game import New_Game

        screen = New_Game()
        screen.draw(self.surface)
        button_named(screen, "Alternate Scenarios").callback()
        self.assertEqual(screen.sub_state, "ALTERNATE")
        screen.draw(self.surface)

    def test_map_browser_tab_opens_a_category(self):
        from screens.setup.select_base_map import Select_Base_Map

        screen = Select_Base_Map()
        button_named(screen, "Historical Scenarios").callback()
        self.assertEqual(screen.sub_state, "OTHER_HISTORICAL")


class ResearchDetailsTests(SharedUiTestCase):
    def open_details(self):
        from screens.game.research import Research_Screen

        game = app_harness.boot_map()
        research = Research_Screen()
        research.start_research(game)
        tech = next(iter(research.tech_tree))
        node = {"status": "AVAILABLE", "tech_key": tech, "level": 1, "icon": None, "cost": 100,
                "display_name": research.get_display_name(tech, 1)}
        with mock.patch("screens.game.research._run_pygame_sub_screen") as run:
            research.open_modal(node)
        return research, research.details_screen, run

    def test_details_open_as_a_sub_screen_and_reset_when_closed(self):
        research, details, run = self.open_details()
        self.assertIs(run.call_args.args[1], details)
        details.draw(self.surface)
        run.call_args.kwargs["on_done"]()
        self.assertIsNone(research.details_screen)
        self.assertTrue(research.elements)

    def test_back_key_closes_only_the_details(self):
        research, details, _run = self.open_details()
        details.handle_back_key()
        self.assertTrue(details.done)
        self.assertFalse(research.done)

    def test_start_action_calls_research_then_closes(self):
        research, details, _run = self.open_details()
        with mock.patch.object(research, "start_or_resume_research") as start:
            details.start_research()
        start.assert_called_once_with(details.node["tech_key"])
        self.assertTrue(details.done)

    def test_drawing_does_not_run_the_research_forecast(self):
        from data import queries

        _research, details, _run = self.open_details()
        with mock.patch.object(queries, "get_research_multiplier", side_effect=AssertionError("frame rules")):
            details.draw(self.surface)


class MatchDetailsTests(SharedUiTestCase):
    @staticmethod
    def player(name, connected=True):
        return SimpleNamespace(player_id=name, name=name, country_id=None, eliminated=False, submitted=False,
                               connected=connected, ping_ms=5)

    def map_screen(self, session):
        map_screen = mock.Mock(realtime_session=session, nation_data={})
        map_screen.map_screen = None
        return map_screen

    def test_rows_follow_the_session_and_keep_the_chosen_sort(self):
        from ui.panels.realtime_status_panel import _MatchDetails

        session = SimpleNamespace(host_id="Host", players={"a": self.player("Bravo"), "b": self.player("Alpha")})
        screen = _MatchDetails(self.map_screen(session))
        screen.sort_by(screen.columns[0])
        self.assertEqual([row["player"] for row in screen.rows], ["Alpha", "Bravo"])

        session.players["c"] = self.player("Aaron", connected=False)
        screen.update()
        self.assertEqual([row["player"] for row in screen.rows], ["Aaron", "Alpha", "Bravo"])
        self.assertEqual(screen.rows[0]["connection"], "Disconnected")
        screen.draw(self.surface)

    def test_no_session_shows_an_empty_table(self):
        from ui.panels.realtime_status_panel import _MatchDetails

        screen = _MatchDetails(self.map_screen(None))
        self.assertEqual(screen.rows, [])
        screen.update()
        screen.draw(self.surface)


class BackKeySoundTests(SharedUiTestCase):
    """The back key sounds like a Back button when it goes back, and only then."""

    def back_sounds(self, screen):
        from ui.navigation import screen as screen_module
        from ui.widgets import ui_elements

        with mock.patch.object(ui_elements, "play_ui_sound") as sound, \
                mock.patch.object(screen_module, "play_ui_sound", sound), \
                mock.patch("ui.navigation.screen.queries.get_keybind",
                           side_effect=lambda _action, default: default):
            screen_module.dispatch_global_keys(screen, key(pygame.K_ESCAPE))
        return [call.args[0] for call in sound.call_args_list]

    def test_leaving_an_ordinary_screen_plays_back_once(self):
        from ui.navigation.screen import Screen

        screen = Screen()
        self.assertEqual(self.back_sounds(screen), ["back"])
        self.assertTrue(screen.done)

    def test_stepping_back_inside_a_screen_plays_back_once(self):
        from screens.setup import new_game

        screen = new_game.New_Game()
        screen.set_sub_state("HISTORICAL")
        with mock.patch.object(new_game, "play_ui_sound") as sound:
            screen.handle_back_key()
        sound.assert_called_once_with("back")
        self.assertEqual(screen.sub_state, "CATEGORY")
        self.assertFalse(screen.done)

    def test_leaving_a_text_box_is_silent(self):
        from screens.game.declare_independence import Declare_Independence_Screen

        screen = Declare_Independence_Screen(mock.Mock(player_country="Alpha", player_unit=None, map_data={},
                                                       nation_data={}, top_bar_rect=None))
        screen.name_field.active = True
        self.assertEqual(self.back_sounds(screen), [])
        self.assertFalse(screen.done)
        self.assertEqual(self.back_sounds(screen), ["back"])
        self.assertTrue(screen.done)

    def test_keybind_capture_and_the_main_menu_are_silent(self):
        from screens.menus.keybinds import Keybinds
        from screens.menus.menu import Menu

        screen = object.__new__(Keybinds)
        screen.done = False
        screen.listening_for = "BACK"
        screen.handle_back_key()
        self.assertFalse(screen.done)
        menu = object.__new__(Menu)
        with mock.patch.object(Menu, "exit_screen") as leave, mock.patch("ui.navigation.screen.play_ui_sound") as sound:
            menu.handle_back_key()
        leave.assert_called_once()
        sound.assert_not_called()

    def test_map_only_sounds_when_it_closes_something(self):
        from screens.game.map import Map
        from ui.panels import army_panel
        from ui.widgets import ui_elements

        game = mock.Mock(selected_province=None)
        with mock.patch.object(army_panel, "handle_back_key", return_value=False), \
                mock.patch.object(ui_elements, "play_ui_sound") as sound:
            Map.handle_back_key(game)
            sound.assert_not_called()
            game.selected_province = {"id": 1}
            Map.handle_back_key(game)
            sound.assert_called_once_with("back")
        game.deselect_province.assert_called_once()

    def test_go_back_option_on_a_three_way_popup_plays_back_from_the_keyboard(self):
        from ui import dialogs
        from ui.navigation import modal_stack
        from ui.widgets import ui_elements

        answers = []
        dialogs.ask_yes_no("T", "Body.", answers.append, back_label="Go back")
        modal = modal_stack.active()
        with mock.patch.object(ui_elements, "play_ui_sound") as sound:
            modal.handle_events([key(pygame.K_ESCAPE)])
        sound.assert_called_once_with("back")
        modal_stack.pop()


class OneSoundPerClickTests(SharedUiTestCase):
    def tearDown(self):
        from ui.navigation import modal_stack
        while not modal_stack.is_empty():
            modal_stack.pop()

    def click_sounds(self, button, *modules):
        """Every sound one click on `button` makes, wherever it is played from."""
        from ui.widgets import ui_elements

        with mock.patch.object(ui_elements, "play_ui_sound") as sound:
            patches = [mock.patch.object(module, "play_ui_sound", sound) for module in modules]
            for patch in patches:
                patch.start()
            try:
                with mock.patch("pygame.mouse.get_pos", return_value=button.rect.center):
                    button.handle_event(click(button.rect.center))
                    button.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=button.rect.center))
            finally:
                for patch in patches:
                    patch.stop()
        return [call.args[0] for call in sound.call_args_list]

    def test_tournament_help_plays_only_info(self):
        from screens.multiplayer.multiplayer_hub import Multiplayer_Hub

        self.assertEqual(self.click_sounds(button_named(Multiplayer_Hub(), "Help")), ["info"])

    def test_guest_lobby_popup_buttons_play_only_info(self):
        lobby = LobbyTests().guest_lobby()
        lobby.reconnect_token = "code"
        for label in ("Match Rules", "Copy Reconnect Code"):
            with self.subTest(label=label), mock.patch("ui.dialogs.pickers.copy_to_clipboard", return_value=True):
                self.assertEqual(self.click_sounds(button_named(lobby, label)), ["info"])

    def test_host_lobby_popup_buttons_play_only_info(self):
        from screens.multiplayer.realtime_multiplayer import Realtime_Lobby

        screen = Realtime_Lobby()
        screen.server_map = SimpleNamespace(nation_data={})
        screen.session = mock.Mock(
            host_id="host", countries=[],
            config=SimpleNamespace(scenario_id="Scenario", max_players=2, max_turns=9, turn_minutes=3, port=1),
            players={"host": LobbyTests.player("Host", "host", None)})
        screen.lan_invite = "invite"
        screen.internet_button_color = lambda: "blue"
        screen.internet_button_label = lambda: "Internet Invite"
        screen.refresh_ui()
        for label in ("Copy LAN Invite", "Internet Invite", "Networking Status"):
            with self.subTest(label=label), mock.patch("ui.dialogs.pickers.copy_to_clipboard", return_value=True):
                self.assertEqual(self.click_sounds(button_named(screen, label)), ["info"])

    def test_networking_help_plays_only_info(self):
        from screens.multiplayer.realtime_multiplayer import Realtime_Host_Setup

        screen = Realtime_Host_Setup()
        self.assertEqual(self.click_sounds(button_named(screen, "Networking Help")), ["info"])

    def load_game_row(self, label):
        screen = save_browser()
        return screen, button_named(screen, label)

    def test_save_row_clicks_when_it_loads_and_plays_info_when_refused(self):
        from screens.menus import load_game

        screen, row = self.load_game_row("Load Game")
        with mock.patch.object(load_game, "newer_version_message", return_value="Update the game."):
            self.assertEqual(self.click_sounds(row, load_game), ["info"])
        self.assertFalse(screen.done)
        with mock.patch.object(load_game, "newer_version_message", return_value=None):
            self.assertEqual(self.click_sounds(row, load_game), ["click"])
        self.assertTrue(screen.done)

    def test_history_refuses_a_newer_save_before_its_turn_list(self):
        from screens.menus import load_game

        _screen, row = self.load_game_row("History")
        with mock.patch.object(load_game, "newer_version_message", return_value="Update the game."), \
                mock.patch.object(load_game.pickers, "open_listbox_selector") as picker:
            self.assertEqual(self.click_sounds(row, load_game), ["info"])
        picker.assert_not_called()

    def test_a_turn_from_the_history_list_does_not_click_a_second_time(self):
        from screens.menus import load_game

        screen, _row = self.load_game_row("History")
        with mock.patch.object(load_game, "newer_version_message", return_value=None), \
                mock.patch.object(load_game, "play_ui_sound") as sound:
            screen.load_specific_save("Save", history_turn=3)
        sound.assert_not_called()

    def test_add_country_clicks_for_its_list_and_plays_info_when_there_is_none(self):
        from screens.editors import historical_leaders_editor as editor

        screen = editor.Historical_Leaders_Editor()
        button = button_named(screen, "+ Add Country")
        data = {"Alpha": {"is_playable": True, "name": "Alpha Republic"}}
        with mock.patch.object(editor.queries, "get_country_data", return_value=data):
            screen.data = {}
            with mock.patch.object(editor.pickers, "open_listbox_selector") as picker:
                self.assertEqual(self.click_sounds(button), ["click"])
            picker.assert_called_once()
            self.assertEqual(picker.call_args.args[3], [("Alpha Republic", "Alpha")])
            screen.data = {"Alpha": []}
            self.assertEqual(self.click_sounds(button), ["info"])

    def test_removing_a_tracked_country_works_without_a_map(self):
        from screens.editors import historical_leaders_editor as editor

        screen = editor.Historical_Leaders_Editor()
        self.assertIsNone(screen.map_screen)
        screen.data = {"Alpha": []}
        data = {"Alpha": {"is_playable": True, "name": "Alpha Republic"}}
        with mock.patch.object(editor.queries, "get_country_data", return_value=data), \
                mock.patch.object(editor.dialogs, "ask_yes_no") as ask:
            screen.remove_country("Alpha")
        self.assertIn("Alpha Republic", ask.call_args.args[1])

    def test_data_refresh_confirm_clicks_only_when_maps_were_found(self):
        from screens.setup import new_game

        screen = new_game.New_Game()
        with mock.patch.object(new_game.pickers, "open_checkbox_list") as picker:
            screen.trigger_global_data_refresh()
        self.assertIsNone(picker.call_args.kwargs["confirm_sound"])
        on_picked = picker.call_args.args[4]
        for started, expected in ((True, ["click"]), (False, [])):
            with self.subTest(started=started), \
                    mock.patch.object(new_game.map_refresh, "refresh_map_directories", return_value=started), \
                    mock.patch.object(new_game, "play_ui_sound") as sound:
                on_picked([])
                self.assertEqual([call.args[0] for call in sound.call_args_list], expected)

    def test_checkbox_lists_click_on_confirm_by_default(self):
        from ui.dialogs.checkbox_list_screen import CheckboxListScreen

        screen = CheckboxListScreen(self.controller, "T", "P", [], lambda _keys: None)
        self.assertEqual(self.click_sounds(button_named(screen, "Confirm")), ["click"])

    def test_token_page_clicks_unless_the_browser_fails(self):
        from screens.multiplayer import realtime_multiplayer as realtime
        from ui.widgets import ui_elements

        screen = object.__new__(realtime.Realtime_Relay_Setup)
        with mock.patch.object(realtime, "IS_WEB", False), \
                mock.patch.object(realtime, "play_ui_sound") as sound, \
                mock.patch.object(ui_elements, "play_ui_sound", sound):
            with mock.patch.object(realtime.webbrowser, "open"):
                screen.open_token_page()
            sound.assert_called_once_with("click")
            sound.reset_mock()
            with mock.patch.object(realtime.webbrowser, "open", side_effect=OSError):
                screen.open_token_page()
            sound.assert_called_once_with("info")

    def test_realtime_details_plays_only_the_table_sound(self):
        game = app_harness.boot_map()
        button = game.btn_realtime_details
        # It is hidden outside a real-time match.
        with mock.patch.object(game, "realtime_session", None), mock.patch.object(button, "visible", True), \
                mock.patch.object(button, "disabled", False):
            self.assertEqual(self.click_sounds(button), ["table"])


class KeybindSoundTests(SharedUiTestCase):
    def test_orders_and_production_keys_play_the_view_button_sound_once(self):
        from screens.game import map_input
        from ui.widgets import ui_elements

        for mode, action in (("UNITS", "ORDERS"), ("ECONOMY", "ECONOMY")):
            with self.subTest(action=action), mock.patch.object(ui_elements, "play_ui_sound") as sound, \
                    mock.patch.object(map_input.queries, "get_keybind_changes_screen", return_value=False):
                map_screen = mock.Mock()
                map_input.handle_view_mode_keybind(map_screen, mode, action)
                sound.assert_called_once_with("select_view")
                map_screen.set_view_mode.assert_called_once_with(mode)

    def orders_screen(self):
        from screens.game.orders import Orders_Screen

        screen = object.__new__(Orders_Screen)
        screen.renaming_unit_index = None
        screen.read_only = False
        screen.map_screen = mock.Mock(tactical_mode=False)
        return screen

    def test_clear_orders_key_plays_the_cancel_sound_even_with_nothing_to_clear(self):
        from ui.widgets import ui_elements

        screen = self.orders_screen()
        with mock.patch.object(type(screen), "clear_all_orders", return_value=False), \
                mock.patch.object(ui_elements, "play_ui_sound") as sound:
            screen.handle_clear_orders_key()
        sound.assert_called_once_with("cancel_orders")

    def test_clear_orders_key_does_not_repeat_a_sound_already_played(self):
        from ui.widgets import ui_elements

        screen = self.orders_screen()
        with mock.patch.object(type(screen), "clear_all_orders", return_value=True), \
                mock.patch.object(ui_elements, "play_ui_sound") as sound:
            screen.handle_clear_orders_key()
        sound.assert_not_called()

    def test_clear_orders_key_is_silent_where_it_is_unavailable(self):
        from ui.widgets import ui_elements

        screen = self.orders_screen()
        screen.read_only = True
        with mock.patch.object(type(screen), "clear_all_orders") as clear, \
                mock.patch.object(ui_elements, "play_ui_sound") as sound:
            screen.handle_clear_orders_key()
        clear.assert_not_called()
        sound.assert_not_called()


class ChoiceButtonTests(SharedUiTestCase):
    def test_selection_and_availability_are_reported(self):
        from ui.widgets.ui_elements import make_choice_button

        callback = mock.Mock()
        chosen = make_choice_button(0, 0, "medium", "A", True, callback)
        self.assertTrue(chosen.is_selected)
        self.assertFalse(chosen.disabled)
        chosen.callback()
        callback.assert_called_once()
        self.assertTrue(make_choice_button(0, 0, "medium", "B", False, callback, enabled=False).disabled)


if __name__ == "__main__":
    unittest.main()
