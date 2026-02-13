"""
NBA Props Agent — Prediction Engine
Implements all 4 model layers + edge detection + Kelly sizing.
"""

import numpy as np
from scipy.stats import lognorm, norm

import config


# ──────────────────────────────────────────────
# LAYER 1: Baseline Projection
# ──────────────────────────────────────────────

def baseline_projection(player):
    """
    Weighted blend of season average and recent form,
    adjusted for minutes trend.

    Returns: float projected points
    """
    season_ppg = player.get('season_ppg', 0)
    l10_ppg = player.get('l10_ppg', season_ppg)
    season_min = player.get('season_min', 30)
    min_trend = player.get('min_trend', season_min)

    # Weighted average
    raw = (config.SEASON_WEIGHT * season_ppg) + (config.RECENT_WEIGHT * l10_ppg)

    # Minutes adjustment: if recent minutes trending up/down, scale proportionally
    if season_min > 0:
        minutes_ratio = min_trend / season_min
        # Cap the adjustment at ±15%
        minutes_ratio = max(0.85, min(1.15, minutes_ratio))
        raw *= minutes_ratio

    return round(raw, 1)


# ──────────────────────────────────────────────
# LAYER 2: Matchup Adjustment
# ──────────────────────────────────────────────

def matchup_adjustment(baseline, player, opponent_ctx, game_pace=100.0):
    """
    Adjust based on opponent defensive strength and projected pace.

    Args:
        baseline: Layer 1 projection
        player: Player dict with season stats
        opponent_ctx: Opponent team context dict
        game_pace: Projected game pace

    Returns: float adjusted projection
    """
    league_avg_pace = 100.0
    league_avg_ppg_allowed = 114.0

    # Opponent defense factor
    opp_ppg_allowed = opponent_ctx.get('opp_ppg_allowed', league_avg_ppg_allowed)
    def_diff = opp_ppg_allowed - league_avg_ppg_allowed

    # Scale by player's scoring volume
    volume_scale = player.get('season_ppg', 15) / 20.0

    # Defense adjustment (conservative: use 10% of the team-level differential)
    def_adj = def_diff * 0.10 * volume_scale

    # Pace adjustment
    pace_diff = game_pace - league_avg_pace
    pace_adj = pace_diff * 0.05 * volume_scale  # ~0.5 pts per 10 pace points above average

    total_adj = def_adj + pace_adj
    return round(baseline + total_adj, 1)


# ──────────────────────────────────────────────
# LAYER 3: Situational Adjustment
# ──────────────────────────────────────────────

def situational_adjustment(projection, context):
    """
    Apply B2B, blowout risk, and teammate absence adjustments.

    Args:
        projection: Post-matchup projection
        context: Dict with situational flags:
            - is_b2b: bool
            - spread: float (absolute value; positive = favored)
            - is_home: bool
            - usage_bump: float (PPG boost from teammate absence)

    Returns: float adjusted projection
    """
    adj = 0.0

    # Back-to-back discount
    if context.get('is_b2b', False):
        adj += config.B2B_DISCOUNT

    # Blowout risk: if heavily favored, starters may sit Q4
    spread = abs(context.get('spread', 0))
    if spread >= config.BLOWOUT_SPREAD_THRESHOLD:
        adj += config.BLOWOUT_DISCOUNT

    # Teammate absence usage bump
    usage_bump = context.get('usage_bump', 0)
    adj += usage_bump

    # Home court advantage (minor, ~0.5 pts)
    if context.get('is_home', False):
        adj += 0.5

    return round(projection + adj, 1)


# ──────────────────────────────────────────────
# LAYER 4: Distribution Modeling
# ──────────────────────────────────────────────

def fit_player_distribution(game_log, projection, std_dev=None):
    """
    Fit a log-normal distribution to a player's game log.
    Falls back to normal distribution if log-normal fit fails.

    Args:
        game_log: List of point totals from recent games
        projection: Our model projection (used as the mean)
        std_dev: Optional override for standard deviation

    Returns:
        Dict with distribution parameters and percentiles
    """
    pts = np.array([p for p in game_log if p is not None and p > 0], dtype=float)

    if len(pts) < 5:
        # Insufficient data — use normal distribution with default std dev
        sd = std_dev or 5.0
        return _normal_distribution(projection, sd)

    # Calculate empirical std dev if not provided
    if std_dev is None:
        std_dev = np.std(pts)

    # Try log-normal fit
    try:
        # Shift data to ensure all positive for log-normal
        pts_shifted = pts + 0.5  # avoid log(0)
        shape, loc, scale = lognorm.fit(pts_shifted, floc=0)

        # Validate the fit is reasonable
        fitted_mean = lognorm.mean(shape, loc, scale)
        if abs(fitted_mean - np.mean(pts)) > 10:
            raise ValueError("Log-normal fit too far from empirical mean")

        # Scale the distribution to match our projection
        scale_factor = projection / fitted_mean if fitted_mean > 0 else 1.0

        percentiles = {
            'p10': round(lognorm.ppf(0.10, shape, loc, scale) * scale_factor, 1),
            'p25': round(lognorm.ppf(0.25, shape, loc, scale) * scale_factor, 1),
            'p50': round(lognorm.ppf(0.50, shape, loc, scale) * scale_factor, 1),
            'p75': round(lognorm.ppf(0.75, shape, loc, scale) * scale_factor, 1),
            'p90': round(lognorm.ppf(0.90, shape, loc, scale) * scale_factor, 1),
            'mean': round(projection, 1),
            'std': round(std_dev, 1),
            'dist_type': 'lognormal',
            'shape': shape,
            'loc': loc,
            'scale': scale * scale_factor,
        }

        return percentiles

    except Exception:
        # Fallback to normal distribution
        return _normal_distribution(projection, std_dev)


