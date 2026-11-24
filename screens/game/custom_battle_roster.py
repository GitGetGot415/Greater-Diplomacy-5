"""Roster cards: layout, selection, dragging, health bars, and drawing."""

import math

import pygame

from data import queries
from map_logic import tactical_rules as rules
from screens.game import custom_battle_layout as layout
from screens.game import custom_battle_sprites as sprites
from ui.rendering import symbol_loader
from ui.rendering.font_manager import fonts
from ui.widgets import flag_icons
from ui.widgets import ui_elements
from ui.widgets.text_utils import fit_text
from ui.widgets.ui_elements import Button
import data.constants as c


class RosterCards:
    """Roster cards: layout, selection, dragging, health bars, and drawing."""

    def card_rect(self, side, index):
        """A card stands in its column; a column's second card stands below its first."""
        columns = self.columns[side]
        column = columns[index]
        row = int(index > 0 and columns[index - 1] == column)
        pane = self.panes[side]
        return pygame.Rect(pane.x + column * (layout.CARD_SIZE[0] + layout.CARD_GAP) + self._roster_scroll(side).value,
                           pane.y + row * (layout.CARD_SIZE[1] + layout.CARD_GAP), *layout.CARD_SIZE)

    def _drop_target(self, side, pos):
        """The column and card row a drop at ``pos`` lands on.

        Near a card's left or right edge, or in the gap between columns, the row is None:
        the dropped card gets a new column there.
        """
        pane = self.panes[side]
        column, within = divmod(pos[0] - pane.x - self._roster_scroll(side).value, layout.CARD_SIZE[0] + layout.CARD_GAP)
        if within < layout.DROP_NEW_COLUMN_EDGE:
            return int(column), None
        if within > layout.CARD_SIZE[0] - layout.DROP_NEW_COLUMN_EDGE:
            return int(column) + 1, None
        return int(column), min(layout.ROSTER_ROWS - 1, max(0, int((pos[1] - pane.y) // (layout.CARD_SIZE[1] + layout.CARD_GAP))))

    @staticmethod
    def _position_edit_button(button, card):
        button.rect.topright = (card.right - layout.CARD_EDIT_INSET, card.top + layout.CARD_EDIT_INSET)

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
        track = self._roster_scroll(side).track
        return bool(track and track.collidepoint(pos))

    def _clear_roster_selection(self):
        self.selected = [None, None]
        self.group = [[], []]

    def _deselect_background(self, event):
        if (event.type != pygame.MOUSEBUTTONDOWN or event.button != 1
                or self.drag is not None or self.marquee is not None or self.bar_drag is not None
                or not (any(index is not None for index in self.selected) or any(self.group))):
            return
        # Controls must keep their selected unit or group available to their callbacks.
        if any(element.visible and element.rect.collidepoint(event.pos) for element in self.elements):
            return
        for side, pane in enumerate(self.panes):
            if self._on_scrollbar(side, event.pos):
                return
            if pane.collidepoint(event.pos) and any(self.card_rect(side, index).collidepoint(event.pos) for index in range(len(self.rosters[side]))):
                return
        self._clear_roster_selection()
        self.refresh_ui()

    def _marquee_events(self, event):
        """Drag a selection square from empty panel space; roster background drags still scroll."""
        if self.marquee is not None:
            if event.type == pygame.MOUSEMOTION:
                self.marquee[2] = event.pos
                self._select_group(self.marquee[0], self.marquee[1], event.pos)
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
        for side, top in enumerate(layout.PANEL_TOPS):
            if (pygame.Rect(layout.PANEL_X, top, layout.PANEL_WIDTH, layout.PANEL_HEIGHT).collidepoint(event.pos)
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
        if math.dist(origin, current) >= layout.DRAG_THRESHOLD:
            area = self._marquee_rect(origin, current).clip(self.panes[side])
            picked = [index for index in range(len(self.rosters[side]))
                      if self.card_rect(side, index).colliderect(area)]
        # One card is an ordinary selection, so Remove and Control keep working.
        selected = picked[0] if len(picked) == 1 else None
        group = picked if len(picked) > 1 else []
        if self.selected[side] == selected and self.group[side] == group:
            return
        self.selected[side] = selected
        self.group[side] = group
        self.refresh_ui()

    def _set_bar_health(self, side, index, x):
        """Set starting HP from the pointer's position along a card's health bar."""
        card = self.card_rect(side, index)
        bar, _flag_x = self._bar_geometry()
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
        bar, _flag_x = self._bar_geometry()
        for side, pane in enumerate(self.panes):
            if not pane.collidepoint(event.pos):
                continue
            for index in range(len(self.rosters[side])):
                card = self.card_rect(side, index)
                if bar.move(card.topleft).inflate(0, 2 * layout.CARD_BAR_GRAB_PAD).collidepoint(event.pos):
                    self.bar_drag = (side, index)
                    self._set_bar_health(side, index, event.pos[0])
                    return True
        return False

    def _move_roster_entry(self, side, index, column, *, row=None, target_side=None):
        """Move one roster entry. The leftmost column deploys in the front rank.

        With ``row``, the entry is dropped on that card space of ``column``. Within one army it
        swaps with the card there. On an empty space, or any space of the other army, it joins
        the column when the column has room. Otherwise, and without ``row``, it gets a new column
        before ``column``; an army already using every column refuses that.
        """
        if target_side is None:
            target_side = side
        if (side not in (0, 1) or target_side not in (0, 1) or not self._roster_reorderable(side)
                or not 0 <= index < len(self.rosters[side])):
            return False
        if target_side != side:
            if self.mode != "setup" or self.campaign is not None or not self._roster_has_space(target_side):
                return False
        unit = self.rosters[side][index]
        before = list(self.rosters[0])
        source = self._column_groups(side)
        target = source if target_side == side else self._column_groups(target_side)
        origin = next(group for group in source if any(entry is unit for entry in group))
        origin_row = next(position for position, entry in enumerate(origin) if entry is unit)
        column = max(0, column)
        group = target[column] if row is not None and column < len(target) else None
        if group is not None and row < len(group) and target_side == side:
            if group[row] is unit:
                return False
            origin[origin_row], group[row] = group[row], unit
        elif group is not None and len(group) - (group is origin) < c.CUSTOM_BATTLE_UNITS_PER_COLUMN:
            origin.pop(origin_row)
            group.append(unit)
        else:
            origin.pop(origin_row)
            if sum(1 for entry_group in target if entry_group) >= c.CUSTOM_BATTLE_MAX_COLUMNS_PER_SIDE:
                return False
            target.insert(min(column, len(target)), [unit])
        self._set_columns(side, source)
        if target_side != side:
            self._set_columns(target_side, target)
        self.group[side] = []
        if self.mode == "setup":
            if target_side != side:
                self._clear_roster_selection()
            self.selected[target_side] = self._index_of(target_side, unit)
            return True
        # Preview: campaign units follow their roster entries (friendly ones come first),
        # and the paused battle deploys again in the new formation.
        if self.campaign is not None:
            order = [next(position for position, entry in enumerate(before) if entry is moved) for moved in self.rosters[0]]
            self.campaign.units[:len(before)] = [self.campaign.units[position] for position in order]
        self._build_simulation()
        return True

    def _roster_reorderable(self, side):
        """Editing reorders both armies; preview reorders only the friendly army."""
        return self.mode == "setup" or (self.mode == "preview" and side == 0)

    def _roster_events(self, event):
        self._deselect_background(event)
        if self.mode == "setup" and (self._marquee_events(event) or self._health_bar_events(event)):
            return True
        if self.drag is not None:
            side, index, origin, active = self.drag
            if event.type == pygame.MOUSEMOTION:
                if math.dist(event.pos, origin) >= layout.DRAG_THRESHOLD:
                    self.drag[3] = True
                return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if active:
                    for target_side, pane in enumerate(self.panes):
                        if pane.collidepoint(event.pos):
                            column, row = self._drop_target(target_side, event.pos)
                            self._move_roster_entry(side, index, column, row=row, target_side=target_side)
                            break
                self.drag = None
                self.refresh_ui()
                return True
            return False
        pointer = getattr(event, "pos", pygame.mouse.get_pos())
        for side, pane in enumerate(self.panes):
            roster = self._roster_scroll(side)
            track = roster.track
            engaged = (pane.collidepoint(pointer) or (track and track.collidepoint(pointer))
                       or roster.bar_drag or self.is_content_dragging(roster))
            if not engaged:
                continue
            if (self._roster_reorderable(side) and event.type == pygame.MOUSEBUTTONDOWN
                    and event.button == 1 and pane.collidepoint(event.pos)):
                for index in range(len(self.rosters[side])):
                    if self.card_rect(side, index).collidepoint(event.pos):
                        if self.mode == "setup":
                            self.selected[side] = index
                            self.group[side] = []
                        self.drag = [side, index, event.pos, False]
                        self.refresh_ui()
                        return True
            if self.handle_list_scroll(event, roster, content=True):
                return True
        return False

    def _card_key(self, side, unit):
        return (self.mode, self.terrain, side, unit["type"], unit["owner"], unit["health"], unit["max_health"])

    @staticmethod
    def _bar_geometry():
        """The health bar rect and the flag's x, in card coordinates; the flag sits right of the bar, under the icon."""
        flag_x = layout.CARD_INSET + layout.CARD_LEFT_WIDTH - layout.CARD_BAR_FLAG_SIZE[0]
        bar = pygame.Rect(layout.CARD_INSET, layout.CARD_BAR_TOP, flag_x - layout.CARD_BAR_FLAG_GAP - layout.CARD_INSET, layout.CARD_BAR_HEIGHT)
        return bar, flag_x

    def _draw_health_bar(self, card, unit):
        bar, flag_x = self._bar_geometry()
        pygame.draw.rect(card, layout.OUTLINE_COLOR, bar)
        ratio = max(0.0, min(1.0, unit["health"] / unit["max_health"]))
        fill = pygame.Rect(bar.x + 1, bar.y + 1, round((bar.width - 2) * ratio), bar.height - 2)
        sprites.draw_health_fill(card, fill, ratio)
        flag_icons.draw_flag(card, unit["owner"], self.country_data, flag_x,
                             bar.centery - layout.CARD_BAR_FLAG_SIZE[1] // 2, size=layout.CARD_BAR_FLAG_SIZE)

    def _cache_card(self, side, unit):
        """Edit Battle and preview cards share one size: the icon over the health bar and flag on the left,
        and health, attack, and defense on the right. Edit Battle adds the unit name beside the gear button."""
        key = self._card_key(side, unit)
        if key not in self.card_surfaces:
            card = pygame.Surface(layout.CARD_SIZE, pygame.SRCALPHA)
            if not self._roster_reorderable(side):
                ui_elements.draw_pixel_panel(card, card.get_rect(), (46, 51, 65), (15, 19, 27))
            name = unit["type"]
            font = fonts.get("tiny")
            icon_x = layout.CARD_INSET + layout.CARD_LEFT_WIDTH // 2
            if self.mode == "preview":
                # Preview shows no unit name, so the unit symbol takes the full height above the bar.
                icon = symbol_loader.get_symbol(name, zoom=1, color=layout.TEAM_COLORS[side],
                                                country=unit["owner"], fit_size=layout.PREVIEW_CARD_ICON_SIZE)
                if icon is not None:
                    card.blit(icon, icon.get_rect(center=(icon_x, layout.PREVIEW_ICON_TOP + layout.PREVIEW_CARD_ICON_SIZE[1] // 2)))
                stats_top = layout.PREVIEW_STATS_TOP
            else:
                shape = rules.unit_shape(name, self.library)
                width, height = layout.UNIT_SHAPE_SIZES[shape]
                icon_scale = min(layout.EDIT_ICON_MAX_SCALE, layout.EDIT_ICON_SIZE[0] / width, layout.EDIT_ICON_SIZE[1] / height)
                sprites.draw_unit_shape(card, shape, (icon_x, layout.EDIT_ICON_TOP + layout.EDIT_ICON_SIZE[1] // 2),
                                0 if side == 0 else math.pi, layout.TEAM_COLORS[side], scale=icon_scale,
                                artwork=self.battle_artwork[name])
                # One line beside the gear button; longer names end in an ellipsis.
                label = queries.get_unit_display_name(name, self.library)
                name_width = layout.CARD_SIZE[0] - 2 * layout.CARD_INSET - layout.CARD_EDIT_SIZE - layout.CARD_EDIT_INSET
                card.blit(font.render(fit_text(label, font, name_width), True, c.UI_TEXT_BRIGHT), (layout.CARD_INSET, layout.CARD_NAME_TOP))
                stats_top = layout.EDIT_STATS_TOP
            self._draw_health_bar(card, unit)
            attack = rules.division_attack(unit, self.library)
            entries = [(icon, queries.format_number(value)) for icon, value in (
                (c.ICON_HEALTH, unit["health"]), (c.ICON_ATTACK, attack), (c.ICON_DEFENSE, unit["defense"]))]
            # A one-pixel row width puts each stat on its own line.
            ui_elements.draw_wrapped_icon_row(
                card, font, entries, layout.CARD_SIZE[0] - layout.CARD_STATS_WIDTH, stats_top, c.UI_TEXT_LIGHT,
                1, line_height=layout.CARD_STAT_ROW_HEIGHT, icon_size=layout.CARD_STAT_ICON_SIZE)
            self.card_surfaces[key] = card
        return self.card_surfaces[key]

    def _draw_roster_card(self, surface, rect, side, unit, *, hovered=False, pressed=False, selected=False):
        if self._roster_reorderable(side):
            color = c.UI_COLORS["blue" if side == 0 else "red"][0]
            if side == 0 and self.controlled_index is not None and unit is self.rosters[0][self.controlled_index]:
                color = tuple(min(255, channel + layout.CONTROLLED_CARD_BRIGHTNESS) for channel in color)
            ui_elements.draw_pixel_button(surface, rect, color, hovered=hovered, pressed=pressed, selected=selected)
        surface.blit(self.card_surfaces[self._card_key(side, unit)], rect)

    def _draw_rosters(self, surface):
        pointer = pygame.mouse.get_pos()
        for side, top in enumerate(layout.PANEL_TOPS):
            panel = pygame.Rect(layout.PANEL_X, top, layout.PANEL_WIDTH, layout.PANEL_HEIGHT)
            ui_elements.draw_pixel_panel(surface, panel, (39, 44, 58), (15, 19, 27))
            surface.blit(self.roster_labels[side], (panel.x + layout.ROSTER_INSET, panel.y + 14))
            old_clip = surface.get_clip()
            surface.set_clip(old_clip.clip(self.panes[side]))
            for index, unit in enumerate(self.rosters[side]):
                rect = self.card_rect(side, index)
                if not rect.colliderect(self.panes[side]):
                    continue
                if self.drag is not None and self.drag[0] == side and self.drag[1] == index and self.drag[3]:
                    continue
                pressed = self.drag is not None and self.drag[:2] == [side, index]
                selected = self.selected[side] == index or index in self.group[side]
                hovered = self.panes[side].collidepoint(pointer) and rect.collidepoint(pointer) and (self.drag is None or pressed)
                self._draw_roster_card(surface, rect, side, unit, hovered=hovered or (self.mode == "setup" and selected), pressed=pressed, selected=selected)
                if self.mode == "setup":
                    button = self.unit_buttons[side, index]
                    self._position_edit_button(button, rect)
                    button.draw(surface)
                if side == 0 and self.controlled_index == index:
                    sprites.draw_player_arrow(surface, (rect.x + layout.CARD_INSET + layout.CARD_LEFT_WIDTH // 2, rect.y + layout.CONTROLLED_ARROW_Y), 0)
            surface.set_clip(old_clip)
            self.draw_list_scrollbar(surface, self.panes[side].x, self.panes[side].bottom + 10,
                                     layout.ROSTER_WIDTH, width=layout.SCROLLBAR_HEIGHT, scroll=self._roster_scroll(side))
        if self.drag is not None and self.drag[3]:
            side, index, origin, active = self.drag
            card = self.card_surfaces[self._card_key(side, self.rosters[side][index])]
            rect = card.get_rect(center=pygame.mouse.get_pos())
            self._draw_roster_card(surface, rect, side, self.rosters[side][index], hovered=True, pressed=True)
            if self.mode == "setup":
                button = self.unit_buttons[side, index]
                self._position_edit_button(button, rect)
                button.draw(surface)
            if side == 0 and self.controlled_index == index:
                sprites.draw_player_arrow(surface, (rect.x + layout.CARD_INSET + layout.CARD_LEFT_WIDTH // 2, rect.y + layout.CONTROLLED_ARROW_Y), 0)
        if self.marquee is not None:
            side, origin, current = self.marquee
            if math.dist(origin, current) >= layout.DRAG_THRESHOLD:
                pygame.draw.rect(surface, layout.TEAM_COLORS[side], self._marquee_rect(origin, current), 1)
