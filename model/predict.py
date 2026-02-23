"""
NBA Props Agent — Prediction Engine v5

PHILOSOPHY: We can't out-project the book using only the book's own lines.
Instead, we find edges from:

1. VIG EXPLOITATION: After removing the ~5% vig, lines where one side has
   disproportionately better value (e.g., book prices over at 54% and under
   at 51% fair → the under has a 49% true prob but only 51% implied = edge)

2. INJURY ADJUSTMENTS: When key players are ruled OUT close to game time,
   books are slow to adjust role player props. We add a small bump for
   teammates of injured stars.

3. ROLE PLAYER INEFFICIENCY: Books set sharper lines for stars (Giannis,
   LeBron) and looser lines for role players. We're more aggressive on
   low-line props where the book's edge is thinner.

4. CROSS-STAT CORRELATION: A player with juice favoring OVER on points
   is likely to be more involved → slight lean on their assists too.

Edges are 3-8% (realistic), not 40% (model artifact).
"""

import numpy as np
from scipy.stats import norm
import config


STD_DEV_PCT = {'PTS': 0.26, 'REB': 0.32, 'AST': 0.35}
STD_DEV_FLOOR = {'PTS': 4.0, 'REB': 1.5, 'AST': 1.5}
MAX_CREDIBLE_EDGE = 0.12  # 12% cap — anything above is suspect


def predict_from_props(raw_props, games, injuries):
    """Generate predictions for all player props."""

    # Build injury context
    team_out_players = {}
    for inj in injuries:
        team = inj.get('team', '')
        if inj.get('status', '').upper() in ('OUT', 'SUSPENDED'):
            team_out_players.setdefault(team, []).append(inj)

    # Group props by player to detect cross-stat signals
    player_props = {}
    for prop in raw_props:
        player_props.setdefault(prop['player_name'], []).append(prop)

    predictions = []
    for prop in raw_props:
        other_props = [p for p in player_props.get(prop['player_name'], [])
                       if p['market'] != prop['market']]
        pred = _predict_single(prop, games, team_out_players, other_props)
        predictions.append(pred)

    actionable = [p for p in predictions if p['side'] != 'NO_BET']
    over_count = len([p for p in actionable if p['side'] == 'OVER'])
    under_count = len([p for p in actionable if p['side'] == 'UNDER'])
    print(f"\n🎯 Predictions: {len(predictions)} total, {len(actionable)} actionable "
          f"({over_count} OVER, {under_count} UNDER)", flush=True)
    return predictions


