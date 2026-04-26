import pygame
from gameState import GameState
import data.constants as c
from ui_elements import Button
from map_logic.rendering.font_manager import fonts
from map_logic.diplomacy import diplomacy_logic
from data import queries
from ui_elements import Button, process_text_input

class Messages_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (25, 25, 35)
        self.map_screen = None
        self.active_tab = "INBOX" # INBOX or COMPOSE
        self.selected_recipient = None
        self.compose_text = ""
        self.scroll_y = 0

    def start_messages(self, map_ref):
        self.map_screen = map_ref
        self.active_tab = "INBOX"
        self.compose_text = ""
        self.scroll_y = 0
        self.refresh_ui()

    def set_tab(self, tab):
        self.active_tab = tab
        self.scroll_y = 0
        self.refresh_ui()

    def select_recipient(self, target):
        self.selected_recipient = target
        
        # --- NEW: Use clean draft check ---
        self.compose_text = queries.get_message_draft(self.map_screen.player_country, target, self.map_screen.nation_data)
        self.refresh_ui()

    def send_message(self):
        if self.selected_recipient and self.compose_text.strip():
            msg = diplomacy_logic.queue_text_message(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient, self.compose_text)
            self.map_screen.show_feedback(msg)
            self.refresh_ui() # Stay on compose tab so they can see it saved
        else:
            self.map_screen.show_feedback("Message cannot be empty!")

    def clear_draft(self):
        if self.selected_recipient:
            msg = diplomacy_logic.cancel_text_message(self.map_screen.nation_data, self.map_screen.player_country, self.selected_recipient)
            self.map_screen.show_feedback(msg)
            self.compose_text = ""
            self.refresh_ui()

    def additional_events(self, event):
        if self.active_tab == "COMPOSE" and self.selected_recipient:
            locked = queries.is_diplomat_busy(self.map_screen.player_country, self.selected_recipient, self.map_screen.nation_data)
            
            if not locked:
                self.compose_text, status = process_text_input(event, self.compose_text, max_length=70)
                if status == "SUBMIT":
                    self.send_message()
                        
        elif self.active_tab == "INBOX":
            if event.type == pygame.MOUSEWHEEL:
                self.scroll_y = min(0, self.scroll_y + event.y * 30)

    def additional_draw(self, surface):
        font_title = fonts.get("heading1")
        font_med = fonts.get("heading2")
        font_small = fonts.get("normal")

        if self.active_tab == "INBOX":
            title = font_title.render("INBOX", True, (255, 255, 255))
            surface.blit(title, (c.SCREEN_WIDTH // 2 - title.get_width() // 2, 20))

            p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
            inbox = p_data.get("inbox", [])

            if not inbox:
                txt = font_med.render("No messages.", True, (150, 150, 150))
                surface.blit(txt, (50, 100))
            else:
                y_pos = 100 + self.scroll_y
                for msg in inbox:
                    # 1. Calculate word wrapping
                    words = msg['content'].split(" ")
                    lines = []
                    current_line = ""
                    max_width = (c.SCREEN_WIDTH - 100) - 40 # 40 for text padding
                    
                    for word in words:
                        test_line = current_line + word + " "
                        if font_small.size(test_line)[0] < max_width:
                            current_line = test_line
                        else:
                            lines.append(current_line)
                            current_line = word + " "
                    if current_line:
                        lines.append(current_line)

                    # 2. Calculate dynamic box height based on number of lines
                    box_height = 45 + (len(lines) * 20) + 15
                    box_height = max(80, box_height) # Ensure it's at least 80px tall

                    # 3. Draw if it's on screen
                    if y_pos + box_height > 80 and y_pos < c.SCREEN_HEIGHT:
                        rect = pygame.Rect(50, y_pos, c.SCREEN_WIDTH - 100, box_height)
                        pygame.draw.rect(surface, (40, 40, 50), rect)
                        pygame.draw.rect(surface, (100, 100, 200), rect, 2)

                        if msg['sender'].startswith("To: "):
                            sender_txt = font_med.render(msg['sender'], True, (150, 255, 150))
                        else:
                            sender_txt = font_med.render(f"From: {msg['sender']}", True, (200, 200, 255))

                        surface.blit(sender_txt, (rect.x + 20, rect.y + 10))
                        
                        # 4. Render each line of text
                        ly = rect.y + 45
                        for l in lines:
                            surface.blit(font_small.render(l, True, (255, 255, 255)), (rect.x + 20, ly))
                            ly += 20
                            
                    # Move down for the next message box
                    y_pos += box_height + 20

        elif self.active_tab == "COMPOSE":
            title = font_title.render("COMPOSE MESSAGE", True, (255, 255, 255))
            surface.blit(title, (c.SCREEN_WIDTH // 2 - title.get_width() // 2, 20))

            if self.selected_recipient:
                # --- NEW: Use clean status check ---
                action, turns = queries.get_diplomatic_status(self.map_screen.player_country, self.selected_recipient, self.map_screen.nation_data)

                # Dynamic Status Logic
                status_text = "Drafting new message to:"
                if turns > 0:
                    status_text = "Awaiting response from:"
                elif isinstance(action, str) and action.startswith("MSG:"):
                    status_text = "Editing queued message to:"
                elif isinstance(action, str) and action:
                    status_text = "Diplomat already deployed to:"

                prompt = font_med.render(f"{status_text} {self.selected_recipient}", True, (200, 255, 200))
                surface.blit(prompt, (50, c.SCREEN_HEIGHT - 180))

                # Hide text input if locked
                if turns == 0 and not (isinstance(action, str) and action and not action.startswith("MSG:")):
                    input_rect = pygame.Rect(50, c.SCREEN_HEIGHT - 140, c.SCREEN_WIDTH - 480, 60)
                    pygame.draw.rect(surface, (20, 20, 20), input_rect)
                    pygame.draw.rect(surface, (255, 255, 255), input_rect, 2)

                    txt_surf = font_med.render(self.compose_text + "|", True, (255, 255, 255))
                    surface.blit(txt_surf, (input_rect.x + 10, input_rect.y + 15))

    # --- UI Elements Refresh Update ---
    # Put this at the end of the file to override the default refresh_ui rendering
    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_to_map)]

        self.elements.append(Button(200, 20, "medium", "blue" if self.active_tab == "INBOX" else "grey", "Inbox", lambda: self.set_tab("INBOX")))
        self.elements.append(Button(420, 20, "medium", "blue" if self.active_tab == "COMPOSE" else "grey", "Compose", lambda: self.set_tab("COMPOSE")))

        if self.active_tab == "COMPOSE":
            y_off = 100
            
            # --- NEW: Clean filtering of playable, living nations ---
            active_nations = queries.get_living_nations(self.map_screen.map_data)
            
            playable = [c for c in active_nations 
                        if queries.is_playable(c, self.map_screen.nation_data) and c != self.map_screen.player_country]
            
            playable.sort()
            
            for i, c in enumerate(playable):
                x_off = 50 + (i % 5) * 220
                row_y = y_off + (i // 5) * 60
                
                # Check for pending messages to this country
                draft = queries.get_message_draft(self.map_screen.player_country, c, self.map_screen.nation_data)
                
                if self.selected_recipient == c:
                    color = "green"
                elif draft:
                    color = "green"
                else:
                    color = "grey"
                    
                self.elements.append(Button(x_off, row_y, "medium", color, c, lambda c_name=c: self.select_recipient(c_name)))

            # DYNAMIC DRAFT BUTTONS
            if self.selected_recipient:
                action, turns = queries.get_diplomatic_status(self.map_screen.player_country, self.selected_recipient, self.map_screen.nation_data)

                if turns > 0:
                    self.elements.append(Button(c.SCREEN_WIDTH - 300, c.SCREEN_HEIGHT - 80, "large", "grey", "Message in Transit", lambda: None))
                elif isinstance(action, str) and action.startswith("MSG:"):
                    self.elements.append(Button(c.SCREEN_WIDTH - 420, c.SCREEN_HEIGHT - 80, "medium", "orange", "Update Draft", self.send_message))
                    self.elements.append(Button(c.SCREEN_WIDTH - 200, c.SCREEN_HEIGHT - 80, "medium", "red", "Clear Draft", self.clear_draft))
                elif isinstance(action, str) and action:
                    self.elements.append(Button(c.SCREEN_WIDTH - 300, c.SCREEN_HEIGHT - 80, "large", "grey", "Diplomat Busy", lambda: None))
                else:
                    self.elements.append(Button(c.SCREEN_WIDTH - 250, c.SCREEN_HEIGHT - 80, "medium", "orange", "Queue Message", self.send_message))

    """def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_to_map)]

        self.elements.append(Button(200, 20, "medium", "blue" if self.active_tab == "INBOX" else "grey", "Inbox", lambda: self.set_tab("INBOX")))
        self.elements.append(Button(420, 20, "medium", "blue" if self.active_tab == "COMPOSE" else "grey", "Compose", lambda: self.set_tab("COMPOSE")))

        if self.active_tab == "COMPOSE":
            y_off = 100
            
            # --- THE FIX ---
            # 1. Scan the map to find who is actually alive right now
            active_nations = set()
            for prov in self.map_screen.map_data.values():
                owner = prov.get("owner")
                if owner and owner not in c.UNPLAYABLE_NATIONS:
                    active_nations.add(owner)
            
            # 2. Filter the playable list to only include living nations
            playable = [c for c, d in self.map_screen.nation_data.items() 
                        if d.get("is_playable") and c != self.map_screen.player_country and c in active_nations]
            # ---------------
            
            playable.sort()
            for i, c in enumerate(playable):
                x_off = 50 + (i % 5) * 220
                row_y = y_off + (i // 5) * 60
                color = "green" if self.selected_recipient == c else "grey"
                self.elements.append(Button(x_off, row_y, "medium", color, c, lambda c_name=c: self.select_recipient(c_name)))

            if self.selected_recipient:
                self.elements.append(Button(c.SCREEN_WIDTH - 250, c.SCREEN_HEIGHT - 80, "medium", "orange", "Send Message", self.send_message))"""

    # --- UI Elements Refresh Update ---
    # Put this at the end of the file to override the default refresh_ui rendering
    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_to_map)]

        self.elements.append(Button(200, 20, "medium", "blue" if self.active_tab == "INBOX" else "grey", "Inbox", lambda: self.set_tab("INBOX")))
        self.elements.append(Button(420, 20, "medium", "blue" if self.active_tab == "COMPOSE" else "grey", "Compose", lambda: self.set_tab("COMPOSE")))

        if self.active_tab == "COMPOSE":
            y_off = 100
            
            # Scan map for living nations
            active_nations = set()
            for prov in self.map_screen.map_data.values():
                owner = prov.get("owner")
                if owner and owner not in c.UNPLAYABLE_NATIONS:
                    active_nations.add(owner)
            
            playable = [c for c, d in self.map_screen.nation_data.items() 
                        if d.get("is_playable") and c != self.map_screen.player_country and c in active_nations]
            
            playable.sort()
            
            # Grab player data once to check for pending messages
            player_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
            
            for i, c in enumerate(playable):
                x_off = 50 + (i % 5) * 220
                row_y = y_off + (i // 5) * 60
                
                # Check for pending messages to this country
                pending = player_data.get("pending_diplomacy", {}).get(c, {})
                action = pending.get("action", "") if isinstance(pending, dict) else pending
                
                if self.selected_recipient == c:
                    color = "green"
                elif isinstance(action, str) and action.startswith("MSG:"):
                    color = "green"
                else:
                    color = "grey"
                    
                self.elements.append(Button(x_off, row_y, "medium", color, c, lambda c_name=c: self.select_recipient(c_name)))

            # DYNAMIC DRAFT BUTTONS
            if self.selected_recipient:
                player_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
                pending = player_data.get("pending_diplomacy", {}).get(self.selected_recipient, {})
                action = pending.get("action", "") if isinstance(pending, dict) else pending
                turns = pending.get("turns", 0) if isinstance(pending, dict) else 0

                if turns > 0:
                    self.elements.append(Button(c.SCREEN_WIDTH - 300, c.SCREEN_HEIGHT - 80, "large", "grey", "Message in Transit", lambda: None))
                elif isinstance(action, str) and action.startswith("MSG:"):
                    self.elements.append(Button(c.SCREEN_WIDTH - 420, c.SCREEN_HEIGHT - 80, "medium", "orange", "Update Draft", self.send_message))
                    self.elements.append(Button(c.SCREEN_WIDTH - 200, c.SCREEN_HEIGHT - 80, "medium", "red", "Clear Draft", self.clear_draft))
                elif isinstance(action, str) and action:
                    self.elements.append(Button(c.SCREEN_WIDTH - 300, c.SCREEN_HEIGHT - 80, "large", "grey", "Diplomat Busy", lambda: None))
                else:
                    self.elements.append(Button(c.SCREEN_WIDTH - 250, c.SCREEN_HEIGHT - 80, "medium", "orange", "Queue Message", self.send_message))

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()