import pygame
from gameState import GameState
from ui_elements import Button
import data.constants as c
from map_logic.rendering.font_manager import fonts

class Multiplayer_Hub(GameState):
    back_state = "MENU"

    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40)
        self.elements = [
            Button("centered", 250, "medium", "green", "Host Game", self.host_game),
            Button("centered", 350, "medium", "blue", "Join Game", self.join_game),
            Button(20, 20, "small", "red", "Back", self.exit_screen),
            Button(c.SCREEN_WIDTH - 120, 20, "small", "blue", "Help", self.show_help)
        ]

    def show_help(self):
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        help_text = (
            "Tournaments allow for asynchronous multiplayer gameplay.\n\n"
            "Host: Create a new tournament, distribute the generated .gd5tour file and the player keys to your friends. "
            "When they send back their .gd5move files, load the tournament and load their moves in the Manage Players panel. "
            "Then process the turn and send the updated .gd5tour file back to them.\n\n"
            "Player: Use 'Join Game' to load the .gd5tour file using your player key. "
            "Submit your orders and click 'Export Turn' to generate a .gd5move file, and send it to the host."
        )
        messagebox.showinfo("Tournament Help", help_text)



    def host_game(self):
        self.next_state = "MULTIPLAYER_HOST"
        self.done = True

    def join_game(self):
        self.next_state = "MULTIPLAYER_JOIN"
        self.done = True



    def draw(self, surface):
        surface.fill(self.bg_color)
        title_text = "Asynchronous Multiplayer"
        font = fonts.get("heading1")
        w = font.size(title_text)[0]
        fonts.draw_text_with_shadow(surface, title_text, c.SCREEN_WIDTH // 2 - w // 2, 100, "heading1", (255, 255, 255))
        super().draw(surface)
