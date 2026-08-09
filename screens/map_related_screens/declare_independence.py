import pygame
import copy
from gameState import MapOverlayScreen
import data.constants as c
from ui.bars import ui_bars
from ui import text_utils
from ui_elements import Button, process_text_input
from map_logic.rendering.font_manager import fonts
from data import queries
from map_logic.system32 import turn_manager

# Longest core name shown on a selection button before it is ellipsised.
CORE_NAME_MAX_CHARS = 15

class Declare_Independence_Screen(MapOverlayScreen):
    overlay_alpha = 200
    input_y = 200
    input_rect_x = 400

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(c.SCREEN_WIDTH // 2 - 350, c.SCREEN_HEIGHT // 2 - 200, 700, 420))
        self.bg_color = (40, 20, 20)
        self.new_country_name = "Free Republic"
        self.new_country_color = [200, 50, 50]
        self.active_input = False
        self.selected_core = None
        self.available_cores = []

        if self.map_screen.player_unit:
            for prov in self.map_screen.map_data.values():
                if self.map_screen.player_unit in prov.get("units", []):
                    self.available_cores = [core for core in prov.get("cores", []) if core not in c.UNPLAYABLE_NATIONS]
                    break

        self.refresh_ui()

    @property
    def name_input_rect(self):
        return pygame.Rect(self.panel_rect.x + 30, self.panel_rect.y + self.input_y + 80, self.input_rect_x, 40)

    def select_core(self, core_tag):
        self.selected_core = core_tag
        if core_tag is None:
            self.new_country_name = "Free Republic"
        else:
            core_name = self.map_screen.nation_data.get(core_tag, {}).get("name", core_tag)
            self.new_country_name = f"Free {core_name}"
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_screen)]
        
        panel_x, panel_y = self.panel_rect.topleft

        self.elements.append(Button(c.SCREEN_WIDTH // 2 - 120, panel_y + 350, "medium", "green", "Confirm", self.confirm_independence))
        self.elements.append(Button(panel_x + 80, panel_y + self.input_y + 150, "small", "orange", "Pick Color", self.pick_color))
        
        btn_x = panel_x + 450
        btn_y = panel_y + 80
        
        color_none = "green" if self.selected_core is None else "blue"
        self.elements.append(Button(btn_x, btn_y, "medium", color_none, "None", lambda: self.select_core(None)))
        
        for i, core_tag in enumerate(self.available_cores):
            core_name = self.map_screen.nation_data.get(core_tag, {}).get("name", core_tag)
            display_name = text_utils.truncate_chars(core_name, CORE_NAME_MAX_CHARS)
            color_core = "green" if self.selected_core == core_tag else "blue"
            self.elements.append(Button(btn_x, btn_y + 60 * (i + 1), "medium", color_core, display_name, lambda ct=core_tag: self.select_core(ct)))

    def pick_color(self):
        def on_confirm(color):
            self.new_country_color = list(color)
            self.refresh_ui()
        queries.open_color_picker(self, "Choose Country Color", tuple(self.new_country_color), on_confirm)

    def confirm_independence(self):
        if not self.new_country_name.strip():
            self.map_screen.show_feedback("Please enter a name!")
            return
            
        unit = self.map_screen.player_unit
        if not unit:
            self.map_screen.show_feedback("Error: No tactical unit found.")
            return
            
        old_tag = self.map_screen.player_country
        
        # 1. Create new tag safely avoiding duplicates
        base_tag = self.new_country_name.strip()
        new_tag = base_tag
        suffix = 1
        while new_tag in self.map_screen.nation_data:
            new_tag = f"{base_tag} {suffix}"
            suffix += 1
            
        old_data = self.map_screen.nation_data.get(old_tag, {})
        new_data = {
            "name": base_tag,
            "color": self.new_country_color,
            "is_playable": True,
            "research": copy.deepcopy(old_data.get("research", {})),
            "at_war_with": [old_tag] if old_tag not in c.UNPLAYABLE_NATIONS else [],
            "allied_with": [],
            "pending_diplomacy": {},
            "diplo_responses": {},
            "claims": [],
            "claim_queue": [],
            "revoke_queue": [],
            "return_queue": [],
            "puppets": [],
            "master": "",
            "puppet_type": "",
            "faction": "",
            "is_faction_leader": False,
            "manpower": self.map_screen.unit_economy.get("manpower", 0),
            "materials": self.map_screen.unit_economy.get("materials", 0),
            "fuel": self.map_screen.unit_economy.get("fuel", 0)
        }
        self.map_screen.nation_data[new_tag] = new_data
        
        # Force bidirectional war
        if old_tag not in c.UNPLAYABLE_NATIONS:
            self.map_screen.nation_data[old_tag].setdefault("at_war_with", []).append(new_tag)
            
        # 2. Grant the tile the unit is currently standing on
        unit_prov = None
        for prov in self.map_screen.map_data.values():
            if unit in prov.get("units", []):
                unit_prov = prov
                break
                
        if unit_prov:
            from map_logic.system32 import edit_province_ownership
            edit_province_ownership.conquer_province(self.map_screen, unit_prov, new_tag)
            edit_province_ownership.add_core(self.map_screen, unit_prov, new_tag)
            if old_tag not in c.UNPLAYABLE_NATIONS:
                edit_province_ownership.add_claim(self.map_screen, unit_prov, old_tag)
                
            if self.selected_core:
                for prov in self.map_screen.map_data.values():
                    if self.selected_core in prov.get("cores", []) and prov != unit_prov:
                        if new_tag not in prov.setdefault("cores", []):
                            prov["cores"].insert(0, new_tag)
                
        # 3. Reassign ownership
        unit["owner"] = new_tag
        
        # 4. Filter queued moves, retaining systemic conversions/repairs
        order = unit.get("order", {})
        if isinstance(order, dict) and order.get("type") == "MOVE":
            unit["order"]["path"] = []
            
        # 5. Escalate to strategic mode as the new leader
        self.map_screen.tactical_mode = False
        self.map_screen.player_country = new_tag
        
        if old_tag in self.map_screen.active_players:
            idx = self.map_screen.active_players.index(old_tag)
            self.map_screen.active_players[idx] = new_tag
            
        from map_logic.diplomacy.diplomacy_events import log_global_event
        log_global_event(self.map_screen.nation_data, f"{base_tag} has declared its independence from {old_tag}!")
        
        self.map_screen.nation_colors[new_tag] = tuple(self.new_country_color)
        
        # 6. Kick off the AI response/turn processing immediately
        turn_manager.advance_time(self.map_screen)
        
        self.done = True

    def handle_back_key(self):
        # Escape leaves the name box before it leaves the screen.
        if self.active_input:
            self.active_input = False
        else:
            self.exit_screen()

    def additional_events(self, event):
        super().additional_events(event)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.active_input = self.name_input_rect.collidepoint(event.pos)

        elif event.type == pygame.KEYDOWN and self.active_input:
            self.new_country_name, status = process_text_input(event, self.new_country_name, max_length=c.COUNTRY_NAME_MAX_LENGTH)
            if status == "SUBMIT":
                self.confirm_independence()
            elif status == "CANCEL":
                self.active_input = False

    def draw_content(self, surface):
        panel_rect = self.panel_rect
        ui_bars.draw_modal_box(surface, panel_rect, bg_color=(40, 30, 30), border_color=(255, 50, 50), border_width=3)
        ui_bars.draw_centered_title(surface, "Declare Independence", panel_rect.y + 20)
        
        font = fonts.get("normal")
        desc = [
            "Declaring independence will permanently separate",
            "your unit from its host country. You will form a",
            "new nation and immediately enter a state of war",
            "with your former commanders.",
            "",
            "All queued moves will be cancelled.",
            "Tactical mode will end."
        ]
        
        y_off = panel_rect.y + 80
        for line in desc:
            txt = font.render(line, True, c.UI_TEXT_LIGHT)
            surface.blit(txt, (panel_rect.x + 30, y_off))
            y_off += 20
            
        surface.blit(font.render("Country Name:", True, (255, 255, 255)), (panel_rect.x + 30, panel_rect.y + self.input_y + 60))
        surface.blit(font.render("Claim Heritage (Cores):", True, c.COLOR_GOLD_HIGHLIGHT), (panel_rect.x + 450, panel_rect.y + 60))
        
        input_rect = self.name_input_rect
        pygame.draw.rect(surface, (60, 60, 80) if self.active_input else (30, 30, 40), input_rect)
        pygame.draw.rect(surface, (200, 200, 200), input_rect, 2)

        name_surf = font.render(self.new_country_name + ("|" if self.active_input else ""), True, (255, 255, 255))
        surface.blit(name_surf, (input_rect.x + 10, input_rect.y + 10))

        color_rect = pygame.Rect(panel_rect.x + 30, panel_rect.y + self.input_y + 150, 40, 40)
        pygame.draw.rect(surface, self.new_country_color, color_rect)
        pygame.draw.rect(surface, (255, 255, 255), color_rect, 2)