"""Builds and paints the modal tool windows that live outside Controller.states.

The editors, pickers and dialogs in ui/ are pushed onto the modal stack from a
button rather than being constructed up front, so test_screen_smoke never sees
them -- and they hold most of the panel chrome and multi-pane scroll code this
refactor touches. Each is built against the real 1939 map and put through
refresh_ui, a draw and a wheel notch.
"""

import unittest

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
        self.exercise(TurnEditorScreen())

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
        self.exercise(ColorPickerScreen(self.map, "Colour", (120, 40, 200), lambda _v: None))

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
