"""Show the current viewer's events from the last completed turn."""
import data.constants as c
from map_logic.turn_processing import unit_events
from map_logic.rendering.font_manager import fonts
from ui import text_utils
from ui.table_screen import TableColumn, TableScreen
from ui_elements import Button

BACKGROUND_COLOR = (80, 60, 40)
ROW_COLOR = (48, 35, 25)
TABLE_MARGIN = 25
CELL_PADDING = 12
UNREAD_BUTTON_SIZE = (120, 30)
UNREAD_BUTTON_MARGIN = 20
COLUMN_SHARES = (("unit_name", "Unit", .20), ("tile_id", "Tile", .08),
                 ("event_label", "Event", .17), ("amount", "Health", .09),
                 ("details", "Details (click row)", .46))


class UnitEventsScreen(TableScreen):
    def __init__(self, map_screen):
        rows = [row | {"event_label": unit_events.EVENT_LABELS[row["event"]]}
                for row in unit_events.entries_for(map_screen)]
        available = c.SCREEN_WIDTH - 2 * TABLE_MARGIN
        widths = [int(available * share) for _key, _label, share in COLUMN_SHARES]
        widths[-1] = available - sum(widths[:-1])
        columns = []
        for (key, label, _share), width in zip(COLUMN_SHARES, widths):
            def fit(value, key=key, width=width):
                text = f"{value:.2f}" if key == "amount" and value else "" if key == "amount" else str(value)
                return text_utils.fit_text(text, fonts.get("small"), width - CELL_PADDING)
            columns.append(TableColumn(key, label, width, align="left", fmt=fit))
        super().__init__(map_screen, "Unit events - Last turn", columns, rows,
                         empty_message="No unit events from the last turn.",
                         on_row_click=self.show_event, row_tint=lambda _row: ROW_COLOR)
        self.bg_color = BACKGROUND_COLOR
        unit_events.mark_read(map_screen)
        map_screen.btn_unit_events.notification_count = map_screen._unit_event_unread

    def refresh_ui(self):
        super().refresh_ui()
        self.btn_mark_all_unread = Button(
            c.SCREEN_WIDTH - UNREAD_BUTTON_MARGIN - UNREAD_BUTTON_SIZE[0],
            UNREAD_BUTTON_MARGIN, UNREAD_BUTTON_SIZE, "yellow", "Mark all unread",
            self.mark_all_unread, font_preset="button_small")
        self.btn_mark_all_unread.apply_state(enabled=bool(self.rows))
        self.elements.append(self.btn_mark_all_unread)

    def mark_all_unread(self):
        unit_events.mark_unread(self.map_screen)
        self.map_screen.btn_unit_events.notification_count = self.map_screen._unit_event_unread

    def draw_background(self, surface):
        self.draw_checkerboard_background(surface, self.bg_color)

    def show_event(self, row):
        from ui import confirm_dialog
        amount = f"\nHealth: {row['amount']:.2f}" if row["amount"] else ""
        confirm_dialog.show_info(row["event_label"],
            f"{row['unit_name']}\nTile: {row['tile_id']}{amount}\n{row['details']}")
