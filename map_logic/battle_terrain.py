"""Temporary tactical terrain, shared shot geometry, and cached ground navigation.

Battlefields belong to an encounter, not to campaign saves. This module has no
pygame dependency; drawing reads the same features used by the simulation.
"""

import heapq
import math
import random
from collections import deque
from dataclasses import dataclass


TERRAIN_NAMES = {
    "plains": "Plains", "hills": "Hills", "desert": "Desert",
    "forest": "Forest", "jungle": "Jungle", "mountain": "Mountains", "swamp": "Swamp",
}
NAV_CELL = 40.0
FEATURE_CELL = 128.0
GROUND_SAMPLE = 12.0
BODY_HEIGHT = 36.0
WEAPON_HEIGHT = BODY_HEIGHT / 2
TREE_HEIGHT = 100.0
# Trunk sizes 1, 2, and 3. A trunk is the tree's hitbox: each radius is half the width of its
# Trunk image in assets/battles/terrain, and the battle screen scales that image to this radius.
TREE_TRUNK_RADII = {1: 8.5, 2: 13.0, 3: 18.0}
TREE_TRUNK_GAP = 20.0  # Least open ground between neighboring trunks' edges; a crowded tree is not planted.
# (smallest, largest) foliage radius for each trunk size, so larger trunks carry larger foliage.
TREE_FOLIAGE_RADII = {1: (24.0, 40.0), 2: (32.0, 55.0), 3: (40.0, 86.0)}
HILL_RADIUS = (140.0, 230.0)
HILL_HEIGHT = (65.0, 125.0)
HAZARD_RADIUS = (65.0, 120.0)
ROCK_HEIGHT = 200.0
DEPLOYMENT_CLEARANCE = 100.0
EDGE_CLEARANCE = 80.0
MAX_CACHED_ROUTES = 2048
# Hills, tree placement attempts, rocks, and impassable water/gaps.
TERRAIN_RECIPES = {
    "plains": (0, 0, 0, 0), "desert": (0, 0, 0, 0),
    "hills": (6, 0, 0, 0), "forest": (0, 252, 0, 0),
    "jungle": (0, 660, 0, 3), "mountain": (13, 0, 7, 4),
    "swamp": (0, 192, 0, 7),
}
# What the impassable water/gaps of each recipe are. Both stop movement and let shots across.
GAP_KINDS = {"mountain": "chasm", "jungle": "marsh", "swamp": "marsh"}
BLOCKS_MOVEMENT = frozenset(("tree", "rock", "chasm", "marsh"))


