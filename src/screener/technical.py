"""
Technical Analysis Indicators

Calculates:
- RSI (Relative Strength Index)
- Moving Averages (SMA, EMA)
- Volume analysis
- Price momentum
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict
from ta.momentum import RSIIndicator
from ta.volume import VolumeWeightedAveragePrice
from ta.trend import SMAIndicator, EMAIndicator


def calculate_rsi(prices: pd.Series, period: int = 14) -> float:
    """
    Calculate RSI (Relative Strength Index).

    Args:
        prices: Series of closing prices
        period: RSI period (default 14)

    Returns:
        Current RSI value (0-100)
    """
    if len(prices) < period + 1:
        return 50.0  # Neutral if not enough data

    rsi = RSIIndicator(close=prices, window=period)
    rsi_values = rsi.rsi()

    if rsi_values.empty or pd.isna(rsi_values.iloc[-1]):
        return 50.0

    return float(rsi_values.iloc[-1])


def calculate_sma(prices: pd.Series, period: int) -> float:
    """Calculate Simple Moving Average."""
    if len(prices) < period:
        return float(prices.mean())

    sma = SMAIndicator(close=prices, window=period)
    sma_values = sma.sma_indicator()

    if sma_values.empty or pd.isna(sma_values.iloc[-1]):
        return float(prices.mean())

    return float(sma_values.iloc[-1])


def calculate_ema(prices: pd.Series, period: int) -> float:
    """Calculate Exponential Moving Average."""
    if len(prices) < period:
        return float(prices.mean())

    ema = EMAIndicator(close=prices, window=period)
    ema_values = ema.ema_indicator()

    if ema_values.empty or pd.isna(ema_values.iloc[-1]):
        return float(prices.mean())

    return float(ema_values.iloc[-1])


def calculate_volume_surge(volumes: pd.Series, period: int = 20) -> float:
    """
    Calculate current volume as percentage of average volume.

    Args:
        volumes: Series of daily volumes
        period: Averaging period (default 20 days)

    Returns:
        Volume surge percentage (100 = average, 200 = 2x average)
    """
    if len(volumes) < period:
        return 100.0

    avg_volume = volumes.iloc[:-1].tail(period).mean()
    current_volume = volumes.iloc[-1]

    if avg_volume == 0:
        return 100.0

    return (current_volume / avg_volume) * 100


def calculate_52week_position(current_price: float, high_52w: float, low_52w: float) -> Dict:
    """
    Calculate price position relative to 52-week range.

    Returns:
        Dict with:
        - distance_from_low_pct: % above 52-week low
        - distance_from_high_pct: % below 52-week high
        - range_position: 0-100 where 0=at low, 100=at high
    """
    if high_52w == low_52w:
        return {
            'distance_from_low_pct': 0,
            'distance_from_high_pct': 0,
            'range_position': 50
        }

    distance_from_low_pct = ((current_price - low_52w) / low_52w) * 100
    distance_from_high_pct = ((high_52w - current_price) / high_52w) * 100
    range_position = ((current_price - low_52w) / (high_52w - low_52w)) * 100

    return {
        'distance_from_low_pct': round(distance_from_low_pct, 2),
        'distance_from_high_pct': round(distance_from_high_pct, 2),
        'range_position': round(range_position, 2)
    }


def calculate_price_momentum(prices: pd.Series, period: int = 5) -> float:
    """
    Calculate price momentum (% change over period).

    Args:
        prices: Series of closing prices
        period: Number of days for momentum calculation

    Returns:
        Momentum as percentage change
    """
    if len(prices) < period + 1:
        return 0.0

    current = prices.iloc[-1]
    previous = prices.iloc[-period - 1]

    if previous == 0:
        return 0.0

    return ((current - previous) / previous) * 100


def get_technical_indicators(df: pd.DataFrame) -> Dict:
    """
    Calculate all technical indicators for a stock.

    Args:
        df: DataFrame with columns: Open, High, Low, Close, Volume

    Returns:
        Dict with all calculated indicators
    """
    close = df['Close']
    volume = df['Volume']
    high = df['High']
    low = df['Low']

    # Calculate 52-week high/low
    high_52w = high.tail(252).max() if len(high) >= 252 else high.max()
    low_52w = low.tail(252).min() if len(low) >= 252 else low.min()

    current_price = close.iloc[-1]

    return {
        'rsi_14': calculate_rsi(close, 14),
        'sma_20': calculate_sma(close, 20),
        'sma_50': calculate_sma(close, 50),
        'sma_200': calculate_sma(close, 200),
        'ema_12': calculate_ema(close, 12),
        'ema_26': calculate_ema(close, 26),
        'volume_surge_pct': calculate_volume_surge(volume, 20),
        'momentum_5d': calculate_price_momentum(close, 5),
        'momentum_20d': calculate_price_momentum(close, 20),
        'high_52w': float(high_52w),
        'low_52w': float(low_52w),
        'current_price': float(current_price),
        **calculate_52week_position(current_price, high_52w, low_52w)
    }


def is_oversold(rsi: float, threshold: float = 40) -> bool:
    """Check if RSI indicates oversold condition."""
    return rsi < threshold


def is_overbought(rsi: float, threshold: float = 70) -> bool:
    """Check if RSI indicates overbought condition."""
    return rsi > threshold


def has_volume_surge(volume_pct: float, threshold: float = 150) -> bool:
    """Check if volume is above threshold % of average."""
    return volume_pct >= threshold


def is_near_52week_low(distance_from_low_pct: float, threshold: float = 15) -> bool:
    """Check if price is within threshold % of 52-week low."""
    return distance_from_low_pct <= threshold


def price_above_sma(current_price: float, sma: float) -> bool:
    """Check if current price is above SMA."""
    return current_price > sma
