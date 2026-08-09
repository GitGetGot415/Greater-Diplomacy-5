import pygame
from gameState import GameState
import data.constants as c
from ui.bars import ui_bars
from ui import text_utils
from ui_elements import Button, process_text_input
from map_logic.rendering.font_manager import fonts
from map_logic.diplomacy import diplomacy_logic, diplomacy_messages
from data import queries

# ==========================================
# LAYOUT
# ==========================================

MSG_LEFT_PANE_W = 280
MSG_INPUT_H = 80

# Top of the scrollable contact list. Pushed down from the header row to make
# room for the fixed Exit / Mark All Read buttons above it.
MSG_CONTACT_LIST_TOP_Y = 120

# Diplomacy buttons sit in a row above the compose box.
MSG_DIPLO_BTN_ROW_OFFSET_Y = -60
MSG_DIPLO_BTN_START_X = MSG_LEFT_PANE_W + 20
MSG_DIPLO_BTN_STEP_X = 220

MSG_BG_DARK = (25, 25, 30)
MSG_BG_LIGHT = (35, 35, 45)
MSG_BUBBLE_PLAYER = (40, 100, 200)
MSG_BUBBLE_PLAYER_DIPLO = (180, 60, 60) # Player diplomatic red
MSG_BUBBLE_AI = (60, 60, 80)
MSG_BUBBLE_AI_DIPLO = (200, 100, 0) # AI diplomatic orange
MSG_BUBBLE_MAX_WIDTH_RATIO = 0.6


