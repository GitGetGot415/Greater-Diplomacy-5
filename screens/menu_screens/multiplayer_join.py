import pygame
from gameState import GameState
from ui_elements import Button
import data.constants as c
from map_logic.rendering.font_manager import fonts

class Multiplayer_Join(GameState):
    back_state = "MULTIPLAYER_HUB"

    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40)
        self.elements = [
            Button("centered", "centered", "medium", "blue", "Load Tournament File", self.load_tour_file),
            Button(20, 20, "small", "red", "Back", self.exit_screen)
        ]



    def load_tour_file(self):
        import tkinter as tk
        from tkinter import filedialog, simpledialog
        from data.io import multiplayer_io
        
        root = tk.Tk()
        root.withdraw()
        
        file_path = filedialog.askopenfilename(
            initialdir=c.TOURNAMENT_SAVES_DIR,
            title="Select Tournament File",
            filetypes=[("Tournament Files", "*.gd5tour")]
        )
        if not file_path:
            return
            
        key = simpledialog.askstring("Player Key", "Enter your Country Key:", parent=root)
        if not key:
            return

        self.selected_tournament_path = file_path
        self.selected_tournament_key = key
        self.next_state = "MAP"
        self.done = True



    def draw(self, surface):
        surface.fill(self.bg_color)
        title = "Join Game"
        font = fonts.get("heading1")
        w = font.size(title)[0]
        fonts.draw_text_with_shadow(surface, title, c.SCREEN_WIDTH // 2 - w // 2, 100, "heading1", (255, 255, 255))
        super().draw(surface)
