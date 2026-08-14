import pygame
import data.constants as c
from data import queries
from map_logic.diplomacy import diplomacy_messages
from gameState import MapOverlayScreen
from map_logic.rendering.font_manager import fonts
from ui_elements import Button
from ui.screen_runner import _run_pygame_sub_screen
from screens.map_related_screens.diplomacy_screen_widgets import build_choice_button


class Declare_War_Screen(MapOverlayScreen):
    pans_camera = False
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_DANGER

    def __init__(self, map_screen, target_nation):
        # Widen the panel to fit buttons side-by-side
        super().__init__(map_screen, pygame.Rect(c.SCREEN_WIDTH//2 - 250, c.SCREEN_HEIGHT//2 - 160, 500, 320))
        self.target_nation = target_nation

        has_wg = queries.has_wargoal(map_screen.player_country, target_nation, map_screen.nation_data, map_screen.map_data)

        cb_required = queries.get_scenario_flag("casus_belli_required", c.CASUS_BELLI_REQUIRED, map_screen.scenario_settings)

        # Spectator / Override catch: if it's the spectator, let them force it anyway
        if map_screen.player_country == "Spectator":
            has_wg = True
            cb_required = False

        my_master = map_screen.nation_data.get(map_screen.player_country, {}).get("master", "")
        their_master = map_screen.nation_data.get(target_nation, {}).get("master", "")

        is_independence = (my_master == target_nation)
        is_preemptive = (their_master == map_screen.player_country)

        if is_independence:
            puppet_cb_label = c.WARGOAL_INDEPENDENCE
            puppet_cb_enabled = True
        elif is_preemptive:
            puppet_cb_label = c.WARGOAL_PREEMPTIVE
            puppet_cb_enabled = True
        else:
            puppet_cb_label = c.WARGOAL_INDEPENDENCE
            puppet_cb_enabled = False

        self.wargoal_options = [
            {"label": c.WARGOAL_TAKE_CLAIMS, "enabled": has_wg},
            {"label": puppet_cb_label, "enabled": puppet_cb_enabled},
            {"label": c.WARGOAL_NO_CB, "enabled": not cb_required},
            {"label": "Don't Declare War", "enabled": True}
        ]

        self.selected_wargoal_idx = 3 # Default to Don't Declare War
        self.justifying = []

        # Check if a war declaration is already queued
        pending = diplomacy_messages.get_pending(map_screen.nation_data, map_screen.player_country, target_nation)
        self.is_editing = pending.get("action") == "WAR_DECLARATION"

        if self.is_editing:
            pending_msg = pending.get("message", "")
            for i, opt in enumerate(self.wargoal_options):
                if opt["label"] == pending_msg and opt["enabled"]:
                    self.selected_wargoal_idx = i
                    break
        else:
            # Auto-select the first enabled wargoal that actually declares war if available
            for i, opt in enumerate(self.wargoal_options):
                if opt["enabled"] and i != 3:
                    self.selected_wargoal_idx = i
                    break

        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Cancel", self.exit_screen)]

        confirm_text = "Update Declaration" if self.is_editing else "Confirm"
        btn_confirm = Button(self.panel_rect.centerx - 150, self.panel_rect.bottom - 70, "new_game", "red", confirm_text, self.confirm)
        self.elements.append(btn_confirm)

        # Two columns of two: options 0/1 on the upper row, 2/3 on the lower one
        for i, opt in enumerate(self.wargoal_options):
            btn_x = self.panel_rect.centerx + (-210 if i % 2 == 0 else 10)
            btn_y = self.panel_rect.y + (80 if i < 2 else 150)
            self.elements.append(
                build_choice_button(btn_x, btn_y, "medium", opt["label"], opt["enabled"],
                                    self.selected_wargoal_idx == i, lambda idx=i: self.select_wg(idx))
            )

        # Making a claim used to be a whole tab of its own, reached from the
        # left bar and unconnected to anything -- you claimed land in one place
        # and declared war in another, and nothing on either screen said the two
        # were related. Fabricating a case is a step of declaring war now, which
        # is the only thing claims were ever for.
        if not self.is_editing:
            self.elements.append(
                Button(self.panel_rect.centerx - 75, self.panel_rect.bottom - 110,
                       "thin", "blue", "Justify a Claim...", self.open_justification,
                       font_preset="normal"))

    def open_justification(self):
        from screens.map_related_screens.claims_screen import open_claim_picker

        open_claim_picker(self.map_screen, self.target_nation)
        self._reread_wargoals()
        self.refresh_ui()

    def _reread_wargoals(self):
        """A claim fabricated just now may have unlocked Take Claims -- a core
        matures the same turn, ordinary land takes CLAIM_TURN_NON_CORE."""
        has_wg = queries.has_wargoal(self.map_screen.player_country, self.target_nation,
                                     self.map_screen.nation_data, self.map_screen.map_data)
        if self.map_screen.player_country == "Spectator":
            has_wg = True
        self.wargoal_options[0]["enabled"] = has_wg

        queued = self.map_screen.nation_data.get(self.map_screen.player_country, {}).get("claim_queue", [])
        self.justifying = [q for q in queued
                           if (self.map_screen.id_to_province.get(q.get("prov_id"), {}) or {})
                           .get("owner") == self.target_nation]

    def select_wg(self, idx):
        if self.wargoal_options[idx]["enabled"]:
            self.selected_wargoal_idx = idx
            self.refresh_ui()

    def confirm(self):
        wg = self.wargoal_options[self.selected_wargoal_idx]["label"]

        if wg == "Don't Declare War":
            diplomacy_messages.clear_pending(self.map_screen.nation_data, self.map_screen.player_country,
                                             self.target_nation, only_actions=["WAR_DECLARATION"])

            p_data = self.map_screen.nation_data[self.map_screen.player_country]
            draft_lists = p_data.get("draft_lists", {})
            if self.target_nation in draft_lists:
                wg_labels = [opt["label"] for opt in self.wargoal_options]
                draft_lists[self.target_nation] = [d for d in draft_lists[self.target_nation] if d not in wg_labels]
                if not draft_lists[self.target_nation]:
                    del draft_lists[self.target_nation]

            self.map_screen.show_feedback("War Declaration Cancelled.")
            self.done = True
        else:
            # Overwrites any existing declaration without triggering the toggle/delete logic
            diplomacy_messages.set_pending(self.map_screen.nation_data, self.map_screen.player_country,
                                           self.target_nation, "WAR_DECLARATION", message=wg)
            self.map_screen.show_feedback("War Declaration Queued!" if not self.is_editing else "War Declaration Updated!")
            self.done = True

    def get_panel_title(self):
        return f"Declare War: {self.target_nation}"

    def draw_content(self, surface):
        self.draw_panel(surface)

        if not self.justifying:
            return

        # A claim takes turns to mature, so say so here rather than leaving the
        # player wondering why Take Claims is still greyed out.
        soonest = min(q.get("turns_left", 0) for q in self.justifying)
        line = (f"Justifying {len(self.justifying)} "
                f"{'claim' if len(self.justifying) == 1 else 'claims'} "
                f"-- {soonest} turn{'s' if soonest != 1 else ''} until the first is ready.")
        text = fonts.get("small").render(line, True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(text, (self.panel_rect.centerx - text.get_width() // 2,
                            self.panel_rect.bottom - 148))


def open_wargoal_selection_menu(map_screen, target_nation):
    _run_pygame_sub_screen(map_screen, Declare_War_Screen(map_screen, target_nation))
