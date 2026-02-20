"""
NBA Props Agent — Prediction Engine (Cloud-Optimized)
Works entirely from Odds API prop lines + ESPN injuries.
No nba_api dependency.

The key insight: the sportsbook line IS the market's best projection.
We look for spots where injuries, matchups, or situations create edges
that the line hasn't fully priced in.
"""

import numpy as np
from scipy.stats import norm
import config


def predict_from_props(raw_props, games, injuries):
    """
    Generate predictions for all players with prop lines.
    
    The sportsbook line is our baseline. We adjust for:
    - Injuries to teammates (usage redistribution → boost)
    - Injuries to key opponents (weaker defense → boost)
    - Game environment (pace, blowout risk)
    """
    # Build injury context per team
    team_out_players = {}
    for inj in injuries:
        team = inj.get('team', '')
        status = inj.get('status', '').upper()
        if status in ('OUT', 'SUSPENDED'):
            if team not in team_out_players:
                team_out_players[team] = []
            team_out_players[team].append(inj)

    # Build game lookup
    game_lookup = {}
    for g in games:
        game_lookup[f"{g['away']}@{g['home']}"] = g
        # Also map by team name for prop matching
        game_lookup[g['home']] = g
        game_lookup[g['away']] = g

    predictions = []
    for prop in raw_props:
        player_name = prop['player_name']
        line = prop['line']
        over_odds = prop.get('over_odds', -110)
        under_odds = prop.get('under_odds', -110)
        bookmaker = prop.get('bookmaker', '')
        game_str = prop.get('game', '')

        # Find the game for this player
        game = None
        for g in games:
            if game_str and (g['home'] in game_str or g['away'] in game_str):
                game = g
                break

        # Start with the line as our baseline (market projection)
        projection = line

        # ── Adjustment 1: Teammate injuries (usage boost) ──
        # If key teammates are out, remaining players get more touches
        teammate_boost = 0.0
        if game:
            # Figure out which team this player is on (approximate from game context)
            home_out = team_out_players.get(game['home'], [])
            away_out = team_out_players.get(game['away'], [])
            
            # Check if significant players are out on either team
            for team_abbrev, out_list in [(game['home'], home_out), (game['away'], away_out)]:
                key_outs = [p for p in out_list if p.get('status', '').upper() in ('OUT', 'SUSPENDED')]
                if len(key_outs) >= 2:
                    # Multiple key players out → remaining players get usage boost
                    # This is a conservative estimate
                    teammate_boost = 1.0 + (0.5 * (len(key_outs) - 2))
                    teammate_boost = min(teammate_boost, 3.0)  # cap at +3 pts

        # ── Adjustment 2: Opponent weakness ──
        opponent_boost = 0.0
        if game:
            opp_out = team_out_players.get(game['home'], []) + team_out_players.get(game['away'], [])
            key_opp_outs = [p for p in opp_out if p.get('status', '').upper() in ('OUT', 'SUSPENDED')]
            if len(key_opp_outs) >= 3:
                opponent_boost = 0.5  # weaker opponent → slight scoring boost

        # Apply adjustments
        total_adjustment = teammate_boost + opponent_boost
        projection = line + total_adjustment

        # ── Edge Calculation ──
        # Estimate probability using normal distribution
        # Typical NBA player std dev is ~7 points for 20+ PPG scorers
        estimated_std = max(line * 0.28, 4.0)  # ~28% of line as std dev

        prob_over = 1 - norm.cdf(line, loc=projection, scale=estimated_std)
        prob_under = norm.cdf(line, loc=projection, scale=estimated_std)

        # Implied probabilities from odds
        impl_over = _odds_to_probability(over_odds)
        impl_under = _odds_to_probability(under_odds)

        edge_over = prob_over - impl_over
        edge_under = prob_under - impl_under

        # Pick the side with better edge
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
            edge = max(edge_over, edge_under)
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

        # Kelly criterion bet sizing
        units = 0.0
        if side != 'NO_BET':
            decimal_odds = _american_to_decimal(odds)
            kelly = (edge / (decimal_odds - 1)) * config.KELLY_FRACTION
            kelly = max(0, min(kelly, config.MAX_SINGLE_BET_PCT))
            units = round(kelly * config.DEFAULT_BANKROLL / 100, 1)

        pred = {
            'player_name': player_name,
            'team': prop.get('team', ''),
            'game_id': game['game_id'] if game else '',
            'line': line,
            'projection': round(projection, 1),
            'adjustment': round(total_adjustment, 1),
            'side': side,
            'edge': round(edge, 4),
            'confidence': confidence,
            'over_odds': over_odds,
            'under_odds': under_odds,
            'prob_over': round(prob_over, 3),
            'prob_under': round(prob_under, 3),
            'units': units,
            'bookmaker': bookmaker,
        }
        predictions.append(pred)

    print(f"\n🎯 Predictions generated for {len(predictions)} players", flush=True)
    return predictions


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
