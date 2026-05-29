# immich-user-notify

A small Python service, packaged as a Docker image and published to GitHub
Container Registry (ghcr.io).

## Run locally

```bash
python main.py
```

## Run with Docker

```bash
docker build -t immich-user-notify .
docker run --rm immich-user-notify
```

## Pull the published image

```bash
docker pull ghcr.io/kadledav/immich-user-notify:latest
docker run --rm ghcr.io/kadledav/immich-user-notify:latest
```

## Publishing

Pushing to `main` (or a `v*` tag) triggers the
[`docker-publish`](.github/workflows/docker-publish.yml) GitHub Actions
workflow, which builds the image and pushes it to ghcr.io using the built-in
`GITHUB_TOKEN` — no secrets to configure.

After the **first** successful run, make the package public once:
**github.com/users/kadledav/packages → immich-user-notify → Package settings →
Change visibility → Public**.
