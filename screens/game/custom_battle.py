"""Edit Battle, read-only Preview Battle, and optional player-controlled combat."""

from collections import deque
from itertools import islice
import math
import random

import pygame

from data import queries
from data.io import starting_defaults
from map_logic import battle_terrain
from map_logic import custom_battle as combat
from map_logic import naval_battle as naval
from map_logic import tactical_campaign
from map_logic import tactical_rules as rules
from screens.game import custom_battle_layout as layout
from screens.game import custom_battle_sprites as sprites
from screens.game.custom_battle_editor import CustomBattleUnitEditor
from screens.setup import player_setup
from ui import dialogs
from ui import sound_effects
from ui.dialogs import pickers
from ui.navigation import screen_runner
from ui.navigation.screen import Screen
from ui.rendering import symbol_loader
from ui.rendering.font_manager import fonts
from ui.widgets import flag_icons
from ui.widgets import ui_elements
from ui.widgets.ui_elements import Button, Slider
import data.constants as c
from screens.game.custom_battle_camera import BattleCamera
from screens.game.custom_battle_render import BattleRender
from screens.game.custom_battle_roster import RosterCards
from screens.game.custom_battle_touch import TouchControls


class CampaignBattle:
    """The tactical-mode encounter a battle belongs to. The player's unit starts as friendly entry 0.

    Reordering the friendly army in preview reorders ``units`` the same way.
    """

    def __init__(self, map_screen, province, units, custom_rosters, custom_columns):
        self.map_screen = map_screen
        self.province = province
        self.units = units  # The campaign units in roster order: friendly army, then enemy army.
        self.unit = units[0]
        self.result_applied = False
        self.custom_rosters = custom_rosters  # The custom-battle armies and their columns to restore afterward.
        self.custom_columns = custom_columns