def circle_contact(start, end, center, radius):
    """First contact along a swept segment, including a segment starting inside."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    ox, oy = start[0] - center[0], start[1] - center[1]
    outside = ox * ox + oy * oy - radius * radius
    if outside <= 0:
        return 0.0
    length = dx * dx + dy * dy
    if not length:
        return None
    along = ox * dx + oy * dy
    discriminant = along * along - length * outside
    if discriminant < 0:
        return None
    fraction = (-along - math.sqrt(discriminant)) / length
    return fraction if 0 <= fraction <= 1 else None


@dataclass(eq=False)
class Feature:
    kind: str
    x: float
    y: float
    radius: float
    height: float = 0.0
    destroyed: bool = False
    # Trees only: the Trunk image size and the foliage circle's radius. Foliage is drawn and never blocks anything.
    trunk: int = 1
    foliage_radius: float = 0.0
    shade: float = 0.0  # Trees only, drawing only: -1 darkest to 1 lightest variation of the foliage's green.


class Battlefield:
    def __init__(self, terrain, size, body_radius, features=()):
        if terrain not in TERRAIN_NAMES:
            raise ValueError(f"Unsupported tactical terrain: {terrain!r}")
        self.terrain = terrain
        self.size = size
        self.body_radius = body_radius
        self.features = list(features)
        self.revision = 0
        self._buckets = {}
        self._navigation = None
        self._routes = {}
        self._sight = {}
        self._index_features()

    @classmethod
    def generate(cls, terrain, size, body_radius, front_gap, seed=None, *, deployment_half_height=None):
        # Terrain randomness does not consume AI temperament or shot-spread draws.
        rng = random.Random(seed)
        field = cls(terrain, size, body_radius)
        hills, trees, rocks, gaps = TERRAIN_RECIPES[terrain]
        left = (size[0] - front_gap) / 2 + DEPLOYMENT_CLEARANCE
        right = size[0] - left
        # Callers without formation geometry retain clear deployment columns.
        tree_left = left if deployment_half_height is None else EDGE_CLEARANCE
        tree_right = size[0] - tree_left

        def place(kind, radius, height=0.0, center=None, **tree):
            min_x, max_x = (tree_left, tree_right) if kind == "tree" else (left, right)
            x, y = center or (rng.uniform(min_x + radius, max_x - radius),
                              rng.uniform(EDGE_CLEARANCE + radius, size[1] - EDGE_CLEARANCE - radius))
            if not (min_x + radius <= x <= max_x - radius
                    and EDGE_CLEARANCE + radius <= y <= size[1] - EDGE_CLEARANCE - radius):
                return
            # Trees may grow beside the armies, leaving their centered ranks clear.
            if (kind == "tree" and deployment_half_height is not None
                    and abs(y - size[1] / 2) < deployment_half_height + body_radius + DEPLOYMENT_CLEARANCE + radius
                    and (x - radius < left or x + radius > right)):
                return
            field.features.append(Feature(kind, x, y, radius, height, **tree))

        for _ in range(hills):
            place("hill", rng.uniform(*HILL_RADIUS), rng.uniform(*HILL_HEIGHT))
        for _ in range(rocks):
            place("rock", rng.uniform(*HAZARD_RADIUS), ROCK_HEIGHT)
        for _ in range(gaps):
            place(GAP_KINDS[terrain], rng.uniform(*HAZARD_RADIUS))
        for _ in range(trees):
            trunk = rng.randint(1, len(TREE_TRUNK_RADII))
            foliage = rng.uniform(*TREE_FOLIAGE_RADII[trunk])
            radius = TREE_TRUNK_RADII[trunk]
            point = (rng.uniform(tree_left + radius, tree_right - radius),
                     rng.uniform(EDGE_CLEARANCE + radius, size[1] - EDGE_CLEARANCE - radius))
            # Do not plant trees in a rock, marsh, or chasm, or within TREE_TRUNK_GAP of another trunk.
            if any(feature.kind in BLOCKS_MOVEMENT
                   and math.dist(point, (feature.x, feature.y))
                   < feature.radius + radius + (TREE_TRUNK_GAP if feature.kind == "tree" else 0.0)
                   for feature in field.features):
                continue
            place("tree", radius, TREE_HEIGHT, point, trunk=trunk, foliage_radius=foliage, shade=rng.uniform(-1.0, 1.0))
        field._index_features()
        field._connect_ground()
        return field

    def _index_features(self):
        self._buckets.clear()
        for feature in self.features:
            if feature.destroyed:
                continue
            for cx in range(int((feature.x - feature.radius) // FEATURE_CELL),
                            int((feature.x + feature.radius) // FEATURE_CELL) + 1):
                for cy in range(int((feature.y - feature.radius) // FEATURE_CELL),
                                int((feature.y + feature.radius) // FEATURE_CELL) + 1):
                    self._buckets.setdefault((cx, cy), []).append(feature)
        self._navigation = None
        self._routes.clear()
        self._sight.clear()

    def nearby(self, start, end, padding=0.0):
        seen = set()
        for cx in range(int((min(start[0], end[0]) - padding) // FEATURE_CELL),
                        int((max(start[0], end[0]) + padding) // FEATURE_CELL) + 1):
            for cy in range(int((min(start[1], end[1]) - padding) // FEATURE_CELL),
                            int((max(start[1], end[1]) + padding) // FEATURE_CELL) + 1):
                for feature in self._buckets.get((cx, cy), ()):
                    if feature not in seen and not feature.destroyed:
                        seen.add(feature)
                        yield feature

    @staticmethod
    def _ground(point, hills):
        return max((feature.height * max(0.0, 1.0 - math.dist(point, (feature.x, feature.y)) / feature.radius)
                    for feature in hills), default=0.0)

    def elevation(self, point):
        return self._ground(point, (feature for feature in self.nearby(point, point) if feature.kind == "hill"))

    def walkable(self, point, padding=None):
        radius = self.body_radius if padding is None else padding
        if not (radius <= point[0] <= self.size[0] - radius
                and radius <= point[1] <= self.size[1] - radius):
            return False
        return not any(feature.kind in BLOCKS_MOVEMENT
                       and math.dist(point, (feature.x, feature.y)) <= feature.radius + radius
                       for feature in self.nearby(point, point, radius))

    def clear_path(self, start, end, padding=None):
        radius = self.body_radius if padding is None else padding
        return self.walkable(end, radius) and not any(
            feature.kind in BLOCKS_MOVEMENT and circle_contact(start, end, (feature.x, feature.y),
                                                               feature.radius + radius) is not None
            for feature in self.nearby(start, end, radius))

    def move(self, start, end):
        """Sweep ground movement, then slide along an open axis without crossing terrain."""
        end = (max(self.body_radius, min(self.size[0] - self.body_radius, end[0])),
               max(self.body_radius, min(self.size[1] - self.body_radius, end[1])))
        if self.clear_path(start, end):
            return end
        candidates = ((end[0], start[1]), (start[0], end[1]))
        return max((point for point in candidates if self.clear_path(start, point)),
                   key=lambda point: math.dist(start, point), default=start)

    def first_hit(self, start, end, z0, z1):
        """First terrain intersection: gaps pass shots, trees/rocks and raised ground stop them."""
        candidates = list(self.nearby(start, end))
        best = None
        hills = [feature for feature in candidates if feature.kind == "hill"]
        for feature in candidates:
            if feature.kind not in {"tree", "rock"}:
                continue
            fraction = circle_contact(start, end, (feature.x, feature.y), feature.radius)
            if fraction is not None:
                point = (start[0] + (end[0] - start[0]) * fraction,
                         start[1] + (end[1] - start[1]) * fraction)
                if z0 + (z1 - z0) * fraction <= self.elevation(point) + feature.height:
                    if best is None or fraction < best[0]:
                        best = fraction, feature
        if hills:
            steps = max(1, math.ceil(math.dist(start, end) / GROUND_SAMPLE))
            for step in range(steps + 1):
                fraction = step / steps
                if best is not None and fraction >= best[0]:
                    break
                point = (start[0] + (end[0] - start[0]) * fraction,
                         start[1] + (end[1] - start[1]) * fraction)
                if self._ground(point, hills) > z0 + (z1 - z0) * fraction:
                    best = fraction, None
                    break
        return best

    def firing_blocker(self, start, end):
        # Exact endpoints are cached only for the current AI decision interval.
        key = start, end
        if key not in self._sight:
            self._sight[key] = self.first_hit(start, end, self.elevation(start) + WEAPON_HEIGHT,
                                             self.elevation(end) + WEAPON_HEIGHT)
        return self._sight[key]

    def destroy_tree(self, feature):
        if feature.kind == "tree" and not feature.destroyed:
            feature.destroyed = True
            self.revision += 1
            self._index_features()

    def _grid(self):
        if self._navigation is None:
            # Extra clearance keeps every edge between neighboring centers safe.
            clearance = self.body_radius + NAV_CELL * math.sqrt(2) / 2
            self._navigation = {(x, y) for x in range(math.ceil(self.size[0] / NAV_CELL))
                                for y in range(math.ceil(self.size[1] / NAV_CELL))
                                if self.walkable(self.cell_center((x, y)), clearance)}
        return self._navigation

    @staticmethod
    def cell_center(cell):
        return ((cell[0] + 0.5) * NAV_CELL, (cell[1] + 0.5) * NAV_CELL)

    def _nearest_cell(self, point, require_path=False):
        grid = self._grid()
        cell = int(point[0] // NAV_CELL), int(point[1] // NAV_CELL)
        if cell in grid:
            return cell
        for candidate in sorted(grid, key=lambda key: math.dist(point, self.cell_center(key))):
            if not require_path or self.clear_path(point, self.cell_center(candidate)):
                return candidate
        return None

    def begin_decision_interval(self):
        self._sight.clear()
        # Moving objectives can create new cell pairs throughout a long encounter.
        if len(self._routes) > MAX_CACHED_ROUTES:
            self._routes.clear()

    @staticmethod
    def _neighbors(cell):
        x, y = cell
        return ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))

    def _connect_ground(self):
        """Remove barriers around isolated pockets before deployment, preserving connected routes."""
        while self.features:
            grid = self._grid()
            if not grid:
                raise ValueError("Tactical battlefield has no navigable ground.")
            start = min(grid)
            connected, queue = {start}, deque([start])
            while queue:
                for neighbor in self._neighbors(queue.popleft()):
                    if neighbor in grid and neighbor not in connected:
                        connected.add(neighbor)
                        queue.append(neighbor)
            isolated = grid - connected
            if not isolated:
                return
            point = self.cell_center(min(isolated))
            blocker = min((feature for feature in self.features if feature.kind in BLOCKS_MOVEMENT),
                          key=lambda feature: math.dist(point, (feature.x, feature.y)) - feature.radius)
            self.features.remove(blocker)
            self._index_features()

    def route(self, start, goal):
        """Cached A* over static ground; each fighter follows its own resulting waypoints."""
        if self.clear_path(start, goal):
            return [goal]
        first, last = self._nearest_cell(start, require_path=True), self._nearest_cell(goal)
        if first is None or last is None:
            return []
        key = first, last
        if key not in self._routes:
            grid = self._grid()
            queue, costs, previous = [(0, first)], {first: 0}, {}
            while queue:
                _, current = heapq.heappop(queue)
                if current == last:
                    cells = [last]
                    while cells[-1] != first:
                        cells.append(previous[cells[-1]])
                    self._routes[key] = tuple(reversed(cells))
                    break
                for neighbor in self._neighbors(current):
                    cost = costs[current] + 1
                    if neighbor in grid and cost < costs.get(neighbor, math.inf):
                        costs[neighbor], previous[neighbor] = cost, current
                        estimate = abs(neighbor[0] - last[0]) + abs(neighbor[1] - last[1])
                        heapq.heappush(queue, (cost + estimate, neighbor))
            else:
                self._routes[key] = ()
        cells = self._routes[key]
        points = [self.cell_center(cell) for cell in cells]
        if points and self.clear_path(points[-1], goal):
            points.append(goal)
        # Skip safe intermediate cells, but never cut across blocked corners.
        for index in range(len(points) - 1, -1, -1):
            if self.clear_path(start, points[index]):
                return points[index:]
        return []
