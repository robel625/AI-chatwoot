---
kind: external_dependency
name: Chatwoot customer-service platform integration
slug: chatwoot
category: external_dependency
category_hints:
    - sdk_real_api
    - client_constraint
scope:
    - '**'
---

### Chatwoot
- Role: External customer-service platform that hosts the test inbox, owns the Telegram channel, and exposes the AgentBot webhook + Application API consumed by the gateway.
- SDK real API: Registration uses the Chatwoot Application API (`/api/v1/accounts/{id}/...`) with the `api_access_token` header (not the Platform App token). The CLI reads the response shape defensively because jbuilder omits `agent_bot` when no bot exists — a known Chatwoot jbuilder edge case.
- Webhook contract: Chatwoot POSTs HMAC-SHA256-signed payloads to `http://eeu-ai-gateway:4000/webhooks/chatwoot`; the gateway verifies raw bytes before admission.
- Callback contract: The gateway posts replies/handoffs back through the Chatwoot API using the bot token saved under `.local/secrets/bot_token`.