"""Reading a treaty somebody has offered you.

The screen that *built* peace terms lived here too, offering Surrender / Demand
Claims / Ceasefire and nothing else. It is gone: terms are itemized now and
assembled in deal_screen.py, which builds a trade the same way for the same
reason. What is left is the other half -- looking at what has been proposed to
you, on the map, before answering it.

That view used to lie. It read the terms out of `parameters` falling back to
`message`, and an AI's offer carried prose in both, so get_projected_owner found
a string starting with none of the three magic prefixes, concluded from that
that *you* were the winner, and painted every province you had ever claimed as
about to become yours. Then the treaty executed as a white peace and nothing
moved at all. It reads the deal's own transfer list now, which is the same list
deal_effects will act on.
"""

import pygame

import data.constants as c
from gameState import MapOverlayScreen
from map_logic.diplomacy import deal as deal_mod
from map_logic.diplomacy import diplomacy_messages
from map_logic.rendering.font_manager import fonts
from ui.bars import ui_bars
from ui.screen_runner import _run_pygame_sub_screen
from ui_elements import make_back_button


class View_Peace_Treaty_Screen(MapOverlayScreen):
    overlay_alpha = 0

    def __init__(self, map_screen, proposer):
        super().__init__(map_screen)
        self.proposer = proposer
        self.target = map_screen.player_country

        pending = diplomacy_messages.get_pending(map_screen.nation_data, proposer, self.target)
        params = pending.get("parameters", pending.get("message", c.PEACE_WHITE_PEACE))
        self.deal = deal_mod.coerce(params, proposer, self.target, kind=deal_mod.KIND_PEACE)
        self.transfers = deal_mod.tile_transfers(self.deal, map_screen.map_data,
                                                 map_screen.nation_data)
        self.terms = deal_mod.describe(self.deal, viewer=self.target,
                                       nation_data=map_screen.nation_data)

        self.elements = [make_back_button(self.exit_screen, style="map")]

    def draw_content(self, surface):
        draw_projected_deal_map(surface, self.map_screen, self.transfers)
        ui_bars.draw_centered_title(
            surface, f"Projected Map: Treaty from {self.proposer}", 30)
        self._draw_terms(surface)

    def _draw_terms(self, surface):
        if not self.terms:
            return
        font = fonts.get("normal")
        panel = pygame.Rect(40, 90, 460, 30 + len(self.terms) * 24)
        ui_bars.draw_translucent_panel(surface, panel, (*c.HUD_PANEL_BG, 230),
                                       border_color=c.MODAL_BORDER)
        for i, line in enumerate(self.terms):
            surface.blit(font.render(line, True, c.UI_TEXT_LIGHT),
                         (panel.x + 15, panel.y + 15 + i * 24))


def draw_projected_deal_map(surface, map_screen, transfers):
    """Tints every province the deal would move, in its new owner's colour."""
    from map_logic.rendering import overlay_renderer

    for prov_id, new_owner in transfers.items():
        prov = map_screen.id_to_province.get(int(prov_id))
        if prov is None or prov.get("owner") == new_owner:
            continue
        color = map_screen.nation_colors.get(new_owner, (255, 255, 255))
        overlay_renderer.draw_map_highlight(surface, map_screen, int(prov_id), color,
                                            base_radius=10)


def open_view_peace_treaty_menu(map_screen, proposer):
    _run_pygame_sub_screen(map_screen, View_Peace_Treaty_Screen(map_screen, proposer))
