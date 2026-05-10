import pygame
from gameState import GameState
import data.constants as c
from ui_elements import Button
from map_logic.rendering.font_manager import fonts
from data import queries
from map_logic.diplomacy import diplomacy_logic

class Faction_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (30, 35, 40)
        self.map_screen = None

    def start_faction(self, map_ref):
        self.map_screen = map_ref
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_to_map)]

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
        btn_leave.disabled = is_leader  # Leaders cannot 'leave', they must disband or transfer (which isn't implemented here)
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

    def leave_faction(self):
        msg = diplomacy_logic.toggle_diplomacy_action(self.map_screen.nation_data, self.map_screen.player_country, self.map_screen.player_country, "LEAVE_FACTION", "")
        self.map_screen.show_feedback(msg)
        self.refresh_ui()

    def disband_faction(self):
        msg = diplomacy_logic.toggle_diplomacy_action(self.map_screen.nation_data, self.map_screen.player_country, self.map_screen.player_country, "DISBAND_FACTION", "")
        self.map_screen.show_feedback(msg)
        self.refresh_ui()

    def view_territories(self):
        self.next_state, self.done = "FACTION_TERRITORIES", True

    def additional_draw(self, surface):
        if not self.map_screen: return

        player_country = self.map_screen.player_country
        nation_data = self.map_screen.nation_data
        my_faction = nation_data.get(player_country, {}).get("faction", "")

        font_title = fonts.get("title")
        font_heading = fonts.get("heading1")
        font_normal = fonts.get("normal")

        # Failsafe if accessed without a faction
        if not my_faction:
            txt = font_title.render("No Faction", True, (150, 150, 150))
            surface.blit(txt, (c.SCREEN_WIDTH // 2 - txt.get_width() // 2, 100))
            return

        title = font_title.render(f"Faction: {my_faction}", True, (255, 255, 255))
        surface.blit(title, (c.SCREEN_WIDTH // 2 - title.get_width() // 2, 40))

        members = queries.get_faction_members(my_faction, nation_data)
        leader = queries.get_faction_leader(my_faction, nation_data)

        leader_txt = font_heading.render(f"Leader: {nation_data.get(leader, {}).get('name', leader)}", True, (255, 215, 0))
        surface.blit(leader_txt, (c.SCREEN_WIDTH // 2 - leader_txt.get_width() // 2, 120))

        list_start_y = 200
        surface.blit(font_heading.render("Members:", True, (200, 200, 200)), (c.SCREEN_WIDTH // 2 - 300, list_start_y))

        for i, member in enumerate(members):
            m_name = nation_data.get(member, {}).get("name", member)
            txt = font_normal.render(f"- {m_name}", True, (255, 255, 255))
            surface.blit(txt, (c.SCREEN_WIDTH // 2 - 280, list_start_y + 40 + (i * 30)))

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()


class Faction_Territories_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 40)
        self.map_screen = None

    def start_view(self, map_ref):
        self.map_screen = map_ref
        self.map_screen.refresh_faction_territories_map()
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_to_faction)]

    def additional_draw(self, surface):
        if not self.map_screen: return

        # Temporarily alter map_screen state to draw cleanly
        prev_layer = self.map_screen.base_layer
        prev_active = self.map_screen.active_map
        
        self.map_screen.base_layer = "FACTION_TERRITORIES"
        self.map_screen.active_map = self.map_screen.faction_territories_map
        
        self.map_screen.hide_raised_rect = True
        self.map_screen.hide_tooltip = True
        self.map_screen.hide_resource_hud = True
        self.map_screen.hide_minimap = True
        
        self.map_screen.additional_draw(surface)
        
        self.map_screen.hide_raised_rect = False
        self.map_screen.hide_tooltip = False
        self.map_screen.hide_resource_hud = False
        self.map_screen.hide_minimap = False
        
        self.map_screen.base_layer = prev_layer
        self.map_screen.active_map = prev_active
        
        # Title
        font = fonts.get("heading1")
        title = font.render("Faction Territories (Pre-War Borders)", True, (255, 255, 255))
        surface.blit(title, (c.SCREEN_WIDTH//2 - title.get_width()//2, c.TOP_BAR_UI_CENTER_Y))

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
        
        # Camera controls
        if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
            # Check if mouse is on top UI bar
            mx, my = pygame.mouse.get_pos()
            on_ui = self.map_screen.top_bar_rect.collidepoint(mx, my) or self.map_screen.bot_bar_rect.collidepoint(mx, my)
            self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

    def exit_to_faction(self):
        self.next_state, self.done = "FACTION", True

    def handle_back_key(self):
        self.exit_to_faction()