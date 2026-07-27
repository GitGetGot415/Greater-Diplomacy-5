import pygame
import data.constants as c
from ui_elements import Button
from map_logic.rendering.font_manager import fonts
from gameState import GameState
from map_logic.ai.automation_logic import (
    automate_player_construction, clear_player_construction,
    automate_player_movement, clear_player_movement,
    automate_player_research, clear_player_research
)

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
            
        self.confirm_action = None
        self.confirm_text = ""
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen)]
        
        if not self.is_valid_player:
            return

        y_pos = self.panel_rect.y + 100
        row_spacing = 150
        
        options = [
            ("Construction", "construction", automate_player_construction, clear_player_construction),
            ("Troop Movement", "movement", automate_player_movement, clear_player_movement),
            ("Research", "research", automate_player_research, clear_player_research)
        ]
        
        for name, key, auto_func, clear_func in options:
            # 1. Automate Next Turn Checkbox
            is_checked = self.map_screen.nation_data[self.player]["automation"].get(key, False)
            chk_col = "green" if is_checked else "grey"
            btn_chk = Button(self.panel_rect.x + 50, y_pos, "puppet_option", chk_col, "Automate Next Turn", lambda k=key: self.toggle_automation(k), font_preset="normal")
            
            # 2. Clear Button
            btn_clr = Button(self.panel_rect.x + 300, y_pos, "puppet_option", "orange", "Clear", lambda f=clear_func: self.request_confirmation("Clear moves? This will refund/pause everything.", f), font_preset="normal")
            
            # 3. Automate This Turn Button
            btn_run = Button(self.panel_rect.x + 550, y_pos, "puppet_option", "blue", "Automate This Turn", lambda f=auto_func: self.request_confirmation("Automate this turn? May overwrite your current queue/moves.", f), font_preset="normal")
            
            self.elements.extend([btn_chk, btn_clr, btn_run])
            
            y_pos += row_spacing

        # If confirmation is active, add confirmation buttons
        if self.confirm_action:
            c_y = c.SCREEN_HEIGHT // 2 + 100
            self.elements.append(Button(c.SCREEN_WIDTH//2 - 250, c_y, "puppet_option", "red", "Cancel", self.cancel_confirmation, font_preset="normal"))
            self.elements.append(Button(c.SCREEN_WIDTH//2 + 50, c_y, "puppet_option", "green", "Confirm", self.execute_confirmation, font_preset="normal"))

    def toggle_automation(self, key):
        if not self.confirm_action and self.is_valid_player:
            val = self.map_screen.nation_data[self.player]["automation"].get(key, False)
            self.map_screen.nation_data[self.player]["automation"][key] = not val
            self.refresh_ui()
        
    def request_confirmation(self, text, action):
        self.confirm_text = text
        self.confirm_action = action
        self.refresh_ui()
        
    def cancel_confirmation(self):
        self.confirm_action = None
        self.confirm_text = ""
        self.refresh_ui()
        
    def execute_confirmation(self):
        if self.confirm_action and self.is_valid_player:
            self.confirm_action(self.map_screen)
        self.confirm_action = None
        self.confirm_text = ""
        self.refresh_ui()
        
    def exit_screen(self):
        self.done = True
        
    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.exit_screen()
        for element in self.elements:
            element.handle_event(event)

    def draw(self, surface):
        surface.fill(self.bg_color)
        
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
            for element in self.elements:
                element.draw(surface)
            return

        normal_font = fonts.get("normal")
        options = ["Construction", "Troop Movement", "Research"]
        y_pos = self.panel_rect.y + 70
        for name in options:
            lbl_surf = normal_font.render(name, True, (200, 200, 200))
            surface.blit(lbl_surf, (self.panel_rect.centerx - lbl_surf.get_width()//2, y_pos))
            y_pos += 150
            
        for element in self.elements:
            element.draw(surface)
            
        if self.confirm_action:
            # Dim the background
            s = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
            s.set_alpha(180)
            s.fill((0, 0, 0))
            surface.blit(s, (0,0))
            
            # Draw popup box
            box_rect = pygame.Rect(c.SCREEN_WIDTH//2 - 400, c.SCREEN_HEIGHT//2 - 100, 800, 200)
            pygame.draw.rect(surface, (50, 20, 20), box_rect)
            pygame.draw.rect(surface, (200, 50, 50), box_rect, 3)
            
            txt_surf = fonts.get("normal").render(self.confirm_text, True, (255,255,255))
            surface.blit(txt_surf, (c.SCREEN_WIDTH//2 - txt_surf.get_width()//2, c.SCREEN_HEIGHT//2 - 50))
            
            for element in self.elements[-2:]:
                element.draw(surface)
