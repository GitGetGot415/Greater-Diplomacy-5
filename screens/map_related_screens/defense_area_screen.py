"""Army-group defense-area map picker."""

import pygame

import data.constants as c
from data import queries
from gameState import MapOverlayScreen
from map_logic.rendering import overlay_renderer
from map_logic.rendering.font_manager import fonts
from ui_elements import Button


class DefenseAreaScreen(MapOverlayScreen):
    """Select the tiles an army should return to when it has been left idle."""

    overlay_alpha = 0
    CENTER_PANEL = False
    PANEL_TITLE = "Create Defense Area"
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_INFO
    PANEL_SIZE = (540, 145)
    PANEL_TOP = 25
    SELECTION_MARKER_RADIUS = 7
    UNIT_BOX_ALPHA = 150

    def __init__(self, map_screen, army_id):
        panel = pygame.Rect(0, self.PANEL_TOP, *self.PANEL_SIZE)
        panel.centerx = c.SCREEN_WIDTH // 2
        super().__init__(map_screen, panel)
        self.army_id = army_id
        army = self._army()
        self.selected_ids = set(army.get("defense_area", [])) if army else set()
        self.refresh_ui()

    def _army(self):
        return next((army for army in queries.get_armies(
            self.player, self.map_screen.nation_data, self.map_screen.map_data)
                     if army.get("id") == self.army_id), None)

    def refresh_ui(self):
        panel = self.panel_rect
        self.elements = [
            Button(panel.x + 36, panel.bottom - 44, "small", "grey", "Cancel",
                   self.exit_screen, font_preset="normal"),
            Button(panel.centerx - 75, panel.bottom - 44, "small", "orange", "Clear",
                   self.clear_selection, font_preset="normal"),
            Button(panel.right - 224, panel.bottom - 44, "medium", "green", "Confirm",
                   self.confirm, font_preset="normal"),
        ]

    def clear_selection(self):
        self.selected_ids.clear()

    def additional_events(self, event):
        super().additional_events(event)
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and not self.is_over_ui(event.pos)):
            province = self.get_clicked_province(event.pos)
            if province:
                province_id = province["id"]
                if province_id in self.selected_ids:
                    self.selected_ids.remove(province_id)
                else:
                    self.selected_ids.add(province_id)

    def confirm(self):
        if not self.map_screen.can_select_map_units():
            self.map_screen.show_feedback(
                "Turn submitted or unavailable; unsubmit to edit defense areas.")
            return
        army = queries.set_army_defense_area(
            self.player, self.army_id, list(self.selected_ids),
            self.map_screen.nation_data, self.map_screen.map_data)
        if army is None:
            self.map_screen.show_feedback("That army no longer exists.")
            self.exit_screen()
            return
        queued = queries.queue_army_defense_orders(
            self.map_screen, self.player, self.army_id)
        self.map_screen.invalidate_map_presentation_cache()
        tile_word = "tile" if len(army["defense_area"]) == 1 else "tiles"
        self.map_screen.show_feedback(
            f"Defense area saved: {len(army['defense_area'])} {tile_word}; "
            f"{queued} return route(s) queued.")
        self.exit_screen()

    def draw(self, surface):
        # The picker is the only map view that deliberately makes force boxes
        # translucent.  It is an ephemeral rendering flag, restored even if a
        # draw path raises, so ordinary planning presentation stays opaque.
        previous_alpha = getattr(self.map_screen, "_army_order_picker_unit_box_alpha", None)
        self.map_screen._army_order_picker_unit_box_alpha = self.UNIT_BOX_ALPHA
        try:
            super().draw(surface)
        finally:
            if previous_alpha is None:
                del self.map_screen._army_order_picker_unit_box_alpha
            else:
                self.map_screen._army_order_picker_unit_box_alpha = previous_alpha

    def draw_content(self, surface):
        for province_id in self.selected_ids:
            overlay_renderer.draw_map_highlight(
                surface, self.map_screen, province_id, (70, 220, 135),
                base_radius=self.SELECTION_MARKER_RADIUS)
        self.draw_panel(surface)
        text_font = fonts.get("normal")
        army = self._army()
        army_name = army.get("name", "Army") if army else "Army"
        instructions = (
            f"Select tiles for {army_name}. Confirming gives its units return orders now."
        )
        count = f"{len(self.selected_ids)} tile{'s' if len(self.selected_ids) != 1 else ''} selected"
        surface.blit(text_font.render(instructions, True, c.UI_TEXT_LIGHT),
                     (self.panel_rect.x + 24, self.panel_rect.y + 52))
        surface.blit(text_font.render(count, True, c.COLOR_GOLD_HIGHLIGHT),
                     (self.panel_rect.x + 24, self.panel_rect.y + 82))


