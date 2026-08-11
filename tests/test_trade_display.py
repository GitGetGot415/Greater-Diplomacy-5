"""A player must be able to see what a trade offer actually asks for.

The offer travels as prose -- the AI's covering line, or the sender's own --
while the numbers stay behind on the sender's pending_diplomacy entry. So the
inbox showed "We propose an exchange to the benefit of us both" above an Accept
button and nothing else.

The direction is the part worth pinning: keys are written from the PROPOSER's
point of view, the same way queries.execute_trade_transfer reads them, so the
receiving side sees them inverted. Rendering that backwards would talk a player
into accepting the opposite of what they thought.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.diplomacy import diplomacy_messages as dm


class DescribeTradeTests(unittest.TestCase):

    def test_the_receiver_gets_what_the_proposer_gives(self):
        lines = dm.describe_trade({"give_materials": 4200, "take_fuel": 1100})
        self.assertEqual(lines[0], "You receive: 4200 Materials")
        self.assertEqual(lines[1], "You give: 1100 Fuel")

    def test_the_proposer_sees_it_the_other_way_round(self):
        lines = dm.describe_trade({"give_materials": 4200, "take_fuel": 1100},
                                  viewer_is_proposer=True)
        self.assertEqual(lines[0], "You receive: 1100 Fuel")
        self.assertEqual(lines[1], "You give: 4200 Materials")

    def test_the_ai_two_key_shape_renders(self):
        """ai_candidates.resource_offer writes only the pair it cares about."""
        lines = dm.describe_trade({"give_fuel": 900, "take_materials": 3000})
        self.assertEqual(lines, ["You receive: 900 Fuel", "You give: 3000 Materials"])

    def test_the_trade_screen_four_key_shape_renders(self):
        lines = dm.describe_trade({"give_materials": 10, "give_fuel": 20,
                                   "take_materials": 30, "take_fuel": 40})
        self.assertEqual(lines[0], "You receive: 10 Materials, 20 Fuel")
        self.assertEqual(lines[1], "You give: 30 Materials, 40 Fuel")

    def test_a_pure_gift_says_so(self):
        lines = dm.describe_trade({"give_materials": 500})
        self.assertEqual(lines[1], "You give: nothing")

    def test_a_demand_for_nothing_in_return_says_so(self):
        lines = dm.describe_trade({"take_materials": 500})
        self.assertEqual(lines[0], "You receive: nothing")

    def test_a_puppet_clause_is_spelled_out(self):
        """The most consequential thing a trade can carry, and the easiest to
        miss if it is not stated."""
        lines = dm.describe_trade({"give_materials": 500, "puppet_state": "RECEIVER"})
        self.assertIn("Puppet terms: RECEIVER", lines)

    def test_a_plain_trade_mentions_no_puppet_clause(self):
        lines = dm.describe_trade({"give_materials": 500, "puppet_state": "NONE"})
        self.assertTrue(all("Puppet" not in line for line in lines))

    def test_junk_parameters_render_nothing_rather_than_raising(self):
        for junk in (None, "", [], 7):
            with self.subTest(junk=junk):
                self.assertEqual(dm.describe_trade(junk), [])

    def test_zero_amounts_are_not_listed(self):
        lines = dm.describe_trade({"give_materials": 500, "give_fuel": 0})
        self.assertEqual(lines[0], "You receive: 500 Materials")


if __name__ == "__main__":
    unittest.main()
