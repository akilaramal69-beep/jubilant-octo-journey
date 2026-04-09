"""
AI Pattern Analysis - Analyzes chart patterns using Groq and mathematical predictions.
"""

import logging
import json
import os
from datetime import datetime
from typing import Optional, Dict, List

import groq
import numpy as np

from core.config import settings

logger = logging.getLogger(__name__)

# Pattern descriptions for AI
PATTERN_TYPES = [
    "Double Top", "Double Bottom", "Head and Shoulders", "Inverse Head and Shoulders",
    "Ascending Triangle", "Descending Triangle", "Symmetrical Triangle",
    "Rising Wedge", "Falling Wedge", "Bull Flag", "Bear Flag",
    "Cup and Handle", "Inverse Cup and Handle", "Bullish Rectangle", "Bearish Rectangle"
]

# Chart pattern detection functions
def detect_patterns(candles: List[dict]) -> Dict[str, any]:
    """
    Detect chart patterns mathematically.
    
    Args:
        candles: List of OHLCV candles
        
    Returns:
        Dictionary of detected patterns
    """
    if len(candles) < 20:
        return {"patterns": [], "strength": 0}
    
    closes = np.array([c["close"] for c in candles])
    highs = np.array([c["high"] for c in candles])
    lows = np.array([c["low"] for c in candles])
    volumes = np.array([c["volume"] for c in candles])
    
    patterns = []
    strength = 0
    
    # 1. Trend detection
    ma20 = float(np.mean(closes[-20:])) if len(closes) >= 20 else float(closes[-1])
    ma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else float(closes[-1])
    
    trend = "bullish" if ma20 > ma50 else "bearish" if ma20 < ma50 else "neutral"
    
    # 2. Volatility
    volatility = float(np.std(closes[-20:]) / np.mean(closes[-20:]) * 100) if len(closes) >= 20 else 0
    
    # 3. Support/Resistance levels
    resistance_levels = find_resistance_levels(highs)
    support_levels = find_support_levels(lows)
    
    # 4. Double top/bottom detection
    double_top = detect_double_top(highs)
    if double_top["found"]:
        patterns.append({"name": "Double Top", "strength": double_top["strength"]})
        strength += double_top["strength"]
    
    double_bottom = detect_double_bottom(lows)
    if double_bottom["found"]:
        patterns.append({"name": "Double Bottom", "strength": double_bottom["strength"]})
        strength += double_bottom["strength"]
    
    # 5. Triangle detection
    triangle = detect_triangle(closes, highs, lows)
    if triangle["found"]:
        patterns.append({"name": triangle["type"], "strength": triangle["strength"]})
        strength += triangle["strength"]
    
    # 6. Wedge detection
    wedge = detect_wedge(highs, lows)
    if wedge["found"]:
        patterns.append({"name": wedge["type"], "strength": wedge["strength"]})
        strength += wedge["strength"]
    
    # 7. Volume analysis
    avg_volume = float(np.mean(volumes[-20:]))
    recent_volume = float(np.mean(volumes[-5:]))
    volume_spike = recent_volume > avg_volume * 1.5
    
    return {
        "trend": trend,
        "volatility": float(round(volatility, 2)),
        "patterns": patterns,
        "strength": min(int(strength), 100),
        "support_levels": support_levels[:3],
        "resistance_levels": resistance_levels[:3],
        "volume_spike": bool(volume_spike),
        "ma20": float(round(ma20, 2)),
        "ma50": float(round(ma50, 2))
    }


def find_resistance_levels(highs: np.ndarray, lookback: int = 20) -> List[float]:
    """Find resistance levels from recent highs."""
    if len(highs) < lookback:
        return []
    
    local_maxima = []
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            local_maxima.append(float(highs[i]))
    
    # Cluster similar levels
    levels = []
    for m in local_maxima[-5:]:
        if not levels or all(abs(m - l) / l > 0.02 for l in levels):
            levels.append(round(m, 2))
    
    return sorted(levels, reverse=True)[:3]


def find_support_levels(lows: np.ndarray, lookback: int = 20) -> List[float]:
    """Find support levels from recent lows."""
    if len(lows) < lookback:
        return []
    
    local_minima = []
    for i in range(1, len(lows) - 1):
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            local_minima.append(float(lows[i]))
    
    levels = []
    for m in local_minima[-5:]:
        if not levels or all(abs(m - l) / l > 0.02 for l in levels):
            levels.append(round(m, 2))
    
    return sorted(levels)[:3]


