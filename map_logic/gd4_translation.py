"""One-way conversion of standard Greater Diplomacy 4 saves into GD5 saves.

GD4 saves are TurboWarp LZ-String Base64 text (or its decompressed equivalent),
not JSON files.  Keep this module pygame-free: the menu is only a thin file
picker around these functions, and tests can validate a conversion headlessly.
"""

import base64
import copy
import json
import math
import os
import re
import shutil
from datetime import datetime

import data.constants as c
from data import queries
from data.map import history_io
from data.platform import sync_persisted_dir


DIVIDER = "\u239a"
SECTION_COUNT = 65
COUNTRY_COUNT = 458
PROVINCE_COUNT = 564
WORLD_PROVINCE_COUNT = 547
RESOURCE_NAMES = {"Iron", "Coal", "Oil", "Wheat"}


class GD4TranslationError(ValueError):
    """A selected file is not a supported standard GD4 save."""


# The order of Country Code in GD4's shipped TurboWarp project.  Province
# ownership, diplomatic lists, and country records all refer to this table.
GD4_COUNTRY_CODES = (
    "USA,CAN,MEX,CUB,DOM,GUA,HON,NIC,COS,PAN,COL,VEN,UNK,NET,FRA,BRA,URU,ARG,CHI,BOL,PAR,PER,ECU,DEN,IRE,POR,SPA,BEL,GER,NOR,SWE,FIN,EST,LAT,LIT,POL,CZE,AST,SWI,ITA,YUG,ALB,GRE,TUR,BUL,ROM,HUN,SOV,JAP,MAN,MON,KAZ,TMS,UZB,KYR,XIN,TIB,XIB,CCP,CHN,YUN,GNX,AUS,ZEA,THA,BRJ,AFG,IRN,IRQ,SAU,ETH,SAF,RUS,UKR,BLR,PHI,SOK,NOK,MAL,INO,VET,LAO,CAM,MYA,BAN,NEP,IND,PAK,ARM,AZE,GEO,KUW,UAE,OMA,YEM,JOR,CYP,SYR,SOM,ERI,SUD,SSD,EGY,LIB,TUN,ALG,MOR,MAU,MLI,SEN,GUN,IVO,BKF,GHA,NGR,CHA,NRA,CMR,GAB,CON,CAR,DRC,UGD,KEN,TAN,ZAM,ANG,NAM,BOT,ZIM,MOZ,MAD,SOL,FIJ,VNU,PAP,SLO,MOL,CRO,BOS,GUY,SUR,EQG,TUA,JAL,REG,DEL,ISH,HAW,GAL,MER,OMI,KAL,RAH,GOG,LUN,YEK,KZE,BNT,CHO,FUT,TOU,ASA,MEN,DND,SMB,DAH,SKO,BOR,OUA,DAR,BEN,ARA,TED,DAZ,FAN,BAY,MBO,DIN,NUB,AZA,NIL,BUG,NGA,BAB,MOG,CHK,HER,NAA,OFS,ZUL,TRA,KAR,KHO,SAR,KHI,BUK,KOK,VFR,IEA,IEG,RKU,RKM,RKO,RKC,RKN,BUR,REA,RCA,RSA,AYA,KAN,MOS,SIB,KAM,MAG,BYA,YAK,AMU,IRK,WRF,VOR,TOM,MPF,PEC,OMS,SBA,NOV,CRU,AHG,XIK,SRI,SHA,VOL,SVE,ZLA,URA,ORS,TYU,TBO,RGC,ALA,QUE,FLO,CAL,CEA,SPQ,KMU,EUR,STA,SEA,ATK,DES,GIG,PFM,EMU,BRI,NUN,NWT,BRC,ABR,SAS,MNT,ONT,NAL,MAI,NYC,TEN,PEN,OHI,VIR,NJE,YUC,CLI,MIS,LOU,TEX,MSO,IOW,DAK,WIS,ILI,MTA,WAS,MIC,OCC,CAT,BAS,GLI,NEB,KNS,WYO,SCO,WAL,MAS,SAP,ICE,GRN,NCA,KRA,RHI,BAV,SAX,GUJ,TAM,MAH,ZAK,KAS,JAM,KUR,TRS,OKA,AND,VAL,VNI,SIC,NAP,PIE,SRA,COR,CRI,NRE,CAU,HWI,MNG,ATY,AKT,NEV,ORE,UTA,ARI,COO,NME,BAJ,SON,CHU,SHN,HEN,JIA,OAX,TMA,VER,SIN,DUR,MCO,AMA,ROR,AMP,PRA,IFG,MGO,MAR,MRC,PUN,IQU,SCR,FAL,TAS,ANT,RGR,ASQ,QUN,TTE,JAV,SUM,CRE,MAC,HOK,KYU,SHI,SAK,SIL,POM,ASL,IKO,😭😭😭,MRS,WGE,DON,KUB,AKG,ZHI,ZHE,FUJ,GUI,CQG,FEG,KON,HRE,CMP,DRE,SIK,MUG,MCN,LPB,PSA,CIC,IRI,CHE,CRK,CHT,CMC,NAV,APA,CHY,MGU,MAT,BRU,ABO,OJI,SIO,INU,ALE,TLI,CIK,PMO,CHM,YKI,SHO,SAN,MTH,SAV,MAO,CEL,GAU,CTH,PTO,SEL,ATG,ATT,PIA,ILY,THR,SLA,NPW,ALM,TAR,ZAB,PRI,ORK,TAI,TEL,BEG,SAT,WAT,PIL,NQU,WHA,WCC,WWE,WEE,WNE,WSE,WAI,WAM,WAF,UNC,TRO"
).split(",")

