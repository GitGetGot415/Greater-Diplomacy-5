# Consolidation audit

This file records implementation boundaries and verification for the attached consolidation plan.
Backend means game rules that run without the map screen.
AI means artificial intelligence. UI means user interface.
See `general_info.txt` for current ownership. See `data_migrations.txt` for compatibility rules.

## Baseline

The initial working tree was clean. No commits were created.
`python run_tests.py` passed 2,785 tests, with five skips.
`python data/generators/generate_data.py --check` reported that all three generated files matched their recipes.

The implementation keeps the current source-replacement mechanism and public import paths.
It adds no dependencies. It does not change the tutorial or TODO file.

## Action and caller inventory

Protocol adapters retain authentication, session checks, stale-turn checks, duplicate checks, and private-state filtering.
Local controls retain their mode checks. Scripted events retain their explicit event authority and execution order.
Editors retain immediate setup actions. Those actions do not become ordinary player permissions.

| Action family | Eligibility and cost owner | Mutation and refund owner | Timing | Adapters and notifications | Cache boundary |
| --- | --- | --- | --- | --- | --- |
| Recruitment | `production_actions.prepare_production`; active unit metadata; treaty restrictions | `submit_production`; canonical paid entries; recorded refunds | Existing deployment queue | Production UI; AI purchases; tournament projection; real-time commands | UI draft invalidation; turn refresh; authoritative snapshot |
| Construction | Shared core and research queries; dynamic building costs | Production actions; explicit AI payment policy | Existing construction queue | Production UI; AI site selection; both multiplayer adapters | Same production boundaries |
| Coring and core removal | Administrative settings and shared cost queries | Production actions; existing economy processor | Existing administrative queue and capture cancellation | Player UI; AI coring; host validation | Core-layer refresh and turn boundaries |
| Movement and conversion | `canonical_unit_order`; shared path and conversion helpers | Existing movement processor; existing paid-order refunds | Existing conversion and movement phases | Orders; tactical controls; AI; editor setup; tournament aircraft adapter; real-time commands | Order invalidation; geometry and turn boundaries |
| Upgrades and repairs | Shared upgrade, maintenance, combat, and affordability queries | Existing movement processor and order-refund helpers | Existing maintenance phases | Orders; AI maintenance; both multiplayer adapters | Order invalidation and stat refresh |
| Air missions and cargo | Shared air-order and cargo helpers in `queries.py` | Existing air processor and cargo roster owner | Existing mission and recovery phases | Orders; AI; scripted spawning; editor setup; both multiplayer adapters | Aircraft geometry and roster boundaries |
| Research queues | `canonical_research_selection`; shared prerequisite queries | `research_processor`; authoritative progress | Existing research phase | Research UI; AI selection; real-time reconstruction; tournament partial state | Research edit and turn boundaries |
| Starting research | Existing shared research-edit queries | Existing research-edit confirmation owner | Immediate authorized setup | Map editor and permitted local spectators | Research-edit invalidation |
| Army editing | Existing army normalization, membership, and target-area helpers | Army helpers in `queries.py` | Existing planning and target-return boundaries | Army panel; Orders; AI orders; tournament records; real-time roster projection | Selection and army-presentation invalidation |
| Country appearance | Existing local permissions; separate network field limits | `apply_country_appearance`; appearance fields only | Existing immediate local edit or server draft | Country editor; subject editor; tournament shared updates; real-time identity projections | Name cache, flag cache, and changed map layers |
| Faction naming | Existing faction membership and collision helper | `faction_actions.rename_faction` | Existing local edit or server draft | Local controls; AI naming; tournament explicit command; real-time command | Country-name cache and faction layers |
| Subject controls | Existing subject and release helpers; shared siphon limits | Existing puppet action owner; validated partial projections | Existing release and diplomacy phases | Subjects UI; AI; events; editor setup; both multiplayer adapters | Ownership, economy, and snapshot boundaries |
| Diplomacy requests and replies | Existing action legality and treaty legality | `diplomacy_lifecycle`; treaty effect owners; existing escrow owner | Existing clash, response, send, and delayed phases | Map controls; Mail; AI; scripted events; both multiplayer adapters | Message and turn presentation boundaries |
| Ratification | Existing member-scope and consent rules; round references | Lifecycle answer writer; existing ratification settlement | Immediate AI answers; existing human waiting period | Treaty UI; AI; tournament country channel; real-time response command | Treaty settlement and snapshots |

