#!/usr/bin/env python3
"""
NBA Props Agent — Main Pipeline Orchestrator

Usage:
    python main.py                    # Run today's slate
    python main.py --date 2026-02-12  # Run a specific date
    python main.py --grade            # Grade yesterday's bets
    python main.py --grade --date 2026-02-11  # Grade a specific date
    python main.py --performance      # Show season performance
"""

import argparse
import sys
import time
from datetime import datetime

import config
import database as db
from ingest.schedule import get_todays_games, get_b2b_teams
from ingest.player_stats import get_all_player_stats
from ingest.odds import get_player_points_props, check_api_usage
from ingest.injuries import get_injury_report, get_out_players, estimate_usage_redistribution
from ingest.team_context import get_team_context, get_projected_game_pace
from model.predict import run_predictions
from output.claude_analysis import generate_claude_analysis
from output.deliver import post_to_discord, send_email, save_report
from tracking.grader import grade_date, grade_yesterday, get_season_performance


def run_daily_pipeline(date=None):
    """
    Full daily pipeline:
    1. Pull schedule
    2. Pull player stats
    3. Pull prop lines
    4. Pull injuries
    5. Pull team context
    6. Build game contexts
    7. Run predictions
    8. Send to Claude for analysis
    9. Deliver report
    10. Log bets
    """
    if date is None:
        date = config.get_today()

    print(f"\n{'='*60}")
    print(f"  NBA PROPS AGENT — {date}")
    print(f"  Pipeline started at {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")

    # Initialize database
    db.init_db()

    # ── Step 1: Schedule ──
    games = get_todays_games(date)
    if not games:
        print("\n🚫 No games today. Exiting.")
        return

    # Detect back-to-backs
    b2b_teams = get_b2b_teams(games, date)

    # ── Step 2: Team Context ──
    team_context = get_team_context()
    time.sleep(1)

    # ── Step 3: Injuries ──
    # Filter to teams playing today
    today_teams = set()
    for g in games:
        today_teams.add(g['home'])
        today_teams.add(g['away'])
    injuries = get_injury_report(teams_filter=today_teams)
    db.store_injuries(injuries, date)

    # ── Step 4: Player Stats ──
    all_players = get_all_player_stats(games)
    db.store_player_stats(all_players, date)

    # ── Step 5: Prop Lines ──
    raw_props = get_player_points_props()

    # Match prop lines to players by name
    prop_lines = {}
    for prop in raw_props:
        prop_lines[prop['player_name']] = prop
    db.store_prop_lines(raw_props, date)

    # ── Step 6: Build Game Contexts ──
    game_contexts = {}
    for game in games:
        home = game['home']
        away = game['away']
        home_ctx = team_context.get(home, {})
        away_ctx = team_context.get(away, {})

        game_pace = get_projected_game_pace(home_ctx, away_ctx)

        # Estimate usage bumps from injuries
        home_out = get_out_players(home, injuries)
        away_out = get_out_players(away, injuries)
        home_players = [p for p in all_players if p['team'] == home]
        away_players = [p for p in all_players if p['team'] == away]
        home_bumps = estimate_usage_redistribution(home_out, home_players) if home_out else {}
        away_bumps = estimate_usage_redistribution(away_out, away_players) if away_out else {}

        # Build context for each team's perspective
        # For home team players: opponent is away team
        for player in home_players:
            game_contexts[f"{game['game_id']}_{player['player_name']}"] = {
                'game_id': game['game_id'],
                'opponent': away,
                'is_b2b': home in b2b_teams,
                'is_home': True,
                'spread': 0,  # TODO: get from odds API
                'game_pace': game_pace,
                'usage_bump': home_bumps.get(player['player_name'], 0),
            }

        # For away team players: opponent is home team
        for player in away_players:
            game_contexts[f"{game['game_id']}_{player['player_name']}"] = {
                'game_id': game['game_id'],
                'opponent': home,
                'is_b2b': away in b2b_teams,
                'is_home': False,
                'spread': 0,
                'game_pace': game_pace,
                'usage_bump': away_bumps.get(player['player_name'], 0),
            }

    # ── Step 7: Run Predictions ──
    print(f"\n🎯 Running prediction engine for {len(all_players)} players...\n")

    predictions = []
    for player in all_players:
        ctx_key = f"{player.get('game_id', '')}_{player['player_name']}"
        game_ctx = game_contexts.get(ctx_key, {})
        opp_team = game_ctx.get('opponent', '')
        opp_ctx = team_context.get(opp_team, {})
        prop_line = prop_lines.get(player['player_name'])

        from model.predict import predict_player
        pred = predict_player(player, opp_ctx, game_ctx, prop_line)
        predictions.append(pred)

    # Sort by edge
    predictions.sort(key=lambda x: -x.get('edge', 0))

    # Store predictions
    db.store_predictions(predictions, date)

    # Print summary
    bets = [p for p in predictions if p.get('side') in ('OVER', 'UNDER')]
    print(f"\n📊 PREDICTION SUMMARY")
    print(f"   Total players analyzed: {len(predictions)}")
    print(f"   Players with prop lines: {len([p for p in predictions if p.get('line')])}")
    print(f"   Actionable bets (edge ≥ 3%): {len(bets)}")

    if bets:
        print(f"\n   🔥 TOP PLAYS:")
        for i, b in enumerate(bets[:5], 1):
            print(f"   {i}. {b['player_name']:25s} {b['side']:5s} {b.get('line', '?'):5} pts | "
                  f"Proj: {b['projection']:5.1f} | Edge: +{b['edge']:.1%} | {b.get('confidence', 'N/A'):6s} | {b.get('units', 0):.1f}u")

    # ── Step 8: Claude Analysis ──
    report = generate_claude_analysis(predictions, games, injuries, date)

    # ── Step 9: Deliver ──
    save_report(report, predictions)
    post_to_discord(report, predictions)
    send_email(report, predictions)

    # ── Step 10: Log bets ──
    for bet in bets:
        db.store_bet({
            'player_name': bet['player_name'],
            'team': bet.get('team', ''),
            'game_id': bet.get('game_id', ''),
            'side': bet['side'],
            'line': bet.get('line', 0),
            'odds': bet.get('over_odds' if bet['side'] == 'OVER' else 'under_odds', -110),
            'edge': bet.get('edge', 0),
            'confidence': bet.get('confidence'),
            'units': bet.get('units', 0),
        }, date)

    print(f"\n{'='*60}")
    print(f"  ✅ PIPELINE COMPLETE — {datetime.now().strftime('%H:%M:%S')}")
    print(f"  📋 {len(bets)} bets logged | Report saved & delivered")
    print(f"{'='*60}\n")

    return predictions


def main():
    parser = argparse.ArgumentParser(description="NBA Props Agent")
    parser.add_argument('--date', type=str, help='Date to run (YYYY-MM-DD)')
    parser.add_argument('--grade', action='store_true', help='Grade bets instead of predicting')
    parser.add_argument('--performance', action='store_true', help='Show season performance')
    parser.add_argument('--init-db', action='store_true', help='Initialize database only')

    args = parser.parse_args()

    if args.init_db:
        db.init_db()
        return

    if args.performance:
        perf = get_season_performance()
        print("\n📊 SEASON PERFORMANCE")
        print(f"   Record: {perf.get('wins', 0)}W - {perf.get('losses', 0)}L")
        total = perf.get('wins', 0) + perf.get('losses', 0)
        if total > 0:
            print(f"   Hit Rate: {perf.get('wins', 0)/total:.1%}")
        print(f"   Total P&L: {perf.get('total_pnl', 0):+.1f} units")
        print(f"   Avg Edge: {perf.get('avg_edge', 0):.1%}")
        return

    if args.grade:
        if args.date:
            grade_date(args.date)
        else:
            grade_yesterday()
        return

    # Default: run daily pipeline
    run_daily_pipeline(date=args.date)


if __name__ == "__main__":
    main()
