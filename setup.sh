#!/bin/bash
# ═══════════════════════════════════════════════════════
# NBA Props Agent — Setup & Deploy Script
# Run this once to initialize everything
# ═══════════════════════════════════════════════════════

set -e

echo "🏀 NBA Props Agent — Setup"
echo "═══════════════════════════════════════"

# 1. Install Python dependencies
echo ""
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# 2. Initialize database
echo ""
echo "💾 Initializing database..."
python main.py --init-db

# 3. Quick validation
echo ""
echo "✅ Validating configuration..."
python -c "
import config
checks = {
    'ODDS_API_KEY': bool(config.ODDS_API_KEY),
    'ANTHROPIC_API_KEY': bool(config.ANTHROPIC_API_KEY),
    'DISCORD_WEBHOOK_URL': bool(config.DISCORD_WEBHOOK_URL),
}
for key, ok in checks.items():
    status = '✅' if ok else '⚠️  NOT SET'
    print(f'  {status} {key}')
"

# 4. Git setup and push
echo ""
echo "📤 Setting up Git repository..."
if [ ! -d ".git" ]; then
    git init
    git branch -M main
fi

# Make sure .env is NOT tracked
echo ".env" >> .gitignore
sort -u .gitignore -o .gitignore

git add -A
git commit -m "Initial commit: NBA Props Agent v1.0 — full automation pipeline"

# Set remote (if not already set)
REPO_URL="https://github.com/xSipesx/NBA-Bot-Props.git"
if git remote get-url origin 2>/dev/null; then
    git remote set-url origin "$REPO_URL"
else
    git remote add origin "$REPO_URL"
fi

echo ""
echo "Ready to push. Run:"
echo "  git push -u origin main"
echo ""

# 5. GitHub Secrets reminder
echo "═══════════════════════════════════════"
echo "⚠️  IMPORTANT: Set GitHub Secrets for automation"
echo ""
echo "Go to: https://github.com/xSipesx/NBA-Bot-Props/settings/secrets/actions"
echo ""
echo "Add these secrets:"
echo "  ODDS_API_KEY          → your rotated Odds API key"
echo "  ANTHROPIC_API_KEY     → your rotated Anthropic key"
echo "  DISCORD_WEBHOOK_URL   → your Discord webhook URL"
echo ""
echo "═══════════════════════════════════════"
echo ""

# 6. Test run option
echo "🧪 To run a test (today's slate):"
echo "  python main.py"
echo ""
echo "📊 To launch dashboard:"
echo "  streamlit run dashboard.py"
echo ""
echo "✅ Setup complete!"
