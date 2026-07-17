# Publishing images

## Purpose

How to build and publish firnline Docker images to Docker Hub. Covers manual
builds with `scripts/build-and-push.sh`, automated CI publishing via GitHub
Actions, the consumer compose file, and image architecture details.

## Prerequisites

- Docker with [buildx](https://docs.docker.com/build/buildx/) support (Docker
  Desktop 4.19+ or `docker-buildx` plugin on Linux).
- A [Docker Hub](https://hub.docker.com/) account.
- `docker login` completed:
  ```bash
  docker login
  ```

## Images

Six images are built and published. Each has its own Dockerfile in the monorepo:

| Image name | Dockerfile |
|---|---|
| firnline-schema | packages/firnline-schema/Dockerfile |
| apid | services/apid/Dockerfile |
| ingestd | services/ingestd/Dockerfile |
| triggerd | services/triggerd/Dockerfile |
| effectd | services/effectd/Dockerfile |
| webui | services/webui/Dockerfile |

`apid` bundles four components (captured, queryd, indexed, mcpd) into a single
container behind one port. All other images are single-service containers.

## Manual build and push

The `scripts/build-and-push.sh` script builds all six images for multiple
architectures and pushes them to a registry in one invocation.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `REGISTRY` | `docker.io/firnline` | Registry prefix applied to all image tags. Change to your own Docker Hub namespace (e.g. `docker.io/yourorg`) when publishing to a personal or organisation account. |
| `VERSION` | auto-detected from `pyproject.toml` (`0.1.0`) | Tag applied to all images. Override with a specific version when publishing a release. |
| `PLATFORMS` | `linux/amd64,linux/arm64` | Comma-separated target platforms for the multi-arch build. Pass a single platform (e.g. `linux/amd64`) for faster local testing. |
| `TAG_LATEST` | `true` | Set to `false` to skip pushing the `latest` tag. Use this for pre-release or test builds. |

### Usage examples

Default invocation — publish the current version as `latest` for both
architectures:

```bash
bash scripts/build-and-push.sh
```

Override the version (e.g. for a release):

```bash
VERSION=v0.1.0-alpha bash scripts/build-and-push.sh
```

Single-platform build for local smoke testing (skips push):

```bash
PLATFORMS=linux/amd64 bash scripts/build-and-push.sh
```

Skip the `latest` tag (pre-release or CI snapshot):

```bash
TAG_LATEST=false bash scripts/build-and-push.sh
```

Publish to a personal Docker Hub namespace:

```bash
REGISTRY=docker.io/myuser bash scripts/build-and-push.sh
```

## Automated CI (GitHub Actions)

The `.github/workflows/docker-publish.yml` workflow builds and pushes all six
images on every `v*` tag push. No manual invocation is needed once the workflow
is configured.

### Required GitHub Secrets

Set these in the repository's **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `DOCKERHUB_USERNAME` | Your Docker Hub username. |
| `DOCKERHUB_TOKEN` | A Docker Hub access token (not your password). |

### Creating a Docker Hub access token

1. Go to [Docker Hub Account Settings](https://hub.docker.com/settings/security).
2. Click **Security** in the left sidebar.
3. Click **New Access Token**.
4. Give it a descriptive name (e.g. `firnline-ci`).
5. Set permissions to **Read & Write**.
6. Copy the generated token immediately — it is shown only once.

Paste the token value into the `DOCKERHUB_TOKEN` secret and your username into
`DOCKERHUB_USERNAME`.

### Release workflow

```
git tag -a v0.1.0-alpha -m "firnline v0.1.0-alpha"
git push origin main --tags
```

The workflow triggers on the `v*` tag, builds all six images for
`linux/amd64` and `linux/arm64`, and pushes them to Docker Hub with both
the version tag and the `latest` tag.

> **Note:** The workflow uses `docker/build-push-action` with the `buildx`
> driver. No special runner configuration is required — GitHub's `ubuntu-latest`
> runner supports QEMU-based multi-arch builds out of the box.

## Consumer compose file

For users who want to run firnline without building from source, the repository
provides `compose.example.yaml` at the repo root. This is the production-facing
compose file that uses pre-built images instead of local `build:` directives.

### Differences from the developer compose

| Aspect | `compose.yaml` (developer) | `compose.example.yaml` (consumer) |
|---|---|---|
| Source checkout | Required — builds from monorepo | Not needed |
| Service definitions | `build:` directives with Dockerfiles | `image:` directives pulling from Docker Hub |
| Image tags | `firnline/xxx:local` | `firnline/xxx:${VERSION}` |
| Dependency | Source files must be present | Only `.env` needed |
| Bootstrap | Inline heredoc in compose | External `scripts/bootstrap.sh` baked into the `firnline-schema` image |

### Consumer quickstart

```bash
# 1. Download the consumer compose file and env template
curl -O https://raw.githubusercontent.com/BaLion29/firnline/main/compose.example.yaml
curl -O https://raw.githubusercontent.com/BaLion29/firnline/main/.env.example

# 2. Configure secrets
cp .env.example .env && vim .env    # set the 4 required values

# 3. Start
docker compose -f compose.example.yaml up -d
```

The four required `.env` values are documented in
[Deployment](deployment.md#step-1-clone-and-configure).

### Pinning versions

Two env vars in `compose.example.yaml` control which images are pulled:

| Variable | Default | Description |
|---|---|---|
| `FIRNLINE_IMAGE_REGISTRY` | `docker.io/firnline` | Container registry prefix for all images. |
| `FIRNLINE_VERSION` | `latest` | Image tag for all six services. |

Pin to a specific release to avoid unexpected upgrades:

```env
FIRNLINE_VERSION=v0.1.0-alpha
```

## Image architecture

All six images share the same build architecture:

- **Multi-arch**: built for `linux/amd64` and `linux/arm64` via Docker
  buildx. QEMU emulation is used in CI; native builds work locally when the
  host arch matches the target.
- **Two-stage builds**: 
  1. **Builder** — `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`. Uses
     `uv sync --frozen --no-dev` to install per-service dependencies and
     builds first-party extension wheels into `/app/wheels/`.
  2. **Runtime** — `python:3.12-slim-bookworm`. Copies only the `.venv`,
     source, and wheels from the builder stage. No build toolchain or
     dev dependencies in the final image.
- **Non-root user**: every image runs as UID 1000. The runtime user is
  created explicitly (`useradd -m -u 1000`) and owns all copied files
  via `--chown`.
- **Schema modules** are baked into the `firnline-schema` image. The
  `schema/modules/` directory does not need to be bind-mounted at runtime
  when using consumer images — the bootstrap container references the
  baked-in schema.
- **First-party extension wheels** (from `extensions/`) are baked into all
  service images under `/extensions/`. The shared entrypoint script
  (`docker/entrypoint.sh`) installs extensions from this directory into
  the `firnline_ext_venv` overlay volume. The `webui` image does not bake
  extension wheels.

## Related documents

- [Deployment](deployment.md) — production deployment guide for consumers
- [../development/release-process.md](../development/release-process.md) — versioning, tags, and release checklist
- [../reference/configuration.md](../reference/configuration.md) — complete env-var reference
- [Backup and restore](backup-and-restore.md) — backup procedure before upgrades
