import sys
import os

# Add the parent directory (project root) to the Python path so it can find the 'data' module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import tkinter as tk
from tkinter import messagebox, ttk
from data import queries
from ui import confirm_dialog

class TurnEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Construction Turns Editor")
        
        # Load the base un-modified definitions to display defaults
        self.unit_data = queries._load_cached_json("unit_library") or {}
        self.building_data = queries._load_cached_json("building_library") or {}
        
        # Load scenario settings to read/write overrides
        self.settings = queries.get_scenario_settings() or {}
        self.unit_overrides = self.settings.get("unit_turn_overrides", {})
        self.building_overrides = self.settings.get("building_turn_overrides", {})

        self.create_widgets()

    def create_widgets(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Units Tab
        self.unit_frame = ttk.Frame(notebook)
        notebook.add(self.unit_frame, text="Units")
        self.setup_tab(self.unit_frame, self.unit_data, self.unit_overrides, "production_time", "Unit Name")

        # Buildings Tab
        self.building_frame = ttk.Frame(notebook)
        notebook.add(self.building_frame, text="Buildings")
        self.setup_tab(self.building_frame, self.building_data, self.building_overrides, "time", "Building Name")

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Button(btn_frame, text="Save All Changes", command=self.save_all).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Reset to Defaults", command=self.reset_to_defaults, fg="red").pack(side=tk.RIGHT, padx=5)

    def setup_tab(self, parent_frame, data_dict, override_dict, turn_key, label_text):
        list_frame = tk.Frame(parent_frame)
        list_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        
        listbox = tk.Listbox(list_frame, width=40)
        listbox.pack(side=tk.LEFT, fill=tk.Y)
        
        scrollbar = tk.Scrollbar(list_frame, command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.config(yscrollcommand=scrollbar.set)
        
        edit_frame = tk.Frame(parent_frame)
        edit_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        tk.Label(edit_frame, text=label_text).grid(row=0, column=0, pady=5, sticky=tk.W)
        name_entry = tk.Entry(edit_frame, state='readonly', width=30)
        name_entry.grid(row=0, column=1, pady=5)
        
        tk.Label(edit_frame, text="Turns to Construct").grid(row=1, column=0, pady=5, sticky=tk.W)
        turn_entry = tk.Entry(edit_frame, width=10)
        turn_entry.grid(row=1, column=1, pady=5, sticky=tk.W)
        
        # Group items by base type
        base_types = {}
        for name, item_data in data_dict.items():
            btype = queries.get_base_item_name(name)
            if btype not in base_types:
                base_types[btype] = []
            base_types[btype].append(name)
            
        def on_select(event):
            selection = event.widget.curselection()
            if selection:
                btype = event.widget.get(selection[0])
                
                name_entry.config(state='normal')
                name_entry.delete(0, tk.END)
                name_entry.insert(0, btype)
                name_entry.config(state='readonly')
                
                # Show turn value (override if exists, else first item's default)
                first_item = base_types[btype][0]
                default_turn = data_dict[first_item].get(turn_key, 0)
                current_turn = override_dict.get(btype, default_turn)
                
                turn_entry.delete(0, tk.END)
                turn_entry.insert(0, str(current_turn))
                
        def apply_change():
            btype = name_entry.get()
            if not btype:
                return
            try:
                new_turns = int(turn_entry.get())
                if new_turns < 1:
                    new_turns = 1
                    
                override_dict[btype] = new_turns
                messagebox.showinfo("Applied", f"Updated all '{btype}' to {new_turns} turns. (Don't forget to Save All)")
            except ValueError:
                messagebox.showerror("Error", "Please enter a valid integer for turns.")
                
        listbox.bind('<<ListboxSelect>>', on_select)
        tk.Button(edit_frame, text="Apply locally", command=apply_change).grid(row=2, column=0, columnspan=2, pady=10)
        
        for btype in base_types:
            listbox.insert(tk.END, btype)

    def save_all(self):
        self.settings["unit_turn_overrides"] = self.unit_overrides
        self.settings["building_turn_overrides"] = self.building_overrides
        queries.save_scenario_settings(self.settings)
        messagebox.showinfo("Saved", "Successfully saved overrides to scenario settings.")
        self.root.destroy()

    def reset_to_defaults(self):
        confirm = confirm_dialog.ask_yes_no("Confirm Reset", "Are you sure you want to clear overrides and reset to defaults? This applies to the current scenario.", tk_parent=self.root)
        if confirm:
            self.unit_overrides.clear()
            self.building_overrides.clear()
            self.save_all()

def open_turn_editor():
    root = tk.Tk()
    app = TurnEditor(root)
    root.geometry("600x400")
    root.mainloop()

if __name__ == "__main__":
    open_turn_editor()
