# Greater Diplomacy 5 Agent Guide (READ EVERYTHING DO NOT SKIM JUST A FEW LINES)

This file gives the rules for AI-assisted changes in this repository.
AI means artificial intelligence. UI means user interface.

## Before Editing

1. Read the relevant code and tests.
   Find every reader, writer, serializer, label, and duplicate implementation of the affected behavior.
   Do not assume the first match is the only caller.
2. Check `git status`.
   Preserve unrelated user changes. Do not discard work to get a clean tree.
3. Read the relevant design notes:
   - `documentation/non_llm_ai.txt`: rule-based AI and shared combat rules.
   - `documentation/ai_movement.txt`: AI unit orders, movement caches, aircraft missions, and movement tuning.
   - `documentation/llm_ai.txt`: large language models (LLMs), prompts, budgets, cancellation, and fairness.
   - `documentation/diplo_stuff.txt`: diplomacy, messages, guarantees, volunteers, attach?s, factions, war, and peace.
   - `data/migrations/MIGRATIONS.md`: required before changing saved fields, stored identifiers, settings keys, or library content that older saves and moves can contain.
4. Find the shared rule or data owner.
   Extend that implementation and make callers use it.

## Required Rules

- Keep `map_logic/system32/` as the turn-processing package.
  The name `system32` is intentional.
  Do not rename it during cleanup or refactoring.
  Rename it only when the user explicitly requests a different name.
- **Keep construction turns, enabled families, unit ranges, and building stats in the one Edit Unit / Building Stats screen. Do not split them into separate screens unless the user asks.**
  This Scenario Settings button opens `screens/editors/unit_stats_editor.py`.
