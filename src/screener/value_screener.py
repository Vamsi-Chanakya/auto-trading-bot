"""
Value Stock Screener

Finds undervalued stocks based on:
- P/E ratio relative to market/industry
- Near 52-week lows
- Fundamental strength (revenue growth)
- Technical confirmation (RSI, volume)
"""

import yfinance as yf
import pandas as pd
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from src.screener.technical import get_technical_indicators, is_near_52week_low, is_oversold, has_volume_surge
from src.config import get_config
from src.logger import signal_log


# Stock universe - Major indices components (S&P 500 sample + additional mid-caps)
# In production, you'd want a more comprehensive list or API
STOCK_UNIVERSE = [
    # Technology
    'AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA', 'AMD', 'INTC', 'CRM', 'ADBE', 'ORCL',
    'CSCO', 'IBM', 'QCOM', 'TXN', 'AVGO', 'NOW', 'INTU', 'PYPL', 'SQ', 'SHOP',
    # Financial
    'JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'BLK', 'SCHW', 'AXP', 'V', 'MA',
    # Healthcare
    'JNJ', 'UNH', 'PFE', 'ABBV', 'MRK', 'LLY', 'TMO', 'ABT', 'DHR', 'BMY',
    # Consumer
    'AMZN', 'WMT', 'HD', 'COST', 'TGT', 'LOW', 'SBUX', 'MCD', 'NKE', 'DIS',
    # Industrial
    'CAT', 'DE', 'UPS', 'FDX', 'HON', 'GE', 'MMM', 'BA', 'LMT', 'RTX',
    # Energy
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'PXD', 'OXY', 'MPC', 'VLO', 'PSX',
    # Telecom & Utilities
    'T', 'VZ', 'TMUS', 'NEE', 'DUK', 'SO', 'D', 'AEP', 'EXC', 'SRE',
    # Real Estate
    'AMT', 'PLD', 'CCI', 'EQIX', 'PSA', 'SPG', 'O', 'WELL', 'AVB', 'EQR',
]


