import pygame
import data.constants as c
from data import queries


PAN_KEYBIND_DEFAULTS = {
    "left": ("PAN_LEFT", pygame.K_LEFT),
    "right": ("PAN_RIGHT", pygame.K_RIGHT),
    "up": ("PAN_UP", pygame.K_UP),
    "down": ("PAN_DOWN", pygame.K_DOWN),
}

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
        # Compatibility mirrors for the original middle/right gestures. The
        # active gesture itself is now tracked independently of button number.
        self._right_drag_last_pos = None
        self._right_drag_moved = False
        # Mouse Settings can assign map panning to any of the three buttons.
        # The old middle/right attributes remain as compatibility mirrors for
        # map overlays and focused camera tests.
        self._pan_drag_button = None
        self._pan_drag_last_pos = None
        self._pan_drag_moved = False
        self._finished_pan_drags = {}
        self._last_keyboard_pan_tick = None
        # currently set to instant, but can be adjusted for smoother transitions

    def cancel_middle_drag(self):
        """Stop the original middle-button pan when another gesture takes over."""
        if self._pan_drag_button == 2:
            self._pan_drag_button = None
            self._pan_drag_last_pos = None
            self._pan_drag_moved = False
        self._middle_drag_last_pos = None
        self._ignore_middle_until_release = True

    def finish_right_drag(self):
        """Clear a main-map right drag and report whether it panned.

        A short right-click must keep reaching the movement-order handler;
        only a drag consumes its matching release.
        """
        return self.finish_pan_drag(3)

    def finish_pan_drag(self, button):
        """Finish one configurable pan gesture and report whether it moved."""
        if self._pan_drag_button == button:
            moved = self._pan_drag_moved
            self._clear_pan_drag(button)
            return moved
        return self._finished_pan_drags.pop(button, False)

    def _clear_pan_drag(self, button):
        self._pan_drag_button = None
        self._pan_drag_last_pos = None
        self._pan_drag_moved = False
        if button == 2:
            self._middle_drag_last_pos = None
        elif button == 3:
            self._right_drag_last_pos = None
            self._right_drag_moved = False

    def _pan_from_drag(self, current_pos, previous_pos):
        """Move the camera by a logical cursor displacement at the live zoom."""
        self.pos.x -= (current_pos[0] - previous_pos[0]) / self.zoom
        self.pos.y -= ((current_pos[1] - previous_pos[1])
                       / (self.zoom * self.tilt_factor))
        self.target_pos = pygame.Vector2(self.pos)

    def _pan_with_arrow_keys(self, left, right, up, down, screen_distance):
        """Move the camera target by a screen-space keyboard distance."""
        self.focus_animation = False
        step_x = screen_distance / self.zoom
        step_y = screen_distance / (self.zoom * self.tilt_factor)
        self.target_pos.x += (right - left) * step_x
        self.target_pos.y += (down - up) * step_y

    @staticmethod
    def _configured_pan_keys():
        """Resolve all four persisted map-pan bindings at one input boundary."""
        return {direction: queries.get_keybind(action, default)
                for direction, (action, default) in PAN_KEYBIND_DEFAULTS.items()}

    def _pan_held_navigation_keys(self):
        """Continue navigation while a configured map-pan key is held.

        Pygame's global key-repeat delay is appropriate for text fields but
        makes camera panning pause after the first press.  Polling here keeps
        only map navigation continuous and avoids changing text input.
        """
        if pygame.display.get_surface() is None:
            # Lightweight tests and headless map tools can update a camera
            # without a display or keyboard device.
            self._last_keyboard_pan_tick = None
            return
        pressed = pygame.key.get_pressed()
        keys = self._configured_pan_keys()
        left = bool(pressed[keys["left"]])
        right = bool(pressed[keys["right"]])
        up = bool(pressed[keys["up"]])
        down = bool(pressed[keys["down"]])
        if not (left or right or up or down):
            self._last_keyboard_pan_tick = None
            return
        now = pygame.time.get_ticks()
        if self._last_keyboard_pan_tick is None:
            self._last_keyboard_pan_tick = now
            return
        elapsed_seconds = min(0.1, max(0, now - self._last_keyboard_pan_tick) / 1000)
        self._last_keyboard_pan_tick = now
        self._pan_with_arrow_keys(
            left, right, up, down,
            c.CAMERA_KEYBOARD_PAN_PIXELS_PER_SECOND * elapsed_seconds)

    def handle_input(self, event, self_map, on_ui, allow_right_drag=False,
                     pan_buttons=None):
        pan_keys = self._configured_pan_keys()
        if event.type == pygame.KEYDOWN and event.key in pan_keys.values():
            # Move once immediately; update() continues while the key remains
            # down, rather than waiting for the application's text-key delay.
            self._pan_with_arrow_keys(
                event.key == pan_keys["left"], event.key == pan_keys["right"],
                event.key == pan_keys["up"], event.key == pan_keys["down"],
                c.CAMERA_KEYBOARD_PAN_PIXELS)
            self._last_keyboard_pan_tick = pygame.time.get_ticks()
            return

        if event.type == pygame.MOUSEWHEEL:
            # Any manual zoom takes control away from the automatic country
            # framing animation, restoring the ordinary cursor-anchored zoom.
            self.focus_animation = False
            zoom_change = event.y * (0.1 * self.target_zoom)
            max_zoom = c.MAX_CAMERA_ZOOM
            self.target_zoom = max(self_map.min_zoom, min(self.target_zoom + zoom_change, max_zoom))

        # Pygame mouse_buttons indices: 0=Left, 1=Middle, 2=Right.  The
        # default preserves the original middle-only gesture; map screens may
        # supply Mouse Settings' enabled buttons.
        # Use logical cursor positions rather than event.rel: on high-DPI
        # displays rel can be reported in a different scale from the game
        # surface, which makes a pan feel faster or slower than the drag.
        if pan_buttons is None:
            pan_buttons = {2}
            if allow_right_drag:
                pan_buttons.add(3)
        else:
            pan_buttons = set(pan_buttons)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button in pan_buttons:
            self.focus_animation = False
            if event.button == 2 and self._ignore_middle_until_release:
                return
            self._pan_drag_button = event.button
            self._pan_drag_last_pos = event.pos if not on_ui else None
            self._pan_drag_moved = False
            if event.button == 2:
                self._middle_drag_last_pos = self._pan_drag_last_pos
            elif event.button == 3:
                self._right_drag_last_pos = self._pan_drag_last_pos
                self._right_drag_moved = False
            return
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2:
                self._ignore_middle_until_release = False
            if self._pan_drag_button == event.button:
                self._finished_pan_drags[event.button] = self._pan_drag_moved
                self._clear_pan_drag(event.button)
            return

        if self._ignore_middle_until_release:
            return

        buttons = getattr(event, "buttons", ())
        button = self._pan_drag_button
        button_index = button - 1 if button else None
        drag_active = (button_index is not None and (
            (len(buttons) > button_index and buttons[button_index])
            or pygame.mouse.get_pressed()[button_index]))
        if event.type == pygame.MOUSEMOTION and drag_active and not on_ui:
            current_pos = event.pos
            if self._pan_drag_last_pos is None:
                previous_pos = (current_pos[0] - event.rel[0],
                                current_pos[1] - event.rel[1])
            else:
                previous_pos = self._pan_drag_last_pos
            if current_pos != previous_pos:
                self._pan_from_drag(current_pos, previous_pos)
                self._right_drag_moved = True
                self._pan_drag_moved = True
            self._pan_drag_last_pos = current_pos
            if button == 2:
                self._middle_drag_last_pos = current_pos
            elif button == 3:
                self._right_drag_last_pos = current_pos
        elif event.type == pygame.MOUSEMOTION and button == 2 and not drag_active:
            self._clear_pan_drag(button)

    def update(self, self_map, SCREEN_HEIGHT):
        # 0. Apply Manual Tilt Factor
        self.tilt_factor = self.manual_tilt_factor
        self._pan_held_navigation_keys()

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
