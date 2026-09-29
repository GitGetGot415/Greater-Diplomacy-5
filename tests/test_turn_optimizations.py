"""Turn caches must save work while preserving rules, ordering and visibility."""

import contextlib
import io
import os
import random
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from data import constants as c, queries
from map_logic.ai import ai_movement, ai_unit_eval, ai_tech_eval
from map_logic.diplomacy import diplomacy_processor as dp, diplomacy_messages as messages
from map_logic.rendering import refresh_map
from map_logic.turn_processing import combat_rules, edit_province_ownership
from tests.stub_map_screen import StubMapScreen
from tests import test_ai_orders


class SparseDiplomacyTests(unittest.TestCase):
    def test_pairs_keep_nation_order_and_deduplicate_opposite_proposals(self):
        data = {name: {} for name in ("C", "A", "B")}
        data.update({f"Dormant {i}": {} for i in range(500)})
        messages.set_pending(data, "B", "A", "WAR_DECLARATION")
        messages.set_pending(data, "A", "B", "FACTION_INVITE")
        messages.set_pending(data, "C", "A", "JOIN_FACTION_REQ")
        self.assertEqual(dp._pending_clash_pairs(data), [("C", "A"), ("A", "B")])

    def test_delayed_legacy_unknown_and_self_entries_do_not_clash(self):
        data = {"A": {"pending_diplomacy": {
            "B": {"action": "WAR_DECLARATION", "turns": 1},
            "C": "FACTION_INVITE", "Missing": {}, "A": {},
        }}, "B": {}, "C": {}}
        self.assertEqual(dp._pending_clash_pairs(data), [])

    def test_one_way_war_cancels_responses_in_both_directions_only_when_due(self):
        for sender, target in (("A", "B"), ("B", "A")):
            for action in dp._WAR_CANCELS:
                with self.subTest(sender=sender, action=action):
                    game = StubMapScreen(["A", "B"])
                    entry = messages.set_pending(game.nation_data, sender, target,
                                                 "WAR_DECLARATION", turns=1)
                    messages.set_response(game.nation_data, target, sender,
                                          messages.RESPONSE_ACCEPT, action)
                    dp._resolve_simultaneous_clashes(game)
                    self.assertTrue(messages.get_response(game.nation_data, target, sender))
                    entry["turns"] = 0
                    dp._resolve_simultaneous_clashes(game)
                    self.assertFalse(messages.get_response(game.nation_data, target, sender))

    def test_pair_reads_live_actions_after_an_earlier_effect_removes_them(self):
        game = StubMapScreen(["A", "B", "C"])
        for target in ("B", "C"):
            messages.set_pending(game.nation_data, "A", target, "CEASEFIRE")
            messages.set_pending(game.nation_data, target, "A", "CEASEFIRE")

        def settle(data, left, right):
            messages.clear_pending(data, "A", "C")

        with mock.patch.object(dp, "finalize_neutral", side_effect=settle) as effect:
            dp._resolve_simultaneous_clashes(game)
        effect.assert_called_once_with(game.nation_data, "A", "B")


