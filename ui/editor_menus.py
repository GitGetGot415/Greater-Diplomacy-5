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

def select_brush_nation(self):
    """Opens a Tkinter selection window and sets mode to NATION."""
    nations = sorted(list(self.nation_data.keys()), key=lambda k: unicodedata.normalize('NFKD', k).encode('ascii', 'ignore').decode('utf-8').lower())
    items = ["Unclaimed", "The Rot", "----------"] + [n for n in nations if n not in ["Unclaimed", "The Rot"] and (n not in c.UNPLAYABLE_NATIONS or n == "None")]
    def cb(val):
        self.brush_nation = val
        self.editor_mode = "NATION" 
        self.show_feedback(f"Brush: {self.brush_nation}")
    queries.open_listbox_selector(self, "Select Nation", "Select Paint Nation:", items, cb)

def select_core_brush(self):
    """Opens a Tkinter selection window and sets mode to CORE."""
    nations = sorted(list(self.nation_data.keys()), key=lambda k: unicodedata.normalize('NFKD', k).encode('ascii', 'ignore').decode('utf-8').lower())
    items = ["Unclaimed", "The Rot", "----------"] + [n for n in nations if n not in ["Unclaimed", "The Rot"] and (n not in c.UNPLAYABLE_NATIONS or n == "None")]
    def cb(val):
        self.brush_nation = val
        self.editor_mode = "CORE" 
        self.show_feedback(f"Core Brush: {self.brush_nation}")
    queries.open_listbox_selector(self, "Select Core Nation", "Select Nation to Add Cores:", items, cb)

