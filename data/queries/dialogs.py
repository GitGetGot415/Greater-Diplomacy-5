"""Dialog, clipboard, and click-sound helpers that hand off to the UI, plus map directory refresh."""

import data.constants as c
import json
import os
import pygame
import subprocess
import sys
import time
from data.platform import run_background, pick_upload_file
from data.map import history_io
from data.map.map_cache import remove_optional_layer_files
from data.queries.content import apply_historical_leader_timeline
from data.queries.saves import build_map_data_save, build_save_dict
from data import queries


def refresh_map_directories(screen, dirs_to_check, success_message="Data refreshed successfully!", options=None, *, context=None):
    """Headlessly instantiates maps on a background thread to prevent UI freezing."""
    # An empty dict behaves the same as None below (every lookup defaults to True),
    # so this also keeps refresh_nation_data's own default-options branch out of play.
    options = options or {}
    # Count total maps first
    total_maps = 0
    valid_scenarios = []
    for scenario_dir in dirs_to_check:
        if not os.path.exists(scenario_dir):
            continue
        for name in os.listdir(scenario_dir):
            scenario_path = os.path.join(scenario_dir, name)
            map_json_path = os.path.join(scenario_path, "map_data.json")
            if os.path.isdir(scenario_path) and os.path.exists(map_json_path):
                valid_scenarios.append((scenario_dir, name, scenario_path, map_json_path))
                total_maps += 1
    
    if total_maps == 0:
        from ui import dialogs as confirm_dialog
        confirm_dialog.show_info("Data Refresh", "No maps found to refresh.")
        return

    # Setup screen state for UI
    screen.is_refreshing = True
    screen.refresh_total = total_maps
    screen.refresh_completed = 0
    screen.refresh_status = "Initializing..."

    def _refresh_thread():
        from screens.game.map import Map
        maps_processed = 0

        for scenario_dir, name, scenario_path, map_json_path in valid_scenarios:
            try:
                screen.refresh_status = f"Syncing: {name}..."
                # 1. Instantiate Map with standard singleplayer configurations to pull existing meta/map data into memory
                temp_map_context = Map(load_path=scenario_path, is_scenario=True, skip_initial_income=True)

                # --- BUG FIX: Restore scenario settings wiped by selection_mode ---
                meta_path = os.path.join(scenario_path, "meta.json")
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            old_meta = json.load(f)
                            if "scenario_settings" in old_meta:
                                temp_map_context.scenario_settings = old_meta["scenario_settings"]
                    except Exception as e:
                        print(f"Error reading meta.json for settings restoration: {e}")
                # ------------------------------------------------------------------

                # 2. Execute the official resync pipeline
                temp_map_context.refresh_nation_data(options=options)
                print(f"refreshed {name}")

                # Re-apply the historical timeline on top -- refresh_nation_data
                # just reset name/adjective/leader fields to their generic base
                # template, which would otherwise blank out anything the
                # Historical Leaders Editor set for this scenario's date.
                if c.SCENARIOS_HISTORICAL_DIR.replace("\\", "/") in scenario_dir.replace("\\", "/"):
                    tm = temp_map_context.time_manager
                    apply_historical_leader_timeline(temp_map_context.nation_data, tm.year, tm.month_index, tm.day)

                # Set all playable country resources to 0 before compounding income calculations
                if options.get("reset_resources", True):
                    for nation_name, stats in temp_map_context.nation_data.items():
                        if nation_name != "GLOBAL_EVENTS" and nation_name not in c.UNPLAYABLE_NATIONS:
                            stats["manpower"] = 0
                            stats["materials"] = 0
                            stats["fuel"] = 0

                # 3. Clean country flags/portraits inside memory before serializing
                queries.scrub_default_images(temp_map_context.nation_data)

                # --- BUG FIX: Fix lowercase unit types and custom names ---
                unit_lib = queries.get_unit_library(context)
                for prov in temp_map_context.map_data.values():
                    for unit in prov.get("units", []):
                        u_type = unit.get("type", "")
                        if u_type:
                            # Match exact casing from unit library if possible
                            for correct_name in unit_lib.keys():
                                if correct_name.lower() == u_type.lower():
                                    unit["type"] = correct_name
                                    break
                            else:
                                words = unit["type"].split()
                                unit["type"] = " ".join(w.capitalize() if w.islower() else w for w in words)
                        
                        c_name = unit.get("custom_name", "")
                        if c_name:
                            words = c_name.split()
                            unit["custom_name"] = " ".join(w.capitalize() if w.islower() else w for w in words)
                # ----------------------------------------------------------

                # 4. Reconstruct the exact structural configuration payload
                # map_data.json carries current province state in new files;
                # the meta overlay remains only in legacy and multiplayer data.
                save_dict = build_save_dict(
                    temp_map_context, include_provinces=False, compact_nations=True)

                # 5. Perform the manual write operations in-place

                with open(os.path.join(scenario_path, "meta.json"), "w") as f:
                    f.write(history_io.dump_text(save_dict, indent=c.SAVE_INDENT))

                with open(map_json_path, "w") as f:
                    f.write(history_io.dump_text(
                        build_map_data_save(temp_map_context), indent=c.SAVE_INDENT))

                if hasattr(temp_map_context, 'history'):
                    history_io.write(scenario_path, temp_map_context.history)

                # These overlays are rebuilt from map state when the scenario
                # loads. Remove any copies left by older refreshes.
                remove_optional_layer_files(scenario_path)
                pygame.image.save(temp_map_context.terrain_map, os.path.join(scenario_path, "terrain.png"))
                pygame.image.save(temp_map_context.id_map, os.path.join(scenario_path, "id_map.png"))

                maps_processed += 1
                screen.refresh_completed = maps_processed

            except Exception as e:
                print(f"[REFRESH ERROR] Failed to automatically sync structural data profiles for '{name}': {e}")

        screen.refresh_status = f"{success_message} Processed {maps_processed} maps."
        # Allow a short delay for the user to read the success message before closing the bar
        time.sleep(1.5)
        screen.is_refreshing = False

    # Fire and forget the background process
    run_background(_refresh_thread)


