import pygame
import tkinter as tk
from tkinter import ttk, filedialog
import json
import os
from map_functions.data.economy_data import BASE_YIELDS, UPKEEP_MODIFIER

def editor_load_map(self):
    """Opens a file dialog to load a map folder directly into the editor."""
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askdirectory(initialdir="scenarios", title="Select Map Folder to Edit")
    root.destroy()

    if path:
        # Re-run asset loader on this instance
        from map_functions.data import load_map
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
    root.geometry("600x400")
    root.attributes("-topmost", True)
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", close_menu)

    # Economy logic
    YIELD_MONEY = BASE_YIELDS["money"]
    
    unit_library = {}
    building_library = {}
    if os.path.exists('map_functions/data/json/unit_data.json'):
        with open('map_functions/data/json/unit_data.json', 'r') as f: unit_library = json.load(f)
    if os.path.exists('map_functions/data/json/building_data.json'):
        with open('map_functions/data/json/building_data.json', 'r') as f: building_library = json.load(f)

    econ_data = {c: {"inc": 0, "bonus": 0, "upkeep": 0} for c in active_countries}

    for prov in self.map_data.values():
        owner = prov.get("owner")
        if owner in econ_data:
            econ_data[owner]["inc"] += 1
            for b_name in prov.get("buildings", []):
                stats = building_library.get(b_name, {})
                econ_data[owner]["bonus"] += stats.get("prod_money", 0)
        
        for unit in prov.get("units", []):
            u_owner = unit.get("owner")
            if u_owner in econ_data:
                stats = unit_library.get(unit["type"], {})
                econ_data[u_owner]["upkeep"] += stats.get("cost_money", 0) * UPKEEP_MODIFIER

    columns = ("Country", "Provinces", "Gross Income", "Upkeep", "Net Income", "Treasury")
    tree = ttk.Treeview(root, columns=columns, show="headings")
    for col in columns:
        tree.heading(col, text=col)
        tree.column(col, width=95, anchor="center")
    
    for c in sorted(active_countries):
        d = econ_data[c]
        provinces = d["inc"]
        gross = (d["inc"] * YIELD_MONEY) + d["bonus"]
        upk = int(d["upkeep"])
        net = gross - upk
        treasury = self.nation_data.get(c, {}).get("money", 0)
        tree.insert("", tk.END, values=(c, provinces, f"+{gross}", f"-{upk}", f"{'+' if net>=0 else ''}{net}", treasury))

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

        template_path = "map_functions/data/json/research_template.json"
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

    unit_path = 'map_functions/data/json/unit_data.json'
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