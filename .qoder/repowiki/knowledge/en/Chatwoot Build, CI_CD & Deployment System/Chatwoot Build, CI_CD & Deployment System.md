---
kind: build_system
name: Chatwoot Build, CI/CD & Deployment System
category: build_system
scope:
    - '**'
source_files:
    - Makefile
    - .circleci/config.yml
    - .circleci/setup_chatwoot.sql
    - docker/Dockerfile
    - docker-compose.yaml
    - docker-compose.production.yaml
    - docker-compose.test.yaml
    - Procfile
    - Procfile.dev
    - Procfile.test
    - Procfile.tunnel
    - Rakefile
    - deployment/setup_20.04.sh
    - deployment/nginx_chatwoot.conf
    - deployment/chatwoot.target
    - deployment/chatwoot-web.1.service
    - deployment/chatwoot-worker.1.service
    - VERSION_CW
    - package.json
    - Gemfile
---

## Overview

Chatwoot is a Rails + Vue/JS monorepo whose build and deployment surface spans several layers: a local `Makefile` for developer workflows, a multi-stage Dockerfile for container images, Compose files for dev/prod environments, a CircleCI pipeline orchestrating linting, frontend tests, backend tests, coverage aggregation, and an on-host installer (`deployment/setup_20.04.sh`) that provisions systemd services. The Ruby runtime is pinned to Ruby 3.4.4 with Bundler 2.5.16; the Node runtime is pinned to Node 24.22.1 with pnpm 10.2.0.

## Toolchain & Version Pinning

- **Ruby**: `ruby:3.4.4-alpine3.21` in Docker, `rvm install "3.4.4"` in CI, `.ruby-version`, Bundler 2.5.16 installed via `gem install bundler -v 2.5.16`.
- **Node/pnpm**: `node:24.22.1-alpine` as a separate stage, `node/install: node-version: '24.22.1'` and `node/install-pnpm: version: '10.2.0'` in CircleCI, `engines.node = "24.x"` / `engines.pnpm = "10.x"` in `package.json`, and `packageManager: "pnpm@10.2.0+sha512..."` lockfile pin.
- **Databases**: PostgreSQL 16 (with pgvector) via `pgvector/pgvector:pg16`; Redis via `redis:alpine`.
- **Search**: OpenSearch 2.11.0 installed inline in the CI backend-tests job (`wget https://artifacts.opensearch.org/releases/bundle/opensearch/2.11.0/opensearch-2.11.0-linux-x64.tar.gz`).
- **Version source of truth**: `VERSION_CW` contains `4.19.1`, mirrored by `package.json` `version: "4.19.1"`. A `.git_sha` file is generated at image build time (`git rev-parse HEAD > /app/.git_sha`) and also written during the Heroku-style `release` process (`echo $SOURCE_VERSION > .git_sha`).

## Local Development Workflow (`Makefile`)

The Makefile exposes:
- `setup` — installs bundler, runs `bundle install`, then `pnpm install`.
- Database tasks: `db_create`, `db_migrate`, `db_seed`, `db_reset`, `db` (which delegates to `rails db:chatwoot_prepare`).
- `server` — starts Rails on `0.0.0.0:3000`.
- `run` / `force_run` / `force_run_tunnel` — launch processes via Overmind against `Procfile.dev` or `Procfile.tunnel`, with port cleanup for 3000/3036.
- `debug` / `debug_worker` — attach debugger sessions to Overmind-managed processes.
- `docker` — builds the production image via `docker build -t chatwoot -f ./docker/Dockerfile .`.

All Rake/Rails commands are invoked through `RAILS_ENV=$(RAILS_ENV) bundle exec rails ...`, defaulting to `development`.

## Container Image (`docker/Dockerfile`)

A two-stage Alpine-based build:

