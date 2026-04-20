"""Minimal Bright Data SERP client (no OpenTelemetry)."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()


def limit_organic(data: Dict[str, Any], max_results: int) -> Dict[str, Any]:
    """Keep at most ``max_results`` organic rows. Google/Bright Data often ignore ``&num=``; slice client-side."""
    if max_results <= 0:
        return data
    organic = data.get("organic")
    if isinstance(organic, list) and len(organic) > max_results:
        return {**data, "organic": organic[:max_results]}
    return data


class BrightDataSERPClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        zone: Optional[str] = None,
        country: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("BRIGHT_DATA_API_KEY")
        self.zone = zone or os.getenv("BRIGHT_DATA_ZONE")
        self.country = country or os.getenv("BRIGHT_DATA_COUNTRY")
        self.api_endpoint = "https://api.brightdata.com/request"

        if not self.api_key:
            raise ValueError("BRIGHT_DATA_API_KEY is required.")
        if not self.zone:
            raise ValueError("BRIGHT_DATA_ZONE is required.")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
        )

    def search(
        self,
        query: str,
        num_results: int = 10,
        language: Optional[str] = None,
        country: Optional[str] = None,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        last_err: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                return self._do_search(query, num_results, language, country)
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(0.5 * (attempt + 1))
        assert last_err is not None
        raise last_err

    def _do_search(
        self,
        query: str,
        num_results: int,
        language: Optional[str],
        country: Optional[str],
    ) -> Dict[str, Any]:
        # Omit &num=: deprecated by Google (Bright Data strips it); use limit_organic after fetch.
        search_url = (
            f"https://www.google.com/search"
            f"?q={requests.utils.quote(query)}"
            f"&brd_json=1"
        )
        if language:
            search_url += f"&hl={language}&lr=lang_{language}"
        target_country = country or self.country
        payload: Dict[str, Any] = {
            "zone": self.zone,
            "url": search_url,
            "format": "json",
        }
        if target_country:
            payload["country"] = target_country

        response = self.session.post(self.api_endpoint, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError(f"Bright Data unexpected response type: {type(result)}")
        inner_status = result.get("status_code")
        if inner_status is not None and inner_status != 200:
            raise RuntimeError(f"Bright Data SERP status_code={inner_status}")
        if "body" in result:
            body = result["body"]
            if isinstance(body, str):
                if not body.strip():
                    raise RuntimeError("Bright Data SERP empty body")
                result = json.loads(body)
            else:
                result = body
        elif "organic" not in result:
            raise RuntimeError("Bright Data response missing 'body' and 'organic'")
        return limit_organic(result, num_results)
