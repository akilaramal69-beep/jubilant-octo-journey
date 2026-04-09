"""
Analysis Engine - Orchestrates technical analysis, scoring, and trading decisions.
"""

import logging
import asyncio
import json
import os
import time
from typing import Optional
from datetime import datetime

from core.config import settings
from analysis.technical import TechnicalAnalysis
from analysis.sentiment import SentimentAnalysis
from execution.executor import TradingExecutor

logger = logging.getLogger(__name__)

# Module-level lock for file operations
_file_lock = asyncio.Lock()

# Global executor instance (initialized in main.py)
_executor: Optional[TradingExecutor] = None


def set_executor(exec_instance: TradingExecutor) -> None:
    """Set the global executor instance."""
    global _executor
    _executor = exec_instance


def _load_json_safe(filepath: str) -> dict:
    """Load JSON file safely, return empty dict on failure."""
    try:
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load {filepath}: {e}")
    return {}


def _atomic_write_json(filepath: str, data: dict) -> None:
    """Write JSON atomically using temp file + rename."""
    temp_path = filepath + ".tmp"
    try:
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, filepath)
    except Exception as e:
        logger.error(f"Failed to write {filepath}: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass


def _calculate_score(
    price: float,
    ema_20: float,
    fib_level_hit: Optional[str],
    sentiment_score: float,
    prev_sentiment: float,
    volume_spike: bool,
    bos: bool,
    elliott_phase: str
) -> int:
    """
    Calculate institutional scoring (0-10) based on multiple factors.
    
    Args:
        price: Current price
        ema_20: 20-period EMA
        fib_level_hit: Fibonacci level hit (if any)
        sentiment_score: Current sentiment (0-1)
        prev_sentiment: Previous sentiment score
        volume_spike: Whether volume spike detected
        bos: Break of Structure detected
        elliott_phase: Elliott wave phase
        
    Returns:
        Score from 0 to 10
    """
    score = 0
    
    # TREND & STRUCTURE (max 3)
    if price > ema_20:
        score += 1
    if bos:
        score += 1
    if ema_20 > 0 and price / ema_20 >= 1 + settings.MOMENTUM_EMA_GAP:
        score += 1
    
    # ELLIOTT WAVE (max 2)
    if elliott_phase in ["Wave 5 Breakout", "Wave 5 Ignition"]:
        score += 2
    elif elliott_phase == "Wave 4 Retracement":
        score += 1
    
    # FIBONACCI + EMA CONFLUENCE (max 3)
    if fib_level_hit:
        score += 1
        if fib_level_hit in ["level_500", "level_618"]:
            score += 2
    elif ema_20 > 0 and abs(price - ema_20) / ema_20 < settings.FIB_TOLERANCE:
        score += 2
    
    # SENTIMENT (max 3)
    if sentiment_score >= 0.70:
        score += 1
    if sentiment_score >= 0.85:
        score += 1
    if sentiment_score - prev_sentiment >= 0.10:
        score += 1
    
    # VOLUME (max 1)
    if volume_spike:
        score += 1
    
    return min(score, 10)


async def analyze_symbol(symbol: str) -> None:
    """
    Perform full analysis on a symbol and decide on trade execution.
    
    Args:
        symbol: Trading pair to analyze (e.g., "BTC/USDT")
    """
    global _executor
    
    if _executor is None:
        logger.warning("Executor not initialized, skipping analysis")
        return
    
    try:
        # Step 0a: Check if symbol already in open positions
        positions = _load_json_safe("/tmp/data/positions.json")
        if symbol in positions:
            logger.debug(f"Symbol {symbol} already has open position, skipping")
            return
        
        # Step 0b: Check max concurrent positions
        if len(positions) >= settings.MAX_CONCURRENT_POSITIONS:
            logger.debug(f"Max positions reached ({len(positions)}), skipping scan")
            return
        
        # Step 0c: Check position cooldown
        cooldown_file = "/tmp/data/cooldown.json"
        cooldown_data = _load_json_safe(cooldown_file)
        if symbol in cooldown_data:
            last_trade_time = cooldown_data[symbol]
            if time.time() - last_trade_time < settings.POSITION_COOLDOWN_SECONDS:
                logger.debug(f"Symbol {symbol} in cooldown, skipping")
                return
        
        # Step 1: Fetch current price
        try:
            current_price = await _executor.get_latest_price(symbol)
            logger.debug(f"{symbol} price: {current_price}")
        except Exception as e:
            logger.error(f"Failed to fetch price for {symbol}: {e}")
            return
        
        # Step 2: Parallel fetch sentiment and OHLCV
        sentiment_task = SentimentAnalysis.get_news_sentiment(symbol)
        ohlcv_task = _executor.fetch_ohlcv(symbol, "1h", 200)
        
        sentiment_score, ohlcv_data = await asyncio.gather(sentiment_task, ohlcv_task)
        
        if not ohlcv_data or len(ohlcv_data) < 30:
            logger.warning(f"Insufficient OHLCV data for {symbol}")
            return
        
        # Extract OHLCV arrays
        ohlcv_df = ohlcv_data  # Already a list of [timestamp, open, high, low, close, volume]
        closes = [c[4] for c in ohlcv_df]
        highs = [c[2] for c in ohlcv_df]
        lows = [c[3] for c in ohlcv_df]
        volumes = [c[5] for c in ohlcv_df]
        
        current_ohlcv = ohlcv_df[-1]
        
        # Step 3: Market regime check
        ema_200 = TechnicalAnalysis.calculate_ema(closes, settings.MARKET_REGIME_EMA_PERIOD)
        price_change_24h = ((closes[-1] - closes[-24]) / closes[-24] * 100) if len(closes) >= 24 else 0
        
        if ema_200 > 0 and current_price < ema_200:
            logger.debug(f"{symbol} below EMA200, skipping")
            return
        
        if price_change_24h < -15:
            logger.debug(f"{symbol} 24h change {price_change_24h:.2f}% < -15%, skipping")
            return
        
        # Step 4: Calculate indicators
        recent_high = max(highs[-20:])
        recent_low = min(lows[-20:])
        
        fib_levels = TechnicalAnalysis.calculate_fibonacci_levels(recent_high, recent_low)
        fib_level_hit = TechnicalAnalysis.is_price_at_fib_level(current_price, fib_levels, settings.FIB_TOLERANCE)
        
        ema_20 = TechnicalAnalysis.calculate_ema(closes, 20)
        atr = TechnicalAnalysis.calculate_atr(highs, lows, closes, 14)
        volume_spike = TechnicalAnalysis.is_volume_spike(volumes, 20, 1.5)
        bos = TechnicalAnalysis.detect_bos(highs, lows, current_price)
        elliott_phase = TechnicalAnalysis.identify_elliott_wave(closes, 3)
        
        # Step 5: Load previous sentiment and score
        analysis_file = "/tmp/data/latest_analysis.json"
        prev_data = _load_json_safe(analysis_file)
        prev_sentiment = prev_data.get(symbol, {}).get("sentiment", 0.5)
        prev_score = prev_data.get(symbol, {}).get("score", 0)
        
        # Step 6: Calculate score
        score = _calculate_score(
            price=current_price,
            ema_20=ema_20,
            fib_level_hit=fib_level_hit,
            sentiment_score=sentiment_score,
            prev_sentiment=prev_sentiment,
            volume_spike=volume_spike,
            bos=bos,
            elliott_phase=elliott_phase
        )
        score_jump = score - prev_score
        
        # Step 7: Check for explosive move
        ohlcv_dict = {
            "open": current_ohlcv[1],
            "high": current_ohlcv[2],
            "low": current_ohlcv[3],
            "close": current_ohlcv[4],
            "volume": current_ohlcv[5]
        }
        explosive_move = TechnicalAnalysis.check_candle_quality(ohlcv_dict, highs, atr)
        
        # Step 8: Trade decision logic
        required_score = settings.REQUIRED_SCORE
        
        should_trade = (
            score >= required_score or
            (score >= 6 and score_jump >= 3 and explosive_move) or
            (score_jump >= 3 and volume_spike and explosive_move)
        )
        
        # Determine signal label
        if score >= 8:
            signal = "STRONG BUY"
        elif score >= 6:
            signal = "BUY"
        elif score >= 4:
            signal = "NEUTRAL"
        else:
            signal = "WAIT"
        
        # Step 9: Save analysis data (atomic write with lock)
        timestamp = datetime.now().isoformat()
        
        analysis_entry = {
            "symbol": symbol,
            "price": current_price,
            "score": score,
            "prev_score": prev_score,
            "score_jump": score_jump,
            "signal": signal,
            "elliott_phase": elliott_phase,
            "sentiment": sentiment_score,
            "prev_sentiment": prev_sentiment,
            "volume_spike": volume_spike,
            "bos": bos,
            "fib_level_hit": fib_level_hit,
            "atr": atr,
            "ema_20": ema_20,
            "ema_200": ema_200,
            "timestamp": timestamp
        }
        
        async with _file_lock:
            # Update latest analysis
            latest = _load_json_safe(analysis_file)
            latest[symbol] = analysis_entry
            latest["last_updated"] = timestamp
            _atomic_write_json(analysis_file, latest)
            
            # Update history (keep last 100)
            history_file = "/tmp/data/analysis_history.json"
            history = _load_json_safe(history_file)
            history[symbol] = history.get(symbol, [])
            history[symbol].append(analysis_entry)
            
            # Trim to last 100 per symbol
            if len(history[symbol]) > 100:
                history[symbol] = history[symbol][-100:]
            
            _atomic_write_json(history_file, history)
        
        logger.info(
            f"{symbol}: Score={score} (jump={score_jump}), Signal={signal}, "
            f"Elliot={elliott_phase}, Sentiment={sentiment_score:.2f}"
        )
        
        # Step 10: Execute trade if signals align
        if should_trade and _executor is not None:
            from execution.manager import RiskManager
            from services.telegram import TelegramService
            
            try:
                # Get balance
                balance = await _executor.get_balance("USDT")
                position_size = RiskManager.calculate_position_size(balance)
                
                # Calculate TP/SL
                if atr > 0:
                    tp_price = current_price + (settings.ATR_TP_MULTIPLIER * atr)
                    sl_price = current_price - (settings.ATR_SL_MULTIPLIER * atr)
                else:
                    # Fallback to percentage
                    tp_price = current_price * 1.03
                    sl_price = current_price * 0.98
                
                # Calculate quantity
                quantity = position_size / current_price
                
                # Execute trade
                order_result = await _executor.place_order(symbol, "buy", quantity)
                
                if order_result and order_result.get("id"):
                    # Save position
                    await RiskManager.save_position(
                        symbol=symbol,
                        entry_price=current_price,
                        quantity=quantity,
                        side="long",
                        tp_price=tp_price,
                        sl_price=sl_price
                    )
                    
                    # Send notification
                    await TelegramService.send_message(
                        f"🚀 <b>ENTRY EXECUTED</b>\n\n"
                        f"Symbol: <code>{symbol}</code>\n"
                        f"Entry: <code>${current_price:.4f}</code>\n"
                        f"Quantity: <code>{quantity:.6f}</code>\n"
                        f"TP: <code>${tp_price:.4f}</code>\n"
                        f"SL: <code>${sl_price:.4f}</code>\n"
                        f"Score: <code>{score}</code>\n"
                        f"Signal: <code>{signal}</code>"
                    )
                    
                    logger.info(f"Trade executed for {symbol} at {current_price}")
                    
            except Exception as e:
                logger.error(f"Failed to execute trade for {symbol}: {e}")
        
    except Exception as e:
        logger.error(f"Analysis failed for {symbol}: {e}")