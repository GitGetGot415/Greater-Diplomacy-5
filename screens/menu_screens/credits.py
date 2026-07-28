import pygame
import webbrowser
from gameState import GameState
from ui_elements import Button
import data.constants as c
from map_logic.rendering.font_manager import fonts

class Credits(GameState):
    back_state = "MENU"

    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40) # Midnight Blue

        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_screen),
        ]
        
        self.credits_list = []
        font = fonts.get("heading2")
        
        # Calculate positions once to avoid re-calculation in draw loop
        current_y = 150
        for item in c.CREDITS_DATA:
            main_text = item.get("main_text", "")
            people = item.get("people", [])
            
            # Fetch width of the main text to position link text to its right
            main_w = font.size(main_text)[0] if main_text else 0
            main_rect = pygame.Rect(200, current_y, main_w, font.get_height())
            
            credit_entry = {
                "main_text": main_text,
                "main_rect": main_rect,
                "people_links": []
            }
            
            current_x = 200 + main_w
            for i, person in enumerate(people):
                link_text = person.get("link_text", "")
                url = person.get("url")
                
                link_w = font.size(link_text)[0] if link_text else 0
                link_rect = pygame.Rect(current_x, current_y, link_w, font.get_height())
                
                credit_entry["people_links"].append({
                    "link_text": link_text,
                    "url": url,
                    "link_rect": link_rect
                })
                current_x += link_w
                
                # Add comma separator if not the last person
                if i < len(people) - 1:
                    comma_text = ", "
                    comma_w = font.size(comma_text)[0]
                    comma_rect = pygame.Rect(current_x, current_y, comma_w, font.get_height())
                    credit_entry["people_links"].append({
                        "link_text": comma_text,
                        "url": None,
                        "link_rect": comma_rect
                    })
                    current_x += comma_w
                    
            self.credits_list.append(credit_entry)
            current_y += 50

    def additional_events(self, event):
        # Hook into mouse clicks to make the hyperlinks functional
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for item in self.credits_list:
                for person in item.get("people_links", []):
                    if person["url"] and person["link_text"] and person["link_rect"].collidepoint(event.pos):
                        webbrowser.open(person["url"])

    def additional_draw(self, surface):
        font = fonts.get("heading2")
        mouse_pos = pygame.mouse.get_pos()
        
        for item in self.credits_list:
            # Draw Main Text
            if item["main_text"]:
                text_surf = font.render(item["main_text"], True, (255, 255, 255))
                surface.blit(text_surf, item["main_rect"].topleft)

            # Draw Link Text
            for person in item.get("people_links", []):
                if person["link_text"]:
                    # Clickable links
                    if person["url"]:
                        is_hovered = person["link_rect"].collidepoint(mouse_pos)
                        link_color = (255, 255, 0) if is_hovered else (100, 100, 255) # Yellow on hover, Blue normal
                        text_surf = font.render(person["link_text"], True, link_color)
                        surface.blit(text_surf, person["link_rect"].topleft)
                        
                        # Dynamic Underline for active links
                        if is_hovered:
                            pygame.draw.line(surface, link_color, 
                                             (person["link_rect"].left, person["link_rect"].bottom - 2), 
                                             (person["link_rect"].right, person["link_rect"].bottom - 2), 2)
                    # Non-clickable text like comma separators
                    else:
                        text_surf = font.render(person["link_text"], True, (255, 255, 255))
                        surface.blit(text_surf, person["link_rect"].topleft)