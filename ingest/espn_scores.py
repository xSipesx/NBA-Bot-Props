"""
Ingest: ESPN Box Scores — fetches actual player stats for grading.
No nba_api needed. Uses ESPN's public scoreboard + box score pages.
"""

import requests
from datetime import datetime

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_BOXSCORE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"


def get_player_stats_from_espn(date):
    """
    Fetch actual PTS, REB, AST for all players who played on the given date.
    Returns: dict of {player_name: {'points': X, 'rebounds': Y, 'assists': Z}}
    """
    print(f"📦 Fetching box scores from ESPN for {date}...", flush=True)

    # Step 1: Get all game IDs for the date
    formatted = date.replace("-", "")  # ESPN wants YYYYMMDD
    try:
        resp = requests.get(ESPN_SCOREBOARD_URL, params={'dates': formatted}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ❌ Error fetching ESPN scoreboard: {e}", flush=True)
        return {}

    events = data.get('events', [])
    if not events:
        print(f"  ⚠️  No games found on ESPN for {date}", flush=True)
        return {}

    print(f"  📋 Found {len(events)} games on ESPN", flush=True)

    # Step 2: For each game, fetch the box score
    all_stats = {}
    for event in events:
        event_id = event.get('id', '')
        event_name = event.get('shortName', '')

        try:
            box_resp = requests.get(ESPN_BOXSCORE_URL, params={'event': event_id}, timeout=15)
            box_resp.raise_for_status()
            box_data = box_resp.json()
        except Exception as e:
            print(f"  ⚠️  Error fetching box score for {event_name}: {e}", flush=True)
            continue

        # Parse player stats from the box score
        boxscore = box_data.get('boxscore', {})
        players_sections = boxscore.get('players', [])

        game_count = 0
        for team_section in players_sections:
            statistics = team_section.get('statistics', [])
            if not statistics:
                continue

            # Find the main stat category (usually index 0)
            stat_block = statistics[0]
            headers = [h.lower() for h in stat_block.get('labels', [])]
            athletes = stat_block.get('athletes', [])

            # Find column indices
            pts_idx = _find_index(headers, ['pts', 'points'])
            reb_idx = _find_index(headers, ['reb', 'rebounds'])
            ast_idx = _find_index(headers, ['ast', 'assists'])

            for athlete in athletes:
                player_info = athlete.get('athlete', {})
                name = player_info.get('displayName', '')
                if not name:
                    name = player_info.get('shortName', '')

                stats_vals = athlete.get('stats', [])
                if not stats_vals:
                    # DNP
                    continue

                try:
                    pts = float(stats_vals[pts_idx]) if pts_idx is not None and pts_idx < len(stats_vals) else None
                    reb = float(stats_vals[reb_idx]) if reb_idx is not None and reb_idx < len(stats_vals) else None
                    ast = float(stats_vals[ast_idx]) if ast_idx is not None and ast_idx < len(stats_vals) else None

                    # Skip DNP entries (stats might be '-' or empty)
                    if pts is not None:
                        all_stats[name] = {
                            'points': pts,
                            'rebounds': reb,
                            'assists': ast,
                        }
                        game_count += 1
                except (ValueError, IndexError):
                    continue

        print(f"  ✅ {event_name}: {game_count} players", flush=True)

    print(f"  📦 Total: {len(all_stats)} players with stats", flush=True)
    return all_stats


def _find_index(headers, candidates):
    """Find the index of a header matching any candidate."""
    for candidate in candidates:
        if candidate in headers:
            return headers.index(candidate)
    return None
