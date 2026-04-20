
# Fetches Google SERP via Bright Data THEN indexes organic results into Typesense.
# Use --append to upsert into an existing index. 
# Use --query and/or --queries-file to override the built-in demo query list.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import typesense
from dotenv import load_dotenv
from typesense.exceptions import ObjectNotFound

from bright_data_serp import BrightDataSERPClient

load_dotenv()

COLLECTION = "serp_results"

# Some obvious "RAG and retrieval" topics
DEFAULT_QUERIES = [
    "site:arxiv.org retrieval augmented generation 2026",
    "site:arxiv.org hybrid search reranking 2026",
    "site:arxiv.org agentic RAG 2026",
    "site:arxiv.org long context vs RAG 2026",
]


def typesense_client() -> typesense.Client:
    return typesense.Client(
        {
            "nodes": [
                {
                    "host": os.getenv("TYPESENSE_HOST", "localhost"),
                    "port": os.getenv("TYPESENSE_PORT", "8108"),
                    "protocol": os.getenv("TYPESENSE_PROTOCOL", "http"),
                }
            ],
            "api_key": os.environ["TYPESENSE_API_KEY"],
            "connection_timeout_seconds": 30,
        }
    )


def collection_schema() -> Dict[str, Any]:
    return {
        "name": COLLECTION,
        "fields": [
            {"name": "title", "type": "string"},
            {"name": "url", "type": "string"},
            {"name": "snippet", "type": "string", "optional": True},
            {"name": "source_query", "type": "string", "facet": True},
            {"name": "domain", "type": "string", "facet": True},
            {"name": "position", "type": "int32"},
        ],
        "default_sorting_field": "position",
    }


def organic_to_documents(
    data: Dict[str, Any], source_query: str
) -> List[Dict[str, Any]]:
    organic = data.get("organic")
    if not isinstance(organic, list):
        return []
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(organic):
        if not isinstance(row, dict):
            continue
        url = row.get("link") or row.get("url") or ""
        if not url:
            continue
        title = (row.get("title") or "")[:8000]
        snippet = (row.get("description") or row.get("snippet") or "") or ""
        snippet = snippet[:16000]
        pos = row.get("rank") or row.get("position") or (i + 1)
        try:
            position = int(pos)
        except (TypeError, ValueError):
            position = i + 1
        domain = urlparse(url).netloc or ""
        doc_id = hashlib.sha256(f"{url}\t{source_query}".encode()).hexdigest()
        out.append(
            {
                "id": doc_id,
                "title": title,
                "url": url,
                "snippet": snippet,
                "source_query": source_query,
                "domain": domain,
                "position": position,
            }
        )
    return out


def ensure_collection(client: typesense.Client, *, recreate: bool) -> None:
    if recreate:
        try:
            client.collections[COLLECTION].delete()
        except ObjectNotFound:
            pass
        client.collections.create(collection_schema())
        return
    try:
        client.collections[COLLECTION].retrieve()
    except ObjectNotFound:
        client.collections.create(collection_schema())


def load_queries(args: argparse.Namespace) -> List[str]:
    queries: List[str] = []
    if args.queries_file:
        text = Path(args.queries_file).read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            queries.append(line)
    extra = args.queries or []
    queries.extend(extra)
    if not queries:
        return list(DEFAULT_QUERIES)
    return queries


def main() -> None:
    p = argparse.ArgumentParser(description="Ingest Bright Data SERP into Typesense.")
    p.add_argument(
        "--num-results",
        type=int,
        default=8,
        help="Max organic rows to index per query after fetch (Google ignores &num=; we slice client-side).",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=0.6,
        help="Seconds between Bright Data requests.",
    )
    p.add_argument(
        "--append",
        action="store_true",
        help="Do not drop the collection; create it only if missing. Use for multiple ingest runs into one index.",
    )
    p.add_argument(
        "--query",
        action="append",
        dest="queries",
        metavar="Q",
        help="SERP query string (repeatable). Default: built-in demo queries if no --queries-file/--query.",
    )
    p.add_argument(
        "--queries-file",
        type=str,
        default=None,
        help="Path to a file with one query per line (# and blank lines ignored).",
    )
    args = p.parse_args()

    client = typesense_client()
    ensure_collection(client, recreate=not args.append)

    bd = BrightDataSERPClient()
    all_docs: List[Dict[str, Any]] = []
    query_list = load_queries(args)

    for q in query_list:
        print(f"Query: {q!r}")
        try:
            raw = bd.search(q, num_results=args.num_results)
        except Exception as e:
            print(f"  error: {e}")
            continue
        docs = organic_to_documents(raw, q)
        print(f"  indexed {len(docs)} organic rows")
        all_docs.extend(docs)
        time.sleep(args.delay)

    if not all_docs:
        print("No documents to import. Check Bright Data credentials and SERP response.")
        return

    jsonl = "\n".join(json.dumps(d, ensure_ascii=False) for d in all_docs)
    imp = client.collections[COLLECTION].documents.import_(jsonl, {"action": "upsert"})
    # import_ returns one JSON object per line
    errors = [line for line in imp.split("\n") if line and '"success":false' in line]
    if errors:
        print("Import reported errors (first few):", errors[:3])
    print(f"Done. Total documents: {len(all_docs)}")


if __name__ == "__main__":
    main()
