"""Cached unit, terrain, and marker sprites for the tactical battle screen."""

from functools import lru_cache
import math
import os

import pygame

from map_logic import naval_battle as naval
from screens.game import custom_battle_layout as layout
from ui.rendering import symbol_loader
import data.constants as c


BODY_SPRITES = {}


ROTATED_SPRITES = {}


BATTLE_ART = {}


TRUNK_ART = {}


@lru_cache(maxsize=256)
def health_fill_surface(size, color):
    """Cache dithered health shading by fill dimensions and displayed color."""
    surface = pygame.Surface(size)
    # Light, middle, and dark bands; a checkerboard of the neighboring shade softens each edge.
    shades = [tuple(max(0, min(255, channel + layout.HEALTH_BAR_SHADE * (1 - band))) for channel in color) for band in range(layout.HEALTH_BAR_BANDS)]
    width, height = size
    for row in range(height):
        band = row * layout.HEALTH_BAR_BANDS // height
        first = band > 0 and (row - 1) * layout.HEALTH_BAR_BANDS // height < band
        last = band < layout.HEALTH_BAR_BANDS - 1 and (row + 1) * layout.HEALTH_BAR_BANDS // height > band
        for column in range(width):
            shade = band
            if (column + row) % 2 == 0:
                shade += 1 if last else -1 if first else 0
            surface.set_at((column, row), shades[shade])
    return surface


def draw_health_fill(surface, fill, ratio):
    if fill.width <= 0 or fill.height <= 0:
        return
    if ratio >= 0.5:
        low, high, blend = layout.HEALTH_BAR_HALF_COLOR, layout.HEALTH_BAR_FULL_COLOR, (ratio - 0.5) * 2
    else:
        low, high, blend = layout.HEALTH_BAR_EMPTY_COLOR, layout.HEALTH_BAR_HALF_COLOR, ratio * 2
    color = tuple(round(a + (b - a) * blend) for a, b in zip(low, high))
    surface.blit(health_fill_surface(fill.size, color), fill)


def trunk_art(size):
    """The unscaled "Trunk" image of one size, loaded once."""
    if size not in TRUNK_ART:
        TRUNK_ART[size] = pygame.image.load(os.path.join(layout.TERRAIN_ART_DIR, f"Trunk {size}.png")).convert_alpha()
    return TRUNK_ART[size]


