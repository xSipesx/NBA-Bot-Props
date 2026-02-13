"""
NBA Props Agent — Configuration
All API keys loaded from environment variables.
All model parameters tunable here.
"""

import os
from datetime import datetime, timezone

# Load .env file if present (for local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed — use system env vars (GitHub Actions, etc.)

# ──────────────────────────────────────────────
# API KEYS (set these as environment variables)
# ──────────────────────────────────────────────
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

# ──────────────────────────────────────────────
# MODEL PARAMETERS
# ──────────────────────────────────────────────

# Layer 1: Baseline weighting
SEASON_WEIGHT = 0.40
RECENT_WEIGHT = 0.60  # applied to L10 average
RECENT_WINDOW = 10    # number of recent games

# Layer 3: Situational adjustments
B2B_DISCOUNT = -2.0          # points deducted for back-to-back
BLOWOUT_SPREAD_THRESHOLD = 10  # spread above which we apply blowout discount
BLOWOUT_DISCOUNT = -1.5       # points deducted for blowout risk (reduced Q4 min)
USAGE_REDISTRIBUTION_FACTOR = 0.30  # % of absent player's PPG redistributed

# Layer 5: Edge detection
MIN_EDGE_THRESHOLD = 0.03     # 3% minimum edge to flag a bet
EDGE_LOW = 0.03               # 3-5% = LOW confidence
EDGE_MEDIUM = 0.05            # 5-8% = MEDIUM confidence
EDGE_HIGH = 0.08              # 8%+ = HIGH confidence

# Bet sizing
KELLY_FRACTION = 0.25         # quarter-Kelly for safety
MAX_SINGLE_BET_PCT = 0.05     # max 5% of bankroll on one bet
MAX_DAILY_EXPOSURE_PCT = 0.20 # max 20% of bankroll per day
DEFAULT_BANKROLL = 1000.0     # default bankroll in units (1u = 1% = $10 on $1000)

# ──────────────────────────────────────────────
# DATA SOURCES
# ──────────────────────────────────────────────

# The Odds API
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_SPORT = "basketball_nba"
ODDS_REGIONS = "us"
ODDS_MARKETS = "player_points"
ODDS_BOOKMAKERS = "fanduel,draftkings,betmgm"  # preferred books in priority order

# NBA API
NBA_API_TIMEOUT = 30  # seconds

# ──────────────────────────────────────────────
# OUTPUT
# ──────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"  # or "claude-opus-4-5-20250929" for highest quality
CLAUDE_MAX_TOKENS = 8000

# ──────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "nba_props.db")

# ──────────────────────────────────────────────
# SCHEDULE
# ──────────────────────────────────────────────
# NBA season roughly Oct-Apr regular season, Apr-Jun playoffs
NBA_SEASON = "2025-26"
NBA_SEASON_ID = "22025"  # nba_api format: 2 + year of start


def get_today():
    """Return today's date string in YYYY-MM-DD format (ET)."""
    from datetime import timezone, timedelta
    et = timezone(timedelta(hours=-5))
    return datetime.now(et).strftime("%Y-%m-%d")
