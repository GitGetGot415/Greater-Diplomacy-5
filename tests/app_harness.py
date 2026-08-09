"""Boots the real application headlessly so tests can poke at real screens.

Controller() constructs all 23 screens without ever entering run()'s loop, which
makes it the cheapest possible guard against constructor-signature drift and
missing-attribute regressions. Getting there needs three things arranged first:

1. SDL pointed at its dummy video/audio drivers.
2. mod_loader neutralised. main._import_project_modules() calls
   mod_loader.install(), which would otherwise apply whatever happens to be
   sitting in the developer's mods/ folder and make test results depend on local
   state. Stubbing mod_files() to return nothing is enough -- install() reads the
   mod set through it and does nothing when it comes back empty.
3. A real display surface, since several screen constructors call
   pygame.display.get_surface() to snapshot a background.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_controller = None
_surface = None
_map = None

# A real historical scenario, so the map-related screens get real provinces,
# units, research and diplomacy to render rather than a stub. Loads in well
# under a second headlessly.
SCENARIO_PATH = "scenarios/historical/1939"

# How flip_state() hands the map to each map-layered screen (main.py's
# "1. Data Handoff" block). Screens taking a province go through
# start_with_province; the rest each have their own one-argument entry point.
MAP_HANDOFFS = {
    "PRODUCTION": "start_with_province",
    "ORDERS": "start_with_province",
    "EDIT_COUNTRY": "start_editor",
    "RESEARCH": "start_research",
    "ECONOMY": "start_economy",
    "MESSAGES": "start_messages",
    "FACTION": "start_faction",
    "FACTION_TERRITORIES": "start_view",
}


def boot():
    """Returns (controller, surface), building them once per interpreter."""
    global _controller, _surface
    if _controller is not None:
        return _controller, _surface

    import mod_loader
    mod_loader.mod_files = lambda: []

    import main
    main._import_project_modules()

    import pygame
    import data.constants as c

    pygame.init()
    _surface = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
    _controller = main.Controller()
    return _controller, _surface


def screens(controller):
    """(state_name, screen) for every state that is constructed up front.

    "MAP" is deliberately None in Controller.states -- it is built by
    flip_state() once a scenario has been chosen -- so it is skipped here.
    """
    return [(name, screen) for name, screen in controller.states.items() if screen is not None]


def boot_map():
    """Loads SCENARIO_PATH into a real Map, wires it into the controller, and
    performs every map-layered screen's handoff.

    Without this, PRODUCTION/ORDERS/ECONOMY/MESSAGES sit with map_screen and
    target_province still None and raise the moment anything touches them --
    which would mean the screens carrying the heaviest panel and scroll code
    were the ones the smoke test could not reach.
    """
    global _map
    if _map is not None:
        return _map

    controller, _ = boot()
    import main
    import data.queries as queries

    game_map = main.Map(load_path=SCENARIO_PATH, is_scenario=True, num_players=1)

    living = sorted(queries.get_living_nations(game_map.map_data))
    game_map.player_country = living[0]
    game_map.active_players = [living[0]]
    game_map.selected_province = next(p for p in game_map.map_data.values()
                                      if p.get("owner") == living[0])

    controller.states["MAP"] = game_map
    for state_name, handoff in MAP_HANDOFFS.items():
        screen = controller.states[state_name]
        if handoff == "start_with_province":
            screen.start_with_province(game_map.selected_province, game_map)
        else:
            getattr(screen, handoff)(game_map)

    _map = game_map
    return game_map
