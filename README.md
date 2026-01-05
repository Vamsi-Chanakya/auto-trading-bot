# Auto Trading Bot

Automated stock trading bot for US markets using Webull. Screens for undervalued stocks near 52-week lows, sends Telegram approval requests, and executes trades with strict risk controls.

## Features

- **Value Screening**: Finds stocks near 52-week lows with solid fundamentals (P/E < 25, market cap > $500M)
- **Technical Analysis**: RSI, volume surge detection, moving averages
- **Telegram Approval**: Every trade requires your approval via Telegram message before execution (FREE!)
- **Risk Management**: Stop-loss (-5%), take-profit (+10%), max 2 holdings, max drawdown protection
- **Paper Trading**: Test strategies risk-free before going live
- **Secure Credentials**: All secrets stored in macOS Keychain, never in files

## Requirements

- macOS (uses Keychain for credential storage)
- Python 3.9+
- Webull account
- Telegram account (free - for trade approvals)

## Installation

```bash
# Clone the repository
git clone https://github.com/Vamsi-Chanakya/auto-trading-bot.git
cd auto-trading-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure credentials (stored securely in macOS Keychain)
python src/credentials.py --setup
```

## Telegram Bot Setup

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to create your bot
3. Copy the bot token you receive
4. Message your new bot (send any message to start a chat)
5. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` to find your chat_id
6. Run `python src/credentials.py --setup` and enter your bot token and chat_id

## Usage

```bash
# Start the trading bot (runs during market hours)
python -m src.main

# Run a single scan (for testing)
python -m src.main --scan

# Check portfolio status
python -m src.main --status

# Check credential configuration
python src/credentials.py --status

# Resume trading if paused (after max drawdown)
python -m src.main --resume
```

## Configuration

Edit `config/settings.yaml` to customize:

| Setting | Default | Description |
|---------|---------|-------------|
| `initial_budget` | $1,000 | Starting capital |
| `max_holdings` | 2 | Maximum concurrent positions |
| `stop_loss_pct` | -5% | Sell if position drops 5% |
| `take_profit_pct` | +10% | Sell if position gains 10% |
| `max_drawdown_pct` | -15% | Pause trading if portfolio drops 15% |
| `paper_trading.enabled` | true | Use paper trading mode |

## How It Works

1. **Scheduler** runs scans every 15 minutes during market hours (9:30 AM - 4:00 PM ET)
2. **Screener** identifies stocks near 52-week lows with good fundamentals
3. **Signal Generator** creates BUY/SELL signals based on criteria
4. **Telegram Bot** sends you a message asking for approval (Y/N)
5. **Trade Executor** places the order on Webull if approved
6. **Risk Manager** monitors positions and enforces stop-loss/take-profit

## Project Structure

```
src/
├── main.py              # Entry point, scheduler
├── credentials.py       # macOS Keychain manager
├── webull_client.py     # Webull API wrapper
├── screener/            # Stock screening logic
├── signals/             # Buy/sell signal generation
├── portfolio/           # Holdings and risk management
├── notifications/       # Twilio SMS integration
├── executor/            # Trade execution
└── db/                  # SQLite persistence
```

## Safety Features

- **Paper trading by default** - Test before risking real money
- **Telegram approval required** - No trades execute without your explicit consent
- **Position limits** - Maximum 2 holdings to manage risk
- **Drawdown protection** - Trading pauses if portfolio drops 15%
- **No day trading** - Minimum 2-day hold period
- **Secure credentials** - All secrets in macOS Keychain, never in code

## Disclaimer

This software is for educational purposes only. Trading stocks involves risk of loss. Past performance does not guarantee future results. Always do your own research before making investment decisions.

## License

MIT
