"""Shared HTTP request helper with bounded retries, used by both API clients.

Retries any requests-layer error (connection, timeout, chunked/decoding, etc.) and
retryable status codes (429, 5xx) with exponential backoff + jitter; non-retryable
4xx raise immediately. Every failure path ends as `error_cls` so callers only have
to catch ImmichError/NtfyError. `retries` is the TOTAL number of attempts (min 1),
not extra retries. The `sleep` callable is injectable so tests stay fast.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Mapping, Type

import requests

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def request_with_retries(
    session: requests.Session,
    method: str,
    url: str,
    *,
    error_cls: Type[Exception],
    params: Mapping[str, object] | None = None,
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    backoff_base: float = 0.5,
    backoff_cap: float = 8.0,
) -> requests.Response:
    retries = max(1, retries)
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = session.request(
                method, url, params=params, data=data, headers=headers, timeout=timeout
            )
        except requests.RequestException as exc:
            # Connection, timeout, chunked-encoding, decoding, redirect, etc. — all
            # retried then wrapped into error_cls so nothing requests-layer leaks raw.
            last_exc = exc
        else:
            if 200 <= resp.status_code < 300:
                return resp
            if resp.status_code not in RETRY_STATUS:
                raise error_cls(
                    f"{method} {url} -> HTTP {resp.status_code}: {resp.text[:200]}"
                )
            last_exc = error_cls(f"{method} {url} -> HTTP {resp.status_code}")
        if attempt < retries - 1:
            sleep(min(backoff_cap, backoff_base * (2 ** attempt)) + random.uniform(0, 0.1))
    raise error_cls(f"{method} {url} failed after {retries} attempt(s)") from last_exc
