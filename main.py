#!/usr/bin/env python3
"""
NBA Props Agent — Main Pipeline Orchestrator
Cloud-optimized: NO nba_api dependency in main pipeline.
Uses Odds API for schedule + props, ESPN for injuries, Claude for analysis.
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

    # ── Step 1: Schedule from Odds API (instant, no nba_api) ──
    from ingest.odds import get_schedule_from_odds, get_player_points_props
    games = get_schedule_from_odds()
    if not games:
        print("\n🚫 No games today. Exiting.", flush=True)
        return

    # ── Step 2: Injuries from ESPN (instant, no nba_api) ──
    from ingest.injuries import get_injury_report, get_out_players, estimate_usage_redistribution
    today_teams = set()
    for g in games:
        today_teams.add(g['home'])
        today_teams.add(g['away'])
    injuries = get_injury_report(teams_filter=today_teams)
    db.store_injuries(injuries, date)

    # ── Step 3: Prop Lines from Odds API (instant, no nba_api) ──
    raw_props = get_player_points_props()
    prop_lines = {}
    for prop in raw_props:
        prop_lines[prop['player_name']] = prop
    db.store_prop_lines(raw_props, date)

    if not raw_props:
        print("\n⚠️  No prop lines available. Generating report without predictions.", flush=True)

    # ── Step 4: Build predictions from prop lines ──
    # The sportsbook line IS the market baseline — we adjust from there
    from model.predict import predict_from_props
    predictions = predict_from_props(raw_props, games, injuries)
    predictions.sort(key=lambda x: -abs(x.get('edge', 0)))
    db.store_predictions(predictions, date)

    bets = [p for p in predictions if p.get('side') in ('OVER', 'UNDER')]
    print(f"\n📊 PREDICTION SUMMARY", flush=True)
    print(f"   Total players with props: {len(predictions)}", flush=True)
    print(f"   Actionable bets (edge ≥ 3%): {len(bets)}", flush=True)

    if bets:
        print(f"\n   🔥 TOP PLAYS:", flush=True)
        for i, b in enumerate(bets[:5], 1):
            print(f"   {i}. {b['player_name']:25s} {b['side']:5s} {b.get('line', '?'):5} pts | "
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
        }, date)

    print(f"\n{'='*60}", flush=True)
    print(f"  ✅ PIPELINE COMPLETE — {datetime.now().strftime('%H:%M:%S')}", flush=True)
    print(f"  📋 {len(bets)} bets logged | Report saved & delivered", flush=True)
    print(f"{'='*60}\n", flush=True)
    return predictions


def main():
    parser = argparse.ArgumentParser(description="NBA Props Agent")
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD)')
    parser.add_argument('--grade', action='store_true', help='Grade bets')
    parser.add_argument('--performance', action='store_true', help='Show performance')
    parser.add_argument('--init-db', action='store_true', help='Init database only')

    args = parser.parse_args()

    if args.init_db:
        db.init_db()
        return

    if args.performance:
        from tracking.grader import get_season_performance
        perf = get_season_performance()
        print(f"\n📊 SEASON: {perf}")
        return

    if args.grade:
        from tracking.grader import grade_date, grade_yesterday
        if args.date:
            grade_date(args.date)
        else:
            grade_yesterday()
        return

    run_daily_pipeline(date=args.date)


if __name__ == "__main__":
    main()
