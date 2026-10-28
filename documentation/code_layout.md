# Code layout

Use this guide to find the owner of a change.
Read `general_info.txt` for state ownership, storage, and build policy.
Read `source_layout_changes.md` for previous and current source paths.

## Directory responsibilities

| Directory | Responsibility |
| --- | --- |
| `base_maps/` | Shipped map bundles. Their content paths stay unchanged. |
| `data/` | State containers, shared queries, constants, content, compatibility, and external data boundaries. |
| `data/json/` | Runtime unit, building, research, country, leader, and AI response content. |
| `data/generators/` | Content recipes and generation. Keep tuning sources beside their generated content. |
| `data/map/` | Regular saves, loads, history, and derived-layer file handling. |
| `data/io/` | Settings, country content, and shared JSON file helpers. |
| `data/multiplayer/tournament/` | Tournament archives, authentication, partial moves, and host validation. |
| `data/multiplayer/realtime/` | Authoritative sessions, clients, servers, snapshots, transports, and relay infrastructure. |
| `map_logic/actions/` | Shared validation and execution of player intents, production purchases, and unit orders. |
| `map_logic/ai/` | Rule-based decisions, legal candidates, valuation, and large language model integration. |
| `map_logic/diplomacy/` | Diplomatic requests, agreements, wars, factions, subjects, and their effects. |
| `map_logic/territory/` | Ownership, cores, claims, and country retirement. |
| `map_logic/turn_processing/` | Turn preparation, coordination, resolution, and unit reports. |
| `map_logic/random_map/` | World geometry and random scenario generation used by the game. |
| `map_logic/imports/` | Map and save conversion from other games. |
| `screens/menus/` | Main navigation, application settings, media, assets, mods, and translation screens. |
| `screens/setup/` | New-game configuration, scenario settings, and initial player selection. |
| `screens/multiplayer/` | Tournament and real-time setup, joining, hosting, and lobby screens. |
| `screens/game/` | The map screen, map input, spectator controls, and in-game feature screens. |
| `screens/editors/` | Editors that operate within the game. |
| `ui/rendering/` | Cached map surfaces, overlays, labels, fonts, and symbols. |
| `ui/camera/` | Map camera interaction and viewing transforms. |
| `ui/dialogs/` | Shared dialogs, notifications, and reusable pickers. |
| `ui/navigation/` | Screen runners, modal screens, and the modal stack. |
| `ui/panels/` | Persistent map panels, progress drawing, status displays, and shared panel layout. |
| `ui/widgets/` | Text, flags, tables, and scrolling support. |
| `ui/bars/` | The map heads-up display and view controls. |
| `ui/information/` | Hover feedback, tooltips, and unit information popups. |
| `map_tools/` | Offline map creation, repair, and validation. |
| `scripts/` | Offline content editors, maintenance, dependency downloads, benchmarks, and previews. |
| `tests/` | Functional tests, regression tests, and shared test support. |
| `documentation/` | Maintained guides and design notes. |

The folders identify owners. Some existing rules still call presentation helpers.
Turn coordination still connects AI, resolution, and presentation refreshes.
Moving those files does not change execution order or permissions.

## Where to make a change

| Task | Start here |
| --- | --- |
| Ask a shared question about current state | `data/queries.py` |
| Change unit, building, or research tuning | `data/json/`, `data/generators/recipes.py`, and shared constants |
| Change world or participant state ownership | `data/game_state.py` and `data/session_state.py` |
| Change production validation, payment, or refunds | `map_logic/actions/production_actions.py` |
| Change unit-order validation, payment, or cancellation | `map_logic/actions/unit_actions.py` |
| Validate a player command independently of its transport | `map_logic/actions/player_actions.py` |
| Change territory ownership or cores | `map_logic/territory/ownership.py` |
| Change turn sequencing | `map_logic/turn_processing/turn_processor.py` and `turn_manager.py` |
| Change map buttons or map input | `screens/game/map.py` and `map_input.py` |
| Change initial country or tactical-unit selection | `screens/setup/player_setup.py` |
| Change country-edit controls | `screens/editors/edit_country.py` |
| Change map drawing or display caches | `ui/rendering/` |
| Change map panels or progress drawing | `ui/panels/` |
| Change tournament file exchange | `data/multiplayer/tournament/files.py` |
| Change real-time authority or snapshots | `data/multiplayer/realtime/session.py` |
| Change real-time transport or relay provisioning | `data/multiplayer/realtime/networking.py` and `relay.py` |
| Change the fresh-game tutorial | `ui/dialogs/message_box.py` |
| Check source packaging and dynamic imports | `compilation_scripts/build_manifest.py` and `tests/test_build_manifest.py` |

`data/queries.py` remains one module at its existing path.
Its shared rule helpers, caches, and save-dictionary builder remain there.
The source reorganization changes its import references only.

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
6. Open a standalone editor with `python scripts/editors/country_editor.py` or `unit_editor.py`.
7. Run sandbox tests with `python -m unittest tests.test_mod_loader_security`.

The previous benchmark, dependency-download, preview, and sandbox-test commands remain available as launchers.
Runtime modules use their current import paths directly.
Source-replacement mods must use the current target paths and imports.
The save format, settings keys, content paths, and game version remain unchanged.

Test files keep their existing module names for focused commands.
The sandbox cases also run during normal test discovery.
Builds do not include offline tools from `scripts/`.
