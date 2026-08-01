import tkinter as tk
from tkinter import ttk
import unicodedata
import data.constants as c
from data.map import load_map
from data import queries
from map_logic.diplomacy.diplomacy_agreements import assign_puppet

# ==========================================
# EDITOR MENUS
# ==========================================

def editor_load_map(self):
    """Opens a native folder picker to load a map folder directly into the editor."""
    def on_folder_picked(path):
        load_map.load_map_assets(self, path)
        self.refresh_political_map()
        self.show_feedback("Map Loaded into Editor")

    queries.open_file_browser(self, "Select Map Folder to Edit", c.SCENARIOS_CUSTOM_DIR,
                              on_folder_picked, mode="select_folder")

def _select_brush(self, mode, attr, items, title, prompt, feedback_label="Brush"):
    """Opens a listbox, stores the pick on `attr` and arms the matching editor mode."""
    def cb(val):
        setattr(self, attr, val)
        self.editor_mode = mode
        self.show_feedback(f"{feedback_label}: {val}")
    queries.open_listbox_selector(self, title, prompt, items, cb)

def _paintable_nations(self):
    """The nation list every nation-painting brush offers, sorted accent-insensitively."""
    nations = sorted(self.nation_data.keys(), key=lambda k: unicodedata.normalize('NFKD', k).encode('ascii', 'ignore').decode('utf-8').lower())
    return ["Unclaimed", "The Rot", "----------"] + [n for n in nations if n not in ["Unclaimed", "The Rot"] and (n not in c.UNPLAYABLE_NATIONS or n == "None")]

def select_brush_nation(self):
    """Opens a Tkinter selection window and sets mode to NATION."""
    _select_brush(self, "NATION", "brush_nation", _paintable_nations(self),
                  "Select Nation", "Select Paint Nation:")

def select_core_brush(self):
    """Opens a Tkinter selection window and sets mode to CORE."""
    _select_brush(self, "CORE", "brush_nation", _paintable_nations(self),
                  "Select Core Nation", "Select Nation to Add Cores:", "Core Brush")

def select_claim_brush(self):
    """Opens a Tkinter selection window and sets mode to CLAIM."""
    _select_brush(self, "CLAIM", "brush_nation", _paintable_nations(self),
                  "Select Claim Nation", "Select Nation to Add Claims:", "Claim Brush")

def open_editor_claims(self):
    """Opens a full-screen sortable table listing every claim on the map."""
    rows = []
    for c_name in sorted(self.nation_data.keys()):
        claims = self.nation_data[c_name].get("claims", [])
        if claims:
            rows.append({"country": c_name, "claims": ", ".join(map(str, claims))})

    from ui.table_screen import TableScreen, TableColumn
    columns = [
        TableColumn("country", "Country", 180, align="left"),
        TableColumn("claims", "Claimed Provinces", 700, align="left"),
    ]

    from ui.player_diplomacy_menus import _run_pygame_sub_screen
    _run_pygame_sub_screen(self, TableScreen(self, "Global Claims Overview", columns, rows,
                                             empty_message="No claims on the map."))

def select_building_brush(self):
    """Opens a selection window for building types and sets mode to BUILDING."""
    bldg_lib = queries.get_building_library()
    items = ["None"] + list(bldg_lib.keys()) if bldg_lib else ["None"]
    _select_brush(self, "BUILDING", "brush_building", items,
                  "Select Building", "Select Building to Place:")

def spec_select_edit_country(self):
    """Opens a Tkinter window for a Spectator to select which nation to edit."""
    items = sorted(queries.get_living_nations(self.map_data))
    if not items:
        self.show_feedback("No active countries on map!")
        return
    def cb(val):
        self.editing_country = val
        self.next_state, self.done = "EDIT_COUNTRY", True
    queries.open_listbox_selector(self, "Select Nation to Edit", "Select Nation to Edit:", items, cb)

def open_editor_date(self):
    """Opens a native screen to edit the game's starting date."""
    from ui.editor_screens import Editor_Date_Screen
    from ui.player_diplomacy_menus import _run_pygame_sub_screen
    _run_pygame_sub_screen(self, Editor_Date_Screen(self))


