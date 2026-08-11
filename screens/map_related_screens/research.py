import pygame
from gameState import GameState, ScreenLayer
import data.constants as c
import ui_elements
from ui_elements import Button, draw_resource_string, draw_combat_stats, draw_bombardment_stats
from map_logic.rendering.font_manager import fonts
from map_logic.rendering import symbol_loader
from data import queries
from ui.bars import ui_bars

# ==========================================
# LAYOUT
# ==========================================

EXIT_BTN_POS = (20, 10)
CATEGORY_BTN_START_X = 180
CATEGORY_BTN_STEP_X = 205
CATEGORY_BTN_Y = 10

HEADER_HEIGHT = 70
HEADER_TITLE_Y = 75
HEADER_OUTPUT_Y = 85
HEADER_OUTPUT_MARGIN_X = 30

TIMELINE_AXIS_Y = 180
TIMELINE_TICK_HALF = 10
TIMELINE_YEAR_LABEL_OFFSET_Y = -40
TIMELINE_YEAR_PADDING = 5     # Extra years drawn either side of the viewport
NODE_ROW_HALF_HEIGHT = 30     # Half a standard 60px node; the row's centre line

# Horizontal scrollbar spanning the full width along the very bottom of the
# screen, letting the whole START_YEAR..END_YEAR timeline be dragged at once.
HSCROLLBAR_HEIGHT = 16
HSCROLLBAR_MARGIN_X = 20
HSCROLLBAR_MARGIN_BOTTOM = 8

# Active research slots box, bottom-left over the timeline. Sits above the
# scrollbar's footprint (height + bottom margin) plus a small gap, so its
# whole box is shifted up rather than merely clipped at the bottom.
HUD_SLOT_STEP_Y = 25
HUD_BASE_HEIGHT = 80
HUD_X = 20
HUD_WIDTH = 400
HUD_BOTTOM_PAD = 20
HUD_SCROLLBAR_CLEARANCE = HSCROLLBAR_HEIGHT + HSCROLLBAR_MARGIN_BOTTOM + 10
HUD_TITLE_X = 30
HUD_TITLE_OFFSET_Y = 10
HUD_SLOT_TEXT_X = 40
HUD_FIRST_SLOT_OFFSET_Y = 40

# Tech detail modal
MODAL_WIDTH = 800
MODAL_HEIGHT = 500
MODAL_ALPHA = 180
MODAL_TITLE_X = 30
MODAL_TITLE_Y = 30
MODAL_ICON_X = 30
MODAL_ICON_Y = 100
MODAL_ICON_BOX = 120
MODAL_TEXT_X = 200          # Left edge of every text column in the modal
MODAL_COST_Y = 100
MODAL_WARNING_Y = 130
MODAL_BODY_START_Y = 170
MODAL_LINE_STEP_Y = 30
MODAL_SUBHEAD_STEP_Y = 25
MODAL_ENTITY_PADDING_Y = 10
MODAL_BTN_Y_OFFSET = 430
MODAL_ACTION_BTN_X = 50
MODAL_CANCEL_BTN_X = 650

# Completed-tech text list
COMPLETED_START_Y = 150
COMPLETED_COLUMN_WIDTH = 320
COMPLETED_START_X = 10
COMPLETED_HEADER_STEP_Y = 40
COMPLETED_ROW_STEP_Y = 28
COMPLETED_INDENT_X = 10

# Scroll feel
SCROLL_WHEEL_STEP = 70
SCROLL_LERP = 0.15

# --- Node row heights (visual layout, deliberately hand-tuned) ---
ROW_Y = [200, 270, 340, 410, 480, 550]
ROW_DEFAULT_Y = 350

# Categories whose nodes default to the wide button size.
WIDE_RESEARCH_CATEGORIES = ["TANKS", "NAVY"]

# Tech families whose display name is "<Class> Type <year>" rather than a
# roman numeral tier, keyed off the year list in the tech tree.
YEAR_TIER_TECHS = {
    "infantry_type": "Infantry Type",
}

# Tech keys whose display name is fixed and unrelated to their level.
FIXED_TECH_NAMES = {
    "civilian_car": "Civilian Car",
    "ww1_armored_car": "WW1 Armored Car",
    "ww1_tank": "WW1 Tank",
    "ww1_railroad_gun": "WW1 Railroad Gun",
    "ww2_railroad_gun": "WW2 Railroad Gun",
    "carrack": "Carrack",
    "ironclad": "Ironclad",
    "pre-dreadnought": "Pre-Dreadnought",
    "dreadnought": "Dreadnought",
    "battleship": "Battleship",
    "bergius_process": "Bergius Process",
    "basic_factory": "Basic Factory",
    "basic_recruitment": "Basic Recruitment Center",
    "landkreuzer_p1000_ratte": "Landkreuzer P.1000 Ratte",
    "landkreuzer_p1500_monster": "Landkreuzer P.1500 Monster",
    "trucks": "Trucks",
    "armored_personnel_carriers": "Armored Personnel Carriers",
    "infantry_fighting_vehicle": "Infantry Fighting Vehicle",
    "electromagnetic_launcher": "Electromagnetic Launcher",
    "railgun": "Railgun",
}

# Tech nodes whose icon isn't just its own display name (see draw_tech_nodes).
# Trucks/APCs unlock a *capability* rather than a directly-buildable unit of the
# same name, so they borrow the closest existing unit icon.
TECH_ICON_OVERRIDES = {
    "resource_refining": "Iron",
    "trucks": "Truck",
    "armored_personnel_carriers": "Mechanized Infantry",
}

