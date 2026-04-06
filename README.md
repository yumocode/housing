# sf-rent-scraper

Scrapes Craigslist SF rooms/shares for cheap deals, scores them with Claude Haiku, and texts you the good ones via Twilio.

**Pipeline:** RSS feed → keyword filter → Claude Haiku scoring (1–10) → Twilio SMS if score ≥ 7

---

## Quickstart

```bash
git clone <your-repo>
cd sf-rent-scraper
pip install -r requirements.txt
cp .env.example .env
# Fill in your API keys in .env
python main.py
```

---

## Deployment Options

### Option A: DigitalOcean Droplet ($4/mo) — Recommended

Cheapest, most reliable, always-on.

```bash
# 1. Spin up the cheapest droplet (Ubuntu 22.04 LTS, $4/mo)
#    at cloud.digitalocean.com — set a $10/mo spending alert to be safe

# 2. SSH in
ssh root@YOUR_DROPLET_IP

# 3. Install Python & pip
apt update && apt install -y python3 python3-pip git

# 4. Clone and set up
git clone https://github.com/YOUR_USERNAME/sf-rent-scraper.git
cd sf-rent-scraper
pip3 install -r requirements.txt
cp .env.example .env
nano .env  # fill in your keys

# 5. Test run
python3 main.py

# 6. Install cron job (runs every 10 minutes)
bash setup_cron.sh

# 7. Monitor
tail -f sf_rent_scraper.log
```

**Will you get charged if you go over?** DigitalOcean won't surprise-charge you for CPU.
The $4/mo plan includes 500GB bandwidth/month — this script uses maybe 10MB/month.
Set a spending alert in the DO console at Settings → Billing → Alerts to be safe.

### Option B: GitHub Actions (free for public repos)

**Free tier caveat:** Private repos get 2,000 min/month free. Running every 10 min =
~4,320 runs/month minimum → exceeds free tier by ~2,320 min (~$0.50/month extra).
For a **public repo**, it's unlimited/free.

**DB persistence caveat:** GitHub Actions caches expire after ~7 days of inactivity.
If the cache expires, the DB resets and you may get re-notified about old listings.
Good enough for a personal scraper; use the droplet if you want rock-solid deduplication.

**Setup:**
1. Push this repo to GitHub
2. Go to Settings → Secrets and add: `ANTHROPIC_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `MY_PHONE_NUMBER`
3. The workflow at `.github/workflows/scraper.yml` runs automatically every 10 minutes
4. Trigger manually: Actions tab → SF Rent Scraper → Run workflow

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | From console.anthropic.com |
| `TWILIO_ACCOUNT_SID` | Yes | — | From console.twilio.com |
| `TWILIO_AUTH_TOKEN` | Yes | — | From console.twilio.com |
| `TWILIO_FROM_NUMBER` | Yes | — | Your Twilio number |
| `MY_PHONE_NUMBER` | Yes | — | Your personal number |
| `SCORE_THRESHOLD` | No | `7` | Minimum score to text |
| `MAX_PRICE` | No | `1000` | Max rent in RSS filter |
| `MAX_LLM_CALLS_PER_RUN` | No | `10` | Cap Haiku calls per run |
| `DB_PATH` | No | `sf_rent_scraper.db` | SQLite file path |
| `LOG_FILE` | No | `sf_rent_scraper.log` | Log file path |

---

## Cost Estimate

| Service | Cost |
|---|---|
| DigitalOcean droplet | ~$4–6/month |
| Twilio SMS | ~$0.008/text (maybe $1–2/month) |
| Claude Haiku API | ~$0.01–0.05/day ($1–2/month) |
| **Total** | **~$7–10/month** |

---

## Project Structure

```
sf-rent-scraper/
├── main.py          # Orchestration — fetch, filter, score, notify
├── config.py        # Env var loading and validation
├── database.py      # SQLite operations
├── filters.py       # Keyword filter (Stage 1)
├── scorer.py        # Claude Haiku scoring (Stage 2)
├── notifier.py      # Twilio SMS
├── requirements.txt
├── .env.example
├── setup_cron.sh    # Install cron on droplet
└── .github/
    └── workflows/
        └── scraper.yml  # GitHub Actions alternative
```

---

## Monitoring

```bash
# Live log
tail -f sf_rent_scraper.log

# Recent hits (score >= 7)
sqlite3 sf_rent_scraper.db "SELECT title, score, neighborhood, url FROM listings WHERE score >= 7 ORDER BY created_at DESC LIMIT 20;"

# All listings seen today
sqlite3 sf_rent_scraper.db "SELECT title, score, notified FROM listings WHERE date(created_at) = date('now') ORDER BY score DESC;"
```
