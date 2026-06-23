import os
import json
import shutil
import pygame
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox
from data import queries 
from gameState import GameState
from ui_elements import Button, process_text_input
from map_logic.rendering.font_manager import fonts
import data.constants as c
from ui.bars import ui_bars

class Load_Game(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (50, 0, 50)
        
        # State variables
        self.renaming_folder = None
        self.new_name_text = ""
        self.deleting_folder = None 
        
        self.save_scroll_y = 0
        self.max_save_scroll = 0
        self.is_dragging_scrollbar = False
        self.scroll_track_rect = None
        self.scroll_handle_rect = None
        
        self.refresh_save_list()

    def refresh_save_list(self):
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_to_menu),
            Button(160, 20, "medium", "green", "Import .zip", self.import_save_zip)
        ]
        
        if not os.path.exists(c.SAVES_DIR):
            os.makedirs(c.SAVES_DIR)
            
        save_folders = os.listdir(c.SAVES_DIR)
        
        # Calculate scroll boundaries
        total_content_height = len(save_folders) * 40
        self.max_save_scroll = min(0, (c.SCREEN_HEIGHT - 200) - total_content_height)

        for i, folder in enumerate(save_folders):
            # Apply the scroll offset to the button Y position
            btn_y = 120 + (i * 40) + self.save_scroll_y
            
            # Simple Y-based culling so we don't draw off-screen buttons
            if not (100 < btn_y < c.SCREEN_HEIGHT - 50):
                continue

            # Hide buttons for the row being renamed or deleted
            if self.renaming_folder == folder or self.deleting_folder == folder:
                continue

            # Load
            self.elements.append(Button(20, btn_y, "save_file", "blue", folder, 
                                        lambda f=folder: self.load_specific_save(f)))
            # History
            self.elements.append(Button(785, btn_y, "small_save_button", "purple", "History", 
                                        lambda f=folder: self.open_history_menu(f)))
            # Rename
            self.elements.append(Button(895, btn_y, "small_save_button", "grey", "Rename", 
                                        lambda f=folder: self.start_rename(f)))
            # Export
            self.elements.append(Button(1005, btn_y, "small_save_button", "green", "Export", 
                                        lambda f=folder: self.export_save_zip(f)))
            # Delete trigger
            self.elements.append(Button(1115, btn_y, "small_save_button", "red", "Del", 
                                        lambda f=folder: self.trigger_delete_conf(f)))

    def _snap_scroll(self, my):
        """Helper to map mouse Y to scroll position."""
        self.save_scroll_y = ui_bars.calculate_scroll_snap(my, self.max_save_scroll, 120, c.SCREEN_HEIGHT - 200)
        self.refresh_save_list()

    def additional_events(self, event):
        # 1. Renaming Input Logic
        if self.renaming_folder:
            is_valid_char = lambda c: c.isalnum() or c in " _-"
            self.new_name_text, status = process_text_input(event, self.new_name_text, validation_func=is_valid_char)
            if status == "SUBMIT": self.finish_rename()
            elif status == "CANCEL": self.renaming_folder = None; self.refresh_save_list()
        
        # 2. Deletion Input Logic
        elif self.deleting_folder:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN: self.confirm_delete()
                elif event.key == pygame.K_ESCAPE: self.cancel_delete()

        # 3. Scrolling Logic
        if event.type == pygame.MOUSEWHEEL:
            self.save_scroll_y += event.y * 40
            self.save_scroll_y = max(self.max_save_scroll, min(0, self.save_scroll_y))
            self.refresh_save_list()

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if self.scroll_handle_rect and self.scroll_handle_rect.collidepoint(mx, my):
                self.is_dragging_scrollbar = True
            elif self.scroll_track_rect and self.scroll_track_rect.collidepoint(mx, my):
                self.is_dragging_scrollbar = True
                self._snap_scroll(my)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.is_dragging_scrollbar = False

        elif event.type == pygame.MOUSEMOTION and self.is_dragging_scrollbar:
            self._snap_scroll(event.pos[1])

    def additional_draw(self, surface):
        # --- Draw Rename Input Box ---
        if self.renaming_folder:
            save_folders = os.listdir("saves")
            idx = save_folders.index(self.renaming_folder) if self.renaming_folder in save_folders else 0
            box_y = 120 + (idx * 40)
            
            input_rect = pygame.Rect(200, box_y, 300, 50)
            pygame.draw.rect(surface, (100, 100, 100), input_rect)
            pygame.draw.rect(surface, (255, 255, 255), input_rect, 2)
            
            font = fonts.get("heading2")
            txt_surf = font.render(self.new_name_text + "|", True, (255, 255, 255))
            surface.blit(txt_surf, (input_rect.x + 10, input_rect.y + 10))
            
            instr = font.render("Enter: Save | Esc: Cancel", True, (200, 200, 200))
            surface.blit(instr, (200, 80))

        # --- Draw Delete Confirmation Popup ---
        if self.deleting_folder:
            ui_bars.draw_fullscreen_overlay(surface, 180)
            
            # Draw Popup Box
            pop_rect = pygame.Rect(550, 10, 500, 100)
            ui_bars.draw_modal_box(surface, pop_rect, bg_color=(60, 20, 20), border_color=(255, 50, 50), border_width=3)
            
            font = fonts.get("heading2")
            msg = font.render(f"Delete '{self.deleting_folder}'?", True, (255, 255, 255))
            msg_rect = msg.get_rect(center=(800, 40))
            surface.blit(msg, msg_rect)
            
            sub_msg = font.render("Press Enter to Confirm or Esc to Cancel", True, (200, 200, 200))
            sub_rect = sub_msg.get_rect(center=(800, 80))
            surface.blit(sub_msg, sub_rect)

        # --- Draw Scrollbar ---
        self.scroll_track_rect, self.scroll_handle_rect = ui_bars.draw_standard_scrollbar(
            surface, self.save_scroll_y, self.max_save_scroll, c.SCREEN_WIDTH - 40, 120, c.SCREEN_HEIGHT - 200
        )

    def trigger_delete_conf(self, folder_name):
        """Activates the delete confirmation state."""
        self.deleting_folder = folder_name
        self.refresh_save_list()

    def confirm_delete(self):
        """Actually deletes the folder."""
        path = os.path.join(c.SAVES_DIR, self.deleting_folder)
        if os.path.exists(path):
            shutil.rmtree(path)
        self.deleting_folder = None
        self.refresh_save_list()

    def cancel_delete(self):
        """Backs out of deletion."""
        self.deleting_folder = None
        self.refresh_save_list()

    def open_history_menu(self, folder_name):
        import tkinter as tk
        from tkinter import ttk
        from data import queries
        
        history_path = os.path.join(c.SAVES_DIR, folder_name, "history.json")
        if not os.path.exists(history_path):
            root = queries.get_transient_tk_root()
            messagebox.showinfo("No History", "No history available for this save.")
            queries.destroy_tk_root(root)
            return
            
        with open(history_path, "r") as f:
            history_data = json.load(f)
            
        if not history_data:
            root = queries.get_transient_tk_root()
            messagebox.showinfo("No History", "History file is empty.")
            queries.destroy_tk_root(root)
            return

        root = tk.Tk()
        root.title(f"History: {folder_name}")
        root.geometry("300x400")
        root.attributes("-topmost", True)
        self.menu_active = True
        
        tk.Label(root, text="Select a past turn to load:", font=("Arial", 12)).pack(pady=10)
        
        frame = tk.Frame(root)
        frame.pack(fill="both", expand=True, padx=10)
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        
        lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
        
        turns = sorted([int(k) for k in history_data.keys()])
        for t in turns:
            date_str = history_data[str(t)].get("date_str", f"Turn {t}")
            lb.insert(tk.END, f"Turn {t}: {date_str}")
            
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=lb.yview)
        
        def close_menu():
            self.menu_active = False
            root.destroy()
            
        root.protocol("WM_DELETE_WINDOW", close_menu)
        
        def on_select(event=None):
            selection = lb.curselection()
            if selection:
                selected_idx = selection[0]
                selected_turn = turns[selected_idx]
                self.selected_save_path = os.path.join(c.SAVES_DIR, folder_name)
                self.selected_history_turn = selected_turn
                self.next_state = "MAP"
                self.done = True
                close_menu()
        
        tk.Button(root, text="Load Selected Turn", command=on_select, bg="#9C27B0", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)
        lb.bind('<Double-1>', on_select)
        
        queries.run_tk_loop(self, root)

    # --- File System Methods (Unchanged logic, just used by UI) ---
    def export_save_zip(self, folder_name):
        try:
            source_path = os.path.join("saves", folder_name)
            zip_filename = os.path.join(str(Path.home() / "Downloads"), f"{folder_name}.zip")
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(source_path):
                    for file in files:
                        zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), source_path))
            messagebox.showinfo("Export Success", f"Exported to Downloads.")
        except Exception as e: messagebox.showerror("Export Error", str(e))

    def import_save_zip(self):
        # Create a temporary root via the centralized helper
        root = queries.get_transient_tk_root()
        
        file_path = filedialog.askopenfilename(filetypes=[("Zip files", "*.zip")])
        
        # Destroy it immediately after getting the path
        queries.destroy_tk_root(root)
        
        if file_path:
            save_name = Path(file_path).stem
            target_dir = os.path.join("saves", save_name)
            if os.path.exists(target_dir): target_dir += "_imported"
            try:
                with zipfile.ZipFile(file_path, 'r') as zip_ref: 
                    zip_ref.extractall(target_dir)
                self.refresh_save_list()
            except Exception as e: 
                messagebox.showerror("Import Error", str(e))

    def start_rename(self, folder_name):
        self.renaming_folder = folder_name
        self.new_name_text = folder_name
        self.refresh_save_list()

    def finish_rename(self):
        if self.new_name_text.strip() != "" and self.new_name_text != self.renaming_folder:
            old_path = os.path.join("saves", self.renaming_folder)
            new_path = os.path.join("saves", self.new_name_text.strip())
            if not os.path.exists(new_path): os.rename(old_path, new_path)
        self.renaming_folder = None
        self.refresh_save_list()

    def load_specific_save(self, folder_name):
        self.selected_save_path = os.path.join("saves", folder_name)
        self.next_state = "MAP"
        self.done = True

    def handle_back_key(self):
        self.exit_to_menu()
        
    def exit_to_menu(self):
        self.next_state = "MENU"
        self.done = True