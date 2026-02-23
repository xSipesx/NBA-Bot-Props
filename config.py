"""
NBA Props Agent — Configuration
"""

import os
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── API KEYS ──
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

# ── MODEL PARAMETERS ──
SEASON_WEIGHT = 0.40
RECENT_WEIGHT = 0.60
RECENT_WINDOW = 10

B2B_DISCOUNT = -2.0
BLOWOUT_SPREAD_THRESHOLD = 10
BLOWOUT_DISCOUNT = -1.5
USAGE_REDISTRIBUTION_FACTOR = 0.30

MIN_EDGE_THRESHOLD = 0.03
EDGE_LOW = 0.03
EDGE_MEDIUM = 0.05
EDGE_HIGH = 0.08

KELLY_FRACTION = 0.25
MAX_SINGLE_BET_PCT = 0.05
MAX_DAILY_EXPOSURE_PCT = 0.20
DEFAULT_BANKROLL = 1000.0

# ── DATA SOURCES ──
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_SPORT = "basketball_nba"
ODDS_REGIONS = "us"
ODDS_MARKETS = "player_points,player_rebounds,player_assists"
ODDS_BOOKMAKERS = "fanduel,draftkings,betmgm"

NBA_API_TIMEOUT = 30
NBA_SEASON = "2025-26"
NBA_SEASON_ID = "22025"

# ── OUTPUT ──
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
CLAUDE_MAX_TOKENS = 8000

# ── DATABASE ──
DB_PATH = os.environ.get("DB_PATH", "nba_props.db")


def get_today():
    from datetime import timezone, timedelta
    et = timezone(timedelta(hours=-5))
    return datetime.now(et).strftime("%Y-%m-%d")
