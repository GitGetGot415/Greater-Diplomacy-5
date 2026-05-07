import pygame
import os
import shutil
import json
import tkinter as tk
from tkinter import filedialog, messagebox
import ui_elements
from gameState import GameState
from ui_elements import Button, Slider, process_text_input
from map_logic.rendering.font_manager import fonts
import data.constants as c
from data.io import keybind_io

class Music_Player(GameState):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (25, 25, 30)
        self.return_state = "MENU"
        
        # Ensure directories and files exist
        if not os.path.exists(c.MUSIC_DIR):
            os.makedirs(c.MUSIC_DIR)
        
        self.albums = self.load_albums()
        self.selected_album = None
        self.now_playing = "None"
        
        self.album_scroll_y = 0
        self.track_scroll_y = 0
        
        # Renaming state
        self.creating_album = False
        self.new_album_name = ""
        
        self.refresh_ui()

    def load_albums(self):
        # We will scan the actual folders to make the hard drive the ultimate source of truth!
        synced_albums = {}
        
        if os.path.exists(c.MUSIC_DIR):
            for item in os.listdir(c.MUSIC_DIR):
                album_dir = os.path.join(c.MUSIC_DIR, item)
                
                if os.path.isdir(album_dir):
                    synced_albums[item] = []
                    for file in os.listdir(album_dir):
                        if file.lower().endswith(('.mp3', '.wav', '.ogg')):
                            # Normalize path slashes for cross-platform JSON storage
                            track_path = os.path.join(album_dir, file).replace("\\", "/")
                            synced_albums[item].append(track_path)
        
        # Overwrite the JSON with whatever was actually on the disk
        with open(c.ALBUMS_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(synced_albums, f, indent=4)
            
        return synced_albums

    def save_albums(self):
        with open(c.ALBUMS_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(self.albums, f, indent=4)

    def refresh_ui(self):
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.handle_back_key)
        ]
        
        # --- Volume Sliders ---
        self.elements.append(
            Slider(c.SCREEN_WIDTH - 250, 40, 200, "SFX Vol", self.controller.volume, self.set_sfx_volume)
        )
        self.elements.append(
            Slider(c.SCREEN_WIDTH - 250, 100, 200, "Music Vol", self.controller.music_volume, self.set_music_volume)
        )
        
        y_offset = 120 + self.album_scroll_y
        
        # --- Left Column: Albums ---
        if self.creating_album:
            self.elements.append(Button(20, y_offset, "medium", "red", "Cancel", self.cancel_new_album))
            y_offset += 60
        else:
            self.elements.append(Button(20, y_offset, "medium", "green", "+ New Album", self.start_new_album))
            y_offset += 60
            
        for album in sorted(self.albums.keys()):
            color = "green" if self.selected_album == album else "grey"
            self.elements.append(Button(20, y_offset, "medium", color, album, lambda a=album: self.select_album(a)))
            self.elements.append(Button(230, y_offset, "small_square", "red", "X", lambda a=album: self.delete_album(a), show_text=True))
            y_offset += 60

        # --- Right Column: Tracks ---
        if self.selected_album:
            track_y = 120 + self.track_scroll_y
            self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 20, track_y, "medium", "blue", "+ Add Track", self.import_track))
            track_y += 60
            
            for track_path in self.albums[self.selected_album]:
                track_name = os.path.basename(track_path)
                is_playing = (self.now_playing == track_path)
                color = "orange" if is_playing else "grey"
                
                self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 20, track_y, "large", color, track_name, lambda p=track_path: self.play_track(p)))
                self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 330, track_y, "small_square", "red", "X", lambda p=track_path: self.delete_track(p), show_text=True))
                track_y += 60

    # --- DUAL VOLUME HANDLERS ---
    def set_sfx_volume(self, val):
        self.controller.volume = val
        if ui_elements.click_sound:
            ui_elements.click_sound.set_volume(val)
        if ui_elements.slider_sound:
            ui_elements.slider_sound.set_volume(val)
        self.save_volumes()
        
    def set_music_volume(self, val):
        self.controller.music_volume = val
        pygame.mixer.music.set_volume(val)
        self.save_volumes()
        
    def save_volumes(self):
        keybind_io.save_settings(
            self.controller.keybinds, self.controller.volume, self.controller.music_volume, self.controller.num_players, 
            getattr(self.controller, 'ai_mode', c.DEFAULT_AI_MODE),
            getattr(self.controller, 'gemini_api_key', ''), getattr(self.controller, 'chatgpt_api_key', ''),
            getattr(self.controller, 'claude_api_key', ''), getattr(self.controller, 'ollama_api_key', ''),
            getattr(self.controller, 'gemini_model', ''), getattr(self.controller, 'chatgpt_model', ''),
            getattr(self.controller, 'claude_model', ''), getattr(self.controller, 'ollama_model', ''),
            getattr(self.controller, 'ai_immersion_level', 'FULL')
        )

    def select_album(self, album):
        self.selected_album = album
        self.track_scroll_y = 0
        self.refresh_ui()

    def start_new_album(self):
        self.creating_album = True
        self.new_album_name = ""
        self.refresh_ui()
        
    def cancel_new_album(self):
        self.creating_album = False
        self.new_album_name = ""
        self.refresh_ui()

    def delete_album(self, album):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        if messagebox.askyesno("Confirm", f"Delete album '{album}' AND physically remove all its files from your disk?"):
            
            # Stop the mixer if a track from this album is currently playing to unlock the file
            if self.now_playing != "None" and album in self.now_playing:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload() 
                self.now_playing = "None"

            # 1. Delete the physical folder from the disk
            album_dir = os.path.join(c.MUSIC_DIR, album)
            if os.path.exists(album_dir):
                try:
                    shutil.rmtree(album_dir)
                except Exception as e:
                    print(f"Error deleting album folder: {e}")
                    
            # 2. Remove it from our active dictionary
            if album in self.albums:
                del self.albums[album]
                
            if self.selected_album == album:
                self.selected_album = None
                
            self.save_albums()
            self.refresh_ui()
            
        root.destroy()
        pygame.event.pump()

    def import_track(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        file_paths = filedialog.askopenfilenames(
            title="Select Music Files",
            filetypes=[("Audio Files", "*.mp3 *.wav *.ogg")]
        )
        root.destroy()
        pygame.event.pump()

        if file_paths and self.selected_album:
            album_dir = os.path.join(c.MUSIC_DIR, self.selected_album)
            if not os.path.exists(album_dir):
                os.makedirs(album_dir)
                
            for path in file_paths:
                file_name = os.path.basename(path)
                dest_path = os.path.join(album_dir, file_name)
                try:
                    shutil.copy(path, dest_path)
                    # Normalize slashes for JSON storage
                    clean_path = dest_path.replace("\\", "/")
                    if clean_path not in self.albums[self.selected_album]:
                        self.albums[self.selected_album].append(clean_path)
                except Exception as e:
                    print(f"Failed to copy {file_name}: {e}")
                    
            self.save_albums()
            self.refresh_ui()

    def delete_track(self, track_path):
        # Stop the mixer if this specific track is playing to unlock the file
        if self.now_playing == track_path:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload() 
            self.now_playing = "None"

        # 1. Delete the physical file from the disk
        if os.path.exists(track_path):
            try:
                os.remove(track_path)
            except Exception as e:
                print(f"Error deleting track file: {e}")
                
        # 2. Remove it from our active dictionary
        if self.selected_album and track_path in self.albums[self.selected_album]:
            self.albums[self.selected_album].remove(track_path)
            self.save_albums()
            self.refresh_ui()

    def play_track(self, track_path):
        try:
            pygame.mixer.music.load(track_path)
            pygame.mixer.music.set_volume(self.controller.volume)
            pygame.mixer.music.play()
            self.now_playing = track_path
            self.refresh_ui()
        except Exception as e:
            print(f"Error playing track: {e}")

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)
            self.additional_events(event)

    def additional_events(self, event):
        mx, my = pygame.mouse.get_pos()
        
        # Scrolling
        if event.type == pygame.MOUSEWHEEL:
            if mx < c.MUSIC_LEFT_PANE_W:
                self.album_scroll_y += event.y * 30
                self.album_scroll_y = min(0, self.album_scroll_y)
            else:
                self.track_scroll_y += event.y * 30
                self.track_scroll_y = min(0, self.track_scroll_y)
            self.refresh_ui()
            
        # Typing Album Name
        if self.creating_album and event.type == pygame.KEYDOWN:
            is_valid_char = lambda c: c.isalnum() or c in " _-"
            self.new_album_name, status = process_text_input(event, self.new_album_name, max_length=20, validation_func=is_valid_char)
            
            if status == "SUBMIT":
                name = self.new_album_name.strip()
                if name and name not in self.albums:
                    self.albums[name] = []
                    # Physically create the empty folder on the disk
                    new_dir = os.path.join(c.MUSIC_DIR, name)
                    if not os.path.exists(new_dir):
                        os.makedirs(new_dir)                        
                    self.save_albums()
                self.creating_album = False
                self.refresh_ui()

    def additional_draw(self, surface):
        font_title = fonts.get("heading1")
        font_norm = fonts.get("normal")
        
        # Left Pane Background
        left_pane = pygame.Rect(0, 0, c.MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT)
        pygame.draw.rect(surface, (35, 35, 45), left_pane)
        pygame.draw.line(surface, (100, 100, 100), (c.MUSIC_LEFT_PANE_W, 0), (c.MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT), 2)
        
        # Top headers
        surface.blit(font_title.render("ALBUMS", True, (255, 255, 255)), (20, 80))
        surface.blit(font_title.render("TRACKS", True, (255, 255, 255)), (c.MUSIC_LEFT_PANE_W + 20, 80))
        
        # Now Playing
        np_text = f"Now Playing: {os.path.basename(self.now_playing)}" if self.now_playing != "None" else "Now Playing: Nothing"
        surface.blit(font_norm.render(np_text, True, (255, 215, 0)), (c.MUSIC_LEFT_PANE_W + 20, 30))

        # Input Box for new album
        if self.creating_album:
            idx = 1 # Assuming it's the second item down
            box_y = 120 + self.album_scroll_y + (idx * 60)
            rect = pygame.Rect(20, box_y, 200, 50)
            pygame.draw.rect(surface, (100, 100, 100), rect)
            pygame.draw.rect(surface, (255, 255, 255), rect, 2)
            surface.blit(font_norm.render(self.new_album_name + "|", True, (255, 255, 255)), (rect.x + 10, rect.y + 15))

    def handle_back_key(self):
        self.next_state = getattr(self, 'return_state', 'MENU')
        self.done = True