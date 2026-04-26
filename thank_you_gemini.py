import os
import re

def refactor_constants():
    changed_files = 0
    
    for root, dirs, files in os.walk('.'):
        # Skip hidden folders, pycache, or virtual environments
        if '.git' in root or '__pycache__' in root or 'venv' in root:
            continue
            
        for file in files:
            if not file.endswith('.py'): 
                continue
                
            filepath = os.path.join(root, file)
            
            # Prevent the script from nuking the actual constants file!
            if "constants.py" in filepath:
                continue
                
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # Regex to match single-line and multi-line tuple imports from data.constants
            pattern = r'from\s+data\.constants\s+import\s+\((.*?)\)|from\s+data\.constants\s+import\s+([^\n]+)'
            matches = list(re.finditer(pattern, content, re.DOTALL))
            
            if not matches:
                continue
                
            constants_to_replace = set()
            new_content = content
            
            for match in matches:
                # Group 1 is the multi-line tuple, Group 2 is the single line
                vars_str = match.group(1) if match.group(1) else match.group(2)
                if vars_str:
                    # Strip any inline comments (#) before splitting
                    vars_str = re.sub(r'#.*', '', vars_str)
                    vars_list = [v.strip() for v in vars_str.split(',') if v.strip()]
                    constants_to_replace.update(vars_list)
                
                # Replace the import statement with the aliased import.
                # If there are multiple imports in one file, just delete the duplicates.
                if match == matches[0]:
                    new_content = new_content.replace(match.group(0), 'import data.constants as c')
                else:
                    new_content = new_content.replace(match.group(0), '')
            
            # Use whole-word boundary matching (\b) so we don't accidentally edit unrelated strings
            for const in constants_to_replace:
                new_content = re.sub(rf'\b{const}\b', f'c.{const}', new_content)
                
            if content != new_content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                changed_files += 1
                print(f"Refactored: {filepath}")
                
    print(f"\nDone! Safely refactored {changed_files} files.")

if __name__ == '__main__':
    refactor_constants()