1. **`pre-builder` stage** (`ruby:3.4.4-alpine3.21`):
   - Installs system deps (`openssl`, `tar`, `build-base`, `tzdata`, `postgresql-dev`, `postgresql-client`, `xz`, `vips`, etc.).
   - Copies Node 24.22.1 from a sibling `node:24.22.1-alpine` stage so musl-compatible native gems (grpc, protobuf) can compile.
   - Runs `bundle install` (excluding development/test gems when `RAILS_ENV=production`) and `pnpm i`.
   - Precompiles assets via `rake assets:precompile` when `RAILS_ENV=production`, then strips `spec`, `node_modules`, `tmp/cache`.
   - Writes `.git_sha` from `git rev-parse HEAD`.

2. **Final stage** (`ruby:3.4.4-alpine3.21`):
   - Installs only runtime deps (`postgresql-client`, `imagemagick`, `vips`).
   - Sets `VIPS_BLOCK_UNTRUSTED=1` to restrict libvips image loaders.
   - Copies `/gems` and `/app` from pre-builder, plus `.git_sha`.
   - Exposes port 3000.

Build args allow overriding `BUNDLE_WITHOUT`, `RAILS_ENV`, `RAILS_SERVE_STATIC_FILES`, `NODE_OPTIONS`, `EXECJS_RUNTIME`, and `BUNDLE_FORCE_RUBY_PLATFORM`. The production image sets `EXECJS_RUNTIME=Disabled` and `RAILS_SERVE_STATIC_FILES=true`.

## Compose Environments

- **Development** (`docker-compose.yaml`): four application services — `rails` (Puma), `sidekiq`, `vite` (dev server on 3036), plus `postgres`, `redis`, `mailhog`. Uses per-service Dockerfiles under `docker/dockerfiles/rails.Dockerfile` and `docker/dockerfiles/vite.Dockerfile` with bind-mounted volumes for hot reload.
- **Production** (`docker-compose.production.yaml`): pulls `chatwoot/chatwoot:latest`, mounts persistent volumes for storage/postgres/redis, binds ports to `127.0.0.1` only, and sets `INSTALLATION_ENV=docker`.
- **Test** (`docker-compose.test.yaml`): used by CI test jobs.

## Process Model (`Procfile*`)

- `Procfile` (Heroku-style): `release` runs `POSTGRES_STATEMENT_TIMEOUT=600s bundle exec rails db:chatwoot_prepare && echo $SOURCE_VERSION > .git_sha`; `web` boots Puma; `worker` boots Sidekiq with `config/sidekiq.yml`.
- `Procfile.dev`, `Procfile.test`, `Procfile.tunnel` — variant process trees consumed by Overmind locally.

## CI/CD Pipeline (`.circleci/config.yml`)

CircleCI 2.1 workflow on `ubuntu-2204:2024.05.1` machines with `resource_class: large`:

| Job | Purpose |
|---|---|
| `lint` | Installs Ruby 3.4.4 + Node 24.22.1 + pnpm 10.2.0, runs `bundle audit update && bundle audit check -v`, RuboCop (`rubocop --parallel`), ESLint (`pnpm run eslint`), and validates the OpenAPI spec (`rake swagger:build` then `openapi-generator-cli validate -i swagger/swagger.json`). Fails if `swagger/swagger.json` is out of sync with YAML sources. |
| `frontend-tests` | Installs Node/pnpm, runs `pnpm run test:coverage` (Vitest), persists `coverage/frontend/lcov.info`. |
| `backend-tests` | Parallelized across 18 nodes using round-robin distribution over `find spec -name '*_spec.rb'`; installs Postgres 16 + pgvector, downloads and configures OpenSearch 2.11.0, seeds DB via `.circleci/setup_chatwoot.sql`, runs `bundle exec rails db:chatwoot_prepare`, then executes RSpec with `--require coverage_helper --format RspecJunitFormatter`. |
| `coverage` | Aggregates coverage artifacts from workspace, publishes frontend LCOV via qlty-orb, stores artifacts. |
| `build` | Placeholder job kept for GitHub required-check compatibility. |

