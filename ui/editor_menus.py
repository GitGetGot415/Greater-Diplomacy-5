import pygame
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import data.constants as c
from data.map import load_map
from data import queries

def editor_load_map(self):
    """Opens a file dialog to load a map folder directly into the editor."""
    root = tk.Tk()
    root.withdraw()
    # Point it to your new base_maps folder instead of scenarios
    # path = filedialog.askdirectory(initialdir="base_maps", title="Select Map Folder to Edit")
    path = filedialog.askdirectory(initialdir=c.SCENARIOS_DIR, title="Select Map Folder to Edit")
    root.destroy()

    if path:
        # Re-run asset loader on this instance
        load_map.load_map_assets(self, path)
        self.refresh_political_map()
        self.show_feedback("Map Loaded into Editor")

def select_brush_nation(self):
    """Opens a Tkinter selection window and sets mode to NATION."""
    root = tk.Tk()
    root.title("Select Nation")
    root.geometry("300x450")
    root.attributes("-topmost", True)
    self.menu_active = True

    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            self.brush_nation = lb.get(selection[0])
            self.editor_mode = "NATION" 
            self.show_feedback(f"Brush: {self.brush_nation}")
        close_menu()

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
    nations = sorted(list(self.nation_data.keys()))
    lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
    for n in nations:
        if n not in ["Ocean", "Lakes"]:
            lb.insert(tk.END, n)
    lb.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=lb.yview)
    
    tk.Button(root, text="Confirm Selection", command=on_select, 
              bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)

    lb.bind('<Double-1>', on_select)

    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except (tk.TclError, Exception):
            break

def select_core_brush(self):
    """Opens a Tkinter selection window and sets mode to CORE."""
    root = tk.Tk()
    root.title("Select Core Nation")
    root.geometry("300x450")
    root.attributes("-topmost", True)
    self.menu_active = True

    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            self.brush_nation = lb.get(selection[0])
            self.editor_mode = "CORE" 
            self.show_feedback(f"Core Brush: {self.brush_nation}")
        close_menu()

    def close_menu():
        self.menu_active = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_menu)
    tk.Label(root, text="Select Nation to Add Cores:", font=("Arial", 12)).pack(pady=10)
    
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10)
    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")
    
    nations = sorted(list(self.nation_data.keys()))
    lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
    for n in nations:
        if n not in c.WATER_NATIONS:
            lb.insert(tk.END, n)
    lb.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=lb.yview)
    
    tk.Button(root, text="Confirm Selection", command=on_select, 
              bg="#FF69B4", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)

    lb.bind('<Double-1>', on_select)

    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except (tk.TclError, Exception):
            break

def select_building_brush(self):
    """Opens a selection window for building types and sets mode to BUILDING."""
    root = tk.Tk()
    root.title("Select Building")
    root.geometry("300x400")
    root.attributes("-topmost", True)
    self.menu_active = True

    # --- DYNAMIC FETCH ---
    from data import queries
    bldg_lib = queries.get_building_library()
    buildings = ["None"] + list(bldg_lib.keys()) if bldg_lib else ["None"]

    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            self.brush_building = lb.get(selection[0])
            self.editor_mode = "BUILDING"
            self.show_feedback(f"Brush: {self.brush_building}")
        close_menu()

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
    
    tk.Button(root, text="Confirm Selection", command=on_select, 
              bg="#2196F3", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)

    lb.bind('<Double-1>', on_select)

    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except (tk.TclError, Exception):
            break

def spec_select_edit_country(self):
    """Opens a Tkinter window for a Spectator to select which nation to edit."""
    active_countries = queries.get_living_nations(self.map_data)
    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root = tk.Tk()
    root.title("Select Nation to Edit")
    root.geometry("300x450")
    root.attributes("-topmost", True)
    self.menu_active = True

    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            self.editing_country = lb.get(selection[0])
            self.next_state, self.done = "EDIT_COUNTRY", True
        close_menu()

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
    
    tk.Button(root, text="Edit Country", command=on_select, 
              bg="#FF9800", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)

    lb.bind('<Double-1>', on_select)

    import pygame
    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except:
            break

