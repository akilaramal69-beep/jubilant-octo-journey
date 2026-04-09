"""
Telegram Bot Service - Command handlers and notifications.
"""

import logging
import asyncio
import json
import os
import time
import threading
from typing import Optional

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from core.config import settings
from services.scanner import get_scanner

logger = logging.getLogger(__name__)

# Module-level application
_telegram_app: Optional[Application] = None
_telegram_client: Optional[httpx.AsyncClient] = None


def _get_telegram_client() -> httpx.AsyncClient:
    """Get or create shared httpx client."""
    global _telegram_client
    if _telegram_client is None:
        _telegram_client = httpx.AsyncClient(timeout=10.0)
    return _telegram_client


class TelegramService:
    """Telegram bot service with command handlers."""

    @staticmethod
    async def send_message(text: str) -> None:
        """Send HTML-formatted message to configured chat ID."""
        if not settings.TELEGRAM_TOKEN or not settings.TELEGRAM_CHAT_ID:
            logger.debug("Telegram not configured, skipping message")
            return
        
        try:
            client = _get_telegram_client()
            
            url = f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/sendMessage"
            
            payload = {
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML"
            }
            
            response = await client.post(url, json=payload)
            response.raise_for_status()
            
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")

    @staticmethod
    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        welcome_text = """
🤖 <b>Crypto Sniper Bot</b>

Welcome to your autonomous trading assistant!

<b>Available Commands:</b>
/start   - Show this welcome message
/status  - View current market analysis
/holdings - View open positions
/pause   - Pause the scanner
/resume  - Resume the scanner
/stats   - View bot statistics

<i>The bot automatically scans for high-probability setups and executes trades.</i>
"""
        await update.message.reply_text(welcome_text, parse_mode="HTML")

    @staticmethod
    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command - show latest analysis."""
        try:
            filepath = "/tmp/data/latest_analysis.json"
            if not os.path.exists(filepath):
                await update.message.reply_text("No analysis data available yet.")
                return
            
            with open(filepath, "r") as f:
                data = json.load(f)
            
            if not data or len(data) <= 1:  # Only last_updated key
                await update.message.reply_text("No analysis data available yet.")
                return
            
            response = "📊 <b>MARKET STATUS</b>\n\n"
            
            symbols_in_data = [k for k in data.keys() if k != "last_updated"]
            
            if not symbols_in_data:
                await update.message.reply_text("No symbols analyzed yet.")
                return
            
            for symbol in settings.SYMBOLS:
                if symbol in data:
                    entry = data[symbol]
                    price = entry.get("price", 0)
                    score = entry.get("score", 0)
                    signal = entry.get("signal", "WAIT")
                    elliott = entry.get("elliott_phase", "None")
                    sentiment = entry.get("sentiment", 0.5)
                    timestamp = entry.get("timestamp", "")
                    
                    # Color code based on score
                    if score >= 7:
                        emoji = "🟢"
                    elif score >= 4:
                        emoji = "🟡"
                    else:
                        emoji = "🔴"
                    
                    response += f"<b>{symbol}</b> {emoji}\n"
                    response += f"  Price: <code>${price:.4f}</code>\n"
                    response += f"  Score: <code>{score}/10</code>\n"
                    response += f"  Signal: <code>{signal}</code>\n"
                    response += f"  Wave: <code>{elliott}</code>\n"
                    response += f"  Sentiment: <code>{sentiment:.2f}</code>\n\n"
                else:
                    response += f"<b>{symbol}</b> ⏳\n  Not yet analyzed\n\n"
            
            await update.message.reply_text(response, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Status command failed: {e}")
            await update.message.reply_text("Error fetching status.")

    @staticmethod
    async def holdings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /holdings command - show open positions."""
        try:
            from execution.manager import RiskManager
            from execution.executor import TradingExecutor
            
            positions = RiskManager.load_positions()
            
            if not positions:
                await update.message.reply_text("No open positions.")
                return
            
            response = "📁 <b>OPEN POSITIONS</b>\n\n"
            
            executor = TradingExecutor()
            
            for symbol, position in positions.items():
                try:
                    current_price = await executor.get_latest_price(symbol)
                except:
                    current_price = 0
                
                entry = position.get("entry_price", 0)
                qty = position.get("quantity", 0)
                tp = position.get("tp_price", 0)
                sl = position.get("sl_price", 0)
                side = position.get("side", "long")
                opened = position.get("opened_at", "")
                breakeven = position.get("breakeven_moved", False)
                partial = position.get("partial_closed", False)
                
                # Calculate PnL
                if current_price > 0:
                    if side == "long":
                        pnl_pct = (current_price - entry) / entry * 100
                    else:
                        pnl_pct = (entry - current_price) / entry * 100
                    pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
                else:
                    pnl_pct = 0
                    pnl_emoji = "⚪"
                
                # Time held
                try:
                    from datetime import datetime
                    opened_time = datetime.fromisoformat(opened)
                    hours_held = (datetime.now() - opened_time).total_seconds() / 3600
                    time_str = f"{hours_held:.1f}h"
                except:
                    time_str = "?"
                
                be_status = "✅" if breakeven else "❌"
                partial_status = "✅" if partial else "❌"
                
                response += f"<b>{symbol}</b> ({side.upper()})\n"
                response += f"  Entry: <code>${entry:.4f}</code>\n"
                response += f"  Current: <code>${current_price:.4f}</code> {pnl_emoji}\n"
                response += f"  PnL: <code>{pnl_pct:.2f}%</code>\n"
                response += f"  TP: <code>${tp:.4f}</code>\n"
                response += f"  SL: <code>${sl:.4f}</code>\n"
                response += f"  Time: <code>{time_str}</code>\n"
                response += f"  BE: {be_status} Partial: {partial_status}\n\n"
            
            await update.message.reply_text(response, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Holdings command failed: {e}")
            await update.message.reply_text("Error fetching holdings.")

    @staticmethod
    async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /pause command."""
        scanner = get_scanner()
        scanner.pause()
        await update.message.reply_text("⏸️ Scanner paused.")

    @staticmethod
    async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /resume command."""
        scanner = get_scanner()
        scanner.resume()
        await update.message.reply_text("▶️ Scanner resumed.")

    @staticmethod
    async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stats command."""
        try:
            scanner = get_scanner()
            
            # Load total scans
            filepath = "/tmp/data/total_scans.json"
            total_scans = 0
            start_time = "Unknown"
            
            if os.path.exists(filepath):
                with open(filepath, "r") as f:
                    data = json.load(f)
                    total_scans = data.get("total_scans", 0)
                    start_time = data.get("start_time", "Unknown")
            
            # Load positions
            from execution.manager import RiskManager
            positions = RiskManager.load_positions()
            
            # Calculate uptime
            try:
                from datetime import datetime
                start_dt = datetime.fromisoformat(start_time)
                uptime_hours = (datetime.now() - start_dt).total_seconds() / 3600
            except:
                uptime_hours = scanner.uptime_seconds / 3600
            
            status_emoji = "🟢" if not scanner.is_paused else "🔴"
            
            response = f"""📈 <b>BOT STATISTICS</b>

Status: {status_emoji} {"Running" if not scanner.is_paused else "Paused"}
Uptime: <code>{uptime_hours:.1f} hours</code>
Total Scans: <code>{total_scans}</code>
Active Positions: <code>{len(positions)}/{settings.MAX_CONCURRENT_POSITIONS}</code>
Circuit Breaker: {"🔴 Active" if scanner.circuit_breaker_active else "🟢 Normal"}
"""
            
            await update.message.reply_text(response, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Stats command failed: {e}")
            await update.message.reply_text("Error fetching stats.")


def start_telegram_bot_thread() -> None:
    """Start Telegram bot in a separate thread."""
    if not settings.TELEGRAM_TOKEN:
        logger.warning("Telegram token not configured, bot not started")
        return
    
    def run_bot():
        """Run bot in thread."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            app = Application.builder().token(settings.TELEGRAM_TOKEN).build()
            
            # Register handlers
            app.add_handler(CommandHandler("start", TelegramService.start_command))
            app.add_handler(CommandHandler("status", TelegramService.status_command))
            app.add_handler(CommandHandler("holdings", TelegramService.holdings_command))
            app.add_handler(CommandHandler("pause", TelegramService.pause_command))
            app.add_handler(CommandHandler("resume", TelegramService.resume_command))
            app.add_handler(CommandHandler("stats", TelegramService.stats_command))
            
            logger.info("Starting Telegram bot polling...")
            app.run_polling()
            
        except Exception as e:
            logger.error(f"Telegram bot error: {e}")
    
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    logger.info("Telegram bot thread started")