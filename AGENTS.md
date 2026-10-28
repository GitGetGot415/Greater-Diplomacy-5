# Greater Diplomacy 5 Agent Guide

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
   - `documentation/player_controls.txt`: player controls, tactical play, spectators, editors, reports, and map display.
   - `documentation/ai_movement.txt`: AI unit orders, movement caches, aircraft missions, and movement tuning.
   - `documentation/llm_ai.txt`: large language models (LLMs), prompts, budgets, cancellation, and fairness.
   - `documentation/diplo_stuff.txt`: diplomacy, messages, guarantees, volunteers, attach?s, factions, war, and peace.
4. Find the shared rule or data owner.
   Extend that implementation and make callers use it.

## Required Rules

- Keep `map_logic/system32/` as the turn-processing package.
  The name `system32` is intentional.
  Do not rename it during cleanup or refactoring.
  Rename it only when the user explicitly requests a different name.
- **Never stage changes, commit to `main` or make another branch without explicit user approval.**
- Use `color`, never `colour`, in identifiers, UI text, comments, and documentation.
- Preserve intentional comments.
  Update inaccurate comments. Keep explanations of rules that are not obvious.
- **Report every change that the user did not explicitly request.**
  This includes obvious bug fixes, improvements, cleanups, version numbers, and changes to other files.
  For each change, say exactly what you changed and why.
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
| `data/queries.py` | Shared state queries, rule helpers, caches, and the save-dictionary builder. |
| `data/migrations.py` | Older GD5 identifiers, saved-data conversions, and load repairs. |
| `data/game_state.py`, `data/session_state.py` | World data, participants, control permissions, and processing progress. |
| `data/runtime_rules.py`, `data/world_nations.py` | World-specific active libraries, derived indexes, and explicit country-mapping context. |
| `data/state_access.py` | Explicit state access, map compatibility properties, and backend execution context. |
| `map_logic/production_actions.py` | Shared production validation, queue construction, charging, cancellation, and refunds. |
| `map_logic/unit_actions.py` | Shared unit-order preparation, execution, replacement, payment, and cancellation. |
| `map_logic/player_actions.py` | Shared multiplayer intent validation and application, plus the validated older projection adapter. |
| `map_logic/diplomacy/action_definitions.py`, `map_logic/diplomacy/faction_records.py` | Diplomatic categories and availability; authoritative faction mutations and compatibility projections. |
| `map_logic/diplomacy/diplomacy_lifecycle.py` | Request identity, channel writes, timing transitions, and response references. |
| `data/json/` | Data libraries and AI response text used without an LLM. |
| `data/map/save_map.py`, `data/map/load_map.py` | Saves, loads, defaults, and migration calls. |
| `data/io/multiplayer_io.py` | Tournament files, player move export, host import, authentication, and filtering. |
| `data/io/realtime_multiplayer.py` | Real-time protocol, server commands, snapshots, and filtered client state. |
| `map_logic/system32/` | Turns, movement, economy, research, and combat. |
| `map_logic/diplomacy/` | Shared diplomacy rules, messages, effects, and state changes. |
| `map_logic/ai/` | Rule-based AI, legal candidates, valuation, LLM selection, and fallbacks. |
| `map_logic/gd4_translation.py`, `map_logic/gdhex_translation.py` | Save imports from other games into GD5. |
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
| Core rules | Share legality, cost, effect, timing, and calculation logic across callers. | `data/queries.py`, `map_logic/` |
| Turn processing | Check order resolution, turn changes, removed countries, wars, and factions. | `map_logic/system32/`, `map_logic/diplomacy/` |
| UI | Derive labels, previews, enabled controls, tooltips, popups, and numbers from execution rules. | `screens/`, `ui/` |
| AI | Generate, value, select, perform, and answer actions without an LLM. Limit LLM choices to legal candidates. | `map_logic/ai/`, `data/json/ai_responses.json` |
| Save/load | Write new state, use safe defaults, migrate old saves, and check a save/load round trip. | `data/queries.py`, `data/map/save_map.py`, `data/map/load_map.py` |
| Tournament multiplayer | Authenticate and validate partial moves. Reject stale or duplicate input. Preserve shared changes and hidden information. | `data/io/multiplayer_io.py`, `tests/test_tournament_moves.py` |
| Real-time multiplayer | Let only the server apply commands. Validate permissions, filter snapshots, and protect private state. | `data/io/realtime_multiplayer.py`, real-time UI, `tests/test_realtime_multiplayer.py`, `tests/test_realtime_fog.py` |
| Other modes | Enforce permissions for single-player, hotseat, spectators, tactical players, AI, editors, tournament players/hosts, and real-time clients/hosts. | `screens/menu_screens/map.py`, affected screens, `data/queries.py` |
| Content tools | Check scenario settings, map editing, scripted actions and conditions, and base data. | `screens/editor_screens/`, scenario screens, map and scenario JSON |
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