def open_editor_economy(self):
    """Opens a full-screen sortable table of every active country's detailed income."""
    active_countries = sorted(queries.get_living_nations(self.map_data))

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    all_econ = queries.calculate_all_economies(self.map_data, self.nation_data)

    def get_stats(cid, res_key):
        d = all_econ[cid]
        bd = d["breakdown"][res_key]
        cur = int(self.nation_data.get(cid, {}).get(res_key, 0))
        inc = int(bd["core"] + bd["non_core"] + bd["resources"])
        bld = int(bd["buildings"])
        upk = int(d["upkeep"][res_key])
        net = int(d["total_inc"][res_key] - d["upkeep"][res_key])
        return cur, inc, bld, upk, net

    rows = []
    for cid in active_countries:
        if cid not in all_econ:
            continue
        row = {"country": cid}
        for prefix, res_key in (("p", "manpower"), ("m", "materials"), ("f", "fuel")):
            cur, inc, bld, upk, net = get_stats(cid, res_key)
            row[f"{prefix}_cur"], row[f"{prefix}_inc"] = cur, inc
            row[f"{prefix}_bld"], row[f"{prefix}_upk"], row[f"{prefix}_net"] = bld, upk, net
        rows.append(row)

    from ui.table_screen import TableScreen, TableColumn
    columns = [TableColumn("country", "Country", 160, align="left")]
    for group, prefix in (("Manpower", "p"), ("Materials", "m"), ("Fuel", "f")):
        for stat, label in (("cur", "Cur"), ("inc", "Inc"), ("bld", "Bld"), ("upk", "Upk"), ("net", "Net")):
            columns.append(TableColumn(f"{prefix}_{stat}", label, 60, group=group))

    from ui.player_diplomacy_menus import _run_pygame_sub_screen
    _run_pygame_sub_screen(self, TableScreen(self, "Global Economy Overview", columns, rows))

def open_starting_economy_editor(self):
    """Opens a native screen to edit starting resources for countries currently existing on the map."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    from ui.editor_screens import Starting_Economy_List_Screen
    from ui.player_diplomacy_menus import _run_pygame_sub_screen
    _run_pygame_sub_screen(self, Starting_Economy_List_Screen(self))
        
def open_spectator_messages(self):
    """Opens a full-screen sortable table of every message sent between active countries."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    all_msgs = []
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

    for c_name, data in self.nation_data.items():
        if data.get("is_playable"):
            inbox = data.get("inbox", [])
            for msg in inbox:
                msg["spectator_read"] = True
                sender = msg.get("sender", "")

                if not sender.startswith("To: "):
                    date_str = msg.get("date", "Unknown")
                    sort_val = 0
                    try:
                        if date_str != "Unknown":
                            parts = date_str.replace(",", "").replace(" AD", "").split(" ")
                            if len(parts) >= 3:
                                d = int(parts[0])
                                m = months.index(parts[1]) if parts[1] in months else 0
                                y = int(parts[2])
                                sort_val = (y * 360) + (m * 30) + d
                    except Exception:
                        pass

                    all_msgs.append({
                        "date": date_str,
                        "date_sort": sort_val,
                        "sender": sender,
                        "receiver": c_name,
                        "type": msg.get("type", "TEXT"),
                        "message": msg.get("content", "")
                    })

    all_msgs.sort(key=lambda m: m["date_sort"], reverse=True)

    from ui.table_screen import TableScreen, TableColumn, truncate
    columns = [
        TableColumn("date", "Date", 130, sort_key=lambda r: r["date_sort"]),
        TableColumn("sender", "Sender", 120),
        TableColumn("receiver", "Receiver", 120),
        TableColumn("type", "Type", 100),
        TableColumn("message", "Message", 700, align="left", fmt=lambda v: truncate(v, 90)),
    ]

    from ui.player_diplomacy_menus import _run_pygame_sub_screen
    _run_pygame_sub_screen(self, TableScreen(self, "Global Messages Overview", columns, all_msgs,
                                             empty_message="No messages have been sent yet."))

