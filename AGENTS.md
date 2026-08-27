# AGENTS.md

Directories in this repo that are generated/output and can usually be ignored when exploring or searching the codebase:

- `web_stage/` — staged copy of the source used for HTML/web compilation output, not hand-written code
- `dist/` — packaged build output (e.g. the macOS `.app` bundle)
- `build/` — intermediate build artifacts from packaging (py2app, etc.)
- `.eggs/` — py2app egg cache
- `__pycache__/` — compiled Python bytecode cache
- `venv/` — local Python virtual environment

also, if you edit anything, don't forget to also update relevant information

for example, if you edit how damage works (maybe make units deal less damage in certain situations), make sure the ui also accounts for this, so you don't have a situation where it says a unit deals some value of damage but in actuality it deals something else entirely

and don't forget to also update the compilation scripts (windows_compilation.py, macos_compilation.py, html_compilation.py) if you added a new python file or something

IMPORTANT: NEVER COMMIT ANYTHING TO MAIN WITHOUT EXPLICITLY ASKING THE USER BEFOREHAND