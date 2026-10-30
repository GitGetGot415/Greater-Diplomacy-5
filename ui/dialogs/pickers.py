"""Dialog, clipboard, and click-sound helpers for screens and panels.

Dialog screens call these helpers back, so each function imports its screen locally.
"""

import pygame
import subprocess
import sys
from data.platform import IS_WEB, pick_upload_file
from ui import dialogs


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

    if IS_WEB:
        if mode == "select_folder":
            # There's no native browser equivalent of "pick a folder on my
            # real disk" (a browser sandbox has no notion of an arbitrary
            # host path) -- not supported on web.
            dialogs.show_error("Not Available", "Choosing a folder isn't supported in the browser build.", tk_parent=tk_parent)
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
    """Plays the UI click sound."""
    from ui.widgets import ui_elements
    ui_elements.play_ui_sound("click")


def ask_directory(game_state, title, initialdir, on_result):
    """Native folder picker; answers on_result with the chosen path, or None if cancelled."""
    open_file_browser(game_state, title, initialdir, mode="select_folder", on_result=on_result)


def ask_color(game_state, title, initial, on_result):
    """Native color picker; answers on_result with an (r, g, b) tuple, or None if cancelled."""
    from ui.dialogs.color_picker_screen import ColorPickerScreen
    from ui.navigation.screen_runner import _run_pygame_sub_screen
    result = {}
    screen = ColorPickerScreen(game_state, title, initial, lambda color: result.setdefault("color", color))
    _run_pygame_sub_screen(game_state, screen, on_done=lambda: on_result(result.get("color")))
