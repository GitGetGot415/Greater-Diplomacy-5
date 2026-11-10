"""Translate mobile pointer gestures once, before screens receive ordinary input.

Map gestures use the shared camera; completed taps and holds use the normal
screen handlers. No game orders or world state are changed here.
"""

from math import ceil, cos, dist, sin, tau

import pygame

from data import constants as c
from data.platform import detect_control_mode


HOLD_MILLISECONDS = 500
DRAG_THRESHOLD_PIXELS = 8
HOLD_INDICATOR_RADIUS = 12
HOLD_INDICATOR_OFFSET = (24, -32)
HOLD_INDICATOR_SEGMENTS = 48
HOLD_INDICATOR_BACKGROUND = (28, 28, 36)
FINGER_EVENTS = (pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP)
MOUSE_EVENTS = (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                pygame.MOUSEMOTION, pygame.MOUSEWHEEL)
MOUSE_POINTER = "mouse"
MOUSE_GESTURE_EVENTS = {
    pygame.MOUSEBUTTONDOWN: pygame.FINGERDOWN,
    pygame.MOUSEBUTTONUP: pygame.FINGERUP,
    pygame.MOUSEMOTION: pygame.FINGERMOTION,
}


class TouchInput:
    def __init__(self):
        # Auto is resolved once per launch, not each time an input device moves.
        self.automatic_mode = detect_control_mode()
        self.owner = None
        self.mode = None
        self.pointers = {}
        self.gesture = None
        self.pinch_distance = None
        self.blocked = False

    def cancel(self):
        """Discard an unfinished gesture without generating a click on release."""
        if self.owner is not None:
            # Dialogs may be simple objects rather than Screen subclasses.
            cancel = getattr(self.owner, "cancel_pointer_input", None)
            if cancel is not None:
                cancel()
        self.gesture = None
        self.pinch_distance = None
        self.blocked = bool(self.pointers)

    def hold_progress(self):
        """Return the release action's progress, or None outside a stationary hold."""
        if (self.gesture is None or not self.gesture["secondary"]
                or self.gesture["dragging"] or self.blocked
                or self.pinch_distance is not None or len(self.pointers) != 1):
            return None
        return max(0.0, min(1.0, (pygame.time.get_ticks() - self.gesture["time"])
                            / HOLD_MILLISECONDS))

    def draw(self, surface, owner, mode):
        """Draw hold feedback above the active screen without performing the action."""
        progress = self.hold_progress()
        if progress is None or owner is not self.owner or mode != self.mode:
            return
        radius = HOLD_INDICATOR_RADIUS
        x, y = self.gesture["start"]
        center = (max(radius, min(surface.get_width() - radius - 1,
                                  x + HOLD_INDICATOR_OFFSET[0])),
                  max(radius, min(surface.get_height() - radius - 1,
                                  y + HOLD_INDICATOR_OFFSET[1])))
        pygame.draw.circle(surface, HOLD_INDICATOR_BACKGROUND, center, radius)
        fill_radius = radius - 2
        if progress == 1.0:
            pygame.draw.circle(surface, c.COLOR_SUCCESS_GREEN, center, fill_radius)
        elif progress > 0:
            # Screen y increases downward: starting at the top and increasing
            # the angle below fills the circular sector clockwise.
            points = [center]
            for step in range(ceil(progress * HOLD_INDICATOR_SEGMENTS) + 1):
                angle = tau * min(progress, step / HOLD_INDICATOR_SEGMENTS)
                points.append((center[0] + round(sin(angle) * fill_radius),
                               center[1] - round(cos(angle) * fill_radius)))
            pygame.draw.polygon(surface, c.COLOR_SUCCESS_GREEN, points)
        pygame.draw.circle(surface, c.UI_TEXT_LIGHT, center, radius, 1)

    @staticmethod
    def _mouse(event_type, pos, button=1, **values):
        values.update(pos=pos, touch=True, mobile_touch=True)
        if event_type != pygame.MOUSEMOTION:
            values["button"] = button
        return pygame.event.Event(event_type, values)

    def process_events(self, events, owner, mode):
        if owner is not self.owner or mode != self.mode:
            self.cancel()
            self.owner, self.mode = owner, mode
        mobile = (self.automatic_mode if mode == "AUTO" else mode) == "MOBILE"
        # SDL can publish the compatibility mouse event before the finger
        # event in the same pump. Only discard mouse input when its matching
        # finger stream exists; some emulators supply mouse events alone.
        finger_events = [event for event in events if event.type in FINGER_EVENTS]
        finger_stream = (bool(finger_events)
                         or any(pointer != MOUSE_POINTER for pointer in self.pointers))
        result = []
        for event in events:
            if (event.type == pygame.WINDOWFOCUSLOST
                    or (event.type == pygame.ACTIVEEVENT and not event.gain)):
                self.cancel()
                self.pointers.clear()
                self.blocked = False
                result.append(event)
            elif event.type in FINGER_EVENTS:
                pointer = (event.touch_id, event.finger_id)
                if mobile:
                    result.extend(self._pointer(event.type, pointer, self._finger_position(event)))
                elif event.type == pygame.FINGERUP:
                    self.pointers.pop(pointer, None)
                    if not self.pointers:
                        self.blocked = False
            elif (mobile and event.type in MOUSE_EVENTS
                  and ((getattr(event, "touch", False) and finger_stream)
                       or self._matches_finger(event, finger_events))):
                # SDL still updates its pointer state, but the corresponding
                # compatibility click must not activate the screen a second time.
                continue
            elif (mobile and event.type in MOUSE_GESTURE_EVENTS
                  and (event.type == pygame.MOUSEMOTION or event.button == 1)):
                if event.type == pygame.MOUSEMOTION and MOUSE_POINTER not in self.pointers:
                    result.append(event)  # Ordinary mouse hover remains immediate.
                else:
                    result.extend(self._pointer(MOUSE_GESTURE_EVENTS[event.type],
                                                MOUSE_POINTER, event.pos))
            else:
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self.pointers.pop(MOUSE_POINTER, None)
                    if not self.pointers:
                        self.blocked = False
                result.append(event)
        return result

    @staticmethod
    def _finger_position(event):
        surface = pygame.display.get_surface()
        width, height = surface.get_size() if surface else (c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        return (round(event.x * width), round(event.y * height))

    def _matches_finger(self, event, finger_events):
        """Some web runtimes omit the touch marker on a duplicate mouse event."""
        kind = MOUSE_GESTURE_EVENTS.get(event.type)
        if kind is None or (event.type != pygame.MOUSEMOTION and event.button != 1):
            return False
        return any(finger.type == kind
                   and dist(event.pos, self._finger_position(finger)) < DRAG_THRESHOLD_PIXELS
                   for finger in finger_events)

    def _has_secondary_action(self, position):
        # Basic dialogs need only ordinary clicks and do not implement this hook.
        available = getattr(self.owner, "has_secondary_action_at", None)
        return bool(available and available(position))

    def _pointer(self, kind, pointer, position):
        if kind == pygame.FINGERDOWN:
            self.pointers[pointer] = position
            if len(self.pointers) == 1 and not self.blocked:
                # Only map workspaces opt in. Menus, overlays and list panels
                # retain their existing primary-button drag handling.
                hit_map = getattr(self.owner, "touch_map_at", None)
                map_screen = hit_map(position) if hit_map else None
                self.gesture = {"start": position, "last": position,
                                "time": pygame.time.get_ticks(), "map": map_screen,
                                "dragging": False,
                                "secondary": self._has_secondary_action(position)}
            elif (len(self.pointers) == 2 and MOUSE_POINTER not in self.pointers
                  and self.gesture and self.gesture["map"] is not None):
                hit_map = self.owner.touch_map_at(position)
                if hit_map is self.gesture["map"]:
                    self.pinch_distance = dist(*self.pointers.values())
                else:
                    self.cancel()
            else:
                self.cancel()
            return []

        if pointer not in self.pointers:
            return []
        self.pointers[pointer] = position
        if kind == pygame.FINGERUP:
            progress = self.hold_progress()
            del self.pointers[pointer]
            if self.pinch_distance is not None or self.blocked:
                # Lifting either finger ends a pinch. The remaining finger
                # cannot turn into a new tap or movement order.
                self.cancel()
                self.blocked = bool(self.pointers)
                return []
            gesture = self.gesture
            self.gesture = None
            if gesture is None:
                return []
            if gesture["dragging"]:
                return ([] if gesture["map"] is not None else
                        [self._mouse(pygame.MOUSEBUTTONUP, position)])
            if dist(gesture["start"], position) >= DRAG_THRESHOLD_PIXELS:
                return []
            button = 1
            if progress == 1.0:
                # A menu, selection, or permission may have changed during the
                # hold. Cancel a stale secondary action instead of clicking through.
                if not self._has_secondary_action(position):
                    return []
                button = 3
            return [self._mouse(pygame.MOUSEBUTTONDOWN, position, button),
                    self._mouse(pygame.MOUSEBUTTONUP, position, button)]

        if self.blocked or self.gesture is None:
            return []
        gesture = self.gesture
        if self.pinch_distance is not None:
            first, second = self.pointers.values()
            distance = dist(first, second)
            if distance > 0 and self.pinch_distance > 0:
                midpoint = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
                gesture["map"].camera.zoom_at(
                    distance / self.pinch_distance, midpoint, gesture["map"])
            self.pinch_distance = distance
            return []

        previous = gesture["last"]
        starting_drag = not gesture["dragging"]
        if starting_drag and dist(gesture["start"], position) < DRAG_THRESHOLD_PIXELS:
            return []
        gesture["dragging"] = True
        gesture["last"] = position
        if gesture["map"] is not None:
            gesture["map"].camera.pan_by(position, previous)
            return []
        motion = self._mouse(pygame.MOUSEMOTION, position,
                             rel=(position[0] - previous[0], position[1] - previous[1]),
                             buttons=(1, 0, 0))
        return ([self._mouse(pygame.MOUSEBUTTONDOWN, gesture["start"], mobile_drag=True), motion]
                if starting_drag else [motion])
