"""Check last-turn reports, private snapshots, read status, and map controls."""
import asyncio
import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pygame
import data.constants as c
from data import queries
from data.io import multiplayer_io
from data.io.realtime_multiplayer import apply_authoritative_snapshot, collect_map_commands
from map_logic.turn_processing import combat_processor, combat_rules, unit_events, turn_processor
from map_logic.turn_processing.time_handler import TimeHandler
from map_logic.rendering.font_manager import fonts
from tests import app_harness
from tests import test_tournament_moves as tournament_tests


def fixture():
    provinces = {pid: {"id": pid, "json_key": str(pid), "owner": owner, "terrain": "Plains",
        "units": [], "neighbors": [], "resources": {}, "buildings": [], "cores": [],
        "unit_queue": [], "building_queue": [], "orders": [], "center": (pid * 10, 10)}
        for pid, owner in ((1, "A"), (2, "B"))}
    nations = {owner: {"name": owner, "is_playable": True, "research": {},
        "at_war_with": [enemy], "allied_with": []} for owner, enemy in (("A", "B"), ("B", "A"))}
    return SimpleNamespace(map_data={str(pid): province for pid, province in provinces.items()},
        id_to_province=provinces, nation_data=nations, scenario_settings={"fog_of_war": False},
        player_country="A", tactical_mode=False, player_unit=None, is_editor=False,
        time_manager=SimpleNamespace(total_turns=1, day=1, month_index=0, year=1939),
        unit_event_log={"turn": 1, "events": []}, unit_event_read_turns={},
        loop_map=False, active_players=["A", "B"], current_player_index=0,
        script_variables=[], default_research=None, viewing_ai_moves=True, ai_is_thinking=False)


def unit(game, owner, pid=1, health=10, attack=6, name="Test division"):
    # Artificial stats isolate report arithmetic from content tuning.
    result = {"owner": owner, "type": "Infantry", "custom_name": name, "health": health,
              "max_health": health, "attack": attack, "defense": 0, "morale": c.DEFAULT_UNIT_MORALE,
              "order": {"type": "MOVE", "path": []}}
    game.id_to_province[pid]["units"].append(result)
    return result


def row(owner="A", unit_id="gone", event="DESTROYED"):
    return {"owner": owner, "unit_id": unit_id, "unit_name": "Lost division", "tile_id": 1,
            "event": event, "amount": 0, "details": "Ground combat"}