Workflow order: `lint` → `coverage` → `build`; `frontend-tests` and `backend-tests` run in parallel and feed into `coverage`.

## On-Host Installation (`deployment/setup_20.04.sh`)

The self-contained installer script (versioned at `CWCTL_VERSION="3.5.1"`) supports Ubuntu 20.04/22.04/24.04 LTS. It accepts options `--install`, `--upgrade`, `--web-only`, `--worker-only`, `--convert`, `--ssl`, `--logs`, `--restart`, `--console`, `--debug`, `--help`, `--version`, and manages:
- System dependency installation.
- PostgreSQL setup with a random password.
- SSL certificate provisioning via Let's Encrypt.
- Nginx configuration (`nginx_chatwoot.conf`).
- Systemd unit files (`chatwoot.target`, `chatwoot-web.1.service`, `chatwoot-worker.1.service`).
- Chatwoot binary installation and service management.

## Rake & Task Loading

`Rakefile` requires `config/application` and conditionally loads enterprise rake tasks via `enterprise/tasks_railtie.rb` if present, then calls `Rails.application.load_tasks`. This means all custom Rake tasks live under `lib/tasks/*.rake` and are auto-discovered.

## Frontend Build & Test Scripts (`package.json`)

- `eslint` / `eslint:fix` — lints `app/**/*.{js,vue}`.
- `test` / `test:watch` / `test:coverage` — Vitest runner with `TZ=UTC`.
- `build:sdk` — Vite library build (`vite.lib.config.ts`).
- `analyze:bundle:*` — bundle-size analysis via `vite.sdk.analyze.config.mts` and `vite.widget.analyze.config.mts`.
- `size` — size-limit checks: widget JS ≤ 300 KB, SDK JS ≤ 40 KB.
- `prepare` — installs Husky hooks; `pre-push` runs `bin/validate_push`.
- `start:dev` / `start:test` — Foreman process managers against `Procfile.dev` / `Procfile.test`.

## Key Conventions & Rules

1. **Runtime versions are pinned everywhere** — Ruby 3.4.4, Bundler 2.5.16, Node 24.22.1, pnpm 10.2.0 appear consistently in Dockerfile, CircleCI, and `package.json` engines/packageManager fields.
2. **OpenAPI spec must stay in sync** — CI enforces that `swagger/swagger.json` matches the YAML sources; any drift fails the build (`if [[ \`git status swagger/swagger.json --porcelain\` ]]` then exit 1).
3. **Database bootstrap uses a single task** — both local Makefile and CI call `rails db:chatwoot_prepare` rather than raw `db:migrate`.
4. **Container images are multi-stage Alpine builds** — compilation happens in a `pre-builder` stage with full toolchains; the final image only carries runtime dependencies and precompiled assets.
5. **Image metadata includes commit SHA** — `.git_sha` is generated at build time and exposed to the running app.
6. **Security hardening in images** — `VIPS_BLOCK_UNTRUSTED=1` restricts libvips loaders; `EXECJS_RUNTIME=Disabled` disables Node execution in production images.
7. **CI splits work by concern** — linting, frontend tests, and backend tests run as separate jobs; backend tests are parallelized across 18 nodes with round-robin spec distribution.
8. **Coverage is aggregated post-run** — frontend and backend coverage outputs are persisted to the CircleCI workspace and merged in the `coverage` job.
9. **On-host deployments use systemd units** — the installer generates `chatwoot.target` plus `chatwoot-web.1.service` and `chatwoot-worker.1.service` managed by systemd.
10. **Environment variables drive behavior** — `RAILS_ENV`, `INSTALLATION_ENV`, `NODE_ENV`, `REDIS_URL`, `POSTGRES_*`, `OPENSEARCH_URL` are the primary configuration surface, templated from `.env.example`.