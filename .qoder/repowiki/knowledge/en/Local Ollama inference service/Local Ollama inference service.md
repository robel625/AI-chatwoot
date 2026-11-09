---
kind: external_dependency
name: Local Ollama inference service
slug: ollama
category: external_dependency
category_hints:
    - client_constraint
    - auth_protocol
scope:
    - '**'
---

### Ollama
- Role: Local LLM provider used by the worker for intent classification and (when enabled) grounded answer generation. No cloud fallback or automatic model pull occurs.
- Auth protocol: No auth header is required in this pilot — authentication is expected to come from host firewall / local-only access.
- Operational note: Shared host Ollama version/model artifacts are an operator-managed dependency; offline deployment requires pre-installing approved models rather than downloading them at runtime.