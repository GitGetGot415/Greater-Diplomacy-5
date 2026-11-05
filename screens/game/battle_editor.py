"""Full-screen battle editing with opposing fronts and reserve card grids."""

import math
import pygame

import data.constants as c
from data import queries
from map_logic.actions import unit_actions
from screens.game.battle_screen import PANE_FRONT, PANE_RESERVE, PANE_ENEMY, PANE_LANES
from ui.navigation.screen import Screen
from ui.widgets.scroll_panes import ScrollPanes
from ui.widgets.ui_elements import Button, draw_pixel_panel, draw_wrapped_icon_row
from ui.widgets import flag_icons
from ui.widgets.text_utils import fit_text
from ui.rendering.font_manager import fonts
from ui.background_styles import COMBAT_PANEL_STYLES
from ui import dialogs


DRAG_THRESHOLD = 6
PANE_ENEMY_RESERVE = "enemy_reserve"
MARGIN = 16
GAP = 8
HEADER_H = 24
RESERVE_TOP = 54
RESERVE_H = 150
LANES_W = 188
CONTROLS_W = 156
CONTROL_BUTTON_H = 36
OUTLOOK_H = 136
CARD_H = 58
CARD_MAX_W = 190
CARD_MIN_W = 128
SCROLLBAR_W = 15
LANE_ROW_H = 42

HELP_TEXT = (
    "Select a lane on the left. Drag your reserves into empty front-line slots, "
    "or onto your front-line cards to swap units. Drag a front-line card into reserves "
    "to hold it back. Allies and enemies are read-only.\n\n"
    "If combat requires one unit to defend several lanes, placing it in a front-line "
    "slot also places it in the other required lanes.\n\n"
    "Empty slots stay empty while editing. When you exit, combat fills required slots "
    "from available reserves. HELD means other units get priority; held units still "
    "fight when needed. A popup lets you continue editing before gaps are filled.\n\n"
    "Reset restores automatic assignments and the AI's wounded-unit rotation.\n\n"
    "The outlook estimates the selected lane's winner and duration using the same "
    "combat rules as Manage Battle, including reserves and automatic filling.\n\n"
    "Exit returns to Manage Battle."
)


