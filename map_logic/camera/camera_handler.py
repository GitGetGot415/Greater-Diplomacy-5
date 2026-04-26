import pygame
import data.constants as c

class MapCamera:
    def __init__(self, min_zoom):
        self.zoom = min_zoom
        self.target_zoom = min_zoom
        self.pos = pygame.Vector2(0, 0)
        self.target_pos = pygame.Vector2(0, 0)
        self.lerp_speed = 0.1
        # currently set to instant, but can be adjusted for smoother transitions

    def handle_input(self, event, self_map, on_ui):
        if event.type == pygame.MOUSEWHEEL:
            zoom_change = event.y * (0.1 * self.target_zoom)
            max_zoom = 10.0
            self.target_zoom = max(self_map.min_zoom, min(self.target_zoom + zoom_change, max_zoom))

        if event.type == pygame.MOUSEMOTION and event.buttons[2] and not on_ui:
            self.pos.x -= event.rel[0] / self.zoom
            self.pos.y -= event.rel[1] / self.zoom
            self.target_pos = pygame.Vector2(self.pos)

    def update(self, self_map, SCREEN_HEIGHT):
        # 1. Smooth Zoom
        if abs(self.zoom - self.target_zoom) > 0.001:
            mx, my = pygame.mouse.get_pos()
            w_pre = pygame.Vector2(((mx / self.zoom) + self.pos.x) % self_map.map_w, 
                                   ((my - self_map.top_ui_height) / self.zoom) + self.pos.y)
            self.zoom += (self.target_zoom - self.zoom) * self.lerp_speed
            self.pos.x = (w_pre.x - (mx / self.zoom)) % self_map.map_w
            self.pos.y = w_pre.y - ((my - self_map.top_ui_height) / self.zoom)
            self.target_pos = pygame.Vector2(self.pos)

        # 2. Smooth Pan
        if self.pos.distance_to(self.target_pos) > 0.1:
            dx = (self.target_pos.x - self.pos.x + self_map.map_w / 2) % self_map.map_w - self_map.map_w / 2
            self.pos.x += dx * self.lerp_speed
            self.pos.y += (self.target_pos.y - self.pos.y) * self.lerp_speed

        # 3. Clamping & Looping
        if self_map.loop_map:
            self.pos.x %= self_map.map_w
        else:
            # If not looping, clamp X between 0 and the max scroll distance
            max_x = self_map.map_w - (c.SCREEN_WIDTH / self.zoom) # Assuming 1600 width
            self.pos.x = max(0, min(self.pos.x, max(0, max_x)))

        max_y = self_map.map_h - ((SCREEN_HEIGHT - self_map.total_ui_h) / self.zoom)
        self.pos.y = max(0, min(self.pos.y, max(0, max_y)))

        self.pos.x = round(self.pos.x, 2)
        self.pos.y = round(self.pos.y, 2)
    
def get_dynamic_ocean_color(camera, min_zoom):
    """Calculates the RGB value for the ocean background based on current zoom level."""
    target_brightest_zoom = max(6.0, min_zoom * 2.0) 
    zoom_range = target_brightest_zoom - min_zoom
    
    if zoom_range > 0:
        t = (camera.zoom - min_zoom) / zoom_range
        t = max(0.0, min(1.0, t))
    else:
        t = 0.0

    dark_blue = (10, 20, 40)
    light_blue = (40, 100, 180)

    r = int(dark_blue[0] + t * (light_blue[0] - dark_blue[0]))
    g = int(dark_blue[1] + t * (light_blue[1] - dark_blue[1]))
    b = int(dark_blue[2] + t * (light_blue[2] - dark_blue[2]))

    return (r, g, b)

def center_camera_on_province(camera_obj, province_center, screen_width, screen_height, total_ui_h):
    """Calculates and snaps the camera to the selected province based on current zoom."""
    cx, cy = province_center
    tx = cx - (screen_width / camera_obj.zoom / 2)
    ty = cy - ((screen_height - total_ui_h) / camera_obj.zoom / 2)
    
    camera_obj.target_pos = pygame.Vector2(tx, ty)
    camera_obj.pos = pygame.Vector2(tx, ty)