# Greater Diplomacy 5 Agent Guide

This file defines the repository-wide rules for AI-assisted changes. The goal is
not merely to make the requested code work in the most obvious mode; a change is
complete only when every affected game mode, state boundary, UI, and build still
agrees about the same behavior.

## Before Editing

1. Read the relevant implementation and tests before changing anything. Search
   for every reader, writer, serializer, label, and duplicated version of the
   behavior; do not assume the first match is the only integration point.
2. Check `git status` and preserve unrelated user changes. Never discard or
   overwrite work just to obtain a clean tree.
3. Read the relevant design notes:
   - `context/ai_stuff.txt` for AI, combat, tactical-player, spectator, or LLM
     work.
   - `context/diplo_stuff.txt` for diplomacy, proposals, messages, guarantees,
     volunteers, military attaches, factions, war, or peace.
   - `context/context_prompts.txt` for the original maintainability preferences
     summarized and made enforceable in this guide.
4. Identify the canonical rule or data owner. Extend it and make consumers use
   it instead of independently recreating the rule.

## Non-Negotiable Rules

- **Never commit anything to `main` without asking the user explicitly first.**
  For risky or multi-part work, use a separate branch if a branch is useful.
  Do not create commits unless the user asked for them or approved them.
- Use `color`, never `colour`, in identifiers, UI text, comments, and docs.
- Preserve intentional comments. Update comments that become inaccurate; do not
  erase explanations of non-obvious invariants while editing nearby code.
- Do not silently change gameplay while refactoring. Behavior changes must be
  requested, be an unmistakable bug fix, or be called out to the user.
- All repository image assets must be real PNG files with `.png` extensions.
  Check the file signature, not only the extension. Report any mismatch and
  convert it when conversion is in scope.
- Generated and packaged directories are not source. Normally exclude these
  from exploration and edits: `web_stage/`, `dist/`, `build/`, `.eggs/`,
  `__pycache__/`, and `venv/`.

## Repository Map and Ownership

| Area | Responsibility |
| --- | --- |
| `data/constants.py` | Shared, genuinely global constants and tuning values. |
| `data/queries.py` | Reusable derived-state queries, shared rule helpers, caches, and the canonical save-dictionary builder. |
| `data/json/` | Data libraries and non-LLM AI response text. |
| `data/map/save_map.py`, `data/map/load_map.py` | Normal save/write, load, defaults, and legacy migration. |
| `data/io/multiplayer_io.py` | Asynchronous tournament files, per-player move export, host import, authentication, and filtering. |
| `data/io/realtime_multiplayer.py` | Authoritative real-time protocol, command validation/application, snapshots, and client projection. |
| `map_logic/turn_processing/` | Turn resolution, movement, economy, research, and combat processing. |
| `map_logic/diplomacy/` | Canonical diplomacy legality, messages, effects, and state transitions. |
| `map_logic/ai/` | Heuristic AI, legal candidates, valuation, LLM selection, and fallback behavior. |
| `screens/` | Standalone menu, in-game, and editor screens. Button construction belongs with the screen that owns it. |
| `ui/` | Reusable widgets, panels, dialogs, bars, popups, and UI framework glue. |
| `compilation_scripts/` | Windows, macOS, and web staging/package manifests. |
| `tests/` | Regression and contract coverage. `run_tests.py` discovers all `test_*.py` files automatically. |

## The Change-Propagation Rule

For every feature or behavior change, trace the change outward from the
canonical rule. Review every row below and edit all applicable surfaces in the
same change. “Not applicable” should be a reasoned conclusion, not an unchecked
assumption.

