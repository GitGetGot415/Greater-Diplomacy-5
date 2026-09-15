"""Benchmark hooks for Objective Judge Horizon (OJH).

OJH (https://github.com/Pr1nted/objective-judge-horizon) measures turn-based
strategy games the same way on the same machine: turn speed, frame rate,
network use and footprint. Without these hooks it has to drive Greater
Diplomacy 5 from the outside, and an outside driver can only guess which calls
make up a turn. This tool measures GD5 through GD5's own code instead:

    python map_tools/ojh_benchmark.py turns --turns 250 --scenario scenarios/historical/1939
    python map_tools/ojh_benchmark.py fps --seconds 5 --late-turns 20 --scenario scenarios/historical/1939

`turns` plays every nation as AI with no window (SDL's dummy driver) and times
each turn from the End Turn call to the end of the last map refresh: AI
preparation (turn_processor.prepare_turn), resolution and the seven refresh
passes, through turn_manager exactly as a player with Skip AI View on gets
them. Nothing about a turn is re-implemented here; the one change is that the
two background phases are awaited in place instead of being handed to
data.platform.run_background, so each turn is timed start to finish.

`fps` opens the real game window with no frame cap and times every frame of
each scene after it settles: the main menu, the map at the start, zoomed all
the way out, zoomed all the way in, scrolling, the largest nation's research screen, the map
while a turn resolves in the background (as a player watches it), and the map
again after --late-turns turns.

Both print OJH's line protocol on stdout, one line per fact:

    OJH players <n>                       AI nations playing
    OJH regions <n> provinces
    OJH ready                             the game is loaded; turn 1 starts next
    OJH turn <n> <seconds>
    OJH renderer <text> / OJH resolution <w>x<h> / OJH vsync off
    OJH scene <name> <frames> <seconds> <p50 ms> <p95 ms> <p99 ms> <1% low fps>
    OJH noscene <name> <why>

Model-driven diplomacy is skipped every turn, the same as pressing Force Skip,
so a benchmark never waits on (or pays for) a remote model. Everything else the
game prints goes to stderr so stdout stays machine-readable.

This is a developer tool: map_tools/ is not shipped by any build.
"""

import argparse
import asyncio
import contextlib
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_SCENARIO = "scenarios/historical/1939"

# Seconds each scene runs before its frames count, so a rebuilt surface or a
# first draw is not timed. The map gets longer because its layers are built
# lazily on the first frames after a load.
SETTLE_SECONDS = 2.0
MAP_START_SETTLE_SECONDS = 5.0

# World units the camera moves per frame in the scrolling scene, divided by
# the zoom so the picture moves the same distance on screen at any zoom.
PAN_STEP = 6.0

# How long the end-turn scene waits for a turn before calling it stuck.
TURN_TIMEOUT_SECONDS = 600.0


# The real stdout, kept before any of the game's prints are sent to stderr, so
# a protocol line written while that redirect is active still reaches OJH.
PROTOCOL_OUT = sys.stdout


def say(text):
    PROTOCOL_OUT.write(text + "\n")
    PROTOCOL_OUT.flush()


