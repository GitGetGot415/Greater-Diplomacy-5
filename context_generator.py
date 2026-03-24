import glob
import os

def combine_files(output_filename="combined_scripts.txt", search_directory=".", json_files_to_include=None):
    """
    Finds all .py files and specific JSON files, writing their content to one text file.
    """
    if json_files_to_include is None:
        json_files_to_include = []

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

    if not files_to_process:
        print(f"No files found to process in '{search_directory}'")
        return

    # Open the output file in write mode
    with open(output_filename, "w", encoding="utf-8") as outfile:
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

    print(f"Successfully wrote {len(files_to_process)} files to '{output_filename}'")

# Example usage:
# List the exact JSON files you want to include here
specific_jsons = ["map_functions/data/unit_data.json", "map_functions/data/countries_data.json"]

combine_files(json_files_to_include=specific_jsons)