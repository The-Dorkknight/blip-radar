#!/bin/sh
# Blip — double-click launcher (macOS; first run: right-click > Open, it is unsigned).
# Starts the radar simulator and opens the phone UI in your browser. No hardware needed.
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then PY=python3; else
  echo "Python 3 is not installed. Install it from https://www.python.org/downloads/macos/"; echo "Press Enter to close."; read -r _; exit 1; fi
echo "Blip flasher + simulator — if the browser does not appear, open the address printed below."
"$PY" tools/sim_radar.py "$@" || { echo "Simulator stopped with an error. Press Enter to close."; read -r _; }
