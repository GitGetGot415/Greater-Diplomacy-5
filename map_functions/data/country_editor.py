import tkinter as tk
from tkinter import messagebox, colorchooser
import json
import os

PATH = "map_functions/data/countries_data.json"

class CountryEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Country Data Editor")
        self.data = self.load_data()

        # UI Elements
        tk.Label(root, text="Country Name:").grid(row=0, column=0)
        self.name_ent = tk.Entry(root)
        self.name_ent.grid(row=0, column=1)

        """tk.Label(root, text="Starting Money:").grid(row=1, column=0)
        self.money_ent = tk.Entry(root)
        self.money_ent.grid(row=1, column=1)"""

        self.color_btn = tk.Button(root, text="Pick Color", command=self.pick_color)
        self.color_btn.grid(row=2, column=0, columnspan=2)
        self.current_color = (150, 150, 150)

        tk.Button(root, text="Save/Update Country", command=self.save_country).grid(row=3, column=0, columnspan=2)
        
        self.listbox = tk.Listbox(root)
        self.listbox.grid(row=4, column=0, columnspan=2, sticky="we")
        self.refresh_list()

    def load_data(self):
        if os.path.exists(PATH):
            with open(PATH, "r") as f: return json.load(f)
        return {}

    def pick_color(self):
        color = colorchooser.askcolor(title="Choose Country Color")[0]
        if color: self.current_color = [int(c) for c in color]

    def save_country(self):
        name = self.name_ent.get().strip()
        if not name: return
        
        self.data[name] = {
            "color": self.current_color,
            "money": int(self.money_ent.get() or 0),
            "manpower": 0,
            "is_playable": True,
            "at_war_with": [],
            "allied_with": []
        }
        
        with open(PATH, "w") as f:
            json.dump(self.data, f, indent=4)
        
        messagebox.showinfo("Success", f"Updated {name}")
        self.refresh_list()

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for name in self.data:
            self.listbox.insert(tk.END, f"{name} (Gold: {self.data[name]['money']})")

if __name__ == "__main__":
    root = tk.Tk()
    CountryEditor(root)
    root.mainloop()