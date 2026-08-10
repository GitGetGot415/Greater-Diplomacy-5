import pygame
import data.constants as c
from data import queries
from map_logic.diplomacy import diplomacy_messages
from gameState import MapOverlayScreen
from ui_elements import Button, make_back_button
from map_logic.rendering.font_manager import fonts
from ui.bars import ui_bars
from ui.screen_runner import _run_pygame_sub_screen
from screens.map_related_screens.diplomacy_screen_widgets import build_choice_button, draw_projected_peace_map


class Peace_Screen(MapOverlayScreen):
    overlay_alpha = 0

    def __init__(self, map_screen, target_nation):
        # Restructured to be a wide, short banner docked cleanly above the bottom UI bar
        super().__init__(map_screen, pygame.Rect(c.SCREEN_WIDTH//2 - 350, c.SCREEN_HEIGHT - 250, 700, 190))
        self.target_nation = target_nation

        my_wargoal = map_screen.nation_data.get(map_screen.player_country, {}).get("wargoals", {}).get(target_nation, {}).get("type", "")
        their_wargoal = map_screen.nation_data.get(target_nation, {}).get("wargoals", {}).get(map_screen.player_country, {}).get("type", "")

        self.terms = [
            c.PEACE_SURRENDER,
            c.PEACE_DEMAND_CLAIMS,
            c.PEACE_WHITE_PEACE
        ]

        self.terms_enabled = [
            True, # Surrender is always an option if at war
            my_wargoal in [c.WARGOAL_TAKE_CLAIMS, c.WARGOAL_NO_CB] or their_wargoal != "", # Allowed if we claimed, No CB, or if it's a defensive war!
            True
        ]

        # Check for existing peace offer
        pending = diplomacy_messages.get_pending(map_screen.nation_data, map_screen.player_country, target_nation)
        self.is_editing = pending.get("action") in ["PEACE_TREATY", "CEASEFIRE"]

        if self.is_editing:
            pending_msg = pending.get("message", "")
            self.selected_term_idx = 2 # Default to Ceasefire
            for i, term in enumerate(self.terms):
                if pending_msg.startswith(term) and self.terms_enabled[i]:
                    self.selected_term_idx = i
                    break

            # Catch raw CEASEFIRE actions from legacy behavior
            if pending.get("action") == "CEASEFIRE":
                self.selected_term_idx = 2
        else:
            self.selected_term_idx = 2 # Default to Ceasefire

        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Cancel", lambda: self.exit_screen())]

        term = self.terms[self.selected_term_idx]
        is_human = self.target_nation in self.map_screen.active_players

        if is_human:
            self.acceptance_text = "This is another player, whether they accept this deal or not is up to them."
            self.acceptance_color = (200, 200, 200)
        else:
            will_accept = queries.will_ai_accept_peace(self.target_nation, self.map_screen.player_country, term, self.map_screen.map_data, self.map_screen.nation_data)
            if will_accept:
                self.acceptance_text = "The AI will accept this peace deal."
                self.acceptance_color = c.COLOR_SUCCESS_GREEN
            else:
                self.acceptance_text = "The AI will REJECT this peace deal."
                self.acceptance_color = (255, 100, 100)

        # Place the 3 main terms left-to-right
        for i, term_str in enumerate(self.terms):
            self.elements.append(
                build_choice_button(self.panel_rect.centerx - 330 + (i * 220), self.panel_rect.y + 80,
                                    "medium", term_str, self.terms_enabled[i],
                                    self.selected_term_idx == i, lambda idx=i: self.select_term(idx))
            )

        confirm_text = "Update Offer" if self.is_editing else "Send Proposal"
        self.elements.append(Button(self.panel_rect.centerx - 100, self.panel_rect.y + 140, "medium", "green", confirm_text, self.confirm))

        if self.is_editing:
            self.elements.append(Button(self.panel_rect.right - 140, self.panel_rect.y + 140, "small", "red", "Cancel Offer", self.revoke_offer))

    def select_term(self, idx):
        if self.terms_enabled[idx]:
            self.selected_term_idx = idx
            self.refresh_ui()

    def revoke_offer(self):
        diplomacy_messages.clear_pending(self.map_screen.nation_data, self.map_screen.player_country,
                                         self.target_nation, only_actions=["PEACE_TREATY", "CEASEFIRE"])
        self.map_screen.show_feedback("Peace Offer Cancelled.")
        self.done = True

    def confirm(self):
        term = self.terms[self.selected_term_idx]
        action_type = "CEASEFIRE" if term == c.PEACE_WHITE_PEACE else "PEACE_TREATY"

        proposer = self.map_screen.player_country
        target = self.target_nation

        # Calculate and freeze territories into the message string
        frozen_ids = []
        if term == c.PEACE_DEMAND_CLAIMS:
            claims = self.map_screen.nation_data.get(proposer, {}).get("claims", [])
            for prov in self.map_screen.map_data.values():
                if prov.get("owner") == target and (prov["id"] in claims or proposer in prov.get("cores", [])):
                    frozen_ids.append(str(prov["id"]))
            if frozen_ids:
                term += f" (Territories demanded: {', '.join(frozen_ids)} + cores)"
            else:
                term += " (No territories demanded)"

        elif term == c.PEACE_SURRENDER:
            claims = self.map_screen.nation_data.get(target, {}).get("claims", [])
            for prov in self.map_screen.map_data.values():
                if prov.get("owner") == proposer and (prov["id"] in claims or target in prov.get("cores", [])):
                    frozen_ids.append(str(prov["id"]))
            if frozen_ids:
                term += f" (Territories surrendered: {', '.join(frozen_ids)} + cores)"
            else:
                term += " (No territories surrendered)"

        # Overwrites directly to bypass the toggle logic
        diplomacy_messages.set_pending(self.map_screen.nation_data, self.map_screen.player_country,
                                       self.target_nation, action_type, parameters=term, message=term)
        self.map_screen.show_feedback("Peace Offer Updated!" if self.is_editing else "Peace Offer Queued!")
        self.done = True

    def draw_content(self, surface):
        draw_projected_peace_map(surface, self.map_screen, self.terms[self.selected_term_idx],
                                 self.map_screen.player_country, self.target_nation)

        # Draw the Banner
        ui_bars.draw_modal_box(surface, self.panel_rect, bg_color=(30, 40, 30, 230), border_color=(50, 255, 50), border_width=3)
        ui_bars.draw_centered_title(surface, f"Peace Terms: {self.target_nation}", self.panel_rect.y + 15)

        small_font = fonts.get("normal")
        acc_surf = small_font.render(self.acceptance_text, True, self.acceptance_color)
        surface.blit(acc_surf, (self.panel_rect.centerx - acc_surf.get_width()//2, self.panel_rect.y + 50))


class View_Peace_Treaty_Screen(MapOverlayScreen):
    overlay_alpha = 0

    def __init__(self, map_screen, proposer):
        super().__init__(map_screen)
        self.proposer = proposer
        self.target = map_screen.player_country

        # Read the parameters directly from the proposed diplomacy message
        pending = diplomacy_messages.get_pending(map_screen.nation_data, self.proposer, self.target)
        self.peace_type = pending.get("parameters", pending.get("message", c.PEACE_WHITE_PEACE))

        self.elements = [make_back_button(self.exit_screen, style="map")]

    def draw_content(self, surface):
        draw_projected_peace_map(surface, self.map_screen, self.peace_type, self.proposer, self.target)

        # Utilize the helper to render the header string over the map preview safely
        ui_bars.draw_centered_title(surface, f"Projected Map: Peace Treaty from {self.proposer}", 30)


def open_peace_menu(map_screen, target_nation):
    _run_pygame_sub_screen(map_screen, Peace_Screen(map_screen, target_nation))

def open_view_peace_treaty_menu(map_screen, proposer):
    _run_pygame_sub_screen(map_screen, View_Peace_Treaty_Screen(map_screen, proposer))
