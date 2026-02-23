"""
Ingest: Sportsbook Odds — fetches points, rebounds, assists props.
"""

import requests
from datetime import datetime, timedelta
import config

ODDS_TEAM_MAP = {
    'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BKN',
    'Charlotte Hornets': 'CHA', 'Chicago Bulls': 'CHI', 'Cleveland Cavaliers': 'CLE',
    'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN', 'Detroit Pistons': 'DET',
    'Golden State Warriors': 'GSW', 'Houston Rockets': 'HOU', 'Indiana Pacers': 'IND',
    'LA Clippers': 'LAC', 'Los Angeles Clippers': 'LAC',
    'Los Angeles Lakers': 'LAL', 'Memphis Grizzlies': 'MEM',
    'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN',
    'New Orleans Pelicans': 'NOP', 'New York Knicks': 'NYK',
    'Oklahoma City Thunder': 'OKC', 'Orlando Magic': 'ORL',
    'Philadelphia 76ers': 'PHI', 'Phoenix Suns': 'PHX',
    'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC',
    'San Antonio Spurs': 'SAS', 'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTA',
    'Washington Wizards': 'WAS',
}

TEAM_IDS = {
    'ATL': 1610612737, 'BOS': 1610612738, 'BKN': 1610612751, 'CHA': 1610612766,
    'CHI': 1610612741, 'CLE': 1610612739, 'DAL': 1610612742, 'DEN': 1610612743,
    'DET': 1610612765, 'GSW': 1610612744, 'HOU': 1610612745, 'IND': 1610612754,
    'LAC': 1610612746, 'LAL': 1610612747, 'MEM': 1610612763, 'MIA': 1610612748,
    'MIL': 1610612749, 'MIN': 1610612750, 'NOP': 1610612740, 'NYK': 1610612752,
    'OKC': 1610612760, 'ORL': 1610612753, 'PHI': 1610612755, 'PHX': 1610612756,
    'POR': 1610612757, 'SAC': 1610612758, 'SAS': 1610612759, 'TOR': 1610612761,
    'UTA': 1610612762, 'WAS': 1610612764,
}

# Map Odds API market keys to readable names
MARKET_LABELS = {
    'player_points': 'PTS',
    'player_rebounds': 'REB',
    'player_assists': 'AST',
}


def _get_todays_events():
    if not config.ODDS_API_KEY:
        return [], []

    events_url = f"{config.ODDS_API_BASE}/sports/{config.ODDS_SPORT}/events"
    try:
        resp = requests.get(events_url, params={
            'apiKey': config.ODDS_API_KEY, 'dateFormat': 'iso',
        }, timeout=15)
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        print(f"  ❌ Error fetching events: {e}", flush=True)
        return [], []

    today = config.get_today()
    tomorrow = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    today_events = [
        e for e in events
        if e.get('commence_time', '')[:10] in (today, tomorrow)
    ]
    if not today_events:
        today_events = [e for e in events if e.get('commence_time', '') >= today][:12]

    return events, today_events


def get_schedule_from_odds():
    if not config.ODDS_API_KEY:
        print("  ❌ ODDS_API_KEY not set.", flush=True)
        return []

    print("📅 Fetching schedule from Odds API...", flush=True)
    _, today_events = _get_todays_events()
    if not today_events:
        print("  ⚠️  No events found", flush=True)
        return []

    games = []
    seen = set()
    for event in today_events:
        home_full = event.get('home_team', '')
        away_full = event.get('away_team', '')
        home = ODDS_TEAM_MAP.get(home_full, home_full)
        away = ODDS_TEAM_MAP.get(away_full, away_full)
        key = f"{away}@{home}"
        if key in seen:
            continue
        seen.add(key)
        games.append({
            'game_id': event.get('id', f"{away}_{home}"),
            'home': home, 'away': away,
            'home_id': TEAM_IDS.get(home), 'away_id': TEAM_IDS.get(away),
            'start_time': event.get('commence_time', ''), 'status': 'scheduled',
        })

    print(f"  ✅ Found {len(games)} games", flush=True)
    for g in games:
        print(f"     {g['away']} @ {g['home']}", flush=True)
    return games


