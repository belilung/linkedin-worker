#!/usr/bin/env bash
# LinkedIn Worker — one-command setup for macOS and Linux
set -e

echo "=== LinkedIn Worker Setup ==="
echo ""

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Install Python 3.11+ first:"
    echo "  macOS:  brew install python@3.11"
    echo "  Ubuntu: sudo apt install python3.11 python3.11-venv"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "ERROR: Python 3.11+ required, found $PY_VERSION"
    exit 1
fi
echo "[OK] Python $PY_VERSION"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "[..] Creating virtual environment..."
    python3 -m venv venv
    echo "[OK] Virtual environment created"
else
    echo "[OK] Virtual environment already exists"
fi

# Activate venv
source venv/bin/activate

# Install package
echo "[..] Installing linkedin-worker and dependencies..."
pip install -e . --quiet
echo "[OK] Package installed"

# Install Playwright browser
echo "[..] Installing Chromium browser (this may take a minute)..."
playwright install chromium
echo "[OK] Chromium installed"

# Linux: install system dependencies for Playwright
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "[..] Installing system dependencies for Playwright (requires sudo)..."
    playwright install-deps chromium
    echo "[OK] System dependencies installed"
fi

# Create .env if not exists
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "[!!] Created .env file. Edit it with your Anthropic API key:"
    echo "     nano .env"
    echo "     Get your key at: https://console.anthropic.com/settings/keys"
else
    echo "[OK] .env already exists"
fi

# Create config.yaml if not exists
if [ ! -f "config.yaml" ]; then
    cp config.example.yaml config.yaml
    echo "[!!] Created config.yaml from example. Edit it with your campaign settings:"
    echo "     nano config.yaml"
else
    echo "[OK] config.yaml already exists"
fi

# Create data directories
mkdir -p data/cookies data/screenshots

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env         — add your ANTHROPIC_API_KEY"
echo "  2. Edit config.yaml  — set up your campaign (search_url, context, voice)"
echo "  3. Activate venv:    source venv/bin/activate"
echo "  4. Login:            linkedin-worker login"
echo "  5. Test:             linkedin-worker connect --dry-run --no-headless"
echo "  6. Run:              linkedin-worker connect"
echo ""
