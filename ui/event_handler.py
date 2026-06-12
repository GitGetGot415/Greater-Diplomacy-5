import pygame
from map_logic.rendering import map_utils
from map_logic.system32 import edit_province_ownership
import data.constants as c
from map_logic.camera import camera_handler
from map_logic.setup import player_setup
from data import queries

def handle_map_events(self, event):
    mx, my = pygame.mouse.get_pos()

    # --- POPUP INTERCEPT ---
    from ui import diplomatic_popups
    if diplomatic_popups.handle_events(self, event):
        return

    # --- HOTSEAT MULTIPLAYER HIJACK ---
    if getattr(self, 'show_player_ready_screen', False):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if hasattr(self, 'ready_btn_rect') and self.ready_btn_rect.collidepoint(mx, my):
                self.show_player_ready_screen = False
                
                # CRITICAL: Re-bake the relations/cores from the perspective of the new player!
                self.refresh_relations_map() 
                self.refresh_political_map() 
                self.refresh_fog_map()
                
                self.show_feedback(f"Turn started for {self.player_country}")
        return # Block all other map events!
        
    # --- CONFIRMATION LOGIC HIJACK ---
    if getattr(self, 'show_exit_confirmation', False):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            center_x, center_y = c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2
            
            yes_rect = pygame.Rect(center_x - 130, center_y + 20, 100, 40)
            no_rect = pygame.Rect(center_x + 30, center_y + 20, 100, 40)

            if yes_rect.collidepoint(mx, my):
                self.confirm_exit()
            elif no_rect.collidepoint(mx, my):
                self.cancel_exit()
        return # Block all other map events while confirming
        
    # --- AI THINKING HIJACK ---
    if getattr(self, 'ai_is_thinking', False):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if hasattr(self, 'force_skip_btn_rect') and self.force_skip_btn_rect.collidepoint(mx, my):
                self.force_skip_llm = True
                
                # --- IMPORTANT: Set the module-level abort flag so running threads instantly die ---
                from map_logic.ai import ai_handler
                ai_handler.FORCE_SKIP = True
                ai_handler.abort_ai_generation()
                
                self.show_feedback("Forcing AI to skip LLM generation...")
        return # Block all other map events while AI is processing!
    
    # 1. UI Check (make sure the mouse can't go through the ui bars)
    
    # Always check the top and bottom bars
    on_ui = self.top_bar_rect.collidepoint(mx, my) or self.bot_bar_rect.collidepoint(mx, my)

    # Only check the side bars if they are actually being rendered
    side_ui_hidden = self.selection_mode or getattr(self, 'hide_raised_rect', False)
    
    if not side_ui_hidden:
        if self.raised_rect.collidepoint(mx, my) or self.ui_background_rect.collidepoint(mx, my):
            on_ui = True

    # 2. Camera Controls (Always allow these so you can move while editing!)
    if event.type == pygame.MOUSEWHEEL:
        self.camera.handle_input(event, self, False)
        if self.selected_province and not self.selection_mode:
            camera_handler.center_camera_on_province(self.camera, self.selected_province["center"], c.SCREEN_WIDTH, c.SCREEN_HEIGHT, self.total_ui_h)
        return

    self.camera.handle_input(event, self, on_ui)

    # 3. HOVER LOGIC (CRITICAL: Must run before painting)
    if not on_ui:
        wx = ((mx / self.camera.zoom) + self.camera.pos.x) % self.map_w
        wy = ((my - self.top_ui_height) / (self.camera.zoom * self.camera.tilt_factor)) + self.camera.pos.y
        
        # --- ADD THIS: Safety clamping ---
        # Ensure wx/wy stay within valid bounds even if math is slightly off
        safe_x = max(0, min(int(wx), self.map_w - 1))
        safe_y = max(0, min(int(wy), self.map_h - 1))
        
        if 0 <= wy < self.map_h:
            # Use the clamped values
            color = self.id_map.get_at((safe_x, safe_y))
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
        if pygame.mouse.get_pressed()[0]: # Left Click
            if self.hovered_province:
                # --- NATION MODE ---
                if self.editor_mode == "NATION":
                    if self.hovered_province.get("owner") != self.brush_nation:
                        if self.hovered_province.get("owner") not in c.WATER_NATIONS:
                            edit_province_ownership.conquer_province(self, self.hovered_province, self.brush_nation)
                
                # --- CORE MODE ---
                elif self.editor_mode == "CORE":
                    if self.hovered_province.get("owner") not in c.WATER_NATIONS:
                        # If painting with Unclaimed, wipe the tile
                        if self.brush_nation in ["Unclaimed", "None", ""]:
                            edit_province_ownership.clear_cores(self, self.hovered_province)
                        else:
                            edit_province_ownership.add_core(self, self.hovered_province, self.brush_nation)
                
                # --- BUILDING MODE ---
                elif self.editor_mode == "BUILDING":
                    current_buildings = self.hovered_province.get("buildings", [])
                    
                    if self.brush_building == "None":
                        self.hovered_province["buildings"] = []
                    else:                        
                        # Stop Advanced Buildings on empty tiles
                        is_advanced = "Refinery" in self.brush_building or "Recruitment" in self.brush_building
                        if is_advanced and not queries.has_basic_factory(self.hovered_province):
                            self.show_feedback("Requires a Basic Factory first!")
                        else:
                            # Logic: Workshops/Factories are in the same "industrial" category
                            is_industrial = "Workshop" in self.brush_building or "Factory" in self.brush_building
                            is_recruitment = "Recruitment" in self.brush_building
    
                            new_list = []
                            for b in current_buildings:
                                # Keep existing building IF it's not the same type we are placing
                                # AND (if placing industrial) it's not also industrial
                                keep = True
                                if is_industrial and ("Workshop" in b or "Factory" in b):
                                    keep = False
                                if "Refinery" in self.brush_building and "Refinery" in b:
                                    keep = False
                                if is_recruitment and "Recruitment" in b:
                                    keep = False
    
                                if keep: new_list.append(b)
    
                            if self.brush_building not in new_list:
                                new_list.append(self.brush_building)
    
                            self.hovered_province["buildings"] = new_list

                # --- RESOURCE MODE ---
                elif self.editor_mode == "RESOURCE":
                    if getattr(self, "brush_resource_type", "None") == "None":
                        # Wipe all resources if the "None" brush is used
                        self.hovered_province["resources"] = {}
                    else:
                        # Ensure resources is a dictionary
                        if not isinstance(self.hovered_province.get("resources"), dict):
                            self.hovered_province["resources"] = {}
                        
                        self.hovered_province["resources"][self.brush_resource_type] = self.brush_resource_amount
        
        # ADD THIS: Right Click (or Middle Click)
        if pygame.mouse.get_pressed()[2]: # Right Click
            if self.hovered_province:
                if self.hovered_province.get("owner") not in c.WATER_NATIONS:
                    
                    if self.editor_mode == "CORE":
                        edit_province_ownership.remove_core(self, self.hovered_province, self.brush_nation)
                    else:
                        self.brush_nation = self.hovered_province.get("owner", "Unclaimed")
                        self.show_feedback(f"Picked: {self.brush_nation}")

        # --- NEW UNIT PLACEMENT LOGIC ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.hovered_province and getattr(self, "editor_mode", "") == "UNIT":
                if getattr(self, "brush_unit", "None") == "None":
                    self.hovered_province["units"] = []
                    self.show_feedback("Units cleared from province")
                else:
                    owner = self.hovered_province.get("owner", "Unclaimed")
                    if owner in c.UNPLAYABLE_NATIONS:
                        self.show_feedback("Cannot place units in unowned territory!")
                    else:
                        unit_stats = queries.get_unit_library().get(self.brush_unit, {})
                        
                        new_unit = {
                            "type": self.brush_unit,
                            "owner": owner,
                            "health": unit_stats.get("health", c.DEFAULT_UNIT_HP),
                            "max_health": unit_stats.get("health", c.DEFAULT_UNIT_HP),
                            "speed": unit_stats.get("speed", c.DEFAULT_UNIT_SPD),
                            "attack": unit_stats.get("attack", c.DEFAULT_UNIT_ATK),
                            "defense": unit_stats.get("defense", c.DEFAULT_UNIT_DEF),
                            "level": 0,
                            "order": {"type": "MOVE", "path": []}
                        }
                        self.hovered_province.setdefault("units", []).append(new_unit)
                        self.show_feedback(f"Placed {self.brush_unit} for {owner}")
        # --------------------------------
        
        # RETURN HERE: This stops the code from reaching the "Select Province" logic below
        return

    # 5. COUNTRY SELECTION MODE (Scenarios)
    if self.selection_mode:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.pending_selection:
                if hasattr(self, 'confirm_rect') and self.confirm_rect.collidepoint(mx, my):
                    player_setup.confirm_player_country(self)
                    # Refresh the fog map as soon as the player officially takes control of the country
                    self.refresh_fog_map()
                elif hasattr(self, 'cancel_rect') and self.cancel_rect.collidepoint(mx, my):
                    player_setup.cancel_selection(self)
                return 
            if self.hovered_province:
                player_setup.select_player_country(self, self.hovered_province)
        return 

    # --- NEW: Direct Map Message Editing ---
    # Moved ABOVE the "STANDARD GAME SELECTION" return block!
    if self.selected_province:
        owner = self.selected_province.get("owner")
        is_foreign = queries.is_foreign_playable(owner, self.player_country, self.nation_data)
        if is_foreign:
            # MAIL BOX! MAIL BOX! MAIL BOX!
            
            mail_rect = pygame.Rect(*c.PROVINCE_UI["mail_box"])
            
            # 1. Handle clicking the box to activate/deactivate it
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if mail_rect.collidepoint(event.pos):
                    self.mail_input_active = True
                else:
                    self.mail_input_active = False
            
            # 2. Handle typing and sending if the box is active
            elif getattr(self, "mail_input_active", False):
                from ui_elements import process_text_input
                from map_logic.diplomacy import diplomacy_logic
                
                self.mail_draft_text, status = process_text_input(
                    event, getattr(self, "mail_draft_text", ""), max_length=120
                )
                
                if status == "SUBMIT":
                    draft = self.mail_draft_text.strip()
                    if draft:
                        msg = diplomacy_logic.queue_text_message(self.nation_data, self.player_country, owner, draft)
                        self.show_feedback(msg)
                    else:
                        diplomacy_logic.cancel_text_message(self.nation_data, self.player_country, owner)
                        self.show_feedback("Draft cleared.")
                    self.mail_input_active = False

    # 6. STANDARD GAME SELECTION
    # Ignore clicks if a province is already selected, or if we are watching AI moves
    if self.selected_province or getattr(self, 'viewing_ai_moves', False):
        return 

    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        if self.hovered_province:
            self.selected_province = self.hovered_province
            camera_handler.center_camera_on_province(self.camera, self.selected_province["center"], c.SCREEN_WIDTH, c.SCREEN_HEIGHT, self.total_ui_h)
            
            # NEW: Load draft if one exists so the box isn't empty if you return
            owner = self.selected_province.get("owner")
            self.mail_draft_text = queries.get_message_draft(self.player_country, owner, self.nation_data)