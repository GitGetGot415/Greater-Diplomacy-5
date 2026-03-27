import tkinter as tk
from tkinter import messagebox, colorchooser
import json
import os
import colorsys

PATH = "map_functions/data/countries_data.json"

class CountryEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Greater Diplomacy - Country Editor")
        self.data = self.load_data()
        self.sort_mode = "NAME"

        # --- Editor UI (Top) ---
        editor_frame = tk.LabelFrame(root, text="Country Details", padx=10, pady=10)
        editor_frame.pack(fill="x", padx=10, pady=5)

        self.color_preview = tk.Canvas(editor_frame, width=50, height=25, bg="grey", highlightthickness=1)
        self.color_preview.grid(row=0, column=2, padx=5)

        tk.Label(editor_frame, text="Internal ID:").grid(row=0, column=0, sticky="w")
        self.id_ent = tk.Entry(editor_frame)
        self.id_ent.grid(row=0, column=1, sticky="we")

        tk.Label(editor_frame, text="Display Name:").grid(row=1, column=0, sticky="w")
        self.name_ent = tk.Entry(editor_frame)
        self.name_ent.grid(row=1, column=1, sticky="we")

        self.color_btn = tk.Button(editor_frame, text="Pick Color", command=self.pick_color)
        self.color_btn.grid(row=2, column=0, columnspan=2, sticky="we", pady=5)
        self.current_color = [150, 150, 150]

        tk.Button(editor_frame, text="Save/Update Country", bg="#4CAF50", fg="white", 
                  command=self.save_country).grid(row=3, column=0, columnspan=3, sticky="we")

        # --- Utility Bar (New Section for Bulk Actions) ---
        util_frame = tk.Frame(root, padx=10)
        util_frame.pack(fill="x", pady=5)
        
        tk.Button(util_frame, text="⚠️ Reset All Countries to Template ⚠️", bg="#f44336", fg="white",
                  command=self.bulk_reset_template).pack(fill="x")

        # --- Control Bar (Middle) ---
        controls_frame = tk.Frame(root, padx=10)
        controls_frame.pack(fill="x", pady=5)

        tk.Label(controls_frame, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.refresh_list())
        self.search_ent = tk.Entry(controls_frame, textvariable=self.search_var)
        self.search_ent.pack(side="left", fill="x", expand=True, padx=5)

        self.btn_sort = tk.Button(controls_frame, text="Sort: Name", width=12, command=self.toggle_sort)
        self.btn_sort.pack(side="right")

        # --- Country List UI (Bottom) ---
        list_container = tk.Frame(root)
        list_container.pack(fill="both", expand=True, padx=10, pady=10)

        self.canvas = tk.Canvas(list_container)
        scrollbar = tk.Scrollbar(list_container, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.refresh_list()

    # --- NEW METHOD: Bulk Reset ---
    def bulk_reset_template(self):
        """Updates every country in the list to the new data format while keeping Name/Color."""
        msg = ("This will reset research, money, and relations for ALL countries to the default template.\n\n"
               "Names and Colors will be preserved. Proceed?")
        if not messagebox.askyesno("Confirm Bulk Reset", msg):
            return

        for int_id in self.data:
            # Preserve existing identifying info
            old_name = self.data[int_id].get("name", int_id)
            old_color = self.data[int_id].get("color", [150, 150, 150])

            # Overwrite with the template
            self.data[int_id] = {
                "name": old_name,
                "color": old_color,
                "research": {"infantry": 1800},
                "money": 0, "manpower": 0, "materials": 0, "fuel": 0,      
                "is_playable": True,
                "at_war_with": [], "allied_with": []
            }

        with open(PATH, "w") as f:
            json.dump(self.data, f, indent=4)
        
        messagebox.showinfo("Success", "All countries have been synchronized to the new template.")
        self.refresh_list()

    def toggle_sort(self):
        if self.sort_mode == "NAME":
            self.sort_mode = "COLOR"
            self.btn_sort.config(text="Sort: Color")
        else:
            self.sort_mode = "NAME"
            self.btn_sort.config(text="Sort: Name")
        self.refresh_list()

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def load_data(self):
        if os.path.exists(PATH):
            try:
                with open(PATH, "r") as f: return json.load(f)
            except: return {}
        return {}

    def pick_color(self):
        color = colorchooser.askcolor(title="Choose Country Color")
        if color[0]: 
            self.current_color = [int(c) for c in color[0]]
            hex_color = '#%02x%02x%02x' % tuple(self.current_color)
            self.color_preview.config(bg=hex_color)

    def save_country(self):
        int_id = self.id_ent.get().strip()
        disp_name = self.name_ent.get().strip() or int_id
        
        if not int_id: 
            messagebox.showwarning("Error", "Internal ID cannot be empty")
            return
        
        if int_id in self.data:
            self.data[int_id]["name"] = disp_name
            self.data[int_id]["color"] = self.current_color
        else:
            self.data[int_id] = {
                "name": disp_name,
                "color": self.current_color,
                "research": {"infantry": 1800},
                "money": 0, "manpower": 0, "materials": 0, "fuel": 0,      
                "is_playable": True,
                "at_war_with": [], "allied_with": []
            }
        
        with open(PATH, "w") as f:
            json.dump(self.data, f, indent=4)
        
        self.refresh_list()
        self.id_ent.delete(0, tk.END)
        self.name_ent.delete(0, tk.END)

    def delete_country(self, int_id):
        if messagebox.askyesno("Confirm", f"Delete {int_id}?"):
            del self.data[int_id]
            with open(PATH, "w") as f:
                json.dump(self.data, f, indent=4)
            self.refresh_list()

    def load_into_editor(self, int_id):
        country = self.data[int_id]
        self.id_ent.delete(0, tk.END)
        self.id_ent.insert(0, int_id)
        self.name_ent.delete(0, tk.END)
        self.name_ent.insert(0, country.get("name", int_id))
        self.current_color = country.get("color", [150, 150, 150])
        hex_color = '#%02x%02x%02x' % tuple(self.current_color)
        self.color_preview.config(bg=hex_color)

    def get_sort_key(self, int_id):
        if self.sort_mode == "NAME":
            return int_id.lower()
        else:
            rgb = self.data[int_id].get("color", [0, 0, 0])
            return colorsys.rgb_to_hsv(rgb[0]/255, rgb[1]/255, rgb[2]/255)

    def refresh_list(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        search_query = self.search_var.get().lower()
        sorted_keys = sorted(self.data.keys(), key=self.get_sort_key)

        for int_id in sorted_keys:
            disp_name = self.data[int_id].get("name", int_id)
            if search_query and search_query not in int_id.lower() and search_query not in disp_name.lower():
                continue

            country_row = tk.Frame(self.scrollable_frame, pady=2, padx=5)
            country_row.pack(fill="x", expand=True)

            rgb = self.data[int_id].get("color", [150, 150, 150])
            hex_color = '#%02x%02x%02x' % tuple(rgb)

            tk.Label(country_row, bg=hex_color, width=3, relief="ridge").pack(side="left")
            list_txt = f"{int_id} ({disp_name})" if int_id != disp_name else int_id
            tk.Label(country_row, text=list_txt, width=30, anchor="w").pack(side="left", padx=5)
            
            tk.Button(country_row, text="Del", fg="red", width=3, 
                      command=lambda i=int_id: self.delete_country(i)).pack(side="right", padx=2)
            tk.Button(country_row, text="Edit", width=4, 
                      command=lambda i=int_id: self.load_into_editor(i)).pack(side="right", padx=2)

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("500x800") # Slightly taller to fit the new button
    CountryEditor(root)
    root.mainloop()