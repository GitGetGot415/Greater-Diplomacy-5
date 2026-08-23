import unicodedata
import data.constants as c
from data.map import load_map
from data import queries

# ==========================================
# EDITOR MENUS
# ==========================================
#
# Every entry point below is a plain function taking the Map_Screen as its
# first argument, which the editor attaches as a method. They almost all do the
# same three things -- refuse to open on an empty map, import a screen class
# late, run it modally -- so those three live in the helpers here and the tools
# below are reduced to what actually differs.


def _has_active_countries(map_screen):
    """Guards the tools that operate on the live nation list.

    Six of them used to carry this check written out verbatim, message and all.
    """
    if not queries.get_living_nations(map_screen.map_data):
        map_screen.show_feedback("No active countries on map!")
        return False
    return True


def _launch(map_screen, screen):
    """Runs `screen` as a modal sub-screen of the editor."""
    from ui.screen_runner import _run_pygame_sub_screen
    _run_pygame_sub_screen(map_screen, screen)


def _launch_editor_screen(map_screen, class_name, *args, needs_countries=False):
    """Opens one of screens.editor_screens' screens, looked up by name."""
    if needs_countries and not _has_active_countries(map_screen):
        return
    from screens import editor_screens
    _launch(map_screen, getattr(editor_screens, class_name)(map_screen, *args))


def _launch_table(map_screen, title, columns, rows, empty_message="Nothing to show.",
                  needs_countries=False, on_row_click=None, row_tint=None):
    """Opens a full-screen sortable table over `rows`."""
    if needs_countries and not _has_active_countries(map_screen):
        return
    from ui.table_screen import TableScreen
    _launch(map_screen, TableScreen(map_screen, title, columns, rows,
                                    empty_message=empty_message,
                                    on_row_click=on_row_click,
                                    row_tint=row_tint))


def editor_load_map(map_screen):
    """Opens the native folder picker to load a map folder directly into the editor."""
    def on_picked(path):
        if path:
            load_map.load_map_assets(map_screen, path)
            map_screen.refresh_political_map()
            map_screen.show_feedback("Map Loaded into Editor")

    queries.open_file_browser(map_screen, "Select Map Folder to Edit", c.SCENARIOS_CUSTOM_DIR,
                              mode="select_folder", on_result=on_picked)

def _select_brush(map_screen, mode, attr, items, title, prompt, feedback_label="Brush"):
    """Opens a listbox, stores the pick on `attr` and arms the matching editor mode."""
    def cb(val):
        setattr(map_screen, attr, val)
        map_screen.editor_mode = mode
        map_screen.show_feedback(f"{feedback_label}: {val}")
    queries.open_listbox_selector(map_screen, title, prompt, items, cb)

def _paintable_nations(map_screen):
    """The nation list every nation-painting brush offers, sorted accent-insensitively."""
    nations = sorted(map_screen.nation_data.keys(), key=lambda k: unicodedata.normalize('NFKD', k).encode('ascii', 'ignore').decode('utf-8').lower())
    return ["Unclaimed", "The Rot", "----------"] + [n for n in nations if n not in ["Unclaimed", "The Rot"] and (n not in c.UNPLAYABLE_NATIONS or n == "None")]

def select_brush_nation(map_screen):
    """Opens a Tkinter selection window and sets mode to NATION."""
    _select_brush(map_screen, "NATION", "brush_nation", _paintable_nations(map_screen),
                  "Select Nation", "Select Paint Nation:")

def select_core_brush(map_screen):
    """Opens a Tkinter selection window and sets mode to CORE."""
    _select_brush(map_screen, "CORE", "brush_nation", _paintable_nations(map_screen),
                  "Select Core Nation", "Select Nation to Add Cores:", "Core Brush")

def select_claim_brush(map_screen):
    """Opens a Tkinter selection window and sets mode to CLAIM."""
    _select_brush(map_screen, "CLAIM", "brush_nation", _paintable_nations(map_screen),
                  "Select Claim Nation", "Select Nation to Add Claims:", "Claim Brush")

def open_editor_claims(map_screen):
    """Opens a full-screen sortable table listing every claim on the map."""
    rows = []
    for c_name in sorted(map_screen.nation_data.keys()):
        claims = map_screen.nation_data[c_name].get("claims", [])
        if claims:
            rows.append({"country": c_name, "claims": ", ".join(map(str, claims))})

    from ui.table_screen import TableColumn
    columns = [
        TableColumn("country", "Country", 180, align="left"),
        TableColumn("claims", "Claimed Provinces", 700, align="left"),
    ]
    _launch_table(map_screen, "Global Claims Overview", columns, rows,
                  empty_message="No claims on the map.")

def select_building_brush(map_screen):
    """Opens a selection window for building types and sets mode to BUILDING."""
    bldg_lib = queries.get_building_library()
    items = ["None"] + list(bldg_lib.keys()) if bldg_lib else ["None"]
    _select_brush(map_screen, "BUILDING", "brush_building", items,
                  "Select Building", "Select Building to Place:")

