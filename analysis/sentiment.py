"""
Sentiment Analysis Module using Groq AI SDK.
"""

import logging
import re
from typing import Optional
import groq
from core.config import settings

logger = logging.getLogger(__name__)

# Initialize Groq client once at module level
_groq_client: Optional[groq.AsyncGroq] = None


def _get_groq_client() -> groq.AsyncGroq:
    """Get or initialize the Groq client."""
    global _groq_client
    if _groq_client is None:
        _groq_client = groq.AsyncGroq(
            api_key=settings.GROQ_API_KEY,
            timeout=settings.GROQ_TIMEOUT_SECONDS
        )
    return _groq_client


class SentimentAnalysis:
    """AI-powered sentiment analysis using Groq LLM."""

    @staticmethod
    async def get_news_sentiment(symbol: str) -> float:
        """
        Get sentiment score for a cryptocurrency using AI analysis.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTC/USDT")
            
        Returns:
            Float between 0.0 (bearish) and 1.0 (bullish), defaults to 0.5 on error
        """
        try:
            # Extract coin name from symbol (e.g., BTC/USDT -> BTC)
            coin_name = symbol.split("/")[0].strip()
            
            # Map common symbols to full names
            coin_names = {
                "BTC": "Bitcoin",
                "ETH": "Ethereum",
                "SOL": "Solana",
                "BNB": "BNB",
                "DOGE": "Dogecoin",
                "XRP": "XRP",
                "ADA": "Cardano",
                "AVAX": "Avalanche",
                "DOT": "Polkadot",
                "MATIC": "Polygon",
                "LINK": "Chainlink",
                "UNI": "Uniswap",
                "ATOM": "Cosmos",
                "LTC": "Litecoin",
                "FIL": "Filecoin",
                "APT": "Aptos",
                "ARB": "Arbitrum",
                "OP": "Optimism"
            }
            
            display_name = coin_names.get(coin_name, coin_name)
            
            system_prompt = """You are a professional crypto trading analyst with access to real-time 
market intelligence. Analyze the current market sentiment for the requested 
cryptocurrency. Consider: recent price action narrative, social media momentum, 
fear/greed dynamics, and macro crypto market conditions. 
Respond with ONLY a single float number between 0.0 and 1.0.
0.0 = extreme fear/bearish, 0.5 = neutral, 1.0 = extreme greed/bullish.
No explanation. No text. Only the number."""
            
            user_prompt = f"Sentiment score for {display_name} right now?"
            
            client = _get_groq_client()
            
            chat_completion = await client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=10
            )
            
            response = chat_completion.choices[0].message.content
            logger.debug(f"Groq response for {symbol}: {response}")
            
            # Try direct float conversion first
            try:
                sentiment = float(response.strip())
                return max(0.0, min(1.0, sentiment))
            except (ValueError, TypeError):
                pass
            
            # Try regex fallback
            match = re.search(r'\d+\.?\d*', response)
            if match:
                sentiment = float(match.group())
                return max(0.0, min(1.0, sentiment))
            
            logger.warning(f"Could not parse sentiment from response: {response}")
            return 0.5
            
        except Exception as e:
            logger.error(f"Sentiment analysis failed for {symbol}: {e}")
            return 0.5