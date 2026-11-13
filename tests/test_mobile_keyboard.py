"""The phone keyboard must open for an active text box and type into it on mobile web."""

import importlib.util
import os
import platform as browser_platform  # pygbag adds .window to the stdlib module
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

from tests.web_fixtures import GarblingWindow
from ui import mobile_keyboard
from ui.widgets.ui_elements import process_text_input

# A minimal DOM: one element type that records its listeners and focus.
FAKE_DOM = r"""
globalThis.window = globalThis;
class FakeElement {
    constructor() { this.listeners = {}; this.style = {}; this.value = ''; }
    addEventListener(type, handler) { this.listeners[type] = handler; }
    setAttribute() {}
    setSelectionRange() {}
    focus() { document.activeElement = this; }
    blur() { if (document.activeElement === this) document.activeElement = null; }
}
globalThis.document = {
    activeElement: null, listeners: {},
    createElement() { return globalThis.hiddenInput = new FakeElement(); },
    addEventListener(type, handler) { this.listeners[type] = handler; },
    body: {appendChild() {}},
};
globalThis.typeInto = (value) => {
    hiddenInput.value = value;
    hiddenInput.listeners.input({isComposing: false});
};
globalThis.pressKey = (key) => {
    const event = {key, stopped: false, preventDefault() {}, stopPropagation() { this.stopped = true; }};
    hiddenInput.listeners.keydown(event);
    return event.stopped;
};
"""


@unittest.skipUnless(importlib.util.find_spec("quickjs"), "QuickJS is not installed")
class MobileKeyboardTests(unittest.TestCase):
    def setUp(self):
        import quickjs

        self.context = quickjs.Context()
        self.context.eval(FAKE_DOM)
        patches = [
            patch.object(browser_platform, "window", GarblingWindow(self.context), create=True),
            patch.object(mobile_keyboard, "IS_WEB", True),
            patch.object(mobile_keyboard, "_installed", False),
            patch.object(mobile_keyboard, "_shown", False),
            patch.object(mobile_keyboard, "_requested", False),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

    def _frame(self, text_box_active, mobile_controls=True):
        if text_box_active:
            mobile_keyboard.request()
        mobile_keyboard.sync(mobile_controls)

    def _input_focused(self):
        return self.context.eval("document.activeElement === globalThis.hiddenInput")

    def test_active_text_box_opens_and_closes_the_keyboard(self):
        self._frame(True)
        self.assertTrue(self._input_focused())
        self._frame(True)
        self.assertTrue(self._input_focused())
        self._frame(False)
        self.assertFalse(self._input_focused())

    def test_desktop_controls_never_open_the_keyboard(self):
        self._frame(True, mobile_controls=False)
        self.assertFalse(mobile_keyboard._installed)
        self.assertEqual(mobile_keyboard.typed_events(), [])

    def test_typed_characters_edit_the_text_box(self):
        self._frame(True)
        fill = self.context.eval("hiddenInput.value")
        self.context.eval(f"typeInto({fill!r} + 'h\\u00e9\\ud83d\\ude00')")
        self.context.eval(f"typeInto({fill!r} + 'h')")
        self.assertTrue(self.context.eval("pressKey('Enter')"))

        text, statuses = "", []
        for event in mobile_keyboard.typed_events():
            self.assertEqual(event.type, pygame.KEYDOWN)
            text, status = process_text_input(event, text)
            statuses.append(status)
        self.assertEqual(text, "h")
        self.assertEqual(statuses[-1], "SUBMIT")
        self.assertEqual(mobile_keyboard.typed_events(), [])

    def test_backspace_past_the_typed_text_still_reaches_the_text_box(self):
        self._frame(True)
        fill = self.context.eval("hiddenInput.value")
        self.context.eval(f"typeInto({fill[:-1]!r})")
        events = mobile_keyboard.typed_events()
        self.assertEqual([event.key for event in events], [pygame.K_BACKSPACE])
        self.assertEqual(process_text_input(events[0], "Rome")[0], "Rom")

    def test_physical_text_keys_do_not_also_reach_the_game(self):
        self._frame(True)
        self.assertTrue(self.context.eval("pressKey('a')"))
        self.assertFalse(self.context.eval("pressKey('ArrowLeft')"))


if __name__ == "__main__":
    unittest.main()
