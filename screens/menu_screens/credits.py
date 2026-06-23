import pygame
import webbrowser
from gameState import GameState
from ui_elements import Button
import data.constants as c
from map_logic.rendering.font_manager import fonts

class Credits(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40) # Midnight Blue

        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_to_menu),
        ]
        
        self.credits_list = []
        font = fonts.get("heading2")
        
        # Calculate positions once to avoid re-calculation in draw loop
        current_y = 150
        for item in c.CREDITS_DATA:
            link_text = item.get("link_text", "")
            main_text = item.get("main_text", "")
            url = item.get("url")
            
            # Fetch width of the main text to position link text to its right
            main_w = font.size(main_text)[0] if main_text else 0
            
            # Setup dedicated rectangles for click masking and drawing
            main_rect = pygame.Rect(200, current_y, main_w, font.get_height())
            link_rect = pygame.Rect(200 + main_w, current_y, font.size(link_text)[0] if link_text else 0, font.get_height())
            
            self.credits_list.append({
                "link_text": link_text,
                "main_text": main_text,
                "url": url,
                "link_rect": link_rect,
                "main_rect": main_rect
            })
            current_y += 50

    def exit_to_menu(self):
        self.next_state = "MENU"
        self.done = True

    def additional_events(self, event):
        # Hook into mouse clicks to make the hyperlinks functional
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for item in self.credits_list:
                if item["url"] and item["link_text"] and item["link_rect"].collidepoint(event.pos):
                    webbrowser.open(item["url"])

    def additional_draw(self, surface):
        font = fonts.get("heading2")
        mouse_pos = pygame.mouse.get_pos()
        
        for item in self.credits_list:
            is_hovered = item["url"] and item["link_text"] and item["link_rect"].collidepoint(mouse_pos)
            link_color = (255, 255, 0) if is_hovered else (100, 100, 255) # Yellow on hover, Blue normal
            
            # Draw Main Text
            if item["main_text"]:
                text_surf = font.render(item["main_text"], True, (255, 255, 255))
                surface.blit(text_surf, item["main_rect"].topleft)

            # Draw Link Text
            if item["link_text"]:
                text_surf = font.render(item["link_text"], True, link_color)
                surface.blit(text_surf, item["link_rect"].topleft)
                
                # Dynamic Underline for active links
                if is_hovered:
                    pygame.draw.line(surface, link_color, 
                                     (item["link_rect"].left, item["link_rect"].bottom - 2), 
                                     (item["link_rect"].right, item["link_rect"].bottom - 2), 2)