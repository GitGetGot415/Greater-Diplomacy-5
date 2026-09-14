"""Interactive map chrome preview for checking dense top-right UI layouts.

Run from the repository root with ``python map_tools/ui_layout_preview.py``.
The preview uses a temporary in-memory historical map only; it never writes a
scenario or save. Press 1-6 to change UI state, S to save a screenshot beneath
the system temporary directory, and Esc to quit.
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pygame

import data.constants as c
from data import queries


MODE_LABELS = {
    1: "Normal map",
    2: "Real-time map",
    3: "Packed army tray",
    4: "Spectator mode",
    5: "Tournament player",
    6: "Tournament host",
}


def _preview_session():
    player = SimpleNamespace(player_id="preview", submitted=False, eliminated=False,
                             connected=True, ping_ms=0, name="Preview Player",
                             country_id="")
    return SimpleNamespace(
        config=SimpleNamespace(max_turns=20), turn_number=4,
        deadline=time.monotonic() + 600, phase="TURN",
        players={"preview": player}, host_id="preview")


def _set_armies(game_map, count):
    queries.ensure_unit_ids(game_map.map_data)
    unit_ids = [unit["unit_id"] for province in game_map.map_data.values()
                for unit in province.get("units", [])
                if unit.get("owner") == game_map.player_country]
    armies = []
    emblems = queries.army_symbol_choices()
    for index in range(count):
        # The packed preview intentionally includes synthetic members after
        # the playable nation's real units run out. It is display-only data,
        # never serialized or submitted to a game.
        member = unit_ids[index] if index < len(unit_ids) else f"preview-unit-{index}"
        armies.append({"id": f"preview-army-{index}", "name": f"Army {index + 1}",
                       "unit_ids": [member],
                       "symbol": emblems[index % len(emblems)] if emblems else "",
                       "symbol_color": [80 + (index * 37) % 150,
                                        80 + (index * 67) % 150,
                                        80 + (index * 97) % 150]})
    game_map.nation_data[game_map.player_country]["armies"] = armies


def main():
    import main as game_main

    pygame.init()
    surface = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
    pygame.display.set_caption(
        "GD5 UI Layout Preview -- 1 Normal | 2 Real-time | 3 Packed | "
        "4 Spectator | 5 Tournament Player | 6 Tournament Host | S Screenshot")
    game_main._import_project_modules()
    game_map = game_main.Map(load_path="scenarios/historical/1939", is_scenario=True, num_players=1)
    # Pick the country with the largest starting force so every preview mode
    # has real stack art and a selected army to display.
    playable_country = max(
        queries.get_living_nations(game_map.map_data),
        key=lambda country: sum(1 for province in game_map.map_data.values()
                                for unit in province.get("units", [])
                                if unit.get("owner") == country))
    game_map.player_country = playable_country
    game_map.active_players = [playable_country]
    game_map.selection_mode = False
    game_map.is_editor = False
    game_map.navigation_intro_popup = None
    # The preview never connects to a real-time server, but the live toolbar
    # still binds these callbacks while drawing its real-time state.
    game_map._realtime_submit = lambda: None
    game_map._realtime_unsubmit = lambda: None
    mode = 1
    clock = pygame.time.Clock()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            elif event.type == pygame.KEYDOWN and event.key in (
                    pygame.K_1, pygame.K_2, pygame.K_3,
                    pygame.K_4, pygame.K_5, pygame.K_6):
                mode = int(event.unicode)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_s:
                output = Path(tempfile.gettempdir()) / "gd5_ui_previews"
                output.mkdir(exist_ok=True)
                path = output / f"ui_preview_{int(time.time())}.png"
                pygame.image.save(surface, path)
                print(f"Saved UI preview: {path}")

        game_map.realtime_multiplayer = mode in (2, 3)
        game_map.multiplayer_mode = mode in (5, 6)
        game_map.multiplayer_host_mode = mode == 6
        game_map.player_country = "Spectator" if mode in (4, 6) else playable_country
        game_map.active_players = ([playable_country] if mode != 6
                                   else [playable_country, "Germany"])
        if game_map.realtime_multiplayer:
            game_map.realtime_session = _preview_session()
            game_map.realtime_session.players["preview"].country_id = game_map.player_country
            game_map.realtime_player_id = "preview"
            game_map.realtime_connection_error = ""
        army_count = {1: 2, 2: 5, 3: 30, 5: 2}.get(mode, 0)
        if army_count:
            _set_armies(game_map, army_count)
        game_map.selected_province = None
        if army_count:
            first_army = game_map.nation_data[game_map.player_country]["armies"][0]
            game_map.selected_unit_ids = set(first_army["unit_ids"])
        else:
            game_map.selected_unit_ids = set()
        # Map.refresh_ui is deliberately a no-op; this is the same per-frame
        # button-state path used by the live map without starting networking.
        from screens.menu_screens.map import update_button_states
        update_button_states(game_map)
        game_map.draw(surface)
        label = pygame.font.Font(None, 24).render(
            f"{MODE_LABELS[mode]}  |  1-6 switch views  |  S saves screenshot",
            True, (255, 235, 150))
        surface.blit(label, (12, c.TOP_UI_HEIGHT + 8))
        pygame.display.flip()
        clock.tick(60)
    pygame.quit()


if __name__ == "__main__":
    main()
