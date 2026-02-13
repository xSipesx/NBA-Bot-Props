"""
Ingest: NBA Schedule
Pulls today's games, teams, and start times via nba_api.
"""

import sys
import time
from datetime import datetime, timedelta, timezone

# nba_api imports
from nba_api.stats.endpoints import ScoreboardV2
from nba_api.stats.static import teams as nba_teams

import config


# Team abbreviation lookup
TEAM_MAP = {t['id']: t['abbreviation'] for t in nba_teams.get_teams()}


def get_todays_games(date=None):
    """
    Fetch today's NBA schedule.

    Args:
        date: Optional date string 'YYYY-MM-DD'. Defaults to today (ET).

    Returns:
        List of dicts: [{'game_id', 'home', 'away', 'home_id', 'away_id', 'start_time', 'status'}, ...]
    """
    if date is None:
        date = config.get_today()

    # nba_api expects MM/DD/YYYY
    parts = date.split("-")
    api_date = f"{parts[1]}/{parts[2]}/{parts[0]}"

    print(f"📅 Fetching schedule for {date}...")

    try:
        scoreboard = ScoreboardV2(
            game_date=api_date,
            league_id="00",
            timeout=config.NBA_API_TIMEOUT
        )
        time.sleep(1)  # rate limit courtesy

        games_header = scoreboard.game_header.get_data_frame()
        line_score = scoreboard.line_score.get_data_frame()

        if games_header.empty:
            print(f"  ⚠️  No games found for {date}")
            return []

        games = []
        for _, row in games_header.iterrows():
            game_id = row['GAME_ID']
            home_id = row['HOME_TEAM_ID']
            away_id = row['VISITOR_TEAM_ID']

            games.append({
                'game_id': game_id,
                'home': TEAM_MAP.get(home_id, str(home_id)),
                'away': TEAM_MAP.get(away_id, str(away_id)),
                'home_id': home_id,
                'away_id': away_id,
                'start_time': str(row.get('GAME_STATUS_TEXT', '')),
                'status': 'scheduled' if row.get('GAME_STATUS_ID', 1) == 1 else 'live' if row.get('GAME_STATUS_ID') == 2 else 'final',
            })

        print(f"  ✅ Found {len(games)} games")
        for g in games:
            print(f"     {g['away']} @ {g['home']} ({g['start_time']})")

        return games

    except Exception as e:
        print(f"  ❌ Error fetching schedule: {e}")
        return []


def was_team_playing_yesterday(team_abbrev, date=None):
    """
    Check if a team played yesterday (back-to-back detection).

    Returns:
        True if the team played yesterday.
    """
    if date is None:
        date = config.get_today()

    yesterday = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_games = get_todays_games(yesterday)

    for g in yesterday_games:
        if g['home'] == team_abbrev or g['away'] == team_abbrev:
            return True
    return False


def get_b2b_teams(games, date=None):
    """
    Given today's games, return set of teams on a back-to-back.
    """
    if date is None:
        date = config.get_today()

    yesterday = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_games = get_todays_games(yesterday)
    yesterday_teams = set()
    for g in yesterday_games:
        yesterday_teams.add(g['home'])
        yesterday_teams.add(g['away'])

    b2b_teams = set()
    for g in games:
        if g['home'] in yesterday_teams:
            b2b_teams.add(g['home'])
        if g['away'] in yesterday_teams:
            b2b_teams.add(g['away'])

    if b2b_teams:
        print(f"  🔄 Back-to-back teams: {', '.join(b2b_teams)}")

    return b2b_teams


if __name__ == "__main__":
    games = get_todays_games()
    if games:
        b2b = get_b2b_teams(games)
