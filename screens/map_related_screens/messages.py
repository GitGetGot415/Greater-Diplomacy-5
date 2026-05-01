import pygame
from gameState import GameState
import data.constants as c
from ui_elements import Button, process_text_input
from map_logic.rendering.font_manager import fonts
from map_logic.diplomacy import diplomacy_logic
from data import queries

class Messages_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = c.MSG_BG_DARK
        self.map_screen = None
        self.selected_recipient = None
        self.compose_text = ""
        self.drafts = [] 
        self.draft_edit_rects = []
        
        self.scroll_y = 0
        self.max_msg_scroll = 0 # Tracks how high we can scroll in the thread
        
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
        self.scroll_y = 0
        self.max_msg_scroll = 0
        self.contact_scroll_y = 0
        self.is_dragging_contacts = False
        self.is_dragging_messages = False
        self.show_all_contacts = False
        self.refresh_ui()

    def save_current_draft(self):
        """Auto-saves whatever is currently typed or queued before switching menus/contacts."""
        if self.selected_recipient and self.map_screen:
            p_data = self.map_screen.nation_data[self.map_screen.player_country]
            pending_dict = p_data.setdefault("pending_diplomacy", {})
            draft_lists = p_data.setdefault("draft_lists", {}) # Isolate the array from the engine
            
            if self.compose_text.strip():
                self.drafts.append(self.compose_text.strip())
                self.compose_text = ""
                
            existing = pending_dict.get(self.selected_recipient, {})
            action_str = ""
            turns_val = 0
            
            # Preserve existing formal diplomatic actions if they exist
            if isinstance(existing, dict):
                if existing.get("action") and not existing.get("action").startswith("MSG:"):
                    action_str = existing.get("action")
                    turns_val = existing.get("turns", 0)
            
            if self.drafts:
                # Use a newline character so the renderer knows to split them back into multiple bubbles later
                combined_text = "\n".join(self.drafts)
                if not action_str:
                    action_str = f"MSG:{combined_text}"
                    
                pending_dict[self.selected_recipient] = {
                    "action": action_str,
                    "turns": turns_val,
                    "message": combined_text
                }
                draft_lists[self.selected_recipient] = self.drafts.copy()
            else:
                # No drafts. If there's a formal action, just clear the message part.
                if action_str:
                    pending_dict[self.selected_recipient] = {
                        "action": action_str,
                        "turns": turns_val,
                        "message": ""
                    }
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
        self.scroll_y = 0
        
        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        for msg in p_data.get("inbox", []):
            if msg.get("sender") == target:
                msg["read"] = True
                
        # Load drafts and sync with the map screen
        draft_str = queries.get_message_draft(self.map_screen.player_country, target, self.map_screen.nation_data)
        draft_lists = p_data.get("draft_lists", {})
        saved_list = draft_lists.get(target, [])
        
        # Check if we have a saved draft list AND it matches the current text to prevent desyncs
        if saved_list and "\n".join(saved_list) == draft_str.strip():
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

    def additional_events(self, event):
        mx, my = pygame.mouse.get_pos()
        
        # --- Handle Draft Delete Clicks ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if hasattr(self, 'draft_edit_rects'):
                for del_rect, idx in self.draft_edit_rects:
                    if del_rect.collidepoint(mx, my):
                        self.drafts.pop(idx)
                        self.save_current_draft()
                        self.refresh_ui()
                        return

        # --- Scrolling Logic ---
        if event.type == pygame.MOUSEWHEEL:
            if mx < c.MSG_LEFT_PANE_W:
                self.contact_scroll_y += event.y * 30
                self.contact_scroll_y = max(self.max_contact_scroll, min(0, self.contact_scroll_y))
                self.refresh_ui() 
            else:
                self.scroll_y += event.y * 40
                self.scroll_y = max(0, min(self.scroll_y, self.max_msg_scroll))

        # --- Drag to Scroll Logic ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if mx < c.MSG_LEFT_PANE_W:
                self.is_dragging_contacts = True
            elif self.selected_recipient and my < c.SCREEN_HEIGHT - c.MSG_INPUT_H:
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
            self.is_dragging_contacts = False
            self.is_dragging_messages = False
            
        elif event.type == pygame.MOUSEMOTION:
            if getattr(self, 'is_dragging_contacts', False):
                self.contact_scroll_y += event.rel[1]
                self.contact_scroll_y = max(self.max_contact_scroll, min(0, self.contact_scroll_y))
                self.refresh_ui() 
            elif getattr(self, 'is_dragging_messages', False):
                self.scroll_y -= event.rel[1] # Subtract so dragging down pulls up newer messages
                self.scroll_y = max(0, min(self.scroll_y, self.max_msg_scroll))
                
        # --- Text Input Logic ---
        if self.selected_recipient:
            locked = queries.is_diplomat_busy(self.map_screen.player_country, self.selected_recipient, self.map_screen.nation_data)
            if not locked:
                self.compose_text, status = process_text_input(event, self.compose_text, max_length=150)
                if status == "SUBMIT":
                    self.send_message()

    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Exit", self.exit_to_map)]
        if not self.map_screen: return
        
        active_nations = set([prov.get("owner") for prov in self.map_screen.map_data.values() if prov.get("owner") not in c.UNPLAYABLE_NATIONS])
        playable = [country for country, d in self.map_screen.nation_data.items() if d.get("is_playable") and country != self.map_screen.player_country and country in active_nations]
        playable.sort()

        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        inbox = p_data.get("inbox", [])

        history_contacts = set()
        for msg in inbox:
            sender = msg.get("sender", "")
            if sender.startswith("To: "):
                history_contacts.add(sender[4:])
            else:
                history_contacts.add(sender)

        pending = p_data.get("pending_diplomacy", {})
        for target in pending.keys():
            if target in playable:
                if queries.get_message_draft(self.map_screen.player_country, target, self.map_screen.nation_data).strip():
                    history_contacts.add(target)

        if self.selected_recipient:
            history_contacts.add(self.selected_recipient)

        y_off = 80 + self.contact_scroll_y
        
        if self.show_all_contacts:
            btn = Button(20, y_off, "medium", "red", "Cancel", self.toggle_add_contact)
            self.elements.append(btn)
            y_off += 60

            display_list = [n for n in playable if n not in history_contacts]
            for country in display_list:
                btn = Button(20, y_off, "medium", "grey", country, lambda c_name=country: self.select_new_contact(c_name))
                self.elements.append(btn)
                y_off += 60
        else:
            btn = Button(20, y_off, "medium", "blue", "+ Add Contact", self.toggle_add_contact)
            self.elements.append(btn)
            y_off += 60

            display_list = [n for n in playable if n in history_contacts]
            for country in display_list:
                color = "green" if self.selected_recipient == country else "grey"
                
                unread = sum(1 for m in p_data.get("inbox", []) if m.get("sender") == country and not m.get("read", False))
                
                display_text = f"{country} ({unread})" if unread > 0 else country
                if unread > 0 and self.selected_recipient != country:
                    color = "red" 

                btn = Button(20, y_off, "medium", color, display_text, lambda c_name=country: self.select_recipient(c_name))
                self.elements.append(btn)
                y_off += 60

        absolute_height = y_off - self.contact_scroll_y 
        self.max_contact_scroll = min(0, c.SCREEN_HEIGHT - absolute_height - 20)

        if self.selected_recipient:
            locked = queries.is_diplomat_busy(self.map_screen.player_country, self.selected_recipient, self.map_screen.nation_data)
            btn_x = c.SCREEN_WIDTH - 150
            btn_y = c.SCREEN_HEIGHT - c.MSG_INPUT_H + 15
            if locked:
                self.elements.append(Button(btn_x, btn_y, "small", "grey", "Diplomat Busy", lambda: None))
            else:
                self.elements.append(Button(btn_x, btn_y, "small", "blue", "Queue", self.send_message))

    def additional_draw(self, surface):
        if not self.map_screen: return
        font_med = fonts.get("heading2")
        font_small = fonts.get("normal")

        left_pane_rect = pygame.Rect(0, 0, c.MSG_LEFT_PANE_W, c.SCREEN_HEIGHT)
        pygame.draw.rect(surface, c.MSG_BG_LIGHT, left_pane_rect)
        pygame.draw.line(surface, (100, 100, 100), (c.MSG_LEFT_PANE_W, 0), (c.MSG_LEFT_PANE_W, c.SCREEN_HEIGHT), 2)

        if not self.selected_recipient:
            txt = font_med.render("Select a nation to view communications.", True, (150, 150, 150))
            surface.blit(txt, (c.MSG_LEFT_PANE_W + 50, c.SCREEN_HEIGHT // 2))
            return

        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        inbox = p_data.get("inbox", [])
        
        display_thread = []
        
        # 1. Build thread with historical messages (reversed so oldest is at index 0)
        for msg in reversed(inbox):
            if msg.get("sender") == self.selected_recipient or msg.get("sender") == f"To: {self.selected_recipient}":
                # Detect newlines and split them back into multiple visual bubbles automatically
                for sub_text in msg["content"].split("\n"):
                    if sub_text.strip():
                        display_thread.append({
                            "content": sub_text, 
                            "is_player": msg["sender"].startswith("To: "), 
                            "is_draft": False,
                            "is_diplo": msg.get("type") == "DIPLOMACY"
                        })
                        
        # Check if there is an active diplomatic action pending for this target
        pending = p_data.get("pending_diplomacy", {}).get(self.selected_recipient, {})
        is_diplo_action = False
        if isinstance(pending, dict):
            act_str = pending.get("action", "")
            if act_str and not act_str.startswith("MSG:"):
                is_diplo_action = True
                
        # 2. Append active drafts chronologically
        for i, draft in enumerate(self.drafts):
            if draft.strip():
                display_thread.append({
                    "content": draft, 
                    "is_player": True, 
                    "is_draft": True, 
                    "draft_idx": i,
                    "is_diplo": is_diplo_action
                })
        
        input_rect = pygame.Rect(c.MSG_LEFT_PANE_W, c.SCREEN_HEIGHT - c.MSG_INPUT_H, c.SCREEN_WIDTH - c.MSG_LEFT_PANE_W, c.MSG_INPUT_H)
        pygame.draw.rect(surface, c.MSG_BG_LIGHT, input_rect)
        pygame.draw.line(surface, (100, 100, 100), (c.MSG_LEFT_PANE_W, input_rect.y), (c.SCREEN_WIDTH, input_rect.y), 2)

        txt_surf = font_small.render(self.compose_text + "|", True, (255, 255, 255))
        surface.blit(txt_surf, (input_rect.x + 20, input_rect.y + 30))

        # --- PRE-CALCULATE SIZES TO ESTABLISH MAX SCROLL CEILING ---
        processed_messages = []
        total_h = 20
        max_width = int((c.SCREEN_WIDTH - c.MSG_LEFT_PANE_W) * c.MSG_BUBBLE_MAX_WIDTH_RATIO)

        for msg in reversed(display_thread):
            words = msg['content'].split(" ")
            lines, current_line = [], ""
            for word in words:
                test_line = current_line + word + " "
                if font_small.size(test_line)[0] < max_width:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word + " "
            if current_line: lines.append(current_line)

            box_height = 20 + (len(lines) * 20)
            box_width = max([font_small.size(l)[0] for l in lines] + [100]) + 30
            total_h += box_height + 15

            processed_messages.append({
                "msg_data": msg,
                "lines": lines,
                "box_height": box_height,
                "box_width": box_width
            })

        self.max_msg_scroll = max(0, total_h - input_rect.y + 20)
        self.scroll_y = max(0, min(self.scroll_y, self.max_msg_scroll))

        current_y = input_rect.y - 20 + self.scroll_y
        self.draft_edit_rects = []
        
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

            if is_player:
                box_x = c.SCREEN_WIDTH - box_width - 30
                color = c.MSG_BUBBLE_PLAYER_DIPLO if is_diplo else c.MSG_BUBBLE_PLAYER
                
                if is_draft:
                    del_rect = pygame.Rect(box_x - 35, current_y + box_height//2 - 12, 25, 25)
                    self.draft_edit_rects.append((del_rect, msg['draft_idx']))
                    
                    pygame.draw.rect(surface, (150, 0, 0), del_rect, border_radius=5)
                    surface.blit(font_small.render("X", True, (255, 255, 255)), (del_rect.x + 7, del_rect.y + 2))
            else:
                box_x = c.MSG_LEFT_PANE_W + 30
                color = c.MSG_BUBBLE_AI_DIPLO if is_diplo else c.MSG_BUBBLE_AI

            bubble_rect = pygame.Rect(box_x, current_y, box_width, box_height)
            pygame.draw.rect(surface, color, bubble_rect, border_radius=10)
            
            if is_draft:
                pygame.draw.rect(surface, (255, 215, 0), bubble_rect, 2, border_radius=10)
            
            ly = current_y + 10
            for l in lines:
                surface.blit(font_small.render(l, True, (255, 255, 255)), (box_x + 15, ly))
                ly += 20
                
            current_y -= 15 

    def exit_to_map(self):
        self.save_current_draft() 
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()