| Surface | Questions to answer | Likely locations |
| --- | --- | --- |
| Core rules | Where is legality, cost, effect, timing, or calculation defined? Can every caller share one implementation? | `data/queries.py`, `map_logic/` |
| Turn processing | Does the rule behave correctly when orders resolve, turns advance, countries disappear, or wars/factions change? | `map_logic/turn_processing/`, `map_logic/diplomacy/` |
| UI | Do labels, previews, enabled states, tooltips, popups, and displayed numbers derive from the same rule as execution? | `screens/`, `ui/` |
| AI | Can heuristic AI discover, value, select, perform, and respond to the feature without an LLM? Is the LLM limited to legal candidates? | `map_logic/ai/`, `data/json/ai_responses.json` |
| Save/load | Is all new persistent state written, loaded with safe defaults, and migrated for old saves? Does a round trip preserve it? | `data/queries.py`, `data/map/save_map.py`, `data/map/load_map.py` |
| Tournament multiplayer | Can a player submit the action without leaking hidden state? Can the host authenticate, validate, merge, reject stale/duplicate moves, and preserve shared-world changes? | `data/io/multiplayer_io.py`, `tests/test_tournament_moves.py` |
| Real-time multiplayer | Is the action represented as a client command, validated and applied only by the authoritative server, included safely in snapshots, and filtered by player visibility? | `data/io/realtime_multiplayer.py`, real-time screens/panels, `tests/test_realtime_multiplayer.py`, `tests/test_realtime_fog.py` |
| Other play modes | Does it respect single-player, hotseat, spectator permissions, tactical one-division control, AI-controlled nations, and editor mode? | `screens/menu_screens/map.py`, affected screens, `data/queries.py` |
| Content tools | Must scenario settings, map/editor UI, scripted-event actions/conditions, or base data be able to author the feature? | `screens/editor_screens/`, scenario screens, scenario/map JSON |
| Builds | Are new modules, packages, data files, dependencies, or dynamically imported screens included everywhere? | compilation files listed below |
| Documentation/tests | Which invariant and failure mode need regression coverage? Which design note or user-facing document is now stale? | `tests/`, `context/`, `README.md` |

### Mandatory multiplayer model

Tournament and real-time multiplayer are separate compatibility surfaces; a
feature working in one says nothing about the other.

- **Tournament mode is file-based and partial-state.** A player move contains
  only authorized changes for that player. A mutation affecting other nations
  or shared state (for example a faction rename, subject appearance, diplomacy,
  or ownership) must use an explicit host-validated command; it cannot rely on
  replacing the submitting nation's record. Preserve session/turn checks,
  duplicate detection, hidden-information filtering, and compatibility with
  older tournament files.
- **Real-time mode is server-authoritative.** A client proposes commands and
  may update local drafts for presentation, but it never establishes canonical
  game state. The server must validate identity, permissions, current state,
  costs, targets, and timing before applying a command. Snapshots sent back to
  clients must not reveal fogged or private data. Keep blocking network work off
  the pygame event loop and keep the desktop-only/web boundary explicit.
- Any new player action or mutable field requires a deliberate decision for
  both systems plus tests for unauthorized, malformed, stale, and valid input
  where relevant.

## Code and Data Design

### One source of truth

- Consolidate duplicated calculations, rules, functions, and state transitions
  into a single well-named helper. Similar behavior should follow the same
  path unless there is a documented gameplay reason it cannot.
- UI previews and AI evaluation must call or derive from the canonical gameplay
  logic. Never copy a damage, price, eligibility, acceptance, capacity, or time
  formula into a label or AI scorer.
- Put reusable dynamic questions about current game state in `data/queries.py`.
  Put shared immutable/tuning values in `data/constants.py` only when they are
  genuinely cross-module.
- Keep screen-specific layout values together near the top of the owning screen
  file. A developer should be able to reposition a UI group by changing one
  anchor/gap value, not several scattered numeric literals. Do not move local
  layout constants into `data/constants.py`.
- Prefer data-driven tables over repeated condition chains when content is
  expected to grow.

### Hardcoding and fallbacks

- Do not hardcode content, tuning values, or repeated magic numbers in behavior
  code. Use existing JSON data, local named constants, `data/constants.py`, or
  shared query helpers as appropriate.
- Non-LLM diplomatic/AI prose belongs in `data/json/ai_responses.json` and is
  accessed through `map_logic/ai/ai_prompts.py`; it must not be embedded at call
  sites.
- Avoid broad `getattr(..., fallback)` for required state. It hides renames and
  incomplete initialization. Use direct attributes when the object contract
  requires them. Use `getattr` only at real compatibility boundaries (old
  saves, optional platform features, lightweight test doubles, or deliberately
  optional mode state), and comment why the fallback is valid when it is not
  obvious.
- Do not add catch-all exception handling that converts programming errors into
  defaults. Catch expected failures narrowly and expose actionable errors.

### Persistence and caching

- Treat a new persistent field as a schema change: define its owner, write it,
  load it, choose an old-save default, and add round-trip/legacy coverage.
- Settings keys must be represented consistently in the settings schema,
  controller state, read/write paths, defaults, and settings UI when exposed.
