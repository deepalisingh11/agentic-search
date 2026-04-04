from __future__ import annotations
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from cache import get_cached, set_cached
from extractor import extract_entities
from models import QueryRequest, SearchResult
from scraper import scrape_pages
from search import search_web

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agentic Search",
    description="Turn any topic query into a structured, source-attributed entity table.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/search", response_model=SearchResult)
async def run_search(req: QueryRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # Check cache first
    cached = get_cached(req.query, req.max_results, req.custom_columns)
    if cached:
        result = SearchResult(**cached)
        result.from_cache = True
        return result

    logger.info(f"Query: '{req.query}' | max_results={req.max_results} | custom_cols={req.custom_columns}")

    urls = await search_web(req.query, req.max_results)
    if not urls:
        raise HTTPException(status_code=502, detail="Search returned no results. Try a different query.")

    pages = await scrape_pages(urls)
    if not pages:
        raise HTTPException(status_code=502, detail="Could not scrape any pages. Try again.")

    try:
        result = await extract_entities(req.query, pages, req.custom_columns)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="LLM extraction failed. Check your GROQ_API_KEY.")

    # Cache the result
    set_cached(req.query, req.max_results, req.custom_columns, result.model_dump())

    logger.info(f"Done: {len(result.rows)} entities, {len(result.columns)} columns")
    return result


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
