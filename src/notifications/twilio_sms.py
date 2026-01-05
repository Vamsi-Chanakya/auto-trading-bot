"""
Twilio SMS Notification System

Handles:
- Sending trade approval requests
- Receiving user responses
- Sending trade confirmations
- Daily portfolio summaries
"""

from typing import Optional, Dict, List
from datetime import datetime, timedelta
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import time
import threading

from src.credentials import CredentialManager
from src.config import get_config
from src.db.models import get_database, Signal, SignalStatus
from src.logger import sms_log


class TwilioSMS:
    """Twilio SMS client for trade notifications and approvals."""

    def __init__(self):
        self.creds = CredentialManager()
        self.config = get_config()
        self._client = None
        self._initialized = False

    def _initialize(self) -> bool:
        """Initialize Twilio client."""
        if self._initialized:
            return True

        if not self.creds.is_twilio_configured():
            sms_log.error("Twilio credentials not configured. Run: python src/credentials.py --setup")
            return False

        try:
            self._client = Client(
                self.creds.twilio_account_sid,
                self.creds.twilio_auth_token
            )
            self._initialized = True
            sms_log.info("Twilio client initialized")
            return True
        except Exception as e:
            sms_log.error(f"Failed to initialize Twilio: {e}")
            return False

    @property
    def from_number(self) -> str:
        """Get Twilio phone number."""
        return self.creds.twilio_phone_number

    @property
    def to_number(self) -> str:
        """Get user's phone number."""
        return self.creds.user_phone_number

    def send_sms(self, message: str) -> Optional[str]:
        """
        Send an SMS message.

        Returns:
            Message SID if successful, None if failed
        """
        if not self._initialize():
            return None

        try:
            msg = self._client.messages.create(
                body=message,
                from_=self.from_number,
                to=self.to_number
            )
            sms_log.info(f"SMS sent: {msg.sid}")
            return msg.sid
        except TwilioRestException as e:
            sms_log.error(f"Twilio error: {e}")
            return None
        except Exception as e:
            sms_log.error(f"Failed to send SMS: {e}")
            return None

    def format_trade_approval(self, signal: Signal) -> str:
        """Format trade approval request message."""
        action = signal.action
        symbol = signal.symbol
        price = signal.suggested_price
        quantity = signal.suggested_quantity
        total = price * quantity
        reason = signal.reason

        # Calculate timeout
        if signal.expires_at:
            minutes_left = max(0, int((signal.expires_at - datetime.utcnow()).total_seconds() / 60))
        else:
            minutes_left = self.config.trading.approval_timeout_minutes

        message = f"""
TRADE APPROVAL #{signal.id}

Action: {action}
Stock: {symbol}
Price: ${price:.2f}
Shares: {quantity}
Total: ${total:.2f}

Reason: {reason}

Reply:
  Y - Approve
  N - Reject

Expires in {minutes_left} min
"""
        return message.strip()

    def format_execution_confirmation(self, symbol: str, action: str,
                                       quantity: int, price: float,
                                       pnl: float = None, pnl_pct: float = None) -> str:
        """Format trade execution confirmation message."""
        total = price * quantity

        if action == 'BUY':
            # Calculate stop-loss and take-profit
            stop_loss = price * (1 + self.config.trading.stop_loss_pct / 100)
            take_profit = price * (1 + self.config.trading.take_profit_pct / 100)

            message = f"""
ORDER EXECUTED

{action} {quantity}x {symbol}
@ ${price:.2f}
Total: ${total:.2f}

Stop-loss: ${stop_loss:.2f} (-5%)
Take-profit: ${take_profit:.2f} (+10%)
"""
        else:  # SELL
            pnl_str = f"${pnl:+.2f} ({pnl_pct:+.1f}%)" if pnl is not None else "N/A"
            message = f"""
ORDER EXECUTED

{action} {quantity}x {symbol}
@ ${price:.2f}
Total: ${total:.2f}

P&L: {pnl_str}
"""
        return message.strip()

    def format_stop_loss_alert(self, symbol: str, current_price: float,
                                buy_price: float, loss_pct: float) -> str:
        """Format stop-loss triggered alert."""
        return f"""
STOP-LOSS TRIGGERED

{symbol}
Buy: ${buy_price:.2f}
Now: ${current_price:.2f}
Loss: {loss_pct:.1f}%

Selling position automatically.
"""

    def format_daily_summary(self, portfolio: Dict) -> str:
        """Format daily portfolio summary."""
        return f"""
DAILY SUMMARY

Portfolio Value: ${portfolio['total_value']:,.2f}
Cash: ${portfolio['cash_balance']:,.2f}
Holdings: ${portfolio['holdings_value']:,.2f}

Total P&L: ${portfolio['total_pnl']:+,.2f} ({portfolio['total_pnl_pct']:+.1f}%)
Holdings: {portfolio['num_holdings']}/{self.config.trading.max_holdings}
"""

    def send_trade_approval_request(self, signal: Signal) -> bool:
        """
        Send trade approval request via SMS.

        Returns:
            True if sent successfully
        """
        if not self.config.notifications.sms_enabled:
            sms_log.info("SMS notifications disabled")
            return False

        message = self.format_trade_approval(signal)
        msg_sid = self.send_sms(message)

        if msg_sid:
            # Update signal with SMS sent timestamp
            db = get_database()
            session = db.get_session()
            try:
                db_signal = session.query(Signal).filter(Signal.id == signal.id).first()
                if db_signal:
                    db_signal.sms_sent_at = datetime.utcnow()
                    session.commit()
            finally:
                session.close()

            return True

        return False

    def send_execution_confirmation(self, symbol: str, action: str,
                                     quantity: int, price: float,
                                     pnl: float = None, pnl_pct: float = None) -> bool:
        """Send trade execution confirmation via SMS."""
        if not self.config.notifications.send_on_execution:
            return False

        message = self.format_execution_confirmation(symbol, action, quantity, price, pnl, pnl_pct)
        return self.send_sms(message) is not None

    def send_stop_loss_alert(self, symbol: str, current_price: float,
                              buy_price: float, loss_pct: float) -> bool:
        """Send stop-loss triggered alert via SMS."""
        if not self.config.notifications.send_on_stop_loss:
            return False

        message = self.format_stop_loss_alert(symbol, current_price, buy_price, loss_pct)
        return self.send_sms(message) is not None

    def send_daily_summary(self, portfolio: Dict) -> bool:
        """Send daily portfolio summary via SMS."""
        if not self.config.notifications.send_daily_summary:
            return False

        message = self.format_daily_summary(portfolio)
        return self.send_sms(message) is not None

    def get_recent_incoming_messages(self, since: datetime = None,
                                      limit: int = 10) -> List[Dict]:
        """
        Get recent incoming SMS messages.

        Args:
            since: Only get messages after this time
            limit: Maximum number of messages

        Returns:
            List of message dicts with 'body', 'from', 'date_sent'
        """
        if not self._initialize():
            return []

        try:
            filters = {
                'to': self.from_number,  # Messages TO our Twilio number
                'limit': limit
            }

            if since:
                filters['date_sent_after'] = since

            messages = self._client.messages.list(**filters)

            return [{
                'sid': msg.sid,
                'body': msg.body.strip().upper() if msg.body else '',
                'from': msg.from_,
                'date_sent': msg.date_sent,
                'status': msg.status
            } for msg in messages]

        except Exception as e:
            sms_log.error(f"Failed to get incoming messages: {e}")
            return []

    def wait_for_response(self, signal_id: int, timeout_minutes: int = None) -> Optional[str]:
        """
        Wait for user response to a trade approval.

        Args:
            signal_id: ID of the signal awaiting approval
            timeout_minutes: How long to wait (default from config)

        Returns:
            User response ('Y', 'N', 'M') or None if timeout/error
        """
        if timeout_minutes is None:
            timeout_minutes = self.config.trading.approval_timeout_minutes

        db = get_database()
        start_time = datetime.utcnow()
        check_interval = 5  # Check every 5 seconds

        sms_log.info(f"Waiting for response to signal #{signal_id} (timeout: {timeout_minutes} min)")

        while True:
            # Check timeout
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            if elapsed >= timeout_minutes * 60:
                sms_log.info(f"Signal #{signal_id} timed out")

                # Update signal status to expired
                session = db.get_session()
                try:
                    db.update_signal_status(session, signal_id, SignalStatus.EXPIRED)
                finally:
                    session.close()

                return None

            # Check for incoming messages
            messages = self.get_recent_incoming_messages(since=start_time, limit=5)

            for msg in messages:
                body = msg['body']

                # Check for valid responses
                if body in ['Y', 'YES', 'APPROVE']:
                    sms_log.info(f"Signal #{signal_id} APPROVED")
                    self._update_signal_response(db, signal_id, 'Y', SignalStatus.APPROVED)
                    return 'Y'

                elif body in ['N', 'NO', 'REJECT']:
                    sms_log.info(f"Signal #{signal_id} REJECTED")
                    self._update_signal_response(db, signal_id, 'N', SignalStatus.REJECTED)
                    return 'N'

                elif body.startswith('M') or body.startswith('MOD'):
                    sms_log.info(f"Signal #{signal_id} MODIFY requested")
                    # For modify, we'd need additional logic
                    return 'M'

            # Wait before next check
            time.sleep(check_interval)

    def _update_signal_response(self, db, signal_id: int, response: str, status: SignalStatus):
        """Update signal with user response."""
        session = db.get_session()
        try:
            signal = session.query(Signal).filter(Signal.id == signal_id).first()
            if signal:
                signal.user_response = response
                signal.responded_at = datetime.utcnow()
                signal.status = status.value
                session.commit()
        finally:
            session.close()