- **Never change the values of units or buildings under any circumstances unless the user explicitly asks for that change.**
  This covers every unit and building value in [Tuning Data](#tuning-data), such as costs, income, stats, production times, ranges, and research years.
  It applies to `data/json/unit_data.json`, `data/json/building_data.json`, `data/generators/recipes.py`, and the unit and building constants in `data/constants.py`.
  Do not change these values to make a test pass, to balance gameplay, or as part of a refactor or another feature.
  This rule covers the game's source data. It does not stop editors from letting players change values in their own scenarios.
- Do not run tests unless absolutely nessecary.
- Never reference Git-ignored files or directories in tests.
- Never generate an image under any circumstances without explicit user approval.
- **Never stage changes, commit to `main` or make another branch without explicit user approval.**
- **Never use `git stash`, `git checkout`, `git reset`, `git restore`, or `git clean` to change the working tree.**
  Do not use them to compare against a baseline or to test a clean state.
  If the command is interrupted, the user's work can stay hidden or be lost.
  To compare with an older version, export it to a separate directory with `git archive`.
  Run the comparison in that directory and leave the working tree unchanged.
- **NEVER edit `version.txt`. Do not change, reformat, or rewrite it for any reason.**
  The game downloads this file from the public repository and compares it with its own version.
  Players see "Outdated" when it is newer than their copy.
  If it changes before a release exists, every player wrongly sees that an update is available.
  Only the user changes `version.txt`, when they release.
  Change `GAME_VERSION` in `data/constants.py` for development work. Report that you did not touch `version.txt`.
- Use `color`, never `colour`, in identifiers, UI text, comments, and documentation.
- Preserve intentional comments.
  Update inaccurate comments. Keep explanations of rules that are not obvious.
- **Report every change that the user did not explicitly request.**
  This includes obvious bug fixes, improvements, cleanups, version numbers, and changes to other files.
  For each change, say exactly what you changed and why, as well as if you think it was an obvious change to make or not.
  Give this report in the same handoff as the change. Do not wait until the user asks.
- Do not change gameplay during a refactor.
  A behavior change needs a user request, an obvious bug, or a clear explanation to the user.
- All repository image assets must be real PNG files with `.png` extensions.
  Check the file signature. Report mismatches and convert them when conversion is in scope.
- Do not treat generated directories as source.
  Normally exclude `web_stage/`, `dist/`, `build/`, `.eggs/`, `__pycache__/`, and `venv/` from searches and edits.
- Treat an exact repeat of the user's previous prompt as a mistake.
  You can ignore that repeated prompt.

## Repository Ownership

| Area | Responsibility |
| --- | --- |
| `data/constants.py` | Constants and tuning values shared across modules. |
| `data/queries/` | Shared state queries, rule helpers, caches, and the save-dictionary builder. One module per topic. |
| `data/migrations/` | All conversion of older GD5 data: identifiers, conversion rules, load repairs, and the snapshot move reader. One file per concern. |
| `data/game_state.py`, `data/session_state.py` | World data, participants, control permissions, and processing progress. |
| `data/runtime_rules.py`, `data/world_nations.py` | World-specific active libraries, derived indexes, and explicit country-mapping context. |
| `data/state_access.py` | Explicit state access, map compatibility properties, and backend execution context. |
| `map_logic/actions/production_actions.py` | Shared production validation, queue construction, charging, cancellation, and refunds. |
| `map_logic/actions/unit_actions.py` | Shared unit-order preparation, execution, replacement, payment, and cancellation. |
| `map_logic/actions/player_actions.py` | Shared multiplayer intent validation and application. |
| `map_logic/diplomacy/action_definitions.py`, `map_logic/diplomacy/faction_records.py` | Diplomatic categories, availability, and AI prompt wording; authoritative faction mutations and compatibility projections. |
| `map_logic/diplomacy/diplomacy_lifecycle.py` | Request identity, channel writes, timing transitions, and response references. |
| `data/json/` | Data libraries and AI response text used without an LLM. |
| `data/map/save_map.py`, `data/map/load_map.py` | Saves, loads, defaults, and migration calls. |
| `data/multiplayer/tournament/files.py` | Tournament files, player move export, host import, authentication, and filtering. |
| `data/multiplayer/realtime/session.py` | Real-time protocol, server commands, snapshots, and filtered client state. |
| `map_logic/system32/` | Turns, movement, economy, research, and combat. |
| `map_logic/diplomacy/` | Shared diplomacy rules, messages, effects, and state changes. |
| `map_logic/ai/` | Rule-based AI, legal candidates, valuation, LLM selection, and fallbacks. |
| `map_logic/imports/gd4_translation.py`, `map_logic/imports/gdhex_translation.py` | Save imports from other games into GD5. |
| `screens/` | Complete menu, game, and editor screens. Each screen builds its own buttons. |
| `ui/` | Shared widgets, panels, dialogs, bars, popups, and UI support. |
| `compilation_scripts/build_manifest.py`, `compilation_scripts/build_support.py` | Shared packaging inventory, platform policy, filtering, staging, and resets. |
| Other `compilation_scripts/` files | Platform packaging tools and native archive procedures. |
| `tests/` | Regression tests and rule checks. `run_tests.py` finds all `test_*.py` files. |

## Apply Changes to All Affected Systems

Start with the shared rule.
Complete this checklist before handoff. Update every affected system in the same change.
Execution, UI, AI, and documentation must agree across affected modes and state transitions.
Give a reason when a system does not apply.

| System | Check | Likely locations |
| --- | --- | --- |
| Core rules | Share legality, cost, effect, timing, and calculation logic across callers. | `data/queries/`, `map_logic/` |
| Turn processing | Check order resolution, turn changes, removed countries, wars, and factions. | `map_logic/system32/`, `map_logic/diplomacy/` |
| UI | Derive labels, previews, enabled controls, tooltips, popups, and numbers from execution rules. | `screens/`, `ui/` |
| AI | Generate, value, select, perform, and answer actions without an LLM. Limit LLM choices to legal candidates. | `map_logic/ai/`, `data/json/ai_responses.json` |
| Save/load | Write new state, use safe defaults, migrate old saves, and check a save/load round trip. | `data/queries/saves.py`, `data/map/save_map.py`, `data/map/load_map.py` |
| Tournament multiplayer | Authenticate and validate partial moves. Reject stale or duplicate input. Preserve shared changes and hidden information. | `data/multiplayer/tournament/files.py`, `tests/test_tournament_moves.py` |
| Real-time multiplayer | Let only the server apply commands. Validate permissions, filter snapshots, and protect private state. | `data/multiplayer/realtime/session.py`, real-time UI, `tests/test_realtime_multiplayer.py`, `tests/test_realtime_fog.py` |
| Other modes | Enforce permissions for single-player, hotseat, spectators, tactical players, AI, editors, tournament players/hosts, and real-time clients/hosts. | `screens/game/map.py`, affected screens, `data/queries/` |
| Content tools | Check scenario settings, map editing, scripted actions and conditions, and base data. | `screens/editors/`, scenario screens, map and scenario JSON |
| Builds | Include new modules, packages, data, dependencies, and dynamically imported screens. | Build files listed below |
| Documentation/tests | Add regression coverage for the rule and failure. Update affected guides. | `tests/`, `documentation/`, `README.md` |

### Multiplayer Rules

Check tournament and real-time multiplayer separately.
Success in one does not prove compatibility with the other.

- **Tournament mode uses files with partial state.**
  A move contains only changes authorized for its player.
  Shared changes require an explicit command that the host validates.
  Examples include faction names, subject appearance, diplomacy, and ownership.
  Do not apply these by replacing the submitting country's record.
  Preserve session and turn checks, duplicate detection, hidden-state filtering, and support for older files.
- **The real-time server owns game state.**
  Clients propose commands and can keep local display drafts.
  Only the server establishes game state.
  Before applying a command, validate identity, permissions, state, costs, targets, and timing.
  Snapshots must not reveal fogged or private data.
  Keep blocking network operations off the pygame event loop.
  Keep desktop-only networking separate from web code.
- For each new player action or editable field, decide how both systems handle it.
  Where applicable, test valid, unauthorized, malformed, and stale input.

## Code and Data Design

### Simplicity (KISS)

- Follow KISS (Keep It Simple, Stupid).
  Use the simplest solution that meets the request and existing rules.
  Add abstractions, state, queues, or fallback behavior only when the required behavior needs them.
- **Implement the action the user requested. Do not substitute a more elaborate behavior.**
  Stop, pause, resume, restart, clear, and delete have different meanings.
  A request to stop something and continue normal operation does not ask for preserving and restoring its previous state.
  Do not add snapshots, saved positions, restoration, or extra preferences unless the request or an existing rule requires them.

Example: An object spawns every five seconds.
If the screen is at its object cap, skip that spawn.
Do not queue skipped spawns for later.

Example 2: You are asked to extend research of a certain unit until the end of the timeline.
Do not create an entire system where if you enter in something like None it automates it for you.
Simply edit the number of levels the unit has and call that done.

Example 3: The user asks to stop battle music on exit and continue normal playlist playback.
Stop the battle track and use the existing playlist selection.
Do not save the previous song, playback position, or paused state and restore them afterward.

Example 4: The player's controlled unit is destroyed during a tactical battle.
End control and let the player spectate the rest of the battle.
Do not hand control to another unit, such as a surviving sub-unit of the same division.

### One Source of Truth

- **Keep `data/json/starting_defaults.json` as the one source of truth for preference and setup defaults.**
  Startup, missing-setting fallbacks, reset controls, and builds must read those values through `data/io/starting_defaults.py`.
  Existing constant names may expose values read from that file. Do not duplicate default values in Python, screen tables, or documentation.
  Keep saved player choices authoritative. Keep gameplay tuning and library content with their existing owners.
- Keep names, identifiers, data shapes, and shared workflows as consistent as possible.
  Standardize unit types across generation, gameplay, UI, AI, editors, and multiplayer.
  Unit type standardization takes priority over keeping older identifiers in current code.
- Add shared migrations when a change affects data from a previously released version.
  Keep compatibility conversion at input boundaries. Use only the standardized representation internally.
  Do not retain naming exceptions only to avoid writing a compatibility conversion.
- Keep level suffixes in canonical unit identifiers, including single-level families.
  Omit the suffix from player-facing unit labels when the family has only one level.
  Use a shared display helper. Keep identifiers intact in saved data and action callbacks.
- Match identifiers, data keys, constants, and documentation to player-facing names for the same thing.
  Keep required formatting differences, such as spaces and capitalization.
  Exception: unit metadata `family` and `settings_family` keep the names of older releases.
  Older saves and scenario settings use them. See `data/migrations/MIGRATIONS.md`, Older Family Names in Unit Metadata.
- Preserve older settings, saves, and protocol values through shared migration rules when names change.
- Test legacy loading and new-data round trips after a stored name changes.
- Check existing helpers before you add another function.
- Follow DRY (Don't Repeat Yourself).
  Combine duplicate calculations, variables, rules, functions, and state changes in one named helper.
  Use the same path for similar behavior unless a documented gameplay rule requires a difference.
- Remove unused functions and organize imports when those changes are in scope.
- Use shared legality, cost, effect, timing, and valuation helpers across execution, UI, AI, scripts, editors, and multiplayer.
  Do not copy damage, price, eligibility, acceptance, capacity, or timing formulas into callers.
- Put reusable questions about current state in the matching module of `data/queries/`.
  Put constants in `data/constants.py` only when modules share them.
- Group a screen's layout values near the top of that screen file.
  Use one anchor or gap value to move a UI group.
  Keep local layout constants out of `data/constants.py`.
- Use data tables instead of repeated condition chains when content is likely to grow.

### Imports

- Place imports at the top of the file by default.
- Keep local imports when initialization order, circular dependencies, platform compatibility, or optional dependencies require them.
- Explain non-obvious exceptions with a short comment near the import or its shared dependency boundary.
- Do not place an import inside a function merely because only that function uses it.
- Preserve mod startup order and headless execution when moving imports.
- Import the owning module when callbacks must resolve a replaceable helper at execution time.
- Keep test imports local when fixtures, environment settings, or mocks must be installed before importing the module.

### Tuning Data

Tuning data means current unit and building statistics, research settings, costs, and combat capabilities.
This includes research years, level counts, prerequisites, unlock lists, prices, production times, and resource output.
It also includes health, attack, defense, speed, range, damage bonuses, immunity, and fort damage capability.

Keep tuning data in its source files:

- `data/json/unit_data.json`, `data/json/building_data.json`, and `data/json/research_template.json`: current settings.
- `data/generators/recipes.py`: data generation.
- `data/constants.py`: shared tuning.
- Shared query and execution helpers: rules defined in code.

### Hardcoding and Fallbacks

- Do not hardcode content, tuning values, or repeated unexplained numbers in behavior code.
  Use JSON data, named local constants, shared constants, or query helpers.
- Store non-LLM diplomatic and AI text in `data/json/ai_responses.json`.
  Read it through `map_logic/ai/ai_prompts.py`.
  Do not embed it at call sites.
- Use direct attributes for required state.
  Broad `getattr(..., fallback)` use can hide renamed fields and incomplete initialization.
  Use `getattr` only at compatibility boundaries or for deliberately optional state.
  Examples include old saves, optional platform features, and lightweight test doubles.
  Explain the fallback when its purpose is not obvious.
- Catch expected errors narrowly.
  Do not turn programming errors into defaults with catch-all exception handlers.
  Give errors that explain how to correct the problem.

### Saves and Caches

- Preserve existing supported public interfaces, saved data, and configuration behavior.
  Change them only when the user explicitly requests a breaking change.
- The game version is the save version. `GAME_VERSION` in `data/constants.py` gives it.
  It names the version in development. Set it to the new version when work on that version starts.
  Then run `python scripts/data/write_released_content.py` to add the release to the list of released names.
  `version.txt` names the last released version. Never edit it (see Required Rules).
  Every save, tournament file, and move file records the version that wrote it.
  Do not add another version number, schema name, or numbered format.
  The stamp refuses files from a newer game and matches real-time players.
  It also asks a tournament host to approve a move from another version. It never selects conversion rules.
- **Never add version-numbered conversion steps or a chain of steps.**
  Do not write per-version files such as `v48.py`. Do not add step lists such as `SAVE_STEPS`.
  An older save must load and be playable in any later game. Exact older values are less important.
  A save from many releases ago must not need one step for each release since then.
- Put every conversion rule for older saves and moves in `data/migrations/conversions.py`.
  Every rule runs on every load, whatever version wrote the file.
  A rule finds an older shape in the data and converts it. It must do nothing to current data.
  See `data/migrations/MIGRATIONS.md`.
- **Never reuse a saved field or identifier with a new meaning.** Give the new meaning a new name.
  Or save the data that is necessary to read the older meaning, as `research_years` does.
  Otherwise no rule can tell older data from current data.
- A file from a newer version is refused with an error that tells the player to update.
- Prefer additive, optional fields with defaults that preserve old behavior.
  Add a conversion rule when a field changes meaning, moves, or changes shape.
  Keep existing field meanings stable.
- Adapt supported older data at the input boundary.
  Keep adaptation rules in one clear place and use one consistent representation internally.
- Base compatibility handling on actual supported formats and callers.
  Do not invent hypothetical legacy cases.
  To find out if a name or format was released, see `data/migrations/MIGRATIONS.md`, Released Names.
- Convert older saves with the conversion rules when they load. Gameplay, UI, and AI code read only the current format.
  Do not add read-time adapters for older save shapes.
- Do not remove existing compatibility mechanisms merely to simplify code.
  Move an adapter into `data/migrations/conversions.py` instead.
- Explain concrete compatibility conflicts before making a breaking change.
- Treat a new saved field as a data-format change.
  Define its owner, writer, loader, and old-save default.
  Test round trips and legacy loading.
- Put older GD5 data conversion rules and identifier aliases in the `data/migrations/` package.
  Call those helpers from loaders, importers, and other data boundaries.
  Keep save imports from other games in their separate translation modules.
  GD4 and Greater Diplomacy Hex Edition are separate games, not older GD5 versions.
  Keep current schema defaults, file access, and gameplay validation with their existing owners.
  Preserve migration order, saved references, unknown valid fields, and permission checks.
- Keep settings keys consistent across the schema, controller, readers, writers, defaults, and settings UI.
  Check settings defaults, saves, and loads after related changes.
- Keep game-specific UI preferences in each save, not in global settings.
  This includes conversation themes and country-specific display colors.
  Loading or starting another game must not inherit these preferences from an unrelated save.
  Use global settings only when the user explicitly requests a preference across all games.
- Preserve unknown or older valid data where possible.
  Migration must produce predictable results and be safe to run once on load.
- History snapshots convert only when a player selects that turn. A selected history turn becomes live game state.
  Do not convert every snapshot on load. migrate_infantry_research is the exception, because snapshots share research_years.
- The conversion rules convert tournament moves from every older release, as they convert saves.
  The host must approve a move whose stamp differs from the host's version. The converted move then passes all normal validation.
  Moves without `player_intents` are snapshot moves. `data/migrations/snapshot_moves.py` reads them. Do not add a reader for one version.
- Load repairs fix invalid current data on every load. Library conversions compare saved data with the active libraries on every load.
  Both are separate from the conversion rules for older formats.
  Examples are unit identities, army rosters, faction leaders, units of disabled families, and buildings missing from the active library.
  A unit whose type is not in the library stays. Thus each released unit name needs a conversion rule.
- Reuse caches instead of reading disk in frame or turn loops.
  Pass an explicit world context to active library queries. No-context library access reads shared default content.
  Change faction membership and leadership through faction services. Country faction fields are derived projections.
  Define when each cache fills and becomes invalid.
  Update shared cached dictionaries in place when screens retain references to them.
- **Planning-phase rendering must use cached presentation data.**
  During player planning, frame `draw` and `update` paths must not run rules, simulations, map-wide state calculations, or AI.
  Calculate those results at turn, state, or input changes.
  Cache the results.
  Invalidate them when source state, map layer, fog, camera parameters, or viewport changes.
  Frames can position and draw cached assets and handle input or active animations.
  They must not repeatedly derive static gameplay or map display data.
- Account for the web build's virtual filesystem and storage synchronization.
  This applies to saves, tournament files, imports, and user-created assets.

### UI Appearance

- **A button must never play two sound effects for one activation.**
  Count sounds played by the button, its callback, and any screen or popup it
  opens. Give that activation one sound owner. For example, a Help button that
  opens a popup with a help/info sound must not also play a click sound; set
  the calling button's `sound_kind=None` when the popup owns the sound.
  Closing the popup is a separate activation and can play its own single sound.
- **Changing appearance does not include changing layout.**
  When asked for a visual or appearance-only change, keep existing buttons,
  panels, cards, slots, scrollbars, and labels in their current positions and
  sizes. Preserve their order, alignment, spacing, and screen regions.
  Change colors, shading, borders, textures, and other styling in place.
  Do not move, reorder, resize, or rearrange controls unless the user explicitly
  requests a layout change. Referencing another screen's appearance does not
  authorize copying its layout.
- **Show only one copy of an item during click-and-drag.**
  While an item is being dragged, show it only under the pointer and hide its
  original rendering. Keep its source space reserved so the layout does not
  shift. Restore it when the drag is canceled or dropped outside a valid
  target; show it at its destination after a valid drop. Do not display both
  a stationary source item and a dragged copy, or duplicate game data to draw
  the drag. Copying requires an explicit user request.
- **A separate screen and a subscreen are different UI formats.**
  A **separate screen** replaces the current view and owns the full application
  canvas, background, layout, input, and navigation. Register it in the
  controller's screen states and use the normal screen transition and
  `on_enter` lifecycle. Back or Exit returns to the previous screen and restores
  its context. Do not leave the map or parent screen visible underneath it.
  A **subscreen** is a child panel, popup, dialog, modal, or overlay shown inside
  or over its parent screen. It uses the parent's view as its surroundings or
  background and closes to reveal that parent. `ModalScreen`, the modal stack,
  and `_run_pygame_sub_screen` implement subscreens, even when the panel is large.
  Putting a UI in a separate Python file or class does not make it a separate
  screen. When the user requests a separate screen, implement the first format;
  do not substitute a subscreen or modal.
- **Always reuse existing UI features and shared components instead of creating duplicate implementations.**
  Search for the existing implementation before adding UI. Extend it when the requested behavior needs more support.
  For example, reuse the existing loading-screen UI instead of making a new loading screen.
  Reuse its behavior as well as its appearance. Extend the shared implementation when needed.
- **Loading bars must report actual work through the shared progress UI.**
  Show known workloads as completed/total work (`#/#`) with a green fill.
  Determine the total from the operation's stages or work items before that work starts.
  Exception: when a workload depends on an earlier phase, show `Calculating...` with an empty, stationary bar until its actual queue is known.
  Exception: when a phase is disabled or has no work, show a full gray bar labeled `N/A`, rather than `0/0`.
  Keep phase bars visible in fixed positions, including an unused letter phase. Keep their numbered labels consecutive.
  Turning off the LLM makes model phases `N/A`; rule-based AI phases still show their actual progress unless those phases are also disabled or have no work.
  Advance the count and green fill only after a stage or item finishes successfully.
  Keep the fill still while work is running. Never animate, cycle, reset, or advance it with elapsed time.
  Count nested loading stages in the same total. Keep progress counting with the code that owns the work.
  Do not add a spinner, indeterminate bar, fake percentage, or alternate loading behavior unless the user explicitly requests it.
- **NEVER take up space just to fill the screen.**
  If a UI can work in a small area, keep it small.
  Do not enlarge controls, panels, or spacing to use empty screen space.
- **UI panels must always remain a constant size during gameplay.**
  Never force panels to resize when their content, selection, or game state changes.
- **Do not add UI help text, hints, or instructional placeholders unless the user explicitly requests them.**
  Do not add text merely because it might be helpful or fill empty space.
- When the user requests a gradient, interpolate directly between the specified start and end colors.
  Do not add intermediate color stops unless the user explicitly requests them.
  For animated gradients, interpolate directly between the current start and end colors at each animation step.
- Use the existing buttons, sliders, and scrollbars as the visual reference for new or changed UI.
- Use a pixel-art style with rectangular shapes, square corners, solid outlines, and raised or recessed bevels.
- Use stepped shade bands and small square dithering where space permits. Avoid smooth gradients and flat control backgrounds.
- Keep slider and scrollbar handles free of grip lines.
- Use the same content drag direction in every scrollable list, panel, menu, dialog, and editor.
  Dragging the content or its background down must move the content down and the scrollbar handle up.
  Dragging horizontal content right must move the content right and the scrollbar handle left.
  Reverse these directions when the player drags up or left.
  Preserve existing directions for mouse wheel scrolling and direct scrollbar dragging.
  Use the shared `Screen.handle_content_drag` and `Screen.handle_list_scroll` helpers in `ui/navigation/screen.py`.
- Keep color swatches flat so they show the selected color.
- Draw simple panels, bars, and control backgrounds in code. Reserve image assets for artwork, icons, portraits, and similar content.
- Keep `assets/backgrounds/Province.png` for the province menu unless the user requests its replacement.
- Reuse the shared shading and cached surfaces in `ui/widgets/ui_elements.py`.
- Preserve hover, pressed, selected, disabled, and permission states when changing appearance.
- Keep the moving checkerboard background's existing flat squares unless the user requests a change.

### UI and Permissions

- Country IDs are storage and protocol keys.
  Use `queries.get_country_display_name` in UI text, popups, headers, lists, and tables.
  Show an ID only with an explicit label or to distinguish duplicate names.
  Use `queries.country_picker_items` for pickers that return IDs.
- A visible control does not grant permission.
  Recheck ownership and permission where state changes.
- Prefer showing unavailable buttons as disabled instead of hiding them.
  Preserve explicit mode, visibility, and privacy rules.
- Tactical players command one division while the host country remains AI-controlled.
  Existing spectator flags control spectator editing.
  Check the actual modes and flags. Do not infer a mode from a related attribute.

### AI and Diplomacy

- **AI-controlled units on every side of a tactical battle must use the same decision rules.**
  Never give friendly or enemy units a unique combat behavior because of their side.
  Base tactical decisions on unit capabilities, health, position, support, threats, and the same temperament rules.
  Side identity selects allies, enemies, and deployment orientation; it must not select a different AI policy.
- Every action available to the rule-based AI must also be available to human players under the same game rules and conditions.
  Do not give AI exclusive actions or bypass human gameplay restrictions.
- **AI countries, rule-based and LLM, follow the same rules as human players, including diplomatic timing.**
  A message, letter, or proposal written in one turn is sent in the send phase after that turn.
  The receiver gets it in the next turn and can answer it only then. See `documentation/diplo_stuff.txt`, Message timing.
  An AI must not read, answer, or react to a message before it is delivered, and must not answer a message in the turn it was delivered.
  This includes later passes or phases of the same turn's processing.
- Keep rule-based AI authoritative when the LLM is enabled or disabled.
  Follow the legal-candidate restriction in the systems checklist.
- Preserve shared prompt prefixes, turn-budget cancellation, and fairness rules from `documentation/llm_ai.txt`.
- Test diplomacy in both directions and through delayed resolution.
  Preserve message timing, cancellation, crossing requests, and unilateral or bilateral behavior.

## Add Files, Assets, or Dependencies

- Add `__init__.py` when a new Python package requires it.
- Register new runtime material in `compilation_scripts/build_manifest.py`.
  Keep platform filtering and staging in `compilation_scripts/build_support.py`.
  The following entry points consume those shared declarations:
  - `compilation_scripts/html_compilation.py`
  - `compilation_scripts/windows_compilation.py`
  - `compilation_scripts/macos_compilation.py`
  - `compilation_scripts/setup.py`
- Run `tests/test_build_manifest.py` after adding runtime material.
  Source tests can pass even when a package omits a module.
- Update `requirements.txt` and platform packaging imports together for new third-party dependencies.
  Do not import desktop-only modules on web paths.

## Verification

Use verification appropriate to each change.

- Do not add tests that check only visual components.
  Check colors, fonts, icons, spacing, alignment, dimensions, overlap, and pixel appearance manually.
  Test callbacks, input, navigation, permissions, game rules, data, persistence, caches, and runtime errors.
  Include behavior reached through UI controls.
  Remove appearance assertions from mixed tests. Preserve their functional assertions.
- Treat editable UI and tutorial text as content.
  Check exact wording only for protocol values, identifiers, or a specific user requirement.
- Tests must not require real network services or an LLM unless marked as integration tests.
- Before you change how tests or scripts are imported or run, search `.github/workflows/` for commands that use them.

### Unit, Building, and Research Tests

- Test mechanics and data use without fixing current values from [Tuning Data](#tuning-data).
  Do not use current tuning as a hidden setup condition. A tuning change must not require unrelated test edits.
- Use explicit artificial fixtures for specific values, outcomes, relationships, prerequisites, unlocks, or capabilities.
  Set every relevant field and restore patched data after each test.
  Do not copy real stats into a fixture and assume that unchanged fields will meet the test conditions.
- Do not assume capabilities from unit names or incidental relationships between real units or families.
  Examples include equal costs or stats, fixed ratios, and one unit always being stronger or faster.
  Check each unit against its own data, or compare artificial fixtures.
  Test a fixed relationship only when a shared gameplay rule requires it. Identify that rule in the test.
- Derive gameplay test expectations from authoritative data, shared constants, or rule helpers.
  For real-content checks, derive setup and expectations from the same authoritative sources.
  Check schema, data propagation, and agreement between systems.
  Use current data only to check that callers read and apply it correctly.
  Preserve exact identifiers and migration rules when they define compatibility contracts.
- When tuning exposes an old assumption, rewrite the test around its intended rule.
  Check other tests for the same assumption, including tests that still pass.

### Tuning Independence

The user edits unit, building, and research data often.
A data edit must not make a test fail, unless the test checks that JSON matches `data/generators/recipes.py`.

- Do not assert a current stat, cost, year, level count, or prerequisite of real content.
- Do not assert that a real technology requires another real technology.
- Test a rule with an artificial fixture. Set every field that the rule reads.
- To check real content, read the expected value from the data, for example with `research_lock_cases`.
- Check every entry in a category. Do not name specific real units or technologies when a loop can select them.
- When a data edit makes a test fail, rewrite the test around its rule. Do not change the data to pass the test.
- Run `python scripts/checks/tuning_stress.py` after you add or change tests that read real content.

## Documentation

### Shared Information

- **Never document the positions of buttons or other UI elements.**
  This applies to guides and design notes. This does NOT apply to in-game help and tutorials.
  Identify controls by name and explain their behavior without screen coordinates, corners, or relative placement.
- Keep each shared explanation in one primary guide. Check existing guides before adding documentation.
- Use short references elsewhere. Keep local conditions, exceptions, permissions, and summaries needed to use each guide independently.
- Update documentation when a change makes an existing explanation incomplete or inaccurate, or adds behavior that users must understand.
  A code edit alone does not require a documentation addition.
- Update the existing topic in its primary guide. Do not append a new section for each development task.
- Document current rules and procedures. Keep development change reports and verification results in the handoff.
  Omit repeated statements that unaffected systems remain unchanged.

### Unit, Building, and Research Data

- Refer readers to the sources in [Tuning Data](#tuning-data) instead of duplicating current settings.
  This includes tables, examples, named-unit lists, and comparisons.
  Do not claim that unit or building families have equal stats, equal costs, or fixed strength relationships.
- Explain shared mechanics, data fields, source locations, and how the game reads current data.
  Preserve save formats, migration rules, permissions, and control instructions.
- Apply this rule to guides, design notes, examples, explanatory comments, docstrings, and tutorial text.
  The game can display current values and capabilities when it derives them from authoritative data or shared rules.

### Language

- Read and follow [Writing Style](documentation/writing_style.md) before writing or editing project text or replying about repository work.
  Keep the detailed writing rules in that guide.
- **Name what you refer to.** Do not use "it", "that", "this", "they", or "the model" when the reader could match it to more than one thing.
  Repeat the noun instead, such as "the rule-based AI" or "the LLM".
  This applies to UI text, documentation, comments, and replies.

### Tutorial and Maintenance

The fresh-game map tutorial is the Help window. Its text is in `data/json/tutorial.json`, and `ui/dialogs/message_box.py` draws it.
See `documentation/general_info.txt`, HELP CONTENT.
Treat it as player documentation.
Update it when map navigation, unit selection, orders, or covered map controls change.
Add or update tests for changed tutorial behavior.

Update documentation, comments, examples, tests, schemas, and UI text when the implementation makes them incomplete or inaccurate.
Check guides that refer to each changed rule. Keep their local instructions and references accurate.
See `documentation/general_info.txt` for the guide index.
Update every description or preview of changed player behavior.

### Handoff

State the behavior change and verification results.
For changes to persisted data or library content, state whether a migration is needed and why.
Name the conversion or old-data default and the affected save, selected-history, and tournament-move paths.
Name the tests and builds that ran and those that did not.
Link relevant files and name remaining risks or unverified platforms.
Give a small example when it helps explain a change.
Do not dump whole files or give a generic change log.