Example: An object spawns every five seconds.
If the screen is at its object cap, skip that spawn.
Do not queue skipped spawns for later.

### One Source of Truth

- Match identifiers, data keys, constants, and documentation to player-facing names for the same thing.
  Keep required formatting differences, such as spaces and capitalization.
- Preserve older settings, saves, and protocol values through shared migration rules when names change.
- Test legacy loading and new-data round trips after a stored name changes.
- Check existing helpers before you add another function.
- Follow DRY (Don't Repeat Yourself).
  Combine duplicate calculations, variables, rules, functions, and state changes in one named helper.
  Use the same path for similar behavior unless a documented gameplay rule requires a difference.
- Remove unused functions and organize imports when those changes are in scope.
- Use shared legality, cost, effect, timing, and valuation helpers across execution, UI, AI, scripts, editors, and multiplayer.
  Do not copy damage, price, eligibility, acceptance, capacity, or timing formulas into callers.
- Put reusable questions about current state in `data/queries.py`.
  Put constants in `data/constants.py` only when modules share them.
- Group a screen's layout values near the top of that screen file.
  Use one anchor or gap value to move a UI group.
  Keep local layout constants out of `data/constants.py`.
- Use data tables instead of repeated condition chains when content is likely to grow.

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
- The game version is the save version. `version.txt` and `GAME_VERSION` in `data/constants.py` give it.
  Every save, tournament file, and move file records the version that wrote it.
  Do not add another version number, schema name, or numbered format.
- A version step converts all older data to the format of one game version.
  Put each step in `SAVE_STEPS` or `MOVE_STEPS` in `data/migrations.py`.
  Give the step the next release version, one above `GAME_VERSION`. Do not change `GAME_VERSION` or `version.txt`.
  See `documentation/data_migrations.txt` for the procedure.
- A file from a newer version is refused with an error that tells the player to update.
- Prefer additive, optional fields with defaults that preserve old behavior.
  Add a version step when a field changes meaning, moves, or changes shape.
  Keep existing field meanings stable.
- Adapt supported older data at the input boundary.
  Keep adaptation rules in one clear place and use one consistent representation internally.
- Base compatibility handling on actual supported formats and callers.
  Do not invent hypothetical legacy cases.
- Convert older saves in their version step. Gameplay, UI, and AI code read only the current format.
  Do not add read-time adapters for older save shapes.
- Do not remove existing compatibility mechanisms merely to simplify code.
  Move an adapter into a version step instead.
- Explain concrete compatibility conflicts before making a breaking change.
- Treat a new saved field as a data-format change.
  Define its owner, writer, loader, and old-save default.
  Test round trips and legacy loading.
- Put older GD5 data conversion rules and identifier aliases in `data/migrations.py`.
  Call those helpers from loaders, importers, and other data boundaries.
  Keep save imports from other games in their separate translation modules.
  GD4 and Greater Diplomacy Hex Edition are separate games, not older GD5 versions.
  Keep current schema defaults, file access, and gameplay validation with their existing owners.
  Preserve migration order, saved references, unknown valid fields, and permission checks.
- Keep settings keys consistent across the schema, controller, readers, writers, defaults, and settings UI.
  Check settings defaults, saves, and loads after related changes.
- Preserve unknown or older valid data where possible.
  Migration must produce predictable results and be safe to run once on load.
- A save step also converts every history snapshot. A selected history turn becomes live game state.
- Tournament move steps convert moves from the previous release only.
  The host must approve each converted move. The converted move then passes all normal validation.
- Load repairs are not version steps. They run on every load and fix invalid current data.
  Examples are unit identities, army rosters, faction leaders, and units or buildings missing from the active library.
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
- Follow the display defaults, tactical rendering, and unit-box selection rules in `documentation/player_controls.txt`.

### AI and Diplomacy

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

1. Add or update focused regression tests for the rule and actual failure.
   Keep useful tests. Rewrite them around the required behavior when necessary.
   Do not delete useful coverage or weaken assertions only to make a failing test pass.
2. Run focused tests during development.
   Example: `python -m unittest tests.test_tournament_moves`.
   Focused regression tests must pass before handoff.
3. Run `python run_tests.py` before handoff when feasible.
4. Complete the affected-systems checklist above.
   For UI, run functional smoke checks and check appearance manually.
   Test alternative permissions and input handling.

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

## Documentation

### Shared Information

- Keep each shared explanation in one primary guide. Check existing guides before adding documentation.
- Use short references elsewhere. Keep local conditions, exceptions, permissions, and summaries needed to use each guide independently.
- Update the primary guide when its rules change.

### Unit, Building, and Research Data

- Refer readers to the sources in [Tuning Data](#tuning-data) instead of duplicating current settings.
  This includes tables, examples, named-unit lists, and comparisons.
  Do not claim that unit or building families have equal stats, equal costs, or fixed strength relationships.
- Explain shared mechanics, data fields, source locations, and how the game reads current data.
  Preserve save formats, migration rules, permissions, and control instructions.
- Apply this rule to guides, design notes, examples, explanatory comments, docstrings, and tutorial text.
  The game can display current values and capabilities when it derives them from authoritative data or shared rules.

### Language

- Make all project documentation as simple as possible.
  Keep it accurate and complete.
  Do not remove conditions, exceptions, or permissions to shorten the text.
- Use ASD-STE100 Simplified Technical English (STE).
  Use its writing rules and approved dictionary.
  See the [official standard](https://www.asd-ste100.org/).
- Use short sentences and one subject per paragraph.
  Give one instruction per sentence.
  Use active voice for instructions and simple verb forms.
- Limit instruction sentences to 20 words and descriptive sentences to 25 words.
  Limit paragraphs to six sentences.
- Use the same term for the same thing.
  Define abbreviations and necessary technical terms on first use.
  Avoid idioms, jokes, vague words, and unnecessary background.
- Keep software and game terms as necessary technical names.
  Preserve paths, identifiers, commands, protocol values, formulas, and exact UI labels.
  Do not rename these to satisfy a vocabulary rule.
- Use numbered steps for procedures.
  Give required conditions before the steps.
  Separate rules, examples, and proposed features.
- Apply these rules to design notes, agent guides, explanatory comments and docstrings.
- These language rules do not apply to `context/TODO.txt`, tutorial help text, or the root `README.md`.
- Preserve third-party licenses, source quotations, and archived source data.
  Simplify the project's explanation of that material, not the original text.
- Check meaning against the code before handoff.
  Do not claim full STE compliance without reviewing both the writing rules and dictionary.

### Tutorial and Maintenance

The fresh-game map tutorial is in `ui/confirm_dialog/message_box.py`.
Treat it as player documentation.
Update it when map navigation, unit selection, orders, or covered bottom-left controls change.
Add or update tests for changed tutorial behavior.

Update affected documentation, comments, examples, tests, schemas, and UI text with the implementation.
Check guides that refer to each changed rule. Keep their local instructions and references accurate.
See `documentation/general_info.txt` for the guide index.
Update every description or preview of changed player behavior.

### Handoff

State the behavior change and verification results.
Name the tests and builds that ran and those that did not.
Link relevant files and name remaining risks or unverified platforms.
Give a small example when it helps explain a change.
Do not dump whole files or give a generic change log.
