import pygame
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
from data.economy_data import BASE_YIELDS, UPKEEP_MODIFIER

def editor_load_map(self):
    """Opens a file dialog to load a map folder directly into the editor."""
    root = tk.Tk()
    root.withdraw()
    # Point it to your new base_maps folder instead of scenarios
    # path = filedialog.askdirectory(initialdir="base_maps", title="Select Map Folder to Edit")
    path = filedialog.askdirectory(initialdir="scenarios", title="Select Map Folder to Edit")
    root.destroy()

    if path:
        # Re-run asset loader on this instance
        from data import load_map
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
        if n not in ["Ocean", "Lakes"]:
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
        except (tk.TclError, Exception):
            break

def select_building_brush(self):
    """Opens a selection window for building types and sets mode to BUILDING."""
    root = tk.Tk()
    root.title("Select Building")
    root.geometry("300x400")
    root.attributes("-topmost", True)
    self.menu_active = True

    buildings = [
        "None",
        "Workshop Lvl 1", "Workshop Lvl 2", "Workshop Lvl 3", "Workshop Lvl 4", "Workshop Lvl 5",
        "Basic Factory",
        "Factory Lvl 1", "Factory Lvl 2", "Factory Lvl 3", "Factory Lvl 4", "Factory Lvl 5",
        "Synthetic Refinery Lvl 1", "Synthetic Refinery Lvl 2", "Synthetic Refinery Lvl 3"
    ]

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
        except (tk.TclError, Exception):
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
        except:
            break

def open_editor_economy(self):
    """Opens a Tkinter window listing the income of every active country."""
    active_countries = set()
    for prov in self.map_data.values():
        owner = prov.get("owner")
        if owner and owner not in ["None", "Unclaimed", "Ocean", "Lakes"]:
            active_countries.add(owner)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root = tk.Tk()
    root.title("Global Economy Overview")
    root.geometry("1100x500") # Wider and taller for better visibility
    root.attributes("-topmost", True)
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", close_menu)

    # --- Styling for Table Look ---
    style = ttk.Style(root)
    try:
        style.theme_use("clam") # Clam theme looks much more like a modern table
    except:
        pass # Fallback if clam isn't available on the OS
        
    style.configure("Treeview.Heading", 
                    background="#d9e1f2", # Light blue-grey background for categories
                    font=('Arial', 10, 'bold'),
                    relief="flat")
                    
    style.configure("Treeview", 
                    background="#ffffff",
                    fieldbackground="#ffffff",
                    rowheight=28,
                    font=('Arial', 10))
                    
    # Economy logic
    YIELD_MANPOWER = BASE_YIELDS.get("manpower", 0)
    YIELD_MATERIALS = BASE_YIELDS.get("materials", 0)
    YIELD_FUEL = BASE_YIELDS.get("fuel", 0)
    
    unit_library = {}
    building_library = {}
    if os.path.exists('data/json/unit_data.json'):
        with open('data/json/unit_data.json', 'r') as f: unit_library = json.load(f)
    if os.path.exists('data/json/building_data.json'):
        with open('data/json/building_data.json', 'r') as f: building_library = json.load(f)

    # Updated data structure to track all 4 resources
    econ_data = {c: {
        "man_inc": 0, "man_upk": 0,
        "mat_inc": 0, "mat_upk": 0,
        "fuel_inc": 0, "fuel_upk": 0
    } for c in active_countries}

    for prov in self.map_data.values():
        owner = prov.get("owner")
        if owner in econ_data:
            is_core = owner in prov.get("cores", [])
            core_mult = 1.0 if is_core else 0.25
            man_mult = 1.0 if is_core else 0.0
            
            # --- Base Yields --- 
            econ_data[owner]["man_inc"] += man_mult * YIELD_MANPOWER
            econ_data[owner]["mat_inc"] += core_mult * YIELD_MATERIALS
            econ_data[owner]["fuel_inc"] += core_mult * YIELD_FUEL
            
            # --- Natural Resources ---
            res = prov.get("resources", {})
            if isinstance(res, dict):
                econ_data[owner]["mat_inc"] += int(res.get("Iron", 0)) * core_mult
                econ_data[owner]["fuel_inc"] += (int(res.get("Coal", 0)) + int(res.get("Oil", 0))) * core_mult

            # --- Buildings ---
            for b_name in prov.get("buildings", []):
                stats = building_library.get(b_name, {})
                econ_data[owner]["man_inc"] += stats.get("prod_manpower", 0) * man_mult
                econ_data[owner]["mat_inc"] += stats.get("prod_materials", 0) * core_mult
                econ_data[owner]["fuel_inc"] += stats.get("prod_fuel", 0) * core_mult
        
        # --- Unit Upkeeps ---
        for unit in prov.get("units", []):
            u_owner = unit.get("owner")
            if u_owner in econ_data:
                stats = unit_library.get(unit["type"], {})
                econ_data[u_owner]["man_upk"] += stats.get("cost_manpower", 0) * UPKEEP_MODIFIER
                econ_data[u_owner]["mat_upk"] += stats.get("cost_materials", 0) * UPKEEP_MODIFIER
                econ_data[u_owner]["fuel_upk"] += stats.get("cost_fuel", 0) * UPKEEP_MODIFIER

    # --- Treeview UI Setup ---
    columns = (
        "Country", 
        "Net Manpower", 
        "Net Materials", 
        "Net Fuel", 
    )
    
    tree = ttk.Treeview(root, columns=columns, show="headings")
    
    # Zebra striping tags to simulate table lines
    tree.tag_configure('evenrow', background='#ffffff')
    tree.tag_configure('oddrow', background='#f2f2f2') 
    
    # State dictionary to track ascending/descending sort for each column
    sort_dirs = {col: True for col in columns}

    # Sorting Logic
    def sort_data(col):
        reverse = sort_dirs[col]
        sort_dirs[col] = not reverse # Toggle for the next time it's clicked
        
        def get_val(c):
            d = econ_data[c]
            if col == "Country": return c
            if col == "Net Manpower": return d["man_inc"] - d["man_upk"]
            if col == "Net Materials": return d["mat_inc"] - d["mat_upk"]
            if col == "Net Fuel": return d["fuel_inc"] - d["fuel_upk"]
            return 0

        # Sort the countries using the dynamic value generator
        sorted_countries = sorted(active_countries, key=get_val, reverse=reverse)
        
        # Clear existing rows
        for item in tree.get_children():
            tree.delete(item)
            
        # Re-populate using the sorted list
        populate_tree(sorted_countries)

    # Set up column headers and bind the sorting command
    widths = {
        "Country": 140,
        "Net Manpower": 120,
        "Net Materials": 120,
        "Net Fuel": 110,
    }

    for col in columns:
        # Passing col to lambda safely captures its state for the button click
        tree.heading(col, text=col, command=lambda c=col: sort_data(c))
        tree.column(col, width=widths[col], anchor="center")
    
    # Helper formatters
    def fmt(net): 
        return f"+{int(net)}" if net >= 0 else str(int(net))
        
    def fmt_full(gross, upk):
        net = gross - upk
        return f"+{int(gross)} / -{int(upk)} / {fmt(net)}"
    
    def populate_tree(country_list):
        for i, c in enumerate(country_list):
            d = econ_data[c]
            
            # Calculate other Nets
            man_net = d["man_inc"] - d["man_upk"]
            mat_net = d["mat_inc"] - d["mat_upk"]
            fuel_net = d["fuel_inc"] - d["fuel_upk"]
                        
            # Apply zebra stripe tags
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            
            tree.insert("", tk.END, values=(
                c, 
                fmt(man_net), 
                fmt(mat_net), 
                fmt(fuel_net), 
            ), tags=(tag,))

    # Initial population (Defaults to alphabetical)
    populate_tree(sorted(active_countries))

    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    tree.configure(yscroll=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)

    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
        except:
            break

    scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
    tree.configure(yscroll=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)

    while self.menu_active:
        try:
            root.update()
            pygame.event.pump()
        except:
            break


