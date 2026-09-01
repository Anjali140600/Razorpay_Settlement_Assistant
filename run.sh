#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
python data/synthetic/generator.py
echo "Starting Streamlit on http://localhost:8501"
exec streamlit run apps/streamlit_app.py --server.port=8501
