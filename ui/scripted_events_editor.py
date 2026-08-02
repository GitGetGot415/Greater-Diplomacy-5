"""Native pygame port of the tkinter Scripted Events Editor.

The structure of the original is kept intact: a main window with nations down
the left and that nation's events on the right, an event window holding a
scrolling stack of conditional rows above a stack of action rows, plus the
Variables editor and the Help popup it opened.

Where the original used a ttk.Combobox, a row here shows the current value on a
button that opens the shared modal list picker -- the same thing a dropdown
does, using the picker every other converted tool already uses.
"""
import re
import pygame
from gameState import GameState
import data.constants as c
from data import queries
from map_logic.system32.time_handler import TimeHandler
from map_logic.rendering.font_manager import fonts
from ui import confirm_dialog
from ui.bars import ui_bars
from ui.table_screen import truncate
from ui_elements import Button, TextField

# ==========================================
# OPTION LISTS
# ==========================================

COND_TYPES = [
    "Turn Number", "Variable", "At War With", "Is At War", "In Faction With",
    "Not In Faction With", "Is In Faction", "Is Faction Leader", "Has Truce With",
    "At Peace With", "Is At Peace", "Random (0.00 - 1.00)", "Received Action",
    "Country Exists", "Country Doesn't Exist", "Occupying Core Of",
    "Occupying All Cores Of", "Occupying Claims Of", "Occupying All Claims",
    "Occupying Tile", "Is AI Controlled", "Is Player Controlled", "Bordering",
    "Not Bordering", "True", "False",
]

CHAIN_OPS = ["AND", "OR", "XOR", "NOR", "NAND"]
NUMERIC_OPS = ["==", "!=", ">", "<", ">=", "<=", "BETWEEN (INC)", "BETWEEN (EXC)"]
TURN_OPS = ["==", ">", "<", ">=", "<=", "BETWEEN (INC)", "BETWEEN (EXC)"]
RECEIVED_ACTIONS = ["WAR_DECLARATION", "JOIN_WARS", "CALL_TO_ARMS", "CREATE_FACTION",
                    "FACTION_INVITE", "JOIN_FACTION_REQ", "TRADE", "CEASEFIRE"]
TRIGGER_TYPES = ["AI Only", "Player Only", "Both"]

# Condition types whose value is a comma-separated list of nation IDs.
TARGET_LIST_TYPES = ["At War With", "In Faction With", "Not In Faction With", "Has Truce With",
                     "At Peace With", "Country Exists", "Country Doesn't Exist",
                     "Occupying Claims Of", "Occupying All Claims"]
# Condition types that take a single nation ID, or blank to mean the event's owner.
SELF_OR_TARGET_TYPES = ["Is AI Controlled", "Is Player Controlled", "Is At War",
                        "Is At Peace", "Is In Faction", "Is Faction Leader"]

EDIT_ACTIONS = ["Edit Name", "Edit Leader Name", "Edit Leader Title",
                "Edit Color", "Edit Flag", "Edit Portrait"]
ACT_TYPES = ["Declare War", "Join Faction", "Create Faction", "Invite to Faction",
             "Accept Proposal", "Reject Proposal", "Send Ceasefire", "Send Custom Message",
             "Queue Claims", "Revoke Claims", "Revoke All Claims", "Give Territory",
             "Spawn Unit", "Set Variable"] + EDIT_ACTIONS
# Actions that only write a plain text value onto the event's owner.
TEXT_ONLY_ACTIONS = ["Edit Name", "Edit Leader Name", "Edit Leader Title",
                     "Queue Claims", "Revoke Claims"]
VAR_MATH_OPS = ["Set", "Add", "Subtract", "Multiply", "Divide"]

VAR_TYPES = ["int", "double", "string"]

HELP_TEXT = """ === EVENT TYPE ===
- AI Only: Event fires only if this country is controlled by an AI
- Player Only: Event fires only if this country is controlled by a player
- Both: Event fires if this country is controlled by either an AI or a player

=== CONDITIONALS ===
- Turn Number: Checks if the current game turn matches the specified value
- At War With: Checks if the nation is at war with the specified target(s) (comma-separated)
- Is At War: Checks if the target nation (or self if blank) is currently in any war
- In Faction With: Checks if the nation shares a faction with the target(s)
- Not In Faction With: Checks if the nation does NOT share a faction with the target(s)
- Is In Faction: Checks if the target nation (or self if blank) is currently in any faction
- Is Faction Leader: Checks if the target nation (or self if blank) is the leader of their faction
- Has Truce With: Checks if the nation has an active truce with the specified target(s) (comma-separated)
- At Peace With: Checks if the nation is explicitly NOT at war with the target(s)
- Is At Peace: Checks if the target nation (or self if blank) is in ZERO wars
- Random (0.00 - 1.00): Returns a random value between 0.0 and 1.0
- Received Action: Checks if a specific diplomatic action is pending from a specific sender
- Country Exists: Checks if the target(s) currently hold territory on the map
- Country Doesn't Exist: Checks if the target(s) are completely wiped off the map
- Occupying Core Of: Checks if the nation occupies any core of the target
- Occupying All Cores Of: Checks if the nation occupies EVERY core of the target
- Occupying Claims Of: Checks if the nation occupies any claim of the target
- Occupying All Claims: Checks if the nation occupies EVERY claim of the target
- Occupying Tile: Checks if the nation occupies specific province IDs (comma-separated)
- Is AI Controlled: Checks if the target nation (or self if blank) is controlled by AI
- Is Player Controlled: Checks if the target nation (or self if blank) is controlled by a human
- Bordering / Not Bordering: Checks physical adjacency to the target
- Variable: Compares a selected global variable against a static value (supports math operators for numerical variables)

=== ACTIONS ===
- Declare War: Declares war on the target
- Join Faction / Create Faction / Invite to Faction: Modifies faction alignments
- Accept / Reject Proposal: Responds to a pending diplomatic request
- Send Ceasefire: Offers peace to the target
- Send Custom Message: Sends a text message to the target
- Queue Claims: Begins fabricating claims on the specified Province IDs (comma-separated)
- Revoke Claims: Removes claims on the specified Province IDs (comma-separated)
- Revoke All Claims: Removes ALL claims held by the target nation
- Edit Name / Leader / Title: Changes cosmetic names for the event owner
- Edit Color / Flag / Portrait: Modifies cosmetic visual aspects
- Give Territory: Transfers the specified Province IDs (comma-separated) to the target nation. Check 'Must Control' if they must currently control the tiles to transfer them.
- Spawn Unit: Spawns the specified unit type for the target nation on the specified Province IDs (comma-separated). Check 'Must Control' if they must currently control the tiles to spawn the unit on them.
- Set Variable: Modifies a selected global variable by setting, adding, subtracting, multiplying, or dividing it by a static value.

The AI Msg Checkbox means that you can allow the ai to generate custom text for that message
It will fallback to whatever you manually entered if the llm ai is turned off or otherwise fails"""


