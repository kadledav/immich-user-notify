# immich-user-notify

A small self-running service that watches the [Immich](https://immich.app) albums
your account can see and sends a **per-user** [ntfy](https://ntfy.sh) push when
photos or members are added — notifying everyone who can see the album **except**
the person who made the change.

Targets the **Immich 3.x** API (developed against **3.0.0**). Immich 3.0 reworked the
album API — `owner`/`ownerId` and `assets` are gone from album responses — so this
release does not work with Immich 2.x, and the older 2.x-era release does not work with
Immich 3.x. See [Upgrading from an Immich 2.x setup](#upgrading-from-an-immich-2x-setup).

Inspired by [pman07/Immich_Notify](https://github.com/pman07/Immich_Notify), but a fresh,
independent implementation with a different design:

- **No per-album setup.** It discovers all albums automatically — nothing to configure per album.
- **Per-user, not one shared topic.** Each person gets their own ntfy topic derived from their email, and the person who *caused* a change isn't pinged about their own action.

## Quick start

1. **Immich API key** — in Immich, *Account Settings → API Keys*, create a key with the
   `album.read` and `user.read` permissions, from an account that can see every album you
   want monitored. Needs an **Immich 3.x** server.
2. **ntfy publisher** — on your ntfy server, create the account this app publishes with and
   allow it to publish to the `immich-*` topics:
   `ntfy user add immich-notify` then `ntfy access immich-notify 'immich-*' wo`.
3. **Configure** — `cp .env.example .env` and fill in the Immich token + URLs and the ntfy
   publisher credentials.
4. **Run** — `docker compose -f docker-compose.example.yml up -d`, or fold the
   `immich-user-notify` service into your existing stack (see
   [`docker-compose.example.yml`](docker-compose.example.yml)).
5. **Subscribe** — each person subscribes to **their own topic** in the ntfy app. The topic
   is `immich-` + the part of their email before `@` (lowercased, other characters → `-`).
   The container logs the full `email → topic` map on startup. Examples:
   - `david.k@example.com` → **`immich-david-k`**
   - `jana@example.com` → **`immich-jana`**

   (With ntfy's default deny-all, also grant each person read access to their topic, e.g.
   `ntfy access alice immich-alice ro`.)

> **ntfy must be reachable by your users' devices.** A LAN-only ntfy only delivers at home;
> for notifications anywhere, expose ntfy over **HTTPS** (a reverse proxy such as Traefik —
> see [`docker-compose.example.yml`](docker-compose.example.yml)) or a VPN. **iOS** additionally
> needs a public HTTPS URL and `NTFY_UPSTREAM_BASE_URL=https://ntfy.sh` (for instant push via
> APNS). `immich-user-notify` itself only talks to ntfy internally and is **not** exposed.

Within one poll interval, new photos and album shares start arriving as pushes.

## What gets notified

| Scenario | Who gets notified |
|---|---|
| Create + share a **new album** | each person it's shared with → "You have been added to …" (the owner/creator is not notified) |
| A new person is added to an **existing album** | only that newly added person |
| **New photo(s)** added to a tracked album | everyone who can see the album, **minus** the sole contributor (if all the new photos share one owner). |
| New member **and** new photos in the **same cycle** | the invited member gets **only** "You have been added …" — not also the "new photos" message |
| Photos/members **removed** | nobody (state is updated silently) |
| Albums that already existed on first run | nobody (baselined silently — see [How it works](#how-it-works)) |

Nobody who already had access is pinged about a share, and a freshly invited member is never spammed with the album's existing activity.

## How it works

Every `PERIODIC_CHECK_INTERVAL_MINUTES` it:

1. Lists albums (`GET /api/albums`) and, for any album whose `assetCount`/member count/
   `updatedAt` changed, fetches the detail (`GET /api/albums/{id}`).
2. Diffs the album's **per-contributor asset counts** (`contributorCounts`) and its
   member-ID set against a small local SQLite DB. Any contributor whose count *grew*
   added photos; the sum of those increases is how many.
3. Attribution comes straight from the server, which groups an album's assets by
   `asset.ownerId` — in Immich only an asset's owner can add it to an album, so this
   reliably identifies the contributor.
4. Sends notifications:
   - **New photos** → everyone who can see the album, **minus** the contributor,
     regardless of when the photos were originally uploaded. If a single person added
     them the message names them; if several people did, it stays anonymous.
   - **New member / new shared album** → only the newly added member
     (`You have been added to "<album>"`). No one else is told that someone joined, and a
     member invited this cycle gets *only* this access message — not also a "new photos"
     notification for the album's existing contents.

Safety details:

- **Bootstrap baseline** — on the app's **first run** it records a one-time timestamp
  and silently baselines every album that already exists. Those pre-existing albums
  never notify about their existing contents, so deploying against your library (or
  losing the DB) doesn't flood everyone.
- **New vs. pre-existing albums** — an album first seen *after* the bootstrap is treated
  as genuinely new only if its `createdAt` is later than the bootstrap; then its members
  get a "you have been added" notification. An old album that merely becomes visible to
  the account later (e.g. shared with it) stays silent, so you aren't spammed about an
  album's whole back-catalogue.
- **Nothing about the photos is stored.** The local DB holds album IDs, user IDs and
  per-user counts — no asset IDs, no file names.
- One ntfy topic per person, derived from their email: `immich-` followed by the part
  before `@`, with every character outside `[A-Za-z0-9_-]` replaced by `-`, lowercased.
  e.g. `david.k@example.com` → topic `immich-david-k`. **At startup the full
  `email → topic` map is logged** (with a warning on any collision) so you know exactly
  which topic each person must subscribe to. With a **non-admin** API key Immich's
  `/api/users` only returns the key's own account, so that map lists a single entry —
  use an admin account's key if you want to see the whole mapping. Everything else keeps
  working either way; recipients come from the album payload itself.

> Note: Immich exposes no "added-to-album" timestamp (only the asset's upload time),
> which is why detection relies on snapshot diffing rather than timestamps — that's
> also why adding an old photo to an album still notifies. `updatedAt` is a bonus
> change signal, not a guarantee: `assetCount`, the member count and
> `FORCE_FULL_SCAN_EVERY` are what make detection self-healing.
> Built for the **Immich 3.x** album API (verified against 3.0.0) and tied to it: the
> 3.0 API is not backward compatible with 2.x, and a future major Immich release may
> well break it again. The server version is logged on startup, with a warning if it
> isn't 3.x.

### Upgrading from an Immich 2.x setup

Pull the new image; the existing `state.db` migrates itself (the old per-asset table is
dropped and the album baseline is reset). **The first run after the upgrade sends no
notifications** — it silently re-records every album, exactly like a fresh install
against an existing library — and normal notifications resume on the next run. The API
key needs no new permissions.

## Configuration

All configuration is via environment variables (typically set in Docker).

| Env var | Required | Default | Meaning |
|---|---|---|---|
| `IMMICH_TOKEN` | yes | — | Immich API key, sent as `x-api-key` (needs `album.read` + `user.read` — see below) |
| `IMMICH_PRIVATE_URL` | yes | — | Internal Immich base URL, e.g. `http://immich_server:2283` |
| `IMMICH_PUBLIC_URL` | yes | — | Public Immich URL for notification links, e.g. `https://photos.example.com` |
| `NTFY_INTERNAL_URL` | yes | — | Internal ntfy base URL, e.g. `http://ntfy:80` |
| `NTFY_PUBLISHER_USERNAME` | yes | — | ntfy account used to publish (HTTP Basic auth) |
| `NTFY_PUBLISHER_PASSWORD` | yes | — | password for that account |
| `PERIODIC_CHECK_INTERVAL_MINUTES` | no | `15` | how often to poll (minutes, ≥ 1) |
| `DEFAULT_LANGUAGE` | no | `en` | language for everyone unless overridden (e.g. `cs`) |
| `USER_LANGUAGES` | no | — | per-person overrides by email, e.g. `david.k@example.com=cs,jane@example.com=en` |
| `LOCALES_DIR` | no | bundled `locales/` | directory of `<lang>.json` translation files |
| `NTFY_ICON_URL` | no | Immich logo | icon shown on notifications (a publicly reachable URL the phone can fetch) |
| `DB_PATH` | no | `/data/state.db` | SQLite state file (mount a volume here) |
| `FORCE_FULL_SCAN_EVERY` | no | `8` | every Nth run, re-scan every album (self-heals missed change signals) |
| `HTTP_TIMEOUT_S` | no | `30` | per-request HTTP timeout (seconds) |
| `HTTP_RETRIES` | no | `3` | total HTTP attempts per request (incl. the first) |
| `TZ` | no | `UTC` | affects log timestamps only (change detection is always UTC) |
| `LOG_LEVEL` | no | `INFO` | logging level (unknown values fall back to `INFO`) |

### Immich API key permissions

Create the key under **Account Settings → API Keys**. Only **read** scopes are needed
(the app never writes to Immich):

| Permission | Used for |
|---|---|
| `album.read` | List albums and read each album's per-contributor asset counts + shared members — the core of change detection. **Required.** |
| `user.read` | The startup `email → topic` mapping (lists users) and resolving a contributor's display name when they aren't in an album's member list. Pick `user.read`, **not** `adminUser.read` (that one is only for the `/admin/users` endpoints, which this app never calls). |

`album.read` is essential. Without `user.read` the app still detects changes and sends
notifications — recipient emails come from the album payload itself — but the startup
mapping log and the contributor-name fallback are skipped. Selecting **All** permissions
also works, it's just broader than necessary. Either way, the key's account must **own or
be shared into** every album you want monitored.

## Notifications

Two notification types (message text comes from the locale files):

| Situation | en | cs |
|---|---|---|
| One person added photos | `Bob added new photos to "Trip".` | `Bob přidal(a) nové fotky do alba „Trip“.` |
| Several people added photos | `More photos were added to "Trip".` | `Do alba „Trip“ byly přidány nové fotky.` |
| You were added to an album | `You have been added to "Trip".` | `Byli jste přidáni do alba „Trip“.` |

Tapping a notification opens the album in `IMMICH_PUBLIC_URL`. Each person subscribes to
their own topic on their ntfy server/app (the topic shown in the startup log).

### ntfy quirks worth knowing

- **ntfy needs to be reachable by the phones.** Expose it over HTTPS (reverse proxy) or a
  VPN; LAN-only delivers at home only. iOS instant push additionally needs a public HTTPS
  URL + `NTFY_UPSTREAM_BASE_URL=https://ntfy.sh`.
- **The notification icon is Android-only.** The Immich-logo icon (`NTFY_ICON_URL`) appears
  on Android; **on iOS, ntfy always uses its own app icon** — there is no per-message icon
  on iOS, so nothing this app sends can change that.
- **ntfy is deny-all by default.** The publisher account needs write access to the
  `immich-*` topics, and each person needs read access to their own topic (see
  [Quick start](#quick-start)).

## Languages

Immich does **not** expose a per-user language via its API, so language is configured
here: `DEFAULT_LANGUAGE` for everyone, with optional per-person `USER_LANGUAGES`
overrides (keyed by email). To add a language, drop a `locales/<lang>.json` file with
the same keys as `locales/en.json`. Currently bundled: **English** (`en`) and
**Czech** (`cs`).

## Deployment (Docker)

Use [`docker-compose.example.yml`](docker-compose.example.yml) — a ready-to-edit stack
(immich-user-notify + ntfy) with named volumes — together with [`.env.example`](.env.example).
To add it to an existing stack instead, copy just the `immich-user-notify` service and make
sure the container can reach both your Immich server (`IMMICH_PRIVATE_URL`) and ntfy
(`NTFY_INTERNAL_URL`). The published image is `ghcr.io/kadledav/immich-user-notify`,
or build it locally with `build: .`.

**Prerequisites:**

1. The `NTFY_PUBLISHER_*` account must be allowed to publish to the per-user topics, e.g.
   `ntfy access immich-notify 'immich-*' wo`.
2. Each person needs read access to their own topic and must subscribe to it, e.g.
   `ntfy access alice immich-alice ro` (ntfy defaults to deny-all).
3. The Immich server must be **3.x** (developed against 3.0.0); the version is logged on
   startup, with a warning if it isn't.
4. The `IMMICH_TOKEN` key needs the `album.read` and `user.read` permissions (see
   [Immich API key permissions](#immich-api-key-permissions)), and its account must
   **own or be shared into** every album you want monitored (it can only see albums it
   has access to).

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

The published image is built and pushed to `ghcr.io/kadledav/immich-user-notify`
by the [`docker-publish`](.github/workflows/docker-publish.yml) GitHub Actions workflow on
push to `main` / a `v*` tag.

## Limitations / notes

- Albums that already exist on the app's first run are baselined silently; their
  existing contents never notify (only changes made afterward do).
- An old album that becomes visible to the account *after* the first run (e.g. someone
  shares an existing album with it) is treated as pre-existing and stays silent, since
  Immich can't tell us whether its members are genuinely new.
- Two different emails can sanitize to the same topic; this is surfaced in the startup
  log so you can spot it.
- Additions only: removals (photos or members) update local state silently and never notify.
- Detection compares per-person photo counts, so if the *same* person removes and adds an
  equal number of photos within one poll interval the two cancel out and nothing is sent.
- Restoring a photo from the Immich trash looks like an addition.
- The counts Immich reports include archived/hidden assets while the album's `assetCount`
  does not, so adding an *already archived* photo may not trip the cheap change check;
  it is then picked up by the next full scan (at most
  `PERIODIC_CHECK_INTERVAL_MINUTES × FORCE_FULL_SCAN_EVERY` later).
- Album rows for albums later deleted in Immich are never pruned from the local DB.
