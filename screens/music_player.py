import pygame
import os
import shutil
from tkinter import filedialog, messagebox
from data import queries
import ui_elements 
from gameState import GameState
from ui_elements import Button, Slider, process_text_input
from map_logic.rendering.font_manager import fonts
import data.constants as c
from data.io import keybind_io

song_y = 32

class Music_Player(GameState):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (25, 25, 30)
        self.return_state = "MENU"
        
        # Ensure directories and files exist
        if not os.path.exists(c.MUSIC_DIR):
            os.makedirs(c.MUSIC_DIR)
        
        self.selected_album = None
        self.view_mode = "PLAYLIST" 
        
        self.album_scroll_y = 0
        self.track_scroll_y = 0
        
        # Renaming state
        self.creating_album = False
        self.new_album_name = ""
        
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.handle_back_key)
        ]
        
        # --- Audio Sliders ---
        slider_x = c.SCREEN_WIDTH - 250
        
        self.elements.append(Slider(slider_x, 40, 200, "SFX Vol", self.controller.sfx_volume, self.set_sfx_volume))
        if c.USE_SOLOUD:
            self.elements.append(Slider(slider_x, 100, 200, "SFX Pitch", self.controller.sfx_pitch, self.set_sfx_pitch))

        self.elements.append(Slider(slider_x, 180, 200, "Music Vol", self.controller.music_volume, self.set_music_volume))
        if c.USE_SOLOUD:
            self.elements.append(Slider(slider_x, 240, 200, "Music Pitch", self.controller.music_pitch, self.set_music_pitch))
        
        # --- View Mode Toggles ---
        color_ed = "blue" if self.view_mode == "EDITOR" else "grey"
        color_pl = "blue" if self.view_mode == "PLAYLIST" else "grey"
        self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 20, 80, "medium", color_ed, "Album Editor", lambda: self.set_view_mode("EDITOR")))
        self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 240, 80, "medium", color_pl, "Active Playlist", lambda: self.set_view_mode("PLAYLIST")))
        
        y_offset = 120 + self.album_scroll_y
        
        # --- Left Column: Albums ---
        if self.creating_album:
            self.elements.append(Button(20, y_offset, "medium", "red", "Cancel", self.cancel_new_album))
            y_offset += 120 
        else:
            self.elements.append(Button(20, y_offset, "medium", "green", "+ New Album", self.start_new_album))
            y_offset += 60
            
        for album in sorted(self.controller.all_albums.keys()):
            # 1. Toggle ON/OFF
            is_active = album in self.controller.active_albums
            tog_color = "green" if is_active else "red"
            tog_text = "ON" if is_active else "OFF"
            self.elements.append(Button(20, y_offset, "small_square", tog_color, tog_text, lambda a=album: self.toggle_album(a), show_text=True))
            
            # 2. Select for Editor
            sel_color = "blue" if self.selected_album == album and self.view_mode == "EDITOR" else "grey"
            self.elements.append(Button(70, y_offset, "medium", sel_color, album, lambda a=album: self.select_album(a)))
            
            # 3. Delete Album
            self.elements.append(Button(290, y_offset, "small_square", "red", "X", lambda a=album: self.delete_album(a), show_text=True))
            y_offset += 60

        # --- Right Column: Tracks ---
        track_y = 150 + self.track_scroll_y
        
        if self.view_mode == "EDITOR":
            if self.selected_album:
                self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 20, track_y, "medium", "green", "+ Add Track", self.import_track))
                track_y += 60
                
                for track_path in self.controller.all_albums[self.selected_album]:
                    track_name = os.path.basename(track_path)
                    self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 20, track_y, "song", "grey", track_name, lambda: None))
                    self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 330, track_y, "tiny_square", "red", "X", lambda p=track_path: self.delete_track(p), show_text=True))
                    track_y += song_y
                    
        elif self.view_mode == "PLAYLIST":
            self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 20, track_y, "medium", "green", "Skip / Random Song", self.play_track))
            track_y += 60
            
            for track_path in self.controller.playlist:
                track_name = os.path.basename(track_path)
                is_playing = (self.controller.now_playing == track_path)
                color = "orange" if is_playing else "grey"
                
                self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 20, track_y, "song", color, track_name, lambda p=track_path: self.play_track(p)))
                track_y += song_y

    def play_track(self, track_path=None):
        """Helper to play a track and instantly update the UI colors."""
        if track_path:
            self.controller.play_specific_song(track_path)
        else:
            self.controller.play_random_song()
        self.refresh_ui()

    # --- AUDIO MODIFICATION HANDLERS ---
    def set_sfx_volume(self, val):
        self.controller.sfx_volume = val
        ui_elements.global_sfx_volume = val    
        
        # If using pygame mixer, update the loaded sounds live
        if not c.USE_SOLOUD:
            if getattr(ui_elements, 'pygame_click_sound', None):
                ui_elements.pygame_click_sound.set_volume(val)
            if getattr(ui_elements, 'pygame_slider_sound', None):
                ui_elements.pygame_slider_sound.set_volume(val)
                
        self.save_audio_settings()

    def set_music_volume(self, val):
        self.controller.music_volume = val
        if c.USE_SOLOUD:
            if self.controller.music_handle is not None:
                self.controller.soloud.set_volume(self.controller.music_handle, val)
        else:
            pygame.mixer.music.set_volume(val)
        self.save_audio_settings()

    def set_music_pitch(self, val):
        self.controller.music_pitch = val
        if self.controller.music_handle is not None:
            speed_mult = 0.5 + (val * 1.5) 
            self.controller.soloud.set_relative_play_speed(self.controller.music_handle, speed_mult)
        self.save_audio_settings()
        
    def set_sfx_pitch(self, val):
        self.controller.sfx_pitch = val
        ui_elements.global_sfx_pitch = val
        self.save_audio_settings()
        
    def save_audio_settings(self):
        queries.save_global_settings(self.controller)

    # --- PLAYLIST & EDITOR ACTIONS ---
    def set_view_mode(self, mode):
        self.view_mode = mode
        self.track_scroll_y = 0
        self.refresh_ui()

    def toggle_album(self, album):
        if album in self.controller.active_albums:
            self.controller.active_albums.remove(album)
        else:
            self.controller.active_albums.append(album)
            
        self.controller.save_active_albums()
        self.controller.build_playlist()
        self.refresh_ui()

    def select_album(self, album):
        self.selected_album = album
        self.set_view_mode("EDITOR")

    def start_new_album(self):
        self.creating_album = True
        self.new_album_name = ""
        self.refresh_ui()
        
    def cancel_new_album(self):
        self.creating_album = False
        self.new_album_name = ""
        self.refresh_ui()

    def delete_album(self, album):
        root = queries.get_transient_tk_root()
        if messagebox.askyesno("Confirm", f"Delete album '{album}' AND physically remove all its files from your disk?"):
            
            if self.controller.now_playing != "None" and album in self.controller.now_playing:
                if self.controller.music_handle is not None:
                    self.controller.soloud.stop(self.controller.music_handle)
                self.controller.now_playing = "None"

            # 1. Delete the physical folder from the disk
            album_dir = os.path.join(c.MUSIC_DIR, album)
            if os.path.exists(album_dir):
                try:
                    shutil.rmtree(album_dir)
                except Exception as e:
                    print(f"Error deleting album folder: {e}")
                    
            if album in self.controller.all_albums:
                del self.controller.all_albums[album]
                
            if album in self.controller.active_albums:
                self.controller.active_albums.remove(album)
                self.controller.save_active_albums()
                
            if self.selected_album == album:
                self.selected_album = None
                
            self.controller.build_playlist()
            self.refresh_ui()
            
        queries.destroy_tk_root(root)

    def import_track(self):
        root = queries.get_transient_tk_root()
        file_paths = filedialog.askopenfilenames(
            title="Select Music Files",
            filetypes=[("Audio Files", "*.mp3 *.wav *.ogg")]
        )
        queries.destroy_tk_root(root)

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
                    if clean_path not in self.controller.all_albums[self.selected_album]:
                        self.controller.all_albums[self.selected_album].append(clean_path)
                except Exception as e:
                    print(f"Failed to copy {file_name}: {e}")
                    
            self.controller.build_playlist()
            self.refresh_ui()

    def delete_track(self, track_path):
        if self.controller.now_playing == track_path:
            if self.controller.music_handle is not None:
                self.controller.soloud.stop(self.controller.music_handle)
            self.controller.now_playing = "None"

        # 1. Delete the physical file from the disk
        if os.path.exists(track_path):
            try:
                os.remove(track_path)
            except Exception as e:
                print(f"Error deleting track file: {e}")
                
        if self.selected_album and track_path in self.controller.all_albums[self.selected_album]:
            self.controller.all_albums[self.selected_album].remove(track_path)
            
        if track_path in self.controller.playlist:
            self.controller.build_playlist()
            
        self.refresh_ui()

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
            is_valid_char = lambda ch: ch.isalnum() or ch in " _-"
            self.new_album_name, status = process_text_input(event, self.new_album_name, max_length=20, validation_func=is_valid_char)
            
            if status == "SUBMIT":
                name = self.new_album_name.strip()
                if name and name not in self.controller.all_albums:
                    self.controller.all_albums[name] = []
                    new_dir = os.path.join(c.MUSIC_DIR, name)
                    if not os.path.exists(new_dir):
                        os.makedirs(new_dir)
                self.creating_album = False
                self.refresh_ui()
            elif status == "CANCEL":
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
        
        np_text = f"Now Playing: {os.path.basename(self.controller.now_playing)}" if self.controller.now_playing != "None" else "Now Playing: Nothing"
        surface.blit(font_norm.render(np_text, True, (255, 215, 0)), (c.MUSIC_LEFT_PANE_W + 20, 30))

        # Input Box for new album
        if self.creating_album:
            box_y = 120 + self.album_scroll_y + 60
            rect = pygame.Rect(20, box_y, 200, 50)
            pygame.draw.rect(surface, (100, 100, 100), rect)
            pygame.draw.rect(surface, (255, 255, 255), rect, 2)
            surface.blit(font_norm.render(self.new_album_name + "|", True, (255, 255, 255)), (rect.x + 10, rect.y + 15))

    def handle_back_key(self):
        self.next_state = getattr(self, 'return_state', 'MENU')
        self.done = True