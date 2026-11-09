---
kind: error_handling
name: Error Handling — Custom Exceptions, Controller Middleware, and Exception Tracking
category: error_handling
scope:
    - '**'
source_files:
    - lib/custom_exceptions/base.rb
    - lib/custom_exceptions/account.rb
    - app/controllers/concerns/request_exception_handler.rb
    - app/controllers/application_controller.rb
    - lib/chatwoot_exception_tracker.rb
    - lib/exception_list.rb
    - config/initializers/custom_error_codes.rb
    - app/mailers/application_mailer.rb
---

## Overview

Chatwoot uses a layered Rails error-handling strategy built around three pillars:

1. **Domain-specific sentinel exceptions** under `lib/custom_exceptions/` that subclass `CustomExceptions::Base`.
2. **Controller-level middleware** (`RequestExceptionHandler`) that centralizes rescue_from handlers and normalizes JSON error responses.
3. **Centralized exception tracking** via `ChatwootExceptionTracker`, which logs to Rails logger and optionally forwards to Sentry when `SENTRY_DSN` is set.

## Key Files and Packages

- `lib/custom_exceptions/base.rb` — Base class for all domain errors; defines `to_hash`, `http_status` (default 403), and an `initialize(data)` contract.
- `lib/custom_exceptions/account.rb`, `inbox/`, `data_import/`, `pdf.rb`, `call_already_accepted.rb`, `whatsapp_contact_info_request_error.rb`, `invalid_announcement_audio.rb`, `custom_filter.rb` — Domain exception subclasses.
- `app/controllers/concerns/request_exception_handler.rb` — Central controller concern providing `rescue_from` hooks and response renderers.
- `app/controllers/application_controller.rb` — Includes `RequestExceptionHandler` and wires `around_action :handle_with_exception` as the global request wrapper.
- `lib/chatwoot_exception_tracker.rb` — Wrapper around Sentry + Rails.logger.
- `lib/exception_list.rb` — Whitelists of third-party exceptions (REST client, SMTP, IMAP) grouped by transport.
- `config/initializers/custom_error_codes.rb` — Registers Rack HTTP status codes `901` (Trial Expired) and `902` (Account Suspended).
- `app/mailers/application_mailer.rb` — Uses `rescue_from(*ExceptionList::SMTP_EXCEPTIONS, with: :handle_smtp_exceptions)` to swallow SMTP failures gracefully.

## Architecture and Conventions

### Sentinel exceptions

All application-domain errors inherit from `CustomExceptions::Base`. Each subclass overrides:

- `message` — usually resolved through I18n keys under `errors.*` (e.g. `errors.signup.blocked_domain`, `errors.account.email_limit_exceeded`).
- Optionally `to_hash` to shape the JSON payload returned to clients.
- Optionally `http_status` to override the default 403 (e.g. `EmailLimitExceeded` returns `:too_many_requests`).

This convention lets controllers render a uniform `{ message: ... }` or custom hash without branching on exception type.

### Controller-level handling

`ApplicationController` includes `RequestExceptionHandler`, which registers these `rescue_from` handlers:

- `ActiveRecord::RecordInvalid` → renders validation messages as `{ message, attributes }` with status `:unprocessable_entity`.
- `CustomExceptions::Inbox::LimitExceeded`, `CustomExceptions::Account::EmailLimitExceeded` → rendered via `render_error_response(exception)`, which calls `exception.to_hash` and `exception.http_status`.

The shared `handle_with_exception` wrapper catches:

- `ActiveRecord::RecordNotFound` → 404 JSON.
- `Pundit::NotAuthorizedError` → 401 JSON.
- `ActionController::ParameterMissing` → 422 JSON.
- `ActiveRecord::QueryCanceled` → 422 JSON with an i18n'd "database query canceled" message (filtered by patterns in `QUERY_CANCELED_ERROR_MESSAGE_PATTERNS`).

Every branch logs via `log_handled_error` (info-level) and ensures `Current.reset` runs in `ensure` to prevent thread-variable leaks in Puma/Thin.

Controllers can add further `rescue_from` entries locally. Examples observed:

- `app/controllers/api/v1/accounts/integrations/shopify_custom_apps_controller.rb` rescues `ActiveRecord::RecordInvalid`, `ActionController::BadRequest`.
- `app/controllers/api/v1/accounts_controller.rb` rescues `CustomExceptions::Account::InvalidEmail` and `Shopify::PendingInstallation::Error`.
- Enterprise call-related controllers rescue `CustomExceptions::CallAlreadyAccepted`, `Voice::CallErrors::*` variants.

### Exception tracking

`ChatwootExceptionTracker.new(exception, user:, account:).capture_exception` is the canonical way to report unexpected errors. It:

1. If `ENV['SENTRY_DSN']` is present, wraps the event in `Sentry.with_scope`, attaches account context/tags and user info, then calls `Sentry.capture_exception`.
2. Always falls back to `Rails.logger.error @exception`.

It is invoked throughout builders, services, jobs, listeners, and controllers where errors are considered unrecoverable at the caller level.

### Transport-layer exception whitelisting

`ExceptionList` enumerates known external-library exceptions:

- `REST_CLIENT_EXCEPTIONS` — RestClient HTTP/status/timeout/SSL variants plus `Errno::ECONNREFUSED`, `SocketError`.
- `SMTP_EXCEPTIONS` — `Net::SMTPSyntaxError`.
- `IMAP_EXCEPTIONS` — connection/reset/unreachable/bye-response/socket errors.

These lists are passed into `rescue_from` at the appropriate layer (e.g. mailers use `ExceptionList::SMTP_EXCEPTIONS`; other layers reference the REST/IMAP lists to decide retry vs. failure semantics).

### Error response format

Handled API errors consistently return JSON bodies:

- Validation: `{ message: ..., attributes: [...] }` with 422.
- Not found / unauthorized: `{ error: "..." }` with 404 / 401.
- Custom exceptions: whatever `to_hash` returns, using `http_status` (default 403).
- Database query cancellation: i18n'd message via `errors.database.query_canceled`.

Unhandled exceptions bubble to Rails' default error page (with `public/500.html`, `public/404.html`, `public/422.html` static templates present).

## Conventions and Constraints

- All domain errors subclass `CustomExceptions::Base` and accept a single `data` argument in `initialize`, stored as `@data`.
- User-facing messages in custom exceptions are resolved through I18n keys rather than hard-coded strings.
- The HTTP status for a custom exception defaults to 403; subclasses override `http_status` when a different code is needed.
- Controllers should not inline `rescue` blocks for expected business errors — they should raise a `CustomExceptions::*` so `RequestExceptionHandler.render_error_response` formats the response uniformly.
- Unexpected errors in long-running code paths (builders, jobs, services, listeners) are reported via `ChatwootExceptionTracker.new(...).capture_exception` rather than re-raising, so background workers do not crash the process.
- SMTP delivery failures are intentionally swallowed at the mailer layer (`ApplicationMailer.rescue_from *ExceptionList::SMTP_EXCEPTIONS`) and logged as warnings, allowing email sending to fail without breaking the surrounding transaction.
- Query cancellations (statement timeouts) are treated as recoverable client errors and surfaced with an i18n'd message instead of leaking PG internals.
- Custom Rack status codes `901` and `902` are registered globally in `config/initializers/custom_error_codes.rb` for trial-expired and account-suspended states.