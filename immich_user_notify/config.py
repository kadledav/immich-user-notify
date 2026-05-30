"""Configuration: env parsing into a frozen Config, plus the email->topic rule.

All required vars are validated up front so the process fails fast on boot with a
single message listing everything that is wrong, instead of crashing later.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

log = logging.getLogger(__name__)

# ntfy topics allow only these characters; everything else is replaced with "-".
_TOPIC_INVALID = re.compile(r"[^A-Za-z0-9_-]")
# All topics are namespaced so they don't clash with other ntfy usage.
_TOPIC_PREFIX = "immich-"

# Default location of the bundled locale files: <repo>/locales, sibling of this package.
_DEFAULT_LOCALES_DIR = str(Path(__file__).resolve().parent.parent / "locales")

# Shown as the notification icon; the ntfy client (phone) fetches it, so it must be a
# publicly reachable URL. The Immich logo is a sensible default.
_DEFAULT_ICON_URL = "https://raw.githubusercontent.com/immich-app/immich/main/design/immich-logo.png"

_REQUIRED = (
    "IMMICH_TOKEN",
    "IMMICH_PRIVATE_URL",
    "IMMICH_PUBLIC_URL",
    "NTFY_INTERNAL_URL",
    "NTFY_PUBLISHER_USERNAME",
    "NTFY_PUBLISHER_PASSWORD",
)


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    immich_token: str
    immich_private_url: str       # internal base, no trailing slash, no /api suffix
    immich_public_url: str        # public base for Click links, no trailing slash
    ntfy_internal_url: str        # e.g. http://ntfy:80, no trailing slash
    ntfy_publisher_username: str
    ntfy_publisher_password: str
    interval_minutes: int = 15
    db_path: str = "/data/state.db"
    log_level: str = "INFO"
    force_full_scan_every: int = 8
    default_language: str = "en"
    user_languages: Mapping[str, str] = field(default_factory=dict)  # email(lower) -> lang
    locales_dir: str = _DEFAULT_LOCALES_DIR
    icon_url: str | None = _DEFAULT_ICON_URL
    http_timeout_s: float = 30.0
    http_retries: int = 3

    @property
    def immich_api_base(self) -> str:
        return f"{self.immich_private_url}/api"

    @property
    def interval_seconds(self) -> int:
        return self.interval_minutes * 60


def topic_for_email(email: str) -> str:
    """Derive a person's ntfy topic from their email: "immich-" + the sanitized
    local part.

    local = part before "@"; replace every char not in [A-Za-z0-9_-] with "-";
    lowercase; prefix with "immich-"; truncate to 64. Returns "" if the local part
    sanitizes to empty (caller drops that recipient).

    e.g. "david.k@gmail.com" -> "immich-david-k"
    """
    local = email.split("@", 1)[0]
    cleaned = _TOPIC_INVALID.sub("-", local).lower()
    if not cleaned:
        return ""
    return f"{_TOPIC_PREFIX}{cleaned}"[:64]


def parse_user_languages(raw: str) -> dict[str, str]:
    """Parse USER_LANGUAGES ("a@x.com=cs,b@y.com=en") into {email_lower: lang_lower}.

    Blank entries are skipped; malformed entries (no "=" or empty side) are ignored
    with a warning.
    """
    result: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            log.warning("USER_LANGUAGES: ignoring malformed entry %r (expected email=lang)", entry)
            continue
        email, lang = entry.split("=", 1)
        email = email.strip().lower()
        lang = lang.strip().lower()
        if email and lang:
            result[email] = lang
        else:
            log.warning("USER_LANGUAGES: ignoring entry with empty side %r", entry)
    return result


def _strip_url(value: str) -> str:
    return value.strip().rstrip("/")


def _int_env(env: Mapping[str, str], name: str, default: int, *, minimum: int, errors: list[str]) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{name} must be an integer, got {raw!r}")
        return default
    if value < minimum:
        errors.append(f"{name} must be >= {minimum}")
    return value


def _float_env(env: Mapping[str, str], name: str, default: float, *, minimum: float, errors: list[str]) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        errors.append(f"{name} must be a number, got {raw!r}")
        return default
    if value < minimum:
        errors.append(f"{name} must be >= {minimum}")
    return value


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Build a Config from the environment, validating all required vars at once."""
    env = os.environ if env is None else env

    missing = [name for name in _REQUIRED if not (env.get(name) or "").strip()]
    errors: list[str] = [f"missing required env var: {name}" for name in missing]

    interval_minutes = 15
    raw_interval = (env.get("PERIODIC_CHECK_INTERVAL_MINUTES") or "").strip()
    if raw_interval:
        try:
            interval_minutes = int(raw_interval)
            if interval_minutes < 1:
                errors.append("PERIODIC_CHECK_INTERVAL_MINUTES must be >= 1")
        except ValueError:
            errors.append(f"PERIODIC_CHECK_INTERVAL_MINUTES must be an integer, got {raw_interval!r}")

    force_full_scan_every = _int_env(env, "FORCE_FULL_SCAN_EVERY", 8, minimum=0, errors=errors)
    http_retries = _int_env(env, "HTTP_RETRIES", 3, minimum=1, errors=errors)
    http_timeout_s = _float_env(env, "HTTP_TIMEOUT_S", 30.0, minimum=0.1, errors=errors)

    if errors:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errors))

    return Config(
        immich_token=env["IMMICH_TOKEN"].strip(),
        immich_private_url=_strip_url(env["IMMICH_PRIVATE_URL"]),
        immich_public_url=_strip_url(env["IMMICH_PUBLIC_URL"]),
        ntfy_internal_url=_strip_url(env["NTFY_INTERNAL_URL"]),
        ntfy_publisher_username=env["NTFY_PUBLISHER_USERNAME"],
        ntfy_publisher_password=env["NTFY_PUBLISHER_PASSWORD"],
        interval_minutes=interval_minutes,
        db_path=(env.get("DB_PATH") or "/data/state.db").strip(),
        log_level=(env.get("LOG_LEVEL") or "INFO").strip(),
        force_full_scan_every=force_full_scan_every,
        default_language=(env.get("DEFAULT_LANGUAGE") or "en").strip().lower(),
        user_languages=parse_user_languages(env.get("USER_LANGUAGES") or ""),
        locales_dir=(env.get("LOCALES_DIR") or _DEFAULT_LOCALES_DIR).strip(),
        icon_url=(env.get("NTFY_ICON_URL") or "").strip() or _DEFAULT_ICON_URL,
        http_timeout_s=http_timeout_s,
        http_retries=http_retries,
    )
