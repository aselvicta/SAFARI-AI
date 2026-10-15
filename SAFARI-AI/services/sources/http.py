"""One HTTP client for every connector: timeouts, retries with backoff, a polite user agent."""

from __future__ import annotations

import time

import httpx

USER_AGENT = "SafariAI/2.0 (+visitor assistant for Tanzania National Parks; respectful crawler)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    pass


class Http:
    def __init__(self, timeout: float = 45.0, retries: int = 3, backoff: float = 1.5, client: httpx.Client | None = None) -> None:
        self.retries = retries
        self.backoff = backoff
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=15.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"},
        )

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.get(url, params=params)
                if response.status_code in RETRY_STATUS and attempt < self.retries:
                    time.sleep(self._delay(attempt, response))
                    continue
                response.raise_for_status()
                return response
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in RETRY_STATUS:
                    break
                if attempt < self.retries:
                    time.sleep(self._delay(attempt))
        raise FetchError(f"GET {url} failed: {last}")

    def json(self, url: str, params: dict | None = None):
        return self.get(url, params).json()

    def close(self) -> None:
        self.client.close()

    def _delay(self, attempt: int, response: httpx.Response | None = None) -> float:
        if response is not None:
            retry_after = response.headers.get("retry-after", "")
            if retry_after.isdigit():
                return min(30.0, float(retry_after))
        return self.backoff * (2**attempt)