class UnitEventRulesTests(unittest.TestCase):
    def test_combat_preserves_execution_and_reports_capped_losses_and_sources(self):
        game = fixture()
        victim = unit(game, "A", health=2)
        unit(game, "B", attack=100, name="Enemy division")
        baseline = copy.deepcopy(game)
        combat_processor.process_combat(baseline)
        with unit_events.record_turn(game):
            unit_events.run_step(game, "Ground combat", combat_processor.process_combat)
        actual = copy.deepcopy(game.map_data)
        for province in actual.values():
            for item in province["units"]:
                item.pop("unit_id", None)
        self.assertEqual(actual, baseline.map_data)
        events = game.unit_event_log["events"]
        received = [entry for entry in events if entry["owner"] == "A" and entry["event"] == "DAMAGE_RECEIVED"]
        self.assertEqual(sum(entry["amount"] for entry in received), 2)
        self.assertTrue(all(entry["tile_id"] == 1 and "Enemy division" in entry["details"] for entry in received))
        self.assertTrue(any(entry["unit_id"] == victim["unit_id"] and entry["event"] == "DESTROYED" for entry in events))
        self.assertEqual(sum(entry["amount"] for entry in events if entry["owner"] == "B" and entry["event"] == "DAMAGE_DEALT"), 2)

    def test_pooled_damage_credit_uses_the_shared_source_contributions(self):
        game = fixture()
        victim = unit(game, "A")
        first = unit(game, "B", attack=4)
        second = unit(game, "B", attack=8)
        shots = combat_rules.damage_shots([first, second], [victim], nation_data=game.nation_data, with_sources=True)
        with unit_events.record_turn(game):
            for targets, attack, sources in shots:
                combat_processor.apply_group_damage(attack, targets, sources=sources, tile=1)
        entries = game.unit_event_log["events"]
        received = sum(entry["amount"] for entry in entries if entry["event"] == "DAMAGE_RECEIVED")
        credits = {entry["unit_id"]: entry["amount"] for entry in entries if entry["event"] == "DAMAGE_DEALT"}
        weights = dict((source["unit_id"], weight) for source, weight in shots[0][2])
        self.assertAlmostEqual(sum(credits.values()), received)
        for identity, weight in weights.items():
            self.assertAlmostEqual(credits[identity], received * weight / sum(weights.values()))

    def test_state_changes_and_casualties_survive_removal(self):
        game = fixture()
        moving = unit(game, "A")
        repaired = unit(game, "A", health=3)
        disbanded = unit(game, "A")
        with unit_events.record_turn(game):
            def move(_game):
                game.id_to_province[1]["units"].remove(moving)
                game.id_to_province[2]["units"].append(moving)
            unit_events.run_step(game, "Movement", move)
            unit_events.run_step(game, "Repairs", lambda _game: repaired.update(health=7))
            unit_events.run_step(game, "Disbanding", lambda _game: game.id_to_province[1]["units"].remove(disbanded))
            unit_events.run_step(game, "Deployments", lambda _game: unit(game, "A"))
            unit_events.run_step(game, "Upgrades", lambda _game: moving.update(type="Test upgrade"))
        entries = game.unit_event_log["events"]
        self.assertEqual({entry["event"] for entry in entries}, {"MOVED", "REPAIRED", "DISBANDED", "DEPLOYED", "UPGRADED"})
        self.assertEqual(next(entry["tile_id"] for entry in entries if entry["event"] == "MOVED"), 2)
        self.assertEqual(next(entry["amount"] for entry in entries if entry["event"] == "REPAIRED"), 4)
        self.assertTrue(all(entry["unit_id"] for entry in entries))

    def test_forecasts_and_combat_outside_resolution_do_not_write_reports(self):
        game = fixture()
        target = unit(game, "A")
        original = copy.deepcopy(game.unit_event_log)
        combat_processor.apply_group_damage(1, [target])
        self.assertEqual(game.unit_event_log, original)
        with unit_events.record_turn(game):
            combat_processor.apply_group_damage(2, [copy.deepcopy(target)])
        self.assertEqual(game.unit_event_log["events"], [])

    def test_new_turn_replaces_events_and_clears_old_read_preferences(self):
        game = fixture()
        game.unit_event_log["events"] = [row()]
        unit_events.mark_read(game)
        unit_events.set_event_filter(game, "DESTROYED")
        game.time_manager.total_turns += 1
        with unit_events.record_turn(game):
            pass
        self.assertEqual(game.unit_event_log, {"turn": 2, "events": []})
        self.assertEqual(game.unit_event_read_turns, {})
        self.assertIsNone(unit_events.event_filter_for(game))

    def test_failed_resolution_does_not_publish_partial_events(self):
        game = fixture()
        target = unit(game, "A")
        unit_events.set_event_filter(game, "DESTROYED")
        with self.assertRaises(RuntimeError), unit_events.record_turn(game):
            combat_processor.apply_group_damage(2, [target])
            raise RuntimeError("Interrupted resolution")
        self.assertEqual(game.unit_event_log["events"], [])
        self.assertEqual(unit_events.event_filter_for(game), "DESTROYED")
        combat_processor.apply_group_damage(2, [target])
        self.assertEqual(game.unit_event_log["events"], [])

    def test_fogged_source_name_and_location_are_private(self):
        game = fixture()
        game.scenario_settings["fog_of_war"] = True
        target = unit(game, "A")
        source = unit(game, "B", pid=2, name="Secret weapon")
        with unit_events.record_turn(game):
            combat_processor.apply_group_damage(1, [target], sources=[(source, 1)], tile=1)
        projected = queries.player_snapshot_projection(game, queries.build_save_dict(game), "A")
        self.assertEqual(len(projected["unit_event_log"]["events"]), 1)
        self.assertNotIn("Secret weapon", json.dumps(projected["unit_event_log"]))
        self.assertNotIn("tile 2", json.dumps(projected["unit_event_log"]))
        parts = projected["unit_event_log"]["events"][0]["detail_parts"]
        self.assertTrue(all("owner" not in part for part in parts))

    def test_detail_flags_use_recorded_owners_even_with_duplicate_names_and_removed_units(self):
        game = fixture()
        victim = unit(game, "A", name="Same name")
        first = unit(game, "B", name="Same name")
        second = unit(game, "A", name="Same name")
        with unit_events.record_turn(game):
            combat_processor.apply_group_damage(2, [victim], sources=[(first, 1), (second, 1)], tile=1)
        received = next(entry for entry in game.unit_event_log["events"] if entry["event"] == "DAMAGE_RECEIVED")
        self.assertEqual([part["owner"] for part in received["detail_parts"] if "owner" in part], ["B", "A"])
        self.assertEqual("".join(part["text"] for part in received["detail_parts"]), received["details"])
        game.id_to_province[1]["units"].clear()
        self.assertEqual(unit_events.entries_for(game)[0]["detail_parts"], received["detail_parts"])

    def test_grounded_air_loss_has_sources_and_destroyed_entry(self):
        game = fixture()
        plane = unit(game, "A")
        plane["type"] = "Monoplane Bomber"
        unit(game, "B", name="Ground attacker")
        with unit_events.record_turn(game):
            unit_events.run_step(game, "Ground combat", combat_processor.process_combat)
        entries = [entry for entry in game.unit_event_log["events"] if entry["owner"] == "A"]
        self.assertEqual({entry["event"] for entry in entries}, {"DAMAGE_RECEIVED", "DESTROYED"})
        self.assertTrue(any("Ground attacker" in entry["details"] for entry in entries))

    def test_tactical_sources_use_the_selected_divisions_visibility(self):
        game = fixture()
        game.scenario_settings["fog_of_war"] = True
        game.tactical_mode = True
        game.player_unit = unit(game, "A")
        source = unit(game, "B", pid=2, name="Hidden source")
        with patch.object(queries, "get_visible_provinces", return_value=({1}, set())) as visibility:
            with unit_events.record_turn(game):
                combat_processor.apply_group_damage(1, [game.player_unit], sources=[(source, 1)], tile=1)
        view = visibility.call_args_list[0].args[0]
        self.assertTrue(view.tactical_mode)
        self.assertIs(view.player_unit, game.player_unit)
        self.assertNotIn("Hidden source", unit_events.entries_for(game)[0]["details"])

    def test_air_strikes_record_incident_tile_and_expended_weapon(self):
        from tests.test_air_mechanics import world, tile, wing
        from map_logic.turn_processing import air_processor
        game = world()
        game.is_editor = False
        base = tile(game, 1, 8)
        target = tile(game, 2, 25, owner="B")
        missile = wing(base, "V2 Rocket", order={"type": "AIR_ATTACK", "target_id": target["id"]})
        wing(target, "Infantry", owner="B")
        with unit_events.record_turn(game):
            unit_events.run_step(game, "Air missions", air_processor.process_air_orders)
        entries = game.unit_event_log["events"]
        dealt = [entry for entry in entries if entry["unit_id"] == missile["unit_id"] and entry["event"] == "DAMAGE_DEALT"]
        self.assertTrue(dealt)
        self.assertTrue(all(entry["tile_id"] == target["id"] for entry in dealt))
        self.assertTrue(any(entry["unit_id"] == missile["unit_id"] and entry["event"] == "EXPENDED" for entry in entries))

    def test_authoritative_resolver_records_and_replaces_each_turn(self):
        game = fixture()
        game.time_manager = TimeHandler(start_year=1939)
        game.history = {}
        game.multi_turns_total = 0
        victim = unit(game, "A", health=2)
        unit(game, "B", attack=100)
        with ExitStack() as stack:
            stack.enter_context(patch.object(c, "RECORD_HISTORY", False))
            stack.enter_context(patch.object(turn_processor.politics, "tick"))
            stack.enter_context(patch.object(turn_processor.economy_processor, "process_economy"))
            stack.enter_context(patch.object(turn_processor.research_processor, "process_national_research"))
            asyncio.run(turn_processor.resolve_turn_logic(game))
            self.assertTrue(any(entry["unit_id"] == victim["unit_id"] for entry in game.unit_event_log["events"]))
            self.assertEqual(game.unit_event_log["turn"], game.time_manager.total_turns)
            asyncio.run(turn_processor.resolve_turn_logic(game))
        self.assertEqual(game.unit_event_log["events"], [])


