import sys
import os

# Add the parent directory (project root) to the Python path so it can find the 'data' module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import tkinter as tk
from tkinter import messagebox
import data.constants as c
import json
from data import queries

PATH = c.UNIT_DATA_PATH

class UnitEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Unit Data Editor")
        self.data = self.load_data()

        fields = [
            ("Unit Name", "name"),
            ("HP", "health"),
            ("Attack", "attack"),
            ("Defense", "defense"),
            ("Speed", "speed"),
            ("Cost (Materials)", "cost_materials"),
            ("Cost (Manpower)", "cost_manpower"),
            ("Cost (Fuel)", "cost_fuel"),
            ("Time", "production_time")
        ]

        self.entries = {}
        for i, (label, key) in enumerate(fields):
            tk.Label(root, text=label).grid(row=i, column=0, padx=10, pady=5)
            ent = tk.Entry(root)
            ent.grid(row=i, column=1, padx=10, pady=5)
            self.entries[key] = ent

        # Main Save Button
        tk.Button(root, text="Save/Update Unit", command=self.save_unit).grid(row=len(fields), column=0, columnspan=2, pady=5)
        
        # New Format Button
        tk.Button(root, text="Reset Formatting to One-Line", command=self.format_json).grid(row=len(fields)+1, column=0, columnspan=2, pady=5)
        
        self.listbox = tk.Listbox(root, width=50)
        self.listbox.grid(row=len(fields)+2, column=0, columnspan=2, padx=10, pady=10)
        self.listbox.bind('<<ListboxSelect>>', self.on_select)
        self.refresh_list()

    def load_data(self):
        if os.path.exists(PATH):
            with open(PATH, "r") as f: return json.load(f)
        return {}

    def custom_json_dump(self, data_dict, filepath):
        """Custom dumper to keep top-level items on new lines, but inner dicts compact."""
        lines = ["{"]
        items = list(data_dict.items())
        for i, (key, val) in enumerate(items):
            # separators=(', ', ': ') removes trailing spaces around formatting to keep it tight
            val_str = json.dumps(val, separators=(', ', ': '))
            comma = "," if i < len(items) - 1 else ""
            lines.append(f'    "{key}": {val_str}{comma}')
        lines.append("}")
        
        with open(filepath, "w") as f:
            f.write("\n".join(lines))
            
        queries.clear_json_caches()  # <-- CLEAR CACHE AFTER DISK WRITE

    def format_json(self):
        """Forces the current data dictionary to rewrite using the custom one-line format."""
        if not self.data:
            messagebox.showwarning("Warning", "No data to format.")
            return
            
        self.custom_json_dump(self.data, PATH)
        messagebox.showinfo("Success", "Unit JSON has been reset to one-line format!")

    def save_unit(self):
        name = self.entries["name"].get().strip()
        if not name: return
        
        try:
            self.data[name] = {
                "health": int(self.entries["health"].get() or 0), 
                "attack": int(self.entries["attack"].get() or 0), 
                "defense": int(self.entries["defense"].get() or 0), 
                "speed": int(self.entries["speed"].get() or 1), 
                "cost_materials": int(self.entries["cost_materials"].get() or 0), 
                "cost_manpower": int(self.entries["cost_manpower"].get() or 0), 
                "cost_fuel": int(self.entries["cost_fuel"].get() or 0), 
                "production_time": int(self.entries["production_time"].get() or 5), 
                "naval_unit": False, 
                "order": {}
            }
            
            # Use the custom dumper instead of standard json.dump
            self.custom_json_dump(self.data, PATH)
            
            messagebox.showinfo("Success", f"Updated {name}")
            self.refresh_list()
        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers for stats.")

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for name in self.data:
            self.listbox.insert(tk.END, name)

    def on_select(self, event):
        selection = event.widget.curselection()
        if selection:
            name = event.widget.get(selection[0])
            unit = self.data[name]
            for key, ent in self.entries.items():
                ent.delete(0, tk.END)
                if key == "name": ent.insert(0, name)
                else: ent.insert(0, str(unit.get(key, 0)))

if __name__ == "__main__":
    root = tk.Tk()
    UnitEditor(root)
    root.mainloop()