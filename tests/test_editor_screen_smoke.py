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
        # The image draws over either background style.
        for settings in ({"menu_background": "checkerboard"}, {"menu_background": "solid"},
                         *({"menu_background": style, "background_image": image}
                           for style in queries.STANDALONE_MENU_BACKGROUNDS for image in images)):
            with self.subTest(settings=settings):
                preview = Standalone_Menu_Preview("Fixture Game", settings)
                preview.update()
                self.exercise(preview)

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
