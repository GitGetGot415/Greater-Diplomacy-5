import pygame
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import unicodedata #
import data.constants as c
from data.map import load_map
from data import queries
from map_logic.diplomacy.diplomacy_agreements import assign_puppet

# ==========================================
# TKINTER WINDOW HELPERS
# ==========================================

def _create_editor_window(title, geometry):
    """Standardizes the creation of floating editor tool windows."""
    root = tk.Tk()
    root.title(title)
    root.geometry(geometry)
    root.attributes("-topmost", True)
    return root

def _run_editor_loop(map_screen, root):
    """Standardizes the Pygame-safe Tkinter event loop."""
    while map_screen.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except (tk.TclError, Exception):
            break

# ==========================================
# EDITOR MENUS
# ==========================================

def editor_load_map(self):
    """Opens a file dialog to load a map folder directly into the editor."""
    root = queries.get_transient_tk_root()
    path = filedialog.askdirectory(initialdir=c.SCENARIOS_CUSTOM_DIR, title="Select Map Folder to Edit")
    queries.destroy_tk_root(root)

    if path:
        # Re-run asset loader on this instance
        load_map.load_map_assets(self, path)
        self.refresh_political_map()
        self.show_feedback("Map Loaded into Editor")

def select_brush_nation(self):
    """Opens a Tkinter selection window and sets mode to NATION."""
    root = _create_editor_window("Select Nation", "300x450")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_menu)
    
    tk.Label(root, text="Select Paint Nation:", font=("Arial", 12)).pack(pady=10)
    
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10)
    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")
    
    # Sort and filter out utility 'countries'
    nations = sorted(list(self.nation_data.keys()), key=lambda k: unicodedata.normalize('NFKD', k).encode('ascii', 'ignore').decode('utf-8').lower())
    lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
    
    # Explicitly add the requested elements to the top
    lb.insert(tk.END, "Unclaimed")
    lb.insert(tk.END, "The Rot")
    lb.insert(tk.END, "----------")

    for n in nations:
        if n in ["Unclaimed", "The Rot"]:
            continue
        if n not in c.UNPLAYABLE_NATIONS or n in ["None"]:
            lb.insert(tk.END, n)
            
    lb.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=lb.yview)
    
    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            selected_val = lb.get(selection[0])
            
            # Prevent the separator line from doing anything
            if selected_val == "----------":
                lb.selection_clear(selection[0])
                return
                
            self.brush_nation = selected_val
            self.editor_mode = "NATION" 
            self.show_feedback(f"Brush: {self.brush_nation}")
        close_menu()

    tk.Button(root, text="Confirm Selection", command=on_select, 
              bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)

    lb.bind('<Double-1>', on_select)
    _run_editor_loop(self, root)

def select_core_brush(self):
    """Opens a Tkinter selection window and sets mode to CORE."""
    root = _create_editor_window("Select Core Nation", "300x450")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_menu)
    tk.Label(root, text="Select Nation to Add Cores:", font=("Arial", 12)).pack(pady=10)
    
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10)
    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")
    
    nations = sorted(list(self.nation_data.keys()), key=lambda k: unicodedata.normalize('NFKD', k).encode('ascii', 'ignore').decode('utf-8').lower())
    lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
    
    lb.insert(tk.END, "Unclaimed")
    lb.insert(tk.END, "The Rot")
    lb.insert(tk.END, "----------")

    for n in nations:
        if n in ["Unclaimed", "The Rot"]:
            continue
        if n not in c.UNPLAYABLE_NATIONS or n in ["None"]:
            lb.insert(tk.END, n)
            
    lb.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=lb.yview)
    
    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            selected_val = lb.get(selection[0])
            if selected_val == "----------":
                lb.selection_clear(selection[0])
                return
                
            self.brush_nation = selected_val
            self.editor_mode = "CORE" 
            self.show_feedback(f"Core Brush: {self.brush_nation}")
        close_menu()

    tk.Button(root, text="Confirm Selection", command=on_select, 
              bg="#FF69B4", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)

    lb.bind('<Double-1>', on_select)
    _run_editor_loop(self, root)


