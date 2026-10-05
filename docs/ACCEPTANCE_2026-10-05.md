# HANDU M00 Railway Acceptance — 2026-10-05

Test source:

`https://v.douyin.com/-MQ7nbsrNjs`

## Result

**PASS**

- Railway gateway: healthy
- MCP public endpoint: authenticated and initialized successfully
- MCP protocol version: `2025-06-18`
- MCP tools exposed: 2
- platform: `douyin`
- content ID: `7690599494710880613`
- M00 job ID: `handu-m00-ed6c5bfe15e3af20e5b3`
- DTK download ID: `1e358583-d209-4a8c-a9c2-ac211866e351`
- source bytes: `6126687`
- SHA-256: `062692010cfa8816bafacfc8170d0b37c38b02a4fe818f2ce830ed5d17a799fe`
- manifest byte count match: yes
- manifest SHA-256 match: yes
- MP4 `ftyp` present: yes
- media handlers: `soun`, `vide`
- audio track present: yes
- video track present: yes
- resource URI: `handu-m00://handu-m00-ed6c5bfe15e3af20e5b3/source.mp4`

## Railway fixes discovered during acceptance

1. `timescale/timescaledb-ha:pg17` hit Railway volume initialization/permission problems.
2. Railway test database was switched to `timescale/timescaledb:latest-pg17`, volume mounted at `/var/lib/postgresql`, with `PGDATA=/var/lib/postgresql/data`.
3. Redis RDB persistence hit volume write errors; the disposable acceptance environment was switched to `redis-server --save "" --appendonly no`.
4. Browser RPC and Gateway both deployed successfully from this dedicated repository.
5. Gateway completed DTK migration, admin bootstrap/login, scoped runtime-key rotation, worker startup, and MCP healthcheck.

No Facebook publishing was performed.
