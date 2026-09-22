"""Guards the frozen application surface: state keys, screen constructors, and
the GameState virtual protocol.

Every screen class name, constructor arity and state-machine string key is
effectively public API -- main.py hardcodes them, and a mod that replaces a
screen module has to keep providing the same class under the same name. Nothing
checked any of that before this file existed.
"""

import unittest
from unittest import mock

import pygame

from tests import app_harness

# The state-machine keys main.py's flip_state() dispatches on. Hardcoded here
# rather than read back from Controller so that deleting one fails the test.
EXPECTED_STATES = {
    "MENU", "NEW_GAME", "RANDOM_SETUP", "LOAD_GAME", "SETTINGS", "UNIT_ART", "CREDITS",
    "MUSIC_PLAYER", "VIEW_ASSETS", "MODS", "SELECT_BASE_MAP", "MAP",
    "PRODUCTION", "ORDERS", "RESEARCH", "ECONOMY", "EDIT_COUNTRY", "MESSAGES",
    "FACTION", "FACTION_TERRITORIES", "SCENARIO_SETTINGS", "MULTIPLAYER_MENU",
    "MULTIPLAYER_HUB", "MULTIPLAYER_HOST", "MULTIPLAYER_JOIN", "MULTIPLAYER_NEW",
    "REAL_TIME_MULTIPLAYER", "REALTIME_HOST_SETUP", "REALTIME_SCENARIO_SELECT", "REALTIME_LOBBY",
    "REALTIME_JOIN", "REALTIME_LAN_BROWSER", "REALTIME_REMOTE_LOBBY", "REALTIME_RELAY_SETUP",
    "REALTIME_RELAY_PROVISION", "TRANSLATE",
    "TRANSLATION_MENU", "TRANSLATE_GD4", "TRANSLATE_GDHEX", "KEYBINDS", "MOUSE_SETTINGS",
}

# GameState's virtual methods. Screens override these; mods rely on them.
# draw_content is deliberately absent: it belongs to MapOverlayScreen, not to
# every screen.
PROTOCOL = (
    "handle_events", "additional_events", "update", "draw", "draw_background",
    "draw_title", "draw_elements", "draw_feedback", "additional_draw",
    "go_to", "exit_screen", "handle_back_key", "get_title", "refresh_ui",
)


class ControllerConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()

    def test_state_keys_are_exactly_as_expected(self):
        self.assertEqual(set(self.controller.states), EXPECTED_STATES)

    def test_every_state_but_map_is_constructed(self):
        missing = [name for name, screen in self.controller.states.items()
                   if screen is None and name != "MAP"]
        self.assertEqual(missing, [], "states failed to construct")

    def test_map_is_built_lazily(self):
        """MAP is intentionally None until a scenario is chosen; if that ever
        changes, flip_state()'s Map-construction branch needs revisiting.

        Read off what boot() recorded rather than off the live controller: it is
        cached per interpreter, and any earlier test file that called boot_map()
        will have filled MAP in by the time this runs.
        """
        self.assertIn("MAP", app_harness.STATES_UNBUILT_AT_BOOT)

    def test_screens_expose_the_gamestate_protocol(self):
        missing = []
        for name, screen in app_harness.screens(self.controller):
            for method in PROTOCOL:
                if not callable(getattr(screen, method, None)):
                    missing.append(f"{name}.{method}")
        self.assertEqual(missing, [])

    def test_screens_start_not_done(self):
        for name, screen in app_harness.screens(self.controller):
            with self.subTest(state=name):
                self.assertFalse(screen.done, f"{name} was already done on construction")

    def test_active_state_is_the_menu(self):
        self.assertIs(self.controller.active_state, self.controller.states["MENU"])

    def test_lobby_music_and_settings_return_to_the_same_live_lobby(self):
        """Convenience screens must not drop a host or guest out of a lobby."""
        controller = self.controller
        original_active = controller.active_state
        original_settings_back = controller.states["SETTINGS"].back_state
        original_music_back = controller.states["MUSIC_PLAYER"].back_state
        try:
            for lobby_name in ("REALTIME_LOBBY", "REALTIME_REMOTE_LOBBY"):
                for destination in ("SETTINGS", "MUSIC_PLAYER"):
                    lobby = controller.states[lobby_name]
                    lobby.next_state, lobby.done = destination, True
                    controller.active_state = lobby
                    controller.flip_state()
                    self.assertEqual(controller.states[destination].back_state, lobby_name)
        finally:
            controller.active_state = original_active
            controller.states["SETTINGS"].back_state = original_settings_back
            controller.states["MUSIC_PLAYER"].back_state = original_music_back

    def test_clear_orders_keybind_is_available_by_default(self):
        from screens.menu_screens.keybinds import (
            KEYBIND_ACTIONS, MAP_PANNING_KEYBIND_ACTIONS,
            MOUSE_CLICK_KEYBIND_ACTIONS, default_keybinds, keybind_conflicts,
        )

        defaults = {action: default for action, _label, default in KEYBIND_ACTIONS}
        self.assertEqual(defaults["CLEAR_ORDERS"], pygame.K_DELETE)
        self.assertIn("CLEAR_ORDERS", self.controller.keybinds)
        self.assertEqual(default_keybinds()["PAN_LEFT"], pygame.K_LEFT)
        self.assertEqual(default_keybinds()["PAN_RIGHT"], pygame.K_RIGHT)
        self.assertEqual(default_keybinds()["PAN_UP"], pygame.K_UP)
        self.assertEqual(default_keybinds()["PAN_DOWN"], pygame.K_DOWN)
        self.assertEqual(len(MAP_PANNING_KEYBIND_ACTIONS), 4)
        self.assertEqual(len(MOUSE_CLICK_KEYBIND_ACTIONS), 3)
        self.assertTrue(all(default_keybinds()[action] is None
                            for action, _label, _default in MOUSE_CLICK_KEYBIND_ACTIONS))
        self.assertTrue(all(action in self.controller.keybinds
                            for action, _label, _default in MAP_PANNING_KEYBIND_ACTIONS))

        duplicate = default_keybinds()
        duplicate["PAN_LEFT"] = duplicate["ORDERS"]
        self.assertEqual(keybind_conflicts(duplicate),
                         [(pygame.K_q, ["Pan Left", "Orders"])])

    def test_keybind_mouse_events_preserve_physical_mouse_input(self):
        from gameState import synthesize_keybind_mouse_events

        physical_click = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                            button=1, pos=(20, 30))
        events = [physical_click,
                  pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a),
                  pygame.event.Event(pygame.KEYUP, key=pygame.K_a)]
        with mock.patch("gameState.pygame.mouse.get_pos", return_value=(80, 90)):
            translated = synthesize_keybind_mouse_events(
                events, {"MOUSE_LEFT_CLICK": pygame.K_a})

        self.assertIs(translated[0], physical_click)
        self.assertEqual(
            [(event.type, getattr(event, "button", None)) for event in translated],
            [(pygame.MOUSEBUTTONDOWN, 1), (pygame.KEYDOWN, None),
             (pygame.MOUSEBUTTONDOWN, 1), (pygame.KEYUP, None),
             (pygame.MOUSEBUTTONUP, 1)])
        self.assertEqual(translated[2].pos, (80, 90))
        self.assertTrue(translated[2].keybind_mouse)

    def test_keybind_screen_exposes_mouse_bindings_and_clear_controls(self):
        from screens.menu_screens.keybinds import ALL_KEYBIND_ACTIONS

        screen = self.controller.states["KEYBINDS"]
        button_text = [element.text for element in screen.elements
                       if hasattr(element, "text")]

        self.assertIn("Left Click Key: UNASSIGNED", button_text)
        self.assertIn("Middle Click Key: UNASSIGNED", button_text)
        self.assertIn("Right Click Key: UNASSIGNED", button_text)
        self.assertEqual(button_text.count("x"), len(ALL_KEYBIND_ACTIONS))
        self.assertIn("Change Screen\nWith This Keybind", button_text)

    def test_loaded_playable_maps_arm_the_navigation_tutorial(self):
        """The map constructor is shared by new, save, and multiplayer loads,
        so arming it here keeps all playable session types consistent."""
        game_map = app_harness.boot_map()
        self.assertTrue(game_map.show_navigation_intro_when_ready)

        import main
        editor_map = main.Map(load_path=app_harness.SCENARIO_PATH,
                              is_scenario=True, force_editor=True)
        self.assertFalse(editor_map.show_navigation_intro_when_ready)

    def test_editor_paint_selection_never_uses_the_unassigned_player_sentinel(self):
        """The loader must preserve editor mode and its UI must not expose
        player diplomacy when a paint stroke selects an ordinary province."""
        from screens.menu_screens.map import update_button_states
        import main

        editor_map = main.Map(load_path=app_harness.SCENARIO_PATH,
                              is_scenario=True, force_editor=True)
        editor_map.selected_province = next(
            province for province in editor_map.map_data.values()
            if province.get("owner") in editor_map.nation_data)

        self.assertEqual(editor_map.player_country, "Editor")
        update_button_states(editor_map)

        self.assertTrue(editor_map.btn_ed_nation.visible)
        self.assertFalse(editor_map.btn_declare_war.visible)

    def test_map_help_button_reopens_the_navigation_tutorial(self):
        game_map = app_harness.boot_map()
        with mock.patch("ui.confirm_dialog.show_navigation_intro") as show_tutorial:
            game_map.btn_help.callback()
        show_tutorial.assert_called_once_with(game_map)
        self.assertLess(game_map.btn_help.rect.right,
                        game_map.btn_refresh_all.rect.left)

    def test_tournament_host_top_toolbar_controls_do_not_overlap(self):
        from screens.menu_screens.map import update_button_states

        game_map = app_harness.boot_map()
        game_map.selection_mode = False
        game_map.selected_province = None
        game_map.player_country = "Spectator"
        game_map.multiplayer_mode = True
        game_map.multiplayer_host_mode = True
        game_map.ai_is_thinking = False
        update_button_states(game_map)

        buttons = (
            game_map.btn_spec_mp_manage,
            game_map.btn_spec_mp_export,
            game_map.btn_spec_mp_keys,
            game_map.btn_global_econ_overview,
            game_map.btn_help,
            game_map.btn_refresh_all,
            game_map.btn_exit_to_menu,
        )
        self.assertTrue(all(button.visible for button in buttons))
        for index, button in enumerate(buttons):
            for other in buttons[index + 1:]:
                self.assertFalse(button.rect.colliderect(other.rect),
                                 f"{button.text} overlaps {other.text}")

    def test_map_with_no_assigned_country_is_read_only_until_selection_recovers(self):
        """An interrupted map handoff must not treat the ``None`` sentinel as
        a country when a province is already selected.

        The player-facing diplomacy branch requires a nation_data record.  The
        fallback preserves map navigation and the close control, while keeping
        all country-owned actions unavailable until the assignment completes.
        """
        from screens.menu_screens.map import update_button_states

        game_map = app_harness.boot_map()
        original_player = game_map.player_country
        original_selected = game_map.selected_province
        original_selection_mode = game_map.selection_mode
        try:
            game_map.player_country = "None"
            game_map.selection_mode = False
            game_map.selected_province = next(
                province for province in game_map.map_data.values()
                if province.get("owner") in game_map.nation_data)

            update_button_states(game_map)

            self.assertTrue(game_map.btn_close_info.visible)
            self.assertFalse(game_map.btn_declare_war.visible)
            self.assertFalse(game_map.btn_gp_edit.visible)
        finally:
            game_map.player_country = original_player
            game_map.selected_province = original_selected
            game_map.selection_mode = original_selection_mode
            update_button_states(game_map)


