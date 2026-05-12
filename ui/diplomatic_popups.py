import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts
from data import queries
import ui_elements

class DiplomaticPopup:
    def __init__(self, sender, text, index):
        self.width = getattr(c, 'POPUP_WIDTH', 450)
        self.height = getattr(c, 'POPUP_HEIGHT', 130)
        
        # Start positions
        start_x = getattr(c, 'POPUP_START_X', (c.SCREEN_WIDTH // 2) - (self.width // 2))
        start_y = getattr(c, 'POPUP_START_Y', 100)
        
        # Cascade offset (cap it so it doesn't push completely off screen)
        offset_step = getattr(c, 'POPUP_OFFSET_STEP', 30)
        max_offset = min(start_x, c.SCREEN_HEIGHT - start_y - self.height)
        total_offset = min(offset_step * index, max_offset)
        
        self.rect = pygame.Rect(start_x + total_offset, start_y + total_offset, self.width, self.height)
        self.x_rect = pygame.Rect(self.rect.right - 30, self.rect.y + 5, 25, 25)

        self.sender = sender
        self.text = text
        self.is_dragging = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0

        self.font_title = fonts.get("heading2")
        self.font_body = fonts.get("small")

    def handle_event(self, event):
        """Returns action string if a state change is needed, otherwise handles internal dragging."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.x_rect.collidepoint(event.pos):
                return "CLOSE"
            elif self.rect.collidepoint(event.pos):
                self.is_dragging = True
                self.drag_offset_x = self.rect.x - event.pos[0]
                self.drag_offset_y = self.rect.y - event.pos[1]
                return "DRAG"
                
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.is_dragging = False
            
        elif event.type == pygame.MOUSEMOTION:
            if self.is_dragging:
                self.rect.x = event.pos[0] + self.drag_offset_x
                self.rect.y = event.pos[1] + self.drag_offset_y
                self.x_rect.x = self.rect.right - 30
                self.x_rect.y = self.rect.y + 5
                return "DRAG"
        return None

    def draw(self, surface):
        # Draw background
        pygame.draw.rect(surface, (40, 40, 50), self.rect)
        pygame.draw.rect(surface, (200, 150, 50), self.rect, 2)

        # Draw close button
        pygame.draw.rect(surface, (150, 0, 0), self.x_rect)
        pygame.draw.rect(surface, (255, 255, 255), self.x_rect, 1)
        x_surf = self.font_body.render("X", True, (255, 255, 255))
        surface.blit(x_surf, (self.x_rect.x + 8, self.x_rect.y + 3))

        # Draw Title
        title_surf = self.font_title.render(f"Diplomatic Alert: {self.sender}", True, (255, 215, 0))
        surface.blit(title_surf, (self.rect.x + 10, self.rect.y + 10))

        # Word wrap logic to prevent text from overflowing the rectangle
        words = self.text.replace("\n", " \n ").split(" ")
        lines = []
        current_line = ""
        max_width = self.width - 20
        
        for word in words:
            if word == "\n":
                lines.append(current_line)
                current_line = ""
            else:
                test_line = current_line + word + " "
                if self.font_body.size(test_line)[0] < max_width:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word + " "
        if current_line:
            lines.append(current_line)

        y_off = self.rect.y + 45
        for line in lines[:4]: # Cap at 4 lines so it doesn't spill out
            line_surf = self.font_body.render(line.strip(), True, (220, 220, 220))
            surface.blit(line_surf, (self.rect.x + 10, y_off))
            y_off += 20


def spawn_popups_for_player(map_screen):
    if not hasattr(map_screen, 'diplomatic_popups'):
        map_screen.diplomatic_popups = []

    if map_screen.player_country in ["None", "Spectator", "Editor"]:
        return

    p_data = map_screen.nation_data.get(map_screen.player_country, {})
    inbox = p_data.get("inbox", [])

    for msg in inbox:
        if msg.get("type") == "DIPLOMACY" and not msg.get("popup_shown", False):
            # Don't show popups for messages the player sent themselves
            if not msg.get("sender", "").startswith("To: "):
                idx = len(map_screen.diplomatic_popups)
                content = msg.get("content", "")
                sender = msg.get("sender", "Unknown")

                # Dynamically append instructions if action requires a bilateral response
                incoming_action, incoming_turns = queries.get_diplomatic_status(sender, map_screen.player_country, map_screen.nation_data)
                if incoming_turns > 0 and incoming_action in c.BILATERAL_ACTIONS:
                    content += "\n(See Messages to accept or decline)"

                popup = DiplomaticPopup(sender, content, idx)
                map_screen.diplomatic_popups.append(popup)
            msg["popup_shown"] = True

def handle_events(map_screen, event):
    if not hasattr(map_screen, 'diplomatic_popups'):
        return False

    # Process from top-most (last in list) to bottom-most
    for i in reversed(range(len(map_screen.diplomatic_popups))):
        popup = map_screen.diplomatic_popups[i]
        res = popup.handle_event(event)
        
        if res == "CLOSE":
            # Hybrid Audio execution for tactile feedback
            if c.USE_SOLOUD and ui_elements.click_sound and ui_elements.soloud_engine and ui_elements.global_sfx_volume > 0:
                handle = ui_elements.soloud_engine.play(ui_elements.click_sound)
                ui_elements.soloud_engine.set_volume(handle, ui_elements.global_sfx_volume)
                ui_elements.soloud_engine.set_relative_play_speed(handle, 0.5 + (ui_elements.global_sfx_pitch * 1.5))
            elif not c.USE_SOLOUD and ui_elements.pygame_click_sound and ui_elements.global_sfx_volume > 0:
                ui_elements.pygame_click_sound.set_volume(ui_elements.global_sfx_volume)
                ui_elements.pygame_click_sound.play()

            map_screen.diplomatic_popups.pop(i)
            return True
            
        elif res == "DRAG":
            # Bring dragged window to front
            if event.type == pygame.MOUSEBUTTONDOWN:
                p = map_screen.diplomatic_popups.pop(i)
                map_screen.diplomatic_popups.append(p)
            return True
            
    return False

def draw(map_screen, surface):
    if not hasattr(map_screen, 'diplomatic_popups'):
        return
    for popup in map_screen.diplomatic_popups:
        popup.draw(surface)

def clear_popups(map_screen):
    map_screen.diplomatic_popups = []