# ==========================================
# SHARED CHROME
# ==========================================

class _ModalScreen(GameState):
    """A dimmed freeze-frame behind a bordered panel -- the shape every converted
    tool window in ui/ uses. Subclasses fill in draw_body() and refresh_ui()."""
    PANEL_SIZE = (1240, 680)
    PAD = 16
    ROW_HEIGHT = 34

    def __init__(self, game_state, title):
        super().__init__()
        # Only used to resolve custom keybinds (BACK/ORDERS) and to host sub-pickers.
        self.map_screen = getattr(game_state, "map_screen", None) or game_state
        self.title = title

        surface = pygame.display.get_surface()
        self.background = surface.copy() if surface else None

        self.panel_rect = pygame.Rect(0, 0, *self.PANEL_SIZE)
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)

    # -- widgets -------------------------------------------------------- #

    def _assign(self, attr, value):
        """Sets an attribute and re-renders -- the callback shape combos and toggles want."""
        setattr(self, attr, value)
        self.refresh_ui()

    def _sized(self, btn, width):
        btn.rect.width = width
        return btn

    def button(self, x, y, width, color, text, callback, preset="list_row"):
        return self._sized(Button(x, y, preset, color, text, callback, font_preset="button_small"), width)

    def combo(self, x, y, width, value, options, title, on_pick, color="light_blue"):
        """A combobox: shows the current value, opens the shared modal list picker."""
        label = truncate(str(value) if str(value) else "-", max(4, (width - 14) // 9))
        return self.button(x, y, width, color, label,
                           lambda: self._choose(title, options, on_pick))

    def _choose(self, title, options, on_pick):
        options = list(options)
        if not options:
            confirm_dialog.show_warning("Nothing to pick", f"There are no {title.lower()} to choose from.")
            return
        queries.open_listbox_selector(self.map_screen, title, f"Select {title}:", options, on_pick)
        self.refresh_ui()

    def toggle(self, x, y, width, checked, text, callback):
        label = truncate(f"[{'X' if checked else '  '}] {text}", max(4, (width - 14) // 9))
        btn = self.button(x, y, width, "green" if checked else "grey", label, callback)
        btn.is_selected = checked
        return btn

    # -- scroll regions ------------------------------------------------- #

    def scroll_attrs(self, name):
        """Per-region scroll state names.

        Underscore-prefixed so a region can never shadow a method: a region
        called "events" would otherwise publish its scrollbar handle as
        self.handle_events and overwrite GameState.handle_events.
        """
        return {"attr": f"_scroll_{name}", "limit_attr": f"_max_{name}",
                "track_attr": f"_track_{name}", "handle_attr": f"_handle_{name}",
                "drag_attr": f"_drag_{name}"}

    def rows_of(self, name, count, top, view_h, row_h=None):
        row_h = row_h or self.ROW_HEIGHT
        attrs = self.scroll_attrs(name)
        return self.layout_list_rows(count, row_h, top, view_h=view_h, cull_top=top - 1,
                                     cull_bottom=top + view_h - row_h + 2,
                                     attr=attrs["attr"], limit_attr=attrs["limit_attr"])

    def route_scroll(self, event, regions):
        """Wheel goes to whichever region the cursor is over; scrollbar presses and
        drags are offered to all of them, which each ignore what is not theirs."""
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            for name, rect in regions.items():
                if rect.collidepoint(pos):
                    self.handle_list_scroll(event, **self.scroll_attrs(name))
                    return
            return
        for name in regions:
            if self.handle_list_scroll(event, **self.scroll_attrs(name)):
                return

    # -- drawing -------------------------------------------------------- #

    def label(self, surface, text, pos, color=(170, 170, 210), preset="small"):
        surface.blit(fonts.get(preset).render(text, True, color), pos)

    def draw_body(self, surface):
        pass

    def draw(self, surface):
        if self.background:
            surface.blit(self.background, (0, 0))
        else:
            surface.fill((20, 20, 28))
        ui_bars.draw_fullscreen_overlay(surface, 210)

        ui_bars.draw_modal_box(surface, self.panel_rect, bg_color=(35, 35, 45),
                               border_color=(100, 150, 255), border_width=3)
        ui_bars.draw_centered_title(surface, self.title, self.panel_rect.y + 12, "heading2")

        self.draw_body(surface)
        for el in self.elements:
            el.draw(surface)


def _run(screen):
    from ui.screen_runner import run_screen
    return run_screen(screen)


# ==========================================
# HELP POPUP
# ==========================================

class _HelpScreen(_ModalScreen):
    PANEL_SIZE = (1020, 660)
    LINE_H = 20

    def __init__(self, game_state):
        super().__init__(game_state, "Scripted Events Help")
        p = self.panel_rect
        self.body_top = p.y + 56
        self.view_h = p.bottom - 70 - self.body_top

        font = fonts.get("normal")
        self.lines = []
        for raw in HELP_TEXT.split("\n"):
            self.lines.extend(confirm_dialog._wrap_text(raw, font, p.width - 2 * self.PAD - 30) or [""])
        self.refresh_ui()

    def refresh_ui(self):
        p = self.panel_rect
        self.elements = [Button(p.centerx - 50, p.bottom - 56, "small", "red", "Close", self.exit_screen)]
        # Nothing is clickable in the body, so the text drives the scroll limit alone.
        self.max_scroll = min(0, self.view_h - len(self.lines) * self.LINE_H)

    def additional_events(self, event):
        self.handle_list_scroll(event)

    def draw_body(self, surface):
        p = self.panel_rect
        font = fonts.get("normal")
        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(p.x + 4, self.body_top, p.width - 8, self.view_h))
        y = self.body_top + self.scroll_y
        for line in self.lines:
            if self.body_top - self.LINE_H < y < self.body_top + self.view_h:
                color = c.COLOR_GOLD_HIGHLIGHT if line.strip().startswith("===") else (220, 220, 220)
                surface.blit(font.render(line, True, color), (p.x + self.PAD, y))
            y += self.LINE_H
        surface.set_clip(clip)
        self.draw_list_scrollbar(surface, p.right - 26, self.body_top, self.view_h)


# ==========================================
# VARIABLES EDITOR
# ==========================================

class _VariablesScreen(_ModalScreen):
    PANEL_SIZE = (960, 580)
    LIST_W = 400

    def __init__(self, game_state, map_ref):
        super().__init__(game_state, "Variables Editor")
        self.map_ref = map_ref
        self.selected = None

        p = self.panel_rect
        self.list_x = p.x + self.PAD
        self.list_top = p.y + 82
        self.list_view_h = p.bottom - 20 - self.list_top

        self.form_x = self.list_x + self.LIST_W + 24
        self.name_field = TextField(self.form_x, p.y + 104, 380, 36)
        self.value_field = TextField(self.form_x, p.y + 236, 380, 36)
        self.var_type = "int"
        self.name_field.text = ""
        self.value_field.text = "0"

        self.refresh_ui()

    @property
    def variables(self):
        return self.map_ref.script_variables

    @property
    def listening_for(self):
        return self.name_field.active or self.value_field.active

    # -- selection ------------------------------------------------------ #

    def select(self, index):
        self.selected = index
        v = self.variables[index]
        self.name_field.text = str(v["name"])
        self.var_type = v["type"]
        self.value_field.text = str(v["value"])
        self.name_field.active = self.value_field.active = False
        self.refresh_ui()

    # -- usage ---------------------------------------------------------- #

    def _usage(self, var_name):
        """Every (nation, event) pair that reads or writes this variable."""
        usage = []
        for nat, ndata in self.map_ref.nation_data.items():
            for ev in ndata.get("scripted_events", []):
                used = any(cond.get("type") == "Variable" and cond.get("variable") == var_name
                           for cond in ev.get("conditions", []))
                used = used or any(a.get("type") == "Set Variable" and a.get("target") == var_name
                                   for a in ev.get("actions", []))
                if used:
                    usage.append((nat, ev))
        return usage

    @staticmethod
    def _nations_used(usage):
        return list({u[0] for u in usage})

    # -- actions -------------------------------------------------------- #

    def add_var(self):
        name = self.name_field.text.strip()
        if not name:
            return
        if any(v["name"] == name for v in self.variables):
            confirm_dialog.show_error("Error", "Variable name must be unique.")
            return
        self.variables.append({"name": name, "type": self.var_type, "value": self.value_field.text})
        self.refresh_ui()

    def update_var(self):
        if self.selected is None or self.selected >= len(self.variables):
            return
        idx = self.selected
        old = self.variables[idx]
        new_name = self.name_field.text.strip()
        new_type = self.var_type
        if not new_name:
            return

        if old["name"] != new_name:
            for i, v in enumerate(self.variables):
                if v["name"] == new_name and i != idx:
                    confirm_dialog.show_error("Error", "Variable name must be unique.")
                    return

        usage = self._usage(old["name"])

        def _finish_rename_and_save():
            if old["name"] != new_name and usage:
                for _nat, ev in usage:
                    for cond in ev.get("conditions", []):
                        if cond.get("type") == "Variable" and cond.get("variable") == old["name"]:
                            cond["variable"] = new_name
                    for a in ev.get("actions", []):
                        if a.get("type") == "Set Variable" and a.get("target") == old["name"]:
                            a["target"] = new_name

            self.variables[idx] = {"name": new_name, "type": new_type, "value": self.value_field.text}
            self.refresh_ui()

        def _coerce_to_string(ok):
            if not ok:
                return
            for _nat, ev in usage:
                for cond in ev.get("conditions", []):
                    if cond.get("type") == "Variable" and cond.get("variable") == old["name"]:
                        if cond.get("operator") not in ("==", "!="):
                            cond["operator"] = "=="
                for a in ev.get("actions", []):
                    if a.get("type") == "Set Variable" and a.get("target") == old["name"]:
                        if a.get("unit_type") != "Set":
                            a["unit_type"] = "Set"
            _finish_rename_and_save()

        def _coerce_to_numeric(ok):
            if not ok:
                return
            for _nat, ev in usage:
                for cond in ev.get("conditions", []):
                    if cond.get("type") == "Variable" and cond.get("variable") == old["name"]:
                        try:
                            float(cond.get("value", "0"))
                        except ValueError:
                            cond["value"] = "0"
                for a in ev.get("actions", []):
                    if a.get("type") == "Set Variable" and a.get("target") == old["name"]:
                        try:
                            float(a.get("message", "0"))
                        except ValueError:
                            a["message"] = "0"
            _finish_rename_and_save()

        if old["type"] in ("int", "double") and new_type == "string" and usage:
            msg = (f"Changing to string will force all non-equals conditionals to '==' and "
                   f"non-set actions to 'Set'.\nCountries using: {', '.join(self._nations_used(usage))}\n"
                   f"Events affected: {len(usage)}\nProceed?")
            confirm_dialog.ask_yes_no("Warning", msg, _coerce_to_string)
            return

        if old["type"] == "string" and new_type in ("int", "double") and usage:
            msg = (f"Changing to int/double will reset non-numerical condition/action values to '0'.\n"
                   f"Countries using: {', '.join(self._nations_used(usage))}\n"
                   f"Events affected: {len(usage)}\nProceed?")
            confirm_dialog.ask_yes_no("Warning", msg, _coerce_to_numeric)
            return

        _finish_rename_and_save()

    def delete_var(self):
        if self.selected is None or self.selected >= len(self.variables):
            return
        idx = self.selected
        var = self.variables[idx]
        usage = self._usage(var["name"])

        def _finish():
            self.variables.pop(idx)
            self.selected = None
            self.refresh_ui()

        if usage:
            msg = (f"Deleting this variable will delete {len(usage)} events across countries: "
                   f"{', '.join(self._nations_used(usage))}.\nProceed?")

            def on_confirm(ok):
                if not ok:
                    return
                for nat, ev in usage:
                    if ev in self.map_ref.nation_data[nat].get("scripted_events", []):
                        self.map_ref.nation_data[nat]["scripted_events"].remove(ev)
                _finish()

            confirm_dialog.ask_yes_no("Warning", msg, on_confirm)
            return

        _finish()

    def _move(self, delta):
        if self.selected is None:
            return
        idx = self.selected
        new_idx = idx + delta
        if 0 <= new_idx < len(self.variables):
            self.variables.insert(new_idx, self.variables.pop(idx))
            self.selected = new_idx
            self.refresh_ui()

    # -- rendering ------------------------------------------------------ #

    def refresh_ui(self):
        p = self.panel_rect
        self.elements = [Button(p.x + self.PAD, p.bottom - 56, "small", "red", "Close", self.exit_screen)]

        for i, y in self.rows_of("vars", len(self.variables), self.list_top, self.list_view_h, row_h=30):
            v = self.variables[i]
            btn = self.button(self.list_x, y, self.LIST_W - 24, "blue",
                              truncate(f"{v['name']} ({v['type']}) = {v['value']}", 40),
                              lambda idx=i: self.select(idx))
            btn.is_selected = i == self.selected
            self.elements.append(btn)

        self.elements += [self.name_field, self.value_field]
        self.elements.append(self.combo(self.form_x, p.y + 170, 380, self.var_type, VAR_TYPES,
                                        "Variable Type", lambda v: self._assign("var_type", v)))

        row_y = p.y + 300
        for i, (label, color, cb) in enumerate((("Add", "blue", self.add_var),
                                                ("Update", "orange", self.update_var),
                                                ("Delete", "red", self.delete_var))):
            self.elements.append(self.button(self.form_x + i * 128, row_y, 120, color, label, cb))

        self.elements.append(self.button(self.form_x, row_y + 44, 184, "light_blue", "Move Up ^",
                                         lambda: self._move(-1)))
        self.elements.append(self.button(self.form_x + 192, row_y + 44, 184, "light_blue", "Move Down v",
                                         lambda: self._move(1)))

    def additional_events(self, event):
        self.route_scroll(event, {"vars": pygame.Rect(self.list_x, self.list_top,
                                                      self.LIST_W, self.list_view_h)})

    def draw_body(self, surface):
        p = self.panel_rect
        self.label(surface, "Variables:", (self.list_x, self.list_top - 20))
        self.label(surface, "Name:", (self.form_x, p.y + 84))
        self.label(surface, "Type:", (self.form_x, p.y + 150))
        self.label(surface, "Starting Value:", (self.form_x, p.y + 216))

        if not self.variables:
            self.label(surface, "No variables yet.", (self.list_x + 4, self.list_top + 6), (150, 150, 150))

        self.draw_list_scrollbar(surface, self.list_x + self.LIST_W - 18, self.list_top,
                                 self.list_view_h, **self.scroll_attrs("vars"))


# ==========================================
# EVENT WINDOW
# ==========================================

class _CondRow:
    """One conditional, holding a live TextField for its value."""
    def __init__(self, data=None):
        data = data or {}
        self.chain = data.get("chain", "AND")
        self.type = data.get("type", "Turn Number")
        self.variable = data.get("variable", "")
        self.operator = data.get("operator", "==")
        self.field = TextField(0, 0, 140, 28, str(data.get("value", "")))

    def to_dict(self):
        return {"chain": self.chain, "type": self.type, "variable": self.variable,
                "operator": self.operator, "value": self.field.text}


class _ActRow:
    """One action. `field` is the single message store the original kept in msg_var:
    the colour string and the image base64 live in it too, and the entry is simply
    not shown for the action types that write it through a picker instead."""
    def __init__(self, data=None):
        data = data or {}
        self.type = data.get("type", "Declare War")
        self.target = data.get("target", "None")
        self.unit_type = data.get("unit_type", "Infantry Type 1910")
        self.ai_generate = bool(data.get("ai_generate", False))
        self.field = TextField(0, 0, 220, 28, str(data.get("message", "")))

    def to_dict(self):
        return {"type": self.type, "target": self.target, "unit_type": self.unit_type,
                "message": self.field.text, "ai_generate": self.ai_generate}


class _EventEditScreen(_ModalScreen):
    LIST_VIEW_H = 204

    def __init__(self, game_state, map_ref, target, event_idx=None):
        verb = "Edit" if event_idx is not None else "Add"
        super().__init__(game_state, f"{verb} Event: {target}")
        self.map_ref = map_ref
        self.target = target
        self.event_idx = event_idx
        self.saved = False

        event_data = {}
        if event_idx is not None:
            event_data = map_ref.nation_data[target]["scripted_events"][event_idx]
            _upgrade_legacy_event(event_data)

        conds_data = event_data.get("conditions") or [{"chain": "AND", "type": "Turn Number",
                                                       "operator": "==", "value": ""}]
        acts_data = event_data.get("actions", [])
        if not acts_data and "action_type" in event_data:
            acts_data = [{"type": event_data["action_type"], "target": event_data.get("action_target", "None")}]

        self.conds = [_CondRow(d) for d in conds_data]
        self.acts = [_ActRow(d) for d in acts_data]
        self.fire_once = event_data.get("fire_once", True)
        self.trigger_type = event_data.get("trigger_type", "AI Only")

        self.countries = sorted(queries.get_living_nations(map_ref.map_data))
        self.unit_types = list(queries.get_unit_library().keys())

        p = self.panel_rect
        self.list_x = p.x + self.PAD
        self.cond_top = p.y + 126
        self.act_top = p.y + 362
        self.btn_col_x = p.right - self.PAD - 100
        self._previews = []

        self.refresh_ui()

    @property
    def variables(self):
        return self.map_ref.script_variables

    @property
    def listening_for(self):
        return any(r.field.active for r in self.conds) or any(r.field.active for r in self.acts)

    # -- condition semantics -------------------------------------------- #

    def _date_string(self, turns_str):
        """The in-game date(s) a turn number lands on, as the original showed in grey."""
        nums = re.findall(r'\d+', turns_str)
        if not nums:
            return ""
        tm = self.map_ref.time_manager
        dpt = self.map_ref.scenario_settings.get("base_days_per_turn", c.DEFAULT_DAYS_PER_TURN)
        out = []
        for num in nums[:2]:  # Max 2 for BETWEEN intervals
            temp_time = TimeHandler(start_year=tm.year)
            temp_time.day = tm.day
            temp_time.month_index = tm.month_index
            temp_time.process_time(int(num) * dpt)
            out.append(temp_time.get_date_string())
        return " / ".join(out)

    def cond_options(self, row):
        """Operator choices and the grey hint for a row -- the original's update_row()."""
        ctype = row.type
        if ctype == "Variable":
            var_type = next((v["type"] for v in self.variables if v["name"] == row.variable), "string")
            return (NUMERIC_OPS if var_type in ("int", "double") else ["==", "!="]), ""
        if ctype in ("Turn Number", "Random (0.00 - 1.00)"):
            hint = ""
            if ctype == "Turn Number":
                dates = self._date_string(row.field.text)
                hint = f"({dates})" if dates else ""
            return TURN_OPS, hint
        if ctype == "Received Action":
            return RECEIVED_ACTIONS, "(Sender Nation ID)"
        if ctype in TARGET_LIST_TYPES:
            return ["=="], "(Target Nation IDs, comma separated)"
        if ctype in ("True", "False"):
            return ["=="], ""
        if ctype == "Occupying All Cores Of":
            return ["==", "!="], "(Target Nation IDs, comma separated)"
        if ctype == "Occupying Tile":
            return ["==", "!="], "(Tile IDs, comma separated)"
        if ctype in SELF_OR_TARGET_TYPES:
            return ["=="], "(Target Nation ID, or blank for self)"
        return ["=="], "(Target Nation ID, comma separated)"

    # -- row edits ------------------------------------------------------ #

    def _set(self, row, attr, value):
        setattr(row, attr, value)
        self.refresh_ui()

    def _move_row(self, rows, row, delta, pin_first):
        idx = rows.index(row)
        new_idx = idx + delta
        # The primary IF condition is pinned to the top, as in the original.
        low = 1 if pin_first else 0
        if idx >= low and low <= new_idx < len(rows):
            rows.insert(new_idx, rows.pop(idx))
            self.refresh_ui()

    def _remove_row(self, rows, row):
        rows.remove(row)
        self.refresh_ui()

    def add_condition(self):
        self.conds.append(_CondRow())
        self.refresh_ui()

    def add_action(self):
        self.acts.append(_ActRow())
        self.refresh_ui()

    # -- action pickers ------------------------------------------------- #

    def pick_color(self, row):
        try:
            initial = tuple(int(v) for v in row.field.text.split(","))[:3]
        except ValueError:
            initial = ()
        if len(initial) != 3:
            initial = (150, 150, 150)
        def on_chosen(chosen):
            if chosen:
                row.field.text = f"{int(chosen[0])},{int(chosen[1])},{int(chosen[2])}"
            self.refresh_ui()

        queries.ask_color(self.map_screen, "Choose color", initial, on_chosen)

    def pick_image(self, row):
        def on_picked(path):
            if path:
                try:
                    img = pygame.image.load(path).convert_alpha()
                    size = c.PORTRAIT_SIZE if row.type == "Edit Portrait" else c.FLAG_SIZE
                    row.field.text = queries.encode_surf_to_b64(pygame.transform.scale(img, size))
                except Exception as e:
                    confirm_dialog.show_error("Error", f"Could not load image: {e}")
            self.refresh_ui()

        queries.open_file_browser(self.map_screen, "Select Image", c.ASSETS_DIR,
                                  extensions=[".png", ".jpg", ".jpeg", ".bmp"], on_result=on_picked)

    # -- saving --------------------------------------------------------- #

    def save_event(self):
        new_event = {
            "conditions": [r.to_dict() for r in self.conds],
            "actions": [r.to_dict() for r in self.acts],
            "fire_once": self.fire_once,
            "trigger_type": self.trigger_type,
        }
        target_data = self.map_ref.nation_data.setdefault(self.target, {})
        events_list = target_data.setdefault("scripted_events", [])
        if self.event_idx is not None:
            events_list[self.event_idx] = new_event
        else:
            events_list.append(new_event)

        self.saved = True
        self.exit_screen()

    # -- layout --------------------------------------------------------- #

    def _row_controls(self, rows, row, index, y, pin_first):
        """The ^ / v / X column every row carries on its right-hand end."""
        out = []
        if pin_first and index == 0:
            return out
        out.append(self.button(self.btn_col_x, y + 2, 30, "light_blue", "^",
                               lambda: self._move_row(rows, row, -1, pin_first), preset="tiny_square"))
        out.append(self.button(self.btn_col_x + 34, y + 2, 30, "light_blue", "v",
                               lambda: self._move_row(rows, row, 1, pin_first), preset="tiny_square"))
        out.append(self.button(self.btn_col_x + 68, y + 2, 30, "red", "X",
                               lambda: self._remove_row(rows, row), preset="tiny_square"))
        return out

    def _build_cond_row(self, row, index, y):
        els = []
        x = self.list_x
        if index == 0:
            els.append(self.button(x, y + 2, 76, "grey", "IF", lambda: None))
            els[-1].apply_state(enabled=False)
        else:
            els.append(self.combo(x, y + 2, 76, row.chain, CHAIN_OPS, "Chain",
                                  lambda v: self._set(row, "chain", v), color="orange"))
        x += 82

        els.append(self.combo(x, y + 2, 200, row.type, COND_TYPES, "Condition Type",
                              lambda v: self._set(row, "type", v)))
        x += 206

        if row.type == "Variable":
            els.append(self.combo(x, y + 2, 170, row.variable or "-",
                                  [v["name"] for v in self.variables], "Variable",
                                  lambda v: self._set(row, "variable", v)))
            x += 176

        ops, hint = self.cond_options(row)
        if row.operator not in ops:
            row.operator = ops[0]
        els.append(self.combo(x, y + 2, 155, row.operator, ops, "Operator",
                              lambda v: self._set(row, "operator", v)))
        x += 161

        row.field.rect.topleft = (x, y + 3)
        els.append(row.field)
        x += 146

        self._hints.append((hint, x, y))
        els += self._row_controls(self.conds, row, index, y, pin_first=True)
        return els

    def _build_act_row(self, row, index, y):
        els = [self.combo(self.list_x, y + 2, 200, row.type, ACT_TYPES, "Action Type",
                          lambda v: self._set(row, "type", v))]
        x = self.list_x + 206
        t = row.type

        def target_combo(options, title="Target"):
            nonlocal x
            els.append(self.combo(x, y + 2, 180, row.target, options, title,
                                  lambda v: self._set(row, "target", v)))
            x += 186

        def message_field():
            nonlocal x
            row.field.rect.topleft = (x, y + 3)
            els.append(row.field)
            x += 226

        def flag_toggle(text):
            nonlocal x
            els.append(self.toggle(x, y + 2, 160, row.ai_generate, text,
                                   lambda: self._set(row, "ai_generate", not row.ai_generate)))
            x += 166

        if t == "Set Variable":
            target_combo([v["name"] for v in self.variables], "Variable")
            var_type = next((v["type"] for v in self.variables if v["name"] == row.target), "string")
            if var_type in ("int", "double"):
                modes = VAR_MATH_OPS
            else:
                modes = ["Set"]
                row.unit_type = "Set"
            if row.unit_type not in modes:
                row.unit_type = modes[0]
            els.append(self.combo(x, y + 2, 250, row.unit_type, modes, "Operation",
                                  lambda v: self._set(row, "unit_type", v)))
            x += 256
            message_field()
        elif t == "Send Custom Message":
            target_combo(["None"] + self.countries)
            message_field()
            flag_toggle("AI Msg")
        elif t == "Edit Color":
            row.target = "None"
            els.append(self.button(x, y + 2, 130, "purple", "Pick Color", lambda: self.pick_color(row)))
            x += 136
            self._previews.append(("color", row.field.text, pygame.Rect(x, y + 3, 60, 28)))
            x += 66
        elif t in ("Edit Flag", "Edit Portrait"):
            row.target = "None"
            els.append(self.button(x, y + 2, 150, "purple", "Browse Image", lambda: self.pick_image(row)))
            x += 156
            kind = "portrait" if t == "Edit Portrait" else "flag"
            self._previews.append((kind, row.field.text, pygame.Rect(x, y + 2, 46, 30)))
            x += 52
        elif t in TEXT_ONLY_ACTIONS:
            row.target = "None"
            message_field()
        elif t == "Revoke All Claims":
            target_combo(["None"] + self.countries)
        elif t == "Give Territory":
            target_combo(["None"] + self.countries)
            message_field()
            flag_toggle("Must Control")
        elif t == "Spawn Unit":
            target_combo(["None"] + self.countries)
            # unit_type doubles as the Set Variable operation, so a row switched over
            # from that can arrive holding "Add"/"Set"; snap it back to a real unit.
            if row.unit_type not in self.unit_types and self.unit_types:
                row.unit_type = self.unit_types[0]
            els.append(self.combo(x, y + 2, 250, row.unit_type, self.unit_types, "Unit Type",
                                  lambda v: self._set(row, "unit_type", v)))
            x += 256
            message_field()
            flag_toggle("Must Control")
        else:
            target_combo(["None"] + self.countries)
            message_field()
            flag_toggle("AI Msg")

        els += self._row_controls(self.acts, row, index, y, pin_first=False)
        return els

    def refresh_ui(self):
        p = self.panel_rect
        self._hints = []
        self._previews = []

        self.elements = [
            self.toggle(p.x + self.PAD, p.y + 56, 380, self.fire_once, "Single-Time Event (Fire Only Once)",
                        lambda: self._assign("fire_once", not self.fire_once)),
            self.combo(p.x + 410, p.y + 56, 240, f"Trigger: {self.trigger_type}", TRIGGER_TYPES,
                       "Trigger Type", lambda v: self._assign("trigger_type", v)),
            self.button(p.right - self.PAD - 170, p.y + 56, 170, "blue", "Help / Info", self.show_help),
        ]

        for i, y in self.rows_of("conds", len(self.conds), self.cond_top, self.LIST_VIEW_H):
            self.elements += self._build_cond_row(self.conds[i], i, y)

        for i, y in self.rows_of("acts", len(self.acts), self.act_top, self.LIST_VIEW_H):
            self.elements += self._build_act_row(self.acts[i], i, y)

        btn_y = p.bottom - 62
        self.elements += [
            self.button(p.x + self.PAD, btn_y, 200, "blue", "Add Conditional", self.add_condition, preset="medium"),
            self.button(p.x + self.PAD + 210, btn_y, 200, "purple", "Add Action", self.add_action, preset="medium"),
            self.button(p.x + self.PAD + 430, btn_y, 120, "red", "Cancel", self.exit_screen, preset="medium"),
            self.button(p.right - self.PAD - 200, btn_y, 200, "green", "Save Event", self.save_event, preset="medium"),
        ]

    def show_help(self):
        _run(_HelpScreen(self.map_screen))
        self.refresh_ui()

    def additional_events(self, event):
        self.route_scroll(event, {
            "conds": pygame.Rect(self.list_x, self.cond_top, self.panel_rect.width - 40, self.LIST_VIEW_H),
            "acts": pygame.Rect(self.list_x, self.act_top, self.panel_rect.width - 40, self.LIST_VIEW_H),
        })

    def draw_body(self, surface):
        p = self.panel_rect
        self.label(surface, "Conditionals:", (self.list_x, self.cond_top - 20), preset="normal")
        self.label(surface, "Actions:", (self.list_x, self.act_top - 20), preset="normal")

        for band_top in (self.cond_top, self.act_top):
            pygame.draw.rect(surface, (26, 26, 34),
                             pygame.Rect(p.x + 8, band_top - 4, p.width - 16, self.LIST_VIEW_H + 8))

        small = fonts.get("small")
        for hint, x, y in self._hints:
            if hint:
                surface.blit(small.render(hint, True, (150, 150, 165)),
                             (x, y + self.ROW_HEIGHT // 2 - 8))

        for kind, payload, rect in self._previews:
            self._draw_preview(surface, kind, payload, rect)

        if not self.acts:
            self.label(surface, "No actions yet -- add one below.",
                       (self.list_x + 4, self.act_top + 8), (150, 150, 150))

        self.draw_list_scrollbar(surface, p.right - 26, self.cond_top, self.LIST_VIEW_H,
                                 **self.scroll_attrs("conds"))
        self.draw_list_scrollbar(surface, p.right - 26, self.act_top, self.LIST_VIEW_H,
                                 **self.scroll_attrs("acts"))

    def _draw_preview(self, surface, kind, payload, rect):
        """Swatch for Edit Color, thumbnail for Edit Flag/Portrait.

        The tkinter version had to round-trip the surface through a temp PNG to
        show it; pygame just blits it.
        """
        if kind == "color":
            try:
                colour = tuple(int(v) for v in payload.split(","))[:3]
            except (ValueError, AttributeError):
                colour = (128, 128, 128)
            pygame.draw.rect(surface, colour if len(colour) == 3 else (128, 128, 128), rect)
            pygame.draw.rect(surface, (255, 255, 255), rect, 1)
            return

        size = c.PORTRAIT_SIZE if kind == "portrait" else c.FLAG_SIZE
        try:
            surf = queries.decode_b64_to_surf(payload, size, is_portrait=(kind == "portrait"),
                                              country_name=self.target)
            scale = min(rect.width / surf.get_width(), rect.height / surf.get_height())
            thumb = pygame.transform.smoothscale(surf, (max(1, int(surf.get_width() * scale)),
                                                        max(1, int(surf.get_height() * scale))))
            surface.blit(thumb, thumb.get_rect(center=rect.center))
        except Exception:
            pygame.draw.rect(surface, (128, 128, 128), rect)
        pygame.draw.rect(surface, (255, 255, 255), rect, 1)


def _upgrade_legacy_event(evt):
    """Folds a pre-conditions-list event into the modern shape, in place."""
    if "conditions" not in evt:
        evt["conditions"] = [{
            "type": evt.get("condition_type", "Turn Number"),
            "operator": "==",
            "value": evt.get("condition_val", ""),
            "chain": "AND",
        }]
        evt["fire_once"] = True


# ==========================================
# MAIN EDITOR
# ==========================================

class Scripted_Events_Editor_Screen(_ModalScreen):
    NAT_W = 260

    def __init__(self, map_ref):
        super().__init__(map_ref, "Scripted Events Editor")
        self.map_ref = map_ref
        self.countries = sorted(queries.get_living_nations(map_ref.map_data))
        self.target = None
        self.selected_event = None

        p = self.panel_rect
        self.nat_x = p.x + self.PAD
        self.nations_top = p.y + 112
        self.nations_view_h = 500

        self.events_x = self.nat_x + self.NAT_W + 40
        self.events_top = p.y + 130
        self.events_view_h = 490

        self.refresh_ui()

    def _events(self):
        if not self.target:
            return []
        return self.map_ref.nation_data.get(self.target, {}).setdefault("scripted_events", [])

    # -- summaries ------------------------------------------------------ #

    def _event_summary(self, evt, index):
        """The one-line description the original listbox showed, verbatim."""
        _upgrade_legacy_event(evt)

        cond_strs = []
        for idx, c_dict in enumerate(evt["conditions"]):
            prefix = "" if idx == 0 else f" {c_dict.get('chain', 'AND')} "
            if c_dict.get("type") == "Turn Number":
                cond_strs.append(f"{prefix}Turn {c_dict.get('operator', '==')} {c_dict.get('value')}")
            elif c_dict.get("type") == "Variable":
                cond_strs.append(f"{prefix}Var {c_dict.get('variable', '')} "
                                 f"{c_dict.get('operator', '==')} {c_dict.get('value')}")
            else:
                cond_strs.append(f"{prefix}{c_dict.get('type')} {c_dict.get('value')}")

        full_cond_str = "".join(cond_strs)
        if len(full_cond_str) > 40:
            full_cond_str = full_cond_str[:37] + "..."

        actions = evt.get("actions", [])
        if not actions and "action_type" in evt:
            actions = [{"type": evt["action_type"], "target": evt.get("action_target", "None")}]

        act_strs = []
        for a in actions:
            a_type = a.get("type")
            if a_type == "Send Custom Message":
                act_strs.append(f"MSG to '{a.get('target')}'")
            elif a_type in EDIT_ACTIONS:
                act_strs.append(f"{a_type}: '{a.get('message')}'")
            elif a_type == "Queue Claims":
                act_strs.append(f"Queue Claims on Provs: '{a.get('message')}'")
            elif a_type == "Revoke Claims":
                act_strs.append(f"Revoke Claims on Provs: '{a.get('message')}'")
            elif a_type == "Revoke All Claims":
                act_strs.append(f"Revoke All Claims for '{a.get('target')}'")
            elif a_type == "Give Territory":
                act_strs.append(f"Give Territory to '{a.get('target')}'")
            elif a_type == "Spawn Unit":
                act_strs.append(f"Spawn {a.get('unit_type', 'Unit')} for '{a.get('target')}'")
            elif a_type == "Set Variable":
                act_strs.append(f"Set Var '{a.get('target')}' {a.get('unit_type', '')} {a.get('message')}")
            else:
                act_strs.append(f"{a_type} '{a.get('target')}'")

        act_str = f"Then {', '.join(act_strs)}"
        if len(act_str) > 40:
            act_str = act_str[:37] + "..."

        once_str = " [Once]" if evt.get("fire_once", True) else " [Repeat]"
        return f"{index + 1}. If {full_cond_str} -> {act_str}{once_str}"

    # -- actions -------------------------------------------------------- #

    def select_nation(self, cid):
        self.target = cid
        self.selected_event = None
        self._scroll_events = 0
        self.refresh_ui()

    def select_event(self, index):
        self.selected_event = index
        self.refresh_ui()

    def open_event(self, event_idx=None):
        if not self.target:
            confirm_dialog.show_warning("Warning", "Select a nation first.")
            return
        _run(_EventEditScreen(self.map_screen, self.map_ref, self.target, event_idx))
        self.refresh_ui()

    def edit_event(self):
        if self.selected_event is not None:
            self.open_event(self.selected_event)

    def remove_event(self):
        events = self._events()
        idx = self.selected_event
        if idx is None or not (0 <= idx < len(events)):
            return
        events.pop(idx)
        self.selected_event = None
        self.refresh_ui()

    def move_event(self, delta):
        events = self._events()
        idx = self.selected_event
        if idx is None:
            return
        new_idx = idx + delta
        if 0 <= new_idx < len(events):
            events.insert(new_idx, events.pop(idx))
            self.selected_event = new_idx
            self.refresh_ui()

    def open_variables(self):
        _run(_VariablesScreen(self.map_screen, self.map_ref))
        self.refresh_ui()

    # -- rendering ------------------------------------------------------ #

    def refresh_ui(self):
        p = self.panel_rect
        self.elements = [Button(self.nat_x, p.y + 46, "small", "red", "Back", self.exit_screen)]

        for i, y in self.rows_of("nations", len(self.countries), self.nations_top,
                                 self.nations_view_h, row_h=30):
            cid = self.countries[i]
            btn = self.button(self.nat_x, y, self.NAT_W - 24, "blue", truncate(cid, 26),
                              lambda cc=cid: self.select_nation(cc))
            btn.is_selected = cid == self.target
            self.elements.append(btn)

        self.elements.append(self.button(self.nat_x, self.nations_top + self.nations_view_h + 12,
                                         self.NAT_W - 24, "green", "Variables", self.open_variables))

        events = self._events()
        row_w = p.right - self.PAD - self.events_x - 20
        for i, y in self.rows_of("events", len(events), self.events_top, self.events_view_h):
            btn = self.button(self.events_x, y, row_w, "blue",
                              truncate(self._event_summary(events[i], i), row_w // 9),
                              lambda idx=i: self.select_event(idx))
            btn.is_selected = i == self.selected_event
            self.elements.append(btn)

        btn_y = p.bottom - 62
        has_sel = self.selected_event is not None
        add_btn = self.button(self.events_x, btn_y, 200, "blue", "Add New Event",
                              lambda: self.open_event(None), preset="medium")
        self.elements.append(add_btn)

        for x_off, width, colour, label, cb in ((210, 110, "orange", "Edit", self.edit_event),
                                                (330, 60, "light_blue", "^", lambda: self.move_event(-1)),
                                                (398, 60, "light_blue", "v", lambda: self.move_event(1))):
            btn = self.button(self.events_x + x_off, btn_y, width, colour, label, cb, preset="medium")
            btn.apply_state(enabled=has_sel, color=colour)
            self.elements.append(btn)

        remove_btn = self.button(p.right - self.PAD - 160, btn_y, 160, "red", "Remove",
                                 self.remove_event, preset="medium")
        remove_btn.apply_state(enabled=has_sel, color="red")
        self.elements.append(remove_btn)

    def additional_events(self, event):
        self.route_scroll(event, {
            "nations": pygame.Rect(self.nat_x, self.nations_top, self.NAT_W, self.nations_view_h),
            "events": pygame.Rect(self.events_x, self.events_top,
                                  self.panel_rect.right - self.events_x, self.events_view_h),
        })

    def draw_body(self, surface):
        p = self.panel_rect
        self.label(surface, "Nations:", (self.nat_x, self.nations_top - 20))
        pygame.draw.line(surface, (70, 70, 95), (self.events_x - 20, p.y + 46),
                         (self.events_x - 20, p.bottom - 16), 1)

        heading = "Select a nation..." if not self.target else f"Events for: {self.target}"
        surface.blit(fonts.get("heading2").render(heading, True, c.COLOR_GOLD_HIGHLIGHT),
                     (self.events_x, p.y + 88))

        if self.target and not self._events():
            self.label(surface, "No events for this nation yet.",
                       (self.events_x + 4, self.events_top + 8), (150, 150, 150))

        self.draw_list_scrollbar(surface, self.nat_x + self.NAT_W - 18, self.nations_top,
                                 self.nations_view_h, **self.scroll_attrs("nations"))
        self.draw_list_scrollbar(surface, p.right - 26, self.events_top, self.events_view_h,
                                 **self.scroll_attrs("events"))


def open_scripted_events_editor(self):
    active_countries = queries.get_living_nations(self.map_data)
    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    if not hasattr(self, 'script_variables'):
        self.script_variables = []

    _run(Scripted_Events_Editor_Screen(self))
    self.hovered_province = None
