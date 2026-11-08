"""Edit Battle, read-only Preview Battle, and optional player-controlled combat."""

import math

import pygame

import data.constants as c
from data import queries
from data.io import starting_defaults
from map_logic import custom_battle as combat
from ui.dialogs import pickers
from ui.navigation.screen import Screen
from ui.rendering.font_manager import fonts
from ui.widgets import ui_elements
from ui.widgets.text_utils import fit_text, wrap_text
from ui.widgets.ui_elements import Button, Slider


PANEL_X = 60
PANEL_WIDTH = 1160
PANEL_HEIGHT = 220
PANEL_TOPS = (365, 120)  # Friendly and enemy rosters retain their separate areas.
CARD_SIZE = (158, 132)
CARD_GAP = 12
ROSTER_INSET = 20
ROSTER_WIDTH = 900
ROSTER_TOP = 56
SCROLLBAR_HEIGHT = 14
BUTTON_WIDTH = 170
FIELD_TOP = 140
TEAM_COLORS = ((85, 170, 245), (235, 100, 90))
GRASS_COLOR = (72, 115, 57)
OUTLINE_COLOR = (22, 30, 22)
MAX_FRAME_SECONDS = 0.25
DRAG_THRESHOLD = 6
GENERATION_SLIDER_POSITION = (c.SCREEN_WIDTH - 270, 48)
GENERATION_SLIDER_WIDTH = 240
GENERATION_BUTTON_SIZE = (100, 40)
GENERATION_BUTTON_POSITION = (GENERATION_SLIDER_POSITION[0] - GENERATION_BUTTON_SIZE[0] - 20, 25)
SIMULATE_BUTTON_SIZE = (100, 40)
SIMULATE_BUTTON_POSITION = (GENERATION_BUTTON_POSITION[0] - SIMULATE_BUTTON_SIZE[0] - 10, 25)
PREVIEW_START_POSITION = ("centered", 625)
PREVIEW_START_SIZE = (220, 50)
PLAYER_COLOR = (255, 225, 95)
CONTROL_KEYS = frozenset((pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d, pygame.K_SPACE))