def select_claim_brush(self):
    """Opens a Tkinter selection window and sets mode to CLAIM."""
    root = _create_editor_window("Select Claim Nation", "300x450")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_menu)
    tk.Label(root, text="Select Nation to Add Claims:", font=("Arial", 12)).pack(pady=10)
    
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10)
    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")
    
    nations = sorted(list(self.nation_data.keys()), key=lambda k: unicodedata.normalize('NFKD', k).encode('ascii', 'ignore').decode('utf-8').lower())
    lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
    
    lb.insert(tk.END, "Unclaimed")
    lb.insert(tk.END, "The Rot")
    lb.insert(tk.END, "----------")

    for n in nations:
        if n in ["Unclaimed", "The Rot"]:
            continue
        if n not in c.UNPLAYABLE_NATIONS or n in ["None"]:
            lb.insert(tk.END, n)
            
    lb.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=lb.yview)
    
    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            selected_val = lb.get(selection[0])
            if selected_val == "----------":
                lb.selection_clear(selection[0])
                return
                
            self.brush_nation = selected_val
            self.editor_mode = "CLAIM" 
            self.show_feedback(f"Claim Brush: {self.brush_nation}")
        close_menu()

    tk.Button(root, text="Confirm Selection", command=on_select, 
              bg="#FF8800", fg="black", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)

    lb.bind('<Double-1>', on_select)
    _run_editor_loop(self, root)


def open_editor_claims(self):
    """Opens a Tkinter window listing every claim on the map."""
    root = _create_editor_window("Global Claims Overview", "600x500")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", close_menu)

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

    _run_editor_loop(self, root)

def select_building_brush(self):
    """Opens a selection window for building types and sets mode to BUILDING."""
    root = _create_editor_window("Select Building", "300x400")
    self.menu_active = True

    # --- DYNAMIC FETCH ---
    bldg_lib = queries.get_building_library()
    buildings = ["None"] + list(bldg_lib.keys()) if bldg_lib else ["None"]

    def close_menu():
        self.menu_active = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_menu)
    tk.Label(root, text="Select Building to Place:", font=("Arial", 12)).pack(pady=10)
    
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10)
    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")
    
    lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
    for b in buildings:
        lb.insert(tk.END, b)
    lb.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=lb.yview)
    
    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            self.brush_building = lb.get(selection[0])
            self.editor_mode = "BUILDING"
            self.show_feedback(f"Brush: {self.brush_building}")
        close_menu()

    tk.Button(root, text="Confirm Selection", command=on_select, 
              bg="#2196F3", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)

    lb.bind('<Double-1>', on_select)
    _run_editor_loop(self, root)

def spec_select_edit_country(self):
    """Opens a Tkinter window for a Spectator to select which nation to edit."""
    active_countries = queries.get_living_nations(self.map_data)
    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root = _create_editor_window("Select Nation to Edit", "300x450")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_menu)
    tk.Label(root, text="Select Nation to Edit:", font=("Arial", 12)).pack(pady=10)
    
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10)
    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")
    
    lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
    for n in sorted(active_countries):
        lb.insert(tk.END, n)
    lb.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=lb.yview)
    
    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            self.editing_country = lb.get(selection[0])
            self.next_state, self.done = "EDIT_COUNTRY", True
        close_menu()

    tk.Button(root, text="Edit Country", command=on_select, 
              bg="#FF9800", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)

    lb.bind('<Double-1>', on_select)
    _run_editor_loop(self, root)

def open_editor_date(self):
    """Opens a Tkinter window to edit the game's starting date."""
    root = _create_editor_window("Set Start Date", "250x350")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", close_menu)

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
    dpt_ent.insert(0, str(self.scenario_settings.get("base_days_per_turn", c.DEFAULT_DAYS_PER_TURN)))
    dpt_ent.pack()

    def apply_date():
        try:
            # Pull directly from the Entry widget
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
            
            self.show_feedback(f"Date & Turn Rate set!")
            close_menu()
        except ValueError:
            messagebox.showerror("Error", "Please enter valid integers.")

    tk.Button(root, text="Apply Date", command=apply_date, bg="#FF9800", fg="black", pady=5).pack(pady=15, fill="x", padx=20)
    _run_editor_loop(self, root)


