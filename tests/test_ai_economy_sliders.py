"""The AI's conscription and fuel-conversion sliders.

saves/runv3: the Soviet Union had 50,000 manpower banked, so the conscription
slider's emergency branch converted three quarters of its manpower income. What
it kept fell below its manpower upkeep, the purchase loop's upkeep cap then
refused every purchase, and the army stopped growing. Germany, short of fuel
with materials to spare, used half of its legal fuel conversion and could not
afford a single tank.
"""

import unittest
from unittest.mock import patch

import data.constants as c
from data import queries
from map_logic.ai import ai_construction


def state(raw_man=20000, upk_man=6000, ratio_man=0.3, ratio_mat=0.4,
          ratio_fuel=0.5, target_man=1.2, target_mat=0.9, target_fuel=1.05):
    return {"raw_man": raw_man, "upk_man": upk_man, "ratio_man": ratio_man,
            "ratio_mat": ratio_mat, "ratio_fuel": ratio_fuel,
            "target_man": target_man, "target_mat": target_mat, "target_fuel": target_fuel}


class ConscriptionFloorTests(unittest.TestCase):
    def test_an_emergency_never_converts_below_what_upkeep_needs(self):
        data = {"manpower": c.AI_CONSCRIPTION_EMERGENCY_MANPOWER + 1, "materials": 50000}
        ai_construction._update_conscription_slider(data, state())
        kept = data["conscription_slider"] * 20000
        self.assertLessEqual(6000 / kept, c.AI_UPKEEP_TARGETS["manpower"] + 1e-9)

    def test_with_no_upkeep_to_cover_the_emergency_branch_still_converts(self):
        data = {"manpower": c.AI_CONSCRIPTION_EMERGENCY_MANPOWER + 1, "materials": 50000}
        ai_construction._update_conscription_slider(data, state(upk_man=0))
        self.assertLess(data["conscription_slider"], 1.0)

    def test_the_floor_never_exceeds_keeping_everything(self):
        data = {"manpower": c.AI_CONSCRIPTION_EMERGENCY_MANPOWER + 1, "materials": 50000}
        ai_construction._update_conscription_slider(data, state(upk_man=10 ** 9))
        self.assertEqual(data["conscription_slider"], 1.0)


class FuelConversionTests(unittest.TestCase):
    def test_short_of_fuel_with_materials_to_spare_uses_the_whole_legal_conversion(self):
        data = {"materials": c.AI_CONVERSION_MIN_MATERIALS + 1, "fuel": c.AI_CONVERSION_PANIC_FUEL + 1}
        with patch.object(queries, "get_max_fuel_conversion", return_value=0.14):
            ai_construction._update_fuel_conversion_slider(
                data, state(ratio_fuel=1.2, ratio_mat=0.4))
        self.assertEqual(data["mat_to_fuel_slider"], 0.14)

    def test_with_fuel_to_spare_it_converts_nothing(self):
        data = {"materials": c.AI_CONVERSION_MIN_MATERIALS + 1, "fuel": c.AI_CONVERSION_PANIC_FUEL + 1}
        with patch.object(queries, "get_max_fuel_conversion", return_value=0.14):
            ai_construction._update_fuel_conversion_slider(
                data, state(ratio_fuel=0.2, ratio_mat=0.4))
        self.assertEqual(data["mat_to_fuel_slider"], 0.0)


if __name__ == "__main__":
    unittest.main()
