#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
if [ ! -x "venv/bin/python" ]; then
    echo "Project Python not found. Run compilation_scripts/run.sh once first."
    read -r -p "Press enter to exit..."
    exit 1
fi
./venv/bin/python compilation_scripts/android_compilation.py "$@"
android_build_exit=$?
read -r -p "Press enter to exit..."
exit "$android_build_exit"
