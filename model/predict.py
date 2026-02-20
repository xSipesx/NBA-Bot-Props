"""
NBA Props Agent — Prediction Engine v2 (Cloud-Optimized)

Edge detection approach:
1. JUICE ASYMMETRY: When books post -130/+100, the -130 side is where sharp money sits.
   We detect when the vig is skewed, suggesting the book knows the line is slightly off.
2. INJURY IMPACT: When key players are OUT, remaining players get usage boosts that
   books are slow to fully price in, especially for role players.
3. VARIANCE EXPLOITATION: High-variance players (streaky scorers) are more likely to
   go over in favorable matchups. We use tighter std dev estimates.
4. LINE SHOPPING: We compare across bookmakers to find stale lines.
"""

import numpy as np
from scipy.stats import norm
import config


def predict_from_props(raw_props, games, injuries):
    """Generate predictions for all players with prop lines."""

    # Build injury context per team
    team_out_players = {}
    for inj in injuries:
        team = inj.get('team', '')
        status = inj.get('status', '').upper()
        if status in ('OUT', 'SUSPENDED'):
            if team not in team_out_players:
                team_out_players[team] = []
            team_out_players[team].append(inj)

    # Build game lookup by team
    team_to_game = {}
    for g in games:
        team_to_game[g['home']] = {'game': g, 'side': 'home', 'opp': g['away']}
        team_to_game[g['away']] = {'game': g, 'side': 'away', 'opp': g['home']}

    # Group props by game for team identification
    game_props = {}
    for prop in raw_props:
        game_str = prop.get('game', '')
        if game_str not in game_props:
            game_props[game_str] = []
        game_props[game_str].append(prop)

    predictions = []
    for prop in raw_props:
        pred = _predict_single(prop, games, team_out_players, team_to_game)
        predictions.append(pred)

    actionable = [p for p in predictions if p['side'] != 'NO_BET']
    print(f"\n🎯 Predictions generated for {len(predictions)} players ({len(actionable)} actionable)", flush=True)
    return predictions


