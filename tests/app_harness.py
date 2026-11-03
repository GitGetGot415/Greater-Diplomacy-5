"""Boots the real application headlessly so tests can poke at real screens.

Controller() constructs all 23 screens without ever entering run()'s loop, which
makes it the cheapest possible guard against constructor-signature drift and
missing-attribute regressions. Getting there needs three things arranged first:

1. SDL pointed at its dummy video/audio drivers. SoLoud is disabled because
   its native output bypasses SDL's silent driver, and startup music is skipped.
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
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests import configure_test_audio
configure_test_audio()

_controller = None
_surface = None
_map = None

#: Which states were still unbuilt the moment the controller was constructed.
#: boot() is cached per interpreter and boot_map() fills MAP in, so a test that
#: asks "is MAP built lazily?" gets a different answer depending on which files
#: discovery happened to run first. Recorded once, at boot, so it cannot.
STATES_UNBUILT_AT_BOOT = set()

# A real historical scenario, so the map-related screens get real provinces,
# units, research and diplomacy to render rather than a stub. Loads in well
# under a second headlessly.
SCENARIO_PATH = "scenarios/historical/1939"

# The screens whose on_enter hook hands them the map.
MAP_LAYERED_STATES = ("PRODUCTION", "ORDERS", "EDIT_COUNTRY", "RESEARCH", "ECONOMY",
                      "MESSAGES", "FACTION", "FACTION_TERRITORIES")


def boot():
    """Returns (controller, surface), building them once per interpreter."""
    global _controller, _surface
    if _controller is not None:
        # Other tests can resize the shared SDL display between harness calls.
        import pygame
        import data.constants as c
        current = pygame.display.get_surface()
        if current is None or current.get_size() != (c.SCREEN_WIDTH, c.SCREEN_HEIGHT):
            pygame.display.init()
            current = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        _surface = current
        return _controller, _surface

    import mod_loader
    mod_loader.mod_files = lambda: []

    import main
    main._import_project_modules()

    import pygame
    import data.constants as c

    # Keep the real mixer available for audio assertions, with no device output.
    # Test code may still mock SoLoud explicitly when checking that backend.
    configure_test_audio()
    c.USE_SOLOUD = False
    pygame.init()
    _surface = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
    # Guard constructor checks against accidental audio or synthesizer startup.
    # Normal startup playback belongs to run(), after the first displayed frame.
    with patch.object(main.Controller, "play_startup_song"):
        _controller = main.Controller()
    STATES_UNBUILT_AT_BOOT.update(
        name for name, screen in _controller.states.items() if screen is None)
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
    controller, _ = boot()
    if _map is not None:
        return _map

    import main
    import data.queries as queries

    game_map = main.Map(load_path=SCENARIO_PATH, is_scenario=True, num_players=1)

    living = sorted(queries.get_living_nations(game_map.map_data))
    game_map.player_country = living[0]
    game_map.active_players = [living[0]]
    game_map.selected_province = next(p for p in game_map.map_data.values()
                                      if p.get("owner") == living[0])

    controller.states["MAP"] = game_map
    for state_name in MAP_LAYERED_STATES:
        controller.states[state_name].on_enter(controller, game_map)

    _map = game_map
    return game_map


from contextlib import contextmanager, ExitStack
from dataclasses import fields
from data.game_state import WorldState
from data.session_state import SessionState

_WORLD_FIELDS = {item.name for item in fields(WorldState)}
_SESSION_FIELDS = {item.name for item in fields(SessionState)}


def state_owner(game, name):
    """Patch the explicit owner rather than a compatibility property."""
    if name in _WORLD_FIELDS:
        return game.world
    if name in _SESSION_FIELDS:
        return game.session
    return game


@contextmanager
def patch_map(game, values=None, **kwargs):
    values = dict(values or {}, **kwargs)
    groups = {"world": {}, "session": {}, "presentation": {}}
    for name, value in values.items():
        group = "world" if name in _WORLD_FIELDS else "session" if name in _SESSION_FIELDS else "presentation"
        groups[group][name] = value
    with ExitStack() as stack:
        stack.enter_context(patch.dict(game.__dict__, groups["presentation"]))
        stack.enter_context(patch.dict(game.world.__dict__, groups["world"]))
        stack.enter_context(patch.dict(game.session.__dict__, groups["session"]))
        yield