# Canonical GD4 province-list index -> current GD5 GD4-map province id.  Zero
# marks the two old GD4 tiles merged out of the GD5 base map.  The last 17 GD4
# records are moon tiles and deliberately have no entry here.
GD4_PROVINCE_TO_GD5 = (
    23,64,102,32,41,3,20,5,85,109,139,226,202,238,206,180,132,119,105,94,136,211,130,188,181,220,274,255,291,315,336,366,369,391,381,428,426,471,443,439,365,318,290,236,300,235,304,245,234,233,276,277,302,407,350,408,341,373,415,448,549,456,460,489,488,523,546,517,553,574,555,544,569,584,596,604,630,649,650,621,668,693,662,638,624,661,646,654,672,675,687,712,729,764,740,748,719,703,685,697,733,711,745,778,786,810,794,818,852,862,851,826,825,864,877,888,908,937,931,897,869,840,808,785,813,767,769,762,732,716,705,0,57,155,172,122,143,160,189,184,343,316,344,374,361,319,325,292,269,249,259,229,212,237,241,203,177,199,230,198,185,178,168,131,97,96,80,74,53,37,28,42,49,71,88,114,124,107,55,38,51,72,75,82,86,116,128,144,156,174,173,162,196,176,193,228,213,242,260,264,281,306,331,354,386,345,270,296,294,327,332,358,378,421,346,309,310,288,253,254,246,243,223,200,205,250,271,285,251,224,218,194,163,169,149,129,108,87,83,68,48,39,43,44,70,103,125,137,170,186,239,286,289,214,182,138,78,58,34,63,90,150,126,123,100,69,14,54,145,171,141,84,15,99,175,127,81,16,77,25,79,40,0,146,165,158,190,204,262,299,357,396,423,438,446,385,328,307,247,227,303,261,179,222,257,195,216,210,164,215,157,209,201,221,275,352,333,287,314,322,340,231,297,412,395,441,393,324,334,298,359,402,372,422,462,427,437,461,514,491,522,570,500,478,533,578,611,648,632,665,694,701,704,741,714,730,736,742,788,798,820,886,905,904,880,876,857,834,822,772,811,842,861,827,797,777,793,836,824,853,848,815,784,746,678,664,566,594,601,543,558,503,537,497,520,509,477,511,557,647,577,540,508,483,452,401,445,473,388,400,494,436,468,434,387,406,414,368,337,349,323,348,339,356,379,367,370,418,451,410,398,399,432,455,482,506,525,539,532,496,463,458,495,548,576,627,626,642,656,605,610,582,547,599,651,641,593,556,521,493,505,472,476,467,457,486,519,501,513,474,475,454,433,397,409,450,499,504,466,453,411,417,431,444,481,510,563,515,535,587,609,622,644,603,625,591,560,542,545,585,619,614,613,640,639,699,686,635,681,708,724,713,737,682,690,683,718,720,759,774,754,750,779,783,804,831,846,859,829,847,821,805,790,795,771,780,930,698,659,598,284,265,830,347,383,939,645
)


