"""Record or compare per-turn game state digests to prove that a refactor preserves gameplay.

Usage:
    python scripts/checks/turn_digest.py --output before.json
    python scripts/checks/turn_digest.py --compare before.json

Run both commands on the same unit, building, and research data. A tuning edit changes the digests.
The check covers headless AI turns only. It does not cover UI, multiplayer, or LLM paths.
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_SCENARIOS = ("scenarios/historical/1939", "scenarios/historical/1914",
                     "scenarios/alternate/Scripted Events Example", "scenarios/alternate/Absurd Puppet Chains")
DEFAULT_TURNS = 25
SEED = 12345


def canonical(value):
    if isinstance(value, dict):
        return sorted(([repr(key), canonical(item)] for key, item in value.items()), key=lambda pair: pair[0])
    if isinstance(value, (set, frozenset)):
        return sorted(repr(canonical(item)) for item in value)
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(type(value))


def play_scenario(scenario, turns, output):
    """Play one scenario. New unit and message IDs use a seeded generator so runs can match."""
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    id_source = random.Random(SEED)
    uuid.uuid4 = lambda: uuid.UUID(int=id_source.getrandbits(128), version=4)
    # Local imports: the seeded uuid4 must be installed before game modules load.
    from data import queries
    from map_logic.system32 import turn_processor
    from tests import app_harness
    import main

    app_harness.boot()
    # The check must not call a model or depend on the local LLM setting.
    queries.get_settings()["ai_mode"] = "OFF"
    game = main.Map(load_path=scenario, is_scenario=True)
    game.selection_mode = False
    game.pending_selection = None
    game.show_player_ready_screen = False
    game.player_country = "Spectator"
    game.active_players = []
    random.seed(SEED)
    digests = []
    for _turn in range(turns):
        game.ai_is_thinking = True
        asyncio.run(turn_processor.prepare_turn(game))
        game.ai_is_thinking = False
        game.viewing_ai_moves = True
        asyncio.run(turn_processor.resolve_turn_logic(game))
        game.viewing_ai_moves = False
        state = [canonical(game.map_data), canonical(game.nation_data), repr(random.getstate())]
        digests.append(hashlib.sha256(json.dumps(state).encode()).hexdigest()[:16])
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(digests, handle)


def collect(scenarios, turns):
    """Run each scenario in a new process with a fixed string hash seed."""
    results = {}
    environment = dict(os.environ, PYTHONHASHSEED="0", SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    with tempfile.TemporaryDirectory() as directory:
        for index, scenario in enumerate(scenarios):
            path = os.path.join(directory, f"{index}.json")
            completed = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--child", scenario, "--turns", str(turns), "--output", path],
                env=environment, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, errors="replace", check=False)
            if completed.returncode:
                raise SystemExit(f"{scenario} failed:\n{completed.stderr[-2000:]}")
            with open(path, encoding="utf-8") as handle:
                results[scenario] = json.load(handle)
            print(f"{scenario}: {len(results[scenario])} turns, final digest {results[scenario][-1]}")
    return results


def compare(expected, actual):
    """Return the number of scenarios that differ, and name the first different turn of each."""
    failures = 0
    for scenario, digests in expected.items():
        other = actual[scenario]
        if digests == other:
            print(f"MATCH {scenario}")
            continue
        failures += 1
        turn = next((index + 1 for index, (a, b) in enumerate(zip(digests, other)) if a != b),
                    min(len(digests), len(other)) + 1)
        print(f"DIFFERENT {scenario}: first differs on turn {turn}")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", help="Write digests to this JSON file.")
    parser.add_argument("--compare", help="Compare new digests to this JSON file.")
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS)
    parser.add_argument("--scenario", action="append", help="Scenario path. Repeat for more than one.")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        play_scenario(args.child, args.turns, args.output)
        return 0
    if not args.output and not args.compare:
        parser.error("Give --output or --compare.")
    if args.compare:
        with open(args.compare, encoding="utf-8") as handle:
            expected = json.load(handle)
        turns = len(next(iter(expected.values())))
        return 1 if compare(expected, collect(tuple(expected), turns)) else 0
    results = collect(tuple(args.scenario or DEFAULT_SCENARIOS), args.turns)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
