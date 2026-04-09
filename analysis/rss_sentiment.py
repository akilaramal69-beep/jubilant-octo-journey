"""
RSS News Sentiment - Fetch crypto headlines for sentiment analysis.
"""

import logging
import asyncio
import re
import xml.etree.ElementTree as ET
from typing import Optional
from datetime import datetime
from functools import lru_cache

import httpx

logger = logging.getLogger(__name__)

# RSS feed URLs for crypto news (with priority weights)
RSS_FEEDS = [
    ("https://www.coindesk.com/feed/", 0.4),      # High credibility
    ("https://cointelegraph.com/rss", 0.4),       # High credibility
    ("https://cryptopanic.com/api/v1/posts/?auth_token=&public=true&kind=news", 0.2),
]

# Weighted keywords for sentiment scoring
BULLISH_KEYWORDS = {
    "bullish": 1.0, "surge": 1.2, "soar": 1.2, "rally": 1.0, "gain": 0.8, "rise": 0.8,
    "breakout": 1.0, "high": 0.5, "new high": 1.2, "record": 1.0, "growth": 0.9,
    "adoption": 0.9, "upgrade": 0.8, "partnership": 0.8, "launch": 0.8, "positive": 0.7,
    "optimistic": 0.8, "buy": 0.9, "long": 0.7, "breakthrough": 1.0, "skyrocket": 1.3,
    "surges": 1.2, "soars": 1.2, "rallys": 1.0, "gains": 0.8, "jumps": 0.9, "rockets": 1.2,
    "ethusiastic": 0.8, "boom": 1.1, "bull run": 1.2, "all-time high": 1.2
}

BEARISH_KEYWORDS = {
    "bearish": 1.0, "crash": 1.3, "plunge": 1.2, "drop": 0.8, "fall": 0.8, "sell": 0.9,
    "breakdown": 1.0, "low": 0.5, "new low": 1.2, "decline": 0.8, "recession": 0.9,
    "hack": 1.0, "scam": 1.1, "ban": 0.9, "warning": 0.7, "risk": 0.6, "negative": 0.7,
    "pessimistic": 0.8, "short": 0.7, "correction": 0.7, "tumble": 1.1, "slump": 0.9,
    "drops": 0.8, "falls": 0.8, "crashes": 1.3, "plunges": 1.2, "selloff": 1.0,
    "bear run": 1.1, "all-time low": 1.2, "crisis": 1.0, "fraud": 1.1, "investigation": 0.9
}

# Cache TTL in seconds
CACHE_TTL = 600  # 10 minutes


