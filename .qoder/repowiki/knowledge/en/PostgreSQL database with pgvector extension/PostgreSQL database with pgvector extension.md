---
kind: external_dependency
name: PostgreSQL database with pgvector extension
slug: postgresql-pgvector
category: external_dependency
category_hints:
    - migration_status
scope:
    - '**'
---

### PostgreSQL (pgvector)
- Role: Persistent store for the gateway's isolated jobs/outbox/audit tables and the knowledge corpus. The compose file pins the `pgvector/pgvector` image; `psycopg[binary]` and `pgvector` are declared dependencies.
- Migration status: Migrations are managed by Alembic (`alembic.ini` + `migrations/versions/`); the knowledge ingestion path also has its own migration chain. Tests run against a separate tmpfs-backed container (`eeu_ai_test`), never the Chatwoot database.
- Constraint: The vector extension is available locally but the pilot creates no vector extension usage itself — only plain text/vector-ready columns exist until RAG phases land.