## Preserved caller differences

- AI building purchases omit manpower charges. `AI_POLICY` records this existing difference.
- Emergency AI cancellation refunds recorded payments only. Normal cancellation retains its older-save price fallback.
- Real-time administrative reconstruction clamps durations. The player and AI queue constructors retain their existing duration policy.
- AI recruitment avoids combat sites and applies its existing ocean-border policy. These remain AI selection rules.
- AI research keeps its existing full-cost restart behavior. Player and real-time research resume authoritative saved progress.
- Tournament moves remain partial country and province projections. They do not become real-time commands.
- Older tournament moves retain administrative duration review. Current moves add shared queue legality and aggregate budget validation.
- Local appearance editing retains its existing mode policy. Network adapters retain their narrower subject and identity checks.
- Scripted events and editors keep their existing setup authority. They do not require a local player identity.

## Deliberate validation changes

Shared production callbacks recheck ownership, research, recruitment sites, and current resources before mutation.
Invalid or unauthorized callbacks cannot add orders or remove paid work.
Current tournament production input uses cumulative affordability checks before host mutation.
Real-time drafts reject repeated projections of the same province queue.
Stable request references prevent old responses from resolving cancelled or replaced requests.
Current network input rejects stale response references and unsupported schema versions.
Older-input adapters retain their documented compatibility policies.

## State boundaries

`WorldState` and `SessionState` contain no widgets, surfaces, audio engines, or transports.
`StateAccess` exposes explicit compatibility properties. It does not keep copied shadow fields or use an automatic attribute proxy.
`world_for` and `session_for` adapt older flat contexts and lightweight test doubles at the compatibility boundary.
Backend consumers use canonical owners. Presentation adapters keep their existing public map interface.

Loading, procedural generation, history, and snapshots update shared mappings in place.
Draft copies isolate world and session containers before replacing dictionaries.
The real-time server loads a backend context. It does not construct a map screen.
Backend geometry uses temporary image pixels and retains computation indexes without a display surface.
Feedback uses an explicit callback. Rendering stays with presentation owners.

The field inventory below includes direct map assignments and assignments made by backend and loading adapters.
Transport objects and authentication routing remain in presentation adapters. They never enter world serialization.

### World

`default_research`, `history`, `id_to_province`, `loop_map`, `map_data`, `map_h`, `map_w`, `nation_data`,
`raw_json_data`, `scenario_settings`, `script_variables`, `time_manager`, `unit_event_log`

### Session

`active_players`, `ai_is_thinking`, `ai_processing_complete`, `current_player_index`, `force_skip_llm`,
`is_editor`, `is_refreshing`, `is_saving`, `loading_status_text`, `multi_turn_abort_requested`,
`multi_turn_processing_complete`, `multi_turns_completed`, `multi_turns_total`, `multiplayer_mode`, `num_players`,
`player_country`, `player_unit`, `proactive_choices`, `proactive_llm_tasks`, `proactive_llm_tasks_completed`,
`proactive_llm_tasks_total`, `proactive_tasks_completed`, `proactive_tasks_total`, `realtime_multiplayer`,
`refresh_tasks_completed`, `refresh_tasks_total`, `responsive_tasks_completed`, `responsive_tasks_total`,
`save_progress_completed`, `save_progress_total`, `selection_mode`, `skip_ai_view`, `summits_completed`,
`summits_total`, `tactical_mode`, `thread_error`, `turn_start_time`, `unit_economy`, `unit_event_read_turns`,
`viewing_ai_moves`, `viewing_country`

### Temporary computation

`_air_distances`, `_air_geometry`, `_units_with_move_order_this_turn`,
`ai_world`, `cached_unit_library`, `econ_cache`, `econ_cache_target`,
`econ_cache_time`, `llm_deadline`, `multiplayer_player_enc_cache`, `partial_visible_provinces`, `visible_provinces`

### Presentation and input adapters