def get_all_player_props():
    """Fetch points, rebounds, and assists props for today's games."""
    if not config.ODDS_API_KEY:
        print("  ❌ ODDS_API_KEY not set.", flush=True)
        return []

    print("💰 Fetching player props (PTS, REB, AST)...", flush=True)
    _, today_events = _get_todays_events()
    if not today_events:
        print("  ⚠️  No events found", flush=True)
        return []

    print(f"  📋 Found {len(today_events)} events", flush=True)
    all_props = []

    for event in today_events:
        event_id = event['id']
        home = event.get('home_team', '')
        away = event.get('away_team', '')
        home_abbrev = ODDS_TEAM_MAP.get(home, home)
        away_abbrev = ODDS_TEAM_MAP.get(away, away)

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
            print(f"  ⚠️  Error fetching props for {away_abbrev} @ {home_abbrev}: {e}", flush=True)
            continue

        game_props = 0
        for bk in data.get('bookmakers', []):
            bk_name = bk.get('key', '')
            for market in bk.get('markets', []):
                market_key = market.get('key', '')
                if market_key not in MARKET_LABELS:
                    continue
                market_label = MARKET_LABELS[market_key]

                player_lines = {}
                for outcome in market.get('outcomes', []):
                    player = outcome.get('description', '')
                    side = outcome.get('name', '')
                    line_val = outcome.get('point', 0)
                    odds = outcome.get('price', -110)

                    if player not in player_lines:
                        player_lines[player] = {'player_name': player, 'line': line_val, 'market': market_key, 'stat': market_label}
                    if side == 'Over':
                        player_lines[player]['over_odds'] = odds
                        player_lines[player]['line'] = line_val
                    elif side == 'Under':
                        player_lines[player]['under_odds'] = odds

                for pname, pdata in player_lines.items():
                    if 'over_odds' in pdata and 'under_odds' in pdata:
                        all_props.append({
                            'player_name': pdata['player_name'],
                            'team': None,
                            'line': pdata['line'],
                            'over_odds': pdata['over_odds'],
                            'under_odds': pdata['under_odds'],
                            'bookmaker': bk_name,
                            'game': f"{away} @ {home}",
                            'market': pdata['market'],
                            'stat': pdata['stat'],
                        })
                        game_props += 1

        print(f"  ✅ {away_abbrev} @ {home_abbrev}: {game_props} prop lines", flush=True)

    deduped = _deduplicate_props(all_props)

    # Count by market
    pts_count = len([p for p in deduped if p['stat'] == 'PTS'])
    reb_count = len([p for p in deduped if p['stat'] == 'REB'])
    ast_count = len([p for p in deduped if p['stat'] == 'AST'])
    print(f"  💰 Total unique lines: {len(deduped)} ({pts_count} PTS, {reb_count} REB, {ast_count} AST)", flush=True)
    return deduped


def _deduplicate_props(props):
    """Keep one line per player+market, preferring FanDuel > DraftKings > BetMGM."""
    priority = {'fanduel': 1, 'draftkings': 2, 'betmgm': 3}
    best = {}
    for p in props:
        key = f"{p['player_name']}_{p['market']}"
        bk_priority = priority.get(p['bookmaker'], 99)
        if key not in best or bk_priority < priority.get(best[key]['bookmaker'], 99):
            best[key] = p
    return list(best.values())


def check_api_usage():
    if not config.ODDS_API_KEY:
        return None
    resp = requests.get(f"{config.ODDS_API_BASE}/sports", params={'apiKey': config.ODDS_API_KEY}, timeout=10)
    remaining = resp.headers.get('x-requests-remaining', '?')
    used = resp.headers.get('x-requests-used', '?')
    print(f"  📊 Odds API: {used} used / {remaining} remaining", flush=True)
    return {'used': used, 'remaining': remaining}
