#!/usr/bin/env python3
"""
NBA Props Agent — Main Pipeline v6
Uses ESPN for player stats (cloud-safe), Odds API for props, ESPN for grading.
Grades yesterday + predicts today in one run.
"""
import sys
print("🔧 Starting NBA Props Agent...", flush=True)

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import config
import database as db


BETS_LEDGER = "bets_ledger.json"


def load_ledger():
    """Load the persistent bets ledger from file."""
    if Path(BETS_LEDGER).exists():
        with open(BETS_LEDGER, 'r') as f:
            return json.load(f)
    return {'bets': [], 'results': []}


def save_ledger(ledger):
    """Save the bets ledger to file."""
    with open(BETS_LEDGER, 'w') as f:
        json.dump(ledger, f, indent=2, default=str)


def grade_yesterday(ledger):
    """Grade yesterday's bets using ESPN box scores."""
    today = config.get_today()
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    # Find ungraded bets from yesterday
    ungraded = [b for b in ledger['bets'] if b.get('date') == yesterday and b.get('result') is None]
    if not ungraded:
        print(f"\n📝 No ungraded bets for {yesterday}", flush=True)
        return None

    print(f"\n📝 Grading {len(ungraded)} bets from {yesterday}...", flush=True)

    from ingest.espn_scores import get_player_stats_from_espn
    actual_stats = get_player_stats_from_espn(yesterday)

    if not actual_stats:
        print("  ⚠️  Could not fetch box scores", flush=True)
        return None

    results = {'date': yesterday, 'wins': 0, 'losses': 0, 'pushes': 0, 'pnl': 0.0, 'details': []}

    for bet in ungraded:
        player = bet['player_name']
        stat_type = bet.get('stat', 'PTS')
        stat_key = {'PTS': 'points', 'REB': 'rebounds', 'AST': 'assists'}.get(stat_type, 'points')

        actual = actual_stats.get(player, {}).get(stat_key)
        if actual is None:
            bet['result'] = 'DNP'
            bet['actual'] = None
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

        bet['result'] = result
        bet['actual'] = actual
        bet['pnl'] = round(pnl, 2)
        results['pnl'] += pnl

        emoji = "✅" if result == 'WIN' else "❌" if result == 'LOSS' else "➖"
        detail = f"{emoji} {player} {stat_type}: {actual:.0f} vs {line_val} {side} → {result} ({pnl:+.1f}u)"
        results['details'].append(detail)
        print(f"  {detail}", flush=True)

    total = results['wins'] + results['losses'] + results['pushes']
    hit_rate = results['wins'] / total if total > 0 else 0
    results['hit_rate'] = round(hit_rate, 3)
    results['pnl'] = round(results['pnl'], 2)

    summary = (f"📊 **RESULTS {yesterday}**: {results['wins']}W-{results['losses']}L"
               f" | Hit Rate: {hit_rate:.0%} | P&L: {results['pnl']:+.1f}u")
    print(f"\n  {summary}", flush=True)

    # Post to Discord
    _post_results_to_discord(yesterday, results)

    # Store in ledger
    ledger['results'].append(results)
    return results


def _post_results_to_discord(date, results):
    """Post grading results to Discord."""
    import requests
    if not config.DISCORD_WEBHOOK_URL:
        return

    content = f"# 📊 Results — {date}\n\n"
    content += f"**{results['wins']}W-{results['losses']}L | Hit Rate: {results['hit_rate']:.0%} | P&L: {results['pnl']:+.1f}u**\n\n"
    content += "\n".join(results.get('details', [])[:25])

    # Calculate season totals from ledger
    ledger = load_ledger()
    all_graded = [b for b in ledger['bets'] if b.get('result') in ('WIN', 'LOSS', 'PUSH')]
    total_w = len([b for b in all_graded if b['result'] == 'WIN'])
    total_l = len([b for b in all_graded if b['result'] == 'LOSS'])
    total_pnl = sum(b.get('pnl', 0) for b in all_graded)
    total_games = total_w + total_l
    season_rate = total_w / total_games if total_games > 0 else 0
    content += f"\n\n**Season: {total_w}W-{total_l}L ({season_rate:.0%}) | Total P&L: {total_pnl:+.1f}u**"

    try:
        # Split if needed
        chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
        for chunk in chunks:
            requests.post(config.DISCORD_WEBHOOK_URL, json={'content': chunk}, timeout=10)
        print("  ✅ Results posted to Discord", flush=True)
    except Exception as e:
        print(f"  ⚠️  Discord error: {e}", flush=True)


