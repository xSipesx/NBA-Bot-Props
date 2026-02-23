"""
NBA Props Agent — Prediction Engine v3

Fixes v2's all-OVER bias by:
1. Making juice analysis bidirectional (detects under-leaning lines too)
2. Adding negative adjustments (blowout risk, pace-down, heavy favorite starters resting)
3. Using proper std dev by stat type (rebounds are tighter than points)
4. Supporting PTS, REB, AST markets
"""

import numpy as np
from scipy.stats import norm
import config


# Standard deviations as percentage of line, by stat type
# Points are most variable, assists least
STD_DEV_PCT = {
    'PTS': 0.24,   # ~6 pts std on a 25-pt line
    'REB': 0.28,   # ~1.5 reb std on a 5.5-reb line
    'AST': 0.30,   # ~1.5 ast std on a 5-ast line
}

# Minimum std dev floors by stat type
STD_DEV_FLOOR = {
    'PTS': 3.5,
    'REB': 1.2,
    'AST': 1.2,
}


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

    predictions = []
    for prop in raw_props:
        pred = _predict_single(prop, games, team_out_players)
        predictions.append(pred)

    actionable = [p for p in predictions if p['side'] != 'NO_BET']
    over_count = len([p for p in actionable if p['side'] == 'OVER'])
    under_count = len([p for p in actionable if p['side'] == 'UNDER'])
    print(f"\n🎯 Predictions: {len(predictions)} total, {len(actionable)} actionable ({over_count} OVER, {under_count} UNDER)", flush=True)
    return predictions


def _predict_single(prop, games, team_out_players):
    """Predict a single player prop."""
    player_name = prop['player_name']
    line = prop['line']
    over_odds = prop.get('over_odds', -110)
    under_odds = prop.get('under_odds', -110)
    stat = prop.get('stat', 'PTS')
    market = prop.get('market', 'player_points')
    game_str = prop.get('game', '')

    # Find the game
    game = None
    for g in games:
        if g['home'] in game_str or g['away'] in game_str:
            game = g
            break

    # ── FACTOR 1: Juice Asymmetry (bidirectional) ──
    # This is the primary signal. Books skew odds when they have information.
    juice_edge = _analyze_juice(over_odds, under_odds)
    # juice_edge > 0 means over lean, < 0 means under lean

    # ── FACTOR 2: Injury chaos ──
    injury_shift = 0.0
    if game:
        home_outs = len(team_out_players.get(game['home'], []))
        away_outs = len(team_out_players.get(game['away'], []))
        total_outs = home_outs + away_outs
        # High injury chaos = higher variance = slight over lean for points
        # but NOT for rebounds/assists which can go either way
        if stat == 'PTS' and total_outs >= 6:
            injury_shift = 0.3
        elif stat == 'PTS' and total_outs >= 10:
            injury_shift = 0.5

    # ── FACTOR 3: Blowout risk (UNDER pressure for favorites) ──
    blowout_adj = 0.0
    # If one team is a huge favorite, their starters may rest Q4
    # This is an UNDER signal for star players on the favored team
    if line >= 22 and stat == 'PTS':
        # Stars on heavy favorites are blowout risk
        blowout_adj = -0.3

    # ── FACTOR 4: Line-level sharpness ──
    # Books are less sharp on low lines (role players)
    # This amplifies the juice signal for role players
    sharpness_mult = 1.0
    if stat == 'PTS':
        if line <= 12:
            sharpness_mult = 1.4  # books least sharp here
        elif line <= 18:
            sharpness_mult = 1.2
        elif line >= 28:
            sharpness_mult = 0.8  # books very sharp on stars
    elif stat in ('REB', 'AST'):
        if line <= 4:
            sharpness_mult = 1.3
        elif line >= 9:
            sharpness_mult = 0.85

    # ── Combine into directional lean ──
    total_lean = (juice_edge * sharpness_mult) + injury_shift + blowout_adj
    projection = line + total_lean

    # ── Edge Calculation ──
    std_pct = STD_DEV_PCT.get(stat, 0.25)
    std_floor = STD_DEV_FLOOR.get(stat, 2.0)
    estimated_std = max(line * std_pct, std_floor)

    prob_over = 1 - norm.cdf(line + 0.5, loc=projection, scale=estimated_std)
    prob_under = norm.cdf(line - 0.5, loc=projection, scale=estimated_std)

    # Remove vig for fair comparison
    impl_over = _odds_to_probability(over_odds)
    impl_under = _odds_to_probability(under_odds)
    total_impl = impl_over + impl_under
    impl_over_fair = impl_over / total_impl
    impl_under_fair = impl_under / total_impl

    edge_over = prob_over - impl_over_fair
    edge_under = prob_under - impl_under_fair

    # Pick the best side
    if edge_over >= config.MIN_EDGE_THRESHOLD and edge_over > edge_under:
        side, edge, odds = 'OVER', edge_over, over_odds
    elif edge_under >= config.MIN_EDGE_THRESHOLD and edge_under > edge_over:
        side, edge, odds = 'UNDER', edge_under, under_odds
    else:
        side, edge, odds = 'NO_BET', max(edge_over, edge_under, 0), -110

    # Confidence tier
    if edge >= config.EDGE_HIGH:
        confidence = 'HIGH'
    elif edge >= config.EDGE_MEDIUM:
        confidence = 'MEDIUM'
    elif edge >= config.EDGE_LOW:
        confidence = 'LOW'
    else:
        confidence = 'NONE'

    # Kelly sizing
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
        'stat': stat,
        'market': market,
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
        'juice_signal': round(juice_edge, 3),
        'injury_shift': round(injury_shift, 2),
        'blowout_adj': round(blowout_adj, 2),
    }


def _analyze_juice(over_odds, under_odds):
    """
    Bidirectional juice analysis.
    Returns positive = over lean, negative = under lean.

    -130/+110 → over lean (+1.2 pts)
    +110/-130 → under lean (-1.2 pts)
    -110/-110 → no signal (0 pts)
    """
    impl_over = _odds_to_probability(over_odds)
    impl_under = _odds_to_probability(under_odds)

    # Difference in implied probabilities
    diff = impl_over - impl_under
    # Scale: 5% implied prob diff ≈ 1.2 pts of lean
    juice_shift = diff * 24

    return max(-2.5, min(2.5, juice_shift))


def _odds_to_probability(american_odds):
    if american_odds < 0:
        return abs(american_odds) / (abs(american_odds) + 100)
    else:
        return 100 / (american_odds + 100)


def _american_to_decimal(american_odds):
    if american_odds < 0:
        return 1 + (100 / abs(american_odds))
    else:
        return 1 + (american_odds / 100)
