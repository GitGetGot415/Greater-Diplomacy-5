import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main as game_main
import pygame
import data.constants as c
from data import queries
from ui.widgets.ui_elements import Button, Slider
from screens.menus.music_player import Music_Player, NEW_ALBUM_LABEL


def make_controller():
    controller = object.__new__(game_main.Controller)
    controller.playlist = []
    controller._failed_music_tracks = set()
    controller.shuffle_disabled_tracks = set()
    controller.now_playing = "None"
    controller._tactical_song_setting = None
    return controller


class ShuffleExclusionTests(unittest.TestCase):
    def test_albums_are_displayed_in_alphabetical_order(self):
        pygame.font.init()
        controller = SimpleNamespace(
            all_albums={"Alpha": [], "Zulu": [], "Bravo": []},
            active_albums=[],
            playlist=[],
            now_playing="None",
            is_shuffle_disabled=lambda path: False,
            sfx_volume=0.5,
            sfx_pitch=0.5,
            music_volume=0.5,
            music_pitch=0.5,
            music_pitch_timeline=c.MUSIC_PITCH_TIMELINE_STATIC,
            starting_song=None,
            music=None,
        )
        player = object.__new__(Music_Player)
        player.controller = controller
        player._scroll_album = 0
        player._scroll_track = 0
        player.handle_back_key = lambda: None

        player.refresh_ui()

        album_buttons = [
            button for button in player.elements
            if getattr(button, "pane", None) == "album" and button.text != "X"  # skip delete buttons
        ]
        self.assertEqual(
            [button.text for button in album_buttons],
            ["Alpha", "Bravo", "Zulu", NEW_ALBUM_LABEL],
        )

    def test_random_selection_skips_excluded_tracks(self):
        controller = make_controller()
        controller.playlist = ["skip.mp3", "play.mp3"]
        controller.shuffle_disabled_tracks = {"skip.mp3"}

        with patch.object(controller, "play_specific_song") as play_specific_song:
            controller.play_random_song()

        play_specific_song.assert_called_once_with("play.mp3")

    def test_preview_playlist_uses_shuffle_rules_without_replacing_the_normal_playlist(self):
        controller = make_controller()
        controller.playlist = ["editor.mp3"]
        controller.shuffle_disabled_tracks = {"skip.mp3"}
        controller._failed_music_tracks = {"failed.mp3"}
        with patch.object(controller, "play_specific_song") as play, patch.object(controller, "tactical_song_candidates") as tactical:
            controller.play_random_song(playlist=["skip.mp3", "failed.mp3", "preview.mp3"])
        play.assert_called_once_with("preview.mp3")
        tactical.assert_not_called()
        self.assertEqual(controller.playlist, ["editor.mp3"])

    def test_exclusion_persists_and_can_be_reversed(self):
        controller = make_controller()
        with patch.object(game_main, "queries", queries, create=True), \
                patch.object(queries, "save_cached_json") as save:
            controller.toggle_shuffle_disabled_track("album\\track.mp3")
            self.assertTrue(controller.is_shuffle_disabled("album/track.mp3"))
            save.assert_called_once_with(
                "shuffle_disabled_tracks", ["album/track.mp3"]
            )

            controller.toggle_shuffle_disabled_track("album/track.mp3")

        self.assertFalse(controller.is_shuffle_disabled("album/track.mp3"))
        self.assertEqual(
            save.call_args_list[-1].args,
            ("shuffle_disabled_tracks", []),
        )

    def test_excluded_song_remains_selectable_and_settings_match_controller(self):
        pygame.font.init()
        track_path = "assets/music/Album/track.mp3"
        controller = SimpleNamespace(
            all_albums={},
            playlist=[track_path],
            now_playing="None",
            is_shuffle_disabled=lambda path: path == track_path,
            sfx_volume=0.5,
            sfx_pitch=0.5,
            music_volume=0.5,
            music_pitch=0.5,
            music_pitch_timeline=c.MUSIC_PITCH_TIMELINE_STATIC,
            starting_song=None,
            music=None,
        )
        player = object.__new__(Music_Player)
        player.controller = controller
        player._scroll_album = 0
        player._scroll_track = 0
        player.handle_back_key = lambda: None

        player.refresh_ui()

        song_button = next(button for button in player.elements if button.text == "track.mp3")
        self.assertFalse(song_button.disabled)

        static_button = next(button for button in player.elements
                             if isinstance(button, Button) and button.text == "Static")
        dynamic_button = next(button for button in player.elements
                              if isinstance(button, Button) and button.text == "Dynamic")
        self.assertTrue(static_button.is_selected)
        self.assertFalse(dynamic_button.is_selected)

        sfx_pitch_slider = next(element for element in player.elements
                                if isinstance(element, Slider)
                                and element.text == "SFX Pitch")
        self.assertEqual(sfx_pitch_slider.value, controller.sfx_pitch)

    def test_timeline_help_explains_modes_and_shuffle_exclusions(self):
        player = object.__new__(Music_Player)

        with patch("ui.dialogs.show_info") as show_info:
            player.show_timeline_and_queue_help()

        title, message = show_info.call_args.args
        self.assertEqual(title, "Music Player Help")
        self.assertIn("Static", message)
        self.assertIn("Dynamic", message)
        self.assertIn("S", message)

    def test_non_excluded_song_button_remains_selectable(self):
        pygame.font.init()
        track_path = "assets/music/Album/track.mp3"
        controller = SimpleNamespace(
            all_albums={},
            playlist=[track_path],
            now_playing="None",
            is_shuffle_disabled=lambda path: False,
            sfx_volume=0.5,
            sfx_pitch=0.5,
            music_volume=0.5,
            music_pitch=0.5,
            music_pitch_timeline=c.MUSIC_PITCH_TIMELINE_STATIC,
            starting_song=None,
            music=None,
        )
        player = object.__new__(Music_Player)
        player.controller = controller
        player._scroll_album = 0
        player._scroll_track = 0
        player.handle_back_key = lambda: None

        player.refresh_ui()

        song_button = next(button for button in player.elements if button.text == "track.mp3")
        self.assertFalse(song_button.disabled)

    def test_ui_toggle_delegates_to_the_controller(self):
        player = object.__new__(Music_Player)
        player.controller = SimpleNamespace(toggle_shuffle_disabled_track=Mock())
        player.refresh_ui = Mock()

        player.toggle_shuffle_exclusion("track.mp3")

        player.controller.toggle_shuffle_disabled_track.assert_called_once_with("track.mp3")
        player.refresh_ui.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