def open_editor_date(self):
    """Opens a Tkinter window to edit the game's starting date."""
    root = tk.Tk()
    root.title("Set Start Date")
    root.geometry("250x300")
    root.attributes("-topmost", True)
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", close_menu)

    # --- Directly use tk.Entry instead of StringVar ---
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

    def apply_date():
        try:
            # Pull directly from the Entry widget
            d = int(day_ent.get())
            m = int(month_ent.get()) - 1
            y = int(year_ent.get())
            
            if not (1 <= d <= 30):
                messagebox.showerror("Error", "Day must be between 1 and 30.")
                return
            if not (0 <= m <= 11):
                messagebox.showerror("Error", "Month must be between 1 and 12.")
                return
                
            self.time_manager.day = d
            self.time_manager.month_index = m
            self.time_manager.year = y
            
            self.show_feedback(f"Date set: {self.time_manager.get_date_string()}")
            close_menu()
        except ValueError:
            messagebox.showerror("Error", "Please enter valid integers.")

    tk.Button(root, text="Apply Date", command=apply_date, bg="#FF9800", fg="white", pady=5).pack(pady=15, fill="x", padx=20)

    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except:
            break


def open_editor_economy(self):
    """Opens a Tkinter window listing the detailed income of every active country."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root = tk.Tk()
    root.title("Global Economy Overview")
    root.geometry("1200x500") 
    root.attributes("-topmost", True)
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
                    
    # Economy logic
    # We delete all the JSON loading and manual province looping here!
    # Instead, we just grab the unified dictionary from the queries file:
    all_econ = queries.calculate_all_economies(self.map_data, self.nation_data)

    # --- Treeview UI Setup (Added Current Columns) ---
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

    import pygame
    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except:
            break
        
def open_spectator_messages(self):
    """Opens a Tkinter window listing all messages sent between active countries."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root = tk.Tk()
    root.title("Global Messages Overview")
    root.geometry("1100x500")
    root.attributes("-topmost", True)
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

    # --- Sorting Logic (Matches Economy Tab) ---
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

    import pygame
    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except Exception:
            break

def open_map_research_editor(self):
    """Opens a UI to edit research for countries currently existing on the map."""
    active_countries = queries.get_living_nations(self.map_data)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    def get_default_research():
        # 1. ALWAYS generate a fresh template from the JSON first
        template_path = c.RESEARCH_TEMPLATE_PATH
        fresh_template = {}
        if os.path.exists(template_path):
            with open(template_path, "r") as f:
                struct = json.load(f)
            fresh_template = {tech: (1800 if data["max_lvl"] == 9999 else 0) for tech, data in struct.items()}
            
            # --- Initialize base tech ---
            if "infantry_type" in fresh_template: fresh_template["infantry_type"] = 1
            if "cavalry" in fresh_template: fresh_template["cavalry"] = 1

        # 2. If the loaded map has an older default_research dict, update it with missing keys
        if getattr(self, "default_research", None) is not None:
            for k, v in fresh_template.items():
                if k not in self.default_research:
                    self.default_research[k] = v
            
            # --- NEW: Scrub out obsolete keys here too! ---
            obsolete_keys = [k for k in self.default_research.keys() if k not in fresh_template]
            for k in obsolete_keys:
                del self.default_research[k]
                
            return self.default_research

        # 3. Otherwise, use the fresh template entirely
        return fresh_template

    default_res = get_default_research()

    root = tk.Tk()
    root.title("Map Tech Editor")
    root.geometry("350x500")
    root.attributes("-topmost", True)
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

    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except:
            break

