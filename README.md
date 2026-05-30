# immich-user-notify

A small self-running service that watches the [Immich](https://immich.app) albums
your account can see and sends a **per-user** [ntfy](https://ntfy.sh) push when
photos or members are added — notifying everyone who can see the album **except**
the person who made the change.

It is inspired by [pman07/Immich_Notify](https://github.com/pman07/Immich_Notify)
(notification style) but fixes its two main limitations:

- **No per-album setup.** It discovers all albums automatically — nothing to configure per album.
- **Per-user, not one shared topic.** Each person gets their own ntfy topic derived from their email, and the person who *caused* a change isn't pinged about their own action.

## How it works

Every `PERIODIC_CHECK_INTERVAL_MINUTES` it:

1. Lists albums (`GET /api/albums`) and, for any album whose `assetCount`/`updatedAt`
   changed, fetches the detail (`GET /api/albums/{id}`).
2. Diffs the album's asset-ID set and member-ID set against a small local SQLite DB
   (it stores **only IDs**, never photo names). New asset IDs and new member IDs are
   the changes.
3. Attributes each new photo to its uploader via `asset.ownerId` — in Immich only an
   asset's owner can add it to an album, so this reliably identifies the contributor.
4. Sends notifications:
   - **New photos** → everyone who can see the album, **minus** the contributor.
     If a single person added them the message names them; if several people did, it
     stays anonymous.
   - **New member** → only the newly added member (`You have been added to "<album>"`).
     No one else is told that someone joined.

Safety details:

- **First sight of an album is a silent baseline** — it records the current contents
  and notifies nothing, so deploying (or losing the DB) never floods everyone.
- **Recency guard**: a newly detected photo older than `3 ×` the interval (by upload
  time) is recorded as seen but not notified — this prevents a storm after the service
  was down for a while.
- One ntfy topic per person, derived from their email: `immich-` followed by the part
  before `@`, with every character outside `[A-Za-z0-9_-]` replaced by `-`, lowercased.
  e.g. `david.k@example.com` → topic `immich-david-k`. **At startup the full
  `email → topic` map is logged** (with a warning on any collision) so you know exactly
  which topic each person must subscribe to.

> Note on attribution: there is no Immich API for *when* an asset was added to an album
> (only when it was uploaded), which is why detection uses snapshot diffing. Requires
> **Immich ≥ 2.7.5**.

## Configuration

All configuration is via environment variables (typically set in Docker).

| Env var | Required | Default | Meaning |
|---|---|---|---|
| `IMMICH_TOKEN` | yes | — | Immich API key (sent as the `x-api-key` header) |
| `IMMICH_PRIVATE_URL` | yes | — | Internal Immich base URL, e.g. `http://immich_server:2283` |
| `IMMICH_PUBLIC_URL` | yes | — | Public Immich URL for notification links, e.g. `https://photos.example.com` |
| `NTFY_INTERNAL_URL` | yes | — | Internal ntfy base URL, e.g. `http://ntfy:80` |
| `NTFY_PUBLISHER_USERNAME` | yes | — | ntfy account used to publish (HTTP Basic auth) |
| `NTFY_PUBLISHER_PASSWORD` | yes | — | password for that account |
| `PERIODIC_CHECK_INTERVAL_MINUTES` | no | `15` | how often to poll (minutes, ≥ 1) |
| `DEFAULT_LANGUAGE` | no | `en` | language for everyone unless overridden (e.g. `cs`) |
| `USER_LANGUAGES` | no | — | per-person overrides by email, e.g. `david.k@example.com=cs,jane@example.com=en` |
| `LOCALES_DIR` | no | bundled `locales/` | directory of `<lang>.json` translation files |
| `NTFY_ICON_URL` | no | — | optional icon URL shown on notifications |
| `DB_PATH` | no | `/data/state.db` | SQLite state file (mount a volume here) |
| `FORCE_FULL_SCAN_EVERY` | no | `8` | every Nth run, re-scan every album (self-heals missed change signals) |
| `RECENCY_MULTIPLIER` | no | `3` | recency window = this × the interval (older additions are recorded but not notified) |
| `HTTP_TIMEOUT_S` | no | `30` | per-request HTTP timeout (seconds) |
| `HTTP_RETRIES` | no | `3` | total HTTP attempts per request (incl. the first) |
| `TZ` | no | `UTC` | affects log timestamps only (change detection is always UTC) |
| `LOG_LEVEL` | no | `INFO` | logging level (unknown values fall back to `INFO`) |

## Notifications

Two notification types (message text comes from the locale files):

| Situation | en | cs |
|---|---|---|
| One person added photos | `Bob added new photos to "Trip".` | `Bob přidal(a) nové fotky do alba „Trip“.` |
| Several people added photos | `More photos were added to "Trip".` | `Do alba „Trip“ byly přidány nové fotky.` |
| You were added to an album | `You have been added to "Trip".` | `Byli jste přidáni do alba „Trip“.` |

Tapping a notification opens the album in `IMMICH_PUBLIC_URL`. Each person subscribes to
their own topic on their ntfy server/app (the topic shown in the startup log).

## Languages

Immich does **not** expose a per-user language via its API, so language is configured
here: `DEFAULT_LANGUAGE` for everyone, with optional per-person `USER_LANGUAGES`
overrides (keyed by email). To add a language, drop a `locales/<lang>.json` file with
the same keys as `locales/en.json`. Currently bundled: **English** (`en`) and
**Czech** (`cs`).

## Deployment (Docker)

```yaml
services:
  immich-user-notify:
    image: ghcr.io/OWNER/immich-user-notify:latest   # replace OWNER with your GitHub user/org
    container_name: immich_user_notify
    restart: unless-stopped
    depends_on: [ntfy]
    networks: [home-docker-net]
    environment:
      TZ: ${TZ}
      IMMICH_TOKEN: ${IMMICH_API_KEY}
      IMMICH_PRIVATE_URL: http://immich_server:2283
      IMMICH_PUBLIC_URL: https://photos.example.com
      NTFY_INTERNAL_URL: http://ntfy:80
      NTFY_PUBLISHER_USERNAME: ${NTFY_PUBLISHER_USERNAME}
      NTFY_PUBLISHER_PASSWORD: ${NTFY_PUBLISHER_PASSWORD}
      PERIODIC_CHECK_INTERVAL_MINUTES: "15"
      DEFAULT_LANGUAGE: cs
    volumes:
      - /path/on/host/immich-user-notify:/data
```

**Prerequisites:**

1. The `NTFY_PUBLISHER_*` account needs **write** access to the per-user topics
   (e.g. `ntfy access <publisher> '*' write`).
2. Each person must be able to **read** their own topic and subscribe to it.
3. The `IMMICH_TOKEN` account must **own or be shared into** every album you want
   monitored (it can only see albums it has access to).

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # Windows; use source .venv/bin/activate on *nix
pip install -r requirements-dev.txt
pytest
```

Run locally against a scratch DB (set the env vars first):

```powershell
$env:DB_PATH = ".\state.db"
python main.py
```

The published image is built and pushed to `ghcr.io/<your-github-user-or-org>/immich-user-notify`
by the [`docker-publish`](.github/workflows/docker-publish.yml) GitHub Actions workflow on
push to `main` / a `v*` tag (the image name is derived automatically from the repository).

## Limitations / notes

- There is no Immich "added-to-album" timestamp, so adding a long-ago-uploaded photo may
  fall outside the recency window and not notify (it's still recorded as seen).
- Two different emails can sanitize to the same topic; this is surfaced in the startup
  log so you can spot it.
- Additions only: removals (photos or members) update local state silently and never notify.
