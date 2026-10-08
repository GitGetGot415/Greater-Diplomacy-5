"""Check editor fill boundaries, input, history, and tool permissions."""

import json
import unittest
from types import SimpleNamespace
from unittest import mock

import pygame

from data import queries
import data.constants as c
from map_logic.turn_processing import edit_province_ownership as ownership
from screens.menu_screens import map as map_module
from tests import app_harness
from ui import diplomatic_popups, event_handler


def sample_editor():
    provinces = [
        {"id": 1, "owner": "A", "cores": ["A", "B"], "neighbors": [2, 4, 99]},
        {"id": 2, "owner": "A", "cores": ["B", "A"], "neighbors": [1, 3, 5]},
        {"id": 3, "owner": "B", "cores": ["A"], "neighbors": [2, 6]},
        {"id": 4, "owner": c.WATER_NATIONS[0], "cores": ["A", "B"], "neighbors": [1, 7]},
        {"id": 5, "owner": "A", "cores": [], "neighbors": [2]},
        {"id": 6, "owner": "A", "cores": ["A", "B"], "neighbors": [3]},
        {"id": 7, "owner": "A", "cores": ["A", "B"], "neighbors": [4]},
    ]
    for province in provinces:
        province.update(map_color=[province["id"], 0, 0], buildings=[], units=[], resources={})
    return SimpleNamespace(
        is_editor=True, editor_mode="NATION", editor_selection_tool="PAINT", brush_nation="C",
        id_to_province={p["id"]: p for p in provinces},
        map_data={str(tuple(p["map_color"])): p for p in provinces},
        nation_data={"A": {}, "B": {}, "C": {}},
        viewing_ai_moves=False, ai_is_thinking=False, centers_need_update=False,
        political_map=None, id_map=None, cores_map=None, map_mode="POLITICAL",
        refresh_all_maps=mock.Mock(), show_feedback=mock.Mock(),
    )


