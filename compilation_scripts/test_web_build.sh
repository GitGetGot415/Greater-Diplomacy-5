#!/bin/bash
# This script lives in compilation_scripts/, but web_stage/ and venv/ are both at
# the project root, so hop up one level from this script's own directory.
cd "$(dirname "$0")/.." || exit 1

if [ ! -f "web_stage/build/web/index.html" ]; then
    echo "============================================================"
    echo "No web build found yet. Run html_compilation.py first:"
    echo "    venv/bin/python compilation_scripts/html_compilation.py"
    echo "============================================================"
    read -rp "Press enter to exit..."
    exit 1
fi

# Kill any server already bound to port 8000 from a previous run of this
# script -- two pygbag servers racing for the same port is what causes the
# browser to hang forever on "Loading... please wait" (requests get split
# unpredictably between the two processes).
lsof -ti tcp:8000 | xargs kill -9 2>/dev/null

echo "Starting local web server for the browser build..."
echo "Press Ctrl+C to stop the server."
echo

# Open the browser once the server below (which blocks this window until
# closed) is actually serving index.html, not just once its port is open --
# pygbag re-packs the whole app and re-fetches its JS/WASM runtime from its
# CDN on every launch, and accepts TCP connections before that finishes, so a
# fixed sleep (or a plain port check) can load the browser against a
# half-started server that then needs a manual refresh to work. Requiring two
# consecutive 200s guards against catching it mid-transition.
(
    ok=0
    while [ "$ok" -lt 2 ]; do
        code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null)
        if [ "$code" = "200" ]; then
            ok=$((ok + 1))
        else
            ok=0
        fi
        sleep 0.5
    done
    open http://localhost:8000/
) &

# --template must match html_compilation.py's build, or this regenerates index.html
# from pygbag's stock template and undoes the aspect-ratio fix in web_index.tmpl.
./venv/bin/python -m pygbag --app_name "Greater Diplomacy 5" --disable-sound-format-error --ume_block 0 --template compilation_scripts/web_index.tmpl web_stage

read -rp "Press enter to exit..."
