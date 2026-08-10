"""Native pygame replacement for the map editor's research (tech) tkinter tool
window -- see screens/editor_screens/__init__.py."""
import pygame
import data.constants as c
from data import queries
from gameState import MapOverlayScreen
from ui_elements import Button, TextField, make_back_button
from ui import confirm_dialog
from ui.bars import ui_bars
from ui.screen_runner import _run_pygame_sub_screen
from map_logic.rendering.font_manager import fonts

# ==========================================
# MAP RESEARCH (TECH) EDITOR
# ==========================================

class Research_Edit_Screen(MapOverlayScreen):
    """Shared editor for a single country, all countries in bulk, or the map default."""
    pans_camera = False
    scroll_anywhere = True
    ROW_HEIGHT = 36

    def __init__(self, map_screen, screen_title, base_data, tech_tree, on_save):
        super().__init__(map_screen, pygame.Rect(0, 0, 640, c.SCREEN_HEIGHT - 100))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"
        self.screen_title = screen_title
        self.tech_tree = tech_tree
        self.on_save = on_save

        # tech -> ("checkbox", bool) or ("entry", str, max_lvl)
        self.tech_state = {}
        for tech, val in base_data.items():
            max_lvl = tech_tree.get(tech, {}).get("max_lvl", 1)
            if max_lvl == 1:
                self.tech_state[tech] = ("checkbox", val >= 1)
            else:
                self.tech_state[tech] = ("entry", str(val), max_lvl)
        self.techs = sorted(self.tech_state.keys())

        self.refresh_ui()

    def toggle_checkbox(self, tech):
        self.tech_state[tech] = ("checkbox", not self.tech_state[tech][1])
        self.refresh_ui()

    def _sync_entries(self):
        """Pulls live text out of on-screen entry fields before they get rebuilt or saved."""
        for el in self.elements:
            tech = getattr(el, "tech_key", None)
            if tech is not None:
                _, _, max_lvl = self.tech_state[tech]
                self.tech_state[tech] = ("entry", el.text, max_lvl)

    def refresh_ui(self):
        self._sync_entries()
        p = self.panel_rect
        self.elements = [
            make_back_button(self.exit_screen, style="map"),
            Button(p.right - 170, p.bottom - 55, "medium", "green", "Save", self.save),
        ]

        row_top = p.y + 70
        view_h = p.height - 140
        cull_top, cull_bottom = p.y + 60, p.bottom - 70
        self.scroll_content_rect = pygame.Rect(p.x + 5, cull_top, p.width - 10, cull_bottom - cull_top)
        for i, y in self.layout_list_rows(len(self.techs), self.ROW_HEIGHT, row_top, view_h=view_h,
                                          cull_top=cull_top, cull_bottom=cull_bottom):
            tech = self.techs[i]
            kind = self.tech_state[tech]
            if kind[0] == "checkbox":
                checked = kind[1]
                btn = Button(p.right - 100, y, "tiny_square", "green" if checked else "grey",
                            "ON" if checked else "OFF", lambda t=tech: self.toggle_checkbox(t), font_preset="tiny")
                btn.is_scrollable = True
                btn.click_guard = self.scroll_click_guard
                self.elements.append(btn)
            else:
                _, text, _max_lvl = kind
                field = TextField(p.right - 160, y, 100, 30, text, numeric=True)
                field.tech_key = tech
                field.is_scrollable = True
                field.click_guard = self.scroll_click_guard
                self.elements.append(field)

        self.list_view_h = view_h

    def save(self):
        self._sync_entries()
        new_data = {}
        for tech, state in self.tech_state.items():
            if state[0] == "checkbox":
                new_data[tech] = 1 if state[1] else 0
            else:
                _, text, max_lvl = state
                try:
                    val = int(text)
                except ValueError:
                    val = 0
                new_data[tech] = max(0, min(val, max_lvl))
        self.on_save(new_data)
        self.done = True

    def draw_content(self, surface):
        p = self.panel_rect
        ui_bars.draw_modal_box(surface, p, bg_color=(30, 30, 45), border_color=(255, 152, 0), border_width=2)
        ui_bars.draw_centered_title(surface, self.screen_title, p.y + 15, "heading2")

        font = fonts.get("normal")
        small_font = fonts.get("small")
        row_top = p.y + 70
        view_h = p.height - 140
        clip_rect = self.scroll_content_rect or pygame.Rect(p.x + 5, p.y + 60, p.width - 10, p.height - 140)

        with ui_bars.clip_scroll_region(surface, clip_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
            for i, y in self.layout_list_rows(len(self.techs), self.ROW_HEIGHT, row_top, view_h=view_h,
                                              cull_top=p.y + 60, cull_bottom=p.bottom - 70):
                tech = self.techs[i]
                label = font.render(tech.replace("_", " ").title(), True, c.UI_TEXT_BRIGHT)
                surface.blit(label, (p.x + 20, y + 4))

                kind = self.tech_state[tech]
                if kind[0] == "entry":
                    hint = small_font.render(f"(0-{kind[2]})", True, c.UI_TEXT_MUTED)
                    surface.blit(hint, (p.right - 250, y + 8))

        self.draw_list_scrollbar(surface, p.right - 15, p.y + 60, view_h)

class Research_List_Screen(MapOverlayScreen):
    pans_camera = False
    scroll_anywhere = True

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 500, c.SCREEN_HEIGHT - 120))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"
        self.active_countries = sorted(queries.get_living_nations(map_screen.map_data))
        self.default_research = self._get_default_research()
        self.refresh_ui()

    def _get_default_research(self):
        map_screen = self.map_screen
        struct = queries.get_tech_tree()
        fresh_template = {tech: (1800 if data["max_lvl"] == 9999 else 0) for tech, data in struct.items()}
        if "infantry_type" in fresh_template: fresh_template["infantry_type"] = 1
        if "cavalry" in fresh_template: fresh_template["cavalry"] = 1

        if getattr(map_screen, "default_research", None) is not None:
            for k, v in fresh_template.items():
                if k not in map_screen.default_research:
                    map_screen.default_research[k] = v
            obsolete_keys = [k for k in map_screen.default_research.keys() if k not in fresh_template]
            for k in obsolete_keys:
                del map_screen.default_research[k]
            return map_screen.default_research

        return fresh_template

    def refresh_ui(self):
        p = self.panel_rect
        force_time_appropriate_on = queries.get_scenario_flag(
            "force_time_appropriate_research", c.DEFAULT_FORCE_TIME_APPROPRIATE_RESEARCH,
            self.map_screen.scenario_settings)

        ftap_btn = Button(p.centerx - 200, p.y + 115, "FTAP", "green", "Force Time-Appropriate Research",
                          self.toggle_force_time_appropriate)
        ftap_btn.is_selected = force_time_appropriate_on

        self.elements = [
            make_back_button(self.exit_screen, style="map"),
            Button(p.x + 20, p.y + 60, "medium", "red", "Edit ALL (Bulk)", self.edit_all),
            Button(p.right - 220, p.y + 60, "medium", "orange", "Edit Map Default", self.edit_default),
            ftap_btn,
        ]

        row_top = p.y + 170
        view_h = p.height - 190
        row_x = p.x + 20
        row_w = p.width - 40
        cull_top, cull_bottom = p.y + 160, p.bottom - 20
        self.scroll_content_rect = pygame.Rect(p.x, cull_top, p.width, cull_bottom - cull_top)
        for i, y in self.layout_list_rows(len(self.active_countries), 40, row_top, view_h=view_h,
                                          cull_top=cull_top, cull_bottom=cull_bottom):
            cid = self.active_countries[i]
            c_res = self.map_screen.nation_data.get(cid, {}).get("research", {})
            is_diff = any(c_res.get(k, v) != v for k, v in self.default_research.items())
            label = f"[MODIFIED] {cid}" if is_diff else cid
            btn = Button(row_x, y, "list_row", "blue", label, lambda cc=cid: self.edit_country(cc))
            btn.rect.width = row_w
            btn.is_scrollable = True
            btn.click_guard = self.scroll_click_guard
            self.elements.append(btn)

        self.list_view_h = view_h

    def _open_editor(self, title, base_data, on_save):
        for k, v in self.default_research.items():
            base_data.setdefault(k, v)
        screen = Research_Edit_Screen(self.map_screen, title, base_data, queries.get_tech_tree(), on_save)
        _run_pygame_sub_screen(self.map_screen, screen, on_done=self.refresh_ui)

    def edit_country(self, cid):
        base_data = dict(self.map_screen.nation_data.get(cid, {}).get("research", self.default_research))

        def save(new_data):
            nd = self.map_screen.nation_data[cid]
            nd.setdefault("research", {}).update(new_data)
            self.map_screen.show_feedback(f"Saved research for {cid}")

        self._open_editor(cid, base_data, save)

    def edit_all(self):
        base_data = self.default_research.copy()

        def save(new_data):
            self.map_screen.default_research = new_data.copy()
            self.default_research = new_data.copy()
            for cid in self.active_countries:
                self.map_screen.nation_data[cid].setdefault("research", {}).update(new_data)
            self.map_screen.show_feedback("Saved research for ALL & Set Default")

        self._open_editor("ALL COUNTRIES", base_data, save)

    def edit_default(self):
        base_data = self.default_research.copy()

        def save(new_data):
            self.map_screen.default_research = new_data.copy()
            self.default_research = new_data.copy()
            self.map_screen.show_feedback("Updated Map Default Tech")

        self._open_editor("MAP DEFAULT", base_data, save)

    def toggle_force_time_appropriate(self):
        settings = self.map_screen.scenario_settings
        default = c.DEFAULT_FORCE_TIME_APPROPRIATE_RESEARCH
        currently_on = queries.get_scenario_flag("force_time_appropriate_research", default, settings)

        if currently_on:
            # Turning off just stops future auto-recompute -- it doesn't touch
            # whatever research values are currently set.
            queries.toggle_scenario_flag(settings, "force_time_appropriate_research", default)
            self.map_screen.show_feedback("Force Time-Appropriate Research: OFF")
            self.refresh_ui()
            return

        current_year = getattr(self.map_screen.time_manager, "year", c.START_YEAR)
        msg = (
            f"This will turn ON Force Time-Appropriate Research, resetting the research of ALL nations "
            f"on the map to match the time-appropriate research levels for year {current_year} "
            f"(the scenario's start year), exactly as if a random scenario was created in {current_year}.\n\n"
            f"While this stays on, changing the scenario's start date will automatically re-align research "
            f"to stay time-appropriate for the new date.\n\n"
            f"Are you sure you want to turn this on?"
        )

        def on_confirm(ok):
            if not ok:
                return
            queries.toggle_scenario_flag(settings, "force_time_appropriate_research", default)
            queries.apply_time_appropriate_research_to_map(self.map_screen, current_year)
            self.default_research = self.map_screen.default_research.copy()
            self.map_screen.show_feedback(f"Force Time-Appropriate Research: ON ({current_year})")
            self.refresh_ui()

        confirm_dialog.ask_yes_no("Force Time-Appropriate Research", msg, on_confirm)

    def draw_content(self, surface):
        p = self.panel_rect
        ui_bars.draw_modal_box(surface, p, bg_color=(30, 30, 45), border_color=(255, 152, 0), border_width=2)
        ui_bars.draw_centered_title(surface, "Map Research Editor", p.y + 20, "heading2")
        self.draw_list_scrollbar(surface, p.right - 15, p.y + 170, self.list_view_h)
