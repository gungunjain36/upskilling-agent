# UpskillBot

A personal upskilling coach on Telegram. Powered by Claude Code CLI — zero per-token AI cost.

## What it does

- **Onboards you** — asks about your situation, assesses your level in each domain, builds a personalized roadmap
- **Sends concepts** — delivers explanations on a schedule you configure (every 2h, 3h, etc.)
- **Gives challenges** — practice problems calibrated to your current level
- **Tracks progress** — Excel spreadsheet with your roadmap, sessions, challenges, and growth
- **Adapts** — updates your level as you demonstrate mastery

**Supported domains:** DSA, Machine Learning, System Design, AI Engineering

## Tech stack

- **FastAPI** — application server
- **python-telegram-bot** — Telegram integration
- **APScheduler** — cron-based concept delivery
- **Claude Code CLI** — AI brain (flat subscription, no per-token cost)
- **openpyxl** — Excel progress tracker
- **Markdown files** — lightweight memory/config storage

## Setup

### 1. Prerequisites

- Python 3.11+
- Claude Code installed and authenticated (`claude --version` should work)
- A Telegram bot token (create via [@BotFather](https://t.me/BotFather))
- Your Telegram chat ID (send a message to your bot, then check `https://api.telegram.org/bot<TOKEN>/getUpdates`)

### 2. Install

```bash
git clone <repo>
cd upskilling_agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your Telegram token and chat ID
```

### 4. Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 5. On your VPS (production)

```bash
# Pull the repo
git pull origin main

# Install deps
pip install -r requirements.txt

# Run with nohup or systemd
nohup uvicorn main:app --host 0.0.0.0 --port 8000 &
```

## Commands (in Telegram)

| Command | Description |
|---------|-------------|
| `/start` | Begin onboarding or restart |
| `/challenge` | Get a practice challenge |
| `/challenge dsa` | Challenge for a specific domain |
| `/concept` | Get a concept explanation |
| `/concept ml` | Concept for a specific domain |
| `/progress` | Full roadmap progress |
| `/status` | Quick level overview |
| `/topic` | See what's next on your roadmap |
| `/reschedule 2` | Change concept delivery to every 2 hours |

## Project structure

```
upskilling_agent/
├── main.py                  # FastAPI entry point
├── config/settings.py       # Environment config
├── agents/
│   ├── orchestrator.py      # Routes messages, handles commands
│   ├── onboarding.py        # Multi-step onboarding flow
│   └── personas.py          # System prompts for each domain agent
├── core/
│   ├── claude_runner.py     # Claude Code CLI subprocess wrapper
│   ├── memory.py            # Markdown/JSON file-based memory
│   ├── tracker.py           # Excel progress tracker
│   └── scheduler.py        # APScheduler cron jobs
├── bot/telegram_bot.py      # Telegram bot setup + routing
└── data/                   # Runtime data (gitignored)
    ├── memory/              # User profile, roadmap, history (JSON)
    └── tracker/             # progress.xlsx
```

## Cost

- **AI:** Claude Code subscription (~$20/month flat, no per-token charges)
- **Server:** Any VPS (even $5/month DigitalOcean works)
- **Telegram:** Free

Total: ~$25/month for unlimited usage.
