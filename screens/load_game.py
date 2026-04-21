import os
import shutil
import pygame
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from gameState import GameState
from ui_elements import Button
from map_functions.rendering.font_manager import fonts
from data.constants import SAVES_DIR

class Load_Game(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (50, 0, 50)
        
        # State variables
        self.renaming_folder = None
        self.new_name_text = ""
        self.deleting_folder = None # Track which save is pending deletion
        
        self.root = tk.Tk()
        self.root.withdraw()
        
        self.refresh_save_list()

    def refresh_save_list(self):
        self.elements = [
            Button(50, 50, "small", "red", "Back", self.exit_to_menu),
            Button(160, 50, "medium", "green", "Import .zip", self.import_save_zip)
        ]
        
        if not os.path.exists(SAVES_DIR):
            os.makedirs(SAVES_DIR)
            
        save_folders = os.listdir(SAVES_DIR)
        for i, folder in enumerate(save_folders):
            btn_y = 120 + (i * 60)
            
            # Hide buttons for the row being renamed or deleted
            if self.renaming_folder == folder or self.deleting_folder == folder:
                continue

            # Load
            self.elements.append(Button(200, btn_y, "medium", "blue", folder, 
                                       lambda f=folder: self.load_specific_save(f)))
            # Rename
            self.elements.append(Button(420, btn_y, "small", "grey", "Rename", 
                                       lambda f=folder: self.start_rename(f)))
            # Export
            self.elements.append(Button(530, btn_y, "small", "blue", "Export", 
                                       lambda f=folder: self.export_save_zip(f)))
            # Delete trigger
            self.elements.append(Button(640, btn_y, "small", "red", "Del", 
                                       lambda f=folder: self.trigger_delete_conf(f)))

    def trigger_delete_conf(self, folder_name):
        """Activates the delete confirmation state."""
        self.deleting_folder = folder_name
        self.refresh_save_list()

    def confirm_delete(self):
        """Actually deletes the folder."""
        path = os.path.join(SAVES_DIR, self.deleting_folder)
        if os.path.exists(path):
            shutil.rmtree(path)
        self.deleting_folder = None
        self.refresh_save_list()

    def cancel_delete(self):
        """Backs out of deletion."""
        self.deleting_folder = None
        self.refresh_save_list()

    def additional_events(self, event):
        # 1. Renaming Input Logic
        if self.renaming_folder:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    self.finish_rename()
                elif event.key == pygame.K_BACKSPACE:
                    self.new_name_text = self.new_name_text[:-1]
                elif event.key == pygame.K_ESCAPE:
                    self.renaming_folder = None
                    self.refresh_save_list()
                else:
                    if event.unicode.isalnum() or event.unicode in " _-":
                        self.new_name_text += event.unicode
        
        # 2. Deletion Input Logic (Enter to confirm, Esc to cancel)
        elif self.deleting_folder:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    self.confirm_delete()
                elif event.key == pygame.K_ESCAPE:
                    self.cancel_delete()

    def additional_draw(self, surface):
        # --- Draw Rename Input Box ---
        if self.renaming_folder:
            save_folders = os.listdir("saves")
            idx = save_folders.index(self.renaming_folder) if self.renaming_folder in save_folders else 0
            box_y = 120 + (idx * 60)
            
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
            # Dim the background
            overlay = pygame.Surface((1600, 900), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            surface.blit(overlay, (0, 0))
            
            # Draw Popup Box
            pop_rect = pygame.Rect(600, 350, 400, 200)
            pygame.draw.rect(surface, (60, 20, 20), pop_rect)
            pygame.draw.rect(surface, (255, 50, 50), pop_rect, 3)
            
            font = fonts.get("heading2")
            msg = font.render(f"Delete '{self.deleting_folder}'?", True, (255, 255, 255))
            msg_rect = msg.get_rect(center=(800, 400))
            surface.blit(msg, msg_rect)
            
            sub_msg = font.render("Press Enter to Confirm or Esc to Cancel", True, (200, 200, 200))
            sub_rect = sub_msg.get_rect(center=(800, 450))
            surface.blit(sub_msg, sub_rect)

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
        file_path = filedialog.askopenfilename(filetypes=[("Zip files", "*.zip")])
        if file_path:
            save_name = Path(file_path).stem
            target_dir = os.path.join("saves", save_name)
            if os.path.exists(target_dir): target_dir += "_imported"
            try:
                with zipfile.ZipFile(file_path, 'r') as zip_ref: zip_ref.extractall(target_dir)
                self.refresh_save_list()
            except Exception as e: messagebox.showerror("Import Error", str(e))

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