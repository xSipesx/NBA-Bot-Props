#!/usr/bin/env python3
"""
NBA Props Agent — Main Pipeline
Cloud-optimized: No nba_api in main pipeline.
"""
import sys
print("🔧 Starting NBA Props Agent...", flush=True)

import argparse
import time
from datetime import datetime

import config
import database as db


def run_daily_pipeline(date=None):
    if date is None:
        date = config.get_today()

    print(f"\n{'='*60}", flush=True)
    print(f"  NBA PROPS AGENT — {date}", flush=True)
    print(f"  Pipeline started at {datetime.now().strftime('%H:%M:%S')}", flush=True)
    print(f"{'='*60}\n", flush=True)

    db.init_db()

    # ── Step 1: Schedule ──
    from ingest.odds import get_schedule_from_odds, get_all_player_props
    games = get_schedule_from_odds()
    if not games:
        print("\n🚫 No games today. Exiting.", flush=True)
        return

    # ── Step 2: Injuries ──
    from ingest.injuries import get_injury_report
    today_teams = set()
    for g in games:
        today_teams.add(g['home'])
        today_teams.add(g['away'])
    injuries = get_injury_report(teams_filter=today_teams)
    db.store_injuries(injuries, date)

    # ── Step 3: Props (PTS + REB + AST) ──
    raw_props = get_all_player_props()
    prop_lines = {}
    for prop in raw_props:
        key = f"{prop['player_name']}_{prop.get('stat', 'PTS')}"
        prop_lines[key] = prop
    db.store_prop_lines(raw_props, date)

    if not raw_props:
        print("\n⚠️  No prop lines available.", flush=True)

    # ── Step 4: Predictions ──
    from model.predict import predict_from_props
    predictions = predict_from_props(raw_props, games, injuries)
    predictions.sort(key=lambda x: -abs(x.get('edge', 0)))
    db.store_predictions(predictions, date)

    bets = [p for p in predictions if p.get('side') in ('OVER', 'UNDER')]
    print(f"\n📊 PREDICTION SUMMARY", flush=True)
    print(f"   Total props analyzed: {len(predictions)}", flush=True)
    print(f"   Actionable bets (edge ≥ 3%): {len(bets)}", flush=True)

    if bets:
        print(f"\n   🔥 TOP PLAYS:", flush=True)
        for i, b in enumerate(bets[:8], 1):
            print(f"   {i}. {b['player_name']:25s} {b['side']:5s} {b.get('line', '?'):5} {b.get('stat', 'PTS'):3s} | "
                  f"Proj: {b['projection']:5.1f} | Edge: +{b['edge']:.1%} | "
                  f"{b.get('confidence', 'N/A'):6s} | {b.get('units', 0):.1f}u", flush=True)

    # ── Step 5: Claude Analysis ──
    from output.claude_analysis import generate_claude_analysis
    print("\n🤖 Sending to Claude for analysis...", flush=True)
    report = generate_claude_analysis(predictions, games, injuries, date)

    # ── Step 6: Deliver ──
    from output.deliver import post_to_discord, send_email, save_report
    save_report(report, predictions)
    post_to_discord(report, predictions)
    send_email(report, predictions)

    # ── Step 7: Log bets ──
    for bet in bets:
        db.store_bet({
            'player_name': bet['player_name'], 'team': bet.get('team', ''),
            'game_id': bet.get('game_id', ''), 'side': bet['side'],
            'line': bet.get('line', 0),
            'odds': bet.get('over_odds' if bet['side'] == 'OVER' else 'under_odds', -110),
            'edge': bet.get('edge', 0), 'confidence': bet.get('confidence'),
            'units': bet.get('units', 0),
            'stat': bet.get('stat', 'PTS'),
        }, date)

    print(f"\n{'='*60}", flush=True)
    print(f"  ✅ PIPELINE COMPLETE — {datetime.now().strftime('%H:%M:%S')}", flush=True)
    print(f"  📋 {len(bets)} bets logged | Report saved & delivered", flush=True)
    print(f"{'='*60}\n", flush=True)
    return predictions


