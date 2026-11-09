---
kind: external_dependency
name: FastAPI ASGI web framework for EEU AI gateway
slug: fastapi
category: external_dependency
category_hints:
    - framework_behavior
scope:
    - '**'
---

### FastAPI
- Role: The EEU AI gateway is a FastAPI application (`>=0.115,<1`) with two separate ASGI apps on one image — the customer webhook app (`eeu_ai.api:create_app`, loopback `:4000`) and the operator console (`eeu_ai.admin.app:create_admin_app`, loopback `:4001`). They never import each other.
- Integration point: `pyproject.toml` declares it as the runtime dependency; `compose.yaml` runs both via `python -m eeu_ai.api` and `python -m eeu_ai.admin`.
- Verify exact endpoint signatures against the current `eeu_ai/admin/routes/*` files.