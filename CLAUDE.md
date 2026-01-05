# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Auto Trading Bot for US stocks using Webull. Screens for undervalued stocks near 52-week lows, sends SMS approval requests via Twilio, and executes trades with strict risk controls.

**Key Constraints:**
- No hardcoded credentials (uses macOS Keychain)
- Paper trading mode by default
- Max 2 holdings at any time
- Stop-loss at -5%, take-profit at +10%
- SMS approval required before every trade
- No day trading, no naked options

## Commands

```bash
# Install dependencies
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# First-time setup (configure credentials)
python src/credentials.py --setup

# Check credential status
python src/credentials.py --status

# Start the trading bot
python -m src.main

# Run single scan (for testing)
python -m src.main --scan

# Check portfolio status
python -m src.main --status

# Resume trading if paused
python -m src.main --resume

# Run tests
pytest tests/
```

## Architecture

The codebase follows a modular architecture with clear separation of concerns:

- **Orchestration**: `src/main.py` - APScheduler runs scans every 15 min during market hours (9:30-4 ET), plus a 5-min stop-loss monitor
- **Credential Security**: `src/credentials.py` - All secrets stored in macOS Keychain under service name "AutoTradingForVamsi"
- **Brokerage Layer**: `src/webull_client.py` - Uses unofficial `webull` PyPI package; supports paper/live mode toggle
- **Signal Flow**: Screener → BuySignalGenerator/SellSignalGenerator → SMS approval → TradeExecutor
- **Persistence**: SQLite database at `data/trades.db` with tables: trades, holdings, signals, portfolio_snapshots, audit_log, trading_state
- **Risk Controls**: Enforced in `src/portfolio/risk.py` - max drawdown pauses trading, PDT tracking, position limits

Key singleton patterns: `get_database()`, `get_webull_client()`, `get_config()` - instantiate once and reuse.

## Data Flow

1. **Scheduler** triggers scan every 15 min during market hours (9:30-4 ET)
2. **ValueScreener** finds stocks near 52-week lows with good fundamentals
3. **SignalEngine** creates BUY/SELL signals based on criteria
4. **TwilioSMS** sends approval request, waits for Y/N response
5. **TradeExecutor** executes approved trades on Webull
6. **PortfolioManager** records trades, tracks P&L
7. **RiskManager** enforces position limits and drawdown rules

## Configuration

Edit `config/settings.yaml` for non-sensitive settings:
- Trading limits (stop-loss, take-profit, max holdings)
- Screener criteria (P/E, RSI thresholds)
- Market hours and scan intervals
- Paper trading toggle

Credentials are stored in macOS Keychain, never in files.

## Key Files to Modify

| Task | File |
|------|------|
| Change trading limits | `config/settings.yaml` |
| Modify screening criteria | `src/screener/value_screener.py` |
| Adjust technical indicators | `src/screener/technical.py` |
| Change SMS message format | `src/notifications/twilio_sms.py` |
| Add new risk controls | `src/portfolio/risk.py` |
| Modify schedule timing | `src/main.py` (`start_scheduler` method) |
| Add/modify DB tables | `src/db/models.py` |

## Testing

```bash
# Run a single test file
pytest tests/test_screener.py -v

# Run specific test
pytest tests/test_screener.py::test_function_name -v
```

Note: The Webull package is unofficial and may break if Webull changes their API.
