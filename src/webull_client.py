"""
Webull API Client Wrapper

Handles:
- Authentication with MFA
- Paper trading mode
- Real trading mode
- Account info retrieval
- Order placement and tracking

NOTE: Uses the unofficial 'webull' package from PyPI.
      This could break if Webull changes their API.
"""

from typing import Optional, Dict, List, Any
from datetime import datetime
import uuid

from webull import webull, paper_webull

from src.credentials import CredentialManager
from src.config import get_config
from src.logger import main_log, trade_log


class WebullClient:
    """Wrapper for Webull API with paper trading support."""

    def __init__(self):
        self.config = get_config()
        self.creds = CredentialManager()
        self._wb = None
        self._is_paper = self.config.paper_trading.enabled
        self._logged_in = False
        self._account_id = None

    @property
    def is_paper_trading(self) -> bool:
        """Check if running in paper trading mode."""
        return self._is_paper

    def _get_or_create_device_id(self) -> str:
        """Get existing device ID or create a new one."""
        device_id = self.creds.webull_device_id
        if not device_id:
            device_id = str(uuid.uuid4())
            self.creds.setup_device_id(device_id)
            main_log.info("Generated new Webull device ID")
        return device_id

    def login(self) -> bool:
        """
        Login to Webull.

        For first-time login, MFA verification code will be required.
        The device ID is stored in Keychain for subsequent logins.
        """
        if not self.creds.is_webull_configured():
            main_log.error("Webull credentials not configured. Run: python src/credentials.py --setup")
            return False

        try:
            # Initialize appropriate client
            if self._is_paper:
                self._wb = paper_webull()
                main_log.info("Initialized Webull PAPER trading client")
            else:
                self._wb = webull()
                main_log.info("Initialized Webull REAL trading client")

            # Get device ID
            device_id = self._get_or_create_device_id()

            # Attempt login
            result = self._wb.login(
                self.creds.webull_email,
                self.creds.webull_password,
                device_id
            )

            if result and 'accessToken' in str(result):
                self._logged_in = True
                main_log.info("Webull login successful")

                # Get account ID
                self._account_id = self._wb.get_account_id()
                main_log.info(f"Account ID: {self._account_id}")

                return True
            else:
                # May need MFA
                main_log.warning("Login may require MFA verification")
                return self._handle_mfa()

        except Exception as e:
            main_log.error(f"Webull login failed: {e}")
            return False

    def _handle_mfa(self) -> bool:
        """Handle MFA verification."""
        try:
            # Send verification code
            self._wb.get_mfa(self.creds.webull_email)
            main_log.info("MFA code sent to your email/phone")

            # Get code from user (this would need to be interactive)
            mfa_code = input("Enter MFA verification code: ").strip()

            # Verify MFA
            result = self._wb.login(
                self.creds.webull_email,
                self.creds.webull_password,
                self._get_or_create_device_id(),
                mfa_code
            )

            if result:
                self._logged_in = True
                self._account_id = self._wb.get_account_id()
                main_log.info("MFA verification successful")
                return True

            main_log.error("MFA verification failed")
            return False

        except Exception as e:
            main_log.error(f"MFA handling failed: {e}")
            return False

    def get_account_info(self) -> Optional[Dict]:
        """Get account information including balances."""
        if not self._logged_in:
            main_log.error("Not logged in")
            return None

        try:
            account = self._wb.get_account()
            return {
                'account_id': self._account_id,
                'net_liquidation': float(account.get('netLiquidation', 0)),
                'total_cash': float(account.get('totalCash', 0)),
                'buying_power': float(account.get('dayBuyingPower', 0)),
                'unrealized_pl': float(account.get('unrealizedProfitLoss', 0)),
                'account_type': 'paper' if self._is_paper else 'live'
            }
        except Exception as e:
            main_log.error(f"Failed to get account info: {e}")
            return None

    def get_positions(self) -> List[Dict]:
        """Get current positions."""
        if not self._logged_in:
            main_log.error("Not logged in")
            return []

        try:
            positions = self._wb.get_positions()
            if not positions:
                return []

            return [{
                'symbol': pos.get('ticker', {}).get('symbol'),
                'quantity': int(pos.get('position', 0)),
                'avg_cost': float(pos.get('costPrice', 0)),
                'current_price': float(pos.get('lastPrice', 0)),
                'market_value': float(pos.get('marketValue', 0)),
                'unrealized_pl': float(pos.get('unrealizedProfitLoss', 0)),
                'unrealized_pl_pct': float(pos.get('unrealizedProfitLossRate', 0)) * 100
            } for pos in positions]

        except Exception as e:
            main_log.error(f"Failed to get positions: {e}")
            return []

    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get current quote for a symbol."""
        try:
            quote = self._wb.get_quote(symbol)
            if not quote:
                return None

            return {
                'symbol': symbol,
                'price': float(quote.get('close', 0)),
                'open': float(quote.get('open', 0)),
                'high': float(quote.get('high', 0)),
                'low': float(quote.get('low', 0)),
                'volume': int(quote.get('volume', 0)),
                'change': float(quote.get('change', 0)),
                'change_pct': float(quote.get('changeRatio', 0)) * 100
            }
        except Exception as e:
            main_log.error(f"Failed to get quote for {symbol}: {e}")
            return None

    def place_order(
        self,
        symbol: str,
        action: str,  # 'BUY' or 'SELL'
        quantity: int,
        order_type: str = 'LMT',  # 'LMT' or 'MKT'
        price: Optional[float] = None,
        time_in_force: str = 'GTC'  # 'GTC' or 'DAY'
    ) -> Optional[Dict]:
        """
        Place a buy or sell order.

        Args:
            symbol: Stock ticker symbol
            action: 'BUY' or 'SELL'
            quantity: Number of shares
            order_type: 'LMT' for limit order, 'MKT' for market order
            price: Limit price (required for limit orders)
            time_in_force: 'GTC' (good till cancelled) or 'DAY'

        Returns:
            Order details dict or None if failed
        """
        if not self._logged_in:
            main_log.error("Not logged in")
            return None

        # Validate inputs
        if action not in ['BUY', 'SELL']:
            main_log.error(f"Invalid action: {action}")
            return None

        if order_type == 'LMT' and price is None:
            main_log.error("Price required for limit orders")
            return None

        try:
            # Get trading PIN
            trading_pin = self.creds.webull_trading_pin
            if not trading_pin:
                main_log.error("Trading PIN not configured")
                return None

            # Place order
            trade_log.info(f"Placing {action} order: {quantity} x {symbol} @ {price or 'MKT'}")

            if order_type == 'LMT':
                result = self._wb.place_order(
                    stock=symbol,
                    tId=None,  # Will be looked up
                    price=price,
                    action=action,
                    orderType='LMT',
                    enforce=time_in_force,
                    quant=quantity
                )
            else:
                result = self._wb.place_order(
                    stock=symbol,
                    tId=None,
                    action=action,
                    orderType='MKT',
                    enforce=time_in_force,
                    quant=quantity
                )

            if result and 'orderId' in str(result):
                order_id = result.get('orderId')
                trade_log.info(f"Order placed successfully. Order ID: {order_id}")
                return {
                    'order_id': order_id,
                    'symbol': symbol,
                    'action': action,
                    'quantity': quantity,
                    'order_type': order_type,
                    'price': price,
                    'status': 'SUBMITTED',
                    'timestamp': datetime.utcnow().isoformat()
                }
            else:
                trade_log.error(f"Order placement failed: {result}")
                return None

        except Exception as e:
            trade_log.error(f"Failed to place order: {e}")
            return None

    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """Get status of a specific order."""
        if not self._logged_in:
            return None

        try:
            orders = self._wb.get_history_orders(status='All')
            for order in orders:
                if str(order.get('orderId')) == str(order_id):
                    return {
                        'order_id': order_id,
                        'symbol': order.get('ticker', {}).get('symbol'),
                        'action': order.get('action'),
                        'quantity': order.get('totalQuantity'),
                        'filled_quantity': order.get('filledQuantity', 0),
                        'price': order.get('lmtPrice'),
                        'avg_fill_price': order.get('avgFilledPrice'),
                        'status': order.get('status'),
                        'status_str': order.get('statusStr')
                    }
            return None
        except Exception as e:
            main_log.error(f"Failed to get order status: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        if not self._logged_in:
            return False

        try:
            result = self._wb.cancel_order(order_id)
            if result:
                trade_log.info(f"Order {order_id} cancelled")
                return True
            return False
        except Exception as e:
            trade_log.error(f"Failed to cancel order: {e}")
            return False

    def get_day_trades_count(self) -> int:
        """Get number of day trades in rolling 5 days (for PDT tracking)."""
        if not self._logged_in:
            return 0

        try:
            account = self._wb.get_account()
            return int(account.get('dayTradeCount', 0))
        except Exception as e:
            main_log.error(f"Failed to get day trade count: {e}")
            return 0

    def is_market_open(self) -> bool:
        """Check if market is currently open."""
        try:
            return self._wb.is_tradable()
        except Exception as e:
            main_log.error(f"Failed to check market status: {e}")
            return False


# Singleton instance
_client_instance: Optional[WebullClient] = None


def get_webull_client() -> WebullClient:
    """Get or create the Webull client instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = WebullClient()
    return _client_instance