def _predict_single(prop, games, team_out_players, other_props):
    player_name = prop['player_name']
    line = prop['line']
    over_odds = prop.get('over_odds', -110)
    under_odds = prop.get('under_odds', -110)
    stat = prop.get('stat', 'PTS')
    market = prop.get('market', 'player_points')
    game_str = prop.get('game', '')

    game = None
    for g in games:
        if g['home'] in game_str or g['away'] in game_str:
            game = g
            break

    # ── Step 1: Calculate fair probabilities (remove vig) ──
    impl_over_raw = _odds_to_probability(over_odds)
    impl_under_raw = _odds_to_probability(under_odds)
    total_impl = impl_over_raw + impl_under_raw
    vig = total_impl - 1.0  # typically ~0.04-0.06

    # Fair probabilities (vig removed equally from both sides)
    fair_over = impl_over_raw / total_impl
    fair_under = impl_under_raw / total_impl

    # The "vig gap" is how much extra probability is loaded on each side
    vig_on_over = impl_over_raw - fair_over
    vig_on_under = impl_under_raw - fair_under

    # ── Step 2: Build our model probability ──
    # Start with the fair probability as baseline
    model_shift = 0.0  # shift in probability space, not point space

    # Factor A: Vig asymmetry signal
    # When the vig is loaded more heavily on one side, the book expects
    # that side to attract more action (i.e., the public is on that side).
    # Fading the public has a small historical edge.
    if vig > 0.04:  # only signal when there's meaningful vig
        vig_diff = vig_on_over - vig_on_under
        # If more vig on over → public is on over → slight under lean
        # Scale: 1% vig difference → 0.5% model shift (very conservative)
        model_shift -= vig_diff * 0.5

    # Factor B: Juice direction (book's lean, not public's)
    # When fair_over >> fair_under, the book believes the over is likely.
    # We trust this signal slightly — book has better info than us.
    juice_direction = fair_over - fair_under
    # A 5% book lean → 1% model lean in same direction
    model_shift += juice_direction * 0.20

    # Factor C: Injury boost for teammates
    injury_boost = 0.0
    if game and stat == 'PTS':
        home_outs = len(team_out_players.get(game['home'], []))
        away_outs = len(team_out_players.get(game['away'], []))
        # Boost remaining players when key teammates are out
        if home_outs >= 2 or away_outs >= 2:
            injury_boost = 0.015  # 1.5% probability boost toward over
        if home_outs >= 4 or away_outs >= 4:
            injury_boost = 0.025  # 2.5% boost for heavy injury games
        model_shift += injury_boost

    # Factor D: Role player inefficiency
    # Books are less sharp on low-line props — our strongest edge source
    line_boost = 0.0
    if stat == 'PTS' and line <= 14:
        line_boost = 0.015  # 1.5% edge on role player points
    elif stat == 'PTS' and line <= 18:
        line_boost = 0.008  # smaller edge on mid-tier players
    elif stat in ('REB', 'AST') and line <= 4:
        line_boost = 0.012  # 1.2% edge on low reb/ast lines
    elif stat in ('REB', 'AST') and line <= 6:
        line_boost = 0.006

    # Factor E: Cross-stat correlation
    cross_boost = 0.0
    for other in other_props:
        other_over = _odds_to_probability(other.get('over_odds', -110))
        other_under = _odds_to_probability(other.get('under_odds', -110))
        other_total = other_over + other_under
        if other_total > 0:
            other_fair_over = other_over / other_total
            # If player's PTS line leans over, their AST/REB may too
            if other_fair_over > 0.55:
                cross_boost = 0.008  # small correlated signal
            elif other_fair_over < 0.45:
                cross_boost = -0.008

    model_shift += cross_boost

    # ── Step 3: Calculate model probabilities ──
    model_over = fair_over + model_shift + line_boost
    model_under = 1.0 - model_over

    # Clamp to valid range
    model_over = max(0.02, min(0.98, model_over))
    model_under = max(0.02, min(0.98, model_under))

    # ── Step 4: Calculate edges ──
    edge_over = model_over - fair_over
    edge_under = model_under - fair_under

    # Cap edges
    edge_over = min(edge_over, MAX_CREDIBLE_EDGE)
    edge_under = min(edge_under, MAX_CREDIBLE_EDGE)

    # Convert model probability to a "projection" for display
    # Using inverse normal CDF to get the point projection
    std_pct = STD_DEV_PCT.get(stat, 0.28)
    std_floor = STD_DEV_FLOOR.get(stat, 2.0)
    estimated_std = max(line * std_pct, std_floor)

    # Projection: the point where P(X > line) = model_over
    # This gives us a human-readable projection number
    projection = line + estimated_std * norm.ppf(model_over) * 0.15
    projection = max(0.0, round(projection, 1))

    # Pick side
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
        'projection': projection,
        'adjustment': round(model_shift, 4),
        'side': side,
        'edge': round(edge, 4),
        'confidence': confidence,
        'over_odds': over_odds,
        'under_odds': under_odds,
        'prob_over': round(model_over, 3),
        'prob_under': round(model_under, 3),
        'units': units,
        'bookmaker': prop.get('bookmaker', ''),
        'juice_signal': round(juice_direction, 3),
        'injury_shift': round(injury_boost, 3),
        'blowout_adj': 0.0,
    }


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
