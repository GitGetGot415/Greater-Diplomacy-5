import pygame
from ui.navigation.screen import Screen
import data.constants as c
from ui.bars import ui_bars
from ui.widgets import text_utils
from ui.widgets import ui_elements
from ui.widgets.ui_elements import Button, process_text_input
from ui.rendering.font_manager import fonts
from map_logic.diplomacy import diplomacy_messages, diplomacy_processor, volunteers
from data import queries
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
MSG_CONTACT_ROW_GAP = 2
MSG_QUEUE_W = 112
MSG_CONTROL_GAP = 12
MSG_HEADER_BUTTON_H = 36
MSG_HEADER_BUTTON_Y = (MSG_HEADER_H - MSG_HEADER_BUTTON_H) // 2
MSG_HEADER_TRADE_W = 116
MSG_HEADER_UNREAD_W = 146
MSG_CONTACT_TOOLBAR_Y = MSG_HEADER_H + MSG_HEADER_BUTTON_Y

# Fixed controls stay above the scrollable conversation rows.
MSG_CONTACT_LIST_TOP_Y = 128

# Diplomacy buttons sit in a row above the compose box.
MSG_DIPLO_BTN_ROW_OFFSET_Y = -MSG_REQUEST_H + 7
MSG_DIPLO_BTN_START_X = MSG_LEFT_PANE_W + 20
MSG_DIPLO_BTN_STEP_X = 220

MSG_BG_DARK = (25, 25, 30)
MSG_BUBBLE_PLAYER = (42, 77, 119)
MSG_BUBBLE_AI = (47, 52, 65)
MSG_DIPLO_ACCENT = (208, 162, 76)
MSG_SELECTED_ACCENT = (112, 181, 242)
MSG_PANEL_BORDER = (13, 17, 24)
MSG_CONTACT_COLOR = (36, 43, 55)
MSG_CONTACT_HOVER = (47, 57, 72)
MSG_CONTACT_SELECTED = (39, 69, 101)
MSG_BUBBLE_FORWARDED = (65, 105, 75)
MSG_BUBBLE_MAX_WIDTH_RATIO = 0.6
MSG_FORWARD_BUTTON_SIZE = (82, 24)


