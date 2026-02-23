"""
Output: Claude API Analysis
Sends structured data to Claude for reasoning and report generation.
Updated for PTS/REB/AST props with v3 prediction fields.
"""

import json
import anthropic

import config


SYSTEM_PROMPT = """You are an elite NBA sports analytics agent. You receive structured data
about today's NBA games including player prop lines (points, rebounds, assists),
model projections, injuries, and edge calculations. Your job is to:

1. Review each flagged +EV opportunity and provide concise matchup reasoning.
2. Identify any factors the model might miss (narrative context, motivation, rest patterns).
3. Rank the top 5-8 plays with conviction levels. Include a mix of OVER and UNDER picks.
4. Flag any picks you'd override or downgrade based on your reasoning.
5. Produce the final executive summary.

Be concise and actionable. No filler. Every sentence should add analytical value.
Sort the final "TOP PLAYS" section by edge, highest first.
End with risk management notes."""


def generate_claude_analysis(predictions, games, injuries, date):
    if not config.ANTHROPIC_API_KEY:
        print("  ⚠️  ANTHROPIC_API_KEY not set. Using fallback report.", flush=True)
        return _generate_fallback_report(predictions, games, date)

    print("🤖 Sending to Claude for analysis...", flush=True)
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
        print(f"  ✅ Claude analysis complete ({len(report)} chars)", flush=True)
        return report

    except Exception as e:
        print(f"  ❌ Claude API error: {e}", flush=True)
        return _generate_fallback_report(predictions, games, date)


def _build_data_payload(predictions, games, injuries, date):
    sections = []
    sections.append(f"# NBA PROPS DATA — {date}")
    sections.append(f"## Games on Slate: {len(games)}")

    for g in games:
        sections.append(f"- {g['away']} @ {g['home']}")

    # Injuries
    sections.append("\n## Injury Report")
    out_players = [i for i in injuries if i.get('status', '').upper() == 'OUT']
    q_players = [i for i in injuries if i.get('status', '').upper() == 'QUESTIONABLE']
    if out_players:
        sections.append("### OUT:")
        for i in out_players:
            sections.append(f"- {i['player_name']} ({i['team']}) — {i.get('reason', 'N/A')}")
    if q_players:
        sections.append("### QUESTIONABLE:")
        for i in q_players:
            sections.append(f"- {i['player_name']} ({i['team']}) — {i.get('reason', 'N/A')}")

    # Predictions
    bets = [p for p in predictions if p.get('side') in ('OVER', 'UNDER')]
    bets.sort(key=lambda x: -x.get('edge', 0))
    no_bets = [p for p in predictions if p.get('side') == 'NO_BET']

    over_count = len([b for b in bets if b['side'] == 'OVER'])
    under_count = len([b for b in bets if b['side'] == 'UNDER'])

    sections.append(f"\n## Model Predictions ({len(bets)} plays: {over_count} OVER, {under_count} UNDER)")

    sections.append(f"\n### Flagged Bets ({len(bets)} plays):")
    for p in bets:
        stat = p.get('stat', 'PTS')
        sections.append(f"""
**{p['player_name']}** — {p.get('side')} {p.get('line', '?')} {stat}
- Projection: {p['projection']} {stat} (adjustment: {p.get('adjustment', 0):+.2f})
- Juice Signal: {p.get('juice_signal', 0):+.3f} | Injury Shift: {p.get('injury_shift', 0):+.1f} | Blowout Adj: {p.get('blowout_adj', 0):+.1f}
- P(Over): {p.get('prob_over', 0):.1%} | P(Under): {p.get('prob_under', 0):.1%}
- Edge: +{p.get('edge', 0):.1%} | Confidence: {p.get('confidence', 'N/A')}
- Suggested: {p.get('units', 0)} units | Odds: {p.get('over_odds', '-110')}/{p.get('under_odds', '-110')} [{p.get('bookmaker', '')}]
""")

    if no_bets:
        sections.append(f"\n### No Edge ({len(no_bets)} props):")
        for p in no_bets[:5]:
            sections.append(f"- {p['player_name']} {p.get('stat', 'PTS')}: Proj {p['projection']} vs Line {p.get('line', '?')} | Edge: {p.get('edge', 0):.1%}")

    return "\n".join(sections)


def _generate_fallback_report(predictions, games, date):
    lines = []
    lines.append(f"# NBA Player Props — {date}")
    lines.append(f"*{len(games)} games | Auto-generated report (no Claude analysis)*\n")

    bets = [p for p in predictions if p.get('side') in ('OVER', 'UNDER')]
    bets.sort(key=lambda x: -x.get('edge', 0))

    lines.append("## TOP PLAYS\n")
    lines.append("| # | Player | Stat | Bet | Line | Edge | Conf | Units |")
    lines.append("|---|--------|------|-----|------|------|------|-------|")

    for i, p in enumerate(bets[:15], 1):
        stat = p.get('stat', 'PTS')
        lines.append(f"| {i} | **{p['player_name']}** | {stat} | {p['side']} | {p.get('line', '?')} | +{p.get('edge', 0):.1%} | {p.get('confidence', 'N/A')} | {p.get('units', 0)}u |")

    lines.append(f"\n---\n*{len(bets)} total plays flagged*")
    return "\n".join(lines)
