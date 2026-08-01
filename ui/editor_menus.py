import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import unicodedata
import data.constants as c
from data.map import load_map
from data import queries
from map_logic.diplomacy.diplomacy_agreements import assign_puppet

# ==========================================
# EDITOR MENUS
# ==========================================

def editor_load_map(self):
    """Opens a file dialog to load a map folder directly into the editor."""
    root = queries.get_transient_tk_root()
    path = filedialog.askdirectory(initialdir=c.SCENARIOS_CUSTOM_DIR, title="Select Map Folder to Edit")
    queries.destroy_tk_root(root)

    if path:
        load_map.load_map_assets(self, path)
        self.refresh_political_map()
        self.show_feedback("Map Loaded into Editor")

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
    """Opens a Tkinter window listing every claim on the map."""
    root, close_menu = queries.create_managed_tk_window(self, "Global Claims Overview", "600x500")

    style = ttk.Style(root)
    try:
        style.theme_use("clam") 
    except:
        pass 
        
    style.configure("Treeview.Heading", 
                    background="#d9e1f2", 
                    font=('Arial', 10, 'bold'),
                    relief="flat")
                    
    style.configure("Treeview", 
                    background="#ffffff",
                    fieldbackground="#ffffff",
                    rowheight=28,
                    font=('Arial', 10))
                    
    columns = ("Country", "Claimed Provinces")
    tree = ttk.Treeview(root, columns=columns, show="headings")
    
    tree.heading("Country", text="Country")
    tree.heading("Claimed Provinces", text="Claimed Provinces")
    tree.column("Country", width=150, anchor="w")
    tree.column("Claimed Provinces", width=420, anchor="w")

    tree.tag_configure('evenrow', background='#ffffff')
    tree.tag_configure('oddrow', background='#f2f2f2') 

    row_idx = 0
    for c_name in sorted(list(self.nation_data.keys())):
        claims = self.nation_data[c_name].get("claims", [])
        if claims:
            claims_str = ", ".join(map(str, claims))
            tag = 'evenrow' if row_idx % 2 == 0 else 'oddrow'
            tree.insert("", tk.END, values=(c_name, claims_str), tags=(tag,))
            row_idx += 1

    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    tree.configure(yscroll=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)

    queries.run_tk_loop(self, root)

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
    """Opens a Tkinter window to edit the game's starting date."""
    root, close_menu = queries.create_managed_tk_window(self, "Set Start Date", "250x350")

    tk.Label(root, text="Day (1-30):", font=("Arial", 10)).pack(pady=(10, 2))
    day_ent = tk.Entry(root, justify="center")
    day_ent.insert(0, str(self.time_manager.day))
    day_ent.pack()

    # We add 1 for the UI since month_index is 0-11 in the backend
    tk.Label(root, text="Month (1-12):", font=("Arial", 10)).pack(pady=(10, 2))
    month_ent = tk.Entry(root, justify="center")
    month_ent.insert(0, str(self.time_manager.month_index + 1))
    month_ent.pack()

    tk.Label(root, text="Year:", font=("Arial", 10)).pack(pady=(10, 2))
    year_ent = tk.Entry(root, justify="center")
    year_ent.insert(0, str(self.time_manager.year))
    year_ent.pack()

    tk.Label(root, text="Base Days Per Turn:", font=("Arial", 10)).pack(pady=(10, 2))
    dpt_ent = tk.Entry(root, justify="center")
    dpt_ent.insert(0, str(queries.get_days_per_turn(self.scenario_settings)))
    dpt_ent.pack()

    def apply_date():
        try:
            d = int(day_ent.get())
            m = int(month_ent.get()) - 1
            y = int(year_ent.get())
            b_dpt = int(dpt_ent.get())
            
            if not (1 <= d <= 30):
                messagebox.showerror("Error", "Day must be between 1 and 30.")
                return
            if not (0 <= m <= 11):
                messagebox.showerror("Error", "Month must be between 1 and 12.")
                return
            if b_dpt <= 0:
                messagebox.showerror("Error", "Days per turn must be positive.")
                return
                
            self.time_manager.day = d
            self.time_manager.month_index = m
            self.time_manager.year = y
            self.scenario_settings["base_days_per_turn"] = b_dpt
            self.scenario_settings["days_per_turn"] = "Default"
            
            queries.save_scenario_settings(self.scenario_settings)
            self.show_feedback(f"Date & Turn Rate set!")
            close_menu()
        except ValueError:
            messagebox.showerror("Error", "Please enter valid integers.")

    tk.Button(root, text="Apply Date", command=apply_date, bg="#FF9800", fg="black", pady=5).pack(pady=15, fill="x", padx=20)
    queries.run_tk_loop(self, root)


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
    """Opens a UI to edit starting resources for countries currently existing on the map."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root, close_menu = queries.create_managed_tk_window(self, "Map Economy Editor", "350x500")

    tk.Label(root, text="Select Country to Edit:", font=("Arial", 12)).pack(pady=5)
    
    lb = tk.Listbox(root, font=("Arial", 11))
    
    def populate_listbox():
        lb.delete(0, tk.END)
        for cid in sorted(active_countries):
            c_data = self.nation_data.get(cid, {})
            is_modified = any(c_data.get(res, 0) != 0 for res in c.ECON_RESOURCE_KEYS)
            prefix = "[MODIFIED] " if is_modified else ""
            lb.insert(tk.END, f"{prefix}{cid}")

    populate_listbox()
    lb.pack(fill="both", expand=True, padx=10, pady=5)

    def open_edit_window(target_country):
        actual_name = target_country.replace("[MODIFIED] ", "")
        base_data = {
            "manpower": self.nation_data.get(actual_name, {}).get("manpower", 0),
            "materials": self.nation_data.get(actual_name, {}).get("materials", 0),
            "fuel": self.nation_data.get(actual_name, {}).get("fuel", 0)
        }
        
        edit_win = tk.Toplevel(root)
        edit_win.title(f"{actual_name} Starting Economy")
        edit_win.geometry("250x250")
        edit_win.attributes("-topmost", True)
        
        entries = {}
        for i, res in enumerate(c.ECON_RESOURCE_KEYS):
            tk.Label(edit_win, text=res.capitalize()).grid(row=i, column=0, sticky="e", padx=5, pady=5)
            ent = tk.Entry(edit_win, width=10)
            ent.insert(0, str(int(base_data[res])))
            ent.grid(row=i, column=1, pady=5)
            entries[res] = ent
            
        def save_econ():
            new_data = {}
            for res, ent in entries.items():
                try:
                    new_data[res] = int(ent.get())
                except ValueError: 
                    new_data[res] = base_data[res]
            
            if actual_name in self.nation_data:
                for res, val in new_data.items():
                    self.nation_data[actual_name][res] = val
                self.show_feedback(f"Saved economy for {actual_name}")
            
            populate_listbox()
            edit_win.destroy()
            
        tk.Button(edit_win, text="Save Economy", command=save_econ, bg="#4CAF50", fg="white").grid(row=3, column=0, columnspan=2, pady=15)

    def edit_selected():
        sel = lb.curselection()
        if not sel: return
        open_edit_window(lb.get(sel[0]))

    def reset_all():
        if messagebox.askyesno("Confirm Reset", "Are you sure you want to reset every starting economy to 0?"):
            for cid in active_countries:
                if cid in self.nation_data:
                    for res in c.ECON_RESOURCE_KEYS:
                        self.nation_data[cid][res] = 0
            self.show_feedback("Reset starting economy for all nations!")
            populate_listbox()
            close_menu()

    tk.Button(root, text="Edit Selected Nation", command=edit_selected, bg="#2196F3", fg="white", pady=5).pack(fill="x", padx=10, pady=5)
    tk.Button(root, text="Reset All to 0", command=reset_all, bg="#f44336", fg="white", pady=5).pack(fill="x", padx=10, pady=5)

    queries.run_tk_loop(self, root)
        
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
    """Opens a UI to edit research for countries currently existing on the map."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    def get_default_research():
        struct = queries.get_tech_tree()
        fresh_template = {tech: (1800 if data["max_lvl"] == 9999 else 0) for tech, data in struct.items()}
            
        if "infantry_type" in fresh_template: fresh_template["infantry_type"] = 1
        if "cavalry" in fresh_template: fresh_template["cavalry"] = 1

        if getattr(self, "default_research", None) is not None:
            for k, v in fresh_template.items():
                if k not in self.default_research:
                    self.default_research[k] = v
            
            obsolete_keys = [k for k in self.default_research.keys() if k not in fresh_template]
            for k in obsolete_keys:
                del self.default_research[k]
                
            return self.default_research

        return fresh_template

    default_res = get_default_research()

    root, close_menu = queries.create_managed_tk_window(self, "Map Tech Editor", "350x560")

    tk.Label(root, text="Select Country to Edit:", font=("Arial", 12)).pack(pady=5)
    
    lb = tk.Listbox(root, font=("Arial", 11))
    
    def populate_listbox():
        lb.delete(0, tk.END)
        for c_name in sorted(active_countries):
            c_res = self.nation_data.get(c_name, {}).get("research", {})
            is_diff = False
            for k, v in default_res.items():
                if c_res.get(k, v) != v:
                    is_diff = True
                    break
            prefix = "[MODIFIED] " if is_diff else ""
            lb.insert(tk.END, f"{prefix}{c_name}")

    populate_listbox()
    lb.pack(fill="both", expand=True, padx=10, pady=5)

    def open_edit_window(target_country, is_bulk=False, is_default_only=False):
        if is_bulk or is_default_only:
            base_data = default_res.copy()
        else:
            actual_name = target_country.replace("[MODIFIED] ", "") 
            base_data = self.nation_data.get(actual_name, {}).get("research", default_res.copy())
        
        for k, v in default_res.items():
            if k not in base_data:
                base_data[k] = v

        edit_win = tk.Toplevel(root)
        title_text = "MAP DEFAULT" if is_default_only else ("ALL COUNTRIES" if is_bulk else actual_name)
        edit_win.title(f"{title_text} Research")
        edit_win.geometry("600x1000")
        edit_win.attributes("-topmost", True)
        
        canvas = tk.Canvas(edit_win)
        scrollbar = tk.Scrollbar(edit_win, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, pady=5)
        scrollbar.pack(side="right", fill="y")
        
        tech_tree = queries.get_tech_tree()

        entries = {}
        for i, tech in enumerate(sorted(base_data.keys())):
            tk.Label(scroll_frame, text=tech.replace("_", " ").title()).grid(row=i, column=0, sticky="e", padx=5)

            # Single-level techs are a yes/no toggle, not a numeric level.
            if tech_tree.get(tech, {}).get("max_lvl", 1) == 1:
                var = tk.IntVar(value=1 if base_data[tech] >= 1 else 0)
                chk = tk.Checkbutton(scroll_frame, variable=var)
                chk.grid(row=i, column=1, pady=2)
                entries[tech] = ("checkbox", var)
            else:
                max_lvl = tech_tree.get(tech, {}).get("max_lvl", 1)
                ent = tk.Entry(scroll_frame, width=8)
                ent.insert(0, str(base_data[tech]))
                ent.grid(row=i, column=1, pady=2)
                tk.Label(scroll_frame, text=f"(0-{max_lvl})", fg="grey").grid(row=i, column=2, sticky="w", padx=5)
                entries[tech] = ("entry", ent, max_lvl)

        def save_res():
            nonlocal default_res
            new_data = {}
            for tech, entry in entries.items():
                if entry[0] == "checkbox":
                    new_data[tech] = entry[1].get()
                else:
                    _, widget, max_lvl = entry
                    try:
                        val = int(widget.get())
                    except ValueError:
                        val = base_data.get(tech, 0)
                    new_data[tech] = max(0, min(val, max_lvl))
            
            if is_default_only:
                self.default_research = new_data.copy()
                default_res = new_data.copy()
                self.show_feedback("Updated Map Default Tech")
            elif is_bulk:
                self.default_research = new_data.copy()
                default_res = new_data.copy()
                for c_name in active_countries:
                    if "research" not in self.nation_data[c_name]:
                        self.nation_data[c_name]["research"] = {}
                    self.nation_data[c_name]["research"].update(new_data)
                self.show_feedback("Saved research for ALL & Set Default")
            else:
                if "research" not in self.nation_data[actual_name]:
                    self.nation_data[actual_name]["research"] = {}
                self.nation_data[actual_name]["research"].update(new_data)
                self.show_feedback(f"Saved research for {actual_name}")
            
            populate_listbox()
            edit_win.destroy()
            
        tk.Button(edit_win, text="Save Tech Levels", command=save_res, bg="#4CAF50", fg="white").pack(side="bottom", fill="x", pady=5)

    def edit_selected():
        sel = lb.curselection()
        if not sel: return
        open_edit_window(lb.get(sel[0]), is_bulk=False)

    def edit_all():
        open_edit_window(None, is_bulk=True)

    def edit_default_only():
        open_edit_window(None, is_default_only=True)

    def force_time_appropriate_research():
        nonlocal default_res
        current_year = getattr(self.time_manager, "year", c.START_YEAR)
        msg = (
            f"This will reset and edit the research of ALL nations on the map to match "
            f"the time-appropriate research levels for year {current_year} (the current year of this map), "
            f"exactly as if a random scenario was created in {current_year}.\n\n"
            f"Are you sure you want to force time-appropriate research for all nations?"
        )
        if not messagebox.askyesno("Force Time Appropriate Research", msg, parent=root):
            return

        time_app_res = queries.get_time_appropriate_research(current_year)
        self.default_research = time_app_res.copy()
        default_res = time_app_res.copy()

        for c_name in active_countries:
            if "research" not in self.nation_data[c_name]:
                self.nation_data[c_name]["research"] = {}
            self.nation_data[c_name]["research"] = time_app_res.copy()

        populate_listbox()
        self.show_feedback(f"Forced Time Appropriate Research for {current_year}")

    tk.Button(root, text="Edit Selected Nation", command=edit_selected, bg="#2196F3", fg="white", pady=5).pack(fill="x", padx=10, pady=2)
    tk.Button(root, text="Edit ALL Nations (Bulk)", command=edit_all, bg="#f44336", fg="white", pady=5).pack(fill="x", padx=10, pady=2)
    tk.Button(root, text="Edit Map Default Tech", command=edit_default_only, bg="#FF9800", fg="white", pady=5).pack(fill="x", padx=10, pady=5)
    tk.Button(root, text="Force Time Appropriate Research", command=force_time_appropriate_research, bg="#4CAF50", fg="white", pady=5).pack(fill="x", padx=10, pady=5)

    queries.run_tk_loop(self, root)