`_badge_state_cache`, `_combat_bubble_records_cache`, `_combat_unit_view_cache`,
`_country_name_blob_sort_cache`, `_country_name_transform_cache`, `_fog_surface_cache`, `_hover_glow_scale_cache`,
`_map_surface_cache`, `_presentation_cache_revision`, `_scripted_response_indicator_cache`,
`_unit_render_index_cache`, `_unit_roster_cache`, `_viewport_scale_cache`, `btn_global_econ_overview`,
`_army_group_viewer`, `_editor_visual_refresh_layers`, `_ignore_left_until_release`, `_ignore_right_until_release`,
`_orders_return_to_province_menu`, `_popup_presentation_revision`, `_realtime_draft_dirty`,
`_realtime_draft_fingerprint`, `_realtime_snapshot_phase`, `_realtime_snapshot_turn`, `_realtime_submit`,
`_realtime_unsubmit`, `_unit_event_unread`, `_unit_event_view`, `_unit_selection_player`, `_unit_selection_turn`,
`active_map`, `ai_response_images`, `army_editor_state`, `army_group_transition_states`, `base_layer`, `bg_color`,
`bot_bar_rect`, `bot_ui_height`, `brush_building`, `brush_nation`, `brush_unit`, `btn_close_info`,
`btn_declare_indep`, `btn_ed_autocore`, `btn_ed_brush`, `btn_ed_building`, `btn_ed_claim`, `btn_ed_clear`,
`btn_ed_core`, `btn_ed_date`, `btn_ed_diplo`, `btn_ed_edited`, `btn_ed_load`, `btn_ed_nation`, `btn_ed_paint`,
`btn_ed_personality`, `btn_ed_refresh`, `btn_ed_resource`, `btn_ed_scripts`, `btn_ed_unit`, `btn_exit_to_menu`,
`btn_go_battle`, `btn_go_orders`, `btn_go_production`, `btn_help`, `btn_import_turn`, `btn_multi_turn`,
`btn_next_turn`, `btn_realtime_details`, `btn_refresh_all`, `btn_skip_ai`, `btn_spec_mp_export`,
`btn_spec_mp_keys`, `btn_spec_mp_manage`, `btn_spectator`, `btn_tactical`, `btn_toggle_names`, `btn_unit_events`,
`btn_view_blank`, `btn_view_cores`, `btn_view_economy`, `btn_view_factions`, `btn_view_foreign_politics`,
`btn_view_political`, `btn_view_relations`, `btn_view_resources`, `btn_view_terrain`, `btn_view_units`, `camera`,
`camera_tilt_slider_val`, `cancel_rect`, `centers_need_update`, `compact_army_unit_object_ids`, `confirm_box_rect`,
`confirm_rect`, `core_text_blobs`, `cores_map`, `country_action_buttons`, `country_actions_scroll_max`,
`country_actions_scroll_rect`, `country_actions_scroll_y`, `country_economy_summaries`, `country_name_surfs`,
`country_text_blobs`, `diplomatic_popups`, `done`, `editing_country`, `editor_history`, `editor_mode`,
`editor_redo_history`, `editor_selection_tool`, `elements`, `error_copied`, `exit_no_rect`, `exit_yes_rect`,
`extreme_hidden_provinces`, `faction_name_surfs`, `faction_territories_map`, `factions_map`, `feedback_text`,
`feedback_timer`, `fog_map`, `font`, `force_skip_btn_rect`, `hide_flag`, `hide_minimap`, `hide_raised_rect`,
`hide_resource_hud`, `hide_tooltip`, `hide_top_info`, `history_turn`, `hover_glow_rect`, `hover_glow_surf`,
`hovered_province`, `hovered_unit_stack`, `id_map`, `last_hovered_id`, `load_path`, `loading_spinner_angle`,
`mail_draft_text`, `mail_input_active`, `map_mode`, `min_zoom`, `multi_turn_abort_btn_rect`,
`multiplayer_session_key`, `nation_colors`, `navigation_intro_popup`, `next_state`, `painting_active`,
`pending_selection`, `pending_unit`, `political_map`, `presentation_enabled`, `raised_rect`, `random_settings`,
`ready_btn_rect`, `realtime_client`, `realtime_connection_error`, `realtime_pending_appearance_updates`,
`realtime_submission_pending`, `realtime_temporary_relay`, `realtime_volunteer_drafts`, `relations_map`,
`se_checkbox_rect`, `sec_idx`, `secondary_mode`, `secondary_modes`, `selected_province`, `selected_unit_ids`,
`show_country_names`, `show_exit_confirmation`, `show_navigation_intro_when_ready`, `show_player_ready_screen`,
`slider_camera_tilt`, `small_font`, `strategic_unit_fade_states`, `submitted_moves`, `terrain_map`, `top_bar_rect`,
`top_ui_height`, `total_ui_h`, `ui_background_rect`, `unassigned_army_card`, `unassigned_army_country`,
`unit_event_filter`, `unit_event_filter_turn`, `unit_hover_hitboxes`, `unit_selection_drag`, `unit_stack_hitboxes`,
`unit_view_bar_rect`, `unit_view_buttons`, `unit_view_filter`, `viewing_research_country`

