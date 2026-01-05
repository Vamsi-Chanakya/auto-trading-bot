"""
Logging Infrastructure for Auto Trading App

Features:
- Rotating log files (prevent disk space issues)
- Separate logs for trades, signals, and errors
- Console output for real-time monitoring
- Never logs sensitive credentials
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Log directory
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Log format
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Max log file size: 5MB, keep 5 backups
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """Create a logger with file and console handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent duplicate handlers
    if logger.handlers:
        return logger

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    # File handler (rotating)
    file_path = os.path.join(LOG_DIR, log_file)
    file_handler = RotatingFileHandler(
        file_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# Pre-configured loggers
def get_main_logger() -> logging.Logger:
    """Main application logger."""
    return setup_logger("main", "trading.log")


def get_trade_logger() -> logging.Logger:
    """Trade execution logger."""
    return setup_logger("trades", "trades.log")


def get_signal_logger() -> logging.Logger:
    """Signal generation logger."""
    return setup_logger("signals", "signals.log")


def get_error_logger() -> logging.Logger:
    """Error and exception logger."""
    return setup_logger("errors", "errors.log", logging.ERROR)


def get_sms_logger() -> logging.Logger:
    """SMS notification logger."""
    return setup_logger("sms", "sms.log")


class SensitiveFilter(logging.Filter):
    """Filter to prevent logging sensitive data."""

    SENSITIVE_KEYS = [
        "password", "pin", "token", "secret", "auth",
        "credential", "api_key", "apikey"
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Check and redact sensitive information."""
        if hasattr(record, 'msg'):
            msg = str(record.msg).lower()
            for key in self.SENSITIVE_KEYS:
                if key in msg:
                    record.msg = "[REDACTED - Contains sensitive data]"
                    break
        return True


# Apply sensitive filter to all loggers
def apply_sensitive_filter():
    """Apply sensitive data filter to root logger."""
    root_logger = logging.getLogger()
    root_logger.addFilter(SensitiveFilter())


# Initialize on import
apply_sensitive_filter()

# Quick access
main_log = get_main_logger()
trade_log = get_trade_logger()
signal_log = get_signal_logger()
error_log = get_error_logger()
sms_log = get_sms_logger()
