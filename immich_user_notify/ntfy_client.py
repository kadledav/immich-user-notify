"""ntfy publish client.

Publishes via ntfy's JSON endpoint (POST a JSON object to the server root) rather
than the header-based endpoint. HTTP headers are encoded as latin-1 by the client
stack, so non-ASCII titles/tags (e.g. Czech "Nové fotky") would be mangled or raise;
the JSON body is UTF-8 and carries title/message/tags safely for any language.
Basic-auth is precomputed once on the session.
"""

from __future__ import annotations

import base64
import json
import re
import time
from typing import Callable, Sequence

import requests

from .httpclient import request_with_retries

_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class NtfyError(Exception):
    """Any failure publishing to ntfy (bad topic, HTTP error, exhausted retries)."""


class NtfyClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        session: requests.Session,
        timeout_s: float = 30.0,
        retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self._session.headers["Authorization"] = f"Basic {token}"
        self._timeout = timeout_s
        self._retries = retries
        self._sleep = sleep

    def publish(
        self,
        topic: str,
        *,
        message: str,
        title: str,
        priority: int = 3,
        tags: Sequence[str] = (),
        click: str | None = None,
        icon: str | None = None,
        markdown: bool = False,
    ) -> None:
        if not _TOPIC_RE.match(topic):
            raise NtfyError(f"invalid ntfy topic: {topic!r}")

        payload: dict[str, object] = {
            "topic": topic,
            "message": message,
            "title": title,
            "priority": priority,
        }
        if tags:
            payload["tags"] = list(tags)
        if click:
            payload["click"] = click
        if icon:
            payload["icon"] = icon
        if markdown:
            payload["markdown"] = True

        request_with_retries(
            self._session,
            "POST",
            f"{self._base_url}/",  # JSON publish goes to the server root, topic in body
            error_cls=NtfyError,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=self._timeout,
            retries=self._retries,
            sleep=self._sleep,
        )
