import asyncio
import logging

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Max characters of text to keep per page (to stay within LLM context)
MAX_PAGE_CHARS = 3000


def _extract_text(html: str) -> str:
    """Strip boilerplate and return clean body text."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise tags
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    # Collapse whitespace
    text = " ".join(text.split())
    return text[:MAX_PAGE_CHARS]


async def _scrape_one(client: httpx.AsyncClient, url: str) -> dict:
    try:
        response = await client.get(url, timeout=8.0, follow_redirects=True)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return {"url": url, "text": "", "error": "Not HTML"}

        text = _extract_text(response.text)
        if not text:
            return {"url": url, "text": "", "error": "Empty content"}

        logger.debug(f"Scraped {url}: {len(text)} chars")
        return {"url": url, "text": text}

    except httpx.TimeoutException:
        logger.warning(f"Timeout scraping {url}")
        return {"url": url, "text": "", "error": "Timeout"}
    except Exception as e:
        logger.warning(f"Error scraping {url}: {e}")
        return {"url": url, "text": "", "error": str(e)}


async def scrape_pages(urls: list[str]) -> list[dict]:
    """Scrape all URLs in parallel and return pages with content."""
    async with httpx.AsyncClient(headers=HEADERS) as client:
        tasks = [_scrape_one(client, url) for url in urls]
        results = await asyncio.gather(*tasks)

    successful = [r for r in results if r.get("text")]
    logger.info(f"Scraped {len(successful)}/{len(urls)} pages successfully")
    return successful
