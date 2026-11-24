import pygame
from ui.navigation.screen import Screen
import data.constants as c
from ui.bars import ui_bars
from ui.widgets.ui_elements import Button, Slider, make_back_button
from ui.rendering.font_manager import fonts
from data import queries
from ui.widgets.table_screen import TableScreen, TableColumn
from ui.background_styles import ECONOMY_PANEL_STYLES
from ui.widgets import ui_elements

from ui.navigation import screen_runner


# ==========================================
# LAYOUT
# ==========================================

TITLE_Y = 40
EXPENSES_BTN_OFFSET_X = 120 # Measured in from the right edge

# Resource rows
ROW_START_Y = 120
ROW_STEP_Y = 120
ROW_WIDTH = 1200
ROW_HEIGHT = 100

# Sliders below the rows
SLIDER_WIDTH = 400
CONSCRIPTION_SLIDER_Y = 530
CONVERSION_SLIDER_Y = CONSCRIPTION_SLIDER_Y + 70
RESEARCH_FUNDING_SLIDER_Y = CONVERSION_SLIDER_Y + 70
SLIDER_CAPTION_OFFSET_Y = 25
SLIDER_SIDE_CAPTION_GAP = 20

CONSCRIPTION_DAMAGE_COLOR_STOPS = (
    (0.0, c.UI_ACCENT_BLUE),
    (0.05, c.COLOR_SUCCESS_GREEN),
    (0.10, c.COLOR_GOLD_HIGHLIGHT),
    (0.20, (255, 80, 80)),
)

# Expenses table controls and columns
EXPENSES_TOGGLE_Y = 65
EXPENSES_TOGGLE_WIDTH = 130
EXPENSES_TOGGLE_HEIGHT = 28
EXPENSES_TOGGLE_GAP = 10
EXPENSES_UNIT_WIDTH = 220
EXPENSES_DETAIL_WIDTH = 180
EXPENSES_RESOURCE_WIDTH = 120


def conscription_damage_color(bonus):
    """Interpolate exponentially between the damage bonus color stops."""
    if bonus <= CONSCRIPTION_DAMAGE_COLOR_STOPS[0][0]:
        return CONSCRIPTION_DAMAGE_COLOR_STOPS[0][1]
    for (low, low_color), (high, high_color) in zip(
            CONSCRIPTION_DAMAGE_COLOR_STOPS, CONSCRIPTION_DAMAGE_COLOR_STOPS[1:]):
        if bonus <= high:
            fraction = (bonus - low) / (high - low)
            blend = 2.0 ** fraction - 1.0
            return tuple(round(start + (end - start) * blend)
                         for start, end in zip(low_color, high_color))
    return CONSCRIPTION_DAMAGE_COLOR_STOPS[-1][1]


def format_amount(value, *, signed=False):
    """Round every economy screen figure to the nearest whole number."""
    return f"{round(value):+d}" if signed else str(round(value))


def income_detail_text(breakdown):
    """List one resource's income entries in the shared breakdown order."""
    parts = []
    for key, gain_label, cost_label, always_shown in queries.INCOME_BREAKDOWN_ENTRIES:
        value = breakdown[key]
        if always_shown or value != 0:
            parts.append(f"{gain_label if value >= 0 else cost_label}: {format_amount(value, signed=True)}")
    return "Details -> " + "  |  ".join(parts)


def expense_table_columns(grouped):
    detail = (TableColumn("count", "Count", EXPENSES_DETAIL_WIDTH) if grouped else
              TableColumn("location", "Location (Prov ID)", EXPENSES_DETAIL_WIDTH))
    return [
        TableColumn("unit", "Unit", EXPENSES_UNIT_WIDTH, align="left"),
        detail,
        *(TableColumn(resource, resource.title(), EXPENSES_RESOURCE_WIDTH,
                      align="right", fmt=lambda value: f"{value:.2f}")
          for resource in c.ECON_RESOURCE_KEYS),
    ]


def expense_table_rows(units, unit_library, nation_data=None):
    """Build individual and grouped presentation rows from the same unit upkeep."""
    individual = []
    grouped = {}
    for unit, prov in units:
        upkeep = queries.get_live_unit_upkeep(unit, unit_library, nation_data)
        unit_name = unit.get("type")
        label = queries.get_unit_display_name(unit_name, unit_library)
        individual.append({"unit": label, "location": prov["id"], **upkeep})

        if unit_name not in grouped:
            grouped[unit_name] = {"unit": label, "count": 0,
                                  **{resource: 0 for resource in c.ECON_RESOURCE_KEYS}}
        group = grouped[unit_name]
        group["count"] += 1
        for resource in c.ECON_RESOURCE_KEYS:
            group[resource] += upkeep[resource]
    return individual, list(grouped.values())