def _predict_single(prop, games, team_out_players, team_to_game):
    """Predict a single player prop."""
    player_name = prop['player_name']
    line = prop['line']
    over_odds = prop.get('over_odds', -110)
    under_odds = prop.get('under_odds', -110)
    game_str = prop.get('game', '')

    # Find the game
    game = None
    player_team = None
    opponent = None
    for g in games:
        home_full = g.get('home', '')
        away_full = g.get('away', '')
        if home_full in game_str or away_full in game_str:
            game = g
            break

    # ── FACTOR 1: Juice Asymmetry ──
    # If over is -130 and under is +110, the book is telling us the over is more likely
    # This is the single most reliable signal from the props themselves
    juice_edge = _analyze_juice(over_odds, under_odds)

    # ── FACTOR 2: Injury-based projection shift ──
    injury_shift = 0.0
    if game:
        # Try to figure out player's team from the game string
        # Props format: "Houston Rockets @ Charlotte Hornets"
        home_out = team_out_players.get(game['home'], [])
        away_out = team_out_players.get(game['away'], [])

        # Significant injuries on EITHER side affect the game
        home_out_count = len(home_out)
        away_out_count = len(away_out)

        # If the opponent has many key players out → easier matchup → slight over lean
        # If player's own team has many outs → more usage for remaining → over lean
        # We don't know the player's team, so we use the total injury chaos as a volatility signal
        total_outs = home_out_count + away_out_count
        if total_outs >= 5:
            # High injury chaos → more variance → overs tend to hit for primary options
            injury_shift = 0.5
        if total_outs >= 8:
            injury_shift = 1.0

    # ── FACTOR 3: Line level analysis ──
    # Higher lines (star players) are more efficient. Lower lines (role players)
    # have more variance and the book is less sharp on them.
    line_inefficiency = 0.0
    if line <= 14.5:
        line_inefficiency = 0.3  # books less sharp on role players
    elif line <= 18.5:
        line_inefficiency = 0.15

    # ── Combine factors into a directional lean ──
    # Positive = lean over, negative = lean under
    total_lean = juice_edge + injury_shift + line_inefficiency

    # Project from line
    projection = line + total_lean

    # ── Edge Calculation ──
    # Use tighter std dev — NBA scoring is less variable than people think
    # Typical std dev is ~20-25% of the line for consistent players
    estimated_std = max(line * 0.22, 3.5)

    prob_over = 1 - norm.cdf(line + 0.5, loc=projection, scale=estimated_std)  # +0.5 for the half-point
    prob_under = norm.cdf(line - 0.5, loc=projection, scale=estimated_std)

    # Implied probabilities from odds (with vig removed)
    impl_over = _odds_to_probability(over_odds)
    impl_under = _odds_to_probability(under_odds)

    # Remove vig for fairer comparison
    total_impl = impl_over + impl_under
    impl_over_fair = impl_over / total_impl
    impl_under_fair = impl_under / total_impl

    edge_over = prob_over - impl_over_fair
    edge_under = prob_under - impl_under_fair

    # Pick side
    if edge_over > edge_under and edge_over >= config.MIN_EDGE_THRESHOLD:
        side = 'OVER'
        edge = edge_over
        odds = over_odds
    elif edge_under > edge_over and edge_under >= config.MIN_EDGE_THRESHOLD:
        side = 'UNDER'
        edge = edge_under
        odds = under_odds
    else:
        side = 'NO_BET'
        edge = max(edge_over, edge_under, 0)
        odds = -110

    # Confidence tier
    if edge >= config.EDGE_HIGH:
        confidence = 'HIGH'
    elif edge >= config.EDGE_MEDIUM:
        confidence = 'MEDIUM'
    elif edge >= config.EDGE_LOW:
        confidence = 'LOW'
    else:
        confidence = 'NONE'

    # Kelly bet sizing
    units = 0.0
    if side != 'NO_BET':
        decimal_odds = _american_to_decimal(odds)
        kelly = (edge / (decimal_odds - 1)) * config.KELLY_FRACTION
        kelly = max(0, min(kelly, config.MAX_SINGLE_BET_PCT))
        units = round(kelly * config.DEFAULT_BANKROLL / 100, 1)

    return {
        'player_name': player_name,
        'team': prop.get('team', ''),
        'game_id': game['game_id'] if game else '',
        'line': line,
        'projection': round(projection, 1),
        'adjustment': round(total_lean, 2),
        'side': side,
        'edge': round(edge, 4),
        'confidence': confidence,
        'over_odds': over_odds,
        'under_odds': under_odds,
        'prob_over': round(prob_over, 3),
        'prob_under': round(prob_under, 3),
        'units': units,
        'bookmaker': prop.get('bookmaker', ''),
        'juice_signal': round(juice_edge, 2),
        'injury_shift': round(injury_shift, 2),
    }


def _analyze_juice(over_odds, under_odds):
    """
    Detect directional signal from juice asymmetry.
    
    Standard line: -110/-110 (no signal)
    Over-leaning: -130/+110 (books think over is more likely)
    Under-leaning: +110/-130 (books think under is more likely)
    
    Returns: positive = over lean, negative = under lean
    """
    impl_over = _odds_to_probability(over_odds)
    impl_under = _odds_to_probability(under_odds)

    # The side with higher implied probability is where the book leans
    diff = impl_over - impl_under

    # Scale: a 5% difference in implied prob ≈ 1 point of projection shift
    juice_shift = diff * 20  # amplify the signal

    # Cap at ±2 points
    return max(-2.0, min(2.0, juice_shift))


def _odds_to_probability(american_odds):
    """Convert American odds to implied probability."""
    if american_odds < 0:
        return abs(american_odds) / (abs(american_odds) + 100)
    else:
        return 100 / (american_odds + 100)


def _american_to_decimal(american_odds):
    """Convert American odds to decimal odds."""
    if american_odds < 0:
        return 1 + (100 / abs(american_odds))
    else:
        return 1 + (american_odds / 100)
