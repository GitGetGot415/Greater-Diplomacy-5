# Greater Diplomacy 5 Agent Guide

This file gives the rules for AI-assisted changes in this repository.
AI means artificial intelligence. UI means user interface.
A change is complete only when all affected game modes, state transitions, UI controls, and builds use the same behavior.

## Before Editing

1. Read the relevant code and tests.
   Find every reader, writer, serializer, label, and duplicate implementation of the affected behavior.
   Do not assume the first match is the only caller.
2. Check `git status`.
   Preserve unrelated user changes. Do not discard work to get a clean tree.
3. Read the relevant design notes:
   - `documentation/non_llm_ai.txt`: rule-based AI, combat, tactical play, and spectators.
   - `documentation/ai_movement.txt`: AI unit orders, movement caches, aircraft missions, and movement tuning.
   - `documentation/llm_ai.txt`: large language models (LLMs), prompts, budgets, cancellation, and fairness.
   - `documentation/diplo_stuff.txt`: diplomacy, messages, guarantees, volunteers, attach?s, factions, war, and peace.
   - `documentation/other/context_prompts.txt`: maintenance preferences.
4. Find the shared rule or data owner.
   Extend that implementation and make callers use it.

## Required Rules

- **Never commit to `main` without explicit user approval.**
  Use a separate branch for risky or multi-part work if useful.
  Do not create any commit unless the user requests or approves it.
- Use `color`, never `colour`, in identifiers, UI text, comments, and documentation.
- Preserve intentional comments.
  Update inaccurate comments. Keep explanations of rules that are not obvious.
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
| `data/json/` | Data libraries and AI response text used without an LLM. |
| `data/map/save_map.py`, `data/map/load_map.py` | Saves, loads, defaults, and old-save migration. |
| `data/io/multiplayer_io.py` | Tournament files, player move export, host import, authentication, and filtering. |
| `data/io/realtime_multiplayer.py` | Real-time protocol, server commands, snapshots, and filtered client state. |
| `map_logic/turn_processing/` | Turns, movement, economy, research, and combat. |
| `map_logic/diplomacy/` | Shared diplomacy rules, messages, effects, and state changes. |
| `map_logic/ai/` | Rule-based AI, legal candidates, valuation, LLM selection, and fallbacks. |
| `screens/` | Complete menu, game, and editor screens. Each screen builds its own buttons. |
| `ui/` | Shared widgets, panels, dialogs, bars, popups, and UI support. |
| `compilation_scripts/` | Windows, macOS, and web build definitions. |
| `tests/` | Regression tests and rule checks. `run_tests.py` finds all `test_*.py` files. |

## Apply Changes to All Affected Systems

Start with the shared rule.
Check each row below and update every affected system in the same change.
Give a reason when a system does not apply.

| System | Check | Likely locations |
| --- | --- | --- |
| Core rules | Share legality, cost, effect, timing, and calculation logic across callers. | `data/queries.py`, `map_logic/` |
| Turn processing | Check order resolution, turn changes, removed countries, wars, and factions. | `map_logic/turn_processing/`, `map_logic/diplomacy/` |
| UI | Derive labels, previews, enabled controls, tooltips, popups, and numbers from execution rules. | `screens/`, `ui/` |
| AI | Generate, value, select, perform, and answer actions without an LLM. Limit LLM choices to legal candidates. | `map_logic/ai/`, `data/json/ai_responses.json` |
| Save/load | Write new state, use safe defaults, migrate old saves, and check a save/load round trip. | `data/queries.py`, `data/map/save_map.py`, `data/map/load_map.py` |
| Tournament multiplayer | Authenticate and validate partial moves. Reject stale or duplicate input. Preserve shared changes and hidden information. | `data/io/multiplayer_io.py`, `tests/test_tournament_moves.py` |
| Real-time multiplayer | Let only the server apply commands. Validate permissions, filter snapshots, and protect private state. | `data/io/realtime_multiplayer.py`, real-time UI, `tests/test_realtime_multiplayer.py`, `tests/test_realtime_fog.py` |
| Other modes | Check single-player, hotseat, spectators, tactical control, AI countries, and editor permissions. | `screens/menu_screens/map.py`, affected screens, `data/queries.py` |
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

### One Source of Truth

- Combine duplicate calculations, rules, functions, and state changes in one named helper.
  Use the same path for similar behavior unless a documented gameplay rule requires a difference.
- Make UI previews and AI scores use the shared gameplay rules.
  Do not copy damage, price, eligibility, acceptance, capacity, or timing formulas into their callers.
- Put reusable questions about current state in `data/queries.py`.
  Put constants in `data/constants.py` only when modules share them.
- Group a screen's layout values near the top of that screen file.
  Use one anchor or gap value to move a UI group.
  Keep local layout constants out of `data/constants.py`.
- Keep unit and building tuning data in its source files.
  Follow the documentation rule below.
- Use data tables instead of repeated condition chains when content is likely to grow.

### Hardcoding and Fallbacks

- Do not hardcode content, tuning values, or repeated unexplained numbers in behavior code.
  Use JSON data, named local constants, shared constants, or query helpers.
- Derive gameplay test expectations from shared constants, data, or rule helpers.
  Do not fix balance values in tests unless they belong to an artificial test fixture.
  A tuning change must not require unrelated test edits.
