import pygame
import data.constants as c
from gameState import GameState, ScreenLayer
from ui_elements import Button, draw_resource_string, draw_combat_stats, draw_bombardment_stats, draw_time_stat, draw_stat_separator
from screens.map_related_screens import recruit_ui
from map_logic.rendering.font_manager import fonts
from data import queries
from ui.bars import resource_hud

# ==========================================
# LAYOUT
# ==========================================

BACK_BTN_POS = (20, 20)

# Scrolling list of buttons + their stat bars
LIST_START_Y = 120
LIST_X = 50
ROW_STEP_Y = 40
SECTION_SPACING = 60

BAR_OFFSET_X = 140
BAR_WIDTH = 570
BAR_HEIGHT = 30
BAR_TEXT_PAD_X = 15

# Coloured section panels drawn behind each group of rows
PANEL_X = 30
PANEL_WIDTH = 750
PANEL_PAD_TOP = 15
PANEL_LABEL_X = 40
PANEL_LABEL_OFFSET_Y = -45

# Fixed chrome (drawn over the scrolling content)
HEADER_HEIGHT = 80
HEADER_TITLE_POS = (150, 25)
SCROLL_BOTTOM_PAD = 150

# Clicks only register between the header band and the resource bar, so a
# button that has scrolled behind either one stays visible but inert.
CLICK_GUARD_TOP = HEADER_HEIGHT
CLICK_GUARD_BOTTOM = c.SCREEN_HEIGHT - resource_hud.BAR_HEIGHT

# Scroll feel
SCROLL_WHEEL_STEP = 50
SCROLL_LERP = 0.15

# --- Section panels: (attr prefix, label, fill, border, text colour) ---
# Each entry paints one coloured block behind its rows. Adding a section means
# adding a row here plus the matching self.<prefix>_start_y / _end_y markers.
SECTION_PANELS = [
    ("admin",    "ADMINISTRATION",     (40, 20, 60), (150, 100, 200), (200, 150, 255)),
    ("other",    "GENERAL BUILDINGS",  (60, 40, 20), (200, 100, 30),  (255, 150, 50)),
    ("recruit",  "RECRUITMENT CENTERS",(60, 30, 30), (200, 50, 50),   (255, 100, 100)),
    ("infantry", "INFANTRY",           (30, 60, 30), (50, 150, 50),   c.COLOR_SUCCESS_GREEN),
    ("tank",     "TANKS",              (20, 45, 20), (40, 120, 40),   (80, 200, 80)),
    ("navy",     "NAVAL FORCES",       (30, 30, 60), (50, 50, 150),   (100, 150, 255)),
    ("custom",   "CUSTOM",             (60, 55, 20), (200, 180, 50),  (255, 220, 100)),
]

BAR_BG_COLOR = (40, 40, 40)
BAR_BORDER_COLOR = (100, 100, 100)
BAR_YIELD_COLOR = (150, 255, 150)
BAR_STAT_COLOR = (200, 200, 200)

