"""
Trading Executor - Binance API wrapper using ccxt.
"""

import logging
from typing import Optional
import ccxt

from core.config import settings

logger = logging.getLogger(__name__)


class TradingExecutor:
    """Async Binance exchange executor using ccxt."""

    def __init__(self):
        """Initialize ccxt Binance with API keys."""
        self.exchange = ccxt.binance({
            "apiKey": settings.BINANCE_API_KEY,
            "secret": settings.BINANCE_SECRET,
            "enableRateLimit": True,
            "defaultType": "spot",
            "options": {
                "defaultType": "spot"
            }
        })
        
        # Set testnet if configured
        if settings.USE_TESTNET:
            self.exchange.set_sandbox_mode(True)
            logger.info("Binance testnet mode enabled")
        else:
            logger.info("Binance production mode enabled")

    async def get_latest_price(self, symbol: str) -> float:
        """
        Fetch current price for a symbol.
        
        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            
        Returns:
            Current price as float
        """
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return float(ticker["last"])
        except Exception as e:
            logger.error(f"Failed to fetch price for {symbol}: {e}")
            raise

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200) -> list:
        """
        Fetch OHLCV candlestick data.
        
        Args:
            symbol: Trading pair
            timeframe: Candle timeframe (1m, 5m, 1h, 4h, 1d)
            limit: Number of candles to fetch
            
        Returns:
            List of OHLCV data [timestamp, open, high, low, close, volume]
        """
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return ohlcv
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV for {symbol}: {e}")
            return []

    async def get_balance(self, currency: str = "USDT") -> float:
        """
        Get available balance for a currency.
        
        Args:
            currency: Currency symbol (default: USDT)
            
        Returns:
            Available balance as float
        """
        try:
            balance = await self.exchange.fetch_balance()
            free = balance.get("free", {}).get(currency, 0.0)
            return float(free)
        except Exception as e:
            logger.error(f"Failed to fetch balance for {currency}: {e}")
            return 0.0

    async def fetch_ticker(self, symbol: str) -> dict:
        """
        Fetch full ticker information for a symbol.
        
        Args:
            symbol: Trading pair
            
        Returns:
            Full ticker dictionary
        """
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return ticker
        except Exception as e:
            logger.error(f"Failed to fetch ticker for {symbol}: {e}")
            return {}

    async def place_order(self, symbol: str, side: str, amount: float) -> dict:
        """
        Place a market order.
        
        Args:
            symbol: Trading pair
            side: "buy" or "sell"
            amount: Order amount in base currency
            
        Returns:
            Order result dictionary
            
        Raises:
            ValueError: If amount below minimum or precision issues
        """
        try:
            # Get market info for precision
            market = self.exchange.market(symbol)
            precision = market.get("precision", {}).get("amount", 8)
            
            # Apply precision
            amount = float(self.exchange.amount_to_precision(symbol, amount))
            
            # Check minimum amount
            min_amount = market.get("limits", {}).get("amount", {}).get("min", 0)
            if amount < min_amount:
                raise ValueError(f"Amount {amount} below minimum {min_amount}")
            
            # Place market order
            order = await self.exchange.create_order(
                symbol=symbol,
                type="market",
                side=side,
                amount=amount
            )
            
            logger.info(f"Order placed: {side} {amount} {symbol}")
            return order
            
        except Exception as e:
            logger.error(f"Failed to place order for {symbol}: {e}")
            raise

    async def close_connection(self) -> None:
        """Close the exchange connection."""
        try:
            await self.exchange.close()
            logger.info("Binance connection closed")
        except Exception as e:
            logger.warning(f"Error closing connection: {e}")