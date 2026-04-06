#!/bin/bash
# Install cron job to run sf-rent-scraper every 10 minutes.
# Run this once on your DigitalOcean droplet after setup.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON=$(which python3)
CRON_CMD="*/10 * * * * cd $SCRIPT_DIR && $PYTHON main.py >> $SCRIPT_DIR/cron.log 2>&1"

# Check if cron job already installed
if crontab -l 2>/dev/null | grep -q "sf-rent-scraper\|main.py"; then
    echo "Cron job already installed. Current crontab:"
    crontab -l
    exit 0
fi

(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
echo "Cron job installed:"
echo "  $CRON_CMD"
echo ""
echo "Monitor with: tail -f $SCRIPT_DIR/sf_rent_scraper.log"
echo "Remove with:  crontab -e  (then delete the line)"