class UnitEventPersistenceTests(unittest.TestCase):
    def test_mark_unread_preserves_other_players_and_survives_save_and_broadcast(self):
        game = fixture()
        game.unit_event_log["events"] = [row(), row("B")]
        game.unit_event_read_turns = {"A": 1, "B": 1}
        authoritative = queries.build_save_dict(game)
        before = copy.deepcopy(game.unit_event_log)
        unit_events.mark_unread(game)
        self.assertEqual(game._unit_event_unread, 1)
        self.assertEqual(game.unit_event_read_turns, {"B": 1})
        self.assertEqual(game.unit_event_log, before)
        loaded = fixture()
        unit_events.restore(loaded, json.loads(json.dumps(queries.build_save_dict(game))))
        unit_events.refresh_presentation(loaded)
        self.assertEqual(loaded._unit_event_unread, 1)
        self.assertEqual(loaded.unit_event_read_turns, {"B": 1})
        game.refresh_all_maps = lambda: unit_events.refresh_presentation(game)
        apply_authoritative_snapshot(game, authoritative)
        self.assertEqual(game._unit_event_unread, 1)
        self.assertEqual(game.unit_event_read_turns, {"B": 1})

    def test_json_round_trip_and_legacy_defaults(self):
        game = fixture()
        entry = row()
        entry["detail_parts"] = [{"text": entry["details"], "owner": "B"}]
        game.unit_event_log["events"] = [entry]
        unit_events.mark_read(game)
        snapshot = json.loads(json.dumps(queries.build_save_dict(game, include_provinces=False)))
        loaded = fixture()
        unit_events.restore(loaded, snapshot)
        self.assertEqual(loaded.unit_event_log, game.unit_event_log)
        unit_events.refresh_presentation(loaded)
        self.assertEqual(loaded._unit_event_unread, 0)
        unit_events.restore(loaded, {})
        self.assertEqual(loaded.unit_event_log["events"], [])
        self.assertEqual(loaded.unit_event_read_turns, {})

    def test_legacy_details_and_malformed_optional_parts_keep_the_original_text(self):
        game = fixture()
        entry = row()
        for parts in (None, [], [None], [{"text": entry["details"], "owner": []}],
                      [{"text": "Different text", "owner": "B"}]):
            with self.subTest(parts=parts):
                unit_events.restore(game, {"unit_event_log": {"turn": 1, "events": [entry | {"detail_parts": parts}]}})
                self.assertEqual(game.unit_event_log["events"], [entry])

    def test_stale_and_malformed_reports_are_discarded(self):
        game = fixture()
        bad_rows = [None, {}, row() | {"event": []}, row() | {"amount": float("nan")},
                    row() | {"amount": -1}, row() | {"tile_id": "1"}, row() | {"owner": []}]
        for value in (None, [], {"turn": 0, "events": [row()]}, {"turn": 1, "events": bad_rows}):
            with self.subTest(value=value):
                unit_events.restore(game, {"unit_event_log": value, "unit_event_read_turns": []})
                self.assertEqual(game.unit_event_log["events"], [])

    def test_player_projection_and_tournament_spectator_do_not_leak_other_reports(self):
        game = fixture()
        game.unit_event_log["events"] = [row(), row("B")]
        for entry in game.unit_event_log["events"]:
            entry["detail_parts"] = [{"text": entry["details"], "owner": entry["owner"]}]
        game.unit_event_read_turns = {"A": 1, "B": 1}
        saved = queries.build_save_dict(game)
        for viewer in ("A", "B", c.TOURNAMENT_SPECTATOR):
            projected = queries.player_snapshot_projection(game, saved, viewer)
            self.assertTrue(all(entry["owner"] == viewer for entry in projected["unit_event_log"]["events"]))
            self.assertLessEqual(set(projected["unit_event_read_turns"]), {viewer})
            self.assertTrue(all(entry["detail_parts"] == [{"text": entry["details"], "owner": viewer}]
                                for entry in projected["unit_event_log"]["events"]))
        spectator = multiplayer_io.build_tournament_spectator_save(saved)
        self.assertEqual(spectator["unit_event_log"]["events"], [])
        self.assertEqual(spectator["unit_event_read_turns"], {})
        self.assertEqual(len(saved["unit_event_log"]["events"]), 2)

    def test_realtime_broadcast_keeps_local_reads_until_the_next_turn(self):
        game = fixture()
        game.refresh_all_maps = lambda: unit_events.refresh_presentation(game)
        game.unit_event_log["events"] = [row()]
        game.unit_event_log["events"][0]["detail_parts"] = [{"text": "Ground combat", "owner": "B"}]
        snapshot = queries.build_save_dict(game)
        unit_events.mark_read(game)
        unit_events.set_event_filter(game, "DESTROYED")
        apply_authoritative_snapshot(game, snapshot)
        self.assertEqual(game._unit_event_unread, 0)
        self.assertEqual(game.unit_event_log["events"][0]["detail_parts"], snapshot["unit_event_log"]["events"][0]["detail_parts"])
        self.assertEqual(unit_events.event_filter_for(game), "DESTROYED")
        snapshot["date"]["total_turns"] += 1
        snapshot["unit_event_log"]["turn"] += 1
        apply_authoritative_snapshot(game, snapshot)
        self.assertEqual(game._unit_event_unread, 1)
        self.assertEqual(game.unit_event_read_turns, {})
        self.assertIsNone(unit_events.event_filter_for(game))

    def test_reports_and_reads_are_not_realtime_commands(self):
        game = fixture()
        game.unit_event_log["events"] = [row()]
        before = collect_map_commands(game, "A")
        unit_events.mark_read(game)
        unit_events.set_event_filter(game, "DESTROYED")
        self.assertEqual(collect_map_commands(game, "A"), before)
        self.assertNotIn("unit_event_filter", queries.build_save_dict(game))

    def test_tournament_move_cannot_replace_host_reports(self):
        helper = tournament_tests.TournamentMoveTests()
        host = tournament_tests.Host()
        host.unit_event_log = {"turn": host.time_manager.total_turns, "events": [row("Leader")]}
        host.unit_event_read_turns = {}
        before = copy.deepcopy(host.unit_event_log)
        forged = helper.player_data("Leader", host, unit_event_log={"turn": 4, "events": [row("Member")]},
                                    unit_event_read_turns={"Member": 4})
        with tempfile.TemporaryDirectory() as temporary:
            path = helper.write_move(temporary, "forged.gd5move", "Leader", forged)
            self.assertEqual(helper.import_moves(host, [path])["loaded"], 1)
        self.assertEqual(host.unit_event_log, before)
        self.assertEqual(host.unit_event_read_turns, {})


