import pygame
from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from ui_elements import Button
from map_functions.rendering.font_manager import fonts

class Economy_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (30, 35, 40)
        self.map_screen = None

    def start_economy(self, map_ref):
        self.map_screen = map_ref
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_to_map)]

    def additional_draw(self, surface):
        if not self.map_screen: return
        
        # Title
        font_title = fonts.get("title")
        title = font_title.render("National Economy", True, (255, 255, 255))
        surface.blit(title, (SCREEN_WIDTH // 2 - title.get_width() // 2, 40))
        
        # Grab the projections and data
        total_inc, upkeep = self.map_screen.get_player_economy_projections()
        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        
        font_large = fonts.get("heading1")
        font_med = fonts.get("heading2")
        
        y_offset = 150
        resources = [
            ("Money", p_data.get('money', 0), total_inc.get('money', 0), upkeep.get('money', 0), (255, 215, 0)),
            ("Manpower", p_data.get('manpower', 0), total_inc.get('manpower', 0), upkeep.get('manpower', 0), (100, 200, 255)),
            ("Materials", p_data.get('materials', 0), total_inc.get('materials', 0), upkeep.get('materials', 0), (180, 180, 180)),
            ("Fuel", p_data.get('fuel', 0), total_inc.get('fuel', 0), upkeep.get('fuel', 0), (200, 100, 255))
        ]
        
        for name, current, inc, exp, color in resources:
            net = inc - exp
            net_str = f"+{int(net)}" if net >= 0 else str(int(net))
            
            # Row Background
            row_rect = pygame.Rect(SCREEN_WIDTH // 2 - 400, y_offset, 800, 60)
            pygame.draw.rect(surface, (40, 40, 50), row_rect)
            pygame.draw.rect(surface, (100, 100, 100), row_rect, 1)
            
            # Current Resource Amount
            surface.blit(font_large.render(f"{name}: {int(current)}", True, color), (row_rect.x + 20, row_rect.y + 15))
            
            # Stats Breakdown
            breakdown = f"Income: +{int(inc)}   |   Upkeep: -{int(exp)}   |   Net: {net_str}"
            surface.blit(font_med.render(breakdown, True, (200, 200, 200)), (row_rect.x + 300, row_rect.y + 18))
            
            y_offset += 80

    def handle_back_key(self):
        self.exit_to_map()

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True