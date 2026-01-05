"""
Sell Signal Generator

Generates sell signals based on:
- Stop-loss threshold (-5%)
- Take-profit threshold (+10%)
- Minimum hold period (2 days)
- Technical indicators (RSI overbought)
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
import yfinance as yf

from src.screener.technical import get_technical_indicators, is_overbought
from src.config import get_config
from src.db.models import get_database, Signal, Holding, SignalStatus
from src.logger import signal_log


class SellSignalGenerator:
    """Generates sell signals based on exit criteria."""

    def __init__(self):
        self.config = get_config()
        self.trading = self.config.trading
        self.screener = self.config.screener
        self.db = get_database()

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current market price for a symbol."""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d")
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
            return None
        except Exception as e:
            signal_log.error(f"Failed to get price for {symbol}: {e}")
            return None

    def get_technical_data(self, symbol: str) -> Optional[Dict]:
        """Get technical indicators for a symbol."""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="6mo")
            if not hist.empty and len(hist) >= 20:
                return get_technical_indicators(hist)
            return None
        except Exception as e:
            signal_log.error(f"Failed to get technicals for {symbol}: {e}")
            return None

    def check_stop_loss(self, holding: Holding, current_price: float) -> tuple[bool, str]:
        """
        Check if stop-loss should be triggered.

        Returns:
            (triggered: bool, reason: str)
        """
        if holding.avg_buy_price <= 0:
            return False, ""

        pnl_pct = ((current_price - holding.avg_buy_price) / holding.avg_buy_price) * 100

        if pnl_pct <= self.trading.stop_loss_pct:
            return True, f"Stop-loss triggered: {pnl_pct:.1f}% (threshold: {self.trading.stop_loss_pct}%)"

        return False, ""

    def check_take_profit(self, holding: Holding, current_price: float) -> tuple[bool, str]:
        """
        Check if take-profit should be triggered.

        Returns:
            (triggered: bool, reason: str)
        """
        if holding.avg_buy_price <= 0:
            return False, ""

        pnl_pct = ((current_price - holding.avg_buy_price) / holding.avg_buy_price) * 100

        if pnl_pct >= self.trading.take_profit_pct:
            return True, f"Take-profit triggered: +{pnl_pct:.1f}% (threshold: +{self.trading.take_profit_pct}%)"

        return False, ""

    def check_min_hold_period(self, holding: Holding) -> tuple[bool, str]:
        """
        Check if minimum hold period has passed.

        Returns:
            (can_sell: bool, reason: str)
        """
        if not holding.first_bought_at:
            return True, ""

        days_held = (datetime.utcnow() - holding.first_bought_at).days

        if days_held < self.trading.min_hold_days:
            return False, f"Min hold period not met ({days_held}/{self.trading.min_hold_days} days)"

        return True, f"Held for {days_held} days"

    def check_technical_exit(self, symbol: str) -> tuple[bool, str]:
        """
        Check technical indicators for exit signal.

        Returns:
            (should_exit: bool, reason: str)
        """
        technicals = self.get_technical_data(symbol)
        if not technicals:
            return False, ""

        rsi = technicals.get('rsi_14', 50)

        # RSI overbought - consider selling
        if is_overbought(rsi, self.screener.rsi_overbought):
            return True, f"RSI overbought: {rsi:.1f}"

        return False, ""

    def generate_signals(self, holdings: List[Holding] = None) -> List[Signal]:
        """
        Generate sell signals for current holdings.

        Args:
            holdings: List of current holdings (if None, fetched from DB)

        Returns:
            List of Signal objects for pending approval
        """
        signals = []

        session = self.db.get_session()
        try:
            if holdings is None:
                holdings = self.db.get_holdings(session)

            if not holdings:
                signal_log.info("No holdings to check for sell signals")
                return signals

            for holding in holdings:
                symbol = holding.symbol
                current_price = self.get_current_price(symbol)

                if current_price is None:
                    signal_log.warning(f"Could not get price for {symbol}, skipping")
                    continue

                # Update holding with current price
                pnl = (current_price - holding.avg_buy_price) * holding.quantity
                pnl_pct = ((current_price - holding.avg_buy_price) / holding.avg_buy_price) * 100
                holding.current_price = current_price
                holding.current_value = current_price * holding.quantity
                holding.unrealized_pl = pnl
                holding.unrealized_pl_pct = pnl_pct
                holding.last_updated_at = datetime.utcnow()
                session.commit()

                # Check sell conditions
                reasons = []
                should_sell = False
                is_emergency = False  # Stop-loss is more urgent

                # 1. Check stop-loss (PRIORITY - bypass hold period)
                stop_loss_triggered, stop_reason = self.check_stop_loss(holding, current_price)
                if stop_loss_triggered:
                    should_sell = True
                    is_emergency = True
                    reasons.append(stop_reason)

                # 2. Check take-profit
                take_profit_triggered, profit_reason = self.check_take_profit(holding, current_price)
                if take_profit_triggered:
                    should_sell = True
                    reasons.append(profit_reason)

                # 3. Check technical exit (if not already triggered by P&L)
                if not should_sell:
                    tech_exit, tech_reason = self.check_technical_exit(symbol)
                    if tech_exit:
                        # Technical exit is a suggestion, not mandatory
                        reasons.append(tech_reason)

                # 4. Check minimum hold period (unless stop-loss)
                if should_sell and not is_emergency:
                    can_sell, hold_reason = self.check_min_hold_period(holding)
                    if not can_sell:
                        signal_log.info(f"{symbol}: {hold_reason} - skipping sell signal")
                        continue
                    reasons.append(hold_reason)

                # Generate sell signal if conditions met
                if should_sell:
                    reason_str = " | ".join(reasons)

                    # Calculate profit/loss for the signal
                    signal = Signal(
                        symbol=symbol,
                        action='SELL',
                        suggested_price=current_price,
                        suggested_quantity=holding.quantity,
                        reason=reason_str,
                        status=SignalStatus.PENDING.value,
                        expires_at=datetime.utcnow() + timedelta(
                            minutes=5 if is_emergency else self.trading.approval_timeout_minutes
                        )
                    )

                    signal = self.db.add_signal(session, signal)
                    signals.append(signal)

                    signal_log.info(
                        f"SELL signal generated: {symbol} x {holding.quantity} @ ${current_price:.2f} | "
                        f"P&L: ${pnl:.2f} ({pnl_pct:+.1f}%) | {reason_str}"
                    )

            # Log to audit
            if signals:
                self.db.log_action(
                    session,
                    action_type='SELL_SIGNALS_GENERATED',
                    description=f"Generated {len(signals)} sell signals",
                    extra_data=str([s.symbol for s in signals])
                )

        finally:
            session.close()

        return signals