class RSSFetcher:
    """Fetch and parse RSS feeds for crypto news sentiment."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._cache: dict = {"sentiment": (None, 0), "articles": (None, 0)}

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create shared HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
        return self._client

    def _is_cache_valid(self, cache_type: str) -> bool:
        """Check if cache is still valid."""
        if cache_type in self._cache:
            _, timestamp = self._cache[cache_type]
            return (datetime.now().timestamp() - timestamp) < CACHE_TTL
        return False

    async def fetch_feed(self, url: str) -> list[dict]:
        """
        Fetch and parse RSS/JSON feed.
        
        Args:
            url: Feed URL
            
        Returns:
            List of article dictionaries with title, published, source, weight
        """
        try:
            client = self._get_client()
            response = await client.get(url)
            response.raise_for_status()
            
            content = response.text
            
            # Determine feed type by URL
            if "cryptopanic" in url:
                return self._parse_json_feed(content)
            else:
                return self._parse_xml_feed(content)
            
        except Exception as e:
            logger.debug(f"Feed fetch failed for {url}: {e}")
            return []

    def _parse_xml_feed(self, content: str) -> list[dict]:
        """Parse RSS XML format using ElementTree."""
        articles = []
        
        try:
            root = ET.fromstring(content)
            
            # RSS format
            if root.tag == "rss":
                channel = root.find("channel")
                if channel is not None:
                    for item in channel.findall("item"):
                        article = self._extract_rss_item(item)
                        if article:
                            articles.append(article)
            
            # Atom format
            elif root.tag == "feed":
                for entry in root.findall("entry"):
                    article = self._extract_atom_entry(entry)
                    if article:
                        articles.append(article)
                        
        except ET.ParseError as e:
            logger.warning(f"XML parse error: {e}")
            # Fallback to regex
            return self._parse_rss_regex(content)
        
        return articles

    def _extract_rss_item(self, item) -> Optional[dict]:
        """Extract relevant fields from RSS item."""
        try:
            title_elem = item.find("title")
            link_elem = item.find("link")
            pub_elem = item.find("pubDate")
            desc_elem = item.find("description")
            
            title = ""
            if title_elem is not None and title_elem.text:
                title = self._clean_html(title_elem.text)
            
            # Skip if no title
            if not title:
                return None
            
            published = ""
            if pub_elem is not None and pub_elem.text:
                published = self._parse_date(pub_elem.text)
            
            # Get description for additional context
            description = ""
            if desc_elem is not None and desc_elem.text:
                description = self._clean_html(desc_elem.text)
            
            return {
                "title": title,
                "description": description,
                "published": published,
                "source": "rss"
            }
        except Exception:
            return None

    def _extract_atom_entry(self, entry) -> Optional[dict]:
        """Extract relevant fields from Atom entry."""
        try:
            title_elem = entry.find("{http://www.w3.org/2005/atom}title")
            link_elem = entry.find("{http://www.w3.org/2005/atom}link")
            pub_elem = entry.find("{http://www.w3.org/2005/atom}published")
            
            title = ""
            if title_elem is not None and title_elem.text:
                title = self._clean_html(title_elem.text)
            
            if not title:
                return None
            
            published = ""
            if pub_elem is not None and pub_elem.text:
                published = pub_elem.text[:10]  # YYYY-MM-DD
            
            return {
                "title": title,
                "description": "",
                "published": published,
                "source": "atom"
            }
        except Exception:
            return None

    def _parse_rss_regex(self, content: str) -> list[dict]:
        """Fallback regex parsing for RSS."""
        articles = []
        
        # Match item blocks
        pattern = r"<item[^>]*>(.*?)</item>"
        items = re.findall(pattern, content, re.DOTALL)
        
        for item in items[:20]:
            title_match = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", item)
            if not title_match:
                title_match = re.search(r"<title>([^<]+)</title>", item)
            
            if title_match:
                articles.append({
                    "title": self._clean_html(title_match.group(1)),
                    "description": "",
                    "published": "",
                    "source": "rss"
                })
        
        return articles

    def _parse_json_feed(self, content: str) -> list[dict]:
        """Parse JSON format feed (Cryptopanic)."""
        try:
            import json
            data = json.loads(content)
            results = data.get("results", [])
            
            articles = []
            for item in results[:20]:
                title = item.get("title", "")
                if title:
                    articles.append({
                        "title": self._clean_html(title),
                        "description": "",
                        "published": item.get("created_at", ""),
                        "source": "cryptopanic"
                    })
            return articles
        except Exception:
            return []

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags and clean text."""
        if not text:
            return ""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode HTML entities
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&#39;", "'")
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _parse_date(self, date_str: str) -> str:
        """Parse various date formats to ISO."""
        try:
            # RFC 2822 format (common in RSS)
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            # Try common patterns
            for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    return datetime.strptime(date_str[:len(fmt)], fmt).strftime("%Y-%m-%d")
                except:
                    pass
            return ""

    def calculate_sentiment(self, articles: list[dict]) -> float:
        """
        Calculate weighted sentiment score from articles.
        
        Args:
            articles: List of article dictionaries
            
        Returns:
            Float between 0 (bearish) and 1 (bullish)
        """
        if not articles:
            return 0.5
        
        bullish_score = 0.0
        bearish_score = 0.0
        
        # Recency weight - articles from last 24h get 2x weight
        now = datetime.now()
        
        for article in articles:
            title = article.get("title", "").lower()
            description = article.get("description", "").lower()
            text = f"{title} {description}"
            
            # Calculate recency weight
            recency_weight = 1.0
            published = article.get("published", "")
            if published:
                try:
                    article_date = datetime.fromisoformat(published[:10])
                    hours_ago = (now - article_date).total_seconds() / 3600
                    if hours_ago < 24:
                        recency_weight = 2.0
                    elif hours_ago < 48:
                        recency_weight = 1.5
                    elif hours_ago > 168:  # > 7 days
                        recency_weight = 0.5
                except Exception:
                    pass
            
            # Check for keyword matches with stemming
            for keyword, weight in BULLISH_KEYWORDS.items():
                if keyword in text:
                    bullish_score += weight * recency_weight
                    break  # One match per article per category
            
            for keyword, weight in BEARISH_KEYWORDS.items():
                if keyword in text:
                    bearish_score += weight * recency_weight
                    break
        
        total = bullish_score + bearish_score
        
        if total == 0:
            return 0.5
        
        # Normalize to 0-1 range
        score = bullish_score / total
        
        # Adjust toward 0.5 if few mentions
        mention_count = min(bullish_score + bearish_score, 5)
        if mention_count < 3:
            score = 0.5 + (score - 0.5) * (mention_count / 3)
        
        return max(0.0, min(1.0, score))

    async def get_news_sentiment(self, coin: str, use_cache: bool = True) -> float:
        """
        Get combined news sentiment for a coin.
        
        Args:
            coin: Coin symbol (BTC, ETH, etc.)
            use_cache: Whether to use cached results
            
        Returns:
            Float between 0 and 1
        """
        # Check cache
        if use_cache and self._is_cache_valid("sentiment"):
            cached_sentiment, _ = self._cache["sentiment"]
            logger.debug(f"Using cached sentiment: {cached_sentiment}")
            return cached_sentiment
        
        all_articles = []
        
        # Fetch all feeds
        tasks = [self.fetch_feed(url) for url, _ in RSS_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_articles.extend(result)
        
        # Filter for coin-relevant articles
        coin_pattern = re.compile(coin, re.IGNORECASE)
        relevant = [
            a for a in all_articles 
            if coin_pattern.search(a.get("title", ""))
        ]
        
        # Use relevant if found, otherwise use all
        articles_to_analyze = relevant if relevant else all_articles[:30]
        
        sentiment = self.calculate_sentiment(articles_to_analyze)
        
        # Cache result
        self._cache["sentiment"] = (sentiment, datetime.now().timestamp())
        
        # Log top headlines for transparency
        if articles_to_analyze:
            top_titles = [a.get("title", "")[:50] for a in articles_to_analyze[:3]]
            logger.info(f"Sentiment for {coin}: {sentiment:.2f} ({len(articles_to_analyze)} articles): {top_titles}")
        
        return sentiment

    def invalidate_cache(self) -> None:
        """Manually invalidate the sentiment cache."""
        self._cache = {"sentiment": (None, 0), "articles": (None, 0)}


# Global instance
_rss_fetcher: Optional[RSSFetcher] = None


def get_rss_fetcher() -> RSSFetcher:
    """Get or create RSS fetcher instance."""
    global _rss_fetcher
    if _rss_fetcher is None:
        _rss_fetcher = RSSFetcher()
    return _rss_fetcher


async def get_hybrid_sentiment(symbol: str, groq_sentiment: float, use_cache: bool = True) -> float:
    """
    Combine Groq AI sentiment with RSS news sentiment.
    
    Args:
        symbol: Trading pair (e.g., "BTC/USDT")
        groq_sentiment: Groq AI sentiment score
        use_cache: Whether to cache RSS results
        
    Returns:
        Weighted average sentiment
    """
    coin = symbol.split("/")[0]
    
    # Get news sentiment with caching
    try:
        rss = get_rss_fetcher()
        news_sentiment = await rss.get_news_sentiment(coin, use_cache=use_cache)
    except Exception as e:
        logger.debug(f"RSS sentiment failed: {e}")
        news_sentiment = 0.5
    
    # Weighted average: 70% Groq, 30% News
    hybrid = (groq_sentiment * 0.7) + (news_sentiment * 0.3)
    
    logger.info(f"Hybrid sentiment {symbol}: Groq={groq_sentiment:.2f}, News={news_sentiment:.2f} -> {hybrid:.2f}")
    
    return hybrid