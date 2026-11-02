import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import pygame

import data.constants as c
from data import queries
from screens.menus import music_player
from screens.menus.music_player import Music_Player, NEW_ALBUM_LABEL


class AlbumFolderTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        patcher = mock.patch.object(c, "MUSIC_DIR", self._dir.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_created_album_can_be_deleted(self):
        name = queries.create_album("  My Album ")
        self.assertEqual(name, "My Album")
        self.assertTrue(queries.is_deletable_album("My Album"))

        queries.delete_album("My Album")

        self.assertFalse(os.path.exists(os.path.join(self._dir.name, "My Album")))

    def test_undeletable_album_cannot_be_deleted(self):
        os.makedirs(os.path.join(self._dir.name, "Shipped"))

        with mock.patch.object(c, "UNDELETABLE_ALBUMS", ("Shipped",)):
            self.assertFalse(queries.is_deletable_album("Shipped"))
            with self.assertRaises(ValueError):
                queries.delete_album("Shipped")
        self.assertTrue(os.path.isdir(os.path.join(self._dir.name, "Shipped")))

    def test_album_without_a_marker_file_can_be_deleted(self):
        os.makedirs(os.path.join(self._dir.name, "Dropped In"))

        queries.delete_album("Dropped In")

        self.assertFalse(os.path.exists(os.path.join(self._dir.name, "Dropped In")))

    def test_unusable_names_are_refused(self):
        os.makedirs(os.path.join(self._dir.name, "Taken"))
        for bad_name in ("", "   ", "a/b", "..", "CON", "taken"):
            with self.subTest(name=bad_name), self.assertRaises(ValueError):
                queries.create_album(bad_name)


class AlbumTileTests(unittest.TestCase):
    def make_player(self, albums):
        pygame.font.init()
        controller = SimpleNamespace(
            all_albums={album: [] for album in albums},
            active_albums=[], playlist=[], now_playing="None",
            is_shuffle_disabled=lambda path: False,
            sfx_volume=0.5, sfx_pitch=0.5, music_volume=0.5, music_pitch=0.5,
            music_pitch_timeline=c.MUSIC_PITCH_TIMELINE_STATIC,
            starting_song=None, is_paused=False,
            load_music_data=mock.Mock(),
        )
        player = object.__new__(Music_Player)
        player.controller = controller
        player._scroll_album = 0
        player._scroll_track = 0
        player.handle_back_key = lambda: None
        return player

    def album_buttons(self, player):
        return [b for b in player.elements if getattr(b, "pane", None) == "album"]

    def test_new_album_tile_is_last_even_when_pinned_by_order(self):
        player = self.make_player(["Alpha", "Zulu"])
        with mock.patch.object(music_player, "ALBUM_ORDER", ["Alpha"]), \
                mock.patch.object(queries, "is_deletable_album", return_value=False):
            player.refresh_ui()

        self.assertEqual([b.text for b in self.album_buttons(player)],
                         ["Alpha", "Zulu", NEW_ALBUM_LABEL])

    def test_tiles_without_a_cover_stack_up_to_the_limit(self):
        pygame.display.init()
        pygame.display.set_mode((10, 10))
        with tempfile.TemporaryDirectory() as music_dir:
            os.makedirs(os.path.join(music_dir, "Cover"))
            pygame.image.save(pygame.Surface((8, 8)), os.path.join(music_dir, "Cover", "cover.png"))
            plain = [f"Plain{index}" for index in range(music_player.ALBUM_MAX_TEXT_STACK + 1)]
            for album in plain:
                os.makedirs(os.path.join(music_dir, album))
            order = ["Cover"] + plain
            player = self.make_player(order)
            with mock.patch.object(c, "MUSIC_DIR", music_dir),                     mock.patch.object(music_player, "ALBUM_ORDER", order):
                player.refresh_ui()

        tiles = {b.text: b for b in self.album_buttons(player) if b.text != "X"}
        first_column_x = tiles["Cover"].rect.x
        second_column_x = tiles["Plain0"].rect.x
        self.assertNotEqual(first_column_x, second_column_x)
        stacked = [tiles[name] for name in plain[:music_player.ALBUM_MAX_TEXT_STACK]]
        self.assertEqual({b.rect.x for b in stacked}, {second_column_x})
        self.assertEqual([b.rect.y for b in stacked], sorted({b.rect.y for b in stacked}))
        self.assertEqual(len({b.rect.y for b in stacked}), len(stacked))
        # The tile past the limit is not stacked in the same slot.
        self.assertNotEqual((tiles[plain[-1]].rect.x, tiles[plain[-1]].rect.y),
                            (second_column_x, stacked[-1].rect.bottom + music_player.ALBUM_GAP))

    def test_only_deletable_albums_get_a_delete_button(self):
        player = self.make_player(["Mine", "Shipped"])
        with mock.patch.object(queries, "is_deletable_album", side_effect=lambda album: album == "Mine"):
            player.refresh_ui()

        delete_buttons = [b for b in self.album_buttons(player) if b.text == "X"]
        self.assertEqual(len(delete_buttons), 1)

    def test_new_album_tile_asks_for_a_name_only(self):
        player = self.make_player([])
        with mock.patch("ui.dialogs.ask_string") as ask:
            player.start_new_album()
        ask.assert_called_once()
        self.assertFalse(ask.call_args.kwargs.get("allow_empty", True))

    def test_create_album_reloads_and_reports_bad_names(self):
        player = self.make_player([])
        player.refresh_ui = mock.Mock()
        with mock.patch.object(queries, "create_album") as create:
            player.create_album("Fresh")
        create.assert_called_once_with("Fresh")
        player.controller.load_music_data.assert_called_once()

        with mock.patch.object(queries, "create_album", side_effect=ValueError("bad")), \
                mock.patch("ui.dialogs.show_error") as show_error:
            player.create_album("???")
        show_error.assert_called_once()

    def test_delete_needs_confirmation(self):
        player = self.make_player([])
        player.delete_album = mock.Mock()
        with mock.patch("ui.dialogs.ask_yes_no") as ask:
            player.start_delete_album("Mine")
            callback = ask.call_args.args[2]
        callback(False)
        player.delete_album.assert_not_called()
        callback(True)
        player.delete_album.assert_called_once_with("Mine")

    def test_album_with_the_playing_song_is_not_deleted(self):
        player = self.make_player([])
        player.controller.now_playing = f"{c.MUSIC_DIR}/Mine/song.mp3"
        with mock.patch.object(queries, "delete_album") as delete, \
                mock.patch("ui.dialogs.show_error") as show_error:
            player.delete_album("Mine")
        delete.assert_not_called()
        show_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
