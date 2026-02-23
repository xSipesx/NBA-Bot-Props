"""
Output: Delivery — Discord (chunked), email, file.
"""

import json
import requests
from datetime import datetime
from pathlib import Path

import config


def post_to_discord(report_text, predictions=None):
    """Post report to Discord, splitting into multiple messages if needed."""
    webhook_url = config.DISCORD_WEBHOOK_URL
    if not webhook_url:
        print("  ⚠️  DISCORD_WEBHOOK_URL not set.", flush=True)
        return False

    print("📨 Posting to Discord...", flush=True)

    # ── Part 1: Embed with top plays ──
    top_plays = [p for p in (predictions or [])
                 if p.get('side') in ('OVER', 'UNDER')]
    top_plays.sort(key=lambda x: -x.get('edge', 0))

    embed = {
        "title": f"🏀 NBA Props Report — {config.get_today()}",
        "description": f"{len(top_plays)} actionable plays found",
        "color": 0x1DA1F2,
        "fields": [],
        "footer": {"text": "NBA Props Agent | Auto-generated"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    for play in top_plays[:10]:
        stat = play.get('stat', 'PTS').lower()
        emoji = "🔥" if play.get('confidence') == 'HIGH' else "⚡" if play.get('confidence') == 'MEDIUM' else "📊"
        embed["fields"].append({
            "name": f"{emoji} {play['player_name']} {play['side']} {play.get('line', '?')} {stat}",
            "value": f"Proj: {play['projection']:.1f} | Edge: +{play['edge']:.1%} | {play.get('units', 0):.1f}u",
            "inline": False,
        })

    if not embed["fields"]:
        embed["description"] = "No actionable plays found today."

    try:
        resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        resp.raise_for_status()
        print("  ✅ Embed posted", flush=True)
    except Exception as e:
        print(f"  ❌ Discord embed error: {e}", flush=True)
        return False

    # ── Part 2: Full Claude analysis, split into chunks ──
    if report_text:
        _post_chunked(webhook_url, report_text)

    return True


def _post_chunked(webhook_url, text, max_len=1900):
    """Split text into Discord-safe chunks and post each one."""
    # Split on double newlines (paragraph breaks) to keep sections intact
    paragraphs = text.split('\n\n')
    chunks = []
    current = ""

    for para in paragraphs:
        # If adding this paragraph would exceed limit, start new chunk
        if len(current) + len(para) + 2 > max_len:
            if current:
                chunks.append(current.strip())
            # If a single paragraph is too long, split on single newlines
            if len(para) > max_len:
                lines = para.split('\n')
                current = ""
                for line in lines:
                    if len(current) + len(line) + 1 > max_len:
                        if current:
                            chunks.append(current.strip())
                        current = line + "\n"
                    else:
                        current += line + "\n"
            else:
                current = para + "\n\n"
        else:
            current += para + "\n\n"

    if current.strip():
        chunks.append(current.strip())

    posted = 0
    for i, chunk in enumerate(chunks):
        try:
            requests.post(webhook_url, json={"content": chunk[:2000]}, timeout=10)
            posted += 1
        except Exception as e:
            print(f"  ⚠️  Failed to post chunk {i+1}: {e}", flush=True)
            break

    print(f"  ✅ Full analysis posted ({posted} messages, {len(text)} chars)", flush=True)


def send_email(report_text, predictions=None):
    """Send via SendGrid."""
    if not config.SENDGRID_API_KEY or not config.EMAIL_TO:
        return False

    print("📧 Sending email...", flush=True)
    payload = {
        "personalizations": [{"to": [{"email": config.EMAIL_TO}]}],
        "from": {"email": "nba-props@agent.local", "name": "NBA Props Agent"},
        "subject": f"🏀 NBA Props — {config.get_today()}",
        "content": [{"type": "text/plain", "value": report_text}],
    }

    try:
        resp = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {config.SENDGRID_API_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        success = resp.status_code in (200, 201, 202)
        print(f"  {'✅' if success else '❌'} Email {'sent' if success else 'failed'}", flush=True)
        return success
    except Exception as e:
        print(f"  ❌ Email error: {e}", flush=True)
        return False


def save_report(report_text, predictions=None, output_dir="reports"):
    """Save report and predictions to files."""
    Path(output_dir).mkdir(exist_ok=True)
    date = config.get_today()

    filepath = Path(output_dir) / f"nba_props_{date}.md"
    with open(filepath, 'w') as f:
        f.write(report_text)
    print(f"  💾 Report saved to {filepath}", flush=True)

    if predictions:
        json_path = Path(output_dir) / f"predictions_{date}.json"
        with open(json_path, 'w') as f:
            json.dump(predictions, f, indent=2, default=str)
        print(f"  💾 Predictions saved to {json_path}", flush=True)

    return str(filepath)
