import pygame
import math
import data.constants as c
from data import queries
from map_logic.rendering import map_utils, symbol_loader
from map_logic.rendering.font_manager import fonts
from map_logic.turn_processing import combat_processor, combat_rules

#: How far outside the viewport a province centre may sit and still be drawn.
#: A province is culled by its centre, but what hangs off it is much bigger than
#: a point: a stack of unit boxes for six nations at full zoom is a few hundred
#: pixels tall, and cropping one at the screen edge would make it pop.
CULL_MARGIN = 250

# The images are deliberately separate from outcome color.  That leaves one
# consistent location category for future combat rules while the renderer can
# still say whether the local player's lanes look favourable.
COMBAT_BUBBLE_ASSETS = {
    queries.COMBAT_LOCATION_DEFENSE: "Defense Bubble",
    queries.COMBAT_LOCATION_OFFENSE: "Offense Bubble",
}
# Bubble art is intentionally compact so it does not hide the unit/order
# information around the tile.  The hit test below uses the image alpha mask,
# so there is no separate square padding to make the clickable area larger than
# the painted bubble.
COMBAT_BUBBLE_ICON_SCALE = 1.2
# Full battle display keeps the bubble readable while allowing the unit boxes
# underneath it to remain visible.
COMBAT_BUBBLE_FULL_ALPHA = 160
# Predicted bubbles are lighter still, so they are easy to distinguish from an
# active battle while retaining enough shape and color to be useful.
COMBAT_BUBBLE_FULL_PREDICTION_ALPHA = 96


def combat_strengths(sides, nation_data, friendly_nations, player_nation=None):
    """What a predicted fight is worth to the player: (friendly, enemy, involved).

    Read off combat_rules.build_battle, the same rule the turn resolver fights
    by, so the bubble's color cannot promise a result the turn will not
    produce. Lanes make this arithmetic honest for free: only the lanes a
    friendly nation actually stands in count, and only the front ranks in them,
    because that is exactly who will trade fire. The version this replaced had
    to weight each volley by the share of it aimed at a friendly unit, since
    damage went everywhere at once.

    `involved` is "a friendly nation holds a front slot", not "a friendly nation
    is standing here" -- an ally waiting out somebody else's battle on military
    access draws the grey bubble of a fight that is not yours.

    A lane's half is a whole side, so an ally fighting beside you counts towards
    the strength of the fight you are reading. That is the honest number: they
    are the ones the enemy has to shoot at instead of you.
    """
    friendly_atk = 0.0
    enemy_atk = 0.0
    involved = False

    battle = combat_rules.build_battle(sides, nation_data)
    for lane in battle.lanes:
        # A volunteer fights on its host's military side, but remains the
        # donor's division for control and presentation.  Treat that side as
        # the player's only in the battle where one of their divisions is
        # actually present; making the host globally friendly would color
        # unrelated host battles as though the donor took part in them.
        def is_friendly_side(side):
            return (any(nation in friendly_nations for nation in side.nations)
                    or (player_nation is not None
                        and any(unit.get("owner") == player_nation
                                for unit in side.front + side.reserve)))

        mine = [side for side in (lane.a, lane.b) if is_friendly_side(side)]
        # Two friends fighting each other is not a fight you are in either way.
        if len(mine) != 1:
            continue

        involved = True
        ours = mine[0]
        theirs = lane.b if ours is lane.a else lane.a
        friendly_atk += combat_rules.volley(ours.front, battle.shares, nation_data)
        enemy_atk += combat_rules.volley(theirs.front, battle.shares, nation_data)

    return friendly_atk, enemy_atk, involved


def combat_outlook_color(sides, nation_data, friendly_nations, player_nation=None):
    """Return the shared red/yellow/green/grey combat-outlook color."""
    friendly_atk, enemy_atk, involved = combat_strengths(
        sides, nation_data, friendly_nations, player_nation)
    if not involved:
        return (150, 150, 150)
    if friendly_atk > enemy_atk:
        return (0, 255, 0)
    if enemy_atk > friendly_atk:
        return (255, 0, 0)
    return (255, 255, 0)


def estimated_combat_outcome(sides, nation_data, province=None, max_turns=100):
    """Estimate the winning side and future volleys for a battle.

    This is deliberately a small, non-mutating simulation of the resolver:
    it rebuilds lanes after every simultaneous exchange, applies the same
    grouped damage function, and includes a province's fort defense when one
    is supplied.

    The returned ``winner_side`` is the index in ``sides`` and is ``None`` when
    the current rules produce a stalemate, both sides survive without a hostile
    lane, or the estimate would exceed the safety limit.  ``turns`` is the
    number of future volleys until that result is reached.
    """
    simulated_sides = [
        [dict(unit) for unit in side if unit.get("health", 0) > 0]
        for side in sides
    ]

    def defense_bonus(unit):
        if province is None:
            return 0
        return queries.get_fort_defense_bonus(
            province, unit, nation_data, combat_active=True)

    for turns in range(max_turns + 1):
        battle = combat_rules.build_battle(simulated_sides, nation_data)
        if not battle.lanes:
            live_side_indexes = [index for index, side in enumerate(simulated_sides)
                                 if side]
            winner_side = (live_side_indexes[0]
                           if len(live_side_indexes) == 1 else None)
            return {"winner_side": winner_side, "turns": turns}

        exchanges = list(combat_rules.exchange(battle, nation_data))
        if not exchanges:
            return {"winner_side": None, "turns": None}

        health_before = sum(
            max(0, float(unit.get("health", 0)))
            for side in simulated_sides for unit in side
        )
        for targets, total_attack in exchanges:
            combat_processor.apply_group_damage(
                total_attack, targets, defense_bonus)

        for index, side in enumerate(simulated_sides):
            simulated_sides[index] = [
                unit for unit in side if unit.get("health", 0) > 0
            ]

        health_after = sum(
            max(0, float(unit.get("health", 0)))
            for side in simulated_sides for unit in side
        )
        if health_after >= health_before:
            return {"winner_side": None, "turns": None}

    return {"winner_side": None, "turns": None}


def estimated_combat_turns(sides, nation_data, province=None, max_turns=100):
    """Estimate future volleys until a battle has no hostile lane remaining.

    This is the backwards-compatible turns-only view used by map combat
    bubbles.  The battle screen uses :func:`estimated_combat_outcome` so it can
    also identify which side is expected to survive.
    """
    return estimated_combat_outcome(
        sides, nation_data, province=province, max_turns=max_turns)["turns"]


def _combat_friendly_nations(map_screen):
    player = map_screen.player_country
    if player in (None, "", "Spectator", "Editor") or getattr(map_screen, "is_editor", False):
        return set()
    return queries.get_all_friendly_nations(player, map_screen.nation_data)


def _combat_is_visible(map_screen, province_ids, *, own_unit=False):
    """One fog gate shared by predicted and persistent combat bubbles."""
    visible = getattr(map_screen, "visible_provinces", None)
    if visible is None:
        return True
    partial = getattr(map_screen, "partial_visible_provinces", set()) or set()
    return own_unit or any(province_id in visible or province_id in partial
                           for province_id in province_ids)


