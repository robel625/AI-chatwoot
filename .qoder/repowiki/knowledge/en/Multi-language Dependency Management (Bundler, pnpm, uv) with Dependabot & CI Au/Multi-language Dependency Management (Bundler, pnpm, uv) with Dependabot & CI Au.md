---
kind: dependency_management
name: Multi-language Dependency Management (Bundler, pnpm, uv) with Dependabot & CI Auditing
category: dependency_management
scope:
    - '**'
source_files:
    - Gemfile
    - Gemfile.lock
    - .ruby-version
    - package.json
    - pnpm-lock.yaml
    - .dependabot/config.yml
    - .circleci/config.yml
    - .dockerignore
    - tests/playwright/package.json
    - services/eeu-ai/pyproject.toml
    - services/eeu-ai/uv.lock
---

## Overview

Chatwoot is a multi-language monorepo that manages dependencies through three separate package managers, each scoped to its language layer:

- **Ruby/Rails backend** — Bundler (`Gemfile` + `Gemfile.lock`)
- **JavaScript/Vue frontend** — pnpm (`package.json` + `pnpm-lock.yaml`)
- **EEU AI microservice** — uv (`services/eeu-ai/pyproject.toml` + `uv.lock`)

A fourth workspace under `tests/playwright/package.json` declares Playwright E2E test dependencies separately.

## Ruby Dependencies (Bundler)

- Source: `source 'https://rubygems.org'` in `Gemfile`.
- Ruby version pinned via both `.ruby-version` and `ruby '3.4.4'` in the Gemfile; CI installs RVM and `bundler -v 2.5.16` explicitly.
- Dependencies are grouped by environment using Bundler groups: `production`, `development`, `test`, and `development, test`. Some gems are loaded conditionally via `require: false` (e.g., `datadog`, `elastic-apm`, `newrelic_rpm`, `sentry-*`).
- A subset of gems use exact pinning (e.g., `rails '7.2.3.1'`, `sidekiq '~> 7.3.10'`, `twitty '~> 0.1.5'`), while others use loose ranges (`>= x.y.z`).
- No private registry or `BUNDLE_SOURCE` override is configured at the repo level; Docker ignores `.bundle` and `vendor/bundle` (see `.dockerignore`), so production builds rely on lockfile resolution against rubygems.org.
- Security auditing is enforced in CI via `bundle exec bundle audit update && bundle exec bundle audit check -v` (`.circleci/config.yml` line 101–103).

## JavaScript Dependencies (pnpm)

- Declared in root `package.json`; lockfile is `pnpm-lock.yaml`.
- Engine constraints: `"node": "24.x"`, `"pnpm": "10.x"`, plus an explicit `packageManager` field pinning `pnpm@10.2.0+sha512:...` for deterministic installs.
- CI uses the CircleCI orb `node/install-pnpm` with `version: '10.2.0'` and runs `pnpm i` as the install command.
- The `pnpm.overrides` section forces transitive dependency versions: `vite` → `6.4.2`, `vitest` → `3.0.5`, `minimatch@<4` → `3.1.5`, `minimatch@>=9.0.0 <9.0.7` → `9.0.9`, `rollup` → `>=4.59.0`. This is the primary mechanism for resolving conflicts between packages that pull different major versions.
- Size budgets are declared under `size-limit` for `widget-*.js` (300 KB) and `sdk.js` (40 KB).
- Husky pre-push hook runs `sh bin/validate_push` (defined in `package.json.husky.hooks.pre-push`).
- ESLint/Prettier linting is wired into `lint-staged` for staged JS/Vue files.

## Python Dependencies (uv)

- The EEU AI service under `services/eeu-ai/` declares dependencies in `pyproject.toml` with a corresponding `uv.lock` lockfile.
- No additional Python toolchain configuration was found at the repo root; this sub-service is self-contained.

## Automated Updates (Dependabot)

- `.dependabot/config.yml` configures two update jobs:
  - `ruby:bundler` on directory `/`, weekly schedule, reviewers `sony-mathew`, `sojan-official`, `subintp`, labels `dependencies` + `ruby`, `version_requirement_updates: auto`.
  - `javascript` on directory `/`, weekly schedule, reviewers `pranavrajs`, `nithindavid`, labels `dependencies` + `javascript`, `version_requirement_updates: auto`.
- No Python/uv update job is configured in Dependabot.

## CI Enforcement

CircleCI (`.circleci/config.yml`) enforces dependency integrity beyond just installing them:

1. **Swagger spec sync**: `rake swagger:build` must leave `swagger/swagger.json` unchanged (line 87–95).
2. **Bundle audit**: `bundle audit update && bundle audit check -v` fails the build on known CVEs (line 101–103).
3. **Rubocop**: `bundle exec rubocop --parallel` (line 106–108).
4. **ESLint**: `pnpm run eslint` (line 111–113).
5. **Frontend tests**: `pnpm run test:coverage` (line 128–130).

## Conventions Observed

- Each language ecosystem keeps its own manifest and lockfile at the top level (or per-subservice); there is no shared dependency graph across languages.
- Lockfiles are committed alongside manifests, ensuring reproducible installs in CI.
- Version pinning strategy is mixed: critical framework gems (Rails, Sidekiq, Vite, Vitest) are pinned to exact or tight ranges; utility gems often use `>=` ranges.
- Transitive dependency conflicts in the JS tree are resolved centrally via `pnpm.overrides` rather than per-package patches.
- No private gem registry or npm/pnpm registry proxy is configured in the repository; all sources resolve to public registries (rubygems.org, npm).
- Docker images exclude `node_modules` and `vendor/bundle` from the context, relying on CI to reinstall dependencies during build.