class PathSearchCacheTests(unittest.TestCase):
    def setUp(self):
        self.provinces = {
            1: {"id": 1, "neighbors": [2, 3], "owner": "A"},
            2: {"id": 2, "neighbors": [1, 4], "owner": "A"},
            3: {"id": 3, "neighbors": [1, 4], "owner": "A"},
            4: {"id": 4, "neighbors": [2, 3], "owner": "B"},
        }
        self.neighbors = ai_movement.build_neighbor_index(self.provinces)
        self.cache = {}

    def route(self, assignments, targets=(2, 3), cache=True, **kwargs):
        return ai_movement._bfs_nearest_target(
            1, set(targets), set(self.provinces), self.provinces, assignments,
            water_ids=set(), neighbor_ids=self.neighbors,
            path_cache=self.cache if cache else None, **kwargs)

    def test_reused_search_still_balances_changing_assignments(self):
        with mock.patch.object(ai_movement, "_search_target_paths",
                               wraps=ai_movement._search_target_paths) as search:
            self.assertEqual(self.route({2: 0, 3: 1}), [2])
            self.assertEqual(self.route({2: 2, 3: 1}), [3])
        self.assertEqual(search.call_count, 1)

    def test_cached_paths_are_independent_and_match_uncached_decisions(self):
        rng = random.Random(71)
        for _ in range(20):
            assignments = {target: rng.randrange(5) for target in (2, 3, 4)}
            cached = self.route(assignments, targets=(2, 3, 4))
            self.assertEqual(cached, self.route(assignments, targets=(2, 3, 4), cache=False))
            cached.clear()  # A caller's path truncation must not corrupt the search.

    def test_target_set_speed_and_transport_rules_have_separate_searches(self):
        self.route({}, targets=(2,))
        self.route({}, targets=(3,))
        self.route({}, targets=(3,), unit_speed=2)
        self.assertEqual(self.route({}, targets=(3,), is_ship=True), [])
        self.assertEqual(self.route({}, targets=(3,), is_convoy=True), [])
        self.assertEqual(len(self.cache), 5)

    def test_cached_search_rechecks_current_capacity_and_headcounts(self):
        capacity = {2: 1, 3: 1}
        full = int(c.AI_RESERVE_DEPTH) + 1
        self.assertEqual(self.route({}, target_stacks={2: full}, target_capacity=capacity), [3])
        self.assertEqual(self.route({}, target_stacks={3: full}, target_capacity=capacity), [2])

    def test_search_storage_is_bounded_and_empty_results_are_cached(self):
        for i in range(ai_movement._PATH_SEARCH_CACHE_LIMIT + 1):
            self.route({}, targets=(1000 + i,))
        self.assertLessEqual(len(self.cache), ai_movement._PATH_SEARCH_CACHE_LIMIT)
        with mock.patch.object(ai_movement, "_search_target_paths",
                               wraps=ai_movement._search_target_paths) as search:
            self.route({}, targets=(9999,))
            self.route({}, targets=(9999,))
        self.assertEqual(search.call_count, 1)


class AttackPreviewCacheTests(unittest.TestCase):
    def setUp(self):
        # Reuse the artificial combat fixture, not its test methods.
        self.fixture = test_ai_orders.ImmediateLossAttackTests()
        self.screen = self.fixture.screen(self.fixture.defender(attack=500, health=1000))

    def check(self, unit, cache):
        return ai_movement._attack_target_is_immediate_loss(
            self.screen, "Avaria", 2, unit, cache)

    def test_equivalent_units_share_one_preview_but_wounds_do_not(self):
        weak = self.fixture.attacker(attack=1, health=1)
        strong = self.fixture.attacker(attack=1, health=1000)
        cache = {}
        with mock.patch.object(ai_movement, "_attackers_would_survive",
                               wraps=ai_movement._attackers_would_survive) as preview:
            self.assertTrue(self.check(weak, cache))
            self.assertTrue(self.check(dict(weak, custom_name="Another division"), cache))
            self.assertFalse(self.check(strong, cache))
        self.assertEqual(preview.call_count, 2)

    def test_replanning_does_not_reuse_changed_defender_stats(self):
        unit = self.fixture.attacker(attack=1, health=1)
        home = self.screen.map_data["home"]
        home["units"] = [unit]
        for defender_attack in (500, 0):
            self.screen.map_data["near"]["units"][0]["attack"] = defender_attack
            ai_movement._assign_unit_orders(
                self.screen, "Avaria", [(unit, home)], self.fixture.context(),
                {1, 2}, set(), {1: [2], 2: [1]})
            self.assertEqual(unit["order"]["path"], [] if defender_attack else [2])

    def test_a_unit_already_on_the_target_does_not_share_identity_sensitive_previews(self):
        unit = self.fixture.attacker(attack=1, health=1)
        self.screen.map_data["near"]["units"].append(unit)
        cache = {}
        for attacker in (dict(unit), unit):
            self.assertEqual(self.check(attacker, cache), self.check(attacker, None))

    def test_reserve_pins_volunteer_allegiance_and_missing_health_do_not_alias(self):
        unit = self.fixture.attacker()
        signature = combat_rules.single_attacker_signature(unit)
        for field, value in (("combat_stance", "RESERVE"), ("lane_target", "Bruland"),
                             ("volunteer_host", "Third country"), ("defense", 5),
                             ("max_health", 200), ("attack", 200)):
            self.assertNotEqual(signature, combat_rules.single_attacker_signature(dict(unit, **{field: value})))
        missing = dict(unit)
        missing.pop("health")
        self.assertNotEqual(combat_rules.single_attacker_signature(missing),
                            combat_rules.single_attacker_signature(dict(missing, health=0)))


