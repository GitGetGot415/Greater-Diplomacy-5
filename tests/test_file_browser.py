"""The file browser's selection, navigation, sorting, and keyboard rules."""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import data.constants as c
from ui.dialogs import file_browser_screen as fb


def key(code, unicode="", mod=0):
    return pygame.event.Event(pygame.KEYDOWN, key=code, unicode=unicode, mod=mod)


class FileBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = os.path.realpath(directory.name)
        os.mkdir(self.path("alpha"))
        os.mkdir(self.path("beta"))
        self.write("a.zip", 300)
        self.write("b.zip", 100)
        self.write("c.zip", 200)
        self.write("notes.txt", 10)
        self.write(os.path.join("alpha", "inner.zip"), 5)
        self.picked = []

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def write(self, name, size):
        with open(self.path(name), "wb") as file:
            file.write(b"x" * size)

    def browser(self, mode="open_file", extensions=(".zip",), start=None):
        return fb.FileBrowserScreen(None, "Test", start or self.root, self.picked.append,
                                    mode=mode, extensions=extensions)

    def names(self, screen):
        return [entry.name for entry in screen.entries]

    def entry(self, screen, name):
        return next(entry for entry in screen.entries if entry.name == name)

    def click(self, screen, name, mods=0, tick=0):
        with mock.patch.object(pygame.key, "get_mods", return_value=mods), \
                mock.patch.object(pygame.time, "get_ticks", return_value=tick):
            screen._row_click(self.entry(screen, name))

    def test_folders_stay_first_and_columns_sort_both_ways(self):
        screen = self.browser()
        self.assertEqual(self.names(screen), ["alpha", "beta", "a.zip", "b.zip", "c.zip"])

        screen._set_sort("size")
        self.assertEqual(self.names(screen), ["alpha", "beta", "b.zip", "c.zip", "a.zip"])
        screen._set_sort("size")
        self.assertEqual(self.names(screen), ["beta", "alpha", "a.zip", "c.zip", "b.zip"])

    def test_folder_and_file_rows_play_one_selection_sound_and_keep_their_targets(self):
        for name, expected_sound in (("alpha", "select_category"), ("a.zip", "select_sub_category")):
            with self.subTest(name=name):
                screen = self.browser()
                index = self.names(screen).index(name)
                row = [element for element in screen.elements if isinstance(element, fb.FileRow)][index]
                with mock.patch.object(fb.ui_elements, "play_ui_sound") as sound, \
                        mock.patch.object(pygame.mouse, "get_pos", return_value=row.rect.center):
                    for event in (
                        pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=row.rect.center, button=1),
                        pygame.event.Event(pygame.MOUSEBUTTONUP, pos=row.rect.center, button=1),
                    ):
                        row.handle_event(event)
                sound.assert_called_once_with(expected_sound)
                self.assertEqual(screen.cursor, self.path(name))
                self.assertEqual(self.picked, [])

    def test_one_click_selects_a_folder_and_a_double_click_opens_it(self):
        screen = self.browser()
        self.click(screen, "alpha")
        self.assertEqual(screen.current_dir, self.root)
        self.assertEqual(screen.selected_folder, self.path("alpha"))

        self.click(screen, "alpha", tick=100)
        self.assertEqual(screen.current_dir, self.path("alpha"))
        self.assertIsNone(screen.selected_folder)

    def test_slow_clicks_do_not_open(self):
        screen = self.browser()
        self.click(screen, "alpha")
        self.click(screen, "alpha", tick=screen.DOUBLE_CLICK_MS + 1)
        self.assertEqual(screen.current_dir, self.root)

    def test_double_click_confirms_a_single_file(self):
        screen = self.browser()
        self.click(screen, "a.zip")
        self.assertEqual(self.picked, [])
        self.click(screen, "a.zip", tick=100)
        self.assertEqual(self.picked, [self.path("a.zip")])
        self.assertTrue(screen.done)

    def test_mouse_press_and_release_reach_the_row_click(self):
        screen = self.browser()
        row = next(el for el in screen.elements if isinstance(el, fb.FileRow))
        pos = row.rect.center
        with mock.patch.object(pygame.mouse, "get_pos", return_value=pos):
            screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1),
                                  pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)])
        self.assertEqual(screen.selected_folder, self.path("alpha"))

    def test_history_moves_back_and_forward_and_new_navigation_clears_forward(self):
        screen = self.browser()
        screen._navigate(self.path("alpha"))
        screen._history_back()
        self.assertEqual(screen.current_dir, self.root)
        screen._history_forward()
        self.assertEqual(screen.current_dir, self.path("alpha"))

        screen._history_back()
        screen._navigate(self.path("beta"))
        self.assertEqual(screen.forward_stack, [])
        self.assertEqual(screen.back_stack, [self.root])

    def test_opening_the_current_folder_adds_no_history(self):
        screen = self.browser()
        screen._navigate(self.root)
        self.assertEqual(screen.back_stack, [])

    def test_ctrl_and_shift_build_a_multi_select(self):
        screen = self.browser("open_files")
        self.click(screen, "a.zip")
        self.click(screen, "c.zip", mods=pygame.KMOD_CTRL, tick=1000)
        self.assertEqual(screen.selected, {self.path("a.zip"), self.path("c.zip")})

        self.click(screen, "c.zip", mods=pygame.KMOD_CTRL, tick=2000)
        self.assertEqual(screen.selected, {self.path("a.zip")})

        # A Shift range starts at the last row clicked without Shift.
        self.click(screen, "a.zip", tick=3000)
        self.click(screen, "c.zip", mods=pygame.KMOD_SHIFT, tick=4000)
        self.assertEqual(screen.selected, {self.path(n) for n in ("a.zip", "b.zip", "c.zip")})

    def test_quick_ctrl_clicks_do_not_confirm(self):
        screen = self.browser("open_files")
        self.click(screen, "a.zip", mods=pygame.KMOD_CTRL)
        self.click(screen, "a.zip", mods=pygame.KMOD_CTRL, tick=50)
        self.assertEqual(self.picked, [])

    def test_multi_select_survives_navigation_and_a_plain_click_elsewhere(self):
        screen = self.browser("open_files")
        self.click(screen, "a.zip")
        screen._navigate(self.path("alpha"))
        self.click(screen, "inner.zip", tick=1000)
        self.assertEqual(screen.selected, {self.path("a.zip"), self.path("alpha", "inner.zip")})

        screen._open_action()
        self.assertEqual(self.picked, [sorted(screen.selected)])

    def test_single_file_selection_clears_on_navigation(self):
        screen = self.browser()
        self.click(screen, "a.zip")
        screen._navigate(self.path("alpha"))
        self.assertEqual(screen.selected, set())
        self.assertEqual(screen.name_field.text, "")

    def test_folder_mode_returns_the_highlight_or_else_the_current_folder(self):
        screen = self.browser("select_folder", extensions=None)
        self.assertEqual(self.names(screen), ["alpha", "beta"])
        screen._open_action()
        self.assertEqual(self.picked, [self.root])

        self.picked.clear()
        screen = self.browser("select_folder", extensions=None)
        self.click(screen, "beta")
        screen._open_action()
        self.assertEqual(self.picked, [self.path("beta")])

    def test_open_with_a_highlighted_folder_enters_it_instead_of_confirming(self):
        screen = self.browser()
        self.click(screen, "alpha")
        screen._open_action()
        self.assertEqual(screen.current_dir, self.path("alpha"))
        self.assertEqual(self.picked, [])

    def test_typed_name_is_relative_to_the_folder_and_confirms(self):
        screen = self.browser()
        screen.name_field.text = "b.zip"
        screen._open_action()
        self.assertEqual(self.picked, [self.path("b.zip")])

    def test_typed_name_that_does_not_exist_reports_and_keeps_the_text(self):
        screen = self.browser()
        screen.name_field.text = "missing.zip"
        screen._open_action()
        self.assertEqual(self.picked, [])
        self.assertTrue(screen.status)
        self.assertEqual(screen.name_field.text, "missing.zip")

    def test_typed_file_outside_the_filter_turns_the_filter_off(self):
        screen = self.browser()
        screen.path_field.text = self.path("notes.txt")
        screen._submit_path()
        self.assertTrue(screen.show_all_types)
        self.assertEqual(screen.selected, {self.path("notes.txt")})
        self.assertEqual(self.picked, [])

    def test_file_type_menu_changes_the_filter_and_blocks_controls_under_it(self):
        screen = self.browser()
        self.assertNotIn("notes.txt", self.names(screen))
        screen._toggle_type_menu()
        all_files = screen._menu_buttons[-1]
        pos = all_files.rect.center
        with mock.patch.object(pygame.mouse, "get_pos", return_value=pos):
            screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1),
                                  pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)])
        self.assertFalse(screen.type_menu_open)
        self.assertIn("notes.txt", self.names(screen))

        screen._toggle_type_menu()
        outside = screen.list_rect.center
        screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=outside, button=1)])
        self.assertFalse(screen.type_menu_open)
        self.assertIsNone(screen.selected_folder)

    def test_hidden_toggle_shows_dot_files(self):
        self.write(".secret.zip", 1)
        screen = self.browser()
        self.assertNotIn(".secret.zip", self.names(screen))
        screen._toggle_hidden()
        self.assertIn(".secret.zip", self.names(screen))

    def test_arrow_keys_type_ahead_and_enter(self):
        screen = self.browser()
        screen.handle_events([key(pygame.K_DOWN), key(pygame.K_DOWN)])
        self.assertEqual(screen.selected_folder, self.path("beta"))
        screen.handle_events([key(pygame.K_UP)])
        self.assertEqual(screen.selected_folder, self.path("alpha"))

        with mock.patch.object(pygame.time, "get_ticks", return_value=10_000):
            screen.handle_events([key(pygame.K_c, "c")])
        self.assertEqual(screen.selected, {self.path("c.zip")})
        screen.handle_events([key(pygame.K_RETURN)])
        self.assertEqual(self.picked, [self.path("c.zip")])

    def test_backspace_and_alt_arrows_navigate(self):
        screen = self.browser(start=self.path("alpha"))
        screen.handle_events([key(pygame.K_BACKSPACE)])
        self.assertEqual(screen.current_dir, self.root)
        screen.handle_events([key(pygame.K_LEFT, mod=pygame.KMOD_ALT)])
        self.assertEqual(screen.current_dir, self.path("alpha"))
        screen.handle_events([key(pygame.K_RIGHT, mod=pygame.KMOD_ALT)])
        self.assertEqual(screen.current_dir, self.root)

    def test_typing_in_a_field_does_not_move_the_list(self):
        screen = self.browser()
        screen.name_field.active = True
        screen.handle_events([key(pygame.K_c, "c"), key(pygame.K_BACKSPACE)])
        self.assertEqual(screen.current_dir, self.root)
        self.assertEqual(screen.selected, set())

    def test_enter_in_the_name_field_confirms_only_once(self):
        screen = self.browser()
        screen.name_field.active = True
        screen.name_field.text = "a.zip"
        screen.handle_events([key(pygame.K_RETURN)])
        self.assertEqual(self.picked, [self.path("a.zip")])

    def test_back_key_cancels_an_edit_before_closing(self):
        screen = self.browser()
        screen.path_field.active = True
        screen.path_field.text = "typed"
        screen.handle_back_key()
        self.assertFalse(screen.done)
        self.assertFalse(screen.path_field.active)
        self.assertEqual(screen.path_field.text, self.root)

        screen.handle_back_key()
        self.assertTrue(screen.done)
        self.assertEqual(self.picked, [])

    def test_breadcrumb_click_navigates_and_empty_bar_starts_typing(self):
        screen = self.browser(start=self.path("alpha"))
        crumb = screen._crumbs[-2]
        pos = crumb.rect.center
        with mock.patch.object(pygame.mouse, "get_pos", return_value=pos):
            screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1),
                                  pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)])
        self.assertEqual(screen.current_dir, self.root)
        self.assertFalse(screen.path_field.active)

        pos = (screen.path_field.rect.right - 2, screen.path_field.rect.centery)
        with mock.patch.object(pygame.mouse, "get_pos", return_value=pos):
            screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1)])
        self.assertTrue(screen.path_field.active)
        self.assertEqual(screen._crumbs, [])

    def test_breadcrumbs_reach_every_parent(self):
        segments = fb.breadcrumbs(self.path("alpha"))
        self.assertEqual(segments[-1], ("alpha", self.path("alpha")))
        self.assertEqual(segments[-2][1], self.root)
        if fb.IS_WINDOWS:
            self.assertEqual(segments[0], (fb.DRIVE_VIEW_LABEL, fb.DRIVE_VIEW))

    def test_clicking_empty_space_clears_only_this_folders_selection(self):
        screen = self.browser("open_files")
        self.click(screen, "a.zip")
        screen._navigate(self.path("alpha"))
        self.click(screen, "inner.zip", tick=1000)
        pos = (screen.rows_rect.centerx, screen.rows_rect.bottom - 2)
        screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1)])
        self.assertEqual(screen.selected, {self.path("a.zip")})

    def test_sizes_and_dates_format_for_display(self):
        self.assertEqual(fb.format_size(512), "512 B")
        self.assertEqual(fb.format_size(1536), "1.5 KB")
        self.assertEqual(fb.format_size(None), "")
        self.assertEqual(fb.format_modified(None), "")

    def test_every_icon_name_has_a_file(self):
        names = {fb.FOLDER_ICON, fb.HOME_ICON, fb.DOWNLOADS_ICON, fb.DRIVE_ICON, fb.FILE_ICON,
                 *fb.EXTENSION_ICONS.values()}
        # Compares exact names, because macOS and Linux paths are case-sensitive.
        self.assertLessEqual(names, set(os.listdir(c.FILE_SYSTEM_ICONS_DIR)))

    def test_entry_icon_follows_the_kind_and_extension(self):
        screen = self.browser()
        with mock.patch.object(screen, "_icon", side_effect=lambda name: name):
            self.assertEqual(screen._entry_icon(self.entry(screen, "alpha")), fb.FOLDER_ICON)
            self.assertEqual(screen._entry_icon(fb.Entry("A.ZIP", "file", 1, 0, "")), fb.EXTENSION_ICONS[".zip"])
            self.assertEqual(screen._entry_icon(fb.Entry("a.unknown", "file", 1, 0, "")), fb.FILE_ICON)
            screen._show(fb.DRIVE_VIEW)
            self.assertEqual(screen._entry_icon(screen.entries[0]), fb.DRIVE_ICON)

    def test_tournament_files_have_their_own_icons(self):
        self.assertEqual(fb.EXTENSION_ICONS[".gd5tour"], "GD5TOUR.png")
        self.assertEqual(fb.EXTENSION_ICONS[".gd5move"], "GD5MOVE.png")

    def test_vector_and_text_files_have_their_own_icons(self):
        self.assertEqual(fb.EXTENSION_ICONS[".svg"], "SVG.png")
        self.assertEqual(fb.EXTENSION_ICONS[".txt"], "Text.png")

    def test_home_and_downloads_folders_get_their_icons_in_the_list_and_sidebar(self):
        home, downloads = self.path("alpha"), self.path("beta")
        screen = self.browser()
        with mock.patch.object(fb.os.path, "expanduser", return_value=home), \
                mock.patch.object(fb, "downloads_dir", return_value=downloads), \
                mock.patch.object(screen, "_icon", side_effect=lambda name: name):
            self.assertEqual(screen._entry_icon(self.entry(screen, "alpha")), fb.HOME_ICON)
            self.assertEqual(screen._entry_icon(self.entry(screen, "beta")), fb.DOWNLOADS_ICON)
            screen.places = [("Home", home), ("Downloads", downloads), ("Other", self.root)]
            screen.refresh_ui()
            icons = [el.image for el in screen.elements if isinstance(el, fb.Button) and el.image]
        self.assertEqual(icons, [fb.HOME_ICON, fb.DOWNLOADS_ICON, fb.FOLDER_ICON])


if __name__ == "__main__":
    unittest.main()
