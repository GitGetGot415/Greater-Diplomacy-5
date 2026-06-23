import os
import shutil
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox
from gameState import GameState
from ui_elements import Button, process_text_input
import data.constants as c
from map_logic.rendering.font_manager import fonts
from data import queries
from ui.bars import ui_bars
from map_logic.system32 import loading_screen

class Select_Base_Map(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (40, 20, 60)
        self.selected_save_path = None
        self.sub_state = "CUSTOM_MAPS"

        # State for custom maps management
        self.scroll_y = 0
        self.max_scroll = 0
        self.is_dragging_scrollbar = False
        self.scroll_track_rect = None
        self.scroll_handle_rect = None

        self.deleting_scenario = None
        self.renaming_scenario = None
        self.new_name_text = ""
        
        self.last_custom_count = -1
        self.last_base_count = -1

        # --- REFRESH STATE ---
        self.is_refreshing = False
        self.refresh_total = 0
        self.refresh_completed = 0
        self.refresh_status = ""

        self.refresh_maps()

    def set_sub_state(self, state):
        self.sub_state = state
        self.scroll_y = 0
        self.deleting_scenario = None
        self.renaming_scenario = None
        self.refresh_maps()

    def update(self):
        super().update()
        
        # Automatically refresh if the number of maps has changed since last viewed
        current_custom = len(os.listdir(c.SCENARIOS_CUSTOM_DIR)) if os.path.exists(c.SCENARIOS_CUSTOM_DIR) else 0
        current_base = len(os.listdir(c.BASE_MAPS_DIR)) if os.path.exists(c.BASE_MAPS_DIR) else 0
        
        if self.last_custom_count != current_custom or self.last_base_count != current_base:
            self.last_custom_count = current_custom
            self.last_base_count = current_base
            self.refresh_maps()

        # Forcefully hide all UI buttons while the loading screen is active
        if getattr(self, 'is_refreshing', False):
            for el in self.elements:
                el.visible = False
        else:
            for el in self.elements:
                el.visible = True

    def refresh_maps(self):
        self.elements = []
        
        if self.sub_state == "CUSTOM_MAPS":
            self.elements.append(Button(20, 20, "small", "red", "Back", self.exit_to_menu))
            self.elements.append(Button(160, 20, "medium", "green", "Import .zip", self.import_scenario_zip))
            self.elements.append(Button("centered", c.SCREEN_HEIGHT - 100, "large", "purple", "New Map", lambda: self.set_sub_state("BASE_MAPS")))

            scenario_dir = c.SCENARIOS_CUSTOM_DIR
            if not os.path.exists(scenario_dir):
                os.makedirs(scenario_dir)

            scenarios = os.listdir(scenario_dir)
            total_content_height = len(scenarios) * 60
            self.max_scroll = min(0, (c.SCREEN_HEIGHT - 200) - total_content_height - 20)

            for i, name in enumerate(scenarios):
                if self.deleting_scenario == name or self.renaming_scenario == name:
                    continue
                    
                btn_y = 150 + (i * 60) + self.scroll_y
                if not (100 < btn_y < c.SCREEN_HEIGHT - 120):
                    continue

                self.elements.append(
                    Button(c.SCREEN_WIDTH // 2 - 250, btn_y, "new_game", "blue", name, 
                           lambda n=name: self.start_editor_with_custom_map(n))
                )
                self.elements.append(
                    Button(c.SCREEN_WIDTH // 2 + 70, btn_y + 5, "small", "grey", "Rename",
                           lambda n=name: self.start_rename(n))
                )
                self.elements.append(
                    Button(c.SCREEN_WIDTH // 2 + 190, btn_y + 5, "small", "green", "Export",
                           lambda n=name: self.export_scenario_zip(n))
                )
                self.elements.append(
                    Button(c.SCREEN_WIDTH // 2 + 310, btn_y + 5, "small_square", "red", "X",
                           lambda n=name: self.trigger_delete_conf(n))
                )

        elif self.sub_state == "BASE_MAPS":
            self.elements.append(Button(20, 20, "small", "red", "Back", lambda: self.set_sub_state("CUSTOM_MAPS")))
            self.elements.append(Button(c.SCREEN_WIDTH - 220, 20, "medium", "purple", "Data Refresh", self.trigger_base_map_data_refresh))
            
            base_dir = c.BASE_MAPS_DIR
            if not os.path.exists(base_dir):
                os.makedirs(base_dir)
                
            maps = os.listdir(base_dir)
            for i, name in enumerate(maps):
                btn_y = 150 + (i * 60)
                self.elements.append(
                    Button("centered", btn_y, "new_game", "blue", name, 
                           lambda n=name: self.start_editor_with_map(n))
                )

    def trigger_base_map_data_refresh(self):
        """Calls the unified data refresh query for base maps."""
        import tkinter as tk
        from tkinter import messagebox
        from data import queries
        
        root = queries.get_transient_tk_root()
        confirm = messagebox.askyesno(
            "Confirm Data Refresh",
            "Are you sure you want to refresh base map data?\nThis process may take a while.",
            parent=root
        )
        queries.destroy_tk_root(root)
        
        if confirm:
            dirs_to_check = [c.BASE_MAPS_DIR]
            queries.refresh_map_directories(self, dirs_to_check, success_message="Synced base maps successfully.")

    # --- FILE MANAGEMENT LOGIC ---
    def import_scenario_zip(self):
        root = queries.get_transient_tk_root()
        file_path = filedialog.askopenfilename(filetypes=[("Zip files", "*.zip")], parent=root)
        
        if file_path:
            save_name = Path(file_path).stem
            target_dir = os.path.join(c.SCENARIOS_CUSTOM_DIR, save_name)
            if os.path.exists(target_dir): target_dir += "_imported"
            try:
                with zipfile.ZipFile(file_path, 'r') as zip_ref: 
                    zip_ref.extractall(target_dir)
                self.refresh_maps()
                messagebox.showinfo("Import Success", "Scenario Imported successfully.", parent=root)
            except Exception as e: 
                messagebox.showerror("Import Error", str(e), parent=root)
                
        queries.destroy_tk_root(root)

    def export_scenario_zip(self, scenario_name):
        root = queries.get_transient_tk_root()
        try:
            source_path = os.path.join(c.SCENARIOS_CUSTOM_DIR, scenario_name)
            zip_filename = os.path.join(str(Path.home() / "Downloads"), f"{scenario_name}_scenario.zip")
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root_dir, dirs, files in os.walk(source_path):
                    for file in files:
                        zipf.write(os.path.join(root_dir, file), os.path.relpath(os.path.join(root_dir, file), source_path))
            messagebox.showinfo("Export Success", f"Exported to Downloads as {scenario_name}_scenario.zip", parent=root)
        except Exception as e: 
            messagebox.showerror("Export Error", str(e), parent=root)
            
        queries.destroy_tk_root(root)

    def start_rename(self, scenario_name):
        self.renaming_scenario = scenario_name
        self.new_name_text = scenario_name
        self.refresh_maps()

    def finish_rename(self):
        if self.new_name_text.strip() != "" and self.new_name_text != self.renaming_scenario:
            old_path = os.path.join(c.SCENARIOS_CUSTOM_DIR, self.renaming_scenario)
            new_path = os.path.join(c.SCENARIOS_CUSTOM_DIR, self.new_name_text.strip())
            if not os.path.exists(new_path): 
                os.rename(old_path, new_path)
        self.renaming_scenario = None
        self.refresh_maps()

    def trigger_delete_conf(self, scenario_name):
        self.deleting_scenario = scenario_name
        self.refresh_maps()

    def confirm_delete(self):
        if self.deleting_scenario:
            path = os.path.join(c.SCENARIOS_CUSTOM_DIR, self.deleting_scenario)
            if os.path.exists(path):
                shutil.rmtree(path)
        self.deleting_scenario = None
        self.refresh_maps()

    def cancel_delete(self):
        self.deleting_scenario = None
        self.refresh_maps()

    def _snap_scroll(self, my):
        self.scroll_y = ui_bars.calculate_scroll_snap(my, self.max_scroll, 150, c.SCREEN_HEIGHT - 200)
        self.refresh_maps()

    def start_editor_with_custom_map(self, map_name):
        self.selected_save_path = os.path.join(c.SCENARIOS_CUSTOM_DIR, map_name)
        self.set_sub_state("CUSTOM_MAPS")
        self.next_state = "MAP"
        self.done = True

    def start_editor_with_map(self, map_name):
        self.selected_save_path = os.path.join(c.BASE_MAPS_DIR, map_name)
        self.set_sub_state("CUSTOM_MAPS")
        self.next_state = "MAP"
        self.done = True

    def exit_to_menu(self):
        self.set_sub_state("CUSTOM_MAPS")
        self.next_state = "MENU"
        self.done = True

    def handle_back_key(self):
        if self.sub_state == "BASE_MAPS":
            self.set_sub_state("CUSTOM_MAPS")
        else:
            self.exit_to_menu()
            
    def handle_events(self, events):
        import pygame
        if getattr(self, 'is_refreshing', False):
            return
            
        for event in events:
            if self.renaming_scenario:
                is_valid_char = lambda ch: ch.isalnum() or ch in " _-"
                self.new_name_text, status = process_text_input(event, self.new_name_text, validation_func=is_valid_char)
                if status == "SUBMIT": self.finish_rename()
                elif status == "CANCEL": 
                    self.renaming_scenario = None
                    self.refresh_maps()
                continue
                
            if self.deleting_scenario:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN: self.confirm_delete()
                    elif event.key == pygame.K_ESCAPE: self.cancel_delete()
                continue

            if self.sub_state == "CUSTOM_MAPS":
                if event.type == pygame.MOUSEWHEEL:
                    self.scroll_y += event.y * 40
                    self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))
                    self.refresh_maps()

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

            super().handle_events([event])

    def draw(self, surface):
        import pygame
        surface.fill(self.bg_color)
        
        title_text = "EDIT EXISTING MAP" if self.sub_state == "CUSTOM_MAPS" else "CREATE NEW MAP FROM BASE"
        ui_bars.draw_centered_title(surface, title_text, 40)

        if self.sub_state == "CUSTOM_MAPS":
            # Draw Scrollbar
            self.scroll_track_rect, self.scroll_handle_rect = ui_bars.draw_standard_scrollbar(
                surface, self.scroll_y, self.max_scroll, c.SCREEN_WIDTH - 40, 150, c.SCREEN_HEIGHT - 200
            )

            # Rename Box
            if self.renaming_scenario:
                scenario_dir = c.SCENARIOS_CUSTOM_DIR
                scenarios = os.listdir(scenario_dir)
                idx = scenarios.index(self.renaming_scenario) if self.renaming_scenario in scenarios else 0
                box_y = 150 + (idx * 60) + self.scroll_y
                
                input_rect = pygame.Rect(c.SCREEN_WIDTH // 2 - 250, box_y, 300, 50)
                pygame.draw.rect(surface, (100, 100, 100), input_rect)
                pygame.draw.rect(surface, (255, 255, 255), input_rect, 2)
                
                font = fonts.get("heading2")
                txt_surf = font.render(self.new_name_text + "|", True, (255, 255, 255))
                surface.blit(txt_surf, (input_rect.x + 10, input_rect.y + 10))
                
                instr = fonts.get("normal").render("Enter: Save | Esc: Cancel", True, (200, 200, 200))
                surface.blit(instr, (input_rect.x, input_rect.y - 25))

            # Delete Confirmation
            if self.deleting_scenario:
                ui_bars.draw_fullscreen_overlay(surface, 180)
                
                pop_rect = pygame.Rect(0, 0, 500, 200)
                pop_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
                ui_bars.draw_modal_box(surface, pop_rect, bg_color=(60, 20, 20), border_color=(255, 50, 50), border_width=3)
                
                font = fonts.get("heading2")
                msg = font.render(f"Delete '{self.deleting_scenario}'?", True, (255, 255, 255))
                msg_rect = msg.get_rect(center=(pop_rect.centerx, pop_rect.y + 60))
                surface.blit(msg, msg_rect)
                
                sub_msg = fonts.get("normal").render("Press Enter to Confirm or Esc to Cancel", True, (200, 200, 200))
                sub_rect = sub_msg.get_rect(center=(pop_rect.centerx, pop_rect.y + 110))
                surface.blit(sub_msg, sub_rect)

        for el in self.elements:
            if el.visible:
                el.draw(surface)

        # --- Draw Progress Bar Overlay ---
        if getattr(self, 'is_refreshing', False):
            loading_screen.draw_simple_refresh_bar(surface, self.refresh_status, self.refresh_completed, self.refresh_total)