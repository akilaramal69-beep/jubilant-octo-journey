"""
FastAPI Main Application - Web server and API endpoints.
"""

import os
import json
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from core.config import settings
from execution.executor import TradingExecutor
from analysis.engine import set_executor
from services.scanner import MarketScanner, get_scanner, set_executor as set_scanner_executor
from services.telegram import start_telegram_bot_thread

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create /tmp/data directory on startup
os.makedirs("/tmp/data", exist_ok=True)

# Global executor instance
_executor: Optional[TradingExecutor] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    global _executor
    
    # Initialize executor
    _executor = TradingExecutor()
    
    # Set executor for analysis engine
    set_executor(_executor)
    
    # Set executor for scanner
    set_scanner_executor(_executor)
    
    logger.info("Starting Crypto Sniper Bot...")
    
    # Start scanner background task
    scanner = get_scanner()
    asyncio.create_task(scanner.run_forever())
    
    # Start Telegram bot in thread
    start_telegram_bot_thread()
    
    logger.info("All services started")
    
    yield
    
    # Cleanup
    logger.info("Shutting down...")
    if _executor:
        await _executor.close_connection()


app = FastAPI(
    title="Crypto Sniper Bot",
    description="Autonomous cryptocurrency trading bot with AI sentiment analysis",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """Koyeb health check endpoint."""
    return JSONResponse({"status": "ok"})


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard HTML."""
    try:
        with open("web/dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        try:
            with open("/app/web/dashboard.html", "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return HTMLResponse(
                content="<html><body><h1>Dashboard not found</h1></body></html>",
                status_code=404
        )


@app.get("/api/status")
async def api_status():
    """Return latest analysis data."""
    try:
        filepath = "/tmp/data/latest_analysis.json"
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                data = json.load(f)
            return JSONResponse(data)
        return JSONResponse({})
    except Exception as e:
        logger.error(f"API status error: {e}")
        return JSONResponse({"error": str(e)})


@app.get("/api/positions")
async def api_positions():
    """Return open positions."""
    try:
        filepath = "/tmp/data/positions.json"
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                data = json.load(f)
            return JSONResponse(data)
        return JSONResponse({})
    except Exception as e:
        logger.error(f"API positions error: {e}")
        return JSONResponse({"error": str(e)})


@app.get("/api/history")
async def api_history():
    """Return analysis history (last 50 entries per symbol)."""
    try:
        filepath = "/tmp/data/analysis_history.json"
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                data = json.load(f)
            
            # Limit to last 50 entries per symbol
            limited_data = {}
            for symbol, entries in data.items():
                limited_data[symbol] = entries[-50:] if len(entries) > 50 else entries
            
            return JSONResponse(limited_data)
        return JSONResponse({})
    except Exception as e:
        logger.error(f"API history error: {e}")
        return JSONResponse({"error": str(e)})


@app.get("/api/scanner")
async def api_scanner():
    """Return scanner status."""
    try:
        scanner = get_scanner()
        return JSONResponse({
            "paused": scanner.is_paused,
            "consecutive_failures": scanner.consecutive_failures,
            "circuit_breaker_active": scanner.circuit_breaker_active,
            "uptime_seconds": scanner.uptime_seconds,
            "total_scans": scanner.total_scans
        })
    except Exception as e:
        logger.error(f"API scanner error: {e}")
        return JSONResponse({"error": str(e)})


@app.post("/api/scanner/pause")
async def api_scanner_pause():
    """Pause the scanner."""
    scanner = get_scanner()
    scanner.pause()
    return JSONResponse({"status": "paused"})


@app.post("/api/scanner/resume")
async def api_scanner_resume():
    """Resume the scanner."""
    scanner = get_scanner()
    scanner.resume()
    return JSONResponse({"status": "resumed"})


@app.get("/api/balance")
async def api_balance():
    """Return current account balance."""
    try:
        if _executor:
            balance = await _executor.get_balance("USDT")
            return JSONResponse({"USDT": balance})
        return JSONResponse({"error": "Executor not initialized"})
    except Exception as e:
        logger.error(f"API balance error: {e}")
        return JSONResponse({"error": str(e)})


@app.get("/api/trades")
async def api_trades():
    """Return trade history."""
    try:
        filepath = "/tmp/data/trade_history.json"
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                data = json.load(f)
            return JSONResponse(data)
        return JSONResponse({"trades": []})
    except Exception as e:
        logger.error(f"API trades error: {e}")
        return JSONResponse({"error": str(e)})


@app.get("/api/stats")
async def api_stats():
    """Return trading statistics."""
    try:
        trades_file = "/tmp/data/trade_history.json"
        trades = []
        if os.path.exists(trades_file):
            with open(trades_file, "r") as f:
                data = json.load(f)
                trades = data.get("trades", [])
        
        if not trades:
            return JSONResponse({
                "total_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_win": 0,
                "avg_loss": 0
            })
        
        wins = [t for t in trades if t.get("pnl_pct", 0) > 0]
        losses = [t for t in trades if t.get("pnl_pct", 0) <= 0]
        
        win_rate = len(wins) / len(trades) * 100 if trades else 0
        total_pnl = sum(t.get("pnl_usd", 0) for t in trades)
        avg_win = sum(t.get("pnl_pct", 0) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.get("pnl_pct", 0) for t in losses) / len(losses) if losses else 0
        
        return JSONResponse({
            "total_trades": len(trades),
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "wins": len(wins),
            "losses": len(losses)
        })
    except Exception as e:
        logger.error(f"API stats error: {e}")
        return JSONResponse({"error": str(e)})


@app.get("/metrics")
async def metrics():
    """Prometheus-style metrics endpoint."""
    try:
        scanner = get_scanner()
        
        # Load position count
        positions_file = "/tmp/data/positions.json"
        position_count = 0
        if os.path.exists(positions_file):
            with open(positions_file, "r") as f:
                positions = json.load(f)
                position_count = len(positions)
        
        # Load total scans
        scans_file = "/tmp/data/total_scans.json"
        total_scans = 0
        if os.path.exists(scans_file):
            with open(scans_file, "r") as f:
                data = json.load(f)
                total_scans = data.get("total_scans", 0)
        
        metrics_text = f"""# HELP crypto_scanner_uptime_seconds Bot uptime in seconds
# TYPE crypto_scanner_uptime_seconds gauge
crypto_scanner_uptime_seconds {scanner.uptime_seconds}

# HELP crypto_scanner_total_scans Total number of scans performed
# TYPE crypto_scanner_total_scans counter
crypto_scanner_total_scans {total_scans}

# HELP crypto_positions_open Current number of open positions
# TYPE crypto_positions_open gauge
crypto_positions_open {position_count}

# HELP crypto_scanner_paused Scanner paused status (1=paused, 0=running)
# TYPE crypto_scanner_paused gauge
crypto_scanner_paused {1 if scanner.is_paused else 0}
"""
        
        return PlainTextResponse(content=metrics_text, media_type="text/plain")
        
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        return PlainTextResponse(content="", status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


@app.post("/api/backtest")
async def api_backtest(days: int = 30, threshold: int = 7):
    """Run a backtest and return results."""
    try:
        from analysis.backtest import run_backtest_sync
        import asyncio
        
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, run_backtest_sync, days, threshold
        )
        return JSONResponse(results)
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        return JSONResponse({"error": str(e)})


@app.get("/api/backtest")
async def get_backtest_results():
    """Get saved backtest results."""
    try:
        filepath = "/tmp/data/backtest_results.json"
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                data = json.load(f)
            return JSONResponse(data)
        return JSONResponse({"error": "No backtest results found"})
    except Exception as e:
        logger.error(f"Get backtest error: {e}")
        return JSONResponse({"error": str(e)})