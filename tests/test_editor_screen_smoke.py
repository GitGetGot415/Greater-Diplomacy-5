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

    # -- screens/editor_screens/scripted_events_editor.py -----------------

    def test_scripted_events_editor(self):
        from screens.editor_screens import scripted_events_editor as se
        self.exercise(se.Scripted_Events_Editor_Screen(self.map))

    def test_scripted_events_help(self):
        from screens.editor_screens import scripted_events_editor as se
        self.exercise(se._HelpScreen(self.map))

    def test_scripted_events_variables(self):
        from screens.editor_screens import scripted_events_editor as se
        self.exercise(se._VariablesScreen(self.map, self.map))

    def test_scripted_events_event_edit(self):
        from screens.editor_screens import scripted_events_editor as se
        target = self.map.player_country
        self.exercise(se._EventEditScreen(self.map, self.map, target))

    # -- screens/editor_screens/ (date_economy/research/brush/diplomacy) --

    def test_map_editor_screens(self):
        from screens import editor_screens
        for name in ("Editor_Date_Screen", "Starting_Economy_List_Screen",
                     "Research_List_Screen", "Resource_Brush_Screen",
                     "Clear_Map_Screen", "Diplomacy_Editor_Screen",
                     "Personality_List_Screen"):
            with self.subTest(screen=name):
                self.exercise(getattr(editor_screens, name)(self.map))

    def test_diplomacy_editor_agreements_view(self):
        from screens import editor_screens
        screen = editor_screens.Diplomacy_Editor_Screen(self.map)
        screen.set_relationship_view("agreements")
        self.exercise(screen)

    def test_convoy_converter(self):
        """Takes a province as well as the map, unlike its siblings."""
        from screens import editor_screens
        self.exercise(editor_screens.Convoy_Converter_Screen(self.map, self.map.selected_province))

    def test_personality_edit(self):
        """Takes a country as well as the map, unlike its siblings."""
        from screens import editor_screens
        self.exercise(editor_screens.Personality_Edit_Screen(self.map, self.map.player_country))

    # -- the other modal tool windows ------------------------------------

    def test_historical_leaders_editor(self):
        from screens.editor_screens.historical_leaders_editor import Historical_Leaders_Editor
        self.exercise(Historical_Leaders_Editor())

    def test_turn_editor(self):
        from screens.editor_screens.turn_editor import TurnEditorScreen
        screen = TurnEditorScreen()
        self.exercise(screen)
        screen.select_tab("administrative")
        self.exercise(screen)
        screen.select_tab("conversion")
        self.exercise(screen)

    def test_conversion_sliders_snap_save_cancel_and_reset(self):
        from screens.editor_screens.turn_editor import TurnEditorScreen
        from data import constants as c, queries
        from ui_elements import Slider, TextField
        settings = {}
        screen = TurnEditorScreen(settings=settings, persist=False)
        screen.select_tab("conversion")
        self.assertFalse(any(isinstance(el, TextField) for el in screen.elements))
        sliders = [el for el in screen.elements if isinstance(el, Slider)]
        self.assertEqual(len(sliders), len(queries.CONVERSION_ACTIONS))
        maximum = c.MAX_CONVERSION_TURNS
        span = maximum - c.MIN_CONVERSION_TURNS
        for name, slider in zip(screen.tab["names"], sliders):
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
                    self.assertEqual(screen.tab["values"][name], str(expected))
        self.assertEqual(settings, {})
        screen.select_tab("unit")
        screen.select_tab("conversion")
        self.assertTrue(all(value == str(maximum) for value in screen.tab["values"].values()))
        with mock.patch.object(queries, "save_scenario_settings") as save, \
                mock.patch("ui.confirm_dialog.show_success"):
            screen.save_all()
        save.assert_not_called()
        self.assertNotIn("conversion_disabled", settings)
        for action in queries.CONVERSION_ACTIONS:
            self.assertEqual(queries.get_conversion_turns(action, settings), maximum)
        self.assertTrue(queries.scenario_has_construction_customizations(settings))
        reopened = TurnEditorScreen(settings=settings, persist=False)
        with mock.patch("ui.confirm_dialog.ask_yes_no", side_effect=lambda _title, _text, cb: cb(True)), \
                mock.patch("ui.confirm_dialog.show_success"):
            reopened.reset_to_defaults()
        self.assertEqual(settings["conversion_turn_overrides"], {})
        self.assertFalse(queries.scenario_has_construction_customizations(settings))

    def test_conversion_editor_repairs_malformed_override_blocks(self):
        from screens.editor_screens.turn_editor import TurnEditorScreen
        from data import queries
        for value in (None, [], "invalid"):
            with self.subTest(value=value):
                settings = {"conversion_turn_overrides": value}
                screen = TurnEditorScreen(settings=settings, persist=False)
                self.assertEqual(settings["conversion_turn_overrides"], value)
                self.assertEqual(screen.tabs["conversion"]["overrides"], {})
                for action, (name, _constant) in queries.CONVERSION_ACTIONS.items():
                    self.assertEqual(screen.tabs["conversion"]["values"][name],
                                     str(queries.get_conversion_turns(action)))

    def test_administrative_editor_saves_all_tabs_and_cancels_cleanly(self):
        from screens.editor_screens.turn_editor import TurnEditorScreen
        from data import queries
        settings = {}
        screen = TurnEditorScreen(settings=settings, persist=False)
        screen.select_tab("administrative")
        name = queries.ADMINISTRATIVE_ACTIONS["CORE"][0]
        duration = screen.tab["defaults"][name] + 3
        field = next(el for el in screen.elements if getattr(el, "entry_key", None) == name)
        field.text = str(duration)
        screen.toggle_disabled(name)
        self.assertEqual(settings, {})  # An abandoned modal has no side effects.
        with mock.patch.object(queries, "save_scenario_settings") as save, \
                mock.patch("ui.confirm_dialog.show_success"):
            screen.save_all()
        save.assert_not_called()  # Lobby settings stay in the session.
        self.assertEqual(settings["administrative_turn_overrides"][name], duration)
        self.assertIn(name, settings["administrative_disabled"])
        self.assertTrue(queries.scenario_has_construction_customizations(settings))
        reopened = TurnEditorScreen(settings=settings, persist=False)
        self.assertEqual(reopened.tabs["administrative"]["values"][name], str(duration))
        with mock.patch("ui.confirm_dialog.ask_yes_no", side_effect=lambda _title, _text, cb: cb(True)), \
                mock.patch("ui.confirm_dialog.show_success"):
            reopened.reset_to_defaults()
        self.assertFalse(queries.scenario_has_construction_customizations(settings))

    def test_list_select_screen(self):
        from ui.list_select_screen import ListSelectScreen
        items = [f"Item {i}" for i in range(60)]
        self.exercise(ListSelectScreen(self.map, "Pick", "Choose one:", items, lambda _v: None))

    def test_checkbox_list_screen(self):
        from ui.checkbox_list_screen import CheckboxListScreen, CheckboxItem
        items = [CheckboxItem(f"opt{i}", f"Option {i}") for i in range(60)]
        self.exercise(CheckboxListScreen(self.map, "Pick", "Choose some:", items, lambda _v: None))

    def test_color_picker_screen(self):
        from ui.color_picker_screen import ColorPickerScreen
        self.exercise(ColorPickerScreen(self.map, "Color", (120, 40, 200), lambda _v: None))

    def test_file_browser_screen(self):
        from ui.file_browser_screen import FileBrowserScreen
        self.exercise(FileBrowserScreen(self.map, "Open", ".", lambda _v: None))

    def test_table_screen(self):
        from ui.table_screen import TableScreen, TableColumn
        columns = [TableColumn("name", "Name", 300, align="left"),
                   TableColumn("value", "Value", 150)]
        rows = [{"name": f"Row {i}", "value": i} for i in range(80)]
        self.exercise(TableScreen(self.map, "Table", columns, rows))


if __name__ == "__main__":
    unittest.main()
