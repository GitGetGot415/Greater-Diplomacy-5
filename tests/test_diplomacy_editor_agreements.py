"""Persistence coverage for the map maker's diplomatic agreement view."""

from types import SimpleNamespace
import unittest

import data.constants as c
from tests.stub_map_screen import StubMapScreen
from screens.editor_screens.diplomacy_editor_screen import Diplomacy_Editor_Screen
from map_logic.diplomacy import guarantees, military_attaches


class DiplomacyEditorAgreementTests(unittest.TestCase):
    def test_save_uses_runtime_agreement_storage_and_directions(self):
        game = StubMapScreen(["A", "B", "C", "D"])
        game.set_war("B", "C")  # C is an eligible attaché host.

        # Saving is state-focused, so use a small editor shell rather than a
        # display-backed screen.  The UI itself is covered by the smoke test.
        editor = object.__new__(Diplomacy_Editor_Screen)
        editor.map_screen = game
        editor.target = "A"
        editor.countries = ["A", "B", "C", "D"]
        editor.others = ["B", "C", "D"]
        editor.wars = set()
        editor.members = set()
        editor.guarantees = {"D"}
        editor.attaches = {"C"}
        editor.access = {"B"}
        editor.is_leader = False
        editor.master = "None"
        editor.puppet_type = c.PUPPET_TYPE_AUTONOMOUS
        editor.faction_field = SimpleNamespace(text="")
        editor.refresh_ui = lambda: None

        editor.save()

        self.assertEqual(guarantees.guaranteed_targets("A", game.nation_data), ["D"])
        self.assertEqual(military_attaches.hosts_for("A", game.nation_data), ["C"])
        self.assertIn("A", game.nation_data["B"]["military_access"])
        self.assertNotIn("B", game.nation_data["A"]["military_access"])


if __name__ == "__main__":
    unittest.main()
