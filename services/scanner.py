"""
Market Scanner - Background scanning loop with circuit breaker.
"""

import logging
import asyncio
import time
from datetime import datetime

from core.config import settings
from analysis.engine import analyze_symbol
from execution.manager import RiskManager

logger = logging.getLogger(__name__)

# Global executor reference
_executor = None


def set_executor(exec_instance) -> None:
    """Set the global executor for scanner."""
    global _executor
    _executor = exec_instance


class MarketScanner:
    """Background market scanner with circuit breaker protection."""

    def __init__(self):
        self.consecutive_failures = 0
        self.circuit_breaker_active = False
        self.circuit_breaker_until = 0
        self._last_position_check = 0
        self._start_time = time.time()
        self._paused = False
        
        # Initialize scans counter
        self._init_scans_counter()

    def _init_scans_counter(self) -> None:
        """Initialize or load scans counter."""
        try:
            import json
            import os
            
            filepath = "/tmp/data/total_scans.json"
            if os.path.exists(filepath):
                with open(filepath, "r") as f:
                    data = json.load(f)
                    self._total_scans = data.get("total_scans", 0)
            else:
                self._total_scans = 0
                
            self._scans_start_time = data.get("start_time", datetime.now().isoformat())
        except:
            self._total_scans = 0
            self._scans_start_time = datetime.now().isoformat()

    def _save_scans_counter(self) -> None:
        """Save scans counter atomically."""
        try:
            import json
            import os
            
            filepath = "/tmp/data/total_scans.json"
            temp_path = filepath + ".tmp"
            
            with open(temp_path, "w") as f:
                json.dump({
                    "total_scans": self._total_scans,
                    "start_time": self._scans_start_time
                }, f)
            
            os.replace(temp_path, filepath)
        except Exception as e:
            logger.warning(f"Failed to save scans counter: {e}")

    async def run_forever(self) -> None:
        """Main scanning loop - runs continuously."""
        logger.info("Market scanner started")
        
        while True:
            try:
                # Check if paused
                if self._paused:
                    logger.info("Scanner paused, sleeping...")
                    await asyncio.sleep(60)
                    continue
                
                # Check circuit breaker
                if self.circuit_breaker_active:
                    if time.time() < self.circuit_breaker_until:
                        logger.warning(f"Circuit breaker active, sleeping 60s...")
                        await asyncio.sleep(60)
                        continue
                    else:
                        logger.info("Circuit breaker deactivated")
                        self.circuit_breaker_active = False
                        self.consecutive_failures = 0
                
                # Check positions every 30 seconds minimum
                current_time = time.time()
                if current_time - self._last_position_check >= 30:
                    if _executor is not None:
                        await RiskManager.check_and_manage_positions(_executor)
                    self._last_position_check = current_time
                
                # Scan all symbols
                logger.info(f"Scanning {len(settings.SYMBOLS)} symbols...")
                
                tasks = [analyze_symbol(s) for s in settings.SYMBOLS]
                await asyncio.gather(*tasks, return_exceptions=True)
                
                # Update scans counter
                self._total_scans += 1
                self._save_scans_counter()
                
                # Reset failures on success
                self.consecutive_failures = 0
                
                logger.info(f"Scan complete. Next scan in {settings.SCAN_INTERVAL_SECONDS}s")
                
            except Exception as e:
                self.consecutive_failures += 1
                logger.error(f"Scanner error (failure #{self.consecutive_failures}): {e}")
                
                # Activate circuit breaker
                if self.consecutive_failures >= settings.MAX_CONSECUTIVE_FAILURES:
                    self.circuit_breaker_active = True
                    self.circuit_breaker_until = time.time() + settings.CIRCUIT_BREAKER_PAUSE_SECONDS
                    
                    # Notify via Telegram
                    from services.telegram import TelegramService
                    try:
                        await TelegramService.send_message(
                            f"⚠️ <b>CIRCUIT BREAKER ACTIVATED</b>\n\n"
                            f"Consecutive failures: <code>{self.consecutive_failures}</code>\n"
                            f"Pausing for: <code>{settings.CIRCUIT_BREAKER_PAUSE_SECONDS}s</code>\n"
                            f"Resume at: <code>{datetime.fromtimestamp(self.circuit_breaker_until).strftime('%H:%M:%S')}</code>"
                        )
                    except:
                        pass
                    
                    logger.warning(f"Circuit breaker activated for {settings.CIRCUIT_BREAKER_PAUSE_SECONDS}s")
            
            # Sleep until next scan
            await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)

    def pause(self) -> None:
        """Pause the scanner."""
        self._paused = True
        logger.info("Scanner paused")

    def resume(self) -> None:
        """Resume the scanner."""
        self._paused = False
        logger.info("Scanner resumed")

    @property
    def is_paused(self) -> bool:
        """Check if scanner is paused."""
        return self._paused

    @property
    def uptime_seconds(self) -> float:
        """Get scanner uptime in seconds."""
        return time.time() - self._start_time

    @property
    def total_scans(self) -> int:
        """Get total scans count."""
        return self._total_scans


# Global scanner instance
_scanner: Optional[MarketScanner] = None


def get_scanner() -> MarketScanner:
    """Get or create the global scanner instance."""
    global _scanner
    if _scanner is None:
        _scanner = MarketScanner()
    return _scanner