class ResearchIndexTests(unittest.TestCase):
    def test_indexed_candidates_match_exact_unlock_and_obsolescence_rules(self):
        library = queries.get_unit_library()
        tree = queries.get_tech_tree()
        rng = random.Random(71)
        for _ in range(15):
            research = {tech: rng.randrange(len(info.get("years", ())) + 2)
                        for tech, info in tree.items()}
            expected = {}
            for name in library:
                base = queries.get_base_unit_name(name)
                if queries.is_unit_obsolete(base, research) or not queries.is_unit_unlocked(name, research):
                    continue
                if base not in expected or queries.get_unit_tier(name) > queries.get_unit_tier(expected[base]):
                    expected[base] = name
            self.assertEqual(ai_unit_eval.buildable_units(research, library), sorted(expected.values()))

    def test_new_research_does_not_reparse_names(self):
        library = {"Medium Tank I": {}, "Medium Tank II": {}}
        queries.get_unit_research_index(library)
        with mock.patch.object(queries, "get_unit_unlock_requirement", side_effect=AssertionError("reparsed")):
            self.assertEqual(ai_unit_eval.buildable_units({"medium_tank": 1}, library), ["Medium Tank I"])
            self.assertEqual(ai_unit_eval.buildable_units({"medium_tank": 2}, library), ["Medium Tank II"])

    def test_in_place_library_edit_invalidates_candidates_and_tech_unlocks(self):
        library = {"Medium Tank I": {}}
        research = {"medium_tank": 1}
        self.assertEqual(ai_tech_eval.units_unlocked_by("medium_tank", research, library), ())
        library["Medium Tank II"] = {}
        self.assertEqual(ai_unit_eval.buildable_units({"medium_tank": 2}, library), ["Medium Tank II"])
        self.assertEqual(ai_tech_eval.units_unlocked_by("medium_tank", research, library), ("Medium Tank II",))

    def test_in_place_year_edit_and_obsolescence_edit_invalidate(self):
        library = {"Infantry Type 1900": {}, "Infantry Type 1910": {}}
        tree = {"infantry_type": {"years": [1900, 1910]}}
        with mock.patch.object(queries, "get_tech_tree", return_value=tree):
            self.assertEqual(ai_unit_eval.buildable_units({"infantry_type": 1}, library), ["Infantry Type 1900"])
            tree["infantry_type"]["years"].reverse()
            self.assertEqual(ai_unit_eval.buildable_units({"infantry_type": 1}, library), ["Infantry Type 1910"])
            with mock.patch.dict(c.OBSOLESCENCE_RULES, {"Infantry Type": ["replacement"]}):
                self.assertEqual(ai_unit_eval.buildable_units({"infantry_type": 1, "replacement": 1}, library), [])

    def test_vehicle_infantry_gate_and_year_both_apply(self):
        family, gate = next(iter(c.VEHICLE_INFANTRY_GATES.items()))
        year = queries.get_tech_tree()["infantry_type"]["years"][0]
        base = next(base for base in ("Motorized Infantry Type", "Mechanized Infantry Type", "Infantry Fighting Vehicle Type")
                    if queries.get_unit_tech_key(base) == family)
        library = {f"{base} {year}": {}}
        self.assertEqual(ai_unit_eval.buildable_units({"infantry_type": 1}, library), [])
        self.assertEqual(ai_unit_eval.buildable_units({gate: 1}, library), [])
        self.assertEqual(ai_unit_eval.buildable_units({gate: 1, "infantry_type": 1}, library), list(library))

    def test_json_refresh_discards_the_index_without_resetting_session_settings(self):
        # Preserve real caches so this test does not reset other screens' data.
        library = {"Medium Tank I": {}}
        original = queries.get_unit_research_index(library)
        configuration = {key: {"data": {"session_value": 1}}
                         for key in ("settings", "scenario_settings", "tech_tree")}
        with mock.patch.object(queries, "_JSON_CACHE", configuration), \
                contextlib.redirect_stdout(io.StringIO()):
            queries.clear_json_caches()
        self.assertEqual(configuration["settings"]["data"], {"session_value": 1})
        self.assertEqual(configuration["scenario_settings"]["data"], {"session_value": 1})
        self.assertIsNone(configuration["tech_tree"]["data"])
        self.assertIsNot(original, queries.get_unit_research_index(library))


