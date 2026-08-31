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

NTFY_TOKEN_ENV = {
    "IMMICH_TOKEN": "t",
    "IMMICH_PRIVATE_URL": "http://immich:2283/",
    "IMMICH_PUBLIC_URL": "https://photos.example.com/",
    "NTFY_INTERNAL_URL": "http://ntfy:80/",
    "NTFY_PUBLISHER_TOKEN": "tk_abc123",
}

def test_defaults_and_url_stripping():
    c = load_config(BASE_ENV)
    assert c.interval_minutes == 15
    assert c.http_retries == 3
    assert c.http_timeout_s == 30.0
    assert c.immich_api_base == "http://immich:2283/api"   # trailing slash stripped
    assert c.immich_public_url == "https://photos.example.com"
    assert c.icon_url.endswith("immich-logo.png")          # default icon = Immich logo
    assert not hasattr(c, "tz")  # dead field removed


def test_icon_url_override():
    c = load_config({**BASE_ENV, "NTFY_ICON_URL": "https://example.com/x.png"})
    assert c.icon_url == "https://example.com/x.png"


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
            "HTTP_TIMEOUT_S": "5.5",
            "HTTP_RETRIES": "4",
        }
    )
    assert c.interval_minutes == 30
    assert c.http_timeout_s == 5.5
    assert c.http_retries == 4
    assert c.interval_seconds == 30 * 60


@pytest.mark.parametrize(
    "overrides",
    [
        {"HTTP_RETRIES": "abc"},          # not an int
        {"HTTP_RETRIES": "0"},            # below minimum
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

def test_ntfy_token_alone_is_sufficient():
    c = load_config(NTFY_TOKEN_ENV)
    assert c.ntfy_publisher_token == "tk_abc123"
    assert c.ntfy_publisher_username is None
    assert c.ntfy_publisher_password is None


def test_immich_token_file_is_read(tmp_path):
    token_file = tmp_path / "immich_token"
    token_file.write_text("file-token\n")
    env = {**BASE_ENV, "IMMICH_TOKEN_FILE": str(token_file)}
    del env["IMMICH_TOKEN"]
    c = load_config(env)
    assert c.immich_token == "file-token"


def test_immich_token_file_takes_precedence_over_inline(tmp_path):
    token_file = tmp_path / "immich_token"
    token_file.write_text("file-token")
    env = {**BASE_ENV, "IMMICH_TOKEN_FILE": str(token_file)}
    c = load_config(env)
    assert c.immich_token == "file-token"


def test_ntfy_token_file_is_read(tmp_path):
    token_file = tmp_path / "ntfy_token"
    token_file.write_text("tk_from_file\n")
    env = {**NTFY_TOKEN_ENV, "NTFY_PUBLISHER_TOKEN_FILE": str(token_file)}
    del env["NTFY_PUBLISHER_TOKEN"]
    c = load_config(env)
    assert c.ntfy_publisher_token == "tk_from_file"


def test_missing_immich_token_and_file_raises():
    env = {k: v for k, v in BASE_ENV.items() if k != "IMMICH_TOKEN"}
    with pytest.raises(ConfigError) as excinfo:
        load_config(env)
    assert "IMMICH_TOKEN" in str(excinfo.value)


def test_missing_ntfy_auth_entirely_raises():
    env = {
        "IMMICH_TOKEN": "t",
        "IMMICH_PRIVATE_URL": "http://immich:2283/",
        "IMMICH_PUBLIC_URL": "https://photos.example.com/",
        "NTFY_INTERNAL_URL": "http://ntfy:80/",
        # no NTFY_PUBLISHER_TOKEN(_FILE), no USERNAME/PASSWORD
    }
    with pytest.raises(ConfigError) as excinfo:
        load_config(env)
    assert "NTFY_PUBLISHER" in str(excinfo.value)


def test_ntfy_partial_username_without_password_raises():
    env = {
        "IMMICH_TOKEN": "t",
        "IMMICH_PRIVATE_URL": "http://immich:2283/",
        "IMMICH_PUBLIC_URL": "https://photos.example.com/",
        "NTFY_INTERNAL_URL": "http://ntfy:80/",
        "NTFY_PUBLISHER_USERNAME": "pub",
    }
    with pytest.raises(ConfigError):
        load_config(env)


def test_unreadable_token_file_raises():
    env = {**BASE_ENV, "IMMICH_TOKEN_FILE": "/nonexistent/path/token"}
    del env["IMMICH_TOKEN"]
    with pytest.raises(ConfigError) as excinfo:
        load_config(env)
    assert "IMMICH_TOKEN_FILE" in str(excinfo.value)
