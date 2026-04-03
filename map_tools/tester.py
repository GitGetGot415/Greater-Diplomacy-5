import pygame
import json
import sys, os
import tkinter as tk
from tkinter import filedialog

sys.path.append(os.path.abspath(os.path.join('..', 'greater-diplomacy-5')))
from map_functions.rendering.font_manager import fonts
from gameState import SCREEN_WIDTH, SCREEN_HEIGHT

# --- NEW: Ask which map to test BEFORE starting Pygame ---
root = tk.Tk()
root.withdraw()
target_dir = filedialog.askdirectory(initialdir="base_maps", title="Select Map to Test")
root.destroy()

if not target_dir:
    print("No map selected.")
    sys.exit()

pygame.init()
WIDTH, HEIGHT = SCREEN_WIDTH, SCREEN_HEIGHT
screen = pygame.display.set_mode((WIDTH, HEIGHT))
clock = pygame.time.Clock()

pygame.display.set_caption(f"Map Tester - {os.path.basename(target_dir)}")
font = fonts.get("normal")

# --- 1. Optimized Data Loading (Using selected folder) ---
visual_map = pygame.image.load(os.path.join(target_dir, "terrain.png")).convert()
id_map = pygame.image.load(os.path.join(target_dir, "id_map.png")).convert()

with open(os.path.join(target_dir, "map_data.json"), "r") as f:
    raw_data = json.load(f)

# Optimization: Store by ID for instant lookups later
map_data = {}
id_to_province = {}

for k, v in raw_data.items():
    # Convert string "(r, g, b)" to actual tuple safely without eval()
    color_tuple = tuple(map(int, k.strip("()").split(",")))
    map_data[color_tuple] = v
    id_to_province[v["id"]] = v

# --- Camera Variables ---
camera_pos = pygame.Vector2(0, 0)
zoom = 1.0
target_zoom = 1.0
lerp_speed = 0.1 

selected_province = None
running = True

while running:
    # 2. Handle Events
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
            
        if event.type == pygame.MOUSEWHEEL:
            # Zoom speed scales with current zoom for consistency
            zoom_change = event.y * (0.1 * target_zoom)
            target_zoom = max(0.2, min(target_zoom + zoom_change, 6.0))
        
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                mx, my = pygame.mouse.get_pos()
                world_x = (mx / zoom) + camera_pos.x
                world_y = (my / zoom) + camera_pos.y
            
                if 0 <= world_x < id_map.get_width() and 0 <= world_y < id_map.get_height():
                    pixel_color = id_map.get_at((int(world_x), int(world_y)))
                    rgb = (pixel_color.r, pixel_color.g, pixel_color.b)
                    selected_province = map_data.get(rgb)

        if event.type == pygame.MOUSEMOTION:
            # If the RIGHT mouse button (index 2) is held down, pan the camera
            if event.buttons[2]: 
                # We divide by zoom so the map moves at the same speed as the cursor
                camera_pos.x -= event.rel[0] / zoom
                camera_pos.y -= event.rel[1] / zoom

    # 3. Smooth Zoom & Camera Logic
    if abs(zoom - target_zoom) > 0.001:
        mx, my = pygame.mouse.get_pos()
        world_m_pre = pygame.Vector2((mx / zoom) + camera_pos.x, (my / zoom) + camera_pos.y)
        zoom += (target_zoom - zoom) * lerp_speed
        camera_pos.x = world_m_pre.x - (mx / zoom)
        camera_pos.y = world_m_pre.y - (my / zoom)

    # 4. Panning Logic
    keys = pygame.key.get_pressed()
    pan_speed = 10 / zoom
    if keys[pygame.K_a]: camera_pos.x -= pan_speed
    if keys[pygame.K_d]: camera_pos.x += pan_speed
    if keys[pygame.K_w]: camera_pos.y -= pan_speed
    if keys[pygame.K_s]: camera_pos.y += pan_speed

    # 5. RENDERING (The Optimized Part)
    screen.fill((20, 20, 20))
    
    # Calculate what part of the image is visible (The "Source Rect")
    src_x = int(camera_pos.x)
    src_y = int(camera_pos.y)
    src_w = int(WIDTH / zoom)
    src_h = int(HEIGHT / zoom)

    # Clamp the source rect so it doesn't go off the original image edges
    # This prevents the "Subsurface out of bounds" error
    src_rect = pygame.Rect(src_x, src_y, src_w, src_h)
    clipped_rect = src_rect.clip(visual_map.get_rect())

    if clipped_rect.width > 0 and clipped_rect.height > 0:
        # Step A: Get a 'view' of the map without copying pixels
        map_view = visual_map.subsurface(clipped_rect)
        
        # Step B: Scale only the visible slice to fill the screen
        # We scale it to (clipped_width * zoom) to maintain aspect ratio
        scaled_view = pygame.transform.scale(map_view, (int(clipped_rect.width * zoom), int(clipped_rect.height * zoom)))
        
        # Step C: Blit with an offset if the camera is outside map bounds
        screen_x = max(0, (-camera_pos.x) * zoom)
        screen_y = max(0, (-camera_pos.y) * zoom)
        screen.blit(scaled_view, (screen_x, screen_y))

    # 6. Draw Debug Info (Optimized lookup)
    if selected_province:
        cx, cy = selected_province["center"]
        screen_cx = (cx - camera_pos.x) * zoom
        screen_cy = (cy - camera_pos.y) * zoom
        
        # Optimized Neighbor Lines: O(1) lookup using id_to_province
        for n_id in selected_province["neighbors"]:
            neighbor = id_to_province.get(n_id)
            if neighbor:
                nx, ny = neighbor["center"]
                screen_nx = (nx - camera_pos.x) * zoom
                screen_ny = (ny - camera_pos.y) * zoom
                pygame.draw.line(screen, (255, 255, 255), (screen_cx, screen_cy), (screen_nx, screen_ny), 2)
        
        pygame.draw.circle(screen, (0, 255, 0), (int(screen_cx), int(screen_cy)), max(1, int(5 * zoom)))

        info_text = f"ID: {selected_province['id']} | Terrain: {selected_province['terrain']}"
        text_surf = font.render(info_text, True, (255, 255, 255), (0, 0, 0))
        screen.blit(text_surf, (10, 10))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()