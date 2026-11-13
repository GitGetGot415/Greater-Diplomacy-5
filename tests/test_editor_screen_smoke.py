"""Builds and paints the modal tool windows that live outside Controller.states.

The editors, pickers and dialogs in ui/ are pushed onto the modal stack from a
button rather than being constructed up front, so test_screen_smoke never sees
them -- and they hold most of the panel chrome and multi-pane scroll code this
refactor touches. Each is built against the real 1939 map and put through
refresh_ui, a draw and a wheel notch.
"""

import unittest
from unittest import mock

import pygame

from tests import app_harness


def wheel(y):
    return pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=y, flipped=False,
                              precise_x=0.0, precise_y=float(y))


class EditorScreenSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()

    def setUp(self):
        self.surface.fill((0, 0, 0))

    def exercise(self, screen):
        screen.refresh_ui()
        screen.draw(self.surface)
        screen.handle_events([wheel(-1), wheel(1)])
        screen.draw(self.surface)

    # -- screens/editors/scripted_events_editor.py -----------------

    def test_scripted_events_editor(self):
        from screens.editors import scripted_events_editor as se
        self.exercise(se.Scripted_Events_Editor_Screen(self.map))

    def test_scripted_events_help(self):
        from screens.editors import scripted_events_editor as se
        self.exercise(se._HelpScreen(self.map))

    def test_scripted_events_variables(self):
        from screens.editors import scripted_events_editor as se
        screen = se._VariablesScreen(self.map, self.map)
        self.exercise(screen)
        with mock.patch("ui.dialogs.show_info") as show_info:
            screen.show_help()
        self.assertEqual(show_info.call_args.kwargs["align"], "left")

    def test_message_popup_accepts_an_alignment_and_defaults_to_center(self):
        from ui.dialogs.message_box import _MessageModal
        modal = _MessageModal(self.surface, "Help", "Short", "info", align="left")
        self.assertEqual(modal.BODY_ALIGN, "left")
        self.assertEqual(_MessageModal(self.surface, "Help", "Short", "info").BODY_ALIGN, "center")
        modal.draw(self.surface)

    def test_scripted_events_global_rules_add_and_delete(self):
        from screens.editors import scripted_events_editor as se
        from map_logic.diplomacy import global_rules
        saved_rules = self.map.global_rules
        self.map.global_rules = []
        try:
            screen = se._GlobalRulesScreen(self.map, self.map)
            first, second = (country for _label, country in screen.country_items[:2])
            screen.country, screen.rule_type, screen.target = first, global_rules.MAKE_PEACE, second
            screen.strength = global_rules.WEAK
            screen.bypass_scripted_events = False
            with mock.patch("ui.dialogs.show_error") as show_error:
                screen.add_rule()
                screen.country, screen.target = second, first  # The same mutual rule, reversed.
                screen.add_rule()
            show_error.assert_called_once()
            self.assertEqual(self.map.global_rules,
                             [{"country": first, "rule": global_rules.MAKE_PEACE, "target": second,
                               "strength": global_rules.WEAK, "bypass_scripted_events": False}])
            self.exercise(screen)
            with mock.patch("ui.dialogs.show_info") as show_info:
                screen.show_help()
            self.assertEqual(show_info.call_args.kwargs["align"], "left")
            screen.select(0)
            screen.delete_rule()
            self.assertEqual(self.map.global_rules, [])
        finally:
            self.map.global_rules = saved_rules

    def test_scripted_events_event_edit(self):
        from screens.editors import scripted_events_editor as se
        target = self.map.player_country
        self.exercise(se._EventEditScreen(self.map, self.map, target))

    # -- screens/editors/ (date_economy/research/brush/diplomacy) --

    def test_map_editor_screens(self):
        from screens import editors as editor_screens
        for name in ("Editor_Date_Screen", "Starting_Economy_List_Screen",
                     "Research_List_Screen", "Resource_Brush_Screen",
                     "Clear_Map_Screen", "Diplomacy_Editor_Screen",
                     "Personality_List_Screen", "Politics_List_Screen",
                     "Editor_Metadata_Screen", "Bulk_Edit_Screen"):
            with self.subTest(screen=name):
                self.exercise(getattr(editor_screens, name)(self.map))

    def test_standalone_export_screen_and_menu_previews(self):
        import base64
        import io
        from data import queries
        from screens.editors.standalone_export import Standalone_Export_Screen, Standalone_Menu_Preview
        screen = Standalone_Export_Screen()
        screen.on_enter(self.controller, None)
        self.exercise(screen)
        # smoothscale refuses palette images, so the menu must convert an 8-bit PNG first.
        palette_png = io.BytesIO()
        pygame.image.save(pygame.Surface((3, 2), depth=8), palette_png, "palette.png")
        images = (queries.encode_rgba_to_b64(bytes([1, 2, 3, 255]) * 6, (3, 2)),
                  base64.b64encode(palette_png.getvalue()).decode("ascii"))
        fits = queries.STANDALONE_IMAGE_FITS
        for settings in ({}, {"background_color": [1, 2, 3]},
                         *({"background_image": image, "image_fit": fit, "image_smoothing": smoothing}
                           for image in images for fit in fits for smoothing in (True, False))):
            with self.subTest(settings=settings):
                preview = Standalone_Menu_Preview("Fixture Game", settings)
                preview.update()
                self.exercise(preview)

    def interesting_entries(self):
        from data import queries
        playable = queries.playable_start_countries(self.map.map_data, self.map.nation_data)
        return [{"country": country, "rank": rank, "description": "Fixture description " * 20}
                for country, rank in zip(playable, ("major", "major", "minor"))]

    def test_export_screen_lists_interesting_countries(self):
        from screens.editors.standalone_export import Standalone_Export_Screen, screen_runner
        entries = self.interesting_entries()
        with mock.patch.dict(self.map.standalone_export_settings, {"interesting_countries": entries}):
            screen = Standalone_Export_Screen()
            screen.on_enter(self.controller, None)
            self.exercise(screen)
            self.assertEqual([entry["rank"] for entry in screen.ordered_countries(screen.settings())],
                             ["major", "major", "minor"])
            with mock.patch.object(screen_runner, "run_screen") as run:
                next(button for button in screen.elements if getattr(button, "callback", None) == screen.preview).callback()
            preview = run.call_args.args[0]
            self.assertEqual(preview.settings, screen.settings())
            self.assertEqual(preview.entries, entries)
            self.assertIs(preview.controller, self.controller)

    def test_window_preview_redraws_only_when_the_background_changes(self):
        from screens.editors.standalone_export import Standalone_Export_Screen
        screen = Standalone_Export_Screen()
        screen.on_enter(self.controller, None)
        first = screen.window_preview_surface
        screen.refresh_ui()  # Scrolling rebuilds the screen the same way.
        self.assertIs(screen.window_preview_surface, first)
        with mock.patch.dict(self.map.standalone_export_settings, {"background_color": [9, 8, 7]}):
            screen.refresh_ui()
            self.assertIsNot(screen.window_preview_surface, first)
            self.exercise(screen)

    def test_standalone_menu_is_one_column_of_equal_buttons(self):
        import data.constants as c
        from screens.menus.menu import Menu
        menu = Menu("Fixture", {})
        column = [button for button in menu.elements if button is not getattr(menu, "exit_btn", None)]
        self.assertEqual([button.text for button in column],
                         ["New Game", "Load Game", "Settings", "Music", "Credits"])
        self.assertEqual(len({button.rect.size for button in column}), 1)
        self.assertEqual(len({button.rect.centerx for button in column}), 1)
        self.assertEqual([button.rect.y for button in column], sorted(button.rect.y for button in column))
        self.assertTrue(all(button.image is None for button in column))
        self.assertEqual(len({tuple(button.color) for button in column}), 1)
        # The button panel sits behind the whole column.
        self.assertTrue(all(menu.button_panel_rect.contains(button.rect) for button in column))
        # The menu shows no version text. The Credits screen names Greater Diplomacy 5 instead.
        self.assertEqual(menu.version_status, "")

    def test_standalone_credits_show_only_the_greater_diplomacy_credit(self):
        import data.constants as c
        from data.io import standalone_game
        from screens.menus import credits
        with mock.patch.object(standalone_game, "IS_STANDALONE", True):
            screen = credits.Credits()
            self.assertEqual(screen.credits_list, [])
            self.exercise(screen)
        self.assertEqual(standalone_game.made_with_text(), f"Made with Greater Diplomacy 5 ({c.GAME_VERSION})")
        self.assertTrue(credits.Credits().credits_list)

    def test_country_selector_panel_surrounds_the_title_and_country_buttons(self):
        from screens.setup import country_select
        screen = country_select.Country_Select_Screen()
        screen.show(self.map.nation_data, self.interesting_entries(), {})
        cards = [button for button in screen.elements if button.rect.top >= country_select.MAJOR_TOP
                 and button.text != "Select Country"]
        self.assertEqual(len(cards), len(screen.entries) + 1)  # Every country, then Other Countries.
        self.assertTrue(all(screen.panel_rect.contains(button.rect) for button in cards))
        self.assertLessEqual(screen.panel_rect.top, screen.title_y)
        self.exercise(screen)

    def test_standalone_new_game_opens_the_country_selector_for_more_than_one_country(self):
        from screens.menus.menu import Menu
        entries = self.interesting_entries()
        for listed, state in ((entries, "COUNTRY_SELECT"), (entries[:1], "MAP"), ([], "MAP")):
            with self.subTest(count=len(listed)):
                self.assertEqual(Menu("Fixture", {"interesting_countries": listed})._standalone_new_game_state(), state)

    def test_country_selector_starts_the_map_as_the_chosen_country(self):
        from data.platform import LoadingSteps
        from screens.setup import country_select
        screen = country_select.Country_Select_Screen()
        self.exercise(screen)  # Before on_enter it shows only Back.
        screen.nation_data = self.map.nation_data
        screen.entries = self.interesting_entries()
        screen.images = {entry["country"]: screen._images(entry["country"]) for entry in screen.entries}
        screen.selected = screen.entries[-1]["country"]
        self.exercise(screen)

        def loaded_map():
            yield "Loading..."
            return True

        for chosen in (screen.entries[0]["country"], None):
            with self.subTest(chosen=chosen), \
                    mock.patch.object(country_select.standalone_game, "scenario_path", return_value="fixture"), \
                    mock.patch.object(country_select.map_launch, "open_saved_map_steps",
                                      return_value=LoadingSteps(loaded_map(), 1)), \
                    mock.patch.object(country_select.player_setup, "start_as_country") as start:
                if chosen:
                    screen.select(chosen)
                    screen.start()
                else:
                    screen.choose_on_map()
                self.assertEqual(screen.next_state, "MAP")
                list(screen.prepare_map_steps(self.controller))
                if chosen:
                    start.assert_called_once_with(self.controller.states["MAP"], chosen)
                else:
                    start.assert_not_called()

    def make_game_preview(self, entries=None):
        from screens.editors.standalone_export import Standalone_Menu_Preview
        entries = self.interesting_entries() if entries is None else entries
        return Standalone_Menu_Preview("Fixture", {"interesting_countries": entries}, self.controller, self.map.nation_data, entries)

    def click_preview_button(self, preview, label):
        button = next(button for button in preview.current_screen.elements if getattr(button, "text", None) == label)
        position = button.rect.center
        with mock.patch("pygame.mouse.get_pos", return_value=position):
            preview.handle_events([
                pygame.event.Event(pygame.MOUSEMOTION, pos=position, rel=(0, 0), buttons=(0, 0, 0)),
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=position, button=1),
                pygame.event.Event(pygame.MOUSEBUTTONUP, pos=position, button=1)])
        preview.update()

    def test_game_preview_navigates_menu_screens_and_back_without_entering_the_game(self):
        from screens.menus.menu import MENU_BUTTON_TABLE, MENU_MAIN_BUTTON_TABLE, STANDALONE_MENU_STATES
        preview = self.make_game_preview()
        for state in STANDALONE_MENU_STATES:
            row = next(row for row in MENU_MAIN_BUTTON_TABLE + MENU_BUTTON_TABLE if row["state"] == state)
            self.click_preview_button(preview, getattr(preview.menu, row["attribute"]).text)
            self.assertEqual(preview.current_state, state)
            preview.draw(self.surface)
            preview.handle_back_key()
            self.assertEqual(preview.current_state, "MENU")
            self.assertFalse(preview.done)
        self.click_preview_button(preview, "New Game")
        self.assertEqual(preview.current_state, "COUNTRY_SELECT")
        selector = preview.current_screen
        minor = preview.entries[-1]["country"]
        self.click_preview_button(preview, selector.name(minor))
        self.assertEqual(selector.selected, minor)
        for label in ("Select Country", "Other Countries"):
            self.click_preview_button(preview, label)
            self.assertEqual(preview.current_state, "COUNTRY_SELECT")
        selector.start()
        selector.choose_on_map()
        self.assertFalse(selector.done)
        selector.go_to("MAP")  # A second boundary also refuses accidental gameplay navigation.
        preview.update()
        self.assertEqual(preview.current_state, "COUNTRY_SELECT")
        preview.handle_back_key()
        self.assertEqual(preview.current_state, "MENU")
        preview.handle_back_key()
        self.assertTrue(preview.done)

    def test_game_preview_always_opens_country_selection_and_closes_from_every_screen(self):
        from screens.editors.standalone_export import Standalone_Menu_Preview
        for entries in ([], self.interesting_entries()[:1]):
            preview = self.make_game_preview(entries)
            self.click_preview_button(preview, "New Game")
            self.assertEqual(preview.current_state, "COUNTRY_SELECT")
            self.assertEqual(preview.current_screen.entries, entries)
            for label in ("Select Country", "Other Countries"):
                self.click_preview_button(preview, label)
                self.assertEqual(preview.current_state, "COUNTRY_SELECT")
                self.assertFalse(preview.done)
        for state in Standalone_Menu_Preview.PREVIEW_STATES:
            preview = self.make_game_preview()
            preview.open_screen(state)
            position = preview.elements[0].rect.center
            with mock.patch("pygame.mouse.get_pos", return_value=position):
                preview.handle_events([
                    pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=position, button=1),
                    pygame.event.Event(pygame.MOUSEBUTTONUP, pos=position, button=1)])
            self.assertTrue(preview.done, state)

    def test_game_preview_settings_and_nested_controls_do_not_write_editor_preferences(self):
        from copy import deepcopy
        import data.constants as c
        from data import queries
        from data.io import settings_schema
        from map_logic.ai import ai_handler
        before = deepcopy(settings_schema.from_controller(self.controller))
        keybinds = deepcopy(self.controller.keybinds)
        saved_path, saved_color = c.SAVES_DIR, c.OCEAN_LIGHT_BLUE
        preview = self.make_game_preview()
        with mock.patch.object(queries, "save_global_settings") as save, mock.patch.object(c, "apply_runtime_settings") as apply, mock.patch.object(ai_handler, "reset_clients") as reset_clients:
            preview.open_screen("SETTINGS")
            settings = preview.current_screen
            settings.toggle_intro_popup(False)
            self.assertEqual(settings.show_strategic_intro_popup, preview.settings_controller.show_strategic_intro_popup)
            changed = settings.show_strategic_intro_popup
            settings.toggle_fps()
            settings.toggle_checkerboard_water()
            settings.toggle_show_unclaimed()
            settings.toggle_army_group_animations()
            settings.cycle_control_mode()
            settings.set_ai_mode("OFF")
            settings.apply_setting("saves_dir", "preview-only")
            settings.apply_setting("ocean_light_color", (1, 2, 3))
            self.assertEqual(c.SAVES_DIR, saved_path)
            self.assertEqual(c.OCEAN_LIGHT_BLUE, saved_color)
            for category, _label in settings.categories():
                settings.set_sub_state(category)
                settings.draw(self.surface)
                if category != "GENERAL":
                    settings.reset_category_defaults()
            self.assertEqual(settings.sub_state, "GENERAL")
            self.click_preview_button(preview, "Keybinds")
            self.assertEqual(preview.current_state, "KEYBINDS")
            bindings = preview.current_screen
            bindings.remove_binding("ORDERS")
            bindings.toggle_screen_change("ORDERS")
            bindings.start_listening("BACK")
            preview.handle_back_key()  # Back belongs to key capture until a key is chosen.
            self.assertEqual(preview.current_state, "KEYBINDS")
            preview.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F6)])
            self.assertEqual(preview.settings_controller.keybinds["BACK"], pygame.K_F6)
            bindings.reset_defaults()
            preview.handle_back_key()
            self.assertEqual(preview.current_state, "SETTINGS")
            self.assertEqual(settings.show_strategic_intro_popup, changed)
            self.click_preview_button(preview, "Mouse Settings")
            self.assertEqual(preview.current_state, "MOUSE_SETTINGS")
            preview.current_screen.toggle_action("left", "pan_map")
            preview.current_screen.reset_defaults()
            preview.handle_back_key()
            preview.handle_back_key()
            self.assertEqual(preview.current_state, "MENU")
            preview.open_screen("SETTINGS")
            self.assertEqual(settings.show_strategic_intro_popup, changed)
            save.assert_not_called()
            apply.assert_not_called()
            reset_clients.assert_not_called()
        self.assertEqual(settings_schema.from_controller(self.controller), before)
        self.assertEqual(self.controller.keybinds, keybinds)

    def test_game_preview_load_browser_never_reads_or_writes_the_editors_saves(self):
        from ui.widgets.content_browser import ContentBrowserScreen
        with mock.patch.object(ContentBrowserScreen, "read_directory", side_effect=AssertionError("preview read editor saves")):
            preview = self.make_game_preview()
            self.click_preview_button(preview, "Load Game")
            browser = preview.current_screen
            browser.reload_entries()
            self.assertEqual(browser.entries, [])
            browser.load_specific_save("fixture")
            browser.activate_selected()
            self.assertFalse(browser.done)
            preview.draw(self.surface)

    def test_game_preview_uses_standalone_credits_and_music_without_library_changes(self):
        from copy import deepcopy
        from data import queries
        preview = self.make_game_preview()
        preview.open_screen("CREDITS")
        self.assertEqual(preview.current_screen.credits_list, [])
        albums = deepcopy(self.controller.active_albums)
        with mock.patch.object(self.controller, "all_albums", {"Fixture": ["fixture/song.mp3"]}), mock.patch.object(self.controller, "play_specific_song") as play, mock.patch.object(queries, "save_global_settings") as save, mock.patch.object(queries, "save_cached_json") as save_json, mock.patch.object(queries, "delete_album") as delete_album:
            preview.open_screen("MUSIC_PLAYER")
            player = preview.current_screen
            self.assertTrue(player.is_standalone)
            player.play_track("fixture/song.mp3")
            play.assert_called_once_with("fixture/song.mp3")
            with mock.patch.object(self.controller, "play_random_song") as random_song:
                player.play_track()
                random_song.assert_called_once_with(playlist=["fixture/song.mp3"])
            player.toggle_album("Fixture")
            self.assertNotIn("Fixture", player.active_albums)
            player.toggle_album("Fixture")
            self.assertIn("Fixture", player.active_albums)
            player.set_starting_song()
            player.reset_starting_song()
            player.delete_album("fixture")
            player.create_album("fixture")
            player.set_music_volume(0.1)
            player.reset_audio_defaults()
            save.assert_not_called()
            save_json.assert_not_called()
            delete_album.assert_not_called()
            self.assertEqual(self.controller.active_albums, albums)
            preview.draw(self.surface)

    def test_interesting_countries_load_from_a_saved_scenario(self):
        from data import queries
        from screens.setup import country_select
        path = "scenarios/historical/1939"
        nation_data, entries = country_select.load_interesting_countries(path, queries.normalized_standalone_export_settings(
            {"interesting_countries": [{"country": "Not A Country", "rank": "major"}] + self.interesting_entries()[::-1]}))
        self.assertEqual([entry["rank"] for entry in entries], ["major", "major", "minor"])
        self.assertTrue(all(entry["country"] in nation_data for entry in entries))

    def test_diplomacy_editor_agreements_view(self):
        from screens import editors as editor_screens
        screen = editor_screens.Diplomacy_Editor_Screen(self.map)
        screen.set_relationship_view("agreements")
        self.exercise(screen)

    def test_convoy_converter(self):
        """Takes a province as well as the map, unlike its siblings."""
        from screens import editors as editor_screens
        self.exercise(editor_screens.Convoy_Converter_Screen(self.map, self.map.selected_province))

    def test_unit_transfer(self):
        from screens import editors as editor_screens
        self.exercise(editor_screens.Unit_Transfer_Screen(self.map, self.map.selected_province))

    def test_personality_edit(self):
        """Takes a country as well as the map, unlike its siblings."""
        from screens import editors as editor_screens
        self.exercise(editor_screens.Personality_Edit_Screen(self.map, self.map.player_country))

    def test_country_edit_windows(self):
        from screens import editors as editor_screens
        for name in ("Politics_Edit_Screen", "Starting_Economy_Edit_Screen"):
            with self.subTest(screen=name):
                self.exercise(getattr(editor_screens, name)(self.map, self.map.player_country))

    # -- the other modal tool windows ------------------------------------

    def test_historical_leaders_editor(self):
        from screens.editors.historical_leaders_editor import Historical_Leaders_Editor
        self.exercise(Historical_Leaders_Editor())

    def test_unit_stats_editor_categories(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        screen = UnitStatsEditorScreen(settings={}, persist=False)
        for key, _label in screen.CATEGORIES:
            with self.subTest(category=key):
                screen.select_category(key)
                self.exercise(screen)

    def test_conversion_sliders_snap_save_cancel_and_reset(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        from data import constants as c, queries
        from ui.widgets.ui_elements import Slider, TextField
        settings = {}
        screen = UnitStatsEditorScreen(settings=settings, persist=False)
        screen.select_category("other")
        screen.toggle_use_defaults("other")
        conversions = screen.turn_tabs["conversion"]
        # Conversions use sliders only. Their text fields would belong to administrative actions.
        self.assertFalse(any(isinstance(el, TextField) and getattr(el, "entry_ref", None) is conversions["values"]
                             for el in screen.elements))
        sliders = [el for el in screen.elements if isinstance(el, Slider)]
        self.assertEqual(len(sliders), len(queries.CONVERSION_ACTIONS))
        maximum = c.MAX_CONVERSION_TURNS
        span = maximum - c.MIN_CONVERSION_TURNS
        for name, slider in zip(conversions["names"], sliders):
            for expected in range(c.MIN_CONVERSION_TURNS, maximum + 1):
                # Stop between ticks to verify snapping through mouse input.
                fraction = min(1, (expected - c.MIN_CONVERSION_TURNS) / span + .02)
                with self.subTest(name=name, fraction=fraction), \
                        mock.patch("pygame.mouse.get_pressed", return_value=(True, False, False)), \
                        mock.patch("pygame.mouse.get_pos", return_value=slider.handle_rect.center):
                    screen.handle_events([
                        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=slider.handle_rect.center),
                        pygame.event.Event(pygame.MOUSEMOTION,
                            pos=(slider.rect.left + round(slider.rect.width * fraction), slider.rect.centery)),
                        pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=slider.handle_rect.center),
                    ])
                    self.assertEqual(conversions["values"][name], str(expected))
        self.assertEqual(settings, {})
        screen.select_category("units")
        screen.select_category("other")
        self.assertTrue(all(value == str(maximum) for value in conversions["values"].values()))
        with mock.patch.object(queries, "save_scenario_settings") as save, \
                mock.patch("ui.dialogs.show_success"):
            screen.save_all()
        save.assert_not_called()
        self.assertNotIn("conversion_disabled", settings)
        for action in queries.CONVERSION_ACTIONS:
            self.assertEqual(queries.get_conversion_turns(action, settings), maximum)
        self.assertTrue(queries.scenario_has_construction_customizations(settings))
        reopened = UnitStatsEditorScreen(settings=settings, persist=False)
        with mock.patch("ui.dialogs.ask_yes_no", side_effect=lambda _title, _text, cb: cb(True)), \
                mock.patch("ui.dialogs.show_success"):
            reopened.reset_to_defaults()
        self.assertFalse(settings.get("conversion_turn_overrides"))
        self.assertFalse(queries.scenario_has_construction_customizations(settings))

    def test_conversion_editor_repairs_malformed_override_blocks(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        from data import queries
        for value in (None, [], "invalid"):
            with self.subTest(value=value):
                settings = {"conversion_turn_overrides": value}
                screen = UnitStatsEditorScreen(settings=settings, persist=False)
                screen.toggle_use_defaults("other")
                self.assertEqual(settings["conversion_turn_overrides"], value)
                for action, (name, _constant) in queries.CONVERSION_ACTIONS.items():
                    self.assertEqual(screen.turn_tabs["conversion"]["values"][name],
                                     str(queries.get_conversion_turns(action)))
                with mock.patch("ui.dialogs.show_success"):
                    screen.save_all()
                self.assertEqual(settings["conversion_turn_overrides"], {})

    def test_administrative_editor_saves_all_tabs_and_cancels_cleanly(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        from data import queries
        settings = {}
        screen = UnitStatsEditorScreen(settings=settings, persist=False)
        screen.select_category("other")
        screen.toggle_use_defaults("other")
        name = queries.ADMINISTRATIVE_ACTIONS["CORE"][0]
        duration = screen.turn_tabs["administrative"]["defaults"][name] + 3
        field = next(el for el in screen.elements if getattr(el, "entry_key", None) == name)
        field.text = str(duration)
        toggle = screen.elements[screen.elements.index(field) + 1]
        toggle.callback()
        self.assertEqual(settings, {})  # An abandoned modal has no side effects.
        with mock.patch.object(queries, "save_scenario_settings") as save, \
                mock.patch("ui.dialogs.show_success"):
            screen.save_all()
        save.assert_not_called()  # Lobby settings stay in the session.
        self.assertEqual(settings["administrative_turn_overrides"][name], duration)
        self.assertIn(name, settings["administrative_disabled"])
        self.assertTrue(queries.scenario_has_construction_customizations(settings))
        reopened = UnitStatsEditorScreen(settings=settings, persist=False)
        self.assertEqual(reopened.turn_tabs["administrative"]["values"][name], str(duration))
        with mock.patch("ui.dialogs.ask_yes_no", side_effect=lambda _title, _text, cb: cb(True)), \
                mock.patch("ui.dialogs.show_success"):
            reopened.reset_to_defaults()
        self.assertFalse(queries.scenario_has_construction_customizations(settings))

    def test_list_select_screen(self):
        from ui.dialogs.list_select_screen import ListSelectScreen
        items = [f"Item {i}" for i in range(60)]
        self.exercise(ListSelectScreen(self.map, "Pick", "Choose one:", items, lambda _v: None))

    def test_checkbox_list_screen(self):
        from ui.dialogs.checkbox_list_screen import CheckboxListScreen, CheckboxItem
        items = [CheckboxItem(f"opt{i}", f"Option {i}") for i in range(60)]
        self.exercise(CheckboxListScreen(self.map, "Pick", "Choose some:", items, lambda _v: None))

    def test_color_picker_screen(self):
        from ui.dialogs.color_picker_screen import ColorPickerScreen
        self.exercise(ColorPickerScreen(self.map, "Color", (120, 40, 200), lambda _v: None))

    def test_file_browser_screen(self):
        from ui.dialogs.file_browser_screen import FileBrowserScreen
        self.exercise(FileBrowserScreen(self.map, "Open", ".", lambda _v: None))

    def test_table_screen(self):
        from ui.widgets.table_screen import TableScreen, TableColumn
        columns = [TableColumn("name", "Name", 300, align="left"),
                   TableColumn("value", "Value", 150)]
        rows = [{"name": f"Row {i}", "value": i} for i in range(80)]
        self.exercise(TableScreen(self.map, "Table", columns, rows))


if __name__ == "__main__":
    unittest.main()
