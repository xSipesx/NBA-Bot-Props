"""
Ingest: Team Context — all nba_api imports are lazy.
"""

import time
import config


def get_team_context():
    """Fetch team-level stats: defensive rating, pace, opponent PPG allowed."""
    from nba_api.stats.endpoints import LeagueDashTeamStats
    from ingest.nba_helper import call_nba_api

    print("🛡️  Fetching team context (defense, pace)...")
    teams = {}

    # Base stats
    try:
        stats = call_nba_api(
            LeagueDashTeamStats,
            season=config.NBA_SEASON,
            per_mode_detailed="PerGame",
            measure_type_detailed_defense="Base",
        )
        time.sleep(1)
        df = stats.get_data_frames()[0]
        for _, row in df.iterrows():
            abbrev = row.get('TEAM_ABBREVIATION', '')
            if not abbrev:
                continue
            teams[abbrev] = {
                'team': abbrev,
                'team_name': row.get('TEAM_NAME', ''),
                'opp_ppg_allowed': 114.0,  # default, updated by advanced stats
            }
    except Exception as e:
        print(f"  ⚠️  Error fetching base team stats: {e}")

    # Advanced stats (def rating, pace)
    try:
        advanced = call_nba_api(
            LeagueDashTeamStats,
            season=config.NBA_SEASON,
            per_mode_detailed="PerGame",
            measure_type_detailed_defense="Advanced",
        )
        time.sleep(1)
        df_adv = advanced.get_data_frames()[0]
        for _, row in df_adv.iterrows():
            abbrev = row.get('TEAM_ABBREVIATION', '')
            if abbrev not in teams:
                teams[abbrev] = {'team': abbrev}
            teams[abbrev]['def_rating'] = round(float(row.get('DEF_RATING', 0) or 0), 1)
            teams[abbrev]['off_rating'] = round(float(row.get('OFF_RATING', 0) or 0), 1)
            teams[abbrev]['net_rating'] = round(float(row.get('NET_RATING', 0) or 0), 1)
            teams[abbrev]['pace'] = round(float(row.get('PACE', 0) or 0), 1)
            teams[abbrev]['opp_ppg_allowed'] = round(float(row.get('DEF_RATING', 0) or 0), 1)
    except Exception as e:
        print(f"  ⚠️  Error fetching advanced team stats: {e}")

    # Rank
    sorted_by_def = sorted(teams.values(), key=lambda x: x.get('def_rating', 999))
    for rank, team in enumerate(sorted_by_def, 1):
        teams[team['team']]['def_rank'] = rank

    print(f"  ✅ Loaded context for {len(teams)} teams")
    return teams


def get_projected_game_pace(home_ctx, away_ctx):
    """Estimate projected pace for a specific game."""
    home_pace = home_ctx.get('pace', 100)
    away_pace = away_ctx.get('pace', 100)
    raw = (home_pace + away_pace) / 2
    return round((raw * 0.8) + (100.0 * 0.2), 1)
