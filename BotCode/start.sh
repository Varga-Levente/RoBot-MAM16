#!/bin/bash
# RoBot BotCode — éles indítószkript (Jetson Nano)
# Automatikus indításhoz: sudo systemctl enable botcode

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"
LOG_DIR="$SCRIPT_DIR/logs"

mkdir -p "$LOG_DIR"

if [ ! -f "$VENV/bin/python" ]; then
    echo "HIBA: venv nem található: $VENV"
    echo "Futtasd: python3.8 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') BotCode indítás..."
cd "$SCRIPT_DIR"
exec "$VENV/bin/python" main.py "$@"
