"""
Risk Management Module

Enforces:
- Position size limits
- Maximum holdings limit
- Maximum drawdown protection
- Daily trade limits
- Pattern day trader (PDT) protection
"""

from typing import Dict, Tuple, Optional
from datetime import datetime, timedelta

from src.db.models import get_database, Trade
from src.config import get_config
from src.logger import main_log


class RiskManager:
    """Manages risk controls and enforces trading limits."""

    def __init__(self):
        self.config = get_config()
        self.trading = self.config.trading
        self.db = get_database()

    def check_position_size(self, price: float, quantity: int,
                            available_cash: float) -> Tuple[bool, str]:
        """
        Check if proposed position size is within limits.

        Returns:
            (allowed: bool, reason: str)
        """
        position_value = price * quantity
        max_position = self.trading.max_position_value

        if position_value > max_position:
            return False, f"Position ${position_value:.2f} exceeds max ${max_position:.2f}"

        if position_value > available_cash:
            return False, f"Position ${position_value:.2f} exceeds available cash ${available_cash:.2f}"

        return True, f"Position size ${position_value:.2f} OK"

    def check_holdings_limit(self, current_holdings: int) -> Tuple[bool, str]:
        """
        Check if we can add another holding.

        Returns:
            (allowed: bool, reason: str)
        """
        max_holdings = self.trading.max_holdings

        if current_holdings >= max_holdings:
            return False, f"At max holdings ({current_holdings}/{max_holdings})"

        return True, f"Holdings OK ({current_holdings}/{max_holdings})"

    def check_drawdown(self, current_value: float, peak_value: float) -> Tuple[bool, str, bool]:
        """
        Check if maximum drawdown has been reached.

        Returns:
            (trading_allowed: bool, reason: str, should_pause: bool)
        """
        if peak_value <= 0:
            return True, "No peak value recorded", False

        drawdown_pct = ((current_value - peak_value) / peak_value) * 100
        max_drawdown = self.trading.max_drawdown_pct  # Negative number

        if drawdown_pct <= max_drawdown:
            return False, f"Max drawdown reached: {drawdown_pct:.1f}% (limit: {max_drawdown}%)", True

        return True, f"Drawdown OK: {drawdown_pct:.1f}%", False

    def check_daily_trades(self) -> Tuple[bool, str]:
        """
        Check if daily trade limit has been reached.

        Returns:
            (allowed: bool, reason: str)
        """
        session = self.db.get_session()
        try:
            # Get trades from today
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            trades = session.query(Trade).filter(
                Trade.executed_at >= today_start
            ).all()

            trade_count = len(trades)
            max_trades = self.trading.max_daily_trades

            if trade_count >= max_trades:
                return False, f"Daily trade limit reached ({trade_count}/{max_trades})"

            return True, f"Daily trades OK ({trade_count}/{max_trades})"

        finally:
            session.close()

    def check_pdt_rule(self) -> Tuple[bool, str]:
        """
        Check Pattern Day Trader rule (max 3 day trades in 5 rolling days).

        A day trade is a buy and sell of the same stock on the same day.

        Returns:
            (allowed: bool, reason: str)
        """
        session = self.db.get_session()
        try:
            # Get trades from last 5 trading days
            five_days_ago = datetime.utcnow() - timedelta(days=7)  # Use 7 to account for weekends
            trades = session.query(Trade).filter(
                Trade.executed_at >= five_days_ago
            ).order_by(Trade.executed_at).all()

            # Count day trades
            day_trades = 0
            buys_by_symbol_date = {}

            for trade in trades:
                trade_date = trade.executed_at.date() if trade.executed_at else None
                if not trade_date:
                    continue

                key = (trade.symbol, trade_date)

                if trade.action == 'BUY':
                    buys_by_symbol_date[key] = True
                elif trade.action == 'SELL':
                    if buys_by_symbol_date.get(key):
                        day_trades += 1

            if day_trades >= 3:
                return False, f"PDT limit reached ({day_trades}/3 day trades in 5 days)"

            return True, f"PDT OK ({day_trades}/3 day trades)"

        finally:
            session.close()

    def is_trading_paused(self) -> Tuple[bool, str]:
        """
        Check if trading is paused (e.g., due to max drawdown).

        Returns:
            (paused: bool, reason: str)
        """
        session = self.db.get_session()
        try:
            paused = self.db.get_state(session, 'trading_paused')
            if paused == 'true':
                reason = self.db.get_state(session, 'pause_reason') or 'Unknown reason'
                return True, reason
            return False, "Trading active"
        finally:
            session.close()

    def pause_trading(self, reason: str):
        """Pause all trading with a reason."""
        session = self.db.get_session()
        try:
            self.db.set_state(session, 'trading_paused', 'true')
            self.db.set_state(session, 'pause_reason', reason)
            self.db.set_state(session, 'paused_at', datetime.utcnow().isoformat())

            self.db.log_action(
                session,
                action_type='TRADING_PAUSED',
                description=f"Trading paused: {reason}"
            )

            main_log.warning(f"TRADING PAUSED: {reason}")
        finally:
            session.close()

    def resume_trading(self):
        """Resume trading."""
        session = self.db.get_session()
        try:
            self.db.set_state(session, 'trading_paused', 'false')
            self.db.set_state(session, 'pause_reason', '')

            self.db.log_action(
                session,
                action_type='TRADING_RESUMED',
                description="Trading resumed"
            )

            main_log.info("Trading resumed")
        finally:
            session.close()

    def pre_trade_check(self, action: str, symbol: str, quantity: int,
                        price: float, available_cash: float,
                        current_holdings: int, portfolio_value: float,
                        peak_value: float) -> Tuple[bool, str]:
        """
        Comprehensive pre-trade risk check.

        Returns:
            (allowed: bool, reason: str)
        """
        checks = []

        # Check if trading is paused
        paused, pause_reason = self.is_trading_paused()
        if paused:
            return False, f"Trading paused: {pause_reason}"

        # Check drawdown
        drawdown_ok, drawdown_msg, should_pause = self.check_drawdown(portfolio_value, peak_value)
        if should_pause:
            self.pause_trading(drawdown_msg)
            return False, drawdown_msg
        checks.append(drawdown_msg)

        # Check daily trades
        daily_ok, daily_msg = self.check_daily_trades()
        if not daily_ok:
            return False, daily_msg
        checks.append(daily_msg)

        # Check PDT rule
        pdt_ok, pdt_msg = self.check_pdt_rule()
        if not pdt_ok:
            return False, pdt_msg
        checks.append(pdt_msg)

        if action == 'BUY':
            # Check holdings limit
            holdings_ok, holdings_msg = self.check_holdings_limit(current_holdings)
            if not holdings_ok:
                return False, holdings_msg
            checks.append(holdings_msg)

            # Check position size
            position_ok, position_msg = self.check_position_size(price, quantity, available_cash)
            if not position_ok:
                return False, position_msg
            checks.append(position_msg)

        return True, " | ".join(checks)

    def get_risk_status(self, portfolio_value: float, peak_value: float,
                        current_holdings: int) -> Dict:
        """Get comprehensive risk status."""
        paused, pause_reason = self.is_trading_paused()
        drawdown_ok, drawdown_msg, _ = self.check_drawdown(portfolio_value, peak_value)
        daily_ok, daily_msg = self.check_daily_trades()
        pdt_ok, pdt_msg = self.check_pdt_rule()
        holdings_ok, holdings_msg = self.check_holdings_limit(current_holdings)

        return {
            'trading_paused': paused,
            'pause_reason': pause_reason if paused else None,
            'drawdown_status': drawdown_msg,
            'drawdown_ok': drawdown_ok,
            'daily_trades_status': daily_msg,
            'daily_trades_ok': daily_ok,
            'pdt_status': pdt_msg,
            'pdt_ok': pdt_ok,
            'holdings_status': holdings_msg,
            'holdings_ok': holdings_ok,
            'can_trade': not paused and drawdown_ok and daily_ok and pdt_ok
        }


# Singleton instance
_risk_manager: Optional[RiskManager] = None


def get_risk_manager() -> RiskManager:
    """Get or create the risk manager instance."""
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager
