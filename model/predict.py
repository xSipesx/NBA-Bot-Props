"""
NBA Props Agent — Prediction Engine v6

FUNDAMENTAL CHANGE: Uses actual player stats (from ESPN) to build
independent projections, then compares against sportsbook lines.

Projection = weighted blend of:
  - Season average (35%)
  - Last 10 games (35%)
  - Last 5 games (30%)
  
Adjusted for minutes trend.

Edge = Model probability vs implied probability from odds.
Only flags plays on rotation players (20+ MPG) with meaningful lines.
"""

from scipy.stats import norm
import config


# Minimum line thresholds — ignore tiny props nobody would bet
MIN_LINE = {
    'PTS': 8.5,    # ignore sub-8.5 point props
    'REB': 2.5,    # ignore sub-2.5 rebound props
    'AST': 1.5,    # ignore sub-1.5 assist props
}

# Minimum minutes to consider a player
MIN_MINUTES = 20


def predict_from_props(raw_props, games, injuries, player_stats):
    """
    Generate predictions by comparing ESPN-based projections vs prop lines.
    
    Args:
        raw_props: list of prop dicts from Odds API
        games: list of game dicts
        injuries: list of injury dicts
        player_stats: list of player dicts from ESPN with season/recent averages
    """
    # Index player stats by name for fast lookup
    stats_by_name = {}
    for p in player_stats:
        stats_by_name[p['name']] = p

    # Build injury out list by team
    team_outs = {}
    for inj in injuries:
        if inj.get('status', '').upper() in ('OUT', 'SUSPENDED'):
            team_outs.setdefault(inj.get('team', ''), []).append(inj)

    predictions = []
    skipped_no_stats = 0
    skipped_low_line = 0
    skipped_low_min = 0

    for prop in raw_props:
        player_name = prop['player_name']
        line = prop['line']
        stat = prop.get('stat', 'PTS')
        market = prop.get('market', 'player_points')

        # Skip tiny props
        if line < MIN_LINE.get(stat, 2.5):
            skipped_low_line += 1
            continue

        # Find player stats (try exact match, then fuzzy)
        pstats = stats_by_name.get(player_name)
        if not pstats:
            # Try matching by last name
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
            predictions.append(pred)

    predictions.sort(key=lambda x: -abs(x.get('edge', 0)))

    actionable = [p for p in predictions if p['side'] != 'NO_BET']
    over_ct = len([p for p in actionable if p['side'] == 'OVER'])
    under_ct = len([p for p in actionable if p['side'] == 'UNDER'])
    
    print(f"\n🎯 Predictions: {len(predictions)} analyzed, {len(actionable)} actionable "
          f"({over_ct} OVER, {under_ct} UNDER)", flush=True)
    print(f"   Skipped: {skipped_no_stats} no stats, {skipped_low_line} low line, "
          f"{skipped_low_min} low minutes", flush=True)
    return predictions


def _predict_single(prop, pstats, games, team_outs):
    """Build a projection and compare to the line."""
    player_name = prop['player_name']
    line = prop['line']
    over_odds = prop.get('over_odds', -110)
    under_odds = prop.get('under_odds', -110)
    stat = prop.get('stat', 'PTS')

    # Find game
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

    # Skip if we don't have real data
    if season_avg == 0 and l10_avg == 0:
        return None

    # Weighted projection
    projection = (0.35 * season_avg) + (0.35 * l10_avg) + (0.30 * l5_avg)

    # Minutes trend adjustment
    min_pg = pstats.get('min_pg', 30)
    min_l5 = pstats.get('min_l5', min_pg)
    if min_pg > 0:
        min_ratio = min_l5 / min_pg
        min_ratio = max(0.85, min(1.15, min_ratio))
        projection *= min_ratio

    # Injury boost: if teammates are out, slight usage bump for remaining players
    injury_adj = 0.0
    if game:
        player_team = pstats.get('team', '')
        team_out_list = team_outs.get(player_team, [])
        if len(team_out_list) >= 2 and stat == 'PTS':
            injury_adj = projection * 0.03  # 3% scoring bump
        if len(team_out_list) >= 4 and stat == 'PTS':
            injury_adj = projection * 0.06  # 6% bump for decimated teams

    projection += injury_adj
    projection = max(0.5, round(projection, 1))

    # ── Edge calculation ──
    # Use the player's ACTUAL std dev from their game log
    estimated_std = max(player_std, 2.0)

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

    # Cap at 15% — anything higher is suspicious
    edge_over = min(edge_over, 0.15)
    edge_under = min(edge_under, 0.15)

    # Pick side
    if edge_over >= config.MIN_EDGE_THRESHOLD and edge_over > edge_under:
        side, edge, odds = 'OVER', edge_over, over_odds
    elif edge_under >= config.MIN_EDGE_THRESHOLD and edge_under > edge_over:
        side, edge, odds = 'UNDER', edge_under, under_odds
    else:
        side, edge, odds = 'NO_BET', max(edge_over, edge_under, 0), -110

    # Confidence
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
