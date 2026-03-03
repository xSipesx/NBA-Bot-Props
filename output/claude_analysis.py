"""
Output: Claude API Analysis — v6
Now sends real player stats to Claude for informed reasoning.
"""

import anthropic
import config

SYSTEM_PROMPT = """You are an elite NBA sports analytics agent. You receive structured data
about today's NBA games including REAL player statistics (season averages, last 5/10 game
averages, standard deviation), prop lines from sportsbooks, and model projections.

Your job:
1. Review each flagged opportunity — the model has real stat-based projections vs the line.
2. Add matchup context the model misses: pace, defensive matchups, motivation, rest.
3. Rank the top 5-8 plays with conviction levels. Include a mix of PTS, REB, AST and OVER/UNDER.
4. Override or downgrade any picks where context contradicts the stats.
5. Note which plays are highest conviction and why.

Be concise and actionable. No filler. Use the player's actual stats to justify each pick.
End with risk management notes."""


def generate_claude_analysis(predictions, games, injuries, date):
    if not config.ANTHROPIC_API_KEY:
        print("  ⚠️  No API key. Using fallback.", flush=True)
        return _generate_fallback_report(predictions, games, date)

    print("🤖 Sending to Claude for analysis...", flush=True)
    payload = _build_data_payload(predictions, games, injuries, date)

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=config.CLAUDE_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Analyze today's slate:\n\n{payload}"}]
        )
        report = message.content[0].text
        print(f"  ✅ Claude analysis complete ({len(report)} chars)", flush=True)
        return report
    except Exception as e:
        print(f"  ❌ Claude API error: {e}", flush=True)
        return _generate_fallback_report(predictions, games, date)


def _build_data_payload(predictions, games, injuries, date):
    sections = []
    sections.append(f"# NBA PROPS DATA — {date}")
    sections.append(f"## {len(games)} Games")
    for g in games:
        sections.append(f"- {g['away']} @ {g['home']}")

    # Injuries
    sections.append("\n## Injuries")
    out = [i for i in injuries if i.get('status', '').upper() == 'OUT']
    if out:
        for i in out:
            sections.append(f"- {i['player_name']} ({i['team']}) OUT — {i.get('reason', '')}")

    # Predictions with real stats
    bets = [p for p in predictions if p.get('side') in ('OVER', 'UNDER')]
    bets.sort(key=lambda x: -x.get('edge', 0))
    no_bets = [p for p in predictions if p.get('side') == 'NO_BET']

    sections.append(f"\n## Flagged Plays ({len(bets)})")
    for p in bets:
        stat = p.get('stat', 'PTS')
        sections.append(f"""
**{p['player_name']}** ({p.get('team','')}) — {p['side']} {p['line']} {stat}
- Season avg: {p.get('season_avg', '?')} | L10: {p.get('l10_avg', '?')} | L5: {p.get('l5_avg', '?')}
- Projection: {p['projection']} (std: {p.get('player_std', '?')}) | Minutes: {p.get('min_pg', '?')} MPG
- P(Over): {p.get('prob_over', 0):.1%} | P(Under): {p.get('prob_under', 0):.1%}
- Edge: +{p.get('edge', 0):.1%} | Confidence: {p.get('confidence', 'N/A')}
- Units: {p.get('units', 0)} | Odds: {p.get('over_odds', '')}/{p.get('under_odds', '')} [{p.get('bookmaker', '')}]
""")

    if no_bets:
        sections.append(f"\n## Near-misses ({len(no_bets)} props analyzed, no edge)")
        for p in sorted(no_bets, key=lambda x: -x.get('edge', 0))[:5]:
            sections.append(f"- {p['player_name']} {p.get('stat','PTS')}: proj {p['projection']} vs line {p['line']} | edge {p.get('edge',0):.1%}")

    return "\n".join(sections)


def _generate_fallback_report(predictions, games, date):
    lines = []
    lines.append(f"# NBA Player Props — {date}")
    lines.append(f"*{len(games)} games | Fallback report*\n")

    bets = [p for p in predictions if p.get('side') in ('OVER', 'UNDER')]
    bets.sort(key=lambda x: -x.get('edge', 0))

    for i, p in enumerate(bets[:15], 1):
        stat = p.get('stat', 'PTS')
        lines.append(f"{i}. **{p['player_name']}** ({p.get('team','')}) {p['side']} {p['line']} {stat} | "
                     f"Proj: {p['projection']} (ssn: {p.get('season_avg','?')}) | Edge: +{p.get('edge',0):.1%} | {p.get('units',0)}u")

    return "\n".join(lines)
