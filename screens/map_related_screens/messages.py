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
        self.scroll_y = 0
        
        self.contact_scroll_y = 0
        self.max_contact_scroll = 0
        self.is_dragging_contacts = False
        
        self.show_all_contacts = False

    def start_messages(self, map_ref):
        self.map_screen = map_ref
        self.selected_recipient = None
        self.compose_text = ""
        self.scroll_y = 0
        self.contact_scroll_y = 0
        self.is_dragging_contacts = False
        self.show_all_contacts = False
        self.refresh_ui()

    def save_current_draft(self):
        """Auto-saves whatever is currently typed in the box before switching menus/contacts."""
        if self.selected_recipient and self.map_screen:
            if self.compose_text.strip():
                diplomacy_logic.queue_text_message(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient, self.compose_text)
            else:
                diplomacy_logic.cancel_text_message(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)

    def select_recipient(self, target):
        self.save_current_draft() # Auto-save current draft before switching
        
        # Toggle off if clicking the already selected contact
        if self.selected_recipient == target:
            self.selected_recipient = None
            self.compose_text = ""
            self.refresh_ui()
            return
        
        self.selected_recipient = target
        self.scroll_y = 0  # Reset scroll for new chat history
        
        # Mark all messages from this target as read
        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        for msg in p_data.get("inbox", []):
            if msg.get("sender") == target:
                msg["read"] = True
                
        # Load any existing draft for the new target
        self.compose_text = queries.get_message_draft(self.map_screen.player_country, target, self.map_screen.nation_data)
        self.refresh_ui()

    def toggle_add_contact(self):
        self.show_all_contacts = not self.show_all_contacts
        self.contact_scroll_y = 0
        self.refresh_ui()

    def select_new_contact(self, target):
        self.show_all_contacts = False
        self.contact_scroll_y = 0  # Snap scroll back to top to prevent buttons hiding off-screen
        self.select_recipient(target)

    def send_message(self):
        if self.selected_recipient:
            if self.compose_text.strip():
                msg = diplomacy_logic.queue_text_message(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient, self.compose_text)
                self.map_screen.show_feedback(msg)
            else:
                msg = diplomacy_logic.cancel_text_message(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)
                self.map_screen.show_feedback(msg)
            self.refresh_ui()

    def additional_events(self, event):
        mx, my = pygame.mouse.get_pos()
        
        # --- Scrolling Logic ---
        if event.type == pygame.MOUSEWHEEL:
            if mx < c.MSG_LEFT_PANE_W:
                self.contact_scroll_y += event.y * 30
                self.contact_scroll_y = max(self.max_contact_scroll, min(0, self.contact_scroll_y))
                self.refresh_ui() # CRITICAL: We have to refresh UI to physically move the buttons!
            else:
                self.scroll_y = min(0, self.scroll_y + event.y * 30)

        # --- Drag to Scroll Logic ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if mx < c.MSG_LEFT_PANE_W:
                self.is_dragging_contacts = True
        
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.is_dragging_contacts = False
            
        elif event.type == pygame.MOUSEMOTION:
            if getattr(self, 'is_dragging_contacts', False):
                self.contact_scroll_y += event.rel[1]
                self.contact_scroll_y = max(self.max_contact_scroll, min(0, self.contact_scroll_y))
                self.refresh_ui() # CRITICAL: Update button positions on drag
                
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
        
        # Populate Contact List Buttons
        active_nations = set([prov.get("owner") for prov in self.map_screen.map_data.values() if prov.get("owner") not in c.UNPLAYABLE_NATIONS])
        playable = [country for country, d in self.map_screen.nation_data.items() if d.get("is_playable") and country != self.map_screen.player_country and country in active_nations]
        playable.sort()

        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        inbox = p_data.get("inbox", [])

        # Extract contacts we have a history with
        history_contacts = set()
        for msg in inbox:
            sender = msg.get("sender", "")
            if sender.startswith("To: "):
                history_contacts.add(sender[4:])
            else:
                history_contacts.add(sender)

        # Automatically include contacts if we have a message drafted for them
        pending = p_data.get("pending_diplomacy", {})
        for target in pending.keys():
            if target in playable:
                if queries.get_message_draft(self.map_screen.player_country, target, self.map_screen.nation_data).strip():
                    history_contacts.add(target)

        # Force the currently selected recipient to appear even if we haven't sent a message yet
        if self.selected_recipient:
            history_contacts.add(self.selected_recipient)

        y_off = 80 + self.contact_scroll_y
        
        if self.show_all_contacts:
            # Display directory to add a new contact
            btn = Button(20, y_off, "medium", "red", "Cancel", self.toggle_add_contact)
            self.elements.append(btn)
            y_off += 60

            display_list = [c for c in playable if c not in history_contacts]
            for country in display_list:
                btn = Button(20, y_off, "medium", "grey", country, lambda c_name=country: self.select_new_contact(c_name))
                self.elements.append(btn)
                y_off += 60
        else:
            # Display active history list
            btn = Button(20, y_off, "medium", "blue", "+ Add Contact", self.toggle_add_contact)
            self.elements.append(btn)
            y_off += 60

            display_list = [c for c in playable if c in history_contacts]
            for country in display_list:
                color = "green" if self.selected_recipient == country else "grey"
                
                # Check for unread messages specifically from this contact
                unread = sum(1 for m in p_data.get("inbox", []) if m.get("sender") == country and not m.get("read", False))
                
                display_text = f"{country} ({unread})" if unread > 0 else country
                if unread > 0 and self.selected_recipient != country:
                    color = "red" # Highlight contacts with unread messages

                btn = Button(20, y_off, "medium", color, display_text, lambda c_name=country: self.select_recipient(c_name))
                self.elements.append(btn)
                y_off += 60

        # Calculate bounds to prevent scrolling into the void
        absolute_height = y_off - self.contact_scroll_y 
        self.max_contact_scroll = min(0, c.SCREEN_HEIGHT - absolute_height - 20)

        # Send Button in the Input Area
        if self.selected_recipient:
            locked = queries.is_diplomat_busy(self.map_screen.player_country, self.selected_recipient, self.map_screen.nation_data)
            btn_x = c.SCREEN_WIDTH - 150
            btn_y = c.SCREEN_HEIGHT - c.MSG_INPUT_H + 15
            if locked:
                self.elements.append(Button(btn_x, btn_y, "small", "grey", "Diplomat Busy", lambda: None))
            else:
                self.elements.append(Button(btn_x, btn_y, "small", "blue", "Draft", self.send_message))

    def additional_draw(self, surface):
        if not self.map_screen: return
        font_med = fonts.get("heading2")
        font_small = fonts.get("normal")

        # --- LEFT PANE: Contacts Background ---
        left_pane_rect = pygame.Rect(0, 0, c.MSG_LEFT_PANE_W, c.SCREEN_HEIGHT)
        pygame.draw.rect(surface, c.MSG_BG_LIGHT, left_pane_rect)
        pygame.draw.line(surface, (100, 100, 100), (c.MSG_LEFT_PANE_W, 0), (c.MSG_LEFT_PANE_W, c.SCREEN_HEIGHT), 2)

        # --- RIGHT PANE: Chat History ---
        if not self.selected_recipient:
            txt = font_med.render("Select a nation to view communications.", True, (150, 150, 150))
            surface.blit(txt, (c.MSG_LEFT_PANE_W + 50, c.SCREEN_HEIGHT // 2))
            return

        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        inbox = p_data.get("inbox", [])
        
        # Filter thread and reverse to draw bottom-to-top (newest at bottom)
        thread = [m for m in inbox if m.get("sender") == self.selected_recipient or m.get("sender") == f"To: {self.selected_recipient}"]
        
        # Draw Input Box Background
        input_rect = pygame.Rect(c.MSG_LEFT_PANE_W, c.SCREEN_HEIGHT - c.MSG_INPUT_H, c.SCREEN_WIDTH - c.MSG_LEFT_PANE_W, c.MSG_INPUT_H)
        pygame.draw.rect(surface, c.MSG_BG_LIGHT, input_rect)
        pygame.draw.line(surface, (100, 100, 100), (c.MSG_LEFT_PANE_W, input_rect.y), (c.SCREEN_WIDTH, input_rect.y), 2)

        # Draw Current Draft Text
        txt_surf = font_small.render(self.compose_text + "|", True, (255, 255, 255))
        surface.blit(txt_surf, (input_rect.x + 20, input_rect.y + 30))

        # Render Messages (Bottom to Top)
        current_y = input_rect.y - 20 + self.scroll_y
        
        for msg in thread:
            is_player = msg['sender'].startswith("To: ")
            
            # Word Wrap Logic
            words = msg['content'].split(" ")
            lines, current_line = [], ""
            max_width = int((c.SCREEN_WIDTH - c.MSG_LEFT_PANE_W) * 0.6) # Max 60% of chat width
            
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
            
            current_y -= box_height
            
            if current_y + box_height < 0:
                continue # Cull messages off-screen above

            # Align right if player, left if AI
            if is_player:
                box_x = c.SCREEN_WIDTH - box_width - 30
                color = c.MSG_BUBBLE_PLAYER
            else:
                box_x = c.MSG_LEFT_PANE_W + 30
                color = c.MSG_BUBBLE_AI

            # Draw Bubble
            bubble_rect = pygame.Rect(box_x, current_y, box_width, box_height)
            pygame.draw.rect(surface, color, bubble_rect, border_radius=10)
            
            # Draw Text
            ly = current_y + 10
            for l in lines:
                surface.blit(font_small.render(l, True, (255, 255, 255)), (box_x + 15, ly))
                ly += 20
                
            current_y -= 15 # Padding between messages

    def exit_to_map(self):
        self.save_current_draft() # Auto-save before exiting
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()