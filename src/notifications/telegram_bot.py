"""
Telegram Bot for Trade Notifications and Approvals

This module handles:
- Sending trade approval requests
- Waiting for user responses (Y/N)
- Sending execution confirmations
- Daily portfolio summaries

FREE alternative to Twilio SMS - unlimited messages!
"""

import time
import requests
from typing import Optional, Dict, List
from datetime import datetime, timedelta

from src.credentials import CredentialManager
from src.config import get_config
from src.db.models import get_database, Signal, SignalStatus
from src.logger import main_log


class TelegramBot:
    """Telegram bot client for trade notifications and approvals."""

    def __init__(self):
        self.config = get_config()
        self.creds = CredentialManager()
        self.db = get_database()
        self._last_update_id = 0

    @property
    def bot_token(self) -> Optional[str]:
        return self.creds.telegram_bot_token

    @property
    def chat_id(self) -> Optional[str]:
        return self.creds.telegram_chat_id

    @property
    def api_url(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}"

    def is_configured(self) -> bool:
        """Check if Telegram credentials are configured."""
        return self.creds.is_telegram_configured()

    def send_message(self, message: str) -> Optional[Dict]:
        """
        Send a message via Telegram.

        Args:
            message: The message text to send

        Returns:
            API response dict or None if failed
        """
        if not self.is_configured():
            main_log.error("Telegram not configured. Run: python src/credentials.py --setup")
            return None

        try:
            url = f"{self.api_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            result = response.json()

            if result.get("ok"):
                main_log.info(f"Telegram message sent successfully")
                return result
            else:
                main_log.error(f"Telegram API error: {result}")
                return None

        except Exception as e:
            main_log.error(f"Failed to send Telegram message: {e}")
            return None

    def get_updates(self, offset: int = 0) -> List[Dict]:
        """
        Get incoming messages from Telegram.

        Args:
            offset: Update ID offset to avoid duplicates

        Returns:
            List of update objects
        """
        if not self.is_configured():
            return []

        try:
            url = f"{self.api_url}/getUpdates"
            params = {
                "offset": offset,
                "timeout": 5,
                "allowed_updates": ["message"]
            }
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            result = response.json()

            if result.get("ok"):
                return result.get("result", [])
            return []

        except Exception as e:
            main_log.error(f"Failed to get Telegram updates: {e}")
            return []

    def format_trade_approval(self, signal: Signal) -> str:
        """Format a trade approval request message."""
        total_value = signal.suggested_price * signal.suggested_quantity
        timeout_minutes = self.config.trading.approval_timeout_minutes

        message = f"""
*TRADE APPROVAL #{signal.id}*

Action: *{signal.action}*
Stock: *{signal.symbol}*
Price: ${signal.suggested_price:.2f}
Shares: {signal.suggested_quantity}
Total: ${total_value:.2f}

Reason: {signal.reason}

Reply:
  *Y* - Approve
  *N* - Reject

_Expires in {timeout_minutes} min_
"""
        return message.strip()

    def format_execution_confirmation(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        pnl: Optional[float] = None,
        pnl_pct: Optional[float] = None
    ) -> str:
        """Format a trade execution confirmation message."""
        total = price * quantity

        if action == "BUY":
            stop_loss = price * 0.95  # -5%
            take_profit = price * 1.10  # +10%
            message = f"""
*ORDER EXECUTED*

BUY {quantity}x {symbol}
@ ${price:.2f}
Total: ${total:.2f}

Stop-loss: ${stop_loss:.2f} (-5%)
Take-profit: ${take_profit:.2f} (+10%)
"""
        else:
            pnl_str = f"${pnl:.2f}" if pnl is not None else "N/A"
            pnl_pct_str = f"{pnl_pct:+.1f}%" if pnl_pct is not None else ""
            message = f"""
*ORDER EXECUTED*

SELL {quantity}x {symbol}
@ ${price:.2f}
Total: ${total:.2f}

P&L: {pnl_str} ({pnl_pct_str})
"""
        return message.strip()

    def format_stop_loss_alert(self, symbol: str, price: float, loss_pct: float) -> str:
        """Format a stop-loss alert message."""
        return f"""
*STOP-LOSS TRIGGERED*

{symbol} @ ${price:.2f}
Loss: {loss_pct:.1f}%

Sell signal generated - check for approval request.
"""

    def format_daily_summary(self, portfolio: Dict) -> str:
        """Format a daily portfolio summary message."""
        message = f"""
*DAILY SUMMARY*

Total Value: ${portfolio.get('total_value', 0):,.2f}
Cash: ${portfolio.get('cash_balance', 0):,.2f}
Holdings: {portfolio.get('num_holdings', 0)}

P&L Today: ${portfolio.get('daily_pl', 0):,.2f} ({portfolio.get('daily_pl_pct', 0):+.1f}%)
P&L Total: ${portfolio.get('total_pl', 0):,.2f} ({portfolio.get('total_pl_pct', 0):+.1f}%)
"""
        return message.strip()

    def send_trade_approval_request(self, signal: Signal) -> bool:
        """
        Send a trade approval request.

        Args:
            signal: The trading signal to approve

        Returns:
            True if message sent successfully
        """
        message = self.format_trade_approval(signal)
        result = self.send_message(message)

        if result:
            # Update signal with sent timestamp
            session = self.db.get_session()
            try:
                db_signal = session.query(Signal).filter(Signal.id == signal.id).first()
                if db_signal:
                    db_signal.sms_sent_at = datetime.utcnow()
                    session.commit()
            finally:
                session.close()

            main_log.info(f"Approval request sent for signal #{signal.id}")
            return True

        return False

    def send_execution_confirmation(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        pnl: Optional[float] = None,
        pnl_pct: Optional[float] = None
    ) -> bool:
        """Send trade execution confirmation."""
        message = self.format_execution_confirmation(
            symbol, action, quantity, price, pnl, pnl_pct
        )
        return self.send_message(message) is not None

    def send_stop_loss_alert(self, symbol: str, price: float, loss_pct: float) -> bool:
        """Send stop-loss alert."""
        message = self.format_stop_loss_alert(symbol, price, loss_pct)
        return self.send_message(message) is not None

    def send_daily_summary(self, portfolio: Dict) -> bool:
        """Send daily portfolio summary."""
        message = self.format_daily_summary(portfolio)
        return self.send_message(message) is not None

    def wait_for_response(
        self,
        signal_id: int,
        timeout_minutes: Optional[int] = None
    ) -> Optional[str]:
        """
        Wait for user response to an approval request.

        Polls Telegram for incoming messages and looks for Y/N responses.

        Args:
            signal_id: The signal ID we're waiting for approval on
            timeout_minutes: How long to wait (default: from config)

        Returns:
            'Y' for approved, 'N' for rejected, 'M' for modify, None for timeout
        """
        if timeout_minutes is None:
            timeout_minutes = self.config.trading.approval_timeout_minutes

        start_time = datetime.utcnow()
        timeout_delta = timedelta(minutes=timeout_minutes)
        check_interval = 5  # seconds

        main_log.info(f"Waiting for response to signal #{signal_id} (timeout: {timeout_minutes} min)")

        # Get current update_id to only look at new messages
        updates = self.get_updates(offset=0)
        if updates:
            self._last_update_id = updates[-1]["update_id"] + 1

        while datetime.utcnow() - start_time < timeout_delta:
            time.sleep(check_interval)

            # Check for timeout
            if datetime.utcnow() - start_time >= timeout_delta:
                break

            # Get new messages
            updates = self.get_updates(offset=self._last_update_id)

            for update in updates:
                self._last_update_id = update["update_id"] + 1

                message = update.get("message", {})
                text = message.get("text", "").strip().upper()
                chat_id = str(message.get("chat", {}).get("id", ""))

                # Only process messages from our configured chat
                if chat_id != self.chat_id:
                    continue

                # Check for approval responses
                if text in ["Y", "YES", "APPROVE"]:
                    self._update_signal_response(signal_id, "Y", SignalStatus.APPROVED)
                    main_log.info(f"Signal #{signal_id} APPROVED by user")
                    return "Y"

                elif text in ["N", "NO", "REJECT"]:
                    self._update_signal_response(signal_id, "N", SignalStatus.REJECTED)
                    main_log.info(f"Signal #{signal_id} REJECTED by user")
                    return "N"

                elif text in ["M", "MOD", "MODIFY"]:
                    main_log.info(f"Signal #{signal_id} MODIFY requested")
                    return "M"

        # Timeout reached
        self._update_signal_status(signal_id, SignalStatus.EXPIRED)
        main_log.warning(f"Signal #{signal_id} EXPIRED (no response within {timeout_minutes} min)")
        return None

    def _update_signal_response(self, signal_id: int, response: str, status: SignalStatus):
        """Update signal with user response."""
        session = self.db.get_session()
        try:
            signal = session.query(Signal).filter(Signal.id == signal_id).first()
            if signal:
                signal.user_response = response
                signal.responded_at = datetime.utcnow()
                signal.status = status.value
                session.commit()
        finally:
            session.close()

    def _update_signal_status(self, signal_id: int, status: SignalStatus):
        """Update signal status."""
        session = self.db.get_session()
        try:
            signal = session.query(Signal).filter(Signal.id == signal_id).first()
            if signal:
                signal.status = status.value
                session.commit()
        finally:
            session.close()