def run_daily_pipeline(date=None):
    if date is None:
        date = config.get_today()

    print(f"\n{'='*60}", flush=True)
    print(f"  NBA PROPS AGENT v6 — {date}", flush=True)
    print(f"  Pipeline started at {datetime.now().strftime('%H:%M:%S')}", flush=True)
    print(f"{'='*60}\n", flush=True)

    db.init_db()
    ledger = load_ledger()

    # ── Grade yesterday first ──
    grade_yesterday(ledger)

    # ── Step 1: Schedule ──
    from ingest.odds import get_schedule_from_odds, get_all_player_props
    games = get_schedule_from_odds()
    if not games:
        print("\n🚫 No games today.", flush=True)
        save_ledger(ledger)
        return

    # ── Step 2: Player Stats from ESPN ──
    from ingest.espn_stats import get_starters_stats, debug_one_player, _get_team_roster, _get_player_gamelog, ESPN_TEAM_IDS

    # Debug: test ESPN API on first team's first player
    first_team = games[0]['home']
    first_espn_id = ESPN_TEAM_IDS.get(first_team)
    if first_espn_id:
        roster = _get_team_roster(first_espn_id, first_team)
        if roster:
            test_player = roster[0]
            print(f"\n🔍 DEBUG: Testing {test_player['name']} (id: {test_player['espn_id']})", flush=True)
            debug_one_player(test_player['espn_id'])
            
            # Also test the actual parsing function
            result = _get_player_gamelog(test_player['espn_id'], test_player['name'])
            if result:
                print(f"\n✅ PARSE SUCCESS: {test_player['name']}", flush=True)
                print(f"   min_pg={result['min_pg']} pts_avg={result['pts_avg']} reb_avg={result['reb_avg']} ast_avg={result['ast_avg']}", flush=True)
                print(f"   pts_l5={result['pts_l5']} pts_std={result['pts_std']} gp={result['gp']}", flush=True)
            else:
                print(f"\n❌ PARSE FAILED for {test_player['name']}", flush=True)

    player_stats = get_starters_stats(games)

    # ── Step 3: Injuries ──
    from ingest.injuries import get_injury_report
    today_teams = set()
    for g in games:
        today_teams.add(g['home'])
        today_teams.add(g['away'])
    injuries = get_injury_report(teams_filter=today_teams)
    db.store_injuries(injuries, date)

    # ── Step 4: Prop Lines ──
    raw_props = get_all_player_props()
    db.store_prop_lines(raw_props, date)

    if not raw_props:
        print("\n⚠️  No prop lines available.", flush=True)
        save_ledger(ledger)
        return

    # ── Step 5: Predictions (real stats vs lines) ──
    from model.predict import predict_from_props
    predictions = predict_from_props(raw_props, games, injuries, player_stats)
    db.store_predictions(predictions, date)

    bets = [p for p in predictions if p.get('side') in ('OVER', 'UNDER')]
    print(f"\n📊 PREDICTION SUMMARY", flush=True)
    print(f"   Props analyzed: {len(predictions)}", flush=True)
    print(f"   Actionable bets: {len(bets)}", flush=True)

    if bets:
        print(f"\n   🔥 TOP PLAYS:", flush=True)
        for i, b in enumerate(bets[:8], 1):
            print(f"   {i}. {b['player_name']:22s} {b['side']:5s} {b.get('line', '?'):5} {b.get('stat', 'PTS'):3s} | "
                  f"Proj: {b['projection']:5.1f} (ssn:{b.get('season_avg',0):.1f} l5:{b.get('l5_avg',0):.1f}) | "
                  f"Edge: +{b['edge']:.1%} | {b.get('confidence', 'N/A'):6s} | {b.get('units', 0):.1f}u", flush=True)

    # ── Step 6: Claude Analysis ──
    from output.claude_analysis import generate_claude_analysis
    print("\n🤖 Sending to Claude for analysis...", flush=True)
    report = generate_claude_analysis(predictions, games, injuries, date)

    # ── Step 7: Deliver ──
    from output.deliver import post_to_discord, save_report
    save_report(report, predictions)
    post_to_discord(report, predictions)

    # ── Step 8: Log bets to ledger ──
    for bet in bets:
        ledger['bets'].append({
            'date': date,
            'player_name': bet['player_name'],
            'team': bet.get('team', ''),
            'stat': bet.get('stat', 'PTS'),
            'side': bet['side'],
            'line': bet.get('line', 0),
            'odds': bet.get('over_odds' if bet['side'] == 'OVER' else 'under_odds', -110),
            'edge': bet.get('edge', 0),
            'confidence': bet.get('confidence'),
            'units': bet.get('units', 0),
            'projection': bet.get('projection', 0),
            'season_avg': bet.get('season_avg', 0),
            'result': None,
            'actual': None,
            'pnl': None,
        })

    save_ledger(ledger)

    print(f"\n{'='*60}", flush=True)
    print(f"  ✅ PIPELINE COMPLETE — {datetime.now().strftime('%H:%M:%S')}", flush=True)
    print(f"  📋 {len(bets)} bets logged | Report delivered", flush=True)
    print(f"{'='*60}\n", flush=True)
    return predictions


def main():
    parser = argparse.ArgumentParser(description="NBA Props Agent")
    parser.add_argument('--date', type=str)
    parser.add_argument('--grade', action='store_true')
    parser.add_argument('--init-db', action='store_true')
    args = parser.parse_args()

    if args.init_db:
        db.init_db()
        return
    if args.grade:
        ledger = load_ledger()
        grade_yesterday(ledger)
        save_ledger(ledger)
        return

    run_daily_pipeline(date=args.date)


if __name__ == "__main__":
    main()
