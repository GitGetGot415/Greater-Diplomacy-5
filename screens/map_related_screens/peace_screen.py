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
from map_logic.diplomacy import diplomacy_messages, ratification
from map_logic.rendering import refresh_map
from map_logic.rendering.font_manager import fonts
from ui import text_utils
from ui.bars import ui_bars
from ui.screen_runner import _run_pygame_sub_screen
from ui_elements import make_back_button


class View_Peace_Treaty_Screen(MapOverlayScreen):
    overlay_alpha = 0
    #: The terms box places itself top-left, beside the map it is about.
    CENTER_PANEL = False

    def __init__(self, map_screen, proposer):
        super().__init__(map_screen)
        self.proposer = proposer
        self.target = map_screen.player_country

        # Two ways a treaty can be sitting in front of you: they proposed it, or
        # your own faction leader signed it on your behalf and you are being
        # asked to ratify. The second lives in its own channel -- see
        # map_logic/diplomacy/ratification.py -- so both are looked for here.
        asked = ratification.pending_for(map_screen.nation_data, self.target)
        if asked.get("signatory") == proposer and deal_mod.is_deal(asked.get("deal")):
            params = asked["deal"]
        else:
            pending = diplomacy_messages.get_pending(map_screen.nation_data, proposer, self.target)
            params = pending.get("parameters", pending.get("message", c.PEACE_WHITE_PEACE))

        self.deal = deal_mod.coerce(params, proposer, self.target, kind=deal_mod.KIND_PEACE)
        self.transfers = deal_mod.tile_transfers(self.deal, map_screen.map_data,
                                                 map_screen.nation_data)
        # What the map reverts to underneath the treaty's own transfers. Without
        # it a peace with no land terms previewed as the current front line,
        # when what it actually restores is the pre-war border.
        self.baseline = deal_mod.baseline_owners(self.deal, map_screen.map_data,
                                                 map_screen.nation_data)
        self.terms = deal_mod.describe(self.deal, viewer=self.target,
                                       nation_data=map_screen.nation_data)

        # Wrapped once, here, rather than every frame -- and the panel is sized
        # from the result so that panel_rect is the box the player can actually
        # see. That matters for more than tidiness: MapOverlayScreen routes the
        # mouse wheel to the list only over panel_rect and to the camera
        # everywhere else, so a panel sized to the whole left of the screen
        # would swallow camera panning under empty space, and no panel at all
        # (which is what this screen had) means the wheel never reaches the list.
        self.lines = self._wrapped()
        self.panel_rect = pygame.Rect(
            self.PANEL.x, self.PANEL.y, self.PANEL.width,
            min(self.PANEL.height, self.PAD * 2 + len(self.lines) * self.LINE_H))

        self.elements = [make_back_button(self.exit_screen, style="map")]

    #: The terms panel. Width and top are fixed; the height is whatever is left
    #: of the screen, and the list scrolls inside it.
    PANEL = pygame.Rect(40, 90, 460, c.SCREEN_HEIGHT - 90 - c.BOT_UI_HEIGHT - 20)
    LINE_H = 24
    PAD = 15

    def draw_content(self, surface):
        draw_projected_deal_map(surface, self.map_screen, self.transfers,
                                deal_mod.parties(self.deal), self.baseline)
        ui_bars.draw_centered_title(
            surface, f"Projected Map: Treaty from {self.proposer}", 30)
        self._draw_terms(surface)

    def _wrapped(self):
        """The terms, broken to the panel width.

        They were blitted raw into a 460px box with the height derived from the
        line count and no clip at either edge. A treaty between two blocs names
        every nation bound by it on one line and emits a cede line per giver, so
        the text ran off the right of the panel, off the right of the window, and
        past the bottom of the screen at about twenty-six terms.
        """
        font = fonts.get("normal")
        width = self.PANEL.width - self.PAD * 2
        lines = []
        for term in self.terms:
            lines.extend(text_utils.wrap_text(term, font, width))
        return lines

    def _draw_terms(self, surface):
        if not self.terms:
            return

        font = fonts.get("normal")
        lines = self.lines
        panel = self.panel_rect

        ui_bars.draw_translucent_panel(surface, panel, (*c.HUD_PANEL_BG, 230),
                                       border_color=c.MODAL_BORDER)

        inner_h = panel.height - self.PAD * 2
        clip = pygame.Rect(panel.x + 5, panel.y + self.PAD, panel.width - 10, inner_h)
        self.scroll_content_rect = clip

        with ui_bars.clip_scroll_region(surface, clip,
                                        draw_top=self.scroll_y != 0,
                                        draw_bottom=self.scroll_y > self.max_scroll):
            for i, y in self.layout_list_rows(len(lines), self.LINE_H,
                                              panel.y + self.PAD, view_h=inner_h,
                                              cull_top=panel.y, cull_bottom=panel.bottom):
                surface.blit(font.render(lines[i], True, c.UI_TEXT_LIGHT),
                             (panel.x + self.PAD, y))

        self.draw_list_scrollbar(surface, panel.right - 12, panel.y + self.PAD,
                                 inner_h, width=8)


def draw_projected_deal_map(surface, map_screen, transfers, parties=(), baseline=None):
    """Paints the map as the deal would leave it, coloring only its signatories.

    `baseline` is deal.baseline_owners -- the map the treaty starts from, which
    for a peace is the pre-war border rather than the front line.

    Falls back to the old per-province blobs when nobody says who the parties
    are: a caller with a bare transfer list -- a mod, or the deprecated
    draw_projected_peace_map forwarder -- still gets a picture.
    """
    if parties:
        preview = refresh_map.build_deal_preview_map(map_screen, parties, transfers,
                                                     baseline)
        _draw_swapped_in(surface, map_screen, preview)
        return

    from map_logic.rendering import overlay_renderer

    for prov_id, new_owner in transfers.items():
        prov = map_screen.id_to_province.get(int(prov_id))
        if prov is None or prov.get("owner") == new_owner:
            continue
        color = map_screen.nation_colors.get(new_owner, (255, 255, 255))
        overlay_renderer.draw_map_highlight(surface, map_screen, int(prov_id), color,
                                            base_radius=10)


def _draw_swapped_in(surface, map_screen, preview):
    """Draws one alternative map surface and puts the real one back.

    The renderer reads exactly one attribute -- map_screen.active_map -- so a
    screen shows a different map by swapping it around its own draw call. Same
    move Faction_Territories_Screen makes; the restore is in a finally because
    leaving the player's map pointed at a treaty preview would outlive the
    screen that wanted it.
    """
    previous_layer = map_screen.base_layer
    previous_map = map_screen.active_map
    try:
        map_screen.base_layer = "POLITICAL"
        map_screen.active_map = preview
        map_screen.draw_clean_map_background(surface)
    finally:
        map_screen.base_layer = previous_layer
        map_screen.active_map = previous_map


def open_view_peace_treaty_menu(map_screen, proposer):
    _run_pygame_sub_screen(map_screen, View_Peace_Treaty_Screen(map_screen, proposer))