def open_listbox_selector(game_state, title, prompt, items, on_confirm_callback, *, is_enabled=None,
                          close_on_select=True):
    """In-engine listbox picker for editor tools and spectators: dims and freezes
    the current frame, then shows a clickable list of rows in a modal panel."""
    from ui.dialogs.list_select_screen import ListSelectScreen
    from ui.navigation.screen_runner import _run_pygame_sub_screen
    screen = ListSelectScreen(game_state, title, prompt, items, on_confirm_callback,
                              is_enabled=is_enabled, close_on_select=close_on_select)
    _run_pygame_sub_screen(game_state, screen)


def _clear_phantom_hover(game_state):
    """Drops the hover a blocking sub-screen left behind, like _run_pygame_sub_screen does."""
    host = getattr(game_state, "map_screen", None) or game_state
    if hasattr(host, "hovered_province"):
        host.hovered_province = None


def open_checkbox_list(game_state, title, prompt, items, on_result, confirm_label="Confirm",
                       show_select_all=True, extra_buttons=None, footnote=None):
    """In-engine multi-toggle picker: replaces the scrollable tk.Checkbutton panels.

    `items` are ui.dialogs.checkbox_list_screen CheckboxItem / SectionHeader objects.
    Answers on_result with the list of checked keys -- empty when nothing was
    ticked, None when the user cancelled, so the two cases stay distinguishable.
    """
    from ui.dialogs.checkbox_list_screen import CheckboxListScreen
    from ui.navigation.screen_runner import run_screen
    result = {}
    def _on_done(screen):
        _clear_phantom_hover(game_state)
        on_result(result.get("keys"))
    run_screen(lambda: CheckboxListScreen(game_state, title, prompt, items,
                                          lambda keys: result.setdefault("keys", keys),
                                          confirm_label=confirm_label,
                                          show_select_all=show_select_all,
                                          extra_buttons=extra_buttons, footnote=footnote),
               on_done=_on_done, caption=title)


def open_color_picker(game_state, title, initial_color, on_confirm_callback):
    """In-engine RGB/hex color picker: replaces tkinter.colorchooser.askcolor."""
    from ui.dialogs.color_picker_screen import ColorPickerScreen
    from ui.navigation.screen_runner import _run_pygame_sub_screen
    screen = ColorPickerScreen(game_state, title, initial_color, on_confirm_callback)
    _run_pygame_sub_screen(game_state, screen)


def open_character_picker(game_state, current_path, on_confirm_callback):
    """In-engine grid picker for choosing a character portrait: shows a
    thumbnail for every image under assets/characters/."""
    from ui.dialogs.character_select_screen import CharacterSelectScreen
    from ui.navigation.screen_runner import _run_pygame_sub_screen
    screen = CharacterSelectScreen(game_state, current_path, on_confirm_callback)
    _run_pygame_sub_screen(game_state, screen)


def open_file_browser(game_state, title, start_dir=None, mode="open_file", extensions=None,
                      on_confirm_callback=None, tk_parent=None, on_result=None):
    """In-engine file/folder picker: replaces filedialog.askopenfilename,
    askopenfilenames and askdirectory.

    Browses the whole machine -- `start_dir` is only where it opens, never a
    fence. `mode` is "open_file", "open_files" (multi-select) or "select_folder".
    Answers on_result with the pick (a path, a list of paths, or None when
    cancelled); on_confirm_callback, when given, fires only on a real pick.
    """
    def _on_result(picked):
        if picked is not None and on_confirm_callback:
            on_confirm_callback(picked)
        _clear_phantom_hover(game_state)
        if on_result:
            on_result(picked)

    if queries.IS_WEB:
        if mode == "select_folder":
            # There's no native browser equivalent of "pick a folder on my
            # real disk" (a browser sandbox has no notion of an arbitrary
            # host path) -- not supported on web.
            from ui import dialogs as confirm_dialog
            confirm_dialog.show_error("Not Available", "Choosing a folder isn't supported in the browser build.", tk_parent=tk_parent)
            _on_result(None)
            return
        pick_upload_file(_on_result, extensions=extensions, multiple=(mode == "open_files"))
        return

    from ui.dialogs.file_browser_screen import run_file_browser
    run_file_browser(title, start_dir, mode=mode, extensions=extensions,
                     game_state=game_state, tk_parent=tk_parent, on_result=_on_result)


def copy_to_clipboard(text):
    """Push text to the OS clipboard, including macOS SDL fallback builds."""
    try:
        if not pygame.scrap.get_init():
            pygame.scrap.init()
        pygame.scrap.put(pygame.SCRAP_TEXT, text.encode("utf-8"))
        return True
    except Exception as e:
        # pygame.scrap is unavailable in a number of macOS packaged builds.
        # pbcopy is part of macOS itself and gives reconnect/invite copying the
        # same reliable fallback as text-input paste uses through pbpaste.
        if sys.platform == "darwin":
            try:
                subprocess.run(["/usr/bin/pbcopy"], input=str(text).encode("utf-8"),
                               check=True, timeout=2)
                return True
            except (OSError, subprocess.SubprocessError):
                pass
        print(f"Failed to copy to clipboard: {e}")
        return False


def play_click_sound():
    """Plays the UI click sound. Thin alias kept for non-UI callers."""
    from ui.widgets import ui_elements
    ui_elements.play_ui_sound("click")