class Messages_Screen(GameState):
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
        # newest message, growing as you scroll back), unlike GameState's
        # scroll_y which is a negative offset. Kept under its own name so
        # the two never share an attribute -- the contact list beside it
        # does use the base class's helpers, on the base convention.
        self.msg_scroll_y = 0
        self.max_msg_scroll = 0
        
        self.contact_scroll_y = 0
        self.max_contact_scroll = 0
        self.is_dragging_contacts = False
        self.is_dragging_messages = False # Tracks dragging inside the message pane
        
        self.show_all_contacts = False

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
        self.is_dragging_messages = False
        self.show_all_contacts = False
        self.refresh_ui()

    def accept_proposal(self, target):
        from map_logic.diplomacy import player_diplomacy_actions
        custom_msg = self.compose_text.strip()
        player_diplomacy_actions.handle_accept_req(self.map_screen, target, custom_msg)
        self.compose_text = ""
        self.refresh_ui()

    def reject_proposal(self, target):
        from map_logic.diplomacy import player_diplomacy_actions
        custom_msg = self.compose_text.strip()
        player_diplomacy_actions.handle_reject_req(self.map_screen, target, custom_msg)
        self.compose_text = ""
        self.refresh_ui()

    def view_peace_treaty(self, target):
        self.save_current_draft()
        from ui.player_diplomacy_menus import open_view_peace_treaty_menu
        open_view_peace_treaty_menu(self.map_screen, target)
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
            if not isinstance(existing, dict):
                # Legacy saves stored a bare action string
                existing = {"action": existing, "turns": 0}

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
                    diplomacy_logic.cancel_text_message(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)

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
        if self.selected_recipient:
            if self.compose_text.strip():
                self.drafts.append(self.compose_text.strip())
                self.compose_text = ""
                self.map_screen.show_feedback("Message queued.")
            
            self.save_current_draft()
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
        mx, my = pygame.mouse.get_pos()
        is_tactical = self.map_screen.tactical_mode
        
        # --- Handle Draft Delete Clicks ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Guarded to the visible message pane so a delete box scrolled
            # behind the compose box (clipped, no longer drawn) can't fire.
            if hasattr(self, 'draft_edit_rects') and not is_tactical and my < c.SCREEN_HEIGHT - MSG_INPUT_H:
                for del_rect, idx in self.draft_edit_rects:
                    if del_rect.collidepoint(mx, my):
                        
                        # HANDLE DIPLOMATIC ACTION UNDO CLICKS
                        if idx == "TRADE_OFFER":
                            # Passing it to the toggle logic safely refunds the escrow!
                            diplomacy_logic.toggle_diplomacy_action(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient, "TRADE", "")
                            self.map_screen.show_feedback("Trade Offer Cancelled.")
                        elif idx == "WAR_DECLARATION":
                            diplomacy_messages.clear_pending(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)
                            self.map_screen.show_feedback("War Declaration Cancelled.")
                        elif isinstance(idx, str) and idx.startswith("FORMAL_"):
                            act_name = idx[7:]
                            diplomacy_messages.clear_pending(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)
                            self.map_screen.show_feedback(f"{act_name.replace('_', ' ').title()} Cancelled.")
                        else:
                            if isinstance(idx, int) and 0 <= idx < len(self.drafts):
                                self.drafts.pop(idx)
                                self.save_current_draft()
                            
                        self.refresh_ui()
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
        if event.type == pygame.MOUSEWHEEL and mx >= MSG_LEFT_PANE_W:
            self.msg_scroll_y += event.y * 40
            self.msg_scroll_y = max(0, min(self.msg_scroll_y, self.max_msg_scroll))

        # --- Drag to Scroll Logic (message thread only) ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.selected_recipient and mx >= MSG_LEFT_PANE_W and my < c.SCREEN_HEIGHT - MSG_INPUT_H:
                # Ensure we aren't dragging when we're actually trying to click 'Delete Draft'
                clicked_del = False
                if hasattr(self, 'draft_edit_rects'):
                    for del_rect, _ in self.draft_edit_rects:
                        if del_rect.collidepoint(mx, my):
                            clicked_del = True
                            break
                if not clicked_del:
                    self.is_dragging_messages = True

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.is_dragging_messages = False

        elif event.type == pygame.MOUSEMOTION:
            if self.is_dragging_messages:
                self.msg_scroll_y -= event.rel[1] # Subtract so dragging down pulls up newer messages
                self.msg_scroll_y = max(0, min(self.msg_scroll_y, self.max_msg_scroll))
                
        # --- Text Input Logic ---
        if self.selected_recipient:
            locked = queries.is_diplomat_busy(self.map_screen.player_country, self.selected_recipient, self.map_screen.nation_data)
            if not locked and not is_tactical:
                self.compose_text, status = process_text_input(event, self.compose_text, max_length=c.MAX_MESSAGE_LENGTH)
                if status == "SUBMIT":
                    self.send_message()

    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Exit", self.exit_screen)]
        self.elements.append(Button(20, 70, "small", "blue", "Mark All Read", self.mark_all_read))
        if self.selected_recipient:
            self.elements.append(Button(130, 20, "small", "orange", "Mark Unread", self.mark_thread_unread))

        if not self.map_screen: return
        
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

        y_off = MSG_CONTACT_LIST_TOP_Y + self.contact_scroll_y
        self.scroll_content_rect = pygame.Rect(0, MSG_CONTACT_LIST_TOP_Y, MSG_LEFT_PANE_W, c.SCREEN_HEIGHT - MSG_CONTACT_LIST_TOP_Y)

        if self.show_all_contacts:
            btn = Button(20, y_off, "medium", "red", "Cancel", self.toggle_add_contact)
            btn.is_scrollable = True
            self.elements.append(btn)
            y_off += 60

            display_list = [n for n in playable if n not in history_contacts]
            for country in display_list:
                display_name = self.map_screen.nation_data.get(country, {}).get("name", country)
                btn = Button(20, y_off, "medium", "grey", display_name, lambda c_name=country: self.select_new_contact(c_name))
                btn.is_scrollable = True
                self.elements.append(btn)
                y_off += 60
        else:
            btn = Button(20, y_off, "medium", "blue", "+ Add Contact", self.toggle_add_contact)
            btn.is_scrollable = True
            self.elements.append(btn)
            y_off += 60

            display_list = [n for n in playable if n in history_contacts]
            for country in display_list:
                color = "green" if self.selected_recipient == country else "grey"

                unread = sum(1 for m in p_data.get("inbox", []) if m.get("sender") == country and not m.get("read", False))

                # Treat unanswered requests as an unread notification. Shares its
                # rule with the map screen's badge so the two always agree.
                if queries.has_unanswered_request(self.map_screen.player_country, country, self.map_screen.nation_data):
                    unread += 1

                display_name = self.map_screen.nation_data.get(country, {}).get("name", country)
                display_text = f"{display_name} ({unread})" if unread > 0 else display_name
                if unread > 0 and self.selected_recipient != country:
                    color = "red"

                btn = Button(20, y_off, "medium", color, display_text, lambda c_name=country: self.select_recipient(c_name))
                btn.is_scrollable = True
                self.elements.append(btn)
                y_off += 60

        absolute_height = y_off - self.contact_scroll_y
        self.max_contact_scroll = min(0, c.SCREEN_HEIGHT - absolute_height - 20)

        if self.selected_recipient:
            is_tactical = self.map_screen.tactical_mode
            btn_x = c.SCREEN_WIDTH - 150
            btn_y = c.SCREEN_HEIGHT - MSG_INPUT_H + 15
            
            if is_tactical:
                self.elements.append(Button(btn_x, btn_y, "small", "grey", "Tactical: Read Only", lambda: None))
            else:
                self.elements.append(Button(btn_x, btn_y, "small", "blue", "Queue", self.send_message))
                
            is_puppet = bool(p_data.get("master", ""))
            target_is_puppet = bool(self.map_screen.nation_data.get(self.selected_recipient, {}).get("master", ""))
            
            my_type = p_data.get("puppet_type", "")
            target_type = self.map_screen.nation_data.get(self.selected_recipient, {}).get("puppet_type", "")

            my_master = p_data.get("master", "")
            target_master = self.map_screen.nation_data.get(self.selected_recipient, {}).get("master", "")

            is_my_integrated = is_puppet and my_type == c.PUPPET_TYPE_INTEGRATED and my_master != self.selected_recipient
            is_target_integrated = target_is_puppet and target_type == c.PUPPET_TYPE_INTEGRATED and target_master != self.map_screen.player_country

            if is_my_integrated:
                btn_trade = Button(btn_x - 130, btn_y, "small", "grey", "Integrated Can't Trade", lambda: None)
                btn_trade.disabled = True
                self.elements.append(btn_trade)
            elif is_target_integrated:
                btn_trade = Button(btn_x - 130, btn_y, "small", "grey", "Target is Integrated", lambda: None)
                btn_trade.disabled = True
                self.elements.append(btn_trade)
            elif is_tactical:
                btn_trade = Button(btn_x - 130, btn_y, "small", "grey", "Tactical: Read Only", lambda: None)
                btn_trade.disabled = True
                self.elements.append(btn_trade)
            else:
                self.elements.append(Button(btn_x - 130, btn_y, "small", "green", "Trade", self.open_trade))

            # --- Bilateral Accept/Reject Buttons ---
            # An answer never competes with our own outgoing offer any more, so
            # there is no "busy" state to grey these out for.
            incoming_action, incoming_turns = queries.get_diplomatic_status(self.selected_recipient, self.map_screen.player_country, self.map_screen.nation_data)
            queued_verdict, queued_action = diplomacy_messages.get_response_status(
                self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)

            if incoming_turns > 0 and incoming_action in c.BILATERAL_ACTIONS:
                action_name = incoming_action.replace("_", " ").title()
                btn_y_diplo = c.SCREEN_HEIGHT - MSG_INPUT_H + MSG_DIPLO_BTN_ROW_OFFSET_Y
                answered = (queued_action == incoming_action)

                is_peace = incoming_action in ["PEACE_TREATY", "CEASEFIRE"]

                def _peace_btn(slot):
                    return Button(MSG_DIPLO_BTN_START_X + MSG_DIPLO_BTN_STEP_X * slot, btn_y_diplo,
                                  "medium", "yellow", "View Peace Treaty",
                                  lambda: self.view_peace_treaty(self.selected_recipient))

                if is_tactical:
                    self.elements.append(Button(MSG_DIPLO_BTN_START_X, btn_y_diplo, "medium", "grey", "Tactical: Read Only", lambda: None))
                    self.elements.append(Button(MSG_DIPLO_BTN_START_X + MSG_DIPLO_BTN_STEP_X, btn_y_diplo, "medium", "grey", "Tactical: Read Only", lambda: None))
                    if is_peace:
                        self.elements.append(_peace_btn(2))
                elif answered and queued_verdict == diplomacy_messages.RESPONSE_ACCEPT:
                    self.elements.append(Button(MSG_DIPLO_BTN_START_X, btn_y_diplo, "medium", "green", "Undo Accept", lambda: self.accept_proposal(self.selected_recipient)))
                elif answered and queued_verdict == diplomacy_messages.RESPONSE_REJECT:
                    self.elements.append(Button(MSG_DIPLO_BTN_START_X, btn_y_diplo, "medium", "red", "Undo Reject", lambda: self.reject_proposal(self.selected_recipient)))
                else:
                    self.elements.append(Button(MSG_DIPLO_BTN_START_X, btn_y_diplo, "medium", "green", f"Accept {action_name}", lambda: self.accept_proposal(self.selected_recipient)))
                    self.elements.append(Button(MSG_DIPLO_BTN_START_X + MSG_DIPLO_BTN_STEP_X, btn_y_diplo, "medium", "red", f"Reject {action_name}", lambda: self.reject_proposal(self.selected_recipient)))
                    if is_peace:
                        self.elements.append(_peace_btn(2))

    def open_trade(self):
        self.save_current_draft()
        from ui.player_diplomacy_menus import open_trade_menu
        open_trade_menu(self.map_screen, self.selected_recipient)
        self.refresh_ui()

    def additional_draw(self, surface):
        if not self.map_screen: return
        font_med = fonts.get("heading2")
        font_small = fonts.get("normal")
        font_tiny = fonts.get("tiny")

        left_pane_rect = pygame.Rect(0, 0, MSG_LEFT_PANE_W, c.SCREEN_HEIGHT)
        pygame.draw.rect(surface, MSG_BG_LIGHT, left_pane_rect)
        pygame.draw.line(surface, (100, 100, 100), (MSG_LEFT_PANE_W, 0), (MSG_LEFT_PANE_W, c.SCREEN_HEIGHT), 2)

        self.draw_list_scrollbar(surface, MSG_LEFT_PANE_W - 20, MSG_CONTACT_LIST_TOP_Y, c.SCREEN_HEIGHT - MSG_CONTACT_LIST_TOP_Y, width=10,
                                 attr="contact_scroll_y", limit_attr="max_contact_scroll",
                                 track_attr="contact_scroll_track_rect", handle_attr="contact_scroll_handle_rect")

        if not self.selected_recipient:
            txt = font_med.render("Select a nation to view communications.", True, c.UI_TEXT_MUTED)
            surface.blit(txt, (MSG_LEFT_PANE_W + 50, c.SCREEN_HEIGHT // 2))
            return

        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        inbox = p_data.get("inbox", [])
        
        display_thread = []
        
        # 1. Build thread with historical messages (reversed so oldest is at index 0)
        for msg in reversed(inbox):
            if msg.get("sender") == self.selected_recipient or msg.get("sender") == f"To: {self.selected_recipient}":
                # Detect newlines and split them back into multiple visual bubbles automatically
                lines_split = [t for t in msg["content"].split("\n") if t.strip()]
                for idx, sub_text in enumerate(lines_split):
                    # Only append the date to the first bubble if it's a split message
                    show_date = msg.get("date", "") if idx == 0 else ""
                    
                    display_thread.append({
                        "content": sub_text, 
                        "is_player": msg["sender"].startswith("To: "), 
                        "is_draft": False,
                        "is_diplo": msg.get("type") == "DIPLOMACY",
                        "date": show_date
                    })
                        
        # Check if there is an active diplomatic action pending for this target
        pending = diplomacy_messages.get_pending(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)
        act_str = pending.get("action", "")
        is_diplo_action = bool(act_str) and not act_str.startswith("MSG:")

        # --- INJECT PENDING FORMAL ACTIONS AS VISUAL DRAFTS SO THEY CAN BE CANCELED ---
        if is_diplo_action and pending.get("turns", 0) == 0:
            if act_str == "TRADE":
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
                "date": ""
            })

        # --- INJECT TEXT DRAFTS AS VISUAL DRAFTS SO THEY CAN BE CANCELED ---
        for idx, draft_text in enumerate(self.drafts):
            display_thread.append({
                "content": draft_text,
                "is_player": True,
                "is_draft": True,
                "draft_idx": idx,
                "is_diplo": False,
                "date": ""
            })
        
        input_rect = pygame.Rect(MSG_LEFT_PANE_W, c.SCREEN_HEIGHT - MSG_INPUT_H, c.SCREEN_WIDTH - MSG_LEFT_PANE_W, MSG_INPUT_H)
        pygame.draw.rect(surface, MSG_BG_LIGHT, input_rect)
        pygame.draw.line(surface, (100, 100, 100), (MSG_LEFT_PANE_W, input_rect.y), (c.SCREEN_WIDTH, input_rect.y), 2)

        txt_surf = font_small.render(self.compose_text + "|", True, (255, 255, 255))
        surface.blit(txt_surf, (input_rect.x + 20, input_rect.y + 30))

        # --- PRE-CALCULATE SIZES TO ESTABLISH MAX SCROLL CEILING ---
        processed_messages = []
        total_h = 20
        max_width = int((c.SCREEN_WIDTH - MSG_LEFT_PANE_W) * MSG_BUBBLE_MAX_WIDTH_RATIO)

        for msg in reversed(display_thread):
            lines = text_utils.wrap_text(msg['content'], font_small, max_width)

            box_height = 20 + (len(lines) * 20)
            if msg.get("date"):
                box_height += 25 # Reserve space above the bubble for the date
                
            box_width = max([font_small.size(l)[0] for l in lines] + [100]) + 30
            total_h += box_height + 15

            processed_messages.append({
                "msg_data": msg,
                "lines": lines,
                "box_height": box_height,
                "box_width": box_width
            })

        # --- DYNAMIC PADDING ---
        # Push the chat thread higher up if we need room for the Accept/Reject buttons
        incoming_action, incoming_turns = queries.get_diplomatic_status(self.selected_recipient, self.map_screen.player_country, self.map_screen.nation_data)
        has_bilateral = (incoming_turns > 0 and incoming_action in c.BILATERAL_ACTIONS)
        bottom_padding = 80 if has_bilateral else 20

        self.max_msg_scroll = max(0, total_h - input_rect.y + bottom_padding)
        self.msg_scroll_y = max(0, min(self.msg_scroll_y, self.max_msg_scroll))

        current_y = input_rect.y - bottom_padding + self.msg_scroll_y
        self.draft_edit_rects = []
        
        msg_pane_rect = pygame.Rect(MSG_LEFT_PANE_W, 0, c.SCREEN_WIDTH - MSG_LEFT_PANE_W, input_rect.y)
        with ui_bars.clip_scroll_region(surface, msg_pane_rect,
                                        draw_top=self.msg_scroll_y < self.max_msg_scroll, draw_bottom=self.msg_scroll_y != 0):
            # Render iterating backwards (Newest -> Oldest), drawing bottom -> up
            for p_msg in processed_messages:
                msg = p_msg["msg_data"]
                lines = p_msg["lines"]
                box_height = p_msg["box_height"]
                box_width = p_msg["box_width"]

                current_y -= box_height
            
                # Culling check - don't draw boxes rendering completely off the top or bottom of the screen
                if current_y + box_height < 0 or current_y > c.SCREEN_HEIGHT:
                    current_y -= 15
                    continue 

                is_player = msg['is_player']
                is_draft = msg.get('is_draft', False)
                is_diplo = msg.get('is_diplo', False)
                date_str = msg.get("date", "")

                draw_y = current_y
            
                # --- Render Date Header ---
                if date_str:
                    date_surf = font_tiny.render(date_str, True, (130, 130, 150))
                    if is_player:
                        surface.blit(date_surf, (c.SCREEN_WIDTH - date_surf.get_width() - 30, draw_y))
                    else:
                        surface.blit(date_surf, (MSG_LEFT_PANE_W + 30, draw_y))
                    draw_y += 20 # Push the physical bubble down 20px so it sits under the text

                # Only color the physical bubble, excluding the space we reserved for the date
                bubble_h = box_height - (25 if date_str else 0)

                if is_player:
                    box_x = c.SCREEN_WIDTH - box_width - 30
                    color = MSG_BUBBLE_PLAYER_DIPLO if is_diplo else MSG_BUBBLE_PLAYER
                
                    if is_draft:
                        del_rect = pygame.Rect(box_x - 35, draw_y + bubble_h//2 - 12, 25, 25)
                        self.draft_edit_rects.append((del_rect, msg['draft_idx']))
                    
                        if not self.map_screen.tactical_mode:
                            pygame.draw.rect(surface, (150, 0, 0), del_rect, border_radius=5)
                            surface.blit(font_small.render("X", True, (255, 255, 255)), (del_rect.x + 7, del_rect.y + 2))
                else:
                    box_x = MSG_LEFT_PANE_W + 30
                    color = MSG_BUBBLE_AI_DIPLO if is_diplo else MSG_BUBBLE_AI

                bubble_rect = pygame.Rect(box_x, draw_y, box_width, bubble_h)
                pygame.draw.rect(surface, color, bubble_rect, border_radius=10)
            
                if is_draft:
                    pygame.draw.rect(surface, c.COLOR_GOLD_HIGHLIGHT, bubble_rect, 2, border_radius=10)
            
                ly = draw_y + 10
                for l in lines:
                    surface.blit(font_small.render(l, True, (255, 255, 255)), (box_x + 15, ly))
                    ly += 20
                
                current_y -= 15 

    def exit_screen(self):
        self.save_current_draft()
        super().exit_screen()