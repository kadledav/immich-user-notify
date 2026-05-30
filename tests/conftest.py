from __future__ import annotations

from datetime import datetime, timezone

import pytest
import requests
import responses

from immich_user_notify.app import App
from immich_user_notify.config import Config
from immich_user_notify.i18n import Translator
from immich_user_notify.immich_client import ImmichClient
from immich_user_notify.ntfy_client import NtfyClient
from immich_user_notify.store import Store


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock(fixed_now):
    return lambda: fixed_now


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "state.db")


@pytest.fixture
def store(db_path):
    s = Store(db_path)
    yield s
    s.close()


@pytest.fixture
def mocked_responses():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture
def immich_base() -> str:
    return "http://immich.local"


@pytest.fixture
def ntfy_base() -> str:
    return "http://ntfy.local"


@pytest.fixture
def config(immich_base, ntfy_base, db_path) -> Config:
    return Config(
        immich_token="test-token",
        immich_private_url=immich_base,
        immich_public_url="https://photos.example.com",
        ntfy_internal_url=ntfy_base,
        ntfy_publisher_username="pub",
        ntfy_publisher_password="secret",
        interval_minutes=15,
        db_path=db_path,
        default_language="en",
        user_languages={},
    )


@pytest.fixture
def translator(config) -> Translator:
    return Translator(config.locales_dir, config.default_language)


@pytest.fixture
def immich(config):
    # retries=1 keeps error-path tests fast (no backoff sleeps).
    return ImmichClient(
        config.immich_api_base,
        config.immich_token,
        session=requests.Session(),
        retries=1,
    )


@pytest.fixture
def ntfy(config):
    return NtfyClient(
        config.ntfy_internal_url,
        config.ntfy_publisher_username,
        config.ntfy_publisher_password,
        session=requests.Session(),
        retries=1,
    )


@pytest.fixture
def app(config, immich, ntfy, store, translator, clock):
    return App(config, immich, ntfy, store, translator, clock=clock)


def post_calls(rsps):
    """All POST requests captured so far (the ntfy publishes)."""
    return [c.request for c in rsps.calls if c.request.method == "POST"]
