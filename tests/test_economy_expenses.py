"""Expenses table views preserve per-unit upkeep and group by displayed type."""

import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

import data.constants as c
from data import queries
from screens.map_related_screens.economy import Economy_Screen, ExpensesTableScreen, expense_table_rows
from tests.stub_map_screen import StubMapScreen


class ExpensesTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    def make_rows(self):
        library = {
            "Infantry 1914": {"cost_manpower": 100, "cost_materials": 20, "cost_fuel": 0},
            "Infantry 1915": {"cost_manpower": 150, "cost_materials": 30, "cost_fuel": 5},
        }
        units = [
            ({"type": "Infantry 1914", "owner": "A"}, {"id": 1}),
            ({"type": "Infantry 1914", "owner": "A"}, {"id": 2}),
            ({"type": "Infantry 1915", "owner": "A"}, {"id": 3}),
            ({"type": "Convoy (Infantry 1914)", "original_type": "Infantry 1914",
              "owner": "A"}, {"id": 4}),
        ]
        return expense_table_rows(units, library)

    def test_grouped_rows_count_each_displayed_type_and_sum_actual_upkeep(self):
        individual, grouped = self.make_rows()
        by_type = {row["unit"]: row for row in grouped}
        self.assertEqual(len(individual), 4)
        self.assertEqual({name: row["count"] for name, row in by_type.items()}, {
            "Infantry 1914": 2, "Infantry 1915": 1,
            "Convoy (Infantry 1914)": 1,
        })
        self.assertEqual([row["location"] for row in individual], [1, 2, 3, 4])
        for resource in c.ECON_RESOURCE_KEYS:
            for name, group in by_type.items():
                expected = sum(row[resource] for row in individual if row["unit"] == name)
                self.assertEqual(group[resource], expected)
            self.assertEqual(sum(row[resource] for row in individual),
                             sum(row[resource] for row in grouped))
        convoy = by_type["Convoy (Infantry 1914)"]
        self.assertEqual(convoy["materials"],
                         queries.get_unit_upkeep({"cost_materials": 20})["materials"])

    def test_toggle_changes_columns_and_rows_without_leaving_the_table(self):
        individual, grouped = self.make_rows()
        table = ExpensesTableScreen(StubMapScreen(["A", "B"]), individual, grouped)
        self.assertIs(table.rows, individual)
        self.assertEqual([column.key for column in table.columns][1], "location")

        table.scroll_y = -90
        table.elements[-1].callback()
        self.assertIs(table.rows, grouped)
        self.assertEqual([column.key for column in table.columns][1], "count")
        self.assertEqual(table.scroll_y, 0)
        self.assertEqual([row["unit"] for row in table.rows],
                         ["Infantry 1914", "Infantry 1915", "Convoy (Infantry 1914)"])

        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        table.draw(surface)

        table.elements[-2].callback()
        self.assertIs(table.rows, individual)
        self.assertEqual([column.key for column in table.columns][1], "location")
        table.draw(surface)

    def test_opening_expenses_collects_only_the_players_units_wherever_they_are(self):
        game = StubMapScreen(["A", "B"])
        game.home_of("A")["units"] = [{"owner": "A", "type": "Infantry 1914"}]
        game.home_of("B")["units"] = [
            {"owner": "A", "type": "Infantry 1914"},
            {"owner": "B", "type": "Infantry 1915"},
        ]
        economy = Economy_Screen()
        economy.map_screen = game
        library = {"Infantry 1914": {"cost_materials": 20}}
        with patch("screens.map_related_screens.economy.queries.get_unit_library",
                   return_value=library), \
                patch("ui.screen_runner._run_pygame_sub_screen") as open_table:
            economy.open_expenses_table()

        table = open_table.call_args.args[1]
        self.assertIsInstance(table, ExpensesTableScreen)
        self.assertEqual([row["location"] for row in table.individual_rows],
                         [game.home_of("A")["id"], game.home_of("B")["id"]])
        self.assertEqual(table.grouped_rows[0]["count"], 2)


if __name__ == "__main__":
    unittest.main()
