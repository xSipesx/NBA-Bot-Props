# 🏀 NBA Player Points Prop Agent

A fully automated pipeline that predicts individual NBA player scoring totals, compares them against sportsbook prop lines, and identifies +EV betting opportunities daily.

## Architecture

```
Python (data + math)  →  Claude AI (reasoning + narrative)  →  You (decision)
```

**Hybrid approach:** Python handles deterministic data ingestion, statistical modeling, and distribution fitting. Claude API handles matchup reasoning, narrative analysis, and report generation.

## Quick Start

### 1. Clone & Install

```bash
git clone <your-repo-url>
cd nba-props-agent
pip install -r requirements.txt
```

### 2. Configure API Keys

```bash
cp .env.example .env
# Edit .env with your API keys
```

**Required:** [The Odds API](https://the-odds-api.com) — Free tier (500 req/month)
**Recommended:** [Anthropic API](https://console.anthropic.com) — For Claude analysis (~$1/day)
**Optional:** Discord webhook, SendGrid email

### 3. Initialize Database

```bash
python main.py --init-db
```

### 4. Run Today's Slate

```bash
python main.py
```

### 5. Grade Yesterday's Bets

```bash
python main.py --grade
```

### 6. View Performance

```bash
python main.py --performance
```

### 7. Launch Dashboard

```bash
streamlit run dashboard.py
```

## Project Structure

```
nba-props-agent/
├── main.py                  # 🎯 Pipeline orchestrator
├── config.py                # ⚙️  All settings and model parameters
├── database.py              # 💾 SQLite schema and CRUD operations
├── dashboard.py             # 📊 Streamlit web dashboard
├── requirements.txt         # 📦 Python dependencies
├── .env.example             # 🔑 API key template
│
├── ingest/                  # 📥 Data ingestion layer
│   ├── schedule.py          #    NBA game schedule (nba_api)
│   ├── player_stats.py      #    Player stats + game logs (nba_api)
│   ├── odds.py              #    Prop lines (The Odds API)
│   ├── injuries.py          #    Injury reports (ESPN scrape)
│   └── team_context.py      #    Team defense, pace (nba_api)
│
├── model/                   # 🧠 Prediction engine
│   └── predict.py           #    4-layer model + edge detection + Kelly
│
├── output/                  # 📤 Report generation + delivery
│   ├── claude_analysis.py   #    Claude API integration
│   └── deliver.py           #    Discord, email, file output
│
├── tracking/                # 📝 Bet tracking + grading
│   └── grader.py            #    Auto-grade bets from box scores
│
├── reports/                 # 📁 Saved daily reports (auto-created)
│
└── .github/workflows/       # ⏰ GitHub Actions automation
    └── daily_props.yml      #    Scheduled daily runs
```

## Model Layers

| Layer | What It Does | Key Parameters |
|-------|-------------|----------------|
| **1. Baseline** | Weighted blend of season avg (40%) + L10 avg (60%), adjusted for minutes trend | `SEASON_WEIGHT`, `RECENT_WEIGHT` |
| **2. Matchup** | Adjusts for opponent defensive rating and projected game pace | Opponent PPG allowed, pace differential |
| **3. Situational** | B2B discount (-2 pts), blowout risk (-1.5 pts), teammate absence bump | `B2B_DISCOUNT`, `BLOWOUT_DISCOUNT` |
| **4. Distribution** | Fits log-normal distribution to game log → percentiles + P(Over) | `scipy.stats.lognorm` |
| **Edge Detection** | Compares model P(Over) vs implied probability from odds | `MIN_EDGE_THRESHOLD` (3%) |
| **Bet Sizing** | Quarter-Kelly criterion with max bet caps | `KELLY_FRACTION` (0.25) |

## Automation (GitHub Actions)

The included workflow runs automatically:

- **3:00 PM ET daily** → Full prediction pipeline
- **10:00 AM ET daily** → Grade yesterday's bets

### Setup GitHub Actions

1. Push this repo to GitHub
2. Go to **Settings → Secrets → Actions**
3. Add your API keys as secrets:
   - `ODDS_API_KEY`
   - `ANTHROPIC_API_KEY`
   - `DISCORD_WEBHOOK_URL`
   - `SENDGRID_API_KEY` (optional)
   - `EMAIL_TO` (optional)

## Tuning the Model

All model parameters are in `config.py`. Key levers:

```python
SEASON_WEIGHT = 0.40       # ↑ = more stable, ↓ = more reactive
RECENT_WEIGHT = 0.60       # inverse of SEASON_WEIGHT
B2B_DISCOUNT = -2.0        # ↑ magnitude = more aggressive B2B fade
MIN_EDGE_THRESHOLD = 0.03  # ↑ = fewer but higher-conviction bets
KELLY_FRACTION = 0.25      # ↑ = more aggressive sizing (max 1.0)
```

After 30+ days of tracked results, review your model performance in the dashboard and adjust these parameters based on:
- **Systematic bias** (consistently over/under projecting) → adjust weights
- **Edge accuracy** (are 8%+ edges actually hitting more?) → adjust thresholds
- **ROI by confidence tier** → adjust Kelly fraction

## Cost

| Component | Monthly Cost |
|-----------|-------------|
| The Odds API | $0 (free tier) or $20 (10K req) |
| Anthropic API | ~$15-30 (1 call/day, Sonnet) |
| GitHub Actions | $0 (free for public repos) |
| Streamlit Cloud | $0 (free tier) |
| **Total** | **$0 – $50/month** |

## Disclaimer

This is an analytical tool — not financial advice. Sports betting involves risk.
Bet responsibly. Past model performance does not guarantee future results.
