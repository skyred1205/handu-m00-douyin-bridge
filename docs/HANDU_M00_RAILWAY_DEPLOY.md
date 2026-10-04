# HANDU M00 Railway deployment

Target: replace HANDU V1.5 Cloudflare M00 with a direct Railway-hosted Douyin intake while keeping M01-M12 production rules unchanged.

## Services

### 1. handu-dtk-postgres

Source: this repository.

- Dockerfile: `services/handu-dtk-postgres/Dockerfile`
- no public domain
- private port 5432
- persistent Railway volume mounted at `/home/postgres/pgdata/data`
- `POSTGRES_DB=dtk`
- `POSTGRES_USER=dtk`
- `POSTGRES_PASSWORD=<secret>`

### 2. Redis

Use a Railway Redis database/service.

The Gateway receives its private Redis URL as `DTK_REDIS_URL`.

### 3. handu-dtk-browser

Source: this repository.

- Dockerfile: `services/handu-dtk-browser/Dockerfile`
- no public domain
- `PORT=9000`
- `DTK_BROWSER_BIND_PORT=9000`
- recommended small-instance settings:
  - `DTK_BROWSER_WARM_CONTEXTS=1`
  - `DTK_BROWSER_MAX_CONCURRENT_MINTS=1`

Private address used by Gateway:

`http://<browser-service>.railway.internal:9000`

### 4. handu-dtk-gateway

Source: this repository.

- Dockerfile: `services/handu-dtk-gateway/Dockerfile`
- public domain enabled
- Railway supplies `PORT`
- required:
  - `DTK_SECRET_KEY=<random 32+ char secret>`
  - `DTK_DATABASE_URL=postgresql+asyncpg://dtk:<password>@<postgres-private-host>:5432/dtk`
  - `DTK_REDIS_URL=<redis-private-url>`
  - `DTK_BROWSER_RPC_URL=http://<browser-private-host>:9000`
  - `HANDU_DTK_ADMIN_USERNAME=<bootstrap username>`
  - `HANDU_DTK_ADMIN_PASSWORD=<bootstrap password>`
  - `HANDU_M00_BRIDGE_TOKEN=<random bearer token>`

Only this service gets a public domain. The DTK API and downloader remain loopback-only inside the container.

## Startup contract

The Gateway performs:

1. DTK migrations.
2. Admin creation on a fresh database; login verification on an existing database.
3. Downloader start.
4. Internal DTK API start.
5. Runtime API-key rotation.
6. DTK worker start.
7. MCP bridge start on Railway `PORT`.
8. `/health` must return HTTP 200.

The runtime API key is scoped only to:

- `douyin:read`
- `media:read`
- `media:write`

The plaintext key is never logged.

## ChatGPT MCP connection

Connect the Gateway public endpoint:

`https://<gateway-domain>/mcp`

Authentication header:

`Authorization: Bearer <HANDU_M00_BRIDGE_TOKEN>`

Expected tools:

- `download_douyin_video(url)`
- `get_m00_manifest(job_id)`

Expected binary resource:

- `handu-m00://<job_id>/source.mp4`

## Acceptance test

Use the current production test link:

`https://v.douyin.com/-MQ7nbsrNjs`

PASS requires:

1. `download_douyin_video` returns a manifest and `source.mp4` resource.
2. MP4 bytes are non-empty.
3. SHA-256 in the manifest matches the received source.
4. DTK reports a Douyin video content id.
5. Source opens and contains video + audio streams.
6. Then HANDU continues M01-M12; M12 must PASS before delivery.

No Facebook publishing is part of this test.