def select_unit_brush(self):
    """Opens a selection window for unit types and sets mode to UNIT."""
    items = ["None", "Convoy", "----------"] + list(queries.get_unit_library().keys())
    _select_brush(self, "UNIT", "brush_unit", items,
                  "Select Unit", "Select Unit to Place:")

def open_convoy_converter(self, province):
    """Opens a Tkinter window to select which units on a tile should be converted to convoys/trucks."""
    units = province.get("units", [])
    if not units:
        self.show_feedback("No units on tile to convert!")
        return

    root, close_menu = queries.create_managed_tk_window(self, "Convert Units", "600x600")

    tk.Label(root, text="Select Units to Convert:", font=("Arial", 12, "bold")).pack(pady=10)
    
    canvas = tk.Canvas(root)
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
    scroll_frame = tk.Frame(canvas)
    
    scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    canvas.pack(side="left", fill="both", expand=True, padx=10, pady=5)
    scrollbar.pack(side="right", fill="y")

    vars_list = []
    unit_lib = queries.get_unit_library()
    
    for i, unit in enumerate(units):
        is_convoyed = "original_type" in unit
        var = tk.BooleanVar(value=is_convoyed)
        vars_list.append((unit, var))
        
        # Display the real underlying unit name
        name = unit.get("original_type", unit.get("type", "Unknown"))
        health = unit.get("health", 100)
        
        # Check if it's a naval unit
        is_naval = unit_lib.get(name, {}).get("naval_unit", False)
        label_text = f"{name} (Convoy)" if not is_naval else f"{name} (Truck)"
        
        cb = tk.Checkbutton(scroll_frame, text=label_text, variable=var, font=("Arial", 10))
        cb.grid(row=i, column=0, sticky="w", pady=2)
        
    def save_changes():
        for unit, var in vars_list:
            if var.get() and "original_type" not in unit:
                # Need to convert to Convoy/Truck
                name = unit.get("type", "Unknown")
                is_naval = unit_lib.get(name, {}).get("naval_unit", False)
                target = "Convoy" if not is_naval else "Truck"
                
                unit["original_type"] = unit["type"]
                unit["original_speed"] = unit.get("speed", 1)
                unit["original_max_health"] = unit.get("max_health", c.DEFAULT_UNIT_HP)
                unit["original_attack"] = unit.get("attack", c.DEFAULT_UNIT_ATK)
                
                pct = unit.get("health", 1) / max(1, unit.get("max_health", 1))
                
                unit["type"] = f"{target} ({unit['type']})"
                unit["speed"] = 1
                
                if target == "Convoy":
                    unit["naval_unit"] = True
                    unit["max_health"] = c.CONVOY_MAX_HP
                    unit["attack"] = c.CONVOY_ATK
                else:
                    unit["naval_unit"] = False
                    unit["max_health"] = c.TRUCK_MAX_HP
                    unit["attack"] = c.TRUCK_ATK
                    
                unit["health"] = unit["max_health"] * pct
                
            elif not var.get() and "original_type" in unit:
                # Need to revert
                queries.revert_transport(unit)
                
        self.show_feedback("Unit transport status updated!")
        close_menu()
        
    tk.Button(root, text="Save Changes", command=save_changes, bg="#4CAF50", fg="white", font=("Arial", 11, "bold")).pack(side="bottom", fill="x", pady=10, padx=20)

    queries.run_tk_loop(self, root)

