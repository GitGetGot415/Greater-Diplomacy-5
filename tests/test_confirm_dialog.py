"""Covers the four dialogs in ui/confirm_dialog/.

They are pushed onto the modal stack from deep inside other screens, so nothing
else in the suite reaches them -- and they all now share one base class, so a
mistake in the shared half breaks every dialog at once.

Everything here drives the in-game (modal stack) path. The standalone blocking
path only runs when no display exists, which is the opposite of a test run.
"""

import unittest
from pathlib import Path
import tempfile
from unittest import mock

import pygame

from tests import app_harness
from ui import confirm_dialog, modal_stack


def key(k):
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode="", mod=0, scancode=0)


def typed(ch):
    return pygame.event.Event(pygame.KEYDOWN, key=ord(ch), unicode=ch, mod=0, scancode=0)


def click(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1)


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _controller, cls.surface = app_harness.boot()

    def setUp(self):
        while not modal_stack.is_empty():
            modal_stack.pop()
        self.answers = []

    def settle(self):
        """Runs the one update() that pops the modal and delivers the answer."""
        modal = modal_stack.active()
        self.assertIsNotNone(modal, "dialog was not pushed onto the modal stack")
        modal.draw(self.surface)
        modal.update()
        return modal

    # -- ask_yes_no ------------------------------------------------------

    def test_yes_no_confirms(self):
        confirm_dialog.ask_yes_no("T", "Sure?", self.answers.append)
        modal = modal_stack.active()
        modal.handle_events([click(modal.yes_rect.center)])
        self.settle()
        self.assertEqual(self.answers, [True])
        self.assertTrue(modal_stack.is_empty())

    def test_yes_no_cancels(self):
        confirm_dialog.ask_yes_no("T", "Sure?", self.answers.append)
        modal = modal_stack.active()
        modal.handle_events([click(modal.no_rect.center)])
        self.settle()
        self.assertEqual(self.answers, [False])

    def test_yes_no_keyboard(self):
        for k, expected in ((pygame.K_y, True), (pygame.K_n, False),
                            (pygame.K_RETURN, True), (pygame.K_ESCAPE, False)):
            with self.subTest(key=k):
                self.answers.clear()
                confirm_dialog.ask_yes_no("T", "Sure?", self.answers.append)
                modal_stack.active().handle_events([key(k)])
                self.settle()
                self.assertEqual(self.answers, [expected])

    def test_yes_no_box_grows_with_the_message(self):
        confirm_dialog.ask_yes_no("T", "short", self.answers.append)
        short_h = modal_stack.active().box_rect.height
        modal_stack.pop()

        confirm_dialog.ask_yes_no("T", "word " * 200, self.answers.append)
        long_h = modal_stack.active().box_rect.height
        modal_stack.pop()
        self.assertGreater(long_h, short_h)

    # -- ask_string / ask_integer ---------------------------------------

    def test_ask_string_returns_typed_text(self):
        confirm_dialog.ask_string("T", "Name?", self.answers.append)
        modal = modal_stack.active()
        modal.handle_events([typed("a"), typed("b"), key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, ["ab"])

    def test_ask_string_backspace(self):
        confirm_dialog.ask_string("T", "Name?", self.answers.append)
        modal = modal_stack.active()
        modal.handle_events([typed("a"), typed("b"), key(pygame.K_BACKSPACE),
                             key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, ["a"])

    def test_text_input_clear_control_erases_the_current_value(self):
        confirm_dialog.ask_string("T", "Name?", self.answers.append, initial="wrong invite")
        modal = modal_stack.active()
        modal.handle_events([click(modal.clear_rect.center), typed("r"), key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, ["r"])

    def test_ask_string_accepts_clipboard_paste(self):
        confirm_dialog.ask_string("T", "Name?", self.answers.append)
        modal = modal_stack.active()
        paste = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_v, unicode="", mod=pygame.KMOD_CTRL)
        with mock.patch("ui_elements._clipboard_text", return_value="Pasted name"):
            modal.handle_events([paste, key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, ["Pasted name"])

    def test_ask_string_accepts_macos_command_v_paste(self):
        confirm_dialog.ask_string("T", "Name?", self.answers.append)
        modal = modal_stack.active()
        paste = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_v, unicode="", mod=pygame.KMOD_GUI)
        with mock.patch("ui_elements._clipboard_text", return_value="Pasted on Mac"):
            modal.handle_events([paste, key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, ["Pasted on Mac"])

    def test_clipboard_falls_back_to_macos_pbpaste(self):
        import ui_elements

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
        confirm_dialog.ask_string("T", "Name?", self.answers.append)
        modal_stack.active().handle_events([key(pygame.K_ESCAPE)])
        self.settle()
        self.assertEqual(self.answers, [None])

    def test_ask_integer_accepts_digits(self):
        confirm_dialog.ask_integer("T", "How many?", self.answers.append)
        modal = modal_stack.active()
        modal.handle_events([typed("4"), typed("2"), key(pygame.K_RETURN)])
        self.settle()
        self.assertEqual(self.answers, [42])

    def test_ask_integer_rejects_out_of_range(self):
        """A rejected value must keep the dialog open with an error, not resolve."""
        confirm_dialog.ask_integer("T", "1-10?", self.answers.append, minvalue=1, maxvalue=10)
        modal = modal_stack.active()
        modal.handle_events([typed("9"), typed("9"), key(pygame.K_RETURN)])
        self.assertFalse(modal._resolved)
        self.assertNotEqual(modal.error_text, "")
        modal.draw(self.surface)

    # -- show_message ----------------------------------------------------

    def test_show_message_closes_without_a_result(self):
        calls = []
        confirm_dialog.show_message("T", "Done.", on_result=lambda: calls.append(True))
        modal = modal_stack.active()
        modal.handle_events([click(modal.ok_rect.center)])
        self.settle()
        self.assertEqual(calls, [True])
        self.assertTrue(modal_stack.is_empty())

    def test_message_kinds_all_render(self):
        for kind in ("info", "success", "warning", "error"):
            with self.subTest(kind=kind):
                confirm_dialog.show_message("T", "Body text.", kind=kind)
                modal = modal_stack.active()
                self.assertEqual(modal.BORDER_COLOR, confirm_dialog._KIND_ACCENTS[kind])
                modal.draw(self.surface)
                modal_stack.pop()

    def test_show_message_with_no_callback(self):
        confirm_dialog.show_message("T", "Body.")
        modal = modal_stack.active()
        modal.handle_events([key(pygame.K_RETURN)])
        self.settle()
        self.assertTrue(modal_stack.is_empty())

    # -- show_person_info ------------------------------------------------

    def test_person_info_renders_links(self):
        links = [{"text": "Site", "url": "https://example.invalid"}, {"text": "No link"}]
        confirm_dialog.show_person_info("Name", "Some blurb.", links)
        modal = modal_stack.active()
        self.assertEqual(len(modal.link_rects), 2)
        modal.draw(self.surface)
        modal.handle_events([key(pygame.K_ESCAPE)])
        self.settle()
        self.assertTrue(modal_stack.is_empty())

    def test_person_info_alignment_moves_the_links(self):
        links = [{"text": "Site", "url": "https://example.invalid"}]
        confirm_dialog.show_person_info("Name", "Blurb.", links, align="left")
        left_x = modal_stack.active().link_rects[0].x
        modal_stack.pop()

        confirm_dialog.show_person_info("Name", "Blurb.", links, align="right")
        right_x = modal_stack.active().link_rects[0].x
        modal_stack.pop()
        self.assertLess(left_x, right_x)

    def test_person_info_without_links_or_text(self):
        confirm_dialog.show_person_info("Name", "", [])
        modal_stack.active().draw(self.surface)
        modal_stack.pop()

    def credited_images(self):
        from data import constants as c
        from ui.confirm_dialog.person_info import expand_credit_images
        return next(images for entry in c.CREDITS_DATA
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
        from ui.confirm_dialog.person_info import expand_credit_images
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
        from ui.confirm_dialog.person_info import expand_credit_images
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
        from ui.confirm_dialog.person_info import expand_credit_images
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
        from ui.confirm_dialog import person_info
        with tempfile.TemporaryDirectory() as directory:
            self.save_credit_test_image(directory, "first.png")
            entries = [{"directory": directory}]
            with mock.patch.object(person_info, "expand_credit_images", wraps=person_info.expand_credit_images) as expand:
                modal = person_info._PersonInfoModal(self.surface, "Artist", "Art", [], None, images=entries)
                self.assertEqual(len(modal.image_rows), 1)
                modal.draw(self.surface)
                modal.draw(self.surface)
                self.assertEqual(expand.call_count, 1)
                self.save_credit_test_image(directory, "second.png")
                reopened = person_info._PersonInfoModal(self.surface, "Artist", "Art", [], None, images=entries)
                self.assertEqual(len(reopened.image_rows), 2)
                self.assertEqual(expand.call_count, 2)

    def test_credit_directory_validation_exposes_bad_content(self):
        from ui.confirm_dialog.person_info import expand_credit_images
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(NotADirectoryError):
                expand_credit_images([{"directory": str(Path(directory) / "missing")}])
        for entry in ({}, {"path": "x.png", "directory": "folder"}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                expand_credit_images([entry])

    def test_credit_images_load_once_and_preserve_aspect_ratio(self):
        images = self.credited_images()
        with mock.patch.object(pygame.image, "load", wraps=pygame.image.load) as load:
            confirm_dialog.show_person_info("Artist", "Art", images=images)
            modal = modal_stack.active()
            self.assertEqual(load.call_count, len({image["path"] for image in images}))
            modal.draw(self.surface)
            modal.draw(self.surface)
            self.assertEqual(load.call_count, len({image["path"] for image in images}))
        self.assertEqual(len(modal.image_rows), len(images))
        for image, row in zip(images, modal.image_rows):
            path = Path(image["path"])
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            source = pygame.image.load(str(path))
            self.assertTrue(row["labels"])
            self.assertTrue(modal.content_rect.contains(row["rect"]))
            self.assertTrue(row["rect"].contains(row["image_rect"]))
            self.assertFalse(row["rect"].colliderect(modal.ok_rect))
            scaled_w, scaled_h = row["image"].get_size()
            expected_w = source.get_width() * scaled_h / source.get_height()
            self.assertAlmostEqual(scaled_w, expected_w, delta=1)
        for index, (previous, following) in enumerate(zip(modal.image_rows, modal.image_rows[1:])):
            if (index + 1) % modal.image_columns:
                self.assertEqual(previous["rect"].top, following["rect"].top)
                self.assertLess(previous["rect"].right, following["rect"].left)
            else:
                self.assertLess(previous["rect"].bottom, following["rect"].top)

    def test_credit_image_pairs_and_odd_final_image_fit_their_columns(self):
        from ui.confirm_dialog.person_info import _PersonInfoModal
        images = self.credited_images()[:5]
        for size in ((360, 320), (1280, 720)):
            for align in ("left", "center", "right"):
                with self.subTest(size=size, align=align):
                    modal = _PersonInfoModal(pygame.Surface(size), "Artist", "Art", [], None,
                                             align, images)
                    self.assertEqual(modal.image_columns, 2)
                    self.assertEqual(len(modal.image_rows), len(images))
                    for index, cell in enumerate(modal.image_rows):
                        self.assertGreaterEqual(cell["rect"].left, modal.content_rect.left)
                        self.assertLessEqual(cell["rect"].right, modal.content_rect.right)
                        if index % modal.image_columns:
                            previous = modal.image_rows[index - 1]
                            self.assertEqual(previous["rect"].top, cell["rect"].top)
                            self.assertFalse(previous["rect"].colliderect(cell["rect"]))
                    self.assertGreater(modal.image_rows[-1]["rect"].top,
                                       modal.image_rows[-2]["rect"].bottom)

    def test_credit_images_scroll_on_small_displays_without_hiding_close(self):
        from ui.confirm_dialog.person_info import _PersonInfoModal
        for size in ((520, 320), (360, 320), (1280, 720)):
            for align in ("left", "center", "right"):
                with self.subTest(size=size, align=align):
                    surface = pygame.Surface(size)
                    modal = _PersonInfoModal(surface, "Artist", "Art", [], None,
                                             align, self.credited_images())
                    self.assertTrue(surface.get_rect().contains(modal.box_rect))
                    self.assertTrue(modal.box_rect.contains(modal.ok_rect))
                    self.assertLess(modal.content_rect.bottom, modal.ok_rect.top)
                    modal.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, y=-100)])
                    self.assertEqual(modal.scroll_y, modal.max_scroll)
                    last = modal.image_rows[-1]["rect"].move(0, -modal.scroll_y)
                    self.assertTrue(modal.content_rect.contains(last))
                    modal.draw(surface)
                    self.assertEqual(surface.get_clip(), surface.get_rect())
                    modal.handle_events([click(modal.ok_rect.center)])
                    self.assertTrue(modal._resolved)

    def test_credit_images_forwarded_from_clickable_name(self):
        from screens.menu_screens import credits
        images = self.credited_images()
        data = [{"main_text": "Art: ", "people": [{"link_text": "Artist", "images": images}]}]
        with mock.patch.object(credits.c, "CREDITS_DATA", data):
            screen = credits.Credits()
        person = screen.credits_list[0]["people_links"][0]
        self.assertTrue(person["has_popup"])
        with mock.patch.object(credits, "show_person_info") as show:
            screen.additional_events(click(person["link_rect"].center))
        show.assert_called_once_with("Artist", "", [], "center", images=images)

    def test_credit_links_follow_images_and_use_scrolled_hitboxes(self):
        from ui.confirm_dialog.person_info import _PersonInfoModal
        links = [{"text": "Site", "url": "https://example.invalid"}]
        surface = pygame.Surface((520, 320))
        modal = _PersonInfoModal(surface, "Artist", "Art", links, None,
                                 "left", self.credited_images())
        self.assertGreater(modal.link_rects[0].top, modal.image_rows[-1]["rect"].bottom)
        modal.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, y=-100)])
        visible_link = modal.link_rects[0].move(0, -modal.scroll_y)
        self.assertTrue(modal.content_rect.contains(visible_link))
        with mock.patch("ui.confirm_dialog.person_info.webbrowser.open") as open_url:
            modal.handle_events([click(visible_link.center)])
        open_url.assert_called_once_with(links[0]["url"])

    def test_credit_image_labels_wrap_within_the_popup(self):
        from ui.confirm_dialog.person_info import _PersonInfoModal
        image = dict(self.credited_images()[0], text="Long image label " * 15)
        surface = pygame.Surface((360, 320))
        modal = _PersonInfoModal(surface, "Artist", "", [], None, images=[image])
        row = modal.image_rows[0]
        self.assertGreater(len(row["labels"]), 1)
        self.assertGreaterEqual(row["rect"].left, modal.content_rect.left)
        self.assertLessEqual(row["rect"].right, modal.content_rect.right)
        modal.draw(surface)

    def test_standalone_person_info_receives_images(self):
        from ui.confirm_dialog import person_info
        images = self.credited_images()
        calls = []
        with mock.patch.object(person_info, "_run_blocking") as run:
            person_info._show_person_info_standalone("Artist", "Art", [], "left", None,
                                                    lambda: calls.append(True), images)
        modal = run.call_args.args[0](self.surface)
        self.assertEqual(len(modal.image_rows), len(images))
        self.assertEqual(calls, [True])

    def scrollable_credit_modal(self):
        from ui.confirm_dialog.person_info import _PersonInfoModal
        return _PersonInfoModal(pygame.Surface((520, 320)), "Artist", "Art", [], None,
                                "left", self.credited_images() * 3)

    def test_credit_scrollbar_is_visible_and_drags_without_a_jump(self):
        modal = self.scrollable_credit_modal()
        track, handle = modal.scroll_track_rect, modal.scroll_handle_rect
        self.assertIsNotNone(track)
        self.assertTrue(modal.box_rect.contains(track))
        self.assertTrue(track.contains(handle))
        self.assertGreater(track.left, modal.content_rect.right)
        surface = pygame.Surface((520, 320))
        modal.draw(surface)
        self.assertNotEqual(surface.get_at(handle.center), surface.get_at(modal.box_rect.topleft))
        grab = (handle.centerx, handle.bottom - 2)
        modal.handle_events([click(grab)])
        modal.handle_events([pygame.event.Event(pygame.MOUSEMOTION, pos=grab)])
        self.assertAlmostEqual(modal.scroll_y, 0, delta=1)
        modal.handle_events([pygame.event.Event(pygame.MOUSEMOTION,
                                                pos=(grab[0], track.bottom + track.height))])
        self.assertEqual(modal.scroll_y, modal.max_scroll)
        self.assertEqual(modal.scroll_handle_rect.bottom, track.bottom)
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
        self.assertTrue(track.contains(modal.scroll_handle_rect))

    def test_credit_scrollbar_is_hidden_when_all_images_fit(self):
        confirm_dialog.show_person_info("Artist", "Art", images=self.credited_images())
        modal = modal_stack.active()
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
        from gameState import GameState

        class Trivial(GameState):
            def draw(self, surface):
                pass

        return Trivial()

    def test_run_screen_pushes_then_pops(self):
        from ui.screen_runner import run_screen

        done = []
        screen = self.make_screen()
        run_screen(screen, on_done=done.append)
        self.assertIs(modal_stack.active().screen, screen)

        screen.done = True
        modal_stack.active().update()
        self.assertTrue(modal_stack.is_empty())
        self.assertEqual(done, [screen])

    def test_sub_screen_clears_hover_and_calls_back_with_no_args(self):
        from ui.screen_runner import _run_pygame_sub_screen

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

        allowed = {"ui/confirm_dialog/base.py", "ui/screen_runner.py"}
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