class ValueScreener:
    """Screens for undervalued stocks meeting value criteria."""

    def __init__(self):
        self.config = get_config()
        self.screener_config = self.config.screener
        self.trading_config = self.config.trading

    def get_stock_data(self, symbol: str) -> Optional[Dict]:
        """
        Fetch comprehensive stock data for screening.

        Returns:
            Dict with price data, fundamentals, and technicals
        """
        try:
            ticker = yf.Ticker(symbol)

            # Get historical data (1 year for technical analysis)
            hist = ticker.history(period="1y")
            if hist.empty or len(hist) < 50:
                return None

            # Get info (fundamentals)
            info = ticker.info

            # Check minimum price
            current_price = hist['Close'].iloc[-1]
            if current_price < self.trading_config.min_stock_price:
                return None

            # Check minimum market cap
            market_cap = info.get('marketCap', 0)
            min_market_cap = self.trading_config.min_market_cap_millions * 1_000_000
            if market_cap < min_market_cap:
                return None

            # Get technical indicators
            technicals = get_technical_indicators(hist)

            return {
                'symbol': symbol,
                'name': info.get('shortName', symbol),
                'sector': info.get('sector', 'Unknown'),
                'industry': info.get('industry', 'Unknown'),
                'current_price': current_price,
                'market_cap': market_cap,
                'market_cap_str': self._format_market_cap(market_cap),

                # Fundamentals
                'pe_ratio': info.get('trailingPE'),
                'forward_pe': info.get('forwardPE'),
                'peg_ratio': info.get('pegRatio'),
                'price_to_book': info.get('priceToBook'),
                'revenue_growth': info.get('revenueGrowth'),
                'earnings_growth': info.get('earningsGrowth'),
                'profit_margin': info.get('profitMargins'),
                'dividend_yield': info.get('dividendYield'),

                # Technicals
                **technicals,

                # Volume
                'avg_volume': info.get('averageVolume', 0),
            }

        except Exception as e:
            signal_log.warning(f"Failed to get data for {symbol}: {e}")
            return None

    def _format_market_cap(self, market_cap: float) -> str:
        """Format market cap for display."""
        if market_cap >= 1_000_000_000_000:
            return f"${market_cap / 1_000_000_000_000:.1f}T"
        elif market_cap >= 1_000_000_000:
            return f"${market_cap / 1_000_000_000:.1f}B"
        elif market_cap >= 1_000_000:
            return f"${market_cap / 1_000_000:.1f}M"
        return f"${market_cap:,.0f}"

    def passes_value_criteria(self, stock: Dict) -> tuple[bool, List[str]]:
        """
        Check if stock meets value investing criteria.

        Returns:
            (passes: bool, reasons: list of why it passed/failed)
        """
        reasons = []
        passes = True

        pe = stock.get('pe_ratio')
        near_low_pct = stock.get('distance_from_low_pct', 100)
        rsi = stock.get('rsi_14', 50)
        volume_surge = stock.get('volume_surge_pct', 100)
        avg_volume = stock.get('avg_volume', 0)

        # Check P/E ratio
        if pe is not None:
            if pe > 0 and pe <= self.screener_config.max_pe_ratio:
                reasons.append(f"P/E={pe:.1f} (below {self.screener_config.max_pe_ratio})")
            elif pe > self.screener_config.max_pe_ratio:
                passes = False
                reasons.append(f"P/E={pe:.1f} too high")
            # Negative P/E (unprofitable) - could be a turnaround opportunity
            elif pe < 0:
                reasons.append(f"Negative P/E (unprofitable)")

        # Check 52-week low proximity
        if is_near_52week_low(near_low_pct, self.screener_config.near_52week_low_pct):
            reasons.append(f"Near 52-wk low ({near_low_pct:.1f}% above)")
        else:
            passes = False
            reasons.append(f"{near_low_pct:.1f}% above 52-wk low (need ≤{self.screener_config.near_52week_low_pct}%)")

        # Check RSI (oversold)
        if is_oversold(rsi, self.screener_config.rsi_oversold):
            reasons.append(f"RSI={rsi:.1f} (oversold)")
        else:
            reasons.append(f"RSI={rsi:.1f}")

        # Check volume surge (institutional interest)
        if has_volume_surge(volume_surge, self.screener_config.volume_surge_pct):
            reasons.append(f"Volume surge {volume_surge:.0f}%")

        # Check minimum average volume
        if avg_volume < self.screener_config.min_avg_volume:
            passes = False
            reasons.append(f"Low volume ({avg_volume:,})")

        # Check sector exclusions
        sector = stock.get('sector', '')
        if sector in self.screener_config.exclude_sectors:
            passes = False
            reasons.append(f"Excluded sector: {sector}")

        return passes, reasons

    def calculate_opportunity_score(self, stock: Dict) -> float:
        """
        Calculate an opportunity score (0-100) for ranking stocks.

        Higher score = Better opportunity
        """
        score = 50.0  # Start neutral

        # Near 52-week low (max +20 points)
        near_low_pct = stock.get('distance_from_low_pct', 100)
        if near_low_pct <= 5:
            score += 20
        elif near_low_pct <= 10:
            score += 15
        elif near_low_pct <= 15:
            score += 10

        # RSI oversold (max +15 points)
        rsi = stock.get('rsi_14', 50)
        if rsi < 30:
            score += 15
        elif rsi < 35:
            score += 10
        elif rsi < 40:
            score += 5

        # Low P/E (max +15 points)
        pe = stock.get('pe_ratio')
        if pe is not None and pe > 0:
            if pe < 10:
                score += 15
            elif pe < 15:
                score += 10
            elif pe < 20:
                score += 5

        # Volume surge (max +10 points)
        volume_surge = stock.get('volume_surge_pct', 100)
        if volume_surge >= 200:
            score += 10
        elif volume_surge >= 150:
            score += 5

        # Revenue growth (max +10 points)
        rev_growth = stock.get('revenue_growth')
        if rev_growth is not None and rev_growth > 0:
            if rev_growth >= 0.20:  # 20%+
                score += 10
            elif rev_growth >= 0.10:  # 10%+
                score += 5

        # Positive momentum recovery (max +5 points)
        momentum_5d = stock.get('momentum_5d', 0)
        if 0 < momentum_5d <= 5:  # Slight upward movement (not too fast)
            score += 5

        return min(100, max(0, score))

    def screen_stocks(self, symbols: List[str] = None, max_workers: int = 10) -> List[Dict]:
        """
        Screen multiple stocks and return those meeting criteria.

        Args:
            symbols: List of symbols to screen (default: STOCK_UNIVERSE)
            max_workers: Number of parallel threads

        Returns:
            List of qualifying stocks sorted by opportunity score
        """
        if symbols is None:
            symbols = STOCK_UNIVERSE

        signal_log.info(f"Screening {len(symbols)} stocks...")
        qualifying_stocks = []

        # Parallel fetching for speed
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_symbol = {
                executor.submit(self.get_stock_data, symbol): symbol
                for symbol in symbols
            }

            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    stock = future.result()
                    if stock is None:
                        continue

                    passes, reasons = self.passes_value_criteria(stock)
                    if passes:
                        stock['score'] = self.calculate_opportunity_score(stock)
                        stock['reasons'] = reasons
                        qualifying_stocks.append(stock)
                        signal_log.info(f"[MATCH] {symbol}: {', '.join(reasons)}")

                except Exception as e:
                    signal_log.warning(f"Error screening {symbol}: {e}")

        # Sort by opportunity score (highest first)
        qualifying_stocks.sort(key=lambda x: x['score'], reverse=True)

        signal_log.info(f"Found {len(qualifying_stocks)} qualifying stocks")
        return qualifying_stocks

    def get_top_opportunities(self, limit: int = 5) -> List[Dict]:
        """Get top N opportunities from the screen."""
        all_opportunities = self.screen_stocks()
        return all_opportunities[:limit]


def run_screener() -> List[Dict]:
    """Convenience function to run the screener."""
    screener = ValueScreener()
    return screener.get_top_opportunities()


if __name__ == "__main__":
    # Test run
    opportunities = run_screener()
    print(f"\nTop {len(opportunities)} Opportunities:")
    print("-" * 60)
    for i, stock in enumerate(opportunities, 1):
        print(f"{i}. {stock['symbol']} ({stock['name']})")
        print(f"   Price: ${stock['current_price']:.2f} | Score: {stock['score']:.0f}")
        print(f"   {', '.join(stock['reasons'])}")
        print()
