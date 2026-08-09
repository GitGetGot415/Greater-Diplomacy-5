"""Covers the four dialogs in ui/confirm_dialog.py.

They are pushed onto the modal stack from deep inside other screens, so nothing
else in the suite reaches them -- and they all now share one base class, so a
mistake in the shared half breaks every dialog at once.

Everything here drives the in-game (modal stack) path. The standalone blocking
path only runs when no display exists, which is the opposite of a test run.
"""

import unittest

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
        from ui.player_diplomacy_menus import _run_pygame_sub_screen

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

        allowed = {"ui/confirm_dialog.py", "ui/screen_runner.py"}
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
