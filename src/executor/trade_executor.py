"""
Trade Executor

Handles:
- Executing approved trades on Webull
- Order management (place, monitor, cancel)
- Paper trading simulation
"""

from typing import Optional, Dict
from datetime import datetime
import time

from src.webull_client import get_webull_client
from src.portfolio.manager import get_portfolio_manager
from src.portfolio.risk import get_risk_manager
from src.notifications.twilio_sms import get_sms_client
from src.db.models import get_database, Signal, SignalStatus
from src.config import get_config
from src.logger import trade_log


class TradeExecutor:
    """Executes trades on Webull or paper trading simulator."""

    def __init__(self):
        self.config = get_config()
        self.webull = get_webull_client()
        self.portfolio = get_portfolio_manager()
        self.risk = get_risk_manager()
        self.sms = get_sms_client()
        self.db = get_database()
        self._is_paper = self.config.paper_trading.enabled

    @property
    def is_paper_trading(self) -> bool:
        """Check if running in paper trading mode."""
        return self._is_paper

    def execute_signal(self, signal: Signal) -> Dict:
        """
        Execute an approved trading signal.

        Args:
            signal: The approved Signal object

        Returns:
            Dict with execution result
        """
        result = {
            'success': False,
            'signal_id': signal.id,
            'symbol': signal.symbol,
            'action': signal.action,
            'message': ''
        }

        # Verify signal is approved
        if signal.status != SignalStatus.APPROVED.value:
            result['message'] = f"Signal not approved (status: {signal.status})"
            trade_log.warning(result['message'])
            return result

        # Pre-trade risk check
        portfolio_data = self.portfolio.get_portfolio_value()
        holdings_count = self.portfolio.get_holdings_count()

        risk_ok, risk_msg = self.risk.pre_trade_check(
            action=signal.action,
            symbol=signal.symbol,
            quantity=signal.suggested_quantity,
            price=signal.suggested_price,
            available_cash=portfolio_data['cash_balance'],
            current_holdings=holdings_count,
            portfolio_value=portfolio_data['total_value'],
            peak_value=portfolio_data.get('peak_value', portfolio_data['total_value'])
        )

        if not risk_ok:
            result['message'] = f"Risk check failed: {risk_msg}"
            trade_log.warning(result['message'])

            # Update signal status
            self._update_signal_status(signal.id, SignalStatus.CANCELLED, notes=risk_msg)
            return result

        # Execute based on mode
        if self._is_paper:
            return self._execute_paper_trade(signal, result)
        else:
            return self._execute_live_trade(signal, result)

    def _execute_paper_trade(self, signal: Signal, result: Dict) -> Dict:
        """Execute a paper (simulated) trade."""
        trade_log.info(f"[PAPER] Executing {signal.action} for {signal.symbol}")

        symbol = signal.symbol
        action = signal.action
        quantity = signal.suggested_quantity
        price = signal.suggested_price

        try:
            # Simulate execution (use suggested price as fill price)
            fill_price = price

            # Record in portfolio
            if action == 'BUY':
                trade = self.portfolio.record_buy(
                    symbol=symbol,
                    quantity=quantity,
                    price=fill_price,
                    order_id=f"PAPER-{datetime.utcnow().timestamp()}",
                    signal_id=signal.id
                )
                pnl = None
                pnl_pct = None
            else:  # SELL
                # Get holding info for P&L
                holdings = self.portfolio.get_holdings()
                holding = next((h for h in holdings if h['symbol'] == symbol), None)

                trade = self.portfolio.record_sell(
                    symbol=symbol,
                    quantity=quantity,
                    price=fill_price,
                    order_id=f"PAPER-{datetime.utcnow().timestamp()}",
                    signal_id=signal.id
                )
                pnl = trade.profit_loss
                pnl_pct = trade.profit_loss_pct

            # Update signal status
            self._update_signal_status(signal.id, SignalStatus.EXECUTED, trade_id=trade.id)

            # Send confirmation SMS
            self.sms.send_execution_confirmation(
                symbol=symbol,
                action=action,
                quantity=quantity,
                price=fill_price,
                pnl=pnl,
                pnl_pct=pnl_pct
            )

            result['success'] = True
            result['fill_price'] = fill_price
            result['trade_id'] = trade.id
            result['message'] = f"[PAPER] {action} {quantity}x {symbol} @ ${fill_price:.2f}"

            trade_log.info(result['message'])

        except Exception as e:
            result['message'] = f"Paper trade execution failed: {e}"
            trade_log.error(result['message'])
            self._update_signal_status(signal.id, SignalStatus.CANCELLED, notes=str(e))

        return result

    def _execute_live_trade(self, signal: Signal, result: Dict) -> Dict:
        """Execute a live trade on Webull."""
        trade_log.info(f"[LIVE] Executing {signal.action} for {signal.symbol}")

        symbol = signal.symbol
        action = signal.action
        quantity = signal.suggested_quantity
        price = signal.suggested_price

        try:
            # Ensure Webull is logged in
            if not self.webull._logged_in:
                if not self.webull.login():
                    result['message'] = "Failed to login to Webull"
                    trade_log.error(result['message'])
                    return result

            # Place limit order slightly better than current price
            # For BUY: slightly above to ensure fill
            # For SELL: slightly below to ensure fill
            if action == 'BUY':
                limit_price = round(price * 1.001, 2)  # 0.1% above
            else:
                limit_price = round(price * 0.999, 2)  # 0.1% below

            # Place order
            order_result = self.webull.place_order(
                symbol=symbol,
                action=action,
                quantity=quantity,
                order_type='LMT',
                price=limit_price,
                time_in_force='DAY'
            )

            if not order_result:
                result['message'] = "Order placement failed"
                trade_log.error(result['message'])
                self._update_signal_status(signal.id, SignalStatus.CANCELLED)
                return result

            order_id = order_result['order_id']
            trade_log.info(f"Order placed: {order_id}")

            # Wait for fill (with timeout)
            fill_price = self._wait_for_fill(order_id, timeout_seconds=60)

            if fill_price is None:
                # Order not filled - cancel and retry or give up
                self.webull.cancel_order(order_id)
                result['message'] = "Order not filled within timeout"
                trade_log.warning(result['message'])
                self._update_signal_status(signal.id, SignalStatus.CANCELLED, notes="Timeout - not filled")
                return result

            # Order filled - record in portfolio
            if action == 'BUY':
                trade = self.portfolio.record_buy(
                    symbol=symbol,
                    quantity=quantity,
                    price=fill_price,
                    order_id=order_id,
                    signal_id=signal.id
                )
                pnl = None
                pnl_pct = None
            else:  # SELL
                trade = self.portfolio.record_sell(
                    symbol=symbol,
                    quantity=quantity,
                    price=fill_price,
                    order_id=order_id,
                    signal_id=signal.id
                )
                pnl = trade.profit_loss
                pnl_pct = trade.profit_loss_pct

            # Update signal status
            self._update_signal_status(signal.id, SignalStatus.EXECUTED, trade_id=trade.id)

            # Send confirmation SMS
            self.sms.send_execution_confirmation(
                symbol=symbol,
                action=action,
                quantity=quantity,
                price=fill_price,
                pnl=pnl,
                pnl_pct=pnl_pct
            )

            result['success'] = True
            result['fill_price'] = fill_price
            result['order_id'] = order_id
            result['trade_id'] = trade.id
            result['message'] = f"[LIVE] {action} {quantity}x {symbol} @ ${fill_price:.2f}"

            trade_log.info(result['message'])

        except Exception as e:
            result['message'] = f"Live trade execution failed: {e}"
            trade_log.error(result['message'])
            self._update_signal_status(signal.id, SignalStatus.CANCELLED, notes=str(e))

        return result

    def _wait_for_fill(self, order_id: str, timeout_seconds: int = 60) -> Optional[float]:
        """
        Wait for an order to be filled.

        Returns:
            Fill price if filled, None if timeout/cancelled
        """
        start_time = time.time()
        check_interval = 2  # Check every 2 seconds

        while time.time() - start_time < timeout_seconds:
            status = self.webull.get_order_status(order_id)

            if status:
                if status.get('status') == 'Filled':
                    return status.get('avg_fill_price')
                elif status.get('status') in ['Cancelled', 'Rejected']:
                    return None

            time.sleep(check_interval)

        return None

    def _update_signal_status(self, signal_id: int, status: SignalStatus,
                               trade_id: int = None, notes: str = None):
        """Update signal status in database."""
        session = self.db.get_session()
        try:
            signal = session.query(Signal).filter(Signal.id == signal_id).first()
            if signal:
                signal.status = status.value
                if trade_id:
                    signal.trade_id = trade_id
                signal.updated_at = datetime.utcnow()
                session.commit()

                # Log to audit
                self.db.log_action(
                    session,
                    action_type='SIGNAL_STATUS_UPDATED',
                    symbol=signal.symbol,
                    description=f"Signal #{signal_id} status: {status.value}" + (f" - {notes}" if notes else ""),
                    signal_id=signal_id,
                    trade_id=trade_id
                )
        finally:
            session.close()

    def execute_approved_signals(self) -> list:
        """
        Find and execute all approved signals.

        Returns:
            List of execution results
        """
        results = []
        session = self.db.get_session()

        try:
            # Get approved signals
            approved = session.query(Signal).filter(
                Signal.status == SignalStatus.APPROVED.value
            ).all()

            for signal in approved:
                result = self.execute_signal(signal)
                results.append(result)

        finally:
            session.close()

        return results


# Singleton instance
_executor: Optional[TradeExecutor] = None


def get_trade_executor() -> TradeExecutor:
    """Get or create trade executor instance."""
    global _executor
    if _executor is None:
        _executor = TradeExecutor()
    return _executor
