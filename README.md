# Crypto Sniper Bot

An autonomous cryptocurrency snipe bot that scans Binance for high-probability trading setups using a 10-point institutional scoring system, executes trades with pro-trader risk management, and provides real-time monitoring via a Web UI and Telegram bot.

## Features

- **10-Point Institutional Scoring System**: Analyzes trend, structure, Elliott waves, Fibonacci confluence, sentiment, and volume
- **AI-Powered Sentiment Analysis**: Uses Groq LLM (llama-3.3-70b-versatile) for market sentiment scoring
- **Advanced Technical Analysis**: Fibonacci levels, EMA, RSI, ATR, BOS detection, Elliott Wave identification
- **Pro-Trader Risk Management**: ATR-based TP/SL, breakeven moves, partial closes at 90% target
- **Circuit Breaker Protection**: Automatic pause after 3 consecutive failures
- **Real-time Web Dashboard**: Dark mode UI with live scores, positions, and AI intelligence feed
- **Telegram Bot**: Full command control (/start, /status, /holdings, /pause, /resume, /stats)
- **Koyeb Deployment Ready**: Single web service with health checks

## Prerequisites

- Python 3.11+
- Binance API keys (testnet for testing, production for live trading)
- Groq API key (free tier available)
- Telegram bot token

## Quick Start

### 1. Clone and Install Dependencies

```bash
cd crypto_sniper
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run Locally

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Or simply:

```bash
python main.py
```

### 4. Access the Dashboard

Open http://localhost:8000 in your browser.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BINANCE_API_KEY` | Binance API key | Required |
| `BINANCE_SECRET` | Binance API secret | Required |
| `USE_TESTNET` | Use Binance testnet | true |
| `GROQ_API_KEY` | Groq API key for AI sentiment | Required |
| `TELEGRAM_TOKEN` | Telegram bot token | Optional |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for notifications | Optional |
| `TRADE_AMOUNT_USD` | Trade amount in USD | 11.50 |
| `MAX_CONCURRENT_POSITIONS` | Max open positions | 3 |
| `SCAN_INTERVAL_SECONDS` | Scan frequency | 900 (15 min) |

## Koyeb Deployment

### Option 1: Deploy from GitHub

1. Push your code to a GitHub repository
2. Create a new app on Koyeb (https://koyeb.com)
3. Select "Git" as the deployment method
4. Choose your repository and branch
5. Koyeb will automatically detect the `koyeb.yaml` and deploy

### Option 2: Manual Docker Deploy

```bash
# Build the Docker image
docker build -t crypto-sniper .

# Run locally
docker run -p 8000:8000 --env-file .env crypto-sniper
```

### Koyeb Configuration

The `koyeb.yaml` file is pre-configured:
- Service type: Web
- Instance: Nano
- Port: 8000
- Health check: /health

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/status` | View current market analysis |
| `/holdings` | View open positions |
| `/pause` | Pause the scanner |
| `/resume` | Resume the scanner |
| `/stats` | View bot statistics |

## Scoring System

The bot uses a 10-point institutional scoring system:

**Trend & Structure (max 3 points)**
- +1: Price above EMA 20
- +1: Break of Structure (BOS) detected
- +1: Price/EMA ratio >= 1 + MOMENTUM_EMA_GAP

**Elliott Wave (max 2 points)**
- +2: Wave 5 Breakout or Ignition
- +1: Wave 4 Retracement

**Fibonacci + EMA Confluence (max 3 points)**
- +1: At Fibonacci level
- +2: At golden zone (50% or 61.8%)
- +2: Within EMA tolerance if no fib hit

**Sentiment (max 3 points)**
- +1: Sentiment >= 0.70
- +1: Sentiment >= 0.85
- +1: Sentiment improvement >= 0.10

**Volume (max 1 point)**
- +1: Volume spike detected

## Risk Management

- **Entry**: Market orders with ATR-based TP/SL
- **TP**: Entry + (3.0 × ATR)
- **SL**: Entry - (1.5 × ATR)
- **Breakeven**: Moves to entry + 0.1% when 50% of TP distance reached
- **Partial Close**: Closes 50% at 90% of TP, tightens SL to midpoint
- **Max Hold Time**: 24 hours

## File Structure

```
crypto_sniper/
├── main.py              # FastAPI application
├── core/config.py       # Configuration
├── analysis/
│   ├── technical.py     # Technical indicators
│   ├── engine.py        # Scoring engine
│   └── sentiment.py     # AI sentiment
├── execution/
│   ├── executor.py      # Binance API wrapper
│   └── manager.py       # Risk management
├── services/
│   ├── scanner.py       # Market scanner
│   └── telegram.py      # Telegram bot
├── web/dashboard.html   # Web UI
├── Dockerfile           # Docker image
├── koyeb.yaml          # Koyeb config
└── requirements.txt    # Dependencies
```

## Notes

- All data files are stored in `/tmp/data/` for Koyeb filesystem compatibility
- The scanner runs in the background and checks positions every 30 seconds
- Circuit breaker activates after 3 consecutive failures
- Testnet mode is enabled by default for safe testing

## Disclaimer

This bot is for educational purposes. Use at your own risk. Always test thoroughly on testnet before using with real funds.