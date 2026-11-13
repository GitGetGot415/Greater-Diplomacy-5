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
                # A standalone menu has no intro animation: one update puts every part at rest.
                menu = preview.menu
                for button, target in menu._center_button_targets:
                    self.assertEqual(button.rect.topleft, target)
                self.assertEqual(menu.button_panel_rect, menu._button_panel_target)
                self.assertEqual(menu._title_draw_pos, menu.title_rect.topleft)
                self.exercise(preview)

    def interesting_entries(self):
        from data import queries
        playable = queries.playable_start_countries(self.map.map_data, self.map.nation_data)
        return [{"country": country, "rank": rank, "description": "Fixture description " * 20}
                for country, rank in zip(playable, ("major", "major", "minor"))]

    def test_export_screen_lists_interesting_countries(self):
        from screens.editors.standalone_export import Standalone_Export_Screen
        entries = self.interesting_entries()
        with mock.patch.dict(self.map.standalone_export_settings, {"interesting_countries": entries}):
            screen = Standalone_Export_Screen()
            screen.on_enter(self.controller, None)
            self.exercise(screen)
            self.assertEqual([entry["rank"] for entry in screen.ordered_countries(screen.settings())],
                             ["major", "major", "minor"])

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
        self.assertEqual(menu.version_status, f"Made with Greater Diplomacy 5 ({c.GAME_VERSION})")

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

    def test_selection_preview_selects_countries_but_never_leaves(self):
        from screens.setup import country_select
        from screens.editors.standalone_export import Standalone_Selection_Preview
        from data import queries
        entries = country_select.interesting_countries(
            {"interesting_countries": self.interesting_entries()}, self.map.map_data, self.map.nation_data)
        image = queries.encode_rgba_to_b64(bytes([1, 2, 3, 255]) * 6, (3, 2))
        settings = {"background_color": [4, 5, 6], "background_image": image}
        preview = Standalone_Selection_Preview(self.map.nation_data, entries, settings)
        self.exercise(preview)
        selector = preview.selector
        # The selector draws the main menu's background, not the default checkerboard.
        self.assertEqual(selector.background.color, [4, 5, 6])
        self.assertIsNotNone(selector.background.image)

        def click(button):
            position = button.rect.center
            preview.handle_events([
                pygame.event.Event(pygame.MOUSEMOTION, pos=position, rel=(0, 0), buttons=(0, 0, 0)),
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=position, button=1),
                pygame.event.Event(pygame.MOUSEBUTTONUP, pos=position, button=1)])

        minor = entries[-1]["country"]
        click(next(button for button in selector.elements if button.text == selector.name(minor)))
        self.assertEqual(selector.selected, minor)
        for label in ("Back", "Select Country"):
            click(next(button for button in selector.elements if button.text == label))
            self.assertFalse(selector.done)
            self.assertFalse(preview.done)
        preview.go_back()
        self.assertTrue(preview.done)

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
