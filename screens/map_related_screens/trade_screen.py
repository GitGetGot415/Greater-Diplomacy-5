import pygame
import data.constants as c
from data import queries
from map_logic.diplomacy import diplomacy_messages
from gameState import MapOverlayScreen
from ui_elements import Button, draw_text_box
from map_logic.rendering.font_manager import fonts
from ui.bars import resource_hud
from ui.screen_runner import _run_pygame_sub_screen
from screens.map_related_screens.diplomacy_screen_widgets import build_choice_row


class Trade_Screen(MapOverlayScreen):
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_CONFIRM

    # Which text attribute each of the four number boxes edits.
    FIELD_ATTRS = {
        "GIVE_MATS": "give_mats_str",
        "GIVE_FUEL": "give_fuel_str",
        "TAKE_MATS": "take_mats_str",
        "TAKE_FUEL": "take_fuel_str",
    }

    def __init__(self, map_screen, target_nation):
        super().__init__(map_screen, pygame.Rect(c.SCREEN_WIDTH//2 - 300, c.SCREEN_HEIGHT//2 - 220, 600, 420))
        self.target_nation = target_nation

        # State tracking for inputs
        self.give_mats_str = "0"
        self.give_fuel_str = "0"
        self.take_mats_str = "0"
        self.take_fuel_str = "0"

        self.puppet_state = "NONE" # "SENDER", "NONE", "RECEIVER"

        # Escrow trackers (resources removed from the player while the offer is pending)
        self.escrow_mats = 0
        self.escrow_fuel = 0

        self.active_input = None
        self.refresh_ui()

    def set_puppet_state(self, state):
        self.puppet_state = state
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Cancel", self.cancel_trade)]
        self.elements.append(Button(self.panel_rect.centerx - 100, self.panel_rect.bottom - 60, "medium", "green", "Confirm Trade", self.confirm_trade))

        # Puppet Options
        y_pos = self.panel_rect.y + 220

        my_master = self.map_screen.nation_data.get(self.map_screen.player_country, {}).get("master", "")
        their_master = self.map_screen.nation_data.get(self.target_nation, {}).get("master", "")
        # A nation already in a puppet relationship can't change direction here
        can_puppet = not (my_master or their_master)

        self.elements.extend(build_choice_row([
            (self.panel_rect.x + 30, y_pos, "SENDER", "Make Them Puppet", can_puppet),
            (self.panel_rect.centerx - 100, y_pos, "NONE", "No Puppeting", True),
            (self.panel_rect.right - 230, y_pos, "RECEIVER", "Become Their Puppet", can_puppet),
        ], self.puppet_state, self.set_puppet_state))

    def evaluate_input(self):
        """Processes typed text, applies clamps, and secures/refunds the escrow safely."""
        p_data = self.map_screen.nation_data[self.map_screen.player_country]

        # Give Materials
        try:
            val_mats = int(self.give_mats_str)
            if val_mats < 0: val_mats = 0
        except ValueError:
            val_mats = 0

        p_data["materials"] = p_data.get("materials", 0) + self.escrow_mats
        taken_mats = min(val_mats, p_data["materials"])
        p_data["materials"] -= taken_mats
        self.escrow_mats = taken_mats
        self.give_mats_str = str(taken_mats)

        # Give Fuel
        try:
            val_fuel = int(self.give_fuel_str)
            if val_fuel < 0: val_fuel = 0
        except ValueError:
            val_fuel = 0

        p_data["fuel"] = p_data.get("fuel", 0) + self.escrow_fuel
        taken_fuel = min(val_fuel, p_data["fuel"])
        p_data["fuel"] -= taken_fuel
        self.escrow_fuel = taken_fuel
        self.give_fuel_str = str(taken_fuel)

        # Take Inputs (No limits, they can ask for a billion if they want)
        try:
            val_take_mats = int(self.take_mats_str)
            if val_take_mats < 0: val_take_mats = 0
            self.take_mats_str = str(val_take_mats)
        except ValueError:
            self.take_mats_str = "0"

        try:
            val_take_fuel = int(self.take_fuel_str)
            if val_take_fuel < 0: val_take_fuel = 0
            self.take_fuel_str = str(val_take_fuel)
        except ValueError:
            self.take_fuel_str = "0"

    def confirm_trade(self):

        self.evaluate_input()

        # Don't allow empty trades
        if self.escrow_mats == 0 and self.escrow_fuel == 0 and self.take_mats_str == "0" and self.take_fuel_str == "0" and self.puppet_state == "NONE":
            self.map_screen.show_feedback("Cannot send an empty trade offer!")
            return

        diplomacy_messages.set_pending(
            self.map_screen.nation_data, self.map_screen.player_country, self.target_nation, "TRADE",
            parameters={
                "give_materials": self.escrow_mats,
                "give_fuel": self.escrow_fuel,
                "take_materials": int(self.take_mats_str),
                "take_fuel": int(self.take_fuel_str),
                "puppet_state": self.puppet_state
            },
            message=f"TRADE PROPOSAL:\nGive: {self.escrow_mats} Mat, {self.escrow_fuel} Fuel\nTake: {self.take_mats_str} Mat, {self.take_fuel_str} Fuel\nPuppet Terms: {self.puppet_state}"
        )

        self.map_screen.show_feedback("Trade Offer Sent!")
        self.done = True

    def cancel_trade(self):
        # Refund any held resources cleanly
        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        queries.cancel_trade_escrow(p_data, {"give_materials": self.escrow_mats, "give_fuel": self.escrow_fuel})
        self.done = True

    def handle_back_key(self):
        # Escape backs out of a focused number box first, then out of the screen.
        if self.active_input:
            self.active_input = None
        else:
            self.cancel_trade()

    def input_rects(self):
        """The four number boxes, keyed by the field they edit."""
        return {
            "GIVE_MATS": pygame.Rect(self.panel_rect.x + 130, self.panel_rect.y + 100, 120, 30),
            "GIVE_FUEL": pygame.Rect(self.panel_rect.x + 130, self.panel_rect.y + 150, 120, 30),
            "TAKE_MATS": pygame.Rect(self.panel_rect.x + 430, self.panel_rect.y + 100, 120, 30),
            "TAKE_FUEL": pygame.Rect(self.panel_rect.x + 430, self.panel_rect.y + 150, 120, 30),
        }

    def additional_events(self, event):
        from ui_elements import process_text_input
        super().additional_events(event)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hit = next((key for key, rect in self.input_rects().items() if rect.collidepoint(event.pos)), None)
            if not hit:
                self.evaluate_input()
            self.active_input = hit

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                self.evaluate_input()
                self.active_input = None
            elif self.active_input:
                attr = self.FIELD_ATTRS[self.active_input]
                text, status = process_text_input(event, getattr(self, attr),
                                                  validation_func=lambda ch: ch.isdigit() or ch == "-")
                setattr(self, attr, text)
                if status == "CANCEL":
                    self.active_input = None

    def get_panel_title(self):
        return f"Trade Agreement: {self.target_nation}"

    def draw_content(self, surface):
        self.draw_panel(surface)

        font_med = fonts.get("heading2")
        font_small = fonts.get("normal")

        # You Give Section
        surface.blit(font_med.render("You Give:", True, (255, 100, 100)), (self.panel_rect.x + 30, self.panel_rect.y + 60))
        surface.blit(font_small.render("Materials:", True, c.UI_TEXT_LIGHT), (self.panel_rect.x + 30, self.panel_rect.y + 105))
        surface.blit(font_small.render("Fuel:", True, c.UI_TEXT_LIGHT), (self.panel_rect.x + 30, self.panel_rect.y + 155))

        # They Give Section
        surface.blit(font_med.render("They Give:", True, c.COLOR_SUCCESS_GREEN), (self.panel_rect.centerx + 30, self.panel_rect.y + 60))
        surface.blit(font_small.render("Materials:", True, c.UI_TEXT_LIGHT), (self.panel_rect.centerx + 30, self.panel_rect.y + 105))
        surface.blit(font_small.render("Fuel:", True, c.UI_TEXT_LIGHT), (self.panel_rect.centerx + 30, self.panel_rect.y + 155))

        # Puppet Header
        surface.blit(font_med.render("Puppeting Terms:", True, c.COLOR_GOLD_HIGHLIGHT), (self.panel_rect.centerx - 80, self.panel_rect.y + 190))

        # Draw Input Boxes
        for key, rect in self.input_rects().items():
            draw_text_box(surface, rect, getattr(self, self.FIELD_ATTRS[key]),
                          active=self.active_input == key, font=font_small, pad_x=5)

    def draw(self, surface):
        super().draw(surface)

        resource_hud.draw_resource_bar(surface, self.map_screen)


def open_trade_menu(map_screen, target_nation):
    _run_pygame_sub_screen(map_screen, Trade_Screen(map_screen, target_nation))