class Production_Screen(GameState):
    back_state = "MAP"

    def __init__(self):
        super().__init__()
        self.bg_color = (25, 25, 25)
        self.target_province = None
        self.map_screen = None
        self.btn_back = None
        self.cancel_hitboxes = []
        
        self.unit_library = queries.get_unit_library()
        self.building_library = queries.get_building_library()
        self.tech_tree = queries.get_tech_tree()
        
        # Use the centralized query
        self.infantry_groups, self.tank_groups, self.navy_groups = queries.get_ordered_unit_groups(self.unit_library)
        self.active_bars = []
        
        # Scroll variables
        self.scroll_y = 0
        self.target_scroll_y = 0
        self.max_scroll = 0

    def handle_events(self, events):
        # Override to block all interaction
        if self.map_screen.tactical_mode:
            for event in events:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.btn_back and self.btn_back.rect.collidepoint(event.pos):
                        self.exit_screen() # Allow back button explicitly
                    else:
                        self.map_screen.show_feedback("Tactical Mode: Cannot interact with national production.")
            return

        super().handle_events(events)

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
                self.scroll_y += (self.target_scroll_y - self.scroll_y) * SCROLL_LERP

            # Keep scrollable buttons pinned to the list. They stay visible (the
            # ProductionChromeOverlay draws over them once they slide behind the
            # header/resource-HUD bars) but a click only registers while the click
            # itself lands clear of those bars, so a still-visible sliver of a
            # button stays clickable and no sfx sneaks through on the hidden part.
            for el in self.elements:
                if getattr(el, 'is_scrollable', False):
                    el.rect.y = el.base_y + int(self.scroll_y)
                    el.click_guard = lambda: CLICK_GUARD_TOP <= pygame.mouse.get_pos()[1] <= CLICK_GUARD_BOTTOM

    def _add_scroll_button(self, x_pos, y_offset, color, text, callback):
        """Creates one of the production screen's scrollable list buttons
        (building/unit/manage rows) and registers it in self.elements."""
        btn = Button(x_pos, y_offset + int(self.scroll_y), "production", color, text, callback, font_preset="button_small")
        btn.base_y = y_offset
        btn.is_scrollable = True
        self.elements.append(btn)
        return btn

    def refresh_ui(self):
        # The back button doesn't scroll, so it is built here but registered at the
        # very end of refresh_ui -- see the ScreenLayer note down there.
        self.btn_back = Button(*BACK_BTN_POS, "small", "red", "Back", self.exit_screen)
        self.elements = []

        current_buildings = self.target_province.get("buildings", [])
        building_queue = self.target_province.get("building_queue", [])
        
        owner_nation = self.target_province.get("owner")
        player_research = self.map_screen.nation_data.get(owner_nation, {}).get("research", {})
        
        is_spectator = self.map_screen.player_country == "Spectator"
        can_spectator_edit = c.SPECTATOR_CAN_EDIT_PRODUCTION

        self.active_bars = []
        y_offset = LIST_START_Y
        x_pos = LIST_X

        # --- BUILDING LOGIC ---
        bldg_groups = {"Other": ["industry"], "Recruitment": ["recruitment"]}
        
        is_core = owner_nation in self.target_province.get("cores", [])
        
        # --- BUGFIX: Coring Restrictions ---
        can_core = False
        has_any_core = any(owner_nation in p.get("cores", []) for p in self.map_screen.map_data.values())
        
        if not has_any_core:
            can_core = True
        elif self.target_province.get("is_coastal", False):
            can_core = True
        else:
            for n_id in self.target_province.get("neighbors", []):
                n_prov = self.map_screen.id_to_province.get(n_id)
                if n_prov and owner_nation in n_prov.get("cores", []):
                    can_core = True
                    break

        self.admin_start_y = y_offset
        if not is_core:
            is_coring = any(q.get("order_type") == "CORE" for q in building_queue)
            core_data = queries.get_core_cost(owner_nation, self.map_screen.map_data)
            
            if is_coring:
                btn_txt = "Coring..."
                btn_color = "grey"
                cb = lambda: None
            elif is_spectator and not can_spectator_edit:
                btn_txt = "Core Territory"
                btn_color = "grey"
                cb = lambda: None
            elif not can_core:
                btn_txt = "Cannot Core"
                btn_color = "grey"
                cb = lambda: None
            else:
                btn_txt = "Core Territory"
                btn_color = "purple"
                cb = lambda: self.start_coring()

            self._add_scroll_button(x_pos, y_offset, btn_color, btn_txt, cb)

            bar_rect = pygame.Rect(x_pos + BAR_OFFSET_X, y_offset, BAR_WIDTH, BAR_HEIGHT)
            mock_stats = {
                "time": core_data["time"],
                "cost_manpower": core_data["cost_manpower"],
                "cost_materials": core_data["cost_materials"],
                "cost_fuel": core_data["cost_fuel"],
                "prod_manpower": 0, "prod_materials": 0, "prod_fuel": 0
            }
            self.active_bars.append((bar_rect, mock_stats, y_offset, "BUILDING"))
            y_offset += ROW_STEP_Y

        # --- REMOVE CORES BUTTON ---
        foreign_cores = [core for core in self.target_province.get("cores", []) if core != owner_nation]
        has_unit = any(u.get("owner") == owner_nation for u in self.target_province.get("units", []))
        
        is_removing_cores = any(q.get("order_type") == "REMOVE_CORE" for q in building_queue)
        remove_data = queries.get_remove_core_cost(owner_nation, self.map_screen.map_data)
        
        if is_removing_cores:
            btn_txt2 = "Removing Cores..."
            btn_color2 = "grey"
            cb2 = lambda: None
        elif not foreign_cores:
            btn_txt2 = "No Foreign Cores"
            btn_color2 = "grey"
            cb2 = lambda: None
        elif not has_unit:
            btn_txt2 = "Needs Garrison"
            btn_color2 = "grey"
            cb2 = lambda: None
        elif not can_core:
            btn_txt2 = "Cannot Remove"
            btn_color2 = "grey"
            cb2 = lambda: None
        elif is_spectator and not can_spectator_edit:
            btn_txt2 = "Remove Cores"
            btn_color2 = "grey"
            cb2 = lambda: None
        else:
            btn_txt2 = "Remove Cores"
            btn_color2 = "red"
            cb2 = lambda: self.start_remove_cores()

        self._add_scroll_button(x_pos, y_offset, btn_color2, btn_txt2, cb2)

        bar_rect2 = pygame.Rect(x_pos + BAR_OFFSET_X, y_offset, BAR_WIDTH, BAR_HEIGHT)
        mock_stats2 = {
            "time": remove_data["time"],
            "cost_manpower": remove_data["cost_manpower"],
            "cost_materials": remove_data["cost_materials"],
            "cost_fuel": remove_data["cost_fuel"],
            "prod_manpower": 0, "prod_materials": 0, "prod_fuel": 0
        }
        self.active_bars.append((bar_rect2, mock_stats2, y_offset, "BUILDING"))
        y_offset += ROW_STEP_Y

        self.admin_end_y = y_offset

        y_offset += SECTION_SPACING
        
        self.other_start_y = y_offset

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
                    # Dynamically calculate the visual cost for the player
                    data = queries.get_building_cost(target, owner_nation, self.map_screen.map_data, self.building_library)
                    is_building = any(q.get("group") == data["group"] for q in building_queue)
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
                        btn_txt = queries.get_condensed_building_name(target)
                        cb = lambda: None
                        btn_color = "grey"
                    else:
                        btn_txt = queries.get_condensed_building_name(target)
                        cb = lambda t=target: self.start_construction(t)
                        btn_color = "orange"
                        if data["group"] == "recruitment": btn_color = "red"

                    self._add_scroll_button(x_pos, y_offset, btn_color, btn_txt, cb)

                    bar_rect = pygame.Rect(x_pos + BAR_OFFSET_X, y_offset, BAR_WIDTH, BAR_HEIGHT)
                    self.active_bars.append((bar_rect, data, y_offset, "BUILDING"))
                    y_offset += ROW_STEP_Y

        self.other_start_y = y_offset
        process_building_categories(bldg_groups["Other"])
        self.other_end_y = y_offset

        y_offset += SECTION_SPACING
        self.recruit_start_y = y_offset
        process_building_categories(bldg_groups["Recruitment"])
        self.recruit_end_y = y_offset
        y_offset += SECTION_SPACING

        # --- UNIT LOGIC ---
        def render_unit_button(unit_name, btn_color):
            nonlocal y_offset
            if queries.get_base_unit_name(unit_name) == "Militia":
                can_build = queries.has_industry(self.target_province)
            else:
                can_build = queries.has_basic_factory(self.target_province)

            if is_spectator and not can_spectator_edit:
                final_btn_color = "grey"
                cb = lambda: None
            else:
                final_btn_color = btn_color if can_build else "grey"
                cb = lambda n=unit_name: self.buy_unit(n)

            self._add_scroll_button(x_pos, y_offset, final_btn_color, queries.get_condensed_unit_name(unit_name), cb)

            stats = self.unit_library[unit_name]
            bar_rect = pygame.Rect(x_pos + BAR_OFFSET_X, y_offset, BAR_WIDTH, BAR_HEIGHT)
            self.active_bars.append((bar_rect, stats, y_offset, "UNIT"))
            y_offset += ROW_STEP_Y

        def unit_speed_sort_key(unit_name):
            # Fastest-to-build units float to the top of their category;
            # materials cost is the tiebreaker when build time is equal.
            stats = self.unit_library.get(unit_name, {})
            return (stats.get('production_time', 0), stats.get('cost_materials', 0))

        def process_unit_groups(groups, btn_color):
            nonlocal y_offset
            unlocked_units = []
            for group_name in groups:
                if queries.is_unit_obsolete(group_name, player_research):
                    continue

                highest_unlocked = None
                tech_key = queries.get_unit_tech_key(group_name)

                if tech_key in ("infantry_type", "motorized_infantry", "mechanized_infantry", "artillery"):
                    year = queries.get_infantry_family_year(tech_key, player_research, self.tech_tree)
                    if year is not None:
                        highest_unlocked = f"{group_name} {year}"
                else:
                    # Let the Roman Numeral block perfectly handle Cavalry, Tanks, Navies, and Militia
                    researched_lvl = player_research.get(tech_key, 0)
                    group_units = [(n, s) for n, s in self.unit_library.items() if queries.get_base_unit_name(n) == group_name]
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
                    unlocked_units.append(highest_unlocked)

            for unit_name in sorted(unlocked_units, key=unit_speed_sort_key):
                render_unit_button(unit_name, btn_color)

        self.infantry_start_y = y_offset
        process_unit_groups(self.infantry_groups, "green")
        self.infantry_end_y = y_offset

        y_offset += SECTION_SPACING 
        self.tank_start_y = y_offset
        process_unit_groups(self.tank_groups, "green")
        self.tank_end_y = y_offset

        y_offset += SECTION_SPACING 
        if self.target_province.get("is_coastal", False):
            self.navy_start_y = y_offset
            process_unit_groups(self.navy_groups, "blue")
            self.navy_end_y = y_offset
        else:
            self.navy_start_y = self.navy_end_y = y_offset

        # --- CUSTOM UNIT LOGIC ---
        # Lets a player build a specific researched tier (e.g. Medium Tank II) even
        # when a higher tier is researched and would otherwise be the only option shown.
        y_offset += SECTION_SPACING
        self.custom_start_y = y_offset

        p_data = self.map_screen.nation_data.get(owner_nation)
        owner_valid = p_data is not None

        custom_units = p_data.get("custom_production_units", []) if owner_valid else []
        valid_custom_units = [u for u in custom_units if u in self.unit_library and queries.is_unit_unlocked(u, player_research)]
        if owner_valid and valid_custom_units != custom_units:
            p_data["custom_production_units"] = valid_custom_units
        custom_units = valid_custom_units

        if not owner_valid or (is_spectator and not can_spectator_edit):
            manage_color, manage_cb = "grey", (lambda: None)
        else:
            manage_color, manage_cb = "pink", self.open_custom_unit_manager

        self._add_scroll_button(x_pos, y_offset, manage_color, "Edit Custom Units", manage_cb)
        y_offset += ROW_STEP_Y

        for unit_name in sorted(custom_units, key=unit_speed_sort_key):
            render_unit_button(unit_name, "yellow")

        self.custom_end_y = y_offset

        # Calculate maximum scroll distance
        self.max_scroll = max(0, y_offset - c.SCREEN_HEIGHT + SCROLL_BOTTOM_PAD)

        # Drawn after the unit list so it covers any scrollable button sliding past it.
        self.elements.append(ScreenLayer(self, "draw_chrome"))

        # Back sits at (20, 20), inside the header band draw_chrome fills, so it has
        # to be registered after the chrome or it gets painted over and vanishes.
        self.elements.append(self.btn_back)

    def start_coring(self):
        owner = self.target_province.get("owner")
        data = queries.get_core_cost(owner, self.map_screen.map_data)
        p_data = self.map_screen.nation_data.get(owner, {})

        if queries.can_afford(p_data, data):
            queries.deduct_resources(p_data, data)
            order = {
                "order_type": "CORE",
                "item_name": "Core Territory",
                "turns_remaining": max(1, data.get("time", 24)),
                "group": "administration",
                "refund": {
                    "cost_materials": data.get("cost_materials", 0),
                    "cost_manpower": data.get("cost_manpower", 0),
                    "cost_fuel": data.get("cost_fuel", 0)
                }
            }
            self.target_province.setdefault("building_queue", []).append(order)
            self.map_screen.show_feedback("Started Coring Territory")
            self.refresh_ui()
        else:
            self.map_screen.show_feedback("Insufficient resources!")

    def start_remove_cores(self):
        owner = self.target_province.get("owner")
        data = queries.get_remove_core_cost(owner, self.map_screen.map_data)
        p_data = self.map_screen.nation_data.get(owner, {})

        if queries.can_afford(p_data, data):
            queries.deduct_resources(p_data, data)
            order = {
                "order_type": "REMOVE_CORE",
                "item_name": "Remove Cores",
                "turns_remaining": max(1, data.get("time", 1)),
                "group": "administration",
                "refund": {
                    "cost_materials": data.get("cost_materials", 0),
                    "cost_manpower": data.get("cost_manpower", 0),
                    "cost_fuel": data.get("cost_fuel", 0)
                }
            }
            self.target_province.setdefault("building_queue", []).append(order)
            self.map_screen.show_feedback("Started Core Removal")
            self.refresh_ui()
        else:
            self.map_screen.show_feedback("Insufficient resources!")

    def start_construction(self, b_name):
        owner = self.target_province.get("owner")
        if owner not in self.target_province.get("cores", []):
            self.map_screen.show_feedback("Must core territory before producing!")
            return

        data = queries.get_building_cost(b_name, owner, self.map_screen.map_data, self.building_library)
        p_data = self.map_screen.nation_data.get(owner, {})

        if queries.can_afford(p_data, data):
            queries.deduct_resources(p_data, data)
            order = {
                "order_type": "BUILDING",
                "item_name": b_name,
                "turns_remaining": max(1, data.get("time", 1)),
                "group": data["group"],
                "refund": {
                    "cost_materials": data.get("cost_materials", 0),
                    "cost_manpower": data.get("cost_manpower", 0),
                    "cost_fuel": data.get("cost_fuel", 0)
                }
            }
            self.target_province.setdefault("building_queue", []).append(order)
            self.map_screen.show_feedback(f"Started {b_name}")
            self.refresh_ui()
        else:
            self.map_screen.show_feedback("Insufficient resources!")

    def buy_unit(self, unit_name):
        owner = self.target_province.get("owner")
        if owner not in self.target_province.get("cores", []):
            self.map_screen.show_feedback("Must core territory before recruiting!")
            return

        stats = self.unit_library.get(unit_name)
        if not stats or not self.map_screen: return

        if stats.get("naval_unit", False) and not self.target_province.get("is_coastal", False):
            self.map_screen.show_feedback("Can't build naval units on landlocked tiles!")
            return

        if queries.get_base_unit_name(unit_name) == "Militia":
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
                "turns_remaining": max(1, stats.get("production_time", 1)),
                "refund": {
                    "cost_materials": stats.get("cost_materials", 0),
                    "cost_manpower": stats.get("cost_manpower", 0),
                    "cost_fuel": stats.get("cost_fuel", 0)
                }
            }
            self.target_province.setdefault("unit_queue", []).append(order)
            self.map_screen.show_feedback(f"Production started: {unit_name}")
            self.refresh_ui()
        else:
            self.map_screen.show_feedback("Insufficient resources!")

    def open_custom_unit_manager(self):
        if not self.map_screen: return

        owner_nation = self.target_province.get("owner")
        p_data = self.map_screen.nation_data.get(owner_nation)
        if p_data is None: return

        player_research = p_data.get("research", {})
        current_custom = set(p_data.get("custom_production_units", []))

        # Group every unit the player currently has the research level for, regardless
        # of whether it's the group's highest tier (that restriction is what this menu exists to bypass).
        # Same Infantry/Tanks/Navy rule the production columns use.
        categorized = queries.get_grouped_units(
            self.unit_library, by_family=False,
            unit_filter=lambda name, stats: queries.is_unit_unlocked(name, player_research))

        for group in categorized.values():
            group.sort()

        import tkinter as tk

        root, close_menu = queries.create_managed_tk_window(self, "Manage Custom Production Units", "420x560")

        tk.Label(root, text="Select researched units to add to the Custom build category:",
                 font=("Arial", 10, "bold"), wraplength=380, justify="left").pack(pady=(10, 5), padx=10)

        vars_by_unit = {}

        def select_all():
            for var in vars_by_unit.values():
                var.set(True)

        def deselect_all():
            for var in vars_by_unit.values():
                var.set(False)

        select_frame = tk.Frame(root)
        select_frame.pack(pady=(0, 5))
        tk.Button(select_frame, text="Select All", command=select_all, width=12).pack(side="left", padx=5)
        tk.Button(select_frame, text="Deselect All", command=deselect_all, width=12).pack(side="left", padx=5)

        container = tk.Frame(root)
        container.pack(fill="both", expand=True, padx=10)

        canvas = tk.Canvas(container, borderwidth=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for category, names in categorized.items():
            if not names: continue
            tk.Label(scroll_frame, text=category, font=("Arial", 10, "bold")).pack(anchor="w", pady=(8, 0))
            for name in names:
                var = tk.BooleanVar(value=name in current_custom)
                vars_by_unit[name] = var
                tk.Checkbutton(scroll_frame, text=name, variable=var).pack(anchor="w", padx=20)

        if not vars_by_unit:
            tk.Label(scroll_frame, text="No units researched yet.").pack(pady=20)

        def on_apply():
            p_data["custom_production_units"] = [name for name, var in vars_by_unit.items() if var.get()]
            close_menu()
            self.refresh_ui()

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Apply", command=on_apply, width=12, bg="#4CAF50", fg="white").pack(side="left", padx=10)
        tk.Button(btn_frame, text="Cancel", command=close_menu, width=12, bg="#f44336", fg="white").pack(side="left", padx=10)

        queries.run_tk_loop(self, root)

    def cancel_order(self, index, q_type):
        queue_key = "building_queue" if q_type == "building" else "unit_queue"
        queue = self.target_province.get(queue_key, [])
        
        if 0 <= index < len(queue):
            item = queue.pop(index)
            
            owner = self.target_province.get("owner", "Unclaimed")
            p_data = self.map_screen.nation_data.get(owner, {})
            
            if "refund" in item:
                queries.refund_resources(p_data, item["refund"])
            else:
                stats = {}
                if item.get("order_type") == "BUILDING":
                    stats = queries.get_building_cost(item.get("item_name"), owner, self.map_screen.map_data, self.building_library)
                elif "unit_type" in item:
                    stats = self.unit_library.get(item["unit_type"], {})
                queries.refund_resources(p_data, stats)

            self.map_screen.show_feedback("Cancelled & Refunded")
            self.refresh_ui()

    def additional_events(self, event):
        if event.type == pygame.MOUSEWHEEL:
            self.target_scroll_y += event.y * SCROLL_WHEEL_STEP
            self.enforce_scroll_bounds()

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.map_screen.player_country == "Spectator" and not c.SPECTATOR_CAN_EDIT_PRODUCTION:
                return
                
            for rect, index, q_type in self.cancel_hitboxes:
                if rect.collidepoint(event.pos):
                    self.cancel_order(index, q_type)
                    return

    def additional_draw(self, surface):
        if not self.target_province: return
        
        # --- DRAW SCROLLING CONTENT ---
        # Every section is the same panel + label, so they are painted from the
        # SECTION_PANELS table rather than seven near-identical blocks.
        scroll = int(self.scroll_y)
        heading_font = fonts.get("heading2")

        for prefix, label, fill, border, text_color in SECTION_PANELS:
            start_y = getattr(self, f"{prefix}_start_y", 0)
            end_y = getattr(self, f"{prefix}_end_y", 0)
            if end_y <= start_y:
                continue

            panel = pygame.Rect(PANEL_X, start_y + scroll - PANEL_PAD_TOP,
                                PANEL_WIDTH, end_y - start_y + PANEL_PAD_TOP)
            pygame.draw.rect(surface, fill, panel)
            pygame.draw.rect(surface, border, panel, 2)
            surface.blit(heading_font.render(label, True, text_color),
                         (PANEL_LABEL_X, start_y + scroll + PANEL_LABEL_OFFSET_Y))

        # Stats Bars -- everything packed onto a single line, per-section
        # colors preserved but labels dropped, so it fits within the bar
        # instead of running off-screen.
        bar_font = fonts.get("small")
        for base_rect, stats, base_y, bar_type in self.active_bars:
            bar_rect = pygame.Rect(base_rect.x, base_y + scroll, base_rect.width, base_rect.height)
            pygame.draw.rect(surface, BAR_BG_COLOR, bar_rect)
            pygame.draw.rect(surface, BAR_BORDER_COLOR, bar_rect, 1)

            text_y = bar_rect.y + (bar_rect.height - bar_font.get_height()) // 2
            x = bar_rect.x + BAR_TEXT_PAD_X

            if bar_type == "BUILDING":
                t = max(1, stats.get('time', 1))
                x = draw_time_stat(surface, bar_font, t, x, text_y, c.COLOR_GOLD_HIGHLIGHT)
                x = draw_stat_separator(surface, bar_font, x, text_y)
                x = draw_resource_string(surface, bar_font, "", stats.get('cost_materials', 0), stats.get('cost_manpower', 0), stats.get('cost_fuel', 0), x, text_y, c.COLOR_GOLD_HIGHLIGHT)
                x = draw_stat_separator(surface, bar_font, x, text_y)
                draw_resource_string(surface, bar_font, "", stats.get('prod_materials', 0), stats.get('prod_manpower', 0), stats.get('prod_fuel', 0), x, text_y, BAR_YIELD_COLOR, is_yield=True)
            else:
                t = max(1, stats.get('production_time', 1))
                x = draw_time_stat(surface, bar_font, t, x, text_y, c.COLOR_GOLD_HIGHLIGHT)
                x = draw_stat_separator(surface, bar_font, x, text_y)
                x = draw_resource_string(surface, bar_font, "", stats.get('cost_materials', 0), stats.get('cost_manpower', 0), stats.get('cost_fuel', 0), x, text_y, c.COLOR_GOLD_HIGHLIGHT)
                x = draw_stat_separator(surface, bar_font, x, text_y)
                x = draw_combat_stats(
                    surface, bar_font, "",
                    stats.get('attack', 0), stats.get('defense', 0), stats.get('health', 0), stats.get('speed', 0),
                    x, text_y, BAR_STAT_COLOR, labeled=False
                )

                if 'bombard_attack' in stats:
                    x = draw_stat_separator(surface, bar_font, x, text_y)
                    draw_bombardment_stats(
                        surface, bar_font,
                        stats.get('bombard_attack', 0), stats.get('bombard_range', 0),
                        x, text_y, BAR_STAT_COLOR, base_text="", labeled=False
                    )

    def draw_chrome(self, surface):
        """Fixed header + resource HUD. Drawn by ProductionChromeOverlay, the very
        last element each frame, so it sits on top of any scrolled-behind buttons."""
        if not self.target_province: return

        # Header overlay block hides scrolling units that go too high
        pygame.draw.rect(surface, self.bg_color, (0, 0, c.SCREEN_WIDTH, HEADER_HEIGHT))
        title_font = fonts.get("heading1")

        # Determine the name to display at the top of the production queue!
        owner_nation = self.target_province.get("owner", "Unclaimed")
        owner_name = self.map_screen.nation_data.get(owner_nation, {}).get("name", owner_nation).upper()
        surface.blit(title_font.render(f"{owner_name} PRODUCTION", True, (255, 255, 255)), HEADER_TITLE_POS)

        resource_hud.draw_resource_bar(surface, self.map_screen, target_nation=owner_nation)

        # Draw Queue (Returns hitbox rectangles for the event handler)
        self.cancel_hitboxes = recruit_ui.draw_recruitment_overlay(surface, self.target_province)

