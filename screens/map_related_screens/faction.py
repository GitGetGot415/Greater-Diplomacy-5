import pygame
from gameState import GameState, resolve_keybind
import data.constants as c
from ui.bars import ui_bars
from ui.flag_icons import draw_flag_centered
from ui_elements import Button, process_text_input, make_back_button, draw_text_box
from map_logic.rendering.font_manager import fonts
from map_logic.diplomacy import faction_actions, faction_leadership
from data import queries


# The roster deliberately ends above the action buttons.  Its content can grow
# freely; this fixed viewport, rather than a growing sequence of row positions,
# is what keeps a large faction usable at every screen height.
ROSTER_LEFT_OFFSET = 300
ROSTER_WIDTH = 600
ROSTER_TOP_Y = 160
ROSTER_BOTTOM_BUTTON_GAP = 245
ROSTER_ROW_HEIGHT = 30
ROSTER_SECTION_GAP = 16

class Faction_Screen(GameState):
    back_state = "MAP"

    def __init__(self):
        super().__init__()
        self.bg_color = (30, 35, 40)
        self.map_screen = None
        self.is_renaming = False
        self.new_faction_name = ""
        self.scroll_y = 0
        self.max_scroll = 0
        self.scroll_content_rect = None

    def start_faction(self, map_ref):
        self.map_screen = map_ref
        self.is_renaming = False
        self.new_faction_name = ""
        self.scroll_y = 0
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]

        if not self.map_screen: return

        player_country = self.map_screen.player_country
        nation_data = self.map_screen.nation_data
        my_faction = nation_data.get(player_country, {}).get("faction", "")

        if not my_faction:
            return

        is_leader = queries.is_faction_leader(player_country, nation_data)

        # Determine if there are pending actions
        pending_action, _ = queries.get_diplomatic_status(player_country, player_country, nation_data)

        # 1. Leave Faction Button
        leave_text = "Undo Leave" if pending_action == "LEAVE_FACTION" else "Leave Faction"
        leave_color = "red" if pending_action == "LEAVE_FACTION" else "orange"
        btn_leave = Button(c.SCREEN_WIDTH // 2 - 250, c.SCREEN_HEIGHT - 100, "medium", leave_color, leave_text, self.leave_faction)
        
        is_puppet = bool(nation_data.get(player_country, {}).get("master", ""))
        
        if is_leader:
            btn_leave.disabled = True
            btn_leave.text = "Leaders Cannot Leave"
        elif is_puppet:
            btn_leave.apply_state(enabled=False, text="Puppets Cannot Leave")
            
        self.elements.append(btn_leave)

        # 2. Disband Faction Button
        disband_text = "Undo Disband" if pending_action == "DISBAND_FACTION" else "Disband Faction"
        disband_color = "orange" if pending_action == "DISBAND_FACTION" else "red"
        btn_disband = Button(c.SCREEN_WIDTH // 2 + 50, c.SCREEN_HEIGHT - 100, "medium", disband_color, disband_text, self.disband_faction)
        btn_disband.disabled = not is_leader
        self.elements.append(btn_disband)

        # 3. Faction Territories Button
        btn_territories = Button(c.SCREEN_WIDTH // 2 - 100, c.SCREEN_HEIGHT - 160, "medium", "blue", "Faction Territories", self.view_territories)
        self.elements.append(btn_territories)
        
        # 4. Rename Faction Button
        if is_leader and not self.is_renaming:
            btn_rename = Button(c.SCREEN_WIDTH // 2 - 100, c.SCREEN_HEIGHT - 220, "medium", "blue", "Rename Faction", self.start_rename)
            self.elements.append(btn_rename)

        # 5. Claim Leadership Button
        #
        # Shown to every member rather than only to one already qualified, so a
        # player can find out that the chair is takeable at all -- and read how
        # far off they are. A disabled button carrying its own reason is the
        # idiom the two above already use.
        if not is_leader:
            self.elements.append(self._claim_button(pending_action))

    def _claim_button(self, pending_action):
        """Take the chair, or the reason you cannot yet.

        The wait is stated as a fact about the world -- "stronger for 3 of 6
        turns" -- rather than counted down silently, because a mechanic whose
        only visible symptom is a button that turns on one day is one nobody
        finds.
        """
        player = self.map_screen.player_country
        queued = pending_action == "CLAIM_FACTION_LEADERSHIP"
        text = "Undo Claim" if queued else "Claim Leadership"
        btn = Button(c.SCREEN_WIDTH // 2 - 100, c.SCREEN_HEIGHT - 220, "medium",
                     "red" if queued else "orange", text, self.claim_leadership)

        if queued:
            return btn

        state = faction_leadership.standing(self.map_screen, player)
        if state is None:
            nation_data = self.map_screen.nation_data
            if nation_data.get(player, {}).get("master", ""):
                btn.apply_state(enabled=False, text="Puppets Cannot Claim")
            elif not queries.get_faction_leader(
                    nation_data.get(player, {}).get("faction", ""), nation_data):
                btn.apply_state(enabled=False, text="Faction Needs A Leader")
            else:
                btn.apply_state(enabled=False, text="Cannot Claim Leadership")
            return btn

        held, needed, ahead = state
        if held >= needed:
            return btn
        if not ahead:
            btn.apply_state(enabled=False, text=f"Need {c.FACTION_CHALLENGE_MARGIN}x The Leader")
        else:
            btn.apply_state(enabled=False, text=f"Stronger For {held} Of {needed} Turns")
        return btn

    def claim_leadership(self):
        self.queue_diplomacy_action(self.map_screen.player_country,
                                    "CLAIM_FACTION_LEADERSHIP")

    def leave_faction(self):
        self.queue_diplomacy_action(self.map_screen.player_country, "LEAVE_FACTION")

    def disband_faction(self):
        self.queue_diplomacy_action(self.map_screen.player_country, "DISBAND_FACTION")

    def view_territories(self):
        self.next_state, self.done = "FACTION_TERRITORIES", True
        
    def start_rename(self):
        self.is_renaming = True
        player_country = self.map_screen.player_country
        self.new_faction_name = self.map_screen.nation_data.get(player_country, {}).get("faction", "")
        self.refresh_ui()

    def confirm_rename(self):
        if not self.map_screen: return
        if getattr(self.map_screen, "realtime_multiplayer", False):
            from map_logic.diplomacy import player_diplomacy_actions
            if not player_diplomacy_actions.can_edit_diplomacy(self.map_screen):
                return
        player_country = self.map_screen.player_country
        old_name = self.map_screen.nation_data.get(player_country, {}).get("faction", "")
        new_name = self.new_faction_name.strip()
        
        if new_name and old_name and new_name != old_name:
            renamed = faction_actions.rename_faction(
                self.map_screen.nation_data, player_country, old_name, new_name)
            if renamed:
                # A tournament move otherwise carries only the renaming
                # leader's nation record.  Keep an explicit, host-validated
                # command so every member is renamed when the host imports it.
                if getattr(self.map_screen, "multiplayer_mode", False):
                    pending = getattr(self.map_screen,
                                      "multiplayer_pending_faction_renames", None)
                    if pending is None:
                        pending = []
                        self.map_screen.multiplayer_pending_faction_renames = pending
                    pending.append({"old_name": old_name, "new_name": new_name})

                self.map_screen.show_feedback(f"Faction renamed to {new_name}")
                from map_logic.rendering import country_names
                country_names.clear_country_name_cache(self.map_screen)
                self.map_screen.refresh_diplomacy_maps()
            else:
                self.map_screen.show_feedback(
                    "Faction names must be unique, and only its leader may rename it.")
                
        self.is_renaming = False
        self.refresh_ui()

    def cancel_rename(self):
        self.is_renaming = False
        self.refresh_ui()
        
    def additional_events(self, event):
        if self.handle_list_scroll(event, content_rect_attr="scroll_content_rect"):
            return
        if self.is_renaming:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    self.confirm_rename()
                elif event.key == resolve_keybind(self, "BACK", pygame.K_ESCAPE):
                    self.cancel_rename()
                else:
                    self.new_faction_name, _ = process_text_input(event, self.new_faction_name, max_length=40)

    def additional_draw(self, surface):
        if not self.map_screen: return

        player_country = self.map_screen.player_country
        nation_data = self.map_screen.nation_data
        my_faction = nation_data.get(player_country, {}).get("faction", "")

        font_title = fonts.get("title")
        font_heading = fonts.get("heading1")
        font_normal = fonts.get("normal")

        if not my_faction:
            ui_bars.draw_centered_title(surface, "No Faction", 100, font_preset="title", color=(150, 150, 150))
            return

        if self.is_renaming:
            title_rect = pygame.Rect(c.SCREEN_WIDTH // 2 - 200, 30, 400, 50)
            draw_text_box(surface, title_rect, self.new_faction_name, active=True,
                          font=font_title)
            
            instr = font_normal.render("Enter: Save | Esc: Cancel", True, c.UI_TEXT_LIGHT)
            surface.blit(instr, (c.SCREEN_WIDTH // 2 - instr.get_width() // 2, 90))
        else:
            ui_bars.draw_centered_title(surface, f"Faction: {my_faction}", 40, font_preset="title")
            
        # Alphabetize what the player reads, not the internal nation IDs.  The
        # latter can differ after a rename or imported save and should never
        # determine the visible roster order.
        members = sorted(
            queries.get_faction_members(my_faction, nation_data),
            key=lambda nation: (queries.get_country_display_name(nation, nation_data).casefold(),
                                nation),
        )
        leader = queries.get_faction_leader(my_faction, nation_data)

        leader_name = queries.get_country_display_name(leader, nation_data)
        leader_txt = font_heading.render(f"Leader: {leader_name}", True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(leader_txt, (c.SCREEN_WIDTH // 2 - leader_txt.get_width() // 2, 120))

        self._draw_roster(surface, nation_data, my_faction, members,
                          font_heading, font_normal)

    def _draw_roster(self, surface, nation_data, faction, members,
                     font_heading, font_normal):
        """Draw a clipped, scrollable faction roster and active challenges."""
        standings = faction_leadership.contenders(nation_data, faction)
        left = c.SCREEN_WIDTH // 2 - ROSTER_LEFT_OFFSET
        bottom = c.SCREEN_HEIGHT - ROSTER_BOTTOM_BUTTON_GAP
        self.scroll_content_rect = pygame.Rect(left, ROSTER_TOP_Y,
                                                ROSTER_WIDTH, bottom - ROSTER_TOP_Y)

        challenge_height = 0
        if standings:
            challenge_height = ROSTER_ROW_HEIGHT * (len(standings) + 1) + ROSTER_SECTION_GAP
        content_height = challenge_height + ROSTER_ROW_HEIGHT * (len(members) + 1)
        self.max_scroll = min(0, self.scroll_content_rect.height - content_height)
        self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))

        y = self.scroll_content_rect.top + self.scroll_y
        with ui_bars.clip_scroll_region(surface, self.scroll_content_rect):
            if standings:
                heading = font_normal.render("Building a claim on the leadership:", True,
                                             c.MSG_NOTIFICATION_COLOR)
                surface.blit(heading, (left, y))
                y += ROSTER_ROW_HEIGHT
                for nation, held, needed in standings:
                    name = queries.get_country_display_name(nation, nation_data)
                    if held >= needed:
                        when = "can claim it now"
                    else:
                        remaining = needed - held
                        when = (f"{remaining} more turn"
                                f"{'' if remaining == 1 else 's'} of holding it")
                    text_x = draw_flag_centered(surface, nation, nation_data, left + 4,
                                                 y, ROSTER_ROW_HEIGHT)
                    line = font_normal.render(f"{name} -- {when}", True, c.UI_TEXT_LIGHT)
                    surface.blit(line, (text_x, y))
                    y += ROSTER_ROW_HEIGHT
                y += ROSTER_SECTION_GAP

            surface.blit(font_heading.render("Members:", True, c.UI_TEXT_LIGHT), (left, y))
            y += ROSTER_ROW_HEIGHT
            for member in members:
                text_x = draw_flag_centered(surface, member, nation_data, left + 4,
                                             y, ROSTER_ROW_HEIGHT)
                name = queries.get_country_display_name(member, nation_data)
                txt = font_normal.render(name, True, (255, 255, 255))
                surface.blit(txt, (text_x, y))
                y += ROSTER_ROW_HEIGHT

        if self.max_scroll < 0:
            self.draw_list_scrollbar(surface, self.scroll_content_rect.right - 15,
                                     self.scroll_content_rect.top,
                                     self.scroll_content_rect.height, width=12)

    def handle_back_key(self):
        # Escape cancels an in-progress rename before it leaves the screen.
        if self.is_renaming:
            self.cancel_rename()
        else:
            self.exit_screen()

class Faction_Territories_Screen(GameState):
    back_state = "FACTION"

    def __init__(self):
        super().__init__()
        self.map_screen = None

    def start_view(self, map_ref):
        self.map_screen = map_ref
        self.map_screen.refresh_map_layers("faction_territories")
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]

    def draw_background(self, surface):
        # Same live flat/checkerboard ocean background as the main map
        # (see Map_Screen.draw_background) instead of the generic always-on
        # checkerboard every other bg_image_path-less screen gets.
        if self.map_screen:
            self.map_screen.draw_background(surface)
        else:
            super().draw_background(surface)

    def additional_draw(self, surface):
        if not self.map_screen: return

        prev_layer = self.map_screen.base_layer
        prev_active = self.map_screen.active_map
        
        self.map_screen.base_layer = "FACTION_TERRITORIES"
        self.map_screen.active_map = self.map_screen.faction_territories_map
        
        self.map_screen.draw_clean_map_background(surface)
        
        self.map_screen.base_layer = prev_layer
        self.map_screen.active_map = prev_active
        
        ui_bars.draw_centered_title(surface, "Faction Territories (Pre-War Borders)", c.TOP_BAR_UI_CENTER_Y)

    def update(self):
        super().update()
        if self.map_screen:
            self.map_screen.camera.update(self.map_screen, c.SCREEN_HEIGHT)

    def handle_events(self, events):
        for event in events:
            super().handle_events([event])
            self.additional_events(event)

    def additional_events(self, event):
        if not self.map_screen: return
        
        if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
            mx, my = pygame.mouse.get_pos()
            on_ui = self.map_screen.top_bar_rect.collidepoint(mx, my) or self.map_screen.bot_bar_rect.collidepoint(mx, my)
            self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

