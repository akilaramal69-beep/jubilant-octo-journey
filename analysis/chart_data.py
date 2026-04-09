"""
Chart Data Storage - Save OHLCV history for charts and analysis.
"""

import logging
import json
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

CHART_DATA_DIR = "/tmp/data/charts"


def ensure_chart_dir():
    """Ensure chart data directory exists."""
    os.makedirs(CHART_DATA_DIR, exist_ok=True)


def get_chart_file(symbol: str) -> str:
    """Get chart data file path for symbol."""
    safe_symbol = symbol.replace("/", "_")
    return os.path.join(CHART_DATA_DIR, f"{safe_symbol}.json")


def save_ohlcv_data(symbol: str, ohlcv_data: list) -> None:
    """
    Save OHLCV data to file for charting.
    
    Args:
        symbol: Trading pair (e.g., "BTC/USDT")
        ohlcv_data: List of [timestamp, open, high, low, close, volume]
    """
    ensure_chart_dir()
    
    filepath = get_chart_file(symbol)
    
    # Convert to chart-friendly format
    candles = []
    for item in ohlcv_data:
        candles.append({
            "time": item[0] // 1000,  # Convert to seconds
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5])
        })
    
    try:
        with open(filepath, "w") as f:
            json.dump({
                "symbol": symbol,
                "updated": datetime.now().isoformat(),
                "candles": candles
            }, f)
        logger.debug(f"Saved {len(candles)} candles for {symbol}")
    except Exception as e:
        logger.error(f"Failed to save chart data for {symbol}: {e}")


def load_ohlcv_data(symbol: str) -> list:
    """
    Load OHLCV data from file.
    
    Args:
        symbol: Trading pair
        
    Returns:
        List of candle dictionaries
    """
    filepath = get_chart_file(symbol)
    
    if not os.path.exists(filepath):
        return []
    
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        return data.get("candles", [])
    except Exception as e:
        logger.error(f"Failed to load chart data for {symbol}: {e}")
        return []


def get_latest_candle(symbol: str) -> Optional[dict]:
    """Get the most recent candle for a symbol."""
    candles = load_ohlcv_data(symbol)
    return candles[-1] if candles else None


def calculate_timeframe_candles(candles: list, interval: str) -> list:
    """
    Aggregate candles to a different timeframe.
    
    Args:
        candles: List of 1h candles
        interval: Target interval (4h, 1d, 1w)
        
    Returns:
        Aggregated candles
    """
    if not candles:
        return []
    
    # Determine interval in seconds
    intervals = {
        "4h": 14400,
        "1d": 86400,
        "1w": 604800
    }
    
    interval_seconds = intervals.get(interval, 3600)
    
    aggregated = []
    current_candle = None
    
    for candle in candles:
        candle_time = candle["time"]
        bucket_time = (candle_time // interval_seconds) * interval_seconds
        
        if current_candle is None or current_candle["time"] != bucket_time:
            current_candle = {
                "time": bucket_time,
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"]
            }
            aggregated.append(current_candle)
        else:
            # Aggregate
            current_candle["high"] = max(current_candle["high"], candle["high"])
            current_candle["low"] = min(current_candle["low"], candle["low"])
            current_candle["close"] = candle["close"]
            current_candle["volume"] += candle["volume"]
    
    return aggregated