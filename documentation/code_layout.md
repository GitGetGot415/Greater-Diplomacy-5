# Code layout

AI means artificial intelligence. UI means user interface.
Use this guide to find the owner of a change.
Read `general_info.txt` for state ownership, storage, and build policy.

## Directory responsibilities

| Directory | Responsibility |
| --- | --- |
| `assets/` | Images and audio. |
| `base_maps/` | Shipped map bundles. Their content paths stay unchanged. |
| `context/` | Development notes and source export tools. |
| `data/` | State containers, shared queries, constants, content, compatibility, and external data boundaries. |
| `data/json/` | Runtime unit, building, research, country, leader, and AI response content. |
| `data/generators/` | Content recipes and generation. Keep tuning sources beside their generated content. |
| `data/map/` | Regular saves, loads, history, and derived-layer file handling. |
| `data/queries/` | Shared state queries and rule helpers. Each module covers one topic. |
| `data/io/` | Settings, country content, and shared JSON file helpers. |
| `data/multiplayer/tournament/` | Tournament archives, authentication, partial moves, and host validation. |
| `data/multiplayer/realtime/` | Authoritative sessions, clients, servers, snapshots, transports, and relay infrastructure. |
| `map_logic/actions/` | Shared validation and execution of player intents, production purchases, and unit orders. |
| `map_logic/ai/` | Rule-based decisions, legal candidates, valuation, and large language model integration. |
| `map_logic/diplomacy/` | Diplomatic requests, agreements, wars, factions, subjects, and their effects. |
| `map_logic/territory/` | Ownership, cores, claims, and country retirement. |
| `map_logic/system32/` | Turn preparation, coordination, resolution, and unit reports. |
| `map_logic/random_map/` | World geometry and random scenario generation used by the game. |
| `map_logic/imports/` | Map and save conversion from other games. |
| `screens/menus/` | Main navigation, application settings, media, assets, mods, and translation screens. |
| `screens/setup/` | New-game configuration, scenario settings, and initial player selection. |
| `screens/multiplayer/` | Tournament and real-time setup, joining, hosting, and lobby screens. |
| `screens/game/` | The map screen, map input, spectator controls, and in-game feature screens. |
| `screens/editors/` | In-game country, economy, date, research, brush, diplomacy, event, leader, and turn-setting editors. |
| `ui/rendering/` | Cached map surfaces, overlays, labels, fonts, and symbols. |
| `ui/camera/` | Map camera interaction and viewing transforms. |
| `ui/dialogs/` | Shared dialogs, notifications, and reusable pickers. `pickers.py` opens pickers. `file_exchange.py` exports and imports player files. |
| `ui/navigation/` | The `Screen` base class, screen runners, modal screens, and the modal stack. |
| `ui/panels/` | Persistent map panels, progress drawing, status displays, and shared panel layout. |
| `ui/widgets/` | Text, flags, tables, and scrolling support. |
| `ui/bars/` | The map heads-up display and view controls. |
| `ui/information/` | Hover feedback, tooltips, and unit information popups. |
| `scripts/` | Offline content editors, maintenance, dependency downloads, benchmarks, and previews. |
| `scripts/data/` | Country-content maintenance. |
| `scripts/maps/` | Offline map creation, repair, and validation. |
| `scripts/editors/` | Standalone desktop content editors. |
| `scripts/dependencies/` | Dependency download tools. |
| `scripts/benchmarks/` | Objective Judge Horizon entry points. |
| `scripts/previews/` | Interactive UI development previews. |
| `scripts/checks/` | Refactor and test checks: gameplay digests and tuning independence. |
| `tests/` | Functional tests, regression tests, and shared test support. |
| `documentation/` | Maintained guides and design notes. |
| `saves/` | Saved games. |
| `scenarios/` | Scenario data. |
| `dist/` | Generated distribution packages. Do not edit these as source. |

`AGENTS.md` defines repository rules for AI changes.
`context/context_generator.py` combines source files into a text file.
`scripts/maps/validation/check_flags.py` and `check_adjectives.py` check `data/json/countries_data.json`.
`scripts/maps/interactive_map_tester.py` provides an interactive pygame map tester. Its earlier name was `tester.py`.
`scripts/maps/automatic_map_painter.py` and `reset_map_data.py` are separate map-authoring tools.

Complete feature screens belong in `screens/`. Each screen builds its own buttons.

The folders identify owners. Some existing rules still call presentation helpers.
Turn coordination still connects AI, resolution, and presentation refreshes.
Moving those files does not change execution order or permissions.

The `map_logic/system32/` name is intentional.
Keep this name unless the user explicitly requests a different name.

## Where to make a change

