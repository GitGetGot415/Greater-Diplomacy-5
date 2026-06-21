import glob
import os
import sys

# Add the parent directory (project root) to the Python path so it can find the 'data' module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import data.constants as c

def combine_files(output_filename="context/combined_scripts.txt", search_directory=".", json_files_to_include=None, acknowledge_patterns=None, silent_ignore_patterns=None):
    """
    Finds all .py files and specific JSON files, writing their content to one text file.
    Acknowledges certain files without writing contents, and completely ignores others.
    Filters out directory paths so only files are processed or listed.
    """
    if json_files_to_include is None: json_files_to_include = []
    if acknowledge_patterns is None: acknowledge_patterns = []
    if silent_ignore_patterns is None: silent_ignore_patterns = []

    # 1. Get all .py files recursively (and ensure they are files, not dirs named .py)
    files_to_process = [
        f for f in glob.glob(os.path.join(search_directory, "**", "*.py"), recursive=True) 
        if os.path.isfile(f)
    ]

    # 2. Add the specific JSON files if they exist
    for json_file in json_files_to_include:
        json_path = os.path.join(search_directory, json_file)
        if os.path.exists(json_path) and os.path.isfile(json_path):
            files_to_process.append(json_path)
        elif not os.path.exists(json_path):
            print(f"Warning: Specified JSON file not found: {json_path}")

    # 3. Get files to acknowledge (content omitted)
    files_to_acknowledge = []
    for pattern in acknowledge_patterns:
        matches = glob.glob(os.path.join(search_directory, pattern), recursive=True)
        # --- NEW: Filter out directories ---
        valid_files = [f for f in matches if os.path.isfile(f)]
        files_to_acknowledge.extend(valid_files)
    
    files_to_acknowledge = list(set(files_to_acknowledge))

    # 4. Get files to completely ignore
    files_to_silently_ignore = []
    for pattern in silent_ignore_patterns:
        matches = glob.glob(os.path.join(search_directory, pattern), recursive=True)
        # --- NEW: Filter out directories here too ---
        valid_files = [f for f in matches if os.path.isfile(f)]
        files_to_silently_ignore.extend(valid_files)

    # 5. Apply all filters
    abs_acknowledged = {os.path.abspath(f) for f in files_to_acknowledge}
    abs_silent = {os.path.abspath(f) for f in files_to_silently_ignore}
    
    # Remove silently ignored files from the acknowledge list
    files_to_acknowledge = [
        filepath for filepath in files_to_acknowledge 
        if os.path.abspath(filepath) not in abs_silent
    ]

    # Remove acknowledged AND silently ignored files from the process list
    files_to_process = [
        filepath for filepath in files_to_process 
        if os.path.abspath(filepath) not in abs_acknowledged 
        and os.path.abspath(filepath) not in abs_silent
    ]

    if not files_to_process and not files_to_acknowledge:
        print(f"No files found to process or acknowledge in '{search_directory}'")
        return

    # Open the output file in write mode
    with open(output_filename, "w", encoding="utf-8") as outfile:
        
        # Write the acknowledged files block first
        if files_to_acknowledge:
            outfile.write("--- Acknowledged Files (Contents Omitted) ---\n")
            outfile.write("The following files exist in the project directory but their contents have been omitted for brevity:\n")
            for filepath in sorted(files_to_acknowledge):
                outfile.write(f"> {filepath}\n")
            outfile.write("-" * 45 + "\n\n")

        # Write the contents of the remaining files to process
        for filepath in files_to_process:
            if os.path.abspath(filepath) == os.path.abspath(output_filename):
                continue
            
            try:
                with open(filepath, "r", encoding="utf-8") as infile:
                    content = infile.read()
                    outfile.write(f"--- Start of file: {filepath} ---\n")
                    outfile.write(content)
                    outfile.write(f"\n--- End of file: {filepath} ---\n\n")
            except Exception as e:
                print(f"Error reading file {filepath}: {e}")

    print(f"Successfully wrote {len(files_to_process)} files and acknowledged {len(files_to_acknowledge)} files to '{output_filename}'")

# Example usage:
# List the exact JSON files you want to include here
specific_jsons = [
    c.UNIT_DATA_PATH,
    c.COUNTRIES_DATA_PATH,
    c.RESEARCH_TEMPLATE_PATH,
    c.BUILDING_DATA_PATH,
    c.SETTINGS_CONFIG_PATH
]

# Skip these files
files_to_skip_but_list = [
    "**/*.dll",
    "**/*.dylib",
    "**/*.so",
    "data/**/*.json",
    "data\editors/**/*.py",
    "soloud.py",
    "setup.py",
    "gameState.py",
    "main.py",
    "ui_elements.py",
    "data\constants.py",
    #"data\queries.py",
    "context\context_generator.py",
    "map_tools\**",
    #"data\**",

    #"ui\**",
    "screens\**",

    #"map_logic/ai\**",
    "map_logic/camera\**",
    #"map_logic/diplomacy\**",
    "map_logic/random_map\**",
    #"map_logic/rendering\**",
    "map_logic/setup\**",
    #"map_logic/system32\**",
]

# FULL:
# constants.py
# queries.py
# ui\**
# screens\**
# ai
# camera
# diplomacy
# random_map
# rendering
# system32

# Files you want totally wiped from existence in the final .txt
files_to_silently_ignore = [
    "**/__pycache__/*",   # Drops everything inside any __pycache__ folder
    "**/*.pyc",           # Catches any compiled python files anywhere
    "**/.git/*",          # Hides git background files if you run this in a repo
    "**/.env",            # Prevents accidentally leaking your environment variables!
    "dist/**",
    "build/**",
    "**/__init__.py"
]

combine_files(
    json_files_to_include=specific_jsons, 
    acknowledge_patterns=files_to_skip_but_list,
    silent_ignore_patterns=files_to_silently_ignore
)