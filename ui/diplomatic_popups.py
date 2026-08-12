import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts
from ui import text_utils
from data import queries
from map_logic.diplomacy import diplomacy_messages

# ==========================================
# LAYOUT
# ==========================================

POPUP_WIDTH = 450
POPUP_HEIGHT = 130
POPUP_MAX_LINES = 4
POPUP_START_X = (c.SCREEN_WIDTH // 2) - (POPUP_WIDTH // 2)
POPUP_START_Y = 100
POPUP_OFFSET_STEP = 30

# Close ("X") box, anchored to the popup's top-right corner.
POPUP_CLOSE_SIZE = 25
POPUP_CLOSE_INSET_X = 30
POPUP_CLOSE_INSET_Y = 5

class DiplomaticPopup:
    def __init__(self, sender, text, index, message=None):
        self.width = POPUP_WIDTH
        self.height = POPUP_HEIGHT
        #: The inbox entry this came from, so the popup can tell when it has
        #: been dealt with. Kept by identity rather than copied: marking the
        #: message read is what the Messages screen already does, and this reads
        #: the same object.
        self.message = message
        
        # Start positions
        start_x = POPUP_START_X
        start_y = POPUP_START_Y
        
        # Cascade offset (cap it so it doesn't push completely off screen)
        offset_step = POPUP_OFFSET_STEP
        max_offset = min(start_x, c.SCREEN_HEIGHT - start_y - self.height)
        total_offset = min(offset_step * index, max_offset)
        
        self.rect = pygame.Rect(start_x + total_offset, start_y + total_offset, self.width, self.height)
        self.x_rect = pygame.Rect(self.rect.right - POPUP_CLOSE_INSET_X, self.rect.y + POPUP_CLOSE_INSET_Y,
                                  POPUP_CLOSE_SIZE, POPUP_CLOSE_SIZE)

        self.sender = sender
        self.text = text
        self.is_dragging = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0

        self.font_title = fonts.get("heading2")
        self.font_body = fonts.get("small")

    def handle_event(self, event):
        """Returns action string if a state change is needed, otherwise handles internal dragging."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.x_rect.collidepoint(event.pos):
                return "CLOSE"
            elif self.rect.collidepoint(event.pos):
                self.is_dragging = True
                self.drag_offset_x = self.rect.x - event.pos[0]
                self.drag_offset_y = self.rect.y - event.pos[1]
                return "DRAG"
                
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.is_dragging = False
            
        elif event.type == pygame.MOUSEMOTION:
            if self.is_dragging:
                self.rect.x = event.pos[0] + self.drag_offset_x
                self.rect.y = event.pos[1] + self.drag_offset_y
                self.x_rect.x = self.rect.right - POPUP_CLOSE_INSET_X
                self.x_rect.y = self.rect.y + POPUP_CLOSE_INSET_Y
                return "DRAG"
        return None

    def draw(self, surface):
        # Draw background
        pygame.draw.rect(surface, (40, 40, 50), self.rect)
        pygame.draw.rect(surface, (200, 150, 50), self.rect, 2)

        # Draw close button
        pygame.draw.rect(surface, (150, 0, 0), self.x_rect)
        pygame.draw.rect(surface, (255, 255, 255), self.x_rect, 1)
        x_surf = self.font_body.render("X", True, (255, 255, 255))
        surface.blit(x_surf, (self.x_rect.x + 8, self.x_rect.y + 3))

        # Draw Title
        title_surf = self.font_title.render(f"Diplomatic Alert: {self.sender}", True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(title_surf, (self.rect.x + 10, self.rect.y + 10))

        # Capped at 4 lines so a long message can't spill out of the popup.
        lines = text_utils.wrap_text(self.text, self.font_body, self.width - 20,
                                     max_lines=POPUP_MAX_LINES)

        y_off = self.rect.y + 45
        for line in lines:
            line_surf = self.font_body.render(line, True, c.UI_TEXT_BRIGHT)
            surface.blit(line_surf, (self.rect.x + 10, y_off))
            y_off += 20


def spawn_popups_for_player(map_screen):
    """Raises an alert for every unseen diplomatic message in the player's inbox.

    Nobody it is not addressed to gets one. A spectator has no diplomacy of
    their own, and neither does a tactical-mode player: their country is run by
    the AI, every screen the alert would send them to is read-only for them, and
    the inbox it is announcing belongs to their host rather than to them.

    The messages are still marked shown. Declaring independence turns tactical
    mode off mid-game, and a player who has just founded a country should not be
    handed a stack of alerts about treaties their old host signed.
    """
    if not hasattr(map_screen, 'diplomatic_popups'):
        map_screen.diplomatic_popups = []

    if map_screen.player_country in ["None", "Spectator", "Editor"]:
        return

    if getattr(map_screen, 'tactical_mode', False):
        # Runs every frame the player is in control, so this also takes down any
        # alert that was already up when the mode changed.
        map_screen.diplomatic_popups = []
        for msg in map_screen.nation_data.get(map_screen.player_country, {}).get("inbox", []):
            if msg.get("type") == "DIPLOMACY":
                msg["popup_shown"] = True
        return

    p_data = map_screen.nation_data.get(map_screen.player_country, {})
    inbox = p_data.get("inbox", [])

    for msg in inbox:
        if msg.get("type") == "DIPLOMACY" and not msg.get("popup_shown", False):
            # Don't show popups for messages the player sent themselves
            if not msg.get("sender", "").startswith("To: "):
                idx = len(map_screen.diplomatic_popups)
                content = msg.get("content", "")
                sender = msg.get("sender", "Unknown")

                # Dynamically append instructions if action requires a bilateral response
                incoming_action, incoming_turns = queries.get_diplomatic_status(sender, map_screen.player_country, map_screen.nation_data)
                if incoming_turns > 0 and incoming_action in c.BILATERAL_ACTIONS:
                    content += "\n(See Messages to accept or decline)"

                popup = DiplomaticPopup(sender, content, idx, message=msg)
                map_screen.diplomatic_popups.append(popup)
            msg["popup_shown"] = True


def is_spent(map_screen, popup):
    """Whether this popup has stopped telling the player anything new.

    Two ways it can: the message has been read, or the request it was announcing
    has been answered. Neither used to close it -- popups were created and then
    never looked at again, so accepting a trade left its alert sitting on screen
    until it was dismissed by hand, next to an offer that no longer existed.

    Closing one by hand is deliberately not the same thing: the X leaves the
    message unread, because dismissing an alert is not reading your mail.
    """
    msg = popup.message
    if msg is None:
        return False
    if msg.get("read"):
        return True

    sender = msg.get("sender", "")
    if not sender or sender.startswith("To: "):
        return False

    # Was this announcing a request, and has that request been dealt with?
    action, turns = queries.get_diplomatic_status(
        sender, map_screen.player_country, map_screen.nation_data)
    if turns > 0 and action in c.BILATERAL_ACTIONS:
        answered, _ = diplomacy_messages.get_response_status(
            map_screen.nation_data, map_screen.player_country, sender)
        return bool(answered)
    return False


def close_spent_popups(map_screen):
    """Drops every popup that has been read or answered. Called each frame."""
    popups = getattr(map_screen, 'diplomatic_popups', None)
    if not popups:
        return
    map_screen.diplomatic_popups = [p for p in popups if not is_spent(map_screen, p)]

def handle_events(map_screen, event):
    if not hasattr(map_screen, 'diplomatic_popups'):
        return False

    # A popup that has been dealt with must not swallow the click that lands on
    # where it used to be, so it goes before anything is hit-tested.
    close_spent_popups(map_screen)

    # Process from top-most (last in list) to bottom-most
    for i in reversed(range(len(map_screen.diplomatic_popups))):
        popup = map_screen.diplomatic_popups[i]
        res = popup.handle_event(event)
        
        if res == "CLOSE":
            # Hybrid Audio execution for tactile feedback
            queries.play_click_sound()
            map_screen.diplomatic_popups.pop(i)
            return True
            
        elif res == "DRAG":
            # Bring dragged window to front
            if event.type == pygame.MOUSEBUTTONDOWN:
                p = map_screen.diplomatic_popups.pop(i)
                map_screen.diplomatic_popups.append(p)
            return True
            
    return False

def draw(map_screen, surface):
    if not hasattr(map_screen, 'diplomatic_popups'):
        return
    close_spent_popups(map_screen)
    for popup in map_screen.diplomatic_popups:
        popup.draw(surface)

def clear_popups(map_screen):
    map_screen.diplomatic_popups = []