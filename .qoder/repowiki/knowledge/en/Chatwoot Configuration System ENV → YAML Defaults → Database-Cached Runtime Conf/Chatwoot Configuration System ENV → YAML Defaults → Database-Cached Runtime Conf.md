---
kind: configuration_system
name: 'Chatwoot Configuration System: ENV → YAML Defaults → Database-Cached Runtime Config'
category: configuration_system
scope:
    - '**'
source_files:
    - lib/global_config.rb
    - lib/config_loader.rb
    - lib/global_config_service.rb
    - app/models/installation_config.rb
    - config/application.rb
    - config/app.yml
    - config/installation_config.yml
    - config/features.yml
    - .env.example
    - config/environments/production.rb
    - config/environments/development.rb
    - config/environments/test.rb
    - config/environments/staging.rb
---

## Overview

Chatwoot uses a layered configuration system combining Rails' built-in mechanisms with a custom runtime configuration store backed by PostgreSQL and Redis:

1. **Environment variables** (`.env`, process env) — loaded via `Dotenv::Rails.load` in `config/application.rb`; used for secrets, infrastructure wiring, and APM agent bootstrapping.
2. **YAML defaults** — static defaults in `config/*.yml` (`app.yml`, `installation_config.yml`, `features.yml`, plus per-environment files under `config/environments/`).
3. **Runtime installation configs** — persisted in the `installation_configs` table (`InstallationConfig` model), read from Redis cache via `GlobalConfig`, reconciled against YAML defaults by `ConfigLoader`.
4. **Feature flags** — declared in `config/features.yml`, synced into `InstallationConfig` as `ACCOUNT_LEVEL_FEATURE_DEFAULTS` (a JSON array of `{name, enabled}` records).

## Key Files and Packages

- `lib/global_config.rb` — Redis-backed cache reader/writer for installation configs; keys prefixed `GLOBAL_CONFIG` under versioned namespace `V1:GLOBAL_CONFIG:*`; falls back to `InstallationConfig.find_by(name:)` when cache misses; typecasts boolean fields using `ActiveRecord::Type::Boolean.new.cast` based on schema in `installation_config.yml`.
- `lib/config_loader.rb` — reconciliation engine run at boot; reads `config/installation_config.yml` and `config/features.yml`, upserts missing or changed rows into `InstallationConfig`, and merges account-level feature defaults.
- `app/models/installation_config.rb` — ActiveRecord model storing installation-wide settings; `serialized_value` column is YAML-serialized `HashWithIndifferentAccess`; exposes `value` getter/setter wrapping `{ value: ... }`; validates SAML SSO cannot be disabled while SAML users exist; marks certain keys (`CAPTAIN_OPEN_AI_*`, `LANGFUSE_*`, `OTEL_PROVIDER`) as restart-required.
- `lib/global_config_service.rb` — convenience wrapper providing `load(config_key, default)` with backward compatibility: if a key is absent from DB/Redis, it falls back to `ENV.fetch(config_key)` and migrates the value into `InstallationConfig` so future reads come from the canonical store.
- `config/application.rb` — loads `.env` via `Dotenv::Rails.load` before any other code; conditionally requires Datadog/ElasticAPM/Scout/NewRelic/Sentry/Judoscale based on env vars; exposes `Chatwoot.config` aliasing `Rails.configuration.x` (from `config_for(:app)`); defines `Chatwoot.redis_ssl_verify_mode`, `encryption_configured?`, `mfa_enabled?` helpers.
- `config/app.yml` — per-environment shared YAML (currently only `version`) loaded via `config_for(:app)`.
- `config/installation_config.yml` — ~700-line catalog of all installable settings (branding, channels, Captain AI, OAuth providers, Stripe, Slack, Shopify, TikTok, Google OAuth, SAML, Cloudflare, APNs VoIP, Langfuse, etc.) with `name`, `value`, `display_title`, `description`, `locked`, `premium`, `type`, `options` metadata.
- `config/features.yml` — feature flag registry (~326 entries) with `name`, `display_name`, `enabled`, optional `column` (defaults to `feature_flags`, newer ones use `feature_flags_ext_1`), `help_url`, `chatwoot_internal`, `premium`, `deprecated`, `hidden`.
- `config/environments/*.rb` — Rails environment overrides (development/production/staging/test).
- `.env.example` — documented template of all supported environment variables (DB, Redis, SMTP, storage, social channels, APM, Rack Attack, Sidekiq, mobile push, etc.).

## Architecture and Conventions

### Layering / Precedence

The effective precedence is:

