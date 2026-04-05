# 🔍 Agentic Search

Turn any topic query into a structured, source-attributed entity table — powered by Serper (Google Search), Groq (Llama), and FastAPI.

**Live demo:** [https://agentic-search-47fh.onrender.com](https://agentic-search-47fh.onrender.com)

---

## What It Does

Enter a query like `"Python Frameworks comparision"` and the system:

1. **Searches** the web via Serper.dev (Google Search API)
2. **Scrapes** the top results in parallel using async HTTP
3. **Infers** a query-appropriate schema via LLM (e.g., Framework Name · Community Size · Latest Version · Database Support)
4. **Extracts** up to 12 entities from scraped content, with every cell traced to its source URL
5. **Caches** results to disk (1-hour TTL) so repeat queries return instantly
6. **Renders** a sortable table with clickable source attribution, CSV/JSON export, and custom columns

---

## Architecture

```
User Query
    │
    ▼
┌─────────────────────────────────────┐
│         FastAPI Backend             │
│                                     │
│  0. Disk cache check                │  ← cache.py
│  1. Serper.dev Search               │  ← search.py
│  2. Parallel Async Scraper          │  ← scraper.py
│  3. Groq LLM — Phase 1 (Schema)     │  ← extractor.py
│  4. Groq LLM — Phase 2 (Extract)    │  ← extractor.py
│  5. Cache result to disk            │  ← cache.py
│                                     │
│  Returns structured SearchResult    │  ← models.py
└─────────────────────────────────────┘
    │
    ▼
Single-file HTML frontend (frontend/index.html)
```

---

## Features

- **Dynamic schema inference:** columns are query-aware ("pizza places" gets Rating/Price/Neighborhood, not generic Description/Notes)
- **Per-cell source tracing:** every value links back to the page it came from
- **Custom columns:** inject any extra column via the UI (e.g., "Founded Year", "Product Link")
- **Fallback link generation:** when a URL can't be reliably extracted, a Google search link is generated instead of leaving a blank or hallucinated value
- **Parallel scraping:** all pages fetched concurrently; scraping 8 pages takes the same wall-clock time as 1
- **File-based caching:** MD5-keyed `.cache/` directory with 1-hour TTL; zero external dependencies
- **Sortable table UI:** click any column header to sort; cached results show a ⚡ badge
- **CSV / JSON export:** one-click download of full results
- **Model toggle:** switch between Fast (Llama-3.1-8B) and Smart (Llama-3.3-70B) directly from the UI

---

## Design Decisions

**Two-phase LLM pipeline.** Phase 1 infers the best 4–6 columns for the query type. Phase 2 extracts entities using that schema with per-column source attribution. Separating these produces better column quality than a single combined prompt, at ~0.5s extra latency.

**Serper.dev over DIY scraping.** Reliable, fast, and ~$0.001/query with 2,500 free queries/month. Avoids the rate-limiting and blocking issues of unofficial scraping approaches.

**Text truncation at 3,000 chars/page.** With up to 12 pages, the extraction prompt stays under ~40k tokens, well within Groq's context window, while still providing enough signal per page.

**File-based TTL cache.** Identical queries (same query + max_results + custom columns) are served from disk with no extra infrastructure. The cache key is an MD5 hash of normalized inputs.

---

## Setup

### Requirements

- Python 3.9+
- [Groq API key](https://console.groq.com) (free)
- [Serper.dev API key](https://serper.dev) (free 2,500 queries/month)

### Environment Variables

Create a `.env` file in the project root (see `.env.example`):

```
GROQ_API_KEY=your_groq_api_key_here
SERPER_API_KEY=your_serper_api_key_here
```

### Local Run

```bash
# 1. Clone the repo
git clone https://github.com/yourname/agentic-search
cd agentic-search

# 2. Create and activate a virtual environment
python3.9 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Set API keys
cp .env.example .env
# Edit .env and fill in GROQ_API_KEY and SERPER_API_KEY

# 4. Install dependencies
cd backend
pip install -r requirements.txt

# 5. Start the server
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

### API-only mode

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "open source database tools", "max_results": 8}'
```

Interactive API docs: **http://localhost:8000/docs**

---

## Deployment (Render)

The repo includes a `render.yaml` for one-click deployment to [Render](https://render.com).

1. Push the repo to GitHub
2. Connect the repo in Render → New Web Service
3. Render auto-detects `render.yaml` and configures the build
4. Add `GROQ_API_KEY` and `SERPER_API_KEY` as environment variables in the Render dashboard
5. Deploy: the service starts at your Render URL

**Live demo:** [https://agentic-search-47fh.onrender.com](https://agentic-search-47fh.onrender.com)

---

## File Structure

```
agentic-search/
├── backend/
│   ├── main.py          # FastAPI app, routes, cache integration
│   ├── search.py        # Serper.dev Google Search
│   ├── scraper.py       # Async parallel scraper (httpx + BeautifulSoup)
│   ├── extractor.py     # Two-phase Groq LLM extraction pipeline
│   ├── models.py        # Pydantic data models
│   ├── cache.py         # File-based JSON cache with TTL
│   └── requirements.txt
├── frontend/
│   └── index.html       # Single-file UI (Tailwind + vanilla JS)
├── .cache/              # Auto-created at runtime (gitignored)
├── .env                 # Local secrets (gitignored)
├── .env.example
├── render.yaml
└── README.md
```

---

## Known Limitations

**Groq token limits.** Groq's free tier enforces both per-minute (TPM/RPM) and daily (TPD) token limits. Each search consumes 2 LLM calls. Heavy use can trigger a 429 rate-limit error, which the backend surfaces with a clear message and retries up to 3 times with backoff.

**Model toggle as a workaround.** The UI exposes a ⚡ Fast / 🧠 Smart toggle:
- **Fast (8B) `llama-3.1-8b-instant`**: lower latency (~3–5s), higher TPM allowance, recommended for most queries, but less token limit per query.  
- **Smart (70B) `llama-3.3-70b-versatile`**: better extraction quality on complex queries, but uses more daily tokens and is ~2–3× slower.

If you hit a daily token limit on 70B, switch to Fast (8B) mode. If you hit a per-minute limit, wait ~60s and retry: the backend is designed to surface the estimated wait time from Groq's error response. 

**Request size limits.** Sending too many sources (12+) with large pages can exceed Groq's per-request token cap for even the 8B model. Reduce "Sources to search" in the UI or switch to 70B (which has a larger per-request limit).

**JavaScript-heavy pages.** The scraper uses plain HTTP, no headless browser. SPAs that require JS rendering won't yield useful content.

**LLM hallucination.** Despite strict prompting, the model may occasionally infer values that are not verbatim present in the source text. Per-cell source links make every claim independently verifiable. Hallucinated URLs are caught and replaced with a Google fallback search link. This is handled in most cases, but please note that in some cases, the model still returns a fake URL that does not exist. 

**Serper free tier.** 2,500 queries/month. Each search call uses one credit.

## Possible Extensions

- **Embedding-based RAG router:** replace keyword scoring with local sentence-transformer embeddings for better section selection
- **Critic agent:** hallucination detection and relevance scoring, already built
- **Query decomposition:** break complex queries like "funded AI startups in healthcare founded after 2020" into sub-queries, run them independently, merge results
- **Persistent cache:** move from FAISS on disk to a hosted vector database (Pinecone, Qdrant free tier) for cache that survives deploys
- **User feedback loop:** thumbs up/down per entity to flag bad extractions and improve cache quality over time
- **Iterative refinement:** after seeing initial results, generate follow-up queries specifically targeting the entities found to fill their missing fields
- **Negative filtering:** let users specify what to exclude ("no aggregator sites", "no listicles") and inject that into query generation
- **Entity-driven querying:** once an entity is found, automatically search for it directly by name to get its official page, not just the pages that mention it
- **Streaming extraction:** yield entities to the frontend as they are found rather than waiting for the full batch
- **Playwright integration:** headless browser scraping for JS-rendered pages (Crunchbase, LinkedIn)
