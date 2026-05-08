import glob
import os
import sys

# Add the parent directory (project root) to the Python path so it can find the 'data' module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import data.constants as c

def combine_files(output_filename="context/combined_scripts.txt", search_directory=".", json_files_to_include=None, acknowledge_patterns=None):
    """
    Finds all .py files and specific JSON files, writing their content to one text file.
    Also acknowledges the existence of specific files without writing their contents.
    """
    if json_files_to_include is None:
        json_files_to_include = []
    if acknowledge_patterns is None:
        acknowledge_patterns = []

    # 1. Get all .py files recursively
    files_to_process = glob.glob(os.path.join(search_directory, "**", "*.py"), recursive=True)

    # 2. Add the specific JSON files if they exist
    for json_file in json_files_to_include:
        # Construct the path (assumes they are in the search_directory or relative to it)
        json_path = os.path.join(search_directory, json_file)
        if os.path.exists(json_path):
            files_to_process.append(json_path)
        else:
            print(f"Warning: Specified JSON file not found: {json_path}")

    # 3. Get files to acknowledge (content omitted)
    files_to_acknowledge = []
    for pattern in acknowledge_patterns:
        matches = glob.glob(os.path.join(search_directory, pattern), recursive=True)
        files_to_acknowledge.extend(matches)
    
    files_to_acknowledge = list(set(files_to_acknowledge))

    # --- NEW: Step 4. Filter out acknowledged files from files_to_process ---
    # We use absolute paths to compare them safely, in case of relative path mismatches
    abs_acknowledged = {os.path.abspath(f) for f in files_to_acknowledge}
    
    files_to_process = [
        filepath for filepath in files_to_process 
        if os.path.abspath(filepath) not in abs_acknowledged
    ]
    # -------------------------------------------------------------------------

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
                outfile.write(f"- {filepath}\n")
            outfile.write("-" * 45 + "\n\n")

        # Write the contents of the remaining files to process
        for filepath in files_to_process:
            # Skip the output file itself
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
    "data/**/*.json",
    "soloud.py",
]

combine_files(
    json_files_to_include=specific_jsons, 
    acknowledge_patterns=files_to_skip_but_list
)