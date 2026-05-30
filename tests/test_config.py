import logging

import pytest

from immich_user_notify.config import ConfigError, load_config
from immich_user_notify.log import resolve_level

BASE_ENV = {
    "IMMICH_TOKEN": "t",
    "IMMICH_PRIVATE_URL": "http://immich:2283/",
    "IMMICH_PUBLIC_URL": "https://photos.example.com/",
    "NTFY_INTERNAL_URL": "http://ntfy:80/",
    "NTFY_PUBLISHER_USERNAME": "pub",
    "NTFY_PUBLISHER_PASSWORD": "secret",
}


def test_defaults_and_url_stripping():
    c = load_config(BASE_ENV)
    assert c.interval_minutes == 15
    assert c.recency_multiplier == 3
    assert c.http_retries == 3
    assert c.http_timeout_s == 30.0
    assert c.immich_api_base == "http://immich:2283/api"   # trailing slash stripped
    assert c.immich_public_url == "https://photos.example.com"
    assert not hasattr(c, "tz")  # dead field removed


def test_missing_required_lists_all():
    with pytest.raises(ConfigError) as excinfo:
        load_config({})
    msg = str(excinfo.value)
    assert "IMMICH_TOKEN" in msg
    assert "NTFY_PUBLISHER_PASSWORD" in msg


def test_tunables_are_read_from_env():
    c = load_config(
        {
            **BASE_ENV,
            "PERIODIC_CHECK_INTERVAL_MINUTES": "30",
            "RECENCY_MULTIPLIER": "2",
            "HTTP_TIMEOUT_S": "5.5",
            "HTTP_RETRIES": "4",
        }
    )
    assert c.interval_minutes == 30
    assert c.recency_multiplier == 2
    assert c.http_timeout_s == 5.5
    assert c.http_retries == 4
    assert c.recency_window_seconds == 2 * 30 * 60


@pytest.mark.parametrize(
    "overrides",
    [
        {"HTTP_RETRIES": "abc"},          # not an int
        {"HTTP_RETRIES": "0"},            # below minimum
        {"RECENCY_MULTIPLIER": "0"},      # below minimum
        {"HTTP_TIMEOUT_S": "nope"},       # not a number
        {"PERIODIC_CHECK_INTERVAL_MINUTES": "0"},
    ],
)
def test_invalid_tunables_raise(overrides):
    with pytest.raises(ConfigError):
        load_config({**BASE_ENV, **overrides})


@pytest.mark.parametrize(
    "level,expected",
    [
        ("INFO", logging.INFO),
        ("debug", logging.DEBUG),
        ("WARNING", logging.WARNING),
        ("BASIC_FORMAT", logging.INFO),   # non-level attribute -> fallback
        ("totally-bogus", logging.INFO),
        ("", logging.INFO),
    ],
)
def test_resolve_level(level, expected):
    assert resolve_level(level) == expected