def select_claim_brush(self):
    """Opens a Tkinter selection window and sets mode to CLAIM."""
    nations = sorted(list(self.nation_data.keys()), key=lambda k: unicodedata.normalize('NFKD', k).encode('ascii', 'ignore').decode('utf-8').lower())
    items = ["Unclaimed", "The Rot", "----------"] + [n for n in nations if n not in ["Unclaimed", "The Rot"] and (n not in c.UNPLAYABLE_NATIONS or n == "None")]
    def cb(val):
        self.brush_nation = val
        self.editor_mode = "CLAIM" 
        self.show_feedback(f"Claim Brush: {self.brush_nation}")
    queries.open_listbox_selector(self, "Select Claim Nation", "Select Nation to Add Claims:", items, cb)

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
    def cb(val):
        self.brush_building = val
        self.editor_mode = "BUILDING"
        self.show_feedback(f"Brush: {self.brush_building}")
    queries.open_listbox_selector(self, "Select Building", "Select Building to Place:", items, cb)

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
    """Opens a Tkinter window listing the detailed income of every active country."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root, close_menu = queries.create_managed_tk_window(self, "Global Economy Overview", "1200x500")

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
                    
    all_econ = queries.calculate_all_economies(self.map_data, self.nation_data)

    columns = (
        "Country", 
        "|1", "P_Cur", "P_Inc", "P_Bld", "P_Upk", "P_Net", 
        "|2", "M_Cur", "M_Inc", "M_Bld", "M_Upk", "M_Net", 
        "|3", "F_Cur", "F_Inc", "F_Bld", "F_Upk", "F_Net", 
        "|4"
    )
    
    tree = ttk.Treeview(root, columns=columns, show="headings")
    tree.tag_configure('evenrow', background='#ffffff')
    tree.tag_configure('oddrow', background='#f2f2f2') 
    
    sort_dirs = {col: True for col in columns}

    def sort_data(col):
        reverse = sort_dirs[col]
        sort_dirs[col] = not reverse 
        
        def get_val(c):
            if c not in all_econ: return 0
            d = all_econ[c]
            if col == "Country": return c
            if col.startswith("|"): return 0
            
            res_key = "manpower" if col.startswith("P_") else ("materials" if col.startswith("M_") else "fuel")
            stat_type = col.split("_")[1]
            bd = d["breakdown"][res_key]
            
            if stat_type == "Cur": return self.nation_data.get(c, {}).get(res_key, 0)
            if stat_type == "Inc": return bd["core"] + bd["non_core"] + bd["resources"]
            if stat_type == "Bld": return bd["buildings"]
            if stat_type == "Upk": return d["upkeep"][res_key]
            if stat_type == "Net": return d["total_inc"][res_key] - d["upkeep"][res_key]
            
            return 0

        sorted_countries = sorted(active_countries, key=get_val, reverse=reverse)
        
        for item in tree.get_children():
            tree.delete(item)
            
        populate_tree(sorted_countries)

    widths = {
        "Country": 130,
        "|1": 20, "P_Cur": 55, "P_Inc": 55, "P_Bld": 55, "P_Upk": 55, "P_Net": 55,
        "|2": 20, "M_Cur": 55, "M_Inc": 55, "M_Bld": 55, "M_Upk": 55, "M_Net": 55,
        "|3": 20, "F_Cur": 55, "F_Inc": 55, "F_Bld": 55, "F_Upk": 55, "F_Net": 55,
        "|4": 20
    }

    for col in columns:
        heading_text = "|" if col.startswith("|") else col
        tree.heading(col, text=heading_text, command=lambda c=col: sort_data(c))
        tree.column(col, width=widths[col], anchor="center")
        
    def populate_tree(country_list):
        for i, c in enumerate(country_list):
            if c not in all_econ: continue
            d = all_econ[c]
            n_data = self.nation_data.get(c, {})
            
            def get_stats(res_key):
                bd = d["breakdown"][res_key]
                cur = int(n_data.get(res_key, 0))
                inc = int(bd["core"] + bd["non_core"] + bd["resources"])
                bld = int(bd["buildings"])
                upk = int(d["upkeep"][res_key])
                net = int(d["total_inc"][res_key] - d["upkeep"][res_key])
                return cur, inc, bld, upk, net

            p_cur, p_inc, p_bld, p_upk, p_net = get_stats("manpower")
            m_cur, m_inc, m_bld, m_upk, m_net = get_stats("materials")
            f_cur, f_inc, f_bld, f_upk, f_net = get_stats("fuel")
                        
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            tree.insert("", tk.END, values=(
                c, 
                "|", p_cur, p_inc, p_bld, p_upk, p_net, 
                "|", m_cur, m_inc, m_bld, m_upk, m_net, 
                "|", f_cur, f_inc, f_bld, f_upk, f_net,
                "|"
            ), tags=(tag,))

    populate_tree(sorted(active_countries))

    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    tree.configure(yscroll=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)

    queries.run_tk_loop(self, root)
        
def open_spectator_messages(self):
    """Opens a Tkinter window listing all messages sent between active countries."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root, close_menu = queries.create_managed_tk_window(self, "Global Messages Overview", "1100x500")

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

    columns = ("Date", "Sender", "Receiver", "Type", "Message")
    tree = ttk.Treeview(root, columns=columns, show="headings")
    
    tree.tag_configure('evenrow', background='#ffffff')
    tree.tag_configure('oddrow', background='#f2f2f2') 

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
                        "sender": sender,
                        "receiver": c_name,
                        "type": msg.get("type", "TEXT"),
                        "content": msg.get("content", ""),
                        "sort_val": sort_val
                    })

    sort_dirs = {col: True for col in columns}

    def sort_data(col):
        reverse = sort_dirs[col]
        sort_dirs[col] = not reverse 
        
        def get_val(m):
            if col == "Date": return m["sort_val"]
            if col == "Sender": return m["sender"]
            if col == "Receiver": return m["receiver"]
            if col == "Type": return m["type"]
            if col == "Message": return m["content"]
            return 0

        sorted_msgs = sorted(all_msgs, key=get_val, reverse=reverse)
        for item in tree.get_children():
            tree.delete(item)
        populate_tree(sorted_msgs)

    for col in columns:
        tree.heading(col, text=col, command=lambda c=col: sort_data(c))

    tree.column("Date", width=130, anchor="center")
    tree.column("Sender", width=120, anchor="center")
    tree.column("Receiver", width=120, anchor="center")
    tree.column("Type", width=100, anchor="center")
    tree.column("Message", width=550, anchor="w")

    def populate_tree(msg_list):
        for row_idx, m in enumerate(msg_list):
            tag = 'evenrow' if row_idx % 2 == 0 else 'oddrow'
            tree.insert("", tk.END, values=(
                m["date"],
                m["sender"],
                m["receiver"],
                m["type"],
                m["content"]
            ), tags=(tag,))

    populate_tree(sorted(all_msgs, key=lambda x: x["sort_val"], reverse=True))

    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    tree.configure(yscroll=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)

    queries.run_tk_loop(self, root)

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

    root, close_menu = queries.create_managed_tk_window(self, "Map Tech Editor", "350x500")

    tk.Label(root, text="Select Country to Edit:", font=("Arial", 12)).pack(pady=5)
    
    lb = tk.Listbox(root, font=("Arial", 11))
    
    def populate_listbox():
        lb.delete(0, tk.END)
        for c in sorted(active_countries):
            c_res = self.nation_data.get(c, {}).get("research", {})
            is_diff = False
            for k, v in default_res.items():
                if c_res.get(k, v) != v:
                    is_diff = True
                    break
            prefix = "[MODIFIED] " if is_diff else ""
            lb.insert(tk.END, f"{prefix}{c}")

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
        edit_win.geometry("300x500")
        edit_win.attributes("-topmost", True)
        
        canvas = tk.Canvas(edit_win)
        scrollbar = tk.Scrollbar(edit_win, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, pady=5)
        scrollbar.pack(side="right", fill="y")
        
        entries = {}
        for i, tech in enumerate(sorted(base_data.keys())):
            tk.Label(scroll_frame, text=tech.replace("_", " ").title()).grid(row=i, column=0, sticky="e", padx=5)
            ent = tk.Entry(scroll_frame, width=8)
            ent.insert(0, str(base_data[tech]))
            ent.grid(row=i, column=1, pady=2)
            entries[tech] = ent
            
        def save_res():
            nonlocal default_res
            new_data = {}
            for tech, ent in entries.items():
                try:
                    new_data[tech] = int(ent.get())
                except ValueError: 
                    new_data[tech] = base_data.get(tech, 0)
            
            if is_default_only:
                self.default_research = new_data.copy()
                default_res = new_data.copy()
                self.show_feedback("Updated Map Default Tech")
            elif is_bulk:
                self.default_research = new_data.copy()
                default_res = new_data.copy()
                for c in active_countries:
                    if "research" not in self.nation_data[c]:
                        self.nation_data[c]["research"] = {}
                    self.nation_data[c]["research"].update(new_data)
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

    tk.Button(root, text="Edit Selected Nation", command=edit_selected, bg="#2196F3", fg="white", pady=5).pack(fill="x", padx=10, pady=2)
    tk.Button(root, text="Edit ALL Nations (Bulk)", command=edit_all, bg="#f44336", fg="white", pady=5).pack(fill="x", padx=10, pady=2)
    tk.Button(root, text="Edit Map Default Tech", command=edit_default_only, bg="#FF9800", fg="white", pady=5).pack(fill="x", padx=10, pady=5)

    queries.run_tk_loop(self, root)

def select_unit_brush(self):
    """Opens a selection window for unit types and sets mode to UNIT."""
    items = ["None"] + list(queries.get_unit_library().keys())
    def cb(val):
        self.brush_unit = val
        self.editor_mode = "UNIT"
        self.show_feedback(f"Brush: {self.brush_unit}")
    queries.open_listbox_selector(self, "Select Unit", "Select Unit to Place:", items, cb)

def select_resource_brush(self):
    """Opens a selection window for resource types and amounts."""
    root, close_menu = queries.create_managed_tk_window(self, "Resource Brush", "300x250")

    tk.Label(root, text="Select Resource Type:", font=("Arial", 12)).pack(pady=10)
    
    dropdown = ttk.Combobox(root, values=["Iron", "Coal", "Oil", "None"], state="readonly", font=("Arial", 11))
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

        self.refresh_relations_map()
        self.refresh_factions_map()
        self.show_feedback(f"Diplomacy saved for {target}")

    tk.Button(right_frame, text="Save Changes", command=save_changes, bg="#4CAF50", fg="white", font=("Arial", 12, "bold")).pack(pady=10, fill="x")

    queries.run_tk_loop(self, root)

def open_edited_countries(self):
    """Opens a Tkinter window listing countries with edited properties."""
    from data.io import country_io
    default_data = country_io.load_all_country_data()
    
    edited_list = []
    for c_id, current_data in self.nation_data.items():
        if c_id in ["Unclaimed", "Ocean", "Lakes", "The Rot", "Spectator", "GLOBAL_EVENTS", "FACTION_WAR_MAPS"]:
            continue
            
        def_country = default_data.get(c_id, {})
        changes = {}
        
        # Tracking what differs from default
        c_name = current_data.get("name", c_id)
        d_name = def_country.get("name", c_id)
        if c_name != d_name: changes["Name"] = c_name
        
        c_leader = current_data.get("leader_name", "")
        d_leader = def_country.get("leader_name", "")
        if c_leader != d_leader: changes["Leader Name"] = c_leader
        
        c_title = current_data.get("leader_title", "")
        d_title = def_country.get("leader_title", "")
        if c_title != d_title: changes["Leader Title"] = c_title
        
        c_flag = current_data.get("flag_data", "DEFAULT")
        if c_flag != "DEFAULT": changes["Flag"] = "CUSTOM"
        
        c_port = current_data.get("portrait_data", "DEFAULT")
        if c_port != "DEFAULT": changes["Portrait"] = "CUSTOM"
        
        if changes:
            edited_list.append((c_id, changes))
            
    root, close_menu = queries.create_managed_tk_window(self, "Edited Countries Overview", "900x500")
    
    style = ttk.Style(root)
    try: style.theme_use("clam")
    except: pass
    
    style.configure("Treeview.Heading", background="#d9e1f2", font=('Arial', 10, 'bold'), relief="flat")
    style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", rowheight=28, font=('Arial', 10))
    
    columns = ("ID", "Name", "Leader Name", "Leader Title", "Flag", "Portrait")
    tree = ttk.Treeview(root, columns=columns, show="headings")
    
    for col in columns:
        tree.heading(col, text=col)
        tree.column(col, anchor="center", width=140)
        
    tree.tag_configure('evenrow', background='#ffffff')
    tree.tag_configure('oddrow', background='#f2f2f2')
    
    for i, (c_id, changes) in enumerate(edited_list):
        tag = 'evenrow' if i % 2 == 0 else 'oddrow'
        tree.insert("", tk.END, values=(
            c_id,
            changes.get("Name", "-"),
            changes.get("Leader Name", "-"),
            changes.get("Leader Title", "-"),
            changes.get("Flag", "-"),
            changes.get("Portrait", "-")
        ), tags=(tag,))
        
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    tree.configure(yscroll=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)
    
    queries.run_tk_loop(self, root)