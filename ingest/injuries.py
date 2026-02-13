"""
Ingest: Injury Reports
Scrapes ESPN's NBA injury page for current player statuses.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime

import config

ESPN_INJURIES_URL = "https://www.espn.com/nba/injuries"

# ESPN team name to standard abbreviation mapping
ESPN_TEAM_MAP = {
    'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BKN',
    'Charlotte Hornets': 'CHA', 'Chicago Bulls': 'CHI', 'Cleveland Cavaliers': 'CLE',
    'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN', 'Detroit Pistons': 'DET',
    'Golden State Warriors': 'GSW', 'Houston Rockets': 'HOU', 'Indiana Pacers': 'IND',
    'LA Clippers': 'LAC', 'Los Angeles Lakers': 'LAL', 'Memphis Grizzlies': 'MEM',
    'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN',
    'New Orleans Pelicans': 'NOP', 'New York Knicks': 'NYK',
    'Oklahoma City Thunder': 'OKC', 'Orlando Magic': 'ORL',
    'Philadelphia 76ers': 'PHI', 'Phoenix Suns': 'PHX',
    'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC',
    'San Antonio Spurs': 'SAS', 'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTA',
    'Washington Wizards': 'WAS',
}


def get_injury_report(teams_filter=None):
    """
    Scrape ESPN injury report.

    Args:
        teams_filter: Optional set of team abbreviations to filter for.
                      If None, returns all injuries.

    Returns:
        List of dicts: [{'player_name', 'team', 'status', 'reason'}, ...]
    """
    print("🏥 Fetching injury report from ESPN...")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    try:
        resp = requests.get(ESPN_INJURIES_URL, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ❌ Error fetching ESPN injuries: {e}")
        return _fallback_injury_report(teams_filter)

    soup = BeautifulSoup(resp.text, 'lxml')
    injuries = []
    current_team = None

    # ESPN structures injuries by team sections
    # The structure varies, so we try multiple parsing strategies
    for section in soup.find_all(['div', 'section'], class_=lambda x: x and 'Wrapper' in str(x)):
        # Try to find team name
        team_header = section.find(['h2', 'h3', 'span'], class_=lambda x: x and ('Team' in str(x) or 'title' in str(x)))
        if team_header:
            team_name = team_header.get_text(strip=True)
            current_team = ESPN_TEAM_MAP.get(team_name, team_name)

        # Find player rows
        for row in section.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 2:
                player_name = cells[0].get_text(strip=True)
                status_text = cells[1].get_text(strip=True) if len(cells) > 1 else ''
                reason = cells[2].get_text(strip=True) if len(cells) > 2 else ''

                # Normalize status
                status = _normalize_status(status_text)

                if player_name and status and not player_name.startswith('NAME'):
                    injury = {
                        'player_name': player_name,
                        'team': current_team or 'UNK',
                        'status': status,
                        'reason': reason,
                    }

                    if teams_filter is None or injury['team'] in teams_filter:
                        injuries.append(injury)

    # Fallback: also try table-based parsing
    if not injuries:
        injuries = _parse_table_format(soup, teams_filter)

    print(f"  ✅ Found {len(injuries)} injury entries")

    # Print summary by status
    out = [i for i in injuries if i['status'] == 'OUT']
    questionable = [i for i in injuries if i['status'] == 'QUESTIONABLE']
    if out:
        print(f"  🔴 OUT ({len(out)}): {', '.join(i['player_name'] for i in out[:10])}")
    if questionable:
        print(f"  🟡 QUESTIONABLE ({len(questionable)}): {', '.join(i['player_name'] for i in questionable[:10])}")

    return injuries


def _parse_table_format(soup, teams_filter):
    """Alternative parsing for table-based ESPN layout."""
    injuries = []
    tables = soup.find_all('table')

    for table in tables:
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all(['td', 'th'])
            if len(cells) >= 3:
                name = cells[0].get_text(strip=True)
                status_text = ''
                reason = ''

                for cell in cells[1:]:
                    text = cell.get_text(strip=True)
                    if text.upper() in ('OUT', 'QUESTIONABLE', 'DOUBTFUL', 'PROBABLE', 'O', 'Q', 'D', 'P'):
                        status_text = text
                    elif not status_text:
                        status_text = text
                    else:
                        reason = text

                status = _normalize_status(status_text)
                if name and status and not name.upper().startswith('NAME'):
                    injuries.append({
                        'player_name': name,
                        'team': 'UNK',
                        'status': status,
                        'reason': reason,
                    })

    return injuries


def _normalize_status(status_text):
    """Normalize injury status strings."""
    s = status_text.upper().strip()
    if s in ('O', 'OUT'):
        return 'OUT'
    elif s in ('Q', 'QUESTIONABLE', 'GTD'):
        return 'QUESTIONABLE'
    elif s in ('D', 'DOUBTFUL'):
        return 'DOUBTFUL'
    elif s in ('P', 'PROBABLE'):
        return 'PROBABLE'
    elif 'OUT' in s:
        return 'OUT'
    elif 'QUESTION' in s:
        return 'QUESTIONABLE'
    elif 'DOUBT' in s:
        return 'DOUBTFUL'
    elif 'PROB' in s:
        return 'PROBABLE'
    return s


def _fallback_injury_report(teams_filter):
    """
    If ESPN scrape fails, try a simpler approach via the NBA official injury report API.
    """
    print("  🔄 Trying fallback injury source...")

    try:
        from nba_api.stats.endpoints import PlayerIndex
        # This doesn't directly give injuries, but we can check roster status
        # For now, return empty and let the user know
        print("  ⚠️  ESPN scrape failed. Injuries may be incomplete.")
        print("     Consider adding FantasyData or sportsdata.io API for reliable injury data.")
        return []
    except Exception:
        return []


def get_team_injuries(team_abbrev, injuries):
    """Filter injuries for a specific team."""
    return [i for i in injuries if i['team'] == team_abbrev]


def get_out_players(team_abbrev, injuries):
    """Get confirmed OUT players for a team."""
    return [i for i in injuries if i['team'] == team_abbrev and i['status'] == 'OUT']


def estimate_usage_redistribution(out_players, team_players):
    """
    Given a list of OUT players and the active roster, estimate how usage/scoring
    gets redistributed.

    Returns:
        Dict mapping active player names to estimated PPG bump.
    """
    if not out_players or not team_players:
        return {}

    # Total PPG lost from OUT players
    total_lost_ppg = sum(p.get('season_ppg', 0) for p in out_players)

    if total_lost_ppg == 0:
        return {}

    # Distribute proportionally by usage/minutes among remaining players
    active = [p for p in team_players if p['player_name'] not in {o['player_name'] for o in out_players}]
    total_remaining_ppg = sum(p.get('season_ppg', 0) for p in active)

    if total_remaining_ppg == 0:
        return {}

    bumps = {}
    for p in active:
        share = p['season_ppg'] / total_remaining_ppg
        bump = total_lost_ppg * share * config.USAGE_REDISTRIBUTION_FACTOR
        bumps[p['player_name']] = round(bump, 1)

    return bumps


if __name__ == "__main__":
    injuries = get_injury_report()
    for i in injuries[:20]:
        print(f"  {i['status']:15s} {i['player_name']:25s} ({i['team']})")
