"""
NBA Props Agent — Streamlit Dashboard

Run with: streamlit run dashboard.py

Tabs:
1. Today's Picks — current day's predictions and top plays
2. Bet Tracker — historical results, P&L chart
3. Model Performance — calibration, hit rate by confidence, ROI
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

import config


st.set_page_config(
    page_title="NBA Props Agent",
    page_icon="🏀",
    layout="wide",
)

# ── Database connection ──
@st.cache_resource
def get_connection():
    return sqlite3.connect(config.DB_PATH, check_same_thread=False)


def query_db(sql, params=None):
    conn = get_connection()
    return pd.read_sql_query(sql, conn, params=params or [])


# ── Header ──
st.title("🏀 NBA Props Agent")
st.markdown(f"*Last updated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}*")

# ── Tabs ──
tab1, tab2, tab3 = st.tabs(["📋 Today's Picks", "📊 Bet Tracker", "🎯 Model Performance"])


# ═══════════════════════════════════════════
# TAB 1: Today's Picks
# ═══════════════════════════════════════════
with tab1:
    today = config.get_today()
    st.subheader(f"Picks for {today}")

    predictions = query_db(
        "SELECT * FROM predictions WHERE date = ? ORDER BY edge DESC",
        [today]
    )

    if predictions.empty:
        st.info("No predictions yet for today. Run the pipeline first: `python main.py`")
    else:
        # Top plays
        bets = predictions[predictions['side'].isin(['OVER', 'UNDER'])]
        no_edge = predictions[~predictions['side'].isin(['OVER', 'UNDER'])]

        if not bets.empty:
            st.markdown("### 🔥 Top Plays")

            cols = st.columns(min(len(bets), 4))
            for i, (_, play) in enumerate(bets.head(4).iterrows()):
                with cols[i]:
                    confidence_color = {
                        'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '🟢'
                    }.get(play['confidence'], '⚪')

                    st.metric(
                        label=f"{confidence_color} {play['player_name']}",
                        value=f"{play['side']} {play['line']} pts",
                        delta=f"+{play['edge']:.1%} edge | {play['units']:.1f}u",
                    )
                    st.caption(f"Proj: {play['projection']:.1f} | σ: {play['std_dev']:.1f}")

            st.markdown("### Full Picks Table")
            display_cols = ['player_name', 'team', 'side', 'line', 'projection', 'prob_over',
                           'edge', 'confidence', 'units', 'p10', 'p25', 'p50', 'p75', 'p90']
            available_cols = [c for c in display_cols if c in bets.columns]
            st.dataframe(
                bets[available_cols].style.format({
                    'projection': '{:.1f}',
                    'prob_over': '{:.1%}',
                    'edge': '{:.1%}',
                    'units': '{:.1f}',
                }),
                use_container_width=True,
            )

        if not no_edge.empty:
            with st.expander(f"No Edge Players ({len(no_edge)})"):
                st.dataframe(
                    no_edge[['player_name', 'team', 'projection', 'line', 'edge']].head(20),
                    use_container_width=True,
                )


# ═══════════════════════════════════════════
# TAB 2: Bet Tracker
# ═══════════════════════════════════════════
with tab2:
    st.subheader("Bet Tracker")

    bets_df = query_db(
        "SELECT * FROM bets WHERE result IS NOT NULL ORDER BY date DESC"
    )

    if bets_df.empty:
        st.info("No graded bets yet. Run `python main.py --grade` after games complete.")
    else:
        # Summary metrics
        col1, col2, col3, col4, col5 = st.columns(5)

        total = len(bets_df[bets_df['result'].isin(['WIN', 'LOSS'])])
        wins = len(bets_df[bets_df['result'] == 'WIN'])
        losses = len(bets_df[bets_df['result'] == 'LOSS'])
        total_pnl = bets_df['pnl'].sum()
        total_wagered = bets_df['units'].sum()
        roi = (total_pnl / total_wagered * 100) if total_wagered > 0 else 0

        col1.metric("Record", f"{wins}W - {losses}L")
        col2.metric("Hit Rate", f"{wins/total:.1%}" if total > 0 else "N/A")
        col3.metric("Total P&L", f"{total_pnl:+.1f}u")
        col4.metric("ROI", f"{roi:+.1f}%")
        col5.metric("Avg Edge", f"{bets_df['edge'].mean():.1%}")

        # Cumulative P&L chart
        st.markdown("### Cumulative P&L")
        bets_sorted = bets_df.sort_values('date')
        bets_sorted['cumulative_pnl'] = bets_sorted['pnl'].cumsum()

        fig = px.line(
            bets_sorted, x='date', y='cumulative_pnl',
            title='Cumulative P&L (units)',
            labels={'cumulative_pnl': 'Units', 'date': 'Date'},
        )
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        st.plotly_chart(fig, use_container_width=True)

        # P&L by confidence
        st.markdown("### P&L by Confidence")
        conf_summary = bets_df.groupby('confidence').agg(
            bets=('result', 'count'),
            wins=('result', lambda x: (x == 'WIN').sum()),
            pnl=('pnl', 'sum'),
            avg_edge=('edge', 'mean'),
        ).reset_index()
        conf_summary['hit_rate'] = conf_summary['wins'] / conf_summary['bets']
        st.dataframe(conf_summary, use_container_width=True)

        # Recent bets
        st.markdown("### Recent Bets")
        recent_display = bets_df.head(30)[['date', 'player_name', 'side', 'line', 'actual_points', 'result', 'pnl', 'edge', 'confidence']]
        st.dataframe(
            recent_display.style.applymap(
                lambda x: 'color: green' if x == 'WIN' else 'color: red' if x == 'LOSS' else '',
                subset=['result']
            ),
            use_container_width=True,
        )


# ═══════════════════════════════════════════
# TAB 3: Model Performance
# ═══════════════════════════════════════════
with tab3:
    st.subheader("Model Performance")

    all_preds = query_db(
        "SELECT p.*, b.actual_points, b.result FROM predictions p "
        "LEFT JOIN bets b ON p.date = b.date AND p.player_name = b.player_name "
        "WHERE b.result IS NOT NULL"
    )

    if all_preds.empty:
        st.info("Not enough data yet. Need graded bets to analyze model performance.")
    else:
        # Projection accuracy
        st.markdown("### Projection Accuracy")
        all_preds['error'] = all_preds['projection'] - all_preds['actual_points']
        all_preds['abs_error'] = all_preds['error'].abs()

        col1, col2, col3 = st.columns(3)
        col1.metric("Mean Absolute Error", f"{all_preds['abs_error'].mean():.1f} pts")
        col2.metric("Mean Error (Bias)", f"{all_preds['error'].mean():+.1f} pts")
        col3.metric("Median Abs Error", f"{all_preds['abs_error'].median():.1f} pts")

        # Scatter: Projected vs Actual
        fig = px.scatter(
            all_preds, x='projection', y='actual_points',
            color='result',
            color_discrete_map={'WIN': 'green', 'LOSS': 'red', 'PUSH': 'gray'},
            title='Projected vs Actual Points',
            labels={'projection': 'Model Projection', 'actual_points': 'Actual Points'},
        )
        fig.add_trace(go.Scatter(x=[0, 50], y=[0, 50], mode='lines', name='Perfect', line=dict(dash='dash', color='gray')))
        st.plotly_chart(fig, use_container_width=True)

        # Hit rate by edge bucket
        st.markdown("### Hit Rate by Edge Size")
        all_preds['edge_bucket'] = pd.cut(
            all_preds['edge'] * 100,
            bins=[0, 3, 5, 8, 12, 100],
            labels=['0-3%', '3-5%', '5-8%', '8-12%', '12%+']
        )
        edge_perf = all_preds.groupby('edge_bucket', observed=True).agg(
            total=('result', 'count'),
            wins=('result', lambda x: (x == 'WIN').sum()),
            pnl=('pnl', 'sum'),
        ).reset_index()
        edge_perf['hit_rate'] = edge_perf['wins'] / edge_perf['total']

        fig = px.bar(edge_perf, x='edge_bucket', y='hit_rate',
                     title='Hit Rate by Edge Size',
                     labels={'hit_rate': 'Hit Rate', 'edge_bucket': 'Edge Bucket'})
        fig.add_hline(y=0.5, line_dash="dash", line_color="red", annotation_text="50%")
        st.plotly_chart(fig, use_container_width=True)

    # Footer
    st.markdown("---")
    st.caption("NBA Props Agent | Hybrid Python + Claude AI | Not financial advice. Bet responsibly.")
