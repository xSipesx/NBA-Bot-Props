"""
Tracking: Bet Grader — lazy nba_api imports.
"""

import time
from datetime import datetime, timedelta

import config
import database as db


def grade_yesterday():
    """Grade all bets from yesterday's games."""
    yesterday = (datetime.strptime(config.get_today(), "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    return grade_date(yesterday)


def grade_date(date):
    """Grade all bets for a specific date."""
    print(f"\n📝 Grading bets for {date}...")
    bets = db.get_ungraded_bets(date)
    if not bets:
        print("  No ungraded bets found.")
        return {'total': 0}

    print(f"  Found {len(bets)} ungraded bets")
    actual_points = _get_actual_points(date)

    results = {'total': len(bets), 'wins': 0, 'losses': 0, 'pushes': 0, 'dnps': 0, 'total_pnl': 0.0}
    for bet in bets:
        player = bet['player_name']
        pts = actual_points.get(player)
        if pts is None:
            db.grade_bet(bet['id'], None, 'DNP', 0.0)
            results['dnps'] += 1
            continue

        line = bet['line']
        side = bet['side']
        odds = bet['odds']
        units = bet['units']

        if pts == line:
            result, pnl = 'PUSH', 0.0
            results['pushes'] += 1
        elif (side == 'OVER' and pts > line) or (side == 'UNDER' and pts < line):
            result = 'WIN'
            pnl = units * (100 / abs(odds)) if odds < 0 else units * (odds / 100)
            results['wins'] += 1
        else:
            result, pnl = 'LOSS', -units
            results['losses'] += 1

        results['total_pnl'] += pnl
        db.grade_bet(bet['id'], pts, result, pnl)
        emoji = "✅" if result == 'WIN' else "❌" if result == 'LOSS' else "➖"
        print(f"  {emoji} {player}: {pts:.0f} pts vs {line} ({side}) → {result} ({pnl:+.1f}u)")

    total_graded = results['wins'] + results['losses'] + results['pushes']
    hit_rate = results['wins'] / total_graded if total_graded > 0 else 0
    print(f"\n  📊 RESULTS: {results['wins']}W - {results['losses']}L | Hit Rate: {hit_rate:.1%} | P&L: {results['total_pnl']:+.1f}u")
    return results


def _get_actual_points(date):
    """Pull actual point totals from box scores."""
    from nba_api.stats.endpoints import ScoreboardV2, BoxScoreTraditionalV3
    from ingest.nba_helper import call_nba_api

    parts = date.split("-")
    api_date = f"{parts[1]}/{parts[2]}/{parts[0]}"
    actual_points = {}

    try:
        scoreboard = call_nba_api(ScoreboardV2, game_date=api_date, league_id="00")
        games_header = scoreboard.game_header.get_data_frame()
        if games_header.empty:
            return actual_points

        for _, row in games_header.iterrows():
            game_id = row['GAME_ID']
            try:
                box = call_nba_api(BoxScoreTraditionalV3, game_id=game_id)
                dfs = box.get_data_frames()
                if dfs:
                    for _, prow in dfs[0].iterrows():
                        name = prow.get('PLAYER_NAME', prow.get('playerName', ''))
                        pts = prow.get('PTS', prow.get('points', None))
                        if name and pts is not None:
                            actual_points[name] = float(pts)
            except Exception as e:
                print(f"  ⚠️  Error fetching box score for {game_id}: {e}")
    except Exception as e:
        print(f"  ❌ Error fetching scoreboard for {date}: {e}")

    print(f"  📦 Loaded actual points for {len(actual_points)} players")
    return actual_points


def get_season_performance():
    return db.get_performance_summary(days=365)

def get_recent_performance(days=7):
    return db.get_performance_summary(days=days)