def _normal_distribution(mean, std):
    """Fallback: use normal distribution for percentile estimates."""
    return {
        'p10': round(mean - 1.28 * std, 1),
        'p25': round(mean - 0.67 * std, 1),
        'p50': round(mean, 1),
        'p75': round(mean + 0.67 * std, 1),
        'p90': round(mean + 1.28 * std, 1),
        'mean': round(mean, 1),
        'std': round(std, 1),
        'dist_type': 'normal',
    }


def probability_over_line(line, distribution):
    """
    Calculate P(player scores > line) from the fitted distribution.
    """
    if distribution.get('dist_type') == 'lognormal':
        shape = distribution['shape']
        loc = distribution['loc']
        scale = distribution['scale']
        return round(1 - lognorm.cdf(line, shape, loc, scale), 4)
    else:
        mean = distribution['mean']
        std = distribution['std']
        if std == 0:
            return 1.0 if mean > line else 0.0
        return round(1 - norm.cdf(line, mean, std), 4)


# ──────────────────────────────────────────────
# EDGE DETECTION & BET SIZING
# ──────────────────────────────────────────────

def odds_to_probability(american_odds):
    """Convert American odds to implied probability."""
    if american_odds < 0:
        return abs(american_odds) / (abs(american_odds) + 100)
    else:
        return 100 / (american_odds + 100)


def detect_edge(prob_over, over_odds, under_odds):
    """
    Compare model probability to implied probability.

    Returns:
        Dict: {side, edge, confidence}
    """
    implied_over = odds_to_probability(over_odds)
    implied_under = odds_to_probability(under_odds)

    edge_over = prob_over - implied_over
    edge_under = (1 - prob_over) - implied_under

    # Pick the side with the larger edge
    if edge_over >= config.MIN_EDGE_THRESHOLD and edge_over >= edge_under:
        return {
            'side': 'OVER',
            'edge': round(edge_over, 4),
            'confidence': _classify_edge(edge_over),
            'model_prob': round(prob_over, 4),
            'implied_prob': round(implied_over, 4),
            'bet_odds': over_odds,
        }
    elif edge_under >= config.MIN_EDGE_THRESHOLD:
        return {
            'side': 'UNDER',
            'edge': round(edge_under, 4),
            'confidence': _classify_edge(edge_under),
            'model_prob': round(1 - prob_over, 4),
            'implied_prob': round(implied_under, 4),
            'bet_odds': under_odds,
        }
    else:
        return {
            'side': 'NO BET',
            'edge': round(max(edge_over, edge_under), 4),
            'confidence': None,
            'model_prob': round(prob_over, 4) if edge_over > edge_under else round(1 - prob_over, 4),
            'implied_prob': round(implied_over, 4) if edge_over > edge_under else round(implied_under, 4),
            'bet_odds': 0,
        }


def kelly_bet_size(edge, american_odds):
    """
    Calculate recommended bet size using quarter-Kelly criterion.

    Returns:
        Float: suggested wager in units
    """
    if edge <= 0 or american_odds == 0:
        return 0.0

    # Convert to decimal odds
    if american_odds < 0:
        decimal_odds = 1 + (100 / abs(american_odds))
    else:
        decimal_odds = 1 + (american_odds / 100)

    # Kelly fraction: (edge * decimal_odds) / (decimal_odds - 1)
    # Simplified: edge / (decimal_odds - 1) when probability is already the edge
    odds_to_1 = decimal_odds - 1
    if odds_to_1 <= 0:
        return 0.0

    full_kelly = edge / odds_to_1
    quarter_kelly = full_kelly * config.KELLY_FRACTION

    # Cap at max single bet percentage
    capped = min(quarter_kelly, config.MAX_SINGLE_BET_PCT)

    # Convert to units (1 unit = 1% of bankroll)
    units = round(capped * 100, 1)  # e.g., 0.015 → 1.5 units

    return max(0.0, units)


def _classify_edge(edge):
    """Classify edge magnitude into confidence tier."""
    if edge >= config.EDGE_HIGH:
        return 'HIGH'
    elif edge >= config.EDGE_MEDIUM:
        return 'MEDIUM'
    elif edge >= config.EDGE_LOW:
        return 'LOW'
    return None


# ──────────────────────────────────────────────
# MASTER PREDICTION FUNCTION
# ──────────────────────────────────────────────

