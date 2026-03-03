"""
Ingest: ESPN Player Stats v3
Correct parsing based on actual API response structure.

GAMELOG response structure:
{
  "labels": ["MIN", "FG", "3PT", "FT", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "+/-", "PTS"],
  "seasonTypes": [
    {
      "displayName": "Regular Season",
      "categories": [
        {
          "events": [
            {"eventId": "401810718", "stats": ["32", "8-17", "2-7", "5-5", "0", "3", "3", "8", "2", "0", "5", "3", "+1", "23"]},
            ...
          ]
        }
      ]
    }
  ],
  "events": {"401810718": {...event details...}, ...}
}

STATS response structure:
{
  "categories": [
    {
      "name": "offensive",
      "labels": ["MIN", "FG%", "3P%", "FT%", ...],
      "statistics": [{"displayValue": "33.2", ...}, ...]
    }
  ]
}
"""

import requests
import time

ESPN_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
ESPN_GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{player_id}/gamelog"
ESPN_STATS_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{player_id}/stats"

ESPN_TEAM_IDS = {
    'ATL': 1, 'BOS': 2, 'BKN': 17, 'CHA': 30, 'CHI': 4,
    'CLE': 5, 'DAL': 6, 'DEN': 7, 'DET': 8, 'GSW': 9,
    'HOU': 10, 'IND': 11, 'LAC': 12, 'LAL': 13, 'MEM': 29,
    'MIA': 14, 'MIL': 15, 'MIN': 16, 'NOP': 3, 'NYK': 18,
    'OKC': 25, 'ORL': 19, 'PHI': 20, 'PHX': 21, 'POR': 22,
    'SAC': 23, 'SAS': 24, 'TOR': 28, 'UTA': 26, 'WAS': 27,
}


def get_starters_stats(games):
    """Fetch stats for rotation players on teams playing today."""
    all_players = []
    teams_loaded = set()

    for game in games:
        for team_abbrev in [game['home'], game['away']]:
            if team_abbrev in teams_loaded:
                continue
            teams_loaded.add(team_abbrev)

            espn_id = ESPN_TEAM_IDS.get(team_abbrev)
            if not espn_id:
                continue

            roster = _get_team_roster(espn_id, team_abbrev)
            if not roster:
                continue

            loaded = 0
            for player in roster:
                stats = _get_player_gamelog(player['espn_id'], player['name'])
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
    try:
        resp = requests.get(ESPN_ROSTER_URL.format(team_id=espn_team_id), timeout=10)
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


def _get_player_gamelog(espn_player_id, player_name):
    """
    Fetch gamelog from ESPN v3 API.
    
    Key insight from debug: labels are at TOP LEVEL of the response,
    and game stats are inside seasonTypes → categories → events list,
    where each event has a 'stats' array matching the top-level labels.
    """
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
        # Step 1: Get column labels from top level
        labels = data.get('labels', [])
        if not labels:
            # Try getting from 'names' field as fallback
            labels = data.get('names', [])
        if not labels:
            return None
        
        labels = [l.upper() if isinstance(l, str) else str(l).upper() for l in labels]

        # Step 2: Find game entries from seasonTypes → categories → events
        season_types = data.get('seasonTypes', [])
        if not season_types:
            return None

        # Find regular season
        reg = None
        for st in season_types:
            name = st.get('displayName', '')
            if 'regular' in name.lower():
                reg = st
                break
        if not reg:
            reg = season_types[0]

        # Get all game events from categories
        all_game_stats = []
        categories = reg.get('categories', [])
        for cat in categories:
            events = cat.get('events', [])
            for event in events:
                stats_raw = event.get('stats', [])
                if stats_raw and stats_raw != ['--']:
                    all_game_stats.append(stats_raw)

        if not all_game_stats:
            return None

        # Step 3: Parse each game using the labels
        game_logs = []
        for raw_stats in all_game_stats:
            game = {}
            for i, val in enumerate(raw_stats):
                if i >= len(labels):
                    break
                label = labels[i]
                try:
                    game[label] = float(val)
                except (ValueError, TypeError):
                    # Handle split stats like "8-17" for FG
                    pass
            
            if 'PTS' in game:
                game_logs.append(game)

        if not game_logs:
            return None

        # Step 4: Calculate averages
        n = len(game_logs)
        l5 = min(5, n)
        l10 = min(10, n)

        def avg(key, count=None):
            subset = game_logs[:count] if count else game_logs
            vals = [g[key] for g in subset if key in g]
            return round(sum(vals) / len(vals), 1) if vals else 0

        def std(key):
            vals = [g[key] for g in game_logs if key in g]
            if len(vals) < 3:
                return round(max(avg(key) * 0.25, 1.5), 1)
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

    except Exception as e:
        print(f"  ⚠️  Parse error for {player_name}: {e}", flush=True)
        return None


def debug_one_player(espn_player_id):
    """Debug: dump raw API responses."""
    import json
    print(f"\n=== DEBUG: Player {espn_player_id} ===", flush=True)

    for name, url_template in [("STATS", ESPN_STATS_URL), ("GAMELOG", ESPN_GAMELOG_URL)]:
        try:
            url = url_template.format(player_id=espn_player_id)
            resp = requests.get(url, params={'region': 'us', 'lang': 'en', 'contentorigin': 'espn'}, timeout=10)
            print(f"\n--- {name} (status {resp.status_code}) ---", flush=True)
            if resp.status_code == 200:
                data = resp.json()
                print(f"Top-level keys: {list(data.keys())}", flush=True)
                
                # For GAMELOG: show labels and first game
                if 'labels' in data:
                    print(f"  labels: {data['labels']}", flush=True)
                if 'seasonTypes' in data:
                    for i, st in enumerate(data['seasonTypes']):
                        st_name = st.get('displayName', f'type_{i}')
                        cats = st.get('categories', [])
                        print(f"  seasonTypes[{i}] '{st_name}': {len(cats)} categories", flush=True)
                        for j, cat in enumerate(cats):
                            events = cat.get('events', [])
                            print(f"    cat[{j}]: {len(events)} events", flush=True)
                            if events:
                                first_event = events[0]
                                print(f"      event[0] keys: {list(first_event.keys())}", flush=True)
                                print(f"      event[0] stats: {first_event.get('stats', [])[:5]}...", flush=True)
                
                # For STATS: show categories structure
                if 'categories' in data and 'labels' not in data:
                    for i, cat in enumerate(data['categories']):
                        cat_name = cat.get('name', cat.get('displayName', f'cat_{i}'))
                        cat_labels = cat.get('labels', [])
                        cat_stats = cat.get('statistics', [])
                        print(f"  categories[{i}] '{cat_name}':", flush=True)
                        print(f"    labels: {cat_labels[:8]}...", flush=True)
                        if cat_stats:
                            print(f"    statistics[0] keys: {list(cat_stats[0].keys()) if isinstance(cat_stats[0], dict) else 'not dict'}", flush=True)
                            print(f"    statistics[0]: {str(cat_stats[0])[:120]}", flush=True)
        except Exception as e:
            print(f"  Error: {e}", flush=True)
