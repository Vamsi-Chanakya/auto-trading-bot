"""
Configuration Loader

Loads settings from config/settings.yaml and provides
easy access throughout the application.
"""

import os
import yaml
from typing import Any, Optional
from dataclasses import dataclass

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config",
    "settings.yaml"
)


@dataclass
class TradingConfig:
    """Trading-related configuration."""
    initial_budget: float
    max_position_pct: float
    max_holdings: int
    stop_loss_pct: float
    take_profit_pct: float
    min_stock_price: float
    min_market_cap_millions: float
    min_hold_days: int
    approval_timeout_minutes: int
    max_drawdown_pct: float
    max_daily_trades: int

    @property
    def max_position_value(self) -> float:
        """Maximum value per position in dollars."""
        return self.initial_budget * (self.max_position_pct / 100)


@dataclass
class MarketConfig:
    """Market hours configuration."""
    timezone: str
    open_hour: int
    open_minute: int
    close_hour: int
    close_minute: int
    scan_interval_minutes: int


@dataclass
class ScreenerConfig:
    """Stock screening criteria."""
    max_pe_ratio: float
    near_52week_low_pct: float
    rsi_oversold: float
    rsi_overbought: float
    volume_surge_pct: float
    min_avg_volume: int
    exclude_sectors: list


@dataclass
class PaperTradingConfig:
    """Paper trading configuration."""
    enabled: bool
    starting_balance: float


@dataclass
class NotificationsConfig:
    """Notification settings."""
    sms_enabled: bool
    send_on_signal: bool
    send_on_execution: bool
    send_on_stop_loss: bool
    send_on_take_profit: bool
    send_daily_summary: bool


class Config:
    """Main configuration class."""

    def __init__(self, config_path: str = CONFIG_PATH):
        self._raw = self._load(config_path)
        self._parse()

    def _load(self, path: str) -> dict:
        """Load YAML configuration file."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with open(path, 'r') as f:
            return yaml.safe_load(f)

    def _parse(self):
        """Parse configuration into typed dataclasses."""
        trading = self._raw.get('trading', {})
        self.trading = TradingConfig(
            initial_budget=trading.get('initial_budget', 1000),
            max_position_pct=trading.get('max_position_pct', 33),
            max_holdings=trading.get('max_holdings', 2),
            stop_loss_pct=trading.get('stop_loss_pct', -5),
            take_profit_pct=trading.get('take_profit_pct', 10),
            min_stock_price=trading.get('min_stock_price', 5),
            min_market_cap_millions=trading.get('min_market_cap_millions', 500),
            min_hold_days=trading.get('min_hold_days', 2),
            approval_timeout_minutes=trading.get('approval_timeout_minutes', 15),
            max_drawdown_pct=trading.get('max_drawdown_pct', -15),
            max_daily_trades=trading.get('max_daily_trades', 4)
        )

        market = self._raw.get('market', {})
        self.market = MarketConfig(
            timezone=market.get('timezone', 'America/New_York'),
            open_hour=market.get('open_hour', 9),
            open_minute=market.get('open_minute', 30),
            close_hour=market.get('close_hour', 16),
            close_minute=market.get('close_minute', 0),
            scan_interval_minutes=market.get('scan_interval_minutes', 15)
        )

        screener = self._raw.get('screener', {})
        self.screener = ScreenerConfig(
            max_pe_ratio=screener.get('max_pe_ratio', 25),
            near_52week_low_pct=screener.get('near_52week_low_pct', 15),
            rsi_oversold=screener.get('rsi_oversold', 40),
            rsi_overbought=screener.get('rsi_overbought', 70),
            volume_surge_pct=screener.get('volume_surge_pct', 150),
            min_avg_volume=screener.get('min_avg_volume', 100000),
            exclude_sectors=screener.get('exclude_sectors', [])
        )

        paper = self._raw.get('paper_trading', {})
        self.paper_trading = PaperTradingConfig(
            enabled=paper.get('enabled', True),
            starting_balance=paper.get('starting_balance', 1000)
        )

        notif = self._raw.get('notifications', {})
        self.notifications = NotificationsConfig(
            sms_enabled=notif.get('sms_enabled', True),
            send_on_signal=notif.get('send_on_signal', True),
            send_on_execution=notif.get('send_on_execution', True),
            send_on_stop_loss=notif.get('send_on_stop_loss', True),
            send_on_take_profit=notif.get('send_on_take_profit', True),
            send_daily_summary=notif.get('send_daily_summary', True)
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Get a raw configuration value by dot-notation key."""
        keys = key.split('.')
        value = self._raw
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value


# Singleton instance
_config_instance: Optional[Config] = None


def get_config() -> Config:
    """Get or create the configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def reload_config():
    """Reload configuration from file."""
    global _config_instance
    _config_instance = Config()
    return _config_instance