def predict_player(player, opponent_ctx, game_context, prop_line=None):
    """
    Run the full 4-layer prediction pipeline for a single player.

    Args:
        player: Player dict with stats
        opponent_ctx: Opponent team context
        game_context: Dict with is_b2b, spread, is_home, usage_bump, game_pace
        prop_line: Optional dict with line, over_odds, under_odds

    Returns:
        Dict with full prediction including edge analysis
    """
    # Layer 1: Baseline
    base = baseline_projection(player)

    # Layer 2: Matchup
    game_pace = game_context.get('game_pace', 100.0)
    matchup_adj = matchup_adjustment(base, player, opponent_ctx, game_pace)

    # Layer 3: Situational
    final_projection = situational_adjustment(matchup_adj, game_context)

    # Layer 4: Distribution
    game_log = player.get('game_log', [])
    std_dev = player.get('std_dev', 5.0)
    distribution = fit_player_distribution(game_log, final_projection, std_dev)

    # Build result
    result = {
        'player_name': player['player_name'],
        'team': player.get('team', ''),
        'position': player.get('position', ''),
        'game_id': player.get('game_id', ''),
        'season_ppg': player.get('season_ppg', 0),
        'l5_ppg': player.get('l5_ppg', 0),
        'l10_ppg': player.get('l10_ppg', 0),
        'projection': final_projection,
        'baseline': base,
        'matchup_adjusted': matchup_adj,
        'std_dev': distribution['std'],
        'p10': distribution['p10'],
        'p25': distribution['p25'],
        'p50': distribution['p50'],
        'p75': distribution['p75'],
        'p90': distribution['p90'],
    }

    # Edge detection if we have a prop line
    if prop_line and prop_line.get('line'):
        line = prop_line['line']
        over_odds = prop_line.get('over_odds', -110)
        under_odds = prop_line.get('under_odds', -110)

        prob_over = probability_over_line(line, distribution)
        edge_result = detect_edge(prob_over, over_odds, under_odds)
        units = kelly_bet_size(edge_result['edge'], edge_result['bet_odds'])

        result.update({
            'line': line,
            'over_odds': over_odds,
            'under_odds': under_odds,
            'prob_over': prob_over,
            'implied_prob_over': odds_to_probability(over_odds),
            'side': edge_result['side'],
            'edge': edge_result['edge'],
            'confidence': edge_result['confidence'],
            'units': units,
            'bookmaker': prop_line.get('bookmaker', ''),
        })
    else:
        result.update({
            'line': None,
            'side': 'NO LINE',
            'edge': 0,
            'confidence': None,
            'units': 0,
        })

    return result


def run_predictions(players, team_context, game_contexts, prop_lines):
    """
    Run predictions for all players on the slate.

    Args:
        players: List of player dicts
        team_context: Dict of team context keyed by abbreviation
        game_contexts: Dict of game context keyed by game_id
        prop_lines: Dict of prop lines keyed by player_name

    Returns:
        List of prediction dicts, sorted by edge (highest first)
    """
    predictions = []

    for player in players:
        # Determine opponent
        game_id = player.get('game_id', '')
        game_ctx = game_contexts.get(game_id, {})
        opp_team = game_ctx.get('opponent', '')
        opp_ctx = team_context.get(opp_team, {})

        # Get prop line if available
        prop_line = prop_lines.get(player['player_name'])

        # Run prediction
        pred = predict_player(player, opp_ctx, game_ctx, prop_line)
        predictions.append(pred)

    # Sort by edge (highest first), then by confidence
    confidence_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2, None: 3}
    predictions.sort(key=lambda x: (
        -x.get('edge', 0),
        confidence_order.get(x.get('confidence'), 3)
    ))

    return predictions


if __name__ == "__main__":
    # Quick test with dummy data
    player = {
        'player_name': 'Test Player',
        'team': 'OKC',
        'season_ppg': 20.0,
        'l10_ppg': 22.0,
        'season_min': 32.0,
        'min_trend': 33.0,
        'std_dev': 6.0,
        'game_log': [18, 25, 22, 15, 28, 20, 24, 19, 30, 21],
    }

    opp_ctx = {'opp_ppg_allowed': 118.0, 'pace': 102.0, 'def_rating': 112.0}
    game_ctx = {'is_b2b': False, 'spread': 5.0, 'is_home': True, 'usage_bump': 0, 'game_pace': 101.0}
    prop = {'line': 21.5, 'over_odds': -110, 'under_odds': -110, 'bookmaker': 'test'}

    result = predict_player(player, opp_ctx, game_ctx, prop)
    print(f"\n🎯 {result['player_name']}")
    print(f"   Projection: {result['projection']} pts (baseline: {result['baseline']})")
    print(f"   Distribution: {result['p10']}/{result['p25']}/{result['p50']}/{result['p75']}/{result['p90']}")
    print(f"   Line: {result.get('line')} | P(Over): {result.get('prob_over', 0):.1%}")
    print(f"   Edge: {result.get('edge', 0):.1%} → {result.get('side')} ({result.get('confidence')})")
    print(f"   Units: {result.get('units', 0)}")
