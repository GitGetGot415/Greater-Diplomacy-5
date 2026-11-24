"""Turn caches must save work while preserving rules, ordering and visibility."""

import contextlib
import io
import random
import unittest
from types import SimpleNamespace
from unittest import mock


import numpy as np
import pygame

from data import constants as c, queries
from data.queries import relations
from map_logic import politics
from map_logic.ai import ai_movement, ai_unit_eval, ai_tech_eval
from map_logic.diplomacy import diplomacy_processor as dp, diplomacy_messages as messages, faction_records
from ui.information import ui_info_popup
from ui.rendering import refresh_map
from screens.game import map_input
from screens.game.map import Map
from map_logic.system32 import combat_rules
from map_logic.territory import ownership
from tests.stub_map_screen import StubMapScreen, map_double
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
            for action in dp.WAR_CANCELLED_ACTIONS:
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
        with mock.patch.object(queries, "get_unit_requirements", side_effect=AssertionError("reparsed")):
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
        self.screen = map_double(
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
                       lambda: province.update(terrain=next(iter(refresh_map.VISUAL_WATER_MAPPING))),
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
        nation_data = self.screen.world.nation_data
        queries.set_country_faction(nation_data, "A", "Pact")
        queries.set_country_faction(nation_data, "B", "Pact")
        queries.set_faction_leadership(nation_data, "A", True)
        self.refresh(refresh_map.refresh_factions_map)
        old = self.screen.factions_map
        queries.set_faction_leadership(nation_data, "A", False)
        queries.set_faction_leadership(nation_data, "B", True)
        self.refresh(refresh_map.refresh_factions_map)
        self.assertIsNot(old, self.screen.factions_map)
        self.refresh(refresh_map.refresh_faction_territories_map)
        old = self.screen.faction_territories_map
        faction_records.set_pre_war_map(nation_data, "Pact", {"1": "B", "2": "A"})
        self.refresh(refresh_map.refresh_faction_territories_map)
        self.assertIsNot(old, self.screen.faction_territories_map)

    def test_faction_leader_is_resolved_once_for_all_member_provinces(self):
        self.screen.nation_data["A"].update(faction="Pact", is_faction_leader=True)
        self.screen.nation_data["B"].update(faction="Pact", is_faction_leader=False)
        with mock.patch.object(queries, "get_faction_leader", wraps=queries.get_faction_leader) as leader:
            self.refresh(refresh_map.refresh_factions_map)
        leader.assert_called_once_with("Pact", self.screen.nation_data)

    def test_relations_recompute_for_new_perspective_and_changed_scores(self):
        score = {"value": -100}

        def scores(viewpoint, nations, *_args):
            return {nation: score["value"] for nation in nations}

        with mock.patch.object(queries, "get_relation_scores_from", side_effect=scores):
            self.refresh(refresh_map.refresh_relations_map)
            old = self.screen.relations_map
            self.screen.player_country = "B"
            self.refresh(refresh_map.refresh_relations_map)
            self.assertIsNot(old, self.screen.relations_map)
            old = self.screen.relations_map
            score["value"] = 100
            self.refresh(refresh_map.refresh_relations_map)
            self.assertIsNot(old, self.screen.relations_map)

    def test_batch_relation_scores_match_pairwise_scores(self):
        provinces = {
            1: {"id": 1, "owner": "A", "cores": ["B", "C"]},
            2: {"id": 2, "owner": "B", "cores": ["A"]},
            3: {"id": 3, "owner": "B", "cores": []},
            4: {"id": 4, "owner": "C", "cores": ["B", "B"]},
            5: {"id": 5, "owner": "B", "cores": ["C"]},
        }
        data = {
            "A": {"claims": [3, 2], "temp_modifiers": {"B": {"general": 25}}},
            "B": {"claims": [1, 4]},
            "C": {"claims": [3], "temp_modifiers": {"B": {"general": -40}}},
        }
        for viewpoint in data:
            for id_to_province in (provinces, None):
                with self.subTest(viewpoint=viewpoint, with_claims=bool(id_to_province)):
                    self.assertEqual(
                        queries.get_relation_scores_from(viewpoint, list(data), data, id_to_province),
                        {nation: queries.get_relation_score(viewpoint, nation, data, id_to_province)
                         for nation in data})

    def test_relations_map_and_opinion_breakdown_follow_compass_drift(self):
        self.screen.map_mode = "RELATIONS"
        self.screen.selected_province = self.screen._relations_hovered_province = self.province_of("B")
        self.screen._presentation_cache_revision = 0
        self.screen._relation_indicator_cache = None
        self.screen.nation_data["A"].update({politics.VALUE_KEY: c.POLITICS_MAX, politics.ECONOMIC_VALUE_KEY: c.POLITICS_MIN})
        queries.add_temporary_modifier("B", "A", "general", -30, self.screen.nation_data)
        politics.set_drift(self.screen.nation_data, "B", 1)
        politics.set_economic_drift(self.screen.nation_data, "B", -1)

        self.refresh(refresh_map.refresh_relations_map)
        # Everyone sees an authoritarian A with its reputation.
        a_reputation = round(politics.effect_at("reputation", c.POLITICS_MAX))
        self.assertEqual(self.screen._relations_scores["A"], -30 + a_reputation)
        ui_info_popup.prepare_relation_indicators(self.screen)

        politics.tick(self.screen)
        politics.tick(self.screen)
        self.screen._presentation_cache_revision += 1
        self.refresh(refresh_map.refresh_relations_map)
        ui_info_popup.prepare_relation_indicators(self.screen)

        # B drifted toward A on both axes, so the shared rule now adds goodwill both ways.
        affinity = relations._political_affinity("A", "B", self.screen.nation_data)
        self.assertGreater(affinity, 0)
        b_reputation = round(politics.effect_at("reputation", politics.value(self.screen.nation_data, "B")))
        self.assertEqual(self.screen._relations_scores["A"], -30 + affinity + a_reputation)
        _, (their_opinion, our_opinion) = self.screen._relation_indicator_cache
        self.assertEqual(their_opinion[1], -30 + affinity + a_reputation)
        self.assertEqual(our_opinion[1], affinity + b_reputation)
        affinity_label = ui_info_popup.RELATION_FACTORS["political_affinity"]
        self.assertIn((affinity_label, affinity), their_opinion[2])
        self.assertIn((affinity_label, affinity), our_opinion[2])
        reputation_label = ui_info_popup.RELATION_FACTORS["political_reputation"]
        self.assertIn((reputation_label, a_reputation), their_opinion[2])

    def show_relations(self):
        self.screen.map_mode = self.screen.base_layer = "RELATIONS"
        self.screen.nation_data["A"]["temp_modifiers"] = {"B": {"general": -30}}
        self.screen.nation_data["B"]["temp_modifiers"] = {"A": {"general": 15}}
        self.screen.camera = SimpleNamespace(pos=pygame.Vector2(), zoom=1, tilt_factor=1)
        self.screen.map_w, self.screen.map_h = self.screen.id_map.get_size()
        self.screen.top_ui_height = 0
        self.screen.touch_map_at = mock.Mock(return_value=self.screen)
        self.refresh(refresh_map.refresh_relations_map)

    def province_of(self, owner):
        return next(p for p in self.screen.map_data.values() if p["owner"] == owner)

    def hover(self, position, *, focused=True, workspace=None):
        with (mock.patch.object(pygame.mouse, "get_focused", return_value=focused),
              mock.patch.object(pygame.mouse, "get_pos", return_value=position)):
            map_input.update_relations_hover(self.screen, workspace=workspace)

    def add_internal_seam(self):
        color = (3, 0, 0)
        province = dict(self.province_of("B"), id=3, map_color=color)
        self.screen.map_data[color] = self.screen.id_to_province[3] = province
        self.screen.id_map.fill((0, 0, 0), (8, 0, 1, 6))
        self.screen.id_map.fill(color, (9, 0, 3, 6))
        return province

    def test_relations_keeps_its_viewpoint_across_an_internal_seam_under_fog(self):
        self.add_internal_seam()
        self.show_relations()
        self.screen.visible_provinces = {1}
        self.screen.partial_visible_provinces = {2}
        self.screen.camera.zoom = 2
        self.screen.camera.tilt_factor = 0.5
        self.screen.top_ui_height = 10
        self.hover((14, 12))
        self.assertEqual(self.screen._relations_viewpoint, "B")
        previous = self.screen.relations_map
        with mock.patch.object(queries, "get_relation_scores_from", side_effect=AssertionError("recomputed")):
            self.hover((16, 12))
            self.assertEqual(self.screen._relations_viewpoint, "B")
            self.assertIs(self.screen.relations_map, previous)
            self.hover((18, 12))
        self.assertIsNone(queries.get_clicked_province((16, 12), self.screen))

    def test_relations_resolves_a_one_pixel_seam_before_checking_farther_away(self):
        self.add_internal_seam()
        border_color = self.province_of("A")["map_color"]
        self.screen.id_map.set_at((8, 0), border_color)
        self.show_relations()

        self.hover((8, 2))
        self.assertEqual(self.screen._relations_viewpoint, "B")
        self.hover((8, 1))
        self.assertEqual(self.screen._relations_viewpoint, "A")

    def test_relations_rejects_a_seam_at_foreign_water_unowned_or_hidden_land(self):
        province = self.add_internal_seam()
        self.show_relations()
        for owner, terrain, extreme_hidden in (
            ("A", "plains", set()),
            ("B", "ocean", set()),
            ("Unclaimed", "plains", set()),
            ("B", "plains", {3}),
        ):
            with self.subTest(owner=owner, terrain=terrain, extreme_hidden=extreme_hidden):
                province.update(owner=owner, terrain=terrain)
                self.screen.extreme_hidden_provinces = extreme_hidden
                self.hover((7, 2))
                self.assertEqual(self.screen._relations_viewpoint, "B")
                self.hover((8, 2))
                self.assertEqual(self.screen._relations_viewpoint, "A")

    def test_relations_seam_does_not_reveal_a_fogged_tile_to_tournament_spectators(self):
        self.add_internal_seam()
        self.screen.player_country = c.TOURNAMENT_SPECTATOR
        self.show_relations()
        self.screen.visible_provinces = {2}

        self.hover((7, 2))
        self.assertEqual(self.screen._relations_viewpoint, "B")
        self.hover((8, 2))
        self.assertEqual(self.screen._relations_viewpoint, c.TOURNAMENT_SPECTATOR)

    def test_relations_tooltip_displays_only_the_country_name_on_a_seam(self):
        from ui.information import tooltip

        self.add_internal_seam()
        self.show_relations()
        self.screen.nation_data["B"]["name"] = "Fixture Country"
        self.screen.hovered_province = self.screen.hovered_unit_stack = self.screen.hovered_combat_bubble = None
        self.screen.small_font = mock.Mock()
        self.screen.small_font.render.return_value = pygame.Surface((1, 1))
        self.hover((8, 2))

        with (mock.patch.object(tooltip, "_province_tooltip_lines", side_effect=AssertionError("province tooltip")),
              mock.patch.object(pygame.mouse, "get_pos", return_value=(8, 2))):
            tooltip.draw_tooltip(self.screen, pygame.Surface((50, 50)))
        self.assertEqual([call.args[0] for call in self.screen.small_font.render.call_args_list], ["Fixture Country"])

    def test_country_gap_wraps_only_on_a_looping_map(self):
        self.add_internal_seam()
        self.screen.id_map.fill((0, 0, 0), (0, 0, 1, 6))
        self.screen.id_map.fill((2, 0, 0), (1, 0, 2, 6))
        self.show_relations()

        self.hover((0, 2))
        self.assertEqual(self.screen._relations_viewpoint, "A")
        self.screen.loop_map = True
        self.hover((0, 2))
        self.assertEqual(self.screen._relations_viewpoint, "B")

    def test_country_picker_accepts_the_seam_and_tactical_picker_requires_a_hit(self):
        self.add_internal_seam()
        self.show_relations()
        self.screen.selection_mode = True
        self.screen.pending_selection = None
        self.screen.secondary_mode = "BLANK"
        self.screen.nation_data["B"]["is_playable"] = True
        self.screen.show_feedback = mock.Mock()
        self.screen.unit_hover_hitboxes = []
        self.screen._tooltip_building_stamp = None
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(8, 2))

        with (mock.patch.object(map_input.player_setup, "select_tactical_unit") as tactical,
              mock.patch.object(map_input.sound_effects, "play_ui_sound")):
            self.screen.tactical_mode = True
            map_input._update_map_hover(self.screen, False, *event.pos)
            map_input._handle_country_selection(self.screen, event, *event.pos, False)
            tactical.assert_not_called()
            self.assertIsNone(self.screen.pending_selection)

            self.screen.tactical_mode = False
            map_input._handle_country_selection(self.screen, event, *event.pos, False)
        self.assertEqual(self.screen.pending_selection, "B")
        self.assertEqual(self.screen.selected_province["owner"], "B")

    def test_the_tooltip_omits_the_hovered_countrys_self_opinion(self):
        from ui.information import tooltip

        self.show_relations()
        self.screen.secondary_mode = "BLANK"
        self.screen.small_font = mock.Mock()
        self.screen.small_font.render.side_effect = lambda *args: pygame.Surface((1, 1))
        self.hover((8, 1))
        self.screen.hovered_province = self.province_of("B")

        with (mock.patch.object(queries, "get_relation_score", side_effect=AssertionError("score recalculated")),
              mock.patch.object(queries, "is_province_visible", return_value=True),
              mock.patch.object(pygame.mouse, "get_pos", return_value=(1, 1))):
            tooltip.draw_tooltip(self.screen, pygame.Surface((50, 50)))
        lines = [call.args[0] for call in self.screen.small_font.render.call_args_list]
        self.assertFalse(any("opinion" in line for line in lines))

    def test_the_view_shows_outgoing_opinions_and_reuses_the_same_owners_surface(self):
        self.show_relations()
        self.assertEqual(self.screen._relations_viewpoint, "A")
        self.assertEqual(self.screen._relations_scores["B"], -30)
        player_view = self.screen.active_map

        self.screen.selected_province = self.province_of("A")
        self.hover((8, 1))
        self.assertEqual(self.screen._relations_viewpoint, "B")
        self.assertEqual(self.screen._relations_scores["A"], 15)
        self.assertIs(self.screen.active_map, self.screen.relations_map)
        self.assertIsNot(self.screen.active_map, player_view)
        with mock.patch.object(queries, "get_relation_scores_from", side_effect=AssertionError("recomputed")):
            self.hover((9, 1))

    def test_own_land_water_and_unowned_land_restore_the_players_view(self):
        self.show_relations()
        water = dict(self.province_of("B"), terrain="ocean")
        unowned = dict(self.province_of("B"), owner="Unclaimed")
        for province in (self.province_of("A"), water, unowned, None):
            with self.subTest(province=province):
                self.hover((8, 1))
                with mock.patch.object(queries, "get_clicked_province", return_value=province):
                    self.hover((2, 1))
                self.assertEqual(self.screen._relations_viewpoint, "A")
                self.assertEqual(self.screen._relations_scores["B"], -30)

    def test_ui_hidden_tiles_and_leaving_the_window_restore_the_players_view(self):
        self.show_relations()
        self.hover((8, 1))
        self.screen.touch_map_at.return_value = None
        self.hover((8, 1))
        self.assertEqual(self.screen._relations_viewpoint, "A")

        self.screen.touch_map_at.return_value = self.screen
        self.hover((8, 1))
        self.screen.extreme_hidden_provinces = {self.province_of("B")["id"]}
        self.hover((8, 1))
        self.assertEqual(self.screen._relations_viewpoint, "A")

        self.screen.extreme_hidden_provinces = set()
        self.hover((8, 1))
        self.hover((8, 1), focused=False)
        self.assertEqual(self.screen._relations_viewpoint, "A")

    def test_deselecting_leaves_the_view_at_the_pointer(self):
        self.show_relations()
        self.screen.selected_province = self.province_of("B")
        self.hover((8, 1))
        self.screen.mail_draft_text = ""
        self.screen.elements = []
        self.screen.show_feedback = mock.Mock()
        with (mock.patch("screens.game.map_buttons.update_button_states"),
              mock.patch.object(queries, "get_relation_scores_from", side_effect=AssertionError("recomputed"))):
            Map.deselect_province(self.screen)
            self.hover((8, 1))
        self.assertIsNone(self.screen.selected_province)
        self.assertEqual(self.screen._relations_viewpoint, "B")

    def test_stationary_pointer_follows_camera_movement(self):
        self.show_relations()
        self.hover((2, 1))
        self.assertEqual(self.screen._relations_viewpoint, "A")
        self.screen.camera.pos.x = 6
        self.hover((2, 1))
        self.assertEqual(self.screen._relations_viewpoint, "B")

    def test_hover_uses_the_active_orders_workspaces_hit_test(self):
        self.show_relations()
        self.screen.touch_map_at.return_value = None
        workspace = SimpleNamespace(touch_map_at=mock.Mock(return_value=self.screen))
        self.hover((8, 1), workspace=workspace)
        self.assertEqual(self.screen._relations_viewpoint, "B")
        workspace.touch_map_at.return_value = None
        self.hover((8, 1), workspace=workspace)
        self.assertEqual(self.screen._relations_viewpoint, "A")

    def test_entering_relations_uses_the_current_pointer(self):
        self.show_relations()
        self.refresh(refresh_map.refresh_political_map)
        self.screen.terrain_map = self.screen.factions_map = self.screen.cores_map = self.screen.faction_territories_map = None
        self.screen.update_country_centers = mock.Mock()
        self.screen.show_feedback = mock.Mock()

        Map.set_map_layer(self.screen, "POLITICAL")
        self.assertIs(self.screen.active_map, self.screen.political_map)
        with (mock.patch.object(pygame.mouse, "get_focused", return_value=True),
              mock.patch.object(pygame.mouse, "get_pos", return_value=(8, 1))):
            Map.set_map_layer(self.screen, "RELATIONS")
        self.assertEqual(self.screen._relations_viewpoint, "B")
        self.assertEqual(self.screen._relations_scores["A"], 15)

    def test_refresh_uses_the_hovered_provinces_current_owner(self):
        self.show_relations()
        province = self.province_of("B")
        self.hover((8, 1))
        self.screen.nation_data["B"]["temp_modifiers"]["A"]["general"] = 25
        self.refresh(refresh_map.refresh_relations_map)
        self.assertEqual(self.screen._relations_scores["A"], 25)
        province["owner"] = "A"
        self.refresh(refresh_map.refresh_relations_map)
        self.assertEqual(self.screen._relations_viewpoint, "A")

    def test_incremental_core_paint_cannot_poison_a_later_cache_hit(self):
        self.screen.ai_is_thinking = False
        self.refresh(refresh_map.refresh_cores_map)
        before = pygame.surfarray.array3d(self.screen.cores_map)
        with mock.patch.object(ownership, "get_mixed_core_color", return_value=(5, 6, 7)):
            ownership.refresh_core_tint(self.screen, self.screen.id_to_province[1], ["A"])
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
            self.assertTrue(np.all(pygame.surfarray.array_alpha(self.screen.fog_map) == refresh_map.FOG_OF_WAR_ALPHA))

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


