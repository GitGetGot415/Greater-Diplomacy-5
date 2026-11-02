"""The rename and delete popups shared by Load Game, Mods, and the map list."""

import os
import tempfile
import unittest
from unittest import mock

from tests import app_harness  # Sets the dummy video driver before pygame starts.

from ui.navigation.game_state import FolderListState


class _FolderScreen(FolderListState):
    back_state = "MENU"

    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.refreshes = 0

    @property
    def managed_dir(self):
        return self.directory

    def refresh_ui(self):
        self.refreshes += 1


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

    def open_delete(self):
        with mock.patch("ui.dialogs.ask_yes_no") as ask:
            self.screen.start_delete("old")
        return ask.call_args.args[2]

    def test_delete_keeps_the_folder_until_the_popup_is_answered(self):
        self.open_delete()
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "old")))

    def test_confirming_the_delete_removes_the_folder_and_refreshes(self):
        self.open_delete()(True)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "old")))
        self.assertEqual(self.screen.refreshes, 1)

    def test_denying_the_delete_keeps_the_folder(self):
        answer = self.open_delete()
        for value in (False, None):
            answer(value)
            self.assertTrue(os.path.isdir(os.path.join(self.dir, "old")))

    def test_back_key_leaves_the_screen(self):
        self.screen.handle_back_key()
        self.assertTrue(self.screen.done)
        self.assertEqual(self.screen.next_state, "MENU")


if __name__ == "__main__":
    unittest.main()
