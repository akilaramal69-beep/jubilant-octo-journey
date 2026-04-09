"""
Risk Manager - Position management, TP/SL, breakeven, partial closes.
"""

import logging
import asyncio
import json
import os
import time
from datetime import datetime
from typing import Optional

from core.config import settings
from execution.executor import TradingExecutor

logger = logging.getLogger(__name__)

# Module-level lock for file operations
_file_lock = asyncio.Lock()


def _load_json_safe(filepath: str) -> dict:
    """Load JSON file safely."""
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


class RiskManager:
    """Risk management for positions."""

    @staticmethod
    def load_positions() -> dict:
        """Load positions from JSON file (sync for quick checks)."""
        return _load_json_safe("/tmp/data/positions.json")

    @staticmethod
    async def save_position(
        symbol: str,
        entry_price: float,
        quantity: float,
        side: str,
        tp_price: float,
        sl_price: float
    ) -> None:
        """Save or update a position."""
        async with _file_lock:
            positions = _load_json_safe("/tmp/data/positions.json")
            
            positions[symbol] = {
                "entry_price": entry_price,
                "quantity": quantity,
                "side": side,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "opened_at": datetime.now().isoformat(),
                "breakeven_moved": False,
                "partial_closed": False,
                "original_quantity": quantity
            }
            
            _atomic_write_json("/tmp/data/positions.json", positions)
            logger.info(f"Position saved: {symbol} @ {entry_price}")

    @staticmethod
    async def remove_position(symbol: str) -> None:
        """Remove a position from tracking."""
        async with _file_lock:
            positions = _load_json_safe("/tmp/data/positions.json")
            
            if symbol in positions:
                del positions[symbol]
                _atomic_write_json("/tmp/data/positions.json", positions)
                logger.info(f"Position removed: {symbol}")

    @staticmethod
    def calculate_position_size(balance: float) -> float:
        """
        Calculate position size based on balance.
        
        Args:
            balance: Available USDT balance
            
        Returns:
            Position size in USD
        """
        if balance <= 0:
            return settings.TRADE_AMOUNT_USD
        
        # Use 95% of balance or fixed amount, whichever is smaller
        position_size = min(settings.TRADE_AMOUNT_USD, balance * 0.95)
        
        # Enforce minimum
        return max(position_size, 11.50)

    @staticmethod
    async def check_and_manage_positions(executor: TradingExecutor) -> None:
        """Check and manage all open positions (TP/SL/breakeven/partial close)."""
        positions = RiskManager.load_positions()
        
        if not positions:
            return
        
        symbols_to_close = []
        
        for symbol, position in list(positions.items()):
            try:
                # Get current price
                current_price = await executor.get_latest_price(symbol)
                entry_price = position["entry_price"]
                quantity = position["quantity"]
                side = position["side"]
                tp_price = position["tp_price"]
                sl_price = position["sl_price"]
                opened_at = position["opened_at"]
                breakeven_moved = position.get("breakeven_moved", False)
                partial_closed = position.get("partial_closed", False)
                
                # Calculate profit percentage
                if side == "long":
                    profit_pct = (current_price - entry_price) / entry_price
                else:
                    profit_pct = (entry_price - current_price) / entry_price
                
                # Calculate distance to TP
                if side == "long":
                    tp_distance = (tp_price - entry_price) / entry_price
                else:
                    tp_distance = (entry_price - tp_price) / entry_price
                
                # Check breakeven move
                if not breakeven_moved and tp_distance > 0:
                    trigger_pct = settings.BREAKEVEN_TRIGGER_PCT
                    if profit_pct >= trigger_pct * tp_distance:
                        # Move SL to breakeven + fee
                        new_sl = entry_price * (1 + settings.SLIPPAGE_FEE_PCT)
                        
                        position["sl_price"] = new_sl
                        position["breakeven_moved"] = True
                        
                        # Save update
                        async with _file_lock:
                            _atomic_write_json("/tmp/data/positions.json", positions)
                        
                        await RiskManager._send_telegram(
                            f"📊 <b>BREAKEVEN MOVED</b>\n\n"
                            f"Symbol: <code>{symbol}</code>\n"
                            f"Entry: <code>${entry_price:.4f}</code>\n"
                            f"New SL: <code>${new_sl:.4f}</code>\n"
                            f"Profit: <code>{profit_pct*100:.2f}%</code>"
                        )
                        
                        logger.info(f"Breakeven moved for {symbol} to {new_sl}")
                
                # Check partial close
                if not partial_closed and tp_distance > 0:
                    trigger_pct = settings.PARTIAL_CLOSE_TRIGGER_PCT
                    if profit_pct >= trigger_pct * tp_distance:
                        # Sell 50% of position
                        partial_qty = quantity * 0.50
                        
                        try:
                            await executor.place_order(symbol, "sell", partial_qty)
                            
                            # Tighten SL to midpoint
                            if side == "long":
                                new_sl = entry_price + 0.5 * (tp_price - entry_price)
                            else:
                                new_sl = entry_price - 0.5 * (tp_price - entry_price)
                            
                            position["quantity"] = quantity - partial_qty
                            position["sl_price"] = new_sl
                            position["partial_closed"] = True
                            
                            # Save update
                            async with _file_lock:
                                _atomic_write_json("/tmp/data/positions.json", positions)
                            
                            await RiskManager._send_telegram(
                                f"📊 <b>PARTIAL CLOSE</b>\n\n"
                                f"Symbol: <code>{symbol}</code>\n"
                                f"Sold: <code>{partial_qty:.6f}</code> (50%)\n"
                                f"Remaining: <code>{position['quantity']:.6f}</code>\n"
                                f"New SL: <code>${new_sl:.4f}</code>"
                            )
                            
                            logger.info(f"Partial close executed for {symbol}")
                            
                        except Exception as e:
                            logger.error(f"Partial close failed for {symbol}: {e}")
                
                # Check SL hit
                if side == "long" and current_price <= sl_price:
                    symbols_to_close.append((symbol, "SL hit"))
                elif side == "short" and current_price >= sl_price:
                    symbols_to_close.append((symbol, "SL hit"))
                
                # Check TP hit
                elif side == "long" and current_price >= tp_price:
                    symbols_to_close.append((symbol, "TP hit"))
                elif side == "short" and current_price <= tp_price:
                    symbols_to_close.append((symbol, "TP hit"))
                
                # Check max holding time
                opened_time = datetime.fromisoformat(opened_at)
                hours_held = (datetime.now() - opened_time).total_seconds() / 3600
                
                if hours_held >= settings.MAX_HOLDING_HOURS:
                    symbols_to_close.append((symbol, "Max hold time reached"))
                
            except Exception as e:
                logger.error(f"Position check failed for {symbol}: {e}")
        
        # Close positions
        for symbol, reason in symbols_to_close:
            try:
                positions = RiskManager.load_positions()
                if symbol in positions:
                    position = positions[symbol]
                    qty = position["quantity"]
                    
                    # Close position
                    side = position["side"]
                    close_side = "sell" if side == "long" else "buy"
                    
                    await executor.place_order(symbol, close_side, qty)
                    await RiskManager.remove_position(symbol)
                    
                    await RiskManager._send_telegram(
                        f"🛑 <b>POSITION CLOSED</b>\n\n"
                        f"Symbol: <code>{symbol}</code>\n"
                        f"Reason: <code>{reason}</code>\n"
                        f"Qty: <code>{qty:.6f}</code>"
                    )
                    
                    logger.info(f"Position closed: {symbol} - {reason}")
                    
            except Exception as e:
                logger.error(f"Failed to close position {symbol}: {e}")

    @staticmethod
    async def _send_telegram(message: str) -> None:
        """Send Telegram notification."""
        from services.telegram import TelegramService
        try:
            await TelegramService.send_message(message)
        except Exception as e:
            logger.warning(f"Telegram notification failed: {e}")