def load_battle_art(artwork):
    """Load the chassis and optional weapon once, before the battlefield starts drawing."""
    if artwork not in BATTLE_ART:
        chassis = pygame.image.load(os.path.join(layout.BATTLE_ART_DIR, "chassis", artwork[0] + ".png")).convert_alpha()
        centered = None
        if artwork[1] is not None:
            turret = pygame.image.load(os.path.join(layout.BATTLE_ART_DIR, "turret", artwork[1] + ".png")).convert_alpha()
            # Weapons point right, with their base in the leftmost square of the image.
            # Pad the barrel side symmetrically so rotation keeps the base on the body center.
            pivot = turret.get_height() // 2
            centered = pygame.Surface((2 * (turret.get_width() - pivot), turret.get_height()), pygame.SRCALPHA)
            centered.blit(turret, (centered.get_width() // 2 - pivot, 0))
        BATTLE_ART[artwork] = chassis, centered
    return BATTLE_ART[artwork]


def battle_sprite(artwork, shape, part, color, scale):
    key = (artwork, shape, part, tuple(color), scale)
    if key not in BODY_SPRITES:
        chassis, turret = BATTLE_ART[artwork]
        width, height = layout.UNIT_SHAPE_SIZES[shape]
        source = turret if part == "turret" else chassis
        if part == "turret":
            factor = width * scale / chassis.get_width()
            size = tuple(max(1, round(side * factor)) for side in source.get_size())
        else:
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
        if shape in naval.SHAPES:
            tinted = source.copy()
            tinted.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
        else:
            tinted = symbol_loader.colorize_red_image(source, color)
        BODY_SPRITES[key] = pygame.transform.scale(tinted, size)
    return BODY_SPRITES[key]


def unit_sprite(shape, color, scale, barrel):
    """An unrotated silhouette pointing right; cached because battles draw hundreds per frame."""
    key = (shape, tuple(color), scale, barrel)
    if key not in BODY_SPRITES:
        width, height = layout.UNIT_SHAPE_SIZES[shape]
        width, height = round(width * scale), round(height * scale)
        sprite = pygame.Surface((width + 12, max(height, 24)), pygame.SRCALPHA)
        body = pygame.Rect(2, (sprite.get_height() - height) // 2, width, height)
        if shape in {"infantry", "cavalry"}:
            pygame.draw.ellipse(sprite, layout.OUTLINE_COLOR, body)
            pygame.draw.ellipse(sprite, color, body.inflate(-4, -4))
        else:
            radius = round(layout.ROUNDED_CORNER_RADIUS * scale) if shape in layout.ROUNDED_SHAPES else 0
            pygame.draw.rect(sprite, layout.OUTLINE_COLOR, body, border_radius=radius)
            pygame.draw.rect(sprite, color, body.inflate(-4, -4), border_radius=max(0, radius - 2))
            if barrel and shape not in layout.UNARMED_SHAPES:
                pygame.draw.line(sprite, layout.OUTLINE_COLOR, body.center,
                                 (sprite.get_width() - 1, body.centery), max(2, round(3 * scale)))
        BODY_SPRITES[key] = sprite
    return BODY_SPRITES[key]


def clear_rotated_sprites():
    """Drop the cached rotations, e.g. when the battlefield zoom changes, so old scales do not pile up."""
    ROTATED_SPRITES.clear()


def draw_rotated_sprite(surface, sprite, key, center, angle, *, alpha=255):
    step = round(math.degrees(angle) / layout.SPRITE_ANGLE_STEP) % (360 // layout.SPRITE_ANGLE_STEP)
    key = (*key, step, alpha)
    rotated = ROTATED_SPRITES.get(key)
    if rotated is None:
        rotated = pygame.transform.rotate(sprite, -step * layout.SPRITE_ANGLE_STEP)
        rotated.set_alpha(alpha)
        ROTATED_SPRITES[key] = rotated
    surface.blit(rotated, rotated.get_rect(center=center))


def draw_unit_shape(surface, shape, center, angle, color, *, scale=1.0, aim=None, artwork=None, recoil=0.0, secondary_aim=None, mount_recoils=None, alpha=255):
    """Draw battle artwork or geometric silhouettes in setup cards and on the field.

    With ``aim``, the turret or gun line follows ``aim`` independently of the hull.
    """
    if artwork is not None:
        if shape in naval.SHAPES:
            sprite = battle_sprite(artwork, shape, "chassis", color, scale)
            draw_rotated_sprite(surface, sprite, (artwork, shape, "chassis", tuple(color), scale), center, angle, alpha=alpha)
            if artwork[1] is not None:
                width, height = layout.UNIT_SHAPE_SIZES[shape]
                sprite = battle_sprite(artwork, shape, "turret", color, scale)
                aims = (angle if aim is None else aim, angle + math.pi if secondary_aim is None else secondary_aim)
                for slot, mount in enumerate(naval.mounts(shape)):
                    forward, sideways = width * mount.forward * scale, height * mount.sideways * scale
                    heading = aims[slot]
                    kick = 4 * mount_recoils[slot] / c.TACTICAL_MUZZLE_SECONDS if mount_recoils else 0.0
                    part_center = (center[0] + math.cos(angle) * forward - math.sin(angle) * sideways - math.cos(heading) * kick * scale, center[1] + math.sin(angle) * forward + math.cos(angle) * sideways - math.sin(heading) * kick * scale)
                    draw_rotated_sprite(surface, sprite, (artwork, shape, "turret", tuple(color), scale), part_center, heading, alpha=alpha)
            return
        for part, heading in (("chassis", angle), ("turret", angle if aim is None else aim)):
            if part == "turret" and artwork[1] is None:
                continue
            sprite = battle_sprite(artwork, shape, part, color, scale)
            key = (artwork, shape, part, tuple(color), scale)
            part_center = center
            if part == "turret" and artwork[1] == "Infantry Gun":
                # The shoulder follows the body while the weapon turns independently to aim.
                offset = layout.UNIT_SHAPE_SIZES[shape][1] * layout.INFANTRY_GUN_SIDE_OFFSET * scale
                part_center = (center[0] - math.sin(angle) * offset,
                               center[1] + math.cos(angle) * offset)
            if part == "turret" and recoil:
                part_center = (part_center[0] - math.cos(heading) * recoil * scale,
                               part_center[1] - math.sin(heading) * recoil * scale)
            draw_rotated_sprite(surface, sprite, key, part_center, heading, alpha=alpha)
        return
    key = (shape, tuple(color), scale, aim is None)
    draw_rotated_sprite(surface, unit_sprite(shape, color, scale, aim is None), key, center, angle, alpha=alpha)
    if aim is not None and shape not in layout.UNARMED_SHAPES:
        # Same reach as the sprite's own gun line at full scale: half the body plus the sprite's margin.
        length = (layout.UNIT_SHAPE_SIZES[shape][0] / 2 + 9 - recoil) * scale
        pygame.draw.line(surface, layout.OUTLINE_COLOR, center,
                         (center[0] + math.cos(aim) * length, center[1] + math.sin(aim) * length),
                         max(1, round(3 * scale)))


def draw_player_arrow(surface, center, angle, stretch=0.0, scale=1.0):
    """Mark the controlled unit and point along its hull heading.

    ``stretch`` is the signed share of top speed: the arrow lengthens with speed and points back while reversing.
    ``scale`` follows the battlefield zoom.
    """
    if stretch < 0:
        angle += math.pi
    extra = abs(stretch) * layout.ARROW_STRETCH
    forward = pygame.Vector2(math.cos(angle), math.sin(angle)) * scale
    sideways = pygame.Vector2(-forward.y, forward.x)
    origin = pygame.Vector2(center)
    if extra * scale >= 1:
        pygame.draw.line(surface, layout.OUTLINE_COLOR, origin + forward * 19, origin + forward * (19 + extra), 4)
        pygame.draw.line(surface, layout.PLAYER_COLOR, origin + forward * 19, origin + forward * (19 + extra), 2)
    head = origin + forward * extra
    points = [head + forward * 33, head + forward * 19 + sideways * 6,
              head + forward * 23, head + forward * 19 - sideways * 6]
    pygame.draw.polygon(surface, layout.OUTLINE_COLOR, points)
    pygame.draw.polygon(surface, layout.PLAYER_COLOR, points, 2)
