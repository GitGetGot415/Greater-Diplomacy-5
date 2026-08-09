import pygame
import data.constants as c
from ui_elements import Button, make_back_button
from map_logic.rendering.font_manager import fonts
from gameState import GameState
from map_logic.ai.automation_logic import (
    automate_player_construction, clear_player_construction,
    automate_player_movement, clear_player_movement,
    automate_player_research, clear_player_research
)

#: label, automation-state key, "do it now" action, "undo it" action.
#: One list: the drawing pass used to carry its own copy of just the labels,
#: which is how a row could be renamed in one place and not the other.
AUTOMATION_OPTIONS = (
    ("Construction", "construction", automate_player_construction, clear_player_construction),
    ("Troop Movement", "movement", automate_player_movement, clear_player_movement),
    ("Research", "research", automate_player_research, clear_player_research),
)

ROW_SPACING = 150


class Automation_Screen(GameState):
    def __init__(self, map_screen):
        super().__init__()
        # Dark red background
        self.bg_color = (60, 20, 20)
        self.map_screen = map_screen
        self.player = map_screen.player_country
        self.panel_rect = pygame.Rect(c.SCREEN_WIDTH//2 - 400, 100, 800, c.SCREEN_HEIGHT - 200)

        self.is_valid_player = self.player in self.map_screen.nation_data and self.player not in ["Spectator", "None", "Editor"]

        # Initialize automation state if not exists
        if self.is_valid_player:
            p_data = self.map_screen.nation_data[self.player]
            if "automation" not in p_data:
                p_data["automation"] = {"construction": False, "movement": False, "research": False}

        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen, style="map")]

        if not self.is_valid_player:
            return

        y_pos = self.panel_rect.y + 100
        for name, key, auto_func, clear_func in AUTOMATION_OPTIONS:
            is_checked = self.map_screen.nation_data[self.player]["automation"].get(key, False)
            chk_col = "green" if is_checked else "grey"
            btn_chk = Button(self.panel_rect.x + 50, y_pos, "automation_option", chk_col, "Automate Next Turn", lambda k=key: self.toggle_automation(k), font_preset="normal")

            btn_clr = Button(self.panel_rect.x + 300, y_pos, "automation_option", "orange", "Clear", lambda f=clear_func: self.confirm_then(f, "Clear moves? This will refund/pause everything."), font_preset="normal")

            btn_run = Button(self.panel_rect.x + 550, y_pos, "automation_option", "blue", "Automate This Turn", lambda f=auto_func: self.confirm_then(f, "Automate this turn? May overwrite your current queue/moves."), font_preset="normal")

            self.elements.extend([btn_chk, btn_clr, btn_run])
            y_pos += ROW_SPACING

    def toggle_automation(self, key):
        if self.is_valid_player:
            val = self.map_screen.nation_data[self.player]["automation"].get(key, False)
            self.map_screen.nation_data[self.player]["automation"][key] = not val
            self.refresh_ui()

    def confirm_then(self, action, question):
        """Asks before running a destructive automation action.

        Was a hand-rolled dimming overlay, box and Cancel/Confirm pair kept in
        `confirm_action`/`confirm_text` on the screen; ask_yes_no is the same
        prompt with Enter/Esc handling and the standard chrome.
        """
        from ui.confirm_dialog import ask_yes_no

        def answered(confirmed):
            if confirmed and self.is_valid_player:
                action(self.map_screen)
            self.refresh_ui()

        ask_yes_no("Automation", question, answered)

    def additional_draw(self, surface):
        # Panel Background
        pygame.draw.rect(surface, (40, 45, 50), self.panel_rect)
        pygame.draw.rect(surface, c.COLOR_DIM_BORDER, self.panel_rect, 3)

        title_font = fonts.get("title")
        title_surf = title_font.render("Automation Settings", True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(title_surf, (self.panel_rect.centerx - title_surf.get_width()//2, self.panel_rect.y + 20))

        if not self.is_valid_player:
            msg_font = fonts.get("normal")
            msg_surf = msg_font.render("Automation is not available in Spectator Mode.", True, (255, 150, 150))
            surface.blit(msg_surf, (self.panel_rect.centerx - msg_surf.get_width()//2, self.panel_rect.centery))
            return

        normal_font = fonts.get("normal")
        y_pos = self.panel_rect.y + 70
        for name, _key, _auto, _clear in AUTOMATION_OPTIONS:
            lbl_surf = normal_font.render(name, True, c.UI_TEXT_LIGHT)
            surface.blit(lbl_surf, (self.panel_rect.centerx - lbl_surf.get_width()//2, y_pos))
            y_pos += ROW_SPACING