class UnitEventViewTests(unittest.TestCase):
    def test_hotseat_tactical_spectator_and_editor_views(self):
        game = fixture()
        game.unit_event_log["events"] = [row(unit_id="mine"), row(unit_id="other"), row("B")]
        unit_events.refresh_presentation(game)
        self.assertEqual(game._unit_event_unread, 2)
        unit_events.mark_read(game)
        game.player_country = "B"
        unit_events.refresh_presentation(game)
        self.assertEqual(game._unit_event_unread, 1)
        game.player_country = "A"
        game.tactical_mode = True
        game.player_unit = {"unit_id": "mine"}
        self.assertEqual([entry["unit_id"] for entry in unit_events.entries_for(game)], ["mine"])
        game.player_country = "Spectator"
        self.assertEqual(len(unit_events.entries_for(game)), 3)
        game.player_country = c.TOURNAMENT_SPECTATOR
        self.assertEqual(unit_events.entries_for(game), [])
        game.is_editor = True
        self.assertEqual(unit_events.entries_for(game), [])


class UnitEventScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()
        from screens.menu_screens.map import Map
        cls.game = Map(load_path=app_harness.SCENARIO_PATH, is_scenario=True)
        cls.game.selection_mode = False
        cls.game.player_country = sorted(queries.get_living_nations(cls.game.map_data))[0]

    def setUp(self):
        self.game.unit_event_log = {"turn": self.game.time_manager.total_turns,
                                    "events": [row(self.game.player_country)]}
        self.game.unit_event_read_turns = {}
        unit_events.set_event_filter(self.game, None)
        unit_events.refresh_presentation(self.game)

    def test_button_icon_badge_placement_and_navigation(self):
        from screens.menu_screens.map import update_button_states
        from ui.bars import resource_hud
        from ui import modal_stack
        from ui_elements import UI_ICONS
        game = self.game
        update_button_states(game)
        button = game.btn_unit_events
        self.assertTrue(button.visible)
        self.assertEqual(button.notification_count, 1)
        self.assertIs(button.image, UI_ICONS["mail"])
        self.assertEqual(button.color, c.UI_COLORS["yellow"][0])
        panel_right = (resource_hud.HUD_START_X - resource_hud.HUD_BOX_PAD_X
                       + len(c.ECON_RESOURCE_KEYS) * resource_hud.HUD_SPACING - resource_hud.HUD_BOX_TRIM)
        self.assertGreater(button.rect.left, panel_right)
        self.assertEqual(button.rect.width, button.rect.height)
        self.assertTrue(game.bot_bar_rect.contains(button.rect))
        self.assertFalse(button.rect.colliderect(game.btn_next_turn.rect))
        with patch.object(modal_stack, "push") as push:
            button.callback()
        screen = push.call_args.args[0].screen
        self.assertEqual(len(screen.rows), 1)
        self.assertEqual(button.notification_count, 0)
        self.assertTrue(any(element.callback == screen.exit_screen for element in screen.elements))

    def test_table_fits_and_draws_from_cached_rows_with_orange_background(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen, CELL_PADDING
        game = self.game
        game.unit_event_log["events"][0]["details"] = "Long incident details " * 80
        screen = UnitEventsScreen(game)
        self.assertLessEqual(screen.table_x + screen.total_w, c.SCREEN_WIDTH)
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        with patch.object(screen, "draw_checkerboard_background", wraps=screen.draw_checkerboard_background) as background:
            with patch.object(unit_events, "entries_for", side_effect=AssertionError("Frame queried reports")):
                screen.draw(surface)
                screen.draw(surface)
            self.assertEqual(background.call_args.args[1], screen.bg_color)
        for column in screen.columns:
            text = column.fmt(screen.rows[0][column.key])
            self.assertLessEqual(fonts.get("small").size(text)[0], column.width - CELL_PADDING)
        with patch("ui.confirm_dialog.show_info") as details:
            screen.show_event(screen.rows[0])
        self.assertIn(game.unit_event_log["events"][0]["details"], details.call_args.args[1])

    def test_owner_flags_follow_destroyed_units_after_sorting_and_filtering(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen
        from ui import flag_icons
        game = self.game
        events = [row(game.player_country) | {"unit_name": "Z destroyed unit"},
                  row("Historic country", event="MOVED") | {"unit_name": "A moving unit"}]
        game.unit_event_log["events"] = events
        flags = {owner: pygame.Surface(flag_icons.ROW_FLAG_SIZE) for owner in {entry["owner"] for entry in events}}
        with patch.object(game, "player_country", "Spectator"), \
                patch.object(flag_icons, "flag_surface", side_effect=lambda owner, _data: flags[owner]) as prepare:
            screen = UnitEventsScreen(game)
        self.assertEqual({call.args[0] for call in prepare.call_args_list}, set(flags))

        class RecordingSurface(pygame.Surface):
            def blit(self, source, dest, *args, **kwargs):
                rect = super().blit(source, dest, *args, **kwargs)
                self.blits.append((source, rect))
                return rect

        surface = RecordingSurface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))

        def check_draw():
            surface.blits = []
            with patch.object(flag_icons, "flag_surface", side_effect=AssertionError("Frame prepared flags")), \
                    patch.object(queries, "decode_b64_to_surf", side_effect=AssertionError("Frame decoded flags")):
                screen.draw(surface)
            drawn = [(index, source, rect) for index, (source, rect) in enumerate(surface.blits)
                     if any(source is flag for flag in flags.values())]
            self.assertEqual(len(drawn), len(screen.rows))
            for entry, (index, flag, flag_rect) in zip(screen.rows, drawn):
                self.assertIs(flag, flags[entry["owner"]])
                name_rect = surface.blits[index + 1][1]
                self.assertLess(flag_rect.right, name_rect.left)
                self.assertEqual(flag_rect.centery, name_rect.centery)
                unit_cell = pygame.Rect(screen.table_x, flag_rect.centery - screen.ROW_HEIGHT // 2,
                                        screen.columns[0].width, screen.ROW_HEIGHT)
                self.assertTrue(unit_cell.contains(flag_rect))
                self.assertTrue(unit_cell.contains(name_rect))

        check_draw()
        screen.sort_by(screen.columns[0])
        self.assertEqual(screen.rows[0]["owner"], "Historic country")
        check_draw()
        screen.set_event_filter("DESTROYED")
        self.assertEqual(len(screen.rows), 1)
        check_draw()

    def test_long_unit_names_fit_beside_cached_country_flags_at_different_widths(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen, CELL_PADDING
        from ui import flag_icons
        self.game.unit_event_log["events"][0]["unit_name"] = "Long unit name " * 40
        for width in (1024, c.SCREEN_WIDTH):
            with self.subTest(width=width), patch.object(c, "SCREEN_WIDTH", width):
                screen = UnitEventsScreen(self.game)
                column = screen.columns[0]
                entry = screen.rows[0]
                self.assertIs(column.icon(entry), flag_icons.flag_surface(entry["owner"], self.game.nation_data))
                content_width = (fonts.get("small").size(column.fmt(entry["unit_name"]))[0]
                                 + column.icon(entry).get_width() + screen.CELL_ICON_GAP)
                self.assertLessEqual(content_width, column.width - CELL_PADDING)
                self.assertLessEqual(column.icon(entry).get_height(), screen.ROW_HEIGHT)
                screen.draw(pygame.Surface((width, c.SCREEN_HEIGHT)))

    def test_details_column_and_popup_show_each_visible_units_flag(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen, CELL_PADDING
        from ui import flag_icons, modal_stack, text_utils
        game = self.game
        parts = [{"text": "Ground combat: "}, {"text": "Same name (tile 1)", "owner": "B"},
                 {"text": "; "}, {"text": "Same name (tile 2)", "owner": "C"},
                 {"text": "; Unknown unit"}]
        entry = game.unit_event_log["events"][0]
        entry.update(details="".join(part["text"] for part in parts), detail_parts=parts)
        colors = {game.player_country: (20, 120, 20), "B": (120, 20, 20), "C": (20, 20, 120)}
        flags = {}
        for owner, color in colors.items():
            flags[owner] = pygame.Surface(flag_icons.ROW_FLAG_SIZE)
            flags[owner].fill(color)
        with patch.object(flag_icons, "flag_surface", side_effect=lambda owner, _data: flags[owner]):
            screen = UnitEventsScreen(game)
        detail_column = screen.columns[-1]
        cell = detail_column.render(screen.rows[0])
        self.assertLessEqual(cell.get_width(), detail_column.width - CELL_PADDING)
        flag_area = flag_icons.ROW_FLAG_SIZE[0] * flag_icons.ROW_FLAG_SIZE[1]
        for owner in ("B", "C"):
            self.assertEqual(pygame.mask.from_threshold(cell, colors[owner], (1, 1, 1, 255)).count(), flag_area)
        with patch.object(modal_stack, "push") as push:
            screen.show_event(screen.rows[0])
        popup = push.call_args.args[0]
        for owner in colors:
            pixels = sum(pygame.mask.from_threshold(line, colors[owner], (1, 1, 1, 255)).count()
                         for line in popup.inline_lines)
            self.assertEqual(pixels, flag_area)
        self.assertTrue(all(line.get_width() <= popup.body_rect.width for line in popup.inline_lines))
        with patch.object(flag_icons, "flag_surface", side_effect=AssertionError("Frame prepared flags")), \
                patch.object(text_utils, "render_inline_text", side_effect=AssertionError("Frame prepared details")):
            surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
            screen.draw(surface)
            popup.draw(surface)

    def test_long_details_popup_keeps_all_flags_and_scrolls_inside_the_viewport(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen
        from ui import modal_stack, flag_icons
        game = self.game
        parts = [{"text": "Ground combat: "}]
        for index in range(30):
            parts.append({"text": "LongUnitName" * 10 + f" (tile {index})", "owner": "B"})
            parts.append({"text": "; "})
        entry = game.unit_event_log["events"][0]
        entry.update(details="".join(part["text"] for part in parts), detail_parts=parts)
        flag = pygame.Surface(flag_icons.ROW_FLAG_SIZE)
        flag.fill((123, 45, 67))
        with patch.object(flag_icons, "flag_surface", return_value=flag):
            screen = UnitEventsScreen(game)
        for size in ((640, 480), (c.SCREEN_WIDTH, c.SCREEN_HEIGHT)):
            with self.subTest(size=size), patch("pygame.display.get_surface", return_value=pygame.Surface(size)), \
                    patch.object(modal_stack, "push") as push:
                screen.show_event(screen.rows[0])
                popup = push.call_args.args[0]
                self.assertTrue(pygame.Rect((0, 0), size).contains(popup.box_rect))
                self.assertTrue(popup.box_rect.contains(popup.ok_rect))
                self.assertFalse(popup.body_rect.colliderect(popup.ok_rect))
                pixels = sum(pygame.mask.from_threshold(line, (123, 45, 67), (1, 1, 1, 255)).count()
                             for line in popup.inline_lines)
                self.assertEqual(pixels, (30 + 1) * flag.get_width() * flag.get_height())
                popup.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, y=-1000)])
                self.assertGreater(popup.body_scroll, 0)
                self.assertEqual(popup.body_scroll, popup.body_scroll_limit)
                popup.draw(pygame.Surface(size))
                popup.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, y=1000)])
                self.assertEqual(popup.body_scroll, 0)
                popup.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)])
                self.assertTrue(popup._resolved)

    def test_mark_all_unread_restores_badge_after_closing_until_reopened(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen
        game = self.game
        before = copy.deepcopy(game.unit_event_log)
        screen = UnitEventsScreen(game)
        self.assertEqual(game.btn_unit_events.notification_count, 0)
        button = screen.btn_mark_all_unread
        self.assertIn(button, screen.elements)
        self.assertFalse(button.disabled)
        bounds = pygame.Rect(0, 0, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        self.assertTrue(bounds.contains(button.rect))
        self.assertTrue(all(not button.rect.colliderect(element.rect)
                            for element in screen.elements if element is not button))
        button.callback()
        screen.refresh_ui()
        screen.exit_screen()
        self.assertEqual(game.btn_unit_events.notification_count, len(screen.rows))
        self.assertEqual(game.unit_event_log, before)
        UnitEventsScreen(game)
        self.assertEqual(game.btn_unit_events.notification_count, 0)

    def test_empty_log_disables_mark_all_unread(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen
        from ui import modal_stack
        self.game.unit_event_log["events"] = []
        screen = UnitEventsScreen(self.game)
        self.assertTrue(screen.btn_mark_all_unread.disabled)
        self.assertEqual(self.game.btn_unit_events.notification_count, 0)
        with patch.object(modal_stack, "push") as push:
            screen.btn_filter_events.callback()
        picker = push.call_args.args[0].screen
        self.assertTrue(all(not picker._item_enabled(item) for item in picker.items))

    def test_filter_picker_shows_only_the_selected_event_and_can_clear_it(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen
        from ui import modal_stack
        game = self.game
        game.unit_event_log["events"] += [row(game.player_country, event="MOVED"), row("Other country")]
        before = copy.deepcopy(game.unit_event_log)
        screen = UnitEventsScreen(game)
        self.assertEqual(len(screen.rows), 2)
        self.assertEqual(screen.btn_filter_events.color, c.UI_COLORS["blue"][0])
        with patch.object(modal_stack, "push") as push:
            screen.btn_filter_events.callback()
        picker = push.call_args.args[0].screen
        self.assertEqual({event for _label, event in picker.items}, {None, *unit_events.EVENT_LABELS})
        picker.select(next(item for item in picker.items if item[1] == "MOVED"))
        self.assertEqual([entry["event"] for entry in screen.rows], ["MOVED"])
        self.assertEqual(screen.btn_filter_events.color, c.UI_COLORS["orange"][0])
        reopened = UnitEventsScreen(game)
        self.assertEqual([entry["event"] for entry in reopened.rows], ["MOVED"])
        self.assertEqual(reopened.btn_filter_events.color, c.UI_COLORS["orange"][0])
        with patch.object(modal_stack, "push") as push:
            reopened.btn_filter_events.callback()
        picker = push.call_args.args[0].screen
        picker.select(next(item for item in picker.items if item[1] is None))
        self.assertEqual(len(reopened.rows), 2)
        self.assertEqual(reopened.btn_filter_events.color, c.UI_COLORS["blue"][0])
        self.assertEqual(game.unit_event_log, before)

    def test_filter_picker_disables_empty_choices_during_search_and_keyboard_selection(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen
        from ui import modal_stack
        game = self.game
        game.unit_event_log["events"] += [row(game.player_country, event="MOVED"),
                                          row("Other country", event="REPAIRED")]
        screen = UnitEventsScreen(game)
        screen.set_event_filter("MOVED")
        with patch.object(modal_stack, "push") as push:
            screen.btn_filter_events.callback()
        picker = push.call_args.args[0].screen
        for _label, event in picker.items:
            self.assertEqual(picker._item_enabled((_label, event)), event in (None, "MOVED", "DESTROYED"))
        # Availability uses the viewer's complete report, including events outside the active filter.
        for element in picker.elements[1:]:
            if not element.disabled:
                self.assertEqual(element.color, c.UI_COLORS["blue"][0])
        picker.search_text = "repair"
        picker.refresh_ui()
        self.assertEqual(len(picker.visible_items), 1)
        self.assertTrue(picker.elements[-1].disabled)
        picker.elements[-1].callback()
        picker._handle_search_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        self.assertFalse(picker.done)
        self.assertEqual(screen.event_filter, "MOVED")
        picker.search_text = "d"
        picker.refresh_ui()
        self.assertFalse(picker._item_enabled(picker.visible_items[0]))
        self.assertTrue(any(not button.disabled for button in picker.elements[1:]))
        for button in picker.elements[1:]:
            if not button.disabled:
                self.assertEqual(button.color, c.UI_COLORS["blue"][0])
        picker._handle_search_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        self.assertTrue(picker.done)
        self.assertEqual(screen.event_filter, "DESTROYED")

    def test_empty_filter_clears_click_targets_and_keeps_mark_all_unread_available(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen
        game = self.game
        screen = UnitEventsScreen(game)
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        screen.draw(surface)
        old_rect = screen.row_hitboxes[0][0]
        screen.scroll_y = -screen.ROW_HEIGHT
        screen.set_event_filter("MOVED")
        self.assertEqual(screen.rows, [])
        self.assertEqual(screen.row_hitboxes, [])
        self.assertEqual(screen.scroll_y, 0)
        self.assertEqual(screen.btn_filter_events.color, c.UI_COLORS["orange"][0])
        with patch.object(unit_events, "entries_for", side_effect=AssertionError("Frame queried reports")):
            screen.draw(surface)
        with patch("ui.confirm_dialog.show_info") as details:
            screen.additional_events(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=old_rect.center))
        details.assert_not_called()
        self.assertFalse(screen.btn_mark_all_unread.disabled)
        screen.btn_mark_all_unread.callback()
        self.assertEqual(game.btn_unit_events.notification_count, len(screen.all_rows))
        with unit_events.record_turn(game):
            pass
        reopened = UnitEventsScreen(game)
        self.assertIsNone(reopened.event_filter)
        self.assertEqual(reopened.btn_filter_events.color, c.UI_COLORS["blue"][0])
        self.assertTrue(reopened.btn_mark_all_unread.disabled)

    def test_filter_respects_tactical_and_spectator_permissions(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen
        game = self.game
        game.unit_event_log["events"] += [row(game.player_country, "other"), row("Other country")]
        for viewer, tactical, editor, expected in (
                (game.player_country, True, False, 1), ("Spectator", False, False, 3),
                (c.TOURNAMENT_SPECTATOR, False, False, 0), (game.player_country, False, True, 0)):
            with self.subTest(viewer=viewer, tactical=tactical, editor=editor), \
                    patch.object(game, "player_country", viewer), patch.object(game, "tactical_mode", tactical), \
                    patch.object(game, "is_editor", editor), patch.object(game, "player_unit", {"unit_id": "gone"}):
                screen = UnitEventsScreen(game)
                screen.set_event_filter("DESTROYED")
                self.assertEqual(len(screen.rows), expected)

    def test_filter_button_is_left_of_unread_without_overlapping_controls(self):
        from screens.map_related_screens.unit_events_screen import UnitEventsScreen
        for width in (1024, c.SCREEN_WIDTH):
            with self.subTest(width=width), patch.object(c, "SCREEN_WIDTH", width):
                screen = UnitEventsScreen(self.game)
                button = screen.btn_filter_events
                unread = screen.btn_mark_all_unread
                self.assertLess(button.rect.right, unread.rect.left)
                self.assertEqual(button.rect.centery, unread.rect.centery)
                self.assertTrue(pygame.Rect(0, 0, width, c.SCREEN_HEIGHT).contains(button.rect))
                self.assertTrue(all(not button.rect.colliderect(element.rect)
                                    for element in screen.elements if element is not button))
                title = pygame.Rect((0, 25), fonts.get("heading1").size(screen.title))
                title.centerx = width // 2
                self.assertFalse(button.rect.colliderect(title))

    def test_normal_save_loader_preserves_reports_and_legacy_has_empty_log(self):
        from data.map import save_map
        from screens.menu_screens.map import Map
        game = self.game
        entry = game.unit_event_log["events"][0]
        entry["detail_parts"] = [{"text": entry["details"], "owner": "B"}]
        unit_events.mark_read(game)
        unit_events.set_event_filter(game, "DESTROYED")
        with tempfile.TemporaryDirectory() as temporary, patch.object(c, "SAVES_DIR", temporary):
            asyncio.run(save_map.save_map_data(game, "reports"))
            path = Path(temporary, "reports")
            loaded = Map(load_path=str(path), skip_initial_income=True)
            self.assertEqual(loaded.unit_event_log, game.unit_event_log)
            self.assertEqual(loaded._unit_event_unread, 0)
            self.assertIsNone(unit_events.event_filter_for(loaded))
            metadata_path = path / "meta.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            del metadata["unit_event_log"]
            del metadata["unit_event_read_turns"]
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            legacy = Map(load_path=str(path), skip_initial_income=True)
            self.assertEqual(legacy.unit_event_log["events"], [])


if __name__ == "__main__":
    unittest.main()
