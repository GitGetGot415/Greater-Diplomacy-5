import pygame
from map_functions.ui import sidebar_info, ui_info_popup
from map_functions.logic import map_utils

def handle_map_events(self, event):
    mx, my = pygame.mouse.get_pos()
    
    # 1. UI Check
    on_ui = (self.top_bar_rect.collidepoint(mx, my) or 
            self.bot_bar_rect.collidepoint(mx, my))

    # 2. Camera Controls (Always allow these so you can move while editing!)
    if event.type == pygame.MOUSEWHEEL:
        self.camera.handle_input(event, self, False)
        if self.selected_province and not self.selection_mode:
            center_camera_on_province(self)
        return

    self.camera.handle_input(event, self, on_ui)

    # 3. HOVER LOGIC (CRITICAL: Must run before painting)
    if not on_ui:
        wx = ((mx / self.camera.zoom) + self.camera.pos.x) % self.map_w
        wy = ((my - self.top_ui_height) / self.camera.zoom) + self.camera.pos.y
        
        if 0 <= wy < self.map_h:
            color = self.id_map.get_at((int(wx), int(wy)))
            self.hovered_province = self.map_data.get((color.r, color.g, color.b))
            
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
        self.hovered_province = self.hover_glow_surf = None

    # 4. EDITOR PAINTING LOGIC
    # We do this AFTER hover logic so we know what we are hovering over
    if getattr(self, 'is_editor', False) and not on_ui:
        if pygame.mouse.get_pressed()[0]: # Left Click held
            if self.hovered_province:
                from map_functions.logic import edit_province_ownership
                if self.hovered_province.get("owner") != self.brush_nation:
                    # do not paint over oceans or lakes
                    if self.hovered_province.get("owner") != "Ocean" or self.hovered_province.get("owner") != "Lakes":
                        edit_province_ownership.conquer_province(self, self.hovered_province, self.brush_nation)
        
        # RETURN HERE: This stops the code from reaching the "Select Province" logic below
        return 

    # 5. COUNTRY SELECTION MODE (Scenarios)
    if self.selection_mode:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.pending_selection:
                if hasattr(self, 'confirm_rect') and self.confirm_rect.collidepoint(mx, my):
                    self.confirm_player_country()
                elif hasattr(self, 'cancel_rect') and self.cancel_rect.collidepoint(mx, my):
                    self.cancel_selection()
                return 
            if self.hovered_province:
                self.select_player_country(self.hovered_province)
        return 

    # 6. STANDARD GAME SELECTION
    if self.selected_province:
        return 

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