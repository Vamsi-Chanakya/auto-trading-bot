"""
Buy Signal Generator

Generates buy signals based on:
- Value screener results
- Portfolio constraints (max holdings, position size)
- Available buying power
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta

from src.screener.value_screener import ValueScreener
from src.config import get_config
from src.db.models import get_database, Signal, SignalStatus
from src.logger import signal_log


class BuySignalGenerator:
    """Generates buy signals for undervalued stocks."""

    def __init__(self):
        self.config = get_config()
        self.trading = self.config.trading
        self.screener = ValueScreener()
        self.db = get_database()

    def get_current_holdings_count(self) -> int:
        """Get number of current holdings from database."""
        session = self.db.get_session()
        try:
            holdings = self.db.get_holdings(session)
            return len(holdings)
        finally:
            session.close()

    def get_available_budget(self, current_cash: float) -> float:
        """
        Calculate available budget for new positions.

        Args:
            current_cash: Current cash balance

        Returns:
            Maximum amount available for a new position
        """
        max_position = self.trading.max_position_value
        return min(current_cash, max_position)

    def calculate_position_size(self, price: float, available_budget: float) -> int:
        """
        Calculate number of shares to buy.

        Args:
            price: Current stock price
            available_budget: Maximum amount to spend

        Returns:
            Number of shares (whole shares only)
        """
        if price <= 0:
            return 0

        # Calculate max shares we can afford
        max_shares = int(available_budget / price)

        # Ensure at least 1 share if we have budget
        return max(0, max_shares)

    def can_generate_buy_signal(self) -> tuple[bool, str]:
        """
        Check if we can generate new buy signals.

        Returns:
            (can_generate: bool, reason: str)
        """
        holdings_count = self.get_current_holdings_count()

        if holdings_count >= self.trading.max_holdings:
            return False, f"Already at max holdings ({holdings_count}/{self.trading.max_holdings})"

        # Check if trading is paused
        session = self.db.get_session()
        try:
            paused = self.db.get_state(session, 'trading_paused')
            if paused == 'true':
                return False, "Trading is paused (max drawdown reached)"
        finally:
            session.close()

        return True, "Ready to generate signals"

    def generate_signals(self, current_cash: float, current_holdings: List[str] = None) -> List[Signal]:
        """
        Generate buy signals based on screener results.

        Args:
            current_cash: Available cash balance
            current_holdings: List of currently held symbols (to avoid duplicates)

        Returns:
            List of Signal objects for pending approval
        """
        if current_holdings is None:
            current_holdings = []

        signals = []

        # Check if we can generate signals
        can_generate, reason = self.can_generate_buy_signal()
        if not can_generate:
            signal_log.info(f"Cannot generate buy signals: {reason}")
            return signals

        # Calculate how many new positions we can take
        current_count = len(current_holdings)
        slots_available = self.trading.max_holdings - current_count

        if slots_available <= 0:
            return signals

        # Run screener
        opportunities = self.screener.get_top_opportunities(limit=slots_available * 2)

        # Filter out already held stocks
        opportunities = [o for o in opportunities if o['symbol'] not in current_holdings]

        if not opportunities:
            signal_log.info("No qualifying opportunities found")
            return signals

        available_budget = self.get_available_budget(current_cash)

        session = self.db.get_session()
        try:
            for stock in opportunities[:slots_available]:
                symbol = stock['symbol']
                price = stock['current_price']

                # Calculate position size
                quantity = self.calculate_position_size(price, available_budget)

                if quantity <= 0:
                    signal_log.info(f"Insufficient funds for {symbol} @ ${price:.2f}")
                    continue

                total_value = quantity * price

                # Build reason string
                reasons = stock.get('reasons', [])
                reason_str = f"Score: {stock['score']:.0f} | " + " | ".join(reasons)

                # Create signal
                signal = Signal(
                    symbol=symbol,
                    action='BUY',
                    suggested_price=price,
                    suggested_quantity=quantity,
                    reason=reason_str,
                    status=SignalStatus.PENDING.value,
                    expires_at=datetime.utcnow() + timedelta(minutes=self.trading.approval_timeout_minutes)
                )

                signal = self.db.add_signal(session, signal)
                signals.append(signal)

                signal_log.info(
                    f"BUY signal generated: {symbol} x {quantity} @ ${price:.2f} "
                    f"(${total_value:.2f})"
                )

                # Reduce available budget for next opportunity
                available_budget -= total_value

                if available_budget < self.trading.min_stock_price:
                    break

            # Log to audit
            if signals:
                self.db.log_action(
                    session,
                    action_type='SIGNALS_GENERATED',
                    description=f"Generated {len(signals)} buy signals",
                    extra_data=str([s.symbol for s in signals])
                )

        finally:
            session.close()

        return signals


def generate_buy_signals(current_cash: float, current_holdings: List[str] = None) -> List[Signal]:
    """Convenience function to generate buy signals."""
    generator = BuySignalGenerator()
    return generator.generate_signals(current_cash, current_holdings)