def open_editor_economy(self):
    """Opens a Tkinter window listing the detailed income of every active country."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root = _create_editor_window("Global Economy Overview", "1200x500")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", close_menu)

    # --- Styling for Table Look ---
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

    # --- Treeview UI Setup ---
    columns = (
        "Country", 
        "|1", "P_Cur", "P_Inc", "P_Bld", "P_Upk", "P_Net", 
        "|2", "M_Cur", "M_Inc", "M_Bld", "M_Upk", "M_Net", 
        "|3", "F_Cur", "F_Inc", "F_Bld", "F_Upk", "F_Net", 
        "|4"
    )
    
    tree = ttk.Treeview(root, columns=columns, show="headings")
    
    # Zebra striping tags
    tree.tag_configure('evenrow', background='#ffffff')
    tree.tag_configure('oddrow', background='#f2f2f2') 
    
    # State dictionary to track ascending/descending sort for each column
    sort_dirs = {col: True for col in columns}

    # Sorting Logic
    def sort_data(col):
        reverse = sort_dirs[col]
        sort_dirs[col] = not reverse 
        
        def get_val(c):
            if c not in all_econ: return 0
            d = all_econ[c]
            if col == "Country": return c
            
            # Don't sort the dividers
            if col.startswith("|"): return 0
            
            # Map the column ID to the specific resource and stat
            res_key = "manpower" if col.startswith("P_") else ("materials" if col.startswith("M_") else "fuel")
            stat_type = col.split("_")[1]
            bd = d["breakdown"][res_key]
            
            if stat_type == "Cur": return self.nation_data.get(c, {}).get(res_key, 0)
            if stat_type == "Inc": return bd["core"] + bd["non_core"] + bd["resources"]
            if stat_type == "Bld": return bd["buildings"]
            if stat_type == "Upk": return d["upkeep"][res_key]
            if stat_type == "Net": return d["total_inc"][res_key] - d["upkeep"][res_key]
            
            return 0

        # Sort the countries using the dynamic value generator
        sorted_countries = sorted(active_countries, key=get_val, reverse=reverse)
        
        # Clear existing rows
        for item in tree.get_children():
            tree.delete(item)
            
        # Re-populate using the sorted list
        populate_tree(sorted_countries)

    # Column Formatting
    widths = {
        "Country": 130,
        "|1": 20, "P_Cur": 55, "P_Inc": 55, "P_Bld": 55, "P_Upk": 55, "P_Net": 55,
        "|2": 20, "M_Cur": 55, "M_Inc": 55, "M_Bld": 55, "M_Upk": 55, "M_Net": 55,
        "|3": 20, "F_Cur": 55, "F_Inc": 55, "F_Bld": 55, "F_Upk": 55, "F_Net": 55,
        "|4": 20
    }

    for col in columns:
        # Render the display text as "|" for any divider column
        heading_text = "|" if col.startswith("|") else col
        # Passing col to lambda safely captures its state for the button click
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
                        
            # Apply zebra stripe tags
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            
            tree.insert("", tk.END, values=(
                c, 
                "|", p_cur, p_inc, p_bld, p_upk, p_net, 
                "|", m_cur, m_inc, m_bld, m_upk, m_net, 
                "|", f_cur, f_inc, f_bld, f_upk, f_net,
                "|"
            ), tags=(tag,))

    # Initial population (Defaults to alphabetical)
    populate_tree(sorted(active_countries))

    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    tree.configure(yscroll=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)

    _run_editor_loop(self, root)
        
def open_spectator_messages(self):
    """Opens a Tkinter window listing all messages sent between active countries."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root = _create_editor_window("Global Messages Overview", "1100x500")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", close_menu)

    # --- Styling for Table Look ---
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
    
    # Zebra striping tags
    tree.tag_configure('evenrow', background='#ffffff')
    tree.tag_configure('oddrow', background='#f2f2f2') 

    # --- Gather Messages ---
    all_msgs = []
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    
    for c_name, data in self.nation_data.items():
        if data.get("is_playable"):
            inbox = data.get("inbox", [])
            for msg in inbox:
                # Mark as read for the spectator so the notification badge clears
                msg["spectator_read"] = True
                
                sender = msg.get("sender", "")
                
                # Avoid duplicates (sent messages are stored as "To: Receiver" in sender's inbox)
                if not sender.startswith("To: "):
                    date_str = msg.get("date", "Unknown")
                    
                    # Parse the date string back into a sortable absolute day value
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

    # --- Sorting Logic ---
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

        # Sort the messages using the dynamic value generator
        sorted_msgs = sorted(all_msgs, key=get_val, reverse=reverse)
        
        # Clear existing rows
        for item in tree.get_children():
            tree.delete(item)
            
        # Re-populate
        populate_tree(sorted_msgs)

    # Map headings to sort command
    for col in columns:
        tree.heading(col, text=col, command=lambda c=col: sort_data(c))

    # Keep original column formatting
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

    # Initial sort: Newest at the top (reverse=True) so most recent dates show up first!
    populate_tree(sorted(all_msgs, key=lambda x: x["sort_val"], reverse=True))

    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    tree.configure(yscroll=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)

    _run_editor_loop(self, root)

def open_map_research_editor(self):
    """Opens a UI to edit research for countries currently existing on the map."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    def get_default_research():
        # 1. ALWAYS generate a fresh template from the cached JSON first
        struct = queries.get_tech_tree()
        fresh_template = {tech: (1800 if data["max_lvl"] == 9999 else 0) for tech, data in struct.items()}
            
        if "infantry_type" in fresh_template: fresh_template["infantry_type"] = 1
        if "cavalry" in fresh_template: fresh_template["cavalry"] = 1

        # 2. If the loaded map has an older default_research dict, update it with missing keys
        if getattr(self, "default_research", None) is not None:
            for k, v in fresh_template.items():
                if k not in self.default_research:
                    self.default_research[k] = v
            
            obsolete_keys = [k for k in self.default_research.keys() if k not in fresh_template]
            for k in obsolete_keys:
                del self.default_research[k]
                
            return self.default_research

        # 3. Otherwise, use the fresh template entirely
        return fresh_template

    default_res = get_default_research()

    root = _create_editor_window("Map Tech Editor", "350x500")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_menu)
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

    _run_editor_loop(self, root)

def select_unit_brush(self):
    """Opens a selection window for unit types and sets mode to UNIT."""
    root = _create_editor_window("Select Unit", "300x400")
    self.menu_active = True

    units = list(queries.get_unit_library().keys())

    def close_menu():
        self.menu_active = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_menu)
    tk.Label(root, text="Select Unit to Place:", font=("Arial", 12)).pack(pady=10)
    
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10)
    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")
    
    lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
    for u in ["None"] + units:
        lb.insert(tk.END, u)
    lb.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=lb.yview)
    
    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            self.brush_unit = lb.get(selection[0])
            self.editor_mode = "UNIT"
            self.show_feedback(f"Brush: {self.brush_unit}")
        close_menu()

    tk.Button(root, text="Confirm Selection", command=on_select, bg="#f44336", fg="white", pady=10).pack(fill="x", padx=10, pady=10)
    lb.bind('<Double-1>', on_select)

    _run_editor_loop(self, root)

def select_resource_brush(self):
    """Opens a selection window for resource types and amounts."""
    root = _create_editor_window("Resource Brush", "300x250")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_menu)

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

    _run_editor_loop(self, root)

def open_scripted_events_editor(self):
    active_countries = queries.get_living_nations(self.map_data)
    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root = _create_editor_window("Scripted Events Editor", "650x550")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close_menu)

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

    events_frame = tk.Frame(right_frame)
    events_frame.pack(fill="both", expand=True, pady=5)
    
    events_scroll = tk.Scrollbar(events_frame)
    events_scroll.pack(side="right", fill="y")
    events_listbox = tk.Listbox(events_frame, yscrollcommand=events_scroll.set)
    events_listbox.pack(side="left", fill="both", expand=True)
    events_scroll.config(command=events_listbox.yview)

    current_target = [None]

    def refresh_events_list():
        events_listbox.delete(0, tk.END)
        target = current_target[0]
        if not target: return
        events = self.nation_data.get(target, {}).get("scripted_events", [])
        for i, evt in enumerate(events):
            # Backwards compatibility parsing
            if "conditions" not in evt:
                evt["conditions"] = [{
                    "type": evt.get("condition_type", "Turn Number"),
                    "operator": "==",
                    "value": evt.get("condition_val", ""),
                    "chain": "AND"
                }]
                evt["fire_once"] = True
                
            conds = evt["conditions"]
            cond_strs = []
            
            for idx, c_dict in enumerate(conds):
                prefix = "" if idx == 0 else f" {c_dict.get('chain', 'AND')} "
                if c_dict.get("type") == "Turn Number":
                    cond_strs.append(f"{prefix}Turn {c_dict.get('operator', '==')} {c_dict.get('value')}")
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
                if a.get('type') == "Send Custom Message":
                    act_strs.append(f"MSG to '{a.get('target')}'")
                else:
                    act_strs.append(f"{a.get('type')} '{a.get('target')}'")
                    
            act_str = f"Then {', '.join(act_strs)}"
            if len(act_str) > 40:
                act_str = act_str[:37] + "..."
                
            once_str = " [Once]" if evt.get("fire_once", True) else " [Repeat]"
            
            events_listbox.insert(tk.END, f"{i+1}. If {full_cond_str} -> {act_str}{once_str}")

    def load_nation_data(event):
        sel = nation_list.curselection()
        if not sel: return
        target = nation_list.get(sel[0])
        current_target[0] = target
        title_lbl.config(text=f"Events for: {target}")
        refresh_events_list()

    nation_list.bind("<<ListboxSelect>>", load_nation_data)

    def get_expected_date_string(turns_str):
        import re
        from map_logic.system32.time_handler import TimeHandler
        nums = re.findall(r'\d+', turns_str)
        if not nums: return ""
        
        date_strs = []
        for num in nums[:2]: # Max 2 for BETWEEN intervals
            t = int(num)
            temp_time = TimeHandler(start_year=self.time_manager.year)
            temp_time.day = self.time_manager.day
            temp_time.month_index = self.time_manager.month_index
            dpt = self.scenario_settings.get("base_days_per_turn", c.DEFAULT_DAYS_PER_TURN)
            
            temp_time.process_time(t * dpt)
            date_strs.append(temp_time.get_date_string())
            
        return " / ".join(date_strs)

    def open_event_window(event_idx=None):
        target = current_target[0]
        if not target:
            messagebox.showwarning("Warning", "Select a nation first.")
            return

        edit_win = tk.Toplevel(root)
        edit_win.title(f"{'Edit' if event_idx is not None else 'Add'} Event: {target}")
        edit_win.geometry("800x650")
        edit_win.attributes("-topmost", True)
        
        event_data = {}
        if event_idx is not None:
            event_data = self.nation_data[target]["scripted_events"][event_idx]
            if "conditions" not in event_data:
                event_data["conditions"] = [{
                    "type": event_data.get("condition_type", "Turn Number"),
                    "operator": "==",
                    "value": event_data.get("condition_val", ""),
                    "chain": "AND"
                }]
                event_data["fire_once"] = True
                
        conds_data = event_data.get("conditions", [{"chain": "AND", "type": "Turn Number", "operator": "==", "value": ""}])
        
        acts_data = event_data.get("actions", [])
        if not acts_data and "action_type" in event_data:
            acts_data = [{"type": event_data["action_type"], "target": event_data.get("action_target", "None")}]

        # --- Top controls ---
        top_frame = tk.Frame(edit_win)
        top_frame.pack(fill="x", padx=10, pady=5)
        
        fire_once_var = tk.BooleanVar(value=event_data.get("fire_once", True))
        tk.Checkbutton(top_frame, text="Single-Time Event (Fire Only Once)", variable=fire_once_var).pack(anchor="w")
        
        trigger_type_var = tk.StringVar(value=event_data.get("trigger_type", "AI Only"))
        ttk.Combobox(top_frame, textvariable=trigger_type_var, values=["AI Only", "Player Only", "Both"], state="readonly", width=12).pack(side="left", padx=10)
        
        # --- Conditions Frame ---
        tk.Label(edit_win, text="Conditionals:", font=("Arial", 10, "bold")).pack(anchor="w", padx=10, pady=(5, 0))
        
        cond_container = tk.Frame(edit_win)
        cond_container.pack(fill="both", expand=True, padx=10, pady=2)
        
        cond_canvas = tk.Canvas(cond_container, height=180)
        cond_scroll = tk.Scrollbar(cond_container, orient="vertical", command=cond_canvas.yview)
        cond_frame = tk.Frame(cond_canvas)
        
        cond_frame.bind("<Configure>", lambda e: cond_canvas.configure(scrollregion=cond_canvas.bbox("all")))
        cond_canvas.create_window((0, 0), window=cond_frame, anchor="nw")
        cond_canvas.configure(yscrollcommand=cond_scroll.set)
        
        cond_scroll.pack(side="right", fill="y")
        cond_canvas.pack(side="left", fill="both", expand=True)
        
        row_objects = []
        
        def repack_conditions():
            for ro in row_objects:
                ro["frame"].pack_forget()
            for ro in row_objects:
                ro["frame"].pack(fill="x", pady=2, padx=2)

        def move_up(r_obj):
            idx = row_objects.index(r_obj)
            if idx > 0:
                row_objects.insert(idx - 1, row_objects.pop(idx))
                repack_conditions()

        def move_down(r_obj):
            idx = row_objects.index(r_obj)
            if idx < len(row_objects) - 1:
                row_objects.insert(idx + 1, row_objects.pop(idx))
                repack_conditions()

        def add_condition_row(c_data=None):
            if c_data is None:
                c_data = {"chain": "AND", "type": "Turn Number", "operator": "==", "value": ""}
                
            row_frame = tk.Frame(cond_frame, relief="ridge", bd=2)
            row_frame.pack(fill="x", pady=2, padx=2)
            
            is_first = (len(row_objects) == 0)
            
            chain_var = tk.StringVar(value=c_data.get("chain", "AND"))
            if not is_first:
                ttk.Combobox(row_frame, textvariable=chain_var, values=["AND", "OR", "XOR", "NOR", "NAND"], width=5, state="readonly").pack(side="left", padx=2)
            else:
                tk.Label(row_frame, text=" IF ", width=5).pack(side="left", padx=2)
                
            type_var = tk.StringVar(value=c_data.get("type", "Turn Number"))
            op_var = tk.StringVar(value=c_data.get("operator", "=="))
            val_var = tk.StringVar(value=c_data.get("value", ""))
            
            type_cb = ttk.Combobox(row_frame, textvariable=type_var, values=["Turn Number", "At War With", "In Faction With", "At Peace With", "Random (0.00 - 1.00)", "Received Action", "Country Exists", "Country Doesn't Exist", "Occupying Core Of", "Occupying All Cores Of", "Occupying Tile", "Is AI Controlled", "Is Player Controlled", "Bordering"], width=18, state="readonly")
            type_cb.pack(side="left", padx=2)
            
            op_cb = ttk.Combobox(row_frame, textvariable=op_var, width=19, state="readonly")
            op_cb.pack(side="left", padx=2)
            
            val_ent = tk.Entry(row_frame, textvariable=val_var, width=15)
            val_ent.pack(side="left", padx=2)
            
            date_lbl = tk.Label(row_frame, text="", fg="gray", width=30, anchor="w")
            date_lbl.pack(side="left", padx=2)
            
            def update_row(*args):
                ctype = type_var.get()
                if ctype in ["Turn Number", "Random (0.00 - 1.00)"]:
                    op_cb.config(values=["==", ">", "<", ">=", "<=", "BETWEEN (INC)", "BETWEEN (EXC)"])
                    if op_var.get() not in ["==", ">", "<", ">=", "<=", "BETWEEN (INC)", "BETWEEN (EXC)"]:
                        op_var.set("==")
                    
                    if ctype == "Turn Number":
                        # Compute expected date projection
                        d_str = get_expected_date_string(val_var.get())
                        if d_str:
                            date_lbl.config(text=f"({d_str})")
                        else:
                            date_lbl.config(text="")
                    else:
                        date_lbl.config(text="")
                elif ctype == "Received Action":
                    op_cb.config(values=["WAR_DECLARATION", "JOIN_WARS", "CALL_TO_ARMS", "FACTION_INVITE", "JOIN_FACTION_REQ", "TRADE", "CEASEFIRE"])
                    if op_var.get() not in ["WAR_DECLARATION", "JOIN_WARS", "CALL_TO_ARMS", "FACTION_INVITE", "JOIN_FACTION_REQ", "TRADE", "CEASEFIRE"]:
                        op_var.set("WAR_DECLARATION")
                    date_lbl.config(text="(Sender Nation ID)")
                elif ctype == "Country Doesn't Exist":
                    op_cb.config(values=["=="])
                    op_var.set("==")
                    date_lbl.config(text="(Target Nation ID)")
                elif ctype == "Occupying All Cores Of":
                    op_cb.config(values=["==", "!="])
                    if op_var.get() not in ["==", "!="]: op_var.set("==")
                    date_lbl.config(text="(Target Nation ID)")
                elif ctype == "Occupying Tile":
                    op_cb.config(values=["==", "!="])
                    if op_var.get() not in ["==", "!="]: op_var.set("==")
                    date_lbl.config(text="(Tile IDs, comma separated)")
                elif ctype in ["Is AI Controlled", "Is Player Controlled"]:
                    op_cb.config(values=["=="])
                    op_var.set("==")
                    date_lbl.config(text="(Target Nation ID or blank for self)")
                else:
                    op_cb.config(values=["=="])
                    op_var.set("==")
                    date_lbl.config(text="")
                    date_lbl.config(text="(Target Nation ID)")
            
            type_var.trace_add("write", update_row)
            val_var.trace_add("write", update_row)
            update_row() # Initial call
            
            row_obj = {
                "frame": row_frame,
                "chain_var": chain_var,
                "type_var": type_var,
                "op_var": op_var,
                "val_var": val_var
            }
            
            def remove_self():
                row_frame.destroy()
                row_objects.remove(row_obj)
                
            if not is_first:
                tk.Button(row_frame, text="X", fg="white", bg="red", command=remove_self).pack(side="right", padx=2)
                
            tk.Button(row_frame, text="v", fg="black", command=lambda r=row_obj: move_down(r)).pack(side="right", padx=1)
            tk.Button(row_frame, text="^", fg="black", command=lambda r=row_obj: move_up(r)).pack(side="right", padx=1)
                
            row_objects.append(row_obj)
            
        for c_data in conds_data:
            add_condition_row(c_data)

        # --- Actions Frame ---
        tk.Label(edit_win, text="Actions:", font=("Arial", 10, "bold")).pack(anchor="w", padx=10, pady=(5, 0))
        
        act_container = tk.Frame(edit_win)
        act_container.pack(fill="both", expand=True, padx=10, pady=2)
        
        act_canvas = tk.Canvas(act_container, height=180)
        act_scroll = tk.Scrollbar(act_container, orient="vertical", command=act_canvas.yview)
        act_frame = tk.Frame(act_canvas)
        
        act_frame.bind("<Configure>", lambda e: act_canvas.configure(scrollregion=act_canvas.bbox("all")))
        act_canvas.create_window((0, 0), window=act_frame, anchor="nw")
        act_canvas.configure(yscrollcommand=act_scroll.set)
        
        act_scroll.pack(side="right", fill="y")
        act_canvas.pack(side="left", fill="both", expand=True)

        act_row_objects = []
        
        def repack_actions():
            for ro in act_row_objects:
                ro["frame"].pack_forget()
            for ro in act_row_objects:
                ro["frame"].pack(fill="x", pady=2, padx=2)

        def move_act_up(r_obj):
            idx = act_row_objects.index(r_obj)
            if idx > 0:
                act_row_objects.insert(idx - 1, act_row_objects.pop(idx))
                repack_actions()

        def move_act_down(r_obj):
            idx = act_row_objects.index(r_obj)
            if idx < len(act_row_objects) - 1:
                act_row_objects.insert(idx + 1, act_row_objects.pop(idx))
                repack_actions()

        def add_action_row(a_data=None):
            if a_data is None:
                a_data = {"type": "Declare War", "target": "None", "message": "", "appearance_data": {}}
                
            row_frame = tk.Frame(act_frame, relief="ridge", bd=2)
            row_frame.pack(fill="x", pady=2, padx=2)
            
            type_var = tk.StringVar(value=a_data.get("type", "Declare War"))
            target_var = tk.StringVar(value=a_data.get("target", "None"))
            msg_var = tk.StringVar(value=a_data.get("message", ""))
            
            type_cb = ttk.Combobox(row_frame, textvariable=type_var, values=["Declare War", "Join Faction", "Create Faction", "Accept Proposal", "Reject Proposal", "Send Ceasefire", "Send Custom Message", "Edit Appearance"], width=18, state="readonly")
            type_cb.pack(side="left", padx=5)
            
            target_cb = ttk.Combobox(row_frame, textvariable=target_var, values=["None"] + sorted(active_countries), width=18)
            
            msg_ent = tk.Entry(row_frame, textvariable=msg_var, width=20)
            
            row_obj = {
                "frame": row_frame,
                "type_var": type_var,
                "target_var": target_var,
                "msg_var": msg_var,
                "app_data": a_data.get("appearance_data", {})
            }
            
            def edit_app():
                app_win = tk.Toplevel(root)
                app_win.title("Appearance Details")
                app_win.geometry("300x250")
                app_win.attributes("-topmost", True)
                
                fields = ["name", "leader_name", "leader_title", "color", "flag_data", "portrait_data"]
                ents = {}
                for i, f in enumerate(fields):
                    tk.Label(app_win, text=f.replace("_", " ").title()+":").grid(row=i, column=0, sticky="e", padx=5, pady=5)
                    ent = tk.Entry(app_win, width=30)
                    ent.insert(0, row_obj["app_data"].get(f, ""))
                    ent.grid(row=i, column=1, pady=5)
                    ents[f] = ent
                    
                def save_app():
                    for f in fields:
                        row_obj["app_data"][f] = ents[f].get()
                    app_win.destroy()
                    
                tk.Button(app_win, text="Save", command=save_app, bg="#4CAF50", fg="white").grid(row=len(fields), column=0, columnspan=2, pady=10)

            app_btn = tk.Button(row_frame, text="Configure Appearance", command=edit_app)
            
            def update_act_row(*args):
                t = type_var.get()
                if t == "Send Custom Message":
                    target_cb.pack(side="left", padx=5)
                    msg_ent.pack(side="left", padx=5)
                    app_btn.pack_forget()
                elif t == "Edit Appearance":
                    target_cb.pack_forget()
                    msg_ent.pack_forget()
                    app_btn.pack(side="left", padx=5)
                else:
                    target_cb.pack(side="left", padx=5)
                    msg_ent.pack_forget()
                    app_btn.pack_forget()
                    
            type_var.trace_add("write", update_act_row)
            update_act_row()
            
            def update_act_row(*args):
                if type_var.get() == "Send Custom Message":
                    msg_ent.pack(side="left", padx=5)
                else:
                    msg_ent.pack_forget()
                    
            type_var.trace_add("write", update_act_row)
            update_act_row()
            
            row_obj = {
                "frame": row_frame,
                "type_var": type_var,
                "target_var": target_var,
                "msg_var": msg_var
            }
            
            def remove_self():
                row_frame.destroy()
                act_row_objects.remove(row_obj)
                
            tk.Button(row_frame, text="X", fg="white", bg="red", command=remove_self).pack(side="right", padx=5)
            tk.Button(row_frame, text="v", fg="black", command=lambda r=row_obj: move_act_down(r)).pack(side="right", padx=1)
            tk.Button(row_frame, text="^", fg="black", command=lambda r=row_obj: move_act_up(r)).pack(side="right", padx=1)
            act_row_objects.append(row_obj)

        for a_data in acts_data:
            add_action_row(a_data)

        def save_event():
            final_conds = []
            for ro in row_objects:
                final_conds.append({
                    "chain": ro["chain_var"].get(),
                    "type": ro["type_var"].get(),
                    "operator": ro["op_var"].get(),
                    "value": ro["val_var"].get()
                })
                
            final_acts = []
            for ro in act_row_objects:
                final_acts.append({
                    "type": ro["type_var"].get(),
                    "target": ro["target_var"].get(),
                    "message": ro["msg_var"].get(),
                    "appearance_data": ro.get("app_data", {})
                })
                
            new_event = {
                "conditions": final_conds,
                "actions": final_acts,
                "fire_once": fire_once_var.get(),
                "trigger_type": trigger_type_var.get()
            }
            
            target_data = self.nation_data.setdefault(target, {})
            events_list = target_data.setdefault("scripted_events", [])
            
            if event_idx is not None:
                events_list[event_idx] = new_event
            else:
                events_list.append(new_event)
                
            refresh_events_list()
            edit_win.destroy()

        bot_frame = tk.Frame(edit_win)
        bot_frame.pack(fill="x", pady=10, padx=10)
        
        tk.Button(bot_frame, text="Add Conditional", command=add_condition_row, bg="#2196F3", fg="white").pack(side="left", padx=5)
        tk.Button(bot_frame, text="Add Action", command=add_action_row, bg="#9C27B0", fg="white").pack(side="left", padx=5)
        tk.Button(bot_frame, text="Save Event", command=save_event, bg="#4CAF50", fg="white").pack(side="right", padx=5)

    def edit_event():
        sel = events_listbox.curselection()
        if not sel: return
        open_event_window(sel[0])

    def remove_event():
        target = current_target[0]
        sel = events_listbox.curselection()
        if not target or not sel: return
        
        idx = sel[0]
        data = self.nation_data.get(target, {})
        events = data.get("scripted_events", [])
        if 0 <= idx < len(events):
            events.pop(idx)
            refresh_events_list()

    btn_frame = tk.Frame(right_frame)
    btn_frame.pack(fill="x", pady=5)
    tk.Button(btn_frame, text="Add New Event", command=lambda: open_event_window(None), bg="#2196F3", fg="white").pack(side="left", expand=True, fill="x", padx=5)
    tk.Button(btn_frame, text="Edit Selected", command=edit_event, bg="#FF9800", fg="black").pack(side="left", expand=True, fill="x", padx=5)
    tk.Button(btn_frame, text="Remove Selected", command=remove_event, bg="#f44336", fg="white").pack(side="right", expand=True, fill="x", padx=5)

    _run_editor_loop(self, root)

def open_diplomacy_editor(self):
    """Opens a Tkinter window to edit global relations and factions."""
    active_countries = queries.get_living_nations(self.map_data)
    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root = _create_editor_window("Global Diplomacy & Factions Editor", "550x700")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close_menu)

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

    _run_editor_loop(self, root)

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
            
    root = _create_editor_window("Edited Countries Overview", "900x500")
    self.menu_active = True
    
    def close_menu():
        self.menu_active = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", close_menu)
    
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
    
    _run_editor_loop(self, root)