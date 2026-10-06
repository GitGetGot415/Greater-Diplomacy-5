"""Map menu controls remain available in the correct modes and call their handlers."""

import unittest

from screens.menu_screens import map as map_module
from tests import app_harness


class MapMenuControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()
        cls.map = app_harness.boot_map()

    def visible_controls(self, is_editor, selected=False):
        """Use the shared control rules without checking screen coordinates."""
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
                    if getattr(el, "visible", False)]
        finally:
            for attr, value in saved.items():
                setattr(game, attr, value)
            map_module.update_button_states(game)

    def test_claims_is_on_a_players_left_bar(self):
        """The Claims tab is a game screen, not only an authoring one.

        It was taken off the play bar on the theory that a claim is only ever a
        justification for one specific war, so the declare-war window is the
        only place it needs to be reachable from. That is true of *making* a
        claim and false of reading the map: who is building a case against whom
        is information about the whole world, and the war screen only ever shows
        one nation's worth of it. Both ways in exist now.
        """
        elements = self.visible_controls(is_editor=False)
        self.assertIn(self.map.btn_gp_claims, elements,
                      "the Claims button is not visible during a game")

    def test_politics_is_on_both_left_bars(self):
        """Players change their country's politics. Editors set each country's starting politics."""
        for is_editor in (True, False):
            elements = self.visible_controls(is_editor=is_editor)
            self.assertIn(self.map.btn_gp_politics, elements,
                          f"the Politics button is not visible (is_editor={is_editor})")

    def test_ai_personality_is_actually_on_screen_in_the_editor(self):
        elements = self.visible_controls(is_editor=True)
        self.assertIn(self.map.btn_ed_personality, elements,
                      "the AI Personality button is not visible in the map editor")

    def test_ai_personality_opens_the_personality_editor(self):
        """The control opens its intended editor once."""
        from ui import editor_menus
        opened = []
        original = editor_menus.open_personality_editor
        editor_menus.open_personality_editor = lambda ms: opened.append(ms)
        try:
            self.map.btn_ed_personality.callback()
        finally:
            editor_menus.open_personality_editor = original
        self.assertEqual(len(opened), 1)


if __name__ == "__main__":
    unittest.main()