def spec_select_edit_country(map_screen):
    """Opens a Tkinter window for a Spectator to select which nation to edit."""
    if not _has_active_countries(map_screen):
        return
    items = sorted(queries.get_living_nations(map_screen.map_data))
    def cb(val):
        map_screen.editing_country = val
        map_screen.next_state, map_screen.done = "EDIT_COUNTRY", True
    queries.open_listbox_selector(map_screen, "Select Nation to Edit", "Select Nation to Edit:", items, cb)

def spec_select_research_country(map_screen):
    """Asks a Spectator whose tech tree to open, the way Identity asks whose
    country to edit.

    The R&D button used to hand a spectator the scenario-authoring checkbox
    list, which says what a nation has finished but not what it is working on.
    The real screen shows both -- it just had no way of being pointed at
    anybody other than the player, which is why spectators were diverted away
    from it in the first place.
    """
    if not _has_active_countries(map_screen):
        return
    items = sorted(queries.get_living_nations(map_screen.map_data))
    def cb(val):
        map_screen.viewing_research_country = val
        map_screen.next_state, map_screen.done = "RESEARCH", True
    queries.open_listbox_selector(map_screen, "Select Nation's Research",
                                  "Select Nation to View Research:", items, cb)


def open_editor_date(map_screen):
    """Opens a native screen to edit the game's starting date."""
    _launch_editor_screen(map_screen, "Editor_Date_Screen")


def open_editor_economy(map_screen):
    """Opens a full-screen sortable table of every active country's detailed income."""
    if not _has_active_countries(map_screen):
        return

    active_countries = sorted(queries.get_living_nations(map_screen.map_data))
    all_econ = queries.calculate_all_economies(map_screen.map_data, map_screen.nation_data)

    def get_stats(cid, res_key):
        d = all_econ[cid]
        bd = d["breakdown"][res_key]
        cur = int(map_screen.nation_data.get(cid, {}).get(res_key, 0))
        inc = int(bd["core"] + bd["non_core"] + bd["resources"])
        bld = int(bd["buildings"])
        upk = int(d["upkeep"][res_key])
        net = int(d["total_inc"][res_key] - d["upkeep"][res_key])
        return cur, inc, bld, upk, net

    rows = []
    for cid in active_countries:
        if cid not in all_econ:
            continue
        row = {"country": cid}
        for prefix, res_key in (("p", "manpower"), ("m", "materials"), ("f", "fuel")):
            cur, inc, bld, upk, net = get_stats(cid, res_key)
            row[f"{prefix}_cur"], row[f"{prefix}_inc"] = cur, inc
            row[f"{prefix}_bld"], row[f"{prefix}_upk"], row[f"{prefix}_net"] = bld, upk, net
        rows.append(row)

    from ui.table_screen import TableColumn
    columns = [TableColumn("country", "Country", 160, align="left")]
    for group, prefix in (("Manpower", "p"), ("Materials", "m"), ("Fuel", "f")):
        for stat, label in (("cur", "Cur"), ("inc", "Inc"), ("bld", "Bld"), ("upk", "Upk"), ("net", "Net")):
            columns.append(TableColumn(f"{prefix}_{stat}", label, 60, group=group))

    _launch_table(map_screen, "Global Economy Overview", columns, rows)

def open_starting_economy_editor(map_screen):
    """Opens a native screen to edit starting resources for countries currently existing on the map."""
    _launch_editor_screen(map_screen, "Starting_Economy_List_Screen", needs_countries=True)
        
def open_spectator_messages(map_screen):
    """Opens a full-screen sortable table of every message sent between active countries."""
    if not _has_active_countries(map_screen):
        return

    from map_logic.diplomacy import diplomacy_messages

    all_msgs = []
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

    for c_name, data in map_screen.nation_data.items():
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
                        "date_sort": sort_val,
                        "sender": sender,
                        "receiver": c_name,
                        # What kind of act it was, not merely that it was
                        # diplomatic -- which is all this column could say
                        # before the action was recorded on the message.
                        "type": diplomacy_messages.message_category(msg),
                        "message": msg.get("content", ""),
                        "parameters": msg.get("parameters"),
                        "llm": bool(msg.get("llm")),
                    })

    all_msgs.sort(key=lambda m: m["date_sort"], reverse=True)

    from ui.table_screen import TableColumn, truncate
    columns = [
        TableColumn("date", "Date", 130, sort_key=lambda r: r["date_sort"]),
        TableColumn("sender", "Sender", 120),
        TableColumn("receiver", "Receiver", 120),
        TableColumn("type", "Type", 100),
        TableColumn("message", "Message", 700, align="left", fmt=lambda v: truncate(v, 90)),
    ]
    hint = "Click a message to read it. Orange = LLM generated."

    # The column has to truncate -- there is no width at which some message
    # does not overflow -- so a row opens the whole thing instead.
    def open_message(row):
        from ui.text_detail_screen import TextDetailScreen
        body = row.get("message", "")

        # The sent copies are dropped above, so the surviving copy is always
        # the recipient's -- the terms read from their side, named rather than
        # called "You", since the reader is neither party.
        terms = diplomacy_messages.describe_trade(row.get("parameters"),
                                                  subject=row.get("receiver", "They"))
        if terms:
            body = f"{body}\n\nTerms:\n" + "\n".join(terms)

        marks = [row.get("date", ""), row.get("type", "")]
        marks.append("written by the model" if row.get("llm") else "standard response")
        _launch(map_screen, TextDetailScreen(
            map_screen,
            f"{row.get('sender', '?')} to {row.get('receiver', '?')}",
            body,
            subtitle="   |   ".join(m for m in marks if m)))

    def tint(row):
        return c.MESSAGE_LLM_ROW_COLOR if row.get("llm") else None

    _launch_table(map_screen, f"Global Messages Overview  ({hint})", columns, all_msgs,
                  empty_message="No messages have been sent yet.",
                  on_row_click=open_message, row_tint=tint)

