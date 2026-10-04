# HANDU M00 Douyin Bridge

MCP service for replacing the HANDU V1.5 Cloudflare M00 intake with a self-hosted Douyin backend.

## Flow

```text
ChatGPT
  -> MCP download_douyin_video
  -> Douyin_TikTok_Download_API /api/v1/parse
  -> DTK media downloader
  -> source.mp4
  -> MCP ResourceLink handu-m00://<job>/source.mp4
```

Backend: `Evil0ctal/Douyin_TikTok_Download_API` v5.

## Required environment

- `DTK_BASE_URL` — reachable DTK API base URL.
- `DTK_API_KEY` — DTK API key with `douyin:read`, `media:read`, `media:write`.
- `HANDU_M00_BRIDGE_TOKEN` — random bearer token for the public MCP endpoint.
- `PORT` — supplied by Railway.
- optional `HANDU_M00_CACHE_DIR` — defaults to `/tmp/handu-m00-cache`; use a mounted Railway volume such as `/data/m00` for persistence.

The DTK deployment must run its downloader sidecar and set `DTK_DOWNLOADER_URL`.

## MCP tools

### `download_douyin_video(url)`

1. Resolves `v.douyin.com` through DTK.
2. Verifies the result is a Douyin video.
3. Starts or reuses a DTK media download.
4. Waits for the video file to settle.
5. Stores it as `source.mp4`.
6. Returns a JSON manifest plus a `ResourceLink`.

The manifest contains the source URL, Douyin content id, DTK download id, byte size and SHA-256.

### `get_m00_manifest(job_id)`

Returns the cached manifest for a completed intake.

## MCP resource

`handu-m00://{job_id}/source.mp4` returns the cached MP4 bytes as a binary MCP resource.

## Health

`GET /health` is intentionally unauthenticated for Railway health checks. It returns 200 only when all required environment variables are present.

## Security

Every route except `/health` requires:

```http
Authorization: Bearer <HANDU_M00_BRIDGE_TOKEN>
```

Railway terminates TLS and controls the external Host header, so the service disables the MCP SDK's local-host DNS-rebinding allowlist and relies on the Railway proxy plus mandatory bearer authentication.

## Local run

```bash
export DTK_BASE_URL=http://127.0.0.1:8000
export DTK_API_KEY=dtk_xxx
export HANDU_M00_BRIDGE_TOKEN='generate-a-long-random-value'
uvicorn handu_m00_bridge.server:app --host 0.0.0.0 --port 8000
```

MCP endpoint: `/mcp`.

## Validation performed before commit

The DTK client flow was exercised with a mocked HTTP backend:

`parse -> start download -> poll -> read video.mp4`

Result: PASS.
