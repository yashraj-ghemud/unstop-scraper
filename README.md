# Unstop Hackathon Alert Agent (Telegram)

Headless automation that checks Unstop for new hackathons and sends Telegram alerts on a schedule via GitHub Actions.

## What it does

- Fetches open hackathons from Unstop (`scraper.py`)
- Stage-1 filtering (fast rules): city/mode/keywords/prize/fee/status (`filter.py`)
- Stage-2 filtering (optional): Groq LLM classification for ambiguous items (`classifier.py`)
- Deduplicates with `seen.json` so you only get new alerts (`state.py`)
- Auto-cleanup: old entries expire after 30 days, max 1000 URLs stored
- Sends one Telegram message per new hackathon + a summary header (`notifier.py`)
- Runs every 6 hours using GitHub Actions and commits `seen.json` back

## Setup

### 1) Create a Telegram bot + get chat id

- Create a bot via BotFather and get `TELEGRAM_BOT_TOKEN`
- Get your `TELEGRAM_CHAT_ID`:
  - Message your bot once in Telegram
  - Run:

    ```bash
    python get_chat_id.py
    ```

  - Find `chat_id=...` in the output

### 2) Optional: Groq LLM (free)

- Create a Groq API key and save it as `GROQ_API_KEY`
- (Optional) Set `GROQ_MODEL` (default: `llama3-70b-8192`)

### 3) Configure preferences

Edit `config.py` or use the `/filter` command in Telegram:

| Field | Default | Description |
|-------|---------|-------------|
| `preferred_mode` | `"both"` | `"online"` / `"offline"` / `"both"` |
| `paid_filter` | `"any"` | `"free"` / `"paid"` / `"any"` |
| `status_filter` | `"any"` | `"live"` / `"expired"` / `"recent"` / `"any"` |
| `domain` | `"Any"` | e.g. `"Engineering"`, `"Management"` |
| `category` | `"Any"` | e.g. `"Software Development"` |
| `city_must_include` | `""` | If set, location must contain this city name |
| `min_prize_inr` | `0` | Minimum prize in INR (0 = no filter) |
| `include_keywords` | *(see code)* | Keywords that must appear |
| `exclude_keywords` | *(see code)* | Keywords that block results |

### 4) GitHub Secrets

In your GitHub repo: Settings > Secrets and variables > Actions > New repository secret

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GROQ_API_KEY` (optional, enables LLM)
- `GROQ_MODEL` (optional)
- `USE_LLM` (optional; set to `0` to disable LLM)

## Run locally (scheduled mode)

```bash
pip install -r requirements.txt
cp env/.env.example env/.env
# fill env/.env with your secrets
python main.py
```

## Interactive bot (on-demand `check` command)

This project also includes a long-polling listener (`bot_check.py`).

> **Note:** `TELEGRAM_CHAT_ID` is **required** for security. The bot will not start without it.

Run locally:

```bash
cp env/.env.example env/.env
# fill env/.env with your secrets
python bot_check.py
```

Then in Telegram, send: `check`

### Bot commands

| Command | Description |
|---------|-------------|
| `/start` | Setup wizard for filters |
| `/filter` | Change filter preferences |
| `check` | Scan Unstop now |
| `seen clear` | Reset seen list (re-notify all) |
| `/help` | Show commands |

## Deploy interactive bot (free, 24/7)

- **Render.com**: Create Web Service, set start command to `python bot_check.py`
- **Koyeb**: Create service with `python bot_check.py` as start command
- **Fly.io**: Use Dockerfile, deploy with `fly deploy`

## GitHub Actions

Workflow file: `.github/workflows/unstop-hackathon-alert.yml`
- Cron: every 6 hours
- Commits `seen.json` back to the repository for dedup persistence

## What changed (v2 fixes)

- **Security**: Bot now requires `TELEGRAM_CHAT_ID` — won't start without it
- **Rate limiting**: 0.5s delay between Telegram messages to avoid API limits
- **seen.json**: All items (including filtered-out) are now marked as seen, preventing re-processing
- **seen.json TTL**: Auto-cleanup after 30 days, max 1000 entries
- **city_must_include**: New filter — only show hackathons in a specific city
- **min_prize_inr**: New filter — minimum prize amount in INR
- **Logging**: Replaced all `print()` with proper `logging` module
- **Playwright pagination**: Fixed overly broad number detection (max 50 pages clamp)
- **Dead code removed**: Unused `_parse_prize_inr`, `if False` no-op
- **Input sanitization**: Category input is now sanitized and truncated
- **Prize info**: Messages now include location and prize in notifications"# unstop-scraper" 