# Tech keys displayed as "<Name> Lvl <n>" instead of a roman numeral.
LEVEL_SUFFIX_TECHS = {
    "recruitment_buildings": "Recruitment Building",
    "general_recruitment": "General Recruitment",
    "resource_refining": "Resource Refining",
    "factory": "Factory",
    "fuel_refining": "Fuel Refining",
}

# Node button sizes, matched against the lowercased display name in order.
# First hit wins, so the more specific entries have to come first.
NODE_SIZE_RULES = [
    (("aircraft carrier", "battleship", "dreadnought", "submarine"), "tech_square_ultra_wide"),
    (("ww2 railroad gun",), "tech_square_ww2_railroad_gun"),
    (("landkreuzer p.1000 ratte",), "tech_square_landkreuzer_p1000_ratte"),
    (("landkreuzer p.1500 monster",), "tech_square_landkreuzer_p1500_monster"),
    (("railroad gun",), "tech_square_railroad_gun"),
    (("railgun",), "tech_square_railgun"),
    (("light tank ix",), "tech_square_wide"),
    (("civilian car", "armored car", "light tank i", "light tank v", "medium tank"), "tech_square_medium"),
]

DEFAULT_TECH_COST = 300

STATUS_COLORS = {"COMPLETED": "green", "RESEARCHING": "orange", "AVAILABLE": "blue", "LOCKED": "grey"}


