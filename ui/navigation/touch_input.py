"""Translate finger gestures once, before screens receive ordinary input.

Map gestures use the shared camera; completed taps and holds use the normal
screen handlers. No game orders or world state are changed here.
"""

from math import dist

import pygame

from data import constants as c
from data.platform import detect_control_mode


HOLD_MILLISECONDS = 500
DRAG_THRESHOLD_PIXELS = 8
FINGER_EVENTS = (pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP)
MOUSE_EVENTS = (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                pygame.MOUSEMOTION, pygame.MOUSEWHEEL)


class TouchInput:
    def __init__(self):
        # Auto is resolved once per launch, not each time an input device moves.
        self.automatic_mode = detect_control_mode()
        self.owner = None
        self.mode = None
        self.fingers = {}
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
        self.blocked = bool(self.fingers)

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
        result = []
        for event in events:
            if (event.type == pygame.WINDOWFOCUSLOST
                    or (event.type == pygame.ACTIVEEVENT and not event.gain)):
                self.cancel()
                self.fingers.clear()
                self.blocked = False
                result.append(event)
            elif event.type in FINGER_EVENTS:
                if mobile:
                    result.extend(self._finger(event))
                elif event.type == pygame.FINGERUP:
                    self.fingers.pop((event.touch_id, event.finger_id), None)
                    if not self.fingers:
                        self.blocked = False
            elif (mobile and event.type in MOUSE_EVENTS
                  and getattr(event, "touch", False)):
                # SDL still updates its pointer state, but the corresponding
                # compatibility click must not activate the screen a second time.
                continue
            else:
                result.append(event)
        return result

    def _finger(self, event):
        surface = pygame.display.get_surface()
        width, height = surface.get_size() if surface else (c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        position = (round(event.x * width), round(event.y * height))
        finger = (event.touch_id, event.finger_id)
        if event.type == pygame.FINGERDOWN:
            self.fingers[finger] = position
            if len(self.fingers) == 1 and not self.blocked:
                # Only map workspaces opt in. Menus, overlays and list panels
                # retain their existing primary-button drag handling.
                hit_map = getattr(self.owner, "touch_map_at", None)
                map_screen = hit_map(position) if hit_map else None
                self.gesture = {"start": position, "last": position,
                                "time": pygame.time.get_ticks(), "map": map_screen,
                                "dragging": False}
            elif len(self.fingers) == 2 and self.gesture and self.gesture["map"] is not None:
                hit_map = self.owner.touch_map_at(position)
                if hit_map is self.gesture["map"]:
                    self.pinch_distance = dist(*self.fingers.values())
                else:
                    self.cancel()
            else:
                self.cancel()
            return []

        if finger not in self.fingers:
            return []
        self.fingers[finger] = position
        if event.type == pygame.FINGERUP:
            del self.fingers[finger]
            if self.pinch_distance is not None or self.blocked:
                # Lifting either finger ends a pinch. The remaining finger
                # cannot turn into a new tap or movement order.
                self.cancel()
                self.blocked = bool(self.fingers)
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
            button = 3 if pygame.time.get_ticks() - gesture["time"] >= HOLD_MILLISECONDS else 1
            return [self._mouse(pygame.MOUSEBUTTONDOWN, position, button),
                    self._mouse(pygame.MOUSEBUTTONUP, position, button)]

        if self.blocked or self.gesture is None:
            return []
        gesture = self.gesture
        if self.pinch_distance is not None:
            first, second = self.fingers.values()
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
