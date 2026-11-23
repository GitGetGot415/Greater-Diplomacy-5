# Greater Diplomacy 5 Agent Guide

Read this entire file from disk and confirm to the user that you read it before making any edits. Answer questions without editing until the user explicitly asks for changes.

## Before Editing

1. Check `git status` and preserve unrelated work. Read the relevant code, tests, and [design notes](#design-notes). Find the readers, writers, serializers, labels, and duplicate implementations for the affected behavior.
2. **Find the closest existing feature and the code that owns its shared rule.** Follow the sibling's calculation, validation, turn timing, storage, display and rounding, AI use, and multiplayer handling wherever they apply. Ask before choosing a different pattern. For repo guidance or tooling, name the relevant convention or existing tool.
3. **Use the shared path for every affected caller.** The owner calculates the complete result. Execution, previews, UI, AI, scripts, editors, and multiplayer consume it directly. Keep names, identifiers, and data shapes consistent across those paths. Convert older supported data at the input boundary. Moving affected callers onto their sibling's shared path is a supporting edit. Report affected behavior that diverges from its sibling and propose the standard behavior even if a test currently expects the difference.
4. **Make the simplest change that implements the requested behavior.** Reuse existing helpers and state. Add a helper, abstraction, fallback, queue, setting, or state only when a requirement needs it. Stop, pause, resume, restart, clear, and delete describe distinct actions. Ask before including adjacent fixes or cleanup. Preserve unrelated gameplay, public interfaces, controls, labels, and the unit and scope of displayed values.
5. **Before the first edit, tell the user which existing feature and shared code you will use.** Give one concrete sentence naming the sibling, owner, and how the change uses the shared path. If there is no applicable sibling or shared owner, say so and name the closest pattern you found or where the rule belongs. For example, “I’ll follow fuel conversion and add the charge in `calculate_all_economies` so the preview, AI, and turn processing use the same result.”

### Design Notes

- Read [diplomatic message timing and cancellation](documentation/diplo_stuff.md) for changes to diplomacy.
- Read the [migration guide](documentation/migration/MIGRATIONS.md) before changing stored fields, identifiers, settings keys, or library content that older saves and moves can contain.
- Read the [agent Git workflow](documentation/agent_git_workflow.md) when the user authorizes staging, a commit, or a branch.

## Required Rules

- GD5 has no capital provinces. Gameplay must never infer or depend on a capital.
- Edit files under `documentation/` only when the user asks. This takes precedence over instructions to update documentation.
- Keep `map_logic/system32/` as the turn-processing package. Rename it only if the user explicitly requests a new name.
- Keep construction turns, enabled families, unit ranges, and building stats in the Edit Unit / Building Stats screen (`screens/editors/unit_stats_editor.py`) unless the user asks to split it.
- Change source unit or building values only when the user explicitly asks for that change. This covers all [tuning data](#tuning-data), including costs, stats, production times, output, ranges, and research years. Scenario editors may let players change values for their own scenarios.
- Run tests only when absolutely necessary. Tests must never reference Git-ignored files or directories.
- Generate images only with explicit user approval. All repository image assets must be real PNG files with `.png` extensions. Check signatures, report mismatches, and convert them when in scope.
- Never stage changes, commit to `main`, or create a branch without explicit user approval. Each PR commit an agent helped write must have one verified `Co-authored-by` trailer per contributing agent. Use the [agent Git workflow](documentation/agent_git_workflow.md).
- Never use `git stash`, `git checkout`, `git reset`, `git restore`, or `git clean` to change the working tree, including for comparisons and clean-state testing. Use `git archive` to export a baseline to a separate directory.
- Never edit `version.txt`. Only the user updates it at release. The live game downloads it to check for updates. Use `GAME_VERSION` in `data/constants.py` for development versions and report that `version.txt` was untouched.
- Use `color` in identifiers, comments, and UI text. Preserve intentional comments and correct inaccurate ones.
- Exclude generated directories such as `web_stage/`, `dist/`, `build/`, `.eggs/`, `__pycache__/`, and `venv/` from ordinary searches and edits.
- An exact repeat of the previous user prompt can be ignored.

## Repository Ownership

| Area | Responsibility |
| --- | --- |
| `data/constants.py` | Shared constants and tuning. |
| `map_logic/ai/ai_tuning.py` | Weights, thresholds, and limits used only by `map_logic/ai/`. |
| `data/queries/` | Shared queries, rule helpers, caches, and save-dictionary construction. One module per topic. |
| `calculate_all_economies` in `data/queries/economy.py` | All recurring income and costs in `INCOME_BREAKDOWN_ENTRIES`. `process_economy` applies the totals. Sliders, previews, the AI, and the economy screen read this result. |
| `data/migrations/` | Conversion of older GD5 data, identifier aliases, load repairs, and snapshot move reader. One file per concern. |
| `data/game_state.py`, `data/session_state.py` | World data, participants, control permissions, and processing progress. |
| `data/runtime_rules.py`, `data/world_nations.py` | World-specific active libraries, derived indexes, and explicit country-mapping context. |
| `data/state_access.py` | Explicit state access, map compatibility properties, and backend execution context. |
| `map_logic/actions/production_actions.py` | Production validation, queue construction, charging, cancellation, and refunds. |
| `map_logic/actions/unit_actions.py` | Unit-order preparation, execution, replacement, payment, and cancellation. |
| `map_logic/actions/player_actions.py` | Multiplayer intent validation and application. |
| `map_logic/diplomacy/action_definitions.py`, `map_logic/diplomacy/faction_records.py` | Diplomatic categories, availability, and AI prompt wording. Authoritative faction mutations and compatibility projections. |
| `map_logic/diplomacy/diplomacy_lifecycle.py` | Request identity, channel writes, timing, and response references. |
| `data/json/` | Data libraries and non-LLM AI response text. |
| `data/map/save_map.py`, `data/map/load_map.py` | Save/load, defaults, and migration calls. |
| `data/multiplayer/tournament/files.py` | Tournament files, move export and import, authentication, and filtering. |
| `data/multiplayer/realtime/session.py` | Real-time protocol, commands, snapshots, and filtered client state. |
| `map_logic/system32/` | Turn processing, movement, economy, research, and combat. |
| `map_logic/diplomacy/` | Diplomacy rules, messages, effects, and state changes. |
| `map_logic/ai/` | Rule-based AI, legal candidates, valuation, LLM selection, and fallbacks. |
| `map_logic/imports/gd4_translation.py`, `map_logic/imports/gdhex_translation.py` | Save imports from GD4 and Greater Diplomacy Hex Edition. |
| `screens/`, `ui/` | Screens build their own buttons. Shared widgets, panels, dialogs, bars, popups, and support belong in `ui/`. |
| `compilation_scripts/build_manifest.py`, `compilation_scripts/build_support.py` | Shared packaging inventory, platform policy, filtering, staging, and resets. Other compilation scripts handle platform entry points and native archives. |
| `tests/` | Regression and rule checks. `run_tests.py` discovers `test_*.py`. |

## Apply Changes to All Affected Systems

Check each row against the requested behavior and give a reason when a system does not apply. Use the same legality, cost, effect, timing, and valuation rules across affected modes and state transitions.

| System | Check |
| --- | --- |
| Core rules | Shared calculations and validation in `data/queries/` and `map_logic/`. |
| Turn processing | Order resolution, turn changes, removed countries, wars, and factions. |
| UI | Labels, previews, enabled controls, tooltips, popups, and numbers agree with execution. |
| AI | Rule-based AI can generate, value, select, perform, and answer actions. The LLM selects only legal candidates. |
| Save/load | Owner, writer, loader, old-data defaults, migration, and round trip. |
| Tournament multiplayer | Validate partial moves, reject stale or duplicate input, and preserve shared changes and hidden information. See `tests/test_tournament_moves.py`. |
| Real-time multiplayer | Server authority, permissions, filtered snapshots, and private state. See `tests/test_realtime_multiplayer.py` and `tests/test_realtime_fog.py`. |
| Other modes | Permissions for single-player, hotseat, spectators, tactical players, AI, editors, tournament players and hosts, and real-time clients and hosts. |
| Content tools | Scenario settings, map editing, scripted actions and conditions, and base data. |
| Builds | Inventory of new modules, packages, data, dependencies, and dynamically imported screens. |
| Tests | Regression coverage for the affected rule and failure. |

### Multiplayer Rules

- Check tournament and real-time separately for each new player action or editable field. Where applicable, test valid, unauthorized, malformed, and stale input.
- Tournament moves contain only authorized partial state. Shared changes such as faction names, subject appearance, diplomacy, and ownership require an explicit host-validated command. Never replace a submitting country's record to apply shared changes. Preserve session and turn checks, duplicate detection, filtering, and support for older files.
- The real-time server owns the state. Clients propose commands and may keep local display drafts. Before applying commands, validate identity, permissions, state, costs, targets, and timing. Snapshots must protect fogged and private data. Keep blocking networking off the pygame event loop and desktop-only networking off web code paths.

## Code and Data Design

### Simplicity (KISS)

- Preserve how the feature works unless the user requests a behavior change. When the screen is at its object cap, skip the spawn. When research needs more levels, change the level count with approval. On battle music exit, stop the track and use the existing playlist selection. If the controlled tactical unit is destroyed, end control and let the player spectate.
- Prefer keeping a command, statement, or data-table entry on one line. Avoid splitting it merely to meet a line-length preference.

### One Source of Truth

- `data/json/starting_defaults.json` owns preference and setup defaults. Startup, missing-setting fallbacks, reset controls, and builds read them through `data/io/starting_defaults.py`. Constants may expose these defaults. Saved choices take precedence. Keep tuning and content with their existing owners.
- Standardize unit types across generation, gameplay, UI, AI, editors, and multiplayer. Keep old identifiers at the input boundary. Canonical identifiers keep level suffixes, including single-level families. Omit the suffix on player-facing labels for single-level families using the shared display helper. Use canonical IDs in saves and callbacks.
- Match identifiers, keys, and constants to player-facing names, allowing formatting differences. Unit metadata `family` and `settings_family` keep older names used by saves and scenarios. Preserve older settings, saves, and protocol values through migrations and test legacy loading and new-data round trips when stored names change.
- Keep shared calculations, rules, and state changes with one owner. Use its helpers for legality, cost, effect, timing, valuation, damage, price, eligibility, acceptance, and capacity. Remove unused functions and organize imports when in scope.
- Put reusable state queries in the matching `data/queries/` module and constants in `data/constants.py` only when shared. Group a screen's layout values near the top of its file and move related controls with one anchor or gap. Prefer data tables for growing content.

### Imports

- Use top-level imports. Keep local imports for initialization order, circular dependencies, platform support, optional dependencies, or test fixtures and mocks that must run before import. Explain non-obvious exceptions. Preserve mod startup order and headless execution.
- Import the owning module when a callback has to resolve a replaceable helper at execution time.

### Tuning Data

Tuning includes stats, costs, production times, outputs, capabilities, research years, levels, prerequisites, and unlocks. Keep settings in `data/json/unit_data.json`, `data/json/building_data.json`, and `data/json/research_template.json`, generation in `data/generators/recipes.py`, shared tuning in `data/constants.py`, and coded rules in shared query and execution helpers.

### Hardcoding and Fallbacks

- Use data, named constants, and queries for content, tuning, or repeated numbers. Put non-LLM diplomatic and AI text in `data/json/ai_responses.json` and read it through `map_logic/ai/ai_prompts.py`.
- Access required state directly. Use `getattr` with a fallback only for compatibility or intentionally optional state, such as platform features or lightweight test doubles. Explain non-obvious fallbacks.
- Catch expected errors narrowly and explain how to correct them. Let programming errors surface.

### Saves and Caches

- `GAME_VERSION` is the save, tournament, and move stamp. Set it when development on a new version starts and run `python scripts/data/write_released_content.py` to add the release to the released names. The stamp rejects newer files with an update message, matches real-time players, and requires host approval for a tournament move with a different stamp. Conversion does not depend on the stamp. Use no additional version, schema name, or numbered format.
- Use `data/migrations/conversions.py` for every conversion of older GD5 saves and moves. Detect old shapes and leave current data alone. Each rule runs on load regardless of version. Use no version-numbered files or conversion chains. Convert at input boundaries, including loaders and importers. Use only the current representation internally. Preserve supported legacy formats and move existing legacy readers into migrations when needed. Keep GD4 and Greater Diplomacy Hex Edition in their separate translators.
- Keep identifiers and saved fields stable. For a new meaning, use a new name or preserve enough data to interpret the old meaning, as with `research_years`. Prefer additive optional fields with old-behavior defaults. For a new stored field identify the owner, writer, loader, and old-save default. Convert moved or reshaped fields and check legacy loads and round trips. Base compatibility on supported formats. Explain conflicts before breaking compatibility and require explicit approval for a break.
- Keep current defaults, file access, and gameplay validation with their owners. Preserve migration order, saved references, unknown valid fields, and permission checks. Keep conversions predictable and safe to run on load.
- Convert history snapshots when selected as live state. `migrate_infantry_research` runs across snapshots because they share `research_years`. Convert tournament moves from all older releases and apply normal validation after the host approves a different stamp. `data/migrations/snapshot_moves.py` reads moves without `player_intents`.
- Load repairs fix invalid current data on every load. Library conversions compare saves with active libraries on every load. Both are separate from legacy format conversion. Check unit identity, army rosters, faction leadership, disabled families, and buildings missing from the library. Unknown unit types remain in the save, so released names need conversion rules.
- Keep settings keys aligned across schema, controller, readers, writers, defaults, and UI. Check defaults, saves, and loads for related changes. Keep game-specific UI preferences, including conversation themes and country display colors, in the game save. Global settings require a preference that the user explicitly wants across games.
- Reuse caches instead of reading disk in frame or turn loops. Pass explicit world context to active library queries. Queries without context read shared defaults. Change faction membership and leadership through faction services. Country faction fields are derived projections. Define cache fill and invalidation events and update retained shared dictionaries in place.
- Planning-phase frames position and draw cached presentation assets, handle input, and run active animations. Calculate rules, simulations, map-wide state, static display data, and AI when relevant turn, state, or input changes occur. Invalidate presentation caches for source state, layer, fog, camera, and viewport changes.
- Account for web virtual filesystem and storage synchronization for saves, tournament files, imports, and user assets.

### UI Appearance

- One sound per button activation. Count the button, callback, and screen or popup. Use `sound_kind=None` on the calling button when a popup owns the sound. Closing the popup is a separate activation.
- Appearance-only work preserves control sizes, positions, order, alignment, spacing, and screen regions. Change styling in place. Layout changes require an explicit request.
- Show a dragged item only under the pointer, render it from its existing data, and reserve its source space. Restore it on cancel or invalid drop. Show it at the destination after a valid drop. Copying requires an explicit request.
- A separate screen owns the full canvas, background, layout, input, and navigation. Hide the parent, register controller state, use the normal transition and `on_enter`, and restore parent context on Back or Exit. `ModalScreen`, the modal stack, and `_run_pygame_sub_screen` implement subscreens inside or over a parent.
- Reuse shared UI behavior and components, including the loading screen. Keep panels a constant size during gameplay and use only the space the UI needs. Keep labels short, reuse existing wording, and include only necessary feature text. Help text, hints, and instructional placeholders require an explicit request.
- Use the shared progress UI for loading. Determine the real workload before starting and show completed/total (`#/#`) in green, counting each stage or item only on success, including nested work. Keep a full gray `N/A` bar for disabled or empty phases and an empty stationary `Calculating...` bar while an earlier phase determines the queue. Keep bars in fixed positions, including unused letter phases, and numbered labels consecutive. With LLM off, model phases show `N/A` and enabled rule-based phases show their real workload. The work owner counts progress. Fill stays still while work runs. Spinners, indeterminate or animated fills, fake percentages, and alternate loading behavior require an explicit request.
- Use existing controls as visual references. Use pixel-art rectangles, square corners, solid outlines, raised or recessed bevels, stepped shade bands, and small square dithering where space permits. Avoid smooth gradients and flat control backgrounds. Keep slider and scrollbar handles free of grip lines. For requested gradients, interpolate directly between specified colors, including each step of an animated gradient. Extra stops require explicit instruction.
- Keep the content drag direction consistent. Dragging content or its background down moves content down and the handle up. Dragging right moves content right and the handle left. Reverse for up or left. Preserve wheel and direct scrollbar directions. Reuse `Screen.handle_content_drag` and `Screen.handle_list_scroll` in `ui/navigation/screen.py`.
- Keep color swatches flat. Draw simple panels, bars, and control backgrounds in code, and reserve images for artwork, icons, portraits, and similar content. Reuse shared shading and cached surfaces in `ui/widgets/ui_elements.py`. Preserve hover, pressed, selected, disabled, and permission states. Keep `assets/backgrounds/Province.png` and the moving checkerboard's flat squares unless the user asks to change them.

### UI and Permissions

- Country IDs are storage and protocol keys. Use `queries.get_country_display_name` in UI and `queries.country_picker_items` for pickers returning IDs. Show IDs only with an explicit label or to distinguish duplicate names.
- Check ownership and permissions where state changes. Prefer disabling unavailable controls unless visibility, mode, or privacy rules require otherwise.
- Tactical players command one division while the host country remains AI-controlled. Use actual mode and spectator flags to determine editing permissions.

### AI and Diplomacy

- AI-controlled tactical units on all sides share decision rules and temperaments. Use capabilities, health, position, support, and threats. Side identity determines allies, enemies, and deployment orientation.
- Rule-based and LLM AI countries follow human gameplay rules, including diplomatic timing. A message, letter, or proposal goes out in the send phase after the turn in which it was written and arrives in the next turn. AI may read and react once the message arrives and reply after the delivery turn. Apply those limits in every processing phase. Preserve [diplomatic timing and cancellation](documentation/diplo_stuff.md).
- Keep rule-based AI authoritative with or without the LLM. Preserve legal candidate selection, shared prompt prefixes, turn-budget cancellation, and fairness.
- Check diplomacy in both directions and through delayed resolution. Preserve message timing, cancellation, crossing requests, and unilateral and bilateral behavior.

## Add Files, Assets, or Dependencies

- Add `__init__.py` when a Python package needs it. Register runtime material in `compilation_scripts/build_manifest.py` and keep filtering and staging in `compilation_scripts/build_support.py`. The shared entry points are `html_compilation.py`, `windows_compilation.py`, `macos_compilation.py`, and `setup.py` in `compilation_scripts/`.
- Run `tests/test_build_manifest.py` after adding runtime material. Update `requirements.txt` and platform packaging imports together when adding third-party dependencies. Keep desktop-only imports off web paths.

## Verification

- Review the diff before handoff. Verify the affected callers use the named shared owner and canonical names and data shapes. Verify compatibility conversion occurs at input boundaries. Tie every edit to the request or a necessary supporting change, including each calculation, UI string, helper, field, fallback, and branch. Remove additions that lack a requirement.
- Verify appearance manually, including colors, fonts, icons, layout, dimensions, overlap, and pixel appearance. Tests cover behavior such as callbacks, input, navigation, permissions, rules, data, persistence, caches, and runtime errors, including paths through UI controls. Remove visual assertions from mixed tests and keep functional assertions.
- Check exact UI and tutorial wording only when required for protocol values, identifiers, or an explicit user requirement. Tests that need real network services or an LLM must be marked as integration tests. Search `.github/workflows/` before changing how tests or scripts run or import.

### Unit, Building, and Research Tests

- Tests must tolerate tuning edits, except when comparing generated JSON with `data/generators/recipes.py`. For specific outcomes or relationships, use artificial fixtures and set every relevant field. Restore patched data after each test. Avoid inheriting hidden assumptions from real content.
- For real-content checks, derive setup and expectations from authoritative data, constants, or shared helpers, such as `research_lock_cases`. Check schema, propagation, and agreement across systems. Loop through all entries in a category when possible. Preserve exact identifiers and migration rules that define compatibility.
- Never assume fixed stats, costs, years, level counts, prerequisites, capabilities, or relationships based on real unit names or current tuning. Assert fixed relationships only when required by a shared gameplay rule and identify that rule in the test. When a tuning change exposes an assumption, fix the test around the rule it covers and check other tests for the same assumption.
- Run `python scripts/checks/tuning_stress.py` after adding or changing tests that read real content or `data/constants.py` values. The `constants` variant changes these values in memory.

## Project Text

- Point readers to [tuning data](#tuning-data) instead of copying current values or claiming fixed relationships in examples, comments, docstrings, tutorial text, or prose. Explain shared mechanics, fields, sources, and data use. The game can display current values from authoritative data or rules. Preserve save formats, migrations, permissions, and controls.
- Name the thing you mean when a pronoun could refer to more than one, such as the rule-based AI or the LLM. Apply this to UI, comments, and replies.
- The fresh-game map tutorial is the Help window. Its content is in `data/json/tutorial.json` and `ui/dialogs/message_box.py` draws it. Update the tutorial and its behavior tests when covered map navigation, unit selection, orders, or controls change.
- Update affected comments, examples, tests, schemas, UI text, and every description or preview of changed behavior. Follow the restriction on edits under `documentation/`.

### Handoff

State the behavior change, verification, required supporting edits, and any separately approved changes. For persisted data or library content, explain whether a migration is needed and why. Name the conversion or default and the affected save, selected-history, and tournament-move paths. Name tests and builds run or skipped. Link relevant files and identify remaining risks or unverified platforms. Include a small example when it clarifies the change.
