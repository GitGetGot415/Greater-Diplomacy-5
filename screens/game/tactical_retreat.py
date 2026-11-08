"""Retreat: the map with the tiles a tactical player's unit can fall back to marked.

Opened from the tactical battle preview. Choosing a marked tile gives the unit a move order
there and returns to the map; Back returns to the preview. A unit with no marked tile can
still open this screen and go back.
"""

import pygame

import data.constants as c
from data import queries
from map_logic.actions import unit_actions
from screens.game import map_input
from ui.navigation.screen import Screen
from ui.widgets.ui_elements import Button

MARKER_SIZE = 18
MARKER_HOVER_SIZE = 26
MARKER_COLOR = c.COLOR_GOLD_HIGHLIGHT
MARKER_OUTLINE = (22, 30, 22)


class Tactical_Retreat_Screen(Screen):
    back_state = "CUSTOM_BATTLE"
    title = "Retreat"
    title_y = 12
    title_preset = "heading2"

    def __init__(self):
        super().__init__()
        self.battle = self.campaign = self.routes = None
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_screen, sound_kind="back")]

    def on_enter(self, app, previous):
        self.battle = previous
        self.campaign = previous.campaign
        self.map_screen = self.campaign.map_screen
        self.routes = queries.find_retreat_routes(
            self.campaign.unit, self.campaign.province, self.map_screen.id_to_province,
            self.map_screen.nation_data, context=self.map_screen)

    def _hovered_id(self, position):
        province = queries.get_clicked_province(position, self.map_screen)
        return province["id"] if province and province["id"] in self.routes else None

    def retreat_to(self, province):
        """Order the unit to the tile and leave the encounter; False if the tile is not an option."""
        route = self.routes.get(province["id"])
        if route is None:
            self.map_screen.show_feedback("The unit cannot retreat there.")
            return False
        unit_actions.apply_action(self.map_screen, self.map_screen.player_country,
                                  self.campaign.province, self.campaign.unit,
                                  {"type": "MOVE", "path": route})
        self.map_screen.invalidate_map_presentation_cache()
        self.battle.finish_retreat()
        self.go_to("MAP")
        return True

    def additional_events(self, event):
        map_ref = self.map_screen
        on_ui = any(isinstance(el, Button) and el.rect.collidepoint(getattr(event, "pos", (-1, -1)))
                    for el in self.elements)
        camera = map_ref.camera
        camera.handle_input(event, map_ref, on_ui,
                            pan_buttons=map_input.mouse_buttons_for_map_panning())
        if event.type == pygame.MOUSEBUTTONUP and camera.finish_pan_drag(event.button):
            return
        if (event.type == pygame.MOUSEBUTTONUP and event.button == 1 and not on_ui):
            province = queries.get_clicked_province(event.pos, map_ref)
            if province is not None:
                self.retreat_to(province)

    def additional_draw(self, surface):
        map_ref = self.map_screen
        map_ref.draw_clean_map_background(surface)
        hovered = self._hovered_id(pygame.mouse.get_pos())
        for province_id in self.routes:
            center = queries.world_to_screen(map_ref.id_to_province[province_id]["center"], map_ref)
            size = MARKER_HOVER_SIZE if province_id == hovered else MARKER_SIZE
            marker = pygame.Rect(0, 0, size, size)
            marker.center = (round(center[0]), round(center[1]))
            pygame.draw.rect(surface, MARKER_COLOR, marker)
            pygame.draw.rect(surface, MARKER_OUTLINE, marker, 2)