def open_map_research_editor(map_screen):
    """Opens a native screen to edit research for countries currently existing on the map."""
    _launch_editor_screen(map_screen, "Research_List_Screen", needs_countries=True)

def select_unit_brush(map_screen):
    """Opens a selection window for unit types and sets mode to UNIT."""
    items = ["None", "Convoy", "----------"] + list(queries.get_unit_library().keys())
    _select_brush(map_screen, "UNIT", "brush_unit", items,
                  "Select Unit", "Select Unit to Place:")

def open_convoy_converter(map_screen, province):
    """Opens a native screen to select which units on a tile should be converted to convoys/trucks."""
    units = province.get("units", [])
    if not units:
        map_screen.show_feedback("No units on tile to convert!")
        return

    _launch_editor_screen(map_screen, "Convoy_Converter_Screen", province)

def select_resource_brush(map_screen):
    """Opens a native screen for picking a resource type and amount to paint."""
    _launch_editor_screen(map_screen, "Resource_Brush_Screen")

def open_diplomacy_editor(map_screen):
    """Opens a native screen to edit global relations, factions and puppets."""
    _launch_editor_screen(map_screen, "Diplomacy_Editor_Screen", needs_countries=True)

def open_personality_editor(map_screen):
    """Opens a native screen to set what each AI nation is like."""
    _launch_editor_screen(map_screen, "Personality_List_Screen", needs_countries=True)

def open_politics_editor(map_screen):
    """Opens a native screen to set where each nation starts on the political axis."""
    _launch_editor_screen(map_screen, "Politics_List_Screen", needs_countries=True)

def open_edited_countries(map_screen):
    """Opens a full-screen sortable table of countries with edited properties."""
    from data.io import country_io
    default_data = country_io.load_all_country_data()

    rows = []
    for c_id, current_data in map_screen.nation_data.items():
        if c_id in ["Unclaimed", "Ocean", "Lakes", "The Rot", "Spectator", "GLOBAL_EVENTS", "FACTION_WAR_MAPS"]:
            continue

        def_country = default_data.get(c_id, {})
        changes = {}

        # Tracking what differs from default
        c_name = current_data.get("name", c_id)
        d_name = def_country.get("name", c_id)
        if c_name != d_name: changes["name"] = c_name

        c_leader = current_data.get("leader_name", "")
        d_leader = def_country.get("leader_name", "")
        if c_leader != d_leader: changes["leader_name"] = c_leader

        c_title = current_data.get("leader_title", "")
        d_title = def_country.get("leader_title", "")
        if c_title != d_title: changes["leader_title"] = c_title

        c_flag = current_data.get("flag_data", "DEFAULT")
        if c_flag != "DEFAULT": changes["flag"] = "CUSTOM"

        c_port = current_data.get("portrait_data", "DEFAULT")
        if c_port != "DEFAULT": changes["portrait"] = "CUSTOM"

        if changes:
            rows.append({
                "id": c_id,
                "name": changes.get("name", "-"),
                "leader_name": changes.get("leader_name", "-"),
                "leader_title": changes.get("leader_title", "-"),
                "flag": changes.get("flag", "-"),
                "portrait": changes.get("portrait", "-"),
            })

    from ui.table_screen import TableColumn
    columns = [
        TableColumn("id", "ID", 150, align="left"),
        TableColumn("name", "Name", 150),
        TableColumn("leader_name", "Leader Name", 150),
        TableColumn("leader_title", "Leader Title", 150),
        TableColumn("flag", "Flag", 100),
        TableColumn("portrait", "Portrait", 100),
    ]

    _launch_table(map_screen, "Edited Countries Overview", columns, rows,
                  empty_message="No countries have been edited yet.")


def open_clear_menu(map_screen):
    """Opens a native screen to clear items from the map based on various criteria."""
    _launch_editor_screen(map_screen, "Clear_Map_Screen")