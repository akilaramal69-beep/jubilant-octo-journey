import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Binance Configuration
    BINANCE_API_KEY: str = ""
    BINANCE_SECRET: str = ""
    USE_TESTNET: bool = True
    
    # Trading Configuration
    SYMBOLS: list[str] = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "DOGE/USDT"]
    SCAN_INTERVAL_SECONDS: int = 900
    TRADE_AMOUNT_USD: float = 11.50
    MAX_CONCURRENT_POSITIONS: int = 3
    FAST_TRADE_MODE: bool = False
    POSITION_COOLDOWN_SECONDS: int = 60
    
    # Technical Analysis Parameters
    FIB_TOLERANCE: float = 0.005
    MOMENTUM_EMA_GAP: float = 0.003
    ATR_TP_MULTIPLIER: float = 3.0
    ATR_SL_MULTIPLIER: float = 1.5
    BREAKEVEN_TRIGGER_PCT: float = 0.50
    PARTIAL_CLOSE_TRIGGER_PCT: float = 0.90
    SLIPPAGE_FEE_PCT: float = 0.001
    MAX_HOLDING_HOURS: int = 24
    MARKET_REGIME_EMA_PERIOD: int = 200
    INDICATOR_CACHE_TTL_SECONDS: int = 30
    
    # Risk Management
    MAX_CONSECUTIVE_FAILURES: int = 3
    CIRCUIT_BREAKER_PAUSE_SECONDS: int = 300
    
    # Groq AI Configuration
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_TIMEOUT_SECONDS: int = 10
    
    # Telegram Configuration
    TELEGRAM_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    
    # Required minimum score for trading
    REQUIRED_SCORE: int = 7


settings = Settings()