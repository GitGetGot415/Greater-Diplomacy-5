import time

import pygame
from ui.navigation.screen import Screen
import data.constants as c
from ui.bars import ui_bars
from ui.widgets import text_utils
from ui.widgets import flag_icons, ui_elements
from ui.widgets.ui_elements import Button, process_text_input
from ui.rendering.font_manager import fonts
from map_logic.diplomacy import diplomacy_messages, diplomacy_processor, volunteers
from data import queries
from data.state_access import session_for
from ui.dialogs import pickers
from ui.background_styles import MESSAGE_PANEL_STYLES

from map_logic.diplomacy import player_diplomacy_actions, ratification
from screens.game.peace_screen import open_view_peace_treaty_menu, open_view_trade_deal_menu
from screens.game.deal_screen import open_trade_menu


# ==========================================
# LAYOUT
# ==========================================

MSG_LEFT_PANE_W = 280
MSG_INPUT_H = 80
MSG_HEADER_H = 64
MSG_REQUEST_H = 64
MSG_MARGIN = 16
MSG_CONTACT_ROW_H = 64
MSG_NEW_CONTACT_ROW_H = 36
MSG_CONTACT_ROW_GAP = 2
MSG_QUEUE_W = 112
MSG_CONTROL_GAP = 12
MSG_HEADER_BUTTON_H = 36
MSG_HEADER_BUTTON_Y = (MSG_HEADER_H - MSG_HEADER_BUTTON_H) // 2
MSG_HEADER_TRADE_W = 116
MSG_HEADER_THEME_W = MSG_HEADER_BUTTON_H  # Square: the Theme button shows the brush icon only.
MSG_HEADER_UNREAD_W = 146
MSG_CONTACT_TOOLBAR_Y = MSG_HEADER_H + MSG_HEADER_BUTTON_Y
# Contact toolbar: the sort button sits left of the small add button. Both end at the pane edge.
MSG_ADD_BUTTON_W = 36
MSG_ADD_BUTTON_X = MSG_LEFT_PANE_W - MSG_MARGIN - MSG_ADD_BUTTON_W
MSG_SORT_BUTTON_W = 84
MSG_SORT_BUTTON_X = MSG_ADD_BUTTON_X - 6 - MSG_SORT_BUTTON_W
# Contact sort orders in button cycle order. Recent puts the newest conversation first.
MSG_SORT_ORDERS = ("A-Z", "Z-A", "Recent")
MSG_CONTACT_FLAG_SIZE = (24, 16)
MSG_HEADER_FLAG_SIZE = (36, 24)
MSG_FLAG_GAP = 8

# The conversation header, reply bar and composer roll in while a country is
# selected and roll out when none is. The contact header keeps Exit reachable.
# Animation times are positive seconds. Entry slows down; exit speeds up.
MSG_BAR_ANIM_SECONDS = 0.2
MSG_BAR_EXIT_ANIM_SECONDS = 0.2
MSG_BUBBLE_ANIM_SECONDS = 0.2
MSG_BUBBLE_EXIT_ANIM_SECONDS = 0.2
# A power of 1 is linear. Higher values make the easing stronger.
MSG_ENTER_EASING_POWER = 3.0
MSG_EXIT_EASING_POWER = 3.0
# Background opacity: 0 is transparent, 1 is opaque. Text and borders stay opaque.
MSG_QUEUED_BUBBLE_OPACITY = 0.5
# Shared gradient strength: 0 is flat, 1 is the standard stepped gradient.
MSG_BUBBLE_GRADIENT_STRENGTH = 1.0
MSG_BOTTOM_BARS_H = MSG_REQUEST_H + MSG_INPUT_H

# Fixed controls stay above the scrollable conversation rows.
MSG_CONTACT_LIST_TOP_Y = 128

# Diplomacy buttons sit in a row above the compose box.
MSG_DIPLO_BTN_ROW_OFFSET_Y = -MSG_REQUEST_H + 7
MSG_DIPLO_BTN_START_X = MSG_LEFT_PANE_W + 20
MSG_DIPLO_BTN_STEP_X = 220

MSG_BG_DARK = (25, 25, 30)
# With no country selected the background is solid black with white text. Selecting a country
# fades the checkerboard in with the bar roll; deselecting fades it back out.
MSG_EMPTY_BG_COLOR = (0, 0, 0)
MSG_EMPTY_TEXT_COLOR = (255, 255, 255)
MSG_BUBBLE_PLAYER = (40, 100, 200)
MSG_BUBBLE_AI = (60, 60, 80)
MSG_DIPLO_ACCENT = (208, 162, 76)
MSG_SELECTED_ACCENT = (112, 181, 242)
MSG_PANEL_BORDER = (13, 17, 24)
MSG_CONTACT_THEME_HOVER_LIGHTEN = 20
MSG_BUBBLE_FORWARDED = (65, 105, 75)
MSG_BUBBLE_MAX_WIDTH_RATIO = 0.6
MSG_FORWARD_BUTTON_SIZE = (82, 24)


def _draw_cached_flag(surface, flag, x, center_y):
    """Draw a prepared flag without reading country data during a frame."""
    rect = flag.get_rect(midleft=(x, center_y))
    surface.blit(flag, rect)
    pygame.draw.rect(surface, (100, 100, 100), rect, 1)
    return rect.right + MSG_FLAG_GAP


