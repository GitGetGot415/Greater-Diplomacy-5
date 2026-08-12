"""Native pygame replacements for the map editor's convoy/resource/clear
tkinter tool windows -- see screens/editor_screens/__init__.py."""
import pygame
import data.constants as c
from data import queries
from gameState import MapOverlayScreen
from ui_elements import Button, TextField, make_back_button
from ui import confirm_dialog
from map_logic.rendering.font_manager import fonts

# ==========================================
# CONVOY / TRUCK CONVERTER
# ==========================================

class Convoy_Converter_Screen(MapOverlayScreen):
    pans_camera = False
    scroll_anywhere = True
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_CONFIRM
    PANEL_TITLE = "Convert Units"
    TITLE_PRESET = "heading2"
    TITLE_Y_OFFSET = c.MODAL_TITLE_Y_OFFSET

    def __init__(self, map_screen, province):
        super().__init__(map_screen, pygame.Rect(0, 0, 560, c.SCREEN_HEIGHT - 160))
        self.back_state = "MAP"
        self.province = province
        self.unit_lib = queries.get_unit_library()
        self.selected = {i for i, unit in enumerate(province.get("units", [])) if "original_type" in unit}
        self.refresh_ui()

    def toggle(self, idx):
        if idx in self.selected:
            self.selected.discard(idx)
        else:
            self.selected.add(idx)
        self.refresh_ui()

    def refresh_ui(self):
        p = self.panel_rect
        self.elements = [
            make_back_button(self.exit_screen, style="map"),
            Button(p.centerx - 110, p.bottom - 55, "medium", "green", "Save Changes", self.save),
        ]

        units = self.province.get("units", [])
        row_top = p.y + 70
        view_h = p.height - 140
        row_x = p.x + 20
        row_w = p.width - 40
        cull_top, cull_bottom = p.y + 60, p.bottom - 70
        self.scroll_content_rect = pygame.Rect(p.x, cull_top, p.width, cull_bottom - cull_top)
        for i, y in self.layout_list_rows(len(units), 40, row_top, view_h=view_h,
                                          cull_top=cull_top, cull_bottom=cull_bottom):
            unit = units[i]
            name = unit.get("original_type", unit.get("type", "Unknown"))
            is_naval = self.unit_lib.get(name, {}).get("naval_unit", False)
            suffix = "(Convoy)" if not is_naval else "(Truck)"
            checked = i in self.selected
            label = f"{'[X]' if checked else '[ ]'} {name} {suffix}"
            btn = Button(row_x, y, "list_row", "green" if checked else "grey", label, lambda ii=i: self.toggle(ii))
            btn.rect.width = row_w
            btn.is_scrollable = True
            btn.click_guard = self.scroll_click_guard
            self.elements.append(btn)

        self.list_view_h = view_h

    def save(self):
        units = self.province.get("units", [])
        for i, unit in enumerate(units):
            want = i in self.selected
            if want and "original_type" not in unit:
                name = unit.get("type", "Unknown")
                is_naval = self.unit_lib.get(name, {}).get("naval_unit", False)
                target = "Convoy" if not is_naval else "Truck"

                unit["original_type"] = unit["type"]
                unit["original_speed"] = unit.get("speed", 1)
                unit["original_max_health"] = unit.get("max_health", c.DEFAULT_UNIT_HP)
                unit["original_attack"] = unit.get("attack", c.DEFAULT_UNIT_ATK)
                unit["original_defense"] = unit.get("defense", c.DEFAULT_UNIT_DEF)

                pct = unit.get("health", 1) / max(1, unit.get("max_health", 1))
                unit["type"] = f"{target} ({unit['type']})"
                unit["speed"] = 1

                if target == "Convoy":
                    unit["naval_unit"] = True
                    unit["max_health"] = c.CONVOY_MAX_HP
                    unit["attack"] = c.CONVOY_ATK
                    unit["defense"] = c.CONVOY_DEF
                else:
                    unit["naval_unit"] = False
                    unit["max_health"] = c.TRUCK_MAX_HP
                    unit["attack"] = c.TRUCK_ATK
                    unit["defense"] = c.TRUCK_DEF

                unit["health"] = unit["max_health"] * pct
            elif not want and "original_type" in unit:
                queries.revert_transport(unit)

        self.map_screen.show_feedback("Unit transport status updated!")
        self.done = True

    def draw_content(self, surface):
        p = self.panel_rect
        self.draw_panel(surface)
        self.draw_list_scrollbar(surface, p.right - 15, p.y + 70, self.list_view_h)

