import pygame
from gameState import GameState
import data.constants as c
from ui_elements import Button, Slider
from map_logic.rendering.font_manager import fonts
from data import queries

class Economy_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (30, 35, 40)
        self.map_screen = None

    def start_economy(self, map_ref):
        self.map_screen = map_ref
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_to_map)]
        
        # New Conversion Slider positioned below the resource rows
        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        
        # Fetch the max allowed conversion limit based on tech
        max_allowed = queries.get_max_fuel_conversion(p_data)
        
        # Safely clamp the loaded slider value just in case they lost tech
        slider_val = min(p_data.get("mat_to_fuel_slider", 0.0), max_allowed)
        p_data["mat_to_fuel_slider"] = slider_val
        
        conscript_val = p_data.get("conscription_slider", 1.0)
        p_data["conscription_slider"] = conscript_val
        
        self.elements.append(Slider(c.SCREEN_WIDTH // 2 - 200, c.ECON_CONSCRIPTION_BTN_Y, 400, "Conscription (Keep Manpower %)", conscript_val, self.set_conscription, visual_max=1.0, allowed_max=1.0))

        self.elements.append(Slider(c.SCREEN_WIDTH // 2 - 200, c.ECON_CONVERT_BTN_Y, 400, "Convert % Mats to Fuel", slider_val, self.set_conversion, visual_max=c.MAX_CONVERSION_SLIDER_VAL, allowed_max=max_allowed))

    def set_conscription(self, val):
        if not self.map_screen: return
        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        p_data["conscription_slider"] = val

    def set_conversion(self, val):
        if not self.map_screen: return
        if not self.map_screen: return
        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        p_data["mat_to_fuel_slider"] = val

    def additional_draw(self, surface):
        if not self.map_screen: return
        
        # Title
        font_title = fonts.get("title")
        title = font_title.render("National Economy", True, (255, 255, 255))
        surface.blit(title, (c.SCREEN_WIDTH // 2 - title.get_width() // 2, 40))
        
        p_data = self.map_screen.nation_data[self.map_screen.player_country]

        # Cache the economy to prevent 60 FPS global recalculations
        current_sliders = (p_data.get("conscription_slider", 1.0), p_data.get("mat_to_fuel_slider", 0.0))
        if not hasattr(self, 'last_econ_state') or self.last_econ_state != current_sliders or self.map_screen.time_manager.total_turns != getattr(self, 'last_econ_turn', -1):
            self.econ_cache = queries.get_economy_projections(self.map_screen.player_country, self.map_screen.map_data, self.map_screen.nation_data)
            self.last_econ_state = current_sliders
            self.last_econ_turn = self.map_screen.time_manager.total_turns
        
        econ_tuple = self.econ_cache

        if len(econ_tuple) == 3:
            total_inc, upkeep, breakdown = econ_tuple
        else:
            total_inc, upkeep = econ_tuple
            breakdown = {k: {"core":0, "non_core":0, "buildings":0, "resources":0, "conversion":0} for k in ["manpower", "materials", "fuel"]}
            
        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        
        font_large = fonts.get("heading1")
        font_med = fonts.get("heading2")
        font_small = fonts.get("normal")
        
        y_offset = 120
        resources = [
            ("manpower", "Manpower", p_data.get('manpower', 0), (100, 200, 255)),
            ("materials", "Materials", p_data.get('materials', 0), (180, 180, 180)),
            ("fuel", "Fuel", p_data.get('fuel', 0), (200, 100, 255))
        ]
        
        for res_key, name, current, color in resources:
            inc = total_inc.get(res_key, 0)
            exp = upkeep.get(res_key, 0)
            bd = breakdown.get(res_key, {})
            net = inc - exp
            net_str = f"+{int(net)}" if net >= 0 else str(int(net))
            
            # Row Background (Made taller to fit details)
            row_rect = pygame.Rect(c.SCREEN_WIDTH // 2 - 600, y_offset, 1200, 100)
            pygame.draw.rect(surface, (40, 40, 50), row_rect)
            pygame.draw.rect(surface, (100, 100, 100), row_rect, 1)
            
            # Current Resource Amount
            surface.blit(font_large.render(f"{name}: {int(current)}", True, color), (row_rect.x + 20, row_rect.y + 15))
            
            # Stats Breakdown (Main)
            main_breakdown = f"Total Income: +{int(inc)}   |   Upkeep: -{int(exp)}   |   Net: {net_str}"
            surface.blit(font_med.render(main_breakdown, True, (200, 200, 200)), (row_rect.x + 350, row_rect.y + 18))
            
            # Detailed Breakdown
            detail_breakdown = f"Details -> Base: +{int(bd.get('base',0))}  |  Core: +{int(bd.get('core',0))}  |  Non-Core: +{int(bd.get('non_core',0))}  |  Buildings: +{int(bd.get('buildings',0))}  |  Resources: +{int(bd.get('resources',0))}"
            if bd.get('conscription', 0) != 0:
                cons_val = int(bd.get('conscription', 0))
                sign = "+" if cons_val > 0 else ""
                label = "Unused Equipment Income" if cons_val > 0 else "Relaxed Conscription Cost"
                detail_breakdown += f"  |  {label}: {sign}{cons_val}"
            if bd.get('conversion', 0) != 0:
                conv_val = int(bd.get('conversion', 0))
                sign = "+" if conv_val > 0 else ""
                label = "Conversion Income" if conv_val > 0 else "Conversion Cost"
                detail_breakdown += f"  |  {label}: {sign}{conv_val}"
                
            if bd.get('siphon', 0) != 0:
                detail_breakdown += f"  |  Siphoned to Master: {int(bd.get('siphon', 0))}"
            if bd.get('siphon_income', 0) != 0:
                detail_breakdown += f"  |  Siphon Income: +{int(bd.get('siphon_income', 0))}"

            surface.blit(font_small.render(detail_breakdown, True, (150, 150, 150)), (row_rect.x + 0, row_rect.y + 60))
            
            y_offset += 120

        # Draw dynamic conversion info below sliders
        man_lost = -breakdown.get("manpower", {}).get("conscription", 0)
        mat_gained = breakdown.get("materials", {}).get("conscription", 0)
        if man_lost > 0:
            cons_txt = font_small.render(f"Converting {int(man_lost)} Manpower -> {int(mat_gained)} Materials", True, (255, 215, 0))
            surface.blit(cons_txt, (c.SCREEN_WIDTH // 2 - cons_txt.get_width() // 2, c.ECON_CONSCRIPTION_BTN_Y + 25))

        mat_lost = -breakdown.get("materials", {}).get("conversion", 0)
        fuel_gained = breakdown.get("fuel", {}).get("conversion", 0)
        if mat_lost > 0:
            conv_txt = font_small.render(f"Converting {int(mat_lost)} Materials -> {int(fuel_gained)} Fuel", True, (255, 215, 0))
            surface.blit(conv_txt, (c.SCREEN_WIDTH // 2 - conv_txt.get_width() // 2, c.ECON_CONVERT_BTN_Y + 25))

    def handle_back_key(self):
        self.exit_to_map()

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True