# HANDU M00 Douyin Bridge

Dedicated repository for the Railway-backed HANDU M00 Douyin intake bridge.

## Live status

Railway acceptance test passed on 2026-10-05 using:

`https://v.douyin.com/-MQ7nbsrNjs`

Verified:

- public MCP authentication and initialization;
- `download_douyin_video`;
- binary `source.mp4` resource retrieval;
- exact byte-count and SHA-256 match;
- valid MP4 container;
- both video and audio tracks.

Deployment details: `docs/HANDU_M00_RAILWAY_DEPLOY.md`

Acceptance evidence: `docs/ACCEPTANCE_2026-10-05.md`