def _lz_decompress_from_base64(source):
    """The TurboWarp TheShovel LZ-String ``decompress from Base64`` block."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    lookup = {char: index for index, char in enumerate(alphabet)}
    text = re.sub(r"\s+", "", source)
    if not text or any(char not in lookup and char != "=" for char in text):
        return None

    data = {"value": lookup.get(text[0], 0), "position": 32, "index": 1}

    def read_bits(width):
        value = 0
        power = 1
        maximum = 1 << width
        while power != maximum:
            bit = data["value"] & data["position"]
            data["position"] >>= 1
            if not data["position"]:
                data["position"] = 32
                if data["index"] >= len(text):
                    raise GD4TranslationError("truncated LZ-String data")
                data["value"] = lookup.get(text[data["index"]], 0)
                data["index"] += 1
            if bit:
                value |= power
            power <<= 1
        return value

    dictionary = {0: 0, 1: 1, 2: 2}
    enlarge_in, dict_size, num_bits = 4, 4, 3
    marker = read_bits(2)
    if marker == 0:
        char = chr(read_bits(8))
    elif marker == 1:
        char = chr(read_bits(16))
    elif marker == 2:
        return ""
    else:
        return None
    dictionary[3] = char
    word = char
    result = [char]

    while True:
        if data["index"] > len(text):
            return None
        code = read_bits(num_bits)
        if code == 0:
            dictionary[dict_size] = chr(read_bits(8))
            code = dict_size
            dict_size += 1
            enlarge_in -= 1
        elif code == 1:
            dictionary[dict_size] = chr(read_bits(16))
            code = dict_size
            dict_size += 1
            enlarge_in -= 1
        elif code == 2:
            return "".join(result)

        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1

        if code in dictionary:
            entry = dictionary[code]
        elif code == dict_size:
            entry = word + word[0]
        else:
            return None
        result.append(entry)
        dictionary[dict_size] = word + entry[0]
        dict_size += 1
        enlarge_in -= 1
        word = entry
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1


def decode_save_text(source):
    """Return decompressed GD4 text, accepting both forms produced by GD4."""
    text = source.lstrip("\ufeff").strip()
    if DIVIDER in text:
        return text
    decoded = _lz_decompress_from_base64(text)
    if decoded and DIVIDER in decoded:
        return decoded
    try:
        decoded = base64.b64decode(text, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        decoded = ""
    if DIVIDER in decoded:
        return decoded
    raise GD4TranslationError("not a decompressed or TurboWarp Base64 GD4 save")


def _decode_json_list(section, label, expected_count=None):
    try:
        outer = json.loads(section)
        values = [json.loads(value) for value in outer]
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise GD4TranslationError(f"invalid GD4 {label} data") from error
    if expected_count is not None and len(values) != expected_count:
        raise GD4TranslationError(
            f"GD4 {label} has {len(values)} records; expected {expected_count} for the standard GD4 map")
    return values


def parse_save(source):
    """Parse and validate the supported GD4 save envelope into its useful fields."""
    parts = decode_save_text(source).split(DIVIDER)
    if len(parts) != SECTION_COUNT:
        raise GD4TranslationError(f"GD4 save has {len(parts)} sections; expected {SECTION_COUNT}")
    countries = _decode_json_list(parts[0], "country", COUNTRY_COUNT)
    provinces = _decode_json_list(parts[1], "province", PROVINCE_COUNT)
    friends = _decode_json_list(parts[2], "friendship", COUNTRY_COUNT)
    wars = _decode_json_list(parts[3], "war", COUNTRY_COUNT)
    if len(GD4_COUNTRY_CODES) != COUNTRY_COUNT or len(GD4_PROVINCE_TO_GD5) != WORLD_PROVINCE_COUNT:
        raise RuntimeError("the bundled GD4 mapping constants are incomplete")
    return {"countries": countries, "provinces": provinces, "friends": friends,
            "wars": wars, "time": _number(parts[12], "time"),
            # GD4 writes the country currently controlled by the local player
            # here.  It is a code, unlike the display names in country records.
            "player_code": str(parts[16]).strip()}


def _number(value, label):
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise GD4TranslationError(f"GD4 {label} is not numeric") from error


def _positive_int(value):
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _resource_dict(value):
    if not isinstance(value, str) or value.strip().upper() in {"", "NO"}:
        return {}
    name, separator, amount = value.partition(",")
    name = name.strip()
    if not separator or name not in RESOURCE_NAMES:
        return {}
    try:
        return {name: max(0, int(round(float(amount.strip()) * 50)))}
    except ValueError:
        return {}


def _unique_name(name, nation_data):
    name = str(name).strip()[:c.COUNTRY_NAME_MAX_LENGTH]
    if not name:
        return "Unclaimed"
    if name not in nation_data:
        return name
    return name


def _make_country_names(records, base_nation_data):
    """GD4 country codes point to records; names may have changed in a save."""
    code_to_name = {}
    nation_data = copy.deepcopy(base_nation_data)
    for index, record in enumerate(records):
        if not isinstance(record, list) or len(record) < 26:
            raise GD4TranslationError(f"GD4 country record {index + 1} is incomplete")
        code = GD4_COUNTRY_CODES[index]
        name = _unique_name(record[2], nation_data)
        if name not in nation_data and name != "Unclaimed":
            template = copy.deepcopy(base_nation_data.get("Unclaimed", {}))
            template.update({"name": name, "is_playable": True, "at_war_with": [], "allied_with": []})
            nation_data[name] = template
        code_to_name[code] = name
        if name in nation_data and name not in {"Ocean", "Lakes", "Unclaimed"}:
            nation_data[name]["leader_title"] = str(record[23]).strip()
            nation_data[name]["leader_name"] = str(record[24]).strip()
    return nation_data, code_to_name


def _apply_diplomacy(nation_data, code_to_name, wars):
    for entry in nation_data.values():
        entry["allied_with"] = []
        entry["at_war_with"] = []
        # GD4 has no factions. Clearing all shared-visibility relationships
        # means an imported player sees only their own territory under fog.
        entry["faction"] = ""
        entry["is_faction_leader"] = False
        entry["master"] = ""
        entry["puppets"] = []

    def add_pair(field, first, second):
        if first == second or first not in nation_data or second not in nation_data:
            return
        if first in {"Ocean", "Lakes", "Unclaimed"} or second in {"Ocean", "Lakes", "Unclaimed"}:
            return
        for left, right in ((first, second), (second, first)):
            if right not in nation_data[left][field]:
                nation_data[left][field].append(right)

    for index, code in enumerate(GD4_COUNTRY_CODES):
        country = code_to_name[code]
        for other_code in wars[index]:
            if other_code in code_to_name:
                add_pair("at_war_with", country, code_to_name[other_code])


def _build_units(troops, owner, year, unit_library):
    troops = _positive_int(troops)
    if not troops or owner == "Unclaimed":
        return []
    unit_type = f"Infantry Type {year}"
    if unit_type not in unit_library:
        choices = sorted(name for name in unit_library if name.startswith("Infantry Type "))
        if not choices:
            raise GD4TranslationError("GD5 has no infantry unit type available")
        unit_type = min(choices, key=lambda name: abs(int(name.rsplit(" ", 1)[1]) - year))
    full, remainder = divmod(troops, 100_000)
    units = [queries.create_unit_dict(unit_type, owner, unit_library) for _ in range(full)]
    if remainder:
        wounded = queries.create_unit_dict(unit_type, owner, unit_library)
        wounded["health"] = wounded["max_health"] * (remainder / 100_000)
        units.append(wounded)
    return units


def _industry_buildings(level):
    """Translate GD4's combined industry level into GD5 production buildings."""
    level = min(_positive_int(level), 8)
    if level == 0:
        return []
    if level == 1:
        return ["Basic Factory"]
    if level == 2:
        return ["Basic Factory", "Basic Recruitment Center"]
    if level == 3:
        return ["Basic Factory", "Recruitment Building Lvl 1"]
    return [f"Factory Lvl {level - 3}", f"Recruitment Building Lvl {level - 2}"]


def build_save_payload(parsed, base_map_dir=None):
    """Build a regular GD5 meta payload and report deliberately lossy actions."""
    base_map_dir = base_map_dir or os.path.join(c.BASE_MAPS_DIR, "GD4")
    try:
        with open(os.path.join(base_map_dir, "meta.json"), encoding="utf-8") as handle:
            base_meta = json.load(handle)
        with open(os.path.join(base_map_dir, "map_data.json"), encoding="utf-8") as handle:
            raw_map = json.load(handle)
    except OSError as error:
        raise GD4TranslationError("the bundled GD5 GD4 base map is unavailable") from error

    months = int(math.floor(parsed["time"]))
    if months < 0:
        raise GD4TranslationError("GD4 dates before year 0 are not supported")
    year, month = divmod(months, 12)
    nation_data, code_to_name = _make_country_names(parsed["countries"], base_meta["nation_data"])
    _apply_diplomacy(nation_data, code_to_name, parsed["wars"])
    unit_library = queries.get_unit_library()
    provinces = {}
    by_id = {province["id"]: (key, province) for key, province in raw_map.items()}
    mapped = 0

    for source_index, record in enumerate(parsed["provinces"][:WORLD_PROVINCE_COUNT]):
        if not isinstance(record, list) or len(record) < 19:
            raise GD4TranslationError(f"GD4 province record {source_index + 1} is incomplete")
        target_id = GD4_PROVINCE_TO_GD5[source_index]
        if not target_id or target_id not in by_id:
            continue
        key, target = by_id[target_id]
        owner = code_to_name.get(str(record[2]), "Unclaimed")
        if owner not in nation_data:
            owner = "Unclaimed"
        industry, forts, troops = (_positive_int(record[3]), _positive_int(record[4]), record[5])
        buildings = _industry_buildings(industry)
        if forts:
            buildings.append(f"Fort Lvl {min(forts, 20)}")
        provinces[key] = {
            "owner": owner,
            "cores": [owner] if owner != "Unclaimed" else [],
            "is_coastal": target.get("is_coastal", False),
            "units": _build_units(troops, owner, year, unit_library),
            "building_queue": [], "unit_queue": [], "orders": [],
            "resources": _resource_dict(record[18]), "buildings": buildings,
        }
        mapped += 1

    # The selected policy is GD5's research appropriate to the imported date,
    # applied only after all owners have been resolved.
    date_research = queries.get_time_appropriate_research(year)
    living = {province["owner"] for province in provinces.values() if province["owner"] != "Unclaimed"}
    for name in living:
        nation_data[name]["research"] = date_research.copy()

    player_code = parsed.get("player_code", "")
    if str(player_code).strip().casefold() == "spectator":
        player_country = "Spectator"
    else:
        player_country = code_to_name.get(player_code, "")
    if player_country not in living and player_country != "Spectator":
        # Malformed/old saves can lack GD4's selected-country field. Spectator
        # is safe for GD5's gameplay UI and does not silently assign a country.
        player_country = "Spectator"

    payload = {
        "version": c.GAME_VERSION,
        "generated_at": datetime.now().isoformat(),
        "date": {"day": 15, "month": month, "year": year, "total_turns": 0},
        "loop_map": base_meta.get("loop_map", True), "player_country": player_country,
        "active_players": [] if player_country == "Spectator" else [player_country],
        "current_player_index": 0,
        "scenario_settings": {"fog_of_war": True, "casus_belli_required": True,
                              "days_per_turn": 30, "use_scripted_events": True,
                              "ai_disabled": False},
        "script_variables": [], "default_research": date_research,
        "nation_data": nation_data, "provinces": provinces,
    }
    notes = [f"Mapped {mapped} GD4 world provinces onto the GD5 GD4 map.",
             "GD4 navy, devastation, queues, mail, flags, portraits, and moon provinces were ignored."]
    return payload, notes