class EditorPaintTests(unittest.TestCase):
    def setUp(self):
        self.editor = sample_editor()
        self.start = self.editor.id_to_province[1]
        self.visual = mock.patch.object(ownership.map_utils, "update_single_province_surface")
        self.visual.start()
        self.addCleanup(self.visual.stop)

    def region_ids(self, mode):
        return {p["id"] for p in queries.get_editor_paint_region(
            self.start, self.editor.id_to_province, mode)}

    def test_territory_region_stops_at_water_and_other_owners(self):
        self.assertEqual(self.region_ids("NATION"), {1, 2, 5})

    def test_core_region_matches_the_complete_set_without_list_order(self):
        self.editor.id_to_province[2]["owner"] = "B"
        self.assertEqual(self.region_ids("CORE"), {1, 2})

    def test_empty_core_region_crosses_ownership_but_stops_at_existing_cores(self):
        self.start["cores"] = []
        self.editor.id_to_province[2]["cores"] = []
        self.editor.id_to_province[2]["owner"] = "B"
        self.assertEqual(self.region_ids("CORE"), {1, 2, 5})

    def test_water_and_unsupported_tools_have_no_region(self):
        self.assertEqual(self.region_ids("RESOURCE"), set())
        self.assertEqual(queries.get_editor_paint_region(
            self.editor.id_to_province[4], self.editor.id_to_province, "CORE"), [])

    def test_fill_uses_an_iterative_search_for_large_regions(self):
        count = 3000
        provinces = {i: {"id": i, "owner": "A", "neighbors": [i + 1]} for i in range(count)}
        self.assertEqual(len(queries.get_editor_paint_region(provinces[0], provinces, "NATION")), count)

    def test_territory_fill_changes_only_the_connected_region(self):
        original = {i: dict(p) for i, p in self.editor.id_to_province.items()}
        layers = ownership.apply_editor_territory_brush(self.editor, self.start)
        for i, province in self.editor.id_to_province.items():
            self.assertEqual(province["owner"], "C" if i in {1, 2, 5} else original[i]["owner"])
            self.assertEqual(province["cores"], original[i]["cores"])
        self.assertIn("political", layers)
        self.assertTrue(self.editor.centers_need_update)

    def test_brush_changes_only_one_tile(self):
        self.editor.editor_selection_tool = "BRUSH"
        ownership.apply_editor_territory_brush(self.editor, self.start)
        self.assertEqual(self.start["owner"], "C")
        self.assertEqual(self.editor.id_to_province[2]["owner"], "A")

    def test_core_fill_add_remove_and_clear_keep_other_core_sets(self):
        for nation, remove, expected in (("C", False, {"A", "B", "C"}),
                                         ("A", True, {"B"}),
                                         (c.UNOWNED_LAND_OWNERS[0], False, set())):
            with self.subTest(nation=nation, remove=remove):
                editor = sample_editor()
                editor.editor_mode = "CORE"
                editor.brush_nation = nation
                layers = ownership.apply_editor_territory_brush(editor, editor.id_to_province[1], remove)
                self.assertEqual(layers, {"cores"})
                for i in (1, 2):
                    self.assertEqual(set(editor.id_to_province[i]["cores"]), expected)
                self.assertEqual(editor.id_to_province[3]["cores"], ["A"])
                self.assertEqual(editor.id_to_province[6]["cores"], ["A", "B"])

    def test_unchanged_fill_returns_no_layers(self):
        self.editor.brush_nation = "A"
        self.assertEqual(ownership.apply_editor_territory_brush(self.editor, self.start), set())

    def test_only_editor_territory_and_cores_can_use_the_helper(self):
        for mode in ("RESOURCE", "CLAIM", "UNIT", "BUILDING"):
            self.editor.editor_mode = mode
            self.assertEqual(ownership.apply_editor_territory_brush(self.editor, self.start), set())
        self.editor.editor_mode = "NATION"
        self.editor.is_editor = False
        self.assertEqual(ownership.apply_editor_territory_brush(self.editor, self.start), set())
        self.assertEqual(self.start["owner"], "A")

    def test_fill_is_one_undo_and_redo_action(self):
        queries.save_editor_state(self.editor)
        ownership.apply_editor_territory_brush(self.editor, self.start)
        queries.restore_editor_state(self.editor)
        self.assertTrue(all(self.editor.id_to_province[i]["owner"] == "A" for i in (1, 2, 5)))
        queries.redo_editor_state(self.editor)
        self.assertTrue(all(self.editor.id_to_province[i]["owner"] == "C" for i in (1, 2, 5)))

    def test_filled_owners_and_cores_survive_the_save_overlay(self):
        ownership.apply_editor_territory_brush(self.editor, self.start)
        self.editor.editor_mode = "CORE"
        ownership.apply_editor_territory_brush(self.editor, self.start)
        saved = json.loads(json.dumps({key: queries.build_saved_province_data(p)
                                      for key, p in self.editor.map_data.items()}))
        loaded = sample_editor()
        queries.overlay_saved_province_data(loaded.map_data, saved)
        for key, province in self.editor.map_data.items():
            self.assertEqual(loaded.map_data[key]["owner"], province["owner"])
            self.assertEqual(loaded.map_data[key]["cores"], province["cores"])


class EditorPaintInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()
        cls.game = app_harness.boot_map()

    def setUp(self):
        editor = sample_editor()
        self.provinces = editor.id_to_province
        values = vars(editor).copy()
        values.update(selected_province=None, selection_mode=False, secondary_mode="BLANK",
                      last_hovered_id=None, extreme_hidden_provinces=set(),
                      editor_history=[], editor_redo_history=[],
                      navigation_intro_popup=None, camera=mock.Mock(),
                      queue_editor_visual_refresh=mock.Mock())
        self.context = mock.patch.dict(self.game.__dict__, values)
        self.context.start()
        self.addCleanup(self.context.stop)
        self.visual = mock.patch.object(ownership.map_utils, "update_single_province_surface")
        self.visual.start()
        self.addCleanup(self.visual.stop)

    def send(self, province_id, event_type, button=1, held=(False, False, False), on_ui=False):
        position = (map_module.EDITOR_SELECTION_TOOL_X, c.BOTTOM_BAR_UI_CENTER_Y) if on_ui else (600, 300)
        event = pygame.event.Event(event_type, pos=position, button=button)
        with mock.patch.object(event_handler.queries, "get_clicked_province", return_value=self.provinces[province_id]), \
                mock.patch.object(event_handler.map_utils, "create_glow_surface", return_value=(None, None)), \
                mock.patch.object(diplomatic_popups, "handle_events", return_value=False), \
                mock.patch("pygame.mouse.get_pressed", return_value=held):
            event_handler.handle_map_events(self.game, event)

    def test_fill_runs_on_click_without_requiring_polled_mouse_state(self):
        self.send(1, pygame.MOUSEBUTTONDOWN)
        self.assertEqual(self.provinces[2]["owner"], "C")
        self.assertEqual(len(self.game.editor_history), 1)
        self.game.queue_editor_visual_refresh.assert_called_once()
        self.send(3, pygame.MOUSEMOTION, held=(True, False, False))
        self.assertEqual(self.provinces[3]["owner"], "B")
        self.game.queue_editor_visual_refresh.assert_called_once()

    def test_brush_still_paints_during_drag(self):
        self.game.editor_selection_tool = "BRUSH"
        self.send(1, pygame.MOUSEMOTION, held=(True, False, False))
        self.assertEqual(self.provinces[1]["owner"], "C")
        self.assertEqual(self.provinces[2]["owner"], "A")

    def test_right_click_removes_a_core_region(self):
        self.game.editor_mode = "CORE"
        self.game.brush_nation = "A"
        self.send(1, pygame.MOUSEBUTTONDOWN, button=3)
        self.assertEqual(self.provinces[1]["cores"], ["B"])
        self.assertEqual(self.provinces[2]["cores"], ["B"])
        self.assertEqual(self.provinces[3]["cores"], ["A"])

    def test_right_click_still_picks_a_territory_owner(self):
        self.send(1, pygame.MOUSEBUTTONDOWN, button=3)
        self.assertEqual(self.game.brush_nation, "A")
        self.assertEqual(self.provinces[2]["owner"], "A")

    def test_fill_does_not_click_through_the_toolbar(self):
        self.send(1, pygame.MOUSEBUTTONDOWN, on_ui=True)
        self.assertEqual(self.provinces[1]["owner"], "A")
        self.game.queue_editor_visual_refresh.assert_not_called()

    def test_other_tools_ignore_paint_selection(self):
        for mode in ("RESOURCE", "CLAIM", "BUILDING", "UNIT"):
            with self.subTest(mode=mode):
                self.game.editor_mode = mode
                self.game.brush_resource_type = "Test Resource"
                self.game.brush_resource_amount = 7
                self.game.brush_building = "Test Building"
                self.game.brush_unit = "None"
                self.provinces[1]["units"] = [{"type": "Test Unit"}]
                self.provinces[2]["units"] = [{"type": "Test Unit"}]
                self.send(1, pygame.MOUSEBUTTONDOWN, held=(True, False, False))
                if mode == "RESOURCE":
                    self.assertEqual(self.provinces[1]["resources"], {"Test Resource": 7})
                    self.assertEqual(self.provinces[2]["resources"], {})
                elif mode == "CLAIM":
                    self.assertEqual(self.game.nation_data["C"]["claims"], [1])
                elif mode == "BUILDING":
                    self.assertEqual(self.provinces[1]["buildings"], ["Test Building"])
                    self.assertEqual(self.provinces[2]["buildings"], [])
                else:
                    self.assertEqual(self.provinces[1]["units"], [])
                    self.assertEqual(len(self.provinces[2]["units"]), 1)

    def test_tool_callbacks_and_permissions(self):
        self.game.btn_ed_brush.callback()
        self.assertEqual(self.game.editor_selection_tool, "BRUSH")
        self.game.btn_ed_paint.callback()
        self.assertEqual(self.game.editor_selection_tool, "PAINT")
        for mode in ("RESOURCE", "CLAIM", "BUILDING", "UNIT"):
            self.game.editor_mode = mode
            map_module.update_button_states(self.game)
            self.assertTrue(self.game.btn_ed_paint.disabled)
            self.game.btn_ed_brush.callback()
            self.assertEqual(self.game.editor_selection_tool, "PAINT")
        self.game.is_editor = False
        self.game.editor_mode = "NATION"
        self.game.btn_ed_brush.callback()
        self.assertEqual(self.game.editor_selection_tool, "PAINT")


if __name__ == "__main__":
    unittest.main()