def draw_unit_shape(surface, shape, center, angle, color, *, scale=1.0):
    """Draw the same geometric silhouettes in setup cards and on the field."""
    width, height = {
        "tank": (28, 19), "artillery": (34, 10),
        "infantry": (21, 21), "cavalry": (30, 17),
    }[shape]
    width, height = round(width * scale), round(height * scale)
    sprite = pygame.Surface((width + 12, max(height, 24)), pygame.SRCALPHA)
    body = pygame.Rect(2, (sprite.get_height() - height) // 2, width, height)
    if shape in {"infantry", "cavalry"}:
        pygame.draw.ellipse(sprite, OUTLINE_COLOR, body)
        pygame.draw.ellipse(sprite, color, body.inflate(-4, -4))
    else:
        pygame.draw.rect(sprite, OUTLINE_COLOR, body)
        pygame.draw.rect(sprite, color, body.inflate(-4, -4))
        pygame.draw.line(sprite, OUTLINE_COLOR, body.center,
                         (sprite.get_width() - 1, body.centery), max(2, round(3 * scale)))
    rotated = pygame.transform.rotate(sprite, -math.degrees(angle))
    surface.blit(rotated, rotated.get_rect(center=center))


def draw_player_arrow(surface, center, angle):
    """Mark the controlled unit and point along its hull heading."""
    forward = pygame.Vector2(math.cos(angle), math.sin(angle))
    sideways = pygame.Vector2(-forward.y, forward.x)
    origin = pygame.Vector2(center)
    points = [origin + forward * 33, origin + forward * 19 + sideways * 6,
              origin + forward * 23, origin + forward * 19 - sideways * 6]
    pygame.draw.polygon(surface, OUTLINE_COLOR, points)
    pygame.draw.polygon(surface, PLAYER_COLOR, points, 2)


class CustomBattleScreen(Screen):
    back_state = "MENU"
    title = "Edit Battle"
    title_y = 42

    def __init__(self):
        super().__init__()
        self.mode = "setup"
        self.library = {}
        self.generation_year = starting_defaults.get_starting_value("random_setup", "start_year")
        self.random_candidates = []
        self.rosters = [[], []]
        self.selected = [None, None]
        self.controlled_index = None
        self.held_keys = set()
        self.card_surfaces = {}
        self.roster_labels = []
        self.panes = []
        self.drag = None
        self.simulation = None
        self.last_tick = 0
        self.status_key = None
        self.status_surfaces = []
        for side, top in enumerate(PANEL_TOPS):
            self.panes.append(pygame.Rect(PANEL_X + ROSTER_INSET, top + ROSTER_TOP,
                                          ROSTER_WIDTH, CARD_SIZE[1]))
            setattr(self, f"roster_{side}_scroll", 0)
            setattr(self, f"roster_{side}_limit", 0)
            setattr(self, f"roster_{side}_content", self.panes[side])
        self.refresh_ui()

    def on_enter(self, app, previous):
        self.done = False
        self.next_state = None
        self.mode = "setup"
        # Main-menu battles use the default library, never a loaded world's overrides.
        self.library = queries.get_unit_library()
        self.unit_names = sorted(combat.land_unit_types(self.library), key=lambda name: (
            queries.get_unit_metadata(name, self.library)["family"],
            queries.get_unit_tier(name, self.library)))
        allowed = set(self.unit_names)
        self.rosters = [[name for name in roster if name in allowed] for roster in self.rosters]
        self.selected = [None, None]
        self.controlled_index = None
        self.held_keys.clear()
        self.card_surfaces.clear()
        self.simulation = None
        self.cancel_active_drags()
        self.random_candidates = combat.land_unit_types_for_year(self.library, self.generation_year)
        self.refresh_ui()

    def get_title(self):
        if self.mode == "result":
            return "You Win" if self.simulation.winner == 0 else "You Lose"
        if self.mode == "preview":
            return "Preview Battle"
        return "Edit Battle" if self.mode == "setup" else "Actual Battle"

    @property
    def reserved_keys(self):
        if self.mode in {"preview", "battle"} and self.simulation.controlled is not None:
            return CONTROL_KEYS
        return ()

    @staticmethod
    def _scroll_options(side):
        return dict(attr=f"roster_{side}_scroll", limit_attr=f"roster_{side}_limit",
                    track_attr=f"roster_{side}_track", handle_attr=f"roster_{side}_handle",
                    drag_attr=f"roster_{side}_dragging", content_rect_attr=f"roster_{side}_content",
                    axis="x")

    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Exit", self.leave,
                                sound_kind="back")]
        if self.mode in {"setup", "preview"}:
            self.roster_labels = []
            for side, top in enumerate(PANEL_TOPS):
                roster = self.rosters[side]
                name = "Friendly Units" if side == 0 else "Enemy Units"
                self.roster_labels.append(fonts.get("heading2").render(
                    f"{name} ({len(roster)})", True, TEAM_COLORS[side]))
                for unit_name in set(roster):
                    self._cache_card(side, unit_name)
                limit = min(0, ROSTER_WIDTH - len(roster) * (CARD_SIZE[0] + CARD_GAP) + CARD_GAP)
                setattr(self, f"roster_{side}_limit", limit)
                offset = max(limit, min(0, getattr(self, f"roster_{side}_scroll")))
                setattr(self, f"roster_{side}_scroll", offset)
                if self.mode == "preview":
                    continue
                x = PANEL_X + PANEL_WIDTH - BUTTON_WIDTH - ROSTER_INSET
                add = Button(x, top + 70, (BUTTON_WIDTH, 42), "blue" if side == 0 else "red",
                             "Add Friendly" if side == 0 else "Add Enemy",
                             lambda side=side: self.open_picker(side), font_size=20)
                add.apply_state(enabled=len(roster) < c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE,
                                color="blue" if side == 0 else "red")
                remove = Button(x, top + 128, (BUTTON_WIDTH, 42), "grey", "Remove",
                                lambda side=side: self.remove_unit(side), font_size=20)
                remove.apply_state(enabled=self.selected[side] is not None, color="red")
                self.elements.extend((add, remove))
                if side == 0:
                    controlling = self.controlled_index is not None and self.controlled_index == self.selected[0]
                    control = Button(x, top + 178, (BUTTON_WIDTH, 32), "yellow",
                                     "Release Control" if controlling else "Control",
                                     self.toggle_control, font_size=18)
                    control.apply_state(enabled=self.selected[0] is not None,
                                        color="yellow" if controlling else "green")
                    self.elements.append(control)
            if self.mode == "preview":
                self.elements.append(Button(*PREVIEW_START_POSITION, PREVIEW_START_SIZE,
                                            "green", "Start", self.start_battle))
                return
            simulate = Button(*SIMULATE_BUTTON_POSITION, SIMULATE_BUTTON_SIZE, "green", "Simulate",
                              self.preview_battle, font_size=18)
            simulate.apply_state(enabled=all(self.rosters), color="green")
            self.elements.append(simulate)
            self.generate_button = Button(
                *GENERATION_BUTTON_POSITION, GENERATION_BUTTON_SIZE, "purple", "Random",
                self.generate_armies, font_size=20)
            self.generate_button.apply_state(enabled=bool(self.random_candidates), color="purple")
            self.year_slider = Slider(
                *GENERATION_SLIDER_POSITION, GENERATION_SLIDER_WIDTH,
                f"Year: {self.generation_year}", self.generation_year - c.START_YEAR,
                self.update_generation_year, visual_max=c.END_YEAR - c.START_YEAR,
                allowed_max=c.END_YEAR - c.START_YEAR)
            self.elements.extend((self.generate_button, self.year_slider))
        elif self.mode == "battle":
            self.pause_button = Button(c.SCREEN_WIDTH - 150, 20, (130, 40), "yellow",
                                       "Resume" if self.simulation.paused else "Pause", self.toggle_pause)
            self.elements.append(self.pause_button)
        else:
            self.elements.extend((
                Button("centered", 370, (220, 50), "green", "Run Again", self.preview_battle),
                Button("centered", 440, (220, 50), "blue", "Edit Armies", self.return_to_setup)))

    def update_generation_year(self, value):
        if self.mode != "setup":
            return
        year = max(c.START_YEAR, min(c.END_YEAR, c.START_YEAR + round(value)))
        if year != self.generation_year:
            self.generation_year = year
            self.random_candidates = combat.land_unit_types_for_year(self.library, year)
            self.generate_button.apply_state(enabled=bool(self.random_candidates), color="purple")
        # Keep the current slider alive while dragging instead of rebuilding controls.
        self.year_slider.text = f"Year: {self.generation_year}"
        self.year_slider.value = self.generation_year - c.START_YEAR
        self.year_slider.handle_rect.centerx = self.year_slider.rect.left + round(
            self.year_slider.rect.width * self.year_slider.value / self.year_slider.visual_max)

    def generate_armies(self):
        if self.mode != "setup" or not self.random_candidates:
            return
        self.cancel_active_drags()
        self.rosters = combat.random_armies(self.random_candidates)
        self.selected = [None, None]
        self.controlled_index = None
        for side in (0, 1):
            setattr(self, f"roster_{side}_scroll", 0)
        self.refresh_ui()

    def open_picker(self, side):
        if self.mode != "setup":
            return
        self.cancel_active_drags()
        pickers.open_listbox_selector(
            self, "Add Friendly Units" if side == 0 else "Add Enemy Units", "",
            queries.unit_picker_items(self.unit_names, self.library),
            lambda name: self.add_unit(side, name), close_on_select=False,
            is_enabled=lambda item: len(self.rosters[side]) < c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE)

    def add_unit(self, side, name):
        if self.mode != "setup" or name not in self.unit_names:
            return
        roster = self.rosters[side]
        if len(roster) >= c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE:
            return
        roster.append(name)
        self.selected[side] = len(roster) - 1
        self.refresh_ui()
        setattr(self, f"roster_{side}_scroll", getattr(self, f"roster_{side}_limit"))

    def remove_unit(self, side):
        index = self.selected[side]
        if self.mode != "setup" or index is None or not 0 <= index < len(self.rosters[side]):
            return
        self.rosters[side].pop(index)
        if side == 0 and self.controlled_index is not None:
            if self.controlled_index == index:
                self.controlled_index = None
            elif self.controlled_index > index:
                self.controlled_index -= 1
        self.selected[side] = None
        self.refresh_ui()

    def toggle_control(self):
        index = self.selected[0]
        if self.mode != "setup" or index is None or not 0 <= index < len(self.rosters[0]):
            return
        self.controlled_index = None if self.controlled_index == index else index
        self.refresh_ui()

    def preview_battle(self):
        if self.mode not in {"setup", "result"} or not all(self.rosters):
            return
        self.cancel_active_drags()
        self.simulation = combat.BattleSimulation(self.library, *self.rosters,
                                                  controlled_index=self.controlled_index)
        self.simulation.paused = True
        self.clear_controls()
        self.mode = "preview"
        self.status_key = None
        self._refresh_status()
        self.refresh_ui()

    def start_battle(self):
        if self.mode != "preview":
            return
        self.clear_controls()
        self.simulation.paused = False
        self.mode = "battle"
        self.last_tick = pygame.time.get_ticks()
        self.refresh_ui()

    def clear_controls(self):
        self.held_keys.clear()
        if self.simulation is not None:
            self.simulation.set_player_input()

    def return_to_setup(self):
        self.cancel_active_drags()
        self.clear_controls()
        self.mode = "setup"
        self.simulation = None
        self.refresh_ui()

    def leave(self):
        if self.mode == "setup":
            self.cancel_active_drags()
            self.exit_screen()
        else:
            self.return_to_setup()

    def toggle_pause(self):
        if self.mode == "battle":
            self.clear_controls()
            self.simulation.paused = not self.simulation.paused
            self.last_tick = pygame.time.get_ticks()
            self.refresh_ui()

    def handle_back_key(self):
        if self.drag is not None:
            self.cancel_active_drags()
        elif self.mode == "battle":
            self.toggle_pause()
        else:
            self.leave()

    def cancel_active_drags(self):
        super().cancel_active_drags()
        self.drag = None
        for element in self.elements:
            if isinstance(element, Slider):
                element.dragging = False
        for side in (0, 1):
            setattr(self, f"roster_{side}_dragging", False)

    def card_rect(self, side, index):
        pane = self.panes[side]
        return pygame.Rect(pane.x + index * (CARD_SIZE[0] + CARD_GAP)
                           + getattr(self, f"roster_{side}_scroll"), pane.y, *CARD_SIZE)

    def _roster_events(self, event):
        if self.drag is not None and self.mode == "setup":
            side, index, origin, active = self.drag
            if event.type == pygame.MOUSEMOTION:
                if math.dist(event.pos, origin) >= DRAG_THRESHOLD:
                    self.drag[3] = True
                return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if active and self.panes[side].collidepoint(event.pos):
                    offset = getattr(self, f"roster_{side}_scroll")
                    destination = int((event.pos[0] - self.panes[side].x - offset)
                                      // (CARD_SIZE[0] + CARD_GAP))
                    destination = min(len(self.rosters[side]) - 1, max(0, destination))
                    name = self.rosters[side].pop(index)
                    self.rosters[side].insert(destination, name)
                    if side == 0 and self.controlled_index is not None:
                        if self.controlled_index == index:
                            self.controlled_index = destination
                        elif index < self.controlled_index <= destination:
                            self.controlled_index -= 1
                        elif destination <= self.controlled_index < index:
                            self.controlled_index += 1
                    self.selected[side] = destination
                self.drag = None
                self.refresh_ui()
                return True
            return False
        pointer = getattr(event, "pos", pygame.mouse.get_pos())
        for side, pane in enumerate(self.panes):
            options = self._scroll_options(side)
            track = getattr(self, options["track_attr"], None)
            engaged = (pane.collidepoint(pointer) or (track and track.collidepoint(pointer))
                       or getattr(self, options["drag_attr"], False)
                       or self.is_content_dragging(options["attr"]))
            if not engaged:
                continue
            if (self.mode == "setup" and event.type == pygame.MOUSEBUTTONDOWN
                    and event.button == 1 and pane.collidepoint(event.pos)):
                for index in range(len(self.rosters[side])):
                    if self.card_rect(side, index).collidepoint(event.pos):
                        self.selected[side] = index
                        self.drag = [side, index, event.pos, False]
                        self.refresh_ui()
                        return True
            if self.handle_list_scroll(event, **options):
                return True
        return False

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.WINDOWFOCUSLOST:
                self.cancel_active_drags()
                self.clear_controls()
                if self.mode == "battle" and not self.simulation.paused:
                    self.toggle_pause()
            if self.done:
                return
            if event.type == pygame.KEYUP:
                self.held_keys.discard(event.key)
            if (event.type == pygame.KEYDOWN and event.key in CONTROL_KEYS
                    and self.mode == "battle" and not self.simulation.paused
                    and self.simulation.controlled is not None and self.simulation.controlled.alive):
                self.held_keys.add(event.key)
                continue
            if (self.mode == "setup" and event.type == pygame.MOUSEWHEEL
                    and self.year_slider.rect.inflate(20, 40).collidepoint(pygame.mouse.get_pos())):
                # A shorter track skips some years when dragged at pixel resolution.
                self.update_generation_year(self.generation_year - c.START_YEAR + event.y)
                continue
            if self.mode in {"setup", "preview"} and self._roster_events(event):
                continue
            for element in list(self.elements):
                element.handle_event(event)

    def _refresh_status(self):
        counts = tuple(sum(fighter.alive and fighter.side == side for fighter in self.simulation.fighters)
                       for side in (0, 1))
        key = (*counts, int(self.simulation.elapsed))
        if key != self.status_key:
            self.status_key = key
            self.status_surfaces = [fonts.get("normal").render(text, True, c.UI_TEXT_BRIGHT)
                                    for text in (f"Friendly: {counts[0]}", f"Enemy: {counts[1]}",
                                                 f"{int(self.simulation.elapsed)}s")]

    def update(self):
        if self.mode != "battle":
            return
        now = pygame.time.get_ticks()
        dt = min(MAX_FRAME_SECONDS, max(0, now - self.last_tick) / 1000.0)
        self.last_tick = now
        self.simulation.set_player_input(
            throttle=int(pygame.K_w in self.held_keys) - int(pygame.K_s in self.held_keys),
            turn=int(pygame.K_d in self.held_keys) - int(pygame.K_a in self.held_keys),
            fire=pygame.K_SPACE in self.held_keys)
        self.simulation.advance(dt)
        self._refresh_status()
        if self.simulation.winner is not None:
            self.clear_controls()
            self.mode = "result"
            self.refresh_ui()

    def _cache_card(self, side, name):
        key = (side, name)
        if key not in self.card_surfaces:
            card = pygame.Surface(CARD_SIZE)
            ui_elements.draw_pixel_panel(card, card.get_rect(), (46, 51, 65), (15, 19, 27))
            draw_unit_shape(card, combat.unit_shape(name, self.library), (CARD_SIZE[0] // 2, 28),
                            0 if side == 0 else math.pi, TEAM_COLORS[side], scale=1.4)
            font = fonts.get("small")
            label = queries.get_unit_display_name(name, self.library)
            for line_number, line in enumerate(wrap_text(label, font, CARD_SIZE[0] - 16)[:3]):
                text = font.render(fit_text(line, font, CARD_SIZE[0] - 16), True, c.UI_TEXT_BRIGHT)
                card.blit(text, text.get_rect(midtop=(CARD_SIZE[0] // 2, 52 + line_number * 18)))
            stats = self.library[name]
            caption = fit_text(f"HP {stats['health']:g}  ATK {stats['attack']:g}", font, CARD_SIZE[0] - 12)
            text = font.render(caption, True, c.UI_TEXT_LIGHT)
            card.blit(text, text.get_rect(midbottom=(CARD_SIZE[0] // 2, CARD_SIZE[1] - 8)))
            self.card_surfaces[key] = card
        return self.card_surfaces[key]

    def _draw_rosters(self, surface):
        for side, top in enumerate(PANEL_TOPS):
            panel = pygame.Rect(PANEL_X, top, PANEL_WIDTH, PANEL_HEIGHT)
            ui_elements.draw_pixel_panel(surface, panel, (39, 44, 58), (15, 19, 27))
            surface.blit(self.roster_labels[side], (panel.x + ROSTER_INSET, panel.y + 14))
            old_clip = surface.get_clip()
            surface.set_clip(old_clip.clip(self.panes[side]))
            for index, name in enumerate(self.rosters[side]):
                rect = self.card_rect(side, index)
                if not rect.colliderect(self.panes[side]):
                    continue
                if self.drag is not None and self.drag[0] == side and self.drag[1] == index and self.drag[3]:
                    continue
                surface.blit(self.card_surfaces[(side, name)], rect)
                if self.selected[side] == index:
                    pygame.draw.rect(surface, TEAM_COLORS[side], rect, 2)
                if side == 0 and self.controlled_index == index:
                    draw_player_arrow(surface, (rect.centerx, rect.y + 28), 0)
            surface.set_clip(old_clip)
            self.draw_list_scrollbar(surface, self.panes[side].x, self.panes[side].bottom + 10,
                                     ROSTER_WIDTH, width=SCROLLBAR_HEIGHT, **self._scroll_options(side))
        if self.drag is not None and self.drag[3]:
            side, index, origin, active = self.drag
            card = self.card_surfaces[(side, self.rosters[side][index])]
            rect = card.get_rect(center=pygame.mouse.get_pos())
            surface.blit(card, rect)
            if side == 0 and self.controlled_index == index:
                draw_player_arrow(surface, (rect.centerx, rect.y + 28), 0)

    def _draw_battle(self, surface):
        field = pygame.Rect((c.SCREEN_WIDTH - c.CUSTOM_BATTLE_ARENA_SIZE[0]) // 2,
                            FIELD_TOP, *c.CUSTOM_BATTLE_ARENA_SIZE)
        pygame.draw.rect(surface, GRASS_COLOR, field)
        pygame.draw.rect(surface, OUTLINE_COLOR, field, 3)
        old_clip = surface.get_clip()
        surface.set_clip(old_clip.clip(field))
        for fighter in self.simulation.fighters:
            center = (round(field.x + fighter.x), round(field.y + fighter.y))
            if not fighter.alive:
                draw_unit_shape(surface, fighter.shape, center, fighter.angle, (53, 65, 44))
                continue
            draw_unit_shape(surface, fighter.shape, center, fighter.angle, TEAM_COLORS[fighter.side])
            bar = pygame.Rect(center[0] - 14, center[1] - 23, 28, 4)
            pygame.draw.rect(surface, OUTLINE_COLOR, bar)
            ratio = fighter.data["health"] / max(1, fighter.data["max_health"])
            pygame.draw.rect(surface, (105, 215, 85), (bar.x, bar.y, round(bar.width * ratio), bar.height))
            if fighter is self.simulation.controlled:
                pygame.draw.circle(surface, PLAYER_COLOR, center, 18, 2)
                draw_player_arrow(surface, center, fighter.angle)
        for shot in self.simulation.projectiles:
            head = (round(field.x + shot.x), round(field.y + shot.y))
            tail = (round(head[0] - shot.vx / c.CUSTOM_BATTLE_PROJECTILE_SPEED * 8),
                    round(head[1] - shot.vy / c.CUSTOM_BATTLE_PROJECTILE_SPEED * 8))
            pygame.draw.line(surface, (250, 232, 150), tail, head, 2)
        surface.set_clip(old_clip)
        if self.mode == "battle" and self.simulation.paused:
            rect = pygame.Rect(0, 0, 210, 70)
            rect.center = field.center
            ui_elements.draw_pixel_panel(surface, rect, (39, 44, 58), (15, 19, 27))
            label = fonts.get("heading2").render("Paused", True, c.UI_TEXT_BRIGHT)
            surface.blit(label, label.get_rect(center=rect.center))

    def additional_draw(self, surface):
        if self.mode in {"setup", "preview"}:
            self._draw_rosters(surface)
        else:
            for image, center in zip(self.status_surfaces, ((220, 103), (1060, 103), (640, 103))):
                surface.blit(image, image.get_rect(center=center))
            if self.mode == "battle":
                self._draw_battle(surface)
