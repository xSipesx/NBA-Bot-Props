"""
Ingest: ESPN Player Stats
Fetches season averages and recent game logs from ESPN's public API.

Correct endpoints:
- Roster: site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{id}/roster
- Gamelog: site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/gamelog
- Stats: site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/stats
"""

import requests
import json
import time

ESPN_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
ESPN_GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{player_id}/gamelog"
ESPN_STATS_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{player_id}/stats"

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
    """Fetch stats for rotation players (20+ MPG) on teams playing today."""
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
                stats = _get_player_season_stats(player['espn_id'], player['name'])
                if stats and stats.get('min_pg', 0) >= 20:
                    player.update(stats)
                    player['team'] = team_abbrev
                    player['game_id'] = game['game_id']
                    all_players.append(player)
                    loaded += 1
                time.sleep(0.15)

            print(f"  ✅ {team_abbrev}: {loaded} rotation players", flush=True)

    starter_count = len([p for p in all_players if p.get('min_pg', 0) >= 28])
    print(f"\n📊 Total: {len(all_players)} rotation players ({starter_count} starters)", flush=True)
    return all_players


def _get_team_roster(espn_team_id, team_abbrev):
    """Get roster from ESPN."""
    try:
        resp = requests.get(
            ESPN_ROSTER_URL.format(team_id=espn_team_id),
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ⚠️  Roster error {team_abbrev}: {e}", flush=True)
        return []

    players = []
    for athlete in data.get('athletes', []):
        players.append({
            'espn_id': athlete.get('id', ''),
            'name': athlete.get('displayName', ''),
            'position': athlete.get('position', {}).get('abbreviation', ''),
        })
    return players


def _get_player_season_stats(espn_player_id, player_name):
    """
    Get player stats using the v3 stats endpoint.
    Falls back to gamelog endpoint if stats endpoint fails.
    """
    # Try the stats endpoint first (gives season averages directly)
    stats = _try_stats_endpoint(espn_player_id, player_name)
    if stats:
        return stats

    # Fallback to gamelog endpoint
    stats = _try_gamelog_endpoint(espn_player_id, player_name)
    if stats:
        return stats

    return None


def _try_stats_endpoint(espn_player_id, player_name):
    """Try the v3 stats endpoint for season averages."""
    try:
        resp = requests.get(
            ESPN_STATS_URL.format(player_id=espn_player_id),
            params={'region': 'us', 'lang': 'en', 'contentorigin': 'espn'},
            timeout=10
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None

    try:
        # Navigate the stats response
        # Structure: {categories: [{name, statistics: [{...}]}]} or similar
        categories = data.get('categories', data.get('statistics', []))
        if not categories:
            # Try alternate structures
            results = data.get('results', [])
            if results:
                categories = results[0].get('categories', [])

        if not categories:
            return None

        stats = {}
        for cat in categories:
            cat_name = cat.get('name', cat.get('displayName', '')).lower()
            for stat in cat.get('statistics', cat.get('stats', [])):
                stat_name = stat.get('abbreviation', stat.get('name', '')).upper()
                stat_val = stat.get('displayValue', stat.get('value', ''))
                try:
                    stats[stat_name] = float(stat_val)
                except (ValueError, TypeError):
                    pass

        if 'PTS' in stats and 'MIN' in stats:
            return {
                'gp': int(stats.get('GP', 0)),
                'min_pg': stats.get('MIN', 0),
                'pts_avg': stats.get('PTS', 0),
                'reb_avg': stats.get('REB', 0),
                'ast_avg': stats.get('AST', 0),
                # Without gamelog, use season as all windows
                'pts_l5': stats.get('PTS', 0),
                'reb_l5': stats.get('REB', 0),
                'ast_l5': stats.get('AST', 0),
                'pts_l10': stats.get('PTS', 0),
                'reb_l10': stats.get('REB', 0),
                'ast_l10': stats.get('AST', 0),
                'pts_std': stats.get('PTS', 20) * 0.25,
                'reb_std': stats.get('REB', 5) * 0.30,
                'ast_std': stats.get('AST', 4) * 0.35,
                'min_l5': stats.get('MIN', 0),
                'pts_log': [], 'reb_log': [], 'ast_log': [],
            }
    except Exception:
        pass
    return None


def _try_gamelog_endpoint(espn_player_id, player_name):
    """Try the v3 gamelog endpoint for game-by-game data."""
    try:
        resp = requests.get(
            ESPN_GAMELOG_URL.format(player_id=espn_player_id),
            params={'region': 'us', 'lang': 'en', 'contentorigin': 'espn'},
            timeout=10
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None

    try:
        # The gamelog response has multiple possible structures.
        # We need to find: labels (column names) and events (rows of stats)
        
        # Structure 1: {seasonTypes: [{categories: [{events: [...]}]}]}
        season_types = data.get('seasonTypes', [])
        
        # Structure 2: {categories: [{events: [...]}]}
        if not season_types:
            categories = data.get('categories', [])
            if categories:
                season_types = [{'categories': categories}]
        
        if not season_types:
            return None

        # Find regular season data
        reg = None
        for st in season_types:
            name = st.get('displayName', st.get('name', ''))
            st_type = st.get('type', 0)
            if 'regular' in name.lower() or st_type == 2:
                reg = st
                break
        if not reg:
            reg = season_types[0]

        categories = reg.get('categories', [])
        if not categories:
            return None

        # Find category with game data
        stat_labels = []
        game_entries = []
        
        for cat in categories:
            events = cat.get('events', [])
            if not events:
                continue
            
            # Get labels
            labels = cat.get('labels', [])
            if labels:
                stat_labels = [l.upper() if isinstance(l, str) else l.get('abbreviation', l.get('name', '')).upper() for l in labels]
            
            game_entries = events
            break

        if not game_entries or not stat_labels:
            return None

        # Parse games
        game_logs = []
        for entry in game_entries:
            raw = entry.get('stats', [])
            if not raw or raw == ['--']:
                continue

            game = {}
            for i, val in enumerate(raw):
                if i >= len(stat_labels):
                    break
                try:
                    game[stat_labels[i]] = float(val)
                except (ValueError, TypeError):
                    pass

            if 'PTS' in game:
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
                return round(avg(key) * 0.25, 1)
            mean = sum(vals) / len(vals)
            var = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
            return round(max(var ** 0.5, 1.0), 1)

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


def debug_one_player(espn_player_id):
    """Debug helper: dump raw API responses for a single player."""
    print(f"\n=== DEBUG: Player {espn_player_id} ===")
    
    for name, url_template in [("STATS", ESPN_STATS_URL), ("GAMELOG", ESPN_GAMELOG_URL)]:
        try:
            url = url_template.format(player_id=espn_player_id)
            resp = requests.get(url, params={'region': 'us', 'lang': 'en', 'contentorigin': 'espn'}, timeout=10)
            print(f"\n--- {name} (status {resp.status_code}) ---")
            if resp.status_code == 200:
                data = resp.json()
                print(f"Top-level keys: {list(data.keys())}")
                for key in data:
                    val = data[key]
                    if isinstance(val, list):
                        print(f"  {key}: list of {len(val)}")
                        if val:
                            first = val[0]
                            if isinstance(first, dict):
                                print(f"    [0] keys: {list(first.keys())}")
                    elif isinstance(val, dict):
                        print(f"  {key}: dict with keys {list(val.keys())[:8]}")
                    else:
                        print(f"  {key}: {str(val)[:80]}")
            else:
                print(f"  Response: {resp.text[:200]}")
        except Exception as e:
            print(f"  Error: {e}")
