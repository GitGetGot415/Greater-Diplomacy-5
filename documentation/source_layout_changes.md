# Source layout changes

The paths below changed during the source reorganization.
Update imports and source-replacement mod targets to use the new paths.
Saved data and runtime content paths do not change.
Runtime imports use the new paths directly.
The previous benchmark, dependency-download, preview, and sandbox-test commands remain available as launchers.

Content recipes remain in `data/generators/`.
Existing test module names remain unchanged.
The sandbox suite moves into `tests/` and also runs during normal test discovery.

| Previous path | Current path |
| --- | --- |
| `data/queries.py` | `data/queries/` (one module for each topic) |
| `map_logic/turn_processing/` | `map_logic/system32/` |
| `docs/SANDBOX_SECURITY.md` | `documentation/other/sandbox_security.md` |
| `data/editors/country_editor.py` | `scripts/editors/country_editor.py` |
| `data/editors/unit_editor.py` | `scripts/editors/unit_editor.py` |
| `data/io/multiplayer_io.py` | `data/multiplayer/tournament/files.py` |
| `data/io/realtime_multiplayer.py` | `data/multiplayer/realtime/session.py` |
| `data/io/realtime_networking.py` | `data/multiplayer/realtime/networking.py` |
| `data/io/realtime_relay.py` | `data/multiplayer/realtime/relay.py` |
| `data/io/realtime_relay_service.py` | `data/multiplayer/realtime/relay_service.py` |
| `data/json/fix_countries.py` | `scripts/data/fix_countries.py` |
| `map_logic/camera/__init__.py` | `ui/camera/__init__.py` |
| `map_logic/camera/camera_handler.py` | `ui/camera/camera_handler.py` |
| `map_logic/gd4_translation.py` | `map_logic/imports/gd4_translation.py` |
| `map_logic/gdhex_translation.py` | `map_logic/imports/gdhex_translation.py` |
| `map_logic/odtl.py` | `map_logic/imports/odtl.py` |
| `map_logic/player_actions.py` | `map_logic/actions/player_actions.py` |
| `map_logic/production_actions.py` | `map_logic/actions/production_actions.py` |
| `map_logic/rendering/__init__.py` | `ui/rendering/__init__.py` |
| `map_logic/rendering/country_names.py` | `ui/rendering/country_names.py` |
| `map_logic/rendering/font_manager.py` | `ui/rendering/font_manager.py` |
| `map_logic/rendering/hover_renderer.py` | `ui/rendering/hover_renderer.py` |
| `map_logic/rendering/map_renderer.py` | `ui/rendering/map_renderer.py` |
| `map_logic/rendering/map_utils.py` | `ui/rendering/map_utils.py` |
| `map_logic/rendering/overlay_renderer.py` | `ui/rendering/overlay_renderer.py` |
| `map_logic/rendering/province_select.py` | `ui/rendering/province_select.py` |
| `map_logic/rendering/refresh_map.py` | `ui/rendering/refresh_map.py` |
| `map_logic/rendering/symbol_loader.py` | `ui/rendering/symbol_loader.py` |
| `map_logic/setup/player_setup.py` | `screens/setup/player_setup.py` |
| `map_logic/turn_processing/edit_province_ownership.py` | `map_logic/territory/ownership.py` |
| `map_logic/turn_processing/loading_screen.py` | `ui/panels/turn_progress.py` |
| `map_logic/unit_actions.py` | `map_logic/actions/unit_actions.py` |
| `map_tools/fetch_dragoman_wasm.py` | `scripts/dependencies/fetch_dragoman_wasm.py` |
| `map_tools/ojh_benchmark.py` | `scripts/benchmarks/ojh_benchmark.py` |
| `map_tools/ui_layout_preview.py` | `scripts/previews/ui_layout_preview.py` |
| `screens/editor_screens/__init__.py` | `screens/editors/__init__.py` |
| `screens/editor_screens/brush_screens.py` | `screens/editors/brush_screens.py` |
| `screens/editor_screens/date_economy_screens.py` | `screens/editors/date_economy_screens.py` |
| `screens/editor_screens/diplomacy_editor_screen.py` | `screens/editors/diplomacy_editor_screen.py` |
| `screens/editor_screens/historical_leaders_editor.py` | `screens/editors/historical_leaders_editor.py` |
| `screens/editor_screens/personality_editor.py` | `screens/editors/personality_editor.py` |
| `screens/editor_screens/politics_editor.py` | `screens/editors/politics_editor.py` |
| `screens/editor_screens/research_screens.py` | `screens/editors/research_screens.py` |
| `screens/editor_screens/scripted_events_editor.py` | `screens/editors/scripted_events_editor.py` |
| `screens/editor_screens/turn_editor.py` | `screens/editors/turn_editor.py` |
| `screens/editor_screens/unit_stats_editor.py` | `screens/editors/unit_stats_editor.py` |
| `screens/map_related_screens/__init__.py` | `screens/game/__init__.py` |
| `screens/map_related_screens/automation_screen.py` | `screens/game/automation_screen.py` |
| `screens/map_related_screens/battle_screen.py` | `screens/game/battle_screen.py` |
| `screens/map_related_screens/claims_screen.py` | `screens/game/claims_screen.py` |
| `screens/map_related_screens/country_summary.py` | `screens/game/country_summary.py` |
| `screens/map_related_screens/deal_screen.py` | `screens/game/deal_screen.py` |
| `screens/map_related_screens/declare_independence.py` | `screens/game/declare_independence.py` |
| `screens/map_related_screens/defense_area_screen.py` | `screens/game/defense_area_screen.py` |
| `screens/map_related_screens/diplomacy_screen_widgets.py` | `screens/game/diplomacy_screen_widgets.py` |
| `screens/map_related_screens/economy.py` | `screens/game/economy.py` |
| `screens/map_related_screens/edit_country.py` | `screens/editors/edit_country.py` |
| `screens/map_related_screens/faction.py` | `screens/game/faction.py` |
| `screens/map_related_screens/messages.py` | `screens/game/messages.py` |
| `screens/map_related_screens/orders.py` | `screens/game/orders.py` |
| `screens/map_related_screens/peace_screen.py` | `screens/game/peace_screen.py` |
| `screens/map_related_screens/politics_screen.py` | `screens/game/politics_screen.py` |
| `screens/map_related_screens/production.py` | `screens/game/production.py` |
| `screens/map_related_screens/puppets_screen.py` | `screens/game/puppets_screen.py` |
| `screens/map_related_screens/recruit_ui.py` | `screens/game/recruit_ui.py` |
| `screens/map_related_screens/research.py` | `screens/game/research.py` |
| `screens/map_related_screens/unit_events_screen.py` | `screens/game/unit_events_screen.py` |
| `screens/map_related_screens/war_screen.py` | `screens/game/war_screen.py` |
| `screens/menu_screens/credits.py` | `screens/menus/credits.py` |
| `screens/menu_screens/keybinds.py` | `screens/menus/keybinds.py` |
| `screens/menu_screens/load_game.py` | `screens/menus/load_game.py` |
| `screens/menu_screens/map.py` | `screens/game/map.py` |
| `screens/menu_screens/menu.py` | `screens/menus/menu.py` |
| `screens/menu_screens/mods.py` | `screens/menus/mods.py` |
| `screens/menu_screens/mouse_settings.py` | `screens/menus/mouse_settings.py` |
| `screens/menu_screens/multiplayer_host.py` | `screens/multiplayer/multiplayer_host.py` |
| `screens/menu_screens/multiplayer_hub.py` | `screens/multiplayer/multiplayer_hub.py` |
| `screens/menu_screens/multiplayer_join.py` | `screens/multiplayer/multiplayer_join.py` |
| `screens/menu_screens/multiplayer_menu.py` | `screens/multiplayer/multiplayer_menu.py` |
| `screens/menu_screens/multiplayer_new.py` | `screens/multiplayer/multiplayer_new.py` |
| `screens/menu_screens/music_player.py` | `screens/menus/music_player.py` |
| `screens/menu_screens/new_game.py` | `screens/setup/new_game.py` |
| `screens/menu_screens/random_setup.py` | `screens/setup/random_setup.py` |
| `screens/menu_screens/realtime_multiplayer.py` | `screens/multiplayer/realtime_multiplayer.py` |
| `screens/menu_screens/scenario_settings.py` | `screens/setup/scenario_settings.py` |
| `screens/menu_screens/select_base_map.py` | `screens/setup/select_base_map.py` |
| `screens/menu_screens/settings.py` | `screens/menus/settings.py` |
| `screens/menu_screens/translate.py` | `screens/menus/translate.py` |
| `screens/menu_screens/translation_menu.py` | `screens/menus/translation_menu.py` |
| `screens/menu_screens/unit_art.py` | `screens/menus/unit_art.py` |
| `screens/menu_screens/view_assets.py` | `screens/menus/view_assets.py` |
| `scripts/test_mod_loader_security.py` | `tests/test_mod_loader_security.py` |
| `ui/army_panel.py` | `ui/panels/army_panel.py` |
| `ui/character_select_screen.py` | `ui/dialogs/character_select_screen.py` |
| `ui/checkbox_list_screen.py` | `ui/dialogs/checkbox_list_screen.py` |
| `ui/color_picker_screen.py` | `ui/dialogs/color_picker_screen.py` |
| `ui/confirm_dialog/__init__.py` | `ui/dialogs/__init__.py` |
| `ui/confirm_dialog/base.py` | `ui/dialogs/base.py` |
| `ui/confirm_dialog/message_box.py` | `ui/dialogs/message_box.py` |
| `ui/confirm_dialog/person_info.py` | `ui/dialogs/person_info.py` |
| `ui/confirm_dialog/text_input.py` | `ui/dialogs/text_input.py` |
| `ui/confirm_dialog/yes_no.py` | `ui/dialogs/yes_no.py` |
| `ui/diplomatic_popups.py` | `ui/panels/diplomatic_popups.py` |
| `ui/editor_menus.py` | `screens/editors/menus.py` |
| `ui/event_handler.py` | `screens/game/map_input.py` |
| `ui/file_browser_screen.py` | `ui/dialogs/file_browser_screen.py` |
| `ui/flag_icons.py` | `ui/widgets/flag_icons.py` |
| `ui/list_select_screen.py` | `ui/dialogs/list_select_screen.py` |
| `ui/map_top_right_layout.py` | `ui/panels/map_top_right_layout.py` |
| `ui/minimap.py` | `ui/panels/minimap.py` |
| `ui/modal_screen.py` | `ui/navigation/modal_screen.py` |
| `ui/modal_stack.py` | `ui/navigation/modal_stack.py` |
| `ui/multiplayer_host_panel.py` | `ui/panels/multiplayer_host_panel.py` |
| `ui/realtime_status_panel.py` | `ui/panels/realtime_status_panel.py` |
| `ui/screen_runner.py` | `ui/navigation/screen_runner.py` |
| `ui/scroll_panes.py` | `ui/widgets/scroll_panes.py` |
| `ui/sidebar_info.py` | `ui/panels/sidebar_info.py` |
| `ui/spectator_menus.py` | `screens/game/spectator_controls.py` |
| `ui/table_screen.py` | `ui/widgets/table_screen.py` |
| `ui/text_detail_screen.py` | `ui/widgets/text_detail_screen.py` |
| `ui/text_utils.py` | `ui/widgets/text_utils.py` |

The previous sandbox guide paths now refer readers to the maintained guide.

The turn-processing package now uses its original `map_logic/system32/` name.
`AGENTS.md` explicitly requires this name unless the user requests another name.
The historical source paths above remain unchanged where they record earlier file moves.

## Imports outside the reorganized folders

Only import references change in these callers:

- `gameState.py`
- `ui_elements.py`
- `.github/workflows/odtl.yml`
- `TEMP_OTHER/aa.py`
- `TEMP_OTHER/unlock_aircraft_research.py`
- `TEMP_OTHER_2/analyze_sizes.py`
- `TEMP_OTHER_2/smoke_fixed_history.py`
- `TEMP_OTHER_2/smoke_reduced.py`

The temporary utilities are local files. Runtime import checks can still load them in this checkout.
`main.py` and `compilation_scripts/build_manifest.py` also use the current paths.
