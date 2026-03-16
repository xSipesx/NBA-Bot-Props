"""
NBA Props Agent — Prediction Engine v7

CHANGES FROM v6 (391W-418L, 48%, -20.9u diagnosis):
1. Projection weights: 45% season, 40% L10, 15% L5 (was 35/35/30)
   → Stops chasing hot/cold streaks books already priced in
2. Higher line floors: PTS≥14.5, REB≥3.5, AST≥2.5
   → No more garbage bench player props
3. Stat-specific edge thresholds: PTS≥5%, REB/AST≥8%
   → REB/AST have too much variance for small edges to be real
4. Hard cap: max 15 plays per day, sorted by edge
   → Eliminates marginal bets that lose to vig
5. Std dev floor raised to 3.0 (was 2.0)
   → Model was overconfident on low-variance projections
6. Minutes floor raised to 25 MPG (was 20)
   → Focus on starters, not rotation guys
"""

from scipy.stats import norm
import config


# Minimum line thresholds — raised to filter out low-value props
MIN_LINE = {
    'PTS': 14.5,
    'REB': 3.5,
    'AST': 2.5,
}

# Stat-specific minimum edge — REB/AST need bigger edge to overcome variance
MIN_EDGE = {
    'PTS': 0.05,   # 5%
    'REB': 0.08,   # 8%
    'AST': 0.08,   # 8%
}

# Max plays per day — only take the best
MAX_DAILY_PLAYS = 15

# Minimum minutes to consider
MIN_MINUTES = 25


def predict_from_props(raw_props, games, injuries, player_stats):
    """Generate predictions comparing ESPN projections vs prop lines."""
    stats_by_name = {}
    for p in player_stats:
        stats_by_name[p['name']] = p

    team_outs = {}
    for inj in injuries:
        if inj.get('status', '').upper() in ('OUT', 'SUSPENDED'):
            team_outs.setdefault(inj.get('team', ''), []).append(inj)

    all_predictions = []
    skipped_no_stats = 0
    skipped_low_line = 0
    skipped_low_min = 0

    for prop in raw_props:
        player_name = prop['player_name']
        line = prop['line']
        stat = prop.get('stat', 'PTS')

        if line < MIN_LINE.get(stat, 3.5):
            skipped_low_line += 1
            continue

        pstats = stats_by_name.get(player_name)
        if not pstats:
            for name, s in stats_by_name.items():
                if player_name.split()[-1] == name.split()[-1] and player_name[0] == name[0]:
                    pstats = s
                    break

        if not pstats:
            skipped_no_stats += 1
            continue

        if pstats.get('min_pg', 0) < MIN_MINUTES:
            skipped_low_min += 1
            continue

        pred = _predict_single(prop, pstats, games, team_outs)
        if pred:
            all_predictions.append(pred)

    # Apply stat-specific edge thresholds
    actionable = []
    for p in all_predictions:
        stat = p.get('stat', 'PTS')
        min_edge = MIN_EDGE.get(stat, 0.05)
        if p['side'] != 'NO_BET' and p['edge'] >= min_edge:
            actionable.append(p)
        else:
            p['side'] = 'NO_BET'

    # Sort by edge and cap at MAX_DAILY_PLAYS
    actionable.sort(key=lambda x: -x['edge'])
    if len(actionable) > MAX_DAILY_PLAYS:
        # Demote plays beyond the cap
        for p in actionable[MAX_DAILY_PLAYS:]:
            p['side'] = 'NO_BET'
        actionable = actionable[:MAX_DAILY_PLAYS]

    over_ct = len([p for p in actionable if p['side'] == 'OVER'])
    under_ct = len([p for p in actionable if p['side'] == 'UNDER'])

    print(f"\n🎯 Predictions: {len(all_predictions)} analyzed, {len(actionable)} actionable "
          f"({over_ct} OVER, {under_ct} UNDER) [capped at {MAX_DAILY_PLAYS}]", flush=True)
    print(f"   Skipped: {skipped_no_stats} no stats, {skipped_low_line} low line, "
          f"{skipped_low_min} low minutes", flush=True)

    # Return all predictions (actionable + no_bet) for Claude analysis context
    return all_predictions


