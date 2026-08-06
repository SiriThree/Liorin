# Liorin production stack

```bash
cd deploy
cp .env.example .env
docker compose up --build
```

Endpoints:

- Agent API: `http://localhost:2024`
- Health: `http://localhost:2024/healthz`
- Metrics snapshot: `http://localhost:2024/metrics`
- Prometheus: `http://localhost:9090`

PostgreSQL is the source of truth. Redis is only a TTL cache and can be flushed without data loss.

`POST /invoke` must be placed behind an authenticated gateway. The gateway must
strip client-supplied identity headers and inject:

```text
X-Liorin-Tenant-Id
X-Liorin-User-Id
X-Liorin-Conversation-Id
X-Liorin-Thread-Id
X-Liorin-Session-Id
```

The API rejects request-body identity or LangGraph `thread_id` values that
conflict with these trusted headers.