def _rolled_shading_levels(owner_2d, water_ids):
    """The border shading as first written with np.roll, kept as the reference.

    The live pass reuses buffers, fills gaps on id-map slots and patches only
    around changed provinces; all of that must still produce these bands.
    """
    filled = owner_2d.copy()
    for _ in range(2):
        for shift, axis in ((1, 1), (-1, 1), (1, 0), (-1, 0)):
            gap = filled == 0
            filled[gap] = np.roll(filled, shift, axis=axis)[gap]
    land = ~np.isin(filled, water_ids) & (filled != 0)

    def touching(band):
        return (np.roll(band, 1, axis=1) | np.roll(band, -1, axis=1)
                | np.roll(band, 1, axis=0) | np.roll(band, -1, axis=0))

    edge_1 = land & ((filled != np.roll(filled, 1, axis=1)) | (filled != np.roll(filled, -1, axis=1))
                     | (filled != np.roll(filled, 1, axis=0)) | (filled != np.roll(filled, -1, axis=0)))
    edge_2 = land & ~edge_1 & touching(edge_1)
    edge_3 = land & ~edge_1 & ~edge_2 & touching(edge_2)
    edge_4 = land & ~edge_1 & ~edge_2 & ~edge_3 & touching(edge_3)
    level = np.zeros(owner_2d.shape, dtype=np.uint8)
    level[edge_1] = 1
    level[edge_3] = 2
    level[edge_4] = 3
    level[land & ~edge_1 & ~edge_2 & ~edge_3 & ~edge_4] = 4
    return level


