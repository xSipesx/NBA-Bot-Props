"""
Ingest: Player Stats — all nba_api imports are lazy.
"""

import time
import numpy as np
import config


def get_roster_for_game(game):
    """Get top 8 players per team by minutes played."""
    from nba_api.stats.endpoints import LeagueDashPlayerStats
    from ingest.nba_helper import call_nba_api

    players = []
    for team_id, team_abbrev in [(game['home_id'], game['home']), (game['away_id'], game['away'])]:
        if not team_id:
            continue
        try:
            stats = call_nba_api(
                LeagueDashPlayerStats,
                season=config.NBA_SEASON,
                team_id_nullable=team_id,
                per_mode_detailed="PerGame",
            )
            df = stats.get_data_frames()[0]
            if df.empty:
                continue
            df = df.sort_values('MIN', ascending=False).head(8)
            for _, row in df.iterrows():
                players.append({
                    'player_id': row['PLAYER_ID'],
                    'player_name': row['PLAYER_NAME'],
                    'team': team_abbrev,
                    'team_id': team_id,
                    'season_ppg': round(row['PTS'], 1),
                    'season_min': round(row['MIN'], 1),
                    'gp': int(row.get('GP', 0)),
                })
        except Exception as e:
            print(f"  ⚠️  Error fetching roster for {team_abbrev}: {e}")
    print(f"  📊 Loaded {len(players)} players for {game['away']} @ {game['home']}")
    return players


def get_player_game_log(player_id, n_games=20):
    """Fetch a player's recent game log."""
    from nba_api.stats.endpoints import PlayerGameLog
    from ingest.nba_helper import call_nba_api

    try:
        log = call_nba_api(
            PlayerGameLog,
            player_id=player_id,
            season=config.NBA_SEASON,
            season_type_all_star="Regular Season",
        )
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
            })
        return games
    except Exception as e:
        print(f"  ⚠️  Error fetching game log for player {player_id}: {e}")
        return []


def compute_player_features(player, game_log):
    """Compute derived features from game log."""
    if not game_log:
        player['l5_ppg'] = player['season_ppg']
        player['l10_ppg'] = player['season_ppg']
        player['std_dev'] = 5.0
        player['game_log'] = []
        player['min_trend'] = player['season_min']
        return player

    pts_list = [g['pts'] for g in game_log if g['pts'] is not None]
    min_list = [g['min'] for g in game_log if g['min'] is not None and g['min'] > 0]

    l5_pts = pts_list[:5] if len(pts_list) >= 5 else pts_list
    l10_pts = pts_list[:10] if len(pts_list) >= 10 else pts_list

    player['l5_ppg'] = round(np.mean(l5_pts), 1) if l5_pts else player['season_ppg']
    player['l10_ppg'] = round(np.mean(l10_pts), 1) if l10_pts else player['season_ppg']
    player['std_dev'] = round(np.std(pts_list), 1) if len(pts_list) >= 5 else 5.0
    player['game_log'] = pts_list[:20]

    l5_min = min_list[:5] if len(min_list) >= 5 else min_list
    player['min_trend'] = round(np.mean(l5_min), 1) if l5_min else player['season_min']

    return player


def get_all_player_stats(games):
    """For each game, get rosters and stats for relevant players."""
    all_players = []
    for game in games:
        print(f"\n🏀 Loading players for {game['away']} @ {game['home']}...")
        roster = get_roster_for_game(game)
        for player in roster:
            game_log = get_player_game_log(player['player_id'])
            player = compute_player_features(player, game_log)
            player['game_id'] = game['game_id']
            if player['season_ppg'] >= 8.0 and player['season_min'] >= 15.0:
                all_players.append(player)
                print(f"     ✅ {player['player_name']:25s} {player['season_ppg']:5.1f} PPG | L10: {player['l10_ppg']:5.1f} | σ: {player['std_dev']:4.1f}")

    print(f"\n📊 Total players loaded: {len(all_players)}")
    return all_players
