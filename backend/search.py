import asyncio
import logging
import os
import httpx

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"


async def search_web(query: str, max_results: int = 8) -> list[str]:
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        raise ValueError("SERPER_API_KEY not set in .env")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            SERPER_URL,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

    urls = [r["link"] for r in data.get("organic", []) if r.get("link")]
    logger.info(f"Search '{query}' returned {len(urls)} URLs")
    return urls