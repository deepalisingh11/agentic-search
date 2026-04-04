"""
Simple file-based JSON cache with TTL.
No external dependencies — just stdlib + pathlib.
"""
from __future__ import annotations
import hashlib
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_TTL_SECONDS = 3600  # 1 hour


def _cache_key(query: str, max_results: int, custom_columns: list[str]) -> str:
    raw = f"{query.lower().strip()}|{max_results}|{','.join(sorted(custom_columns))}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def get_cached(query: str, max_results: int, custom_columns: list[str]) -> dict | None:
    key = _cache_key(query, max_results, custom_columns)
    path = _cache_path(key)

    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
        age = time.time() - data.get("_cached_at", 0)
        if age > CACHE_TTL_SECONDS:
            path.unlink(missing_ok=True)
            logger.info(f"Cache expired for '{query}'")
            return None
        logger.info(f"Cache hit for '{query}' (age {int(age)}s)")
        return data["result"]
    except Exception as e:
        logger.warning(f"Cache read error: {e}")
        return None


def set_cached(query: str, max_results: int, custom_columns: list[str], result: dict) -> None:
    key = _cache_key(query, max_results, custom_columns)
    path = _cache_path(key)
    try:
        path.write_text(json.dumps({"_cached_at": time.time(), "result": result}))
        logger.info(f"Cached result for '{query}'")
    except Exception as e:
        logger.warning(f"Cache write error: {e}")
