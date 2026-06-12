# screens/map_related_screens/edit_country.py
import pygame
import os
from pathlib import Path
import tkinter as tk 
from tkinter import colorchooser, filedialog
import unicodedata
from gameState import GameState
from ui_elements import Button, process_text_input
import ui_elements
from map_logic.rendering.font_manager import fonts
import data.constants as c
from ui import buttons
from data import queries
from map_logic.rendering import country_names

input_box_x = c.EDIT_COUNTRY_UI_X1
second_right_ui_x = c.EDIT_COUNTRY_UI_X2
right_ui_x = c.EDIT_COUNTRY_UI_X3
x_offset_confirmation = -100

class Edit_Country_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (30, 30, 40)
        self.map_screen = None
        self.editing_country = None
        
        # Dimensions
        self.flag_size = c.FLAG_SIZE
        self.portrait_size = c.PORTRAIT_SIZE
        
        # Scaled drawing constraints
        self.flag_scale = 6
        self.portrait_scale = 6

        self.flag_rect = pygame.Rect(input_box_x, 150, self.flag_size[0] * self.flag_scale, self.flag_size[1] * self.flag_scale)
        self.portrait_rect = pygame.Rect(second_right_ui_x, 150, self.portrait_size[0] * self.portrait_scale, self.portrait_size[1] * self.portrait_scale)
        
        self.flag_surf = pygame.Surface(self.flag_size, pygame.SRCALPHA)
        self.portrait_surf = pygame.Surface(self.portrait_size, pygame.SRCALPHA)
        self.flag_surf.fill((255, 255, 255, 255))
        self.portrait_surf.fill((255, 255, 255, 255))
        
        # Editor State
        self.active_color = (0, 0, 0)
        self.draw_mode = "BRUSH" # Can be "BRUSH" or "FILL"
        self.active_input = None # "COUNTRY_NAME", "NAME", or "TITLE"
        self.resetting_type = None # "FLAG" or "PORTRAIT"
        self.show_unsaved_confirmation = False
        
        self.is_drawing = False
        self.history = []
        self.history_index = -1
        
        self.country_name = ""
        self.leader_name = ""
        self.leader_title = ""
        self.new_map_color = [150, 150, 150]

        # Original state trackers for unsaved changes popup
        self.orig_country_name = ""
        self.orig_leader_name = ""
        self.orig_leader_title = ""
        self.orig_map_color = [150, 150, 150]
        
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
        
        # Uses the explicit editing_country flag set by the map screen
        self.editing_country = getattr(self.map_screen, "editing_country", self.map_screen.player_country)
        
        # Load existing data
        p_data = self.map_screen.nation_data[self.editing_country]
        self.country_name = p_data.get("name", self.editing_country)
        self.leader_name = p_data.get("leader_name", "")
        self.leader_title = p_data.get("leader_title", "")
        self.new_map_color = list(p_data.get("color", [150, 150, 150]))

        # Track the original baseline to check for unsaved changes on exit
        self.orig_country_name = self.country_name
        self.orig_leader_name = self.leader_name
        self.orig_leader_title = self.leader_title
        self.orig_map_color = list(self.new_map_color)

        # Added .copy() here to protect the global image cache from being mutated by the brush tools!
        self.flag_surf = queries.decode_b64_to_surf(p_data.get("flag_data", "DEFAULT"), self.flag_size, is_portrait=False, country_name=self.editing_country).copy()
        self.portrait_surf = queries.decode_b64_to_surf(p_data.get("portrait_data", "DEFAULT"), self.portrait_size, is_portrait=True, country_name=self.editing_country).copy()
            
        # Initialize History
        self.history = [(self.flag_surf.copy(), self.portrait_surf.copy())]
        self.history_index = 0
            
        self.refresh_ui()

    def has_unsaved_changes(self):
        if self.history_index > 0: return True
        if self.country_name != self.orig_country_name: return True
        if self.leader_name != self.orig_leader_name: return True
        if self.leader_title != self.orig_leader_title: return True
        if self.new_map_color != self.orig_map_color: return True
        return False

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
        
        # Slice to [:3] to ensure we only pass RGB to Tkinter, dropping the Alpha
        color_code = colorchooser.askcolor(title="Choose Brush Color", initialcolor=tuple(self.active_color)[:3])
        
        if color_code[0]: 
            # Re-append the full opacity alpha channel (255) to the returned RGB tuple
            self.active_color = tuple(int(c) for c in color_code[0]) + (255,)
            
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

    def import_flag(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        file_path = filedialog.askopenfilename(
            title="Select Flag Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp")]
        )
        root.destroy()
        pygame.event.pump() # Clears any phantom mouse clicks Tkinter leaves behind

        if file_path:
            try:
                new_img = pygame.image.load(file_path).convert()
                self.flag_surf = pygame.transform.scale(new_img, self.flag_size)
                self.save_state()
                self.map_screen.show_feedback("Flag Imported!")
            except Exception as e:
                self.map_screen.show_feedback("Failed to import flag.")

    def import_portrait(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        file_path = filedialog.askopenfilename(
            title="Select Portrait Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp")]
        )
        root.destroy()
        pygame.event.pump()

        if file_path:
            try:
                new_img = pygame.image.load(file_path).convert()
                self.portrait_surf = pygame.transform.scale(new_img, self.portrait_size)
                self.save_state()
                self.map_screen.show_feedback("Portrait Imported!")
            except Exception as e:
                self.map_screen.show_feedback("Failed to import portrait.")

    def refresh_ui(self):
        buttons.render_edit_country_buttons(self)

    def set_color(self, color):
        self.active_color = color

    def set_tool(self, tool):
        self.draw_mode = tool            
        self.refresh_ui()

    def save_state(self):
        """Saves the current drawing for undo/redo."""
        # Cut off any redo history if we make a new action
        self.history = self.history[:self.history_index + 1]
        self.history.append((self.flag_surf.copy(), self.portrait_surf.copy()))
        if len(self.history) > 30: # Limit history to 30 steps
            self.history.pop(0)
        else:
            self.history_index += 1
            
    def undo(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.flag_surf = self.history[self.history_index][0].copy()
            self.portrait_surf = self.history[self.history_index][1].copy()

    def redo(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.flag_surf = self.history[self.history_index][0].copy()
            self.portrait_surf = self.history[self.history_index][1].copy()

    def trigger_reset(self, target_type):
        self.resetting_type = target_type

    def reset_map_color(self):
        """Resets the map color to the original value stored upon entering the editor."""
        self.new_map_color = list(self.orig_map_color)
        self.map_screen.show_feedback("Map color reset to default!")
        self.save_state()

    def confirm_reset(self):
        if self.resetting_type == "FLAG":
            self.flag_surf = queries.decode_b64_to_surf("DEFAULT", self.flag_size, is_portrait=False, country_name=self.editing_country)
        elif self.resetting_type == "PORTRAIT":
            self.portrait_surf = queries.decode_b64_to_surf("DEFAULT", self.portrait_size, is_portrait=True, country_name=self.editing_country)
        
        self.map_screen.show_feedback(f"{self.resetting_type.title()} reset to default!")
        self.save_state()
        self.resetting_type = None

    def cancel_reset(self):
        self.resetting_type = None

    def open_switch_appearance_menu(self):
        """Opens a floating Tkinter tree configuration list to copy assets from another nation."""
        import tkinter as tk

        root = tk.Tk()
        root.title("Switch Appearance Profile")
        root.geometry("300x450")
        root.attributes("-topmost", True)
        self.menu_active = True

        def close_menu():
            self.menu_active = False
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", close_menu)
        tk.Label(root, text="Select Target Country look:", font=("Arial", 12)).pack(pady=10)
        
        frame = tk.Frame(root)
        frame.pack(fill="both", expand=True, padx=10)
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        
        countries = sorted(list(self.map_screen.nation_data.keys()), key=lambda k: unicodedata.normalize('NFKD', k).encode('ascii', 'ignore').decode('utf-8').lower()) # <-- Modified line
        lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
        for country in countries:
            if country not in c.UNPLAYABLE_NATIONS:
                lb.insert(tk.END, country)
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=lb.yview)
        
        def on_select(event=None):
            selection = lb.curselection()
            if selection:
                chosen_country = lb.get(selection[0])
                src_data = self.map_screen.nation_data[chosen_country]
                
                # Transfer textural profile definitions
                self.country_name = src_data.get("name", chosen_country)
                self.leader_name = src_data.get("leader_name", "")
                self.leader_title = src_data.get("leader_title", "")
                self.new_map_color = list(src_data.get("color", [150, 150, 150]))
                
                # Fetch asset matrices safely into local storage caches
                self.flag_surf = queries.decode_b64_to_surf(src_data.get("flag_data", "DEFAULT"), self.flag_size, is_portrait=False, country_name=chosen_country)
                self.portrait_surf = queries.decode_b64_to_surf(src_data.get("portrait_data", "DEFAULT"), self.portrait_size, is_portrait=True, country_name=chosen_country)
                
                self.save_state()
                self.map_screen.show_feedback(f"Appearance copied from {chosen_country}!")
            close_menu()

        tk.Button(root, text="Apply Configuration", command=on_select, bg="#FF9800", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)
        lb.bind('<Double-1>', on_select)

        while self.menu_active and not self.done:
            try:
                root.update()
                pygame.event.pump()
                pygame.time.wait(c.CPU_LIMITER)
            except:
                break

    def save_and_exit(self):
        p_data = self.map_screen.nation_data[self.editing_country]
        p_data["name"] = self.country_name
        p_data["leader_name"] = self.leader_name
        p_data["leader_title"] = self.leader_title
        p_data["flag_data"] = queries.encode_surf_to_b64(self.flag_surf)
        p_data["portrait_data"] = queries.encode_surf_to_b64(self.portrait_surf)
        
        # Scrub it immediately to keep RAM clean
        queries.scrub_default_images({self.editing_country: p_data})
        
        # Refresh Country Name Cache
        country_names.clear_country_name_cache(self.map_screen)
        
        # COLOR SAVE LOGIC
        old_color = p_data.get("color")
        if list(old_color) != list(self.new_map_color):
            p_data["color"] = self.new_map_color
            
            # Update the quick-lookup dict in the map screen
            self.map_screen.nation_colors[self.editing_country] = tuple(self.new_map_color)
            
            # Trigger full map re-renders so the new color shows up instantly!
            self.map_screen.refresh_political_map()
            self.map_screen.refresh_cores_map()
        
        self.map_screen.show_feedback("Country Data Saved!")
        self.force_exit_to_map()

    def handle_events(self, events):
        for event in events:
            # --- UNSAVED CHANGES POPUP INTERCEPT ---
            if self.show_unsaved_confirmation:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        self.force_exit_to_map()
                    elif event.key == pygame.K_ESCAPE:
                        self.show_unsaved_confirmation = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos
                    center_x, center_y = c.SCREEN_WIDTH // 2 + x_offset_confirmation, c.SCREEN_HEIGHT // 2
                    yes_rect = pygame.Rect(center_x - 130, center_y + 40, 100, 40)
                    no_rect = pygame.Rect(center_x + 30, center_y + 40, 100, 40)
                    if yes_rect.collidepoint(mx, my):
                        self.force_exit_to_map()
                    elif no_rect.collidepoint(mx, my):
                        self.show_unsaved_confirmation = False
                continue

            if self.resetting_type:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        self.confirm_reset()
                    elif event.key == pygame.K_ESCAPE:
                        self.cancel_reset()
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos
                    center_x, center_y = c.SCREEN_WIDTH // 2 + x_offset_confirmation, c.SCREEN_HEIGHT // 2
                    yes_rect = pygame.Rect(center_x - 130, center_y + 40, 100, 40)
                    no_rect = pygame.Rect(center_x + 30, center_y + 40, 100, 40)
                    if yes_rect.collidepoint(mx, my):
                        self.confirm_reset()
                    elif no_rect.collidepoint(mx, my):
                        self.cancel_reset()
                continue
                
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
                            
                elif self.draw_mode == "PICKER" and is_click:
                    self.active_color = surf.get_at((rel_x, rel_y))
                    self.draw_mode = "BRUSH" # Auto-revert back to the brush after picking
                    self.refresh_ui()

        if self.flag_rect.collidepoint(mx, my):
            apply(self.flag_surf, self.flag_rect, self.flag_scale)
        elif self.portrait_rect.collidepoint(mx, my):
            apply(self.portrait_surf, self.portrait_rect, self.portrait_scale)

    def additional_events(self, event):
        # 1. Text Input Selection Logic
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if pygame.Rect(input_box_x, 500, 300, 40).collidepoint(mx, my):
                self.active_input = "COUNTRY_NAME"
            elif pygame.Rect(input_box_x, 575, 300, 40).collidepoint(mx, my):
                self.active_input = "NAME"
            elif pygame.Rect(input_box_x, 650, 300, 40).collidepoint(mx, my):
                self.active_input = "TITLE"
            else:
                self.active_input = None
            
            # Fire a drawing execute on click
            if self.flag_rect.collidepoint(mx, my) or self.portrait_rect.collidepoint(mx, my):
                self.is_drawing = True
            self.execute_draw(mx, my, is_click=True)
            
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if getattr(self, "is_drawing", False):
                self.is_drawing = False
                self.save_state()

        # 2. Continuous Drawing Logic (Dragging)
        elif event.type == pygame.MOUSEMOTION and pygame.mouse.get_pressed()[0]:
            mx, my = event.pos
            self.execute_draw(mx, my, is_click=False)

        # 3. Keyboard Logic
        elif event.type == pygame.KEYDOWN:
            mods = pygame.key.get_mods()
            # Handle Undo / Redo
            if event.key == pygame.K_z and (mods & pygame.KMOD_CTRL or mods & pygame.KMOD_GUI):
                self.undo()
            elif event.key == pygame.K_y and (mods & pygame.KMOD_CTRL or mods & pygame.KMOD_GUI):
                self.redo()
            else:
                if self.active_input:
                    # TODO: constants.py the hardcoded 50 please
                    if self.active_input == "COUNTRY_NAME":
                        self.country_name, _ = process_text_input(event, self.country_name, max_length=50)
                    elif self.active_input == "NAME":
                        self.leader_name, _ = process_text_input(event, self.leader_name, max_length=50)
                    elif self.active_input == "TITLE":
                        self.leader_title, _ = process_text_input(event, self.leader_title, max_length=50)

    def additional_draw(self, surface):
        title_font = fonts.get("title")
        heading_font = fonts.get("heading2")
        normal_font = fonts.get("normal")

        surface.blit(title_font.render("Edit Country Identity", True, (255, 255, 255)), (c.EDIT_COUNTRY_TITLE_X, c.EDIT_COUNTRY_TITLE_Y))

        # Render Scaled Canvases
        scaled_flag = pygame.transform.scale(self.flag_surf, (self.flag_rect.width, self.flag_rect.height))

        # Render Scaled Canvases
        scaled_flag = pygame.transform.scale(self.flag_surf, (self.flag_rect.width, self.flag_rect.height))
        scaled_portrait = pygame.transform.scale(self.portrait_surf, (self.portrait_rect.width, self.portrait_rect.height))
        
        surface.blit(scaled_flag, self.flag_rect.topleft)
        surface.blit(scaled_portrait, self.portrait_rect.topleft)
        
        # Borders around canvases
        pygame.draw.rect(surface, (200, 200, 200), self.flag_rect, 2)
        pygame.draw.rect(surface, (200, 200, 200), self.portrait_rect, 2)

        # Labels
        surface.blit(heading_font.render("Flag (60x40)", True, (200, 200, 200)), (input_box_x, 110))
        surface.blit(heading_font.render("Leader Portrait (60x60)", True, (200, 200, 200)), (second_right_ui_x, 110))
        
        # Render Palette & Tool Header
        surface.blit(heading_font.render("Color Palette", True, (200, 200, 200)), (right_ui_x, 110))
        
        # Render Active Color Indicator ("selected")
        color_x = c.SCREEN_WIDTH - 150
        color_y = 70
        
        if self.active_color == (0, 0, 0, 0):
            # Draw a dark background and blit the red line icon over it
            pygame.draw.rect(surface, (40, 40, 40), (color_x, color_y, 60, 60))
            red_line_icon = ui_elements.UI_ICONS.get("red_line")
            if red_line_icon:
                # Scale it slightly smaller than the box so the border still looks clean
                scaled_icon = pygame.transform.scale(red_line_icon, (50, 50))
                surface.blit(scaled_icon, (color_x + 5, color_y + 5))
        else:
            pygame.draw.rect(surface, self.active_color, (color_x, color_y, 60, 60))
            
        pygame.draw.rect(surface, (255, 255, 255), (color_x, color_y, 60, 60), 2)
        surface.blit(normal_font.render("Selected", True, (200, 200, 200)), (color_x, color_y - 20))

        # --- Map Color Preview ---
        map_color_x = c.SCREEN_WIDTH - 200
        map_color_y = 600
        surface.blit(heading_font.render("Map Color", True, (200, 200, 200)), (map_color_x, map_color_y - 30))
        pygame.draw.rect(surface, self.new_map_color, (map_color_x, map_color_y, 60, 40))
        pygame.draw.rect(surface, (255, 255, 255), (map_color_x, map_color_y, 60, 40), 2)

        # Draw Text Inputs
        
        def draw_input_box(y_pos, label_text, input_state, value):
            surface.blit(normal_font.render(label_text, True, (200, 200, 200)), (input_box_x, y_pos - 20))
            rect = pygame.Rect(input_box_x, y_pos, 300, 40)
            color = (200, 255, 200) if self.active_input == input_state else (100, 100, 100)
            pygame.draw.rect(surface, color, rect, 2)
            surface.blit(normal_font.render(value + ("|" if self.active_input == input_state else ""), True, (255, 255, 255)), (input_box_x + 10, y_pos + 10))

        draw_input_box(500, "Country Name:", "COUNTRY_NAME", self.country_name)
        draw_input_box(575, "Leader Name:", "NAME", self.leader_name)
        draw_input_box(650, "Leader Title:", "TITLE", self.leader_title)

        # --- DRAW RESET CONFIRMATION POPUP ---
        if self.resetting_type:
            overlay = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            surface.blit(overlay, (0, 0))

            box_rect = pygame.Rect(0, 0, 450, 200)
            box_rect.center = (c.SCREEN_WIDTH // 2 + x_offset_confirmation, c.SCREEN_HEIGHT // 2)
            pygame.draw.rect(surface, (60, 20, 20), box_rect)
            pygame.draw.rect(surface, (255, 50, 50), box_rect, 3)

            msg = heading_font.render(f"Reset {self.resetting_type.title()} to Default?", True, (255, 255, 255))
            surface.blit(msg, msg.get_rect(center=(box_rect.centerx, box_rect.y + 50)))

            sub_msg = normal_font.render("Press Enter to Confirm or Esc to Cancel", True, (200, 200, 200))
            surface.blit(sub_msg, sub_msg.get_rect(center=(box_rect.centerx, box_rect.y + 90)))

            yes_rect = pygame.Rect(box_rect.centerx - 130, box_rect.y + 140, 100, 40)
            no_rect = pygame.Rect(box_rect.centerx + 30, box_rect.y + 140, 100, 40)

            mx, my = pygame.mouse.get_pos()
            pygame.draw.rect(surface, (150, 0, 0) if yes_rect.collidepoint(mx, my) else (100, 0, 0), yes_rect)
            pygame.draw.rect(surface, (0, 150, 0) if no_rect.collidepoint(mx, my) else (0, 100, 0), no_rect)

            btn_font = fonts.get("button")
            yes_txt = btn_font.render("YES", True, (255, 255, 255))
            no_txt = btn_font.render("NO", True, (255, 255, 255))
            
            surface.blit(yes_txt, yes_txt.get_rect(center=yes_rect.center))
            surface.blit(no_txt, no_txt.get_rect(center=no_rect.center))

        # --- DRAW UNSAVED CONFIRMATION POPUP ---
        if getattr(self, "show_unsaved_confirmation", False):
            overlay = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            surface.blit(overlay, (0, 0))

            box_rect = pygame.Rect(0, 0, 450, 200)
            box_rect.center = (c.SCREEN_WIDTH // 2 + x_offset_confirmation, c.SCREEN_HEIGHT // 2)
            pygame.draw.rect(surface, (60, 20, 20), box_rect)
            pygame.draw.rect(surface, (255, 50, 50), box_rect, 3)

            msg = heading_font.render("Discard Unsaved Changes?", True, (255, 255, 255))
            surface.blit(msg, msg.get_rect(center=(box_rect.centerx, box_rect.y + 50)))

            sub_msg = normal_font.render("Press Enter to Discard or Esc to Cancel", True, (200, 200, 200))
            surface.blit(sub_msg, sub_msg.get_rect(center=(box_rect.centerx, box_rect.y + 90)))

            yes_rect = pygame.Rect(box_rect.centerx - 130, box_rect.y + 140, 100, 40)
            no_rect = pygame.Rect(box_rect.centerx + 30, box_rect.y + 140, 100, 40)

            mx, my = pygame.mouse.get_pos()
            pygame.draw.rect(surface, (150, 0, 0) if yes_rect.collidepoint(mx, my) else (100, 0, 0), yes_rect)
            pygame.draw.rect(surface, (0, 150, 0) if no_rect.collidepoint(mx, my) else (0, 100, 0), no_rect)

            btn_font = fonts.get("button")
            yes_txt = btn_font.render("DISCARD", True, (255, 255, 255))
            no_txt = btn_font.render("CANCEL", True, (255, 255, 255))
            
            surface.blit(yes_txt, yes_txt.get_rect(center=yes_rect.center))
            surface.blit(no_txt, no_txt.get_rect(center=no_rect.center))

        # --- Draw Original Key Country ID block ---
        id_display_x = c.EDIT_COUNTRY_ID_DISPLAY_X
        id_display_y = c.EDIT_COUNTRY_ID_DISPLAY_Y
        id_text = f"Country ID: {self.editing_country}"
        id_surf = normal_font.render(id_text, True, (150, 150, 150))
        surface.blit(id_surf, (id_display_x, id_display_y))

    def handle_back_key(self):
        self.exit_to_map()

    def exit_to_map(self):
        if self.has_unsaved_changes():
            self.show_unsaved_confirmation = True
        else:
            self.force_exit_to_map()

    def force_exit_to_map(self):
        self.show_unsaved_confirmation = False
        self.next_state, self.done = "MAP", True