def select_resource_brush(self):
    """Opens a selection window for resource types and amounts."""
    root, close_menu = queries.create_managed_tk_window(self, "Resource Brush", "300x250")

    tk.Label(root, text="Select Resource Type:", font=("Arial", 12)).pack(pady=10)
    
    dropdown = ttk.Combobox(root, values=["Iron", "Coal", "Oil", "Wheat", "None"], state="readonly", font=("Arial", 11))
    dropdown.set("Iron") 
    dropdown.pack(pady=5)

    tk.Label(root, text="Resource Amount:", font=("Arial", 12)).pack(pady=5)
    amt_ent = tk.Entry(root, font=("Arial", 11), justify="center")
    amt_ent.insert(0, "50")
    amt_ent.pack(pady=5)

    def on_confirm():
        try:
            amt = int(amt_ent.get())
            self.brush_resource_type = dropdown.get() 
            self.brush_resource_amount = amt
            self.editor_mode = "RESOURCE"
            
            if self.brush_resource_type == "None":
                self.show_feedback("Brush: Erase Resources")
            else:
                self.show_feedback(f"Brush: {self.brush_resource_type} ({amt})")
                
            close_menu()
        except ValueError:
            messagebox.showerror("Error", "Amount must be a whole number.")

    tk.Button(root, text="Confirm Selection", command=on_confirm, 
              bg="#9C27B0", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=15)

    queries.run_tk_loop(self, root)

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
    """Opens a Tkinter window to clear items from the map based on various criteria."""
    root, close_menu = queries.create_managed_tk_window(self, "Clear Map Items", "450x350")
    
    options = [
        "all units",
        "all buildings",
        "all resources",
        "all units from (x) country",
        "all buildings on (x) countries territory",
        "all resources on (x) countries territory",
        "all (x) units",
        "all (x) resources",
        "all (x) units from country (x)",
        "all (x) resources on (x) countries territory"
    ]
    
    tk.Label(root, text="Select what to clear:", font=("Arial", 12, "bold")).pack(pady=5)
    
    option_var = tk.StringVar(value=options[0])
    option_menu = ttk.Combobox(root, textvariable=option_var, values=options, state="readonly", width=45)
    option_menu.pack(pady=5)
    
    country_var = tk.StringVar()
    unit_type_var = tk.StringVar()
    resource_type_var = tk.StringVar()
    
    param_frame = tk.Frame(root)
    param_frame.pack(fill="x", padx=20, pady=10)
    
    country_lbl = tk.Label(param_frame, text="Country:")
    
    existing_owners = {p.get("owner") for p in self.map_data.values()}
    active_countries = sorted([n for n in existing_owners if n and n not in ["Unclaimed", "The Rot"]])
    
    country_cb = ttk.Combobox(param_frame, textvariable=country_var, values=active_countries, state="readonly", width=25)
    
    unit_lbl = tk.Label(param_frame, text="Unit Type:")
    
    existing_unit_types = set()
    for prov in self.map_data.values():
        for unit in prov.get("units", []):
            if "type" in unit:
                existing_unit_types.add(unit["type"])
    unit_types = sorted(list(existing_unit_types))
    
    unit_cb = ttk.Combobox(param_frame, textvariable=unit_type_var, values=unit_types, state="readonly", width=25)
    
    resource_lbl = tk.Label(param_frame, text="Resource:")
    resource_types = ["Iron", "Coal", "Oil", "Wheat"]
    resource_cb = ttk.Combobox(param_frame, textvariable=resource_type_var, values=resource_types, state="readonly", width=25)
    
    def update_visibility(*args):
        opt = option_var.get()
        
        country_lbl.grid_forget()
        country_cb.grid_forget()
        unit_lbl.grid_forget()
        unit_cb.grid_forget()
        resource_lbl.grid_forget()
        resource_cb.grid_forget()
        
        row = 0
        if "country" in opt or "countries" in opt:
            country_lbl.grid(row=row, column=0, sticky="e", pady=2, padx=5)
            country_cb.grid(row=row, column=1, sticky="w", pady=2)
            if not country_var.get() and active_countries:
                country_cb.set(active_countries[0])
            row += 1
            
        if "unit" in opt and "(x)" in opt:
            if opt in ["all (x) units", "all (x) units from country (x)"]:
                unit_lbl.grid(row=row, column=0, sticky="e", pady=2, padx=5)
                unit_cb.grid(row=row, column=1, sticky="w", pady=2)
                if not unit_type_var.get() and unit_types:
                    unit_cb.set(unit_types[0])
                row += 1
                
        if "resource" in opt and "(x)" in opt:
            if opt in ["all (x) resources", "all (x) resources on (x) countries territory"]:
                resource_lbl.grid(row=row, column=0, sticky="e", pady=2, padx=5)
                resource_cb.grid(row=row, column=1, sticky="w", pady=2)
                if not resource_type_var.get() and resource_types:
                    resource_cb.set(resource_types[0])
                row += 1

    option_var.trace_add("write", update_visibility)
    update_visibility()
    
    def confirm_clear():
        opt = option_var.get()
        c_val = country_var.get()
        u_val = unit_type_var.get()
        r_val = resource_type_var.get()
        
        if ("country" in opt or "countries" in opt) and not c_val:
            messagebox.showerror("Error", "Please select a country.")
            return
        if opt in ["all (x) units", "all (x) units from country (x)"] and not u_val:
            messagebox.showerror("Error", "Please select a unit type.")
            return
        if opt in ["all (x) resources", "all (x) resources on (x) countries territory"] and not r_val:
            messagebox.showerror("Error", "Please select a resource type.")
            return
            
        msg = f"Are you sure you want to clear:\n{opt}"
        if c_val and ("country" in opt or "countries" in opt): msg += f"\nCountry: {c_val}"
        if u_val and opt in ["all (x) units", "all (x) units from country (x)"]: msg += f"\nUnit: {u_val}"
        if r_val and opt in ["all (x) resources", "all (x) resources on (x) countries territory"]: msg += f"\nResource: {r_val}"
            
        if not messagebox.askyesno("Confirm Clear", msg):
            return
            
        for prov_id, prov_data in self.map_data.items():
            owner = prov_data.get("owner", "Unclaimed")
            
            if "countries territory" in opt and owner != c_val:
                continue
                
            if "units" in opt:
                if opt in ["all units", "all units from (x) country"]:
                    if opt == "all units from (x) country":
                        prov_data["units"] = [u for u in prov_data.get("units", []) if u.get("owner") != c_val]
                    else:
                        prov_data["units"] = []
                elif opt == "all (x) units":
                    prov_data["units"] = [u for u in prov_data.get("units", []) if u.get("type") != u_val]
                elif opt == "all (x) units from country (x)":
                    prov_data["units"] = [u for u in prov_data.get("units", []) if not (u.get("type") == u_val and u.get("owner") == c_val)]
                    
            if "buildings" in opt:
                prov_data["buildings"] = []
                
            if "resources" in opt:
                if opt in ["all resources", "all resources on (x) countries territory"]:
                    prov_data["resources"] = {}
                    if "resource" in prov_data:
                        del prov_data["resource"]
                elif opt in ["all (x) resources", "all (x) resources on (x) countries territory"]:
                    if isinstance(prov_data.get("resources"), dict) and r_val in prov_data["resources"]:
                        del prov_data["resources"][r_val]
                    if prov_data.get("resource", {}).get("type") == r_val:
                        del prov_data["resource"]
                        
        self.refresh_all_maps()
        self.show_feedback("Map cleared according to criteria.")
        close_menu()

    tk.Button(root, text="Confirm Clear", command=confirm_clear, bg="#f44336", fg="white", font=("Arial", 11, "bold")).pack(side="bottom", fill="x", pady=20, padx=20)
    
    queries.run_tk_loop(self, root)