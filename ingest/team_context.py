"""
Ingest: Team Context
Pulls team defensive ratings, pace, and opponent positional scoring data.
"""

import time
from nba_api.stats.endpoints import (
    LeagueDashTeamStats,
    TeamEstimatedMetrics,
)
import config


def get_team_context():
    """
    Fetch team-level stats: defensive rating, pace, opponent PPG allowed.

    Returns:
        Dict keyed by team abbreviation:
        {
            'OKC': {
                'def_rating': 105.2,
                'pace': 99.3,
                'opp_ppg_allowed': 108.5,
                'def_rank': 1,
                ...
            }
        }
    """
    print("🛡️  Fetching team context (defense, pace)...")

    teams = {}

    # 1. Basic team stats (opponent PPG, pace proxy)
    try:
        stats = LeagueDashTeamStats(
            season=config.NBA_SEASON,
            per_mode_detailed="PerGame",
            measure_type_detailed_defense="Opponent",  # opponent stats = what they allow
            timeout=config.NBA_API_TIMEOUT,
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
                'opp_ppg_allowed': round(row.get('PTS', 0), 1),  # opponent scoring = defense
                'opp_fga': round(row.get('FGA', 0), 1),
                'opp_fg_pct': round(row.get('FG_PCT', 0), 3),
                'opp_fg3_pct': round(row.get('FG3_PCT', 0), 3),
                'opp_fta': round(row.get('FTA', 0), 1),
            }
    except Exception as e:
        print(f"  ⚠️  Error fetching opponent stats: {e}")

    # 2. Advanced metrics (def rating, pace)
    try:
        advanced = LeagueDashTeamStats(
            season=config.NBA_SEASON,
            per_mode_detailed="PerGame",
            measure_type_detailed_defense="Advanced",
            timeout=config.NBA_API_TIMEOUT,
        )
        time.sleep(1)

        df_adv = advanced.get_data_frames()[0]
        for _, row in df_adv.iterrows():
            abbrev = row.get('TEAM_ABBREVIATION', '')
            if abbrev not in teams:
                teams[abbrev] = {'team': abbrev}

            teams[abbrev]['def_rating'] = round(row.get('DEF_RATING', 0), 1)
            teams[abbrev]['off_rating'] = round(row.get('OFF_RATING', 0), 1)
            teams[abbrev]['net_rating'] = round(row.get('NET_RATING', 0), 1)
            teams[abbrev]['pace'] = round(row.get('PACE', 0), 1)

    except Exception as e:
        print(f"  ⚠️  Error fetching advanced team stats: {e}")

    # Rank teams by defensive rating
    sorted_by_def = sorted(teams.values(), key=lambda x: x.get('def_rating', 999))
    for rank, team in enumerate(sorted_by_def, 1):
        teams[team['team']]['def_rank'] = rank

    sorted_by_pace = sorted(teams.values(), key=lambda x: x.get('pace', 0), reverse=True)
    for rank, team in enumerate(sorted_by_pace, 1):
        teams[team['team']]['pace_rank'] = rank

    print(f"  ✅ Loaded context for {len(teams)} teams")

    # Print top 5 defenses and top 5 pace teams
    print("  🏆 Top 5 Defenses:")
    for t in sorted_by_def[:5]:
        print(f"     {t.get('def_rank', '?'):2d}. {t['team']:3s} — DEF RTG: {t.get('def_rating', '?')}")
    print("  🏃 Top 5 Pace:")
    for t in sorted_by_pace[:5]:
        print(f"     {t.get('pace_rank', '?'):2d}. {t['team']:3s} — PACE: {t.get('pace', '?')}")

    return teams


def get_projected_game_pace(home_team_ctx, away_team_ctx):
    """Estimate the projected pace for a specific game."""
    home_pace = home_team_ctx.get('pace', 100)
    away_pace = away_team_ctx.get('pace', 100)
    league_avg_pace = 100.0  # approximate

    # Formula: average of both teams' pace, regressed slightly to mean
    raw = (home_pace + away_pace) / 2
    regressed = (raw * 0.8) + (league_avg_pace * 0.2)
    return round(regressed, 1)


def get_matchup_adjustment(player_ppg, opp_team_ctx, league_avg_ppg_allowed=114.0):
    """
    Calculate matchup adjustment based on opponent defense.

    If opponent allows more points than league average, boost projection.
    If opponent is elite defensively, discount projection.

    Returns:
        Float adjustment (positive = boost, negative = discount)
    """
    opp_ppg_allowed = opp_team_ctx.get('opp_ppg_allowed', league_avg_ppg_allowed)
    diff = opp_ppg_allowed - league_avg_ppg_allowed

    # Scale the adjustment relative to the player's scoring volume
    # A 25 PPG scorer is more affected by matchup than a 10 PPG scorer
    scale_factor = player_ppg / 20.0  # normalized around ~20 PPG

    adjustment = diff * 0.10 * scale_factor  # conservative multiplier

    return round(adjustment, 1)


if __name__ == "__main__":
    teams = get_team_context()