- Do not assume incidental relationships between real units.
  These include equal costs, equal stats, fixed ratios, or one unit always being stronger or faster.
  Units can be tuned separately.
  Check each unit against its own data, or compare artificial fixtures.
  Test a fixed relationship only when a shared gameplay rule requires it.
  Identify that rule in the test.
- Treat editable UI and tutorial text as content.
  Test structure, navigation, callbacks, icons, layout, and behavior.
  Check exact wording only for protocol values, identifiers, or a specific user requirement.
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

- Treat a new saved field as a schema change.
  Define its owner, writer, loader, and old-save default.
  Test round trips and legacy loading.
- Keep settings keys consistent across the schema, controller, readers, writers, defaults, and settings UI.
- Preserve unknown or older valid data where possible.
  Migration must produce predictable results and be safe to run once on load.
- Reuse caches instead of reading disk in frame or turn loops.
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
- Check normal players, hotseat, spectators, tactical players, tournament players and hosts, real-time clients and hosts, AI, and editors.
- Tactical players command one division while the host country remains AI-controlled.
  Existing spectator flags control spectator editing.
  Check the actual modes and flags. Do not infer a mode from a related attribute.
- Use these map display rules:
  - Strategic country selection: Political layer, country names on, Units off.
  - Tactical country selection and play: Units on, country names off.
  - Normal strategic play and loaded games: start with Units on and country names off.
  - Tactical rendering: draw every visible division at every zoom.
    Do not apply strategic fading or zoomed-out army compression.
  - Tactical country selection: a clicked unit box selects from that box's divisions.
    Fall back to the tile only when no rendered box exists there.
- Test useful layout conditions: no overlap, containment, reachable controls, and consistent spacing.
  Do not freeze arbitrary coordinates or tunable unit values in tests.
  Derive expectations from their owners.

### AI and Diplomacy

- Rule-based AI is authoritative and must work with the LLM disabled.
  The model selects only actions already generated and validated as legal.
- Reuse shared AI or rule valuations for units, technology, proposals, and diplomatic outcomes.
- Preserve shared prompt prefixes, turn-budget cancellation, and fairness rules from `documentation/llm_ai.txt`.
- Before changing diplomacy, read `documentation/diplo_stuff.txt`.
  Test both directions and delayed resolution.
  Preserve message timing, cancellation, crossing requests, and unilateral or bilateral behavior.
- UI, AI, scripted events, editor setup, tournament import, and real-time diplomacy must use shared legality and effect functions.

## Add Files, Assets, or Dependencies

- Add `__init__.py` when a new Python package requires it.
- Include new runtime modules, packages, data, assets, dependencies, and dynamically imported screens in each applicable build file:
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

1. Add or update focused regression tests for the rule and actual failure.
   Keep useful tests. Rewrite them around the required behavior when necessary.

2. Run focused tests during development.
   Example: `python -m unittest tests.test_tournament_moves`.

3. Run `python run_tests.py` before handoff when feasible.

4. For gameplay, check execution, UI and AI agreement, saves, and both multiplayer systems where applicable.

5. For UI, run smoke or layout checks.
   Check alternative permissions and screen sizes.
   Tests must not require real network services or an LLM unless marked as integration tests.

6. State exactly which tests and builds ran and which did not.

## Documentation

### Unit, Building, and Research Data

- Never document current unit or building stats, research settings, costs, or combat capabilities.
  These can change frequently. Documentation must not duplicate them.
- This includes research years, level counts, prerequisites, unlock lists, prices, production times, and resource output.
  It also includes health, attack, defense, speed, range, damage bonuses, immunity, and fort damage capability.
- Do not document these settings as tables, examples, named-unit lists, or comparisons.
  Do not claim that unit or building families have equal stats, equal costs, or fixed strength relationships.
- Explain shared mechanics, data fields, source locations, and how the game reads current data.
  Preserve save formats, migration rules, permissions, and control instructions.
- Refer readers to `data/json/unit_data.json`, `data/json/building_data.json`, and `data/json/research_template.json` for current settings.
  Refer to `data/generators/recipes.py` for data generation and `data/constants.py` for shared tuning.
  Refer to shared query and execution helpers for rules defined in code.
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
- Do not edit the TODO text file using this language.
- Do not edit the tutorial help text using this language.
- Do not edit the README markdown file in the root of the repository using this language.
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
Keep `documentation/non_llm_ai.txt`, `documentation/llm_ai.txt`, and `documentation/diplo_stuff.txt` consistent with the rules.
Keep `documentation/ai_movement.txt` consistent with AI unit-order planning.
Update every description or preview of changed player behavior.

At handoff, state the behavior change and verification results.
Link relevant files and name remaining risks or unverified platforms.
Do not dump whole files or give a generic change log.

## Completion Conditions

A change is complete only when all applicable conditions are met:

- One clear implementation owns the rule.
- Execution, UI, AI, and documentation agree.
- Old saves load safely and new state survives a round trip.
- Both multiplayer systems are supported, or a concrete reason explains why they do not apply.
- Affected player and editor modes enforce the correct permissions.
- Build definitions include new runtime material.
- Focused tests pass, and the full suite ran when feasible.
- Relevant design notes are accurate.
