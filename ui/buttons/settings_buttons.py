import pygame
import ui_elements
from ui_elements import Button, Slider
import data.constants as c
from ui.buttons.common import make_option_buttons

# --- Settings screen ---
SETTINGS_RIGHT_COL_X = c.SCREEN_WIDTH - 250
SETTINGS_BACK_POS = (50, 50)
SETTINGS_FULLSCREEN_Y = 40
SETTINGS_CHECKERBOARD_WATER_Y = 100
SETTINGS_FPS_TOGGLE_Y = 160
SETTINGS_DRAG_KEY_Y = 220
SETTINGS_PLAYER_SLIDER_Y = 340
SETTINGS_FPS_SLIDER_Y = 400
SETTINGS_AI_THREAD_SLIDER_POS = (60, 400)
SETTINGS_SLIDER_WIDTH = 200
SETTINGS_RESET_Y = 650
SETTINGS_KEYBIND_ROWS_Y = (470, 530, 590)
SETTINGS_AI_TOGGLE_POS = (10, c.SCREEN_HEIGHT - 60)
SETTINGS_AI_PROVIDER_Y = c.SCREEN_HEIGHT - 250
SETTINGS_AI_PROVIDER_START_X = 10
SETTINGS_AI_PROVIDER_STEP_X = 110
SETTINGS_AI_IMMERSION_X = 10
SETTINGS_AI_IMMERSION_ROWS_Y = (c.SCREEN_HEIGHT - 110, c.SCREEN_HEIGHT - 155, c.SCREEN_HEIGHT - 200)
SETTINGS_CLEAR_BTN_GAP_X = 10
SETTINGS_PATH_EDIT_OFFSET_X = -220
SETTINGS_PATH_RESET_OFFSET_X = -110
SETTINGS_PATH_BOX_X = c.SCREEN_WIDTH // 2 - 150


