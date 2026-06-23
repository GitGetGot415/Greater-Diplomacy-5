import pygame
import webbrowser
import ui_elements
from gameState import GameState
from ui_elements import Button
import data.constants as c
from map_logic.rendering.font_manager import fonts

class Menu(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40) # Midnight Blue
        self.bg_image_path = c.MENU_BG_FILE 

        self.elements = [
            Button("centered", "centered - 120", "medium", "green", "New Game", self.new_game, image=ui_elements.UI_ICONS.get("new_game")),
            Button("centered", "centered - 60", "medium", "green", "Load Game", self.load_game, image=ui_elements.UI_ICONS.get("load_game")),
            Button("centered", "centered + 0", "medium", "green", "Map Editor", self.map_editor, image=ui_elements.UI_ICONS.get("map_editor")),
            Button("centered", "centered + 60", "medium", "orange", "Credits", self.credits, image=ui_elements.UI_ICONS.get("credits")),
            Button("centered", "centered + 120", "medium", "blue", "Music Player", self.music_player, image=ui_elements.UI_ICONS.get("music")),
            Button("centered", "centered + 180", "medium", "grey", "Settings", self.settings, image=ui_elements.UI_ICONS.get("settings"))
        ]
        
        self.bottom_texts = []
        font = fonts.get("heading2")
        
        current_y = c.MENU_BOTTOM_TEXT_START_Y
        for item in c.MENU_BOTTOM_TEXTS:
            link_text = item.get("link_text", "")
            main_text = item.get("main_text", "")
            url = item.get("url")
            
            # Fetch width of the main text to correctly offset the link text to its right
            main_w = font.size(main_text)[0] if main_text else 0
            
            # Setup dedicated rectangles for click masking and isolated drawing
            main_rect = pygame.Rect(c.MENU_BOTTOM_TEXT_START_X, current_y, main_w, font.get_height())
            link_rect = pygame.Rect(c.MENU_BOTTOM_TEXT_START_X + main_w, current_y, font.size(link_text)[0] if link_text else 0, font.get_height())
            
            self.bottom_texts.append({
                "link_text": link_text,
                "main_text": main_text,
                "url": url,
                "link_rect": link_rect,
                "main_rect": main_rect
            })
            current_y += c.MENU_BOTTOM_TEXT_STEP_Y

    def additional_events(self, event):
        # We hook into mouse clicks here to make the hyperlinks functional
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for item in self.bottom_texts:
                if item["url"] and item["link_text"] and item["link_rect"].collidepoint(event.pos):
                    webbrowser.open(item["url"])
                    
                    # Play the UI click sound for auditory feedback
                    from data import queries
                    queries.play_click_sound()

    def additional_draw(self, surface):
        font = fonts.get("heading2")
        mouse_pos = pygame.mouse.get_pos()
        
        for item in self.bottom_texts:
            is_hovered = item["url"] and item["link_text"] and item["link_rect"].collidepoint(mouse_pos)
            link_color = c.MENU_BOTTOM_TEXT_HOVER_COLOR if is_hovered else c.MENU_BOTTOM_TEXT_LINK_COLOR
            
            # --- Draw the Main Chunk (Now on the Left) ---
            if item["main_text"]:
                fonts.draw_text_with_shadow(surface, item["main_text"], item["main_rect"].x, item["main_rect"].y, "heading2", c.MENU_BOTTOM_TEXT_COLOR)

            # --- Draw the Link Chunk (Now on the Right) ---
            if item["link_text"]:
                fonts.draw_text_with_shadow(surface, item["link_text"], item["link_rect"].x, item["link_rect"].y, "heading2", link_color)
                
                # Dynamic Underline for hovered active links
                if is_hovered:
                    pygame.draw.line(surface, link_color, (item["link_rect"].left, item["link_rect"].bottom - 2), (item["link_rect"].right, item["link_rect"].bottom - 2), 2)

    def new_game(self):
        self.next_state = "NEW_GAME"
        self.done = True

    def load_game(self):
        self.next_state = "LOAD_GAME"
        self.done = True

    def credits(self):
        self.next_state = "CREDITS"
        self.done = True

    def music_player(self):
        self.next_state = "MUSIC_PLAYER"
        self.done = True

    def settings(self):
        self.next_state = "SETTINGS"
        self.done = True

    def map_editor(self):
        self.next_state = "SELECT_BASE_MAP"
        self.done = True
