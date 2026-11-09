---
kind: logging_system
name: Rails Logger with Lograge Structured JSON and Sidekiq/Sentry Integration
category: logging_system
scope:
    - '**'
source_files:
    - config/initializers/lograge.rb
    - config/initializers/filter_parameter_logging.rb
    - config/environments/production.rb
    - config/environments/development.rb
    - config/initializers/sidekiq.rb
    - config/initializers/sentry.rb
    - lib/captain_response_dequeued_logger.rb
---

## Overview

Chatwoot uses the standard Rails logging stack (`ActiveSupport::Logger` / `Logger`) as its primary log producer, optionally enhanced by the **lograge** gem for structured HTTP request logs. Errors are additionally forwarded to **Sentry** (via `sentry-ruby`, `sentry-rails`, `sentry-sidekiq`) when a DSN is configured. There is no custom logger framework — all application code calls `Rails.logger.<level>` directly.

## Key Files

- `config/initializers/lograge.rb` — conditional lograge setup (gated on `LOGRAGE_ENABLED`).
- `config/initializers/filter_parameter_logging.rb` — sensitive-parameter redaction list.
- `config/environments/production.rb` — production logger sink, log level, tags, formatter.
- `config/environments/development.rb` — development logger sink and default `debug` level.
- `config/initializers/sidekiq.rb` — Sidekiq server logger configuration and dequeue logging middleware.
- `config/initializers/sentry.rb` — Sentry initialization (errors + optional tracing).
- `lib/captain_response_dequeued_logger.rb` — Sidekiq server middleware that logs Captain AI job dequeues.
- `Gemfile` / `Gemfile.lock` — declare `lograge`, `sentry-ruby`, `sentry-rails`, `sentry-sidekiq`.

## Architecture & Conventions

### Sinks and routing

- **Web process**: `config/logger` is set in `config/environments/production.rb`. When `RAILS_LOG_TO_STDOUT=true` (default), it writes to `$stdout` wrapped in `ActiveSupport::TaggedLogging` with the tag `:request_id`; otherwise it rotates files under `log/<env>.log` using `File#rotate(1, LOG_SIZE.megabytes)`.
- **Sidekiq worker process**: `config/initializers/sidekiq.rb` sets `config.server_middleware` to include `CaptainResponseDequeuedLogger` and an opt-in `ChatwootDequeuedLogger` (gated by `ENABLE_SIDEKIQ_DEQUEUE_LOGGER`). In production, Sidekiq's logger formatter is switched to `Sidekiq::Logger::Formatters::JSON` and default job logging is skipped via `skip_default_job_logging = true`.
- **HTTP request logs**: When `LOGRAGE_ENABLED=true`, lograge replaces Action Controller's logger output with JSON-formatted lines via `Lograge::Formatters::Json.new`. It adds a `custom_payload` block injecting `host`, `remote_ip`, and `user_id` (only for `Api::BaseController` requests where `current_user` is a `User`), strips `controller/action/format/id` from params via `custom_options`, and ignores `RoomChannel#update_presence` events through `ignore_custom`.
- **Errors to Sentry**: `config/initializers/sentry.rb` initializes Sentry only when `SENTRY_DSN` is present, enabling it in `%w[staging production]`. Exception classes `Rack::Timeout::RequestTimeoutException` and `MutexApplicationJob::LockAcquisitionError` are excluded. PII capture defaults to enabled unless `DISABLE_SENTRY_PII` is set.

### Log levels

- Production default: `LOG_LEVEL=info` (from `ENV.fetch('LOG_LEVEL', 'info')`).
- Development default: `LOG_LEVEL=debug`.
- Sidekiq production level is read from `ENV.fetch('LOG_LEVEL', 'info').upcase.to_s` and applied via `Logger.const_get(...)`.

### Structured fields

- Request-level structured fields come from lograge's `custom_payload`: `host`, `remote_ip`, `user_id`.
- Params are included via `custom_options` after stripping `controller`, `action`, `format`, `id`.
- All log lines are tagged with `request_id` via `config.log_tags = [:request_id]`.
- Sidekiq jobs use `Sidekiq.logger` (separate from `Rails.logger`) and emit JSON-formatted lines in production.

### Sensitive data handling

`filter_parameter_logging.rb` adds these parameter names to the filter list:

```
password, secret, _key, auth, crypt, salt, certificate, otp, access, private,
protected, ssn, install_url, otp_secret, otp_code, backup_code, mfa_token,
otp_backup_codes
```

Plus a regex that filters any key containing `token` except keys matching `website_token`.

### Usage patterns in application code

Across `app/` and `lib/`, logging is done by calling `Rails.logger.debug/info/warn/error/fatal` directly with string interpolation or exception objects. Common patterns include:

- Error paths: `Rails.logger.error "Error in ...: #{e.message}"` or `Rails.logger.error e`.
- Warning paths: `Rails.logger.warn "..."`.
- Info/debug paths: `Rails.logger.info "[Context] ..."` or `Rails.logger.debug { "..." }` (lazy block form used in `lib/active_storage/migrator.rb`).
- Prefixed context strings like `[IMAP::FETCH_EMAIL_SERVICE]`, `[INBOX HEALTH]`, `[Slack]`, `[EEU AI Gateway]` are commonly prepended to human-readable messages.

There is no centralized logger wrapper class; each caller decides the level and message shape.

## Rules Enforced by Configuration

1. **Lograge is opt-in**: The entire initializer is wrapped in `if ActiveModel::Type::Boolean.new.cast(ENV.fetch('LOGRAGE_ENABLED', false)).present?`, so without the env var, lograge is never required and request logs remain unstructured.
2. **Production stdout vs file sink is environment-driven**: `RAILS_LOG_TO_STDOUT` selects between `$stdout` and `log/<env>.log` rotation.
3. **Default log level per environment**: production defaults to `info`; development defaults to `debug`.
4. **Sensitive parameters are filtered**: The filter list plus the token regex are applied automatically by Rails' built-in parameter filtering.
5. **Sentry is disabled by default**: Only initialized when `SENTRY_DSN` is set, and only in staging/production environments.
6. **Sidekiq dequeue logging is opt-in**: `ChatwootDequeuedLogger` is added only when `ENABLE_SIDEKIQ_DEQUEUE_LOGGER` is truthy.
7. **Presence-channel WebSocket updates are suppressed from lograge**: `RoomChannel#update_presence` events are explicitly ignored via `ignore_custom`.