def render_settings_buttons(settings_screen):
    """Renders the buttons and sliders for the Settings screen."""
    keybind_x = SETTINGS_RIGHT_COL_X

    settings_screen.elements = [
        ui_elements.make_back_button(settings_screen.save_and_go_back, pos=SETTINGS_BACK_POS),
        Button(keybind_x, SETTINGS_FULLSCREEN_Y, "medium", "blue", "Toggle Fullscreen", settings_screen.toggle_full),
        Button(keybind_x, SETTINGS_CHECKERBOARD_WATER_Y, "medium", "green" if settings_screen.checkerboard_water else "red",
               f"Checkerboard Water: {'ON' if settings_screen.checkerboard_water else 'OFF'}", settings_screen.toggle_checkerboard_water),
        Button(keybind_x, SETTINGS_FPS_TOGGLE_Y, "medium", "green" if settings_screen.show_fps else "red",
               f"Show FPS: {'ON' if settings_screen.show_fps else 'OFF'}", settings_screen.toggle_fps),
        Button(keybind_x, SETTINGS_DRAG_KEY_Y, "medium", "purple", f"Drag Key: {settings_screen.drag_mouse_toggle}", settings_screen.toggle_drag_button),
    ]

    # --- MASTER AI TOGGLE BUTTON ---
    ai_is_on = settings_screen.ai_mode != "OFF"
    settings_screen.elements.append(
        Button(*SETTINGS_AI_TOGGLE_POS, "small", "green" if ai_is_on else "red",
               "LLM AI: ON" if ai_is_on else "LLM AI: OFF",
               settings_screen.toggle_ai_enabled, font_preset="normal")
    )

    # --- Only render the sub-options if AI is currently turned ON ---
    if ai_is_on:
        # AI provider picker
        settings_screen.elements.extend(make_option_buttons([
            (SETTINGS_AI_PROVIDER_START_X + i * SETTINGS_AI_PROVIDER_STEP_X, SETTINGS_AI_PROVIDER_Y, mode, mode)
            for i, mode in enumerate(("OLLAMA", "GEMINI", "CHATGPT", "CLAUDE"))
        ], settings_screen.set_ai_mode, settings_screen.ai_mode))

        # AI immersion level picker
        settings_screen.elements.extend(make_option_buttons([
            (SETTINGS_AI_IMMERSION_X, y, level, f"{level} AI")
            for y, level in zip(SETTINGS_AI_IMMERSION_ROWS_Y, ("LITE", "FULL", "ABSOLUTE"))
        ], settings_screen.set_ai_immersion_level, settings_screen.ai_immersion_level, color="red"))

        # --- API KEY & MODEL CLEAR BUTTONS ---
        clear_x = c.SETTINGS_BOX_X + c.SETTINGS_BOX_W + SETTINGS_CLEAR_BTN_GAP_X
        for box_type, box_y in (("KEY", c.SETTINGS_KEY_BOX_Y), ("MOD", c.SETTINGS_MOD_BOX_Y)):
            settings_screen.elements.append(
                Button(clear_x, box_y, "small_square", "red", "X",
                       lambda b=box_type: settings_screen.clear_input(b))
            )

    # Sliders
    settings_screen.player_slider = Slider(keybind_x, SETTINGS_PLAYER_SLIDER_Y, SETTINGS_SLIDER_WIDTH,
                                           f"Players: {settings_screen.num_players}",
                                           (settings_screen.num_players - 1) / 7.0, settings_screen.set_players)
    fps_val = (settings_screen.controller.target_fps - 10) / 50.0
    settings_screen.fps_slider = Slider(keybind_x, SETTINGS_FPS_SLIDER_Y, SETTINGS_SLIDER_WIDTH,
                                        f"Max FPS: {settings_screen.controller.target_fps}", fps_val, settings_screen.set_fps)

    # Render above the player count
    thread_val = (settings_screen.ai_threads - 1) / 7.0
    settings_screen.ai_thread_slider = Slider(*SETTINGS_AI_THREAD_SLIDER_POS, SETTINGS_SLIDER_WIDTH,
                                              f"Maximum AI Threads: {settings_screen.ai_threads}",
                                              thread_val, settings_screen.set_ai_threads)

    # Only show the slider if an AI mode is active
    settings_screen.ai_thread_slider.visible = ai_is_on

    settings_screen.elements.extend([
        settings_screen.ai_thread_slider,
        settings_screen.player_slider,
        settings_screen.fps_slider,
        Button(keybind_x, SETTINGS_RESET_Y, "medium", "red", "Reset Defaults", settings_screen.reset_defaults),
    ])

    # Rebindable keys: label shows the bound key, or the capture prompt while listening
    keybind_rows = zip(SETTINGS_KEYBIND_ROWS_Y,
                       (("FULLSCREEN", "Fullscreen", pygame.K_F11),
                        ("BACK", "Back", pygame.K_ESCAPE),
                        ("ORDERS", "Orders", pygame.K_q)))
    for y, (action, label, default_key) in keybind_rows:
        if settings_screen.listening_for == action:
            text = "Press any key..."
        else:
            key_name = pygame.key.name(settings_screen.controller.keybinds.get(action, default_key)).upper()
            text = f"{label} Key: {key_name}"
        settings_screen.elements.append(
            Button(keybind_x, y, "medium", "grey", text,
                   lambda a=action: settings_screen.start_listening(a))
        )

    # Edit/Reset pair for each path and colour row, driven off the screen's own table
    for y, _kind, key, _label in settings_screen.PATH_ROWS:
        settings_screen.elements.extend([
            Button(SETTINGS_PATH_BOX_X + SETTINGS_PATH_EDIT_OFFSET_X, y, "small", "blue", "Edit", lambda k=key: settings_screen.edit_setting(k)),
            Button(SETTINGS_PATH_BOX_X + SETTINGS_PATH_RESET_OFFSET_X, y, "small", "red", "Reset", lambda k=key: settings_screen.reset_setting(k)),
        ])