class BattleEditorScreen(ScrollPanes, Screen):
    """A controller state; the battle overview supplies shared presentation data."""

    title = "Edit Battle"
    title_y = 12
    title_preset = "heading2"
    bg_color = c.PANEL_THEME_DANGER[0]

    def __init__(self, overview=None):
        super().__init__()
        self.overview = self.province = None
        self.selected_lane = 0
        self.drag_unit = None
        self.drag_surface = self.drag_rect = None
        self.drag_start = None
        self.drag_stamp = None
        self.opened_turn = None
        self.back_state = "ORDERS"
        self._observed_state = None
        self.front_slots = None
        self._exit_confirmation_open = False
        self.refresh_ui()
        if overview is not None:
            self.start(overview)

    def on_enter(self, app, previous):
        overview = previous.battle_editor_overview
        del previous.battle_editor_overview
        self.back_state = next(name for name, screen in app.states.items() if screen is previous)
        self.start(overview)

    def start(self, overview):
        self.overview = overview
        self.map_screen = overview.map_screen
        self.province = overview.province
        self.player = overview.player
        self.opened_turn = self.map_screen.time_manager.total_turns
        self.selected_lane = overview.selected_lane
        self.done = False
        self._exit_confirmation_open = False
        self.front_slots = None
        self.cancel_drag()
        for pane in self.regions:
            setattr(self, self.scroll_attrs(pane)["attr"], 0)
        self.refresh_ui()
        self._observed_state = self._source_stamp()

    def current(self):
        lane, near, far = self.overview.current()
        if lane is not None and self.front_slots is not None:
            near = near._replace(
                front=[unit for unit in self.front_slots[lane.index] if unit is not None],
                reserve=self._reserve_units(near))
        return lane, near, far

    def my_units(self):
        return self.overview.my_units()

    def can_command(self, unit):
        return self.overview.can_command(unit)

    def is_mine(self, side):
        return self.overview.is_mine(side)

    def seated(self):
        if self.front_slots is None:
            return self.overview.seated()
        seated = {id(unit) for slots in self.front_slots.values() for unit in slots if unit is not None}
        for lane in self.overview.battle.lanes:
            _near, far = self.overview.near_far(lane)
            seated.update(id(unit) for unit in far.front)
        return seated

    def _reserve_units(self, side):
        """The editor's bench follows its cards, rather than automatic seating."""
        seated = self.seated()
        mine = ([unit for unit in self.my_units() if id(unit) not in seated]
                if self.overview.is_mine(side) else [])
        commanded = {id(unit) for unit in mine}
        rest = [unit for unit in self.province.get('units', [])
                if queries.get_unit_combat_owner(unit) in side.nations
                and id(unit) not in seated and id(unit) not in commanded]
        return mine + rest

    def _layout(self):
        width = c.SCREEN_WIDTH - 2 * MARGIN
        bottom_top = c.SCREEN_HEIGHT - MARGIN - RESERVE_H
        middle_top = RESERVE_TOP + RESERVE_H + 2 * GAP
        middle_h = bottom_top - 2 * GAP - middle_top
        self.controls_rect = pygame.Rect(
            c.SCREEN_WIDTH - MARGIN - CONTROLS_W, middle_top,
            CONTROLS_W, HEADER_H + 3 * CONTROL_BUTTON_H + 4 * GAP)
        self.outcome_rect = pygame.Rect(self.controls_rect.x, self.controls_rect.bottom + GAP,
                                        CONTROLS_W, OUTLOOK_H)
        self.lanes_rect = pygame.Rect(MARGIN, middle_top, LANES_W, middle_h)
        self.regions = {
            PANE_LANES: pygame.Rect(MARGIN, middle_top + HEADER_H, LANES_W, middle_h - HEADER_H),
            PANE_ENEMY_RESERVE: pygame.Rect(MARGIN, RESERVE_TOP + HEADER_H,
                                           width, RESERVE_H - HEADER_H),
            PANE_RESERVE: pygame.Rect(MARGIN, bottom_top + HEADER_H,
                                     width, RESERVE_H - HEADER_H),
        }
        center_x = MARGIN + LANES_W + 2 * GAP
        center_w = self.controls_rect.left - 2 * GAP - center_x
        half_h = (middle_h - 2 * GAP) // 2
        for pane, top in ((PANE_ENEMY, middle_top),
                          (PANE_FRONT, middle_top + half_h + 2 * GAP)):
            self.regions[pane] = pygame.Rect(center_x, top + HEADER_H, center_w, half_h - HEADER_H)
        self.divider = (center_x, middle_top + half_h + GAP, center_w)

    def refresh_ui(self, *, placed_unit=None):
        self._layout()
        self.elements = []
        self.row_paint = {}
        self.card_surfaces = {}
        self.slot_rects = {}
        self.empty_slots = {}
        self.lane_labels = []
        self.headings = {}
        self.lane_outcome = None
        self.outcome_surface = None
        if self.overview is not None:
            stamp = self._source_stamp()
            if self._observed_state is not None and stamp != self._observed_state:
                # An authoritative update invalidates temporary positions,
                # including when input arrives before the next frame update.
                self.cancel_drag()
                self.front_slots = None
                self.province = self.map_screen.id_to_province.get(self.province['id'], self.province)
                self._observed_state = stamp
            self.overview.province = self.province
        for pane in self.regions:
            setattr(self, self.scroll_attrs(pane)["limit_attr"], 0)
        controls = self.controls_rect
        reset = Button(controls.x + GAP, controls.y + HEADER_H,
                       (CONTROLS_W - 2 * GAP, CONTROL_BUTTON_H), "red", "Reset",
                       self.reset_assignments, font_preset="button_small")
        reset.disabled = not self.can_edit_now()
        help_button = Button(controls.x + GAP, reset.rect.bottom + GAP,
                             (CONTROLS_W - 2 * GAP, CONTROL_BUTTON_H), "blue", "Help",
                             self.show_help, font_preset="button_small")
        done = Button(controls.x + GAP, help_button.rect.bottom + GAP,
                      (CONTROLS_W - 2 * GAP, CONTROL_BUTTON_H), "green", "Exit",
                      self.exit_screen, font_preset="button_small", sound_kind="back")
        self.elements.extend((reset, help_button, done))
        if self.overview is None:
            return
        self.overview.visible = queries.is_province_visible(self.map_screen, self.province['id'])
        self.overview.selected_lane = self.selected_lane
        self.overview.rebuild()
        self.selected_lane = self.overview.selected_lane
        self.battle = self.overview.battle
        self.title = f"Edit Battle - Province {self.province['id']}"
        if not self.overview.visible or not self.battle.lanes:
            return
        if self.front_slots is None:
            # Positions are temporary editor state. Rebuilding the execution
            # preview must not fill vacancies or compact the player's cards.
            self.front_slots = {}
            for lane in self.battle.lanes:
                near, far = self.overview.near_far(lane)
                count = max(lane.slots, len(near.front), len(far.front))
                self.front_slots[lane.index] = list(near.front) + [None] * (count - len(near.front))
        if placed_unit is not None:
            self._fill_shared_fronts(placed_unit)
        self._lane_rows()
        lane, near, far = self.current()
        self.lane_outcome = self.overview._estimate_lane_outcome(lane)
        self.outcome_surface = pygame.Surface(self.outcome_rect.size, pygame.SRCALPHA)
        self.overview._paint_outcome(self.outcome_surface, lane,
                                     rect=self.outcome_surface.get_rect(), outcome=self.lane_outcome)
        slots = len(self.front_slots[lane.index])
        self._card_grid(PANE_ENEMY, far.front, slots=slots)
        self._card_grid(PANE_FRONT, self.front_slots[lane.index], slots=slots)
        reserves = near.reserve
        seated = self.seated()
        enemies = [unit for unit in self.province.get('units', [])
                   if queries.get_unit_combat_owner(unit) in far.nations and id(unit) not in seated]
        enemies = queries.filter_visible_units(
            enemies, self.player, self.province, self.map_screen.nation_data)
        self._card_grid(PANE_ENEMY_RESERVE, enemies)
        self._card_grid(PANE_RESERVE, reserves)
        captions = {
            PANE_ENEMY_RESERVE: f"ENEMY RESERVES ({len(enemies)})",
            PANE_ENEMY: f"ENEMY FRONT  {len(far.front)}/{lane.slots}",
            PANE_FRONT: f"YOUR FRONT  {len(near.front)}/{lane.slots}",
            PANE_RESERVE: f"YOUR SIDE'S RESERVES ({len(reserves)})",
        }
        font = fonts.get('small')
        self.headings = {pane: font.render(text, True, c.UI_TEXT_LIGHT)
                         for pane, text in captions.items()}

    def _lane_rows(self):
        rect = self.regions[PANE_LANES]
        self.row_paint[PANE_LANES] = []
        for index, y in self.pane_rows(PANE_LANES, len(self.battle.lanes),
                                       rect.y, rect.height,
                                       row_h=LANE_ROW_H):
            lane = self.battle.lanes[index]
            near, far = self.overview.near_far(lane)
            front_count = sum(unit is not None for unit in self.front_slots[lane.index])
            mine = self.is_mine(near) or self.is_mine(far)
            button = Button(rect.x + GAP, y, (rect.width - SCROLLBAR_W - 2 * GAP, LANE_ROW_H),
                            'blue' if mine else 'grey', '', lambda i=index: self._select(i))
            button.is_selected = index == self.selected_lane
            self.add_pane_row(PANE_LANES, button)
            label = pygame.Surface(button.rect.size, pygame.SRCALPHA)
            font = fonts.get('small')
            x = 6
            number = font.render(f"{index + 1}.", True, c.UI_TEXT_LIGHT)
            label.blit(number, (x, 12))
            x += number.get_width() + GAP
            for side in (near, far):
                owner = self.overview.side_display_nations(side)[0]
                x = flag_icons.draw_flag_centered(label, owner, self.map_screen.nation_data,
                                                  x, 0, LANE_ROW_H) + GAP
            tally = font.render(f"{front_count} v {len(far.front)}", True, c.UI_TEXT_LIGHT)
            label.blit(tally, (label.get_width() - tally.get_width() - 5, 12))
            self.lane_labels.append((button.rect, label))

    def _card_grid(self, pane, units, slots=None):
        rect = self.regions[pane]
        units = list(units)
        if slots is None:
            units.sort(key=lambda unit: unit.get('combat_stance') != 'RESERVE')
        available_w = rect.width - SCROLLBAR_W - GAP
        max_columns = max(1, (available_w + GAP) // (CARD_MIN_W + GAP))
        if slots is None:
            columns = max(1, (available_w + GAP) // (CARD_MAX_W + GAP))
        else:
            columns = min(max_columns, max(1, math.ceil(slots / 2)))
        card_w = min(CARD_MAX_W, (available_w - (columns - 1) * GAP) // columns)
        count = max(len(units), slots or 0)
        rows = math.ceil(count / columns)
        attrs = self.scroll_attrs(pane)
        limit = min(0, rect.height - rows * (CARD_H + GAP) + GAP)
        setattr(self, attrs['attr'], max(limit, min(0, self.pane_scroll(pane))))
        self.row_paint[pane] = []
        self.slot_rects[pane] = []
        self.empty_slots[pane] = []
        for grid_row, y in self.layout_list_rows(
                rows, CARD_H + GAP, rect.y, view_h=rect.height, pad=-GAP,
                cull_top=rect.top, cull_bottom=rect.bottom,
                attr=attrs['attr'], limit_attr=attrs['limit_attr']):
            for column in range(columns):
                index = grid_row * columns + column
                if index >= count:
                    break
                card_rect = pygame.Rect(rect.x + column * (card_w + GAP), y, card_w, CARD_H)
                if index >= len(units) or units[index] is None:
                    self.slot_rects[pane].append(card_rect)
                    self.empty_slots[pane].append((card_rect, index))
                    continue
                unit = units[index]
                self.row_paint[pane].append((card_rect, (unit, '')))
                self.card_surfaces[pane, id(unit)] = self._card_surface(unit, pane, card_rect.size)

    def _card_surface(self, unit, pane, size):
        surface = pygame.Surface(size, pygame.SRCALPHA)
        mine = self.can_command(unit)
        color = 'grey' if not mine else ('blue' if pane == PANE_FRONT else
                                         'orange' if unit.get('combat_stance') == 'RESERVE' else 'green')
        draw_pixel_panel(surface, surface.get_rect(), c.UI_COLORS[color][0], c.COLOR_DIM_BORDER)
        row = self.overview.combat_row_data[id(unit)]
        font = fonts.get('small')
        x = flag_icons.draw_flag_centered(surface, unit.get('owner'), self.map_screen.nation_data,
                                          5, 3, font.get_height())
        health = font.render(queries.format_health_percent(row['profile']), True, c.UI_TEXT_MUTED)
        name = unit.get('custom_name') or queries.get_condensed_unit_name(unit.get('type', 'Unit'))
        name = fit_text(name, font, max(1, size[0] - x - health.get_width() - 12))
        surface.blit(font.render(name, True, c.UI_TEXT_LIGHT), (x, 3))
        surface.blit(health, (size[0] - health.get_width() - 5, 3))
        draw_wrapped_icon_row(surface, font, row['entries'], 6, font.get_height() + 6,
                              c.UI_TEXT_LIGHT, size[0] - 12, line_height=font.get_height())
        return surface

    def _select(self, index):
        self.selected_lane = index
        for pane in self.regions:
            setattr(self, self.scroll_attrs(pane)['attr'], 0)
        self.refresh_ui()

    def additional_draw(self, surface):
        style = COMBAT_PANEL_STYLES['main']
        for rect in (self.lanes_rect, self.controls_rect):
            draw_pixel_panel(surface, rect, style['color'], c.COLOR_DIM_BORDER,
                             gradient_strength=style['gradient_strength'])
        font = fonts.get('small')
        for caption, rect in (('LANES', self.lanes_rect), ('CONTROLS', self.controls_rect)):
            surface.blit(font.render(caption, True, c.UI_TEXT_LIGHT), (rect.x + GAP, rect.y + 3))
        for pane, heading in self.headings.items():
            rect = self.regions[pane]
            surface.blit(heading, (rect.x, rect.y - HEADER_H + 3))
        x, y, width = self.divider
        pygame.draw.line(surface, c.UI_TEXT_MUTED, (x, y), (x + width, y))
        if self.outcome_surface is not None:
            surface.blit(self.outcome_surface, self.outcome_rect)

    def show_help(self):
        self.cancel_drag()
        dialogs.show_info("Battle Editor Help", HELP_TEXT)

    def _paint_cards(self, pane):
        def paint(surface):
            for rect in self.slot_rects.get(pane, ()):
                pygame.draw.rect(surface, c.COLOR_DIM_BORDER, rect, 1)
            for rect, (unit, _note) in self.row_paint.get(pane, ()):
                surface.blit(self.card_surfaces[pane, id(unit)], rect)
        return paint

    def _paint_lanes(self, surface):
        for rect, label in self.lane_labels:
            surface.blit(label, rect)

    def draw_elements(self, surface):
        foregrounds = {pane: self._paint_cards(pane) for pane in self.regions if pane != PANE_LANES}
        foregrounds[PANE_LANES] = self._paint_lanes
        self.draw_panes(surface, foregrounds=foregrounds)

    def draw(self, surface):
        Screen.draw(self, surface)
        self.draw_foreground(surface)

    def can_edit_now(self):
        return (self.overview is not None and self.map_screen.player_country == self.player
                and self.map_screen.time_manager.total_turns == self.opened_turn
                and self.map_screen.id_to_province.get(self.province['id']) is self.province
                and queries.is_province_visible(self.map_screen, self.province['id'])
                and self.map_screen.can_select_map_units()
                and bool(self.my_units()))

    def _source_stamp(self):
        map_ref = self.map_screen
        stamp = (id(map_ref.id_to_province.get(self.province['id'])),
                 map_ref._presentation_cache_revision, map_ref.player_country,
                 map_ref.time_manager.total_turns, map_ref.tactical_mode,
                 id(map_ref.player_unit))
        if map_ref.realtime_multiplayer:
            session = map_ref.realtime_session
            player = session.players.get(map_ref.realtime_player_id) if session else None
            stamp += (session.phase if session else None,
                      (player.submitted, player.eliminated) if player else None)
        return stamp

    def cancel_drag(self):
        self.drag_unit = self.drag_surface = self.drag_rect = self.drag_start = self.drag_stamp = None

    def _changed(self, *, placed_unit=None):
        self.map_screen.invalidate_map_presentation_cache()
        # Our own order edits preserve the in-progress positions. External
        # state changes instead discard them at the refresh boundary above.
        self._observed_state = self._source_stamp()
        self.refresh_ui(placed_unit=placed_unit)

    def _fill_shared_fronts(self, unit):
        """Mirror required shared defense without filling unrelated vacancies."""
        if self.battle.shares.get(id(unit), 0) < 2:
            return
        for lane in self.battle.lanes:
            near, _far = self.overview.near_far(lane)
            if not any(current is unit for current in near.front):
                continue
            slots = self.front_slots[lane.index]
            if any(current is unit for current in slots):
                continue
            index = next((index for index, current in enumerate(slots) if current is None), None)
            if index is not None:
                slots[index] = unit

    def reset_assignments(self):
        self.cancel_drag()
        if not self.can_edit_now():
            return
        unit_actions.reset_battle_orders(
            self.map_screen, self.player, self.province, self.my_units())
        self.front_slots = None
        self._changed()

    def drop_unit(self, unit, pane, replacement=None, slot_index=None):
        """A front-row drop swaps troops; a reserve drop holds a unit back."""
        if not self.can_edit_now() or not self.can_command(unit):
            return False
        lane, near, far = self.current()
        if lane is None or not self.is_mine(near):
            return False
        if pane == PANE_RESERVE:
            if id(unit) not in self.seated():
                return False
            changes = [(unit, None, True)]
        elif pane == PANE_FRONT:
            nation = queries.get_unit_combat_owner(unit)
            if nation not in near.nations:
                return False
            target = next((enemy for enemy in far.nations if queries.are_at_war(
                nation, enemy, self.map_screen.nation_data)), None)
            if target is None:
                return False
            slots = self.front_slots[lane.index]
            if replacement is not None:
                slot_index = next((index for index, current in enumerate(slots)
                                   if current is replacement), None)
            elif slot_index is None:
                slot_index = next((index for index, current in enumerate(slots) if current is None), None)
                if slot_index is None:
                    slot_index = next((index for index in reversed(range(len(slots)))
                                       if self.can_command(slots[index])
                                       and queries.get_unit_combat_owner(slots[index]) == nation), None)
            if type(slot_index) is not int or not 0 <= slot_index < len(slots):
                return False
            replacement = slots[slot_index]
            if replacement is unit:
                return False
            changes = [(unit, target, False)]
            if replacement is not None:
                if (not any(current is replacement for current in near.front)
                        or not self.can_command(replacement)
                        or queries.get_unit_combat_owner(replacement) != nation):
                    return False
                changes.append((replacement, None, True))
        else:
            return False
        unit_actions.apply_battle_orders(self.map_screen, self.player, self.province, changes)
        removed = {id(current) for current, _target, _reserve in changes}
        for slots in self.front_slots.values():
            for index, current in enumerate(slots):
                if current is not None and id(current) in removed:
                    slots[index] = None
        if pane == PANE_FRONT:
            self.front_slots[lane.index][slot_index] = unit
        self._changed(placed_unit=unit if pane == PANE_FRONT else None)
        return True

    def _row_at(self, pane, pos):
        if not self.regions[pane].collidepoint(pos):
            return None
        return next(((rect, unit) for rect, (unit, _note) in self.row_paint.get(pane, ())
                     if rect.collidepoint(pos)), None)

    def handle_events(self, events):
        for event in events:
            if self.done or self._exit_confirmation_open:
                return
            if event.type == pygame.WINDOWFOCUSLOST:
                self.cancel_drag()
            if self.drag_unit is not None:
                if event.type == pygame.MOUSEMOTION:
                    self.drag_rect.center = event.pos
                    continue
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    unit, start, stamp = self.drag_unit, self.drag_start, self.drag_stamp
                    self.cancel_drag()
                    if (stamp != self._source_stamp()
                            or pygame.Vector2(event.pos).distance_to(start) < DRAG_THRESHOLD):
                        continue
                    for pane in (PANE_FRONT, PANE_RESERVE):
                        if self.regions[pane].collidepoint(event.pos):
                            row = self._row_at(pane, event.pos)
                            slot = next((index for rect, index in self.empty_slots.get(pane, ())
                                         if rect.collidepoint(event.pos)), None)
                            self.drop_unit(unit, pane, row[1] if row and pane == PANE_FRONT else None,
                                           slot_index=slot)
                            break
                    continue
            # Scrollbar drags take priority over grabbing a unit card.
            if self.route_pane_scroll(event):
                continue
            if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                    and self.can_edit_now()):
                for pane in (PANE_FRONT, PANE_RESERVE):
                    row = self._row_at(pane, event.pos)
                    if row is not None and self.can_command(row[1]):
                        rect, unit = row
                        self.drag_unit, self.drag_start = unit, event.pos
                        self.drag_stamp = self._source_stamp()
                        self.drag_surface = self.card_surfaces[pane, id(unit)]
                        self.drag_rect = rect.copy()
                        break
                if self.drag_unit is not None:
                    continue
            super().handle_events([event])

    def draw_foreground(self, surface):
        for pane, rect in self.regions.items():
            self.draw_pane_scrollbar(surface, pane, rect.right - SCROLLBAR_W,
                                     rect.top, rect.height, width=SCROLLBAR_W)
            pygame.draw.line(surface, c.UI_TEXT_MUTED, (rect.left, rect.bottom),
                             (rect.right - 1, rect.bottom))
        if self.drag_surface is not None:
            for pane in (PANE_FRONT, PANE_RESERVE):
                pygame.draw.rect(surface, c.COLOR_GOLD_HIGHLIGHT, self.regions[pane], 1)
            surface.blit(self.drag_surface, self.drag_rect)

    def update(self):
        if self.overview is None:
            return
        if (self.map_screen.player_country != self.player
                or self.map_screen.time_manager.total_turns != self.opened_turn
                or self.province['id'] not in self.map_screen.id_to_province):
            self._finish_exit()
            return
        stamp = self._source_stamp()
        if stamp != self._observed_state:
            self.refresh_ui()

    def exit_screen(self):
        if self.done or self._exit_confirmation_open:
            return
        self.cancel_drag()
        if self.can_edit_now():
            if self._source_stamp() != self._observed_state:
                self.refresh_ui()
            if self._reserves_will_fill_gaps():
                self._exit_confirmation_open = True

                def answered(leave):
                    if not self._exit_confirmation_open:
                        return
                    self._exit_confirmation_open = False
                    if leave:
                        self._finish_exit()
                    else:
                        self.update()

                dialogs.ask_yes_no(
                    "Empty Front-Line Slots",
                    "Some empty front-line slots will be filled automatically from available "
                    "reserves when you leave. HELD units can still be put on the front line "
                    "if needed. Continue editing, or leave the arrangement as is?",
                    on_result=answered, yes_label="Leave As Is", no_label="Continue Editing")
                return
        self._finish_exit()

    def _reserves_will_fill_gaps(self):
        if self.front_slots is None:
            return False
        # Read the execution owner's actual arrangement, across every lane;
        # an empty slot alone does not mean enough reserves exist to fill it.
        self.overview.rebuild()
        for lane in self.overview.battle.lanes:
            slots = self.front_slots.get(lane.index, ())
            near, _far = self.overview.near_far(lane)
            if any(unit is None for unit in slots) and len(near.front) > sum(
                    unit is not None for unit in slots):
                return True
        return False

    def _finish_exit(self):
        self._exit_confirmation_open = False
        self.cancel_drag()
        if self.overview is not None:
            self.overview.selected_lane = self.selected_lane
            self.overview._editor_closed()
        super().exit_screen()
