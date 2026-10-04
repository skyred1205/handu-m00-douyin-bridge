# HANDU DTK Browser RPC for Railway

Railway-safe build of DTK browser-rpc, pinned to the exact source revision used by DTK 5.1.3.

## Pins

- DTK source: `31d56df1462e99f24621eb2c6f060af183bf24fd`
- CloakBrowser: `f04c23da285b3b3d3cf10c8f9d282e7adc1d52ce`

The pinned CloakBrowser revision launches Chromium with `--no-sandbox`. This image therefore does not request Linux `SYS_ADMIN` or privileged mode.

## Railway variables

Set:

- `PORT=9000`
- `DTK_BROWSER_BIND_PORT=9000`
- optional `DTK_BROWSER_WARM_CONTEXTS=1`
- optional `DTK_BROWSER_MAX_CONCURRENT_MINTS=1` for a small Railway instance
- optional `DTK_BROWSER_DEFAULT_COUNTRY=VN`

Do not expose a public domain. The Gateway should use Railway private networking:

`DTK_BROWSER_RPC_URL=http://<browser-service>.railway.internal:9000`

## Health

Railway health path: `/rpc/health`.

The endpoint must return JSON with `status: "ok"`; the upstream service reports backend failures in the response body.
