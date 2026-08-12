"""The AI must not buy with one valuation and sell with another.

_run_purchase_loop takes the argmax of ai_unit_eval's marginal score.
_disband_worst_unit_if_deficit predates the overhaul and ranked by raw
stats["attack"], so a nation paid for the unit its own evaluator rated best and
then deleted that same unit as its "worst". On saves/Japan deletes their own
units, 25 nations were simultaneously building and scrapping one type, four
units were deleted while standing in a battle, and 46 of 85 nations were
disbanding something -- because the purchase loop accumulated upk_fuel and never
once read it, so it bought fuel units without limit and the disband pass then
paid the bill one unit per turn.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import ai_construction, ai_unit_eval


# Two land units of the same role. The cheap one is what the old attack-ranked
# picker always chose; the evaluator rates it lower per point of resource pain.
LIBRARY = {
    "Scout Car": {"attack": 100, "defense": 0, "health": 400, "production_time": 1,
                  "cost_materials": 300, "cost_manpower": 100, "cost_fuel": 200},
    "Heavy Gun": {"attack": 900, "defense": 0, "health": 400, "production_time": 1,
                  "cost_materials": 800, "cost_manpower": 100, "cost_fuel": 200},
    "Rifles": {"attack": 400, "defense": 0, "health": 600, "production_time": 1,
               "cost_materials": 400, "cost_manpower": 300, "cost_fuel": 0},
}


def value(name, score):
    """Just the two fields the picker reads."""
    return ai_unit_eval.UnitValue(
        name=name, role=ai_unit_eval.ROLE_LINE, score=score, combat=0.0, offense=0.0,
        durability=0.0, soak=0.0, pain=1.0, stats=LIBRARY[name], naval=False)


def unit(u_type, owner="Avaria"):
    return {"type": u_type, "owner": owner, "health": 400,
            "order": {"type": "MOVE", "path": []}}


class Screen:
    """Two owned provinces, plus one next door that can be given an enemy."""

    def __init__(self, provs, at_war=("Borland",)):
        self.map_data = {str(p["id"]): p for p in provs}
        self.id_to_province = {p["id"]: p for p in provs}
        self.nation_data = {
            "Avaria": {"at_war_with": list(at_war), "allied_with": [], "puppets": [],
                       "master": "", "faction": "", "research": {}},
            "Borland": {"at_war_with": ["Avaria"], "allied_with": [], "puppets": [],
                        "master": "", "faction": "", "research": {}},
        }


def province(pid, units=(), queue=(), owner="Avaria", neighbors=()):
    return {"id": pid, "json_key": str(pid), "owner": owner, "cores": [owner],
            "neighbors": list(neighbors), "units": list(units),
            "unit_queue": [{"unit_type": t, "turns_remaining": 1} for t in queue],
            "buildings": [], "terrain": "plains"}


class DisbandChoiceTests(unittest.TestCase):
    """Which unit the nation gives up, when it has to give one up."""

    def disband(self, provs, deficits=("cost_fuel",), values=None, at_war=("Borland",)):
        screen = Screen(provs, at_war=at_war)
        ai_construction._disband_worst_unit_if_deficit(
            screen, screen.nation_data["Avaria"], [p for p in provs if p["owner"] == "Avaria"],
            "Avaria", list(deficits), LIBRARY, values)
        return [u for p in provs for u in p["units"]
                if u.get("order", {}).get("type") == "DISBAND"]

    def test_it_gives_up_the_unit_its_own_valuation_rates_lowest(self):
        """Not the lowest attack. Scout Car has a ninth of Heavy Gun's attack and
        is scored higher, which is the case the old picker got backwards."""
        cheap, dear = unit("Scout Car"), unit("Heavy Gun")
        scrapped = self.disband([province(1, [cheap, dear])],
                                values={"Scout Car": value("Scout Car", 9.0),
                                        "Heavy Gun": value("Heavy Gun", 1.0)})
        self.assertEqual([u["type"] for u in scrapped], ["Heavy Gun"])

    def test_the_old_attack_ranking_would_have_chosen_the_other_one(self):
        """Guards the test above against passing for the wrong reason."""
        self.assertLess(LIBRARY["Scout Car"]["attack"], LIBRARY["Heavy Gun"]["attack"])

    def test_only_one_unit_goes_per_turn(self):
        units = [unit("Scout Car"), unit("Scout Car"), unit("Heavy Gun")]
        self.assertEqual(len(self.disband([province(1, units)])), 1)

    def test_nothing_goes_when_no_resource_is_short(self):
        self.assertEqual(self.disband([province(1, [unit("Scout Car")])], deficits=()), [])

    def test_a_unit_that_costs_nothing_scarce_is_safe(self):
        """Rifles burn no fuel, so a fuel deficit is not their problem."""
        self.assertEqual(self.disband([province(1, [unit("Rifles")])]), [])

    def test_an_obsolete_unit_goes_before_a_better_scored_one(self):
        """Obsolescence stays the first key -- that part was always right."""
        keep, obsolete = unit("Heavy Gun"), unit("Scout Car")
        screen = Screen([province(1, [keep, obsolete])])
        screen.nation_data["Avaria"]["research"] = {}
        import data.queries as queries
        real = queries.is_unit_obsolete
        queries.is_unit_obsolete = lambda t, r: t == "Scout Car"
        try:
            ai_construction._disband_worst_unit_if_deficit(
                screen, screen.nation_data["Avaria"], list(screen.map_data.values()),
                "Avaria", ["cost_fuel"], LIBRARY,
                {"Scout Car": value("Scout Car", 9.0), "Heavy Gun": value("Heavy Gun", 1.0)})
        finally:
            queries.is_unit_obsolete = real
        self.assertEqual(obsolete["order"]["type"], "DISBAND")
        self.assertEqual(keep["order"]["type"], "MOVE")


class NeverAtTheFrontTests(unittest.TestCase):
    """Nothing here ever looked at where a unit was standing."""

    def run_disband(self, provs):
        screen = Screen(provs)
        mine = [p for p in provs if p["owner"] == "Avaria"]
        ai_construction._disband_worst_unit_if_deficit(
            screen, screen.nation_data["Avaria"], mine, "Avaria", ["cost_fuel"], LIBRARY, {})
        return [u for p in provs for u in p["units"]
                if u.get("order", {}).get("type") == "DISBAND"]

    def test_a_unit_sharing_a_tile_with_an_enemy_is_never_chosen(self):
        contested = province(1, [unit("Scout Car"), unit("Scout Car", owner="Borland")])
        safe = province(2, [unit("Scout Car")])
        scrapped = self.run_disband([contested, safe])
        self.assertEqual(len(scrapped), 1)
        self.assertIn(scrapped[0], safe["units"])

    def test_a_unit_with_an_enemy_next_door_is_never_chosen(self):
        border = province(1, [unit("Scout Car")], neighbors=[3])
        rear = province(2, [unit("Scout Car")])
        enemy = province(3, [unit("Scout Car", owner="Borland")], owner="Borland")
        scrapped = self.run_disband([border, rear, enemy])
        self.assertEqual(len(scrapped), 1)
        self.assertIn(scrapped[0], rear["units"])

    def test_an_army_that_is_entirely_at_the_front_gives_up_nothing(self):
        """Losing the war costs more than the deficit does."""
        front = province(1, [unit("Scout Car"), unit("Scout Car", owner="Borland")])
        self.assertEqual(self.run_disband([front]), [])

    def test_a_neighbour_at_peace_is_not_a_front(self):
        border = province(1, [unit("Scout Car")], neighbors=[3])
        neutral = province(3, [unit("Scout Car", owner="Borland")], owner="Borland")
        scrapped = self.run_disband_at_peace([border, neutral])
        self.assertEqual(len(scrapped), 1)

    def run_disband_at_peace(self, provs):
        screen = Screen(provs, at_war=())
        screen.nation_data["Borland"]["at_war_with"] = []
        mine = [p for p in provs if p["owner"] == "Avaria"]
        ai_construction._disband_worst_unit_if_deficit(
            screen, screen.nation_data["Avaria"], mine, "Avaria", ["cost_fuel"], LIBRARY, {})
        return [u for p in provs for u in p["units"]
                if u.get("order", {}).get("type") == "DISBAND"]


class NotWhatYouAreBuildingTests(unittest.TestCase):
    """The reported symptom, stated directly."""

    def run_disband(self, provs):
        screen = Screen(provs)
        ai_construction._disband_worst_unit_if_deficit(
            screen, screen.nation_data["Avaria"], provs, "Avaria", ["cost_fuel"], LIBRARY, {})
        return [u for p in provs for u in p["units"]
                if u.get("order", {}).get("type") == "DISBAND"]

    def test_a_type_on_order_is_never_scrapped(self):
        p = province(1, [unit("Scout Car")], queue=["Scout Car"])
        self.assertEqual(self.run_disband([p]), [])

    def test_a_queue_in_one_province_protects_the_type_everywhere(self):
        building = province(1, [], queue=["Scout Car"])
        standing = province(2, [unit("Scout Car")])
        self.assertEqual(self.run_disband([building, standing]), [])

    def test_a_different_type_is_still_available(self):
        p = province(1, [unit("Scout Car"), unit("Heavy Gun")], queue=["Scout Car"])
        scrapped = self.run_disband([p])
        self.assertEqual([u["type"] for u in scrapped], ["Heavy Gun"])


class PeacetimeMilitiaTests(unittest.TestCase):
    """The same rule, applied to the one hardcoded unit name left in the AI."""

    def militia(self):
        return {"type": "Militia I", "owner": "Avaria", "health": 400,
                "order": {"type": "MOVE", "path": []}}

    def test_militia_stand_down_at_peace(self):
        m = self.militia()
        ai_construction._disband_peacetime_militia("Avaria", [province(1, [m])], at_war=False)
        self.assertEqual(m["order"]["type"], "DISBAND")

    def test_militia_are_kept_during_a_war(self):
        m = self.militia()
        ai_construction._disband_peacetime_militia("Avaria", [province(1, [m])], at_war=True)
        self.assertEqual(m["order"]["type"], "MOVE")

    def test_militia_on_order_are_not_scrapped_the_turn_they_are_bought(self):
        """The purchase loop is name-blind and buys militia when its own
        valuation rates them worth buying. Paying for a unit and deleting its
        twin in one turn is the whole bug, whatever the unit is called."""
        m = self.militia()
        prov = province(1, [m], queue=["Militia I"])
        ai_construction._disband_peacetime_militia("Avaria", [prov], at_war=False)
        self.assertEqual(m["order"]["type"], "MOVE")

    def test_someone_elses_militia_are_not_ours_to_disband(self):
        theirs = self.militia()
        theirs["owner"] = "Borland"
        ai_construction._disband_peacetime_militia("Avaria", [province(1, [theirs])], at_war=False)
        self.assertEqual(theirs["order"]["type"], "MOVE")


class TacticalPlayerTests(unittest.TestCase):
    """A tactical-mode player's own division is not the host's to scrap.

    In tactical mode the player commands one unit and the AI is handed the
    country around them on purpose (get_active_ai_nations empties the human
    player list), so both passes here are the host deciding what to do with the
    player's unit. From the player's side it would look like their division
    simply vanished.
    """

    def militia(self, owner="Avaria"):
        return {"type": "Militia I", "owner": owner, "health": 400,
                "order": {"type": "MOVE", "path": []}}

    def tactical(self, screen, unit):
        screen.tactical_mode = True
        screen.player_unit = unit
        return screen

    def cull(self, screen, provs):
        ai_construction._disband_worst_unit_if_deficit(
            screen, screen.nation_data["Avaria"],
            [p for p in provs if p["owner"] == "Avaria"], "Avaria",
            ["cost_fuel"], LIBRARY, {})
        return [u for p in provs for u in p["units"]
                if u.get("order", {}).get("type") == "DISBAND"]

    def test_the_deficit_cull_gives_up_the_next_unit_instead(self):
        """Skipped at selection rather than refused at the end, so the host
        still balances its books -- it just gives up somebody else."""
        me, spare = unit("Scout Car"), unit("Scout Car")
        provs = [province(1, [me, spare])]

        scrapped = self.cull(self.tactical(Screen(provs), me), provs)

        self.assertEqual(scrapped, [spare])

    def test_nothing_goes_when_the_player_is_the_only_candidate(self):
        me = unit("Scout Car")
        provs = [province(1, [me])]

        self.assertEqual(self.cull(self.tactical(Screen(provs), me), provs), [])

    def test_a_player_playing_as_militia_is_not_stood_down_at_peace(self):
        me, spare = self.militia(), self.militia()

        ai_construction._disband_peacetime_militia(
            "Avaria", [province(1, [me, spare])], at_war=False, protected=me)

        self.assertEqual(me["order"]["type"], "MOVE")
        self.assertEqual(spare["order"]["type"], "DISBAND")

    def test_strategic_mode_protects_nobody(self):
        """player_unit outlives tactical mode -- declaring independence turns
        the mode off and leaves the attribute set. It is the mode that decides."""
        me = unit("Scout Car")
        provs = [province(1, [me])]
        screen = Screen(provs)
        screen.tactical_mode = False
        screen.player_unit = me

        self.assertEqual(self.cull(screen, provs), [me])

    def test_a_screen_with_no_tactical_mode_at_all_is_survivable(self):
        """The editor's map tools build screens without either attribute."""
        self.assertIsNone(ai_construction.tactical_player_unit(Screen([province(1, [])])))


