# screens/map_related_screens/edit_country.py
import pygame
import base64
import os
from pathlib import Path
import tkinter as tk 
from tkinter import colorchooser 
from gameState import GameState
from ui_elements import Button
from map_functions.rendering.font_manager import fonts

right_ui_x = 1150
input_box_x = 100

# Helper functions for encoding/decoding surfaces to JSON strings
def encode_surf(surf):
    img_str = pygame.image.tostring(surf, "RGB")
    return base64.b64encode(img_str).decode('utf-8')

def decode_surf(b64_str, size):
    try:
        img_bytes = base64.b64decode(b64_str)
        return pygame.image.fromstring(img_bytes, size, "RGB")
    except:
        surf = pygame.Surface(size)
        surf.fill((255, 255, 255))
        return surf

class Edit_Country_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (30, 30, 40)
        self.map_screen = None
        
        # Dimensions
        self.flag_size = (60, 40)
        self.portrait_size = (60, 60)
        
        # Scaled drawing constraints
        self.flag_scale = 8
        self.portrait_scale = 8
        
        self.flag_rect = pygame.Rect(50, 150, self.flag_size[0] * self.flag_scale, self.flag_size[1] * self.flag_scale)
        self.portrait_rect = pygame.Rect(600, 150, self.portrait_size[0] * self.portrait_scale, self.portrait_size[1] * self.portrait_scale)
        
        self.flag_surf = pygame.Surface(self.flag_size)
        self.portrait_surf = pygame.Surface(self.portrait_size)
        self.flag_surf.fill((255, 255, 255))
        self.portrait_surf.fill((255, 255, 255))
        
        # Editor State
        self.active_color = (0, 0, 0)
        self.draw_mode = "BRUSH" # Can be "BRUSH" or "FILL"
        self.active_input = None # "COUNTRY_NAME", "NAME", or "TITLE"
        
        self.country_name = ""
        self.leader_name = ""
        self.leader_title = ""
        self.new_map_color = [150, 150, 150]
        
        # https://smilebasic.com/en/e-manual/manual28/
        self.palette = [
            (0,0,0),            # Black
            (32,32,32),         # Very Dark Grey
            (64,64,64),         # Dark Grey
            (96,96,96),         # Darkish Grey
            (128,128,128),      # Grey
            (196,196,196),      # Light Grey
            (220,220,220),      # Very Light Grey
            (255,255,255),      # White
            
            (255,96,96),        # Light Red
            (255,200,20),       # Light Orange
            (255,255,128),      # Light Yellow
            (96,255,128),       # Lime
            (128,255,255),      # Light Indigo
            (64,64,255),        # Light Blue
            (200,64,255),       # Light Purple
            (255,128,255),      # Light Pink

            (255,0,0),          # Red
            (255,160,16),       # Orange
            (255,255,32),       # Yellow
            (0,192,0),          # Green
            (80,200,255),       # Indigo
            (0,0,255),          # Blue
            (160,32,255),       # Purple
            (255,96,208),       # Pink
            
            (196,0,0),          # Dark Red
            (200,120,12),       # Dark Orange
            (200,200,0),        # Dark Yellow
            (0,128,0),          # Dark Green
            (60,160,200),       # Dark Indigo
            (0,0,196),          # Dark Blue
            (120,16,200),       # Dark Purple
            (200,80,160),       # Dark Pink

            # (160,128,96),       # Oak Tree
            # (255,208,160),      # White Skin

            (128,0,0),          # Very Dark Red
            (160,80,10),        # Brown
            (128,128,0),        # Very Dark Yellow
            (0,64,0),           # Very Dark Green
            (32,128,160),       # Very Dark Indigo
            (0,0,128),          # Very Dark Blue
            (80,12,160),        # Very Dark Purple
            (160,60,120),       # Very Dark Pink

            # (128,0,128),        # Austria-Hungary
        ]

    def start_editor(self, map_ref):
        self.map_screen = map_ref
        
        # Load existing data
        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        self.country_name = p_data.get("name", self.map_screen.player_country)
        self.leader_name = p_data.get("leader_name", "")
        self.leader_title = p_data.get("leader_title", "")
        self.new_map_color = list(p_data.get("color", [150, 150, 150]))

        if p_data.get("flag_data"):
            self.flag_surf = decode_surf(p_data["flag_data"], self.flag_size)
        else:
            self.flag_surf.fill((255, 255, 255))
            
        if p_data.get("portrait_data"):
            self.portrait_surf = decode_surf(p_data["portrait_data"], self.portrait_size)
        else:
            self.portrait_surf.fill((255, 255, 255))
            
        self.refresh_ui()

    def pick_map_color(self):
        """Opens a native color picker to select the country's map color."""
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True) # Keeps it above the Pygame window
        
        color_code = colorchooser.askcolor(title="Choose Map Color", initialcolor=tuple(self.new_map_color))
        
        if color_code[0]: # If they didn't click cancel
            self.new_map_color = [int(c) for c in color_code[0]]
            
        root.destroy()
        pygame.event.pump() # Clears any phantom mouse clicks Tkinter leaves behind

    def pick_custom_brush_color(self):
        """Opens a native color picker to select a custom drawing color."""
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True) 
        
        color_code = colorchooser.askcolor(title="Choose Brush Color", initialcolor=tuple(self.active_color))
        
        if color_code[0]: 
            self.active_color = tuple(int(c) for c in color_code[0])
            
        root.destroy()
        pygame.event.pump()
        
    def export_flag(self):
        downloads_path = str(Path.home() / "Downloads")
        safe_name = "".join(c for c in self.country_name if c.isalnum() or c in " _-") or "Flag"
        export_path = os.path.join(downloads_path, f"{safe_name}_flag.png")
        try:
            pygame.image.save(self.flag_surf, export_path)
            self.map_screen.show_feedback(f"Exported to Downloads")
        except Exception as e:
            self.map_screen.show_feedback("Failed to export")

    def export_portrait(self):
        downloads_path = str(Path.home() / "Downloads")
        safe_name = "".join(c for c in self.country_name if c.isalnum() or c in " _-") or "Portrait"
        export_path = os.path.join(downloads_path, f"{safe_name}_portrait.png")
        try:
            pygame.image.save(self.portrait_surf, export_path)
            self.map_screen.show_feedback(f"Exported to Downloads")
        except Exception as e:
            self.map_screen.show_feedback("Failed to export")

    def refresh_ui(self):
        self.elements = [
            Button(20, 20, "small", "red", "Cancel", self.exit_to_map),
            Button(140, 20, "medium", "green", "Save Changes", self.save_and_exit)
        ]
        
        # Export Buttons
        self.elements.append(Button(50, 490, "medium", "blue", "Export Flag", self.export_flag))
        self.elements.append(Button(600, 670, "medium", "blue", "Export Portrait", self.export_portrait))
        
        # Build Palette Buttons
        for i, color in enumerate(self.palette):
            colors_per_row = 8
            space_between_colors = 45
            x = right_ui_x + (i % colors_per_row) * space_between_colors
            y = 150 + (i // colors_per_row) * space_between_colors
            btn = Button(x, y, "small_square", "grey", "", lambda c=color: self.set_color(c), show_text=False)
            btn.color = btn.hover_color = color
            btn.shading = False
            self.elements.append(btn)

        # Tool Selection Buttons
        brush_color = "blue" if self.draw_mode == "BRUSH" else "grey"
        fill_color = "blue" if self.draw_mode == "FILL" else "grey"
        
        self.elements.append(Button(right_ui_x, 375, "small_square", brush_color, "Brush", lambda: self.set_tool("BRUSH")))
        self.elements.append(Button(right_ui_x + 120, 375, "small_square", fill_color, "Fill", lambda: self.set_tool("FILL")))
        
        # Updated Buttons to have both Map Color and Custom Brush Color pickers side-by-side
        self.elements.append(Button(right_ui_x, 550, "small", "orange", "Map Color", self.pick_map_color))
        self.elements.append(Button(right_ui_x + 300, 375, "small", "purple", "Brush Color", self.pick_custom_brush_color))

    def set_color(self, color):
        self.active_color = color

    def set_tool(self, tool):
        self.draw_mode = tool
        self.refresh_ui()

    def save_and_exit(self):
        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        p_data["name"] = self.country_name
        p_data["leader_name"] = self.leader_name
        p_data["leader_title"] = self.leader_title
        p_data["flag_data"] = encode_surf(self.flag_surf)
        p_data["portrait_data"] = encode_surf(self.portrait_surf)
        
        # --- NEW COLOR SAVE LOGIC ---
        old_color = p_data.get("color")
        if list(old_color) != list(self.new_map_color):
            p_data["color"] = self.new_map_color
            
            # Update the quick-lookup dict in the map screen
            self.map_screen.nation_colors[self.map_screen.player_country] = tuple(self.new_map_color)
            
            # Trigger full map re-renders so the new color shows up instantly!
            self.map_screen.refresh_political_map()
            # self.map_screen.refresh_relations_map()
            self.map_screen.refresh_cores_map()
        
        self.map_screen.show_feedback("Country Data Saved!")
        self.exit_to_map()

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)
            self.additional_events(event)

    def execute_draw(self, mx, my, is_click):
        """Handles applying the brush or fill onto the proper surface"""
        def apply(surf, rect, scale):
            rel_x = (mx - rect.x) // scale
            rel_y = (my - rect.y) // scale
            
            if 0 <= rel_x < surf.get_width() and 0 <= rel_y < surf.get_height():
                if self.draw_mode == "BRUSH":
                    surf.set_at((rel_x, rel_y), self.active_color)
                elif self.draw_mode == "FILL" and is_click:
                    # Fast DFS Flood Fill
                    target_color = surf.get_at((rel_x, rel_y))
                    if target_color == self.active_color: 
                        return
                    
                    w, h = surf.get_size()
                    stack = [(rel_x, rel_y)]
                    
                    while stack:
                        x, y = stack.pop()
                        if surf.get_at((x, y)) == target_color:
                            surf.set_at((x, y), self.active_color)
                            if x > 0: stack.append((x - 1, y))
                            if x < w - 1: stack.append((x + 1, y))
                            if y > 0: stack.append((x, y - 1))
                            if y < h - 1: stack.append((x, y + 1))

        if self.flag_rect.collidepoint(mx, my):
            apply(self.flag_surf, self.flag_rect, self.flag_scale)
        elif self.portrait_rect.collidepoint(mx, my):
            apply(self.portrait_surf, self.portrait_rect, self.portrait_scale)

    def additional_events(self, event):
        # 1. Text Input Selection Logic
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if pygame.Rect(input_box_x, 600, 300, 40).collidepoint(mx, my):
                self.active_input = "COUNTRY_NAME"
            elif pygame.Rect(input_box_x, 700, 300, 40).collidepoint(mx, my):
                self.active_input = "NAME"
            elif pygame.Rect(input_box_x, 800, 300, 40).collidepoint(mx, my):
                self.active_input = "TITLE"
            else:
                self.active_input = None
            
            # Fire a drawing execute on click
            self.execute_draw(mx, my, is_click=True)

        # 2. Continuous Drawing Logic (Dragging)
        elif event.type == pygame.MOUSEMOTION and pygame.mouse.get_pressed()[0]:
            mx, my = event.pos
            self.execute_draw(mx, my, is_click=False)

        # 3. Keyboard Logic
        if event.type == pygame.KEYDOWN and self.active_input:
            if event.key == pygame.K_BACKSPACE:
                if self.active_input == "COUNTRY_NAME": self.country_name = self.country_name[:-1]
                elif self.active_input == "NAME": self.leader_name = self.leader_name[:-1]
                elif self.active_input == "TITLE": self.leader_title = self.leader_title[:-1]
            else:
                # Limit length to prevent UI overflow
                if self.active_input == "COUNTRY_NAME" and len(self.country_name) < 25:
                    self.country_name += event.unicode
                elif self.active_input == "NAME" and len(self.leader_name) < 20:
                    self.leader_name += event.unicode
                elif self.active_input == "TITLE" and len(self.leader_title) < 20:
                    self.leader_title += event.unicode

    def additional_draw(self, surface):
        title_font = fonts.get("title")
        heading_font = fonts.get("heading2")
        normal_font = fonts.get("normal")

        surface.blit(title_font.render("Edit Country Identity", True, (255, 255, 255)), (350, 20))

        # Render Scaled Canvases
        scaled_flag = pygame.transform.scale(self.flag_surf, (self.flag_rect.width, self.flag_rect.height))
        scaled_portrait = pygame.transform.scale(self.portrait_surf, (self.portrait_rect.width, self.portrait_rect.height))
        
        surface.blit(scaled_flag, self.flag_rect.topleft)
        surface.blit(scaled_portrait, self.portrait_rect.topleft)
        
        # Borders around canvases
        pygame.draw.rect(surface, (200, 200, 200), self.flag_rect, 2)
        pygame.draw.rect(surface, (200, 200, 200), self.portrait_rect, 2)

        # Labels
        surface.blit(heading_font.render("Flag (60x40)", True, (200, 200, 200)), (50, 110))
        surface.blit(heading_font.render("Leader Portrait (60x60)", True, (200, 200, 200)), (600, 110))
        
        # Render Palette & Tool Header
        surface.blit(heading_font.render("Color Palette", True, (200, 200, 200)), (right_ui_x, 110))
        
        # Render Active Color Indicator ("selected")
        color_x = 1450
        color_y = 500
        pygame.draw.rect(surface, self.active_color, (color_x, color_y, 60, 60))
        pygame.draw.rect(surface, (255, 255, 255), (color_x, color_y, 60, 60), 2)
        surface.blit(normal_font.render("Selected", True, (200, 200, 200)), (color_x - 5, color_y + 70))

        # --- NEW: Map Color Preview ---
        # Shifted slightly right to fit cleanly next to the side-by-side buttons
        map_color_x = 1430
        map_color_y = 700
        surface.blit(heading_font.render("Map Color", True, (200, 200, 200)), (map_color_x, map_color_y - 30))
        pygame.draw.rect(surface, self.new_map_color, (map_color_x, map_color_y, 60, 40))
        pygame.draw.rect(surface, (255, 255, 255), (map_color_x, map_color_y, 60, 40), 2)

        # Draw Text Inputs
        
        def draw_input_box(y_pos, label_text, input_state, value):
            surface.blit(heading_font.render(label_text, True, (200, 200, 200)), (input_box_x, y_pos - 40))
            rect = pygame.Rect(input_box_x, y_pos, 300, 40)
            color = (200, 255, 200) if self.active_input == input_state else (100, 100, 100)
            pygame.draw.rect(surface, color, rect, 2)
            surface.blit(normal_font.render(value + ("|" if self.active_input == input_state else ""), True, (255, 255, 255)), (input_box_x + 10, y_pos + 10))

        draw_input_box(600, "Country Name:", "COUNTRY_NAME", self.country_name)
        draw_input_box(700, "Leader Name:", "NAME", self.leader_name)
        draw_input_box(800, "Leader Title:", "TITLE", self.leader_title)

    def handle_back_key(self):
        self.exit_to_map()

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True