| Task | Start here |
| --- | --- |
| Ask a shared question about current state | `data/queries/` |
| Change unit, building, or research tuning | `data/json/`, `data/generators/recipes.py`, and shared constants |
| Change world or participant state ownership | `data/game_state.py` and `data/session_state.py` |
| Change production validation, payment, or refunds | `map_logic/actions/production_actions.py` |
| Change unit-order validation, payment, or cancellation | `map_logic/actions/unit_actions.py` |
| Validate a player command independently of its transport | `map_logic/actions/player_actions.py` |
| Change territory ownership or cores | `map_logic/territory/ownership.py` |
| Change turn sequencing | `map_logic/system32/turn_processor.py` and `turn_manager.py` |
| Change map buttons or map input | `screens/game/map.py` and `map_input.py` |
| Change what a screen does when it opens | The `on_enter` method of that screen |
| Change how a screen opens the map | The `prepare_map` method of that screen and `screens/game/map_launch.py` |
| Add or change a diplomatic action | `map_logic/diplomacy/action_definitions.py`, `treaty_effects.py`, and `diplomacy_processor.py` |
| Change initial country or tactical-unit selection | `screens/setup/player_setup.py` |
| Change unit rows, unit commands, or map targeting in Orders and Tactical Orders | `ui/panels/unit_commands.py` |
| Change the Orders or Tactical Orders panel itself | `screens/game/orders.py` or `screens/game/tactical_orders.py` |
| Change country-edit controls | `screens/editors/edit_country.py` |
| Change application settings buttons | `screens/menus/settings.py` |
| Change map drawing or display caches | `ui/rendering/` |
| Change map panels or progress drawing | `ui/panels/` |
| Change tournament file exchange | `data/multiplayer/tournament/files.py` |
| Change real-time authority or snapshots | `data/multiplayer/realtime/session.py` |
| Change real-time transport or relay provisioning | `data/multiplayer/realtime/networking.py` and `relay.py` |
| Change the fresh-game tutorial | `ui/dialogs/message_box.py` |
| Check source packaging and dynamic imports | `compilation_scripts/build_manifest.py` and `tests/test_build_manifest.py` |

Read `general_info.txt`, DISPLAY SUPPORT, for shared image caches.
Camera tilt also uses `ui/rendering/map_utils.py`.

`data/queries/` is a package that replaces the former single module `data/queries.py`.
The package `__init__.py` re-exports every public name, so callers still write `queries.name(...)`.
A new public name needs no entry in `__init__.py`.
Do not use a public name in two modules of this package. `tests/test_queries_package.py` checks this.
Each module imports only from modules that come before it in the layer list in `data/queries/__init__.py`.
A test can replace a query with `mock.patch.object(queries, "name", ...)`.
Other queries must still see that replacement.
They therefore read replaced names as `queries.name` and do not import them.
Read the `data/queries/__init__.py` docstring before you add a query that tests replace.

Modules in `data/` do not import `ui/` or `screens/`.
Put code that opens a dialog or a screen in `ui/` or `screens/`.
`data/multiplayer/tournament/files.py` is an exception. It draws a progress bar and clears name caches.
`data/migrations/snapshot_moves.py` is a temporary exception. It clears name caches. It stays while snapshot moves convert.
`tests/test_queries_package.py` checks this rule.

Read [AGENTS.md, Imports](../AGENTS.md#imports) for the import policy.
Game startup installs mods before importing game modules.
Deferred imports avoid initialization cycles and preserve headless execution and optional platform features.

## Development commands

Run commands from the repository root.
The dependency download command accesses the network.
The country maintenance command writes country content.
Review its source before use.

1. Run all tests with `python run_tests.py`.
2. Check content generation with `python data/generators/generate_data.py --check`.
3. Open the layout preview with `python scripts/previews/ui_layout_preview.py`.
4. Show benchmark options with `python scripts/benchmarks/ojh_benchmark.py --help`.
5. Download the browser dependency with `python scripts/dependencies/fetch_dragoman_wasm.py`.
6. Open the standalone country editor with `python scripts/editors/country_editor.py`.
7. Run sandbox tests with `python -m unittest tests.test_mod_loader_security`.
8. Record gameplay digests with `python scripts/checks/turn_digest.py --output before.json`.
9. Compare gameplay digests with `python scripts/checks/turn_digest.py --compare before.json`.
10. Find tests that depend on tuning with `python scripts/checks/tuning_stress.py`.

Runtime modules use their current import paths directly.
Source-replacement mods must use the current target paths and imports.
The save format, settings keys, content paths, and game version remain unchanged.

Test files keep their existing module names for focused commands.
The sandbox cases also run during normal test discovery.
The test runner reports discovery time, slow tests, and slow test groups.
Group times include shared fixture work that individual test times omit.
Use `python run_tests.py tests.test_import_smoke` to time one module.
Use `--durations 0` to hide timing details. Use `--quiet` to hide per-test progress.
Import and sandbox probes run up to four child processes concurrently.
Each probe keeps its own interpreter. Sandbox probes also keep separate temporary folders.
Full test runs use up to four worker processes. Each worker has separate pygame state and patched globals.
Each discovered module suite stays together. Its tests run sequentially within one worker.
Workers retain normal discovery hooks, failure reports, skips, and timing results.
Use `--jobs 1` for sequential execution. Use `--jobs 2` to reduce worker memory use.
Focused commands use one process unless you supply `--jobs`.
Content checks reuse parsed indexes while their source libraries stay unchanged.
Archive behavior tests use fast password derivation. Dedicated encryption tests retain production derivation and its required work factor.
Air UI tests use fresh in-memory maps. Persistence tests still save and load real files.
The cached application harness restores its display before reuse if another test changed the display size.
The ODTL module supplies a discovery hook for its standalone function tests.
Builds do not include offline tools from `scripts/`.
