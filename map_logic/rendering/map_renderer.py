import pygame
from map_logic.rendering import hover_renderer, province_select, overlay_renderer, country_names
from map_logic.turn_processing import loading_screen
from ui import minimap
from data import queries
from map_logic.diplomacy import faction_leadership
from map_logic import politics
import data.constants as c
import ui_elements
from map_logic.rendering.font_manager import fonts
from ui.bars import flag_renderer
from ui.information import tooltip, ui_info_popup as unit_info_popup
from ui.bars import resource_hud, top_bar_text, ui_bars
from screens.map_related_screens import recruit_ui
from ui import sidebar_info

def draw_map_screen(map_screen, surface):
    # --- HOTSEAT MULTIPLAYER OVERRIDE ---
    if map_screen.show_player_ready_screen:
        surface.fill((10, 10, 15)) # Deep black/blue
        
        font = fonts.get("title")
        display_name = map_screen.nation_data.get(map_screen.player_country, {}).get("name", map_screen.player_country)
        txt = font.render(f"Player {map_screen.current_player_index + 1} ({display_name}) Ready?", True, (255, 255, 255))
        surface.blit(txt, txt.get_rect(center=(surface.get_width()//2, surface.get_height()//2 - 50)))

        btn_font = fonts.get("heading2")
        btn_txt = btn_font.render("Click here to start turn", True, (150, 255, 150))
        map_screen.ready_btn_rect = btn_txt.get_rect(center=(surface.get_width()//2, surface.get_height()//2 + 50))
        surface.blit(btn_txt, map_screen.ready_btn_rect)
        
        return # Skip drawing the map and UI completely!

    # --- MULTI-TURN RENDER SKIP OPTIMIZATION ---
    if map_screen.multi_turns_total > 0 and map_screen.multi_turns_completed < map_screen.multi_turns_total:
        surface.fill((10, 10, 15))
        loading_screen.draw_turn_loading_screen(map_screen, surface)
        return
        
    # --- LAYER 1: THE BASE MAP ---
    current_base = map_screen.active_map

    vw = surface.get_width() / map_screen.camera.zoom
    vh = (surface.get_height() - map_screen.total_ui_h) / (map_screen.camera.zoom * map_screen.camera.tilt_factor)
    
    x1_world = map_screen.camera.pos.x
    y1_world = map_screen.camera.pos.y
    
    # --- NEW: Extract negative Y for screen offset and skybox ---
    render_y_offset = 0
    if y1_world < 0:
        render_y_offset = -y1_world * map_screen.camera.zoom * map_screen.camera.tilt_factor
        vh += y1_world # Shrink the required source height since the top is sky
        y1_world = 0

    x1, y1 = int(x1_world), int(y1_world)
    
    # Draw Skybox
    if render_y_offset > 0:
        sky_rect = pygame.Rect(0, map_screen.top_ui_height, c.SCREEN_WIDTH, int(render_y_offset) + 2) # +2 overlap to prevent seam tearing
        pygame.draw.rect(surface, c.COLOR_SKYBOX, sky_rect)

    if map_screen.loop_map:
        w1 = int(min(vw, map_screen.map_w - x1))
        h1 = int(min(vh, map_screen.map_h - y1))
        if w1 > 0 and h1 > 0:
            # Base Map
            v1 = current_base.subsurface((x1, y1, w1, h1))
            scaled_w1 = int(w1*map_screen.camera.zoom)
            scaled_h1 = int(h1*map_screen.camera.zoom*map_screen.camera.tilt_factor)
            surface.blit(pygame.transform.scale(v1, (scaled_w1, scaled_h1)), (0, map_screen.top_ui_height + int(render_y_offset)))
            
            # Fog Map
            if map_screen.fog_map:
                f1 = map_screen.fog_map.subsurface((x1, y1, w1, h1))
                surface.blit(pygame.transform.scale(f1, (scaled_w1, scaled_h1)), (0, map_screen.top_ui_height + int(render_y_offset)))
                
        if w1 < vw and h1 > 0:
            # Clamp to map_w: on a very wide/ultrawide viewport (e.g. the
            # borderless-fullscreen fallback in main.toggle_fullscreen uses
            # the monitor's native resolution, which can be much wider than
            # the design resolution min_zoom was calibrated against), vw can
            # exceed 2x the map width. This code only draws one wrap-around
            # copy, so anything beyond a full extra map-width would ask
            # subsurface() for pixels past current_base's actual edge.
            wrap_w = min(int(vw - w1), map_screen.map_w)
            if wrap_w > 0:
                scaled_wrap_w = int(wrap_w*map_screen.camera.zoom)
                scaled_h1 = int(h1*map_screen.camera.zoom*map_screen.camera.tilt_factor)
                
                # Base Map
                v2 = current_base.subsurface((0, y1, wrap_w, h1))
                surface.blit(pygame.transform.scale(v2, (scaled_wrap_w, scaled_h1)), (int(w1*map_screen.camera.zoom), map_screen.top_ui_height + int(render_y_offset)))
                
                # Fog Map
                if map_screen.fog_map:
                    f2 = map_screen.fog_map.subsurface((0, y1, wrap_w, h1))
                    surface.blit(pygame.transform.scale(f2, (scaled_wrap_w, scaled_h1)), (int(w1*map_screen.camera.zoom), map_screen.top_ui_height + int(render_y_offset)))
    else:
        src_rect = pygame.Rect(x1, y1, int(vw), int(vh))
        clipped = src_rect.clip(current_base.get_rect())
        if clipped.width > 0 and clipped.height > 0:
            scaled_w = int(clipped.width*map_screen.camera.zoom)
            scaled_h = int(clipped.height*map_screen.camera.zoom*map_screen.camera.tilt_factor)
            
            # Base Map
            view = current_base.subsurface(clipped)
            surface.blit(pygame.transform.scale(view, (scaled_w, scaled_h)), (0, map_screen.top_ui_height + int(render_y_offset)))
            
            # Fog Map
            if map_screen.fog_map:
                f_view = map_screen.fog_map.subsurface(clipped)
                surface.blit(pygame.transform.scale(f_view, (scaled_w, scaled_h)), (0, map_screen.top_ui_height + int(render_y_offset)))

    # --- CPU BOTTLENECK OPTIMIZATION ---
    # Pygame's transform functions (scale, rotate, tilt) are extremely heavy.
    # If we render thousands of units, arrows, and buildings at 60 FPS while the AI is thinking,
    # the Python GIL chokes the background thread and makes turn processing take forever!
    # By short-circuiting the render loop here, we save massive amounts of CPU time.
    if map_screen.ai_is_thinking or map_screen.is_refreshing or map_screen.is_saving:
        if map_screen.is_saving:
            loading_screen.draw_simple_refresh_bar(surface, map_screen.loading_status_text, map_screen.save_progress_completed, map_screen.save_progress_total)
        else:
            loading_screen.draw_turn_loading_screen(map_screen, surface)
        ui_bars.draw_ui_bars(map_screen, surface)
        if not map_screen.selection_mode:
            flag_renderer.draw_flag(map_screen, surface)
            top_bar_text.draw_top_text(map_screen, surface)
        return

    # --- LAYER 2: SELECTION & HOVER ---
    if not map_screen.selected_province:
        hover_renderer.draw_hover_glow(map_screen, surface)

    # --- LAYER 3: OVERLAYS (Units & Movement Arrows) ---
    # Keep the bubble records while the arrows are painted.  The bubbles are
    # blitted after this loop so an arrow ending at a fight cannot cover it.
    combat_records = overlay_renderer.draw_overlay_content(
        map_screen, surface, draw_combat=False)
    
    if map_screen.secondary_mode == "UNITS":
        for province in map_screen.map_data.values():
            for unit in province.get("units", []):
                if queries.is_unit_in_edge_battle(unit):
                    tag = unit.get("_edge_battle", {})
                    path = tag.get("retreat_path", []) if isinstance(tag, dict) else []
                    if not path:
                        continue

                    owner = unit.get("owner")
                    is_current_player_unit = (owner == map_screen.player_country)
                    is_spectator = map_screen.player_country == "Spectator"
                    if (not is_current_player_unit and not is_spectator
                            and not map_screen.viewing_ai_moves):
                        continue

                    is_tactical = map_screen.tactical_mode and map_screen.player_unit
                    force_vis = (unit is map_screen.player_unit) if is_tactical else is_current_player_unit
                    preview_tag = dict(tag)
                    preview_tag["retreat_path"] = path
                    owner_color = map_screen.nation_colors.get(owner, (255, 255, 0))
                    overlay_renderer.draw_edge_movement_path(
                        surface, map_screen, preview_tag, unit.get("speed", 1),
                        owner_color, force_visible=force_vis)
                    continue
                order = unit.get("order")
                if not order:
                    continue

                owner = unit.get("owner")

                # Only show the arrows for the CURRENT player taking their turn!
                is_current_player_unit = (owner == map_screen.player_country)
                is_spectator = map_screen.player_country == "Spectator"

                # Hide the arrows if it's not the current player's unit, the player isn't spectating,
                # and the game isn't actively resolving AI/global turns.
                if not is_current_player_unit and not is_spectator and not map_screen.viewing_ai_moves:
                    continue

                # --- NEW: Tell the renderer to bypass Fog of War if the player owns this specific unit ---
                # Fix for tactical mode: only force visible if it's the specific tactical unit
                is_tactical = map_screen.tactical_mode and map_screen.player_unit
                force_vis = (unit is map_screen.player_unit) if is_tactical else is_current_player_unit

                if order.get("type") == "BOMBARD":
                    target_id = order.get("target_id")
                    if target_id is not None:
                        bomb_range = queries.get_bombardment_range(unit.get("type", ""))
                        overlay_renderer.draw_bombardment_arrow(
                            surface, map_screen, province, target_id, bomb_range,
                            force_visible=force_vis)

                elif order.get("type") == "MOVE":
                    path = order.get("path", [])
                    if path:
                        speed = unit.get("speed", 1)

                        # If we are resolving global turns (viewing_ai_moves), hide future queued moves
                        # by truncating the path to only what happens this turn to prevent hotseat leaks
                        if map_screen.viewing_ai_moves:
                            path = path[:speed]
                            if not path:
                                continue

                        # Dynamically pull the color of the unit's owner (fallback to yellow)
                        owner_color = map_screen.nation_colors.get(
                            unit.get("owner", "Unclaimed"), (255, 255, 0))

                        overlay_renderer.draw_split_movement_path_until_midpoint(
                            surface, map_screen, province, path, speed,
                            owner_color, force_visible=force_vis)

    if map_screen.secondary_mode == "UNITS":
        overlay_renderer.draw_combat_bubbles(map_screen, surface, combat_records)
                            
    # --- LAYER 3.5: COUNTRY NAMES ---
    country_names.draw_country_names(map_screen, surface)
    
    # --- LAYER 3.8: PROVINCE MENU OVERLAYS ---
    if map_screen.selected_province:
        if map_screen.selection_mode:
            # Use the transparent black for country selection confirmation
            # Only the map area is dimmed here, not the UI bars, so this is a
            # rect panel rather than draw_fullscreen_overlay.
            map_area = pygame.Rect(0, map_screen.top_ui_height, surface.get_width(),
                                   surface.get_height() - map_screen.total_ui_h)
            ui_bars.draw_translucent_panel(surface, map_area, (0, 0, 0, 160))
        else:
            # Use the custom transparent PNG for the actual province menu
            # Pass the backgrounds directory to the image loader!
            province_bg = ui_bars.get_ui_image(c.PROVINCE_BG_FILE, directory=c.BACKGROUNDS_DIR)
            if province_bg.get_size() != surface.get_size():
                province_bg = pygame.transform.scale(province_bg, surface.get_size())
            surface.blit(province_bg, (0, 0))
            
        province_select.draw_province_select(map_screen, surface)

    # --- LAYER 4: UI BARS & HUD ---
    ui_bars.draw_ui_bars(map_screen, surface)
    
    if not map_screen.selection_mode:
        # Call our clean, separated functions instead!
        flag_renderer.draw_flag(map_screen, surface)
        top_bar_text.draw_top_text(map_screen, surface)
        resource_hud.draw_bottom_text(map_screen, surface)
        
        # Note: Sidebar info and minimap logic goes below here just like before
        if map_screen.selected_province: 
            sidebar_info.draw_sidebar_info(map_screen, surface)
            sidebar_info.draw_owner_portrait(map_screen, surface)
            unit_info_popup.draw_unit_info(map_screen, surface)
            
            # Always draw the queue! (Fog of War handles hiding contents)
            # if self.selected_province.get("owner") == self.player_country or self.player_country == "Spectator":
            recruit_ui.draw_map_queue_overlay(surface, map_screen.selected_province, map_screen)

        hide_mini = map_screen.hide_minimap or map_screen.selected_province
        if not hide_mini:
            minimap.draw_minimap(map_screen, surface, surface.get_width(), surface.get_height())

    # --- LAYER 5: SELECTION MODE ---
    else:
        if map_screen.pending_selection:
            disp_name = map_screen.nation_data.get(map_screen.pending_selection, {}).get("name", map_screen.pending_selection)
            
            # Contextual prompt formatting for Tactical Mode
            if map_screen.tactical_mode and getattr(map_screen, 'pending_unit', None):
                prompt_txt = f"Play as {map_screen.pending_unit.get('type')} ({disp_name})?"
            else:
                prompt_txt = f"Play as {disp_name}?"
        else:
            if map_screen.tactical_mode:
                prompt_txt = "Select a Unit to Control"
            else:
                prompt_txt = "Select a Country to Play As"
            
        big_font = fonts.get("title")
        txt = big_font.render(prompt_txt, True, (255, 255, 255))
        bg_rect = txt.get_rect(center=(surface.get_width()//2, 50))
        pygame.draw.rect(surface, (0, 0, 0, 180), bg_rect.inflate(20, 10))
        surface.blit(txt, bg_rect)

        # --- NEW: Scripted Events Checkmark ---
        if not map_screen.pending_selection:
            has_events = queries.scenario_has_scripted_events(map_screen.nation_data)
            cb_font = fonts.get("normal")

            if has_events:
                se_val = queries.get_scenario_flag("use_scripted_events", c.DEFAULT_USE_SCRIPTED_EVENTS, map_screen.scenario_settings)
                if se_val:
                    cb_text = "Scripted Events Enabled"
                else:
                    cb_text = "Scripted Events Disabled"
                cb_color = (255, 255, 255)
            else:
                se_val = False
                cb_text = "No Scripted Events Detected"
                cb_color = (150, 150, 150)

            txt_w = cb_font.size(cb_text)[0]
            total_w = 20 + 10 + txt_w
            start_x = surface.get_width() // 2 - total_w // 2
            start_y = c.SCREEN_HEIGHT - 40
            map_screen.se_checkbox_rect = pygame.Rect(start_x, start_y, 20, 20)

            bg_rect2 = pygame.Rect(start_x - 10, start_y - 5, total_w + 20, 30)
            pygame.draw.rect(surface, (0, 0, 0, 180), bg_rect2)

            pygame.draw.rect(surface, cb_color, map_screen.se_checkbox_rect, 2)
            if se_val and has_events:
                pygame.draw.rect(surface, (0, 255, 0), map_screen.se_checkbox_rect.inflate(-8, -8))

            cb_surf = cb_font.render(cb_text, True, cb_color)
            surface.blit(cb_surf, (map_screen.se_checkbox_rect.right + 10, map_screen.se_checkbox_rect.y))

        if map_screen.pending_selection:
            box_rect = pygame.Rect(0, 0, 400, 200)
            box_rect.center = (surface.get_width()//2, surface.get_height()//2)

            disp_name = map_screen.nation_data.get(map_screen.pending_selection, {}).get("name", map_screen.pending_selection)
            # Contextual instructions for Tactical Mode
            if map_screen.tactical_mode and getattr(map_screen, 'pending_unit', None):
                instr_txt = f"Start Game as {map_screen.pending_unit.get('type')}?"
            else:
                instr_txt = f"Start Game as {disp_name}?"

            # Published for ui/event_handler.py to hit-test -- see draw_confirm_prompt.
            map_screen.confirm_rect, map_screen.cancel_rect = ui_bars.draw_confirm_prompt(
                surface, box_rect, instr_txt, overlay_alpha=100)

    # --- LAYER 6: FEEDBACK & TOOLTIPS ---
    # Check flag before drawing the tooltip
    # this is the stuff that makes it so that if you select a province you don't display the tooltip
    if map_screen.hovered_province and not map_screen.selected_province and not map_screen.hide_tooltip: 
        tooltip.draw_tooltip(map_screen, surface)
        
    # --- LAYER 7: EXIT CONFIRMATION MODAL ---
    if map_screen.show_exit_confirmation:
        box_rect = pygame.Rect(0, 0, 450, 200)
        box_rect.center = (surface.get_width() // 2, surface.get_height() // 2)

        # Published rather than recomputed by the click handler. These used to be
        # written out again in ui/event_handler.py in a different coordinate
        # frame (centre-relative rather than box-relative); the two agreed only
        # because the box happened to be 200 tall, so resizing it here would
        # have silently moved the buttons out from under their own hitboxes.
        map_screen.exit_yes_rect, map_screen.exit_no_rect = ui_bars.draw_confirm_prompt(
            surface, box_rect, "Quit to Main Menu?", "Unsaved progress will be lost.",
            yes_label="EXIT", no_label="STAY",
            yes_color=(150, 0, 0), no_color=(0, 150, 0), hover=True)
    
def draw_badges(map_screen, surface):
    """Draws notification badges on top of buttons after the main UI renders."""
    if not map_screen.selection_mode and not map_screen.hide_raised_rect:

        # Get counts
        unread_msgs = queries.get_unread_message_count(map_screen.player_country, map_screen.nation_data)
        free_research = queries.has_free_research_slots(map_screen.player_country, map_screen.nation_data)
        incoming_claims = queries.get_incoming_justifications_count(map_screen.player_country, map_screen.nation_data, map_screen.id_to_province)
        # Everyone in the faction sees this, not only the leader and not only
        # the challenger: a handover changes who negotiates for the bloc and who
        # can put your provinces on the table, which is everybody's business.
        # contenders reads the counter faction_leadership.tick already wrote, so
        # this costs a dict lookup per member rather than a sweep of the map.
        my_faction = map_screen.nation_data.get(map_screen.player_country, {}).get("faction", "")
        leadership_contested = bool(
            faction_leadership.contenders(map_screen.nation_data, my_faction))

        def draw_badge(btn, text):
            if not btn.visible: return
            ui_elements.draw_notification_badge(surface, btn.rect, str(text))

        # Draw the badges on the respective buttons
        if unread_msgs > 0:
            draw_badge(map_screen.btn_gp_msgs, unread_msgs)

        if free_research:
            draw_badge(map_screen.btn_gp_rd, "!")

        if leadership_contested:
            draw_badge(map_screen.btn_gp_faction, "!")

        if incoming_claims > 0:
            draw_badge(map_screen.btn_gp_claims, incoming_claims)

        # Which way the country is drifting politically, and only while it is
        # actually going somewhere. politics.tick clears the direction on
        # reaching either end of the axis, so "we have arrived" and "the player
        # chose to hold" are one condition rather than two.
        political_drift = politics.drift(map_screen.nation_data, map_screen.player_country)
        if political_drift:
            draw_badge(map_screen.btn_gp_politics, "<" if political_drift < 0 else ">")
