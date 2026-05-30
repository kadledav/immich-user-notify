"""Entry point: load config, wire clients, run the polling loop."""

from __future__ import annotations

import logging

import requests

from immich_user_notify.app import App
from immich_user_notify.config import ConfigError, load_config
from immich_user_notify.i18n import Translator
from immich_user_notify.immich_client import ImmichClient
from immich_user_notify.log import setup_logging
from immich_user_notify.ntfy_client import NtfyClient
from immich_user_notify.store import Store


def main() -> None:
    setup_logging("INFO")
    log = logging.getLogger("immich_user_notify")

    try:
        config = load_config()
    except ConfigError as exc:
        log.error("%s", exc)
        raise SystemExit(2)

    setup_logging(config.log_level)
    log.info(
        "immich-user-notify starting (interval=%d min, db=%s, default_lang=%s)",
        config.interval_minutes,
        config.db_path,
        config.default_language,
    )

    # Separate sessions: distinct auth headers (x-api-key vs Basic).
    immich = ImmichClient(
        config.immich_api_base,
        config.immich_token,
        session=requests.Session(),
        timeout_s=config.http_timeout_s,
        retries=config.http_retries,
    )
    ntfy = NtfyClient(
        config.ntfy_internal_url,
        config.ntfy_publisher_username,
        config.ntfy_publisher_password,
        session=requests.Session(),
        timeout_s=config.http_timeout_s,
        retries=config.http_retries,
    )
    store = Store(config.db_path)
    translator = Translator(config.locales_dir, config.default_language)

    app = App(config, immich, ntfy, store, translator)
    try:
        app.run_forever()
    finally:
        store.close()


if __name__ == "__main__":
    main()