class ConversationRow(Button):
    """A conversation row with cached text and the shared button input behavior."""

    def __init__(self, x, y, width, name, preview, unread, selected, callback, flag, *, compact=False, theme_color=None):
        height = MSG_NEW_CONTACT_ROW_H if compact else MSG_CONTACT_ROW_H
        super().__init__(x, y, (width, height), "grey", name, callback,
                         sound_kind="select_category")
        self.is_selected = selected
        base = tuple(theme_color) if theme_color is not None else MSG_BG_DARK
        hover = tuple(min(255, channel + MSG_CONTACT_THEME_HOVER_LIGHTEN) for channel in base)
        self.set_colors(base, hover)
        name_font = fonts.get_size(18, bold=bool(unread))
        preview_font = fonts.get("small")
        badge_font = fonts.get("tiny")
        self.flag = flag
        self.badge = badge_font.render(str(unread), True, (255, 255, 255)) if unread else None
        self.badge_width = max(24, self.badge.get_width() + 12) if self.badge else 0
        flag_space = self.flag.get_width() + MSG_FLAG_GAP
        text_width = width - 32 - flag_space - (self.badge_width + 8 if unread else 0)
        self.name_surface = name_font.render(text_utils.fit_text(name, name_font, text_width), True, (241, 245, 250))
        self.name_y = (height - self.name_surface.get_height()) // 2 if compact else 10
        self.preview_surface = (preview_font.render(
            text_utils.fit_text(preview, preview_font, width - 32), True, (174, 185, 200)) if not compact else None)

    def draw(self, surface):
        if not self.visible:
            return
        ui_elements.draw_pixel_button(
            surface, self.rect, self.color, hover_color=self.hover_color,
            pressed_color=self.pressed_color, pressed=self.is_pressed,
            disabled=self.disabled, border_color=MSG_PANEL_BORDER, gradient_strength=0.25)
        if self.is_selected:
            pygame.draw.rect(surface, MSG_SELECTED_ACCENT,
                             (self.rect.x + 2, self.rect.y + 2, 4, self.rect.height - 4))
        name_x = _draw_cached_flag(surface, self.flag, self.rect.x + 16,
                                   self.rect.y + self.name_y + self.name_surface.get_height() // 2)
        surface.blit(self.name_surface, (name_x, self.rect.y + self.name_y))
        if self.preview_surface is not None:
            surface.blit(self.preview_surface, (self.rect.x + 16, self.rect.y + 36))
        if self.badge:
            badge_rect = pygame.Rect(self.rect.right - self.badge_width - 10,
                                     self.rect.y + 10, self.badge_width, 22)
            ui_elements.draw_pixel_panel(surface, badge_rect, (52, 103, 158), MSG_PANEL_BORDER,
                                         gradient_strength=0.25)
            surface.blit(self.badge, self.badge.get_rect(center=badge_rect.center))


class Messages_Screen(Screen):
    back_state = "MAP"

    def __init__(self):
        super().__init__()
        self.bg_color = MSG_BG_DARK
        self.map_screen = None
        self.selected_recipient = None
        self.compose_text = ""
        self.drafts = [] 
        self.draft_edit_rects = []
        
        # The message thread scrolls on the positive convention (0 at the
        # newest message, growing as you scroll back), unlike Screen's
        # scroll_y which is a negative offset. Kept under its own name so
        # the two never share an attribute -- the contact list beside it
        # does use the base class's helpers, on the base convention.
        self.msg_scroll_y = 0
        self.max_msg_scroll = 0
        
        self.contact_scroll_y = 0
        self.max_contact_scroll = 0
        self.is_dragging_contacts = False
        self.message_drag_state = None
        self.forward_button_rects = []
        
        self.show_all_contacts = False
        self.contact_sort = MSG_SORT_ORDERS[0]
        self.processed_messages = []
        self.compose_surface = None
        self.compose_enabled = False

        # 0 is fully rolled out, 1 fully rolled in. bar_anim holds the start
        # time and start value of a roll toward bar_target.
        self.bar_shown = 0.0
        self.bar_target = 0.0
        self.bar_anim = None
        self.bar_elements = []
        # Start time of each bubble's slide-in, kept so a rebuild does not replay it.
        self.bubble_starts = {}
        self.exiting_thread = None
        self.black_cover = None
        # True only while select_recipient rebuilds for a contact switch: bubbles start fully slid in.
        self.settle_new_bubbles = False

    def on_enter(self, app, previous):
        self.start_messages(app.states["MAP"])

    def start_messages(self, map_ref):
        self.map_screen = map_ref
        self.selected_recipient = None
        self.compose_text = ""
        self.drafts = []
        self.draft_edit_rects = []
        self.msg_scroll_y = 0
        self.max_msg_scroll = 0
        self.contact_scroll_y = 0
        self.is_dragging_contacts = False
        self.message_drag_state = None
        self.forward_button_rects = []
        self.show_all_contacts = False
        self.bar_shown = 0.0
        self.bar_target = 0.0
        self.bar_anim = None
        self.bubble_starts = {}
        self.exiting_thread = None
        self.refresh_ui()

    @property
    def text_input_active(self):
        """The compose bar accepts keystrokes whenever a conversation is open."""
        return self.selected_recipient is not None or super().text_input_active

    def accept_proposal(self, target):
        custom_msg = self.compose_text.strip()
        player_diplomacy_actions.handle_accept_req(self.map_screen, target, custom_msg)
        self.compose_text = ""
        self.refresh_ui()

    def reject_proposal(self, target):
        custom_msg = self.compose_text.strip()
        player_diplomacy_actions.handle_reject_req(self.map_screen, target, custom_msg)
        self.compose_text = ""
        self.refresh_ui()

    def view_peace_treaty(self, target):
        self.save_current_draft()
        open_view_peace_treaty_menu(self.map_screen, target)
        self.refresh_ui()

    def view_trade_deal(self, target):
        self.save_current_draft()
        open_view_trade_deal_menu(self.map_screen, target)
        self.refresh_ui()

    def save_current_draft(self):
        """Save typed and queued text before switching menus or contacts."""
        if self.selected_recipient and self.map_screen:
            if self.compose_text.strip():
                self.drafts.append(self.compose_text.strip())
                self.compose_text = ""
            diplomacy_messages.save_text_drafts(
                self.map_screen.nation_data, self.map_screen.player_country,
                self.selected_recipient, self.drafts)

    def select_recipient(self, target):
        self.save_current_draft()

        if self.selected_recipient == target:
            self._start_thread_exit()
            self.selected_recipient = None
            self.compose_text = ""
            self.drafts = []
            self.refresh_ui()
            return

        # Switching contacts keeps the bars open, so the bubbles also appear without sliding.
        switching = self.selected_recipient is not None
        self.exiting_thread = None
        self.bubble_starts = {}
        self.selected_recipient = target
        self.message_drag_state = None
        self.msg_scroll_y = 0
        
        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        for msg in p_data.get("inbox", []):
            if msg.get("sender") == target:
                msg["read"] = True
                
        # Load drafts and sync with the map screen
        draft_lists = p_data.get("draft_lists", {})
        saved_list = draft_lists.get(target, [])
        draft_str = queries.get_message_draft(self.map_screen.player_country, target, self.map_screen.nation_data)
        
        if saved_list:
            self.drafts = saved_list.copy()
        elif draft_str.strip():
            # Automatically separate out external drafts that use newlines
            self.drafts = draft_str.strip().split("\n") 
        else:
            self.drafts = []
            
        self.compose_text = ""
        self.settle_new_bubbles = switching
        self.refresh_ui()
        self.settle_new_bubbles = False

    def cycle_contact_sort(self):
        self.contact_sort = MSG_SORT_ORDERS[(MSG_SORT_ORDERS.index(self.contact_sort) + 1) % len(MSG_SORT_ORDERS)]
        self.contact_scroll_y = 0
        self.refresh_ui()

    def toggle_add_contact(self):
        self.show_all_contacts = not self.show_all_contacts
        self.contact_scroll_y = 0
        self.refresh_ui()

    def edit_conversation_theme(self):
        if not self.selected_recipient:
            return
        country = self.selected_recipient
        colors = session_for(self.map_screen).conversation_colors
        name = queries.get_country_display_name(country, self.map_screen.nation_data)
        pickers.open_color_picker(
            self.map_screen, f"{name}: Conversation Theme", self.bg_color,
            lambda color: self._set_conversation_color(colors, country, color),
            on_reset=lambda: self._set_conversation_color(colors, country, None))

    def _set_conversation_color(self, colors, country, color):
        if color is None:
            colors.pop(country, None)
        else:
            colors[country] = list(color)
        if self.map_screen and session_for(self.map_screen).conversation_colors is colors:
            self.refresh_ui()

    def select_new_contact(self, target):
        self.show_all_contacts = False
        self.contact_scroll_y = 0
        self.select_recipient(target)

    def send_message(self):
        if self.map_screen.tactical_mode:
            return
        if self.selected_recipient:
            message = self.compose_text.strip()
            if message:
                self.drafts.append(message)
                self.compose_text = ""
                self.map_screen.show_feedback("Message queued.")
            
            self.save_current_draft()
            if message:
                ui_elements.play_ui_sound("send_message")
            self.refresh_ui()

    def _forward_targets(self, message):
        """Returns living countries this player can send the message to."""
        active_nations = {
            prov.get("owner") for prov in self.map_screen.map_data.values()
            if prov.get("owner") not in c.UNPLAYABLE_NATIONS
        }
        sender = message.get("sender", "") if isinstance(message, dict) else ""
        return [
            country for country, data in self.map_screen.nation_data.items()
            if data.get("is_playable")
            and country != self.map_screen.player_country
            and country != sender
            and country in active_nations
        ]

    def open_forward_picker(self, message):
        """Opens the country picker for one received message."""
        if not self.map_screen or self.map_screen.tactical_mode:
            return

        targets = self._forward_targets(message)
        targets.sort(key=lambda country: self.map_screen.nation_data.get(country, {}).get("name", country))
        if not targets:
            self.map_screen.show_feedback("There are no countries available to receive this message.")
            return

        # ListSelectScreen accepts display strings. Add the internal country key
        # only when two countries share a display name, then map the selection
        # back to the authoritative nation key in the callback.
        labels = []
        label_to_country = {}
        for country in targets:
            display_name = queries.get_country_display_name(country, self.map_screen.nation_data)
            label = display_name
            if label in label_to_country:
                label = f"{display_name} ({country})"
            labels.append(label)
            label_to_country[label] = country

        def confirm(label):
            target = label_to_country.get(label)
            if target:
                self.queue_forward(message, target)

        self.save_current_draft()
        pickers.open_listbox_selector(
            self, "Forward Message", "Select a country to receive this message:",
            labels, confirm)
        self.refresh_ui()

    def queue_forward(self, message, target):
        """Queues a provenance-stamped forward and keeps the current thread open."""
        if not self.map_screen or self.map_screen.tactical_mode:
            return
        result = diplomacy_messages.queue_forwarded_message(
            self.map_screen.nation_data, self.map_screen.player_country,
            target, self.map_screen.player_country, message)
        target_name = queries.get_country_display_name(target, self.map_screen.nation_data)
        if result.startswith("Forward queued"):
            self.map_screen.show_feedback(f"{result} ({target_name})")
        else:
            self.map_screen.show_feedback(result)
        self.refresh_ui()

    def mark_thread_unread(self):
        """Marks all messages from the selected contact as unread and returns to contact list."""
        if not self.selected_recipient or not self.map_screen: return
        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        for msg in p_data.get("inbox", []):
            if msg.get("sender") == self.selected_recipient:
                msg["read"] = False
                
        # Deselect recipient to return to contact list
        self.save_current_draft()
        self._start_thread_exit()
        self.selected_recipient = None
        self.compose_text = ""
        self.drafts = []
        self.refresh_ui()

    def mark_all_read(self):
        """Marks every received message as read.

        Unanswered incoming requests are excluded: their "unread" status is
        derived from the pending diplomatic state (not the message's read
        flag), so they only clear once the player actually responds.
        """
        if not self.map_screen: return
        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        for msg in p_data.get("inbox", []):
            msg["read"] = True
        self.refresh_ui()

    def additional_events(self, event):
        mx, my = getattr(event, "pos", pygame.mouse.get_pos())
        is_tactical = self.map_screen.tactical_mode
        in_thread = self.thread_rect.collidepoint((mx, my))
        if self.selected_recipient and event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            clicked_action = any(rect.collidepoint((mx, my)) for rect, _ in
                                 self.draft_edit_rects + self.forward_button_rects)
            if not (event.type == pygame.MOUSEBUTTONDOWN and clicked_action):
                if self.handle_content_drag(event, attr="msg_scroll_y", limit_attr="max_msg_scroll",
                                            rect_attr="thread_rect", drag_attr="message_drag_state",
                                            lo=0, hi=self.max_msg_scroll, refresh=False):
                    self.draft_edit_rects = []
                    self.forward_button_rects = []
                    return
        
        # --- Handle Draft Delete Clicks ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Guarded to the visible message pane so a delete box scrolled
            # behind the compose box (clipped, no longer drawn) can't fire.
            if not is_tactical and in_thread:
                for del_rect, idx in self.draft_edit_rects:
                    if del_rect.collidepoint(mx, my):
                        
                        # HANDLE DIPLOMATIC ACTION UNDO CLICKS
                        if idx == "TRADE_OFFER":
                            pending = diplomacy_messages.get_pending(
                                self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)
                            # Passing it to the toggle logic safely refunds the escrow!
                            diplomacy_processor.toggle_diplomacy_action(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient, "TRADE", "")
                            if pending.get("action") == "TRADE" and not diplomacy_messages.get_pending(
                                    self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient):
                                ui_elements.play_ui_sound("delete_message")
                            self.map_screen.show_feedback("Trade Offer Cancelled.")
                        elif idx == "WAR_DECLARATION":
                            diplomacy_messages.clear_pending(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)
                            self.map_screen.show_feedback("War Declaration Cancelled.")
                        elif isinstance(idx, str) and idx.startswith("FORMAL_"):
                            act_name = idx[7:]
                            pending = diplomacy_messages.get_pending(
                                self.map_screen.nation_data, self.map_screen.player_country,
                                self.selected_recipient)
                            if act_name == diplomacy_messages.FORWARD_ACTION:
                                diplomacy_messages.cancel_queued_forward(
                                    self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)
                            elif act_name == volunteers.ACTION:
                                if pending.get("turns", 0) == 0:
                                    volunteers.cancel_offer(
                                        self.map_screen, self.map_screen.player_country,
                                        self.selected_recipient)
                                    self.map_screen.show_feedback("Volunteer Offer Cancelled.")
                                else:
                                    self.map_screen.show_feedback("Cannot undo after the volunteer offer was delivered.")
                            elif act_name == volunteers.RECALL_ACTION:
                                msg = diplomacy_processor.toggle_diplomacy_action(
                                    self.map_screen.nation_data, self.map_screen.player_country,
                                    self.selected_recipient, volunteers.RECALL_ACTION)
                                self.map_screen.show_feedback(msg)
                            else:
                                diplomacy_messages.clear_pending(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)
                                self.map_screen.show_feedback(f"{act_name.replace('_', ' ').title()} Cancelled.")
                        else:
                            if isinstance(idx, int) and 0 <= idx < len(self.drafts):
                                self.drafts.pop(idx)
                                self.save_current_draft()
                                ui_elements.play_ui_sound("delete_message")
                            
                        self.refresh_ui()
                        return

        # Forward buttons are drawn with the message bubbles because their
        # positions move with the thread scroll. Handle release here rather than
        # making them ordinary screen elements, so a clipped/off-screen button
        # can never be clicked from stale geometry.
        if (event.type == pygame.MOUSEBUTTONUP and event.button == 1
                and not is_tactical and in_thread):
            for forward_rect, message in reversed(self.forward_button_rects):
                if forward_rect.collidepoint((mx, my)):
                    self.message_drag_state = None
                    self.open_forward_picker(message)
                    return

        # --- Contact List Scrolling (wheel, scrollbar-handle drag, content drag) ---
        if event.type == pygame.MOUSEWHEEL and mx < MSG_LEFT_PANE_W:
            self.scroll_by(event, attr="contact_scroll_y", limit_attr="max_contact_scroll", speed=30)
        elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            if self.handle_list_scroll(event, attr="contact_scroll_y", limit_attr="max_contact_scroll",
                                        track_attr="contact_scroll_track_rect", handle_attr="contact_scroll_handle_rect",
                                        drag_attr="is_dragging_contacts", content_rect_attr="scroll_content_rect"):
                return

        # --- Message Thread Scrolling ---
        if event.type == pygame.MOUSEWHEEL and in_thread:
            self.msg_scroll_y += event.y * 40
            self.msg_scroll_y = max(0, min(self.msg_scroll_y, self.max_msg_scroll))
            self.draft_edit_rects = []
            self.forward_button_rects = []

        # --- Text Input Logic ---
        if self.selected_recipient:
            locked = queries.is_diplomat_busy(self.map_screen.player_country, self.selected_recipient, self.map_screen.nation_data)
            if not locked and not is_tactical:
                previous_text = self.compose_text
                self.compose_text, status = process_text_input(event, self.compose_text, max_length=c.MAX_MESSAGE_LENGTH)
                if status == "SUBMIT":
                    self.send_message()
                elif self.compose_text != previous_text:
                    self._prepare_composer()

    def refresh_ui(self):
        self._build_ui()
        self._anchor_bars()

    def update(self):
        target = 1.0 if self.selected_recipient else 0.0
        now = time.monotonic()
        if self.exiting_thread and now - self.exiting_thread["started_at"] >= MSG_BUBBLE_EXIT_ANIM_SECONDS:
            self.exiting_thread = None
        if target != self.bar_target:
            self.bar_target = target
            self.bar_anim = (now, self.bar_shown)
        if self.bar_anim:
            start, origin = self.bar_anim
            entering = target > origin
            duration = MSG_BAR_ANIM_SECONDS if entering else MSG_BAR_EXIT_ANIM_SECONDS
            progress = max(0.0, min(1.0, (now - start) / duration))
            eased = 1 - (1 - progress) ** MSG_ENTER_EASING_POWER if entering else progress ** MSG_EXIT_EASING_POWER
            self.bar_shown = origin + (target - origin) * eased
            if progress >= 1.0:
                self.bar_anim = None
            self._apply_bar_offsets()

    def _start_thread_exit(self):
        """Keep cached bubbles until their exit animation ends. Disable their controls immediately."""
        now = time.monotonic()
        messages = []
        for prepared in self.processed_messages:
            progress = max(0.0, min(1.0, (now - prepared["anim_start"]) / MSG_BUBBLE_ANIM_SECONDS))
            messages.append(dict(prepared, exit_offset=(1 - progress) ** MSG_ENTER_EASING_POWER))
        self.exiting_thread = {"messages": messages, "started_at": now, "rect": self.thread_rect.copy(),
                               "scroll_y": self.msg_scroll_y, "max_scroll": self.max_msg_scroll} if messages else None
        self.message_drag_state = None
        self.draft_edit_rects = []
        self.forward_button_rects = []

    def _bar_offsets(self):
        """Vertical shift of the top and bottom conversation bars at the current roll."""
        hidden = 1.0 - self.bar_shown
        return -round(hidden * MSG_HEADER_H), round(hidden * MSG_BOTTOM_BARS_H)

    def _anchor_bars(self):
        """Remember each bar button's resting y so rebuilt buttons keep rolling."""
        self.bar_elements = []
        if not self.map_screen:
            return
        for element in self.elements:
            rect = element.rect
            if rect.x >= MSG_LEFT_PANE_W and rect.bottom <= MSG_HEADER_H:
                self.bar_elements.append((element, rect.y, True))
            elif rect.x >= MSG_LEFT_PANE_W and rect.top >= self.thread_rect.bottom:
                self.bar_elements.append((element, rect.y, False))
        self._apply_bar_offsets()

    def _apply_bar_offsets(self):
        top_dy, bottom_dy = self._bar_offsets()
        for element, base_y, is_top in self.bar_elements:
            element.rect.y = base_y + (top_dy if is_top else bottom_dy)

    def _build_ui(self):
        colors = session_for(self.map_screen).conversation_colors if self.map_screen else {}
        # With no country selected, keep the last color so the fade to black does not jump to the default.
        if self.selected_recipient:
            self.bg_color = tuple(colors.get(self.selected_recipient, MSG_BG_DARK))
        self.elements = [Button(MSG_MARGIN, MSG_HEADER_BUTTON_Y, (70, MSG_HEADER_BUTTON_H), "red", "Exit", self.exit_screen,
                                font_preset="button_small", sound_kind="back")]
        self.elements.append(Button(94, MSG_HEADER_BUTTON_Y, (170, MSG_HEADER_BUTTON_H), "blue", "Mark All Read", self.mark_all_read,
                                    font_preset="button_small"))
        # The thread draws these hitboxes after it knows the current scroll
        # position. Never retain geometry from a frame that was rebuilt.
        self.forward_button_rects = []
        if not self.map_screen: return
        self.thread_rect = pygame.Rect(MSG_LEFT_PANE_W, MSG_HEADER_H,
                                       c.SCREEN_WIDTH - MSG_LEFT_PANE_W,
                                       c.SCREEN_HEIGHT - MSG_HEADER_H - MSG_INPUT_H - MSG_REQUEST_H)
        self._prepare_thread()
        self._prepare_composer()
        unread_x = c.SCREEN_WIDTH - MSG_MARGIN - MSG_HEADER_UNREAD_W
        trade_x = unread_x - MSG_CONTROL_GAP - MSG_HEADER_TRADE_W
        theme_x = trade_x - MSG_CONTROL_GAP - MSG_HEADER_THEME_W
        header = queries.get_country_display_name(self.selected_recipient, self.map_screen.nation_data) if self.selected_recipient else "Messages"
        header_font = fonts.get("heading2")
        self.header_flag = (flag_icons.flag_surface(self.selected_recipient, self.map_screen.nation_data, MSG_HEADER_FLAG_SIZE)
                            if self.selected_recipient else None)
        flag_space = self.header_flag.get_width() + MSG_FLAG_GAP if self.header_flag is not None else 0
        header_width = theme_x - MSG_LEFT_PANE_W - 2 * MSG_MARGIN - flag_space
        self.header_surface = header_font.render(text_utils.fit_text(header, header_font, header_width), True, (241, 245, 250))
        self.sidebar_title_surface = fonts.get("normal").render("Messages", True, (220, 229, 240))
        self.empty_thread_surface = header_font.render("Select a nation to view communications.", True, MSG_EMPTY_TEXT_COLOR)
        
        active_nations = set([prov.get("owner") for prov in self.map_screen.map_data.values() if prov.get("owner") not in c.UNPLAYABLE_NATIONS])
        playable = [country for country, d in self.map_screen.nation_data.items() if d.get("is_playable") and country != self.map_screen.player_country and country in active_nations]
        playable.sort(key=lambda country: self.map_screen.nation_data.get(country, {}).get("name", country))

        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        inbox = p_data.get("inbox", [])

        history_contacts = set()
        for msg in inbox:
            sender = msg.get("sender", "")
            if sender.startswith("To: "):
                history_contacts.add(sender[4:])
            else:
                history_contacts.add(sender)

        # These all iterate snapshots -- a turn can still be resolving while this
        # screen rebuilds, and a live iterator would trip over the changes.
        pending = diplomacy_messages.get_pending_map(self.map_screen.nation_data, self.map_screen.player_country)
        for target, p_info in list(pending.items()):
            if target in playable and isinstance(p_info, dict) and p_info.get("action"):
                history_contacts.add(target)
            elif target in playable and queries.get_message_draft(self.map_screen.player_country, target, self.map_screen.nation_data).strip():
                history_contacts.add(target)

        # Anyone waiting on our answer, plus anyone we've already answered. Without
        # this a request whose message went astray would raise the unread badge
        # while having no row here to click -- a notification with nowhere to go.
        for sender in queries.get_pending_request_senders(self.map_screen.player_country, self.map_screen.nation_data):
            if sender in playable:
                history_contacts.add(sender)
        for sender in list(diplomacy_messages.get_response_map(self.map_screen.nation_data, self.map_screen.player_country)):
            if sender in playable:
                history_contacts.add(sender)

        if self.selected_recipient:
            history_contacts.add(self.selected_recipient)

        self.scroll_content_rect = pygame.Rect(MSG_MARGIN, MSG_CONTACT_LIST_TOP_Y,
                                               MSG_LEFT_PANE_W - 2 * MSG_MARGIN - 14,
                                               c.SCREEN_HEIGHT - MSG_CONTACT_LIST_TOP_Y - MSG_MARGIN)
        if self.show_all_contacts:
            self.elements.append(Button(132, MSG_CONTACT_TOOLBAR_Y, (132, MSG_HEADER_BUTTON_H), "grey", "Cancel", self.toggle_add_contact,
                                        font_preset="button_small"))
            display_list = [n for n in playable if n not in history_contacts]
        else:
            self.elements.append(Button(MSG_SORT_BUTTON_X, MSG_CONTACT_TOOLBAR_Y, (MSG_SORT_BUTTON_W, MSG_HEADER_BUTTON_H), "grey",
                                        self.contact_sort, self.cycle_contact_sort, font_preset="button_small"))
            self.elements.append(Button(MSG_ADD_BUTTON_X, MSG_CONTACT_TOOLBAR_Y, (MSG_ADD_BUTTON_W, MSG_HEADER_BUTTON_H), "green", "+",
                                        self.toggle_add_contact, font_preset="button_small", sound_kind="paper"))
            display_list = [n for n in playable if n in history_contacts]
        previews = {}
        unread_counts = {}
        # The inbox is newest first, so a contact's first entry gives its recency rank.
        recency = {}
        for message in inbox:
            sender = message.get("sender", "")
            outgoing = sender.startswith("To: ")
            country = sender[4:] if outgoing else sender
            recency.setdefault(country, len(recency))
            previews.setdefault(country, ("You: " if outgoing else "") + " ".join(message.get("content", "").split()))
            if not outgoing and not message.get("read", False):
                unread_counts[country] = unread_counts.get(country, 0) + 1

        # display_list starts in A-Z order. The Add list has no messages, so it stays A-Z.
        if not self.show_all_contacts:
            if self.contact_sort == "Z-A":
                display_list.reverse()
            elif self.contact_sort == "Recent":
                # Stable sort: contacts without messages keep A-Z order after the rest.
                display_list.sort(key=lambda country: recency.get(country, len(recency)))

        row_height = MSG_NEW_CONTACT_ROW_H if self.show_all_contacts else MSG_CONTACT_ROW_H
        row_step = row_height + MSG_CONTACT_ROW_GAP
        self.max_contact_scroll = min(0, self.scroll_content_rect.height - len(display_list) * row_step)
        self.contact_scroll_y = max(self.max_contact_scroll, min(0, self.contact_scroll_y))
        for index, country in enumerate(display_list):
            y = MSG_CONTACT_LIST_TOP_Y + index * row_step + self.contact_scroll_y
            display_name = queries.get_country_display_name(country, self.map_screen.nation_data)
            unread = unread_counts.get(country, 0)
            # Unanswered requests use the same unread rule as the map badge.
            if queries.has_unanswered_request(self.map_screen.player_country, country, self.map_screen.nation_data):
                unread += 1
            callback = self.select_new_contact if self.show_all_contacts else self.select_recipient
            row = ConversationRow(MSG_MARGIN, y, self.scroll_content_rect.width,
                                  display_name, previews.get(country, ""), unread,
                                  self.selected_recipient == country,
                                  lambda target=country, select=callback: select(target),
                                  flag=flag_icons.flag_surface(country, self.map_screen.nation_data, MSG_CONTACT_FLAG_SIZE),
                                  compact=self.show_all_contacts, theme_color=colors.get(country))
            row.is_scrollable = True
            row.click_guard = self.content_hover_guard()
            self.elements.append(row)

        is_tactical = self.map_screen.tactical_mode
        queue_button = Button(c.SCREEN_WIDTH - MSG_MARGIN - MSG_QUEUE_W,
                              c.SCREEN_HEIGHT - MSG_INPUT_H + MSG_MARGIN,
                              (MSG_QUEUE_W, MSG_INPUT_H - 2 * MSG_MARGIN), "blue", "Queue",
                              self.send_message, font_preset="button_small", sound_kind=None)
        queue_button.apply_state(enabled=bool(self.selected_recipient) and not is_tactical, color="blue")
        self.elements.append(queue_button)
        unread_button = Button(unread_x, MSG_HEADER_BUTTON_Y, (MSG_HEADER_UNREAD_W, MSG_HEADER_BUTTON_H), "orange",
                               "Mark Unread", self.mark_thread_unread, font_preset="button_small")
        unread_button.disabled = not self.selected_recipient
        self.elements.append(unread_button)
        # Integrated puppets used to be barred from trading with anyone but
        # their master. They trade like anyone else now.
        trade_button = Button(trade_x, MSG_HEADER_BUTTON_Y, (MSG_HEADER_TRADE_W, MSG_HEADER_BUTTON_H), "orange", "Trade", self.open_trade,
                              font_preset="button_small")
        trade_button.disabled = not self.selected_recipient or is_tactical
        self.elements.append(trade_button)
        theme_button = Button(theme_x, MSG_HEADER_BUTTON_Y, (MSG_HEADER_THEME_W, MSG_HEADER_BUTTON_H), "blue", "Theme",
                              self.edit_conversation_theme, image=ui_elements.UI_ICONS.get("brush"),
                              show_text=False, font_preset="button_small")
        theme_button.disabled = not self.selected_recipient
        self.elements.append(theme_button)

        # Ratification has its own channel. A leader can ask several members without replacing unrelated offers.
        # Its controls take priority over ordinary bilateral replies.
        if self.selected_recipient and self._offer_ratification_buttons():
            return

        incoming_action, incoming_turns = "", 0
        queued_verdict, queued_action = "", ""
        if self.selected_recipient:
            incoming_action, incoming_turns = queries.get_diplomatic_status(self.selected_recipient, self.map_screen.player_country, self.map_screen.nation_data)
            queued_verdict, queued_action = diplomacy_messages.get_response_status(
                self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)

        has_offer = incoming_turns > 0 and incoming_action in c.BILATERAL_ACTIONS
        answered = has_offer and queued_action == incoming_action
        accepted = answered and queued_verdict == diplomacy_messages.RESPONSE_ACCEPT
        declined = answered and queued_verdict == diplomacy_messages.RESPONSE_REJECT
        action_name = incoming_action.replace("_", " ").title() if has_offer else ""
        accept_label = "Undo Accept" if accepted else f"Accept {action_name}".strip()
        decline_label = "Undo Decline" if declined else f"Decline {action_name}".strip()
        # Replies remain independent of our outgoing diplomat's travel state.
        editable = has_offer and not is_tactical
        self.elements.append(self._reply_button(0, "green", accept_label,
                                                lambda: self.accept_proposal(self.selected_recipient),
                                                enabled=editable and not declined))
        self.elements.append(self._reply_button(1, "red", decline_label,
                                                lambda: self.reject_proposal(self.selected_recipient),
                                                enabled=editable and not accepted))
        is_peace = has_offer and incoming_action in ("PEACE_TREATY", "CEASEFIRE")
        is_trade = has_offer and incoming_action == "TRADE"
        view_label = "View Peace Treaty" if is_peace else "View Trade Deal" if is_trade else "View Offer"
        view_callback = self.view_peace_treaty if is_peace else self.view_trade_deal
        self.elements.append(self._reply_button(2, "yellow", view_label,
                                                lambda: view_callback(self.selected_recipient),
                                                enabled=is_peace or is_trade))

    def _reply_button(self, slot, color, label, callback, *, enabled=True):
        button = Button(MSG_DIPLO_BTN_START_X + MSG_DIPLO_BTN_STEP_X * slot,
                        c.SCREEN_HEIGHT - MSG_INPUT_H + MSG_DIPLO_BTN_ROW_OFFSET_Y,
                        (200, 50), color, label, callback, font_preset="button_small")
        button.fit_text = True
        button.fit_single_line = True
        button.apply_state(enabled=enabled, color=color)
        return button

    def _offer_ratification_buttons(self):
        """Ratify / refuse, when the selected contact is the leader who signed.

        Returns True when it drew them, so the ordinary Accept/Reject pair for
        that nation stays out of the way -- answering the treaty is the only
        thing that matters while one is on the table.
        """

        asked = ratification.pending_for(self.map_screen.nation_data,
                                         self.map_screen.player_country)
        if not asked or asked.get("signatory") != self.selected_recipient:
            return False

        verdict = asked.get("verdict")
        editable = not self.map_screen.tactical_mode

        ratified = verdict == ratification.RATIFY
        refused = verdict == ratification.REFUSE
        self.elements.append(self._reply_button(0, "green", "Ratified (undo)" if ratified else "Ratify Treaty",
                                                self.clear_ratification if ratified else lambda: self.answer_ratification(True),
                                                enabled=editable and not refused))
        self.elements.append(self._reply_button(1, "red", "Refused (undo)" if refused else "Refuse & Leave Faction",
                                                self.clear_ratification if refused else lambda: self.answer_ratification(False),
                                                enabled=editable and not ratified))
        self.elements.append(self._reply_button(2, "yellow", "View Treaty",
                                                lambda: self.view_peace_treaty(self.selected_recipient)))
        return True

    def answer_ratification(self, accept):
        if self.map_screen.tactical_mode:
            return
        player_diplomacy_actions.handle_ratify_treaty(self.map_screen, accept)
        self.refresh_ui()

    def clear_ratification(self):
        """Takes back an answer, while the leader is still waiting on it."""
        if self.map_screen.tactical_mode or not player_diplomacy_actions.can_edit_diplomacy(self.map_screen):
            return

        ratification.pending_for(self.map_screen.nation_data,
                                 self.map_screen.player_country).pop("verdict", None)
        self.refresh_ui()

    def open_trade(self):
        if not self.selected_recipient or self.map_screen.tactical_mode:
            return
        self.save_current_draft()
        open_trade_menu(self.map_screen, self.selected_recipient)
        self.refresh_ui()

    def _prepare_thread(self):
        """Cache message presentation when the conversation or its state changes."""
        self.processed_messages = []
        self.max_msg_scroll = 0
        self.draft_edit_rects = []
        self.delete_label = fonts.get("small").render("X", True, (255, 255, 255))
        if not self.selected_recipient:
            return

        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        inbox = p_data.get("inbox", [])
        
        display_thread = []
        archived_terms = False

        # 1. Build thread with historical messages (reversed so oldest is at index 0)
        for msg in reversed(inbox):
            if msg.get("sender") == self.selected_recipient or msg.get("sender") == f"To: {self.selected_recipient}":
                is_player = msg["sender"].startswith("To: ")

                # Detect newlines and split them back into multiple visual bubbles automatically
                lines_split = [t for t in msg["content"].split("\n") if t.strip()]
                for idx, sub_text in enumerate(lines_split):
                    # Only append the date to the first bubble if it's a split message
                    show_date = msg.get("date", "") if idx == 0 else ""
                    forwarded_header = []
                    if idx == 0 and diplomacy_messages.is_forwarded(msg):
                        details = diplomacy_messages.forwarded_details(msg)
                        forwarded_header = [
                            ">> FORWARDED MESSAGE",
                            f"Originally sent by {details['original_sender']} to {details['original_receiver']} on {details['original_date']}",
                            f"Forwarded by {details['forwarded_by']} on {details['forwarded_at']}",
                        ]

                    display_thread.append({
                        "content": sub_text,
                        "is_player": is_player,
                        "is_draft": False,
                        "is_diplo": msg.get("type") == "DIPLOMACY",
                        "date": "" if forwarded_header else show_date,
                        "forwarded_header": forwarded_header,
                        "forward_source": msg if idx == 0 and not is_player else None,
                    })

                # --- WHAT THIS TRADE ACTUALLY ASKED FOR ---
                # The offer travels as prose only -- the AI's covering line, or
                # the sender's own -- so without this a player was asked to
                # accept terms they could not see, and after accepting had no
                # record of what they had agreed to. The numbers ride on the
                # message now, so they stay put once the offer is resolved and
                # its pending entry cleared. Keys are written from the
                # PROPOSER's point of view, so the sent copy reads them
                # straight and the received copy reads them inverted.
                trade_subject = None
                trade_viewer_is_proposer = is_player
                if diplomacy_messages.is_forwarded(msg):
                    # A forwarded treaty is being read by a third party. Keep
                    # the terms in the original recipient's voice instead of
                    # relabelling them as the current reader's own deal.
                    trade_details = diplomacy_messages.forwarded_details(msg)
                    trade_subject = trade_details["original_receiver"]
                    trade_viewer_is_proposer = False
                for line in diplomacy_messages.describe_trade(
                        msg.get("parameters"),
                        viewer_is_proposer=trade_viewer_is_proposer,
                        subject=trade_subject,
                        nation_data=self.map_screen.nation_data):
                    archived_terms = True
                    display_thread.append({
                        "content": line, "is_player": is_player, "is_draft": False,
                        "is_diplo": True, "date": "", "forwarded_header": [],
                        "forward_source": None,
                    })

        # Saves made before the terms were recorded on the message still have
        # them on the sender's pending entry, which is the only place they ever
        # lived. Read from there when the thread carried none.
        their_offer = diplomacy_messages.get_pending(
            self.map_screen.nation_data, self.selected_recipient, self.map_screen.player_country)
        if (not archived_terms and their_offer.get("action") == "TRADE"
                and their_offer.get("turns", 0) > 0):
            for line in diplomacy_messages.describe_trade(
                    their_offer.get("parameters"),
                    nation_data=self.map_screen.nation_data):
                display_thread.append({
                    "content": line, "is_player": False, "is_draft": False,
                    "is_diplo": True, "date": "", "forwarded_header": [],
                    "forward_source": None,
                })

        # Check if there is an active diplomatic action pending for this target
        pending = diplomacy_messages.get_pending(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)
        act_str = pending.get("action", "")
        is_diplo_action = bool(act_str) and not act_str.startswith("MSG:")
        forward_queued = diplomacy_messages.has_queued_forward(pending)

        # --- INJECT PENDING FORMAL ACTIONS AS VISUAL DRAFTS SO THEY CAN BE CANCELED ---
        if forward_queued or (is_diplo_action and pending.get("turns", 0) == 0):
            if forward_queued:
                content_str = f"Pending Forward Message: {pending['forwarded_message']['content']}"
                d_idx = f"FORMAL_{diplomacy_messages.FORWARD_ACTION}"
            elif act_str == "TRADE":
                content_str = pending.get("message", "Proposed Trade")
                d_idx = "TRADE_OFFER"
            elif act_str == "WAR_DECLARATION":
                content_str = f"War Declaration ({pending.get('message', 'Declare War')})"
                d_idx = "WAR_DECLARATION"
            else:
                act_lbl = act_str.replace("_", " ").title()
                msg_param = pending.get("message", "")
                content_str = f"Pending {act_lbl}: {msg_param}" if msg_param else f"Pending {act_lbl}"
                d_idx = f"FORMAL_{act_str}"

            display_thread.append({
                "content": content_str,
                "is_player": True,
                "is_draft": True,
                "draft_idx": d_idx,
                "is_diplo": True,
                "date": "",
                "forwarded_header": [],
                "forward_source": None,
            })

        # --- INJECT TEXT DRAFTS AS VISUAL DRAFTS SO THEY CAN BE CANCELED ---
        for idx, draft_text in enumerate(self.drafts):
            display_thread.append({
                "content": draft_text,
                "is_player": True,
                "is_draft": True,
                "draft_idx": idx,
                "is_diplo": False,
                "date": "",
                "forwarded_header": [],
                "forward_source": None,
            })
        
        font_small = fonts.get("normal")
        font_tiny = fonts.get("tiny")
        max_width = int(self.thread_rect.width * MSG_BUBBLE_MAX_WIDTH_RATIO)
        line_height = max(20, font_small.get_height())
        total_h = 20
        # A bubble slides in once, when it first appears in this conversation. Numbering
        # equal bubbles from the oldest keeps an older bubble's key when a newer one arrives.
        now = time.monotonic()
        if self.settle_new_bubbles:
            now -= MSG_BUBBLE_ANIM_SECONDS
        counts = {}
        for msg in display_thread:
            same = (msg["is_player"], msg["is_draft"], msg["content"])
            counts[same] = counts.get(same, -1) + 1
            msg["anim_start"] = self.bubble_starts.setdefault(same + (counts[same],), now)
        for msg in reversed(display_thread):
            lines = text_utils.wrap_text(msg["content"], font_small, max_width)
            headers = []
            for index, header in enumerate(msg["forwarded_header"]):
                color = c.COLOR_GOLD_HIGHLIGHT if index == 0 else (170, 180, 195)
                headers.extend((line, color) for line in text_utils.wrap_text(header, font_tiny, max_width))
            if not headers and msg["date"]:
                headers = [(msg["date"], (151, 163, 181))]
            width = max([font_small.size(line)[0] for line in lines]
                        + [font_tiny.size(line)[0] for line, _color in headers] + [100]) + 30
            header_h = len(headers) * 20 + (5 if headers else 0)
            bubble_h = 20 + len(lines) * line_height
            height = header_h + bubble_h
            cached = pygame.Surface((width, height), pygame.SRCALPHA)
            for index, (line, color) in enumerate(headers):
                rendered = font_tiny.render(line, True, color)
                x = width - rendered.get_width() if msg["is_player"] else 0
                cached.blit(rendered, (x, index * 20))
            color = MSG_BUBBLE_PLAYER if msg["is_player"] else MSG_BUBBLE_AI
            if msg["forwarded_header"]:
                color = MSG_BUBBLE_FORWARDED
            border = c.COLOR_GOLD_HIGHLIGHT if msg["is_draft"] or msg["forwarded_header"] else MSG_PANEL_BORDER
            bubble = pygame.Rect(0, header_h, width, bubble_h)
            if msg["is_draft"]:
                color = (*color, round(255 * MSG_QUEUED_BUBBLE_OPACITY))
            ui_elements.draw_pixel_panel(cached, bubble, color, border,
                                         gradient_strength=MSG_BUBBLE_GRADIENT_STRENGTH)
            if msg["is_diplo"]:
                pygame.draw.rect(cached, MSG_DIPLO_ACCENT, (2, header_h + 2, 3, bubble_h - 4))
            for index, line in enumerate(lines):
                cached.blit(font_small.render(line, True, (242, 245, 250)), (15, header_h + 10 + index * line_height))
            forward = None
            if msg["forward_source"] and not self.map_screen.tactical_mode:
                forward = Button(0, 0, MSG_FORWARD_BUTTON_SIZE, "grey", "Forward", lambda: None, font_preset="tiny")
            self.processed_messages.append({"msg_data": msg, "surface": cached, "anim_start": msg["anim_start"],
                                            "box_height": height, "box_width": width,
                                            "header_h": header_h, "bubble_h": bubble_h,
                                            "forward_button": forward})
            total_h += height + 15
        self.max_msg_scroll = max(0, total_h - self.thread_rect.height + 20)
        self.msg_scroll_y = max(0, min(self.msg_scroll_y, self.max_msg_scroll))

    def _prepare_composer(self):
        """Cache the input text after edits and conversation changes."""
        self.input_rect = pygame.Rect(MSG_LEFT_PANE_W + MSG_MARGIN,
                                      c.SCREEN_HEIGHT - MSG_INPUT_H + MSG_MARGIN,
                                      c.SCREEN_WIDTH - MSG_LEFT_PANE_W - 2 * MSG_MARGIN - MSG_QUEUE_W - MSG_CONTROL_GAP,
                                      MSG_INPUT_H - 2 * MSG_MARGIN)
        self.compose_enabled = bool(self.selected_recipient) and not self.map_screen.tactical_mode
        if self.compose_enabled:
            self.compose_enabled = not queries.is_diplomat_busy(
                self.map_screen.player_country, self.selected_recipient, self.map_screen.nation_data)
        text = self.compose_text + ("|" if self.compose_enabled else "")
        self.compose_surface = fonts.get("normal").render(text, True, (242, 245, 250))

    def draw_background(self, surface):
        """Black until a country is selected. bar_shown carries the eased fade in both directions."""
        if self.bar_shown <= 0.0:
            surface.fill(MSG_EMPTY_BG_COLOR)
            return
        super().draw_background(surface)
        if self.bar_shown < 1.0:
            if self.black_cover is None or self.black_cover.get_size() != surface.get_size():
                self.black_cover = pygame.Surface(surface.get_size())
                self.black_cover.fill(MSG_EMPTY_BG_COLOR)
            self.black_cover.set_alpha(round(255 * (1.0 - self.bar_shown)))
            surface.blit(self.black_cover, (0, 0))

    def _draw_panel(self, surface, rect, name):
        style = MESSAGE_PANEL_STYLES[name]
        ui_elements.draw_pixel_panel(surface, rect, style["color"], MSG_PANEL_BORDER,
                                     gradient_strength=style["gradient_strength"])

    def additional_draw(self, surface):
        if not self.map_screen:
            return
        self._draw_panel(surface, pygame.Rect(0, 0, MSG_LEFT_PANE_W, c.SCREEN_HEIGHT), "contacts")
        self._draw_panel(surface, pygame.Rect(0, 0, MSG_LEFT_PANE_W, MSG_HEADER_H), "header")
        top_dy, bottom_dy = self._bar_offsets()
        self._draw_panel(surface, pygame.Rect(MSG_LEFT_PANE_W, top_dy, c.SCREEN_WIDTH - MSG_LEFT_PANE_W, MSG_HEADER_H), "header")
        sidebar_title_y = MSG_CONTACT_TOOLBAR_Y + (MSG_HEADER_BUTTON_H - self.sidebar_title_surface.get_height()) // 2
        surface.blit(self.sidebar_title_surface, (MSG_MARGIN, sidebar_title_y))
        header_x = MSG_LEFT_PANE_W + MSG_MARGIN
        if self.header_flag is not None:
            header_x = _draw_cached_flag(surface, self.header_flag, header_x, top_dy + MSG_HEADER_H // 2)
        surface.blit(self.header_surface, (header_x,
                                           top_dy + (MSG_HEADER_H - self.header_surface.get_height()) // 2))
        self.draw_list_scrollbar(surface, MSG_LEFT_PANE_W - 20, MSG_CONTACT_LIST_TOP_Y,
                                 self.scroll_content_rect.height, width=10,
                                 attr="contact_scroll_y", limit_attr="max_contact_scroll",
                                 track_attr="contact_scroll_track_rect", handle_attr="contact_scroll_handle_rect")
        request_rect = pygame.Rect(MSG_LEFT_PANE_W, self.thread_rect.bottom + bottom_dy,
                                    self.thread_rect.width, MSG_REQUEST_H)
        self._draw_panel(surface, request_rect, "requests")
        composer_rect = pygame.Rect(MSG_LEFT_PANE_W, request_rect.bottom,
                                     self.thread_rect.width, MSG_INPUT_H)
        self._draw_panel(surface, composer_rect, "composer")
        input_rect = self.input_rect.move(0, bottom_dy)
        ui_elements.draw_text_input_background(surface, input_rect, active=self.compose_enabled,
                                               style_name="message",
                                               border_color=MSG_SELECTED_ACCENT if self.compose_enabled else (80, 90, 106))
        text_rect = input_rect.inflate(-24, -12)
        with ui_bars.clip_scroll_region(surface, text_rect, draw_top=False, draw_bottom=False):
            x = text_rect.x - max(0, self.compose_surface.get_width() - text_rect.width)
            surface.blit(self.compose_surface, (x, text_rect.centery - self.compose_surface.get_height() // 2))
        if self.bar_shown < 1.0:
            # Centered on the screen height and on the conversation area, fading with the background.
            self.empty_thread_surface.set_alpha(round(255 * (1.0 - self.bar_shown)))
            surface.blit(self.empty_thread_surface, self.empty_thread_surface.get_rect(
                center=(self.thread_rect.centerx, c.SCREEN_HEIGHT // 2)))
        self.draft_edit_rects = []
        self.forward_button_rects = []
        if self.exiting_thread:
            thread = self.exiting_thread
            self._draw_thread(surface, thread["messages"], thread["rect"], thread["scroll_y"],
                              thread["max_scroll"], exit_started=thread["started_at"])
        else:
            self._draw_thread(surface, self.processed_messages, self.thread_rect, self.msg_scroll_y, self.max_msg_scroll)

    def _draw_thread(self, surface, messages, rect, scroll_y, max_scroll, *, exit_started=None):
        current_y = rect.bottom - 20 + scroll_y
        now = time.monotonic()
        interactive = self.selected_recipient is not None and exit_started is None
        exit_progress = max(0.0, min(1.0, (now - exit_started) / MSG_BUBBLE_EXIT_ANIM_SECONDS)) if exit_started is not None else None
        with ui_bars.clip_scroll_region(surface, rect, draw_top=scroll_y < max_scroll, draw_bottom=scroll_y != 0):
            for prepared in messages:
                current_y -= prepared["box_height"]
                msg = prepared["msg_data"]
                if current_y + prepared["box_height"] >= rect.top and current_y < rect.bottom:
                    x = rect.right - prepared["box_width"] - 30 if msg["is_player"] else rect.left + 30
                    # Each bubble enters and leaves through its sender's side.
                    edge_x = rect.right if msg["is_player"] else rect.left - prepared["box_width"]
                    if exit_progress is None:
                        progress = max(0.0, min(1.0, (now - prepared["anim_start"]) / MSG_BUBBLE_ANIM_SECONDS))
                        offset = (1 - progress) ** MSG_ENTER_EASING_POWER
                    else:
                        initial = prepared["exit_offset"]
                        offset = initial + (1 - initial) * exit_progress ** MSG_EXIT_EASING_POWER
                    x += round((edge_x - x) * offset)
                    surface.blit(prepared["surface"], (x, current_y))
                    button_y = current_y + prepared["header_h"] + prepared["bubble_h"] // 2
                    if interactive and msg["is_draft"] and not self.map_screen.tactical_mode:
                        delete_rect = pygame.Rect(x - 35, button_y - 12, 25, 25)
                        self.draft_edit_rects.append((delete_rect.clip(rect), msg["draft_idx"]))
                        ui_elements.draw_pixel_button(surface, delete_rect, (130, 48, 48))
                        surface.blit(self.delete_label, self.delete_label.get_rect(center=delete_rect.center))
                    forward = prepared["forward_button"]
                    if interactive and forward:
                        forward.rect.topleft = (x + prepared["box_width"] + 8,
                                                 button_y - MSG_FORWARD_BUTTON_SIZE[1] // 2)
                        forward.draw(surface)
                        self.forward_button_rects.append((forward.rect.clip(rect), msg["forward_source"]))
                current_y -= 15

    def exit_screen(self):
        self.save_current_draft()
        super().exit_screen()