def open_map_research_editor(self):
    """Opens a native screen to edit research for countries currently existing on the map."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    from ui.editor_screens import Research_List_Screen
    from ui.player_diplomacy_menus import _run_pygame_sub_screen
    _run_pygame_sub_screen(self, Research_List_Screen(self))

def select_unit_brush(self):
    """Opens a selection window for unit types and sets mode to UNIT."""
    items = ["None", "Convoy", "----------"] + list(queries.get_unit_library().keys())
    _select_brush(self, "UNIT", "brush_unit", items,
                  "Select Unit", "Select Unit to Place:")

def open_convoy_converter(self, province):
    """Opens a native screen to select which units on a tile should be converted to convoys/trucks."""
    units = province.get("units", [])
    if not units:
        self.show_feedback("No units on tile to convert!")
        return

    from ui.editor_screens import Convoy_Converter_Screen
    from ui.player_diplomacy_menus import _run_pygame_sub_screen
    _run_pygame_sub_screen(self, Convoy_Converter_Screen(self, province))

def select_resource_brush(self):
    """Opens a native screen for picking a resource type and amount to paint."""
    from ui.editor_screens import Resource_Brush_Screen
    from ui.player_diplomacy_menus import _run_pygame_sub_screen
    _run_pygame_sub_screen(self, Resource_Brush_Screen(self))

def open_diplomacy_editor(self):
    """Opens a Tkinter window to edit global relations and factions."""
    active_countries = queries.get_living_nations(self.map_data)
    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root, close_menu = queries.create_managed_tk_window(self, "Global Diplomacy & Factions Editor", "550x700")

    # UI Layout
    left_frame = tk.Frame(root, width=200)
    left_frame.pack(side="left", fill="y", padx=10, pady=10)
    right_frame = tk.Frame(root)
    right_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)

    tk.Label(left_frame, text="Nations:", font=("Arial", 12, "bold")).pack()
    scrollbar = tk.Scrollbar(left_frame)
    scrollbar.pack(side="right", fill="y")
    nation_list = tk.Listbox(left_frame, yscrollcommand=scrollbar.set, exportselection=False)
    nation_list.pack(fill="both", expand=True)
    scrollbar.config(command=nation_list.yview)

    for i in sorted(active_countries):
        nation_list.insert(tk.END, i)

    title_lbl = tk.Label(right_frame, text="Select a nation...", font=("Arial", 14, "bold"))
    title_lbl.pack(pady=5)

    war_frame = tk.LabelFrame(right_frame, text="At War With:")
    war_frame.pack(fill="x", pady=5)

    war_scroll = tk.Scrollbar(war_frame)
    war_scroll.pack(side="right", fill="y")
    war_list = tk.Listbox(war_frame, selectmode=tk.MULTIPLE, height=5, exportselection=False, yscrollcommand=war_scroll.set)
    war_list.pack(fill="x", padx=5, pady=5)
    war_scroll.config(command=war_list.yview)

    fac_frame = tk.LabelFrame(right_frame, text="Faction Info:")
    fac_frame.pack(fill="both", expand=True, pady=5)

    tk.Label(fac_frame, text="Faction Name:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
    fac_name_var = tk.StringVar()
    fac_entry = tk.Entry(fac_frame, textvariable=fac_name_var)
    fac_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=5)

    is_leader_var = tk.BooleanVar()
    leader_cb = tk.Checkbutton(fac_frame, text="Is Faction Leader?", variable=is_leader_var)
    leader_cb.grid(row=1, column=0, columnspan=2, sticky="w", padx=5)

    tk.Label(fac_frame, text="Faction Members (Select to Add/Remove):").grid(row=2, column=0, columnspan=2, sticky="w", padx=5, pady=5)

    mem_scroll = tk.Scrollbar(fac_frame)
    mem_scroll.grid(row=3, column=2, sticky="ns")
    member_list = tk.Listbox(fac_frame, selectmode=tk.MULTIPLE, height=5, exportselection=False, yscrollcommand=mem_scroll.set)
    member_list.grid(row=3, column=0, columnspan=2, sticky="ew", padx=5)
    mem_scroll.config(command=member_list.yview)

    pup_frame = tk.LabelFrame(right_frame, text="Puppet Info:")
    pup_frame.pack(fill="both", expand=True, pady=5)

    tk.Label(pup_frame, text="Master Nation:").grid(row=0, column=0, sticky="w", padx=5)
    master_var = tk.StringVar()
    master_menu = ttk.Combobox(pup_frame, textvariable=master_var, values=["None"] + sorted(active_countries))
    master_menu.grid(row=0, column=1, sticky="ew", padx=5)

    tk.Label(pup_frame, text="Puppet Type:").grid(row=1, column=0, sticky="w", padx=5)
    ptype_var = tk.StringVar()
    ptype_menu = ttk.Combobox(pup_frame, textvariable=ptype_var, values=[c.PUPPET_TYPE_AUTONOMOUS, c.PUPPET_TYPE_INTEGRATED])
    ptype_menu.grid(row=1, column=1, sticky="ew", padx=5)

    current_target = [None]

    def load_nation_data(event):
        sel = nation_list.curselection()
        if not sel: return
        target = nation_list.get(sel[0])
        current_target[0] = target
        title_lbl.config(text=f"Editing: {target}")

        data = self.nation_data.get(target, {})

        war_list.delete(0, tk.END)
        enemies = data.get("at_war_with", [])
        for i, c_name in enumerate(sorted(active_countries)):
            if c_name == target: continue
            war_list.insert(tk.END, c_name)
            if c_name in enemies:
                war_list.selection_set(tk.END)

        fac_name_var.set(data.get("faction", ""))
        is_leader_var.set(data.get("is_faction_leader", False))

        member_list.delete(0, tk.END)
        for i, c_name in enumerate(sorted(active_countries)):
            if c_name == target: continue
            member_list.insert(tk.END, c_name)
            if data.get("faction", "") and self.nation_data.get(c_name, {}).get("faction", "") == data.get("faction", ""):
                member_list.selection_set(tk.END)

        master_val = data.get("master", "None")
        master_var.set(master_val if master_val else "None")
        ptype_var.set(data.get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS))

    nation_list.bind("<<ListboxSelect>>", load_nation_data)

    def save_changes():
        target = current_target[0]
        if not target: return

        data = self.nation_data.get(target, {})

        # 1. Update Wars (Bidirectional)
        for c_name in active_countries:
            if target in self.nation_data[c_name].get("at_war_with", []):
                self.nation_data[c_name]["at_war_with"].remove(target)

        selected_wars = [war_list.get(i) for i in war_list.curselection()]
        data["at_war_with"] = selected_wars
        for enemy in selected_wars:
            if target not in self.nation_data[enemy].get("at_war_with", []):
                self.nation_data[enemy].setdefault("at_war_with", []).append(target)

        # 2. Update Factions
        new_faction = fac_name_var.get().strip()
        data["faction"] = new_faction
        data["is_faction_leader"] = is_leader_var.get()

        selected_members = [member_list.get(i) for i in member_list.curselection()]
        for c_name in active_countries:
            if c_name == target: continue
            if c_name in selected_members:
                self.nation_data[c_name]["faction"] = new_faction
                if new_faction:
                    self.nation_data[c_name]["is_faction_leader"] = False
            elif self.nation_data[c_name].get("faction", "") == new_faction and new_faction != "":
                self.nation_data[c_name]["faction"] = ""
                self.nation_data[c_name]["is_faction_leader"] = False

        # 3. Update Puppet State
        old_master = data.get("master", "")
        if old_master and old_master != "None" and old_master in self.nation_data:
            if target in self.nation_data[old_master].get("puppets", []):
                self.nation_data[old_master]["puppets"].remove(target)

        new_master = master_var.get()
        if new_master and new_master != "None" and new_master != target:
            assign_puppet(self.map_data, self.nation_data, new_master, target, ptype_var.get())
        else:
            data["master"] = ""
            data["puppet_type"] = ""

        self.refresh_diplomacy_maps()
        self.show_feedback(f"Diplomacy saved for {target}")

    tk.Button(right_frame, text="Save Changes", command=save_changes, bg="#4CAF50", fg="white", font=("Arial", 12, "bold")).pack(pady=10, fill="x")

    queries.run_tk_loop(self, root)

def open_edited_countries(self):
    """Opens a full-screen sortable table of countries with edited properties."""
    from data.io import country_io
    default_data = country_io.load_all_country_data()

    rows = []
    for c_id, current_data in self.nation_data.items():
        if c_id in ["Unclaimed", "Ocean", "Lakes", "The Rot", "Spectator", "GLOBAL_EVENTS", "FACTION_WAR_MAPS"]:
            continue

        def_country = default_data.get(c_id, {})
        changes = {}

        # Tracking what differs from default
        c_name = current_data.get("name", c_id)
        d_name = def_country.get("name", c_id)
        if c_name != d_name: changes["name"] = c_name

        c_leader = current_data.get("leader_name", "")
        d_leader = def_country.get("leader_name", "")
        if c_leader != d_leader: changes["leader_name"] = c_leader

        c_title = current_data.get("leader_title", "")
        d_title = def_country.get("leader_title", "")
        if c_title != d_title: changes["leader_title"] = c_title

        c_flag = current_data.get("flag_data", "DEFAULT")
        if c_flag != "DEFAULT": changes["flag"] = "CUSTOM"

        c_port = current_data.get("portrait_data", "DEFAULT")
        if c_port != "DEFAULT": changes["portrait"] = "CUSTOM"

        if changes:
            rows.append({
                "id": c_id,
                "name": changes.get("name", "-"),
                "leader_name": changes.get("leader_name", "-"),
                "leader_title": changes.get("leader_title", "-"),
                "flag": changes.get("flag", "-"),
                "portrait": changes.get("portrait", "-"),
            })

    from ui.table_screen import TableScreen, TableColumn
    columns = [
        TableColumn("id", "ID", 150, align="left"),
        TableColumn("name", "Name", 150),
        TableColumn("leader_name", "Leader Name", 150),
        TableColumn("leader_title", "Leader Title", 150),
        TableColumn("flag", "Flag", 100),
        TableColumn("portrait", "Portrait", 100),
    ]

    from ui.player_diplomacy_menus import _run_pygame_sub_screen
    _run_pygame_sub_screen(self, TableScreen(self, "Edited Countries Overview", columns, rows,
                                             empty_message="No countries have been edited yet."))


def open_clear_menu(self):
    """Opens a native screen to clear items from the map based on various criteria."""
    from ui.editor_screens import Clear_Map_Screen
    from ui.player_diplomacy_menus import _run_pygame_sub_screen
    _run_pygame_sub_screen(self, Clear_Map_Screen(self))