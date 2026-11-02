import os

import data.constants as c
from ui import dialogs
from ui.dialogs import file_exchange
from ui.widgets.content_browser import ContentBrowserScreen
from ui.widgets.ui_elements import Button, make_back_button, play_ui_sound
from screens.setup import map_refresh


class Select_Base_Map(ContentBrowserScreen):
    back_state = "MENU"
    title = "MAP EDITOR"
    content_label = "maps"

    # Resolve directory settings when the screen refreshes.
    CATEGORIES = {
        "CUSTOM_MAPS": ("Custom Maps", "SCENARIOS_CUSTOM_DIR"),
        "BASE_MAPS": ("Base Maps", "BASE_MAPS_DIR"),
        "OTHER_HISTORICAL": ("Historical Scenarios", "SCENARIOS_HISTORICAL_DIR"),
        "OTHER_ALTERNATE": ("Alternate Scenarios", "SCENARIOS_ALTERNATE_DIR"),
    }
    CATEGORY_WIDTH = 232

    def __init__(self):
        super().__init__()
        self.bg_color = (40, 20, 60)
        self.selected_save_path = None
        self.sub_state = "CUSTOM_MAPS"
        self.refresh_ui()

    @property
    def managed_dir(self):
        return c.SCENARIOS_CUSTOM_DIR

    def refresh_ui(self):
        _label, directory_attr = self.CATEGORIES[self.sub_state]
        directory = getattr(c, directory_attr)
        is_custom = self.sub_state == "CUSTOM_MAPS"
        note = ("" if is_custom else
                "Open this source as a new custom map. Saving creates a copy and keeps the source unchanged.")
        self.build_browser(directory, "No maps in this category. Import a custom map or choose another category.", note)
        self.elements.extend([
            make_back_button(self.exit_screen),
            Button(c.SCREEN_WIDTH - 324, 24, (160, 40), "green", "Import .zip", self.import_custom_map,
                   font_preset="button_small"),
            Button(c.SCREEN_WIDTH - 152, 24, (128, 40), "grey", "Refresh", self.reload_entries,
                   font_preset="button_small"),
        ])
        for index, (state, (label, _attr)) in enumerate(self.CATEGORIES.items()):
            button = Button(self.MARGIN + index * (self.CATEGORY_WIDTH + self.ACTION_GAP), self.CATEGORY_Y,
                            (self.CATEGORY_WIDTH, 38), "grey", label,
                            lambda category=state: self.set_sub_state(category), font_preset="button_small")
            button.is_selected = state == self.sub_state
            self.elements.append(button)
        self.add_browser_action("Rename", lambda: self.manage_selected(self.start_rename), 0, enabled=is_custom)
        self.add_browser_action("Export", lambda: self.manage_selected(self.export_scenario_zip), 1, "green", enabled=is_custom)
        self.add_browser_action("Delete…", lambda: self.manage_selected(self.start_delete), 2, "red", enabled=is_custom)
        refresh_button = Button(c.SCREEN_WIDTH - 252, self.CATEGORY_Y, (228, 38), "purple", "Data Refresh",
                                self.trigger_base_map_data_refresh, font_preset="button_small")
        refresh_button.apply_state(enabled=self.sub_state == "BASE_MAPS", color="purple")
        self.elements.append(refresh_button)
        label = "Edit Map" if is_custom else "Create from Base" if self.sub_state == "BASE_MAPS" else "Edit Copy"
        self.open_button = Button(c.SCREEN_WIDTH - 244, c.SCREEN_HEIGHT - 64, (220, 44), "green", label,
                                  self.activate_selected, sound_kind=None)
        self.open_button.apply_state(enabled=self.selection_can_open, color="green")
        self.elements.append(self.open_button)

    def import_custom_map(self):
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
        self.set_sub_state("CUSTOM_MAPS")
        self.go_to("MAP")

    def exit_screen(self):
        self.set_sub_state("CUSTOM_MAPS")
        super().exit_screen()

    def handle_back_key(self):
        if self.search_field.active:
            self.finish_search()
        elif self.sub_state != "CUSTOM_MAPS":
            play_ui_sound("back")
            self.set_sub_state("CUSTOM_MAPS")
        else:
            self.go_back()