class GlobalKeyDispatchTests(unittest.TestCase):
    class State:
        listening_for = None

        def __init__(self):
            self.cleared = 0
            self.back = 0

        def handle_back_key(self):
            self.back += 1

        def handle_clear_orders_key(self):
            self.cleared += 1

    def test_clear_orders_key_routes_to_optional_screen_handler(self):
        from gameState import dispatch_global_keys

        state = self.State()
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DELETE)
        with mock.patch("gameState.queries.get_keybind",
                        side_effect=lambda _action, default: default):
            dispatch_global_keys(state, event)

        self.assertEqual(state.cleared, 1)

    def test_clear_orders_key_honours_rebinding(self):
        from gameState import dispatch_global_keys

        state = self.State()
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x)

        def binding(action, default):
            return pygame.K_x if action == "CLEAR_ORDERS" else default

        with mock.patch("gameState.queries.get_keybind", side_effect=binding):
            dispatch_global_keys(state, event)

        self.assertEqual(state.cleared, 1)

    def test_keybinds_do_not_fire_while_a_text_bar_has_focus(self):
        from gameState import dispatch_global_keys

        state = self.State()
        state.active_input = "MODEL"
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DELETE)
        with mock.patch("gameState.queries.get_keybind",
                        side_effect=lambda _action, default: default):
            dispatch_global_keys(state, event)

        self.assertEqual(state.cleared, 0)

    def test_back_key_still_reaches_a_focused_text_bar(self):
        from gameState import dispatch_global_keys

        state = self.State()
        state.active_input = "MODEL"
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        with mock.patch("gameState.queries.get_keybind",
                        side_effect=lambda _action, default: default):
            dispatch_global_keys(state, event)

        self.assertEqual(state.back, 1)

    def test_keybinds_do_not_fire_while_an_army_name_editor_is_open(self):
        from gameState import dispatch_global_keys

        state = self.State()
        state.map_screen = mock.Mock(army_editor_state={"name": "Northern Command"})
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DELETE)
        with mock.patch("gameState.queries.get_keybind",
                        side_effect=lambda _action, default: default):
            dispatch_global_keys(state, event)

        self.assertEqual(state.cleared, 0)


if __name__ == "__main__":
    unittest.main()
