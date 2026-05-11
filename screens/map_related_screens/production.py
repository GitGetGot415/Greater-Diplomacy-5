# screens/map_related_screens/production.py

import pygame
import data.constants as c
from gameState import GameState
from ui_elements import Button, draw_resource_string, draw_combat_stats
from screens.map_related_screens import recruit_ui
from map_logic.rendering.font_manager import fonts
from map_logic.rendering import symbol_loader
from data import queries

class Production_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (25, 25, 25)
        self.target_province = None
        self.map_screen = None
        self.cancel_hitboxes = []
        
        self.unit_library = queries.get_unit_library()
        self.building_library = queries.get_building_library()
        self.tech_tree = queries.get_tech_tree()
        
        self.infantry_groups, self.tank_groups, self.navy_groups = self.get_ordered_groups()
        self.active_bars = []
        
        # Scroll variables
        self.scroll_y = 0
        self.target_scroll_y = 0
        self.max_scroll = 0

    def get_group_name(self, name):
        return queries.get_base_unit_name(name)

    def get_ordered_groups(self):
        infantry_groups, tank_groups, navy_groups = [], [], []
        for name, stats in self.unit_library.items():
            base = self.get_group_name(name)
            if stats.get("naval_unit", False):
                if base not in navy_groups: navy_groups.append(base)
            elif "Tank" in base or "Armored Car" in base:
                if base not in tank_groups: tank_groups.append(base)
            else:
                if base not in infantry_groups: infantry_groups.append(base)
        return infantry_groups, tank_groups, navy_groups

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        self.scroll_y = 0
        self.target_scroll_y = 0
        self.refresh_ui()

    def enforce_scroll_bounds(self):
        self.target_scroll_y = max(-self.max_scroll, min(self.target_scroll_y, 0))
        self.scroll_y = max(-self.max_scroll, min(self.scroll_y, 0))

    def update(self):
        super().update()
        if hasattr(self, 'target_scroll_y'):
            self.enforce_scroll_bounds()
            if abs(self.scroll_y - self.target_scroll_y) > 0.5:
                self.scroll_y += (self.target_scroll_y - self.scroll_y) * 0.15
                
                # Apply scroll to buttons
                for el in self.elements:
                    if getattr(el, 'is_scrollable', False):
                        el.rect.y = el.base_y + int(self.scroll_y)

    def refresh_ui(self):
        # The back button doesn't scroll
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_to_map)]
        
        current_buildings = self.target_province.get("buildings", [])
        queue = self.target_province.get("deployment_queue", [])
        
        owner_nation = self.target_province.get("owner")
        player_research = self.map_screen.nation_data.get(owner_nation, {}).get("research", {})
        
        is_spectator = self.map_screen.player_country == "Spectator"
        can_spectator_edit = getattr(c, 'SPECTATOR_CAN_EDIT_PRODUCTION', True)

        self.active_bars = []
        y_offset = 120
        x_pos = 50

        # --- BUILDING LOGIC ---
        bldg_groups = {"Other": ["industry"], "Recruitment": ["recruitment"]}
        
        def process_building_categories(cat_groups):
            nonlocal y_offset
            for group_id in cat_groups:
                b_list = [b for b, d in self.building_library.items() if d.get("group") == group_id]
                target = None
                owned_in_group = [b for b in current_buildings if self.building_library.get(b, {}).get("group") == group_id]

                if not owned_in_group:
                    target = b_list[0] if b_list else None
                else:
                    for i, b_name in enumerate(b_list):
                        if b_name in owned_in_group:
                            if i + 1 < len(b_list):
                                target = b_list[i+1]

                if target:
                    data = self.building_library[target]
                    is_building = any(q.get("group") == data["group"] for q in queue)
                    req_tech, req_lvl = queries.get_building_required_tech(target)

                    if req_tech and player_research.get(req_tech, 0) < req_lvl:
                        continue 

                    # --- ENFORCE FACTORY DEPENDENCY ---
                    if data["group"] in ["recruitment"]:
                        if not queries.has_basic_factory(self.target_province):
                            continue

                    if is_building:
                        btn_txt = "Building..."
                        cb = lambda: None
                        btn_color = "grey"
                    elif is_spectator and not can_spectator_edit:
                        btn_txt = target
                        cb = lambda: None
                        btn_color = "grey"
                    else:
                        btn_txt = target
                        cb = lambda t=target: self.start_construction(t)
                        btn_color = "orange"
                        if data["group"] == "recruitment": btn_color = "red"

                    btn = Button(x_pos, y_offset, "medium", btn_color, btn_txt, cb)
                    btn.base_y = y_offset
                    btn.is_scrollable = True
                    self.elements.append(btn)

                    bar_rect = pygame.Rect(x_pos + 210, y_offset, 550, 50)
                    self.active_bars.append((bar_rect, data, y_offset, "BUILDING"))
                    y_offset += 60

        self.other_start_y = y_offset
        process_building_categories(bldg_groups["Other"])
        self.other_end_y = y_offset

        y_offset += 30
        self.recruit_start_y = y_offset
        process_building_categories(bldg_groups["Recruitment"])
        self.recruit_end_y = y_offset
        y_offset += 30

        # --- UNIT LOGIC ---
        def process_unit_groups(groups, btn_color):
            nonlocal y_offset
            for group_name in groups:
                if queries.is_unit_obsolete(group_name, player_research):
                    continue

                highest_unlocked = None
                tech_key = group_name.lower().replace(" ", "_")
                researched_lvl = player_research.get(tech_key, 0)

                if tech_key == "infantry_type":
                    inf_years = self.tech_tree.get("infantry_type", {}).get("years", [c.START_YEAR])
                    if researched_lvl > 0:
                        year = inf_years[min(researched_lvl - 1, len(inf_years)-1)]
                        highest_unlocked = f"Infantry Type {year}"
                elif tech_key == "cavalry":
                    if researched_lvl > 0:
                        highest_unlocked = "Cavalry"
                else:
                    group_units = [(n, s) for n, s in self.unit_library.items() if self.get_group_name(n) == group_name]
                    highest_lvl = -1
                    for name, stats in group_units:
                        lvl_str = name.replace(group_name, "").strip()
                        lvl = queries.roman_to_int(lvl_str)
                        required_research = max(1, lvl) 
                        if researched_lvl >= required_research:
                            if lvl > highest_lvl:
                                highest_lvl = lvl
                                highest_unlocked = name

                if highest_unlocked:
                    lookup_name = highest_unlocked
                    
                    if lookup_name == "Militia":
                        can_build = queries.has_industry(self.target_province)
                    else:
                        can_build = queries.has_basic_factory(self.target_province)
                    
                    if is_spectator and not can_spectator_edit:
                        final_btn_color = "grey"
                        cb = lambda: None
                    else:
                        final_btn_color = btn_color if can_build else "grey"
                        cb = lambda n=lookup_name: self.buy_unit(n)
                    
                    btn = Button(x_pos, y_offset, "medium", final_btn_color, highest_unlocked, cb)
                    btn.base_y = y_offset
                    btn.is_scrollable = True
                    self.elements.append(btn)
                    
                    stats = self.unit_library[lookup_name]
                    bar_rect = pygame.Rect(x_pos + 210, y_offset, 550, 50)
                    self.active_bars.append((bar_rect, stats, y_offset, "UNIT"))
                    y_offset += 60

        self.infantry_start_y = y_offset
        process_unit_groups(self.infantry_groups, "green")
        self.infantry_end_y = y_offset

        y_offset += 30 
        self.tank_start_y = y_offset
        process_unit_groups(self.tank_groups, "green")
        self.tank_end_y = y_offset

        y_offset += 30 
        if self.target_province.get("is_coastal", False):
            self.navy_start_y = y_offset
            process_unit_groups(self.navy_groups, "blue")
            self.navy_end_y = y_offset
        else:
            self.navy_start_y = self.navy_end_y = y_offset

        # Calculate maximum scroll distance
        self.max_scroll = max(0, y_offset - c.SCREEN_HEIGHT + 150)

    def start_construction(self, b_name):
        data = self.building_library[b_name]
        owner = self.target_province.get("owner")
        p_data = self.map_screen.nation_data.get(owner, {})

        if queries.can_afford(p_data, data):
            queries.deduct_resources(p_data, data)
            order = {
                "order_type": "BUILDING",
                "item_name": b_name,
                "turns_remaining": max(1, data.get("time", c.DAYS_PER_TURN) // c.DAYS_PER_TURN),
                "group": data["group"],
                "refund": {
                    "materials": data.get("cost_materials", 0),
                    "manpower": data.get("cost_manpower", 0),
                    "fuel": data.get("cost_fuel", 0)
                }
            }
            self.target_province.setdefault("deployment_queue", []).append(order)
            self.map_screen.show_feedback(f"Started {b_name}")
            self.refresh_ui()
        else:
            self.map_screen.show_feedback("Insufficient resources!")

    def buy_unit(self, unit_name):
        stats = self.unit_library.get(unit_name)
        if not stats or not self.map_screen: return

        if unit_name == "Militia":
            if not queries.has_industry(self.target_province):
                self.map_screen.show_feedback("Requires a Workshop or Factory to recruit Militia!")
                return
        else:
            if not queries.has_basic_factory(self.target_province):
                self.map_screen.show_feedback("Requires a Basic Factory or better to recruit!")
                return

        owner = self.target_province.get("owner")
        p_data = self.map_screen.nation_data.get(owner, {})

        if queries.can_afford(p_data, stats):
            queries.deduct_resources(p_data, stats)
            order = {
                "unit_type": unit_name,
                "turns_remaining": max(1, stats.get("production_time", c.DAYS_PER_TURN) // c.DAYS_PER_TURN),
                "refund": {
                    "materials": stats.get("cost_materials", 0),
                    "manpower": stats.get("cost_manpower", 0),
                    "fuel": stats.get("cost_fuel", 0)
                }
            }
            self.target_province.setdefault("deployment_queue", []).append(order)
            self.map_screen.show_feedback(f"Production started: {unit_name}")
            self.refresh_ui()
        else:
            self.map_screen.show_feedback("Insufficient resources!")

    def cancel_order(self, index):
        queue = self.target_province.get("deployment_queue", [])
        if 0 <= index < len(queue):
            item = queue.pop(index)
            
            owner = self.target_province.get("owner", "Unclaimed")
            p_data = self.map_screen.nation_data.get(owner, {})
            
            if "refund" in item:
                for res, amount in item["refund"].items():
                    p_data[res] = p_data.get(res, 0) + amount
            else:
                stats = {}
                if item.get("order_type") == "BUILDING":
                    stats = self.building_library.get(item.get("item_name"), {})
                elif "unit_type" in item:
                    stats = self.unit_library.get(item["unit_type"], {})
                queries.refund_resources(p_data, stats)

            self.map_screen.show_feedback("Cancelled & Refunded")
            self.refresh_ui()

    def additional_events(self, event):
        if event.type == pygame.MOUSEWHEEL:
            self.target_scroll_y += event.y * 50
            self.enforce_scroll_bounds()

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.map_screen.player_country == "Spectator" and not getattr(c, 'SPECTATOR_CAN_EDIT_PRODUCTION', True):
                return
                
            for rect, index in self.cancel_hitboxes:
                if rect.collidepoint(event.pos):
                    self.cancel_order(index)
                    return

    def additional_draw(self, surface):
        if not self.target_province: return
        
        # --- DRAW SCROLLING CONTENT ---
        # Draw category backgrounds mapped to the current scroll y
        scroll = int(self.scroll_y)

        # General Buildings (Orange)
        if self.other_end_y > self.other_start_y:
            land_rect = pygame.Rect(30, self.other_start_y + scroll - 15, 840, self.other_end_y - self.other_start_y + 15)
            pygame.draw.rect(surface, (60, 40, 20), land_rect)
            pygame.draw.rect(surface, (200, 100, 30), land_rect, 2)
            lbl = fonts.get("heading2").render("GENERAL BUILDINGS", True, (255, 150, 50))
            surface.blit(lbl, (40, self.other_start_y + scroll - 45))

        # Recruitment (Red)
        if getattr(self, 'recruit_end_y', 0) > getattr(self, 'recruit_start_y', 0):
            recruit_rect = pygame.Rect(30, self.recruit_start_y + scroll - 15, 840, self.recruit_end_y - self.recruit_start_y + 15)
            pygame.draw.rect(surface, (60, 30, 30), recruit_rect)
            pygame.draw.rect(surface, (200, 50, 50), recruit_rect, 2)
            lbl = fonts.get("heading2").render("RECRUITMENT CENTERS", True, (255, 100, 100))
            surface.blit(lbl, (40, self.recruit_start_y + scroll - 45))

        # Infantry (Green)
        if self.infantry_end_y > self.infantry_start_y:
            inf_rect = pygame.Rect(30, self.infantry_start_y + scroll - 15, 840, self.infantry_end_y - self.infantry_start_y + 15)
            pygame.draw.rect(surface, (30, 60, 30), inf_rect)
            pygame.draw.rect(surface, (50, 150, 50), inf_rect, 2)
            lbl = fonts.get("heading2").render("INFANTRY", True, (100, 255, 100))
            surface.blit(lbl, (40, self.infantry_start_y + scroll - 45))

        # Tanks (Dark Green)
        if self.tank_end_y > self.tank_start_y:
            tank_rect = pygame.Rect(30, self.tank_start_y + scroll - 15, 840, self.tank_end_y - self.tank_start_y + 15)
            pygame.draw.rect(surface, (20, 45, 20), tank_rect) 
            pygame.draw.rect(surface, (40, 120, 40), tank_rect, 2) 
            lbl = fonts.get("heading2").render("TANKS", True, (80, 200, 80))
            surface.blit(lbl, (40, self.tank_start_y + scroll - 45))

        # Navy (Blue)
        if self.navy_end_y > self.navy_start_y:
            navy_rect = pygame.Rect(30, self.navy_start_y + scroll - 15, 840, self.navy_end_y - self.navy_start_y + 15)
            pygame.draw.rect(surface, (30, 30, 60), navy_rect)
            pygame.draw.rect(surface, (50, 50, 150), navy_rect, 2)
            lbl = fonts.get("heading2").render("NAVAL FORCES", True, (100, 150, 255))
            surface.blit(lbl, (40, self.navy_start_y + scroll - 45))

        # Stats Bars
        bar_font = fonts.get("small")
        for base_rect, stats, base_y, bar_type in self.active_bars:
            bar_rect = pygame.Rect(base_rect.x, base_y + scroll, base_rect.width, base_rect.height)
            pygame.draw.rect(surface, (40, 40, 40), bar_rect)
            pygame.draw.rect(surface, (100, 100, 100), bar_rect, 1)
            
            if bar_type == "BUILDING":
                t = max(1, stats.get('time', c.DAYS_PER_TURN) // c.DAYS_PER_TURN)
                draw_resource_string(surface, bar_font, f"Build Time: {t} turns   |   Cost: ", stats.get('cost_materials', 0), stats.get('cost_manpower', 0), stats.get('cost_fuel', 0), bar_rect.x + 15, bar_rect.y + 6, (255, 215, 0))
                draw_resource_string(surface, bar_font, f"Yield (Per Turn):   ", stats.get('prod_materials', 0), stats.get('prod_manpower', 0), stats.get('prod_fuel', 0), bar_rect.x + 15, bar_rect.y + 26, (150, 255, 150), is_yield=True)
            else:
                t = max(1, stats.get('production_time', c.DAYS_PER_TURN) // c.DAYS_PER_TURN)
                draw_resource_string(surface, bar_font, f"Deploy: {t} turns   |   Cost: ", stats.get('cost_materials', 0), stats.get('cost_manpower', 0), stats.get('cost_fuel', 0), bar_rect.x + 15, bar_rect.y + 6, (255, 215, 0))
                
                # --- MODIFIED COMBAT STATS STRING ---
                draw_combat_stats(
                    surface, bar_font, "Combat Stats:   ", 
                    stats.get('attack', 0), stats.get('defense', 0), stats.get('health', 0), stats.get('speed', 0), 
                    bar_rect.x + 15, bar_rect.y + 26, (200, 200, 200)
                )

        # --- STATIC OVERLAYS ---
        # Draw header overlay block to hide scrolling units that go too high
        pygame.draw.rect(surface, self.bg_color, (0, 0, c.SCREEN_WIDTH, 80))
        title_font = fonts.get("heading1")
        
        # Determine the name to display at the top of the production queue!
        owner_nation = self.target_province.get("owner", "Unclaimed")
        owner_name = self.map_screen.nation_data.get(owner_nation, {}).get("name", owner_nation).upper()
        surface.blit(title_font.render(f"{owner_name} PRODUCTION", True, (255, 255, 255)), (150, 25))

        # Draw HUD
        hud_rect = pygame.Rect(0, c.SCREEN_HEIGHT - 60, c.SCREEN_WIDTH, 60)
        pygame.draw.rect(surface, (30, 30, 30), hud_rect)
        pygame.draw.line(surface, (100, 100, 100), (0, hud_rect.y), (c.SCREEN_WIDTH, hud_rect.y), 2)

        p_data = self.map_screen.nation_data.get(owner_nation, {})
        res_font = fonts.get("heading2")
        resources = [
            (f"Manpower: {p_data.get('manpower', 0)}", (100, 200, 255)),
            (f"Materials: {p_data.get('materials', 0)}", (180, 180, 180)),
            (f"Fuel: {p_data.get('fuel', 0)}", (200, 100, 255))
        ]
        for i, (text, color) in enumerate(resources):
            surface.blit(res_font.render(text, True, color), (50 + (i * 300), hud_rect.y + 15))

        # Draw Queue (Returns hitbox rectangles for the event handler)
        self.cancel_hitboxes = recruit_ui.draw_recruitment_overlay(surface, self.target_province)

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()