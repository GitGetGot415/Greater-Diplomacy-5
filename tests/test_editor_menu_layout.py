"""No two buttons that are on screen together may sit on top of each other.

The AI Personality button was built, registered, made visible and smoke-tested,
and still could not be seen by anybody: it was placed on row 9 of the editor's
left bar, where btn_gp_claims already sat, and Claims is later in the elements
list so it painted over it exactly. Worse, GameState.handle_events hands every
event to every element with no consume, so the one click landed on both.

Nothing caught it because a button's row is a hand-picked integer and no test
ever compared two of them. That is what this file is for. It asks the real
screen which elements it would actually draw, and refuses to let any two of
them share ground -- so the next row picked by hand fails here instead of
silently disappearing.
"""

import unittest

from screens.menu_screens import map as map_module
from tests import app_harness


class LeftBarLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()
        cls.map = app_harness.boot_map()

    def visible_left_bar(self, is_editor, selected=False):
        """The left-bar elements the map screen would paint this frame.

        update_button_states is the single authority on what is on screen, so
        the test asks it rather than re-deriving the rules and getting them
        wrong in a different way.
        """
        game = self.map
        # A freshly booted map is still on the country-picking screen, where
        # update_button_states returns after two buttons. The bar under test
        # only exists once a country has been chosen.
        saved = {a: getattr(game, a) for a in ("is_editor", "selected_province", "selection_mode")}
        try:
            game.is_editor = is_editor
            game.selection_mode = False
            game.selected_province = saved["selected_province"] if selected else None
            map_module.update_button_states(game)
            return [el for el in game.elements
                    if getattr(el, "visible", False)
                    and getattr(el, "rect", None) is not None
                    and el.rect.x == map_module.LEFT_UI_BAR_X]
        finally:
            for attr, value in saved.items():
                setattr(game, attr, value)
            map_module.update_button_states(game)

    def assert_no_overlap(self, elements, label):
        for i, first in enumerate(elements):
            for second in elements[i + 1:]:
                if first.rect.colliderect(second.rect):
                    self.fail(
                        f"{label}: {getattr(first, 'text', first)!r} at {tuple(first.rect)} "
                        f"overlaps {getattr(second, 'text', second)!r} at {tuple(second.rect)}")

    def test_the_editors_left_bar_has_no_two_buttons_in_one_place(self):
        elements = self.visible_left_bar(is_editor=True)
        self.assertGreater(len(elements), 5, "no left-bar buttons were visible at all")
        self.assert_no_overlap(elements, "editor")

    def test_a_players_left_bar_has_no_two_buttons_in_one_place(self):
        elements = self.visible_left_bar(is_editor=False)
        self.assertGreater(len(elements), 5, "no left-bar buttons were visible at all")
        self.assert_no_overlap(elements, "play")

    def test_claims_is_on_a_players_left_bar(self):
        """The Claims tab is a game screen, not only an authoring one.

        It was taken off the play bar on the theory that a claim is only ever a
        justification for one specific war, so the declare-war window is the
        only place it needs to be reachable from. That is true of *making* a
        claim and false of reading the map: who is building a case against whom
        is information about the whole world, and the war screen only ever shows
        one nation's worth of it. Both ways in exist now.
        """
        elements = self.visible_left_bar(is_editor=False)
        self.assertIn(self.map.btn_gp_claims, elements,
                      "the Claims button is not visible during a game")

    def test_ai_personality_is_actually_on_screen_in_the_editor(self):
        elements = self.visible_left_bar(is_editor=True)
        self.assertIn(self.map.btn_ed_personality, elements,
                      "the AI Personality button is not visible in the map editor")

    def test_ai_personality_opens_the_personality_editor(self):
        """The click has to reach one handler, not two.

        Pressing where it used to sit ran open_personality_editor *and*
        open_claims_menu, which is why the personality list appeared only after
        the Claims screen was closed -- if the player ever thought to look.
        """
        from ui import editor_menus
        opened = []
        original = editor_menus.open_personality_editor
        editor_menus.open_personality_editor = lambda ms: opened.append(ms)
        try:
            self.map.btn_ed_personality.callback()
        finally:
            editor_menus.open_personality_editor = original
        self.assertEqual(len(opened), 1)

        hits = [el for el in self.visible_left_bar(is_editor=True)
                if el.rect.collidepoint(self.map.btn_ed_personality.rect.center)]
        self.assertEqual(hits, [self.map.btn_ed_personality],
                         "another visible button shares the AI Personality button's ground")


if __name__ == "__main__":
    unittest.main()
