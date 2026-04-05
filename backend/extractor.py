"""
Two-phase extraction pipeline.

Phase 1: Schema inference (query → entity type + columns)
Phase 2: Entity extraction (pages → structured rows with source attribution)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse

from groq import Groq, APIStatusError, RateLimitError

from models import CellValue, EntityRow, SearchResult

logger = logging.getLogger(__name__)

GROQ_MODEL_FAST = "llama-3.1-8b-instant"
GROQ_MODEL_SMART = "llama-3.3-70b-versatile"

def _get_client() -> Groq:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set")
    return Groq(api_key=api_key)

def _groq_call(client: Groq, *, model: str, messages: list, temperature: float, max_tokens: int) -> str:
    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content

        except RateLimitError as e:
            # Parse the "try again in Xm Ys" hint from the error message if present
            err_msg = str(e)
            wait_hint = ""
            match = re.search(r"try again in ([\dm\s\.]+s)", err_msg, re.IGNORECASE)
            if match:
                wait_hint = f" Groq says: try again in {match.group(1)}."

            # Daily token limit (TPD) — retrying immediately won't help
            if "tokens per day" in err_msg or "TPD" in err_msg:
                is_smart = "70b" in model.lower() or "versatile" in model.lower()
                suggestion = " Try switching to ⚡ Fast (8B) mode above." if is_smart else " Consider upgrading your Groq plan."
                raise ValueError(
                    f"Daily token limit reached for model '{model}'.{wait_hint}{suggestion}"
                ) from e

            # Per-minute limit (TPM/RPM) — back off and retry
            wait = 20 * (attempt + 1)
            logger.warning(f"Groq rate-limited (attempt {attempt+1}/{MAX_RETRIES}). Waiting {wait}s...")
            time.sleep(wait)
            continue

        except APIStatusError as e:
            code = e.status_code
            err_type = e.body.get("error", {}).get("type", "") if isinstance(e.body, dict) else ""
            err_msg  = e.body.get("error", {}).get("message", str(e)) if isinstance(e.body, dict) else str(e)

            # NEW
            if code == 413 or err_type == "tokens":
                is_fast = "8b" in model.lower() or "instant" in model.lower()
                suggestion = " Or try switching to 🧠 Smart (70B), which has a larger token limit." if is_fast else " Try reducing 'Sources to search' or the query length."
                raise ValueError(
                    f"Request too large for Groq model '{model}'. "
                    f"Try reducing 'Sources to search' or the query length.{suggestion}"
                ) from e

            if code == 429:
                wait = 20 * (attempt + 1)
                logger.warning(f"Groq rate-limited (attempt {attempt+1}/{MAX_RETRIES}). Waiting {wait}s...")
                time.sleep(wait)
                continue

            raise
    raise ValueError(f"Groq rate limit persisted after {MAX_RETRIES} retries. Please wait a minute and try again.")
    
def _parse_json_response(text: str) -> dict:
    for attempt in [text, re.sub(r"```(?:json)?", "", text).strip()]:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON: {text[:300]}")


def _parse_json_array(text: str) -> list:
    text = re.sub(r"```(?:json)?", "", text).strip()
    for attempt in [text, text[text.find("["):text.rfind("]") + 1]]:
        try:
            return json.loads(attempt)
        except (json.JSONDecodeError, ValueError):
            pass
    return []


# ---------------------------------------------------------------------------
# Phase 1: Schema inference
# ---------------------------------------------------------------------------

def _infer_schema(client: Groq, query: str, custom_columns: list[str], model: str) -> dict:
    custom_hint = ""
    if custom_columns:
        custom_hint = (
            f"\nThe user has also specifically requested these extra columns "
            f"(include them verbatim): {custom_columns}"
        )

    prompt = f"""You are a data schema designer. Given a search query, decide:
1. What type of entities the results will be (e.g. "AI startups", "pizza restaurants", "open source tools")
2. The 4–6 most useful columns to capture about each entity
{custom_hint}

Query: "{query}"

Return ONLY a JSON object with no extra text:
{{
  "entity_type": "<short plural label for the entities>",
  "columns": ["<col1>", "<col2>", "<col3>", "<col4>"]
}}

