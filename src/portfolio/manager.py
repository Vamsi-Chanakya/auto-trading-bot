"""
Portfolio Manager

Manages:
- Current holdings tracking
- Cash balance tracking
- Portfolio value calculations
- Performance metrics
"""

from typing import Dict, List, Optional
from datetime import datetime
import yfinance as yf

from src.db.models import get_database, Holding, Trade, PortfolioSnapshot
from src.config import get_config
from src.logger import main_log


class PortfolioManager:
    """Manages portfolio holdings and performance tracking."""

    def __init__(self, initial_cash: float = None):
        self.config = get_config()
        self.db = get_database()

        # Initialize cash from config if not provided
        if initial_cash is None:
            initial_cash = self.config.trading.initial_budget

        self._cash_balance = initial_cash

    @property
    def cash_balance(self) -> float:
        """Get current cash balance."""
        return self._cash_balance

    def get_holdings(self) -> List[Dict]:
        """Get all current holdings with latest prices."""
        session = self.db.get_session()
        try:
            holdings = self.db.get_holdings(session)
            result = []

            for h in holdings:
                # Get current price
                current_price = self._get_current_price(h.symbol) or h.current_price or h.avg_buy_price

                # Calculate P&L
                current_value = current_price * h.quantity
                pnl = current_value - h.total_cost
                pnl_pct = (pnl / h.total_cost * 100) if h.total_cost > 0 else 0

                # Calculate days held
                days_held = (datetime.utcnow() - h.first_bought_at).days if h.first_bought_at else 0

                result.append({
                    'symbol': h.symbol,
                    'quantity': h.quantity,
                    'avg_buy_price': h.avg_buy_price,
                    'total_cost': h.total_cost,
                    'current_price': current_price,
                    'current_value': current_value,
                    'unrealized_pnl': pnl,
                    'unrealized_pnl_pct': pnl_pct,
                    'stop_loss_price': h.stop_loss_price,
                    'take_profit_price': h.take_profit_price,
                    'days_held': days_held,
                    'first_bought_at': h.first_bought_at
                })

            return result

        finally:
            session.close()

    def get_holdings_count(self) -> int:
        """Get number of current holdings."""
        session = self.db.get_session()
        try:
            return len(self.db.get_holdings(session))
        finally:
            session.close()

    def get_holdings_symbols(self) -> List[str]:
        """Get list of currently held symbols."""
        session = self.db.get_session()
        try:
            holdings = self.db.get_holdings(session)
            return [h.symbol for h in holdings]
        finally:
            session.close()

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """Get current market price for a symbol."""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d")
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
        except Exception as e:
            main_log.warning(f"Could not get price for {symbol}: {e}")
        return None

    def get_portfolio_value(self) -> Dict:
        """
        Calculate total portfolio value.

        Returns:
            Dict with cash, holdings_value, total_value, etc.
        """
        holdings = self.get_holdings()
        holdings_value = sum(h['current_value'] for h in holdings)
        total_value = self._cash_balance + holdings_value

        # Calculate total P&L
        total_cost = sum(h['total_cost'] for h in holdings)
        unrealized_pnl = holdings_value - total_cost
        unrealized_pnl_pct = (unrealized_pnl / total_cost * 100) if total_cost > 0 else 0

        # Total P&L from initial budget
        initial = self.config.trading.initial_budget
        total_pnl = total_value - initial
        total_pnl_pct = (total_pnl / initial * 100) if initial > 0 else 0

        return {
            'cash_balance': self._cash_balance,
            'holdings_value': holdings_value,
            'total_value': total_value,
            'num_holdings': len(holdings),
            'total_cost': total_cost,
            'unrealized_pnl': unrealized_pnl,
            'unrealized_pnl_pct': unrealized_pnl_pct,
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'initial_budget': initial
        }

    def record_buy(self, symbol: str, quantity: int, price: float,
                   order_id: str = None, signal_id: int = None) -> Trade:
        """
        Record a buy transaction.

        Updates cash balance, creates/updates holding, and logs trade.
        """
        total_cost = quantity * price
        self._cash_balance -= total_cost

        # Calculate stop-loss and take-profit prices
        stop_loss = price * (1 + self.config.trading.stop_loss_pct / 100)
        take_profit = price * (1 + self.config.trading.take_profit_pct / 100)

        session = self.db.get_session()
        try:
            # Update or create holding
            self.db.update_or_create_holding(
                session, symbol, quantity, price, stop_loss, take_profit
            )

            # Record trade
            trade = Trade(
                symbol=symbol,
                action='BUY',
                quantity=quantity,
                price=price,
                total_value=total_cost,
                order_id=order_id,
                signal_id=signal_id,
                executed_at=datetime.utcnow()
            )
            trade = self.db.add_trade(session, trade)

            # Log action
            self.db.log_action(
                session,
                action_type='TRADE_EXECUTED',
                symbol=symbol,
                description=f"BUY {quantity} x {symbol} @ ${price:.2f} = ${total_cost:.2f}",
                trade_id=trade.id,
                signal_id=signal_id
            )

            main_log.info(f"Recorded BUY: {quantity} x {symbol} @ ${price:.2f}")
            return trade

        finally:
            session.close()

    def record_sell(self, symbol: str, quantity: int, price: float,
                    order_id: str = None, signal_id: int = None) -> Trade:
        """
        Record a sell transaction.

        Updates cash balance, removes/updates holding, calculates P&L, and logs trade.
        """
        total_proceeds = quantity * price
        self._cash_balance += total_proceeds

        session = self.db.get_session()
        try:
            # Get original holding info for P&L calculation
            holding = self.db.get_holding(session, symbol)
            buy_price = holding.avg_buy_price if holding else 0
            days_held = (datetime.utcnow() - holding.first_bought_at).days if holding and holding.first_bought_at else 0

            # Calculate P&L
            profit_loss = (price - buy_price) * quantity
            profit_loss_pct = ((price - buy_price) / buy_price * 100) if buy_price > 0 else 0

            # Record trade
            trade = Trade(
                symbol=symbol,
                action='SELL',
                quantity=quantity,
                price=price,
                total_value=total_proceeds,
                order_id=order_id,
                signal_id=signal_id,
                buy_price=buy_price,
                profit_loss=profit_loss,
                profit_loss_pct=profit_loss_pct,
                hold_days=days_held,
                executed_at=datetime.utcnow()
            )
            trade = self.db.add_trade(session, trade)

            # Update or remove holding
            if holding:
                if quantity >= holding.quantity:
                    # Full sale - remove holding
                    self.db.remove_holding(session, symbol)
                else:
                    # Partial sale - reduce quantity
                    holding.quantity -= quantity
                    holding.total_cost = holding.quantity * holding.avg_buy_price
                    session.commit()

            # Log action
            self.db.log_action(
                session,
                action_type='TRADE_EXECUTED',
                symbol=symbol,
                description=f"SELL {quantity} x {symbol} @ ${price:.2f} = ${total_proceeds:.2f} | P&L: ${profit_loss:.2f} ({profit_loss_pct:+.1f}%)",
                trade_id=trade.id,
                signal_id=signal_id
            )

            main_log.info(
                f"Recorded SELL: {quantity} x {symbol} @ ${price:.2f} | "
                f"P&L: ${profit_loss:.2f} ({profit_loss_pct:+.1f}%)"
            )
            return trade

        finally:
            session.close()

    def take_snapshot(self) -> PortfolioSnapshot:
        """Take a snapshot of current portfolio for performance tracking."""
        portfolio = self.get_portfolio_value()

        session = self.db.get_session()
        try:
            # Get previous snapshot for daily P&L calculation
            prev_snapshot = self.db.get_latest_snapshot(session)

            daily_pl = None
            daily_pl_pct = None
            if prev_snapshot:
                daily_pl = portfolio['total_value'] - prev_snapshot.total_value
                daily_pl_pct = (daily_pl / prev_snapshot.total_value * 100) if prev_snapshot.total_value > 0 else 0

            # Track peak and drawdown
            peak_value = portfolio['total_value']
            if prev_snapshot and prev_snapshot.peak_value:
                peak_value = max(peak_value, prev_snapshot.peak_value)

            drawdown = portfolio['total_value'] - peak_value
            drawdown_pct = (drawdown / peak_value * 100) if peak_value > 0 else 0

            snapshot = PortfolioSnapshot(
                date=datetime.utcnow(),
                total_value=portfolio['total_value'],
                cash_balance=portfolio['cash_balance'],
                holdings_value=portfolio['holdings_value'],
                daily_pl=daily_pl,
                daily_pl_pct=daily_pl_pct,
                total_pl=portfolio['total_pnl'],
                total_pl_pct=portfolio['total_pnl_pct'],
                peak_value=peak_value,
                drawdown=drawdown,
                drawdown_pct=drawdown_pct,
                num_holdings=portfolio['num_holdings']
            )

            snapshot = self.db.add_snapshot(session, snapshot)
            return snapshot

        finally:
            session.close()

    def get_trade_history(self, symbol: str = None, limit: int = 50) -> List[Dict]:
        """Get trade history."""
        session = self.db.get_session()
        try:
            trades = self.db.get_trades(session, symbol, limit)
            return [{
                'id': t.id,
                'symbol': t.symbol,
                'action': t.action,
                'quantity': t.quantity,
                'price': t.price,
                'total_value': t.total_value,
                'profit_loss': t.profit_loss,
                'profit_loss_pct': t.profit_loss_pct,
                'hold_days': t.hold_days,
                'executed_at': t.executed_at
            } for t in trades]
        finally:
            session.close()

    def print_summary(self):
        """Print portfolio summary to console."""
        portfolio = self.get_portfolio_value()
        holdings = self.get_holdings()

        print("\n" + "=" * 60)
        print("PORTFOLIO SUMMARY")
        print("=" * 60)
        print(f"Cash Balance:    ${portfolio['cash_balance']:,.2f}")
        print(f"Holdings Value:  ${portfolio['holdings_value']:,.2f}")
        print(f"Total Value:     ${portfolio['total_value']:,.2f}")
        print(f"Total P&L:       ${portfolio['total_pnl']:+,.2f} ({portfolio['total_pnl_pct']:+.1f}%)")
        print("-" * 60)

        if holdings:
            print("\nHOLDINGS:")
            for h in holdings:
                print(f"  {h['symbol']}: {h['quantity']} shares @ ${h['avg_buy_price']:.2f}")
                print(f"    Current: ${h['current_price']:.2f} | P&L: ${h['unrealized_pnl']:+.2f} ({h['unrealized_pnl_pct']:+.1f}%)")
                print(f"    Stop: ${h['stop_loss_price']:.2f} | Target: ${h['take_profit_price']:.2f}")
        else:
            print("\nNo holdings")

        print("=" * 60)


# Singleton instance
_manager_instance: Optional[PortfolioManager] = None


def get_portfolio_manager() -> PortfolioManager:
    """Get or create the portfolio manager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = PortfolioManager()
    return _manager_instance
