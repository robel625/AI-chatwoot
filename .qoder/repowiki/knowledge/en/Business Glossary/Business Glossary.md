---
kind: business_term
name: Business Glossary
category: business_term
scope:
    - '**'
---

### EEU AI gateway
- Definition：The EEU local pilot's FastAPI service that sits between Chatwoot and local Ollama, classifying inbound customer messages, routing them to specialist agents, generating grounded answers, and delivering replies or human handoffs back to Chatwoot.
- Aliases：eeu-ai-gateway、gateway

### AgentBot
- Definition：The Chatwoot concept representing the EEU AI system as a bot identity attached to a designated test inbox; registration creates an AgentBot row and assigns it to the inbox via the Chatwoot Application API.
- Aliases：bot identity

### handoff
- Definition：The outcome where the AI cannot produce a verified answer and the conversation is opened for a human agent instead of being answered by the bot. Distinct from a failed delivery; it is a deliberate policy decision recorded in the audit trace.
- Aliases：human handoff、escalation

### grounded answer
- Definition：A customer-facing reply composed by Ollama from verified tool results or retrieved knowledge, then validated to ensure no number, payment status, outage ETA, or success claim appears unless present in the grounded fact set. If validation fails, the system falls back to an approved template or a handoff.
- Aliases：grounded generation、dynamic generation

### development mode
- Definition：An opt-in environment posture (`EEU_DEVELOPMENT_MODE`) that suppresses ordinary handoffs and instead asks the AI to explain limitations honestly, ask clarifying questions, and continue multi-turn context — while protected escalations (identity verification, ethics reporting) remain enforced.
- Aliases：AI-only responses、dev mode

### strict safety
- Definition：The default safety posture (`EEU_STRICT_SAFETY=true`) that forbids free-form model prose in customer replies and forces fixed-copy/template answers; the pilot's local setup may opt out, but this must never face real EEU customers without the safety layer.
- Aliases：strict_safety

### knowledge base
- Definition：The independent RAG corpus ingested into the gateway's PostgreSQL (with pgvector) containing EEU tariff, procedure, and FAQ documents. It is separate from Chatwoot's data and from live account records; retrieval returns confidence tiers (HIGH/LOW/NO_EVIDENCE) used by the supervisor.
- Aliases：RAG knowledge base、corpus

### synthetic adapters
- Definition：In-memory mock implementations of the billing/meter/outage/upstream account-data adapters used during development and testing to exercise the full dynamic-generation pipeline without connecting to real EEU services.
- Aliases：mock adapters、fake adapters

### execution trace
- Definition：Append-only metadata about a single job's processing stages (webhook_admission → job_creation → pii_protection → intent_routing → agent_execution → knowledge_retrieval → response_delivery → job_completion), including agent, intent, model, confidence tier, duration, and derived outcome.
- Aliases：Layer A trace、trace row

### business audit event
- Definition：Append-only business-layer events (customer message received, intent classified, identity verification requested/succeeded, billing lookup requested/succeeded/failed, response delivery confirmed, knowledge response provided, human handoff requested) tied to the same correlation id as the execution trace.
- Aliases：Layer B event、audit event

### correlation id
- Definition：A UUID minted at job admission that ties together Layer A execution stages and Layer B business audit events for a single customer turn, enabling correlated review across both traces.
- Aliases：correlation_key

### protected escalation
- Definition：A security-sensitive workflow branch (identity verification, corruption/ethics reporting) that cannot be bypassed by development mode or loose generation; these paths always follow their approved workflow regardless of `EEU_DEVELOPMENT_MODE`.
- Aliases：protected workflow、protected escalation

### safe fetch override
- Definition：The Chatwoot Compose override (`chatwoot.local-override.yaml`) setting `SAFE_FETCH_ALLOW_PRIVATE_NETWORK=true` so Rails/Sidekiq can POST to the private gateway URL. Approved only for the local synthetic pilot; it broadens all private-network outbound requests from Chatwoot.
- Aliases：private-network override、SafeFetch override