class ExpensesTableScreen(TableScreen):
    HEADER_Y = 108
    ROW_TOP = 150

    def __init__(self, game_state, individual_rows, grouped_rows):
        self.individual_rows = individual_rows
        self.grouped_rows = grouped_rows
        self.grouped = False
        super().__init__(game_state, "Military Upkeep Expenses",
                         expense_table_columns(False), individual_rows,
                         empty_message="No units to show expenses for.")

    def set_grouped(self, grouped):
        if self.grouped == grouped:
            return
        self.grouped = grouped
        self.columns = expense_table_columns(grouped)
        self.rows = self.grouped_rows if grouped else self.individual_rows
        self.scroll_y = 0
        self.max_scroll = 0
        self.sort_reverse.clear()
        self.refresh_ui()

    def refresh_ui(self):
        super().refresh_ui()
        left = c.SCREEN_WIDTH // 2 - EXPENSES_TOGGLE_WIDTH - EXPENSES_TOGGLE_GAP // 2
        for grouped, label in ((False, "Individual"), (True, "Grouped")):
            x = left + (EXPENSES_TOGGLE_WIDTH + EXPENSES_TOGGLE_GAP) * int(grouped)
            color = "orange" if self.grouped == grouped else "blue"
            self.elements.append(Button(x, EXPENSES_TOGGLE_Y,
                                        (EXPENSES_TOGGLE_WIDTH, EXPENSES_TOGGLE_HEIGHT),
                                        color, label, lambda value=grouped: self.set_grouped(value),
                                        font_preset="button_small"))