class CustomBattleScreen(TouchControls, BattleCamera, RosterCards, BattleRender, Screen):
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
        self.terrain = starting_defaults.get_starting_value("random_setup", "custom_battle_terrain")
        self.terrain_art = []
        self.canopy_art = []  # (tree, transparent foliage surface), drawn above units.
        self.terrain_art_key = None
        self.visibility_key = None
        self.visibility_outline = ()
        self.visibility_blockers = ()
        self.visibility_mask_key = None
        self.visibility_mask = None
        self.foliage_shadow_outline = ()
        self.foliage_shadow_mask = None
        self.visible_fighters = set()
        self.terrain_sprites = {}
        self.battle_seed = None
        self.random_candidates = []
        self.rosters = [[], []]
        # Each roster entry's column, in roster order (see tactical_campaign.valid_columns). Every roster change goes through _set_columns.
        self.columns = [[], []]
        self.selected = [None, None]
        # Roster indices chosen by a selection square; two or more entries per side.
        self.group = [[], []]
        self.campaign = None  # A CampaignBattle while a tactical-mode encounter is shown.
        self.choosing_retreat = False
        self.viewing_overlay = False  # Settings or Music is open over preview, battle, or results.
        self.bar_drag = None  # (side, index) of the card whose health bar is being dragged
        self.marquee = None  # [side, start position, current position] while dragging a square
        self.controlled_index = None
        self.held_keys = set()
        self.firing = False  # Left mouse held on the battlefield while controlling a sub-unit.
        self.secondary_firing = False
        self.touch_mode = False
        self.touch_pointers = {}  # pointer -> (drive/aim, last position)
        self.touch_weapon_mode = "Primary"
        self.touch_weapon_buttons = []
        self.camera = [0.0, 0.0]  # Battlefield coordinates at the screen's top-left corner.
        self.zoom_index = layout.DEFAULT_ZOOM_INDEX
        self.pan_drag = None  # Last pointer position while dragging the battlefield.
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
        self.kill_feed = deque()
        # Explosion animations: the sub-unit, the animation age in seconds, its palette, and the battlefield point it grows from.
        # A destroyed vehicle or ship explodes from its center in DEATH_EXPLOSION_PALETTE;
        # a torpedo hit splashes from the point the torpedo struck in TORPEDO_SPLASH_PALETTE.
        self.death_explosions = []
        self.death_explosion_circle = None
        self.kill_feed_surface = None
        self.kill_feed_pane.value = self.kill_feed_pane.limit = 0
        self.kill_feed_pane.bar_drag = False
        self.kill_feed_pane.track = self.kill_feed_pane.handle = None
        self.kill_feed_rect = pygame.Rect(c.SCREEN_WIDTH - layout.SCREEN_EDGE_MARGIN - layout.KILL_FEED_WIDTH,
                                          layout.KILL_FEED_TOP, layout.KILL_FEED_WIDTH, layout.KILL_FEED_HEIGHT)
        self.kill_feed_pane.content_rect = self.kill_feed_rect.inflate(-2 * layout.KILL_FEED_INSET, -2 * layout.KILL_FEED_INSET)
        self.kill_feed_pane.content_rect.width -= layout.KILL_FEED_SCROLLBAR_WIDTH + layout.KILL_FEED_SCROLLBAR_GAP
        self.controlled_stats_key = None
        self.controlled_stats_surface = None
        self.forecast_key = None  # The armies the forecast line was calculated for.
        self.forecast_surface = None
        for side, top in enumerate(layout.PANEL_TOPS):
            self.panes.append(pygame.Rect(layout.PANEL_X + layout.ROSTER_INSET, top + layout.ROSTER_TOP,
                                          layout.ROSTER_WIDTH, layout.ROSTER_HEIGHT))
            self._roster_scroll(side).value = 0
            self._roster_scroll(side).limit = 0
            self._roster_scroll(side).content_rect = self.panes[side]
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
            self.start_tactical_music()
            return
        if self.viewing_overlay:
            # Back from Settings or Music: preserve the current music, view, and simulation.
            # Only the clock restarts, so no combat time passes while the screen was open.
            self.viewing_overlay = False
            self.done = False
            self.next_state = None
            self.last_tick = pygame.time.get_ticks()
            self.refresh_ui()  # The Pause button must read Resume if opening the screen paused the battle.
            return
        if self.campaign is not None:
            self._end_campaign()
        self.stop_tactical_music()
        self.done = False
        self.next_state = None
        self.mode = "setup"
        self.preview_intro_started = None
        self.preview_intro_stage = None
        # Main-menu battles use the default library, never a loaded world's overrides.
        self.library = queries.get_unit_library()
        self.country_data = queries.get_country_data()
        self.gear_icon = symbol_loader.get_symbol(
            "Gear", zoom=1, fit_size=(layout.CARD_EDIT_SIZE - 2 * layout.CARD_EDIT_ICON_PAD, layout.CARD_EDIT_SIZE - 2 * layout.CARD_EDIT_ICON_PAD))
        self.nationalities = sorted(
            (country for country in self.country_data if queries.is_playable(country, self.country_data)),
            key=lambda country: queries.get_country_display_name(country, self.country_data))
        if not self.nationalities:
            raise ValueError("Custom battles need at least one playable country in countries_data.json.")
        self.unit_names = sorted(rules.custom_unit_types(self.library), key=lambda name: (
            queries.get_unit_metadata(name, self.library)["family"],
            queries.get_unit_tier(name, self.library)))
        allowed = set(self.unit_names)
        self.selected = [None, None]
        self.group = [[], []]
        self.controlled_index = None
        for side in (0, 1):
            self._set_columns(side, [[unit for unit in group if rules.battle_unit_type(unit["type"], self.library) in allowed]
                                     for group in self._column_groups(side)])
        self.held_keys.clear()
        self.card_surfaces.clear()
        self.simulation = None
        self.cancel_active_drags()
        self.random_candidates = tactical_campaign.custom_unit_types_for_year(self.library, self.generation_year, self.terrain)
        self.refresh_ui()

    def _enter_campaign(self, map_screen, province, friendly, enemy):
        """Open preview at once for a tactical player's encounter, controlling their unit."""
        self.done = False
        self.next_state = None
        self.campaign = CampaignBattle(map_screen, province, friendly + enemy, self.rosters, self.columns)
        self.library = queries.get_unit_library(map_screen)
        self.country_data = map_screen.world.nation_data
        turn, frozen_supply = getattr(map_screen, "tactical_combat_supply", (None, None))
        if turn != map_screen.world.time_manager.total_turns:
            frozen_supply = queries.SupplySnapshot(map_screen)
        with queries.combat_supply(frozen_supply):
            self.rosters = [tactical_campaign.campaign_roster(side, self.library, province.get("terrain")) for side in (friendly, enemy)]
        self.columns = [tactical_campaign.paired_columns(len(roster)) for roster in self.rosters]
        self.selected = [None, None]
        self.group = [[], []]
        self.controlled_index = 0
        self.held_keys.clear()
        self.card_surfaces.clear()
        self.simulation = None
        self.mode = "setup"
        self.cancel_active_drags()
        for side in (0, 1):
            self._roster_scroll(side).value = 0
        self.preview_battle()

    def _end_campaign(self):
        self.rosters = self.campaign.custom_rosters
        self.columns = self.campaign.custom_columns
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

    def open_overlay(self, state):
        """Open Settings or Music over preview, battle, or results; Back returns to the same view."""
        if self.mode not in {"preview", "battle", "result"} or self.preview_intro_stage is not None:
            return
        self.cancel_active_drags()
        self.clear_controls()
        if self.mode == "battle":
            self.simulation.paused = True  # Stays paused after Back until the player chooses Resume.
        self.viewing_overlay = True
        self.go_to(state)

    def finish_retreat(self):
        """The retreat order is given: the encounter is over."""
        self._end_campaign()

    def _apply_campaign_result(self):
        """A finished tactical encounter changes the campaign: damage stays and the dead are gone."""
        campaign = self.campaign
        if campaign is None or campaign.result_applied:
            return
        campaign.result_applied = True
        artillery = tactical_campaign.campaign_artillery(campaign.unit, campaign.province,
                                              campaign.map_screen.world.nation_data, self.library)
        sides = tactical_campaign.campaign_sides(campaign.unit, campaign.province, campaign.map_screen.world.nation_data)
        tactical_campaign.apply_campaign_result(self.simulation, campaign.units, campaign.province, artillery, side_units=sides, player_unit=campaign.unit)
        player_setup.settle_tactical_tile(campaign.map_screen, campaign.province)

    def continue_campaign(self):
        """Leave the finished encounter. A destroyed tactical division sends the player to spectating."""
        if self.mode != "result" or self.campaign is None:
            return
        campaign = self.campaign
        died = campaign.unit["health"] <= 0
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

    def show_help(self):
        if self.mode not in {"setup", "preview"} or self.preview_intro_stage is not None:
            return
        self.cancel_active_drags()
        text = layout.EDIT_BATTLE_HELP_TEXT if self.mode == "setup" else layout.PREVIEW_BATTLE_HELP_TEXT + (layout.PREVIEW_CAMPAIGN_HELP_TEXT if self.campaign is not None else layout.PREVIEW_CUSTOM_HELP_TEXT)
        dialogs.show_info(f"{self.get_title()} Help", text)

    @property
    def reserved_keys(self):
        if (self.preview_intro_stage is None and self.mode in {"preview", "battle"}
                and self.simulation.controlled is not None):
            return layout.CONTROL_KEYS
        return ()

    def _roster_scroll(self, side):
        """The horizontal pane of one side's roster cards."""
        return self.scroll_state(f"roster_{side}", "x")

    @property
    def kill_feed_pane(self):
        return self.scroll_state("kill_feed")

    def refresh_ui(self):
        self.unit_buttons = {}
        self.elements = []
        self.help_button = None
        if self.mode in {"setup", "preview"}:
            title_width, title_height = fonts.get(self.title_preset).size(self.get_title())
            self.help_button = ui_elements.make_info_button(0, 0, self.show_help)
            self.help_button.rect.midleft = (c.SCREEN_WIDTH // 2 + title_width - title_width // 2 + layout.TITLE_HELP_GAP, self.title_y + title_height // 2)
            self.elements.append(self.help_button)
        self.battle_artwork = {}
        for name in dict.fromkeys(unit["type"] for roster in self.rosters for unit in roster):
            family = queries.get_unit_metadata(name, self.library)["family"]
            shape = rules.unit_shape(name, self.library)
            artwork = (naval.ARTWORK[shape] if shape in naval.SHAPES else layout.BATTLE_ART_FAMILIES["Motorized Infantry Type"] if rules.packed_ship_type(name, self.library)
                       else layout.BATTLE_ART_FAMILIES.get(family))
            self.battle_artwork[name] = artwork
            if artwork is not None:
                sprites.load_battle_art(artwork)
        if self.mode == "setup" or (self.mode in {"battle", "result"} and self.campaign is None):
            self.elements.append(Button(20, 20, "small", "red", "Exit", self.leave,
                                        sound_kind="back"))
        if self.mode in {"preview", "battle", "result"}:
            # Battle and results keep the same Pause, Settings, and Music positions.
            right = c.SCREEN_WIDTH - layout.SCREEN_EDGE_MARGIN
            if self.mode in {"battle", "result"}:
                right -= layout.PAUSE_BUTTON_SIZE[0] + layout.OVERLAY_BUTTON_GAP
            for symbol, state, color, sound in (("Music", "MUSIC_PLAYER", "blue", "open_music"),
                                                ("Gear", "SETTINGS", "grey", "open_settings")):
                right -= layout.OVERLAY_BUTTON_SIZE[0]
                icon = symbol_loader.get_symbol(symbol, zoom=1, fit_size=layout.OVERLAY_ICON_SIZE)
                self.elements.append(Button(right, layout.OVERLAY_BUTTON_TOP, layout.OVERLAY_BUTTON_SIZE, color, "",
                                            lambda state=state: self.open_overlay(state),
                                            image=icon, show_text=False, sound_kind=sound))
                right -= layout.OVERLAY_BUTTON_GAP
        if self.mode in {"battle", "result"}:
            self.pause_button = Button(c.SCREEN_WIDTH - layout.SCREEN_EDGE_MARGIN - layout.PAUSE_BUTTON_SIZE[0], layout.OVERLAY_BUTTON_TOP,
                                       layout.PAUSE_BUTTON_SIZE, "yellow",
                                       "Resume" if self.mode == "battle" and self.simulation.paused else "Pause",
                                       self.toggle_pause)
            self.pause_button.apply_state(enabled=self.mode == "battle", color="yellow")
            self.elements.append(self.pause_button)
        if self.mode in {"setup", "preview"}:
            self.roster_labels = []
            for side, top in enumerate(layout.PANEL_TOPS):
                roster = self.rosters[side]
                name = "Friendly Units" if side == 0 else "Enemy Units"
                self.roster_labels.append(fonts.get("heading2").render(
                    f"{name} ({len(roster)})", True, layout.TEAM_COLORS[side]))
                for index, unit in enumerate(roster):
                    self._cache_card(side, unit)
                    if self.mode == "setup":
                        self.unit_buttons[side, index] = Button(
                            0, 0, (layout.CARD_EDIT_SIZE, layout.CARD_EDIT_SIZE), "grey", "",
                            lambda side=side, unit=unit: self.edit_unit(side, unit),
                            image=self.gear_icon, show_text=False,
                            sound_kind="open_settings")
                column_count = self.columns[side][-1] + 1 if roster else 0
                limit = min(0, layout.ROSTER_WIDTH - column_count * (layout.CARD_SIZE[0] + layout.CARD_GAP) + layout.CARD_GAP)
                self._roster_scroll(side).limit = limit
                offset = max(limit, min(0, self._roster_scroll(side).value))
                self._roster_scroll(side).value = offset
                if self.mode == "preview":
                    continue
                x = layout.PANEL_X + layout.PANEL_WIDTH - layout.BUTTON_WIDTH - layout.ROSTER_INSET
                clear = Button(x, top + layout.CLEAR_ALL_OFFSET_Y, (layout.BUTTON_WIDTH, layout.CLEAR_ALL_HEIGHT), "red", "Clear All", lambda side=side: self.clear_army(side), font_size=18)
                clear.apply_state(enabled=bool(roster), color="red")
                add = Button(x, top + 70, (layout.BUTTON_WIDTH, 42), "blue" if side == 0 else "red",
                             "Add Friendly" if side == 0 else "Add Enemy",
                             lambda side=side: self.open_picker(side), font_size=20)
                add.apply_state(enabled=self._roster_has_space(side),
                                color="blue" if side == 0 else "red")
                duplicate = Button(x - layout.BUTTON_WIDTH - layout.CARD_GAP, top + layout.CLEAR_ALL_OFFSET_Y, (layout.BUTTON_WIDTH, layout.CLEAR_ALL_HEIGHT), "grey", "Duplicate", lambda side=side: self.duplicate_unit(side), font_size=18)
                duplicate.apply_state(enabled=self.selected[side] is not None and self._roster_has_space(side), color="blue" if side == 0 else "red")
                remove = Button(x, top + 128, (layout.BUTTON_WIDTH, 42), "grey", "Remove",
                                lambda side=side: self.remove_unit(side), font_size=20)
                remove.apply_state(enabled=self.selected[side] is not None, color="red")
                self.elements.extend((clear, add, remove, duplicate))
                if side == 0:
                    controlling = self.controlled_index is not None and self.controlled_index == self.selected[0]
                    control = Button(x, top + 178, (layout.BUTTON_WIDTH, 32), "yellow",
                                     "Release Control" if controlling else "Control",
                                     self.toggle_control, font_size=18)
                    control.apply_state(enabled=self.selected[0] is not None,
                                        color="yellow" if controlling else "green")
                    self.elements.append(control)
            if self.mode == "preview":
                start = Button(*layout.PREVIEW_START_POSITION, layout.PREVIEW_START_SIZE,
                               "green", "Start", self.start_battle)
                retreat = Button(start.rect.right + layout.PREVIEW_RETREAT_GAP, start.rect.y,
                                 layout.PREVIEW_RETREAT_SIZE, "red", "Retreat", self.retreat,
                                 sound_kind="back")
                self.elements.extend((start, retreat))
                return
            self._refresh_forecast()
            simulate = Button(*layout.SIMULATE_BUTTON_POSITION, layout.SIMULATE_BUTTON_SIZE, "green", "Simulate",
                              self.preview_battle, font_size=18, sound_kind=None)
            simulate.apply_state(enabled=all(self.rosters), color="green")
            self.elements.append(simulate)
            self.generate_button = Button(
                *layout.GENERATION_BUTTON_POSITION, layout.GENERATION_BUTTON_SIZE, "purple", "Random",
                self.generate_armies, font_size=20)
            self.generate_button.apply_state(enabled=bool(self.random_candidates), color="purple")
            self.year_slider = Slider(
                *layout.GENERATION_SLIDER_POSITION, layout.GENERATION_SLIDER_WIDTH,
                f"Year: {self.generation_year}", self.generation_year - c.START_YEAR,
                self.update_generation_year, visual_max=c.END_YEAR - c.START_YEAR,
                allowed_max=c.END_YEAR - c.START_YEAR)
            self.elements.extend((self.generate_button, self.year_slider))
            self.elements.append(Button(*layout.TERRAIN_BUTTON_POSITION, layout.TERRAIN_BUTTON_SIZE, "grey",
                                        battle_terrain.TERRAIN_NAMES[self.terrain], self.choose_terrain,
                                        font_size=20))
        elif self.mode == "battle":
            self.touch_weapon_buttons = []
            if self.touch_mode and self.simulation.controlled is not None and self.simulation.controlled.alive and self.simulation.controlled.weapon(1) is not None:
                width, height = layout.TOUCH_WEAPON_SIZE
                left = c.SCREEN_WIDTH - layout.TOUCH_PAD_MARGIN - (width * 3 + layout.TOUCH_WEAPON_GAP * 2)
                top = self._touch_pad_rect("aim").top - height - layout.TOUCH_WEAPON_GAP
                for index, mode in enumerate(layout.TOUCH_WEAPON_MODES):
                    button = Button(left + index * (width + layout.TOUCH_WEAPON_GAP), top, layout.TOUCH_WEAPON_SIZE,
                                    "yellow" if mode == self.touch_weapon_mode else "grey", mode,
                                    lambda mode=mode: self._select_touch_weapon(mode), font_size=16)
                    button.apply_state(enabled=self._driving(),
                                       color="yellow" if mode == self.touch_weapon_mode else "grey")
                    self.touch_weapon_buttons.append(button)
                    self.elements.append(button)
        elif self.campaign is not None:
            self.elements.append(Button("centered", 370, (220, 50), "green", "Continue",
                                        self.continue_campaign))
        else:
            self.elements.extend((
                Button("centered", 370, (220, 50), "green", "Run Again", self.preview_battle,
                       sound_kind=None),
                Button("centered", 440, (220, 50), "blue", "Edit Armies", self.return_to_setup)))

    def _refresh_forecast(self):
        """Forecast how the armies would fare in the normal game, only when their types, order, or health change."""
        key = self.terrain, tuple(tuple((unit["type"], unit["health"]) for unit in roster) for roster in self.rosters)
        if key == self.forecast_key:
            return
        self.forecast_key = key
        if not all(self.rosters):
            self.forecast_surface = None
            return
        winner, turns = tactical_campaign.normal_game_forecast(*self.rosters)
        if turns is None:
            text, color = "Normal game: no clear winner", c.UI_TEXT_MUTED
        else:
            span = f"{turns} turn" if turns == 1 else f"{turns} turns"
            if winner is None:
                text, color = f"Normal game: both armies destroyed in {span}", c.UI_TEXT_MUTED
            else:
                army = "Friendly" if winner == 0 else "Enemy"
                text, color = f"Normal game: {army} army wins in {span}", layout.TEAM_COLORS[winner]
        self.forecast_surface = fonts.get("normal").render(text, True, color)

    def update_generation_year(self, value):
        if self.mode != "setup":
            return
        year = max(c.START_YEAR, min(c.END_YEAR, c.START_YEAR + round(value)))
        if year != self.generation_year:
            self.generation_year = year
            self.random_candidates = tactical_campaign.custom_unit_types_for_year(self.library, year, self.terrain)
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
                        for side, roster in enumerate(tactical_campaign.random_armies(self.random_candidates))]
        self.columns = [tactical_campaign.paired_columns(len(roster)) for roster in self.rosters]
        self.selected = [None, None]
        self.group = [[], []]
        self.controlled_index = None
        for side in (0, 1):
            self._roster_scroll(side).value = 0
        self.refresh_ui()

    def open_picker(self, side):
        if self.mode != "setup":
            return
        self.cancel_active_drags()
        pickers.open_listbox_selector(
            self, "Add Friendly Units" if side == 0 else "Add Enemy Units", "",
            queries.unit_picker_items(self.unit_names, self.library),
            lambda name: self.add_unit(side, name), close_on_select=False, background_draw=self.draw,
            is_enabled=lambda item: self._roster_has_space(side))

    def choose_terrain(self):
        if self.mode != "setup" or self.campaign is not None:
            return
        self.cancel_active_drags()
        pickers.open_listbox_selector(self, "Battle Terrain", "",
                                     [(label, key) for key, label in battle_terrain.TERRAIN_NAMES.items()],
                                     self.set_terrain)

    def set_terrain(self, terrain):
        if self.mode != "setup" or self.campaign is not None or terrain not in battle_terrain.TERRAIN_NAMES:
            return
        self.cancel_active_drags()
        for roster in self.rosters:
            for entry in roster:
                prepared = rules.prepare_battle_unit(entry, self.library, terrain)
                entry.clear()
                entry.update(prepared)
        self.terrain = terrain
        self.random_candidates = tactical_campaign.custom_unit_types_for_year(self.library, self.generation_year, terrain)
        self.card_surfaces.clear()
        self.forecast_key = None
        self.refresh_ui()

    def _roster_has_space(self, side):
        return len(self.rosters[side]) < c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE

    def _column_groups(self, side):
        return tactical_campaign.column_groups(self.rosters[side], self.columns[side])

    def _set_columns(self, side, groups):
        """Replace one army with ``groups``: columns front to back, each listing its cards top to bottom.

        Empty columns close up, and control stays with the same friendly entry.
        """
        controlled = self.rosters[0][self.controlled_index] if self.controlled_index is not None else None
        self.rosters[side][:], self.columns[side][:] = tactical_campaign.flatten_columns(groups)
        if controlled is not None:
            self.controlled_index = self._index_of(0, controlled)

    def _index_of(self, side, unit):
        return next((index for index, entry in enumerate(self.rosters[side]) if entry is unit), None)

    def _place_new_unit(self, side, unit):
        """Add a unit to the column tactical_campaign.open_column chooses, select it, and scroll its column into view."""
        groups = self._column_groups(side)
        column = tactical_campaign.open_column(groups)
        if column is None:
            return
        if column == len(groups):
            groups.append([])
        groups[column].append(unit)
        self._set_columns(side, groups)
        self.selected[side] = self._index_of(side, unit)
        self.refresh_ui()
        roster = self._roster_scroll(side)
        roster.value = max(roster.limit, min(0, layout.ROSTER_WIDTH - (column + 1) * (layout.CARD_SIZE[0] + layout.CARD_GAP) + layout.CARD_GAP))

    def add_unit(self, side, name):
        if self.mode != "setup" or name not in self.unit_names:
            return
        if not self._roster_has_space(side):
            return
        self._place_new_unit(side, self._new_unit(side, name))

    def _new_unit(self, side, name, country=None):
        if country is None:
            country = self.nationalities[min(side, len(self.nationalities) - 1)]
        return rules.create_battle_unit(name, country, self.library, self.terrain)

    def duplicate_unit(self, side):
        if self.mode != "setup" or self.campaign is not None or side not in (0, 1):
            return
        index = self.selected[side]
        if index is None or not 0 <= index < len(self.rosters[side]) or not self._roster_has_space(side):
            return
        self.cancel_active_drags()
        original = self.rosters[side][index]
        duplicate = self._new_unit(side, original["type"], original["owner"])
        duplicate["health"] = original["health"]
        self.group[side] = []
        self._place_new_unit(side, duplicate)

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
        removed = self.rosters[side][index]
        self._set_columns(side, [[entry for entry in group if entry is not removed] for group in self._column_groups(side)])
        self.group[side] = []
        self.selected[side] = min(index, len(self.rosters[side]) - 1) if self.rosters[side] else None
        self.refresh_ui()

    def clear_army(self, side):
        if self.mode != "setup" or side not in (0, 1):
            return
        self.cancel_active_drags()
        self._set_columns(side, [])
        self.selected[side] = None
        self.group[side] = []
        if side == 0:
            self.controlled_index = None
        self._roster_scroll(side).value = 0
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
        self._clear_roster_selection()
        self.battle_seed = random.getrandbits(64)
        self._build_simulation()
        self.clear_controls()
        self.mode = "preview"
        # Start the clock on the first draw so entry always includes a black frame.
        self.preview_intro_started = None
        self.preview_intro_stage = 0
        sound_effects.play_ui_sound("open_music")
        self.start_tactical_music()
        self.status_key = None
        self._refresh_status()
        self.refresh_ui()

    def start_tactical_music(self):
        """Play the tactical songs for the prepared battle: tank songs when the enemy has a tank."""
        if self.controller is not None:
            self.controller.set_tactical_battle_music(True, tanks=self.simulation.enemy_has_tanks())

    def stop_tactical_music(self):
        """Return to normal playlist music at full volume."""
        if self.controller is not None:
            self.controller.set_tactical_battle_music(False)
            self.controller.set_music_volume_scale(1.0)

    def zoom_volume_share(self):
        """Full volume at the default zoom and closer; zooming out lowers it in proportion to the zoom."""
        return min(1.0, self.zoom / layout.ZOOM_LEVELS[layout.DEFAULT_ZOOM_INDEX])

    def sound_listener(self):
        """Where battle sounds are heard from: the living controlled unit, otherwise the screen's center."""
        controlled = self.simulation.controlled
        if controlled is not None and controlled.alive:
            return controlled.x, controlled.y
        return self.to_field(self.view_rect().center)

    def distance_volume_share(self, fighter):
        """Full volume near the sound listener, fading linearly to SFX_DISTANCE_FLOOR farther away."""
        distance = math.dist(self.sound_listener(), (fighter.x, fighter.y)) / self.simulation.arena_size[0]
        fade = max(0.0, min(1.0, (distance - layout.SFX_FULL_VOLUME_DISTANCE) / (layout.SFX_FLOOR_DISTANCE - layout.SFX_FULL_VOLUME_DISTANCE)))
        return 1.0 - fade * (1.0 - layout.SFX_DISTANCE_FLOOR)

    def battle_sfx_volume_share(self, fighter):
        """Apply the editable battle SFX multiplier, the shared zoom reduction, and the sound's distance from the listener."""
        return layout.BATTLE_SFX_VOLUME * self.zoom_volume_share() * self.distance_volume_share(fighter)

    def update_battle_music_volume(self):
        """Lower music in actual battle: BATTLE_MUSIC_VOLUME, then quieter the further the view zooms out."""
        if self.controller is not None and self.mode == "battle":
            self.controller.set_music_volume_scale(layout.BATTLE_MUSIC_VOLUME * self.zoom_volume_share())

    def _build_simulation(self):
        """Deploy the armies, paused, as preview shows them."""
        self.kill_feed.clear()
        self.death_explosions.clear()
        self.kill_feed_pane.value = 0
        self.kill_feed_pane.bar_drag = False
        self._refresh_kill_feed()
        self.simulation = combat.BattleSimulation(self.library, *self.rosters,
                                                  friendly_columns=self.columns[0], enemy_columns=self.columns[1],
                                                  controlled_index=self.controlled_index,
                                                  seed=self.battle_seed,
                                                  terrain=self.campaign.province["terrain"] if self.campaign else self.terrain,
                                                  on_shot=self._play_shot_sound,
                                                  on_hit=self._play_hit_sound,
                                                  on_kill=self._record_kill)
        self.simulation.paused = True
        self.terrain_sprites.clear()
        self._cache_terrain_art()

    def _record_kill(self, source, target, cause):
        """Update the recent kills when a battlefield sub-unit dies."""
        if target.shape not in rules.FOOT_SHAPES:
            self.death_explosions.append((target, 0.0, layout.DEATH_EXPLOSION_PALETTE, (target.x, target.y)))
            sound_effects.play_ui_sound("tank_explosion", volume_scale=self.battle_sfx_volume_share(target))
        if self.kill_feed_pane.value < 0:
            self.kill_feed_pane.value -= layout.KILL_FEED_ROW_HEIGHT
        self.kill_feed.appendleft((source, target, cause))
        self._refresh_kill_feed()

    def _refresh_kill_feed(self):
        """Cache the fixed-size panel, including when no kills have occurred."""
        view_height = self.kill_feed_pane.content_rect.height
        self.kill_feed_pane.limit = min(0, view_height - len(self.kill_feed) * layout.KILL_FEED_ROW_HEIGHT)
        self.kill_feed_pane.value = max(self.kill_feed_pane.limit, min(0, self.kill_feed_pane.value))
        panel = pygame.Surface((layout.KILL_FEED_WIDTH, layout.KILL_FEED_HEIGHT), pygame.SRCALPHA)
        ui_elements.draw_pixel_panel(panel, panel.get_rect(), layout.CONTROL_STATS_COLOR, layout.CONTROL_STATS_BORDER)
        content = self.kill_feed_pane.content_rect.move(-self.kill_feed_rect.x, -self.kill_feed_rect.y)
        panel.set_clip(content)
        actor_width = layout.KILL_FEED_ACTOR_WIDTH
        font = fonts.get("tiny")
        # Scrollbar positions can be fractional; deque slicing needs an integer row index.
        first = math.floor(-self.kill_feed_pane.value / layout.KILL_FEED_ROW_HEIGHT)
        visible = islice(self.kill_feed, first, first + layout.KILL_FEED_VISIBLE_ROWS + 1)
        controlled = self.simulation.controlled if self.simulation is not None else None
        for row, (killer, victim, kind) in enumerate(visible, first):
            top = layout.KILL_FEED_INSET + row * layout.KILL_FEED_ROW_HEIGHT + self.kill_feed_pane.value
            for index, fighter in enumerate((killer, victim)):
                x = layout.KILL_FEED_INSET + index * (actor_width + layout.KILL_FEED_CAUSE_WIDTH)
                x = flag_icons.draw_flag_centered(panel, fighter.data["owner"], self.country_data,
                                                  x, top, layout.KILL_FEED_ROW_HEIGHT, layout.KILL_FEED_FLAG_SIZE)
                center = (x + layout.KILL_FEED_ICON_SIZE[0] // 2, top + layout.KILL_FEED_ROW_HEIGHT // 2)
                if controlled is not None and fighter.division == controlled.division:
                    color = layout.PLAYER_COLOR if fighter is controlled else layout.KILL_FEED_DIVISION_COLOR
                    highlight = pygame.Rect(0, 0, layout.KILL_FEED_ICON_SIZE[1], layout.KILL_FEED_ICON_SIZE[1])
                    highlight.center = center
                    pygame.draw.rect(panel, color, highlight)
                artwork = symbol_loader.get_symbol(fighter.data["type"], zoom=1,
                                                    color=layout.TEAM_COLORS[fighter.side], country=fighter.data["owner"],
                                                    fit_size=layout.KILL_FEED_ICON_SIZE)
                if artwork is not None:
                    panel.blit(artwork, artwork.get_rect(center=center))
            center = (layout.KILL_FEED_INSET + actor_width + layout.KILL_FEED_CAUSE_WIDTH // 2,
                      top + layout.KILL_FEED_ROW_HEIGHT // 2)
            if kind == "ram":
                text = font.render("RAM", True, c.UI_TEXT_BRIGHT)
                panel.blit(text, text.get_rect(center=center))
            else:
                # A code-drawn arrow remains readable without relying on font glyphs.
                pygame.draw.line(panel, c.UI_TEXT_BRIGHT, (center[0] - 8, center[1]), (center[0] + 8, center[1]), 2)
                pygame.draw.polygon(panel, c.UI_TEXT_BRIGHT,
                                    [(center[0] + 8, center[1]), (center[0] + 2, center[1] - 4),
                                     (center[0] + 2, center[1] + 4)])
        panel.set_clip(None)
        self.draw_list_scrollbar(panel, layout.KILL_FEED_WIDTH - layout.KILL_FEED_INSET - layout.KILL_FEED_SCROLLBAR_WIDTH,
                                 layout.KILL_FEED_INSET, view_height, width=layout.KILL_FEED_SCROLLBAR_WIDTH,
                                 scroll=self.kill_feed_pane)
        for rect in (self.kill_feed_pane.track, self.kill_feed_pane.handle):
            if rect is not None:
                rect.move_ip(self.kill_feed_rect.topleft)
        self.kill_feed_surface = panel

    def _kill_feed_events(self, event):
        """Scroll the feed without steering, firing, panning, or zooming the battlefield."""
        if event.type not in {pygame.MOUSEWHEEL, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION}:
            return False
        position = getattr(event, "pos", pygame.mouse.get_pos())
        engaged = (self.kill_feed_rect.collidepoint(position) or self.kill_feed_pane.bar_drag
                   or self.is_content_dragging(self.kill_feed_pane))
        if not engaged:
            return False
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.firing = False
                self.pan_drag = None
            elif event.button == 3:
                self.secondary_firing = False
        before = self.kill_feed_pane.value
        self.handle_list_scroll(event, self.kill_feed_pane, speed=layout.KILL_FEED_ROW_HEIGHT, content=True)
        if before != self.kill_feed_pane.value:
            self._refresh_kill_feed()
        return True

    def _play_shot_sound(self, fighter):
        # Keep audio randomness separate from the seeded simulation's aiming and movement decisions.
        if fighter.weapon(fighter.fired_weapon).get("projectile") == "torpedo":
            kind = "torpedo_launch"
        elif fighter.weapon(fighter.fired_weapon)["shell"]:
            kind = random.choice(layout.TANK_SHOT_SOUNDS)
        elif fighter is self.simulation.controlled:
            kind = "heavy_gunshot"
        else:
            kind = random.choice(layout.RIFLE_SHOT_SOUNDS)
        sound_effects.play_ui_sound(kind, volume_scale=self.battle_sfx_volume_share(fighter))

    def _play_hit_sound(self, target, damage, projectile=None, point=None):
        # The simulation supplies HP actually lost, including the remaining-HP limit.
        if projectile == "torpedo":
            # A torpedo hit splashes: the explosion animation in water colors, and its own sound.
            self.death_explosions.append((target, 0.0, layout.TORPEDO_SPLASH_PALETTE, point))
            sound_effects.play_ui_sound("torpedo_hit", volume_scale=self.battle_sfx_volume_share(target))
            return
        if target.shape in rules.SOFT_TARGET_SHAPES:
            sounds = layout.FLESH_HIT_SOUNDS
        elif damage <= target.data["max_health"] * layout.RICOCHET_MAX_HEALTH_SHARE:
            sounds = layout.RICOCHET_SOUNDS
        else:
            return
        sound_effects.play_ui_sound(random.choice(sounds), volume_scale=self.battle_sfx_volume_share(target))

    def start_battle(self):
        if self.mode != "preview" or self.preview_intro_stage is not None:
            return
        self.clear_controls()
        self.simulation.paused = False
        self.mode = "battle"
        self._refresh_controlled_stats()
        self.zoom_by(0, pygame.mouse.get_pos())
        self.update_battle_music_volume()
        self.last_tick = pygame.time.get_ticks()
        controlled = self.simulation.controlled
        if controlled is not None:
            self._follow_controlled_camera(controlled, pygame.mouse.get_pos())
        else:
            self._center_camera(self.simulation.arena_size[0] / 2, self.simulation.arena_size[1] / 2)
        self.refresh_ui()
        self._refresh_visibility()

    def clear_controls(self):
        self.held_keys.clear()
        self.firing = False
        self.secondary_firing = False
        self.touch_pointers.clear()
        self.kill_feed_pane.bar_drag = False
        if self.simulation is not None:
            self.simulation.set_player_input()

    def cancel_pointer_input(self):
        super().cancel_pointer_input()
        self.clear_controls()

    def return_to_setup(self):
        self.cancel_active_drags()
        self.clear_controls()
        self.stop_tactical_music()
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
        self.pan_drag = None
        for element in self.elements:
            if isinstance(element, Slider):
                element.dragging = False
        for button in self.unit_buttons.values():
            button.is_pressed = False

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.WINDOWFOCUSLOST:
                self.cancel_active_drags()
                # Only a player driving a living unit needs the battle held; a spectator's battle keeps running.
                driving = self._driving()
                self.clear_controls()
                if driving:
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
            if event.type == pygame.KEYDOWN and event.key in layout.CONTROL_KEYS and self._driving():
                self.held_keys.add(event.key)
                continue
            if self.mode in {"battle", "result"} and self._kill_feed_events(event):
                continue
            if self.mode in {"battle", "result"} and self._battlefield_mouse(event):
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

    def _battlefield_mouse(self, event):
        """The wheel zooms; left/right mouse fire primary/secondary weapons while controlling a sub-unit.

        While spectating or viewing results, a left drag makes the battlefield follow the pointer.
        """
        if event.type == pygame.MOUSEWHEEL:
            self.zoom_by(1 if event.y > 0 else -1 if event.y < 0 else 0, pygame.mouse.get_pos())
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button in (1, 3):
            if event.button == 1:
                self.firing = False
                self.pan_drag = None
            else:
                self.secondary_firing = False
            return False  # Buttons still need the release.
        if event.type == pygame.MOUSEMOTION and self.pan_drag is not None:
            self._move_camera(self.camera[0] - (event.pos[0] - self.pan_drag[0]) / self.zoom,
                              self.camera[1] - (event.pos[1] - self.pan_drag[1]) / self.zoom)
            self.pan_drag = event.pos
            return True
        if (event.type != pygame.MOUSEBUTTONDOWN or event.button not in (1, 3)
                or any(element.rect.collidepoint(event.pos) for element in self.elements)):
            return False
        if self._driving():
            if event.button == 1:
                self.firing = True
            else:
                self.secondary_firing = True
        elif event.button == 1 and (self.mode == "result" or self.simulation.controlled is None
                                   or not self.simulation.controlled.alive):
            self.pan_drag = event.pos
        return True

    def _refresh_status(self):
        counts = tuple(sum(fighter.alive for fighter in self.simulation.fighters if fighter.side == side) for side in (0, 1))
        key = (*counts, int(self.simulation.elapsed))
        if key != self.status_key:
            self.status_key = key
            self.status_surfaces = [fonts.get("normal").render(text, True, c.UI_TEXT_BRIGHT)
                                    for text in (f"Friendly: {counts[0]}", f"Enemy: {counts[1]}",
                                                 f"{int(self.simulation.elapsed)}s")]

    def _refresh_controlled_stats(self):
        """Cache the controlled unit's readout only when its displayed values change."""
        controlled = self.simulation.controlled if self.simulation is not None else None
        if self.mode != "battle" or controlled is None or not controlled.alive:
            self.controlled_stats_key = None
            self.controlled_stats_surface = None
            return
        # Speed is signed along the hull. Round the countdown up so an unfinished reload never reads zero.
        key = (round(controlled.speed, 1) or 0.0, round(math.degrees(controlled.angle)) % 360,
               math.ceil(max(0.0, controlled.cooldown) * 10))
        if controlled.weapon(1) is not None:
            key += (math.ceil(max(0.0, controlled.secondary_cooldown) * 10),)
        if key == self.controlled_stats_key:
            return
        self.controlled_stats_key = key
        speed, angle, reload_tenths = key[:3]
        reload_status = f"{reload_tenths / 10:.1f}s" if reload_tenths else "Ready"
        lines = (f"Speed: {speed:.1f} px/s", f"Angle: {angle}\N{DEGREE SIGN}", f"Reload: {reload_status}")
        if controlled.weapon(1) is not None:
            secondary = f"{key[3] / 10:.1f}s" if key[3] else "Ready"
            lines = (*lines[:2], f"Primary: {reload_status}", f"Secondary: {secondary}")
        panel = pygame.Surface(layout.CONTROL_STATS_SIZE)
        ui_elements.draw_pixel_panel(panel, panel.get_rect(), layout.CONTROL_STATS_COLOR, layout.CONTROL_STATS_BORDER)
        text_rect = panel.get_rect().inflate(-2 * layout.CONTROL_STATS_INSET, -2 * layout.CONTROL_STATS_INSET)
        ui_elements.draw_pixel_panel(panel, text_rect, layout.CONTROL_STATS_TEXT_BACKGROUND,
                                     layout.CONTROL_STATS_BORDER, gradient_strength=0.0, recessed=True)
        for row, text in enumerate(lines):
            image = fonts.get("normal").render(text, True, c.UI_TEXT_BRIGHT)
            panel.blit(image, (text_rect.x + layout.CONTROL_STATS_TEXT_PADDING,
                               text_rect.y + layout.CONTROL_STATS_TEXT_PADDING + row * layout.CONTROL_STATS_ROW_HEIGHT))
        self.controlled_stats_surface = panel

    def update(self):
        if self.preview_intro_stage is not None:
            self._update_preview_intro()
            return
        if self.mode not in {"battle", "result"}:
            return
        now = pygame.time.get_ticks()
        dt = min(layout.MAX_FRAME_SECONDS, max(0, now - self.last_tick) / 1000.0)
        self.last_tick = now
        if self.mode == "result" or not self.simulation.paused:
            self.death_explosions = [(fighter, age + dt, palette, point) for fighter, age, palette, point in self.death_explosions if age + dt < layout.DEATH_EXPLOSION_SECONDS]
        if self.mode == "result":
            return
        driving = self._driving()
        pointer = pygame.mouse.get_pos()
        controlled = self.simulation.controlled
        aim_point = None
        move_direction = None
        throttle = int(pygame.K_w in self.held_keys) - int(pygame.K_s in self.held_keys)
        turn = int(pygame.K_d in self.held_keys) - int(pygame.K_a in self.held_keys)
        primary, secondary = self.firing, self.secondary_firing
        if self.touch_mode and controlled is not None and controlled.alive:
            drive, aim = self._touch_axes("drive"), self._touch_axes("aim")
            move_direction = drive
            pointer = (c.SCREEN_WIDTH / 2 + aim.x * layout.TOUCH_PAD_SIZE,
                       c.SCREEN_HEIGHT / 2 + aim.y * layout.TOUCH_PAD_SIZE)
            if aim.length_squared():
                aim_distance = controlled.weapon_range if controlled.naval else layout.TOUCH_AIM_DISTANCE
                aim_point = (controlled.x + aim.x * aim_distance,
                             controlled.y + aim.y * aim_distance)
            weapon_mode = self.touch_weapon_mode if controlled.weapon(1) is not None else "Primary"
            primary = bool(aim.length_squared()) and weapon_mode in {"Primary", "Both"}
            secondary = bool(aim.length_squared()) and weapon_mode in {"Secondary", "Both"}
        if controlled is not None and controlled.alive:
            # Convert the pointer to a firing target only after applying its camera offset.
            self._follow_controlled_camera(controlled, pointer)
        self.simulation.set_player_input(
            throttle=throttle if driving else 0.0, turn=turn if driving else 0.0,
            fire=primary if driving else False, secondary_fire=secondary if driving else False,
            aim_point=(aim_point if self.touch_mode else self.to_field(pointer)) if driving else None,
            move_direction=move_direction if driving else None)
        self.simulation.advance(dt)
        if self.terrain_art_key != (id(self.simulation.battlefield), self.simulation.battlefield.revision, self.zoom):
            self._cache_terrain_art()
        controlled = self.simulation.controlled
        if controlled is not None and controlled.alive:
            self._follow_controlled_camera(controlled, pointer)
        elif self.held_keys or self.firing or self.secondary_firing or self.touch_pointers:
            # The controlled sub-unit is gone: the player spectates, so drop held input and leave the camera free.
            self.clear_controls()
        if self.touch_weapon_buttons and (controlled is None or not controlled.alive):
            self.elements = [element for element in self.elements if element not in self.touch_weapon_buttons]
            self.touch_weapon_buttons.clear()
        self._refresh_status()
        if self.simulation.winner is not None:
            self.clear_controls()
            self.stop_tactical_music()
            self.mode = "result"
            self._apply_campaign_result()
            self.refresh_ui()
        self._refresh_controlled_stats()
        self._refresh_visibility()

    def _refresh_visibility(self):
        """Cache sight geometry on observer/terrain changes and project it on camera changes."""
        controlled = self.simulation.controlled if self.simulation is not None else None
        if self.mode != "battle" or controlled is None or not controlled.alive:
            self.visibility_key = self.visibility_mask_key = None
            self.visibility_mask = None
            self.foliage_shadow_mask = None
            self.visible_fighters.clear()
            return
        if self.simulation.naval:
            # Naval battles show the whole battlefield: nothing is blacked out beyond sight range.
            self.visibility_key = self.visibility_mask_key = None
            self.visibility_mask = self.foliage_shadow_mask = None
            self.visible_fighters = {id(fighter) for fighter in self.simulation.fighters}
            return
        field = self.simulation.battlefield
        origin = controlled.x, controlled.y
        reach = self.simulation.sight_range
        key = field, field.revision, origin, reach
        if key != self.visibility_key:
            self.visibility_key = key
            self.visibility_blockers = field.sight_blockers(origin, reach)
            self.visibility_outline = battle_terrain.sight_polygon(origin, reach, self.visibility_blockers)
            foliage = field.foliage_silhouettes(origin, reach)
            self.foliage_shadow_outline = battle_terrain.sight_polygon(origin, reach, foliage) if foliage else ()
        self.visible_fighters = {id(fighter) for fighter in self.simulation.fighters if fighter is controlled or battle_terrain.point_in_sight(origin, (fighter.x, fighter.y), reach, self.visibility_blockers)}
        size = self.view_rect().size
        mask_key = key, tuple(self.camera), self.zoom, size
        if mask_key != self.visibility_mask_key:
            self.visibility_mask_key = mask_key
            if self.visibility_mask is None or self.visibility_mask.get_size() != size:
                self.visibility_mask = pygame.Surface(size, pygame.SRCALPHA)
            self.visibility_mask.fill((0, 0, 0, 255))
            pygame.draw.polygon(self.visibility_mask, (0, 0, 0, 0), [self.to_screen(x, y) for x, y in self.visibility_outline])
            if self.foliage_shadow_outline:
                if self.foliage_shadow_mask is None or self.foliage_shadow_mask.get_size() != size:
                    self.foliage_shadow_mask = pygame.Surface(size, pygame.SRCALPHA)
                self.foliage_shadow_mask.fill((0, 0, 0, layout.FOLIAGE_SHADOW_ALPHA))
                pygame.draw.polygon(self.foliage_shadow_mask, (0, 0, 0, 0), [self.to_screen(x, y) for x, y in self.foliage_shadow_outline])
                # Keep the stronger shadow: foliage must never reveal an opaque sight blocker.
                self.visibility_mask.blit(self.foliage_shadow_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MAX)

    def _update_preview_intro(self):
        if self.preview_intro_started is None:
            return
        elapsed = (pygame.time.get_ticks() - self.preview_intro_started) / 1000.0
        opening_at = layout.PREVIEW_SLIDE_IN_SECONDS + layout.PREVIEW_HOLD_SECONDS
        # Check both boundaries in order, even if a slow frame crosses both.
        if self.preview_intro_stage == 0 and elapsed >= layout.PREVIEW_SLIDE_IN_SECONDS:
            sound_effects.play_ui_sound("select_unit_filter")
            self.preview_intro_stage = 1
        if self.preview_intro_stage == 1 and elapsed >= opening_at:
            sound_effects.play_ui_sound("open_music")
            self.preview_intro_stage = 2
        if elapsed >= opening_at + layout.PREVIEW_SLIDE_OUT_SECONDS:
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
            elapsed -= layout.PREVIEW_SLIDE_IN_SECONDS + layout.PREVIEW_HOLD_SECONDS
            shown = 1.0 - min(1.0, max(0.0, elapsed / layout.PREVIEW_SLIDE_OUT_SECONDS))
        else:
            surface.fill((0, 0, 0))
            shown = min(1.0, max(0.0, elapsed / layout.PREVIEW_SLIDE_IN_SECONDS))
        top_height = c.SCREEN_HEIGHT // 2
        bottom_height = c.SCREEN_HEIGHT - top_height
        bars = (
            pygame.Rect(0, -top_height + round(top_height * shown), c.SCREEN_WIDTH, top_height),
            pygame.Rect(0, c.SCREEN_HEIGHT - round(bottom_height * shown), c.SCREEN_WIDTH, bottom_height),
        )
        for rect in bars:
            ui_elements.draw_pixel_panel(surface, rect, layout.PREVIEW_BAR_COLOR, layout.PREVIEW_BAR_BORDER,
                                         gradient_strength=layout.PREVIEW_BAR_GRADIENT_STRENGTH)

    def additional_draw(self, surface):
        if self.mode in {"setup", "preview"}:
            self._draw_rosters(surface)
            if self.mode == "setup" and self.forecast_surface is not None:
                surface.blit(self.forecast_surface,
                             self.forecast_surface.get_rect(center=(c.SCREEN_WIDTH // 2, layout.FORECAST_CENTER_Y)))
            return
        center_x = c.SCREEN_WIDTH // 2
        for image, center in zip(self.status_surfaces, (
                (center_x - layout.BATTLE_STATUS_SIDE_OFFSET, layout.BATTLE_STATUS_Y),
                (center_x + layout.BATTLE_STATUS_SIDE_OFFSET, layout.BATTLE_STATUS_Y), (center_x, layout.BATTLE_STATUS_Y))):
            surface.blit(image, image.get_rect(center=center))
        if self.kill_feed_surface is not None:
            surface.blit(self.kill_feed_surface, self.kill_feed_rect)
        controlled = self.simulation.controlled
        if self.touch_mode and self.mode == "battle" and controlled is not None and controlled.alive:
            for role in ("drive", "aim"):
                rect = self._touch_pad_rect(role)
                ui_elements.draw_pixel_panel(surface, rect, layout.CONTROL_STATS_COLOR, layout.CONTROL_STATS_BORDER, recessed=True)
                axes = self._touch_axes(role)
                knob = pygame.Rect(0, 0, 28, 28)
                knob.center = (rect.centerx + axes.x * (rect.width / 2 - knob.width / 2),
                               rect.centery + axes.y * (rect.height / 2 - knob.height / 2))
                ui_elements.draw_pixel_panel(surface, knob, layout.TEAM_COLORS[0] if role == "drive" else layout.PLAYER_COLOR,
                                             layout.CONTROL_STATS_BORDER)
        if (self.mode == "battle" and controlled is not None and controlled.alive
                and self.controlled_stats_surface is not None):
            panel = self.controlled_stats_surface
            surface.blit(panel, panel.get_rect(bottomleft=(layout.SCREEN_EDGE_MARGIN,
                                                          surface.get_height() - layout.SCREEN_EDGE_MARGIN)))
        if self.mode == "battle" and self.simulation.paused:
            rect = pygame.Rect(0, 0, 210, 70)
            rect.center = self.view_rect().center
            ui_elements.draw_pixel_panel(surface, rect, (39, 44, 58), (15, 19, 27))
            label = fonts.get("heading2").render("Paused", True, c.UI_TEXT_BRIGHT)
            surface.blit(label, label.get_rect(center=rect.center))
