from data import queries
from ui_elements import Button
from map_logic.rendering import overlay_renderer


def build_choice_button(x, y, size, label, enabled, selected, callback):
    """One button in a mutually exclusive option row.

    Green when picked, blue when available, greyed and unclickable when not,
    plus the gold selection border. Every option row in these menus (wargoals,
    peace terms, puppet direction, claim view mode) had its own copy of this.
    """
    color = ("green" if selected else "blue") if enabled else "grey"
    btn = Button(x, y, size, color, label, callback)
    btn.is_selected = selected
    if not enabled:
        btn.apply_state(enabled=False)
    return btn

def build_choice_row(specs, current, on_select, size="medium"):
    """Builds a whole option row from (x, y, value, label[, enabled]) specs."""
    return [
        build_choice_button(spec[0], spec[1], size, spec[3],
                            spec[4] if len(spec) > 4 else True,
                            spec[2] == current, lambda v=spec[2]: on_select(v))
        for spec in specs
    ]

def draw_projected_peace_map(surface, map_screen, peace_type, proposer, target):
    """Tints every province that would change hands if the treaty went through."""
    p_color = map_screen.nation_colors.get(proposer, (0, 255, 0))
    t_color = map_screen.nation_colors.get(target, (255, 0, 0))

    for prov in map_screen.map_data.values():
        curr = prov.get("owner")
        if curr not in (proposer, target):
            continue
        proj = queries.get_projected_owner(prov, peace_type, proposer, target, map_screen.nation_data)
        if proj == curr:
            continue
        color = p_color if proj == proposer else t_color if proj == target else None
        if color:
            overlay_renderer.draw_map_highlight(surface, map_screen, prov["id"], color, base_radius=10)