class Economy_Screen(Screen):
    back_state = "MAP"

    def __init__(self):
        super().__init__()
        self.bg_color = (30, 35, 40)
        self.map_screen = None

    def on_enter(self, app, previous):
        self.start_economy(app.states["MAP"])

    def start_economy(self, map_ref):
        self.map_screen = map_ref
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]
        
        # Expenses button positioned in the top right corner
        btn_expenses = Button(c.SCREEN_WIDTH - EXPENSES_BTN_OFFSET_X, c.BACK_BTN_TOPLEFT[1], "small", "orange", "Expenses", self.open_expenses_table, sound_kind=None)
        self.elements.append(btn_expenses)
        
        # Sliders below the resource rows
        p_data = self.map_screen.world.nation_data[self.map_screen.session.player_country]
        max_conversion = queries.get_max_fuel_conversion(p_data)
        slider_x = c.SCREEN_WIDTH // 2 - SLIDER_WIDTH // 2
        conscription = Slider(slider_x, CONSCRIPTION_SLIDER_Y, SLIDER_WIDTH, "Conscription (Keep Manpower %)", queries.get_conscription_rate(p_data), self.set_conscription, click_track=True)
        self.conscription_slider = conscription
        conversion = Slider(slider_x, CONVERSION_SLIDER_Y, SLIDER_WIDTH, "Convert % Mats to Fuel", queries.get_fuel_conversion_rate(p_data, max_conversion=max_conversion), self.set_conversion, visual_max=c.MAX_CONVERSION_SLIDER_VAL, allowed_max=max_conversion, click_track=True)
        funding = Slider(slider_x, RESEARCH_FUNDING_SLIDER_Y, SLIDER_WIDTH, "Research Funding", queries.get_research_funding_rate(p_data), self.set_research_funding, click_track=True)
        for slider in (conscription, conversion, funding):
            slider.disabled = self.map_screen.session.tactical_mode
            slider.click_guard = self.can_edit_realtime
        self.elements.extend((conscription, conversion, funding))
        self.refresh_economy_preview()

    def refresh_economy_preview(self):
        """Cache income and slider captions when economy inputs change."""
        country = self.map_screen.world.nation_data[self.map_screen.session.player_country]
        self.econ_cache = queries.get_economy_projections(
            self.map_screen.session.player_country, self.map_screen.world.map_data, self.map_screen.world.nation_data, context=self.map_screen)
        spent = queries.get_research_funding_spent(self.econ_cache[2])
        days = queries.get_days_per_turn(self.map_screen.world.scenario_settings)
        bonus = queries.get_funded_research_points(country, spent, days)
        if not spent and queries.get_research_funding_rate(country):
            caption = "No Materials income"
        else:
            caption = f"Materials budget {format_amount(spent)}   |   Bonus research +{bonus:,.2f} pts/turn"
        self.research_funding_caption = fonts.get("normal").render(caption, True, c.COLOR_GOLD_HIGHLIGHT)
        bonus = queries.get_conscription_damage_bonus(country)
        self.conscription_damage_caption = f"dmg modifier: +{bonus:.2%}"
        self.conscription_damage_color = conscription_damage_color(bonus)

    def set_conscription(self, val):
        self.set_slider_rate("conscription_slider", val)

    def set_conversion(self, val):
        if not self.map_screen: return
        country = self.map_screen.world.nation_data[self.map_screen.session.player_country]
        self.set_slider_rate("mat_to_fuel_slider", val, queries.get_max_fuel_conversion(country))

    def set_research_funding(self, val):
        self.set_slider_rate("research_funding_slider", val)

    def set_slider_rate(self, key, val, maximum=1.0):
        """Store one economy slider through the shared validation and refresh path."""
        if not self.map_screen or self.map_screen.session.tactical_mode: return
        if not self.can_edit_realtime() or not queries.valid_slider_rate(val): return
        # The slider computes its value in floating point and can land just past a research limit.
        self.map_screen.world.nation_data[self.map_screen.session.player_country][key] = min(val, maximum)
        self.refresh_economy_preview()
        self.map_screen.invalidate_map_presentation_cache()

    def can_edit_realtime(self):
        return queries.require_realtime_turn_open(self.map_screen, "the economy")

    def additional_draw(self, surface):
        if not self.map_screen: return
        
        ui_bars.draw_centered_title(surface, "National Economy", TITLE_Y)

        total_inc, upkeep, breakdown = self.econ_cache

        font_large = fonts.get("heading1")
        font_med = fonts.get("heading2")
        font_small = fonts.get("normal")
        
        y_offset = ROW_START_Y
        resources = [
            ("manpower", "Manpower", self.map_screen.player_manpower, c.COLOR_RESOURCE_MANPOWER),
            ("materials", "Materials", self.map_screen.player_materials, c.COLOR_RESOURCE_MATERIALS),
            ("fuel", "Fuel", self.map_screen.player_fuel, c.COLOR_RESOURCE_FUEL)
        ]
        
        for res_key, name, current, color in resources:
            inc = total_inc[res_key]
            exp = upkeep[res_key]
            
            # Row Background (Made taller to fit details)
            row_rect = pygame.Rect(c.SCREEN_WIDTH // 2 - ROW_WIDTH // 2, y_offset, ROW_WIDTH, ROW_HEIGHT)
            style = ECONOMY_PANEL_STYLES["resource"]
            ui_elements.draw_pixel_panel(surface, row_rect, style["color"], (100, 100, 100),
                                         border_width=1, gradient_strength=style["gradient_strength"])
            
            # Current Resource Amount
            surface.blit(font_large.render(f"{name}: {format_amount(current)}", True, color), (row_rect.x + 20, row_rect.y + 15))

            main_breakdown = (f"Total Income: {format_amount(inc, signed=True)}   |   Upkeep: -{format_amount(exp)}   |   "
                              f"Net: {format_amount(inc - exp, signed=True)}")
            detail_breakdown = income_detail_text(breakdown[res_key])

            # Stats Breakdown (Main)
            surface.blit(font_med.render(main_breakdown, True, c.UI_TEXT_LIGHT), (row_rect.x + 350, row_rect.y + 18))
            
            # Detailed Breakdown
            surface.blit(font_small.render(detail_breakdown, True, c.UI_TEXT_MUTED), (row_rect.x + 0, row_rect.y + 60))
            
            y_offset += ROW_STEP_Y

        damage_txt = font_small.render(self.conscription_damage_caption, True, self.conscription_damage_color)
        surface.blit(damage_txt, damage_txt.get_rect(midleft=(
            self.conscription_slider.rect.right + SLIDER_SIDE_CAPTION_GAP,
            self.conscription_slider.rect.centery)))

        # Draw dynamic conversion info below sliders.
        man_lost = -breakdown["manpower"]["conscription"]
        mat_gained = breakdown["materials"]["conscription"]
        if man_lost > 0:
            cons_txt = font_small.render(f"Converting {format_amount(man_lost)} Manpower -> {format_amount(mat_gained)} Materials", True, c.COLOR_GOLD_HIGHLIGHT)
            surface.blit(cons_txt, (c.SCREEN_WIDTH // 2 - cons_txt.get_width() // 2,
                                   CONSCRIPTION_SLIDER_Y + SLIDER_CAPTION_OFFSET_Y))

        mat_lost = -breakdown["materials"]["conversion"]
        fuel_gained = breakdown["fuel"]["conversion"]
        if mat_lost > 0:
            conv_txt = font_small.render(f"Converting {format_amount(mat_lost)} Materials -> {format_amount(fuel_gained)} Fuel", True, c.COLOR_GOLD_HIGHLIGHT)
            surface.blit(conv_txt, (c.SCREEN_WIDTH // 2 - conv_txt.get_width() // 2, CONVERSION_SLIDER_Y + SLIDER_CAPTION_OFFSET_Y))
        caption = self.research_funding_caption
        surface.blit(caption, (c.SCREEN_WIDTH // 2 - caption.get_width() // 2, RESEARCH_FUNDING_SLIDER_Y + SLIDER_CAPTION_OFFSET_Y))

    def open_expenses_table(self):
        if not self.map_screen: return

        # Retrieve all currently owned units and the base unit stat library
        _, units = queries.get_nation_provinces_and_units(self.map_screen.session.player_country, self.map_screen.world.map_data)
        unit_lib = queries.get_unit_library(self.map_screen)

        individual_rows, grouped_rows = expense_table_rows(units, unit_lib, self.map_screen.world.nation_data)

        screen_runner._run_pygame_sub_screen(self.map_screen,
                               ExpensesTableScreen(self, individual_rows, grouped_rows))