def _predict_single(prop, pstats, games, team_outs):
    """Build a projection and compare to the line."""
    player_name = prop['player_name']
    line = prop['line']
    over_odds = prop.get('over_odds', -110)
    under_odds = prop.get('under_odds', -110)
    stat = prop.get('stat', 'PTS')

    game_str = prop.get('game', '')
    game = None
    for g in games:
        if g['home'] in game_str or g['away'] in game_str:
            game = g
            break

    # ── Build projection from real data ──
    stat_key = {'PTS': 'pts', 'REB': 'reb', 'AST': 'ast'}.get(stat, 'pts')

    season_avg = pstats.get(f'{stat_key}_avg', 0)
    l10_avg = pstats.get(f'{stat_key}_l10', season_avg)
    l5_avg = pstats.get(f'{stat_key}_l5', season_avg)
    player_std = pstats.get(f'{stat_key}_std', 5.0)

    if season_avg == 0 and l10_avg == 0:
        return None

    # v7 weights: heavier on season (stable), lighter on L5 (noisy)
    projection = (0.45 * season_avg) + (0.40 * l10_avg) + (0.15 * l5_avg)

    # Minutes trend adjustment (dampened — cap at ±10%)
    min_pg = pstats.get('min_pg', 30)
    min_l5 = pstats.get('min_l5', min_pg)
    if min_pg > 0:
        min_ratio = min_l5 / min_pg
        min_ratio = max(0.90, min(1.10, min_ratio))
        projection *= min_ratio

    # Injury boost (points only, conservative)
    injury_adj = 0.0
    if game and stat == 'PTS':
        player_team = pstats.get('team', '')
        team_out_list = team_outs.get(player_team, [])
        if len(team_out_list) >= 3:
            injury_adj = projection * 0.03
        if len(team_out_list) >= 5:
            injury_adj = projection * 0.05

    projection += injury_adj
    projection = max(0.5, round(projection, 1))

    # ── Edge calculation ──
    # Std dev floor raised to 3.0 to prevent overconfidence
    estimated_std = max(player_std, 3.0)

    prob_over = 1 - norm.cdf(line + 0.5, loc=projection, scale=estimated_std)
    prob_under = norm.cdf(line - 0.5, loc=projection, scale=estimated_std)

    # Fair implied probabilities (vig removed)
    impl_over = _odds_to_prob(over_odds)
    impl_under = _odds_to_prob(under_odds)
    total_impl = impl_over + impl_under
    fair_over = impl_over / total_impl if total_impl > 0 else 0.5
    fair_under = impl_under / total_impl if total_impl > 0 else 0.5

    edge_over = prob_over - fair_over
    edge_under = prob_under - fair_under

    # Pick side (threshold checked later in predict_from_props with stat-specific minimums)
    base_threshold = 0.03  # loose filter here, tightened per-stat above
    if edge_over >= base_threshold and edge_over > edge_under:
        side, edge, odds = 'OVER', edge_over, over_odds
    elif edge_under >= base_threshold and edge_under > edge_over:
        side, edge, odds = 'UNDER', edge_under, under_odds
    else:
        side, edge, odds = 'NO_BET', max(edge_over, edge_under, 0), -110

    # Confidence
    if edge >= 0.12:
        confidence = 'HIGH'
    elif edge >= 0.08:
        confidence = 'MEDIUM'
    elif edge >= 0.05:
        confidence = 'LOW'
    else:
        confidence = 'NONE'

    # Kelly sizing
    units = 0.0
    if side != 'NO_BET':
        dec_odds = _american_to_decimal(odds)
        kelly = (edge / (dec_odds - 1)) * config.KELLY_FRACTION
        kelly = max(0, min(kelly, config.MAX_SINGLE_BET_PCT))
        units = round(kelly * config.DEFAULT_BANKROLL / 100, 1)

    return {
        'player_name': player_name,
        'team': pstats.get('team', ''),
        'game_id': game['game_id'] if game else '',
        'line': line,
        'stat': stat,
        'market': prop.get('market', ''),
        'projection': projection,
        'season_avg': season_avg,
        'l5_avg': l5_avg,
        'l10_avg': l10_avg,
        'player_std': round(estimated_std, 1),
        'min_pg': pstats.get('min_pg', 0),
        'adjustment': round(injury_adj, 1),
        'side': side,
        'edge': round(edge, 4),
        'confidence': confidence,
        'over_odds': over_odds,
        'under_odds': under_odds,
        'prob_over': round(prob_over, 3),
        'prob_under': round(prob_under, 3),
        'units': units,
        'bookmaker': prop.get('bookmaker', ''),
    }


def _odds_to_prob(american_odds):
    if american_odds < 0:
        return abs(american_odds) / (abs(american_odds) + 100)
    return 100 / (american_odds + 100)


def _american_to_decimal(american_odds):
    if american_odds < 0:
        return 1 + (100 / abs(american_odds))
    return 1 + (american_odds / 100)
