# HANDU DTK Railway Gateway

Single Railway service containing the components that must share local media bytes:

- DTK API on `127.0.0.1:8001`
- DTK worker
- DTK media downloader on `127.0.0.1:9100`
- HANDU M00 MCP bridge on Railway `$PORT`

This avoids Railway cross-service volume sharing entirely. The Douyin source is transient: downloader writes it, DTK API reads it, the MCP bridge copies it to its M00 cache, and ChatGPT reads it immediately.

## Pinned upstream images

Both DTK images are pinned to release 5.1.3 exact build:

`sha-31d56df1462e99f24621eb2c6f060af183bf24fd`

- `evil0ctal/douyin_tiktok_download_api`
- `evil0ctal/douyin_tiktok_download_api-downloader`

## Required Railway variables

- `DTK_SECRET_KEY` — random value, at least 32 characters.
- `DTK_DATABASE_URL` — PostgreSQL 17 + TimescaleDB URL, asyncpg form.
- `DTK_REDIS_URL` — Redis URL.
- `HANDU_DTK_ADMIN_USERNAME` — bootstrap/admin username.
- `HANDU_DTK_ADMIN_PASSWORD` — bootstrap/admin password, at least 8 characters.
- `HANDU_M00_BRIDGE_TOKEN` — bearer token ChatGPT uses for the MCP endpoint.
- `PORT` — supplied by Railway.
- `DTK_BROWSER_RPC_URL` — recommended for unattended identity minting; point at the private Railway browser-rpc service.

Optional downloader concurrency variables remain compatible with upstream DTK.

## Automatic bootstrap

On every start the gateway:

1. applies DTK migrations;
2. creates the configured admin on a fresh database, or verifies it can log in on an existing one;
3. starts the downloader and internal DTK API;
4. revokes older active API keys named `handu-m00-runtime`;
5. creates a new key scoped only to `douyin:read`, `media:read`, `media:write`;
6. starts the DTK worker;
7. starts the public HANDU MCP bridge with the new key in that child process only.

The full DTK API key is never printed.

## Browser RPC

DTK's browser-rpc remains a separate Railway service because it carries Chromium/CloakBrowser. The pinned CloakBrowser version used by DTK launches Chromium with `--no-sandbox`, so the Railway deployment does not rely on `SYS_ADMIN` even though upstream Docker Compose contains that capability for its normal host deployment.

## Public surface

Only the MCP bridge listens on Railway `$PORT`. The DTK API and downloader bind to loopback and are not public.