class MapSurfaceCacheTests(unittest.TestCase):
    def setUp(self):
        self.screen = SimpleNamespace(
            id_map=pygame.Surface((12, 6)), map_mode="POLITICAL", player_country="A",
            nation_colors={"A": (200, 30, 20), "B": (30, 200, 20)},
            nation_data={"A": {}, "B": {}}, selection_mode=False,
            viewing_ai_moves=False, active_players=["A"], scenario_settings={},
        )
        colors = ((1, 0, 0), (2, 0, 0))
        self.screen.map_data = {color: {"id": i, "owner": owner, "terrain": "plains",
                                                "cores": [owner], "map_color": color, "neighbors": []}
                                for i, (color, owner) in enumerate(zip(colors, ("A", "B")), 1)}
        self.screen.id_to_province = {p["id"]: p for p in self.screen.map_data.values()}
        for i, color in enumerate(colors):
            self.screen.id_map.fill(color, (i * 6, 0, 6, 6))

    def refresh(self, function):
        with contextlib.redirect_stdout(io.StringIO()):
            function(self.screen)

    def test_all_modes_reuse_surfaces_then_match_a_forced_rebuild(self):
        modes = ((refresh_map.refresh_political_map, "political_map"),
                 (refresh_map.refresh_cores_map, "cores_map"),
                 (refresh_map.refresh_relations_map, "relations_map"),
                 (refresh_map.refresh_factions_map, "factions_map"),
                 (refresh_map.refresh_faction_territories_map, "faction_territories_map"))
        for function, attr in modes:
            with self.subTest(layer=attr):
                self.refresh(function)
                original = getattr(self.screen, attr)
                with mock.patch.object(refresh_map, "_build_map_surface", side_effect=AssertionError("rebuilt")):
                    self.refresh(function)
                self.assertIs(original, getattr(self.screen, attr))
                refresh_map.invalidate_map_surface_cache(self.screen, attr)
                self.refresh(function)
                self.assertTrue(np.array_equal(pygame.surfarray.array3d(original),
                                               pygame.surfarray.array3d(getattr(self.screen, attr))))

    def test_ownership_colors_terrain_and_geometry_invalidate_political_pixels(self):
        self.refresh(refresh_map.refresh_political_map)
        province = self.screen.id_to_province[1]
        for mutate in (lambda: province.update(owner="B"),
                       lambda: self.screen.nation_colors.update(B=(10, 20, 200)),
                       lambda: province.update(terrain=next(iter(c.VISUAL_WATER_MAPPING))),
                       lambda: setattr(self.screen, "id_map", self.screen.id_map.copy())):
            previous = self.screen.political_map
            mutate()
            self.refresh(refresh_map.refresh_political_map)
            self.assertIsNot(previous, self.screen.political_map)

    def test_core_faction_leader_and_prewar_border_changes_invalidate(self):
        self.refresh(refresh_map.refresh_cores_map)
        old = self.screen.cores_map
        self.screen.id_to_province[1]["cores"].append("B")
        self.refresh(refresh_map.refresh_cores_map)
        self.assertIsNot(old, self.screen.cores_map)
        self.screen.nation_data["A"].update(faction="Pact", is_faction_leader=True)
        self.screen.nation_data["B"].update(faction="Pact", is_faction_leader=False)
        self.refresh(refresh_map.refresh_factions_map)
        old = self.screen.factions_map
        self.screen.nation_data["A"]["is_faction_leader"] = False
        self.screen.nation_data["B"]["is_faction_leader"] = True
        self.refresh(refresh_map.refresh_factions_map)
        self.assertIsNot(old, self.screen.factions_map)
        self.refresh(refresh_map.refresh_faction_territories_map)
        old = self.screen.faction_territories_map
        self.screen.nation_data["FACTION_WAR_MAPS"] = {"Pact": {"1": "B", "2": "A"}}
        self.refresh(refresh_map.refresh_faction_territories_map)
        self.assertIsNot(old, self.screen.faction_territories_map)

    def test_faction_leader_is_resolved_once_for_all_member_provinces(self):
        self.screen.nation_data["A"].update(faction="Pact", is_faction_leader=True)
        self.screen.nation_data["B"].update(faction="Pact", is_faction_leader=False)
        with mock.patch.object(queries, "get_faction_leader", wraps=queries.get_faction_leader) as leader:
            self.refresh(refresh_map.refresh_factions_map)
        leader.assert_called_once_with("Pact", self.screen.nation_data)

    def test_relations_recompute_for_new_perspective_and_changed_scores(self):
        with mock.patch.object(queries, "get_relation_score", return_value=-100) as score:
            self.refresh(refresh_map.refresh_relations_map)
            old = self.screen.relations_map
            self.screen.player_country = "B"
            self.refresh(refresh_map.refresh_relations_map)
            self.assertIsNot(old, self.screen.relations_map)
            old = self.screen.relations_map
            score.return_value = 100
            self.refresh(refresh_map.refresh_relations_map)
            self.assertIsNot(old, self.screen.relations_map)

    def test_incremental_core_paint_cannot_poison_a_later_cache_hit(self):
        self.screen.ai_is_thinking = False
        self.refresh(refresh_map.refresh_cores_map)
        before = pygame.surfarray.array3d(self.screen.cores_map)
        with mock.patch.object(edit_province_ownership, "get_mixed_core_color", return_value=(5, 6, 7)):
            edit_province_ownership.refresh_core_tint(self.screen, self.screen.id_to_province[1], ["A"])
        self.refresh(refresh_map.refresh_cores_map)
        self.assertTrue(np.array_equal(before, pygame.surfarray.array3d(self.screen.cores_map)))

    def test_fog_reuses_pixels_but_always_updates_visibility_and_hotseat_blanking(self):
        with mock.patch.object(c, "USE_FOG_OF_WAR", True), \
                mock.patch.object(queries, "get_visible_provinces", return_value=({1}, {2})) as vision:
            self.refresh(refresh_map.refresh_fog_map)
            old = self.screen.fog_map
            self.screen.visible_provinces = set()
            self.refresh(refresh_map.refresh_fog_map)
            self.assertIs(old, self.screen.fog_map)
            self.assertEqual(self.screen.visible_provinces, {1})
            self.assertEqual(vision.call_count, 2)
            vision.return_value = ({2}, {1})
            self.refresh(refresh_map.refresh_fog_map)
            self.assertIsNot(old, self.screen.fog_map)
            self.screen.viewing_ai_moves = True
            self.screen.active_players = ["A", "B"]
            self.refresh(refresh_map.refresh_fog_map)
            self.assertEqual(self.screen.visible_provinces, set())
            self.assertEqual(self.screen.partial_visible_provinces, set())
            self.assertTrue(np.all(pygame.surfarray.array_alpha(self.screen.fog_map) == c.FOG_OF_WAR_ALPHA))

    def test_fog_selection_spectator_and_strength_transitions(self):
        with mock.patch.object(c, "USE_FOG_OF_WAR", True), \
                mock.patch.object(queries, "get_visible_provinces", return_value=(set(), set())) as vision:
            self.refresh(refresh_map.refresh_fog_map)
            old = self.screen.fog_map
            self.screen.scenario_settings["fog_of_war_strength"] = "extreme"
            self.refresh(refresh_map.refresh_fog_map)
            self.assertIsNot(old, self.screen.fog_map)
            self.assertEqual(self.screen.extreme_hidden_provinces, {1, 2})
            self.screen.selection_mode = True
            self.refresh(refresh_map.refresh_fog_map)
            self.assertIsNone(self.screen.fog_map)
            self.screen.selection_mode = False
            vision.return_value = (None, None)
            self.refresh(refresh_map.refresh_fog_map)
            self.assertIsNone(self.screen.fog_map)
            self.assertIsNone(self.screen.visible_provinces)


if __name__ == "__main__":
    unittest.main()
