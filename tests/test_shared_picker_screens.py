"""Save translation and tournament screens share one flow and keep their own settings."""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import data.constants as c
from data.state_access import BackendState
from map_logic.imports import gd4_translation, gdhex_translation
from screens.menus import translation_menu
from screens.multiplayer import tournament_picker
from screens.multiplayer.multiplayer_host import Multiplayer_Host
from screens.multiplayer.multiplayer_join import Multiplayer_Join
from screens.setup import map_refresh
from ui import dialogs
from ui.dialogs import pickers


class DisplayTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))


class SaveTranslationScreenTests(DisplayTestCase):
    CASES = ((translation_menu.Greater_Diplomacy_4_Translation, gd4_translation,
              gd4_translation.GD4TranslationError),
             (translation_menu.Greater_Diplomacy_Hex_Translation, gdhex_translation,
              gdhex_translation.GDHEXTranslationError))

    def pick(self, screen, path):
        with mock.patch.object(pickers, "open_file_browser") as browser:
            screen.choose_save()
        browser.call_args.kwargs["on_result"](path)
        return browser

    def translate(self, screen):
        screen.update()  # This frame paints the status.
        screen.update()

    def test_browser_uses_the_extensions_and_title_of_each_format(self):
        for screen_type, _translator, _error in self.CASES:
            with self.subTest(screen=screen_type.__name__):
                screen = screen_type()
                browser = self.pick(screen, None)
                self.assertEqual(browser.call_args.args[1], screen_type.browser_title)
                self.assertEqual(browser.call_args.kwargs["extensions"], list(screen_type.extensions))
                self.assertIsNone(screen.pending_path)

    def test_success_uses_the_translator_of_each_format(self):
        for screen_type, translator, _error in self.CASES:
            with self.subTest(screen=screen_type.__name__):
                screen = screen_type()
                self.pick(screen, "folder/save.txt")
                with mock.patch.object(translator, "translate_file",
                                       return_value=("out/new_save", ["A note."])) as translate:
                    self.translate(screen)
                translate.assert_called_once_with("folder/save.txt")
                self.assertTrue(screen.status_ok)
                self.assertIn("new_save", screen.status)
                self.assertEqual(screen.notes[0], "A note.")

    def test_each_format_reports_its_own_translation_error(self):
        for screen_type, translator, error in self.CASES:
            with self.subTest(screen=screen_type.__name__):
                screen = screen_type()
                self.pick(screen, "folder/save.txt")
                with mock.patch.object(translator, "translate_file", side_effect=error("Bad save")):
                    self.translate(screen)
                self.assertFalse(screen.status_ok)
                self.assertIn("Bad save", screen.status)
                self.assertEqual(screen.notes, [])

    def test_translation_waits_one_frame_for_the_status_to_paint(self):
        screen_type, translator, _error = self.CASES[0]
        screen = screen_type()
        self.pick(screen, "folder/save.txt")
        with mock.patch.object(translator, "translate_file", return_value=("out", [])) as translate:
            screen.update()
            translate.assert_not_called()
            screen.update()
            translate.assert_called_once()


class TournamentPickerTests(DisplayTestCase):
    def open_tournament(self, screen, opener, path, key):
        with mock.patch.object(pickers, "open_file_browser") as browser, \
                mock.patch.object(dialogs, "ask_string") as ask, \
                mock.patch.object(screen, "go_to") as go_to:
            opener()
            browser.call_args.kwargs["on_result"](path)
            if path:
                ask.call_args.args[2](key)
        return browser, ask, go_to

    def test_host_and_join_ask_for_their_own_key_and_open_the_map(self):
        for screen_type, opener, title in ((Multiplayer_Host, "load_existing", "Master Key"),
                                           (Multiplayer_Join, "load_tour_file", "Player Key")):
            with self.subTest(screen=screen_type.__name__):
                screen = screen_type()
                browser, ask, go_to = self.open_tournament(
                    screen, getattr(screen, opener), "folder/game.gd5tour", "secret")
                self.assertEqual(browser.call_args.kwargs["extensions"], [".gd5tour"])
                self.assertEqual(ask.call_args.args[0], title)
                self.assertEqual(screen.selected_tournament_path, "folder/game.gd5tour")
                self.assertEqual(screen.selected_tournament_key, "secret")
                go_to.assert_called_once_with("MAP")

    def test_cancelled_key_or_file_stays_on_the_screen(self):
        for path, key in (("folder/game.gd5tour", ""), (None, "secret")):
            with self.subTest(path=path, key=key):
                screen = Multiplayer_Join()
                _browser, _ask, go_to = self.open_tournament(screen, screen.load_tour_file, path, key)
                go_to.assert_not_called()
                self.assertFalse(hasattr(screen, "selected_tournament_path"))

    def test_both_screens_return_to_the_multiplayer_hub(self):
        self.assertTrue(issubclass(Multiplayer_Host, tournament_picker.TournamentPickerScreen))
        self.assertTrue(issubclass(Multiplayer_Join, tournament_picker.TournamentPickerScreen))
        self.assertEqual(Multiplayer_Host.back_state, "MULTIPLAYER_HUB")
        self.assertEqual(Multiplayer_Join.back_state, "MULTIPLAYER_HUB")


class MapRefreshTests(unittest.TestCase):
    def test_folder_without_maps_reports_it_and_starts_no_refresh(self):
        screen = mock.Mock(spec=["is_refreshing"])
        screen.is_refreshing = False
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(dialogs, "show_info") as show_info, \
                mock.patch.object(map_refresh, "run_background") as background:
            map_refresh.refresh_map_directories(screen, [folder])
        show_info.assert_called_once()
        background.assert_not_called()
        self.assertFalse(screen.is_refreshing)


class OptionalMapStateTests(unittest.TestCase):
    def test_each_map_owns_its_multiplayer_and_editor_state(self):
        first, second = BackendState(), BackendState()
        first.submitted_moves.add("A")
        first.multiplayer_keys_dict["A"] = "key"
        first.realtime_volunteer_drafts["A"] = []
        first.editor_history.append("state")
        self.assertEqual(second.submitted_moves, set())
        self.assertEqual(second.multiplayer_keys_dict, {})
        self.assertEqual(second.realtime_volunteer_drafts, {})
        self.assertEqual(second.editor_history, [])

    def test_backend_state_reads_every_optional_rule_field_without_a_screen(self):
        state = BackendState()
        self.assertIsNone(state.realtime_server_map)
        self.assertIsNone(state.realtime_match_metadata)
        self.assertIsNone(state.unit_event_filter_turn)
        self.assertIsNone(state._presentation_cache_revision)
        self.assertIsNone(state._bilateral_response_indicator_cache)
        self.assertFalse(state.presentation_enabled)


if __name__ == "__main__":
    unittest.main()