1. Process environment variables (highest priority — used directly by initializers and services).
2. `GlobalConfig.get(...)` / `GlobalConfigService.load(...)` — reads from Redis first, then `InstallationConfig` DB row, with `GlobalConfigService.load` falling back to `ENV` for migration support.
3. `ConfigLoader` reconciles `config/installation_config.yml` defaults into the DB on boot (only creating/updating missing or changed rows unless `reconcile_only_new: false`).
4. `config/features.yml` defaults are merged into `ACCOUNT_LEVEL_FEATURE_DEFAULTS` in `InstallationConfig`.
5. Per-environment `config/environments/*.rb` and `config/*.yml` files provide Rails framework defaults.

### Cache Strategy

`GlobalConfig` caches each config key in Redis under `V1:GLOBAL_CONFIG:<key>` with a 1-day TTL (`DEFAULT_EXPIRY = 1.day`). On write, `InstallationConfig#after_commit :clear_cache` invalidates the entire `GLOBAL_CONFIG` namespace via `$alfred.with { |conn| conn.scan_each(match: "#{VERSION}:#{KEY_PREFIX}:*") }.del(...)`. This means writes are O(n) cache invalidations but reads are single Redis GETs.

### Type System

`installation_config.yml` declares a `type` per field (`text`, `boolean`, `secret`, `code`, `number`, `select`). `GlobalConfig.typecast_config` re-casts values retrieved from Redis using `ActiveRecord::Type::Boolean.new.cast` when the schema says `boolean`. Secret-typed configs are marked for redaction in the dashboard UI.

### Feature Flags

Feature flags are defined centrally in `config/features.yml` and stored per-account in `Account.feature_flags` (bitset columns). The comment header explicitly forbids reordering existing entries and mandates that new flags go into `feature_flags_ext_1` once the original 63-slot column is full. `ConfigLoader.reconcile_feature_config` merges these into `ACCOUNT_LEVEL_FEATURE_DEFAULTS` in `InstallationConfig` (locked=true, meaning not editable via Super Admin).

### Migration Path

`GlobalConfigService.load` provides a one-way migration bridge: if a config key is not present in DB/Redis, it reads from `ENV`, creates an `InstallationConfig` row, and clears the cache so subsequent reads hit the canonical store. The TODO comment indicates this fallback will be deprecated later.

### Secrets Handling

Secrets flow through two paths:
- Infrastructure secrets (DB, Redis, SMTP, APM agents) are consumed directly from `ENV` in `config/initializers/*.rb`.
- Application secrets (OAuth clients, API keys, webhooks) are declared in `installation_config.yml` with `type: secret` and managed through the `InstallationConfig` / `GlobalConfig` pipeline.

## Conventions and Constraints

- **Do not reorder feature flags**: `config/features.yml` header states "DO NOT change the order of features EVER" because bit positions are persisted per-column; new flags must append to `feature_flags_ext_1`.
- **Locked configs**: `installation_config.yml` entries without explicit `locked: false` default to `locked: true` (enforced by `InstallationConfig#set_lock` before_validation), hiding them from the Super Admin UI.
- **Restart-required configs**: `InstallationConfig::RESTART_REQUIRED_CONFIG_KEYS` lists keys whose changes require a process restart (Captain LLM keys, Langfuse keys, OTEL provider).
- **SAML SSO guard**: `InstallationConfig#validate :saml_sso_users_check` prevents disabling `ENABLE_SAML_SSO_LOGIN` when any `User` has `provider == 'saml'`.
- **Default scope ordering**: `InstallationConfig` uses `default_scope { order(created_at: :desc) }` to surface the latest revision of each config name.
- **Env-driven feature toggles**: APM agents and infrastructure components are conditionally required in `config/application.rb` only when their corresponding `ENV` var is present (`DD_TRACE_AGENT_URL`, `ELASTIC_APM_SECRET_TOKEN`, `SCOUT_KEY`, `NEW_RELIC_LICENSE_KEY`, `SENTRY_DSN`, `JUDOSCALE_URL`).
- **Redis SSL verify mode**: `Chatwoot.redis_ssl_verify_mode` returns `OpenSSL::VERIFY_NONE` only when `REDIS_OPENSSL_VERIFY_MODE == 'none'`, otherwise `VERIFY_PEER`.
- **Active Record encryption gating**: MFA/2FA is enabled only when `ACTIVE_RECORD_ENCRYPTION_PRIMARY_KEY`, `_DETERMINISTIC_KEY`, and `_KEY_DERIVATION_SALT` are all set (`Chatwoot.encryption_configured?`).
- **ConfigLoader reconcile modes**: `reconcile_only_new: true` (default) preserves existing user-modified values and only adds new ones; `false` overwrites existing values with defaults.