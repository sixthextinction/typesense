"""Static UI + /api/search proxy (keeps Typesense admin key off the browser)."""

from __future__ import annotations

import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import typesense
from dotenv import load_dotenv

load_dotenv()

STATIC = Path(__file__).resolve().parent / "static"
COLLECTION = "serp_results"
PORT = int(os.getenv("SERVE_PORT", "8765"))


def client() -> typesense.Client:
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
            "connection_timeout_seconds": 10,
        }
    )


class Handler(BaseHTTPRequestHandler):
    _ts: typesense.Client | None = None

    @classmethod
    def typesense(cls) -> typesense.Client:
        if cls._ts is None:
            cls._ts = client()
        return cls._ts

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.address_string()}] {fmt % args}")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/search":
            self._search(parsed.query)
            return
        if parsed.path == "/" or parsed.path == "/index.html":
            self._file(STATIC / "index.html", "text/html; charset=utf-8")
            return
        self.send_error(404, "Not found")

    def _file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self.send_error(404, "Not found")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _search(self, query: str) -> None:
        qs = urllib.parse.parse_qs(query)
        q = (qs.get("q") or [""])[0].strip()
        fq = (qs.get("filter_by") or [""])[0].strip()

        if not q:
            payload = {
                "hits": [],
                "found": 0,
                "facet_counts": [],
                "q": q,
            }
            self._json(payload)
            return

        # Text search spans four stored fields (see ingest schema). Weights tune BM25-style
        # ranking: a term in the title should matter more than the same term buried in the
        # snippet, and more than an incidental match in the URL or domain string.
        # Order MUST match query_by — Typesense applies weights positionally.
        query_by = "title,snippet,url,domain"
        query_by_weights = "4,3,1,1" # so titles are more important than snippets, which are more important than urls, which are more important than domains

        params: dict = {
            "q": q,
            "query_by": query_by,
            "query_by_weights": query_by_weights,
            "facet_by": "source_query,domain",
            "max_facet_values": 40,
            "per_page": 25,
        }
        if fq:
            params["filter_by"] = fq

        try:
            result = self.typesense().collections[COLLECTION].documents.search(params)
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        self._json(result)

    def _json(self, obj: object) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"SERP demo UI: http://127.0.0.1:{PORT}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