Column guidelines:
- Always start with the entity name as column 1
- Choose columns a user would actually care about for this query
- Be specific: prefer "Funding Stage" over "Info", "Cuisine Type" over "Details"
- 4 columns minimum, 6 maximum (not counting any user-requested extra columns)
- Do NOT include a link or URL column"""

    raw = _groq_call(client, model=model, messages=[{"role": "user", "content": prompt}],
                     temperature=0.1, max_tokens=300)
    schema = _parse_json_response(raw)

    base_cols: list[str] = schema.get("columns", ["Name", "Description"])
    for cc in custom_columns:
        if cc not in base_cols:
            base_cols.append(cc)

    schema["columns"] = base_cols
    return schema


# ---------------------------------------------------------------------------
# Phase 2: Entity extraction
# ---------------------------------------------------------------------------

def _build_context(pages: list[dict]) -> str:
    parts = [f"[SOURCE {i+1}: {p['url']}]\n{p['text']}" for i, p in enumerate(pages)]
    return "\n\n".join(parts)


def _extract_entities(
    client: Groq,
    query: str,
    columns: list[str],
    pages: list[dict],
    model: str,
) -> list[dict]:
    context = _build_context(pages)
    cols_str = ", ".join(f'"{c}"' for c in columns)

    prompt = f"""You are a precise data extraction engine. Extract entities from web content.

Search query: "{query}"
Columns to fill: {cols_str}

Web content from multiple sources:
{context}

Instructions:
- Extract up to 12 distinct entities relevant to the query
- For each entity, fill every column with a value found VERBATIM in the sources
- For URL/link columns: only extract a URL if it appears complete and exact in the source text. A valid URL starts with https:// and ends cleanly (no truncation). 
- For each column value, record which SOURCE NUMBER it came from (integer, 1-based)
- Use "N/A" if a value is truly not found in any source
- Do NOT hallucinate — only use what the sources say
- Deduplicate: each real-world entity appears at most once

Return ONLY a JSON array:
[
  {{
    "<col>": "<value>",
    "<col>_source": <source_number or null>,
    ...repeat for all columns...
  }}
]"""

    raw = _groq_call(client, model=model, messages=[{"role": "user", "content": prompt}],
                     temperature=0.1, max_tokens=4000)
    return _parse_json_array(raw)

def _make_search_link(entity_name: str, query: str) -> str:
    """Generate a Google search URL for the entity — always valid, never hallucinated."""
    search_term = f"{entity_name} {query}"
    return f"https://www.google.com/search?q={urllib.parse.quote_plus(search_term)}"

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def extract_entities(
    query: str,
    pages: list[dict],
    custom_columns: list[str] | None = None,
    use_fast_model: bool = True,
) -> SearchResult:
    client = _get_client()
    custom_columns = custom_columns or []
    model = GROQ_MODEL_FAST if use_fast_model else GROQ_MODEL_SMART
    logger.info(f"Using model: {model}")

    # Phase 1: infer schema
    logger.info("Phase 1: inferring schema...")
    schema = _infer_schema(client, query, custom_columns, model)
    entity_type = schema.get("entity_type", "Results")
    columns = schema.get("columns", ["Name", "Description"])
    logger.info(f"Schema: {entity_type} | Columns: {columns}")

    # Phase 2: extract entities
    logger.info("Phase 2: extracting entities...")
    raw_rows = _extract_entities(client, query, columns, pages, model)

    # Build typed rows
    url_map = {i + 1: p["url"] for i, p in enumerate(pages)}
    source_urls = {p["url"] for p in pages}
    name_col = columns[0]  
    rows: list[EntityRow] = []

    for raw in raw_rows:
        cells: dict[str, CellValue] = {}
        entity_name = str(raw.get(name_col, "")).strip()

        for col in columns:
            value = raw.get(col, "N/A")

            # If a link column value is N/A, source URLs, or anything without a real path, reject it
            col_is_link = re.search(r'link|url|website|site', col, re.IGNORECASE)
            if col_is_link:
                val_str = str(value).strip()
                is_bad = (
                    val_str in ("N/A", "", "null") or
                    val_str in source_urls or
                    not val_str.startswith("http")
                )
                if is_bad and entity_name:
                    value = _make_search_link(entity_name, query)

            source_idx = raw.get(f"{col}_source")
            # fallback: if no source tagged but value exists, use source 1
            if not source_idx and str(value).strip() not in ("N/A", "", "null"):
                source_idx = 1
            source_url = url_map.get(source_idx) if source_idx else None

            cells[col] = CellValue(value=value, source_url=source_url)
        rows.append(EntityRow(cells=cells))

    return SearchResult(
        query=query,
        entity_type=entity_type,
        columns=columns,
        rows=rows,
        sources_scraped=len(pages),
        sources_used=len(pages),
    )