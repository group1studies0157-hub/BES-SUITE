#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Bridge Engineering Suite — Linux / macOS Setup & Launch
# ─────────────────────────────────────────────────────────────

echo ""
echo " Bridge Engineering Suite v2.0"
echo " ================================"
echo ""

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo " ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi

# Create venv if needed
if [ ! -d "venv" ]; then
    echo " Creating virtual environment..."
    python3 -m venv venv
fi

# Activate
source venv/bin/activate

# Install deps
echo " Installing dependencies..."
pip install -r requirements.txt --quiet

# Optional: set API key for dimension extraction
# export ANTHROPIC_API_KEY="your_key_here"

echo ""
echo " Launching Bridge Engineering Suite..."
echo ""
python main.py
