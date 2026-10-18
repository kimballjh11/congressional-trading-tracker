#!/usr/bin/env bash
# Non-interactive setup for when .env is already configured.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

PYTHON="${PYTHON:-python3}"
VENV_DIR="$PROJECT_DIR/venv"
DATA_DIR="$PROJECT_DIR/data"

echo "==> Congressional Trading Tracker — finish setup"

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  echo "ERROR: .env not found in $PROJECT_DIR"
  echo "Create it from .env.example with your Gmail credentials first."
  exit 1
fi

PIP="$VENV_DIR/bin/pip"
PY="$VENV_DIR/bin/python"

if [[ -d "$VENV_DIR" ]] && { [[ ! -x "$PY" ]] || [[ ! -x "$PIP" ]]; }; then
  echo "==> Found an incomplete virtual environment at $VENV_DIR — removing it"
  rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "==> Creating virtual environment"
  if ! "$PYTHON" -m venv "$VENV_DIR"; then
    echo "ERROR: failed to create the virtual environment at $VENV_DIR (see the error above)."
    echo "On Debian/Ubuntu, this is usually fixed by: sudo apt install python3-venv"
    echo "Then re-run this script."
    exit 1
  fi
fi

echo "==> Installing dependencies"
"$PIP" install -r requirements.txt

echo "==> Creating data directory"
mkdir -p "$DATA_DIR"

OS="$(uname -s)"
if [[ "$OS" == "Linux" ]]; then
  CRON_LINE="0 8 * * * cd $PROJECT_DIR && $PY $PROJECT_DIR/run_on_wake.py >> $DATA_DIR/cron.log 2>&1"
  EXISTING="$(crontab -l 2>/dev/null || true)"
  if echo "$EXISTING" | grep -q "run_on_wake.py"; then
    echo "==> Cron job already installed"
  else
    printf '%s\n%s\n' "$EXISTING" "$CRON_LINE" | crontab -
    echo "==> Cron job installed (daily at 8:00 AM)"
  fi
elif [[ "$OS" == "Darwin" ]]; then
  echo "==> macOS detected — run 'python3 setup.py' to install the LaunchAgent"
else
  echo "==> Skipping scheduler setup on $OS"
fi

echo "==> Running test pipeline"
"$PY" "$PROJECT_DIR/run_on_wake.py" --test

echo "==> Setup complete"
