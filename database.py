"""
NBA Props Agent — Database Layer
SQLite database for storing game data, predictions, bets, and results.
"""

import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager
import config


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist."""
    with get_db() as conn:
        conn.executescript("""
            -- Daily game schedule
            CREATE TABLE IF NOT EXISTS games (
                game_id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                home_score INTEGER,
                away_score INTEGER,
                spread REAL,
                total REAL,
                status TEXT DEFAULT 'scheduled',
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Player season + recent stats snapshot (one row per player per date)
            CREATE TABLE IF NOT EXISTS player_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                player_id INTEGER NOT NULL,
                player_name TEXT NOT NULL,
                team TEXT NOT NULL,
                position TEXT,
                season_ppg REAL,
                season_min REAL,
                season_usg REAL,
                season_ts_pct REAL,
                l5_ppg REAL,
                l10_ppg REAL,
                std_dev REAL,
                game_log_json TEXT,  -- JSON array of last 20 game point totals
                UNIQUE(date, player_id)
            );

            -- Sportsbook prop lines
            CREATE TABLE IF NOT EXISTS prop_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                player_id INTEGER,
                player_name TEXT NOT NULL,
                team TEXT,
                market TEXT DEFAULT 'player_points',
                line REAL NOT NULL,
                over_odds INTEGER,   -- American odds (e.g., -110, +105)
                under_odds INTEGER,
                bookmaker TEXT,
                fetched_at TEXT DEFAULT (datetime('now')),
                UNIQUE(date, player_name, bookmaker)
            );

            -- Injury reports
            CREATE TABLE IF NOT EXISTS injuries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                player_name TEXT NOT NULL,
                team TEXT NOT NULL,
                status TEXT NOT NULL,  -- OUT, DOUBTFUL, QUESTIONABLE, PROBABLE
                reason TEXT,
                fetched_at TEXT DEFAULT (datetime('now')),
                UNIQUE(date, player_name)
            );

            -- Team context (defensive ratings, pace, etc.)
            CREATE TABLE IF NOT EXISTS team_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                team TEXT NOT NULL,
                def_rating REAL,
                pace REAL,
                opp_ppg_allowed REAL,
                opp_ppg_allowed_pg REAL,
                opp_ppg_allowed_sg REAL,
                opp_ppg_allowed_sf REAL,
                opp_ppg_allowed_pf REAL,
                opp_ppg_allowed_c REAL,
                UNIQUE(date, team)
            );

            -- Model predictions
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                game_id TEXT,
                player_name TEXT NOT NULL,
                team TEXT,
                position TEXT,
                projection REAL NOT NULL,
                std_dev REAL,
                p10 REAL,
                p25 REAL,
                p50 REAL,
                p75 REAL,
                p90 REAL,
                line REAL,
                prob_over REAL,
                implied_prob_over REAL,
                edge REAL,
                side TEXT,          -- OVER, UNDER, NO BET
                confidence TEXT,    -- LOW, MEDIUM, HIGH
                units REAL,
                reasoning TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(date, player_name)
            );

            -- Bet log (locked picks that were actually wagered or recommended)
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                player_name TEXT NOT NULL,
                team TEXT,
                game_id TEXT,
                side TEXT NOT NULL,       -- OVER or UNDER
                line REAL NOT NULL,
                odds INTEGER NOT NULL,    -- American odds on the side we bet
                edge REAL,
                confidence TEXT,
                units REAL NOT NULL,
                actual_points REAL,       -- filled by grader
                result TEXT,              -- WIN, LOSS, PUSH, DNP
                pnl REAL,                 -- profit/loss in units
                graded_at TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Daily summary
            CREATE TABLE IF NOT EXISTS daily_summary (
                date TEXT PRIMARY KEY,
                total_bets INTEGER,
                wins INTEGER,
                losses INTEGER,
                pushes INTEGER,
                dnps INTEGER,
                total_units_wagered REAL,
                total_pnl REAL,
                roi REAL,
                report_text TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Model performance tracking
            CREATE TABLE IF NOT EXISTS model_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_start TEXT,
                period_end TEXT,
                total_predictions INTEGER,
                brier_score REAL,
                hit_rate REAL,
                roi REAL,
                avg_edge REAL,
                by_confidence_json TEXT,  -- JSON breakdown
                calibration_json TEXT,    -- JSON calibration curve data
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
    print("✅ Database initialized successfully.")


def store_games(games, date):
    """Store game schedule."""
    with get_db() as conn:
        for g in games:
            conn.execute("""
                INSERT OR REPLACE INTO games (game_id, date, home_team, away_team, spread, total, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (g['game_id'], date, g['home'], g['away'], g.get('spread'), g.get('total'), g.get('status', 'scheduled')))


def store_player_stats(stats, date):
    """Store player stats snapshot."""
    with get_db() as conn:
        for s in stats:
            conn.execute("""
                INSERT OR REPLACE INTO player_stats
                (date, player_id, player_name, team, position, season_ppg, season_min, season_usg, season_ts_pct, l5_ppg, l10_ppg, std_dev, game_log_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (date, s['player_id'], s['player_name'], s['team'], s.get('position'),
                  s['season_ppg'], s['season_min'], s.get('season_usg'), s.get('season_ts_pct'),
                  s.get('l5_ppg'), s.get('l10_ppg'), s.get('std_dev'),
                  json.dumps(s.get('game_log', []))))


def store_prop_lines(lines, date):
    """Store prop lines."""
    with get_db() as conn:
        for l in lines:
            conn.execute("""
                INSERT OR REPLACE INTO prop_lines
                (date, player_id, player_name, team, market, line, over_odds, under_odds, bookmaker)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (date, l.get('player_id'), l['player_name'], l.get('team'), 'player_points',
                  l['line'], l['over_odds'], l['under_odds'], l['bookmaker']))


def store_injuries(injuries, date):
    """Store injury report."""
    with get_db() as conn:
        for i in injuries:
            conn.execute("""
                INSERT OR REPLACE INTO injuries (date, player_name, team, status, reason)
                VALUES (?, ?, ?, ?, ?)
            """, (date, i['player_name'], i['team'], i['status'], i.get('reason')))


def store_predictions(predictions, date):
    """Store model predictions."""
    with get_db() as conn:
        for p in predictions:
            conn.execute("""
                INSERT OR REPLACE INTO predictions
                (date, game_id, player_name, team, position, projection, std_dev,
                 p10, p25, p50, p75, p90, line, prob_over, implied_prob_over,
                 edge, side, confidence, units, reasoning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (date, p.get('game_id'), p['player_name'], p.get('team'), p.get('position'),
                  p['projection'], p.get('std_dev'), p.get('p10'), p.get('p25'), p.get('p50'),
                  p.get('p75'), p.get('p90'), p.get('line'), p.get('prob_over'),
                  p.get('implied_prob_over'), p.get('edge'), p.get('side'),
                  p.get('confidence'), p.get('units'), p.get('reasoning')))


def store_bet(bet, date):
    """Store a locked bet."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO bets (date, player_name, team, game_id, side, line, odds, edge, confidence, units)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (date, bet['player_name'], bet.get('team'), bet.get('game_id'),
              bet['side'], bet['line'], bet['odds'], bet.get('edge'),
              bet.get('confidence'), bet['units']))


def get_ungraded_bets(date):
    """Get bets that haven't been graded yet."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM bets WHERE date = ? AND result IS NULL", (date,)
        ).fetchall()
        return [dict(r) for r in rows]


def grade_bet(bet_id, actual_points, result, pnl):
    """Grade a single bet."""
    with get_db() as conn:
        conn.execute("""
            UPDATE bets SET actual_points = ?, result = ?, pnl = ?, graded_at = datetime('now')
            WHERE id = ?
        """, (actual_points, result, pnl, bet_id))


def get_performance_summary(days=30):
    """Get aggregate performance over the last N days."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total_bets,
                SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN result = 'PUSH' THEN 1 ELSE 0 END) as pushes,
                SUM(units) as total_wagered,
                SUM(COALESCE(pnl, 0)) as total_pnl,
                AVG(edge) as avg_edge
            FROM bets
            WHERE date >= date('now', ?) AND result IS NOT NULL
        """, (f'-{days} days',)).fetchone()
        return dict(row) if row else {}


if __name__ == "__main__":
    init_db()
