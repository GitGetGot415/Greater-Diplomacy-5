import pygame
from map_functions.ui import sidebar_info, ui_info_popup
from map_functions.logic import map_utils

def handle_map_events(self, event):
    mx, my = pygame.mouse.get_pos()
    
    # 1. UI Check: Are we over the bars?
    on_ui = (self.top_bar_rect.collidepoint(mx, my) or 
            self.bot_bar_rect.collidepoint(mx, my))

    # 2. Camera Controls: Always allow Panning/Zooming
    # This lets the player look around before picking a country
    if event.type == pygame.MOUSEWHEEL:
        self.camera.handle_input(event, self, False)
        if self.selected_province and not self.selection_mode:
            center_camera_on_province(self)
        return

    self.camera.handle_input(event, self, on_ui)

    # 3. HOVER LOGIC: Calculate world coordinates and detect province under mouse
    # We do this BEFORE the selection_mode check so the glow works in both modes.
    if not on_ui:
        # Translate screen mouse to map world coordinates
        wx = ((mx / self.camera.zoom) + self.camera.pos.x) % self.map_w
        wy = ((my - self.top_ui_height) / self.camera.zoom) + self.camera.pos.y
        
        if 0 <= wy < self.map_h:
            color = self.id_map.get_at((int(wx), int(wy)))
            self.hovered_province = self.map_data.get((color.r, color.g, color.b))
            
            # Generate the glow surface if we moved to a new province
            if self.hovered_province:
                curr_id = self.hovered_province["id"]
                if curr_id != self.last_hovered_id:
                    self.hover_glow_surf, self.hover_glow_rect = map_utils.create_glow_surface(
                        self.id_map, self.hovered_province["map_color"]
                    )
                    self.last_hovered_id = curr_id
            else:
                self.last_hovered_id = None
                self.hover_glow_surf = None
        else: 
            self.hovered_province = self.hover_glow_surf = None
    else:
        # Clear hover if mouse moves over UI bars
        self.hovered_province = self.hover_glow_surf = None

    # 4. COUNTRY SELECTION MODE: Specifically for New Games
    if self.selection_mode:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # If the "Confirm/Cancel" box is up, check those buttons first
            if self.pending_selection:
                if hasattr(self, 'confirm_rect') and self.confirm_rect.collidepoint(mx, my):
                    self.confirm_player_country()
                elif hasattr(self, 'cancel_rect') and self.cancel_rect.collidepoint(mx, my):
                    self.cancel_selection()
                return # Block the click from hitting the map behind the box
            
            # If no box is up, use our hover data to pick a country
            if self.hovered_province:
                self.select_player_country(self.hovered_province)
        
        # return early so "Standard" logic below doesn't run during selection
        return 

    # 5. STANDARD MAP LOGIC: Runs only during normal gameplay
    # If a province is selected (menu is open), don't allow clicking other provinces
    if self.selected_province:
        # Clear hover data to keep the screen clean while the menu is open
        self.hovered_province = None
        self.hover_glow_surf = None
        return 

    # Normal Map Selection (Free Roam)
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        if self.hovered_province:
            self.selected_province = self.hovered_province
            center_camera_on_province(self)

def center_camera_on_province(self):
    """Calculates and snaps the camera to the selected province based on current zoom."""
    cx, cy = self.selected_province["center"]
    tx = cx - (pygame.display.get_surface().get_width() / self.camera.zoom / 2)
    ty = cy - ((pygame.display.get_surface().get_height() - self.total_ui_h) / self.camera.zoom / 2)
    
    self.camera.target_pos = pygame.Vector2(tx, ty)
    self.camera.pos = pygame.Vector2(tx, ty)