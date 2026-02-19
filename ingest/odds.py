"""
Ingest: Sportsbook Odds
Pulls player points prop lines from The Odds API.
Supports FanDuel, DraftKings, BetMGM and others.

Requires: ODDS_API_KEY environment variable.
Sign up free: https://the-odds-api.com
"""

import requests
from datetime import datetime

import config


def get_player_points_props(event_ids=None):
    """
    Fetch player points prop lines for today's NBA games.

    The Odds API returns props grouped by game (event).

    Args:
        event_ids: Optional list of event IDs to filter. If None, fetches all today's games.

    Returns:
        List of dicts: [{'player_name', 'team', 'line', 'over_odds', 'under_odds', 'bookmaker'}, ...]
    """
    if not config.ODDS_API_KEY:
        print("  ❌ ODDS_API_KEY not set. Skipping odds fetch.")
        print("     Sign up free at https://the-odds-api.com")
        return []

    print("💰 Fetching player points props...")

    # Step 1: Get today's events (games)
    events_url = f"{config.ODDS_API_BASE}/sports/{config.ODDS_SPORT}/events"
    try:
        resp = requests.get(events_url, params={
            'apiKey': config.ODDS_API_KEY,
            'dateFormat': 'iso',
        }, timeout=15)
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        print(f"  ❌ Error fetching events: {e}")
        return []

    # Filter to today's games
    # NBA games at 7+ PM ET are dated the NEXT day in UTC (e.g. 7:30 PM ET = 12:30 AM UTC+1)
    # So we need to match both today ET and tomorrow UTC
    today = config.get_today()
    from datetime import datetime, timedelta
    tomorrow = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    today_events = [
        e for e in events
        if e.get('commence_time', '')[:10] in (today, tomorrow)
    ]

    if not today_events:
        # Fallback: take the next upcoming events
        today_events = [e for e in events if e.get('commence_time', '') >= today][:10]

    print(f"  📋 Found {len(today_events)} events for today")

    # Step 2: Fetch player props for each event
    all_props = []

    for event in today_events:
        event_id = event['id']
        home = event.get('home_team', '')
        away = event.get('away_team', '')

        props_url = f"{config.ODDS_API_BASE}/sports/{config.ODDS_SPORT}/events/{event_id}/odds"

        try:
            resp = requests.get(props_url, params={
                'apiKey': config.ODDS_API_KEY,
                'regions': config.ODDS_REGIONS,
                'markets': config.ODDS_MARKETS,
                'oddsFormat': 'american',
                'bookmakers': config.ODDS_BOOKMAKERS,
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ⚠️  Error fetching props for {away} @ {home}: {e}")
            continue

        # Parse bookmaker data
        bookmakers = data.get('bookmakers', [])
        for bk in bookmakers:
            bk_name = bk.get('key', '')
            markets = bk.get('markets', [])

            for market in markets:
                if market.get('key') != 'player_points':
                    continue

                outcomes = market.get('outcomes', [])
                # Group outcomes by player (Over/Under pairs)
                player_lines = {}

                for outcome in outcomes:
                    player = outcome.get('description', '')
                    side = outcome.get('name', '')  # 'Over' or 'Under'
                    line = outcome.get('point', 0)
                    odds = outcome.get('price', -110)

                    if player not in player_lines:
                        player_lines[player] = {'player_name': player, 'line': line}

                    if side == 'Over':
                        player_lines[player]['over_odds'] = odds
                        player_lines[player]['line'] = line
                    elif side == 'Under':
                        player_lines[player]['under_odds'] = odds

                for pname, pdata in player_lines.items():
                    if 'over_odds' in pdata and 'under_odds' in pdata:
                        all_props.append({
                            'player_name': pdata['player_name'],
                            'team': _guess_team(pdata['player_name'], home, away),
                            'line': pdata['line'],
                            'over_odds': pdata['over_odds'],
                            'under_odds': pdata['under_odds'],
                            'bookmaker': bk_name,
                            'game': f"{away} @ {home}",
                        })

        print(f"  ✅ {away} @ {home}: {len([p for p in all_props if p['game'] == f'{away} @ {home}'])} player lines")

    # Deduplicate: prefer FanDuel > DraftKings > BetMGM
    deduped = _deduplicate_props(all_props)

    print(f"  💰 Total unique player lines: {len(deduped)}")
    for p in sorted(deduped, key=lambda x: x['line'], reverse=True)[:10]:
        print(f"     {p['player_name']:25s} {p['line']:5.1f} pts (O:{p['over_odds']:+d} / U:{p['under_odds']:+d}) [{p['bookmaker']}]")

    return deduped


def _is_tonight(commence_time_str, today_str):
    """Check if a UTC time falls in tonight's window (ET evening)."""
    try:
        ct = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
        # Games tonight in ET are roughly today 23:00 UTC to tomorrow 06:00 UTC
        today = datetime.strptime(today_str, "%Y-%m-%d")
        from datetime import timedelta
        window_start = today.replace(hour=22, minute=0)
        window_end = today.replace(hour=23, minute=59) + timedelta(hours=8)
        ct_naive = ct.replace(tzinfo=None)
        return window_start <= ct_naive <= window_end
    except Exception:
        return False


def _guess_team(player_name, home_team, away_team):
    """Placeholder — the API doesn't always give team. We'll match in the pipeline."""
    return None


def _deduplicate_props(props):
    """
    Keep one line per player, preferring bookmakers in priority order.
    """
    priority = {'fanduel': 1, 'draftkings': 2, 'betmgm': 3}
    best = {}

    for p in props:
        name = p['player_name']
        bk_priority = priority.get(p['bookmaker'], 99)

        if name not in best or bk_priority < priority.get(best[name]['bookmaker'], 99):
            best[name] = p

    return list(best.values())


def check_api_usage():
    """Check remaining API quota."""
    if not config.ODDS_API_KEY:
        return None

    url = f"{config.ODDS_API_BASE}/sports"
    resp = requests.get(url, params={'apiKey': config.ODDS_API_KEY}, timeout=10)

    remaining = resp.headers.get('x-requests-remaining', '?')
    used = resp.headers.get('x-requests-used', '?')
    print(f"  📊 Odds API usage: {used} used / {remaining} remaining")
    return {'used': used, 'remaining': remaining}


if __name__ == "__main__":
    check_api_usage()
    props = get_player_points_props()
