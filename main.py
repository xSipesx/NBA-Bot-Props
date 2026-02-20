#!/usr/bin/env python3
"""
NBA Props Agent — Main Pipeline Orchestrator
All nba_api imports are lazy to avoid hanging on cloud servers.
"""

import argparse
import sys
import time
from datetime import datetime

import config
import database as db


def run_daily_pipeline(date=None):
    if date is None:
        date = config.get_today()

    print(f"\n{'='*60}")
    print(f"  NBA PROPS AGENT — {date}")
    print(f"  Pipeline started at {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")

    db.init_db()

    # ── Step 1: Schedule (Odds API — no nba_api needed) ──
    from ingest.odds import get_schedule_from_odds
    games = get_schedule_from_odds()
    if not games:
        print("  🔄 Odds API schedule empty, trying nba_api fallback...")
        from ingest.schedule import get_todays_games
        games = get_todays_games(date)
    if not games:
        print("\n🚫 No games today. Exiting.")
        return

    # B2B detection (non-critical)
    b2b_teams = set()
    try:
        from ingest.schedule import get_b2b_teams
        b2b_teams = get_b2b_teams(games, date)
    except Exception as e:
        print(f"  ⚠️  Could not detect B2B teams: {e}")

    # ── Step 2: Team Context (nba_api — non-critical) ──
    team_context = {}
    try:
        from ingest.team_context import get_team_context
        team_context = get_team_context()
    except Exception as e:
        print(f"  ⚠️  Could not load team context: {e}")
    time.sleep(1)

    # ── Step 3: Injuries ──
    from ingest.injuries import get_injury_report, get_out_players, estimate_usage_redistribution
    today_teams = set()
    for g in games:
        today_teams.add(g['home'])
        today_teams.add(g['away'])
    injuries = get_injury_report(teams_filter=today_teams)
    db.store_injuries(injuries, date)

    # ── Step 4: Player Stats (nba_api — non-critical) ──
    all_players = []
    try:
        from ingest.player_stats import get_all_player_stats
        all_players = get_all_player_stats(games)
    except Exception as e:
        print(f"  ⚠️  Could not load player stats: {e}")
    if all_players:
        db.store_player_stats(all_players, date)

    # ── Step 5: Prop Lines ──
    from ingest.odds import get_player_points_props
    raw_props = get_player_points_props()
    prop_lines = {}
    for prop in raw_props:
        prop_lines[prop['player_name']] = prop
    db.store_prop_lines(raw_props, date)

    # ── Step 6: Build Game Contexts ──
    from ingest.team_context import get_projected_game_pace
    game_contexts = {}
    for game in games:
        home = game['home']
        away = game['away']
        home_ctx = team_context.get(home, {})
        away_ctx = team_context.get(away, {})
        game_pace = get_projected_game_pace(home_ctx, away_ctx)

        home_out = get_out_players(home, injuries)
        away_out = get_out_players(away, injuries)
        home_players = [p for p in all_players if p['team'] == home]
        away_players = [p for p in all_players if p['team'] == away]
        home_bumps = estimate_usage_redistribution(home_out, home_players) if home_out else {}
        away_bumps = estimate_usage_redistribution(away_out, away_players) if away_out else {}

        for player in home_players:
            game_contexts[f"{game['game_id']}_{player['player_name']}"] = {
                'game_id': game['game_id'], 'opponent': away,
                'is_b2b': home in b2b_teams, 'is_home': True,
                'spread': 0, 'game_pace': game_pace,
                'usage_bump': home_bumps.get(player['player_name'], 0),
            }
        for player in away_players:
            game_contexts[f"{game['game_id']}_{player['player_name']}"] = {
                'game_id': game['game_id'], 'opponent': home,
                'is_b2b': away in b2b_teams, 'is_home': False,
                'spread': 0, 'game_pace': game_pace,
                'usage_bump': away_bumps.get(player['player_name'], 0),
            }

    # ── Step 7: Run Predictions ──
    from model.predict import predict_player
    print(f"\n🎯 Running prediction engine for {len(all_players)} players...\n")
    predictions = []
    for player in all_players:
        ctx_key = f"{player.get('game_id', '')}_{player['player_name']}"
        game_ctx = game_contexts.get(ctx_key, {})
        opp_team = game_ctx.get('opponent', '')
        opp_ctx = team_context.get(opp_team, {})
        prop_line = prop_lines.get(player['player_name'])
        pred = predict_player(player, opp_ctx, game_ctx, prop_line)
        predictions.append(pred)

    predictions.sort(key=lambda x: -x.get('edge', 0))
    db.store_predictions(predictions, date)

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
    from output.claude_analysis import generate_claude_analysis
    report = generate_claude_analysis(predictions, games, injuries, date)

    # ── Step 9: Deliver ──
    from output.deliver import post_to_discord, send_email, save_report
    save_report(report, predictions)
    post_to_discord(report, predictions)
    send_email(report, predictions)

    # ── Step 10: Log bets ──
    for bet in bets:
        db.store_bet({
            'player_name': bet['player_name'], 'team': bet.get('team', ''),
            'game_id': bet.get('game_id', ''), 'side': bet['side'],
            'line': bet.get('line', 0),
            'odds': bet.get('over_odds' if bet['side'] == 'OVER' else 'under_odds', -110),
            'edge': bet.get('edge', 0), 'confidence': bet.get('confidence'),
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
    parser.add_argument('--grade', action='store_true', help='Grade bets')
    parser.add_argument('--performance', action='store_true', help='Show performance')
    parser.add_argument('--init-db', action='store_true', help='Initialize database only')

    args = parser.parse_args()

    if args.init_db:
        db.init_db()
        return

    if args.performance:
        from tracking.grader import get_season_performance
        perf = get_season_performance()
        print(f"\n📊 SEASON: {perf.get('wins', 0)}W - {perf.get('losses', 0)}L | P&L: {perf.get('total_pnl', 0):+.1f}u")
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
