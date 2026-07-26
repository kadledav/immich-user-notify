"""Typed wrapper over the Immich 3.x REST API (developed against 3.0.0; not 2.x).

Dumb client: HTTP in, dataclasses out, retries inside. No business logic.
Auth is the `x-api-key` header set on the session.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import requests

from .httpclient import request_with_retries
from .models import AlbumDetail, AlbumSummary, Member
from .timeutil import parse_immich_dt

_OWNER_ROLE = "owner"


class ImmichError(Exception):
    """Any failure talking to Immich (HTTP error, bad JSON, exhausted retries)."""


def _map_user(dto: dict[str, Any], *, role: str | None = None) -> Member:
    return Member(
        user_id=dto["id"],
        email=dto.get("email"),
        name=dto.get("name"),
        role=role,
    )


def _split_album_users(dto: dict[str, Any]) -> tuple[Member, list[Member]]:
    """Split `albumUsers` into (owner, other members).

    Since Immich 3.0 the owner is an `albumUsers` entry with role "owner" (the old
    `owner`/`ownerId` fields are gone). Never rely on position: the server orders the
    list by role then name, so an editor commonly sorts first.
    """
    owner: Member | None = None
    members: list[Member] = []
    for au in dto.get("albumUsers") or []:
        user = au.get("user") or {}
        if not user.get("id"):
            continue
        role = au.get("role")
        member = _map_user(user, role=role)
        if role == _OWNER_ROLE and owner is None:
            owner = member
        else:
            members.append(member)
    if owner is None:
        raise ValueError("albumUsers has no entry with role 'owner'")
    # Belt-and-braces: the owner must never appear as a shared member, or they would be
    # notified that their own album was shared with them.
    members = [m for m in members if m.user_id != owner.user_id]
    return owner, members


def _map_contributor_counts(dto: dict[str, Any]) -> dict[str, int] | None:
    """userId -> asset count, or None when Immich omitted the field.

    Immich only computes `contributorCounts` for shared albums. An *empty list* means
    "shared album, no assets" and must stay distinct from an absent field, which means
    "no signal at all" -- collapsing the two would make removing and re-adding every
    photo look like no change.
    """
    raw = dto.get("contributorCounts")
    if raw is None:
        return None
    return {c["userId"]: int(c["assetCount"]) for c in raw}


def _map_album_summary(dto: dict[str, Any]) -> AlbumSummary:
    return AlbumSummary(
        id=dto["id"],
        name=dto["albumName"],
        asset_count=int(dto.get("assetCount", 0)),
        shared=bool(dto.get("shared", False)),
        updated_at=parse_immich_dt(dto["updatedAt"]),
        member_count=len(dto.get("albumUsers") or []),
    )


def _map_album_detail(dto: dict[str, Any]) -> AlbumDetail:
    owner, members = _split_album_users(dto)
    return AlbumDetail(
        id=dto["id"],
        name=dto["albumName"],
        created_at=parse_immich_dt(dto["createdAt"]),
        updated_at=parse_immich_dt(dto["updatedAt"]),
        owner=owner,
        members=members,
        contributor_counts=_map_contributor_counts(dto),
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
        # Deliberately unfiltered. Immich 3.0 renamed the `shared` filter to `isShared`
        # and added `isOwned`, but filtering to shared albums would hide an album that
        # we already track and that has since been un-shared, so we would stop updating
        # its state. Cheap either way: the list response carries no assets.
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

    def get_server_version(self) -> tuple[int, int, int]:
        """(major, minor, patch) from GET /api/server/version (needs no key scope)."""
        data = self._get("/server/version")
        return _mapped(
            "/server/version",
            lambda: (int(data["major"]), int(data["minor"]), int(data["patch"])),
        )