def _destination_path(source_path, saves_dir):
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", os.path.splitext(os.path.basename(source_path))[0]).strip()
    stem = stem or "GD4 Import"
    base = os.path.join(saves_dir, f"GD4 - {stem}")
    destination, suffix = base, 2
    while os.path.exists(destination):
        destination = f"{base} ({suffix})"
        suffix += 1
    return destination


def translate_file(source_path, saves_dir=None, base_map_dir=None):
    """Convert ``source_path`` and return ``(destination, notes)``.

    The source is read only.  A new uniquely named GD5 save folder is created.
    """
    try:
        with open(source_path, encoding="utf-8") as handle:
            parsed = parse_save(handle.read())
    except OSError as error:
        raise GD4TranslationError(f"could not read {os.path.basename(source_path)}") from error

    base_map_dir = base_map_dir or os.path.join(c.BASE_MAPS_DIR, "GD4")
    payload, notes = build_save_payload(parsed, base_map_dir)
    saves_dir = saves_dir or c.SAVES_DIR
    os.makedirs(saves_dir, exist_ok=True)
    destination = _destination_path(source_path, saves_dir)
    os.makedirs(destination)
    try:
        with open(os.path.join(destination, "meta.json"), "w", encoding="utf-8") as handle:
            handle.write(history_io.dump_text(payload, indent=c.SAVE_INDENT))
        shutil.copy2(os.path.join(base_map_dir, "map_data.json"), os.path.join(destination, "map_data.json"))
        for asset in ("terrain.png", "id_map.png", "political.png", "cores.png"):
            shutil.copy2(os.path.join(base_map_dir, asset), os.path.join(destination, asset))
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    sync_persisted_dir(saves_dir)
    return destination, notes
