#!/usr/bin/env bash
# One-time setup for the SANParks Otter Trail availability tracker
set -e

echo "==> Installing Python dependencies …"
pip install -r requirements.txt

echo "==> Installing Playwright Chromium browser …"
playwright install chromium
playwright install-deps chromium

echo "==> Copying .env template (edit this before running) …"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "     Created .env – open it and fill in your notification settings."
else
    echo "     .env already exists – skipping."
fi

echo ""
echo "Done! Next steps:"
echo "  1. Edit .env with your email / Telegram credentials"
echo "  2. Run once manually:  python checker.py"
echo "  3. Add to cron for automatic checks (every 10 minutes):"
echo "       crontab -e"
echo "       */10 * * * * cd $(pwd) && python checker.py >> checker.log 2>&1"
