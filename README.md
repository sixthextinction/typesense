# A free Algolia-style search over local data

This is accompaniment for [my blog post](https://python.plainenglish.io/i-built-a-0-search-engine-on-real-web-data-no-algolia-or-elasticsearch-10be241aef3b) on using Typesense for a fully local, free, and open-source search layer over Google results (ArXiv hits fetched using SERP.)

Bright Data [SERP](https://brightdata.com/) results become a local, searchable index with [Typesense](https://typesense.org/) and a tiny Python UI. The point is not “another export”: it is a **search-driven surface** you can demo and iterate on—answer engines, internal tools, and “ask my corpus” products all start from collected web data; this repo shows one path from **collect once** to **query and reuse many times**.

## Prerequisites

- Docker (for Typesense)
- Python 3.10+
- Bright Data account: API key and a SERP-capable zone

**Working directory:** Run the commands below from `scripts/typesense` (from repo root: `cd scripts/typesense`).

## Environment

Copy `.env` from your secrets store (do not commit real keys). Variables:

| Variable | Purpose |
|----------|---------|
| `BRIGHT_DATA_API_KEY` | Bearer token for `api.brightdata.com` |
| `BRIGHT_DATA_ZONE` | Zone name for SERP requests |
| `BRIGHT_DATA_COUNTRY` | Optional country hint for routing |
| `TYPESENSE_API_KEY` | Must match the key in `docker-compose.yml` (default dev: `devtypesense`) |
| `TYPESENSE_HOST` / `TYPESENSE_PORT` / `TYPESENSE_PROTOCOL` | Optional; default `localhost`, `8108`, `http` |
| `SERVE_PORT` | Optional; default `8765` for `serve.py` |

## Run Typesense

```bash
cd scripts/typesense
docker compose up -d
```

API listens on `http://localhost:8108`.

## Install Python deps

```bash
cd scripts/typesense
pip install -r requirements.txt
```

## Ingest SERP rows

**Fresh index** (drops `serp_results` and recreates the collection, then upserts):

```bash
cd scripts/typesense
python ingest.py
```

**Append to an existing index** (creates the collection only if missing; use for multiple Bright Data runs into one index):

```bash
cd scripts/typesense
python ingest.py --append
```

**Custom queries** (repeatable `--query` and/or a file):

```bash
cd scripts/typesense
python ingest.py --append --query "site:news.ycombinator.com HN" --queries-file my_queries.txt
```

`my_queries.txt` is one query per line; lines starting with `#` and blank lines are ignored.

`--num-results` caps how many **organic** rows are kept per query after each SERP response (Google no longer reliably honors `num` in the search URL; Bright Data may strip it).

`--delay` is the pause in seconds between Bright Data requests (default `0.6`); raise it if you hit rate limits.

## Search UI

```bash
cd scripts/typesense
python serve.py
```

Open `http://127.0.0.1:8765/`. Search is proxied to Typesense so the admin API key stays off the browser. Facet chips filter by **seed query** and **domain** (Typesense `filter_by` with `&&` between conditions).

## Mini case study: shortlist papers from multiple SERP runs

**Scenario:** You are doing a **lit-review-style pass** over a topic (e.g. RAG / retrieval). Bright Data has already run several **different Google queries** (the default demo uses multiple `site:arxiv.org …` seeds). Each organic row in the index is tagged with the exact query string that produced it (`source_query` in Typesense—shown as **Seed query** in the UI).

**What works well here:**

1. **Keyword search on title/snippet** — Try terms like `memory`, `graph`, `chunk`, or `RAG`. You quickly see **which collected results** mention those angles, without opening every PDF.

2. **Seed-query chips = provenance, not “topic”** — A chip is **which SERP run** that row came from (which seed string was sent to Google), not a semantic label for the paper. Clicking a chip means: *among my current search hits, only rows collected under that seed.*

3. **Comparing seeds** — Run the same search (e.g. `RAG`), then filter by **one seed** (e.g. long-context vs RAG) and **another** (e.g. agentic RAG). You get **different shortlists** because each seed asked Google a different question; overlap is not guaranteed.

4. **Domain chip** — Optionally narrow to one host (e.g. `arxiv.org`) when your index mixes domains.

**Limit:** This is **navigation over SERP metadata** (title, snippet, URL, provenance). It does **not** replace full-text search inside PDFs.

## Files

| File | Role |
|------|------|
| `bright_data_serp.py` | Minimal Bright Data Request API client for Google JSON SERP |
| `requirements.txt` | Python dependencies |
| `ingest.py` | Fetch organic results, map to documents, JSONL upsert |
| `serve.py` | Static UI + `/api/search` |
| `static/index.html` | Demo UI |
| `docker-compose.yml` | Local Typesense |