def combat_bubble_records(map_screen):
    """Describe every visible combat bubble and its Orders-screen destination.

    The records are intentionally data-only: rendering, unit hiding and input
    hit-testing all consume this same list so a combat category or click target
    cannot drift away from the image actually painted on the map.
    """
    player = map_screen.player_country
    friendly = _combat_friendly_nations(map_screen)
    records = []

    for prediction in queries.get_combat_predictions(map_screen):
        if prediction["type"] == "meeting":
            continue

        province = map_screen.id_to_province[prediction["loc"]]
        if not _combat_is_visible(map_screen, [province["id"]]):
            continue
        sides = [[unit for units in prediction["forces"].values() for unit in units]]
        current_unit_ids = {id(unit) for unit in province.get("units", [])}
        battle_unit_ids = {id(unit) for side in sides for unit in side}
        actual_battle = queries.is_province_in_active_combat(
            province, map_screen.nation_data)
        records.append({
            "kind": "province",
            "province_id": province["id"],
            "center": province["center"],
            "category": queries.get_combat_location_category(
                province, player, map_screen.nation_data),
            "color": combat_outlook_color(
                sides, map_screen.nation_data, friendly, player),
            "potential": not actual_battle,
            "estimated_turns": estimated_combat_turns(
                sides, map_screen.nation_data, province=province),
            "unit_ids": battle_unit_ids,
            # Incoming attackers belong to the predicted fight, but are still
            # physically on their origin tiles. In compact mode, only units
            # currently on the battle tile are hidden under its bubble.
            "hidden_unit_ids": (
                battle_unit_ids & current_unit_ids
                if actual_battle and c.BATTLE_DISPLAY_MODE == "COMPACT"
                else set()),
            "orders_province_id": province["id"],
        })

    return records


def _combat_bubble_symbol(record, zoom):
    asset = COMBAT_BUBBLE_ASSETS[record["category"]]
    alpha = _combat_bubble_alpha(record)
    return symbol_loader.get_symbol(asset, zoom * COMBAT_BUBBLE_ICON_SCALE,
                                    color=record["color"], alpha=alpha)


def _combat_bubble_alpha(record):
    """Return the opacity for an active or predicted combat bubble."""
    if c.BATTLE_DISPLAY_MODE == "COMPACT":
        return 128 if record.get("potential") else 255
    if record.get("potential"):
        return COMBAT_BUBBLE_FULL_PREDICTION_ALPHA
    return COMBAT_BUBBLE_FULL_ALPHA


def _draw_combat_bubble_turns(surface, rect, bubble, record, zoom):
    """Draw the estimated remaining turns at the bubble's visual center."""
    turns = record.get("estimated_turns")
    label = "?" if turns is None else str(max(0, int(turns)))
    text = fonts.get("tiny").render(label, True, (255, 255, 255))

    # Render the label at the camera scale first. The subsequent fit is only a
    # guard against multi-digit values spilling over the bubble, so zooming the
    # map keeps the number proportional to the art behind it.
    zoom = max(0.01, float(zoom))
    text = pygame.transform.smoothscale(
        text, (max(1, int(text.get_width() * zoom)),
               max(1, int(text.get_height() * zoom))))

    # Bubble art is intentionally small. Scale the label to the central area so
    # two-digit estimates remain legible without spilling over the outline.
    max_width = max(1, int(bubble.get_width() * 0.68))
    max_height = max(1, int(bubble.get_height() * 0.68))
    scale = min(1.0, max_width / text.get_width(),
                max_height / text.get_height())
    if scale < 1.0:
        text = pygame.transform.smoothscale(
            text, (max(1, int(text.get_width() * scale)),
                   max(1, int(text.get_height() * scale))))

    alpha = _combat_bubble_alpha(record)
    text.set_alpha(alpha)
    shadow = text.copy()
    shadow.fill((0, 0, 0, alpha), special_flags=pygame.BLEND_RGBA_MULT)

    text_pos = text.get_rect(center=rect.center)
    shadow_pos = text_pos.move(1, 1)
    surface.blit(shadow, shadow_pos)
    surface.blit(text, text_pos)


def _combat_bubble_key(record):
    """Return the stable identity used to carry hover state between frames."""
    if record["kind"] == "province":
        return record["kind"], record["province_id"]
    return record["kind"], tuple(record["pair"])


def _combat_bubble_is_hovered(map_screen, record):
    hovered = getattr(map_screen, "hovered_combat_bubble", None)
    return hovered is not None and _combat_bubble_key(hovered) == _combat_bubble_key(record)


def _highlight_combat_bubble(bubble):
    """Add a bright, shape-matched hover treatment to a bubble surface."""
    highlighted = bubble.copy()
    mask = pygame.mask.from_surface(bubble)
    overlay = mask.to_surface(setcolor=(255, 255, 255, 80),
                              unsetcolor=(0, 0, 0, 0))
    highlighted.blit(overlay, (0, 0))

    # The outline follows the alpha mask rather than the image rectangle, which
    # keeps the hover feedback consistent with the click target at the corners.
    outline = mask.outline()
    if len(outline) > 1:
        pygame.draw.lines(highlighted, (255, 255, 255, 255), True, outline, 1)
    return highlighted


