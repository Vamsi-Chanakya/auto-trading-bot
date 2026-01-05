"""
Auto Trading App - Main Entry Point

This is the main orchestrator that:
1. Schedules market scans during trading hours
2. Generates buy/sell signals
3. Requests user approval via SMS
4. Executes approved trades
5. Monitors positions for stop-loss/take-profit
"""

import sys
import signal
import argparse
from datetime import datetime, time as dtime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from src.config import get_config
from src.credentials import CredentialManager
from src.webull_client import get_webull_client
from src.portfolio.manager import get_portfolio_manager
from src.portfolio.risk import get_risk_manager
from src.signals.buy_signal import generate_buy_signals
from src.signals.sell_signal import generate_sell_signals, check_stop_losses
from src.notifications.telegram_bot import get_approval_manager, get_telegram_client
from src.executor.trade_executor import get_trade_executor
from src.db.models import get_database
from src.logger import main_log


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self):
        self.config = get_config()
        self.creds = CredentialManager()
        self.portfolio = get_portfolio_manager()
        self.risk = get_risk_manager()
        self.approval = get_approval_manager()
        self.executor = get_trade_executor()
        self.telegram = get_telegram_client()
        self.db = get_database()
        self.scheduler = None
        self.tz = pytz.timezone(self.config.market.timezone)

        self._running = False

    def check_prerequisites(self) -> bool:
        """Check that all required credentials are configured."""
        if not self.creds.is_webull_configured():
            main_log.error("Webull credentials not configured!")
            print("\nPlease run: python src/credentials.py --setup")
            return False

        if not self.creds.is_telegram_configured():
            main_log.error("Telegram credentials not configured!")
            print("\nPlease run: python src/credentials.py --setup")
            return False

        return True

    def is_market_hours(self) -> bool:
        """Check if current time is within market hours."""
        now = datetime.now(self.tz)
        market_open = dtime(
            self.config.market.open_hour,
            self.config.market.open_minute
        )
        market_close = dtime(
            self.config.market.close_hour,
            self.config.market.close_minute
        )

        current_time = now.time()
        is_weekday = now.weekday() < 5  # Monday = 0, Friday = 4

        return is_weekday and market_open <= current_time <= market_close

    def scan_for_opportunities(self):
        """
        Main scan job - runs every 15 minutes during market hours.

        1. Check for sell signals (stop-loss, take-profit)
        2. Check for buy signals (new opportunities)
        3. Request approval and execute
        """
        if not self.is_market_hours():
            main_log.info("Outside market hours - skipping scan")
            return

        main_log.info("=" * 50)
        main_log.info("Starting market scan...")

        # Check if trading is paused
        paused, reason = self.risk.is_trading_paused()
        if paused:
            main_log.warning(f"Trading paused: {reason}")
            return

        try:
            # 1. Check existing holdings for sell signals
            main_log.info("Checking holdings for sell signals...")
            sell_signals = generate_sell_signals()

            if sell_signals:
                main_log.info(f"Generated {len(sell_signals)} sell signals")
                for signal in sell_signals:
                    self._process_signal(signal)

            # 2. Check for buy opportunities
            holdings = self.portfolio.get_holdings_symbols()
            portfolio = self.portfolio.get_portfolio_value()

            if len(holdings) < self.config.trading.max_holdings:
                main_log.info("Checking for buy opportunities...")
                buy_signals = generate_buy_signals(
                    current_cash=portfolio['cash_balance'],
                    current_holdings=holdings
                )

                if buy_signals:
                    main_log.info(f"Generated {len(buy_signals)} buy signals")
                    for signal in buy_signals:
                        self._process_signal(signal)
                else:
                    main_log.info("No qualifying buy opportunities found")
            else:
                main_log.info(f"At max holdings ({len(holdings)}/{self.config.trading.max_holdings})")

            # 3. Take portfolio snapshot
            self.portfolio.take_snapshot()

        except Exception as e:
            main_log.error(f"Scan error: {e}")

        main_log.info("Scan complete")
        main_log.info("=" * 50)

    def _process_signal(self, signal):
        """Process a single signal through approval and execution."""
        main_log.info(f"Processing signal #{signal.id}: {signal.action} {signal.symbol}")

        # Request approval via SMS
        response = self.approval.request_approval(signal)

        if response == 'Y':
            # Execute the trade
            result = self.executor.execute_signal(signal)
            if result['success']:
                main_log.info(f"Trade executed: {result['message']}")
            else:
                main_log.warning(f"Trade failed: {result['message']}")

        elif response == 'N':
            main_log.info(f"Signal #{signal.id} rejected by user")

        elif response == 'M':
            main_log.info(f"Signal #{signal.id} modify requested - not implemented yet")

        else:
            main_log.info(f"Signal #{signal.id} timed out or no response")

    def check_stop_loss_quick(self):
        """
        Quick stop-loss check - runs every 5 minutes.

        More frequent than full scan to catch rapid drops.
        """
        if not self.is_market_hours():
            return

        try:
            stop_signals = check_stop_losses()
            for signal in stop_signals:
                # Stop-loss is urgent - process immediately
                self._process_signal(signal)

        except Exception as e:
            main_log.error(f"Stop-loss check error: {e}")

    def send_daily_summary(self):
        """Send daily portfolio summary at market close."""
        try:
            portfolio = self.portfolio.get_portfolio_value()
            self.telegram.send_daily_summary(portfolio)
            main_log.info("Daily summary sent")
        except Exception as e:
            main_log.error(f"Failed to send daily summary: {e}")

    def start_scheduler(self):
        """Start the APScheduler with all jobs."""
        self.scheduler = BlockingScheduler(timezone=self.tz)

        # Main scan - every 15 minutes during market hours
        self.scheduler.add_job(
            self.scan_for_opportunities,
            CronTrigger(
                day_of_week='mon-fri',
                hour='9-15',
                minute='*/15',
                timezone=self.tz
            ),
            id='main_scan',
            name='Main Market Scan'
        )

        # Additional scan at market open
        self.scheduler.add_job(
            self.scan_for_opportunities,
            CronTrigger(
                day_of_week='mon-fri',
                hour=9,
                minute=35,  # 5 minutes after open
                timezone=self.tz
            ),
            id='open_scan',
            name='Market Open Scan'
        )

        # Quick stop-loss check - every 5 minutes
        self.scheduler.add_job(
            self.check_stop_loss_quick,
            CronTrigger(
                day_of_week='mon-fri',
                hour='9-15',
                minute='*/5',
                timezone=self.tz
            ),
            id='stop_loss_check',
            name='Stop-Loss Monitor'
        )

        # Daily summary at market close
        self.scheduler.add_job(
            self.send_daily_summary,
            CronTrigger(
                day_of_week='mon-fri',
                hour=16,
                minute=5,
                timezone=self.tz
            ),
            id='daily_summary',
            name='Daily Summary'
        )

        # Daily portfolio snapshot
        self.scheduler.add_job(
            self.portfolio.take_snapshot,
            CronTrigger(
                day_of_week='mon-fri',
                hour=16,
                minute=1,
                timezone=self.tz
            ),
            id='daily_snapshot',
            name='Daily Snapshot'
        )

        main_log.info("Scheduler configured with jobs:")
        for job in self.scheduler.get_jobs():
            main_log.info(f"  - {job.name}: {job.trigger}")

    def run(self):
        """Start the trading bot."""
        print("\n" + "=" * 60)
        print("AUTO TRADING BOT")
        print("=" * 60)

        # Check prerequisites
        if not self.check_prerequisites():
            sys.exit(1)

        # Show configuration
        mode = "PAPER TRADING" if self.config.paper_trading.enabled else "LIVE TRADING"
        print(f"\nMode: {mode}")
        print(f"Budget: ${self.config.trading.initial_budget:,.2f}")
        print(f"Max Holdings: {self.config.trading.max_holdings}")
        print(f"Stop Loss: {self.config.trading.stop_loss_pct}%")
        print(f"Take Profit: +{self.config.trading.take_profit_pct}%")
        print(f"Scan Interval: {self.config.market.scan_interval_minutes} minutes")
        print(f"Timezone: {self.config.market.timezone}")

        # Show current portfolio
        self.portfolio.print_summary()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        # Start scheduler
        print("\nStarting scheduler...")
        print("Press Ctrl+C to stop\n")

        self._running = True
        self.start_scheduler()

        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            pass

    def run_once(self):
        """Run a single scan (for testing)."""
        print("\nRunning single scan...")
        self.scan_for_opportunities()
        self.portfolio.print_summary()

    def _shutdown(self, signum, frame):
        """Graceful shutdown handler."""
        print("\nShutting down...")
        self._running = False
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
        sys.exit(0)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Auto Trading Bot for Webull',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main                  Start the trading bot
  python -m src.main --scan           Run a single scan
  python -m src.main --status         Show portfolio status
  python -m src.main --setup          Configure credentials
        """
    )

    parser.add_argument('--scan', action='store_true',
                        help='Run a single scan and exit')
    parser.add_argument('--status', action='store_true',
                        help='Show portfolio status and exit')
    parser.add_argument('--setup', action='store_true',
                        help='Configure credentials')
    parser.add_argument('--resume', action='store_true',
                        help='Resume trading if paused')

    args = parser.parse_args()

    if args.setup:
        creds = CredentialManager()
        creds.setup_webull()
        creds.setup_twilio()
        creds.status()
        return

    if args.status:
        portfolio = get_portfolio_manager()
        portfolio.print_summary()

        risk = get_risk_manager()
        portfolio_data = portfolio.get_portfolio_value()
        risk_status = risk.get_risk_status(
            portfolio_value=portfolio_data['total_value'],
            peak_value=portfolio_data.get('peak_value', portfolio_data['total_value']),
            current_holdings=portfolio_data['num_holdings']
        )
        print("\nRisk Status:")
        print(f"  Trading Active: {'No' if risk_status['trading_paused'] else 'Yes'}")
        print(f"  Drawdown: {risk_status['drawdown_status']}")
        print(f"  Daily Trades: {risk_status['daily_trades_status']}")
        print(f"  PDT Status: {risk_status['pdt_status']}")
        return

    if args.resume:
        risk = get_risk_manager()
        risk.resume_trading()
        print("Trading resumed")
        return

    # Start the bot
    bot = TradingBot()

    if args.scan:
        bot.run_once()
    else:
        bot.run()


if __name__ == "__main__":
    main()