class FuelGuardTests(unittest.TestCase):
    """upk_fuel was accumulated by the purchase loop and never once read.

    So a nation bought tanks and ships until its materials ran out, no matter
    what they cost to run: on the reported save the German Reich was spending
    2.43x its fuel income on upkeep with ten fuel-burning units on order.
    """

    def buy(self, ratio_fuel, target_fuel=0.7):
        """One purchase pass, and what came out of it."""
        provs = [province(1, [])]
        screen = Screen(provs, at_war=())
        data = screen.nation_data["Avaria"]
        data.update({"materials": 100000, "manpower": 100000, "fuel": 100000})

        values = {"Scout Car": value("Scout Car", 9.0),   # burns fuel, rated best
                  "Rifles": value("Rifles", 5.0)}         # burns none
        state = {
            "target_man": 0.8, "target_mat": 0.6, "target_fuel": target_fuel,
            "inc_man": 1000.0, "inc_mat": 1000.0, "inc_fuel": 1000.0,
            "upk_man": 0.0, "upk_mat": 0.0, "upk_fuel": ratio_fuel * 1000.0,
            "econ": {"total_inc": {"materials": 1000, "manpower": 1000, "fuel": 1000},
                     "upkeep": {"materials": 0, "manpower": 0, "fuel": 0}},
            "unit_values": values,
            "role_targets": {ai_unit_eval.ROLE_LINE: 50.0},
            "role_counts": {},
        }

        real_sites = ai_construction._recruit_sites
        ai_construction._recruit_sites = lambda *a: {"militia": provs, "factory": provs,
                                                     "naval": provs}
        try:
            ai_construction._run_purchase_loop(
                screen, "Avaria", data, provs, LIBRARY, {}, state)
        finally:
            ai_construction._recruit_sites = real_sites
        return [q["unit_type"] for q in provs[0]["unit_queue"]]

    def test_a_nation_within_its_fuel_budget_buys_the_unit_it_rates_best(self):
        bought = self.buy(ratio_fuel=0.1)
        self.assertIn("Scout Car", bought)

    def test_a_nation_over_its_fuel_budget_buys_no_more_fuel_units(self):
        self.assertNotIn("Scout Car", self.buy(ratio_fuel=2.43))

    def test_it_keeps_raising_troops_that_need_no_fuel(self):
        """Fuel cannot join the materials/manpower break: most units burn none,
        and stopping outright would leave a nation unable to afford armour and
        therefore unable to raise infantry either."""
        self.assertIn("Rifles", self.buy(ratio_fuel=2.43))

    def test_it_does_not_bank_money_for_a_tank_it_cannot_run(self):
        """Saving up for something unaffordable to operate is the same mistake
        as buying it -- and would stop the nation buying anything at all."""
        self.assertTrue(self.buy(ratio_fuel=2.43), "bought nothing, so it banked instead")


