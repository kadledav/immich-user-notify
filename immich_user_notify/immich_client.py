"""Typed wrapper over the Immich REST API (>= 2.7.5).

Dumb client: HTTP in, dataclasses out, retries inside. No business logic.
Auth is the `x-api-key` header set on the session.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import requests

from .httpclient import request_with_retries
from .models import AlbumDetail, AlbumSummary, Asset, Member
from .timeutil import parse_immich_dt


class ImmichError(Exception):
    """Any failure talking to Immich (HTTP error, bad JSON, exhausted retries)."""


def _map_user(dto: dict[str, Any], *, role: str | None = None) -> Member:
    return Member(
        user_id=dto["id"],
        email=dto.get("email"),
        name=dto.get("name"),
        role=role,
    )


def _map_members(dto: dict[str, Any]) -> list[Member]:
    members: list[Member] = []
    for au in dto.get("albumUsers") or []:
        user = au.get("user") or {}
        if not user.get("id"):
            continue
        members.append(_map_user(user, role=au.get("role")))
    return members


def _map_asset(dto: dict[str, Any]) -> Asset:
    file_created = dto.get("fileCreatedAt")
    return Asset(
        id=dto["id"],
        owner_id=dto["ownerId"],
        created_at=parse_immich_dt(dto["createdAt"]),
        file_created_at=parse_immich_dt(file_created) if file_created else None,
        original_file_name=dto.get("originalFileName"),
        type=dto.get("type"),
    )


def _map_album_summary(dto: dict[str, Any]) -> AlbumSummary:
    return AlbumSummary(
        id=dto["id"],
        name=dto["albumName"],
        owner_id=dto["ownerId"],
        asset_count=int(dto.get("assetCount", 0)),
        shared=bool(dto.get("shared", False)),
        updated_at=parse_immich_dt(dto["updatedAt"]),
        owner=_map_user(dto["owner"]),
        member_count=len(dto.get("albumUsers") or []),
    )


def _map_album_detail(dto: dict[str, Any]) -> AlbumDetail:
    return AlbumDetail(
        id=dto["id"],
        name=dto["albumName"],
        owner_id=dto["ownerId"],
        created_at=parse_immich_dt(dto["createdAt"]),
        updated_at=parse_immich_dt(dto["updatedAt"]),
        owner=_map_user(dto["owner"]),
        members=_map_members(dto),
        assets=[_map_asset(a) for a in (dto.get("assets") or [])],
    )


def _mapped(path: str, fn: Callable[[], Any]) -> Any:
    """Run a DTO mapper, turning a malformed payload into ImmichError (not KeyError)
    so per-album isolation and the ImmichError handlers still apply."""
    try:
        return fn()
    except (KeyError, TypeError, ValueError) as exc:
        raise ImmichError(f"{path}: unexpected payload shape ({exc!r})") from exc


class ImmichClient:
    def __init__(
        self,
        api_base: str,
        token: str,
        *,
        session: requests.Session,
        timeout_s: float = 30.0,
        retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._session = session
        self._session.headers["x-api-key"] = token
        self._session.headers.setdefault("Accept", "application/json")
        self._timeout = timeout_s
        self._retries = retries
        self._sleep = sleep

    def _get(self, path: str, *, params: dict[str, object] | None = None) -> Any:
        resp = request_with_retries(
            self._session,
            "GET",
            f"{self._api_base}{path}",
            error_cls=ImmichError,
            params=params,
            timeout=self._timeout,
            retries=self._retries,
            sleep=self._sleep,
        )
        try:
            return resp.json()
        except ValueError as exc:  # includes json.JSONDecodeError
            raise ImmichError(f"GET {path}: invalid JSON response") from exc

    def list_albums(self) -> list[AlbumSummary]:
        data = self._get("/albums")
        return _mapped("/albums", lambda: [_map_album_summary(a) for a in data])

    def get_album(self, album_id: str) -> AlbumDetail:
        data = self._get(f"/albums/{album_id}")
        return _mapped(f"/albums/{album_id}", lambda: _map_album_detail(data))

    def list_users(self) -> list[Member]:
        data = self._get("/users")
        return _mapped("/users", lambda: [_map_user(u) for u in data])

    def get_user(self, user_id: str) -> Member:
        data = self._get(f"/users/{user_id}")
        return _mapped(f"/users/{user_id}", lambda: _map_user(data))

    def get_me(self) -> Member:
        data = self._get("/users/me")
        return _mapped("/users/me", lambda: _map_user(data))
