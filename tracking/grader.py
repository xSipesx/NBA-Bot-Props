"""
Tracking: Bet Grader
Runs the morning after games to pull actual box scores and grade all bets.
Calculates P&L and updates the bet log.
"""

import time
from datetime import datetime, timedelta
from nba_api.stats.endpoints import BoxScoreTraditionalV3, ScoreboardV2
from nba_api.stats.static import players as nba_players

import config
import database as db


def grade_yesterday():
    """Grade all bets from yesterday's games."""
    yesterday = (datetime.strptime(config.get_today(), "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    return grade_date(yesterday)


def grade_date(date):
    """
    Grade all bets for a specific date.

    1. Get ungraded bets for the date
    2. Pull actual box scores
    3. Grade each bet (WIN/LOSS/PUSH/DNP)
    4. Calculate P&L
    5. Update database

    Returns:
        Dict summary of grading results
    """
    print(f"\n📝 Grading bets for {date}...")

    # Get ungraded bets
    bets = db.get_ungraded_bets(date)
    if not bets:
        print("  No ungraded bets found.")
        return {'total': 0}

    print(f"  Found {len(bets)} ungraded bets")

    # Get actual points for all players from box scores
    actual_points = _get_actual_points(date)

    # Grade each bet
    results = {'total': len(bets), 'wins': 0, 'losses': 0, 'pushes': 0, 'dnps': 0, 'total_pnl': 0.0}

    for bet in bets:
        player = bet['player_name']
        pts = actual_points.get(player)

        if pts is None:
            # Player didn't play (DNP, injury, etc.)
            db.grade_bet(bet['id'], None, 'DNP', 0.0)
            results['dnps'] += 1
            print(f"  ⏭️  {player}: DNP")
            continue

        # Determine result
        line = bet['line']
        side = bet['side']
        odds = bet['odds']
        units = bet['units']

        if pts == line:
            result = 'PUSH'
            pnl = 0.0
            results['pushes'] += 1
        elif side == 'OVER' and pts > line:
            result = 'WIN'
            pnl = _calculate_win_pnl(odds, units)
            results['wins'] += 1
        elif side == 'UNDER' and pts < line:
            result = 'WIN'
            pnl = _calculate_win_pnl(odds, units)
            results['wins'] += 1
        else:
            result = 'LOSS'
            pnl = -units
            results['losses'] += 1

        results['total_pnl'] += pnl
        db.grade_bet(bet['id'], pts, result, pnl)

        emoji = "✅" if result == 'WIN' else "❌" if result == 'LOSS' else "➖"
        print(f"  {emoji} {player}: {pts:.0f} pts vs {line} ({side}) → {result} ({pnl:+.1f}u)")

    # Print summary
    total_graded = results['wins'] + results['losses'] + results['pushes']
    hit_rate = results['wins'] / total_graded if total_graded > 0 else 0

    print(f"\n  📊 RESULTS: {results['wins']}W - {results['losses']}L - {results['pushes']}P ({results['dnps']} DNP)")
    print(f"  📊 Hit Rate: {hit_rate:.1%}")
    print(f"  📊 P&L: {results['total_pnl']:+.1f} units")

    return results


def _get_actual_points(date):
    """
    Pull actual point totals for all players from box scores on a given date.

    Returns:
        Dict mapping player name to points scored.
    """
    parts = date.split("-")
    api_date = f"{parts[1]}/{parts[2]}/{parts[0]}"

    actual_points = {}

    try:
        scoreboard = ScoreboardV2(game_date=api_date, league_id="00", timeout=config.NBA_API_TIMEOUT)
        time.sleep(1)
        games_header = scoreboard.game_header.get_data_frame()

        if games_header.empty:
            print(f"  ⚠️  No games found for {date}")
            return actual_points

        for _, row in games_header.iterrows():
            game_id = row['GAME_ID']

            try:
                box = BoxScoreTraditionalV3(game_id=game_id, timeout=config.NBA_API_TIMEOUT)
                time.sleep(0.8)

                # Get player stats from the box score
                dfs = box.get_data_frames()
                if dfs:
                    player_df = dfs[0]  # Player stats
                    for _, prow in player_df.iterrows():
                        name = prow.get('PLAYER_NAME', prow.get('playerName', ''))
                        pts = prow.get('PTS', prow.get('points', None))

                        if name and pts is not None:
                            actual_points[name] = float(pts)

            except Exception as e:
                print(f"  ⚠️  Error fetching box score for game {game_id}: {e}")
                continue

    except Exception as e:
        print(f"  ❌ Error fetching scoreboard for {date}: {e}")

    print(f"  📦 Loaded actual points for {len(actual_points)} players")
    return actual_points


def _calculate_win_pnl(american_odds, units):
    """Calculate profit from a winning bet."""
    if american_odds < 0:
        return units * (100 / abs(american_odds))
    else:
        return units * (american_odds / 100)


def get_season_performance():
    """Get full season performance summary."""
    return db.get_performance_summary(days=365)


def get_recent_performance(days=7):
    """Get performance for the last N days."""
    return db.get_performance_summary(days=days)


if __name__ == "__main__":
    grade_yesterday()