def run_grading(date=None):
    """Grade yesterday's picks and post results to Discord."""
    from datetime import timedelta

    if date is None:
        yesterday = (datetime.strptime(config.get_today(), "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        date = yesterday

    print(f"\n📝 Grading bets for {date}...", flush=True)

    # Fetch actual stats from ESPN box scores (no nba_api needed)
    from ingest.espn_scores import get_player_stats_from_espn
    actual_stats = get_player_stats_from_espn(date)

    if not actual_stats:
        print("  ⚠️  Could not fetch box scores. Skipping grading.", flush=True)
        return

    # Load yesterday's bets from database
    bets = db.get_ungraded_bets(date)
    if not bets:
        print("  No ungraded bets found.", flush=True)
        return

    print(f"  Found {len(bets)} bets to grade", flush=True)

    results = {'wins': 0, 'losses': 0, 'pushes': 0, 'dnps': 0, 'pnl': 0.0}
    graded_lines = []

    for bet in bets:
        player = bet['player_name']
        stat_type = bet.get('stat', 'PTS')
        stat_key = {'PTS': 'points', 'REB': 'rebounds', 'AST': 'assists'}.get(stat_type, 'points')

        actual = actual_stats.get(player, {}).get(stat_key)
        if actual is None:
            db.grade_bet(bet['id'], None, 'DNP', 0.0)
            results['dnps'] += 1
            continue

        line_val = bet['line']
        side = bet['side']
        odds = bet['odds']
        units = bet['units']

        if actual == line_val:
            result, pnl = 'PUSH', 0.0
            results['pushes'] += 1
        elif (side == 'OVER' and actual > line_val) or (side == 'UNDER' and actual < line_val):
            result = 'WIN'
            pnl = units * (100 / abs(odds)) if odds < 0 else units * (odds / 100)
            results['wins'] += 1
        else:
            result, pnl = 'LOSS', -units
            results['losses'] += 1

        results['pnl'] += pnl
        db.grade_bet(bet['id'], actual, result, pnl)
        emoji = "✅" if result == 'WIN' else "❌" if result == 'LOSS' else "➖"
        graded_lines.append(f"{emoji} {player} {stat_type}: {actual:.0f} vs {line_val} {side} → {result} ({pnl:+.1f}u)")
        print(f"  {graded_lines[-1]}", flush=True)

    total_graded = results['wins'] + results['losses'] + results['pushes']
    hit_rate = results['wins'] / total_graded if total_graded > 0 else 0

    summary = (f"📊 **RESULTS {date}**: {results['wins']}W-{results['losses']}L"
               f" | Hit Rate: {hit_rate:.0%} | P&L: {results['pnl']:+.1f}u")
    print(f"\n  {summary}", flush=True)

    # Post results to Discord
    _post_results_to_discord(date, results, graded_lines, summary)
    return results


def _post_results_to_discord(date, results, graded_lines, summary):
    """Post grading results to Discord."""
    import requests

    if not config.DISCORD_WEBHOOK_URL:
        return

    content = f"# 📊 Results — {date}\n\n{summary}\n\n"
    content += "\n".join(graded_lines[:25])  # cap at 25 to stay under Discord limit
    if len(graded_lines) > 25:
        content += f"\n... and {len(graded_lines) - 25} more"

    try:
        requests.post(config.DISCORD_WEBHOOK_URL, json={'content': content[:1900]}, timeout=10)
        print("  ✅ Results posted to Discord", flush=True)
    except Exception as e:
        print(f"  ⚠️  Discord error: {e}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="NBA Props Agent")
    parser.add_argument('--date', type=str)
    parser.add_argument('--grade', action='store_true')
    parser.add_argument('--performance', action='store_true')
    parser.add_argument('--init-db', action='store_true')
    args = parser.parse_args()

    if args.init_db:
        db.init_db()
        return
    if args.grade:
        run_grading(date=args.date)
        return
    if args.performance:
        print("📊 Run `streamlit run dashboard.py` for full performance view")
        return

    run_daily_pipeline(date=args.date)


if __name__ == "__main__":
    main()
