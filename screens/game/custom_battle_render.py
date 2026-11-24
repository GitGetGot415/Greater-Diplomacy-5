"""Battlefield drawing: terrain, foliage, units, shots, explosions, and edge markers."""

import math

import pygame

from map_logic import naval_battle as naval
from map_logic import tactical_rules as rules
from screens.game import custom_battle_layout as layout
from screens.game import custom_battle_sprites as sprites
from ui.rendering.font_manager import fonts
from ui.widgets import flag_icons
import data.constants as c


class BattleRender:
    """Battlefield drawing: terrain, foliage, units, shots, explosions, and edge markers."""

    def _draw_controls(self, surface, fighter, center):
        """Range, firing cone, gun direction, heading arrow, and reload for the controlled sub-unit only."""
        zoom = self.zoom
        slots = range(len(naval.mounts(fighter.shape))) if fighter.naval else (0,)
        for slot in slots:
            bearing, cone = naval.sector(fighter, slot) if fighter.naval else (fighter.angle, rules.firing_cone(fighter.shape))
            origin = self.to_screen(*naval.mount_position(fighter, slot)) if fighter.naval else center
            reach = round(fighter.weapon(slot).get("range", rules.WEAPON_RANGE) * zoom)
            if cone is None:
                pygame.draw.circle(surface, layout.RANGE_COLOR, origin, reach, 1)
            else:
                steps = max(1, math.ceil(cone / layout.CONE_ARC_STEP))
                start = bearing - cone / 2
                edge = [(origin[0] + math.cos(start + cone * step / steps) * reach, origin[1] + math.sin(start + cone * step / steps) * reach) for step in range(steps + 1)]
                pygame.draw.lines(surface, layout.RANGE_COLOR, True, [origin, *edge])
            aim = fighter.weapon_aim(slot)
            end = (origin[0] + math.cos(aim) * reach, origin[1] + math.sin(aim) * reach)
            pygame.draw.line(surface, layout.AIM_LINE_COLOR, origin, end, 1)
        indicator_scale = max(layout.MIN_PLAYER_INDICATOR_SCALE, zoom)
        pygame.draw.circle(surface, layout.PLAYER_COLOR, center, max(layout.PLAYER_RING_RADIUS, fighter.radius + 4) * indicator_scale, 2)
        sprites.draw_player_arrow(surface, center, fighter.angle,
                          fighter.speed / fighter.max_speed if fighter.max_speed else 0.0, scale=indicator_scale)
        for slot in (0, 1):
            if fighter.weapon(slot) is None or fighter.weapon_cooldown(slot) <= 0:
                continue
            # The ring fills clockwise from the top as the weapon reloads.
            loaded = max(0.0, min(1.0, 1.0 - fighter.weapon_cooldown(slot) / fighter.reload_duration(slot)))
            radius = (max(layout.RELOAD_RING_RADIUS, fighter.radius + 8) + slot * 5) * indicator_scale
            steps = max(2, math.ceil(math.tau * loaded / layout.CONE_ARC_STEP))
            ring = [(center[0] + math.cos(-math.pi / 2 + math.tau * loaded * step / steps) * radius,
                     center[1] + math.sin(-math.pi / 2 + math.tau * loaded * step / steps) * radius)
                    for step in range(steps + 1)]
            pygame.draw.lines(surface, layout.RELOAD_COLOR if not slot else layout.PLAYER_COLOR, False, ring, 2)

    def _draw_grass(self, surface):
        """The battlefield and its faint, fixed checkerboard; anything past its edges is dark."""
        surface.fill(layout.OFF_FIELD_COLOR)
        zoom = self.zoom
        width, height = self.simulation.arena_size
        left, top = self.to_screen(0, 0)
        right, bottom = self.to_screen(width, height)
        field = pygame.Rect(left, top, right - left, bottom - top)
        color = layout.TERRAIN_COLORS[self.simulation.battlefield.terrain]
        check_color = tuple(min(255, channel + 4) for channel in color)
        surface.fill(color, field)
        span_width, span_height = self._view_span()
        columns = range(max(0, int(self.camera[0] // layout.GRASS_TILE)),
                        min(math.ceil(width / layout.GRASS_TILE), math.ceil((self.camera[0] + span_width) / layout.GRASS_TILE)))
        rows = range(max(0, int(self.camera[1] // layout.GRASS_TILE)),
                     min(math.ceil(height / layout.GRASS_TILE), math.ceil((self.camera[1] + span_height) / layout.GRASS_TILE)))
        # Squares sit on the battlefield, so they pan and zoom with it but never animate.
        edges_x = {column: (round((column * layout.GRASS_TILE - self.camera[0]) * zoom),
                            round((min(width, (column + 1) * layout.GRASS_TILE) - self.camera[0]) * zoom))
                   for column in columns}
        for row in rows:
            y0 = round((row * layout.GRASS_TILE - self.camera[1]) * zoom)
            y1 = round((min(height, (row + 1) * layout.GRASS_TILE) - self.camera[1]) * zoom)
            for column in columns:
                if (row + column) % 2:
                    x0, x1 = edges_x[column]
                    surface.fill(check_color, (x0, y0, x1 - x0, y1 - y0))
        pygame.draw.rect(surface, layout.OUTLINE_COLOR, field.inflate(6, 6), 3)

    def _trunk_sprite(self, size, width):
        """A trunk image scaled to its hitbox width at the current zoom."""
        source = sprites.trunk_art(size)
        pixels = max(2, round(width * self.zoom))
        key = "trunk", size, pixels
        if key not in self.terrain_sprites:
            height = max(2, round(source.get_height() * pixels / source.get_width()))
            self.terrain_sprites[key] = pygame.transform.scale(source, (pixels, height))
        return self.terrain_sprites[key]

    def _see_through_foliage(self, radius, color):
        """A foliage circle at FOLIAGE_ALPHA, so the sub-units and trunk beneath it show faintly."""
        key = "foliage", radius, color
        if key not in self.terrain_sprites:
            sprite = pygame.Surface((radius * 2 + 1, radius * 2 + 1), pygame.SRCALPHA)
            pygame.draw.circle(sprite, color, (radius, radius), radius)
            sprite.set_alpha(layout.FOLIAGE_ALPHA)
            self.terrain_sprites[key] = sprite
        return self.terrain_sprites[key]

    def _cache_terrain_art(self):
        """Cache terrain artwork at geometry/zoom changes; drawing only places surfaces.

        Ground features and tree trunks draw beneath units. Foliage draws above them as the canopy.
        """
        field = self.simulation.battlefield
        self.terrain_art_key = id(field), field.revision, self.zoom
        self.terrain_art = []
        self.canopy_art = []
        for feature in sorted(field.features, key=lambda feature: feature.kind == "tree"):
            if feature.destroyed:
                continue
            if feature.kind == "tree":
                self.terrain_art.append((feature, self._trunk_sprite(feature.trunk, feature.radius * 2)))
                # Only the green channel varies, so every tree stays a shade of FOLIAGE_COLOR.
                red, green, blue = layout.FOLIAGE_COLOR
                color = red, max(0, min(255, green + round(feature.shade * layout.FOLIAGE_GREEN_VARIATION))), blue
                radius = max(1, round(feature.foliage_radius * self.zoom))
                self.canopy_art.append((feature, self._see_through_foliage(radius, color)))
                continue
            radius = max(2, round(feature.radius * self.zoom))
            key = feature.kind, radius, feature.height if feature.kind == "hill" else 0
            if key not in self.terrain_sprites:
                art = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
                if feature.kind == "hill":
                    # Each contour represents the same height, so taller mounds
                    # have more bands. Mountain mounds keep their brown palette.
                    bands = [(1.0 - band * layout.HILL_CONTOUR_HEIGHT / feature.height,
                              tuple(max(0, min(255, channel + layout.HILL_BASE_SHADE + band * layout.HILL_CONTOUR_SHADE))
                                    for channel in layout.TERRAIN_COLORS[field.terrain]))
                             for band in range(math.ceil(feature.height / layout.HILL_CONTOUR_HEIGHT))]
                else:
                    colors = layout.FEATURE_COLORS[feature.kind]
                    bands = [(1.0 - band / (len(colors) + 1), color) for band, color in enumerate(colors)]
                for fraction, color in bands:
                    size = radius * fraction
                    points = []
                    step = max(1, round(layout.FEATURE_PIXEL_STEP * self.zoom))
                    for index in range(layout.FEATURE_OUTLINE_POINTS):
                        angle = math.tau * index / layout.FEATURE_OUTLINE_POINTS
                        points.append((radius + round(math.cos(angle) * size / step) * step,
                                       radius + round(math.sin(angle) * size / step) * step))
                    pygame.draw.polygon(art, color, points)
                self.terrain_sprites[key] = art
            self.terrain_art.append((feature, self.terrain_sprites[key]))

    def _draw_terrain(self, surface):
        visible = surface.get_rect()
        for feature, art in self.terrain_art:
            rect = art.get_rect(center=self.to_screen(feature.x, feature.y))
            if rect.colliderect(visible):
                surface.blit(art, rect)

    def _draw_canopy(self, surface):
        """Draw every tree's cached, partly transparent foliage above units."""
        visible = surface.get_rect()
        for feature, art in self.canopy_art:
            rect = art.get_rect(center=self.to_screen(feature.x, feature.y))
            if rect.colliderect(visible):
                surface.blit(art, rect)

    def _draw_death_explosions(self, surface, limited_sight):
        if not self.death_explosions:
            return
        diameter = max(3, math.ceil(layout.DEATH_EXPLOSION_RADIUS * self.zoom) * 2 + 1)
        if self.death_explosion_circle is None or self.death_explosion_circle.get_width() != diameter:
            self.death_explosion_circle = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        for fighter, age, (circle_color, colors), point in self.death_explosions:
            if limited_sight and id(fighter) not in self.visible_fighters:
                continue
            progress = age / layout.DEATH_EXPLOSION_SECONDS
            center = self.to_screen(*point)
            radius = layout.DEATH_EXPLOSION_RADIUS * progress * self.zoom
            circle = self.death_explosion_circle
            circle.fill((0, 0, 0, 0))
            pygame.draw.circle(circle, (*circle_color, round(layout.DEATH_EXPLOSION_CIRCLE_ALPHA * (1 - progress))), (diameter // 2, diameter // 2), max(1, round(radius)))
            surface.blit(circle, circle.get_rect(center=center))
            size = max(1, round(layout.DEATH_EXPLOSION_PARTICLE_SIZE * (1 - progress) * self.zoom))
            color = colors[min(len(colors) - 1, int(progress * len(colors)))]
            for dx, dy in layout.DEATH_EXPLOSION_OFFSETS:
                rect = pygame.Rect(0, 0, size, size)
                rect.center = (round(center[0] + dx * radius), round(center[1] + dy * radius))
                layout.DEATH_EXPLOSION_DRAW_PARTICLE(surface, color, rect)

    def _draw_battle(self, surface):
        self._draw_grass(surface)
        self._draw_terrain(surface)
        zoom = self.zoom
        # Shapes partly on screen still draw; the widest shape fits inside this margin.
        margin = math.ceil(140 * zoom)
        visible = self.view_rect().inflate(margin, margin)
        bar_size = (round(28 * zoom), round(4 * zoom))
        flag_size = tuple(max(2, round(side * zoom)) for side in layout.BATTLE_FLAG_SIZE)
        controlled = self.simulation.controlled
        limited_sight = self.mode == "battle" and controlled is not None and controlled.alive and self.visibility_mask is not None
        labeled = []  # Living sub-units whose health bars and flags draw above the foliage.
        for fighter in self.simulation.fighters:
            if limited_sight and id(fighter) not in self.visible_fighters:
                continue
            center = self.to_screen(fighter.x, fighter.y)
            if not visible.collidepoint(center):
                continue
            if not fighter.alive:
                sprites.draw_unit_shape(surface, fighter.shape, center, fighter.angle, layout.DEAD_COLOR,
                                scale=zoom, aim=fighter.aim, secondary_aim=fighter.secondary_aim, artwork=self.battle_artwork[fighter.data["type"]], alpha=layout.SUBMARINE_ALPHA if fighter.shape == "submarine" else 255)
                continue
            scale = zoom
            sprites.draw_unit_shape(surface, fighter.shape, center, fighter.angle, layout.TEAM_COLORS[fighter.side],
                            scale=scale, aim=fighter.aim,
                            artwork=self.battle_artwork[fighter.data["type"]],
                            recoil=4 * fighter.recoil / c.TACTICAL_MUZZLE_SECONDS, secondary_aim=fighter.secondary_aim, mount_recoils=fighter.mount_recoils, alpha=layout.SUBMARINE_ALPHA if fighter.shape == "submarine" else 255)
            if fighter.naval:
                for slot in range(len(naval.mounts(fighter.shape))):
                    if fighter.mount_muzzles[slot] > 0:
                        tip = self.to_screen(*naval.muzzle_position(fighter, slot))
                        projectile = fighter.weapon(slot)["projectile"]
                        flash = max(2, round((2 if projectile == "bullet" else 5) * scale))
                        color = {"torpedo": layout.TORPEDO_WAKE_COLOR, "bullet": layout.SHOT_COLOR}.get(projectile, layout.ARTILLERY_SHOT_COLOR)
                        pygame.draw.rect(surface, color, (tip[0] - flash, tip[1] - flash, flash * 2, flash * 2))
            elif fighter.muzzle > 0:
                shell = fighter.weapon(fighter.fired_weapon)["shell"]
                length = layout.UNIT_SHAPE_SIZES[fighter.shape][0] / 2
                tip = (round(center[0] + math.cos(fighter.aim) * length * scale),
                       round(center[1] + math.sin(fighter.aim) * length * scale))
                flash = max(2, round((5 if shell else 2) * scale))
                pygame.draw.rect(surface, layout.TANK_SHOT_COLOR if shell else layout.SHOT_COLOR,
                                 (tip[0] - flash, tip[1] - flash, flash * 2, flash * 2))
            labeled.append((fighter, center, scale))
        line_width = max(1, round(layout.SHOT_WIDTH * zoom))
        tank_line_width = max(2, round(layout.TANK_SHOT_WIDTH * zoom))
        for shot in self.simulation.projectiles:
            head = self.to_screen(shot.x, shot.y)
            if shot.kind == "artillery_shell":
                elevated = (head[0], head[1] - round(max(0.0, shot.height) * layout.SHELL_HEIGHT_DRAW_SCALE * zoom))
                if visible.collidepoint(head) or visible.collidepoint(elevated):
                    size = max(2, round(4 * zoom))
                    pygame.draw.ellipse(surface, layout.ARTILLERY_SHADOW_COLOR, (head[0] - size, head[1] - size // 2, size * 2, size))
                    pygame.draw.rect(surface, layout.ARTILLERY_SHOT_COLOR, (elevated[0] - size // 2, elevated[1] - size // 2, size, size))
                continue
            if shot.kind == "torpedo":
                if visible.collidepoint(head):
                    speed = math.hypot(shot.vx, shot.vy) or 1.0
                    direction = shot.vx / speed, shot.vy / speed
                    tail = (head[0] - direction[0] * 36 * zoom, head[1] - direction[1] * 36 * zoom)
                    body = (head[0] - direction[0] * 12 * zoom, head[1] - direction[1] * 12 * zoom)
                    pygame.draw.line(surface, layout.TORPEDO_WAKE_COLOR, tail, head, max(1, round(3 * zoom)))
                    pygame.draw.line(surface, layout.TORPEDO_COLOR, body, head, max(2, round(5 * zoom)))
                continue
            if not visible.collidepoint(head):
                continue
            tail_length = layout.SHOT_TAIL * zoom / (math.hypot(shot.vx, shot.vy) or 1.0)
            tail = (round(head[0] - shot.vx * tail_length), round(head[1] - shot.vy * tail_length))
            tank_shell = shot.weapon_data["shell"]
            pygame.draw.line(surface, layout.TANK_SHOT_COLOR if tank_shell else layout.SHOT_COLOR, tail, head,
                             tank_line_width if tank_shell else line_width)
        for x, y, remaining, shell in self.simulation.impacts:
            point = self.to_screen(x, y)
            size = max(1, round((7 if shell else 3) * zoom * remaining / c.TACTICAL_IMPACT_SECONDS))
            color = layout.SPLASH_COLOR if shell in {"artillery_shell", "torpedo"} else layout.TANK_SHOT_COLOR if shell else layout.SHOT_COLOR
            pygame.draw.rect(surface, color,
                             (point[0] - size, point[1] - size, size * 2, size * 2), max(1, round(zoom)))
        self._draw_death_explosions(surface, limited_sight)
        self._draw_canopy(surface)
        for fighter, center, scale in labeled:
            bar = pygame.Rect(center[0] - bar_size[0] // 2, center[1] - round((fighter.radius + 8 if fighter.naval else 23) * scale), *bar_size)
            pygame.draw.rect(surface, layout.OUTLINE_COLOR, bar)
            ratio = max(0.0, min(1.0, fighter.data["health"] / fighter.data["max_health"]))
            sprites.draw_health_fill(surface, pygame.Rect(bar.x, bar.y, round(bar.width * ratio), bar.height), ratio)
            flag_icons.draw_flag(surface, fighter.data["owner"], self.country_data,
                                 bar.right + round(layout.BATTLE_FLAG_GAP * zoom),
                                 bar.centery - flag_size[1] // 2, size=flag_size)
        if controlled is not None and controlled.alive:
            self._draw_controls(surface, controlled, self.to_screen(controlled.x, controlled.y))
            self._draw_edge_indicators(surface, controlled)
        if limited_sight:
            # Cover terrain, bodies, labels, effects, and aiming guides together.
            # Screen controls and battle readouts are drawn above this world mask.
            surface.blit(self.visibility_mask, (0, 0))

    def _draw_edge_indicators(self, surface, controlled):
        """Group off-screen divisions by direction; show the nearest distance in each group."""
        bounds = self.view_rect().inflate(-layout.EDGE_INDICATOR_INSET * 2, -layout.EDGE_INDICATOR_INSET * 2)
        bounds.top = max(bounds.top, layout.EDGE_INDICATOR_TOP)
        origin = pygame.Vector2(self.to_screen(controlled.x, controlled.y))
        origin.x = max(bounds.left, min(bounds.right - 1, origin.x))
        origin.y = max(bounds.top, min(bounds.bottom - 1, origin.y))
        view = self.view_rect()
        indicators = {}
        for division in self.simulation.divisions:
            enemies = [unit for unit in division if unit.alive and unit.side != controlled.side and id(unit) in self.visible_fighters]
            if not enemies or any(view.collidepoint(self.to_screen(unit.x, unit.y)) for unit in enemies):
                continue
            enemy = min(enemies, key=lambda unit: math.hypot(unit.x - controlled.x, unit.y - controlled.y))
            direction = pygame.Vector2(self.to_screen(enemy.x, enemy.y)) - origin
            if direction.length_squared() == 0:
                continue
            direction.normalize_ip()
            horizontal = math.inf
            vertical = math.inf
            if direction.x:
                horizontal = ((bounds.right - 1 - origin.x) if direction.x > 0 else bounds.left - origin.x) / direction.x
            if direction.y:
                vertical = ((bounds.bottom - 1 - origin.y) if direction.y > 0 else bounds.top - origin.y) / direction.y
            point = origin + direction * min(horizontal, vertical)
            edge = ("right" if direction.x > 0 else "left") if horizontal <= vertical else ("bottom" if direction.y > 0 else "top")
            along = point.y if horizontal <= vertical else point.x
            key = edge, round(along / layout.EDGE_INDICATOR_SPACING)
            distance = math.hypot(enemy.x - controlled.x, enemy.y - controlled.y)
            count = 1
            if key in indicators:
                previous = indicators[key]
                count += previous[3]
                if previous[2] < distance:
                    point, direction, distance = previous[:3]
            indicators[key] = point, direction, distance, count
        for point, direction, distance, count in indicators.values():
            sideways = pygame.Vector2(-direction.y, direction.x)
            size = layout.EDGE_INDICATOR_SIZE
            points = [point, point - direction * size * 2 + sideways * size,
                      point - direction * size * 2 - sideways * size]
            pygame.draw.polygon(surface, layout.OUTLINE_COLOR, points)
            color = layout.TEAM_COLORS[1 - controlled.side]
            pygame.draw.polygon(surface, color, points, 2)
            distance_label = str(round(distance / layout.EDGE_INDICATOR_LABEL_STEP) * layout.EDGE_INDICATOR_LABEL_STEP)
            caption = f"{count}x {distance_label}" if count > 1 else distance_label
            label = fonts.get("small").render(caption, True, color)
            label_rect = label.get_rect(center=point - direction * size * 3)
            label_rect.clamp_ip(view)
            surface.blit(label, label_rect)

    def draw_background(self, surface):
        """Keep the battlefield behind combat and the finished battle's result controls."""
        if self.mode in {"battle", "result"}:
            self._draw_battle(surface)
        else:
            super().draw_background(surface)
