"""
Backtesting Module - Validate scoring thresholds on historical data.
"""

import logging
import json
import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import ccxt

from core.config import settings
from analysis.technical import TechnicalAnalysis

logger = logging.getLogger(__name__)

# 0.1% fee per side (0.2% round trip)
FEE_PCT = 0.001


class Backtester:
    """Offline backtester for validating scoring thresholds."""

    def __init__(self, start_date: str, end_date: str, initial_balance: float = 10000):
        """
        Initialize backtester.
        
        Args:
            start_date: ISO date string (YYYY-MM-DD)
            end_date: ISO date string (YYYY-MM-DD)
            initial_balance: Starting balance in USDT
        """
        self.start_date = datetime.fromisoformat(start_date)
        self.end_date = datetime.fromisoformat(end_date)
        self.initial_balance = initial_balance
        self.balance = initial_balance
        
        # Initialize exchange
        self.exchange = ccxt.binance({
            "enableRateLimit": True,
            "defaultType": "spot"
        })
        if settings.USE_TESTNET:
            self.exchange.set_sandbox_mode(True)
        
        # Results storage
        self.trades = []
        self.equity_curve = []
        
        # Track open positions
        self._open_positions: set = set()

    def run_backtest(self, symbols: list[str], score_threshold: int = 7) -> dict:
        """
        Run backtest across symbols.
        
        Args:
            symbols: List of trading pairs
            score_threshold: Minimum score to enter trade
            
        Returns:
            Backtest results dictionary
        """
        logger.info(f"Starting backtest: {self.start_date} to {self.end_date}")
        logger.info(f"Symbols: {symbols}, Threshold: {score_threshold}")
        
        for symbol in symbols:
            try:
                self._backtest_symbol(symbol, score_threshold)
            except Exception as e:
                logger.error(f"Backtest failed for {symbol}: {e}")
        
        return self._calculate_results()
    
    def _fetch_ohlcv_paginated(self, symbol: str, since: int, until: int) -> list:
        """Fetch OHLCV with pagination for date ranges > ~83 days."""
        all_ohlcv = []
        current_since = since
        batch_limit = 1000  # Stay under 2000 limit
        
        while current_since < until:
            try:
                batch = self.exchange.fetch_ohlcv(
                    symbol, "1h", since=current_since, limit=batch_limit
                )
                
                if not batch:
                    break
                    
                all_ohlcv.extend(batch)
                
                # Check if we've reached the end of available data
                if len(batch) < batch_limit:
                    break
                
                # Move to next batch - use timestamp of last candle + 1 hour
                current_since = batch[-1][0] + 3600000
                
            except Exception as e:
                logger.warning(f"Pagination error for {symbol}: {e}")
                break
        
        # Trim to requested date range
        ohlcv = [c for c in all_ohlcv if c[0] <= until]
        
        return ohlcv

    def _backtest_symbol(self, symbol: str, threshold: int) -> None:
        """Backtest a single symbol."""
        since = int(self.start_date.timestamp() * 1000)
        until = int(self.end_date.timestamp() * 1000)
        
        # Calculate expected candles
        hours = int((self.end_date - self.start_date).total_seconds() / 3600)
        required_candles = hours + 200  # +200 for warmup
        
        logger.info(f"{symbol}: Need ~{required_candles} candles for {hours} hours")
        
        # Fetch with pagination if needed
        if required_candles > 2000:
            ohlcv = self._fetch_ohlcv_paginated(symbol, since, until)
        else:
            ohlcv = self.exchange.fetch_ohlcv(
                symbol, "1h", since=since, limit=2000
            )
        
        if len(ohlcv) < 200:
            logger.warning(f"Insufficient data for {symbol}")
            return
        
        # Validate data starts near expected date
        if ohlcv and abs(ohlcv[0][0] - since) > 86400000:  # >1 day off
            logger.warning(f"{symbol}: Data starts at {datetime.fromtimestamp(ohlcv[0][0]/1000)}, expected {self.start_date}")
        
        logger.info(f"Testing {symbol} with {len(ohlcv)} candles")
        
        # Process in rolling window
        for i in range(100, len(ohlcv) - 24):
            # Get lookback data
            historical = ohlcv[:i]
            closes = [c[4] for c in historical]
            highs = [c[2] for c in historical]
            lows = [c[3] for c in historical]
            volumes = [c[5] for c in historical]
            
            current_candle = historical[-1]
            current_price = current_candle[4]
            
            # Skip if already in position
            if symbol in self._open_positions:
                continue
            
            # Calculate indicators
            score = self._calculate_score(
                price=current_price,
                closes=closes,
                highs=highs,
                lows=lows,
                volumes=volumes
            )
            
            # Entry signal
            if score >= threshold:
                entry_price = current_price
                entry_time = datetime.fromtimestamp(current_candle[0]/1000)
                
                # Track open position
                self._open_positions.add(symbol)
                
                # Simulate trade with TP/SL
                atr = TechnicalAnalysis.calculate_atr(highs, lows, closes, 14)
                tp_price = entry_price + (settings.ATR_TP_MULTIPLIER * atr)
                sl_price = entry_price - (settings.ATR_SL_MULTIPLIER * atr)
                
                # Look ahead up to 24 hours for exit
                future = ohlcv[i:i+24]
                exit_price = None
                exit_time = None
                exit_reason = None
                
                for future_candle in future:
                    high = future_candle[2]
                    low = future_candle[3]
                    
                    tp_hit = high >= tp_price
                    sl_hit = low <= sl_price
                    
                    # Conservative: if both hit same candle, assume SL hit first
                    if sl_hit and tp_hit:
                        exit_price = sl_price
                        exit_time = datetime.fromtimestamp(future_candle[0]/1000)
                        exit_reason = "SL"
                        break
                    elif tp_hit:
                        exit_price = tp_price
                        exit_time = datetime.fromtimestamp(future_candle[0]/1000)
                        exit_reason = "TP"
                        break
                    elif sl_hit:
                        exit_price = sl_price
                        exit_time = datetime.fromtimestamp(future_candle[0]/1000)
                        exit_reason = "SL"
                        break
                
                # No exit in 24h - close at market
                if exit_price is None:
                    exit_price = future[-1][4]
                    exit_time = datetime.fromtimestamp(future[-1][0]/1000)
                    exit_reason = "TIME"
                
                # Clear open position
                self._open_positions.discard(symbol)
                
                # Calculate PnL with fees
                raw_pnl_pct = (exit_price - entry_price) / entry_price * 100
                pnl_pct = raw_pnl_pct - (FEE_PCT * 2 * 100)  # Round trip fees
                
                # Use fixed position sizing like live bot
                position_size = min(settings.TRADE_AMOUNT_USD, self.balance * 0.95)
                pnl_usd = position_size * (pnl_pct / 100)
                
                self.balance += pnl_usd
                
                self.trades.append({
                    "symbol": symbol,
                    "entry_time": entry_time.isoformat(),
                    "exit_time": exit_time.isoformat(),
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "pnl_raw_pct": raw_pnl_pct,
                    "pnl_usd": pnl_usd,
                    "position_size": position_size,
                    "reason": exit_reason,
                    "score": score
                })
                
                # Track equity curve
                self.equity_curve.append({
                    "time": exit_time.isoformat(),
                    "equity": self.balance
                })
                
                logger.info(f"Trade: {symbol} {entry_time.date()} {exit_reason} {pnl_pct:.2f}%")

    def _calculate_results(self) -> dict:
        """Calculate backtest results."""
        if not self.trades:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "max_drawdown": 0,
                "note": "No trades generated"
            }
        
        wins = sum(1 for t in self.trades if t["pnl_pct"] > 0)
        total_pnl = sum(t["pnl_usd"] for t in self.trades)
        win_rate = wins / len(self.trades) * 100
        
        # Calculate max drawdown
        peak = self.initial_balance
        max_dd = 0
        equity = self.initial_balance
        
        for trade in self.trades:
            equity += trade["pnl_usd"]
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        
        results = {
            "period": f"{self.start_date.date()} to {self.end_date.date()}",
            "initial_balance": self.initial_balance,
            "final_balance": self.balance,
            "total_pnl": total_pnl,
            "total_pnl_pct": (self.balance - self.initial_balance) / self.initial_balance * 100,
            "total_trades": len(self.trades),
            "win_rate": win_rate,
            "max_drawdown": max_dd,
            "wins": wins,
            "losses": len(self.trades) - wins,
            "equity_curve": self.equity_curve,
            "note": "Threshold analysis below shows performance IF you had filtered trades by score - it does not show what would have happened if you used a different threshold from the start. Re-run with different thresholds separately for accurate comparison."
        }
        
        # Save results
        os.makedirs("/tmp/data", exist_ok=True)
        with open("/tmp/data/backtest_results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)
        
        logger.info(f"Backtest complete: {len(self.trades)} trades, {win_rate:.1f}% win rate, ${total_pnl:.2f} PnL")
        
        return results


def run_backtest_sync(days: int = 30, threshold: int = 7) -> dict:
    """Run backtest synchronously (for use in async contexts)."""
    end = datetime.now()
    start = end - timedelta(days=days)
    
    backtester = Backtester(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        initial_balance=10000
    )
    
    return backtester.run_backtest(settings.SYMBOLS, score_threshold=threshold)


async def run_quick_backtest(days: int = 30) -> dict:
    """Run a quick backtest over recent days."""
    return await asyncio.get_event_loop().run_in_executor(
        None, run_backtest_sync, days, settings.REQUIRED_SCORE
    )