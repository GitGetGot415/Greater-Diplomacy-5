"""Edit Battle, read-only Preview Battle, and optional player-controlled combat."""

import math
import random

import pygame

import data.constants as c
from data import queries
from data.io import starting_defaults
from map_logic import custom_battle as combat
from map_logic.system32 import combat_rules
from ui.dialogs import pickers
from ui.navigation import screen_runner
from ui.navigation.modal_screen import ModalScreen
from ui.navigation.screen import Screen
from ui.rendering import symbol_loader
from ui.rendering.font_manager import fonts
from ui.widgets import ui_elements
from ui.widgets import flag_icons
from ui.widgets.text_utils import fit_text, wrap_text
from ui.widgets.ui_elements import Button, Slider
from screens.setup import player_setup


PANEL_X = 60
ROSTER_TOP = 56
PANEL_WIDTH = 1160
PANEL_TOPS = (365, 120)  # Friendly and enemy rosters retain their separate areas.
CARD_SIZE = (158, 148)
CARD_GAP = 12
PREVIEW_CARD_ICON_SIZE = (96, 60)
PREVIEW_ICON_CENTER_Y = 40
# Health bar rows: preview puts the bar under the icon; editing puts it at the card bottom.
PREVIEW_BAR_TOP = 80
EDIT_BAR_TOP = 124
CARD_BAR_HEIGHT = 14
CARD_BAR_GRAB_PAD = 6  # Extra pixels above and below the bar that still grab it in editing.
CARD_ROW_INSET = 8
CARD_BAR_FLAG_GAP = 6
CARD_BAR_FLAG_SIZE = (24, 16)
PREVIEW_STATS_TOP = 108
HEALTH_BAR_FULL_COLOR = (105, 215, 85)
HEALTH_BAR_HALF_COLOR = (235, 205, 60)  # Reached at half health.
HEALTH_BAR_EMPTY_COLOR = (215, 60, 50)  # Reached at zero health; the fill blends between the three colors.
HEALTH_BAR_SHADE = 30  # Brightness step between the light, middle, and dark bands of the fill.
HEALTH_BAR_BANDS = 3
PANEL_BOTTOM_SPACE = 32  # Below the cards: scrollbar row and margin.
PANEL_HEIGHT = ROSTER_TOP + CARD_SIZE[1] + PANEL_BOTTOM_SPACE
CARD_STATS_TOP = 96
CARD_STAT_ICON_SIZE = 14
BATTLE_FLAG_SIZE = (14, 9)
BATTLE_FLAG_GAP = 3
MIXED_LABEL = "Mixed"
CARD_EDIT_SIZE = 24
CARD_EDIT_INSET = 6
ROSTER_INSET = 20
ROSTER_WIDTH = 900
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
PREVIEW_RETREAT_SIZE = (160, 50)
PREVIEW_RETREAT_GAP = 20  # Between Start and Retreat.
# Preview entry animation: edit these durations in seconds, then restart the game.
# Slide durations must be positive; the hold can be zero.
PREVIEW_SLIDE_IN_SECONDS = 0.2
PREVIEW_HOLD_SECONDS = 0.5
PREVIEW_SLIDE_OUT_SECONDS = 0.2
# Independent of Messages so the battle bars can be restyled separately.
PREVIEW_BAR_COLOR = (46, 56, 72)
PREVIEW_BAR_BORDER = (13, 17, 24)
PREVIEW_BAR_GRADIENT_STRENGTH = 0.5
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


class CampaignBattle:
    """The tactical-mode encounter a battle belongs to. The player's unit is friendly entry 0."""

    def __init__(self, map_screen, province, unit, custom_rosters):
        self.map_screen = map_screen
        self.province = province
        self.unit = unit
        self.custom_rosters = custom_rosters  # The custom-battle armies to restore afterward.


