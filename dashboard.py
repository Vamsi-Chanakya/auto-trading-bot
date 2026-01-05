"""
Trading Bot Dashboard

Run with: streamlit run dashboard.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import sqlite3
import os

# Database path
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "trades.db")

st.set_page_config(
    page_title="Trading Bot Dashboard",
    page_icon="📈",
    layout="wide"
)


def get_connection():
    """Get database connection."""
    return sqlite3.connect(DB_PATH)


@st.cache_data(ttl=60)
def load_portfolio_snapshots():
    """Load portfolio snapshots for charting."""
    conn = get_connection()
    query = """
        SELECT date, total_value, cash_balance, holdings_value,
               daily_pl, daily_pl_pct, total_pl, total_pl_pct,
               peak_value, drawdown_pct, num_holdings
        FROM portfolio_snapshots
        ORDER BY date ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
    return df


@st.cache_data(ttl=60)
def load_trades():
    """Load all trades."""
    conn = get_connection()
    query = """
        SELECT id, symbol, action, quantity, price, total_value,
               profit_loss, profit_loss_pct, hold_days,
               created_at, executed_at
        FROM trades
        ORDER BY created_at DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'])
    return df


@st.cache_data(ttl=60)
def load_holdings():
    """Load current holdings."""
    conn = get_connection()
    query = """
        SELECT symbol, quantity, avg_buy_price, total_cost,
               current_price, current_value, unrealized_pl, unrealized_pl_pct,
               stop_loss_price, take_profit_price, first_bought_at
        FROM holdings
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


