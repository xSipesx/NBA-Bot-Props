"""
Output: Claude API Analysis
Sends structured data payload to Claude for final analysis,
narrative reasoning, and report generation.

This is the "brain" of the hybrid approach — Python does the math,
Claude does the reasoning.
"""

import json
import anthropic

import config


SYSTEM_PROMPT = """You are an elite NBA sports analytics agent. You receive structured data 
about today's NBA games including player stats, model projections, prop lines, injuries, 
and edge calculations. Your job is to:

1. Review each flagged +EV opportunity and provide concise matchup reasoning.
2. Identify any factors the model might miss (narrative context, motivation, rest patterns).
3. Rank the top 3-5 plays with conviction levels.
4. Flag any picks you'd override or downgrade based on your reasoning.
5. Produce the final executive summary.

Be concise and actionable. No filler. Every sentence should add analytical value.
Use the structured report format with the ============ separators for each player.
Sort the final "TOP PLAYS" section by edge, highest first.
End with risk management notes."""


def generate_claude_analysis(predictions, games, injuries, date):
    """
    Send the model's predictions + context to Claude for final analysis.

    Args:
        predictions: List of prediction dicts from the model
        games: List of game dicts
        injuries: List of injury dicts
        date: Date string

    Returns:
        String: Claude's full analysis report
    """
    if not config.ANTHROPIC_API_KEY:
        print("  ⚠️  ANTHROPIC_API_KEY not set. Generating report without Claude analysis.")
        return _generate_fallback_report(predictions, games, date)

    print("🤖 Sending to Claude for analysis...")

    # Build the data payload
    payload = _build_data_payload(predictions, games, injuries, date)

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

        message = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=config.CLAUDE_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Run today's slate. Here is the structured data:\n\n{payload}"
            }]
        )

        report = message.content[0].text
        print(f"  ✅ Claude analysis complete ({len(report)} chars)")
        return report

    except Exception as e:
        print(f"  ❌ Claude API error: {e}")
        return _generate_fallback_report(predictions, games, date)


def _build_data_payload(predictions, games, injuries, date):
    """Build the structured data string to send to Claude."""

    sections = []
    sections.append(f"# NBA PROPS DATA — {date}")
    sections.append(f"## Games on Slate: {len(games)}")

    # Games overview
    for g in games:
        sections.append(f"- {g['away']} @ {g['home']} | Status: {g.get('status', 'scheduled')}")

    # Injuries
    sections.append("\n## Injury Report")
    out_players = [i for i in injuries if i['status'] == 'OUT']
    q_players = [i for i in injuries if i['status'] == 'QUESTIONABLE']
    if out_players:
        sections.append("### OUT:")
        for i in out_players:
            sections.append(f"- {i['player_name']} ({i['team']}) — {i.get('reason', 'N/A')}")
    if q_players:
        sections.append("### QUESTIONABLE:")
        for i in q_players:
            sections.append(f"- {i['player_name']} ({i['team']}) — {i.get('reason', 'N/A')}")

    # Predictions with edge
    sections.append("\n## Model Predictions (sorted by edge)")
    bets = [p for p in predictions if p.get('side') in ('OVER', 'UNDER')]
    no_bets = [p for p in predictions if p.get('side') == 'NO BET']

    sections.append(f"\n### Flagged Bets ({len(bets)} plays):")
    for p in bets:
        sections.append(f"""
**{p['player_name']}** ({p['team']}) — {p.get('side')} {p.get('line', '?')} pts
- Season: {p['season_ppg']} PPG | L10: {p['l10_ppg']} PPG
- Model Projection: {p['projection']} pts (σ: {p['std_dev']})
- Distribution: 10th:{p['p10']} | 25th:{p['p25']} | 50th:{p['p50']} | 75th:{p['p75']} | 90th:{p['p90']}
- Line: {p.get('line', '?')} | P(Over): {p.get('prob_over', 0):.1%} | Implied: {p.get('implied_prob_over', 0):.1%}
- Edge: +{p.get('edge', 0):.1%} | Confidence: {p.get('confidence', 'N/A')}
- Suggested: {p.get('units', 0)} units | Odds: {p.get('over_odds', '-110')}/{p.get('under_odds', '-110')} [{p.get('bookmaker', '')}]
""")

    if no_bets:
        sections.append(f"\n### No Edge ({len(no_bets)} players):")
        for p in no_bets[:5]:  # just show a few
            sections.append(f"- {p['player_name']} ({p['team']}): Proj {p['projection']} vs Line {p.get('line', '?')} | Edge: {p.get('edge', 0):.1%}")

    return "\n".join(sections)


def _generate_fallback_report(predictions, games, date):
    """Generate a basic report without Claude (pure data-driven)."""

    lines = []
    lines.append(f"# NBA Player Points Props — {date}")
    lines.append(f"*{len(games)} games | Auto-generated report (no Claude analysis)*\n")

    bets = [p for p in predictions if p.get('side') in ('OVER', 'UNDER')]
    bets.sort(key=lambda x: -x.get('edge', 0))

    lines.append("## TOP PLAYS\n")
    lines.append("| Rank | Player | Bet | Line | Edge | Conf. | Units |")
    lines.append("|------|--------|-----|------|------|-------|-------|")

    for i, p in enumerate(bets[:10], 1):
        lines.append(f"| {i} | **{p['player_name']}** ({p['team']}) | {p['side']} | {p.get('line', '?')} pts | +{p.get('edge', 0):.1%} | {p.get('confidence', 'N/A')} | {p.get('units', 0)}u |")

    lines.append("\n---\n## ALL PREDICTIONS\n")

    for p in predictions:
        if p.get('line') is None:
            continue
        emoji = "🔥" if p.get('confidence') == 'HIGH' else "⚡" if p.get('confidence') == 'MEDIUM' else "➖"
        lines.append(f"{emoji} **{p['player_name']}** ({p['team']}): Proj {p['projection']} | Line {p.get('line', '?')} | {p.get('side')} | Edge: +{p.get('edge', 0):.1%} | {p.get('units', 0)}u")

    return "\n".join(lines)