## Verification record

### Automated checks

`python run_tests.py` ran 2,807 tests without failures. Five tests were skipped.
The final run took approximately 104 seconds.
It includes the new state, metadata, production, appearance, lifecycle, settings, and build checks.
It also includes existing game-mode, save, history, cache, tournament, real-time, fog, and model-budget checks.
Tests use mocked model services. They do not require an external model provider.

Focused checks passed during each implementation stage.
The final action group passed 154 tests.
The final legacy metadata interface group passed 36 tests.
The tournament group passed 32 tests, including current-schema budget and response-reference cases.

`python data/generators/generate_data.py --check` reported three unchanged generated files.
All generated files match the recipes.
A structural comparison confirmed that unit fields outside metadata retain their original values.
`git diff --check` passed.

### Behavior comparisons

A backend test loads a historical scenario and completes both turn phases without a display or map-screen import.
World and session containers use the normal loader and processors in that test.

A one-time comparison ran original and replacement AI production effects from equal state and equal gameplay random state.
The resulting full-turn state and gameplay random state matched.
The comparison excluded timestamps and new internal request identities.

A separate comparison checked original and metadata-based queries for every active unit.
It checked grouping, tiers, requirements, upgrades, AI categories, and division names.
Unlock and upgrade checks used five deterministic research assignments.
The comparison found no differences.

Gameplay preservation is limited to behavior demonstrated by these checks.
These comparisons do not prove equivalence for every edited library or replacement module.

### Packaging

All four entry points consume the shared manifest and staging helpers.
Windows and web builds completed with the final runtime source.
The output paths are `dist/GD5 WINDOWS v46.zip` and `web_stage/build/GD5 WEB v46.zip`.
Archive checks include dynamic modules, loose sources, runtime resets, private directories, native material, and PNG signatures.
The Windows archive contains 1,798 entries. Its frozen shared modules match the current source code.
The nested web application archive contains 1,681 entries. Its Python sources match the current source files.

Inventory comparisons applied original platform filters to the current source tree.
Windows inventories matched at 1,684 files. Web inventories matched at 1,681 files.
The original macOS policy included 1,685 files. The shared policy includes 1,684 files.
The only macOS exclusion is generated file `data/json/__pycache__/fix_countries.cpython-313.pyc`.
New runtime files appear through the shared source inventory and explicit hidden imports.

The source scan found one older PNG signature mismatch: `assets/music/Type R/icon.png` contains JPEG data.
This ignored local album is excluded from releases. No included PNG signature mismatch was found.

The web build reported missing optional `imageio-ffmpeg`.
The staged application contains no MP3 files, so this build required no conversion.
Future albums without replacements can require that existing conversion tool.

No native macOS build ran. This host runs Windows and has neither py2app nor `ditto`.
Manifest, import, setup, and staging checks do not replace a native macOS build.

### Manual and browser checks

Rendered desktop screens were inspected for production, orders, research, messages, settings, and the map.
Additional previews covered diplomatic drafts, reply controls, ratification controls, and the diplomacy editor.
Functional tests cover permissions, tactical selection, spectator controls, and strategic display defaults.
These checks do not replace an extended interactive play session.

The browser smoke attempt served the built web output through a local HTTP server.
Edge reached the loading screen but timed out while fetching the external pygame-web runtime.
The retry also remained on the loading screen.
Browser gameplay, save synchronization, and import/export remain unverified.
The web archive and source checks passed independently of that runtime limitation.