class ApprovalManager:
    """High-level approval workflow manager."""

    def __init__(self):
        self.telegram = TelegramBot()
        self.db = get_database()

    def request_approval(self, signal: Signal) -> Optional[str]:
        """
        Request approval for a trading signal.

        Sends a Telegram message and waits for Y/N response.

        Args:
            signal: The signal to approve

        Returns:
            'Y' for approved, 'N' for rejected, 'M' for modify, None for timeout
        """
        # Send approval request
        if not self.telegram.send_trade_approval_request(signal):
            main_log.error(f"Failed to send approval request for signal #{signal.id}")
            return None

        # Wait for response
        response = self.telegram.wait_for_response(signal.id)

        return response

    def process_pending_signals(self) -> Dict[str, int]:
        """
        Process all pending signals.

        Returns:
            Dict with counts: {'approved': n, 'rejected': n, 'expired': n}
        """
        results = {"approved": 0, "rejected": 0, "expired": 0, "error": 0}

        session = self.db.get_session()
        try:
            pending = self.db.get_pending_signals(session)

            for signal in pending:
                response = self.request_approval(signal)

                if response == "Y":
                    results["approved"] += 1
                elif response == "N":
                    results["rejected"] += 1
                elif response is None:
                    results["expired"] += 1
                else:
                    results["error"] += 1

        finally:
            session.close()

        return results


# Singleton instances
_telegram_instance: Optional[TelegramBot] = None
_approval_instance: Optional[ApprovalManager] = None


def get_telegram_client() -> TelegramBot:
    """Get or create the Telegram client instance."""
    global _telegram_instance
    if _telegram_instance is None:
        _telegram_instance = TelegramBot()
    return _telegram_instance


def get_approval_manager() -> ApprovalManager:
    """Get or create the approval manager instance."""
    global _approval_instance
    if _approval_instance is None:
        _approval_instance = ApprovalManager()
    return _approval_instance