def select_unit_brush(self):
    """Opens a selection window for unit types and sets mode to UNIT."""
    root = tk.Tk()
    root.title("Select Unit")
    root.geometry("300x400")
    root.attributes("-topmost", True)
    self.menu_active = True

    unit_path = c.UNIT_DATA_PATH
    units = list(queries.get_unit_library().keys())

    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            self.brush_unit = lb.get(selection[0])
            self.editor_mode = "UNIT"
            self.show_feedback(f"Brush: {self.brush_unit}")
        close_menu()

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
    
    tk.Button(root, text="Confirm Selection", command=on_select, bg="#f44336", fg="white", pady=10).pack(fill="x", padx=10, pady=10)
    lb.bind('<Double-1>', on_select)

    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except:
            break

def select_resource_brush(self):
    """Opens a selection window for resource types and amounts."""
    root = tk.Tk()
    root.title("Resource Brush")
    root.geometry("300x250")
    root.attributes("-topmost", True)
    self.menu_active = True

    tk.Label(root, text="Select Resource Type:", font=("Arial", 12)).pack(pady=10)
    
    # FIX: Remove the StringVar and just use the Combobox directly
    dropdown = ttk.Combobox(root, values=["Iron", "Coal", "Oil", "None"], state="readonly", font=("Arial", 11))
    dropdown.set("Iron") # Set the default visual value
    dropdown.pack(pady=5)

    tk.Label(root, text="Resource Amount:", font=("Arial", 12)).pack(pady=5)
    amt_ent = tk.Entry(root, font=("Arial", 11), justify="center")
    amt_ent.insert(0, "50")
    amt_ent.pack(pady=5)

    def on_confirm():
        try:
            amt = int(amt_ent.get())
            # Grab the value directly from the dropdown widget
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

    def close_menu():
        self.menu_active = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_menu)

    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except (tk.TclError, Exception):
            break

def open_diplomacy_editor(self):
    """Opens a Tkinter window to edit global relations and factions."""
    active_countries = queries.get_living_nations(self.map_data)
    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root = tk.Tk()
    root.title("Global Diplomacy & Factions Editor")
    root.geometry("550x550")
    root.attributes("-topmost", True)
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

    for c in sorted(active_countries):
        nation_list.insert(tk.END, c)

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
        for i, c in enumerate(sorted(active_countries)):
            if c == target: continue
            war_list.insert(tk.END, c)
            if c in enemies:
                war_list.selection_set(tk.END)

        fac_name_var.set(data.get("faction", ""))
        is_leader_var.set(data.get("is_faction_leader", False))

        member_list.delete(0, tk.END)
        for i, c in enumerate(sorted(active_countries)):
            if c == target: continue
            member_list.insert(tk.END, c)
            if data.get("faction", "") and self.nation_data.get(c, {}).get("faction", "") == data.get("faction", ""):
                member_list.selection_set(tk.END)

    nation_list.bind("<<ListboxSelect>>", load_nation_data)

    def save_changes():
        target = current_target[0]
        if not target: return

        data = self.nation_data.get(target, {})

        # 1. Update Wars (Bidirectional)
        for c in active_countries:
            if target in self.nation_data[c].get("at_war_with", []):
                self.nation_data[c]["at_war_with"].remove(target)

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
        for c in active_countries:
            if c == target: continue
            if c in selected_members:
                self.nation_data[c]["faction"] = new_faction
                if new_faction:
                    self.nation_data[c]["is_faction_leader"] = False
            elif self.nation_data[c].get("faction", "") == new_faction and new_faction != "":
                self.nation_data[c]["faction"] = ""
                self.nation_data[c]["is_faction_leader"] = False

        self.refresh_relations_map()
        self.refresh_factions_map()
        self.show_feedback(f"Diplomacy saved for {target}")

    tk.Button(right_frame, text="Save Changes", command=save_changes, bg="#4CAF50", fg="white", font=("Arial", 12, "bold")).pack(pady=10, fill="x")

    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(10) # --- CPU LIMITER FIX ---
        except (tk.TclError, Exception):
            break