class FrontlineScreen(MapOverlayScreen):
    """Create a frontline by selecting the two sides of a land border."""

    overlay_alpha = 0
    CENTER_PANEL = False
    PANEL_TITLE = "Create Frontline"
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_INFO
    PANEL_SIZE = (620, 150)
    PANEL_TOP = 25
    SELECTION_MARKER_RADIUS = 8
    FRONTLINE_MARKER_RADIUS = 5
    UNIT_BOX_ALPHA = 150

    def __init__(self, map_screen, army_id):
        panel = pygame.Rect(0, self.PANEL_TOP, *self.PANEL_SIZE)
        panel.centerx = c.SCREEN_WIDTH // 2
        super().__init__(map_screen, panel)
        self.army_id = army_id
        self.home_id = None
        self.target_id = None
        self.refresh_ui()

    def _army(self):
        return next((army for army in queries.get_armies(
            self.player, self.map_screen.nation_data, self.map_screen.map_data)
                     if army.get("id") == self.army_id), None)

    def _target_country(self):
        province = self.map_screen.id_to_province.get(self.target_id)
        return province.get("owner") if province else None

    def _current_frontline_ids(self):
        army = self._army()
        return queries.get_army_frontline_province_ids(
            self.player, army.get("frontline_country") if army else None,
            self.map_screen.map_data)

    def refresh_ui(self):
        panel = self.panel_rect
        self.elements = [
            Button(panel.x + 34, panel.bottom - 44, "small", "grey", "Cancel",
                   self.exit_screen, font_preset="normal"),
            Button(panel.centerx - 73, panel.bottom - 44, "small", "orange", "Clear",
                   self.clear_selection, font_preset="normal"),
            Button(panel.right - 224, panel.bottom - 44, "medium", "green", "Confirm",
                   self.confirm, font_preset="normal"),
        ]

    def clear_selection(self):
        self.home_id = None
        self.target_id = None

    @staticmethod
    def _is_land(province):
        return isinstance(province, dict) and not queries.is_water_province(province)

    def _set_border_side(self, province):
        if not self._is_land(province):
            return
        province_id = province["id"]
        if province.get("owner") == self.player:
            target = self.map_screen.id_to_province.get(self.target_id)
            if target and province_id in target.get("neighbors", []):
                self.home_id = province_id
            else:
                self.home_id, self.target_id = province_id, None
            return
        if (not isinstance(province.get("owner"), str)
                or province.get("owner") in c.UNPLAYABLE_NATIONS):
            return
        home = self.map_screen.id_to_province.get(self.home_id)
        if home and province_id in home.get("neighbors", []):
            self.target_id = province_id
        else:
            self.home_id, self.target_id = None, province_id

    def additional_events(self, event):
        super().additional_events(event)
        if (event.type != pygame.MOUSEBUTTONDOWN or event.button != 1
                or self.is_over_ui(event.pos)):
            return
        province = self.get_clicked_province(event.pos)
        if province is not None:
            self._set_border_side(province)

    def confirm(self):
        if not self.map_screen.can_select_map_units():
            self.map_screen.show_feedback(
                "Turn submitted or unavailable; unsubmit to edit army orders.")
            return
        target_country = self._target_country()
        if self.home_id is not None and self.target_id is not None:
            home = self.map_screen.id_to_province.get(self.home_id)
            target = self.map_screen.id_to_province.get(self.target_id)
            if target is None or home is None or self.target_id not in home.get("neighbors", []):
                self.map_screen.show_feedback("Select two adjacent land tiles across a border.")
                return
        elif self.home_id is not None or self.target_id is not None:
            self.map_screen.show_feedback("Select the adjacent tile on the other side of the border.")
            return
        army = queries.set_army_frontline(
            self.player, self.army_id, target_country,
            self.map_screen.nation_data, self.map_screen.map_data)
        if army is None:
            self.map_screen.show_feedback("That border is no longer valid.")
            return
        if target_country is None:
            queued = (queries.queue_army_defense_orders(
                self.map_screen, self.player, self.army_id)
                      if army.get("order_mode") == c.ARMY_ORDER_DEFENSE else 0)
            self.map_screen.show_feedback(
                f"Frontline cleared; {queued} defense route(s) queued.")
        else:
            queued = queries.queue_army_frontline_orders(
                self.map_screen, self.player, self.army_id)
            country_name = queries.get_country_display_name(
                target_country, self.map_screen.nation_data)
            self.map_screen.show_feedback(
                f"Frontline set against {country_name}; {queued} route(s) queued.")
        self.map_screen.invalidate_map_presentation_cache()
        self.exit_screen()

    def draw(self, surface):
        previous_alpha = getattr(self.map_screen, "_army_order_picker_unit_box_alpha", None)
        self.map_screen._army_order_picker_unit_box_alpha = self.UNIT_BOX_ALPHA
        try:
            super().draw(surface)
        finally:
            if previous_alpha is None:
                del self.map_screen._army_order_picker_unit_box_alpha
            else:
                self.map_screen._army_order_picker_unit_box_alpha = previous_alpha

    def draw_content(self, surface):
        for province_id in self._current_frontline_ids():
            overlay_renderer.draw_map_highlight(
                surface, self.map_screen, province_id, (70, 150, 235),
                base_radius=self.FRONTLINE_MARKER_RADIUS)
        if self.home_id is not None:
            overlay_renderer.draw_map_highlight(
                surface, self.map_screen, self.home_id, (70, 155, 240),
                base_radius=self.SELECTION_MARKER_RADIUS)
        if self.target_id is not None:
            overlay_renderer.draw_map_highlight(
                surface, self.map_screen, self.target_id, (235, 105, 75),
                base_radius=self.SELECTION_MARKER_RADIUS)
        self.draw_panel(surface)
        text_font = fonts.get("normal")
        if self.home_id is None and self.target_id is None:
            instructions = "Click either side of a land border, then click the adjacent tile across it."
            status = "Confirm with no selection to clear the existing frontline."
        elif self.home_id is None or self.target_id is None:
            instructions = "Now click the adjacent land tile on the other side of that border."
            status = "A frontline is created only from two neighboring tiles."
        else:
            country_name = queries.get_country_display_name(
                self._target_country(), self.map_screen.nation_data)
            instructions = f"Border selected against {country_name}."
            status = "Confirm to spread this army along the full shared border."
        surface.blit(text_font.render(instructions, True, c.UI_TEXT_LIGHT),
                     (self.panel_rect.x + 24, self.panel_rect.y + 52))
        surface.blit(text_font.render(status, True, c.COLOR_GOLD_HIGHLIGHT),
                     (self.panel_rect.x + 24, self.panel_rect.y + 82))