class Research_Screen(GameState):
    back_state = "MAP"

    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 30)
        self.map_screen = None
        self.current_category = "INFANTRY" 
        self.categories = ["INFANTRY", "TANKS", "NAVY", "INDUSTRY", "COMPLETED"]

        # REPLACED DISK I/O WITH CACHED QUERIES
        self.tech_tree = queries.get_tech_tree()
        self.unit_library = queries.get_unit_library()
        self.building_library = queries.get_building_library()
        
        self.active_modal = None

        self.complete_panel_x = 250
        self.complete_panel_y = 125

        # --- Timeline Variables ---
        self.scroll_x = 0
        self.target_scroll_x = 0
        self.min_scroll_x = self.max_scroll_x = 0
        self.pixels_per_year = c.RESEARCH_TIMELINE_SPACING
        self.scroll_content_rect = pygame.Rect(0, HEADER_HEIGHT, c.SCREEN_WIDTH, c.SCREEN_HEIGHT - HEADER_HEIGHT)

        # --- Timeline scrollbar drag state ---
        self.hscroll_track_rect = None
        self.hscroll_handle_rect = None
        self.is_dragging_hscrollbar = False

        self.setup_nodes()

    @property
    def subject(self):
        """Whose research this screen is showing.

        A player sees their own. A spectator picks a nation first, and it
        arrives on the map screen as `viewing_research_country` -- the same
        hand-off channel `editing_country` already uses for the identity
        editor, rather than a second mechanism doing the same job.
        """
        chosen = getattr(self.map_screen, "viewing_research_country", "")
        return chosen or self.map_screen.player_country

    @property
    def subject_data(self):
        return self.map_screen.nation_data[self.subject]

    @property
    def can_edit(self):
        """Whether this viewer may change what the subject researches.

        Tactical mode has always been read-only here. A spectator is the same
        kind of onlooker, gated by its own switch so a host can hand out the
        view without the power.
        """
        if self.map_screen.tactical_mode:
            return False
        if self.map_screen.player_country == "Spectator":
            return c.SPECTATOR_CAN_EDIT_RESEARCH
        return True

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)
            self.additional_events(event)

    def setup_nodes(self):
        """Dynamically positions nodes based on their associated year."""
        
        self.tech_years = {}
        for tech_key, data in self.tech_tree.items():
            years = data.get("years", [1900] * data["max_lvl"])
            for i, y in enumerate(years):
                self.tech_years[(tech_key, i + 1)] = y

        # Stagger the Y positions to prevent branches overlapping (visual layout, not logic)
        y1, y2, y3, y4, y5, y6 = ROW_Y

        self.tech_rows = {
            "infantry_type": y1,
            "cavalry": y4, "trucks": y4, "armored_personnel_carriers": y4, "infantry_fighting_vehicle": y4,
            "militia": y3,
            "artillery": y2,
            "ww1_armored_car": y1, "armored_car": y1, "civilian_car": y1,
            "ww1_tank": y2, "light_tank": y2,
            "medium_tank": y3, "main_battle_tank": y3,
            "heavy_tank": y4, "super_heavy_tank": y4, "landkreuzer_p1000_ratte": y6, "landkreuzer_p1500_monster": y6,
            "electromagnetic_launcher": y6, "railgun": y6,
            "ww1_railroad_gun": y5, "ww2_railroad_gun": y6,
            "destroyer": y1,
            "carrack": y2, "ironclad": y2, "pre-dreadnought": y2, "dreadnought": y2,
            "battleship": y2,
            "aircraft_carrier": y2,
            "submarine": y3,
            "workshop": y1, "basic_factory": y1, "factory": y1,
            "bergius_process": y4, "fuel_refining": y4,
            "basic_recruitment": y2, "recruitment_buildings": y2,
            "general_recruitment": y3,
            "resource_refining": y5
        }

        self.nodes = {"INFANTRY": [], "TANKS": [], "NAVY": [], "INDUSTRY": []}

        for tech_key, data in self.tech_tree.items():
            cat = data["category"]
            if cat in self.nodes:
                max_lvl = data["max_lvl"]
                for lvl in range(1, max_lvl + 1):
                    year = self.tech_years.get((tech_key, lvl), 1900)
                    row_y = self.tech_rows.get(tech_key, ROW_DEFAULT_Y)
                    self.nodes[cat].append({
                        "key": tech_key,
                        "lvl": lvl,
                        "year": year,
                        "base_y": row_y
                    })

    def hud_slots_rect(self):
        """Screen-space rect of the ACTIVE RESEARCH SLOTS box drawn over the timeline."""
        hud_height = HUD_BASE_HEIGHT + (c.RESEARCH_SLOTS * HUD_SLOT_STEP_Y)
        top_y = c.SCREEN_HEIGHT - hud_height - HUD_SCROLLBAR_CLEARANCE
        return pygame.Rect(HUD_X, top_y, HUD_WIDTH, hud_height - HUD_BOTTOM_PAD)

    def _sync_tech_node_positions(self):
        """Slides tech-node buttons with the timeline scroll. They stay visible
        (ResearchHudOverlay draws the slots box over them once they slide behind
        it -- tall nodes like railroad guns/landkreuzers can reach that corner)
        but a click only registers while clear of the HUD, so no sfx sneaks through."""
        hud_rect = self.hud_slots_rect()
        for el in self.elements:
            if getattr(el, 'is_tech_node', False):
                el.rect.x = el.base_x + self.scroll_x
                # Checked against the click position, not the whole button rect, so the
                # still-visible sliver of a node only partly behind the HUD stays clickable.
                el.click_guard = lambda hr=hud_rect: not hr.collidepoint(pygame.mouse.get_pos())

    def update(self):
        super().update()
        if hasattr(self, 'target_scroll_x'):

            self.enforce_scroll_bounds()

            if abs(self.scroll_x - self.target_scroll_x) > 0.5:
                self.scroll_x += (self.target_scroll_x - self.scroll_x) * SCROLL_LERP

            self._sync_tech_node_positions()

    def additional_events(self, event):
        if self.current_category in ["INFANTRY", "TANKS", "NAVY", "INDUSTRY"] and not self.active_modal:
            if event.type == pygame.MOUSEWHEEL:
                self.target_scroll_x += event.y * SCROLL_WHEEL_STEP

            # A grab on the scrollbar itself takes priority over dragging the
            # timeline content -- otherwise a mouse-down on the bar would arm
            # both gestures and fight over the same motion events.
            if not self.handle_timeline_scrollbar(event):
                # Content-drag targets target_scroll_x, same as the wheel, and lets
                # update()'s existing lerp ease scroll_x the rest of the way -- matches
                # every other scrollable list instead of this being the one screen
                # dragged with the right mouse button.
                self.handle_content_drag(event, attr="target_scroll_x", rect_attr="scroll_content_rect",
                                         lo=self.min_scroll_x, hi=self.max_scroll_x, refresh=False, axis="x")

            # --- Clamp user input immediately ---
            self.enforce_scroll_bounds()

            self._sync_tech_node_positions()

    def handle_timeline_scrollbar(self, event):
        """Drag-to-scroll on the horizontal scrollbar track/handle at the
        bottom of the screen. Mirrors GameState.handle_list_scroll's
        grab/drag/snap pattern, but against scroll_x's own signed min/max-year
        range instead of the mixin's fixed 0..negative-max convention -- so it
        drives target_scroll_x directly rather than going through that helper.
        Returns True when the event was consumed.
        """
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was_dragging = self.is_dragging_hscrollbar
            self.is_dragging_hscrollbar = False
            if was_dragging:
                return True

        track = self.hscroll_track_rect
        handle = self.hscroll_handle_rect

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and track:
            if handle and handle.collidepoint(event.pos):
                self.is_dragging_hscrollbar = True  # Grabbing the handle drags from where it sits
                self._cancel_pressed_elements()
                return True
            if track.collidepoint(event.pos):
                self.is_dragging_hscrollbar = True  # Clicking the bare track jumps to that spot
                self._cancel_pressed_elements()
                self.snap_timeline_scroll(event.pos[0])
                return True
        elif event.type == pygame.MOUSEMOTION and self.is_dragging_hscrollbar:
            self.snap_timeline_scroll(event.pos[0])
            return True

        return False

    def snap_timeline_scroll(self, mouse_x):
        """Jumps target_scroll_x to wherever the scrollbar handle was dragged.

        year_to_x's scroll_x convention runs backwards from a left-to-right
        scrollbar (scroll_x is most positive at the timeline's START_YEAR end
        and most negative at its END_YEAR end -- see year_to_x), so the
        min/max passed to the generic horizontal-scrollbar math are negated
        and swapped to land the handle at the correct end.
        """
        track = self.hscroll_track_rect
        if not track:
            return
        value = ui_bars.calculate_scroll_snap_horizontal(
            mouse_x, -self.max_scroll_x, -self.min_scroll_x, track.x, track.width)
        self.target_scroll_x = -value

    def tech_year(self, tech_key, lvl):
        """The year a year-tiered tech reaches this level."""
        years = self.tech_tree.get(tech_key, {}).get("years", [c.START_YEAR])
        return years[min(max(lvl, 1) - 1, len(years) - 1)]

    def get_display_name(self, tech_key, lvl):
        """The player-facing name of a tech at a given level.

        Three naming schemes, each driven by its own table at the top of this
        file rather than a chain of ifs: year-tiered families, fixed one-off
        names, and "<Name> Lvl <n>". Anything unlisted falls back to a title
        cased key plus a roman numeral.
        """
        if tech_key in YEAR_TIER_TECHS:
            return f"{YEAR_TIER_TECHS[tech_key]} {self.tech_year(tech_key, lvl)}"

        if tech_key in FIXED_TECH_NAMES:
            return FIXED_TECH_NAMES[tech_key]

        if tech_key in LEVEL_SUFFIX_TECHS:
            return f"{LEVEL_SUFFIX_TECHS[tech_key]} Lvl {lvl}"

        base_name = tech_key.replace('_', ' ').title()
        return f"{base_name} {c.ROMAN_NUMERALS.get(lvl, str(lvl))}"

    def year_to_x(self, year, include_scroll=True):
        """Screen x of a year on the timeline. The node buttons position
        themselves before the scroll offset is applied, hence the flag."""
        current_year = self.map_screen.time_manager.year
        x = (year - current_year) * self.pixels_per_year + (c.SCREEN_WIDTH // 2)
        return x + self.scroll_x if include_scroll else x

    def tech_cost(self, tech_key):
        return self.tech_tree.get(tech_key, {}).get("cost", DEFAULT_TECH_COST)

    def start_research(self, map_ref):
        self.map_screen = map_ref
        self.current_category = "INFANTRY"
        self.active_modal = None
        self.scroll_x = 0
        self.target_scroll_x = 0
        # Research_Screen is a singleton built once at boot (see main.py), but the
        # scenario's tech_tree can be pruned (disabled units/buildings) on every
        # map load -- rebuild self.nodes from whatever tech_tree looks like now,
        # instead of the stale set of keys computed at startup.
        self.setup_nodes()
        self.enforce_scroll_bounds()
        self.refresh_ui()

    def set_category(self, cat):
        self.current_category = cat
        self.active_modal = None
        self.scroll_x = 0
        self.target_scroll_x = 0
        self.enforce_scroll_bounds()
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = []
        # "is the subject a real nation" rather than "is the player not None":
        # the literal "Spectator" is not a key in nation_data, which is what
        # used to make this screen unreachable for them at all.
        if not self.map_screen or self.subject not in self.map_screen.nation_data: return
        player_data = self.subject_data
        res_levels = player_data.setdefault("research", {})
        queue = player_data.setdefault("research_queue", [])
        
        is_tactical = self.map_screen.tactical_mode

        if self.active_modal:
            st = self.active_modal["status"]
            panel_x, panel_y = self.complete_panel_x, self.complete_panel_y

            self.elements.append(Button(panel_x + MODAL_CANCEL_BTN_X, panel_y + MODAL_BTN_Y_OFFSET, "small", "red", "Cancel", self.close_modal))

            if not self.can_edit:
                # The one slot the action button lives in, so an onlooker has no
                # route to modal_start_research or modal_pause_research at all
                # rather than a disabled-looking button that still fires.
                label = "Tactical: Read Only" if is_tactical else "Spectator: Read Only"
                self.elements.append(Button(panel_x + MODAL_ACTION_BTN_X, panel_y + MODAL_BTN_Y_OFFSET, "medium", "grey", label, lambda: None))
            else:
                if st == "AVAILABLE":
                    if len(queue) >= c.RESEARCH_SLOTS:
                        self.elements.append(Button(panel_x + MODAL_ACTION_BTN_X, panel_y + MODAL_BTN_Y_OFFSET, "medium", "grey", "Slots Full", lambda: None))
                    else:
                        self.elements.append(Button(panel_x + MODAL_ACTION_BTN_X, panel_y + MODAL_BTN_Y_OFFSET, "medium", "blue", "Start Research", self.modal_start_research))
                elif st == "RESEARCHING":
                    self.elements.append(Button(panel_x + MODAL_ACTION_BTN_X, panel_y + MODAL_BTN_Y_OFFSET, "medium", "orange", "Pause", self.modal_pause_research))
                elif st == "LOCKED":
                    self.elements.append(Button(panel_x + MODAL_ACTION_BTN_X, panel_y + MODAL_BTN_Y_OFFSET, "medium", "red", "Missing Reqs", lambda: None))
                elif st == "COMPLETED":
                    self.elements.append(Button(panel_x + MODAL_ACTION_BTN_X, panel_y + MODAL_BTN_Y_OFFSET, "medium", "green", "Researched", lambda: None))
            return
        
        self.elements.append(Button(*EXIT_BTN_POS, "small", "red", "Exit", self.exit_screen))

        for i, cat in enumerate(self.categories):
            color = "green" if self.current_category == cat else "blue"
            btn = Button(CATEGORY_BTN_START_X + (i * CATEGORY_BTN_STEP_X), CATEGORY_BTN_Y, "medium", color, cat, lambda c=cat: self.set_category(c))
            self.elements.append(btn)

        if self.current_category == "COMPLETED":
            pass
        else:
            self.draw_tech_nodes(res_levels, queue)
            # Drawn last so it covers any tech-node button still sliding past it.
            self.elements.append(ScreenLayer(self, "draw_hud_slots"))
            self.elements.append(ScreenLayer(self, "draw_timeline_scrollbar"))

    def get_button_size(self, tech_key, display_name):
        """Picks a node's button size from NODE_SIZE_RULES (first match wins)."""
        name = display_name.lower()
        for needles, size in NODE_SIZE_RULES:
            if any(needle in name for needle in needles):
                return size

        if self.current_category in WIDE_RESEARCH_CATEGORIES:
            return "tech_square_wide"

        return "tech_square"

    def draw_tech_nodes(self, res_levels, queue):
        for node in self.nodes.get(self.current_category, []):
            tech_key = node["key"]
            lvl = node["lvl"]
            year = node["year"]
            base_y = node["base_y"]
            
            # 1. Get the display name first
            display_name = self.get_display_name(tech_key, lvl)
            
            # 2. Use our new helper to get the size
            btn_size = self.get_button_size(tech_key, display_name)
            btn_w, btn_h = c.SIZES.get(btn_size, (80, 80))
            x_offset = btn_w // 2

            base_x = self.year_to_x(year, include_scroll=False) - x_offset
            # Row's vertical center line is base_y + 30 (matches draw_connections'
            # anchor, based on the standard 60px-tall button). Center every node on
            # that line instead of always dropping its top at base_y, so taller
            # buttons (railroad guns, landkreuzers, ...) don't hang below the row.
            node_y = (base_y + NODE_ROW_HALF_HEIGHT) - (btn_h // 2)
            
            # ... (Rest of your existing logic for status, color, and icon)
            cur_lvl = res_levels.get(tech_key, 0)
            is_researching = any(q["tech_name"] == tech_key for q in queue)
            
            status = "LOCKED"
            if cur_lvl >= lvl:
                status = "COMPLETED"
            elif is_researching and cur_lvl + 1 == lvl:
                status = "RESEARCHING"
            elif cur_lvl == lvl - 1:
                reqs = self.tech_tree[tech_key].get("req", {})
                if self.check_requirements(res_levels, reqs, lvl):
                    status = "AVAILABLE"
                else:
                    status = "LOCKED"
                    
            btn_color = STATUS_COLORS[status]

            unlocks = queries.get_tech_unlocks(tech_key, lvl)
            is_large = (self.building_library.get(tech_key, {}).get("group") in c.LARGE_ICON_BUILDING_GROUPS or 
                        any(self.building_library.get(u, {}).get("group") in c.LARGE_ICON_BUILDING_GROUPS for u in unlocks))
            
            icon_scale = 4.0 if is_large else 2.0

            icon_name = TECH_ICON_OVERRIDES.get(tech_key, display_name)
            icon = symbol_loader.get_symbol(icon_name, icon_scale)
            
            node_info = {
                "tech_key": tech_key,
                "level": lvl,
                "display_name": display_name,
                "cost": self.tech_cost(tech_key),
                "status": status,
                "icon": icon,
                "target_year": year
            }
            
            btn = Button(base_x + self.scroll_x, node_y, btn_size, btn_color, display_name,
                         lambda n=node_info: self.open_modal(n), image=icon, show_text=False)
            
            btn.base_x = base_x
            btn.is_tech_node = True
            
            self.elements.append(btn)

    def check_requirements(self, res_levels, reqs, target_lvl=1):
        # Single source of truth, so this screen and the AI can never disagree
        # about whether a tech is available.
        return queries.check_tech_requirements(res_levels, reqs, target_lvl)

    def open_modal(self, node_info):
        self.active_modal = node_info
        self.refresh_ui()
        
    def close_modal(self):
        self.active_modal = None
        self.refresh_ui()

    def modal_start_research(self):
        self.start_or_resume_research(self.active_modal["tech_key"])
        self.close_modal()

    def modal_pause_research(self):
        self.pause_research(self.active_modal["tech_key"])
        self.close_modal()

    def start_or_resume_research(self, tech_name):
        if not self.can_edit:
            return
        player_data = self.subject_data
        progress_cache = player_data.setdefault("research_progress", {})
        total_cost = self.tech_cost(tech_name)
        points_remaining = progress_cache.pop(tech_name, total_cost)
            
        player_data["research_queue"].append({
            "tech_name": tech_name, 
            "points_remaining": points_remaining
        })
        self.refresh_ui()

    def pause_research(self, tech_name):
        if not self.can_edit:
            return
        player_data = self.subject_data
        queue = player_data.get("research_queue", [])
        progress_cache = player_data.setdefault("research_progress", {})
        for i, project in enumerate(queue):
            if project["tech_name"] == tech_name:
                progress_cache[tech_name] = project["points_remaining"]
                queue.pop(i)
                break
        self.refresh_ui()

    def draw_timeline_axis(self, surface):
        if self.current_category in ["COMPLETED"] or self.active_modal:
            return

        current_year = self.map_screen.time_manager.year
        axis_y = TIMELINE_AXIS_Y

        pygame.draw.line(surface, (150, 150, 150), (0, axis_y), (c.SCREEN_WIDTH, axis_y), 3)
        year_font = fonts.get("heading2")

        start_year = int((-self.scroll_x - (c.SCREEN_WIDTH // 2)) / self.pixels_per_year) + current_year - TIMELINE_YEAR_PADDING
        end_year = int((c.SCREEN_WIDTH - self.scroll_x - (c.SCREEN_WIDTH // 2)) / self.pixels_per_year) + current_year + TIMELINE_YEAR_PADDING

        # --- Clamp the visual tick marks ---
        start_year = max(c.START_YEAR, start_year)
        end_year = min(c.END_YEAR + 1, end_year) # +1 so the actual END_YEAR is drawn
        # ----------------------------------------

        for year in range(start_year, end_year):
            x = self.year_to_x(year)

            # Removed the modulo 5 check; draws a major tick and text for every year
            pygame.draw.line(surface, (200, 200, 200), (x, axis_y - TIMELINE_TICK_HALF), (x, axis_y + TIMELINE_TICK_HALF), 2)
            txt = year_font.render(str(year), True, c.UI_TEXT_LIGHT)
            surface.blit(txt, (x - txt.get_width()//2, axis_y + TIMELINE_YEAR_LABEL_OFFSET_Y))

    def draw_connections(self, surface, res_levels):
        import math
        nodes = self.nodes.get(self.current_category, [])
        lookup = {(n["key"], n["lvl"]): n for n in nodes}
        
        for node in nodes:
            k = node["key"]
            l = node["lvl"]

            x1 = self.year_to_x(node["year"])
            y1 = node["base_y"] + NODE_ROW_HALF_HEIGHT
            p1 = (x1, y1)
            
            def draw_line_to_prev(req_k, req_lvl):
                prev_node = lookup.get((req_k, req_lvl))
                if prev_node:
                    x2 = self.year_to_x(prev_node["year"])
                    y2 = prev_node["base_y"] + NODE_ROW_HALF_HEIGHT
                    p2 = (x2, y2)
                    color = (0, 255, 0) if res_levels.get(req_k, 0) >= req_lvl else (100, 100, 100)
                    
                    pygame.draw.line(surface, color, p2, p1, 3)
                    
                    # Draw Arrow in the middle pointing from p2 -> p1
                    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
                    dx = p1[0] - p2[0]
                    dy = p1[1] - p2[1]

                    # Only draw arrows if the line is long enough to avoid extreme clutter
                    if math.hypot(dx, dy) > 20:
                        angle_rad = math.atan2(dy, dx)
                        head_size = 10
                        # Shift the tip forward so the arrowhead's centroid (not its tip) sits on the midpoint
                        half_depth = (head_size * math.cos(math.pi / 6)) / 2
                        tip = (mx + half_depth * math.cos(angle_rad),
                               my + half_depth * math.sin(angle_rad))
                        left_wing = (tip[0] - head_size * math.cos(angle_rad - math.pi / 6),
                                     tip[1] - head_size * math.sin(angle_rad - math.pi / 6))
                        right_wing = (tip[0] - head_size * math.cos(angle_rad + math.pi / 6),
                                       tip[1] - head_size * math.sin(angle_rad + math.pi / 6))
                        pygame.draw.polygon(surface, color, [tip, left_wing, right_wing])

            # Draw standard linear connection to previous level
            if l > 1:
                draw_line_to_prev(k, l - 1)
                
            reqs = self.tech_tree[k].get("req", {})
            
            def process_req(req_k, req_v):
                # If the requirement is dynamic, draw it for EVERY level
                if isinstance(req_v, str) and req_v.startswith("MATCH_LEVEL"):
                    req_val = l
                    if "+" in req_v: req_val += int(req_v.split("+")[1])
                    elif "-" in req_v: req_val -= int(req_v.split("-")[1])
                    draw_line_to_prev(req_k, req_val)
                # If the requirement is static (e.g. basic_factory 1), ONLY draw it from level 1
                elif l == 1:
                    draw_line_to_prev(req_k, req_v)

            # Draw an arrow per prerequisite, whatever OR/AND nesting it sits in
            for req_k, req_v in queries.walk_tech_requirements(reqs):
                process_req(req_k, req_v)

    def draw_hud_slots(self, surface):
        hud_rect = self.hud_slots_rect()
        pygame.draw.rect(surface, (40, 40, 60), hud_rect)
        pygame.draw.rect(surface, (200, 200, 200), hud_rect, 2)
        hud_font = fonts.get("button")
        surface.blit(hud_font.render("ACTIVE RESEARCH SLOTS:", True, (255, 255, 0)), (HUD_TITLE_X, hud_rect.top + HUD_TITLE_OFFSET_Y))

        queue = self.subject_data.get("research_queue", [])
        for i in range(c.RESEARCH_SLOTS):
            y_off = hud_rect.top + HUD_FIRST_SLOT_OFFSET_Y + (i * HUD_SLOT_STEP_Y)
            if i < len(queue):
                p = queue[i]
                tech_name = p['tech_name'].replace('_',' ').title()
                pts_left = p.get('points_remaining', 0)
                total_cost = self.tech_cost(p['tech_name'])
                progress_pct = int((1 - (pts_left / total_cost)) * 100)
                
                txt = f"Slot {i+1}: {tech_name} ({pts_left} pts left | {progress_pct}%)"
                surface.blit(hud_font.render(txt, True, c.COLOR_SUCCESS_GREEN), (HUD_SLOT_TEXT_X, y_off))
            else:
                surface.blit(hud_font.render(f"Slot {i+1}: [EMPTY]", True, c.UI_TEXT_MUTED), (HUD_SLOT_TEXT_X, y_off))

    def draw_timeline_scrollbar(self, surface):
        """Full-width scrollbar along the very bottom of the screen, so the
        entire START_YEAR..END_YEAR timeline can be dragged in one go instead
        of only via the wheel or a drag on the (much narrower) node area."""
        track_x = HSCROLLBAR_MARGIN_X
        track_y = c.SCREEN_HEIGHT - HSCROLLBAR_MARGIN_BOTTOM - HSCROLLBAR_HEIGHT
        track_w = c.SCREEN_WIDTH - (2 * HSCROLLBAR_MARGIN_X)

        # See snap_timeline_scroll for why this is negated/swapped.
        track, handle = ui_bars.draw_standard_scrollbar_horizontal(
            surface, -self.scroll_x, -self.max_scroll_x, -self.min_scroll_x,
            track_x, track_y, track_w, HSCROLLBAR_HEIGHT)
        self.hscroll_track_rect = track
        self.hscroll_handle_rect = handle

    def draw_subscreen_modal(self, surface):
        ui_bars.draw_fullscreen_overlay(surface, MODAL_ALPHA)

        panel_rect = pygame.Rect(self.complete_panel_x, self.complete_panel_y, MODAL_WIDTH, MODAL_HEIGHT)
        pygame.draw.rect(surface, (30, 30, 40), panel_rect)
        pygame.draw.rect(surface, (200, 200, 200), panel_rect, 2)

        font_title = fonts.get("heading1")
        font_med = fonts.get("heading2")
        font_small = fonts.get("normal")

        title = font_title.render(self.active_modal["display_name"].upper(), True, (255, 255, 255))
        surface.blit(title, (panel_rect.x + MODAL_TITLE_X, panel_rect.y + MODAL_TITLE_Y))

        if self.active_modal["icon"]:
            original_icon = self.active_modal["icon"]
            width, height = original_icon.get_size()

            scale_factor = min(MODAL_ICON_BOX / width, MODAL_ICON_BOX / height)
            
            new_width = width * scale_factor
            new_height = height * scale_factor
        
            big_icon = pygame.transform.scale(original_icon, (new_width, new_height))
            
            surface.blit(big_icon, (panel_rect.x + MODAL_ICON_X + (MODAL_ICON_BOX - new_width) // 2,
                                    panel_rect.y + MODAL_ICON_Y + (MODAL_ICON_BOX - new_height) // 2))

        cost = self.active_modal["cost"]
        
        days_per_turn = queries.get_days_per_turn(self.map_screen.scenario_settings)
        pts_per_turn = c.BASE_RESEARCH_POINTS_PER_DAY * days_per_turn
        
        base_time = max(1, cost // max(1, pts_per_turn)) 
        cost_txt = font_med.render(f"Base Research Cost: {queries.format_number(cost)} pts ({int(base_time)} turns)", True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(cost_txt, (panel_rect.x + MODAL_TEXT_X, panel_rect.y + MODAL_COST_Y))

        # --- AHEAD OF TIME SIMULATION ---
        current_exact_year = queries.get_exact_year(self.map_screen.time_manager)
        target_year = self.active_modal.get("target_year", 1900)
        
        actual_turns = 0
        sim_year = current_exact_year
        pts_accumulated = 0
        
        base_pts_per_turn = c.BASE_RESEARCH_POINTS_PER_DAY * days_per_turn
        year_inc = days_per_turn / 360.0
        
        # Simulate the research progress turn-by-turn using the central math query
        while pts_accumulated < cost and actual_turns < c.MAX_RESEARCH_TURN_SIMULATION:
            mult = queries.get_research_multiplier(sim_year, target_year)
            pts_accumulated += (base_pts_per_turn * mult)
            sim_year += year_inc
            actual_turns += 1
            
        if actual_turns > base_time:
            # --- MODIFIED WARNING LOGIC ---
            warn_x = panel_rect.x + MODAL_TEXT_X
            icon_h = max(16, font_small.get_height())
            warn_icon = ui_elements.scale_icon(c.ICON_WARNING, icon_h)
            if warn_icon:
                surface.blit(warn_icon, (warn_x, panel_rect.y + MODAL_WARNING_Y + 2))
                warn_x += icon_h + 5


            warn_txt = font_small.render(f"Ahead of Time Penalty! Estimated Actual Time: ~{actual_turns} turns", True, (255, 100, 100))
            surface.blit(warn_txt, (warn_x, panel_rect.y + MODAL_WARNING_Y))
        # --------------------------------

        y_off = panel_rect.y + MODAL_BODY_START_Y # Shifted down to make room for the warning text
        text_x = panel_rect.x + MODAL_TEXT_X
        display_name = self.active_modal["display_name"]
        tech_key = self.active_modal["tech_key"]
        level = self.active_modal["level"]
        
        # Show what this tech unlocks - one per line so a long bonus string
        # doesn't get crammed alongside others and run off the edge of the modal.
        unlocks = queries.get_tech_unlocks(tech_key, level)
        if unlocks:
            surface.blit(font_small.render("Unlocks:", True, (150, 255, 150)), (text_x, y_off))
            y_off += MODAL_LINE_STEP_Y
            for unlock in unlocks:
                surface.blit(font_small.render(f"- {unlock}", True, (150, 255, 150)), (text_x, y_off))
                y_off += MODAL_LINE_STEP_Y
            
        # Collect entities to show stats for (both the tech itself AND anything it unlocks)
        entities_to_show = []
        if display_name in self.unit_library or display_name in self.building_library:
            entities_to_show.append(display_name)
            
        for unlock in unlocks:
            if unlock in self.unit_library or unlock in self.building_library:
                if unlock not in entities_to_show:
                    entities_to_show.append(unlock)
                    
        # Fallback ONLY if there's no unit, no building, and no programmatic unlocks
        if not entities_to_show and not unlocks:
            txt1 = "Advanced statistical data unavailable."
            surface.blit(font_small.render(txt1, True, c.UI_TEXT_MUTED), (text_x, y_off))
            y_off += MODAL_LINE_STEP_Y


        # Draw stats for all relevant entities dynamically
        for entity in entities_to_show:
            # Draw a sub-header if the tech unlocks multiple things or if the unlocked item has a different name than the tech
            if entity != display_name or len(entities_to_show) > 1:
                surface.blit(font_small.render(f"Stats for {entity}:", True, c.COLOR_GOLD_HIGHLIGHT), (text_x, y_off))
                y_off += MODAL_SUBHEAD_STEP_Y
                
            if entity in self.unit_library:
                s = self.unit_library[entity]
                
                # --- MODIFIED COMBAT STATS STRING ---
                draw_combat_stats(
                    surface, font_small, "Combat Stats:   ",
                    s.get('attack', 0), s.get('defense', 0), s.get('health', 0), s.get('speed', 0),
                    text_x, y_off, (200, 200, 200)
                )
                y_off += MODAL_LINE_STEP_Y

                if 'bombard_attack' in s:
                    draw_bombardment_stats(
                        surface, font_small,
                        s.get('bombard_attack', 0), s.get('bombard_range', 0),
                        text_x, y_off, (200, 200, 200)
                    )
                    y_off += MODAL_LINE_STEP_Y

                draw_resource_string(
                    surface, font_small, "Production Cost:   ",
                    s.get('cost_materials', 0), s.get('cost_manpower', 0), s.get('cost_fuel', 0),
                    text_x, y_off, (200, 200, 200)
                )
                y_off += MODAL_LINE_STEP_Y
                
            elif entity in self.building_library:
                if entity == "Basic Factory" and self.map_screen and self.subject in self.map_screen.nation_data:
                    s = queries.get_building_cost(entity, self.subject, self.map_screen.map_data, self.building_library)
                else:
                    s = self.building_library[entity]

                txt1 = f"Construction Time: {max(1, s.get('time',0) // 1)} turns"
                surface.blit(font_small.render(txt1, True, c.UI_TEXT_LIGHT), (text_x, y_off))
                y_off += MODAL_LINE_STEP_Y
                
                draw_resource_string(
                    surface, font_small, "Yield (Per Turn):   ",
                    s.get('prod_materials', 0), s.get('prod_manpower', 0), s.get('prod_fuel', 0),
                    text_x, y_off, (150, 255, 150), is_yield=True
                )
                y_off += MODAL_LINE_STEP_Y
                
                draw_resource_string(
                    surface, font_small, "Construction Cost:   ",
                    s.get('cost_materials', 0), s.get('cost_manpower', 0), s.get('cost_fuel', 0),
                    text_x, y_off, (200, 200, 200)
                )
                y_off += MODAL_LINE_STEP_Y
                
            y_off += MODAL_ENTITY_PADDING_Y # Padding between items

    def render_completed_text_list(self, surface):
        player_data = self.subject_data
        res_levels = player_data.get("research", {})
        
        text_font = fonts.get("button")
        label_font = fonts.get("heading2")
        
        organized = {cat: [] for cat in self.categories if cat != "COMPLETED"}
        for tech_id, data in self.tech_tree.items():
            cat = data["category"]
            lvl = res_levels.get(tech_id, 0)
            organized[cat].append((tech_id, lvl, data["max_lvl"]))

        for i, (cat_name, techs) in enumerate(organized.items()):
            curr_x = COMPLETED_START_X + (i * COMPLETED_COLUMN_WIDTH)
            curr_y = COMPLETED_START_Y
            
            head = label_font.render(cat_name, True, c.COLOR_GOLD_HIGHLIGHT)
            surface.blit(head, (curr_x, curr_y))
            curr_y += COMPLETED_HEADER_STEP_Y
            
            techs.sort(key=lambda x: x[2] != 9999)
            
            for tech_id, lvl, max_lvl in techs:
                display_name = tech_id.replace('_', ' ').title()
                
                if max_lvl == 1:
                    val_text = ": YES" if lvl >= 1 else ": NO"
                elif tech_id in YEAR_TIER_TECHS:
                    val_text = f": {self.tech_year(tech_id, lvl)}" if lvl > 0 else ": 0"
                else:
                    val_text = f": {lvl}"

                color = (200, 200, 200) if lvl > 0 else (100, 100, 100)

                txt_surf = text_font.render(f"{display_name}{val_text}", True, color)
                surface.blit(txt_surf, (curr_x + COMPLETED_INDENT_X, curr_y))
                curr_y += COMPLETED_ROW_STEP_Y

    def enforce_scroll_bounds(self):
        """Prevents the timeline from scrolling past the defined START_YEAR or END_YEAR."""
        if self.map_screen:
            current_year = self.map_screen.time_manager.year
            # Negative scroll moves the camera to future years (right), positive to past years (left)
            self.min_scroll_x = -((c.END_YEAR - current_year) * self.pixels_per_year)
            self.max_scroll_x = -((c.START_YEAR - current_year) * self.pixels_per_year)

            self.target_scroll_x = max(self.min_scroll_x, min(self.target_scroll_x, self.max_scroll_x))
            self.scroll_x = max(self.min_scroll_x, min(self.scroll_x, self.max_scroll_x))

    def additional_draw(self, surface):
        if not self.map_screen: return
        
        # --- Axis Rendering ---
        self.draw_timeline_axis(surface)
        
        # --- Standard Header ---
        pygame.draw.rect(surface, (40, 40, 50), (0, 0, c.SCREEN_WIDTH, HEADER_HEIGHT))
        pygame.draw.line(surface, (200, 200, 200), (0, HEADER_HEIGHT), (c.SCREEN_WIDTH, HEADER_HEIGHT), 2)

        font = fonts.get("heading1")
        # Whose tree this is, once it can be somebody else's. A player is only
        # ever looking at their own, so naming them there would be noise.
        looking_at = "" if self.subject == self.map_screen.player_country else f"{self.subject} -- "
        ts = font.render(f"{looking_at}VIEWING: {self.current_category}", True, (255, 255, 255))
        surface.blit(ts, (c.SCREEN_WIDTH//2 - ts.get_width()//2, HEADER_TITLE_Y))

        # --- DYNAMIC OUTPUT CALCULATION ---
        days_per_turn = queries.get_days_per_turn(self.map_screen.scenario_settings)
        pts_per_turn = int(c.BASE_RESEARCH_POINTS_PER_DAY * days_per_turn)
        output_text = font.render(f"RESEARCH OUTPUT: {pts_per_turn} pts/turn", True, (0, 255, 255))
        surface.blit(output_text, (c.SCREEN_WIDTH - output_text.get_width() - HEADER_OUTPUT_MARGIN_X, HEADER_OUTPUT_Y))

        if self.current_category == "COMPLETED":
            self.render_completed_text_list(surface)
        else:
            player_data = self.subject_data
            res_levels = player_data.get("research", {})
            self.draw_connections(surface, res_levels)

        # ACTIVE RESEARCH SLOTS is now drawn by ResearchHudOverlay (appended last
        # in refresh_ui), so it renders on top of any scrolled tech-node button.

        if self.active_modal:
            self.draw_subscreen_modal(surface)

    def handle_back_key(self):
        # Escape closes an open tech modal before it leaves the screen.
        if self.active_modal:
            self.close_modal()
        else:
            self.exit_screen()
