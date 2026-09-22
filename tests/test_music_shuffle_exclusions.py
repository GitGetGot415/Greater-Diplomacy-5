import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main as game_main
import pygame
import data.constants as c
from data import queries
from ui_elements import Button, Slider
from screens.menu_screens.music_player import (
    MUSIC_LEFT_PANE_W,
    MUSIC_PROGRESS_X,
    MUSIC_PROGRESS_SIZE,
    MUSIC_TIMELINE_BUTTON_GAP,
    MUSIC_TIMELINE_BUTTON_X,
    TRACK_SHUFFLE_TOGGLE_GAP,
    Music_Player,
)


def make_controller():
    controller = object.__new__(game_main.Controller)
    controller.playlist = []
    controller._failed_beepbox_tracks = set()
    controller.shuffle_disabled_tracks = set()
    controller.now_playing = "None"
    return controller


class ShuffleExclusionTests(unittest.TestCase):
    def test_random_selection_skips_excluded_tracks(self):
        controller = make_controller()
        controller.playlist = ["skip.mp3", "play.mp3"]
        controller.shuffle_disabled_tracks = {"skip.mp3"}

        with patch.object(controller, "play_specific_song") as play_specific_song:
            controller.play_random_song()

        play_specific_song.assert_called_once_with("play.mp3")

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

    def test_excluded_song_button_is_disabled_and_toggle_is_right_and_green(self):
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
            is_paused=False,
        )
        player = object.__new__(Music_Player)
        player.controller = controller
        player._scroll_album = 0
        player._scroll_track = 0
        player.handle_back_key = lambda: None

        player.refresh_ui()

        song_button = next(button for button in player.elements if button.text == "track.mp3")
        exclusion_button = next(button for button in player.elements if button.text == "X")
        self.assertTrue(song_button.disabled)
        self.assertEqual(exclusion_button.rect.left,
                         song_button.rect.right + TRACK_SHUFFLE_TOGGLE_GAP)
        self.assertEqual(exclusion_button.color, c.UI_COLORS["green"][0])

        static_button = next(button for button in player.elements
                             if isinstance(button, Button) and button.text == "Static")
        dynamic_button = next(button for button in player.elements
                              if isinstance(button, Button) and button.text == "Dynamic")
        self.assertEqual(static_button.rect.left, MUSIC_TIMELINE_BUTTON_X)
        self.assertGreaterEqual(static_button.rect.left,
                                MUSIC_PROGRESS_X + MUSIC_PROGRESS_SIZE[0])
        self.assertEqual(dynamic_button.rect.left,
                         static_button.rect.right + MUSIC_TIMELINE_BUTTON_GAP)
        self.assertTrue(static_button.is_selected)
        self.assertFalse(dynamic_button.is_selected)

        sfx_pitch_slider = next(element for element in player.elements
                                if isinstance(element, Slider)
                                and element.text == "SFX Pitch")
        self.assertEqual(sfx_pitch_slider.value, controller.sfx_pitch)

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
            is_paused=False,
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