# ==========================================
# RESOURCE BRUSH
# ==========================================

class Resource_Brush_Screen(MapOverlayScreen):
    pans_camera = False
    RESOURCE_TYPES = ["Iron", "Coal", "Oil", "Wheat", "None"]
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_SPECIAL
    PANEL_TITLE = "Resource Brush"
    TITLE_PRESET = "heading2"
    TITLE_Y_OFFSET = c.MODAL_TITLE_Y_OFFSET

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 400, 300))
        self.back_state = "MAP"
        self.selected_resource = "Iron"
        self.amount_field = TextField(0, 0, 150, 40, "50", numeric=True)
        self.refresh_ui()

    def refresh_ui(self):
        p = self.panel_rect
        self.amount_field.rect.topleft = (p.centerx - 75, p.y + 190)

        self.elements = [
            make_back_button(self.exit_screen, style="map"),
            Button(p.centerx - 130, p.y + 90, "medium", "blue", f"Resource: {self.selected_resource}", self.pick_resource),
            Button(p.centerx - 100, p.bottom - 55, "medium", "purple", "Confirm Selection", self.confirm),
            self.amount_field,
        ]

    def pick_resource(self):
        def on_pick(val):
            self.selected_resource = val
            self.refresh_ui()
        queries.open_listbox_selector(self.map_screen, "Select Resource Type", "Choose a resource type:",
                                      self.RESOURCE_TYPES, on_pick)
        self.refresh_ui()

    def confirm(self):
        try:
            amt = int(self.amount_field.text)
        except ValueError:
            confirm_dialog.show_error("Error", "Amount must be a whole number.")
            return

        self.map_screen.brush_resource_type = self.selected_resource
        self.map_screen.brush_resource_amount = amt
        self.map_screen.editor_mode = "RESOURCE"

        if self.selected_resource == "None":
            self.map_screen.show_feedback("Brush: Erase Resources")
        else:
            self.map_screen.show_feedback(f"Brush: {self.selected_resource} ({amt})")

        self.done = True

    def draw_content(self, surface):
        p = self.panel_rect
        self.draw_panel(surface)

        label = fonts.get("normal").render("Amount:", True, c.UI_TEXT_BRIGHT)
        surface.blit(label, label.get_rect(midright=(p.centerx - 85, p.y + 210)))

# ==========================================
# CLEAR MAP ITEMS
# ==========================================