def detect_double_top(highs: np.ndarray) -> Dict:
    """Detect double top pattern."""
    if len(highs) < 40:
        return {"found": False, "strength": 0}
    
    peaks = []
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            peaks.append((i, float(highs[i])))
    
    if len(peaks) >= 2:
        for i in range(len(peaks) - 1):
            p1, v1 = peaks[i]
            p2, v2 = peaks[i + 1]
            # Peaks should be within 10 candles and 5% of each other
            if p2 - p1 < 20 and abs(v1 - v2) / v1 < 0.05:
                return {"found": True, "strength": 70}
    
    return {"found": False, "strength": 0}


def detect_double_bottom(lows: np.ndarray) -> Dict:
    """Detect double bottom pattern."""
    if len(lows) < 40:
        return {"found": False, "strength": 0}
    
    troughs = []
    for i in range(1, len(lows) - 1):
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            troughs.append((i, float(lows[i])))
    
    if len(troughs) >= 2:
        for i in range(len(troughs) - 1):
            t1, v1 = troughs[i]
            t2, v2 = troughs[i + 1]
            if t2 - t1 < 20 and abs(v1 - v2) / v1 < 0.05:
                return {"found": True, "strength": 70}
    
    return {"found": False, "strength": 0}


def detect_triangle(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> Dict:
    """Detect triangle patterns."""
    if len(closes) < 30:
        return {"found": False, "type": "", "strength": 0}
    
    # Check if highs are decreasing and lows are increasing (symmetrical)
    recent_highs = highs[-15:]
    recent_lows = lows[-15:]
    
    high_slope = float((recent_highs[-1] - recent_highs[0]) / len(recent_highs))
    low_slope = float((recent_lows[-1] - recent_lows[0]) / len(recent_lows))
    
    if high_slope < 0 and low_slope > 0:
        return {"found": True, "type": "Symmetrical Triangle", "strength": 60}
    elif high_slope < 0 and abs(low_slope) < 0.001:
        return {"found": True, "type": "Descending Triangle", "strength": 55}
    elif abs(high_slope) < 0.001 and low_slope > 0:
        return {"found": True, "type": "Ascending Triangle", "strength": 55}
    
    return {"found": False, "type": "", "strength": 0}


def detect_wedge(highs: np.ndarray, lows: np.ndarray) -> Dict:
    """Detect wedge patterns."""
    if len(highs) < 30:
        return {"found": False, "type": "", "strength": 0}
    
    recent_highs = highs[-20:]
    recent_lows = lows[-20:]
    
    high_slope = float((recent_highs[-1] - recent_highs[0]) / len(recent_highs))
    low_slope = float((recent_lows[-1] - recent_lows[0]) / len(recent_lows))
    
    # Both moving in same direction but converging
    if high_slope > 0 and low_slope > 0 and high_slope > low_slope:
        return {"found": True, "type": "Falling Wedge (Bullish)", "strength": 65}
    elif high_slope < 0 and low_slope < 0 and high_slope < low_slope:
        return {"found": True, "type": "Rising Wedge (Bearish)", "strength": 65}
    
    return {"found": False, "type": "", "strength": 0}


def calculate_predictions(candles: List[dict]) -> Dict:
    """
    Calculate mathematical price predictions.
    
    Args:
        candles: List of OHLCV candles
        
    Returns:
        Prediction data
    """
    if len(candles) < 20:
        return {}
    
    closes = np.array([c["close"] for c in candles])
    highs = np.array([c["high"] for c in candles])
    lows = np.array([c["low"] for c in candles])
    
    # Linear regression for trend
    x = np.arange(len(closes))
    slope, intercept = np.polyfit(x, closes, 1)
    slope = float(slope)
    intercept = float(intercept)
    
    # Calculate next 3 periods
    future_x = np.array([len(closes), len(closes) + 1, len(closes) + 2])
    future_prices = slope * future_x + intercept
    
    # Volatility-based prediction bands
    std = float(np.std(closes[-20:]))
    
    # Fibonacci extension prediction
    high = float(np.max(highs[-20:]))
    low = float(np.min(lows[-20:]))
    diff = high - low
    
    fib_1618 = high + 0.618 * diff
    fib_2618 = high + 1.618 * diff
    
    # Calculate ATR safely
    atr_value = 0.0
    if len(candles) >= 14:
        atr_value = float(np.mean(highs[-14:] - lows[-14:]))
    
    return {
        "trend_slope": float(round(slope, 4)),
        "trend_direction": "bullish" if slope > 0 else "bearish",
        "predicted_prices": [
            float(round(future_prices[0], 2)),
            float(round(future_prices[1], 2)),
            float(round(future_prices[2], 2))
        ],
        "volatility_std": float(round(std, 2)),
        "upper_band": float(round(closes[-1] + 2 * std, 2)),
        "lower_band": float(round(closes[-1] - 2 * std, 2)),
        "fib_1618": float(round(fib_1618, 2)),
        "fib_2618": float(round(fib_2618, 2)),
        "atr": atr_value
    }


async def analyze_with_ai(symbol: str, candles: List[dict], patterns: Dict, predictions: Dict) -> Dict:
    """
    Use Groq to analyze patterns and provide AI insights.
    
    Args:
        symbol: Trading pair
        candles: OHLCV data
        patterns: Detected patterns
        predictions: Mathematical predictions
        
    Returns:
        AI analysis results
    """
    if not candles or len(candles) < 20:
        return {"error": "Insufficient data for AI analysis"}
    
    # Prepare data summary for AI
    recent = candles[-20:]
    price_start = recent[0]["close"]
    price_end = recent[-1]["close"]
    change = ((price_end - price_start) / price_start * 100)
    
    summary = f"""
Analyze {symbol} chart data:

PRICE DATA:
- Current Price: ${price_end:.2f}
- 20-period change: {change:.2f}%
- Trend: {patterns.get('trend', 'unknown')}
- Volatility: {patterns.get('volatility', 0):.2f}%

PATTERNS DETECTED:
{chr(10).join([f"- {p['name']} ({p['strength']}%)" for p in patterns.get('patterns', [])]) or "None"}

SUPPORT/RESISTANCE:
- Support: {patterns.get('support_levels', [])}
- Resistance: {patterns.get('resistance_levels', [])}

MATHEMATICAL PREDICTIONS:
- Next 3 candles: {predictions.get('predicted_prices', [])}
- Upper band (2σ): ${predictions.get('upper_band', 0)}
- Lower band (2σ): ${predictions.get('lower_band', 0)}
- ATR: ${predictions.get('atr', 0)}

Provide:
1. Overall market analysis (bullish/bearish/neutral)
2. Key levels to watch
3. Entry/exit recommendations
4. Risk assessment (low/medium/high)

Respond in JSON format with keys: analysis, key_levels, recommendation, risk_level
"""
    
    try:
        client = groq.AsyncGroq(api_key=settings.GROQ_API_KEY, timeout=settings.GROQ_TIMEOUT_SECONDS)
        
        chat = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a professional crypto trading analyst. Analyze chart data and provide actionable insights. Respond ONLY in JSON."},
                {"role": "user", "content": summary}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        response = chat.choices[0].message.content
        
        # Try to parse JSON
        import re
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            ai_analysis = json.loads(json_match.group())
            logger.info(f"AI analysis for {symbol}: {ai_analysis.get('analysis', 'N/A')[:50]}")
            return ai_analysis
        else:
            return {"analysis": response, "raw": True}
            
    except Exception as e:
        logger.error(f"AI analysis failed for {symbol}: {e}")
        return {"error": str(e)}


async def full_analysis(symbol: str, candles: List[dict]) -> Dict:
    """
    Perform full pattern and AI analysis on a symbol.
    
    Args:
        symbol: Trading pair
        candles: OHLCV data
        
    Returns:
        Complete analysis
    """
    # 1. Detect patterns
    patterns = detect_patterns(candles)
    
    # 2. Calculate predictions
    predictions = calculate_predictions(candles)
    
    # 3. AI analysis
    ai = await analyze_with_ai(symbol, candles, patterns, predictions)
    
    return {
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "patterns": patterns,
        "predictions": predictions,
        "ai_analysis": ai
    }


def save_analysis(symbol: str, analysis: Dict) -> None:
    """Save analysis to file."""
    os.makedirs("/tmp/data/analysis", exist_ok=True)
    filepath = f"/tmp/data/analysis/{symbol.replace('/', '_')}.json"
    
    try:
        with open(filepath, "w") as f:
            json.dump(analysis, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save analysis: {e}")