def open_map_research_editor(self):
    """Opens a UI to edit research for countries currently existing on the map."""
    active_countries = set()
    for prov in self.map_data.values():
        owner = prov.get("owner")
        if owner and owner not in ["None", "Unclaimed", "Ocean", "Lakes"]:
            active_countries.add(owner)

    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    def get_default_research():
        if getattr(self, "default_research", None) is not None:
            return self.default_research

        template_path = "data/json/research_template.json"
        res_dict = {}
        if os.path.exists(template_path):
            with open(template_path, "r") as f:
                struct = json.load(f)
            res_dict = {tech: (1800 if data["max_lvl"] == 9999 else 0) for tech, data in struct.items()}
            if "carrack" in res_dict: res_dict["carrack"] = 1
        return res_dict

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
        except:
            break


def select_unit_brush(self):
    """Opens a selection window for unit types and sets mode to UNIT."""
    root = tk.Tk()
    root.title("Select Unit")
    root.geometry("300x400")
    root.attributes("-topmost", True)
    self.menu_active = True

    unit_path = 'data/json/unit_data.json'
    units = list(json.load(open(unit_path, 'r')).keys()) if os.path.exists(unit_path) else []

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
    dropdown = ttk.Combobox(root, values=["Iron", "Coal", "Oil"], state="readonly", font=("Arial", 11))
    dropdown.set("Iron") # Set the default visual value
    dropdown.pack(pady=5)

    tk.Label(root, text="Resource Amount:", font=("Arial", 12)).pack(pady=5)
    amt_ent = tk.Entry(root, font=("Arial", 11), justify="center")
    amt_ent.insert(0, "50")
    amt_ent.pack(pady=5)

    def on_confirm():
        try:
            amt = int(amt_ent.get())
            # FIX: Grab the value directly from the dropdown widget
            self.brush_resource_type = dropdown.get() 
            self.brush_resource_amount = amt
            self.editor_mode = "RESOURCE"
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
        except (tk.TclError, Exception):
            break