def scene_statistics(frame_seconds):
    """(frames, seconds, p50 ms, p95 ms, p99 ms, 1% low fps) for one scene.

    The 1% low is the frame rate over the slowest 1% of frames (at least one),
    the figure OJH compares across games. None when too few frames were drawn
    to say anything.
    """
    if len(frame_seconds) < 2:
        return None
    ordered = sorted(frame_seconds)
    count = len(ordered)
    total = sum(ordered)
    slow_count = max(1, count // 100)
    slow = sum(ordered[count - slow_count:])

    def percentile(p):
        return ordered[min(count - 1, int(p * (count - 1)))] * 1000.0

    low = slow_count / slow if slow > 0 else 0.0
    return count, total, percentile(0.50), percentile(0.95), percentile(0.99), low


def report_scene(name, frame_seconds):
    stats = scene_statistics(frame_seconds)
    if stats is None:
        say(f"OJH noscene {name} too few frames were drawn to time")
        return
    count, total, p50, p95, p99, low = stats
    say(f"OJH scene {name} {count} {total:.5f} {p50:.3f} {p95:.3f} {p99:.3f} {low:.2f}")


def boot(scenario, window):
    """Loads the scenario into a real Controller and Map, every nation AI.

    Uses tests/app_harness.py, which already performs flip_state()'s map
    hand-off for every map-layered screen; a second copy of that here would
    drift. The harness points SDL at its dummy drivers, so a windowed run puts
    the video driver back before pygame starts.
    """
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    video_driver = os.environ.get("SDL_VIDEODRIVER")
    from tests import app_harness
    if window:
        if video_driver is None:
            os.environ.pop("SDL_VIDEODRIVER", None)
        else:
            os.environ["SDL_VIDEODRIVER"] = video_driver
    app_harness.SCENARIO_PATH = scenario
    controller, surface = app_harness.boot()
    map_screen = app_harness.boot_map()
    map_screen.player_country = "Spectator"
    map_screen.active_players = []
    map_screen.selection_mode = False
    map_screen.skip_ai_view = True
    return controller, surface, map_screen


def skip_model_diplomacy(map_screen):
    """What the Force Skip button does. trigger_ai_thread() clears both flags at
    the start of every turn, so this runs after it, every turn."""
    from map_logic.ai import ai_handler
    map_screen.force_skip_llm = True
    ai_handler.FORCE_SKIP = True


async def play_turn(map_screen):
    """One whole turn through turn_manager, returning its wall-clock seconds.

    advance_time() is the End Turn button. It prepares the turn and hands AI
    preparation to run_background; Map.update() is the frame that notices
    preparation finished and, with Skip AI View on, calls advance_time() again
    for resolution and the refresh passes. Both hand-offs are caught and awaited
    here so the turn is timed from its first call to its last refresh.
    """
    from map_logic.turn_processing import turn_manager

    pending = []

    def hold(fn, *args, **kwargs):
        pending.append((fn, args, kwargs))

    async def run_pending():
        while pending:
            fn, args, kwargs = pending.pop(0)
            result = fn(*args, **kwargs)
            if asyncio.iscoroutine(result):
                await result

    background = turn_manager.run_background
    turn_manager.run_background = hold
    try:
        started = time.perf_counter()
        turn_manager.advance_time(map_screen)
        skip_model_diplomacy(map_screen)
        await run_pending()
        map_screen.update()
        await run_pending()
        seconds = time.perf_counter() - started
    finally:
        turn_manager.run_background = background
    if map_screen.thread_error:
        raise RuntimeError(f"turn failed inside Greater Diplomacy 5:\n{map_screen.thread_error}")
    return seconds


def run_turns(args):
    random.seed(args.seed)
    with contextlib.redirect_stdout(sys.stderr):
        _, _, map_screen = boot(args.scenario, window=False)
        from data import queries
        players = len(queries.get_active_ai_nations(map_screen))
    say(f"OJH players {players}")
    say(f"OJH regions {len(map_screen.map_data)} provinces")
    say("OJH ready")

    async def play():
        for turn in range(1, args.turns + 1):
            with contextlib.redirect_stdout(sys.stderr):
                seconds = await play_turn(map_screen)
            say(f"OJH turn {turn} {seconds:.6f}")

    asyncio.run(play())
    return 0


class FrameClock:
    """Times each drawn frame of one scene, ignoring the settle period."""

    def __init__(self, name, seconds, settle):
        now = time.perf_counter()
        self.name = name
        self.count_from = now + settle
        self.end = self.count_from + seconds
        self.last = now
        self.frames = []

    def tick(self):
        now = time.perf_counter()
        if now >= self.count_from:
            self.frames.append(now - self.last)
        self.last = now
        return now < self.end


def bring_window_to_front():
    """macOS throttles a window that is covered or not in front to about one
    frame a second (display.flip() blocks for a second every few frames), which
    would time the operating system rather than the game. pygame-ce exposes the
    window; plain pygame does not, and then this does nothing."""
    import pygame
    window_type = getattr(pygame, "Window", None)
    if window_type is not None:
        window_type.from_display_module().focus()


def draw_frame(state, surface):
    import pygame
    events = pygame.event.get()
    for event in events:
        if event.type == pygame.QUIT:
            raise SystemExit(1)
    state.handle_events(events)
    state.update()
    state.draw(surface)
    pygame.display.flip()


def run_scene(name, state, surface, seconds, settle=SETTLE_SECONDS, every_frame=None):
    clock = FrameClock(name, seconds, settle)
    while True:
        if every_frame:
            every_frame()
        draw_frame(state, surface)
        if not clock.tick():
            break
    report_scene(name, clock.frames)


def set_camera(map_screen, zoom, center):
    """Snaps the camera to `zoom` with `center` (world units) in the middle of
    the map area, instead of easing there over the next frames."""
    import data.constants as c
    import pygame
    camera = map_screen.camera
    view_h = c.SCREEN_HEIGHT - map_screen.top_ui_height
    pos = pygame.Vector2(center.x - c.SCREEN_WIDTH / (2 * zoom),
                         center.y - view_h / (2 * zoom * camera.tilt_factor))
    camera.zoom = camera.target_zoom = zoom
    camera.pos = pygame.Vector2(pos)
    camera.target_pos = pygame.Vector2(pos)


def camera_center(map_screen):
    import data.constants as c
    import pygame
    camera = map_screen.camera
    view_h = c.SCREEN_HEIGHT - map_screen.top_ui_height
    return pygame.Vector2(camera.pos.x + c.SCREEN_WIDTH / (2 * camera.zoom),
                          camera.pos.y + view_h / (2 * camera.zoom * camera.tilt_factor))


def run_fps(args):
    random.seed(args.seed)
    with contextlib.redirect_stdout(sys.stderr):
        controller, surface, map_screen = boot(args.scenario, window=True)
    import pygame
    import data.constants as c
    bring_window_to_front()

    say(f"OJH renderer pygame {pygame.version.ver}, SDL {'.'.join(map(str, pygame.get_sdl_version()))}, "
        f"{pygame.display.get_driver()} (software drawing)")
    say(f"OJH resolution {surface.get_width()}x{surface.get_height()}")
    say("OJH vsync off")

    with contextlib.redirect_stdout(sys.stderr):
        seconds = args.seconds
        run_scene("menu", controller.states["MENU"], surface, seconds)

        run_scene("map-start", map_screen, surface, seconds, settle=MAP_START_SETTLE_SECONDS)
        home_zoom = map_screen.camera.zoom
        home_center = camera_center(map_screen)

        set_camera(map_screen, map_screen.min_zoom, home_center)
        run_scene("map-out", map_screen, surface, seconds)

        set_camera(map_screen, c.MAX_CAMERA_ZOOM, home_center)
        run_scene("map-in", map_screen, surface, seconds)

        set_camera(map_screen, home_zoom, home_center)

        def pan():
            center = camera_center(map_screen)
            center.x += PAN_STEP / map_screen.camera.zoom
            set_camera(map_screen, map_screen.camera.zoom, center)

        run_scene("map-pan", map_screen, surface, seconds, every_frame=pan)

        set_camera(map_screen, home_zoom, home_center)
        run_research_scene(controller, map_screen, surface, seconds)

        run_end_turn_scene(map_screen, surface)

        async def late():
            for _ in range(args.late_turns):
                await play_turn(map_screen)

        asyncio.run(late())
        set_camera(map_screen, home_zoom, home_center)
        run_scene("map-late", map_screen, surface, seconds)
    return 0


def largest_nation(map_screen):
    """The nation holding the most provinces, the busiest research screen."""
    from data import queries
    living = sorted(queries.get_living_nations(map_screen.map_data))
    return max(living, key=lambda nation: len(queries.get_nation_provinces_and_units(nation, map_screen.map_data)[0]))


def run_research_scene(controller, map_screen, surface, seconds):
    """The research screen, as a spectator sees it after picking a nation.

    A spectator has no research of its own: the screen shows the nation chosen
    through `viewing_research_country`. Without one it draws nothing, which
    would time an empty screen, so the largest nation is picked for it and
    unpicked afterwards.
    """
    research = controller.states["RESEARCH"]
    map_screen.viewing_research_country = largest_nation(map_screen)
    try:
        research.start_research(map_screen)
        run_scene("panel", research, surface, seconds)
    finally:
        map_screen.viewing_research_country = ""


def run_end_turn_scene(map_screen, surface):
    """Frames drawn while one turn resolves on its background thread, the way a
    player watching the loading bar sees it. Timed for the whole turn, with no
    settle: the turn is the scene."""
    from map_logic.turn_processing import turn_manager

    frames = []
    started = time.perf_counter()
    turn_manager.advance_time(map_screen)
    last = time.perf_counter()
    while True:
        skip_model_diplomacy(map_screen)
        draw_frame(map_screen, surface)
        now = time.perf_counter()
        frames.append(now - last)
        last = now
        busy = map_screen.ai_is_thinking or map_screen.is_refreshing or map_screen.viewing_ai_moves
        if not busy or map_screen.thread_error:
            break
        if now - started > TURN_TIMEOUT_SECONDS:
            say(f"OJH noscene end-turn the turn did not finish within {TURN_TIMEOUT_SECONDS:.0f} s")
            return
    if map_screen.thread_error:
        raise RuntimeError(f"turn failed inside Greater Diplomacy 5:\n{map_screen.thread_error}")
    report_scene("end-turn", frames)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO,
                        help="scenario or map directory to load (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=20260914, help="seed for Python's random module")
    modes = parser.add_subparsers(dest="mode", required=True)
    turns = modes.add_parser("turns", help="time turns with no window")
    turns.add_argument("--turns", type=int, default=50)
    fps = modes.add_parser("fps", help="time frames in the real window")
    fps.add_argument("--seconds", type=float, default=5.0, help="seconds each scene is timed for")
    fps.add_argument("--late-turns", type=int, default=20, help="turns played before the late-game map scene")
    args = parser.parse_args(argv)
    if args.mode == "turns":
        return run_turns(args)
    return run_fps(args)


if __name__ == "__main__":
    sys.exit(main())
