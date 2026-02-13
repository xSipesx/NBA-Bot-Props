"""
Ingest: Player Stats
Pulls season averages, recent game logs, and computed features for each player.
Uses nba_api for all data.
"""

import time
import numpy as np
from nba_api.stats.endpoints import (
    PlayerGameLog,
    CommonPlayerInfo,
    LeagueDashPlayerStats,
    PlayerDashboardByGameSplits,
)
from nba_api.stats.static import players as nba_players, teams as nba_teams

import config

# Build lookup dicts
ALL_PLAYERS = {p['id']: p for p in nba_players.get_players()}
TEAM_MAP = {t['id']: t['abbreviation'] for t in nba_teams.get_teams()}
TEAM_NAME_TO_ABBREV = {t['full_name']: t['abbreviation'] for t in nba_teams.get_teams()}


def get_roster_for_game(game):
    """
    Get relevant players (likely starters + key rotation) for both teams in a game.
    Uses league-wide player stats filtered to the teams, sorted by minutes.
    Returns top 8 players per team by minutes played.
    """
    home_id = game['home_id']
    away_id = game['away_id']
    players = []

    for team_id, team_abbrev in [(home_id, game['home']), (away_id, game['away'])]:
        try:
            stats = LeagueDashPlayerStats(
                season=config.NBA_SEASON,
                team_id_nullable=team_id,
                per_mode_detailed="PerGame",
                timeout=config.NBA_API_TIMEOUT,
            )
            time.sleep(0.8)

            df = stats.get_data_frames()[0]
            if df.empty:
                continue

            # Sort by minutes, take top 8 (starters + key bench)
            df = df.sort_values('MIN', ascending=False).head(8)

            for _, row in df.iterrows():
                players.append({
                    'player_id': row['PLAYER_ID'],
                    'player_name': row['PLAYER_NAME'],
                    'team': team_abbrev,
                    'team_id': team_id,
                    'season_ppg': round(row['PTS'], 1),
                    'season_min': round(row['MIN'], 1),
                    'season_fga': round(row.get('FGA', 0), 1),
                    'season_fta': round(row.get('FTA', 0), 1),
                    'season_fg_pct': round(row.get('FG_PCT', 0), 3),
                    'season_fg3_pct': round(row.get('FG3_PCT', 0), 3),
                    'season_ft_pct': round(row.get('FT_PCT', 0), 3),
                    'gp': int(row.get('GP', 0)),
                })

        except Exception as e:
            print(f"  ⚠️  Error fetching roster for {team_abbrev}: {e}")

    print(f"  📊 Loaded {len(players)} players for {game['away']} @ {game['home']}")
    return players


def get_player_game_log(player_id, n_games=20):
    """
    Fetch a player's recent game log.

    Returns:
        List of dicts with per-game stats, most recent first.
    """
    try:
        log = PlayerGameLog(
            player_id=player_id,
            season=config.NBA_SEASON,
            season_type_all_star="Regular Season",
            timeout=config.NBA_API_TIMEOUT,
        )
        time.sleep(0.6)

        df = log.get_data_frames()[0]
        if df.empty:
            return []

        df = df.head(n_games)

        games = []
        for _, row in df.iterrows():
            games.append({
                'date': row['GAME_DATE'],
                'matchup': row['MATCHUP'],
                'min': row['MIN'],
                'pts': row['PTS'],
                'fga': row['FGA'],
                'fgm': row['FGM'],
                'fta': row['FTA'],
                'ftm': row['FTM'],
                'fg3a': row.get('FG3A', 0),
                'fg3m': row.get('FG3M', 0),
                'reb': row.get('REB', 0),
                'ast': row.get('AST', 0),
                'plus_minus': row.get('PLUS_MINUS', 0),
                'wl': row.get('WL', ''),
            })

        return games

    except Exception as e:
        print(f"  ⚠️  Error fetching game log for player {player_id}: {e}")
        return []


def compute_player_features(player, game_log):
    """
    Compute derived features from a player's game log.

    Adds to player dict:
        l5_ppg, l10_ppg, std_dev, game_log (list of pts), min_trend,
        boom_rate, bust_rate
    """
    if not game_log:
        player['l5_ppg'] = player['season_ppg']
        player['l10_ppg'] = player['season_ppg']
        player['std_dev'] = 5.0  # default
        player['game_log'] = []
        player['min_trend'] = player['season_min']
        player['boom_rate'] = 0.0
        player['bust_rate'] = 0.0
        return player

    pts_list = [g['pts'] for g in game_log if g['pts'] is not None]
    min_list = [g['min'] for g in game_log if g['min'] is not None and g['min'] > 0]

    # Recent averages
    l5_pts = pts_list[:5] if len(pts_list) >= 5 else pts_list
    l10_pts = pts_list[:10] if len(pts_list) >= 10 else pts_list

    player['l5_ppg'] = round(np.mean(l5_pts), 1) if l5_pts else player['season_ppg']
    player['l10_ppg'] = round(np.mean(l10_pts), 1) if l10_pts else player['season_ppg']
    player['std_dev'] = round(np.std(pts_list), 1) if len(pts_list) >= 5 else 5.0
    player['game_log'] = pts_list[:20]

    # Minutes trend (average of last 5 vs season)
    l5_min = min_list[:5] if len(min_list) >= 5 else min_list
    player['min_trend'] = round(np.mean(l5_min), 1) if l5_min else player['season_min']

    # Boom/bust rates
    avg = player['season_ppg']
    if avg > 0 and len(pts_list) >= 10:
        player['boom_rate'] = round(sum(1 for p in pts_list if p > avg * 1.3) / len(pts_list), 2)
        player['bust_rate'] = round(sum(1 for p in pts_list if p < avg * 0.7) / len(pts_list), 2)
    else:
        player['boom_rate'] = 0.0
        player['bust_rate'] = 0.0

    return player


def get_all_player_stats(games):
    """
    Master function: for each game, get rosters and full stats for all relevant players.

    Returns:
        List of enriched player dicts with all features computed.
    """
    all_players = []

    for game in games:
        print(f"\n🏀 Loading players for {game['away']} @ {game['home']}...")
        roster = get_roster_for_game(game)

        for player in roster:
            # Get game log and compute features
            game_log = get_player_game_log(player['player_id'])
            player = compute_player_features(player, game_log)
            player['game_id'] = game['game_id']

            # Only include players averaging 8+ PPG and 15+ min (skip deep bench)
            if player['season_ppg'] >= 8.0 and player['season_min'] >= 15.0:
                all_players.append(player)
                print(f"     ✅ {player['player_name']:25s} {player['season_ppg']:5.1f} PPG | L10: {player['l10_ppg']:5.1f} | σ: {player['std_dev']:4.1f}")
            else:
                print(f"     ⏭️  {player['player_name']:25s} {player['season_ppg']:5.1f} PPG — below threshold, skipping")

    print(f"\n📊 Total players loaded: {len(all_players)}")
    return all_players


if __name__ == "__main__":
    from ingest.schedule import get_todays_games
    games = get_todays_games()
    if games:
        players = get_all_player_stats(games[:1])  # test with first game only