class OffensiveOrderScreen(MapOverlayScreen):
    """Choose a multi-tile objective line inside a frontline country."""

    overlay_alpha = 0
    CENTER_PANEL = False
    PANEL_TITLE = "Set Offensive Line"
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_INFO
    PANEL_SIZE = (600, 150)
    PANEL_TOP = 25
    SELECTION_MARKER_RADIUS = 8
    FRONTLINE_MARKER_RADIUS = 5
    UNIT_BOX_ALPHA = 150

    def __init__(self, map_screen, army_id):
        panel = pygame.Rect(0, self.PANEL_TOP, *self.PANEL_SIZE)
        panel.centerx = c.SCREEN_WIDTH // 2
        super().__init__(map_screen, panel)
        self.army_id = army_id
        army = self._army()
        self.selected_ids = set(army.get("offensive_area", [])) if army else set()
        self.refresh_ui()

    def _army(self):
        return next((army for army in queries.get_armies(
            self.player, self.map_screen.nation_data, self.map_screen.map_data)
                     if army.get("id") == self.army_id), None)

    def _frontline_country(self):
        army = self._army()
        return army.get("frontline_country") if army else None

    def _frontline_ids(self):
        country = self._frontline_country()
        return queries.get_army_frontline_province_ids(
            self.player, country, self.map_screen.map_data)

    def refresh_ui(self):
        panel = self.panel_rect
        self.elements = [
            Button(panel.x + 34, panel.bottom - 44, "small", "grey", "Cancel",
                   self.exit_screen, font_preset="normal"),
            Button(panel.centerx - 73, panel.bottom - 44, "small", "orange", "Clear",
                   self.clear_selection, font_preset="normal"),
            Button(panel.right - 224, panel.bottom - 44, "medium", "green", "Confirm",
                   self.confirm, font_preset="normal"),
        ]

    def clear_selection(self):
        self.selected_ids.clear()

    def additional_events(self, event):
        super().additional_events(event)
        if (event.type != pygame.MOUSEBUTTONDOWN or event.button != 1
                or self.is_over_ui(event.pos)):
            return
        province = self.get_clicked_province(event.pos)
        if province is None:
            return
        target_country = self._frontline_country()
        if province.get("owner") != target_country:
            country_name = queries.get_country_display_name(
                target_country, self.map_screen.nation_data)
            self.map_screen.show_feedback(
                f"Choose a province belonging to {country_name}.")
            return
        province_id = province["id"]
        if province_id in self.selected_ids:
            self.selected_ids.remove(province_id)
        else:
            self.selected_ids.add(province_id)

    def confirm(self):
        if not self.map_screen.can_select_map_units():
            self.map_screen.show_feedback(
                "Turn submitted or unavailable; unsubmit to edit army orders.")
            return
        selected_ids = sorted(self.selected_ids, key=str)
        army = queries.set_army_offensive_area(
            self.player, self.army_id, selected_ids,
            self.map_screen.nation_data, self.map_screen.map_data)
        if army is None:
            self.map_screen.show_feedback("The frontline or its target is no longer valid.")
            self.exit_screen()
            return
        queued = (queries.queue_army_offensive_orders(
            self.map_screen, self.player, self.army_id)
                  if self.selected_ids else
                  queries.queue_army_frontline_orders(
                      self.map_screen, self.player, self.army_id))
        self.map_screen.invalidate_map_presentation_cache()
        if not self.selected_ids:
            self.map_screen.show_feedback("Offensive order cleared; army remains on its frontline.")
        else:
            tile_word = "tile" if len(self.selected_ids) == 1 else "tiles"
            self.map_screen.show_feedback(
                f"Offensive line saved: {len(self.selected_ids)} {tile_word}; "
                f"{queued} route(s) queued.")
        self.exit_screen()

    def draw(self, surface):
        previous_alpha = getattr(self.map_screen, "_army_order_picker_unit_box_alpha", None)
        self.map_screen._army_order_picker_unit_box_alpha = self.UNIT_BOX_ALPHA
        try:
            super().draw(surface)
        finally:
            if previous_alpha is None:
                del self.map_screen._army_order_picker_unit_box_alpha
            else:
                self.map_screen._army_order_picker_unit_box_alpha = previous_alpha

    def draw_content(self, surface):
        for province_id in self._frontline_ids():
            overlay_renderer.draw_map_highlight(
                surface, self.map_screen, province_id, (70, 150, 235),
                base_radius=self.FRONTLINE_MARKER_RADIUS)
        for province_id in self.selected_ids:
            overlay_renderer.draw_map_highlight(
                surface, self.map_screen, province_id, (245, 155, 55),
                base_radius=self.SELECTION_MARKER_RADIUS)
        self.draw_panel(surface)
        text_font = fonts.get("normal")
        army = self._army()
        army_name = army.get("name", "Army") if army else "Army"
        target_name = queries.get_country_display_name(
            self._frontline_country(), self.map_screen.nation_data)
        instructions = f"Select one or more target tiles in {target_name} for {army_name}."
        count = len(self.selected_ids)
        status = ("No objective line selected; Confirm keeps the army on its frontline."
                  if not count else
                  f"{count} target {'tile' if count == 1 else 'tiles'} selected; "
                  "the army will spread its advance across them.")
        surface.blit(text_font.render(instructions, True, c.UI_TEXT_LIGHT),
                     (self.panel_rect.x + 24, self.panel_rect.y + 52))
        surface.blit(text_font.render(status, True, c.COLOR_GOLD_HIGHLIGHT),
                     (self.panel_rect.x + 24, self.panel_rect.y + 82))
