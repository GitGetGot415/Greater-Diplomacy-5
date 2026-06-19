import tkinter as tk
from tkinter import ttk, messagebox, colorchooser, filedialog
import pygame
import os
import tempfile
import re
import data.constants as c
from data import queries
from map_logic.system32.time_handler import TimeHandler

def open_scripted_events_editor(self):
    active_countries = queries.get_living_nations(self.map_data)
    if not active_countries:
        self.show_feedback("No active countries on map!")
        return

    root = queries.create_tk_window("Scripted Events Editor", "650x550")
    self.menu_active = True

    def close_menu():
        self.menu_active = False
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close_menu)

    def show_scripted_events_help():
        """Spawns a read-only popup explaining the scripting engine."""
        help_win = tk.Toplevel(root)
        help_win.title("Scripted Events Help")
        help_win.geometry("700x800")
        help_win.attributes("-topmost", True)
        
        text_widget = tk.Text(help_win, wrap="word", font=("Arial", 10))
        text_widget.pack(fill="both", expand=True, padx=10, pady=10)
        
        help_text = """ === EVENT TYPE ===
- AI Only: Event fires only if this country is controlled by an AI
- Player Only: Event fires only if this country is controlled by a player
- Both: Event fires if this country is controlled by either an AI or a player

=== CONDITIONALS ===
- Turn Number: Checks if the current game turn matches the specified value
- At War With: Checks if the nation is at war with the specified target(s) (comma-separated)
- Is At War: Checks if the target nation (or self if blank) is currently in any war
- In Faction With: Checks if the nation shares a faction with the target(s)
- Not In Faction With: Checks if the nation does NOT share a faction with the target(s)
- Is In Faction: Checks if the target nation (or self if blank) is currently in any faction
- Is Faction Leader: Checks if the target nation (or self if blank) is the leader of their faction
- Has Truce With: Checks if the nation has an active truce with the specified target(s) (comma-separated)
- At Peace With: Checks if the nation is explicitly NOT at war with the target(s)
- Is At Peace: Checks if the target nation (or self if blank) is in ZERO wars
- Random (0.00 - 1.00): Returns a random value between 0.0 and 1.0
- Received Action: Checks if a specific diplomatic action is pending from a specific sender
- Country Exists: Checks if the target(s) currently hold territory on the map
- Country Doesn't Exist: Checks if the target(s) are completely wiped off the map
- Occupying Core Of: Checks if the nation occupies any core of the target
- Occupying All Cores Of: Checks if the nation occupies EVERY core of the target
- Occupying Claims Of: Checks if the nation occupies any claim of the target
- Occupying All Claims: Checks if the nation occupies EVERY claim of the target
- Occupying Tile: Checks if the nation occupies specific province IDs (comma-separated)
- Is AI Controlled: Checks if the target nation (or self if blank) is controlled by AI
- Is Player Controlled: Checks if the target nation (or self if blank) is controlled by a human
- Bordering / Not Bordering: Checks physical adjacency to the target

=== ACTIONS ===
- Declare War: Declares war on the target
- Join Faction / Create Faction / Invite to Faction: Modifies faction alignments
- Accept / Reject Proposal: Responds to a pending diplomatic request
- Send Ceasefire: Offers peace to the target
- Send Custom Message: Sends a text message to the target
- Queue Claims: Begins fabricating claims on the specified Province IDs (comma-separated)
- Revoke Claims: Removes claims on the specified Province IDs (comma-separated)
- Revoke All Claims: Removes ALL claims held by the target nation
- Edit Name / Leader / Title: Changes cosmetic names for the event owner
- Edit Color / Flag / Portrait: Modifies cosmetic visual aspects

The AI Msg Checkbox means that you can allow the ai to generate custom text for that message
It will fallback to whatever you manually entered if the llm ai is turned off or otherwise fails"""
        
        text_widget.insert("1.0", help_text)
        text_widget.config(state="disabled") # Make read-only

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
                a_type = a.get('type')
                if a_type == "Send Custom Message":
                    act_strs.append(f"MSG to '{a.get('target')}'")
                elif a_type in ["Edit Name", "Edit Leader Name", "Edit Leader Title", "Edit Color", "Edit Flag", "Edit Portrait"]:
                    act_strs.append(f"{a_type}: '{a.get('message')}'")
                elif a_type == "Queue Claims":
                    act_strs.append(f"Queue Claims on Provs: '{a.get('message')}'")
                elif a_type == "Revoke Claims":
                    act_strs.append(f"Revoke Claims on Provs: '{a.get('message')}'")
                elif a_type == "Revoke All Claims":
                    act_strs.append(f"Revoke All Claims for '{a.get('target')}'")
                else:
                    act_strs.append(f"{a_type} '{a.get('target')}'")
                    
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
        
        help_btn = tk.Button(top_frame, text="Help / Info", command=show_scripted_events_help, bg="#2196F3", fg="white", font=("Arial", 9, "bold"))
        help_btn.pack(side="right", padx=10)
        
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
            if idx > 1: # Prevents moving above the primary IF condition
                row_objects.insert(idx - 1, row_objects.pop(idx))
                repack_conditions()

        def move_down(r_obj):
            idx = row_objects.index(r_obj)
            if idx > 0 and idx < len(row_objects) - 1: # Prevents the IF condition from moving down
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
            
            type_cb = ttk.Combobox(row_frame, textvariable=type_var, values=["Turn Number", "At War With", "Is At War", "In Faction With", "Not In Faction With", "Is In Faction", "Is Faction Leader", "Has Truce With", "At Peace With", "Is At Peace", "Random (0.00 - 1.00)", "Received Action", "Country Exists", "Country Doesn't Exist", "Occupying Core Of", "Occupying All Cores Of", "Occupying Claims Of", "Occupying All Claims", "Occupying Tile", "Is AI Controlled", "Is Player Controlled", "Bordering", "Not Bordering", "True", "False"], width=18, state="readonly")
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
                        d_str = get_expected_date_string(val_var.get())
                        if d_str:
                            date_lbl.config(text=f"({d_str})")
                        else:
                            date_lbl.config(text="")
                    else:
                        date_lbl.config(text="")
                elif ctype == "Received Action":
                    op_cb.config(values=["WAR_DECLARATION", "JOIN_WARS", "CALL_TO_ARMS", "CREATE_FACTION", "FACTION_INVITE", "JOIN_FACTION_REQ", "TRADE", "CEASEFIRE"])
                    if op_var.get() not in ["WAR_DECLARATION", "JOIN_WARS", "CALL_TO_ARMS", "CREATE_FACTION", "FACTION_INVITE", "JOIN_FACTION_REQ", "TRADE", "CEASEFIRE"]:
                        op_var.set("WAR_DECLARATION")
                    date_lbl.config(text="(Sender Nation ID)")
                elif ctype in ["At War With", "In Faction With", "Not In Faction With", "Has Truce With", "At Peace With", "Country Exists", "Country Doesn't Exist", "Occupying Claims Of", "Occupying All Claims"]:
                    op_cb.config(values=["=="])
                    op_var.set("==")
                    date_lbl.config(text="(Target Nation IDs, comma separated)")
                elif ctype in ["True", "False"]:
                    op_cb.config(values=["=="])
                    op_var.set("==")
                    date_lbl.config(text="")
                elif ctype == "Occupying All Cores Of":
                    op_cb.config(values=["==", "!="])
                    if op_var.get() not in ["==", "!="]: op_var.set("==")
                    date_lbl.config(text="(Target Nation IDs, comma separated)")
                elif ctype == "Occupying Tile":
                    op_cb.config(values=["==", "!="])
                    if op_var.get() not in ["==", "!="]: op_var.set("==")
                    date_lbl.config(text="(Tile IDs, comma separated)")
                elif ctype in ["Is AI Controlled", "Is Player Controlled", "Is At War", "Is At Peace", "Is In Faction", "Is Faction Leader"]:
                    op_cb.config(values=["=="])
                    op_var.set("==")
                    date_lbl.config(text="(Target Nation ID, or blank for self)")
                else:
                    op_cb.config(values=["=="])
                    op_var.set("==")
                    date_lbl.config(text="(Target Nation ID, comma separated)")
            
            type_var.trace_add("write", update_row)
            val_var.trace_add("write", update_row)
            update_row()
            
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
                a_data = {"type": "Declare War", "target": "None", "message": ""}
                
            row_frame = tk.Frame(act_frame, relief="ridge", bd=2)
            row_frame.pack(fill="x", pady=2, padx=2)
            
            type_var = tk.StringVar(value=a_data.get("type", "Declare War"))
            target_var = tk.StringVar(value=a_data.get("target", "None"))
            msg_var = tk.StringVar(value=a_data.get("message", ""))
            ai_var = tk.BooleanVar(value=a_data.get("ai_generate", False))
            
            edit_options = ["Edit Name", "Edit Leader Name", "Edit Leader Title", "Edit Color", "Edit Flag", "Edit Portrait"]
            all_options = ["Declare War", "Join Faction", "Create Faction", "Invite to Faction", "Accept Proposal", "Reject Proposal", "Send Ceasefire", "Send Custom Message", "Queue Claims", "Revoke Claims", "Revoke All Claims"] + edit_options
            
            type_cb = ttk.Combobox(row_frame, textvariable=type_var, values=all_options, width=18, state="readonly")
            type_cb.pack(side="left", padx=5)
            
            target_cb = ttk.Combobox(row_frame, textvariable=target_var, values=["None"] + sorted(active_countries), width=18)
            msg_ent = tk.Entry(row_frame, textvariable=msg_var, width=20)
            ai_cb = tk.Checkbutton(row_frame, text="AI Msg", variable=ai_var)
            
            def do_pick_color():
                color_code = colorchooser.askcolor(title="Choose color")[0]
                if color_code:
                    msg_var.set(f"{int(color_code[0])},{int(color_code[1])},{int(color_code[2])}")
                    update_act_row()

            def do_pick_image():
                filepath = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")])
                if filepath:
                    try:
                        img = pygame.image.load(filepath).convert_alpha()
                        is_port = type_var.get() == "Edit Portrait"
                        size = c.PORTRAIT_SIZE if is_port else c.FLAG_SIZE
                        img = pygame.transform.scale(img, size)
                        b64_str = queries.encode_surf_to_b64(img)
                        msg_var.set(b64_str)
                        update_act_row()
                    except Exception as e:
                        messagebox.showerror("Error", f"Could not load image: {e}")

            pick_color_btn = tk.Button(row_frame, text="Pick Color", command=do_pick_color)
            pick_img_btn = tk.Button(row_frame, text="Browse Image", command=do_pick_image)
            preview_lbl = tk.Label(row_frame, width=4, height=1)

            row_obj = {
                "frame": row_frame,
                "type_var": type_var,
                "target_var": target_var,
                "msg_var": msg_var,
                "ai_var": ai_var
            }
            
            def update_act_row(*args):
                t = type_var.get()
                
                target_cb.pack_forget()
                msg_ent.pack_forget()
                ai_cb.pack_forget()
                pick_color_btn.pack_forget()
                pick_img_btn.pack_forget()
                preview_lbl.pack_forget()

                if t == "Send Custom Message":
                    target_cb.pack(side="left", padx=5)
                    msg_ent.pack(side="left", padx=5)
                    ai_cb.pack(side="left", padx=5)
                elif t == "Edit Color":
                    target_var.set("None")
                    pick_color_btn.pack(side="left", padx=5)
                    preview_lbl.pack(side="left", padx=5)
                    try:
                        c_val = msg_var.get()
                        if c_val:
                            r,g,b = map(int, c_val.split(','))
                            preview_lbl.config(bg=f"#{r:02x}{g:02x}{b:02x}", image='', width=4, height=1)
                        else:
                            preview_lbl.config(bg='gray', image='', width=4, height=1)
                    except:
                        preview_lbl.config(bg='gray', image='', width=4, height=1)
                elif t in ["Edit Flag", "Edit Portrait"]:
                    target_var.set("None")
                    pick_img_btn.pack(side="left", padx=5)
                    preview_lbl.pack(side="left", padx=5)
                    
                    b64_str = msg_var.get()
                    if b64_str:
                        is_port = (t == "Edit Portrait")
                        size = c.PORTRAIT_SIZE if is_port else c.FLAG_SIZE
                        
                        surf = queries.decode_b64_to_surf(b64_str, size, is_portrait=is_port, country_name=target)
                        
                        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
                        os.close(tmp_fd)
                        pygame.image.save(surf, tmp_path)
                        
                        try:
                            img = tk.PhotoImage(file=tmp_path)
                            preview_lbl.config(image=img, width=size[0], height=size[1], bg='white')
                            preview_lbl.image = img 
                        except Exception:
                            preview_lbl.config(bg='gray', image='', width=4, height=1)
                            
                        os.remove(tmp_path)
                    else:
                        preview_lbl.config(bg='gray', image='', width=4, height=1)
                elif t in ["Edit Name", "Edit Leader Name", "Edit Leader Title", "Queue Claims", "Revoke Claims"]:
                    target_var.set("None")
                    msg_ent.pack(side="left", padx=5)
                elif t == "Revoke All Claims":
                    target_cb.pack(side="left", padx=5)
                else:
                    target_cb.pack(side="left", padx=5)
                    msg_ent.pack(side="left", padx=5)
                    ai_cb.pack(side="left", padx=5)
                    
            type_var.trace_add("write", update_act_row)
            update_act_row()
            
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
                    "ai_generate": ro["ai_var"].get()
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

    def move_event_up():
        target = current_target[0]
        sel = events_listbox.curselection()
        if not target or not sel: return
        idx = sel[0]
        if idx > 0:
            events = self.nation_data[target]["scripted_events"]
            events.insert(idx - 1, events.pop(idx))
            refresh_events_list()
            events_listbox.selection_set(idx - 1)

    def move_event_down():
        target = current_target[0]
        sel = events_listbox.curselection()
        if not target or not sel: return
        idx = sel[0]
        events = self.nation_data[target]["scripted_events"]
        if idx < len(events) - 1:
            events.insert(idx + 1, events.pop(idx))
            refresh_events_list()
            events_listbox.selection_set(idx + 1)

    btn_frame = tk.Frame(right_frame)
    btn_frame.pack(fill="x", pady=5)
    tk.Button(btn_frame, text="Add New Event", command=lambda: open_event_window(None), bg="#2196F3", fg="white").pack(side="left", expand=True, fill="x", padx=2)
    tk.Button(btn_frame, text="Edit", command=edit_event, bg="#FF9800", fg="black").pack(side="left", expand=True, fill="x", padx=2)
    tk.Button(btn_frame, text="^", command=move_event_up, bg="#d9e1f2", fg="black").pack(side="left", expand=False, fill="x", padx=2)
    tk.Button(btn_frame, text="v", command=move_event_down, bg="#d9e1f2", fg="black").pack(side="left", expand=False, fill="x", padx=2)
    tk.Button(btn_frame, text="Remove", command=remove_event, bg="#f44336", fg="white").pack(side="right", expand=True, fill="x", padx=2)

    queries.run_tk_loop(self, root)