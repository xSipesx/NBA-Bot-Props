"""
Output: Delivery
Sends the final report via Discord webhook, email, or saves to file.
"""

import json
import requests
from datetime import datetime
from pathlib import Path

import config


def post_to_discord(report_text, predictions=None):
    """Post the report to a Discord channel via webhook."""
    webhook_url = config.DISCORD_WEBHOOK_URL
    if not webhook_url:
        print("  ⚠️  DISCORD_WEBHOOK_URL not set. Skipping Discord delivery.")
        return False

    print("📨 Posting to Discord...")

    top_plays = [p for p in (predictions or [])
                 if p.get('side') in ('OVER', 'UNDER') and p.get('confidence') in ('HIGH', 'MEDIUM')]
    top_plays.sort(key=lambda x: -x.get('edge', 0))

    embed = {
        "title": f"🏀 NBA Props Report — {config.get_today()}",
        "description": f"{len(top_plays)} actionable plays found",
        "color": 0x1DA1F2,
        "fields": [],
        "footer": {"text": "NBA Props Agent | Auto-generated"},
        "timestamp": datetime.utcnow().isoformat(),
    }

    for play in top_plays[:5]:
        emoji = "🔥" if play.get('confidence') == 'HIGH' else "⚡"
        embed["fields"].append({
            "name": f"{emoji} {play['player_name']} {play['side']} {play.get('line', '?')} pts",
            "value": f"Proj: {play['projection']:.1f} | Edge: +{play['edge']:.1%} | {play.get('units', 0):.1f}u",
            "inline": False,
        })

    if not embed["fields"]:
        embed["description"] = "No high-conviction plays found today."

    try:
        resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        resp.raise_for_status()

        if report_text:
            truncated = report_text[:1900] + "\n*[truncated]*" if len(report_text) > 1900 else report_text
            requests.post(webhook_url, json={"content": f"```\n{truncated}\n```"}, timeout=10)

        print("  ✅ Discord delivery successful")
        return True
    except Exception as e:
        print(f"  ❌ Discord error: {e}")
        return False


def send_email(report_text, predictions=None):
    """Send the report via SendGrid email."""
    if not config.SENDGRID_API_KEY or not config.EMAIL_TO:
        print("  ⚠️  Email not configured. Skipping.")
        return False

    print("📧 Sending email report...")
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
        print(f"  {'✅' if success else '❌'} Email {'sent' if success else 'failed'}")
        return success
    except Exception as e:
        print(f"  ❌ Email error: {e}")
        return False


def save_report(report_text, predictions=None, output_dir="reports"):
    """Save report and raw predictions to local files."""
    Path(output_dir).mkdir(exist_ok=True)
    date = config.get_today()

    filepath = Path(output_dir) / f"nba_props_{date}.md"
    with open(filepath, 'w') as f:
        f.write(report_text)
    print(f"  💾 Report saved to {filepath}")

    if predictions:
        json_path = Path(output_dir) / f"predictions_{date}.json"
        with open(json_path, 'w') as f:
            json.dump(predictions, f, indent=2, default=str)
        print(f"  💾 Predictions saved to {json_path}")

    return str(filepath)
