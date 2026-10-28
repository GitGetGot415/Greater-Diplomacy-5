"""Launch scripts/dependencies/fetch_dragoman_wasm.py from the previous command path."""

from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    runpy.run_path(str(ROOT / "scripts/dependencies/fetch_dragoman_wasm.py"), run_name="__main__")
