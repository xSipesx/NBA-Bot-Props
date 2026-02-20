"""
Ingest: Team Context — only used for local runs.
Cloud pipeline doesn't need this.
"""

def get_team_context():
    return {}

def get_projected_game_pace(home_ctx, away_ctx):
    return 100.0
