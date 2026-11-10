#!/bin/bash
# This script lives in compilation_scripts/, but dist/ and venv/ are both at
# the project root, so hop up one level from this script's own directory.
cd "$(dirname "$0")/.." || exit 1

./venv/bin/python compilation_scripts/test_web_build.py
web_test_exit=$?

read -rp "Press enter to exit..."
exit "$web_test_exit"