- Preserve unknown or older valid data when possible. Migrations must be
  deterministic and safe to run once on load.
- Prefer existing caches over repeated disk reads in frame or turn loops.
  When adding a cache, define when it is populated and invalidated; mutate a
  shared cached dictionary in place if existing screens retain references to it.
- Remember the web build's virtual filesystem and persistence synchronization
  for saves, tournament files, imports, and user-created assets.

### UI and permissions

- A control's visibility is not authorization. Enforce ownership and permission
  checks again at the state-changing boundary.
- Explicitly consider normal player, hotseat, spectator, tactical player,
  tournament player/host, real-time client/host, AI, and editor behavior.
- Tactical mode commands one division while the host nation remains AI-run.
  Spectator editing abilities are controlled by the existing spectator feature
  flags. Do not infer either mode merely from the presence of a related
  attribute.
- Layout tests should protect useful invariants such as non-overlap, containment,
  reachability, and consistent spacing. Avoid brittle tests whose only purpose
  is to freeze an arbitrary pixel coordinate.

### AI and diplomacy contracts

- The heuristic/rules layer is always authoritative and must work with the LLM
  disabled. The model may choose only among actions already generated and
  validated as legal.
- If a second system needs to value a unit, technology, proposal, or diplomatic
  outcome, reuse the canonical AI/rules valuation instead of inventing another.
- Preserve prompt-prefix sharing, turn-budget cancellation, and fairness rules
  described in `context/ai_stuff.txt` when changing LLM work.
- Diplomacy has precise message timing, cancellation, crossing-request, and
  unilateral/bilateral semantics. Read `context/diplo_stuff.txt` and test both
  directions and delayed resolution before changing it.
- Diplomacy triggered by UI, AI, scripted events, editor setup, tournament
  import, and real-time commands should converge on the same legality and effect
  functions.

## Adding Files, Packages, Assets, or Dependencies

- Add `__init__.py` where a new Python package requires it.
- Update every applicable build definition when adding a runtime Python file,
  package, data directory, dynamically imported screen, asset group, or
  dependency:
  - `compilation_scripts/html_compilation.py`
  - `compilation_scripts/windows_compilation.py`
  - `compilation_scripts/macos_compilation.py`
  - `compilation_scripts/setup.py` (the py2app manifest)
- Run `tests/test_build_manifest.py`. It exists because omitted modules can pass
  source tests and fail only inside packaged Windows, macOS, or web builds.
- Update `requirements.txt` and platform-specific packaging imports together for
  new third-party dependencies. Do not import desktop-only modules on web paths.

## Verification

Every code change needs proportionate verification.

1. Add or update focused regression tests for the behavior and the bug's actual
   failure mode. Do not delete a useful test merely because an implementation
   changed; rewrite it around the invariant when appropriate.
2. Run focused tests while iterating, for example:
   `python -m unittest tests.test_tournament_moves`.
3. Run the complete suite before handoff when feasible: `python run_tests.py`.
4. For gameplay changes, cover rule execution plus UI/AI agreement, save/load,
   tournament behavior, and real-time authority wherever applicable.
5. For UI changes, perform the relevant smoke/layout test and manually reason
   through alternate permissions and screen sizes. Tests must not require real
   network services or an LLM unless explicitly marked as integration tests.
6. If a full suite or platform build cannot be run, state exactly what was and
   was not verified.

## Keeping Information Current

Update relevant documentation, comments, examples, tests, schemas, and UI copy
in the same change as the implementation. In particular, keep
`context/ai_stuff.txt` and `context/diplo_stuff.txt` synchronized with the rules
they explain. If behavior displayed to the player changes, update every place
that describes or previews it.

When handing work back, summarize the behavior changed and verification
performed. Do not dump entire files or produce a generic GitHub-style changelog;
point to the relevant files and call out any remaining risks or unverified
platforms.

## Definition of Done

A change is done only when:

- the canonical implementation is clear and duplicated rules were not added;
- execution, UI, AI, and documentation agree;
- saves load safely and new state round-trips;
- tournament and real-time multiplayer were implemented or consciously ruled
  out with a concrete reason;
- all affected player/editor modes enforce the right permissions;
- build manifests include new runtime material;
- focused regression tests pass, and the full suite was run when feasible; and
- relevant design notes remain accurate.