class DeficitAccountingTests(unittest.TestCase):
    """Which resources count as short, and against which upkeep."""

    TARGETS = {"manpower": 0.8, "materials": 0.6, "fuel": 0.7}

    def test_a_resource_inside_its_target_is_not_a_deficit(self):
        over = ai_construction._deficit_list(
            {"manpower": 10, "materials": 10, "fuel": 10},
            {"manpower": 100, "materials": 100, "fuel": 100}, self.TARGETS)
        self.assertEqual(over, [])

    def test_each_resource_reports_under_the_stat_that_buys_it(self):
        over = ai_construction._deficit_list(
            {"manpower": 0, "materials": 0, "fuel": 90},
            {"manpower": 100, "materials": 100, "fuel": 100}, self.TARGETS)
        self.assertEqual(over, ["cost_fuel"])

    def test_no_income_at_all_counts_as_short(self):
        over = ai_construction._deficit_list(
            {"manpower": 0, "materials": 0, "fuel": 0},
            {"manpower": 0, "materials": 0, "fuel": 0}, self.TARGETS)
        self.assertEqual(sorted(over), ["cost_fuel", "cost_manpower", "cost_materials"])

    def test_exactly_on_target_is_not_over_it(self):
        over = ai_construction._deficit_list(
            {"manpower": 80, "materials": 60, "fuel": 70},
            {"manpower": 100, "materials": 100, "fuel": 100}, self.TARGETS)
        self.assertEqual(over, [])


if __name__ == "__main__":
    unittest.main()