class StopLossMonitor:
    """
    Continuous monitor for stop-loss conditions.
    Can be run more frequently than regular sell signal checks.
    """

    def __init__(self):
        self.generator = SellSignalGenerator()

    def check_stop_losses(self) -> List[Signal]:
        """
        Quick check for stop-loss conditions only.
        Bypasses minimum hold period.
        """
        signals = []
        db = get_database()
        session = db.get_session()

        try:
            holdings = db.get_holdings(session)

            for holding in holdings:
                current_price = self.generator.get_current_price(holding.symbol)
                if current_price is None:
                    continue

                triggered, reason = self.generator.check_stop_loss(holding, current_price)

                if triggered:
                    signal = Signal(
                        symbol=holding.symbol,
                        action='SELL',
                        suggested_price=current_price,
                        suggested_quantity=holding.quantity,
                        reason=f"URGENT: {reason}",
                        status=SignalStatus.PENDING.value,
                        expires_at=datetime.utcnow() + timedelta(minutes=5)  # Short timeout
                    )

                    signal = db.add_signal(session, signal)
                    signals.append(signal)

                    signal_log.warning(f"STOP-LOSS: {holding.symbol} - {reason}")

        finally:
            session.close()

        return signals


def generate_sell_signals(holdings: List[Holding] = None) -> List[Signal]:
    """Convenience function to generate sell signals."""
    generator = SellSignalGenerator()
    return generator.generate_signals(holdings)


def check_stop_losses() -> List[Signal]:
    """Convenience function for quick stop-loss check."""
    monitor = StopLossMonitor()
    return monitor.check_stop_losses()
