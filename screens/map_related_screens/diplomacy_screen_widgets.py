from ui_elements import Button


def build_choice_button(x, y, size, label, enabled, selected, callback, font_preset="button"):
    """One button in a mutually exclusive option row.

    Green when picked, blue when available, greyed and unclickable when not,
    plus the gold selection border. Every option row in these menus (wargoals,
    peace terms, puppet direction, claim view mode) had its own copy of this.
    """
    color = ("green" if selected else "blue") if enabled else "grey"
    btn = Button(x, y, size, color, label, callback, font_preset=font_preset)
    btn.is_selected = selected
    if not enabled:
        btn.apply_state(enabled=False)
    return btn

def build_choice_row(specs, current, on_select, size="medium", font_preset="button"):
    """Builds a whole option row from (x, y, value, label[, enabled]) specs."""
    return [
        build_choice_button(spec[0], spec[1], size, spec[3],
                            spec[4] if len(spec) > 4 else True,
                            spec[2] == current, lambda v=spec[2]: on_select(v),
                            font_preset=font_preset)
        for spec in specs
    ]

def draw_projected_peace_map(surface, map_screen, peace_type, proposer, target):
    """DEPRECATED. Tints every province a treaty would move.

    Took one of the three old peace sentences and re-derived the transfers from
    it with rules that did not match the ones execution used -- this tested
    `prov["id"] in claims` where execute_peace_treaty tested was_original_owner,
    so the preview and the outcome could differ. A deal states its own transfers
    now; see peace_screen.draw_projected_deal_map, which this forwards to.
    """
    from map_logic.diplomacy import deal as deal_mod
    from screens.map_related_screens.peace_screen import draw_projected_deal_map

    agreement = deal_mod.coerce(peace_type, proposer, target, kind=deal_mod.KIND_PEACE)
    transfers = deal_mod.tile_transfers(agreement, map_screen.map_data, map_screen.nation_data)
    draw_projected_deal_map(surface, map_screen, transfers)