def _combat_bubble_hit_mask(bubble):
    """Return a shaped hit mask, including the inside of hollow bubble art."""
    mask = pygame.mask.from_surface(bubble)
    center = (bubble.get_width() // 2, bubble.get_height() // 2)
    if mask.get_at(center):
        return mask

    # Potential Bubble is an outlined circle. Its transparent centre is still
    # part of the circular button, while its transparent corners are not.
    fill_surface = pygame.Surface(bubble.get_size(), pygame.SRCALPHA)
    bounds = mask.get_bounding_rects()[0]
    pygame.draw.ellipse(fill_surface, (255, 255, 255, 255), bounds)
    return pygame.mask.from_surface(fill_surface)


def _combat_bubble_instances(map_screen, record):
    """Yield each wrapped, screen-space instance of one rendered bubble."""
    bubble = _combat_bubble_symbol(record, map_screen.camera.zoom)
    if bubble is None:
        return
    bubble = map_utils.apply_tilt(bubble, map_screen.camera.tilt_factor,
                                  c.APPLY_TILT_TO_OVERLAYS)
    offsets = [0, -map_screen.map_w, map_screen.map_w] if map_screen.loop_map else [0]
    for offset in offsets:
        sx, sy = queries.world_to_screen(record["center"], map_screen, offset)
        yield bubble, bubble.get_rect(center=(int(sx), int(sy)))


def _draw_combat_bubble(surface, map_screen, record):
    """Draw one image-backed bubble at all wrapped map positions."""
    for bubble, rect in _combat_bubble_instances(map_screen, record):
        if (-CULL_MARGIN < rect.centerx < surface.get_width() + CULL_MARGIN
                and -CULL_MARGIN < rect.centery < surface.get_height() + CULL_MARGIN):
            if _combat_bubble_is_hovered(map_screen, record):
                bubble = _highlight_combat_bubble(bubble)
            surface.blit(bubble, rect)
            _draw_combat_bubble_turns(
                surface, rect, bubble, record, map_screen.camera.zoom)


def draw_combat_bubbles(map_screen, surface, records=None):
    """Draw asset-backed combat bubbles and return their shared records."""
    if map_screen.secondary_mode != "UNITS":
        return []
    records = combat_bubble_records(map_screen) if records is None else records
    for record in records:
        _draw_combat_bubble(surface, map_screen, record)
    return records


def combat_bubble_at_screen_pos(map_screen, screen_pos):
    """Return the rendered combat bubble hit by a map click or hover.

    The hitbox is the bubble surface's non-transparent pixels, after the same
    zoom and tilt transforms used for drawing.  In particular, transparent
    corners of the source PNG are not clickable.
    """
    if (map_screen.viewing_ai_moves
            or map_screen.secondary_mode != "UNITS"):
        return None
    click_x, click_y = screen_pos
    for record in reversed(combat_bubble_records(map_screen)):
        for bubble, rect in _combat_bubble_instances(map_screen, record):
            if not rect.collidepoint(click_x, click_y):
                continue
            local_x = click_x - rect.x
            local_y = click_y - rect.y
            if _combat_bubble_hit_mask(bubble).get_at((local_x, local_y)):
                return record
    return None


def status_icon(map_screen, name):
    """A faded, tilted overlay badge -- training, disbanding, converting, building.

    Four call sites wrote this out identically, each ending in set_alpha on what
    get_symbol handed back. That surface is now shared between every caller
    asking for the same picture at the same size, so the fade has to be part of
    the request rather than something done to the result: "Hammer" at 1.5x is
    both this badge and the main menu's mods button, and whichever drew last
    would have decided how solid the other one looked.
    """
    icon = symbol_loader.get_symbol(name, map_screen.camera.zoom * c.OVERLAY_STATUS_ICON_SCALE,
                                    alpha=c.OVERLAY_STATUS_ICON_ALPHA)
    if not icon:
        return None
    return map_utils.apply_tilt(icon, map_screen.camera.tilt_factor, c.APPLY_TILT_TO_STATUS_ICONS)


def draw_map_highlight(surface, map_screen, pid, color, base_radius=10, inset=0, is_justifying=False):
    """Draws a highlighted ellipse over a province for diplomatic or contextual screens."""
    prov = map_screen.id_to_province.get(pid)
    if not prov: return
    for offset in [0, -map_screen.map_w, map_screen.map_w]:
        sx, sy = queries.world_to_screen(prov["center"], map_screen, offset)
        if -100 < sx < c.SCREEN_WIDTH + 100:
            radius_x = max(2, int(base_radius * map_screen.camera.zoom))
            
            if is_justifying:
                radius_x = max(1, int(radius_x * 0.6))
            if inset > 0:
                radius_x = max(1, radius_x - (inset * max(1, int(1.5 * map_screen.camera.zoom))))
                
            radius_y = int(radius_x * map_screen.camera.tilt_factor) if c.APPLY_TILT_TO_OVERLAYS else radius_x
            
            ellipse_surf = pygame.Surface((radius_x*2, radius_y*2), pygame.SRCALPHA)
            pygame.draw.ellipse(ellipse_surf, (*color, 150), ellipse_surf.get_rect())
            surface.blit(ellipse_surf, (int(sx) - radius_x, int(sy) - radius_y))
            pygame.draw.ellipse(surface, color, pygame.Rect(int(sx) - radius_x, int(sy) - radius_y, radius_x*2, radius_y*2), max(2, int(2*map_screen.camera.zoom)))

def draw_bombardment_arrow(surface, map_screen, start_province, target_id,
                           bomb_range=1, alpha=255, force_visible=False):
    """Draws a barrage sprite pointing from a gun's tile at the tile it is shelling.

    Movement uses a Line/Circle/Triangle chain because a path has many hops;
    a barrage is a single throw, so one rotated sprite sat between the two tiles
    reads the direction on its own. The sprite depends on the gun's reach, so a
    long-range shot is distinguishable from a short one at a glance.
    """
    target_prov = map_screen.id_to_province.get(target_id)
    if not target_prov: return

    # --- FOG OF WAR VISIBILITY CHECK ---
    if not force_visible and map_screen.visible_provinces is not None:
        partial = getattr(map_screen, 'partial_visible_provinces', set()) or set()
        allowed = map_screen.visible_provinces.union(partial)
        if start_province["id"] not in allowed and target_id not in allowed:
            return

    cam = map_screen.camera
    icon_name = queries.get_bombardment_arrow_icon(bomb_range)
    arrow_img = symbol_loader.get_symbol(icon_name, cam.zoom * c.BOMBARDMENT_ARROW_SCALE)

    p1 = list(start_province["center"])
    p2 = list(target_prov["center"])

    # Account for map wrap to get the shortest continuous distance
    p2[0] = queries.get_wrapped_x(p1[0], p2[0], map_screen.map_w, map_screen.loop_map)

    offsets = [0, -map_screen.map_w, map_screen.map_w] if map_screen.loop_map else [0]

    for offset in offsets:
        start_pos = queries.world_to_screen(p1, map_screen, offset)
        end_pos = queries.world_to_screen(p2, map_screen, offset)

        mid = ((start_pos[0] + end_pos[0]) / 2, (start_pos[1] + end_pos[1]) / 2)

        # Culling
        if mid[0] < -50 or mid[0] > surface.get_width() + 50:
            continue

        dx = end_pos[0] - start_pos[0]
        dy = end_pos[1] - start_pos[1]
        angle = math.degrees(math.atan2(-dy, dx))

        if arrow_img:
            rotated = pygame.transform.rotate(arrow_img, angle)
            if alpha < 255:
                rotated = rotated.copy()
                rotated.set_alpha(alpha)
            rotated = map_utils.apply_tilt(rotated, cam.tilt_factor, c.APPLY_TILT_TO_ARROWS)
            surface.blit(rotated, rotated.get_rect(center=mid))
        else:
            # Fallback until the barrage sprite is present in assets/images
            pygame.draw.line(surface, (255, 200, 0), start_pos, end_pos,
                             max(2, int(3 * cam.zoom)))


def midpoint_bounce_pairs(map_screen):
    """Return hostile head-on movement pairs whose orders are knowable here.

    During the AI-move viewing phase all orders are deliberately rendered, so
    the marker must use the full board just like the movement arrows do. During
    ordinary play, only the local player's orders are known; limiting the
    resolver query prevents an enemy order from leaking through this preview.
    Spectators and the editor can inspect the whole board at any time.
    """
    player = getattr(map_screen, "player_country", None)
    full_board = (getattr(map_screen, "viewing_ai_moves", False)
                  or player in ("Spectator", "Editor")
                  or getattr(map_screen, "is_editor", False))
    visible_to = None if full_board else {player}
    return combat_rules.find_meeting_pairs(
        map_screen.map_data, map_screen.nation_data, visible_to)


def midpoint_bounce_outcomes(map_screen):
    """Describe each predicted swap and whether it becomes an immediate overrun.

    A meeting engagement exchanges one volley before movement continues. If a
    side is completely destroyed by that first exchange, the stronger side
    does not actually bounce; it keeps moving into the other province. Slower
    fights still use the ordinary bounce marker because both sides survive the
    first exchange and are stopped there for the turn.
    """
    player = getattr(map_screen, "player_country", None)
    full_board = (getattr(map_screen, "viewing_ai_moves", False)
                  or player in ("Spectator", "Editor")
                  or getattr(map_screen, "is_editor", False))
    visible_to = None if full_board else {player}

    outcomes = []
    for pair in combat_rules.find_meeting_pairs(
            map_screen.map_data, map_screen.nation_data, visible_to):
        prov_a, prov_b, side_a, side_b = combat_rules.meeting_sides(
            map_screen.id_to_province, pair, visible_to)
        estimate = estimated_combat_outcome(
            [side_a, side_b], map_screen.nation_data)
        winner_side = estimate.get("winner_side")
        is_overrun = (winner_side in (0, 1)
                      and estimate.get("turns") == 1)

        if is_overrun and winner_side == 1:
            origin_id, target_id = prov_b["id"], prov_a["id"]
        else:
            origin_id, target_id = prov_a["id"], prov_b["id"]

        outcomes.append({
            "pair": pair,
            "origin_id": origin_id,
            "target_id": target_id,
            "overrun": is_overrun,
        })
    return outcomes


def draw_midpoint_bounces(map_screen, surface):
    """Draw a rotated bounce or overrun marker halfway between hostile swaps.

    The marker is placed from the same shortest wrapped edge used by movement
    paths, then rotated in the direction the relevant side is moving. This
    keeps the art aligned with the actual edge even when the map loops
    horizontally.
    """
    if not getattr(map_screen, "viewing_ai_moves", False) and not (
            getattr(map_screen, "player_country", None) in ("Spectator", "Editor")
            or getattr(map_screen, "is_editor", False)):
        return

    outcomes = midpoint_bounce_outcomes(map_screen)
    if not outcomes:
        return

    cam = map_screen.camera

    allowed = None
    visible_provinces = getattr(map_screen, "visible_provinces", None)
    if visible_provinces is not None:
        partial = getattr(map_screen, "partial_visible_provinces", set()) or set()
        allowed = visible_provinces.union(partial)

    offsets = [0, -map_screen.map_w, map_screen.map_w] if map_screen.loop_map else [0]
    for outcome in outcomes:
        start_province = map_screen.id_to_province.get(outcome["origin_id"])
        end_province = map_screen.id_to_province.get(outcome["target_id"])
        if not start_province or not end_province:
            continue

        icon_name = (c.ICON_MIDPOINT_OVERRUN
                     if outcome["overrun"] else c.ICON_MIDPOINT_BOUNCE)
        bounce_img = symbol_loader.get_symbol(
            icon_name, cam.zoom * c.MIDPOINT_BOUNCE_SCALE)
        if bounce_img is None:
            continue

        # Match movement-path fog behavior: a visible endpoint is enough to
        # show the edge, while two hidden endpoints reveal nothing.
        if allowed is not None and not (
                start_province["id"] in allowed or end_province["id"] in allowed):
            continue

        p1 = list(start_province["center"])
        p2 = list(end_province["center"])
        p2[0] = queries.get_wrapped_x(
            p1[0], p2[0], map_screen.map_w, map_screen.loop_map)

        for offset in offsets:
            start_pos = queries.world_to_screen(p1, map_screen, offset)
            end_pos = queries.world_to_screen(p2, map_screen, offset)
            mid = ((start_pos[0] + end_pos[0]) / 2,
                   (start_pos[1] + end_pos[1]) / 2)

            if (mid[0] < -CULL_MARGIN or mid[0] > surface.get_width() + CULL_MARGIN
                    or mid[1] < -CULL_MARGIN or mid[1] > surface.get_height() + CULL_MARGIN):
                continue

            dx = end_pos[0] - start_pos[0]
            dy = end_pos[1] - start_pos[1]
            if dx == 0 and dy == 0:
                continue
            angle = math.degrees(math.atan2(-dy, dx))
            rotated = pygame.transform.rotate(bounce_img, angle)
            rotated = map_utils.apply_tilt(
                rotated, cam.tilt_factor, c.APPLY_TILT_TO_ARROWS)
            surface.blit(rotated, rotated.get_rect(center=mid))


def draw_movement_path(surface, map_screen, start_province, path_ids, color=(255, 255, 0), alpha=255, force_visible=False):
    """Draws a multi-segment path with lines underneath circles and a triangle at the end."""
    if not path_ids: return

    cam = map_screen.camera

    # Build an ordered list of all nodes in the path
    nodes = [start_province]
    for step_id in path_ids:
        target_node = map_screen.id_to_province.get(step_id)
        if target_node:
            nodes.append(target_node)

    if len(nodes) < 2: return
    
    # --- FOG OF WAR VISIBILITY CHECK ---
    def is_segment_visible(n1, n2):
        if force_visible or map_screen.visible_provinces is None:
            return True
        partial = getattr(map_screen, 'partial_visible_provinces', set()) or set()
        allowed = map_screen.visible_provinces.union(partial)
        # If EITHER the start or end of this specific segment is visible, draw the segment!
        return n1["id"] in allowed or n2["id"] in allowed

    # Grab the UI symbols (Base scale is tweaked for zoom)
    line_base = symbol_loader.get_symbol("Line", cam.zoom * 1, color)
    circle_img = symbol_loader.get_symbol("Circle", cam.zoom * 1, color)
    triangle_img = symbol_loader.get_symbol("Triangle", cam.zoom * 1, color)

    offsets = [0, -map_screen.map_w, map_screen.map_w] if map_screen.loop_map else [0]

    # PASS 1: Draw all lines FIRST so they render underneath the shapes
    for i in range(len(nodes) - 1):
        n1 = nodes[i]
        n2 = nodes[i+1]
        
        # --- Apply the fog mask ---
        if not is_segment_visible(n1, n2):
            continue
            
        p1 = list(n1["center"])
        p2 = list(n2["center"])

        # Account for map wrap to get the shortest continuous distance
        p2[0] = queries.get_wrapped_x(p1[0], p2[0], map_screen.map_w, map_screen.loop_map)

        for offset in offsets:
            # 1. Get the actual tilted screen coordinates for final placement
            start_pos = queries.world_to_screen(p1, map_screen, offset)
            end_pos = queries.world_to_screen(p2, map_screen, offset)

            # Basic culling to avoid drawing off-screen lines
            min_x = min(start_pos[0], end_pos[0])
            max_x = max(start_pos[0], end_pos[0])
            if max_x < 0 or min_x > surface.get_width():
                continue

            # 2. Calculate un-tilted logic for the raw rotation and length
            usx1 = (p1[0] + offset - cam.pos.x) * cam.zoom
            usy1 = (p1[1] - cam.pos.y) * cam.zoom
            usx2 = (p2[0] + offset - cam.pos.x) * cam.zoom
            usy2 = (p2[1] - cam.pos.y) * cam.zoom

            udx = usx2 - usx1
            udy = usy2 - usy1
            udist = math.hypot(udx, udy)
            uangle = math.degrees(math.atan2(-udy, udx))

            if line_base and int(udist) > 0:
                thickness = max(2, int(4 * cam.zoom))
                
                # Scale base image to the UN-TILTED distance
                scaled_line = pygame.transform.scale(line_base, (int(udist), thickness))
                
                # Rotate by the UN-TILTED angle
                rotated_line = pygame.transform.rotate(scaled_line, uangle)
                
                if alpha < 255:
                    rotated_line.set_alpha(alpha)
                    
                # --- THE FIX: Apply the tilt compression to the final rotated block ---
                rotated_line = map_utils.apply_tilt(rotated_line, cam.tilt_factor, c.APPLY_TILT_TO_ARROWS)
                
                # Place it at the TILTED midpoint
                rect = rotated_line.get_rect(center=((start_pos[0] + end_pos[0])/2, (start_pos[1] + end_pos[1])/2))
                surface.blit(rotated_line, rect)
            else:
                pygame.draw.line(surface, color, start_pos, end_pos, max(1, int(3 * cam.zoom)))

    # PASS 2: Draw the node markers on top of the lines
    for i in range(1, len(nodes)):
        n1 = nodes[i-1]
        n2 = nodes[i]
        
        # --- Apply the fog mask ---
        if not is_segment_visible(n1, n2):
            continue

        p1 = list(n1["center"])
        p2 = list(n2["center"])

        is_last = (i == len(nodes) - 1)

        # Apply the exact same map wrap logic to the endpoints
        p2[0] = queries.get_wrapped_x(p1[0], p2[0], map_screen.map_w, map_screen.loop_map)

        for offset in offsets:
            start_pos = queries.world_to_screen(p1, map_screen, offset)
            end_pos = queries.world_to_screen(p2, map_screen, offset)

            # Culling Check
            if end_pos[0] < -50 or end_pos[0] > surface.get_width() + 50:
                continue

            dx = end_pos[0] - start_pos[0]
            dy = end_pos[1] - start_pos[1]
            angle = math.degrees(math.atan2(-dy, dx))

            if is_last:
                if triangle_img:
                    rotated_tri = pygame.transform.rotate(triangle_img, angle)
                    if alpha < 255: rotated_tri.set_alpha(alpha)
                    rotated_tri = map_utils.apply_tilt(rotated_tri, cam.tilt_factor, c.APPLY_TILT_TO_ARROWS)
                    rect = rotated_tri.get_rect(center=end_pos)
                    surface.blit(rotated_tri, rect)
                else:
                    head_size = 15 * cam.zoom
                    angle_rad = math.atan2(dy, dx)
                    left_wing = (end_pos[0] - head_size * math.cos(angle_rad - math.pi / 6),
                                 end_pos[1] - head_size * math.sin(angle_rad - math.pi / 6))
                    right_wing = (end_pos[0] - head_size * math.cos(angle_rad + math.pi / 6),
                                   end_pos[1] - head_size * math.sin(angle_rad + math.pi / 6))
                    pygame.draw.polygon(surface, color, [end_pos, left_wing, right_wing])
            else:
                if circle_img:
                    draw_circle = circle_img.copy() if alpha < 255 else circle_img
                    if alpha < 255: draw_circle.set_alpha(alpha)
                    draw_circle = map_utils.apply_tilt(draw_circle, cam.tilt_factor, c.APPLY_TILT_TO_ARROWS)
                    rect = draw_circle.get_rect(center=end_pos)
                    surface.blit(draw_circle, rect)
                else:
                    radius_x = max(3, int(4 * cam.zoom))
                    radius_y = int(radius_x * cam.tilt_factor) if c.APPLY_TILT_TO_ARROWS else radius_x
                    pygame.draw.ellipse(surface, color, pygame.Rect(int(end_pos[0]) - radius_x, int(end_pos[1]) - radius_y, radius_x*2, radius_y*2))

def draw_overlay_content(map_screen, surface, draw_combat=True):
    """Orchestrates what icons/symbols to draw over the map."""
    if map_screen.secondary_mode == "BLANK":
        return []

    # --- Render Combat Prediction Bubbles ---
    combat_records = []
    combat_unit_ids = set()
    if map_screen.secondary_mode == "UNITS":
        combat_records = combat_bubble_records(map_screen)
        combat_unit_ids = {unit_id for record in combat_records
                           for unit_id in record.get("hidden_unit_ids", set())}
    # ---------------------------------------------

    for color_key, province in map_screen.map_data.items():
        
        # --- FOG OF WAR VISIBILITY CHECK ---
        is_vis = True
        is_partial = False
        if map_screen.visible_provinces is not None:
            if province["id"] in map_screen.visible_provinces:
                is_vis = True
            elif getattr(map_screen, 'partial_visible_provinces', None) is not None and province["id"] in map_screen.partial_visible_provinces:
                is_vis = False
                is_partial = True
            else:
                fog_strength = getattr(map_screen, 'scenario_settings', {}).get("fog_of_war_strength", "normal")
                if fog_strength == "lite":
                    is_vis = False
                    is_partial = True
                else:
                    continue # Completely hidden
            
        cx, cy = province["center"]
        
        # Wrapping logic for screen coordinates
        offsets = [0, -map_screen.map_w, map_screen.map_w] if map_screen.loop_map else [0]
        
        for offset in offsets:
            sx, sy = queries.world_to_screen((cx, cy), map_screen, offset)
            sx, sy = int(sx), int(sy)

            # Culling. The height half of this was missing, so a zoomed-in map
            # composed and blitted the icons for every tile above and below the
            # viewport -- most of the map, at the zoom people actually fight at.
            # The margin is generous because these are centre points and a tall
            # stack of unit boxes or a big building sprite hangs well outside it.
            if (-CULL_MARGIN < sx < surface.get_width() + CULL_MARGIN
                    and -CULL_MARGIN < sy < surface.get_height() + CULL_MARGIN):

                # --- UNIT VIEW ---
                if map_screen.secondary_mode == "UNITS":
                    # .get, like every other read of this key below it. A
                    # province dict is not guaranteed to carry one -- the editor
                    # and the map tools both build provinces without it.
                    #
                    # Filtered once per province: a hidden submarine must not
                    # trip any per-unit indicator (disband, conversion, the "?"
                    # blip) even in an otherwise fully-visible province -- full
                    # province visibility and per-submarine visibility are
                    # separate layers.
                    visible_units = [unit for unit in queries.filter_visible_units(
                        province.get("units", []), map_screen.player_country,
                        province, map_screen.nation_data)
                        if id(unit) not in combat_unit_ids]

                    if visible_units:
                        draw_unit_icon(map_screen, surface, sx, sy, province, is_partial)

                    if not is_partial and queries.is_training_troops(province):
                        training_sym = status_icon(map_screen, c.ICON_TRAINING)
                        if training_sym:
                            rect = training_sym.get_rect(center=(sx, sy))
                            surface.blit(training_sym, rect)

                    # --- Disband Indicator ---
                    if not is_partial and any(u.get("order", {}).get("type") == "DISBAND" for u in visible_units):
                        disband_sym = status_icon(map_screen, c.ICON_DISBANDING)
                        if disband_sym:
                            rect = disband_sym.get_rect(center=(sx, sy))
                            surface.blit(disband_sym, rect)

                    # --- Repair Indicator ---
                    if not is_partial and any(u.get("order", {}).get("type") == "REPAIR" for u in visible_units):
                        repair_sym = status_icon(map_screen, c.ICON_REPAIRING)
                        if repair_sym:
                            rect = repair_sym.get_rect(center=(sx, sy))
                            surface.blit(repair_sym, rect)

                    # --- Upgrade Indicator ---
                    if not is_partial and any(u.get("order", {}).get("type") == "UPGRADE" for u in visible_units):
                        upgrade_sym = status_icon(map_screen, c.ICON_UPGRADING)
                        if upgrade_sym:
                            rect = upgrade_sym.get_rect(center=(sx, sy))
                            surface.blit(upgrade_sym, rect)

                    # --- Conversion Indicator (Convoy/Truck transformations) ---
                    if not is_partial:
                        convert_order = next((u.get("order", {}) for u in visible_units
                                               if u.get("order", {}).get("type") == "CONVERT"), None)
                        convert_icon = None
                        if convert_order:
                            base_icon = c.CONVERSION_ICONS.get(convert_order.get("to"))
                            if base_icon in (c.ICON_CONVERTING_TO_TRUCK, c.ICON_CONVERTING_TO_SHIP):
                                turns_left = max(1, min(c.TRUCK_CONVERT_TURNS, convert_order.get("turns_left", 1)))
                                convert_icon = f"{base_icon} {turns_left}"
                            else:
                                convert_icon = base_icon
                        if convert_icon:
                            convert_sym = status_icon(map_screen, convert_icon)
                            if convert_sym:
                                rect = convert_sym.get_rect(center=(sx, sy))
                                surface.blit(convert_sym, rect)

                # --- ECONOMY VIEW ---
                elif map_screen.secondary_mode == "ECONOMY":
                    if is_partial:
                        # Show an unknown building marker if any infrastructure exists
                        if province.get("buildings") or province.get("building_queue"):
                            sym = symbol_loader.get_symbol("Unknown Building", map_screen.camera.zoom * getattr(c, 'BUILDING_ICON_SCALE', 1.0))
                            if sym:
                                sym = map_utils.apply_tilt(sym, map_screen.camera.tilt_factor, getattr(c, 'APPLY_TILT_TO_OVERLAYS', True))
                                draw_x = sx - (sym.get_width() // 2)
                                draw_y = sy - (sym.get_height() // 2)
                                surface.blit(sym, (draw_x, draw_y))
                        continue # Hide specific economy details in partial vision
                    
                    # Draw Buildings
                    buildings = province.get("buildings", []).copy()
                    
                    # --- NEW: Inject transitional workshop building ---
                    b_queue = province.get("building_queue", [])
                    if b_queue and b_queue[0].get("item_name") == "Basic Factory":
                        rem = b_queue[0].get("turns_remaining", c.BASIC_FACTORY_TURNS)
                        lvl = 1 if rem >= 17 else 2 if rem >= 13 else 3 if rem >= 9 else 4 if rem >= 5 else 5
                        buildings.append(f"Workshop Lvl {lvl}")

                    # Forts form the bottom layer, with factories/workshops in
                    # the middle and recruitment centers on top.  The sprites
                    # share a visual baseline even though fort sprites grow in
                    # height with their level.
                    b_lib = queries.get_building_library()
                    layer_order = {"fortification": 0, "industry": 1, "recruitment": 2}
                    buildings = sorted(
                        buildings,
                        key=lambda b: layer_order.get(b_lib.get(b, {}).get("group"), 1),
                    )

                    # Match the baseline to the exact factory sprite that the
                    # existing centered-building path uses, including zoom and
                    # optional tilt rounding.
                    building_zoom = map_screen.camera.zoom * c.BUILDING_ICON_SCALE
                    reference_symbol = symbol_loader.get_symbol("Factory Lvl 1", building_zoom)
                    if reference_symbol:
                        reference_symbol = map_utils.apply_tilt(
                            reference_symbol, map_screen.camera.tilt_factor,
                            c.APPLY_TILT_TO_OVERLAYS)
                        building_bottom = sy + (reference_symbol.get_height() + 1) // 2
                    else:
                        building_bottom = sy
                    
                    for i, b_name in enumerate(buildings):

                        # Just in case we want to offset it for some reason
                        offset_x = 0
                        offset_y = 0
                        
                        sym_name = b_name
                        symbol = symbol_loader.get_symbol(sym_name, building_zoom)
                        
                        if symbol:
                            symbol = map_utils.apply_tilt(symbol, map_screen.camera.tilt_factor, c.APPLY_TILT_TO_OVERLAYS)
                            # All building sprites share the tile's horizontal
                            # centre. Fort sprites use their bottom edge as the
                            # same baseline as those 19px-high sprites, keeping
                            # the fort visually underneath them.
                            is_fort = b_lib.get(b_name, {}).get("group") == "fortification"
                            draw_x = sx + offset_x - (symbol.get_width() // 2)
                            if is_fort:
                                draw_y = building_bottom + offset_y - symbol.get_height()
                            else:
                                draw_y = sy + offset_y - (symbol.get_height() // 2)
                            surface.blit(symbol, (draw_x, draw_y))
                        else:
                            # Fallback colored squares for different types
                            color = (150, 150, 150) # Grey for workshop
                            if "Factory" in b_name: color = (100, 100, 200) # Blue-ish for factory
                            if "Refinery" in b_name: color = (200, 100, 100) # Red-ish for refinery
                            if "Fort" in b_name: color = (120, 120, 120) # Grey for fort
                            
                            w_scaled = int(12 * map_screen.camera.zoom)
                            h_scaled = int(12 * map_screen.camera.zoom * (map_screen.camera.tilt_factor if c.APPLY_TILT_TO_OVERLAYS else 1.0))
                            
                            # Center the rect using the same logic
                            is_fort = b_lib.get(b_name, {}).get("group") == "fortification"
                            fallback_y = (building_bottom + offset_y - h_scaled
                                          if is_fort
                                          else sy + offset_y - (h_scaled // 2))
                            rect = pygame.Rect(
                                sx + offset_x - (w_scaled // 2),
                                fallback_y,
                                w_scaled, 
                                h_scaled
                            )
                            pygame.draw.rect(surface, color, rect)
                            pygame.draw.rect(surface, (255, 255, 255), rect, 1) # Border
                    
                    # Draw Construction Hammer
                    if queries.is_constructing_building(province):
                        hammer_sym = status_icon(map_screen, c.ICON_CONSTRUCTION)
                        if hammer_sym:
                            rect = hammer_sym.get_rect(center=(sx, sy))
                            surface.blit(hammer_sym, rect)
                
                # --- RESOURCES VIEW ---
                elif map_screen.secondary_mode == "RESOURCES":
                    if is_partial: continue # Hide resources in partial vision
                    
                    resources = province.get("resources", {})
                    if isinstance(resources, dict) and resources:
                        resource_items = [(res_type, amount) for res_type, amount in resources.items() if amount > 0]
                        if resource_items:
                            icon_spacing = max(1, int(20 * map_screen.camera.zoom))
                            icons = []
                            for res_type, amount in resource_items:
                                sym = symbol_loader.get_symbol(res_type, map_screen.camera.zoom * 0.8)
                                if sym:
                                    sym = map_utils.apply_tilt(sym, map_screen.camera.tilt_factor, c.APPLY_TILT_TO_OVERLAYS)
                                    icons.append((sym, res_type))
                                else:
                                    c_col = (200, 200, 200)
                                    if res_type == "Iron": c_col = (180, 180, 180)
                                    if res_type == "Coal": c_col = (50, 50, 50)
                                    if res_type == "Oil": c_col = (30, 30, 30)
                                    if res_type == "Wheat": c_col = (220, 200, 60)
                                    w_scaled = int(15 * map_screen.camera.zoom)
                                    h_scaled = int(15 * map_screen.camera.zoom * (map_screen.camera.tilt_factor if c.APPLY_TILT_TO_OVERLAYS else 1.0))
                                    icons.append((None, res_type, c_col, w_scaled, h_scaled))

                            total_width = 0
                            for icon in icons:
                                if icon[0] is not None:
                                    total_width += icon[0].get_width()
                                else:
                                    total_width += icon[3]
                            total_width += icon_spacing * (len(icons) - 1)

                            current_x = sx - (total_width // 2)
                            for icon in icons:
                                if icon[0] is not None:
                                    sym = icon[0]
                                    rect = sym.get_rect(center=(current_x + sym.get_width() // 2, sy))
                                    surface.blit(sym, rect)
                                    current_x += sym.get_width() + icon_spacing
                                else:
                                    c_col, w_scaled, h_scaled = icon[2], icon[3], icon[4]
                                    rect = pygame.Rect(current_x, sy - (h_scaled // 2), w_scaled, h_scaled)
                                    pygame.draw.rect(surface, c_col, rect)
                                    pygame.draw.rect(surface, (255, 255, 255), rect, 1)
                                    current_x += w_scaled + icon_spacing

    # Map rendering passes draw_combat=False and paints these after movement
    # and bombardment arrows. Direct callers retain the old self-contained
    # behavior by leaving draw_combat at its default.
    if draw_combat and map_screen.secondary_mode == "UNITS":
        draw_combat_bubbles(map_screen, surface, combat_records)
    return combat_records

#: Composed unit boxes, keyed by everything that is drawn into one. Building a
#: box means a fresh surface, a colorized symbol, two font renders and a
#: supersampled downscale, and a zoomed-out map asks for a few hundred of them a
#: frame -- almost all repeats, since "German Reich, Infantry, 3" looks the same
#: on every tile it appears. Keyed on the drawn size rather than the zoom so a
#: box survives the zoom lerp settling.
UNIT_BOXES = {}

#: Same reasoning as symbol_loader.SCALED_CACHE_LIMIT: dropped wholesale, since
#: it refills from what is on screen within a frame.
UNIT_BOX_CACHE_LIMIT = 2000


def unit_box_size(map_screen):
    """The on-screen size of one unit box at the current zoom and tilt."""
    # Dampened Scaling rules
    display_scale = 0.25 + (map_screen.camera.zoom * 0.12)
    scaled_w = max(20, int(c.UNIT_BOX_WIDTH * display_scale))
    scaled_h = max(8, int(c.UNIT_BOX_HEIGHT * display_scale))
    if map_screen.camera.tilt_factor < 0.99 and getattr(c, 'APPLY_TILT_TO_OVERLAYS', True):
        scaled_h = max(8, int(scaled_h * map_screen.camera.tilt_factor))
    return scaled_w, scaled_h, display_scale


def _cache_box(key, build):
    box = UNIT_BOXES.get(key)
    if box is None:
        box = build()
        if len(UNIT_BOXES) >= UNIT_BOX_CACHE_LIMIT:
            UNIT_BOXES.clear()
        UNIT_BOXES[key] = box
    return box


#: The border + colorized symbol art for one (unit type, nation color,
#: inverted) combination, before the per-turn unit count is drawn on top.
#: Unlike UNIT_BOXES this key excludes `count` and `size` -- a stack's count
#: changes almost every turn on an active front, which used to invalidate the
#: whole box (colorize the symbol, draw the border, fit it to width) even
#: though none of that actually depends on how many units are in the stack.
#: This stays a near-permanent cache instead of being rebuilt every turn.
_BOX_TEMPLATES = {}
_BOX_TEMPLATE_CACHE_LIMIT = 500


def _get_box_template(symbol_name, border_color, inverted, owner=None):
    key = (symbol_name, tuple(border_color), inverted, c.UNIT_ART_STYLE, owner)
    cached = _BOX_TEMPLATES.get(key)
    if cached is not None:
        return cached

    internal_w = c.UNIT_BOX_WIDTH
    internal_h = c.UNIT_BOX_HEIGHT
    box_surf = pygame.Surface((internal_w, internal_h), pygame.SRCALPHA)

    if inverted:
        box_surf.fill((255, 255, 255))
        pygame.draw.rect(box_surf, (0, 0, 0), box_surf.get_rect(), 4)
        symbol = symbol_loader.get_symbol(symbol_name, 2.5, color=(0, 0, 0), country=owner)
    else:
        box_surf.fill(c.UNIT_BOX_BG_COLOR)
        pygame.draw.rect(box_surf, border_color, box_surf.get_rect(), 4)
        symbol = symbol_loader.get_symbol(symbol_name, 2.5, color=border_color, country=owner)

    text_x = 10
    if symbol:
        # Constrain the symbol itself if it's too wide
        max_sym_w = int(internal_w * 0.6) # Limit symbol to 60% of box width
        if symbol.get_width() > max_sym_w:
            ratio = max_sym_w / symbol.get_width()
            new_h = max(1, int(symbol.get_height() * ratio))
            symbol = pygame.transform.smoothscale(symbol, (max_sym_w, new_h))

        sym_rect = symbol.get_rect(midleft=(8, internal_h // 2))
        box_surf.blit(symbol, sym_rect)
        text_x = sym_rect.right + 8

    if len(_BOX_TEMPLATES) >= _BOX_TEMPLATE_CACHE_LIMIT:
        _BOX_TEMPLATES.clear()
    result = (box_surf, text_x)
    _BOX_TEMPLATES[key] = result
    return result


def unit_box(symbol_name, border_color, count, inverted, size, owner=None):
    """One nation's box: its color, the unit it leads with, and how many.

    Drawn at UNIT_BOX_WIDTH x UNIT_BOX_HEIGHT and supersampled down to `size`,
    which is what keeps it crisp at any zoom. `inverted` is the tactical-mode
    player's own division, drawn black on white so they can find themselves.
    `owner` is the stack's nation id, so a style with nation-specific art
    (see symbol_loader.py) draws the right one.
    """
    def build():
        internal_h = c.UNIT_BOX_HEIGHT
        internal_w = c.UNIT_BOX_WIDTH
        template, text_x = _get_box_template(symbol_name, border_color, inverted, owner)
        box_surf = template.copy()

        if inverted:
            text_color = (0, 0, 0)
            shadow_color = (255, 255, 255)
        else:
            text_color = c.UNIT_BOX_TEXT_COLOR
            shadow_color = (0, 0, 0)

        # Draw Unit Count Text
        font = fonts.get("button")
        count_str = str(count)
        count_txt = font.render(count_str, True, text_color)
        shadow_txt = font.render(count_str, True, shadow_color)

        # --- TEXT COMPRESSION FIX (UNIFORM SCALE) ---
        # Ensure we never pass a 0 or negative width to smoothscale
        max_text_w = max(1, internal_w - text_x - 6)

        # If the text is wider than the space we have, scale it down uniformly to fit
        if count_txt.get_width() > max_text_w:
            scale_ratio = max_text_w / count_txt.get_width()
            new_w = int(max_text_w)
            new_h = max(1, int(count_txt.get_height() * scale_ratio))
            count_txt = pygame.transform.smoothscale(count_txt, (new_w, new_h))
            shadow_txt = pygame.transform.smoothscale(shadow_txt, (new_w, new_h))

        txt_y = (internal_h // 2) - (count_txt.get_height() // 2)
        box_surf.blit(shadow_txt, (text_x + 2, txt_y + 2))
        box_surf.blit(count_txt, (text_x, txt_y))

        # Supersampling/Anti-aliasing final stretch down
        return pygame.transform.smoothscale(box_surf, size)

    return _cache_box((symbol_name, tuple(border_color), count, inverted, size, c.UNIT_ART_STYLE, owner), build)


def unknown_box(size):
    """The box a tile gets under partial vision: somebody is there, no more."""
    def build():
        internal_w = c.UNIT_BOX_WIDTH
        internal_h = c.UNIT_BOX_HEIGHT
        box_surf = pygame.Surface((internal_w, internal_h), pygame.SRCALPHA)
        box_surf.fill(getattr(c, 'UNIT_BOX_BG_COLOR', (40, 40, 40)))
        pygame.draw.rect(box_surf, (150, 150, 150), box_surf.get_rect(), 4)

        font = fonts.get("button")
        txt = font.render("?", True, getattr(c, 'UNIT_BOX_TEXT_COLOR', (255, 255, 255)))
        box_surf.blit(txt, txt.get_rect(center=(internal_w // 2, internal_h // 2)))

        return pygame.transform.smoothscale(box_surf, size)

    return _cache_box(("?", (), 0, False, size), build)


def draw_unit_icon(map_screen, surface, sx, sy, province, is_partial=False,
                   units=None, units_are_visible=False):
    # Filtered up front: a lone hidden submarine must not even trip the "?"
    # partial-fog blip, or its position leaks through despite being otherwise
    # invisible to anyone who isn't allied or already fighting it.
    if units is None:
        units = province.get("units", [])
    if not units_are_visible:
        units = queries.filter_visible_units(
            units, map_screen.player_country, province, map_screen.nation_data)
    if not units:
        return

    scaled_w, scaled_h, display_scale = unit_box_size(map_screen)

    if is_partial:
        final_surf = unknown_box((scaled_w, scaled_h))
        surface.blit(final_surf, final_surf.get_rect(center=(sx, int(sy))))
        return

    # Keep each donor's volunteers in their own stack. They remain visibly the
    # donor's divisions even though combat and capture use their host side.
    units_by_owner = {}
    for u in units:
        owner = u.get("owner", "Unclaimed")
        units_by_owner.setdefault(owner, []).append(u)

    gap = max(2, int(4 * display_scale)) # Spacing between stacked boxes

    # 2. Calculate the vertical offset to perfectly center the entire stack over the province
    total_boxes = len(units_by_owner)
    total_stack_height = (scaled_h * total_boxes) + (gap * (total_boxes - 1))
    
    # Start drawing from the top of the stack and move down
    current_sy = sy - (total_stack_height // 2) + (scaled_h // 2)

    # --- NEW: Sort owners by Total HP descending, but keep Player Tactical Unit on top ---
    is_tactical = map_screen.tactical_mode
    player_unit = map_screen.player_unit
    
    def get_owner_sort_weight(o):
        if is_tactical and any(u is player_unit for u in units_by_owner[o]):
            return (1, 0)
        return (0, sum(u.get("health", 0) for u in units_by_owner[o]))

    sorted_owners = sorted(
        units_by_owner.keys(), 
        key=lambda o: get_owner_sort_weight(o),
        reverse=True
    )

    for owner in sorted_owners:
        owner_units = units_by_owner[owner]
        
        if is_tactical and any(u is player_unit for u in owner_units):
            best_unit = player_unit
        else:
            best_unit = queries.get_best_unit_by_defense_then_attack_then_speed(owner_units)
        
        if not best_unit:
            continue

        unit_count = len(owner_units)
        unit_type = best_unit.get("type", "")
        owner_color = map_screen.nation_colors.get(owner, (200, 200, 200))
        
        # Check if it's a dynamic convoy or truck
        if unit_type.startswith("Convoy"):
            symbol_name = "Convoy"
        elif unit_type.startswith("Truck"):
            symbol_name = "Truck"
        else:
            symbol_name = unit_type

        # --- TACTICAL MODE INVERSION ---
        is_player_tactical = map_screen.tactical_mode and map_screen.player_unit is best_unit

        final_surf = unit_box(symbol_name, owner_color, unit_count,
                              is_player_tactical, (scaled_w, scaled_h), owner=owner)

        # Blit using the stacked Y coordinate
        rect = final_surf.get_rect(center=(sx, int(current_sy)))
        surface.blit(final_surf, rect)

        # Move the offset down for the next owner's box in the stack
        current_sy += scaled_h + gap


def draw_split_movement_path(surface, map_screen, start_prov, path, speed, base_color, force_visible=False):
    """Standardized helper to draw multi-segment movement paths with queued opacity."""
    if not path: return
    
    immediate_path = path[:speed]
    queued_path = path[speed:]
    
    if immediate_path:
        draw_movement_path(surface, map_screen, start_prov, immediate_path, color=base_color, force_visible=force_visible)
        
    if queued_path:
        bright_color = (min(255, base_color[0] + 150), min(255, base_color[1] + 150), min(255, base_color[2] + 150))
        q_start = map_screen.id_to_province.get(immediate_path[-1]) if immediate_path else start_prov
        draw_movement_path(surface, map_screen, q_start, queued_path, color=bright_color, alpha=120, force_visible=force_visible)