class CustomBattleScreen(Screen):
    back_state = "MENU"
    title = "Edit Battle"
    title_y = 42

    def __init__(self):
        super().__init__()
        self.mode = "setup"
        self.controller = None
        self.library = {}
        self.country_data = {}
        self.nationalities = []
        self.generation_year = starting_defaults.get_starting_value("random_setup", "start_year")
        self.random_candidates = []
        self.rosters = [[], []]
        self.selected = [None, None]
        # Roster indices chosen by a selection square; two or more entries per side.
        self.group = [[], []]
        self.campaign = None  # A CampaignBattle while a tactical-mode encounter is shown.
        self.choosing_retreat = False
        self.bar_drag = None  # (side, index) of the card whose health bar is being dragged
        self.marquee = None  # [side, start position, current position] while dragging a square
        self.controlled_index = None
        self.held_keys = set()
        self.card_surfaces = {}
        self.unit_buttons = {}
        self.gear_icon = None
        self.roster_labels = []
        self.panes = []
        self.drag = None
        self.simulation = None
        self.last_tick = 0
        self.preview_intro_started = None
        self.preview_intro_stage = None
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
        self.controller = app
        request = getattr(previous, "tactical_battle_request", None)
        if request is not None:
            previous.tactical_battle_request = None
            self._enter_campaign(previous, *request)
            return
        if self.choosing_retreat:
            # Back from the retreat map: show the same preview again.
            self.choosing_retreat = False
            self.done = False
            self.next_state = None
            self.controller.set_tactical_battle_music(True)
            return
        if self.campaign is not None:
            self._end_campaign()
        if self.controller is not None:
            self.controller.set_tactical_battle_music(False)
        self.done = False
        self.next_state = None
        self.mode = "setup"
        self.preview_intro_started = None
        self.preview_intro_stage = None
        # Main-menu battles use the default library, never a loaded world's overrides.
        self.library = queries.get_unit_library()
        self.country_data = queries.get_country_data()
        self.gear_icon = symbol_loader.get_symbol(
            "Gear", zoom=1, fit_size=(CARD_EDIT_SIZE - 8, CARD_EDIT_SIZE - 8))
        self.nationalities = sorted(
            (country for country in self.country_data if queries.is_playable(country, self.country_data)),
            key=lambda country: queries.get_country_display_name(country, self.country_data))
        if not self.nationalities:
            raise ValueError("Custom battles need at least one playable country in countries_data.json.")
        self.unit_names = sorted(combat.land_unit_types(self.library), key=lambda name: (
            queries.get_unit_metadata(name, self.library)["family"],
            queries.get_unit_tier(name, self.library)))
        allowed = set(self.unit_names)
        self.rosters = [[unit for unit in roster if unit["type"] in allowed] for roster in self.rosters]
        self.selected = [None, None]
        self.group = [[], []]
        self.controlled_index = None
        self.held_keys.clear()
        self.card_surfaces.clear()
        self.simulation = None
        self.cancel_active_drags()
        self.random_candidates = combat.land_unit_types_for_year(self.library, self.generation_year)
        self.refresh_ui()

    def _enter_campaign(self, map_screen, province, friendly, enemy):
        """Open preview at once for a tactical player's encounter, controlling their unit."""
        self.done = False
        self.next_state = None
        self.campaign = CampaignBattle(map_screen, province, map_screen.player_unit, self.rosters)
        self.library = queries.get_unit_library(map_screen)
        self.country_data = map_screen.nation_data
        self.rosters = [friendly, enemy]
        self.selected = [None, None]
        self.group = [[], []]
        self.controlled_index = 0
        self.held_keys.clear()
        self.card_surfaces.clear()
        self.simulation = None
        self.mode = "setup"
        self.cancel_active_drags()
        for side in (0, 1):
            setattr(self, f"roster_{side}_scroll", 0)
        self.preview_battle()

    def _end_campaign(self):
        self.rosters = self.campaign.custom_rosters
        self.campaign = None
        self.choosing_retreat = False

    def retreat(self):
        """Custom battles return to editing; a tactical encounter picks a tile on the map."""
        if self.mode != "preview" or self.preview_intro_stage is not None:
            return
        if self.campaign is None:
            self.return_to_setup()
            return
        self.clear_controls()
        self.choosing_retreat = True
        self.go_to("TACTICAL_RETREAT")

    def finish_retreat(self):
        """The retreat order is given: the encounter is over."""
        self._end_campaign()

    def continue_campaign(self):
        """Leave the finished encounter. A dead tactical unit sends the player to spectating."""
        if self.mode != "result" or self.campaign is None:
            return
        campaign = self.campaign
        died = not self.simulation.controlled.alive
        self._end_campaign()
        if died:
            player_setup.lose_tactical_unit(campaign.map_screen, campaign.province)
        self.go_to("MAP")

    def get_title(self):
        if self.mode == "result":
            return "You Win" if self.simulation.winner == 0 else "You Lose"
        if self.mode == "preview":
            return "Preview Battle"
        return "Edit Battle" if self.mode == "setup" else "Actual Battle"

    @property
    def reserved_keys(self):
        if (self.preview_intro_stage is None and self.mode in {"preview", "battle"}
                and self.simulation.controlled is not None):
            return CONTROL_KEYS
        return ()

    @staticmethod
    def _scroll_options(side):
        return dict(attr=f"roster_{side}_scroll", limit_attr=f"roster_{side}_limit",
                    track_attr=f"roster_{side}_track", handle_attr=f"roster_{side}_handle",
                    drag_attr=f"roster_{side}_dragging", content_rect_attr=f"roster_{side}_content",
                    axis="x")

    def refresh_ui(self):
        self.unit_buttons = {}
        self.elements = []
        if self.mode == "setup" or (self.mode in {"battle", "result"} and self.campaign is None):
            self.elements.append(Button(20, 20, "small", "red", "Exit", self.leave,
                                        sound_kind="back"))
        if self.mode in {"setup", "preview"}:
            self.roster_labels = []
            for side, top in enumerate(PANEL_TOPS):
                roster = self.rosters[side]
                name = "Friendly Units" if side == 0 else "Enemy Units"
                self.roster_labels.append(fonts.get("heading2").render(
                    f"{name} ({len(roster)})", True, TEAM_COLORS[side]))
                for index, unit in enumerate(roster):
                    self._cache_card(side, unit)
                    if self.mode == "setup":
                        self.unit_buttons[side, index] = Button(
                            0, 0, (CARD_EDIT_SIZE, CARD_EDIT_SIZE), "grey", "",
                            lambda side=side, unit=unit: self.edit_unit(side, unit),
                            image=self.gear_icon, show_text=False,
                            sound_kind="open_settings")
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
                start = Button(*PREVIEW_START_POSITION, PREVIEW_START_SIZE,
                               "green", "Start", self.start_battle)
                retreat = Button(start.rect.right + PREVIEW_RETREAT_GAP, start.rect.y,
                                 PREVIEW_RETREAT_SIZE, "red", "Retreat", self.retreat,
                                 sound_kind="back")
                self.elements.extend((start, retreat))
                return
            simulate = Button(*SIMULATE_BUTTON_POSITION, SIMULATE_BUTTON_SIZE, "green", "Simulate",
                              self.preview_battle, font_size=18, sound_kind=None)
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
        elif self.campaign is not None:
            self.elements.append(Button("centered", 370, (220, 50), "green", "Continue",
                                        self.continue_campaign))
        else:
            self.elements.extend((
                Button("centered", 370, (220, 50), "green", "Run Again", self.preview_battle,
                       sound_kind=None),
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
        self.rosters = [[self._new_unit(side, name, random.choice(self.nationalities)) for name in roster]
                        for side, roster in enumerate(combat.random_armies(self.random_candidates))]
        self.selected = [None, None]
        self.group = [[], []]
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
        roster.append(self._new_unit(side, name))
        self.selected[side] = len(roster) - 1
        self.refresh_ui()
        setattr(self, f"roster_{side}_scroll", getattr(self, f"roster_{side}_limit"))

    def _new_unit(self, side, name, country=None):
        if country is None:
            country = self.nationalities[min(side, len(self.nationalities) - 1)]
        return queries.create_unit_dict(name, country, self.library)

    def edit_unit(self, side, unit):
        if self.mode != "setup" or not any(entry is unit for entry in self.rosters[side]):
            return
        self.cancel_active_drags()
        screen_runner._run_pygame_sub_screen(
            self, CustomBattleUnitEditor(self, side, self._units_to_edit(side, unit)))

    def _units_to_edit(self, side, unit):
        """A card in a selected group edits the whole group; any other card edits itself."""
        grouped = [self.rosters[side][index] for index in self.group[side]]
        return grouped if any(entry is unit for entry in grouped) else [unit]

    def set_unit_options(self, side, units, *, owner=None, health_percent=None):
        """Set nationality and starting HP (a percent of each unit's maximum HP) for roster entries."""
        if (self.mode != "setup" or not units
                or not all(any(entry is unit for entry in self.rosters[side]) for unit in units)):
            return False
        if owner is not None and owner not in self.nationalities:
            return False
        if health_percent is not None and not (
                isinstance(health_percent, (int, float)) and not isinstance(health_percent, bool)
                and 0 < health_percent <= 100):
            return False
        for unit in units:
            if owner is not None:
                unit["owner"] = owner
            if health_percent is not None:
                unit["health"] = unit["max_health"] * health_percent / 100
        self.card_surfaces.clear()
        self.refresh_ui()
        return True

    def remove_unit(self, side):
        index = self.selected[side]
        if self.mode != "setup" or index is None or not 0 <= index < len(self.rosters[side]):
            return
        self.rosters[side].pop(index)
        self.group[side] = []
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
        # Start the clock on the first draw so entry always includes a black frame.
        self.preview_intro_started = None
        self.preview_intro_stage = 0
        ui_elements.play_ui_sound("open_music")
        if self.controller is not None:
            self.controller.set_tactical_battle_music(True)
        self.status_key = None
        self._refresh_status()
        self.refresh_ui()

    def start_battle(self):
        if self.mode != "preview" or self.preview_intro_stage is not None:
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
        if self.controller is not None:
            self.controller.set_tactical_battle_music(False)
        self.mode = "setup"
        self.preview_intro_started = None
        self.preview_intro_stage = None
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
        elif self.campaign is None:
            self.leave()

    def cancel_active_drags(self):
        super().cancel_active_drags()
        self.drag = None
        self.marquee = None
        self.bar_drag = None
        for element in self.elements:
            if isinstance(element, Slider):
                element.dragging = False
        for button in self.unit_buttons.values():
            button.is_pressed = False
        for side in (0, 1):
            setattr(self, f"roster_{side}_dragging", False)

    def card_rect(self, side, index):
        pane = self.panes[side]
        return pygame.Rect(pane.x + index * (CARD_SIZE[0] + CARD_GAP)
                           + getattr(self, f"roster_{side}_scroll"), pane.y, *CARD_SIZE)

    @staticmethod
    def _position_edit_button(button, card):
        button.rect.topright = (card.right - CARD_EDIT_INSET, card.top + CARD_EDIT_INSET)

    def _unit_button_events(self, event):
        if (self.mode != "setup" or self.drag is not None
                or event.type not in {pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP}):
            return False
        for (side, index), button in self.unit_buttons.items():
            self._position_edit_button(button, self.card_rect(side, index))
            if self.panes[side].collidepoint(event.pos):
                engaged = button.is_pressed or button.rect.collidepoint(event.pos)
                if engaged:
                    button.handle_event(event)
                    return True
            elif event.type == pygame.MOUSEBUTTONUP:
                button.is_pressed = False
        return False

    def _on_scrollbar(self, side, pos):
        track = getattr(self, f"roster_{side}_track", None)
        return bool(track and track.collidepoint(pos))

    def _marquee_events(self, event):
        """Drag a selection square from empty panel space; roster background drags still scroll."""
        if self.marquee is not None:
            if event.type == pygame.MOUSEMOTION:
                self.marquee[2] = event.pos
                return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                side, origin, _current = self.marquee
                self.marquee = None
                self._select_group(side, origin, event.pos)
                return True
            return False
        if (event.type != pygame.MOUSEBUTTONDOWN or event.button != 1 or self.drag is not None):
            return False
        if any(isinstance(element, Button) and element.rect.collidepoint(event.pos)
               for element in self.elements):
            return False
        for side, top in enumerate(PANEL_TOPS):
            if (pygame.Rect(PANEL_X, top, PANEL_WIDTH, PANEL_HEIGHT).collidepoint(event.pos)
                    and not self.panes[side].collidepoint(event.pos)
                    and not self._on_scrollbar(side, event.pos)):
                self.marquee = [side, event.pos, event.pos]
                return True
        return False

    @staticmethod
    def _marquee_rect(origin, current):
        return pygame.Rect(min(origin[0], current[0]), min(origin[1], current[1]),
                           abs(origin[0] - current[0]), abs(origin[1] - current[1]))

    def _select_group(self, side, origin, current):
        """Select the visible cards the square touches; a click without dragging clears the selection."""
        picked = []
        if math.dist(origin, current) >= DRAG_THRESHOLD:
            area = self._marquee_rect(origin, current).clip(self.panes[side])
            picked = [index for index in range(len(self.rosters[side]))
                      if self.card_rect(side, index).colliderect(area)]
        # One card is an ordinary selection, so Remove and Control keep working.
        self.selected[side] = picked[0] if len(picked) == 1 else None
        self.group[side] = picked if len(picked) > 1 else []
        self.refresh_ui()

    def _set_bar_health(self, side, index, x):
        """Set starting HP from the pointer's position along a card's health bar."""
        card = self.card_rect(side, index)
        bar, _flag_x = self._bar_geometry(EDIT_BAR_TOP)
        percent = round((x - card.x - bar.x) / bar.width * 100)
        unit = self.rosters[side][index]
        self.set_unit_options(side, self._units_to_edit(side, unit), health_percent=max(1, min(100, percent)))

    def _health_bar_events(self, event):
        """Press or drag along a card's health bar to set its starting HP."""
        if self.bar_drag is not None:
            side, index = self.bar_drag
            if event.type == pygame.MOUSEMOTION:
                self._set_bar_health(side, index, event.pos[0])
                return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._set_bar_health(side, index, event.pos[0])
                self.bar_drag = None
                return True
            return False
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1 or self.drag is not None:
            return False
        bar, _flag_x = self._bar_geometry(EDIT_BAR_TOP)
        for side, pane in enumerate(self.panes):
            if not pane.collidepoint(event.pos):
                continue
            for index in range(len(self.rosters[side])):
                card = self.card_rect(side, index)
                if bar.move(card.topleft).inflate(0, 2 * CARD_BAR_GRAB_PAD).collidepoint(event.pos):
                    self.bar_drag = (side, index)
                    self._set_bar_health(side, index, event.pos[0])
                    return True
        return False

    def _roster_events(self, event):
        if self.mode == "setup" and (self._marquee_events(event) or self._health_bar_events(event)):
            return True
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
                    unit = self.rosters[side].pop(index)
                    self.rosters[side].insert(destination, unit)
                    self.group[side] = []
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
                        self.group[side] = []
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
            if self.preview_intro_stage is not None:
                # Global Back handling remains available while the UI is covered.
                continue
            if self._unit_button_events(event):
                continue
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
        if self.preview_intro_stage is not None:
            self._update_preview_intro()
            return
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
            if self.controller is not None:
                self.controller.set_tactical_battle_music(False)
            self.mode = "result"
            self.refresh_ui()

    def _update_preview_intro(self):
        if self.preview_intro_started is None:
            return
        elapsed = (pygame.time.get_ticks() - self.preview_intro_started) / 1000.0
        opening_at = PREVIEW_SLIDE_IN_SECONDS + PREVIEW_HOLD_SECONDS
        # Check both boundaries in order, even if a slow frame crosses both.
        if self.preview_intro_stage == 0 and elapsed >= PREVIEW_SLIDE_IN_SECONDS:
            ui_elements.play_ui_sound("select_unit_filter")
            self.preview_intro_stage = 1
        if self.preview_intro_stage == 1 and elapsed >= opening_at:
            ui_elements.play_ui_sound("open_music")
            self.preview_intro_stage = 2
        if elapsed >= opening_at + PREVIEW_SLIDE_OUT_SECONDS:
            self.preview_intro_stage = None
            self.preview_intro_started = None

    def draw(self, surface):
        if self.preview_intro_stage is None:
            super().draw(surface)
            return
        if self.preview_intro_started is None:
            self.preview_intro_started = pygame.time.get_ticks()
            surface.fill((0, 0, 0))
            return
        elapsed = (pygame.time.get_ticks() - self.preview_intro_started) / 1000.0
        if self.preview_intro_stage == 2:
            # Reveal the roster preview only as the bars move apart.
            super().draw(surface)
            elapsed -= PREVIEW_SLIDE_IN_SECONDS + PREVIEW_HOLD_SECONDS
            shown = 1.0 - min(1.0, max(0.0, elapsed / PREVIEW_SLIDE_OUT_SECONDS))
        else:
            surface.fill((0, 0, 0))
            shown = min(1.0, max(0.0, elapsed / PREVIEW_SLIDE_IN_SECONDS))
        top_height = c.SCREEN_HEIGHT // 2
        bottom_height = c.SCREEN_HEIGHT - top_height
        bars = (
            pygame.Rect(0, -top_height + round(top_height * shown), c.SCREEN_WIDTH, top_height),
            pygame.Rect(0, c.SCREEN_HEIGHT - round(bottom_height * shown), c.SCREEN_WIDTH, bottom_height),
        )
        for rect in bars:
            ui_elements.draw_pixel_panel(surface, rect, PREVIEW_BAR_COLOR, PREVIEW_BAR_BORDER,
                                         gradient_strength=PREVIEW_BAR_GRADIENT_STRENGTH)

    def _card_key(self, side, unit):
        return (self.mode, side, unit["type"], unit["owner"], unit["health"], unit["max_health"])

    @staticmethod
    def _bar_geometry(top):
        """The health bar rect and the flag's x, in card coordinates; the flag sits right of the bar."""
        flag_x = CARD_SIZE[0] - CARD_ROW_INSET - CARD_BAR_FLAG_SIZE[0]
        bar = pygame.Rect(CARD_ROW_INSET, top,
                          flag_x - CARD_BAR_FLAG_GAP - CARD_ROW_INSET, CARD_BAR_HEIGHT)
        return bar, flag_x

    def _draw_health_bar(self, card, unit, top):
        bar, flag_x = self._bar_geometry(top)
        pygame.draw.rect(card, OUTLINE_COLOR, bar)
        ratio = max(0.0, min(1.0, unit["health"] / unit["max_health"]))
        fill = pygame.Rect(bar.x + 1, bar.y + 1, round((bar.width - 2) * ratio), bar.height - 2)
        if ratio >= 0.5:
            low, high, blend = HEALTH_BAR_HALF_COLOR, HEALTH_BAR_FULL_COLOR, (ratio - 0.5) * 2
        else:
            low, high, blend = HEALTH_BAR_EMPTY_COLOR, HEALTH_BAR_HALF_COLOR, ratio * 2
        base = [round(a + (b - a) * blend) for a, b in zip(low, high)]
        # Light, middle, and dark bands; a checkerboard of the neighboring shade softens each edge.
        shades = [tuple(max(0, min(255, channel + HEALTH_BAR_SHADE * (1 - band)))
                        for channel in base) for band in range(HEALTH_BAR_BANDS)]
        for row in range(fill.height):
            band = row * HEALTH_BAR_BANDS // fill.height
            first = band > 0 and (row - 1) * HEALTH_BAR_BANDS // fill.height < band
            last = band < HEALTH_BAR_BANDS - 1 and (row + 1) * HEALTH_BAR_BANDS // fill.height > band
            for column in range(fill.width):
                shade = band
                if (column + row) % 2 == 0:
                    shade += 1 if last else -1 if first else 0
                card.set_at((fill.x + column, fill.y + row), shades[shade])
        flag_icons.draw_flag(card, unit["owner"], self.country_data, flag_x,
                             bar.centery - CARD_BAR_FLAG_SIZE[1] // 2, size=CARD_BAR_FLAG_SIZE)

    def _cache_card(self, side, unit):
        key = self._card_key(side, unit)
        if key not in self.card_surfaces:
            width, height = CARD_SIZE
            card = pygame.Surface(CARD_SIZE)
            ui_elements.draw_pixel_panel(card, card.get_rect(), (46, 51, 65), (15, 19, 27))
            name = unit["type"]
            font = fonts.get("tiny")
            if self.mode == "preview":
                # Preview shows no unit name: a large icon, then a health bar with the flag to its right.
                icon = symbol_loader.get_symbol(name, zoom=1, color=TEAM_COLORS[side],
                                                country=unit["owner"], fit_size=PREVIEW_CARD_ICON_SIZE)
                if icon is not None:
                    card.blit(icon, icon.get_rect(center=(width // 2, PREVIEW_ICON_CENTER_Y)))
                self._draw_health_bar(card, unit, PREVIEW_BAR_TOP)
                stats_top = PREVIEW_STATS_TOP
            else:
                draw_unit_shape(card, combat.unit_shape(name, self.library), (width // 2, 28),
                                0 if side == 0 else math.pi, TEAM_COLORS[side], scale=1.4)
                label = queries.get_unit_display_name(name, self.library)
                line_height = font.get_height()
                for line_number, line in enumerate(wrap_text(label, font, width - 16)[:3]):
                    text = font.render(fit_text(line, font, width - 16), True, c.UI_TEXT_BRIGHT)
                    card.blit(text, text.get_rect(midtop=(width // 2, 52 + line_number * line_height)))
                self._draw_health_bar(card, unit, EDIT_BAR_TOP)
                stats_top = CARD_STATS_TOP
            attack = unit["attack"] * combat_rules.effective_damage_multiplier(unit)
            entries = [(icon, queries.format_number(value)) for icon, value in (
                (c.ICON_HEALTH, unit["health"]), (c.ICON_ATTACK, attack), (c.ICON_DEFENSE, unit["defense"]))]
            ui_elements.draw_wrapped_icon_row(
                card, font, entries, 6, stats_top, c.UI_TEXT_LIGHT,
                width - 12, icon_size=CARD_STAT_ICON_SIZE)
            self.card_surfaces[key] = card
        return self.card_surfaces[key]

    def _draw_rosters(self, surface):
        for side, top in enumerate(PANEL_TOPS):
            panel = pygame.Rect(PANEL_X, top, PANEL_WIDTH, PANEL_HEIGHT)
            ui_elements.draw_pixel_panel(surface, panel, (39, 44, 58), (15, 19, 27))
            surface.blit(self.roster_labels[side], (panel.x + ROSTER_INSET, panel.y + 14))
            old_clip = surface.get_clip()
            surface.set_clip(old_clip.clip(self.panes[side]))
            for index, unit in enumerate(self.rosters[side]):
                rect = self.card_rect(side, index)
                if not rect.colliderect(self.panes[side]):
                    continue
                if self.drag is not None and self.drag[0] == side and self.drag[1] == index and self.drag[3]:
                    continue
                surface.blit(self.card_surfaces[self._card_key(side, unit)], rect)
                if self.mode == "setup":
                    button = self.unit_buttons[side, index]
                    self._position_edit_button(button, rect)
                    button.draw(surface)
                if self.selected[side] == index or index in self.group[side]:
                    pygame.draw.rect(surface, TEAM_COLORS[side], rect, 2)
                if side == 0 and self.controlled_index == index:
                    draw_player_arrow(surface, (rect.centerx, rect.y + 28), 0)
            surface.set_clip(old_clip)
            self.draw_list_scrollbar(surface, self.panes[side].x, self.panes[side].bottom + 10,
                                     ROSTER_WIDTH, width=SCROLLBAR_HEIGHT, **self._scroll_options(side))
        if self.drag is not None and self.drag[3]:
            side, index, origin, active = self.drag
            card = self.card_surfaces[self._card_key(side, self.rosters[side][index])]
            rect = card.get_rect(center=pygame.mouse.get_pos())
            surface.blit(card, rect)
            button = self.unit_buttons[side, index]
            self._position_edit_button(button, rect)
            button.draw(surface)
            if side == 0 and self.controlled_index == index:
                draw_player_arrow(surface, (rect.centerx, rect.y + 28), 0)
        if self.marquee is not None:
            side, origin, current = self.marquee
            if math.dist(origin, current) >= DRAG_THRESHOLD:
                pygame.draw.rect(surface, TEAM_COLORS[side], self._marquee_rect(origin, current), 1)

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
            flag_icons.draw_flag(surface, fighter.data["owner"], self.country_data,
                                 bar.right + BATTLE_FLAG_GAP,
                                 bar.centery - BATTLE_FLAG_SIZE[1] // 2, size=BATTLE_FLAG_SIZE)
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


class CustomBattleUnitEditor(ModalScreen):
    """Edit one custom roster entry, or a selected group, with the country picker and an HP slider."""

    PANEL_SIZE = (460, 250)
    ROW_TOP = 70
    ROW_HEIGHT = 42
    ROW_GAP = 12
    DONE_SIZE = (100, 34)
    SLIDER_OFFSET = ROW_HEIGHT + ROW_GAP + 28
    DONE_GAP = 40

    def __init__(self, battle_screen, side, units):
        super().__init__(battle_screen, "Unit Settings" if len(units) == 1 else "Group Settings")
        self.battle_screen = battle_screen
        self.side = side
        self.units = units
        self.refresh_ui()

    def _health_percent(self, unit):
        return unit["health"] / unit["max_health"] * 100

    def refresh_ui(self):
        x = self.panel_rect.x + self.PAD
        y = self.panel_rect.y + self.ROW_TOP
        width = self.panel_rect.width - self.PAD * 2
        owners = {unit["owner"] for unit in self.units}
        percents = {round(self._health_percent(unit)) for unit in self.units}
        country = (queries.get_country_display_name(next(iter(owners)), self.battle_screen.country_data)
                   if len(owners) == 1 else MIXED_LABEL)
        health = f"{next(iter(percents))}%" if len(percents) == 1 else MIXED_LABEL
        buttons = [
            Button(x, y, (width, self.ROW_HEIGHT), "grey", f"Nationality: {country}",
                   self.choose_country, font_size=18),
            Button(self.panel_rect.centerx - self.DONE_SIZE[0] // 2,
                   y + self.SLIDER_OFFSET + self.DONE_GAP, self.DONE_SIZE, "blue", "Done",
                   self.exit_screen, font_size=18, sound_kind="back"),
        ]
        for button in buttons:
            button.fit_text = True
            button.fit_single_line = True
        # The label is drawn above the track, so the slider sits below that label's room.
        self.hp_slider = Slider(x, y + self.SLIDER_OFFSET, width, f"Starting HP: {health}",
                                self._health_percent(self.units[0]), self.set_percent,
                                visual_max=100, allowed_max=100)
        self.elements = [buttons[0], self.hp_slider, buttons[1]]

    def set_percent(self, value):
        percent = max(1, round(value))
        if self.battle_screen.set_unit_options(self.side, self.units, health_percent=percent):
            # Keep the dragged slider alive instead of rebuilding the controls.
            self.hp_slider.text = f"Starting HP: {percent}%"

    def _set_options(self, **options):
        if self.battle_screen.set_unit_options(self.side, self.units, **options):
            self.refresh_ui()

    def choose_country(self):
        pickers.open_listbox_selector(
            self, "Nationality", "",
            queries.country_picker_items(self.battle_screen.nationalities, self.battle_screen.country_data),
            lambda country: self._set_options(owner=country))
