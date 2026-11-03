"""Selection, file operations, input, and cache boundaries in saved-content browsers."""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests import app_harness

import pygame


def key(code, text=""):
    return pygame.event.Event(pygame.KEYDOWN, key=code, unicode=text, mod=0)


def button_named(screen, text):
    return next(element for element in screen.elements if getattr(element, "text", None) == text)


class ContentBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()

    def setUp(self):
        from data import constants as c

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for setting in ("SAVES_DIR", "SCENARIOS_CUSTOM_DIR", "BASE_MAPS_DIR",
                        "SCENARIOS_HISTORICAL_DIR", "SCENARIOS_ALTERNATE_DIR"):
            path = self.root / setting
            path.mkdir()
            patcher = mock.patch.object(c, setting, str(path))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.constants = c
        patcher = mock.patch("ui.navigation.screen.sync_persisted_dir")
        self.persist = patcher.start()
        self.addCleanup(patcher.stop)

    def bundle(self, name="Campaign", setting="SAVES_DIR", meta=None, modified=100):
        directory = Path(getattr(self.constants, setting)) / name
        directory.mkdir()
        (directory / "map_data.json").write_text("{}", encoding="utf-8")
        if meta is not None:
            (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        os.utime(directory, (modified, modified))
        return directory

    def save_screen(self):
        from screens.menus.load_game import Load_Game
        return Load_Game()

    def map_screen(self):
        from screens.setup.select_base_map import Select_Base_Map
        return Select_Base_Map()

    def click(self, screen, button):
        with mock.patch("pygame.mouse.get_pos", return_value=button.rect.center):
            screen.handle_events([
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center),
                pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=button.rect.center),
            ])

    def test_selection_does_not_open_and_primary_action_loads_the_selected_save(self):
        self.bundle("Alpha")
        beta = self.bundle("Beta", modified=200)
        screen = self.save_screen()
        with mock.patch.object(screen, "load_specific_save") as load:
            self.click(screen, button_named(screen, "Alpha"))
            load.assert_not_called()
            screen.handle_events([key(pygame.K_DOWN)])
            # Recently modified sorting puts Beta before Alpha.
            screen.handle_events([key(pygame.K_UP)])
            self.assertEqual(screen.selected_entry.path, str(beta))
            self.click(screen, button_named(screen, "Load Game"))
        load.assert_called_once_with("Beta")

    def test_search_is_case_insensitive_and_empty_results_cannot_open(self):
        self.bundle("Alpha")
        self.bundle("BETA")
        screen = self.save_screen()
        screen.search_field.active = True
        screen.handle_events([key(pygame.K_b, "b"), key(pygame.K_e, "e")])
        self.assertEqual([entry.name for entry in screen.filtered_entries], ["BETA"])
        with mock.patch.object(screen, "activate_selected") as activate:
            screen.handle_events([key(pygame.K_RETURN)])
        activate.assert_not_called()
        screen.search_field.text = "missing"
        screen.filter_entries("missing")
        self.assertIsNone(screen.selected_entry)
        with mock.patch.object(screen, "load_specific_save") as load:
            screen.activate_selected()
        load.assert_not_called()
        self.click(screen, button_named(screen, "Clear"))
        self.assertEqual(len(screen.filtered_entries), 2)

    def test_sort_order_and_refresh_preserve_selection(self):
        self.bundle("Alpha", modified=100)
        self.bundle("beta", modified=200)
        screen = self.save_screen()
        self.assertEqual([entry.name for entry in screen.filtered_entries], ["beta", "Alpha"])
        screen.cycle_sort()
        self.assertEqual([entry.name for entry in screen.filtered_entries], ["Alpha", "beta"])
        self.assertEqual(screen.selected_entry.name, "beta")
        screen.cycle_sort()
        self.assertEqual([entry.name for entry in screen.filtered_entries], ["beta", "Alpha"])
        self.bundle("New", modified=300)
        screen.reload_entries()
        self.assertEqual(screen.selected_entry.name, "beta")
        self.assertEqual(len(screen.entries), 3)

    def test_hidden_entries_and_regular_files_are_not_browsed(self):
        self.bundle("Visible")
        self.bundle(".Hidden")
        (Path(self.constants.SAVES_DIR) / "notes.txt").write_text("fixture", encoding="utf-8")
        screen = self.save_screen()
        self.assertEqual([entry.name for entry in screen.entries], ["Visible"])

    def test_draw_update_scroll_and_search_use_cached_files(self):
        from data import queries

        for index in range(12):
            self.bundle(f"Save {index:02d}", meta={"scenario_metadata": {"description": "Details " * 150}})
        screen = self.save_screen()
        screen.draw(self.surface)
        with mock.patch("os.scandir", side_effect=AssertionError("Unexpected directory scan")), \
                mock.patch.object(queries, "read_saved_content_summary", side_effect=AssertionError("Unexpected metadata read")):
            screen.update()
            screen.draw(self.surface)
            for pane in ("items", "details"):
                with mock.patch("pygame.mouse.get_pos", return_value=screen.regions[pane].center):
                    screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, y=-2, x=0)])
            screen.search_field.text = "Save"
            screen.filter_entries("Save")
        self.assertLess(screen.pane_scroll("details"), 0)

    def test_scroll_is_routed_to_the_hovered_pane_and_keyboard_reaches_the_last_item(self):
        for index in range(18):
            self.bundle(f"Save {index:02d}")
        screen = self.save_screen()
        with mock.patch("pygame.mouse.get_pos", return_value=screen.detail_panel.center):
            screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, y=-2, x=0)])
        self.assertEqual(screen.pane_scroll("items"), 0)
        screen.handle_events([key(pygame.K_DOWN) for _ in range(30)])
        self.assertEqual(screen.selected_entry, screen.filtered_entries[-1])
        self.assertLess(screen.pane_scroll("items"), 0)
        screen.draw(self.surface)

    def test_dragging_content_scrolls_without_selecting_a_row(self):
        for index in range(12):
            self.bundle(f"Save {index:02d}")
        screen = self.save_screen()
        screen.draw(self.surface)
        row = button_named(screen, "Save 02")
        start = row.rect.center
        end = (start[0], start[1] + 50)
        with mock.patch("pygame.mouse.get_pos", return_value=end), \
                mock.patch.object(screen, "select_entry") as select:
            screen.handle_events([
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=start),
                pygame.event.Event(pygame.MOUSEMOTION, pos=end, rel=(0, 50), buttons=(1, 0, 0)),
                pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=end),
            ])
        select.assert_not_called()
        self.assertLess(screen.pane_scroll("items"), 0)

    def test_escape_releases_search_focus_before_leaving(self):
        from ui.navigation.screen import dispatch_global_keys, keyboard_input_is_captured

        for screen in (self.save_screen(), self.map_screen()):
            with self.subTest(screen=type(screen).__name__):
                screen.search_field.active = True
                self.assertTrue(keyboard_input_is_captured(screen))
                dispatch_global_keys(screen, key(pygame.K_ESCAPE))
                self.assertFalse(screen.search_field.active)
                self.assertFalse(screen.done)
                dispatch_global_keys(screen, key(pygame.K_ESCAPE))
                self.assertTrue(screen.done)
                self.assertEqual(screen.next_state, "MENU")

    def test_rename_and_confirmed_delete_refresh_entries_and_sync_storage(self):
        from ui import dialogs

        self.bundle("Original")
        screen = self.save_screen()
        with mock.patch.object(dialogs, "ask_string") as ask:
            self.click(screen, button_named(screen, "Rename"))
        ask.call_args.args[2]("Renamed")
        self.assertEqual(screen.selected_entry.name, "Renamed")
        self.assertFalse((Path(self.constants.SAVES_DIR) / "Original").exists())
        with mock.patch.object(dialogs, "ask_yes_no") as ask:
            self.click(screen, button_named(screen, "Delete…"))
        self.assertTrue((Path(self.constants.SAVES_DIR) / "Renamed").exists())
        ask.call_args.args[2](False)
        self.assertEqual(len(screen.entries), 1)
        ask.call_args.args[2](True)
        self.assertEqual(screen.entries, [])
        self.persist.assert_has_calls([mock.call(self.constants.SAVES_DIR), mock.call(self.constants.SAVES_DIR)])

    def test_map_tabs_open_sources_without_management_permissions(self):
        custom = self.bundle("Custom", "SCENARIOS_CUSTOM_DIR")
        self.bundle("Base", "BASE_MAPS_DIR")
        screen = self.map_screen()
        self.assertEqual(screen.selected_entry.path, str(custom))
        self.click(screen, button_named(screen, "Base Maps"))
        self.assertEqual(screen.sub_state, "BASE_MAPS")
        with mock.patch.object(screen, "start_rename") as rename:
            button_named(screen, "Rename").callback()
        rename.assert_not_called()
        with mock.patch.object(screen, "start_editor_with_map") as edit:
            self.click(screen, button_named(screen, "Create from Base"))
        edit.assert_called_once_with("Base", self.constants.BASE_MAPS_DIR)
        screen.handle_back_key()
        self.assertEqual(screen.sub_state, "CUSTOM_MAPS")
        with mock.patch.object(screen, "start_editor_with_map") as edit:
            self.click(screen, button_named(screen, "Edit Map"))
        edit.assert_called_once_with("Custom", self.constants.SCENARIOS_CUSTOM_DIR)

    def test_import_uses_existing_exchange_and_refreshes_after_success(self):
        from ui.dialogs import file_exchange

        for screen, directory in ((self.save_screen(), self.constants.SAVES_DIR),
                                  (self.map_screen(), self.constants.SCENARIOS_CUSTOM_DIR)):
            with self.subTest(screen=type(screen).__name__), \
                    mock.patch.object(file_exchange, "import_zip_to_dir") as import_zip:
                self.click(screen, button_named(screen, "Import .zip"))
                args = import_zip.call_args.args
                self.assertEqual(args[:2], (screen, directory))
                self.bundle("Imported", "SAVES_DIR" if directory == self.constants.SAVES_DIR else "SCENARIOS_CUSTOM_DIR")
                args[2]()
                self.assertEqual(screen.selected_entry.name, "Imported")

    def test_export_uses_the_selected_directory_and_existing_exchange(self):
        from ui.dialogs import file_exchange

        save = self.bundle("Campaign")
        custom = self.bundle("Custom", "SCENARIOS_CUSTOM_DIR")
        for screen, path, filename in ((self.save_screen(), save, "Campaign.zip"),
                                       (self.map_screen(), custom, "Custom_scenario.zip")):
            with self.subTest(screen=type(screen).__name__), \
                    mock.patch.object(file_exchange, "export_dir_as_zip") as export:
                self.click(screen, button_named(screen, "Export"))
                export.assert_called_once_with(str(path), filename)

    def test_background_refresh_reloads_only_when_work_finishes(self):
        screen = self.map_screen()
        with mock.patch.object(screen, "reload_entries") as reload:
            screen.is_refreshing = True
            screen.update()
            screen.update()
            reload.assert_not_called()
            screen.is_refreshing = False
            screen.update()
            screen.update()
        reload.assert_called_once()

    def test_controller_refreshes_browsers_on_entry(self):
        import main
        from screens.menus.load_game import Load_Game
        from screens.setup.select_base_map import Select_Base_Map

        for state, screen_class in (("LOAD_GAME", Load_Game), ("SELECT_BASE_MAP", Select_Base_Map)):
            previous = SimpleNamespace(next_state=state, done=True)
            target = screen_class.__new__(screen_class)
            controller = SimpleNamespace(active_state=previous, states={state: target})
            with mock.patch.object(screen_class, "reload_entries") as reload_entries:
                main.Controller.flip_state(controller)
            reload_entries.assert_called_once()
            self.assertIs(controller.active_state, target)

    def test_summary_uses_existing_metadata_and_display_names_without_loading_history(self):
        from data import queries

        path = self.bundle(meta={"version": self.constants.GAME_VERSION,
                                 "date": {"day": 15, "month": 2, "year": 1234, "total_turns": 7},
                                 "player_country": "fixture_id",
                                 "nation_data": {"fixture_id": {"name": "Display Name"}},
                                 "scenario_metadata": {"author": "Fixture", "description": "Description"}})
        with mock.patch.object(queries, "get_country_data", return_value={}), \
                mock.patch("builtins.open", wraps=open) as reads:
            summary = queries.read_saved_content_summary(str(path))
        reads.assert_called_once_with(str(path / "meta.json"), encoding="utf-8")
        self.assertEqual(summary["error"], "")
        self.assertIn("Player: Display Name", summary["details"])
        self.assertIn("Author: Fixture", summary["details"])
        self.assertIn("Description", summary["details"])
        self.assertIn("Turn: 7", summary["details"])

    def test_missing_metadata_is_supported_and_bad_metadata_blocks_opening(self):
        from data import queries

        path = self.bundle()
        self.assertEqual(queries.read_saved_content_summary(str(path))["error"], "")
        for payload in ("{broken", "[]", '{"scenario_metadata": {"author": []}}', '{"version": "v999999"}'):
            with self.subTest(payload=payload):
                (path / "meta.json").write_text(payload, encoding="utf-8")
                screen = self.save_screen()
                self.assertTrue(screen.selection_error)
                with mock.patch.object(screen, "load_specific_save") as load:
                    screen.activate_selected()
                load.assert_not_called()
        (path / "map_data.json").unlink()
        (path / "meta.json").unlink()
        self.assertTrue(queries.read_saved_content_summary(str(path))["error"])
