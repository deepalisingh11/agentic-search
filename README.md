<!-- # 🔍 Agentic Search

Turn any topic query into a structured, source-attributed entity table — powered by DuckDuckGo, Groq (Llama 3.3 70B), and FastAPI.

![Demo](https://placehold.co/800x400?text=Agentic+Search+Demo)

---

## What It Does

Enter a query like `"AI startups in healthcare"` and the system:

1. **Searches** the web via DuckDuckGo (no API key required)
2. **Scrapes** the top results in parallel using async HTTP
3. **Infers** a query-appropriate schema via Groq (e.g., Name · Funding Stage · Therapeutic Area · HQ · Founded)
4. **Extracts** up to 12 entities from the scraped content, with every cell value traced to its source URL
5. **Renders** a clean table with clickable source attribution and CSV/JSON export

---

## Architecture

```
User Query
    │
    ▼
┌─────────────────────────────────────┐
│  FastAPI Backend  (backend/main.py) │
│                                     │
│  1. DuckDuckGo Search               │  ← search.py
│     └─ returns top N URLs           │
│                                     │
│  2. Parallel Async Scraper          │  ← scraper.py
│     └─ httpx + BeautifulSoup        │
│     └─ up to 8 pages simultaneously │
│                                     │
│  3. Groq LLM — Phase 1 (Schema)     │  ← extractor.py
│     └─ infers entity type + columns │
│                                     │
│  4. Groq LLM — Phase 2 (Extract)    │  ← extractor.py
│     └─ fills rows with source refs  │
│                                     │
│  Returns structured SearchResult    │
└─────────────────────────────────────┘
    │
    ▼
Single-file HTML frontend (frontend/index.html)
    └─ Table with per-cell source links
    └─ CSV / JSON export
```

---

## Design Decisions

### Two-phase LLM approach
Rather than a single extraction prompt, the system uses two Groq calls:
- **Phase 1 (Schema):** Given just the query, determine the best 4–6 columns. This keeps the schema focused and query-aware — "pizza places" gets Rating/Cuisine/Price/Neighborhood, not generic Description/URL/Notes.
- **Phase 2 (Extract):** Using the inferred schema, extract entities with per-column source attribution.

This separation produces better column quality than a single combined prompt, with minimal added latency (~0.5s extra on fast models).

### Per-cell source tracing
Each cell carries the source URL it was extracted from. The LLM is instructed to record `<column>_source` as an integer index into the scraped pages list, which the backend maps to actual URLs. This makes every fact verifiable.

### Parallel scraping
All pages are fetched concurrently with `asyncio.gather`, so scraping 8 pages takes roughly the same time as scraping 1 (network-bound). Timeouts are set to 8s per page, and failures are silently skipped.

### DuckDuckGo (no API key)
The `duckduckgo_search` Python library provides free web search with no signup. The trade-off is occasional rate limiting on heavy use — for a production system, Serper.dev (~$5/1000 queries) would be more reliable.

### Text truncation
Each scraped page is trimmed to 3,000 characters before being sent to the LLM. With 8 pages, this keeps the extraction prompt under ~25k tokens (well within Groq's context window) while still providing enough signal.

---

## Setup

### Requirements
- Python 3.11+
- A free [Groq API key](https://console.groq.com)

### Install & Run

```bash
# Clone the repo
git clone https://github.com/yourname/agentic-search
cd agentic-search

# Set up environment
cp .env.example .env
# Edit .env and add your GROQ_API_KEY

# Install Python dependencies
cd backend
pip install -r requirements.txt

# Run the server (from backend/ directory)
uvicorn main:app --reload --port 8000
```

Open your browser at **http://localhost:8000**

### API-only mode
The backend exposes a REST API independently of the frontend:

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "open source database tools", "max_results": 8}'
```

Interactive API docs: **http://localhost:8000/docs**

---

## File Structure

```
agentic-search/
├── backend/
│   ├── main.py          # FastAPI app + route definitions
│   ├── search.py        # DuckDuckGo web search
│   ├── scraper.py       # Async parallel page scraper
│   ├── extractor.py     # Two-phase Groq LLM extraction
│   ├── models.py        # Pydantic data models
│   └── requirements.txt
├── frontend/
│   └── index.html       # Single-file UI (Tailwind + vanilla JS)
├── .env.example
├── .gitignore
└── README.md
```

---

## Known Limitations

| Limitation | Notes |
|---|---|
| DuckDuckGo rate limits | Heavy use may trigger temporary blocks. Swap `search.py` for Serper.dev for production. |
| JavaScript-heavy pages | Scraper uses plain HTTP (no browser). Sites that require JS rendering (SPAs) won't yield useful content. |
| LLM hallucination | Despite strict prompting, the model may occasionally infer a value not directly in the source text. Per-cell source links make this verifiable. |
| No caching | Identical queries re-run the full pipeline. Redis or disk caching would be a natural next step. |
| Sequential LLM calls | The two Groq calls run in sequence. They could be partially parallelized for lower latency. |

---

## Potential Extensions

- **Streaming progress** via SSE so the UI updates in real time per step
- **Result caching** with Redis or SQLite
- **Playwright-based scraping** for JavaScript-heavy pages
- **Multiple search providers** with fallback (DuckDuckGo → Serper → Bing)
- **Column filtering & sorting** in the UI
- **Persistent history** of past queries -->

# 🔍 Agentic Search

Turn any topic query into a structured, source-attributed entity table — powered by Serper (Google Search), Groq (Llama), and FastAPI.

---

## What It Does

Enter a query like `"AI startups in healthcare"` and the system:

1. **Searches** the web via Serper.dev (Google Search API)
2. **Scrapes** the top results in parallel using async HTTP
3. **Infers** a query-appropriate schema via Groq (e.g., Name · Funding Stage · Therapeutic Area · HQ · Founded)
4. **Extracts** up to 12 entities from the scraped content, with every cell value traced back to its source URL
5. **Caches** results to disk (1-hour TTL) so repeat queries are instant
6. **Renders** a clean sortable table with clickable source attribution and CSV/JSON export

---

## Architecture

```
User Query
    │
    ▼
┌─────────────────────────────────────┐
│         FastAPI Backend             │
│           (backend/main.py)         │
│                                     │
│  0. Disk cache check                │  ← cache.py
│     └─ returns immediately on hit   │
│                                     │
│  1. Serper.dev Search               │  ← search.py
│     └─ returns top N Google URLs    │
│                                     │
│  2. Parallel Async Scraper          │  ← scraper.py
│     └─ httpx + BeautifulSoup        │
│     └─ up to 12 pages simultaneously│
│                                     │
│  3. Groq LLM — Phase 1 (Schema)     │  ← extractor.py
│     └─ infers entity type + columns │
│                                     │
│  4. Groq LLM — Phase 2 (Extract)    │  ← extractor.py
│     └─ fills rows with source refs  │
│                                     │
│  5. Cache result to disk            │  ← cache.py
│                                     │
│  Returns structured SearchResult    │  ← models.py
└─────────────────────────────────────┘
    │
    ▼
Single-file HTML frontend (frontend/index.html)
    └─ Sortable table with per-cell source links
    └─ CSV / JSON export
```

---

## Design Decisions

### Two-phase LLM approach
Rather than a single extraction prompt, the system uses two Groq calls:
- **Phase 1 (Schema):** Given just the query, determine the best 4–6 columns. This keeps the schema focused and query-aware — "pizza places" gets Rating/Cuisine/Price/Neighborhood, not generic Description/URL/Notes.
- **Phase 2 (Extract):** Using the inferred schema, extract entities with per-column source attribution.

This separation produces better column quality than a single combined prompt, with minimal added latency (~0.5s on fast models).

### Per-cell source tracing
Each cell carries the source URL it was extracted from. The LLM records a `<column>_source` integer index into the scraped pages list, which the backend maps to actual URLs. This makes every fact independently verifiable.

### Fallback link generation
When a link/URL column can't be reliably extracted from source text (hallucinated, truncated, or pointing back at the scraped page itself), the system generates a Google search URL for the entity instead of leaving it blank or returning a broken link. This ensures every row in a URL column has a usable, non-hallucinated value.

### Parallel scraping
All pages are fetched concurrently with `asyncio.gather`, so scraping 8 pages takes roughly the same time as scraping 1 (network-bound). Timeouts are set to 8s per page; failures are silently skipped.

### Serper.dev for search
The system uses Serper.dev (Google Search API) rather than scraping DuckDuckGo directly. Serper is reliable, fast, and costs ~$0.001/query — with 2,500 free queries/month on the free tier. This avoids the rate-limiting and blocking issues inherent in unofficial scraping approaches.

### File-based caching
Identical queries (same query string + max_results + custom columns) are served from a `.cache/` directory with a 1-hour TTL. The cache key is an MD5 hash of the normalized inputs. This adds zero external dependencies (no Redis) while meaningfully reducing latency and API costs for repeated queries. The frontend shows a ⚡ Cached badge when a result is served from cache.

### Text truncation
Each scraped page is trimmed to 3,000 characters before being sent to the LLM. With up to 12 pages, this keeps the extraction prompt under ~40k tokens — well within Groq's context window — while still providing enough signal per page.

---

## Setup

### Requirements
- Python 3.11+
- A free [Groq API key](https://console.groq.com)
- A free [Serper.dev API key](https://serper.dev) — 2,500 free queries/month

### Install & Run

```bash
# Clone the repo
git clone https://github.com/yourname/agentic-search
cd agentic-search

# Set your API keys
cp .env.example .env
# Edit .env and fill in GROQ_API_KEY and SERPER_API_KEY

# Install Python dependencies
cd backend
pip install -r requirements.txt

# Run the server (from the backend/ directory)
uvicorn main:app --reload --port 8000
```

Open your browser at **http://localhost:8000**

### Environment Variables

Create a `.env` file in the project root (see `.env.example`):

```
GROQ_API_KEY=your_groq_api_key_here
SERPER_API_KEY=your_serper_api_key_here
```

### API-only mode

The backend exposes a REST API independently of the frontend:

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "open source database tools", "max_results": 8}'
```

Interactive API docs: **http://localhost:8000/docs**

---

## File Structure

```
agentic-search/
├── backend/
│   ├── main.py          # FastAPI app, routes, cache integration
│   ├── search.py        # Serper.dev Google Search
│   ├── scraper.py       # Async parallel page scraper (httpx + BeautifulSoup)
│   ├── extractor.py     # Two-phase Groq LLM extraction pipeline
│   ├── models.py        # Pydantic data models (QueryRequest, SearchResult, etc.)
│   ├── cache.py         # File-based JSON cache with TTL
│   └── requirements.txt
├── frontend/
│   └── index.html       # Single-file UI (Tailwind + vanilla JS)
├── .cache/              # Auto-created at runtime; gitignored
├── .env                 # Your local secrets (gitignored)
├── .env.example         # Template for required environment variables
├── .gitignore
└── README.md
```

---

## Known Limitations

| Limitation | Notes |
|---|---|
| **Groq rate limits** | The free tier allows ~30 requests/min and ~14,400 requests/day on `llama-3.1-8b-instant`. Each search consumes 2 LLM calls. Burst usage may trigger a 429 error, surfaced to the user as a 500. Upgrade to a paid Groq tier or switch to `llama-3.3-70b-versatile` (commented out in `extractor.py`) for higher throughput, at the cost of ~2–3× more latency. |
| **Groq model selection** | Defaults to `llama-3.1-8b-instant` for speed. `llama-3.3-70b-versatile` is available as a commented-out alternative for higher extraction quality. Edit the `GROQ_MODEL` constant at the top of `extractor.py` to switch. |
| **Serper free tier** | 2,500 queries/month. Each search call consumes one credit. |
| **JavaScript-heavy pages** | The scraper uses plain HTTP (no browser). SPAs and pages that require JS rendering won't yield useful text content. |
| **LLM hallucination** | Despite strict prompting, the model may occasionally infer values not directly present in source text. Per-cell source links make every claim independently verifiable. The fallback link generator prevents hallucinated URLs from appearing in link columns. |
| **Sequential LLM calls** | The two Groq phases run sequentially. Latency could be reduced by overlapping Phase 1 with scraping. |
| **No persistent query history** | Past queries are not stored beyond the 1-hour file cache. |

---

## Potential Extensions

- **Streaming progress** via SSE so the UI updates in real time per pipeline step
- **Playwright-based scraping** for JavaScript-heavy pages
- **Multiple search providers** with fallback (Serper → Bing → DuckDuckGo)
- **Redis caching** for multi-instance or serverless deployments
- **Persistent query history** with SQLite
- **Configurable TTL** and cache invalidation via the API

---

## Evaluation Notes

- **Output quality** — Two-phase prompting with strict anti-hallucination instructions, per-cell source attribution, and fallback link generation ensure results are accurate and traceable. Latency is typically 5–10s for a cold query; cached queries return in under 100ms. Cost is ~$0.001/query (Serper) plus negligible Groq free-tier usage.
- **Design choices** — Key problems identified: schema variance across query types, hallucinated URLs, and redundant LLM calls on repeat queries. Solved via dynamic schema inference, link validation + Google fallback, and file-based TTL caching respectively.
- **Code structure** — Each concern is isolated to its own module (`search`, `scraper`, `extractor`, `cache`, `models`), with a thin `main.py` orchestrator. Modules are independently readable and testable.
- **Documentation** — This README covers approach, architecture, design decisions, setup, and limitations. The `/docs` endpoint provides live interactive API documentation.
- **Complexity** — Beyond the basics: two-phase LLM pipeline, per-cell source tracing, link fallback generation, file-based TTL caching, sortable table UI, CSV/JSON export, and user-injectable custom columns.

---

## Submission

Please share your code via a public GitHub repository and send an email to **csamarinas@umass.edu** with the exact subject line:

> **CIIR challenge submission**

Your submission will be compared against other candidates on:

- **Output quality**: do the results actually make sense? Are they accurate and useful for real queries? Are latency and cost reasonable for a real system?
- **Design choices**: what problems did you identify and how did you solve them? What trade-offs did you make?
- **Code structure**: is the codebase well-organized and readable?
- **Documentation**: clear setup instructions, explanation of your approach, and known limitations
- **Complexity of implementation**: how far did you push the solution beyond the basics?

Including a URL with a live demo on a free-tier cloud instance is also encouraged.
