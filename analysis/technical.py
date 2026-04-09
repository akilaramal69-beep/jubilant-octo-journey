"""
Technical Analysis Module for Crypto Sniper Bot.
Implements Fibonacci, RSI, EMA, ATR, Volume Spike, BOS, Elliott Wave, and Market Regime detection.
"""

import logging
from typing import Optional
import pandas as pd
import numpy as np
from scipy.signal import argrelextrema
import time

logger = logging.getLogger(__name__)

# Module-level indicator cache with TTL
_indicator_cache: dict = {}


def _get_cached(key: str) -> tuple[Optional[any], bool]:
    """Check if cache key exists and is not expired."""
    if key in _indicator_cache:
        value, timestamp = _indicator_cache[key]
        if time.time() - timestamp < 30:
            return value, True
    return None, False


def _set_cache(key: str, value: any) -> None:
    """Set cache key with current timestamp."""
    _indicator_cache[key] = (value, time.time())


class TechnicalAnalysis:
    """Technical analysis methods for cryptocurrency trading."""

    @staticmethod
    def calculate_fibonacci_levels(high: float, low: float) -> dict:
        """
        Calculate Fibonacci retracement levels.
        
        Args:
            high: High price of the range
            low: Low price of the range
            
        Returns:
            Dictionary with Fibonacci levels or empty dict on invalid input
        """
        if high <= low or high <= 0 or low <= 0:
            return {}
        
        diff = high - low
        return {
            "level_0": low,
            "level_236": low + 0.236 * diff,
            "level_382": low + 0.382 * diff,
            "level_500": low + 0.500 * diff,
            "level_618": low + 0.618 * diff,
            "level_786": low + 0.786 * diff,
            "level_100": high
        }

    @staticmethod
    def calculate_fibonacci_extensions(high: float, low: float) -> dict:
        """
        Calculate Fibonacci extension levels beyond the high.
        
        Args:
            high: High price of the range
            low: Low price of the range
            
        Returns:
            Dictionary with extension levels or empty dict on invalid input
        """
        if high <= low or high <= 0 or low <= 0:
            return {}
        
        diff = high - low
        return {
            "level_1272": high + 0.272 * diff,
            "level_1618": high + 0.618 * diff
        }

    @staticmethod
    def calculate_fibonacci_bearish(high: float, low: float) -> dict:
        """
        Calculate Fibonacci levels for bearish market (resistance zones ascending from low).
        
        Args:
            high: High price of the range
            low: Low price of the range
            
        Returns:
            Dictionary with bearish Fibonacci levels
        """
        if high <= low or high <= 0 or low <= 0:
            return {}
        
        diff = high - low
        return {
            "level_0": low,
            "level_236": low + 0.236 * diff,
            "level_382": low + 0.382 * diff,
            "level_500": low + 0.500 * diff,
            "level_618": low + 0.618 * diff,
            "level_786": low + 0.786 * diff,
            "level_100": high
        }

    @staticmethod
    def is_price_at_fib_level(price: float, levels: dict, tolerance: float) -> Optional[str]:
        """
        Check if price is at a Fibonacci level within tolerance.
        
        Args:
            price: Current price
            levels: Dictionary of Fibonacci levels
            tolerance: Tolerance percentage for matching
            
        Returns:
            Level name if matched, None otherwise
        """
        if not levels:
            return None
        
        for level_name, level_value in levels.items():
            if level_value > 0:
                diff_pct = abs(price - level_value) / level_value
                if diff_pct <= tolerance:
                    return level_name
        return None

    @staticmethod
    def calculate_rsi(prices: list, period: int = 14) -> float:
        """
        Calculate RSI using Wilder's smoothing method.
        
        Args:
            prices: List of closing prices
            period: RSI period (default 14)
            
        Returns:
            RSI value (0-100), defaults to 50.0 on failure
        """
        try:
            if not prices:
                return 50.0
            
            series = pd.Series(prices)
            delta = series.diff()
            
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            
            avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            result = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0
            return float(result)
        except Exception as e:
            logger.warning(f"RSI calculation failed: {e}")
            return 50.0

    @staticmethod
    def calculate_ema(prices: list, period: int = 20) -> float:
        """
        Calculate Exponential Moving Average.
        
        Args:
            prices: List of price values
            period: EMA period
            
        Returns:
            EMA value, returns 0.0 if insufficient data
        """
        try:
            if len(prices) < period:
                return 0.0
            
            series = pd.Series(prices)
            ema = series.ewm(span=period, adjust=False).mean()
            result = ema.iloc[-1]
            
            return float(result) if not pd.isna(result) else 0.0
        except Exception as e:
            logger.warning(f"EMA calculation failed: {e}")
            return 0.0

    @staticmethod
    def calculate_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
        """
        Calculate Average True Range.
        
        Args:
            highs: List of high prices
            lows: List of low prices
            closes: List of close prices
            period: ATR period
            
        Returns:
            ATR value, returns 0.0 on failure
        """
        try:
            if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
                return 0.0
            
            high_series = pd.Series(highs)
            low_series = pd.Series(lows)
            close_series = pd.Series(closes)
            
            prev_close = close_series.shift(1)
            
            tr = pd.concat([
                high_series - low_series,
                (high_series - prev_close).abs(),
                (low_series - prev_close).abs()
            ], axis=1).max(axis=1)
            
            atr = tr.rolling(window=period).mean()
            result = atr.iloc[-1]
            
            return float(result) if not pd.isna(result) else 0.0
        except Exception as e:
            logger.warning(f"ATR calculation failed: {e}")
            return 0.0

    @staticmethod
    def is_volume_spike(volumes: list, period: int = 20, multiplier: float = 1.5) -> bool:
        """
        Detect if current volume is a spike compared to recent average.
        
        Args:
            volumes: List of volume values
            period: Lookback period for baseline
            multiplier: Minimum multiplier for spike detection
            
        Returns:
            True if volume spike detected, False otherwise
        """
        try:
            if len(volumes) < period + 1:
                return False
            
            # Exclude current candle from baseline
            baseline = volumes[-period:-1]
            if len(baseline) < period:
                return False
            
            sma = sum(baseline) / len(baseline)
            
            if sma <= 0:
                return False
            
            current_volume = volumes[-1]
            return current_volume >= sma * multiplier
        except Exception as e:
            logger.warning(f"Volume spike detection failed: {e}")
            return False

    @staticmethod
    def detect_bos(highs: list, lows: list, price: float) -> bool:
        """
        Detect Break of Structure (BOS) - bullish bias.
        
        Args:
            highs: List of high prices
            lows: List of low prices
            price: Current price
            
        Returns:
            True if bullish BOS detected, False otherwise
        """
        try:
            if len(highs) < 10:
                return False
            
            # Bullish BOS: price breaks above highest high of previous 9 candles
            recent_highs = highs[-10:-1]
            structure_high = max(recent_highs)
            
            return price > structure_high
        except Exception as e:
            logger.warning(f"BOS detection failed: {e}")
            return False

    @staticmethod
    def identify_elliott_wave(closes: list, order: int = 3) -> str:
        """
        Identify Elliott Wave pattern in price data.
        
        Args:
            closes: List of closing prices
            order: Order for peak detection
            
        Returns:
            Wave pattern string or "None"
        """
        try:
            if len(closes) < 30:
                return "None"
            
            # Cache check
            cache_key = f"elliott_{len(closes)}_{closes[-1]:.2f}"
            cached_result, found = _get_cached(cache_key)
            if found:
                return cached_result
            
            # Smooth the data
            series = pd.Series(closes)
            smoothed = series.rolling(3).mean().dropna()
            
            if len(smoothed) < 20:
                result = "None"
                _set_cache(cache_key, result)
                return result
            
            # Find peaks and troughs
            peaks_idx = argrelextrema(smoothed.values, np.greater, order=order)[0]
            troughs_idx = argrelextrema(smoothed.values, np.less, order=order)[0]
            
            # Merge and sort extrema
            all_extrema = sorted(list(peaks_idx) + list(troughs_idx))
            
            if len(all_extrema) < 5:
                result = "None"
                _set_cache(cache_key, result)
                return result
            
            # Validate strict alternation
            prev_type = None
            filtered_extrema = []
            for idx in all_extrema:
                current_type = "peak" if idx in peaks_idx else "trough"
                if prev_type is not None and current_type == prev_type:
                    continue
                filtered_extrema.append(idx)
                prev_type = current_type
            
            if len(filtered_extrema) < 5:
                result = "None"
                _set_cache(cache_key, result)
                return result
            
            # Take last 6 points
            points = filtered_extrema[-6:]
            
            if len(points) < 5:
                result = "None"
                _set_cache(cache_key, result)
                return result
            
            # Get price values for the 5-wave check
            w0_idx = points[0]
            w1_idx = points[1]
            w2_idx = points[2]
            w3_idx = points[3]
            w4_idx = points[4]
            
            w0_price = smoothed.iloc[w0_idx]
            w1_high = smoothed.iloc[w1_idx]
            w2_low = smoothed.iloc[w2_idx]
            w3_high = smoothed.iloc[w3_idx]
            w4_low = smoothed.iloc[w4_idx]
            
            # W2 cannot breach start
            if w2_low < w0_price:
                result = "None"
                _set_cache(cache_key, result)
                return result
            
            # W3 must exceed W1
            if w3_high <= w1_high:
                result = "None"
                _set_cache(cache_key, result)
                return result
            
            # W4 cannot overlap W1
            if w4_low <= w1_high:
                result = "None"
                _set_cache(cache_key, result)
                return result
            
            # Wave 3 is never the shortest - critical rule
            w1 = w1_high - w0_price
            w3 = w3_high - w2_low
            w5_est = closes[-1] - w4_low
            
            # Reject only if W3 is shorter than BOTH W1 and estimated W5
            if w3 < w1 and w3 < w5_est:
                result = "None"
                _set_cache(cache_key, result)
                return result
            
            # Determine wave phase
            current_price = closes[-1]
            
            if current_price > w3_high:
                result = "Wave 5 Breakout"
            elif w4_low < current_price <= w3_high:
                result = "Wave 5 Ignition"
            else:
                result = "Wave 4 Retracement"
            
            _set_cache(cache_key, result)
            return result
            
        except Exception as e:
            logger.warning(f"Elliott Wave identification failed: {e}")
            return "None"

    @staticmethod
    def is_market_uptrend(closes: list, period: int = 200) -> bool:
        """
        Determine if market is in an uptrend using EMA 200.
        
        Args:
            closes: List of closing prices
            period: EMA period for trend determination
            
        Returns:
            True if in uptrend, False otherwise
        """
        try:
            if len(closes) < period:
                logger.warning(f"Insufficient data for EMA {period}, defaulting to True")
                return True
            
            ema = TechnicalAnalysis.calculate_ema(closes, period)
            return closes[-1] > ema
        except Exception as e:
            logger.warning(f"Market trend check failed: {e}")
            return True

    @staticmethod
    def check_candle_quality(ohlcv: dict, highs: list, atr: float) -> bool:
        """
        Check candle quality for fakeout filter - all 5 conditions must pass.
        
        Args:
            ohlcv: Dictionary with open, high, low, close, volume
            highs: List of recent high prices
            atr: Current ATR value
            
        Returns:
            True if candle passes all quality checks
        """
        try:
            open_price = ohlcv.get("open", 0)
            close_price = ohlcv.get("close", 0)
            high_price = ohlcv.get("high", 0)
            low_price = ohlcv.get("low", 0)
            
            if open_price <= 0 or close_price <= 0:
                return False
            
            # Condition 1: Body ratio >= 0.6
            candle_range = high_price - low_price
            if candle_range <= 0:
                return False
            
            body = abs(close_price - open_price)
            body_ratio = body / candle_range
            
            if body_ratio < 0.6:
                return False
            
            # Condition 2: Close in top 80% of candle range
            distance_from_top = high_price - close_price
            position_in_range = 1 - (distance_from_top / candle_range)
            
            if position_in_range < 0.80:
                return False
            
            # Condition 3: Candle size > 1.5 × ATR
            if candle_range <= 1.5 * atr:
                return False
            
            # Condition 4: Close above recent range high
            if len(highs) < 6:
                return False
            
            recent_high = max(highs[-6:-1])
            if close_price <= recent_high:
                return False
            
            # Condition 5: FOMO filter - distance from range high <= 0.5 × ATR
            distance_from_high = high_price - close_price
            if distance_from_high > 0.5 * atr:
                return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Candle quality check failed: {e}")
            return False