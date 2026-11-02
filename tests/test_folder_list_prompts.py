"""The rename and delete popups shared by Load Game, Mods, and the map list."""

import os
import tempfile
import unittest
from unittest import mock

from tests import app_harness  # Sets the dummy video driver before pygame starts.

import pygame

from ui.navigation.game_state import FolderListState


class _RecordingElement:
    def __init__(self):
        self.events = []

    def handle_event(self, event):
        self.events.append(event)


class _FolderScreen(FolderListState):
    back_state = "MENU"

    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.element = _RecordingElement()
        self.elements = [self.element]
        self.refreshes = 0

    @property
    def managed_dir(self):
        return self.directory

    def refresh_ui(self):
        self.refreshes += 1


def click():
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(5, 5))


def key(code):
    return pygame.event.Event(pygame.KEYDOWN, key=code, unicode="", mod=0)


class FolderListPromptTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = temp.name
        os.mkdir(os.path.join(self.dir, "old"))
        self.screen = _FolderScreen(self.dir)
        persist = mock.patch("ui.navigation.game_state.sync_persisted_dir")
        persist.start()
        self.addCleanup(persist.stop)

    def open_rename(self):
        with mock.patch("ui.dialogs.ask_string") as ask:
            self.screen.start_rename("old")
        return ask

    def test_rename_opens_a_popup_with_the_current_name(self):
        ask = self.open_rename()
        self.assertEqual(ask.call_args.kwargs["initial"], "old")
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "old")))

    def test_rename_answer_renames_the_folder_and_refreshes(self):
        answer = self.open_rename().call_args.args[2]
        answer("  new name  ")
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "new name")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "old")))
        self.assertEqual(self.screen.refreshes, 1)

    def test_rename_cancel_and_blank_answers_change_nothing(self):
        answer = self.open_rename().call_args.args[2]
        for value in (None, "", "   ", "old"):
            answer(value)
            self.assertTrue(os.path.isdir(os.path.join(self.dir, "old")), value)

    def test_rename_does_not_replace_an_existing_folder(self):
        os.mkdir(os.path.join(self.dir, "taken"))
        self.open_rename().call_args.args[2]("taken")
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "old")))

    def test_rename_rejects_path_characters(self):
        is_valid = self.open_rename().call_args.kwargs["is_valid_char"]
        for char in "/\\.:":
            self.assertFalse(is_valid(char), char)
        for char in "aZ9 _-":
            self.assertTrue(is_valid(char), char)

    def test_delete_popup_blocks_the_buttons_behind_it(self):
        self.screen.start_delete("old")
        self.screen.handle_events([click()])
        self.assertEqual(self.screen.element.events, [])
        self.assertEqual(self.screen.deleting_item, "old")

    def test_buttons_receive_events_when_no_popup_is_open(self):
        event = click()
        self.screen.handle_events([event])
        self.assertEqual(self.screen.element.events, [event])

    def test_enter_confirms_the_delete(self):
        self.screen.start_delete("old")
        self.screen.handle_events([key(pygame.K_RETURN)])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "old")))
        self.assertIsNone(self.screen.deleting_item)

    def test_back_key_cancels_the_delete_without_leaving_the_screen(self):
        self.screen.start_delete("old")
        self.screen.handle_back_key()
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "old")))
        self.assertIsNone(self.screen.deleting_item)
        self.assertFalse(self.screen.done)

    def test_back_key_leaves_the_screen_when_no_popup_is_open(self):
        self.screen.handle_back_key()
        self.assertTrue(self.screen.done)
        self.assertEqual(self.screen.next_state, "MENU")


if __name__ == "__main__":
    unittest.main()
