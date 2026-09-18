import pygame
import data.constants as c

class MapCamera:
    def __init__(self, min_zoom):
        self.zoom = min_zoom
        self.target_zoom = min_zoom
        self.pos = pygame.Vector2(0, 0)
        self.target_pos = pygame.Vector2(0, 0)
        self.lerp_speed = 0.1
        # An explicit map focus keeps its pan target intact while its zoom
        # eases.  Ordinary mouse-wheel zoom deliberately continues to anchor
        # beneath the cursor instead.
        self.focus_animation = False
        self.tilt_factor = 1.0
        self.manual_tilt_factor = 1.0 # Added explicit manual control factor
        self._middle_drag_last_pos = None
        self._ignore_middle_until_release = False
        # Right drag is available on the main map only.  Its release is kept
        # separate from the normal short right-click movement-order gesture.
        self._right_drag_last_pos = None
        self._right_drag_moved = False
        # currently set to instant, but can be adjusted for smoother transitions

    def cancel_middle_drag(self):
        """Stop a pan when a conflicting right-button gesture begins."""
        self._middle_drag_last_pos = None
        self._ignore_middle_until_release = True

    def finish_right_drag(self):
        """Clear a main-map right drag and report whether it panned.

        A short right-click must keep reaching the movement-order handler;
        only a drag consumes its matching release.
        """
        moved = self._right_drag_moved
        self._right_drag_last_pos = None
        self._right_drag_moved = False
        return moved

    def _pan_from_drag(self, current_pos, previous_pos):
        """Move the camera by a logical cursor displacement at the live zoom."""
        self.pos.x -= (current_pos[0] - previous_pos[0]) / self.zoom
        self.pos.y -= ((current_pos[1] - previous_pos[1])
                       / (self.zoom * self.tilt_factor))
        self.target_pos = pygame.Vector2(self.pos)

    def handle_input(self, event, self_map, on_ui, allow_right_drag=False):
        if event.type == pygame.KEYDOWN and event.key in (
                pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
            # KEYDOWN repeats are configured centrally in main.py.  Convert
            # the screen-distance tuning value to world space, keeping each
            # key press equally responsive at every zoom level.
            self.focus_animation = False
            step_x = c.CAMERA_KEYBOARD_PAN_PIXELS / self.zoom
            step_y = c.CAMERA_KEYBOARD_PAN_PIXELS / (self.zoom * self.tilt_factor)
            if event.key == pygame.K_LEFT:
                self.target_pos.x -= step_x
            elif event.key == pygame.K_RIGHT:
                self.target_pos.x += step_x
            elif event.key == pygame.K_UP:
                self.target_pos.y -= step_y
            else:
                self.target_pos.y += step_y
            return

        if event.type == pygame.MOUSEWHEEL:
            # Any manual zoom takes control away from the automatic country
            # framing animation, restoring the ordinary cursor-anchored zoom.
            self.focus_animation = False
            zoom_change = event.y * (0.1 * self.target_zoom)
            max_zoom = c.MAX_CAMERA_ZOOM
            self.target_zoom = max(self_map.min_zoom, min(self.target_zoom + zoom_change, max_zoom))

        # Pygame mouse_buttons indices: 0=Left, 1=Middle, 2=Right.  Camera
        # panning is deliberately fixed to middle mouse so map selection can
        # safely use left click and right-drag without competing for input.
        # Use logical cursor positions rather than event.rel: on high-DPI
        # displays rel can be reported in a different scale from the game
        # surface, which makes a pan feel faster or slower than the drag.
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
            self.focus_animation = False
            if self._ignore_middle_until_release:
                return
            self._middle_drag_last_pos = event.pos if not on_ui else None
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 2:
            self._middle_drag_last_pos = None
            self._ignore_middle_until_release = False
            return

        if allow_right_drag and event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            self.focus_animation = False
            self._right_drag_last_pos = event.pos if not on_ui else None
            self._right_drag_moved = False
            return

        if self._ignore_middle_until_release:
            return

        buttons = getattr(event, "buttons", ())
        middle_drag_active = ((len(buttons) > 1 and buttons[1])
                              or pygame.mouse.get_pressed()[1])
        right_drag_active = (allow_right_drag and ((len(buttons) > 2 and buttons[2])
                             or pygame.mouse.get_pressed()[2]))
        if event.type == pygame.MOUSEMOTION and middle_drag_active and not on_ui:
            current_pos = event.pos
            if self._middle_drag_last_pos is None:
                previous_pos = (current_pos[0] - event.rel[0],
                                current_pos[1] - event.rel[1])
            else:
                previous_pos = self._middle_drag_last_pos
            self._pan_from_drag(current_pos, previous_pos)
            self._middle_drag_last_pos = current_pos
        elif event.type == pygame.MOUSEMOTION and right_drag_active and not on_ui:
            current_pos = event.pos
            if self._right_drag_last_pos is None:
                previous_pos = (current_pos[0] - event.rel[0],
                                current_pos[1] - event.rel[1])
            else:
                previous_pos = self._right_drag_last_pos
            if current_pos != previous_pos:
                self._pan_from_drag(current_pos, previous_pos)
                self._right_drag_moved = True
            self._right_drag_last_pos = current_pos
        elif event.type == pygame.MOUSEMOTION and not middle_drag_active:
            self._middle_drag_last_pos = None

    def update(self, self_map, SCREEN_HEIGHT):
        # 0. Apply Manual Tilt Factor
        self.tilt_factor = self.manual_tilt_factor

        # 1. Smooth Zoom
        if abs(self.zoom - self.target_zoom) > 0.001:
            if self.focus_animation:
                self.zoom += (self.target_zoom - self.zoom) * self.lerp_speed
            else:
                mx, my = pygame.mouse.get_pos()
                world_x = (mx / self.zoom) + self.pos.x
                if self_map.loop_map:
                    world_x %= self_map.map_w
                w_pre = pygame.Vector2(
                    world_x,
                    ((my - self_map.top_ui_height) / (self.zoom * self.tilt_factor)) + self.pos.y,
                )
                self.zoom += (self.target_zoom - self.zoom) * self.lerp_speed
                self.pos.x = w_pre.x - (mx / self.zoom)
                if self_map.loop_map:
                    self.pos.x %= self_map.map_w
                self.pos.y = w_pre.y - ((my - self_map.top_ui_height) / (self.zoom * self.tilt_factor))
                self.target_pos = pygame.Vector2(self.pos)

        # 2. Smooth Pan
        if self.pos.distance_to(self.target_pos) > 0.1:
            if self_map.loop_map:
                dx = ((self.target_pos.x - self.pos.x + self_map.map_w / 2)
                      % self_map.map_w - self_map.map_w / 2)
            else:
                dx = self.target_pos.x - self.pos.x
            self.pos.x += dx * self.lerp_speed
            self.pos.y += (self.target_pos.y - self.pos.y) * self.lerp_speed

        # 3. Clamping & Looping
        if self_map.loop_map:
            self.pos.x %= self_map.map_w
        else:
            # In normal gameplay the raised left UI bar overlays the map.  Let
            # the view move left by that bar's world-space width so map x=0
            # can be placed immediately beside it rather than underneath it.
            left_ui_offset = 0
            if not getattr(self_map, "selection_mode", False) and not getattr(self_map, "hide_raised_rect", False):
                left_ui_offset = c.UI_LEFT_OFFSET
            min_x = -left_ui_offset / self.zoom
            max_x = self_map.map_w - (c.SCREEN_WIDTH / self.zoom)
            self.pos.x = max(min_x, min(self.pos.x, max(min_x, max_x)))

        max_y = self_map.map_h - ((SCREEN_HEIGHT - self_map.total_ui_h) / (self.zoom * self.tilt_factor))
        
        # --- NEW: Bottom Squish Logic ---
        if max_y < 0:
            # Map is vertically smaller than the viewport. 
            # Lock it to the bottom to reveal the sky above it.
            self.pos.y = max_y
        else:
            # Standard clamp when zoomed in
            self.pos.y = max(0, min(self.pos.y, max_y))

        self.pos.x = round(self.pos.x, 2)
        self.pos.y = round(self.pos.y, 2)
        if (self.focus_animation and abs(self.zoom - self.target_zoom) <= 0.001
                and self.pos.distance_to(self.target_pos) <= 0.1):
            self.focus_animation = False
    
def get_dynamic_ocean_color(camera, min_zoom):
    """Calculates the RGB value for the ocean background based on current zoom level."""
    target_brightest_zoom = max(6.0, min_zoom * 2.0) 
    zoom_range = target_brightest_zoom - min_zoom
    
    if zoom_range > 0:
        t = (camera.zoom - min_zoom) / zoom_range
        t = max(0.0, min(1.0, t))
    else:
        t = 0.0

    dark_blue = c.OCEAN_DARK_BLUE
    light_blue = c.OCEAN_LIGHT_BLUE
    
    r = int(dark_blue[0] + t * (light_blue[0] - dark_blue[0]))
    g = int(dark_blue[1] + t * (light_blue[1] - dark_blue[1]))
    b = int(dark_blue[2] + t * (light_blue[2] - dark_blue[2]))

    return (r, g, b)

def center_camera_on_province(camera_obj, province_center, screen_width, screen_height, total_ui_h, x_offset=0):
    """Calculates and snaps the camera to the selected province based on current zoom.

    x_offset shifts the camera left by that many screen pixels (at the current zoom),
    which pushes the province rendering to the right on screen -- used to keep the
    selected unit clear of the orders panel that occupies the left side of the screen.
    """
    cx, cy = province_center
    tx = cx - (screen_width / camera_obj.zoom / 2) - (x_offset / camera_obj.zoom)
    ty = cy - ((screen_height - total_ui_h) / (camera_obj.zoom * getattr(camera_obj, 'tilt_factor', 1.0)) / 2)
    
    camera_obj.target_pos = pygame.Vector2(tx, ty)
    camera_obj.pos = pygame.Vector2(tx, ty)


def focus_camera_on_position(camera_obj, world_position, screen_width, screen_height,
                             total_ui_h, target_zoom, animate=False):
    """Focus a camera on a world point, optionally easing pan and zoom together."""
    cx, cy = world_position
    tilt_factor = getattr(camera_obj, "tilt_factor", 1.0)
    target_pos = pygame.Vector2(
        cx - (screen_width / target_zoom / 2),
        cy - ((screen_height - total_ui_h) / (target_zoom * tilt_factor) / 2),
    )
    camera_obj.target_zoom = target_zoom
    camera_obj.target_pos = target_pos
    camera_obj.focus_animation = animate
    if not animate:
        camera_obj.zoom = target_zoom
        camera_obj.pos = pygame.Vector2(target_pos)
