# Congressional Trading Tracker

Automated pipeline that monitors U.S. congressional stock trades from official financial disclosure filings, scores them for suspicious activity, and emails you a daily report.

Members of Congress are required to disclose stock trades within 45 days. This tool scrapes those filings from the House Clerk and Senate EFDS, enriches them with committee assignments and market data, scores each trade on 7 suspicion signals, and sends you an email with the flagged ones.

## What It Does

1. **Scrapes** new Periodic Transaction Reports (PTRs) from the House and Senate disclosure sites
2. **Parses** trade details from PDFs (House) and HTML reports (Senate)
3. **Enriches** each trade with the member's committee assignments and stock data (sector, price)
4. **Scores** each trade 0–100 on multiple suspicion signals
5. **Emails** you a formatted report of flagged trades, grouped by severity

No API keys needed — all data comes from public government sources.

## Quick Start

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/congressional-trading-tracker.git
cd congressional-trading-tracker

# Run the interactive setup
python3 setup.py
```

The setup script will:
- Check your Python version (3.8+ required)
- Create a virtual environment and install dependencies
- Walk you through Gmail credentials for email reports
- Set up daily automation for your OS
- Offer a test run

## Requirements

- Python 3.8+
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) (requires 2-Step Verification)
- Internet connection (for scraping and stock data)

### Dependencies

Installed automatically by `setup.py`:

| Package | Purpose |
|---------|---------|
| `requests` | HTTP requests for scraping |
| `beautifulsoup4` | HTML parsing (Senate filings) |
| `pdfplumber` | PDF text extraction (House filings) |
| `yfinance` | Stock price, sector, and industry data |
| `python-dotenv` | Load Gmail credentials from `.env` |

## How the Pipeline Works

```
House Clerk ──┐
              ├── Parse trades ── Enrich ── Score ── Email report
Senate EFDS ──┘
```

### Pipeline Steps

| Step | File | What it does |
|------|------|-------------|
| 1a | `scraper.py` | Scrapes House PTR filings from disclosures-clerk.house.gov |
| 1b | `senate_scraper.py` | Scrapes Senate PTR filings from efdsearch.senate.gov |
| 2 | `parser.py` | Downloads and parses trade details from PDFs/HTML |
| 3 | `enricher.py` | Adds committee assignments and stock data (via yfinance) |
| 4 | `scorer.py` | Scores each trade 0–100 on 7 suspicion signals |
| 5 | `emailer.py` | Sends an HTML email report grouped by severity tier |

`main.py` orchestrates all steps. `run_on_wake.py` wraps it with once-per-day logic.

## Scoring System

Each trade is scored 0–100 based on 7 independent signals. Scores are capped at 100.

| Signal | Points | Trigger |
|--------|--------|---------|
| **Committee/Sector Match** | +25 | Member sits on a committee that oversees the stock's sector |
| **Ways & Means** | +10 | Ways & Means committee (affects all sectors via tax policy) |
| **Large Trade** | +10/+15 | Trade amount >$50K (+10) or >$100K (+15) |
| **Disclosure Delay** | +8/+15 | Filed 30–37 days late (+8) or 38–45 days, near the legal limit (+15) |
| **Cluster Trading** | +15/+20 | 2 members traded the same stock (+15) or 3+ members (+20) |
| **Spouse/Dependent** | +10 | Trade made through spouse, dependent, or joint account |
| **Legislation Timing** | +20 | Trade near a relevant committee hearing (placeholder — not yet implemented) |
| **Contrarian Buy** | +10 | Stock dropped >10% in 30 days before a purchase |

### Score Tags

| Score | Tag | Email Treatment |
|-------|-----|----------------|
| 76–100 | High Alert | Red section, shown first |
| 51–75 | Suspicious | Orange section |
| 26–50 | Noteworthy | Blue section |
| 0–25 | Routine | Not shown in email |

All thresholds and point values are configurable in `config.py`.

## Configuration

Edit `config.py` to customize:

- **Score thresholds** — adjust when trades get tagged as suspicious
- **Point values** — tune how many points each signal contributes
- **Committee/sector mappings** — add or modify which committees map to which stock sectors
- **Email tiers** — change colors, labels, or add new tiers
- **SMTP settings** — use a different email provider
- **File paths** — change where data files are stored

## Project Structure

```
congressional-trading-tracker/
├── setup.py              # Interactive first-time setup
├── config.py             # All configurable settings
├── main.py               # Pipeline orchestrator
├── run_on_wake.py        # Daily run wrapper (skip if already ran today)
├── check_status.py       # Pipeline health check
├── scraper.py            # House disclosure scraper
├── senate_scraper.py     # Senate disclosure scraper
├── parser.py             # PDF/HTML trade parser
├── enricher.py           # Committee + stock data enrichment
├── scorer.py             # 7-signal suspicion scoring
├── emailer.py            # HTML email report sender
├── requirements.txt      # Python dependencies
├── .env.example          # Template for Gmail credentials
├── .gitignore            # Keeps secrets and data out of git
└── README.md             # This file
```

## Manual Usage

If you prefer to run things manually instead of using automation:

```bash
# Activate the virtual environment
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows

# Run the full pipeline
python main.py

# Run with once-per-day logic
python run_on_wake.py

# Force a run (even if already ran today)
python run_on_wake.py --test

# Check pipeline health
python check_status.py

# Run individual steps
python scraper.py               # Just scrape House filings
python senate_scraper.py        # Just scrape Senate filings
python parser.py                # Just parse filings
python enricher.py              # Just enrich trades
python scorer.py                # Just score trades
python emailer.py               # Just send the email report
```

## Troubleshooting

### "No new filings found"
This is normal if the pipeline already ran today. The scraper tracks which filings it has seen in `data/seen_trades.json`. To re-process everything, delete that file:
```bash
rm data/seen_trades.json
```

### Gmail authentication failed
- Make sure you're using an **App Password**, not your regular Gmail password
- App Passwords require **2-Step Verification** to be enabled
- Generate one at: https://myaccount.google.com/apppasswords
- Check your `.env` file has the correct values

### Senate scraper returns 503
The Senate EFDS site (`efdsearch.senate.gov`) is occasionally under maintenance. The pipeline handles this gracefully — it logs the issue and continues with House filings only. Senate scraping will resume automatically when the site comes back.

### "externally-managed-environment" error
This happens on newer macOS/Linux systems that prevent global pip installs. The setup script avoids this by using a virtual environment. If you see this error, make sure you ran `setup.py` (which creates a venv) rather than installing packages globally.

### Pipeline ran but no email
- Check `data/run_log.txt` for error messages
- Run `python check_status.py` to see the last run result
- Make sure your `.env` credentials are correct
- Try `python emailer.py` directly to isolate email issues

### LaunchAgent not running (macOS)
```bash
# Check if it's loaded
launchctl list | grep trading

# View logs
cat data/launchagent_stdout.log
cat data/launchagent_stderr.log

# Reload
launchctl unload ~/Library/LaunchAgents/com.congressional.tradingtracker.plist
launchctl load ~/Library/LaunchAgents/com.congressional.tradingtracker.plist
```

## Data Sources

| Source | URL | Data |
|--------|-----|------|
| House Clerk | disclosures-clerk.house.gov | PTR filings (PDF) |
| Senate EFDS | efdsearch.senate.gov | PTR filings (HTML) |
| House Clerk XML | clerk.house.gov | Committee assignments |
| Senate.gov | senate.gov | Committee assignments |
| Yahoo Finance | via `yfinance` | Stock price, sector, industry |

All sources are public government data or free financial APIs. No API keys required.

## License

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
