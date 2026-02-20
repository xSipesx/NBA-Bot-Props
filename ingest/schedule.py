"""
Ingest: NBA Schedule — all nba_api imports are lazy.
"""

import time
from datetime import datetime, timedelta

import config


def get_todays_games(date=None):
    """Fetch today's NBA schedule via nba_api (fallback source)."""
    if date is None:
        date = config.get_today()

    parts = date.split("-")
    api_date = f"{parts[1]}/{parts[2]}/{parts[0]}"
    print(f"📅 Fetching schedule for {date}...")

    try:
        from nba_api.stats.endpoints import ScoreboardV2
        from nba_api.stats.static import teams as nba_teams
        from ingest.nba_helper import call_nba_api

        TEAM_MAP = {t['id']: t['abbreviation'] for t in nba_teams.get_teams()}

        scoreboard = call_nba_api(ScoreboardV2, game_date=api_date, league_id="00")
        games_header = scoreboard.game_header.get_data_frame()

        if games_header.empty:
            print(f"  ⚠️  No games found for {date}")
            return []

        games = []
        for _, row in games_header.iterrows():
            home_id = row['HOME_TEAM_ID']
            away_id = row['VISITOR_TEAM_ID']
            games.append({
                'game_id': row['GAME_ID'],
                'home': TEAM_MAP.get(home_id, str(home_id)),
                'away': TEAM_MAP.get(away_id, str(away_id)),
                'home_id': home_id,
                'away_id': away_id,
                'start_time': str(row.get('GAME_STATUS_TEXT', '')),
                'status': 'scheduled',
            })

        print(f"  ✅ Found {len(games)} games")
        return games

    except Exception as e:
        print(f"  ❌ Error fetching schedule: {e}")
        return []


def get_b2b_teams(games, date=None):
    """Return set of teams on a back-to-back."""
    if date is None:
        date = config.get_today()
    yesterday = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        yesterday_games = get_todays_games(yesterday)
    except Exception:
        return set()
    yesterday_teams = set()
    for g in yesterday_games:
        yesterday_teams.add(g['home'])
        yesterday_teams.add(g['away'])
    b2b = set()
    for g in games:
        if g['home'] in yesterday_teams:
            b2b.add(g['home'])
        if g['away'] in yesterday_teams:
            b2b.add(g['away'])
    if b2b:
        print(f"  🔄 B2B teams: {', '.join(b2b)}")
    return b2b
