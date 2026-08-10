from ui_elements import Button


def make_option_buttons(options, on_select, current, size="small", color="blue", font_preset="button"):
    """Builds a row/column of mutually exclusive buttons with the active one highlighted.

    Options are (x, y, value, label) tuples. Used for every "pick exactly one
    of these" cluster (AI provider, immersion level, wargoal, peace term...) so
    the gold selection border and the callback binding are done identically.
    """
    built = []
    for x, y, value, label in options:
        btn = Button(x, y, size, color, label, lambda v=value: on_select(v), font_preset=font_preset)
        btn.is_selected = (value == current)
        built.append(btn)
    return built
