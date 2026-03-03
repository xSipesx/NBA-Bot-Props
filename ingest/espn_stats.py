"""
Ingest: ESPN Player Stats
Fetches season averages and recent game logs from ESPN's public API.
Works from cloud servers (unlike nba_api which is blocked).
"""

import requests
import time

ESPN_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
ESPN_GAMELOG_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/players/{player_id}/gamelog"

# ESPN team IDs
ESPN_TEAM_IDS = {
    'ATL': 1, 'BOS': 2, 'BKN': 17, 'CHA': 30, 'CHI': 4,
    'CLE': 5, 'DAL': 6, 'DEN': 7, 'DET': 8, 'GSW': 9,
    'HOU': 10, 'IND': 11, 'LAC': 12, 'LAL': 13, 'MEM': 29,
    'MIA': 14, 'MIL': 15, 'MIN': 16, 'NOP': 3, 'NYK': 18,
    'OKC': 25, 'ORL': 19, 'PHI': 20, 'PHX': 21, 'POR': 22,
    'SAC': 23, 'SAS': 24, 'TOR': 28, 'UTA': 26, 'WAS': 27,
}


def get_starters_stats(games):
    """
    For each game, fetch rosters and stats for rotation players (20+ MPG).
    Returns list of player dicts with season averages and recent form.
    """
    all_players = []
    teams_loaded = set()

    for game in games:
        for team_abbrev in [game['home'], game['away']]:
            if team_abbrev in teams_loaded:
                continue
            teams_loaded.add(team_abbrev)

            espn_id = ESPN_TEAM_IDS.get(team_abbrev)
            if not espn_id:
                print(f"  ⚠️  Unknown team: {team_abbrev}", flush=True)
                continue

            roster = _get_team_roster(espn_id, team_abbrev)
            if not roster:
                continue

            loaded = 0
            for player in roster:
                stats = _get_player_gamelog(player['espn_id'])
                if stats and stats.get('min_pg', 0) >= 20:
                    player.update(stats)
                    player['team'] = team_abbrev
                    player['game_id'] = game['game_id']
                    all_players.append(player)
                    loaded += 1
                time.sleep(0.2)  # be polite to ESPN

            print(f"  ✅ {team_abbrev}: {loaded} rotation players loaded", flush=True)

    starter_count = len([p for p in all_players if p.get('min_pg', 0) >= 28])
    print(f"\n📊 Total: {len(all_players)} rotation players ({starter_count} starters)", flush=True)
    return all_players


def _get_team_roster(espn_team_id, team_abbrev):
    """Get roster for a team from ESPN."""
    try:
        resp = requests.get(
            ESPN_ROSTER_URL.format(team_id=espn_team_id),
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ⚠️  Error fetching {team_abbrev} roster: {e}", flush=True)
        return []

    players = []
    for athlete in data.get('athletes', []):
        players.append({
            'espn_id': athlete.get('id', ''),
            'name': athlete.get('displayName', ''),
            'position': athlete.get('position', {}).get('abbreviation', ''),
        })
    return players


def _get_player_gamelog(espn_player_id):
    """Get season stats from a player's game log."""
    try:
        resp = requests.get(
            ESPN_GAMELOG_URL.format(player_id=espn_player_id),
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    try:
        # Navigate ESPN gamelog structure
        season_types = data.get('seasonTypes', [])
        if not season_types:
            return None

        # Find regular season
        reg_season = None
        for st in season_types:
            if st.get('displayName', '') == 'Regular Season' or st.get('type') == 2:
                reg_season = st
                break
        if not reg_season:
            reg_season = season_types[0]

        categories = reg_season.get('categories', [])
        if not categories:
            return None

        # Find the stats category with game-by-game data
        entries = []
        stat_labels = []
        for cat in categories:
            events = cat.get('events', [])
            if events:
                entries = events
                # Get stat column names
                stat_labels = []
                for s in cat.get('labels', []):
                    if isinstance(s, str):
                        stat_labels.append(s.upper())
                    elif isinstance(s, dict):
                        stat_labels.append(s.get('abbreviation', s.get('name', '')).upper())
                break

        if not entries:
            return None

        # Parse each game
        game_logs = []
        for entry in entries:
            raw_stats = entry.get('stats', [])
            if not raw_stats or raw_stats == ['--']:
                continue

            game = {}
            for i, val in enumerate(raw_stats):
                if i >= len(stat_labels):
                    break
                label = stat_labels[i]
                try:
                    game[label] = float(val)
                except (ValueError, TypeError):
                    # Handle split stats like "8-15" for FG
                    pass

            if 'PTS' in game and 'MIN' in game:
                game_logs.append(game)

        if not game_logs:
            return None

        # Calculate averages
        n = len(game_logs)
        l5 = min(5, n)
        l10 = min(10, n)

        def avg(key, count=None):
            vals = [g.get(key, 0) for g in game_logs[:count] if key in g]
            return round(sum(vals) / len(vals), 1) if vals else 0

        def std(key):
            vals = [g.get(key, 0) for g in game_logs if key in g]
            if len(vals) < 3:
                return 5.0
            mean = sum(vals) / len(vals)
            var = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
            return round(var ** 0.5, 1)

        return {
            'gp': n,
            'min_pg': avg('MIN'),
            'pts_avg': avg('PTS'), 'reb_avg': avg('REB'), 'ast_avg': avg('AST'),
            'pts_l5': avg('PTS', l5), 'reb_l5': avg('REB', l5), 'ast_l5': avg('AST', l5),
            'pts_l10': avg('PTS', l10), 'reb_l10': avg('REB', l10), 'ast_l10': avg('AST', l10),
            'pts_std': std('PTS'), 'reb_std': std('REB'), 'ast_std': std('AST'),
            'min_l5': avg('MIN', l5),
            'pts_log': [g.get('PTS', 0) for g in game_logs[:10]],
            'reb_log': [g.get('REB', 0) for g in game_logs[:10]],
            'ast_log': [g.get('AST', 0) for g in game_logs[:10]],
        }

    except Exception:
        return None
