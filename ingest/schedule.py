"""
Ingest: NBA Schedule — only used for local runs.
The cloud pipeline uses Odds API for schedule (see odds.py).
"""

def get_todays_games(date=None):
    """Fetch schedule via nba_api (local only, blocks on cloud)."""
    from nba_api.stats.endpoints import ScoreboardV2
    from nba_api.stats.static import teams as nba_teams
    import config
    
    if date is None:
        date = config.get_today()
    parts = date.split("-")
    api_date = f"{parts[1]}/{parts[2]}/{parts[0]}"
    
    TEAM_MAP = {t['id']: t['abbreviation'] for t in nba_teams.get_teams()}
    scoreboard = ScoreboardV2(game_date=api_date, league_id="00", timeout=30)
    games_header = scoreboard.game_header.get_data_frame()
    
    games = []
    for _, row in games_header.iterrows():
        home_id = row['HOME_TEAM_ID']
        away_id = row['VISITOR_TEAM_ID']
        games.append({
            'game_id': row['GAME_ID'], 'home': TEAM_MAP.get(home_id, ''),
            'away': TEAM_MAP.get(away_id, ''), 'home_id': home_id, 'away_id': away_id,
            'start_time': str(row.get('GAME_STATUS_TEXT', '')), 'status': 'scheduled',
        })
    return games

def get_b2b_teams(games, date=None):
    return set()