class MapLayerShadingTests(unittest.TestCase):
    """Faster layer builds must paint exactly what a full np.roll rebuild paints."""

    CELL = 9  # 8 px of province, then a 1 px black gap line.
    COLUMNS, ROWS = 16, 10

    def setUp(self):
        self.rng = random.Random(7)
        self.owners = ["A", "B", "C", "D"]
        self.screen = map_double(
            id_map=pygame.Surface((self.CELL * self.COLUMNS, self.CELL * self.ROWS)),
            map_mode="POLITICAL", player_country="A",
            nation_colors={"A": (200, 30, 20), "B": (30, 200, 20), "C": (20, 30, 200), "D": (250, 250, 0)},
            nation_data={name: {} for name in self.owners},
        )
        self.screen.map_data = {}
        for index in range(self.COLUMNS * self.ROWS):
            column, row = divmod(index, self.ROWS)
            color = (index + 1, 7, 9)
            self.screen.id_map.fill(color, (column * self.CELL, row * self.CELL,
                                            self.CELL - 1, self.CELL - 1))
            terrain = "ocean" if index % 11 == 0 else "plains"
            self.screen.map_data[color] = {
                "id": index + 1, "terrain": terrain, "map_color": color, "cores": [],
                "owner": "Ocean" if terrain == "ocean" else self.rng.choice(self.owners + ["Unclaimed"])}
        self.screen.id_to_province = {p["id"]: p for p in self.screen.map_data.values()}

    def political(self):
        with contextlib.redirect_stdout(io.StringIO()):
            refresh_map.refresh_political_map(self.screen)
        return pygame.surfarray.array3d(self.screen.political_map)

    def expected_political(self):
        """The political layer rebuilt from scratch with the reference shading."""
        id_3d = pygame.surfarray.array3d(self.screen.id_map)
        owner_2d = np.zeros(id_3d.shape[:2], dtype=np.int64)
        color_3d = np.zeros(id_3d.shape, dtype=np.uint8)
        owner_ids = {}
        for key, data in self.screen.map_data.items():
            if data["terrain"] in refresh_map.VISUAL_WATER_MAPPING:
                owner, color = "Ocean", c.COLOR_CHROMA_PINK
            else:
                owner = data["owner"]
                color = self.screen.nation_colors.get(owner, refresh_map.UNOWNED_COLOR)
            pixels = np.all(id_3d == key, axis=2)
            owner_2d[pixels] = owner_ids.setdefault(owner, len(owner_ids) + 1)
            color_3d[pixels] = color
        water = [owner_ids.get(name, -1) for name in ("Ocean", "Lakes", "Unclaimed")]
        level = _rolled_shading_levels(owner_2d, water)
        return refresh_map._SHADE_LUT[level[:, :, None], color_3d]

    def change_owners(self, provinces):
        for province_id in provinces:
            province = self.screen.id_to_province[province_id]
            if province["terrain"] == "plains":
                province["owner"] = self.rng.choice([o for o in self.owners if o != province["owner"]])

    def test_a_full_build_matches_the_reference_shading(self):
        self.assertTrue(np.array_equal(self.political(), self.expected_political()))
        self.assertEqual(self.screen.political_map.get_colorkey()[:3], c.COLOR_CHROMA_PINK)

    def test_a_few_captures_patch_last_turns_shading_including_across_the_map_edge(self):
        self.political()
        # Province 2 sits on the left edge, where the shading wraps to the right edge.
        self.change_owners((2, self.COLUMNS * self.ROWS - 5))
        with mock.patch.object(refresh_map._Layout, "full_levels",
                               side_effect=AssertionError("swept the whole map")):
            patched = self.political()
        self.assertTrue(np.array_equal(patched, self.expected_political()))

    def test_too_many_captures_fall_back_to_a_full_sweep_that_still_matches(self):
        self.political()
        self.change_owners(range(1, self.COLUMNS * self.ROWS + 1, 2))
        with mock.patch.object(refresh_map._Layout, "full_levels",
                               autospec=True, side_effect=refresh_map._Layout.full_levels) as sweep:
            rebuilt = self.political()
        sweep.assert_called_once()
        self.assertTrue(np.array_equal(rebuilt, self.expected_political()))

    def test_one_province_repaint_touches_only_that_province(self):
        from ui.rendering import map_utils

        before = self.political()
        province = self.screen.id_to_province[5]
        map_utils.update_single_province_surface(
            self.screen.political_map, self.screen.id_map, province["map_color"], [1, 2, 3])
        after = pygame.surfarray.array3d(self.screen.political_map)
        inside = np.all(pygame.surfarray.array3d(self.screen.id_map) == province["map_color"], axis=2)
        self.assertTrue(np.all(after[inside] == (1, 2, 3)))
        self.assertTrue(np.array_equal(after[~inside], before[~inside]))
        # A color no pixel shows paints nothing.
        map_utils.update_single_province_surface(
            self.screen.political_map, self.screen.id_map, (250, 251, 252), (9, 9, 9))
        self.assertTrue(np.array_equal(pygame.surfarray.array3d(self.screen.political_map), after))


if __name__ == "__main__":
    unittest.main()