class Clear_Map_Screen(MapOverlayScreen):
    pans_camera = False
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_DANGER
    PANEL_TITLE = "Clear Map Items"
    TITLE_PRESET = "heading2"
    TITLE_Y_OFFSET = c.MODAL_TITLE_Y_OFFSET

    OPTIONS = [
        "all units", "all buildings", "all resources",
        "all units from (x) country", "all buildings on (x) countries territory",
        "all resources on (x) countries territory", "all (x) units", "all (x) resources",
        "all (x) units from country (x)", "all (x) resources on (x) countries territory",
    ]
    RESOURCE_TYPES = ["Iron", "Coal", "Oil", "Wheat"]

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 600, 420))
        self.back_state = "MAP"

        self.selected_option = self.OPTIONS[0]
        self.selected_country = ""
        self.selected_unit_type = ""
        self.selected_resource_type = ""

        existing_owners = {p.get("owner") for p in map_screen.map_data.values()}
        self.available_countries = sorted(n for n in existing_owners if n and n not in ["Unclaimed", "The Rot"])

        existing_unit_types = set()
        for prov in map_screen.map_data.values():
            for unit in prov.get("units", []):
                if "type" in unit:
                    existing_unit_types.add(unit["type"])
        self.available_unit_types = sorted(existing_unit_types)

        self.refresh_ui()

    def needs_country(self):
        return "country" in self.selected_option or "countries" in self.selected_option

    def needs_unit_type(self):
        return self.selected_option in ("all (x) units", "all (x) units from country (x)")

    def needs_resource_type(self):
        return self.selected_option in ("all (x) resources", "all (x) resources on (x) countries territory")

    def refresh_ui(self):
        p = self.panel_rect
        opt_btn = Button(p.x + 30, p.y + 90, "large", "blue", self.selected_option, self.pick_option)
        opt_btn.rect.width = p.width - 60

        self.elements = [
            make_back_button(self.exit_screen, style="map"),
            Button(p.centerx - 130, p.bottom - 55, "editor_ui", "red", "Confirm Clear", self.confirm_clear),
            opt_btn,
        ]

        y = p.y + 190
        if self.needs_country():
            label = self.selected_country or "Select Country..."
            btn = Button(p.x + 30, y, "editor_ui", "orange", f"Country: {label}", self.pick_country)
            btn.rect.width = p.width - 60
            self.elements.append(btn)
            y += 60
        if self.needs_unit_type():
            label = self.selected_unit_type or "Select Unit..."
            btn = Button(p.x + 30, y, "editor_ui", "orange", f"Unit: {label}", self.pick_unit_type)
            btn.rect.width = p.width - 60
            self.elements.append(btn)
            y += 60
        if self.needs_resource_type():
            label = self.selected_resource_type or "Select Resource..."
            btn = Button(p.x + 30, y, "editor_ui", "orange", f"Resource: {label}", self.pick_resource_type)
            btn.rect.width = p.width - 60
            self.elements.append(btn)
            y += 60

    def pick_option(self):
        def on_pick(val):
            self.selected_option = val
            self.refresh_ui()
        queries.open_listbox_selector(self.map_screen, "Select What to Clear", "Choose an option:", self.OPTIONS, on_pick)
        self.refresh_ui()

    def pick_country(self):
        def on_pick(val):
            self.selected_country = val
            self.refresh_ui()
        queries.open_listbox_selector(self.map_screen, "Select Country", "Choose a country:",
                                      self.available_countries, on_pick)
        self.refresh_ui()

    def pick_unit_type(self):
        def on_pick(val):
            self.selected_unit_type = val
            self.refresh_ui()
        queries.open_listbox_selector(self.map_screen, "Select Unit Type", "Choose a unit type:",
                                      self.available_unit_types, on_pick)
        self.refresh_ui()

    def pick_resource_type(self):
        def on_pick(val):
            self.selected_resource_type = val
            self.refresh_ui()
        queries.open_listbox_selector(self.map_screen, "Select Resource", "Choose a resource:",
                                      self.RESOURCE_TYPES, on_pick)
        self.refresh_ui()

    def confirm_clear(self):
        opt = self.selected_option
        c_val = self.selected_country
        u_val = self.selected_unit_type
        r_val = self.selected_resource_type

        if self.needs_country() and not c_val:
            confirm_dialog.show_error("Error", "Please select a country.")
            return
        if self.needs_unit_type() and not u_val:
            confirm_dialog.show_error("Error", "Please select a unit type.")
            return
        if self.needs_resource_type() and not r_val:
            confirm_dialog.show_error("Error", "Please select a resource type.")
            return

        msg = f"Are you sure you want to clear:\n{opt}"
        if c_val and self.needs_country(): msg += f"\nCountry: {c_val}"
        if u_val and self.needs_unit_type(): msg += f"\nUnit: {u_val}"
        if r_val and self.needs_resource_type(): msg += f"\nResource: {r_val}"

        def on_confirm(ok):
            if not ok:
                return

            map_data = self.map_screen.map_data
            for prov_id, prov_data in map_data.items():
                owner = prov_data.get("owner", "Unclaimed")

                if "countries territory" in opt and owner != c_val:
                    continue

                if "units" in opt:
                    if opt in ("all units", "all units from (x) country"):
                        if opt == "all units from (x) country":
                            prov_data["units"] = [u for u in prov_data.get("units", []) if u.get("owner") != c_val]
                        else:
                            prov_data["units"] = []
                    elif opt == "all (x) units":
                        prov_data["units"] = [u for u in prov_data.get("units", []) if u.get("type") != u_val]
                    elif opt == "all (x) units from country (x)":
                        prov_data["units"] = [u for u in prov_data.get("units", [])
                                              if not (u.get("type") == u_val and u.get("owner") == c_val)]

                if "buildings" in opt:
                    prov_data["buildings"] = []

                if "resources" in opt:
                    if opt in ("all resources", "all resources on (x) countries territory"):
                        prov_data["resources"] = {}
                        if "resource" in prov_data:
                            del prov_data["resource"]
                    elif opt in ("all (x) resources", "all (x) resources on (x) countries territory"):
                        if isinstance(prov_data.get("resources"), dict) and r_val in prov_data["resources"]:
                            del prov_data["resources"][r_val]
                        if prov_data.get("resource", {}).get("type") == r_val:
                            del prov_data["resource"]

            self.map_screen.refresh_all_maps()
            self.map_screen.show_feedback("Map cleared according to criteria.")
            self.done = True

        confirm_dialog.ask_yes_no("Confirm Clear", msg, on_confirm)

    def draw_content(self, surface):
        self.draw_panel(surface)