@st.cache_data(ttl=60)
def load_signals():
    """Load recent signals."""
    conn = get_connection()
    query = """
        SELECT id, symbol, action, suggested_price, suggested_quantity,
               reason, status, user_response, created_at
        FROM signals
        ORDER BY created_at DESC
        LIMIT 50
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'])
    return df


def load_summary_stats():
    """Load summary statistics."""
    conn = get_connection()
    cursor = conn.cursor()

    stats = {}

    # Total trades
    cursor.execute("SELECT COUNT(*) FROM trades")
    stats['total_trades'] = cursor.fetchone()[0]

    # Winning trades
    cursor.execute("SELECT COUNT(*) FROM trades WHERE profit_loss > 0")
    stats['winning_trades'] = cursor.fetchone()[0]

    # Losing trades
    cursor.execute("SELECT COUNT(*) FROM trades WHERE profit_loss < 0")
    stats['losing_trades'] = cursor.fetchone()[0]

    # Total P&L
    cursor.execute("SELECT COALESCE(SUM(profit_loss), 0) FROM trades WHERE action='SELL'")
    stats['total_realized_pl'] = cursor.fetchone()[0]

    # Current holdings count
    cursor.execute("SELECT COUNT(*) FROM holdings")
    stats['current_holdings'] = cursor.fetchone()[0]

    # Latest portfolio value
    cursor.execute("""
        SELECT total_value, cash_balance, total_pl_pct
        FROM portfolio_snapshots
        ORDER BY date DESC LIMIT 1
    """)
    row = cursor.fetchone()
    if row:
        stats['portfolio_value'] = row[0]
        stats['cash_balance'] = row[1]
        stats['total_pl_pct'] = row[2]
    else:
        stats['portfolio_value'] = 1000  # Default starting balance
        stats['cash_balance'] = 1000
        stats['total_pl_pct'] = 0

    conn.close()
    return stats


# Dashboard Header
st.title("📈 Trading Bot Dashboard")
st.markdown("Track your paper trading performance in real-time")

# Refresh button
if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

st.divider()

# Load data
stats = load_summary_stats()
snapshots = load_portfolio_snapshots()
trades = load_trades()
holdings = load_holdings()
signals = load_signals()

# Key Metrics Row
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="Portfolio Value",
        value=f"${stats['portfolio_value']:,.2f}",
        delta=f"{stats['total_pl_pct']:.1f}%" if stats['total_pl_pct'] else None
    )

with col2:
    st.metric(
        label="Cash Balance",
        value=f"${stats['cash_balance']:,.2f}"
    )

with col3:
    st.metric(
        label="Realized P&L",
        value=f"${stats['total_realized_pl']:,.2f}",
        delta="profit" if stats['total_realized_pl'] > 0 else "loss" if stats['total_realized_pl'] < 0 else None
    )

with col4:
    win_rate = (stats['winning_trades'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
    st.metric(
        label="Win Rate",
        value=f"{win_rate:.0f}%",
        delta=f"{stats['winning_trades']}W / {stats['losing_trades']}L"
    )

st.divider()

# Portfolio Value Over Time Chart
st.subheader("💰 Portfolio Value Over Time")

if not snapshots.empty:
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=snapshots['date'],
        y=snapshots['total_value'],
        mode='lines+markers',
        name='Total Value',
        line=dict(color='#2E86AB', width=2),
        fill='tozeroy',
        fillcolor='rgba(46, 134, 171, 0.1)'
    ))

    # Add starting balance reference line
    fig.add_hline(y=1000, line_dash="dash", line_color="gray",
                  annotation_text="Starting Balance ($1,000)")

    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Portfolio Value ($)",
        hovermode='x unified',
        height=400
    )

    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No portfolio snapshots yet. Run the bot to generate data.")

# Two column layout for Holdings and Recent Trades
col1, col2 = st.columns(2)

with col1:
    st.subheader("📊 Current Holdings")
    if not holdings.empty:
        holdings_display = holdings[['symbol', 'quantity', 'avg_buy_price', 'current_price',
                                      'unrealized_pl', 'unrealized_pl_pct']].copy()
        holdings_display.columns = ['Symbol', 'Qty', 'Avg Cost', 'Current', 'P&L ($)', 'P&L (%)']
        holdings_display['Avg Cost'] = holdings_display['Avg Cost'].apply(lambda x: f"${x:.2f}")
        holdings_display['Current'] = holdings_display['Current'].apply(lambda x: f"${x:.2f}" if x else "N/A")
        holdings_display['P&L ($)'] = holdings_display['P&L ($)'].apply(lambda x: f"${x:.2f}" if x else "N/A")
        holdings_display['P&L (%)'] = holdings_display['P&L (%)'].apply(lambda x: f"{x:.1f}%" if x else "N/A")
        st.dataframe(holdings_display, use_container_width=True, hide_index=True)
    else:
        st.info("No current holdings")

with col2:
    st.subheader("🔔 Recent Signals")
    if not signals.empty:
        signals_display = signals[['created_at', 'symbol', 'action', 'status', 'user_response']].head(10).copy()
        signals_display.columns = ['Time', 'Symbol', 'Action', 'Status', 'Response']
        signals_display['Time'] = signals_display['Time'].dt.strftime('%m/%d %H:%M')
        st.dataframe(signals_display, use_container_width=True, hide_index=True)
    else:
        st.info("No signals generated yet")

st.divider()

# Trade History
st.subheader("📜 Trade History")

if not trades.empty:
    trades_display = trades[['created_at', 'symbol', 'action', 'quantity', 'price',
                              'total_value', 'profit_loss', 'profit_loss_pct']].copy()
    trades_display.columns = ['Date', 'Symbol', 'Action', 'Qty', 'Price', 'Total', 'P&L ($)', 'P&L (%)']
    trades_display['Date'] = trades_display['Date'].dt.strftime('%Y-%m-%d %H:%M')
    trades_display['Price'] = trades_display['Price'].apply(lambda x: f"${x:.2f}")
    trades_display['Total'] = trades_display['Total'].apply(lambda x: f"${x:.2f}")
    trades_display['P&L ($)'] = trades_display['P&L ($)'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "-")
    trades_display['P&L (%)'] = trades_display['P&L (%)'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "-")

    st.dataframe(trades_display, use_container_width=True, hide_index=True)

    # P&L by Trade chart
    sell_trades = trades[trades['action'] == 'SELL'].copy()
    if not sell_trades.empty:
        st.subheader("📉 P&L by Trade")
        fig = px.bar(
            sell_trades,
            x='symbol',
            y='profit_loss',
            color='profit_loss',
            color_continuous_scale=['red', 'gray', 'green'],
            color_continuous_midpoint=0,
            title="Profit/Loss per Closed Trade"
        )
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No trades executed yet. Run the bot to start trading!")

# Footer
st.divider()
st.markdown("""
<div style='text-align: center; color: gray;'>
    <small>Auto Trading Bot Dashboard | Paper Trading Mode | Data refreshes every 60 seconds</small>
</div>
""", unsafe_allow_html=True)
