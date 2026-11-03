import os

import data.constants as c
from ui import dialogs
from ui.dialogs import file_exchange
from screens.game import map_launch
from ui.widgets.content_browser import ContentBrowserScreen
from ui.widgets.ui_elements import Button, make_back_button, play_ui_sound
from screens.setup import map_refresh
from ui.navigation.screen import ButtonMenuScreen, MenuListScreen, Screen


class Select_Base_Map(ContentBrowserScreen):
    back_state = "MENU"
    title = "MAP EDITOR"
    content_label = "maps"
    ACTION_COUNT = 3

    # Resolve directory settings when the screen refreshes.
    CATEGORIES = {
        "CUSTOM_MAPS": ("Custom Maps", "SCENARIOS_CUSTOM_DIR"),
        "BASE_MAPS": ("Base Maps", "BASE_MAPS_DIR"),
        "OTHER_HISTORICAL": ("Historical Scenarios", "SCENARIOS_HISTORICAL_DIR"),
        "OTHER_ALTERNATE": ("Alternate Scenarios", "SCENARIOS_ALTERNATE_DIR"),
    }

    def __init__(self):
        super().__init__()
        self.bg_color = (40, 20, 60)
        self.selected_save_path = None
        self.sub_state = "CUSTOM_MAPS"
        self.choosing_sources = False
        self.refresh_ui()

    def on_enter(self, app, previous):
        # Refresh on entry. Frame updates use cached entries.
        self.selected_entry = None
        self.choosing_sources = False
        self.sub_state = "CUSTOM_MAPS"
        self.reload_entries()

    def get_title(self):
        if self.sub_state == "SOURCES":
            return "NEW MAP"
        return self.CATEGORIES[self.sub_state][0].upper() if self.choosing_sources else self.title

    def has_menu_list(self):
        return self.sub_state != "SOURCES"

    def prepare_map(self, app):
        map_launch.open_saved_map(app, self.selected_save_path, force_editor=True)
        return True

    @property
    def managed_dir(self):
        return c.SCENARIOS_CUSTOM_DIR

    def refresh_ui(self):
        if self.sub_state == "SOURCES":
            self.elements = [make_back_button(self.return_to_maps),
                             *ButtonMenuScreen.build_menu_buttons([
                                 (label, color, lambda category=state: self.set_sub_state(category))
                                 for (state, (label, _attr)), color in zip(
                                     self.CATEGORIES.items(), ("green", "orange", "blue", "purple"))
                                 if state != "CUSTOM_MAPS"
                             ])]
            return
        _label, directory_attr = self.CATEGORIES[self.sub_state]
        directory = getattr(c, directory_attr)
        if self.choosing_sources:
            self.elements = [make_back_button(self.return_to_sources)]
            if self.sub_state == "BASE_MAPS":
                self.elements.append(Button(c.SCREEN_WIDTH - 252, self.CATEGORY_Y, (228, 38), "purple", "Data Refresh",
                                            self.trigger_base_map_data_refresh, font_preset="button_small"))
            os.makedirs(directory, exist_ok=True)
            with os.scandir(directory) as files:
                names = [entry.name for entry in files if not entry.name.startswith(".") and entry.is_dir()]
            self.add_menu_list([(name, name) for name in names],
                               lambda name: self.start_editor_with_map(name, directory))
            return
        self.build_browser(directory, "No maps in this category. Import a custom map or choose another category.")
        self.elements.extend([
            make_back_button(self.exit_screen),
            Button(c.SCREEN_WIDTH - 324, 24, (160, 40), "green", "Import .zip", self.import_custom_map,
                   font_preset="button_small"),
            Button(c.SCREEN_WIDTH - 152, 24, (128, 40), "grey", "Refresh", self.reload_entries,
                   font_preset="button_small"),
        ])
        if self.selected_entry:
            self.add_browser_action("Rename", lambda: self.manage_selected(self.start_rename), 0, "blue")
            self.add_browser_action("Export", lambda: self.manage_selected(self.export_scenario_zip), 1, "green")
            self.add_browser_action("Delete…", lambda: self.manage_selected(self.start_delete), 2, "red")
            self.open_button = self.add_primary_action("Edit Map")
        else:
            self.open_button = self.add_primary_action("New Map", self.return_to_sources)

    def return_to_sources(self):
        self.choosing_sources = True
        self.set_sub_state("SOURCES")

    def return_to_maps(self):
        self.choosing_sources = False
        self.set_sub_state("CUSTOM_MAPS")

    def additional_draw(self, surface):
        if self.choosing_sources and self.sub_state != "SOURCES":
            MenuListScreen.additional_draw(self, surface)
        elif not self.choosing_sources:
            super().additional_draw(surface)

    def draw_elements(self, surface):
        if self.choosing_sources:
            Screen.draw_elements(self, surface)
        else:
            super().draw_elements(surface)

    def additional_events(self, event):
        if self.choosing_sources and self.sub_state != "SOURCES":
            MenuListScreen.additional_events(self, event)
        elif not self.choosing_sources:
            super().additional_events(event)

    def import_custom_map(self):
        self.choosing_sources = False
        self.set_sub_state("CUSTOM_MAPS")
        file_exchange.import_zip_to_dir(self, self.managed_dir, self.reload_entries)

    def manage_selected(self, handler):
        if self.sub_state == "CUSTOM_MAPS":
            self.call_selected(handler)

    def activate_selected(self):
        if self.selection_can_open:
            entry = self.selected_entry
            play_ui_sound("click")
            self.start_editor_with_map(entry.name, os.path.dirname(entry.path))

    def trigger_base_map_data_refresh(self):
        """Refresh base map data after confirmation."""
        if self.sub_state != "BASE_MAPS":
            return

        def on_confirm(confirm):
            if confirm:
                map_refresh.refresh_map_directories(self, [c.BASE_MAPS_DIR],
                                                   success_message="Synced base maps successfully.")

        dialogs.ask_yes_no(
            "Confirm Data Refresh",
            "Are you sure you want to refresh base map data?\nThis process may take a while.",
            on_confirm
        )

    def export_scenario_zip(self, scenario_name):
        file_exchange.export_dir_as_zip(os.path.join(self.managed_dir, scenario_name),
                                        f"{scenario_name}_scenario.zip")

    def start_editor_with_map(self, map_name, directory):
        self.selected_save_path = os.path.join(directory, map_name)
        self.choosing_sources = False
        self.set_sub_state("CUSTOM_MAPS")
        self.go_to("MAP")

    def exit_screen(self):
        self.choosing_sources = False
        self.set_sub_state("CUSTOM_MAPS")
        super().exit_screen()

    def handle_back_key(self):
        if self.search_field.active:
            self.finish_search()
        elif self.sub_state == "SOURCES":
            play_ui_sound("back")
            self.return_to_maps()
        elif self.choosing_sources:
            play_ui_sound("back")
            self.return_to_sources()
        else:
            self.go_back()
