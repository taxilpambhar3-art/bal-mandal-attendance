#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment with Python 3.9..."
    /usr/bin/python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

echo "Starting Bal Mandal Attendance Server on http://127.0.0.1:8000 ..."
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
