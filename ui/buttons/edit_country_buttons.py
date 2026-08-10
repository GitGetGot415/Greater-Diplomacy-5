import ui_elements
from ui_elements import Button
import data.constants as c

# --- Edit Country screen ---
EDIT_COUNTRY_SWITCH_BTN_X = 350
EDIT_COUNTRY_SWITCH_BTN_Y = 20
EDIT_COUNTRY_CANCEL_POS = (20, 20)
EDIT_COUNTRY_SAVE_POS = (140, 20)
EDIT_COUNTRY_ICON_STEP_X = 50   # Export/Import/Reset triplets
EDIT_COUNTRY_RESET_OFFSET_X = 100
EDIT_COUNTRY_FLAG_ROW_Y = 400
EDIT_COUNTRY_PORTRAIT_ROW_Y = 520
EDIT_COUNTRY_TOOLS_ROW_Y = 375
EDIT_COUNTRY_UNDO_ROW_Y = 425
EDIT_COUNTRY_MAP_COLOR_Y = 600
EDIT_COUNTRY_RESET_COLOR_POS = (c.SCREEN_WIDTH - 330, 550)
EDIT_COUNTRY_SWATCH_START_Y = 150
EDIT_COUNTRY_SWATCH_STEP = 45
EDIT_COUNTRY_SWATCH_COLUMNS = 8
EDIT_COUNTRY_SIDE_TOOL_OFFSET_X = 225
EDIT_COUNTRY_BRUSH_COLOR_Y = 60
EDIT_COUNTRY_NULL_COLOR_Y = 105


def render_edit_country_buttons(edit_screen):
    """Renders the buttons for the Edit Country Screen."""
    icons = ui_elements.UI_ICONS
    edit_screen.elements = []

    edit_screen.btn_cancel = Button(*EDIT_COUNTRY_CANCEL_POS, "small", "red", "Cancel", edit_screen.exit_screen)
    edit_screen.btn_save = Button(*EDIT_COUNTRY_SAVE_POS, "medium", "green", "Save Changes", edit_screen.save_and_exit)

    # Switch country graphics configuration handler
    edit_screen.btn_switch_appearance = Button(
        EDIT_COUNTRY_SWITCH_BTN_X,
        EDIT_COUNTRY_SWITCH_BTN_Y,
        "medium", "orange", "Switch Appearance",
        edit_screen.open_switch_appearance_menu
    )

    # Flag and portrait rows are the same Export / Import / Reset triplet, so
    # they come off one spec rather than six near-identical lines.
    for column_x, row_y, kind, attr in ((c.EDIT_COUNTRY_UI_X1, EDIT_COUNTRY_FLAG_ROW_Y, "flag", "flag"),
                                        (c.EDIT_COUNTRY_UI_X2, EDIT_COUNTRY_PORTRAIT_ROW_Y, "portrait", "port")):
        label = kind.capitalize()
        setattr(edit_screen, "btn_exp_" + attr, Button(
            column_x, row_y, "small_square", "blue", "Export " + label,
            getattr(edit_screen, "export_" + kind), image=icons.get("export"), show_text=False))
        setattr(edit_screen, "btn_imp_" + attr, Button(
            column_x + EDIT_COUNTRY_ICON_STEP_X, row_y, "small_square", "green", "Import " + label,
            getattr(edit_screen, "import_" + kind), image=icons.get("import"), show_text=False))
        setattr(edit_screen, "btn_reset_" + attr, Button(
            column_x + EDIT_COUNTRY_RESET_OFFSET_X, row_y, "small", "red", "Reset",
            lambda k=kind: edit_screen.trigger_reset(k.upper())))

    edit_screen.btn_reset_map_color = Button(*EDIT_COUNTRY_RESET_COLOR_POS, "small", "red", "Reset Color", edit_screen.reset_map_color)

    edit_screen.elements.extend([
        edit_screen.btn_cancel, edit_screen.btn_save, edit_screen.btn_switch_appearance,
        edit_screen.btn_exp_flag, edit_screen.btn_imp_flag, edit_screen.btn_reset_flag,
        edit_screen.btn_exp_port, edit_screen.btn_imp_port, edit_screen.btn_reset_port,
        edit_screen.btn_reset_map_color
    ])

    for i, color in enumerate(edit_screen.palette):
        x = c.EDIT_COUNTRY_UI_X3 + (i % EDIT_COUNTRY_SWATCH_COLUMNS) * EDIT_COUNTRY_SWATCH_STEP
        y = EDIT_COUNTRY_SWATCH_START_Y + (i // EDIT_COUNTRY_SWATCH_COLUMNS) * EDIT_COUNTRY_SWATCH_STEP
        btn = Button(x, y, "small_square", "grey", "", lambda c_val=color: edit_screen.set_color(c_val), show_text=False)
        btn.set_colors(color)
        btn.shading = False
        edit_screen.elements.append(btn)

    # Drawing tools are a one-of-three picker; the active tool shows blue
    for slot, (tool, label, icon_name) in enumerate((("PICKER", "Color Picker", "color_picker"),
                                                    ("BRUSH", "Brush", "brush"),
                                                    ("FILL", "Fill", "paint"))):
        edit_screen.elements.append(
            Button(c.EDIT_COUNTRY_UI_X3 + slot * EDIT_COUNTRY_ICON_STEP_X, EDIT_COUNTRY_TOOLS_ROW_Y, "small_square",
                   "blue" if edit_screen.draw_mode == tool else "grey", label,
                   lambda t=tool: edit_screen.set_tool(t), image=icons.get(icon_name), show_text=False)
        )

    side_tool_x = c.EDIT_COUNTRY_UI_X3 + EDIT_COUNTRY_SIDE_TOOL_OFFSET_X
    edit_screen.elements.extend([
        Button(c.EDIT_COUNTRY_UI_X3, EDIT_COUNTRY_UNDO_ROW_Y, "small_square", "grey", "Undo", edit_screen.undo),
        Button(c.EDIT_COUNTRY_UI_X3 + EDIT_COUNTRY_ICON_STEP_X, EDIT_COUNTRY_UNDO_ROW_Y, "small_square", "grey", "Redo", edit_screen.redo),
        Button(c.EDIT_COUNTRY_UI_X3 + EDIT_COUNTRY_RESET_OFFSET_X, EDIT_COUNTRY_MAP_COLOR_Y, "small", "orange", "Map Color", edit_screen.pick_map_color),
        Button(side_tool_x, EDIT_COUNTRY_BRUSH_COLOR_Y, "small_square", "light_grey", "Brush Color", edit_screen.pick_custom_brush_color, image=icons.get("colors"), show_text=False),
        Button(side_tool_x, EDIT_COUNTRY_NULL_COLOR_Y, "small_square", "light_grey", "Null Color", lambda: edit_screen.set_color((0, 0, 0, 0)), image=icons.get("red_line"), show_text=False)
    ])