class ConversationRow(Button):
    """A conversation row with cached text and the shared button input behavior."""

    def __init__(self, x, y, width, name, preview, unread, selected, callback):
        super().__init__(x, y, (width, MSG_CONTACT_ROW_H), "grey", name, callback,
                         sound_kind="select_category")
        self.is_selected = selected
        self.set_colors(MSG_CONTACT_SELECTED if selected else MSG_CONTACT_COLOR,
                        MSG_CONTACT_HOVER if not selected else (48, 83, 120))
        name_font = fonts.get_size(18, bold=bool(unread))
        preview_font = fonts.get("small")
        badge_font = fonts.get("tiny")
        self.badge = badge_font.render(str(unread), True, (255, 255, 255)) if unread else None
        self.badge_width = max(24, self.badge.get_width() + 12) if self.badge else 0
        text_width = width - 32 - (self.badge_width + 8 if unread else 0)
        self.name_surface = name_font.render(text_utils.fit_text(name, name_font, text_width), True, (241, 245, 250))
        self.preview_surface = preview_font.render(
            text_utils.fit_text(preview, preview_font, width - 32), True, (174, 185, 200))

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
        surface.blit(self.name_surface, (self.rect.x + 16, self.rect.y + 10))
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
        self.processed_messages = []
        self.compose_surface = None
        self.compose_enabled = False

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
        self.refresh_ui()

    @property
    def text_input_active(self):
        """The compose bar accepts keystrokes whenever a conversation is open."""
        return self.selected_recipient is not None

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
        """Auto-saves whatever is currently typed or queued before switching menus/contacts."""
        if self.selected_recipient and self.map_screen:
            p_data = self.map_screen.nation_data[self.map_screen.player_country]
            pending_dict = diplomacy_messages.get_pending_map(self.map_screen.nation_data, self.map_screen.player_country, writable=True)
            draft_lists = p_data.setdefault("draft_lists", {}) # Isolate the array from the engine
            
            if self.compose_text.strip():
                self.drafts.append(self.compose_text.strip())
                self.compose_text = ""
                
            existing = pending_dict.get(self.selected_recipient, {})

            if existing.get("turns", 0) > 0 and existing.get("action", "").startswith("MSG:"):
                # Keep the sent message and its reply reference while saving local text drafts.
                if self.drafts:
                    draft_lists[self.selected_recipient] = self.drafts.copy()
                else:
                    draft_lists.pop(self.selected_recipient, None)
                return

            action_str = ""
            existing_action = existing.get("action") or ""

            # Preserve existing formal diplomatic actions if they exist
            if existing_action and not existing_action.startswith("MSG:"):
                action_str = existing_action

            # Rebuild from the original entry so fields this screen doesn't care
            # about (timer, cached_members) survive a trip through the compose box.
            def _rebuild(action, message):
                entry = dict(existing)
                entry["action"] = action
                entry["turns"] = existing.get("turns", 0)
                entry["message"] = message
                return entry

            if self.drafts:
                # Use a newline character so the renderer knows to split them back into multiple bubbles later
                combined_text = "\n".join(self.drafts)
                if action_str:
                    pending_dict[self.selected_recipient] = _rebuild(action_str, existing.get("message", ""))
                else:
                    pending_dict[self.selected_recipient] = _rebuild(f"MSG:{combined_text}", combined_text)
                draft_lists[self.selected_recipient] = self.drafts.copy()
            else:
                # No drafts. Preserve formal actions.
                if action_str:
                    pending_dict[self.selected_recipient] = _rebuild(action_str, existing.get("message", ""))
                else:
                    diplomacy_messages.cancel_text_message(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)

                if self.selected_recipient in draft_lists:
                    del draft_lists[self.selected_recipient]

    def select_recipient(self, target):
        self.save_current_draft()
        
        if self.selected_recipient == target:
            self.selected_recipient = None
            self.compose_text = ""
            self.drafts = []
            self.refresh_ui()
            return
        
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
        self.refresh_ui()

    def toggle_add_contact(self):
        self.show_all_contacts = not self.show_all_contacts
        self.contact_scroll_y = 0
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
        self.elements = [Button(MSG_MARGIN, MSG_HEADER_BUTTON_Y, (70, MSG_HEADER_BUTTON_H), "red", "Exit", self.exit_screen,
                                font_preset="button_small", sound_kind="back")]
        self.elements.append(Button(94, MSG_HEADER_BUTTON_Y, (170, MSG_HEADER_BUTTON_H), "grey", "Mark All Read", self.mark_all_read,
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
        header = queries.get_country_display_name(self.selected_recipient, self.map_screen.nation_data) if self.selected_recipient else "Messages"
        header_font = fonts.get("heading2")
        header_width = trade_x - MSG_LEFT_PANE_W - 2 * MSG_MARGIN
        self.header_surface = header_font.render(text_utils.fit_text(header, header_font, header_width), True, (241, 245, 250))
        self.sidebar_title_surface = fonts.get("normal").render("Messages", True, (220, 229, 240))
        self.empty_thread_surface = header_font.render("Select a nation to view communications.", True, c.UI_TEXT_MUTED)
        
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
            self.elements.append(Button(132, MSG_CONTACT_TOOLBAR_Y, (132, MSG_HEADER_BUTTON_H), "blue", "+ Add Contact", self.toggle_add_contact,
                                        font_preset="button_small"))
            display_list = [n for n in playable if n in history_contacts]
        previews = {}
        unread_counts = {}
        for message in inbox:
            sender = message.get("sender", "")
            outgoing = sender.startswith("To: ")
            country = sender[4:] if outgoing else sender
            previews.setdefault(country, ("You: " if outgoing else "") + " ".join(message.get("content", "").split()))
            if not outgoing and not message.get("read", False):
                unread_counts[country] = unread_counts.get(country, 0) + 1

        row_step = MSG_CONTACT_ROW_H + MSG_CONTACT_ROW_GAP
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
                                  lambda target=country, select=callback: select(target))
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
        unread_button = Button(unread_x, MSG_HEADER_BUTTON_Y, (MSG_HEADER_UNREAD_W, MSG_HEADER_BUTTON_H), "grey",
                               "Mark Unread", self.mark_thread_unread, font_preset="button_small")
        unread_button.disabled = not self.selected_recipient
        self.elements.append(unread_button)
        # Integrated puppets used to be barred from trading with anyone but
        # their master. They trade like anyone else now.
        trade_button = Button(trade_x, MSG_HEADER_BUTTON_Y, (MSG_HEADER_TRADE_W, MSG_HEADER_BUTTON_H), "grey", "Trade", self.open_trade,
                              font_preset="button_small")
        trade_button.disabled = not self.selected_recipient or is_tactical
        self.elements.append(trade_button)

        if self.selected_recipient:
            # --- Ratifying a treaty our faction leader signed for us ---
            # Its own channel, not pending_diplomacy -- a leader asking four
            # members at once would otherwise clobber four unrelated offers --
            # so it needs its own pair of buttons rather than riding the
            # Accept/Reject ones below.
            if self._offer_ratification_buttons():
                return

            # --- Bilateral Accept/Reject Buttons ---
            # An answer never competes with our own outgoing offer any more, so
            # there is no "busy" state to grey these out for.
            incoming_action, incoming_turns = queries.get_diplomatic_status(self.selected_recipient, self.map_screen.player_country, self.map_screen.nation_data)
            queued_verdict, queued_action = diplomacy_messages.get_response_status(
                self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)

            if incoming_turns > 0 and incoming_action in c.BILATERAL_ACTIONS:
                action_name = incoming_action.replace("_", " ").title()
                answered = (queued_action == incoming_action)

                is_peace = incoming_action in ["PEACE_TREATY", "CEASEFIRE"]
                is_trade = incoming_action == "TRADE"
                is_viewable_deal = is_peace or is_trade

                def _view_deal_btn(slot):
                    label = "View Peace Treaty" if is_peace else "View Trade Deal"
                    callback = self.view_peace_treaty if is_peace else self.view_trade_deal
                    return self._reply_button(slot, "yellow", label, lambda: callback(self.selected_recipient))

                if is_tactical:
                    for slot, label in enumerate((f"Accept {action_name}", f"Reject {action_name}")):
                        self.elements.append(self._reply_button(slot, "grey", label, lambda: None, enabled=False))
                    if is_viewable_deal:
                        self.elements.append(_view_deal_btn(2))
                elif answered and queued_verdict == diplomacy_messages.RESPONSE_ACCEPT:
                    self.elements.append(self._reply_button(0, "green", "Undo Accept", lambda: self.accept_proposal(self.selected_recipient)))
                elif answered and queued_verdict == diplomacy_messages.RESPONSE_REJECT:
                    self.elements.append(self._reply_button(0, "red", "Undo Reject", lambda: self.reject_proposal(self.selected_recipient)))
                else:
                    self.elements.append(self._reply_button(0, "green", f"Accept {action_name}", lambda: self.accept_proposal(self.selected_recipient)))
                    self.elements.append(self._reply_button(1, "red", f"Reject {action_name}", lambda: self.reject_proposal(self.selected_recipient)))
                    if is_viewable_deal:
                        self.elements.append(_view_deal_btn(2))

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

        if verdict == ratification.RATIFY:
            label, color = "Ratified (undo)", "green"
        elif verdict == ratification.REFUSE:
            label, color = "Refused (undo)", "red"
        else:
            self.elements.append(self._reply_button(0, "green", "Ratify Treaty",
                                                    lambda: self.answer_ratification(True), enabled=editable))
            self.elements.append(self._reply_button(1, "red", "Refuse & Leave Faction",
                                                    lambda: self.answer_ratification(False), enabled=editable))
            self.elements.append(self._reply_button(2, "yellow", "View Treaty",
                                                    lambda: self.view_peace_treaty(self.selected_recipient)))
            return True

        self.elements.append(self._reply_button(0, color, label, self.clear_ratification, enabled=editable))
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
            ui_elements.draw_pixel_panel(cached, bubble, color, border, gradient_strength=0.25)
            if msg["is_diplo"]:
                pygame.draw.rect(cached, MSG_DIPLO_ACCENT, (2, header_h + 2, 3, bubble_h - 4))
            for index, line in enumerate(lines):
                cached.blit(font_small.render(line, True, (242, 245, 250)), (15, header_h + 10 + index * line_height))
            forward = None
            if msg["forward_source"] and not self.map_screen.tactical_mode:
                forward = Button(0, 0, MSG_FORWARD_BUTTON_SIZE, "grey", "Forward", lambda: None, font_preset="tiny")
            self.processed_messages.append({"msg_data": msg, "surface": cached,
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

    def _draw_panel(self, surface, rect, name):
        style = MESSAGE_PANEL_STYLES[name]
        ui_elements.draw_pixel_panel(surface, rect, style["color"], MSG_PANEL_BORDER,
                                     gradient_strength=style["gradient_strength"])

    def additional_draw(self, surface):
        if not self.map_screen:
            return
        self._draw_panel(surface, pygame.Rect(0, 0, MSG_LEFT_PANE_W, c.SCREEN_HEIGHT), "contacts")
        self._draw_panel(surface, pygame.Rect(0, 0, MSG_LEFT_PANE_W, MSG_HEADER_H), "header")
        self._draw_panel(surface, pygame.Rect(MSG_LEFT_PANE_W, 0, c.SCREEN_WIDTH - MSG_LEFT_PANE_W, MSG_HEADER_H), "header")
        sidebar_title_y = MSG_CONTACT_TOOLBAR_Y + (MSG_HEADER_BUTTON_H - self.sidebar_title_surface.get_height()) // 2
        surface.blit(self.sidebar_title_surface, (MSG_MARGIN, sidebar_title_y))
        surface.blit(self.header_surface, (MSG_LEFT_PANE_W + MSG_MARGIN, (MSG_HEADER_H - self.header_surface.get_height()) // 2))
        self.draw_list_scrollbar(surface, MSG_LEFT_PANE_W - 20, MSG_CONTACT_LIST_TOP_Y,
                                 self.scroll_content_rect.height, width=10,
                                 attr="contact_scroll_y", limit_attr="max_contact_scroll",
                                 track_attr="contact_scroll_track_rect", handle_attr="contact_scroll_handle_rect")
        request_rect = pygame.Rect(MSG_LEFT_PANE_W, self.thread_rect.bottom,
                                    self.thread_rect.width, MSG_REQUEST_H)
        self._draw_panel(surface, request_rect, "requests")
        composer_rect = pygame.Rect(MSG_LEFT_PANE_W, request_rect.bottom,
                                     self.thread_rect.width, MSG_INPUT_H)
        self._draw_panel(surface, composer_rect, "composer")
        ui_elements.draw_text_input_background(surface, self.input_rect, active=self.compose_enabled,
                                               style_name="message",
                                               border_color=MSG_SELECTED_ACCENT if self.compose_enabled else (80, 90, 106))
        text_rect = self.input_rect.inflate(-24, -12)
        with ui_bars.clip_scroll_region(surface, text_rect, draw_top=False, draw_bottom=False):
            x = text_rect.x - max(0, self.compose_surface.get_width() - text_rect.width)
            surface.blit(self.compose_surface, (x, text_rect.centery - self.compose_surface.get_height() // 2))
        if not self.selected_recipient:
            surface.blit(self.empty_thread_surface, self.empty_thread_surface.get_rect(center=self.thread_rect.center))
        current_y = self.thread_rect.bottom - 20 + self.msg_scroll_y
        self.draft_edit_rects = []
        self.forward_button_rects = []
        with ui_bars.clip_scroll_region(surface, self.thread_rect,
                                        draw_top=self.msg_scroll_y < self.max_msg_scroll, draw_bottom=self.msg_scroll_y != 0):
            for prepared in self.processed_messages:
                current_y -= prepared["box_height"]
                msg = prepared["msg_data"]
                if current_y + prepared["box_height"] >= self.thread_rect.top and current_y < self.thread_rect.bottom:
                    x = (self.thread_rect.right - prepared["box_width"] - 30 if msg["is_player"]
                         else self.thread_rect.left + 30)
                    surface.blit(prepared["surface"], (x, current_y))
                    button_y = current_y + prepared["header_h"] + prepared["bubble_h"] // 2
                    if msg["is_draft"] and not self.map_screen.tactical_mode:
                        delete_rect = pygame.Rect(x - 35, button_y - 12, 25, 25)
                        self.draft_edit_rects.append((delete_rect.clip(self.thread_rect), msg["draft_idx"]))
                        ui_elements.draw_pixel_button(surface, delete_rect, (130, 48, 48))
                        surface.blit(self.delete_label, self.delete_label.get_rect(center=delete_rect.center))
                    forward = prepared["forward_button"]
                    if forward:
                        forward.rect.topleft = (x + prepared["box_width"] + 8,
                                                 button_y - MSG_FORWARD_BUTTON_SIZE[1] // 2)
                        forward.draw(surface)
                        self.forward_button_rects.append((forward.rect.clip(self.thread_rect), msg["forward_source"]))
                current_y -= 15

    def exit_screen(self):
        self.save_current_draft()
        super().exit_screen()