class ApprovalManager:
    """Manages the trade approval workflow."""

    def __init__(self):
        self.sms = TwilioSMS()
        self.db = get_database()
        self.config = get_config()

    def request_approval(self, signal: Signal) -> Optional[str]:
        """
        Request approval for a trade signal.

        Sends SMS and waits for response.

        Returns:
            User response ('Y', 'N', 'M') or None if failed/timeout
        """
        # Send approval request
        if not self.sms.send_trade_approval_request(signal):
            sms_log.error(f"Failed to send approval request for signal #{signal.id}")
            return None

        # Wait for response
        return self.sms.wait_for_response(signal.id)

    def process_pending_signals(self) -> List[Dict]:
        """
        Process all pending signals that need approval.

        Returns:
            List of processed signals with their outcomes
        """
        results = []
        session = self.db.get_session()

        try:
            pending = self.db.get_pending_signals(session)

            for signal in pending:
                # Check if expired
                if signal.expires_at and datetime.utcnow() > signal.expires_at:
                    self.db.update_signal_status(session, signal.id, SignalStatus.EXPIRED)
                    results.append({
                        'signal_id': signal.id,
                        'symbol': signal.symbol,
                        'action': signal.action,
                        'outcome': 'EXPIRED'
                    })
                    continue

                # Request approval
                response = self.request_approval(signal)

                results.append({
                    'signal_id': signal.id,
                    'symbol': signal.symbol,
                    'action': signal.action,
                    'outcome': response or 'TIMEOUT'
                })

        finally:
            session.close()

        return results


# Singleton instances
_sms_client: Optional[TwilioSMS] = None
_approval_manager: Optional[ApprovalManager] = None


def get_sms_client() -> TwilioSMS:
    """Get or create SMS client instance."""
    global _sms_client
    if _sms_client is None:
        _sms_client = TwilioSMS()
    return _sms_client


def get_approval_manager() -> ApprovalManager:
    """Get or create approval manager instance."""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager
