"""Covers the four dialogs in ui/dialogs/.

They are pushed onto the modal stack from deep inside other screens, so nothing
else in the suite reaches them -- and they all now share one base class, so a
mistake in the shared half breaks every dialog at once.

Tests drive the in-game modal stack, where run_screen wraps each dialog screen.
Standalone checks drive run_screen's own window with a closed-window event.
"""

import unittest
from pathlib import Path
import tempfile
from unittest import mock

import pygame

import data.constants as c
from tests import app_harness
from ui import dialogs
from ui.navigation import modal_stack
from ui import sound_effects


def key(k):
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode="", mod=0, scancode=0)


def typed(ch):
    return pygame.event.Event(pygame.KEYDOWN, key=ord(ch), unicode=ch, mod=0, scancode=0)


def click(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1)


def release(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)


def press(pos):
    """A full click: dialog buttons answer on release, like every Button."""
    return [click(pos), release(pos)]


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _controller, cls.surface = app_harness.boot()
        # Other test modules can resize the cached application display.
        cls.surface = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))

    def setUp(self):
        while not modal_stack.is_empty():
            modal_stack.pop()
        self.answers = []

    def dialog(self):
        """The dialog screen on top of the modal stack."""
        wrapper = modal_stack.active()
        self.assertIsNotNone(wrapper, "dialog was not pushed onto the modal stack")
        return wrapper.screen

    def settle(self):
        """Runs the one update() that pops the modal and delivers the answer."""
        modal = modal_stack.active()
        self.assertIsNotNone(modal, "dialog was not pushed onto the modal stack")
        modal.draw(self.surface)
        modal.update()
        return modal

    # -- ask_yes_no ------------------------------------------------------

    def test_yes_no_confirms(self):
        dialogs.ask_yes_no("T", "Sure?", self.answers.append)
        modal = self.dialog()
        modal.handle_events(press(modal.yes_rect.center))
        self.settle()
        self.assertEqual(self.answers, [True])
        self.assertTrue(modal_stack.is_empty())

    def test_yes_no_cancels(self):
        dialogs.ask_yes_no("T", "Sure?", self.answers.append)
        modal = self.dialog()
        modal.handle_events(press(modal.no_rect.center))
        self.settle()
        self.assertEqual(self.answers, [False])

    def test_yes_no_keyboard(self):
        for k, expected in ((pygame.K_y, True), (pygame.K_n, False),
                            (pygame.K_RETURN, True), (pygame.K_ESCAPE, False)):
            with self.subTest(key=k):
                self.answers.clear()
                dialogs.ask_yes_no("T", "Sure?", self.answers.append)
                modal_stack.active().handle_events([key(k)])
                self.settle()
                self.assertEqual(self.answers, [expected])

    def test_three_choice_dialog_buttons_return_distinct_results(self):
        for rectangle, expected in (("yes_rect", True), ("no_rect", False), ("back_rect", None)):
            with self.subTest(rectangle=rectangle):
                self.answers.clear()
                dialogs.ask_yes_no("T", "Save, discard, or return?", self.answers.append,
                                          yes_label="Save", no_label="Cancel", back_label="Go back")
                modal = self.dialog()
                modal.handle_events(press(getattr(modal, rectangle).center))
                self.settle()
                self.assertEqual(self.answers, [expected])

    def test_three_choice_keyboard_returns_to_screen_on_back(self):
        for keyboard_key, expected in ((pygame.K_RETURN, True), (pygame.K_n, False),
                                       (pygame.K_ESCAPE, None), (pygame.K_g, None), (pygame.K_F8, None)):
            with self.subTest(key=keyboard_key), mock.patch(
                    "ui.navigation.screen.queries.get_keybind",
                    side_effect=lambda action, default: pygame.K_F8 if action == "BACK" else default):
                self.answers.clear()
                dialogs.ask_yes_no("T", "Save?", self.answers.append, back_label="Go back")
                modal_stack.active().handle_events([key(keyboard_key)])
                self.settle()
                self.assertEqual(self.answers, [expected])

    def standalone_window_closed(self):
        """A standalone tool with no game display, whose window the user closes."""
        from ui.navigation import screen_runner
        return (mock.patch.object(screen_runner.ui_bars, "acquire_surface", return_value=(self.surface, True)),
                mock.patch.object(screen_runner.ui_bars, "release_surface"),
                mock.patch.object(pygame.event, "get", return_value=[pygame.event.Event(pygame.QUIT)]))

    def test_closing_a_standalone_three_choice_window_answers_go_back(self):
        acquire, release, quit_event = self.standalone_window_closed()
        with acquire, release, quit_event:
            dialogs.ask_yes_no("T", "Save?", self.answers.append, back_label="Go back")
        self.assertEqual(self.answers, [None])

    def test_closing_a_standalone_two_choice_window_answers_no(self):
        acquire, release, quit_event = self.standalone_window_closed()
        with acquire, release, quit_event:
            dialogs.ask_yes_no("T", "Save?", self.answers.append)
        self.assertEqual(self.answers, [False])

    def test_closing_a_standalone_text_window_answers_cancelled(self):
        acquire, release, quit_event = self.standalone_window_closed()
        with acquire, release, quit_event:
            dialogs.ask_string("T", "Name?", self.answers.append)
        self.assertEqual(self.answers, [None])

    def test_closing_a_standalone_message_window_calls_back_without_arguments(self):
        calls = []
        acquire, release, quit_event = self.standalone_window_closed()
        with acquire, release, quit_event:
            dialogs.show_message("T", "Done.", on_result=lambda: calls.append(True))
        self.assertEqual(calls, [True])

    # -- ask_string / ask_integer ---------------------------------------

    def test_ask_string_returns_typed_text(self):
        dialogs.ask_string("T", "Name?", self.answers.append)
        modal = self.dialog()
        modal.handle_events([typed("a"), typed("b"), key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, ["ab"])

    def test_ask_string_backspace(self):
        dialogs.ask_string("T", "Name?", self.answers.append)
        modal = self.dialog()
        modal.handle_events([typed("a"), typed("b"), key(pygame.K_BACKSPACE),
                             key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, ["a"])

    def test_text_input_clear_control_erases_the_current_value(self):
        dialogs.ask_string("T", "Name?", self.answers.append, initial="wrong invite")
        modal = self.dialog()
        modal.handle_events([*press(modal.clear_rect.center), typed("r"), key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, ["r"])

    def test_ask_string_accepts_clipboard_paste(self):
        dialogs.ask_string("T", "Name?", self.answers.append)
        modal = self.dialog()
        paste = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_v, unicode="", mod=pygame.KMOD_CTRL)
        with mock.patch("ui.widgets.ui_elements._clipboard_text", return_value="Pasted name"):
            modal.handle_events([paste, key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, ["Pasted name"])

    def test_ask_string_accepts_macos_command_v_paste(self):
        dialogs.ask_string("T", "Name?", self.answers.append)
        modal = self.dialog()
        paste = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_v, unicode="", mod=pygame.KMOD_GUI)
        with mock.patch("ui.widgets.ui_elements._clipboard_text", return_value="Pasted on Mac"):
            modal.handle_events([paste, key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, ["Pasted on Mac"])

    def test_clipboard_falls_back_to_macos_pbpaste(self):
        from ui.widgets import ui_elements

        pbpaste = mock.Mock(returncode=0, stdout=b"From the Mac clipboard\x00")
        with mock.patch.object(ui_elements.sys, "platform", "darwin"), \
             mock.patch.object(ui_elements.pygame.scrap, "get_init", return_value=True), \
             mock.patch.object(ui_elements.pygame.scrap, "get", return_value=b""), \
             mock.patch.object(ui_elements.subprocess, "run", return_value=pbpaste) as run:
            self.assertEqual(ui_elements._clipboard_text(), "From the Mac clipboard")

        run.assert_called_once_with(
            ["/usr/bin/pbpaste"],
            stdout=ui_elements.subprocess.PIPE,
            stderr=ui_elements.subprocess.DEVNULL,
            check=False,
            timeout=1,
        )

    def test_ask_string_cancel_yields_none(self):
        dialogs.ask_string("T", "Name?", self.answers.append)
        modal_stack.active().handle_events([key(pygame.K_ESCAPE)])
        self.settle()
        self.assertEqual(self.answers, [None])

    def test_ask_string_max_length_stops_new_characters(self):
        dialogs.ask_string("T", "Name?", self.answers.append, initial="ab", max_length=3)
        modal = self.dialog()
        modal.handle_events([typed("c"), typed("d"), key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, ["abc"])

    def test_ask_integer_accepts_digits(self):
        dialogs.ask_integer("T", "How many?", self.answers.append)
        modal = self.dialog()
        modal.handle_events([typed("4"), typed("2"), key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, [42])

    def test_ask_integer_rejects_out_of_range(self):
        """A rejected value must keep the dialog open with an error, not resolve."""
        dialogs.ask_integer("T", "1-10?", self.answers.append, minvalue=1, maxvalue=10)
        modal = self.dialog()
        modal.handle_events([typed("9"), typed("9"), key(pygame.K_RETURN)])
        self.assertFalse(modal.done)
        self.assertNotEqual(modal.error_text, "")
        modal.draw(self.surface)

    # -- show_message ----------------------------------------------------

    def test_show_message_closes_without_a_result(self):
        calls = []
        dialogs.show_message("T", "Done.", on_result=lambda: calls.append(True))
        modal = self.dialog()
        with mock.patch.object(sound_effects, "play_ui_sound") as sound:
            modal.handle_events([click(modal.ok_rect.center)])
            self.assertFalse(modal.done)
            sound.assert_not_called()
            modal.handle_events([release(modal.ok_rect.center)])
            sound.assert_called_once_with("back")
            modal.handle_events([click(modal.ok_rect.center), release(modal.ok_rect.center)])
            sound.assert_called_once_with("back")
        self.settle()
        self.assertEqual(calls, [True])
        self.assertTrue(modal_stack.is_empty())

    def test_message_ok_cancels_when_released_outside_like_other_buttons(self):
        dialogs.show_info("T", "Help text.")
        modal = self.dialog()
        outside = (modal.ok_rect.left - 10, modal.ok_rect.centery)
        with mock.patch.object(sound_effects, "play_ui_sound") as sound:
            modal.handle_events([click(modal.ok_rect.center), release(outside)])
            self.assertFalse(modal.done)
            modal.handle_events([click(outside), release(modal.ok_rect.center)])
            self.assertFalse(modal.done)
            sound.assert_not_called()
            modal.handle_events([click(modal.ok_rect.center), release(modal.ok_rect.center)])
            sound.assert_called_once_with("back")
        self.settle()
        self.assertTrue(modal_stack.is_empty())

    def test_only_the_blue_popups_play_the_help_and_back_sounds(self):
        for kind, opened, clicked in (("info", ["info"], "back"), ("success", [], "click"),
                                      ("warning", [], "click"), ("error", [], "click")):
            with self.subTest(kind=kind), mock.patch.object(sound_effects, "play_ui_sound") as sound:
                dialogs.show_message("T", "Body.", kind=kind)
                modal = self.dialog()
                self.assertEqual([call.args[0] for call in sound.call_args_list], opened)
                sound.reset_mock()
                modal.handle_events([click(modal.ok_rect.center), release(modal.ok_rect.center)])
                sound.assert_called_once_with(clicked)
                modal_stack.pop()

    def test_credits_popup_uses_the_blue_popup_button_and_sounds(self):
        with mock.patch.object(sound_effects, "play_ui_sound") as sound:
            dialogs.show_person_info("Name", "Some blurb.", [])
            sound.assert_called_once_with("info")
            sound.reset_mock()
            modal = self.dialog()
            self.assertEqual(modal.ok_button.text, "OK")
            modal.handle_events([click(modal.ok_rect.center)])
            self.assertFalse(modal.done)
            modal.handle_events([release(modal.ok_rect.center)])
            sound.assert_called_once_with("back")
        self.settle()
        self.assertTrue(modal_stack.is_empty())

    def test_info_button_leaves_the_help_sound_to_the_popup(self):
        from ui.widgets.ui_elements import make_info_button
        with mock.patch.object(sound_effects, "play_ui_sound") as sound:
            button = make_info_button(10, 10, lambda: dialogs.show_info("T", "Help text."))
            button.handle_event(click(button.rect.center))
            button.handle_event(release(button.rect.center))
            sound.assert_called_once_with("info")
        modal_stack.pop()

    def test_keyboard_close_plays_back_once_on_blue_popups_only(self):
        for open_popup, expected in ((lambda: dialogs.show_info("T", "Body."), ["back"]),
                                     (lambda: dialogs.show_person_info("Name", "Blurb.", []), ["back"]),
                                     (lambda: dialogs.show_error("T", "Body."), [])):
            for pressed in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_SPACE):
                with self.subTest(expected=expected, key=pressed):
                    open_popup()
                    modal = self.dialog()
                    with mock.patch.object(sound_effects, "play_ui_sound") as sound:
                        modal.handle_events([key(pressed), key(pressed)])
                    self.assertTrue(modal.done)
                    self.assertEqual([call.args[0] for call in sound.call_args_list], expected)
                    modal_stack.pop()

    def test_credits_arrow_keys_scroll_without_closing_or_a_sound(self):
        dialogs.show_person_info("Name", "Blurb.", [])
        modal = self.dialog()
        with mock.patch.object(sound_effects, "play_ui_sound") as sound:
            modal.handle_events([key(pygame.K_DOWN)])
        self.assertFalse(modal.done)
        sound.assert_not_called()
        modal_stack.pop()

    def test_message_kinds_all_render(self):
        for kind in ("info", "success", "warning", "error"):
            with self.subTest(kind=kind):
                dialogs.show_message("T", "Body text.", kind=kind)
                modal = self.dialog()
                modal.draw(self.surface)
                modal_stack.pop()

    def test_show_message_with_no_callback(self):
        dialogs.show_message("T", "Body.")
        modal = self.dialog()
        modal.handle_events([key(pygame.K_RETURN)])
        self.settle()
        self.assertTrue(modal_stack.is_empty())

    def long_message_modal(self, inline):
        from ui.dialogs.message_box import _MessageModal
        text = "\n".join(f"Help line {n}." for n in range(60))
        return _MessageModal(pygame.Surface((520, 320)), "Help", text, "info",
                             inline_parts=[(text, None)] if inline else None)

    def test_long_help_text_stops_at_the_window_and_scrolls_like_credits(self):
        for inline in (False, True):
            with self.subTest(inline=inline):
                modal = self.long_message_modal(inline)
                self.assertLessEqual(modal.panel_rect.bottom, 320)
                self.assertGreater(modal.max_scroll, 0)
                self.assertIsNotNone(modal.scroll_track_rect)
                modal.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, y=-1000)])
                self.assertEqual(modal.scroll_y, modal.max_scroll)
                modal.handle_events([key(pygame.K_PAGEUP)])
                self.assertLess(modal.scroll_y, modal.max_scroll)
                modal.handle_events([key(pygame.K_UP)] * 100)
                self.assertEqual(modal.scroll_y, 0)
                track = modal.scroll_track_rect
                modal.handle_events([click((track.centerx, track.bottom - 1))])
                self.assertEqual(modal.scroll_y, modal.max_scroll)
                surface = pygame.Surface((520, 320))
                modal.draw(surface)
                self.assertEqual(surface.get_clip(), surface.get_rect())
                modal.handle_events([click(modal.ok_rect.center), release(modal.ok_rect.center)])
                self.assertTrue(modal.done)

    def test_help_text_that_fits_has_no_scrollbar(self):
        dialogs.show_info("T", "Help text.")
        modal = self.dialog()
        self.assertEqual(modal.max_scroll, 0)
        self.assertIsNone(modal.scroll_track_rect)
        modal_stack.pop()

    def test_long_credit_text_without_images_scrolls(self):
        """Credits used to scroll only when an entry had images."""
        from ui.dialogs.person_info import _PersonInfoModal
        modal = _PersonInfoModal(pygame.Surface((520, 320)), "Artist",
                                 "\n".join(f"Line {n}." for n in range(60)), [], None)
        self.assertGreater(modal.max_scroll, 0)
        self.assertIsNotNone(modal.scroll_track_rect)

    # -- show_person_info ------------------------------------------------

    def test_person_info_renders_links(self):
        links = [{"text": "Site", "url": "https://example.invalid"}, {"text": "No link"}]
        dialogs.show_person_info("Name", "Some blurb.", links)
        modal = self.dialog()
        self.assertEqual(len(modal.link_rects), 2)
        modal.draw(self.surface)
        modal.handle_events([key(pygame.K_ESCAPE)])
        self.settle()
        self.assertTrue(modal_stack.is_empty())

    def test_person_info_without_links_or_text(self):
        dialogs.show_person_info("Name", "", [])
        modal_stack.active().draw(self.surface)
        modal_stack.pop()

    def credited_images(self):
        from screens.menus.credits import CREDITS_DATA
        from ui.dialogs.person_info import expand_credit_images
        return next(images for entry in CREDITS_DATA
                    for person in entry.get("people", [])
                    for images in [expand_credit_images(person.get("images"))] if images
                    and all(Path(image["path"]).parent == Path(c.ARMY_SYMBOLS_DIR)
                            for image in images))

    def save_credit_test_image(self, directory, filename):
        path = Path(directory) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(pygame.Surface((20, 30), pygame.SRCALPHA), str(path))
        return path

    def test_credit_directory_lists_only_png_files_in_stable_order(self):
        from ui.dialogs.person_info import expand_credit_images
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            second = self.save_credit_test_image(root, "zeta.PNG")
            first = self.save_credit_test_image(root, "Alpha.png")
            self.save_credit_test_image(root, "nested/child.png")
            (root / "metadata.json").write_text("{}", encoding="utf-8")
            (root / "folder.png").mkdir()
            images = expand_credit_images([{"directory": directory}])
        self.assertEqual(images, [{"path": first.as_posix(), "text": first.name},
                                  {"path": second.as_posix(), "text": second.name}])

    def test_credit_directory_supports_recursive_and_pattern_exclusions(self):
        from ui.dialogs.person_info import expand_credit_images
        with tempfile.TemporaryDirectory() as directory:
            for name in ("keep.png", "skip.png", "Randomly_A.png", "culture/same.png",
                         "other/same.png", "culture/skip.png"):
                self.save_credit_test_image(directory, name)
            descriptor = {"directory": directory, "recursive": True,
                          "exclude": ["skip.png", "Randomly_*.png", "culture/same.png"]}
            images = expand_credit_images([descriptor])
            self.assertEqual([image["text"] for image in images], ["keep.png", "other/same.png"])
            self.assertEqual([image["path"] for image in images],
                             [(Path(directory) / name).as_posix() for name in ("keep.png", "other/same.png")])
            self.assertEqual(descriptor["exclude"], ["skip.png", "Randomly_*.png", "culture/same.png"])

    def test_credit_directories_mix_with_explicit_images_and_keep_custom_labels(self):
        from ui.dialogs.person_info import expand_credit_images
        with tempfile.TemporaryDirectory() as directory:
            first = self.save_credit_test_image(directory, "a.png")
            second = self.save_credit_test_image(directory, "b.png")
            entries = [{"path": first.as_posix(), "text": "Custom label"},
                       {"directory": directory, "exclude": "a.png"},
                       {"path": first.as_posix(), "text": "Second appearance"}]
            images = expand_credit_images(entries)
            self.assertEqual(images, [entries[0], {"path": second.as_posix(), "text": second.name}, entries[2]])
            images[0]["text"] = "Changed in copy"
            self.assertEqual(entries[0]["text"], "Custom label")

    def test_credit_directories_expand_only_on_open_and_detect_new_images_on_reopen(self):
        from ui.dialogs import person_info
        with tempfile.TemporaryDirectory() as directory:
            self.save_credit_test_image(directory, "first.png")
            entries = [{"directory": directory}]
            with mock.patch.object(person_info, "expand_credit_images", wraps=person_info.expand_credit_images) as expand:
                modal = person_info._PersonInfoModal(self.surface, "Artist", "Art", [], images=entries)
                self.assertEqual(len(modal.image_rows), 1)
                modal.draw(self.surface)
                modal.draw(self.surface)
                self.assertEqual(expand.call_count, 1)
                self.save_credit_test_image(directory, "second.png")
                reopened = person_info._PersonInfoModal(self.surface, "Artist", "Art", [], images=entries)
                self.assertEqual(len(reopened.image_rows), 2)
                self.assertEqual(expand.call_count, 2)

    def test_credit_directory_validation_exposes_bad_content(self):
        from ui.dialogs.person_info import expand_credit_images
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(NotADirectoryError):
                expand_credit_images([{"directory": str(Path(directory) / "missing")}])
        for entry in ({}, {"path": "x.png", "directory": "folder"}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                expand_credit_images([entry])

    def test_credit_images_load_once_before_drawing(self):
        images = self.credited_images()
        with mock.patch.object(pygame.image, "load", wraps=pygame.image.load) as load:
            dialogs.show_person_info("Artist", "Art", images=images)
            modal = self.dialog()
            self.assertEqual(load.call_count, len({image["path"] for image in images}))
            modal.draw(self.surface)
            modal.draw(self.surface)
            self.assertEqual(load.call_count, len({image["path"] for image in images}))
        self.assertEqual(len(modal.image_rows), len(images))
        for image, row in zip(images, modal.image_rows):
            path = Path(image["path"])
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_credit_images_scroll_and_close_on_small_displays(self):
        from ui.dialogs.person_info import _PersonInfoModal
        for size in ((520, 320), (360, 320), (1280, 720)):
            for align in ("left", "center", "right"):
                with self.subTest(size=size, align=align):
                    surface = pygame.Surface(size)
                    modal = _PersonInfoModal(surface, "Artist", "Art", [],
                                             align, self.credited_images())
                    modal.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, y=-100)])
                    self.assertEqual(modal.scroll_y, modal.max_scroll)
                    modal.draw(surface)
                    self.assertEqual(surface.get_clip(), surface.get_rect())
                    modal.handle_events([click(modal.ok_rect.center), release(modal.ok_rect.center)])
                    self.assertTrue(modal.done)

    def test_credit_images_forwarded_from_clickable_name(self):
        from screens.menus import credits
        images = self.credited_images()
        data = [{"main_text": "Art: ", "people": [{"link_text": "Artist", "images": images}]}]
        with mock.patch.object(credits, "CREDITS_DATA", data):
            screen = credits.Credits()
        person = screen.credits_list[0]["people_links"][0]
        self.assertTrue(person["has_popup"])
        with mock.patch.object(credits, "show_person_info") as show:
            screen.additional_events(click(person["link_rect"].center))
        show.assert_called_once_with("Artist", "", [], "center", images=images)

    def test_credit_links_use_scrolled_hitboxes(self):
        from ui.dialogs.person_info import _PersonInfoModal
        links = [{"text": "Site", "url": "https://example.invalid"}]
        surface = pygame.Surface((520, 320))
        modal = _PersonInfoModal(surface, "Artist", "Art", links,
                                 "left", self.credited_images())
        modal.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, y=-100)])
        visible_link = modal.link_rects[0].move(0, -modal.scroll_y)
        with mock.patch("ui.dialogs.person_info.webbrowser.open") as open_url:
            modal.handle_events([click(visible_link.center)])
        open_url.assert_called_once_with(links[0]["url"])

    def test_standalone_person_info_receives_images(self):
        from ui.navigation import screen_runner
        images = self.credited_images()
        calls = []
        with mock.patch.object(screen_runner, "run_screen") as run:
            dialogs.show_person_info("Artist", "Art", [], "left", None,
                                     lambda: calls.append(True), images=images)
        make_dialog, on_done = run.call_args.args[:2]
        modal = make_dialog()
        self.assertEqual(len(modal.image_rows), len(images))
        on_done(modal)
        self.assertEqual(calls, [True])

    def scrollable_credit_modal(self):
        from ui.dialogs.person_info import _PersonInfoModal
        return _PersonInfoModal(pygame.Surface((520, 320)), "Artist", "Art", [],
                                "left", self.credited_images() * 3)

    def test_credit_scrollbar_drags_without_a_jump(self):
        modal = self.scrollable_credit_modal()
        track, handle = modal.scroll_track_rect, modal.scroll_handle_rect
        self.assertIsNotNone(track)
        surface = pygame.Surface((520, 320))
        modal.draw(surface)
        grab = (handle.centerx, handle.bottom - 2)
        modal.handle_events([click(grab)])
        modal.handle_events([pygame.event.Event(pygame.MOUSEMOTION, pos=grab)])
        self.assertAlmostEqual(modal.scroll_y, 0, delta=1)
        modal.handle_events([pygame.event.Event(pygame.MOUSEMOTION,
                                                pos=(grab[0], track.bottom + track.height))])
        self.assertEqual(modal.scroll_y, modal.max_scroll)
        modal.handle_events([pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(0, 0), button=1)])
        modal.handle_events([pygame.event.Event(pygame.MOUSEMOTION, pos=(grab[0], track.top))])
        self.assertEqual(modal.scroll_y, modal.max_scroll)

    def test_credit_scrollbar_track_wheel_keys_and_focus_loss(self):
        modal = self.scrollable_credit_modal()
        track = modal.scroll_track_rect
        modal.handle_events([click((track.centerx, track.bottom - 1))])
        self.assertEqual(modal.scroll_y, modal.max_scroll)
        modal.handle_events([pygame.event.Event(pygame.WINDOWFOCUSLOST)])
        self.assertIsNone(modal._scroll_drag_offset)
        modal.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, y=1)])
        self.assertLess(modal.scroll_y, modal.max_scroll)
        previous = modal.scroll_y
        modal.handle_events([key(pygame.K_UP)])
        self.assertLess(modal.scroll_y, previous)

    def test_credit_scrollbar_is_hidden_when_all_images_fit(self):
        dialogs.show_person_info("Artist", "Art", images=self.credited_images())
        modal = self.dialog()
        self.assertEqual(modal.max_scroll, 0)
        self.assertIsNone(modal.scroll_track_rect)
        self.assertIsNone(modal.scroll_handle_rect)



class ScreenRunnerTests(unittest.TestCase):
    """run_screen is the one modal-launch path; _run_pygame_sub_screen is its
    map-layered flavour. Both must push exactly one modal and pop it again."""

    @classmethod
    def setUpClass(cls):
        _controller, cls.surface = app_harness.boot()

    def setUp(self):
        while not modal_stack.is_empty():
            modal_stack.pop()

    def make_screen(self):
        from ui.navigation.screen import Screen

        class Trivial(Screen):
            def draw(self, surface):
                pass

        return Trivial()

    def test_run_screen_pushes_then_pops(self):
        from ui.navigation.screen_runner import run_screen

        done = []
        screen = self.make_screen()
        run_screen(screen, on_done=done.append)
        self.assertIs(modal_stack.active().screen, screen)

        screen.done = True
        modal_stack.active().update()
        self.assertTrue(modal_stack.is_empty())
        self.assertEqual(done, [screen])

    def test_sub_screen_clears_hover_and_calls_back_with_no_args(self):
        from ui.navigation.screen_runner import _run_pygame_sub_screen

        class FakeMap:
            hovered_province = {"id": 1}

        host = FakeMap()
        calls = []
        screen = self.make_screen()
        _run_pygame_sub_screen(host, screen, on_done=lambda: calls.append(True))

        screen.done = True
        modal_stack.active().update()
        self.assertTrue(modal_stack.is_empty())
        self.assertEqual(calls, [True])
        self.assertIsNone(host.hovered_province,
                          "closing a map-layered sub-screen left the province highlighted")

    def test_no_nested_event_loop_in_the_ui_package(self):
        """A blocking loop reached from the game freezes a pygbag tab: the main
        loop never gets back to its await. The only permitted ones are guarded
        by "no display exists yet"."""
        import ast
        import os

        allowed = {"ui/navigation/screen_runner.py"}
        offenders = []
        ui_dir = os.path.join(app_harness.ROOT, "ui")
        for dirpath, _dirnames, filenames in os.walk(ui_dir):
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                rel = os.path.relpath(path, app_harness.ROOT).replace(os.sep, "/")
                if rel in allowed:
                    continue
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
                for node in ast.walk(tree):
                    if not isinstance(node, ast.While):
                        continue
                    for inner in ast.walk(node):
                        if (isinstance(inner, ast.Attribute) and inner.attr == "get"
                                and isinstance(inner.value, ast.Attribute)
                                and inner.value.attr == "event"):
                            offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(offenders, [])

if __name__ == "__main__":
    unittest.main()
